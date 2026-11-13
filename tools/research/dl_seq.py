#!/usr/bin/env python3
"""深層学習（1次元 CNN / LSTM）で、6銘柄の直近の値動きの並びから、次の数時間の値動きの向きを当てられるかを調べる。

- 入力：直近 48 本（1時間足、確定足だけ）の6銘柄の値動き（ATR で割った値）＋ 時刻の情報。
- 出力：対象の銘柄の、次の HOLD 時間の値動き（ATR で割った値）。6銘柄まとめて1つのモデルで学習する。
- 取引：予測の上位 q を買い、下位 q を売る（q は学習データの予測の分布から決める）。
- 評価は他の研究と同じ：設計期間の中のウォークフォワード（2019/2020/2021）で q を決め、検証期間は1回だけ見る。
- 損益はコスト込み（銘柄ごとの pips のコスト）。最終確認期間は使わない。

使い方: python3 tools/research/dl_seq.py [保有時間] [cnn|lstm]
"""
import os
import sys

import numpy as np
import pandas as pd
import torch
from torch import nn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import ml_train as M  # noqa: E402
import seasonality as S  # noqa: E402

LOOK = 48
torch.set_num_threads(4)


def panel():
    """6銘柄の1時間足を共通の時刻にそろえ、各銘柄の「1本の値動き ÷ ATR」を並べる。"""
    idx = None
    for p in M.CROSS:
        b = D.bars(p, "1h")
        idx = b.index if idx is None else idx.intersection(b.index)
    cols, info = [], {}
    for p in M.CROSS:
        b = D.bars(p, "1h").reindex(idx)
        a = M.atr(b).shift(1)
        cols.append(((b["c"] - b["c"].shift(1)) / a).clip(-6, 6).rename(p))
        ret, atrp = M.target(p, 1)
        info[p] = b
    pn = pd.concat(cols, axis=1)
    return idx, pn, info


def build(hold):
    idx, pn, info = panel()
    base0 = info[M.CROSS[0]]
    tfe = pd.DataFrame(index=idx)
    for clk in ("tky", "ldn", "ny"):
        h = base0[f"{clk}_h"].values
        tfe[f"{clk}_s"] = np.sin(2 * np.pi * h / 24)
        tfe[f"{clk}_c"] = np.cos(2 * np.pi * h / 24)
    dow = base0["tky_dow"].values
    for k in range(5):
        tfe[f"dow{k}"] = (dow == k).astype(float)
    tfe["gotobi"] = S.gotobi_mask(pd.DatetimeIndex(base0["tky_date"])).astype(float)
    X = np.nan_to_num(pn.values.astype(np.float32))
    TF = tfe.values.astype(np.float32)
    samples = []
    for i, p in enumerate(M.CROSS):
        b = D.bars(p, "1h").reindex(idx)
        pip = D.pip_size(p)
        r = S.window_returns(b, hold, pip)
        a = (M.atr(b).shift(1) / pip).values
        excl = S.rollover_mask(b.ffill(), hold)
        pos = np.arange(len(idx))
        ok = (pos >= LOOK + 100) & ~np.isnan(r) & (a > 0) & ~excl
        for t in pos[ok]:
            samples.append((t, i, r[t], a[t], S.COST[p]))
    s = pd.DataFrame(samples, columns=["t", "pair", "ret", "atr", "cost"])
    s["time"] = idx[s["t"].values]
    return X, TF, s


class Net(nn.Module):
    def __init__(self, nch, nstat, kind):
        super().__init__()
        self.kind = kind
        if kind == "lstm":
            self.rnn = nn.LSTM(nch, 32, batch_first=True)
            h = 32
        else:
            self.conv = nn.Sequential(nn.Conv1d(nch, 32, 5, padding=2), nn.ReLU(),
                                      nn.Conv1d(32, 32, 5, padding=2), nn.ReLU())
            h = 64
        self.head = nn.Sequential(nn.Linear(h + nstat, 64), nn.ReLU(), nn.Dropout(0.2), nn.Linear(64, 1))

    def forward(self, seq, stat):
        if self.kind == "lstm":
            out, _ = self.rnn(seq)
            z = out[:, -1]
        else:
            c = self.conv(seq.transpose(1, 2))
            z = torch.cat([c.mean(dim=2), c[:, :, -1]], dim=1)
        return self.head(torch.cat([z, stat], dim=1)).squeeze(1)


def batch(X, TF, s, rows):
    t = s["t"].values[rows]
    seq = np.stack([X[k - LOOK:k] for k in t])                    # k 本目の始値の時点：k-1 本目までの確定足
    pair = np.eye(len(M.CROSS), dtype=np.float32)[s["pair"].values[rows]]
    stat = np.concatenate([TF[t], pair], axis=1)
    return torch.from_numpy(seq), torch.from_numpy(stat)


def fit_predict(X, TF, s, tr, te, kind, seed=0, epochs=3):
    torch.manual_seed(seed)
    np.random.seed(seed)
    net = Net(X.shape[1], TF.shape[1] + len(M.CROSS), kind)
    opt = torch.optim.Adam(net.parameters(), lr=1e-3, weight_decay=1e-4)
    y = torch.from_numpy(np.clip(s["ret"].values / s["atr"].values, -5, 5).astype(np.float32))
    tr_rows = np.where(tr)[0]
    for _ in range(epochs):
        net.train()
        np.random.shuffle(tr_rows)
        for j in range(0, len(tr_rows), 512):
            rows = tr_rows[j:j + 512]
            seq, st = batch(X, TF, s, rows)
            loss = nn.functional.huber_loss(net(seq, st), y[rows])
            opt.zero_grad()
            loss.backward()
            opt.step()
    net.eval()

    def pred(mask):
        rows = np.where(mask)[0]
        out = []
        with torch.no_grad():
            for j in range(0, len(rows), 4096):
                seq, st = batch(X, TF, s, rows[j:j + 4096])
                out.append(net(seq, st).numpy())
        return np.concatenate(out) if out else np.array([])
    return pred(tr), pred(te)


def stat(p):
    if len(p) < 20:
        return {"n": len(p), "mean": 0.0, "pf": 0.0, "t": 0.0}
    gp, gl = p[p > 0].sum(), -p[p < 0].sum()
    return {"n": len(p), "mean": p.mean(), "pf": gp / gl if gl > 0 else 9.99, "t": p.mean() / p.std(ddof=1) * np.sqrt(len(p))}


def fmt(x):
    return f"{x['n']}回 1取引 {x['mean']:+.2f}pips PF {x['pf']:.2f} t {x['t']:.2f}"


def trades(pred, ptr, d, q, hold):
    hi, lo = np.quantile(ptr, 1 - q), np.quantile(ptr, q)
    side = np.where(pred >= hi, 1.0, np.where(pred <= lo, -1.0, 0.0))
    step = (pd.DatetimeIndex(d["time"]).hour % hold) == 0
    m = (side != 0) & step
    return side[m] * d["ret"].values[m] - d["cost"].values[m]


def run(hold=2, kind="cnn"):
    X, TF, s = build(hold)
    qs = [0.05, 0.10, 0.20]
    out = [f"## 深層学習（{kind}）・6銘柄まとめ・保有 {hold} 時間", "",
           f"- 学習データ {len(s):,} 本、入力：直近 {LOOK} 本 × 6銘柄の値動き ＋ 時刻", ""]
    wf = {q: [] for q in qs}
    for yr in (2019, 2020, 2021):
        tr = (s["time"] < pd.Timestamp(f"{yr}-01-01")).values
        te = ((s["time"] >= pd.Timestamp(f"{yr}-01-01")) & (s["time"] < pd.Timestamp(f"{yr + 1}-01-01"))).values
        ptr, pte = fit_predict(X, TF, s, tr, te, kind)
        for q in qs:
            x = stat(trades(pte, ptr, s[te], q, hold))
            wf[q].append(x)
            out.append(f"- {yr} 上位・下位 {int(q * 100)}%: {fmt(x)}")
        print(yr, "done", file=sys.stderr, flush=True)
    best = None
    for q in qs:
        if all(x["mean"] > 0 and x["n"] >= 30 for x in wf[q]):
            sc = sum(x["t"] for x in wf[q])
            if best is None or sc > best[1]:
                best = (q, sc)
    out.append("")
    if best is None:
        out.append("**ウォークフォワードの3年すべてでコスト込みプラスになる設定はありませんでした（不合格）。**")
        return "\n".join(out) + "\n"
    q = best[0]
    des = D.period_mask(pd.DatetimeIndex(s["time"]), D.DESIGN)
    val = D.period_mask(pd.DatetimeIndex(s["time"]), D.VALID)
    ptr, pv = fit_predict(X, TF, s, des, val, kind)
    x = stat(trades(pv, ptr, s[val], q, hold))
    ok = x["mean"] > 0 and x["pf"] >= 1.10 and x["n"] >= 100
    out += [f"→ 上位・下位 {int(q * 100)}% を採用", "", f"### 検証期間：{fmt(x)} → **{'合格' if ok else '不合格'}**", ""]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    hold = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    kind = sys.argv[2] if len(sys.argv) > 2 else "cnn"
    text = run(hold, kind)
    print(text)
    open(os.path.join(D.ROOT, "reports", "research", f"dl_{kind}_h{hold}.md"), "w", encoding="utf-8").write(text)

#!/usr/bin/env python3
"""汎用的なロジック（トレンドフォロー・逆張り・ブレイクアウト・RSI・ボリンジャーバンドなど）が、
今の時刻ルールの組み合わせが負けた月の支えになるかを調べる（1時間足、17ペア、コスト後）。

見ること
1. コスト後の1回あたりの損益（pips）が、3期間（2015〜21年・5年の前半・後半）でプラスか
2. 今のシステム（MT5 実行413＋412 の月ごとの損益率）が負けた月に、代わりに勝っていたか
3. 今のシステムとの月ごとの相関

- シグナルは、足が確定した時点の値だけで決める（未来の情報は使わない）。次の足の始値で入り、H 本後の足の始値で出る。
- 日付の変わり目（NY 16〜18時）にかかる取引と、週末をまたぐ取引は除く（スプレッドの見かけの値動きを避けるため）。
- 月ごとの損益は、各取引を「その戦略の1取引のばらつき」で割ってリスクをそろえ、全ペアで平均した値。

使い方: python3 tools/research/generic_panel.py → reports/research/generic_panel.md
"""
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

PAIRS = ["USDJPY", "EURJPY", "GBPJPY", "EURUSD", "AUDJPY", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP",
         "NZDJPY", "CADJPY", "CHFJPY", "AUDCAD", "AUDNZD", "NZDCAD"]
PER = (("15-21", "2015-01-01", "2021-11-01"), ("前半", "2021-11-01", "2024-11-01"), ("後半", "2024-11-01", "2027-01-01"))


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean().values
    dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean().values
    return 100 - 100 / (1 + up / np.maximum(dn, 1e-12))


def signals(df):
    """{名前: (向きの配列（+1/-1/0）, 保有本数)}。足 i の終値までの情報で決め、i+1 の始値で入る。"""
    c = df["c"].values
    h = df["h"].values
    lo = df["l"].values
    out = {}
    for L in (6, 24, 120):
        past = c - np.r_[np.full(L, np.nan), c[:-L]]
        out[f"モメンタム {L}h→24h"] = (np.sign(np.nan_to_num(past)), 24)
    for L, H in ((6, 6), (24, 24)):
        past = c - np.r_[np.full(L, np.nan), c[:-L]]
        sd = pd.Series(past).rolling(500, min_periods=200).std().values
        z = past / sd
        out[f"逆張り {L}h（|z|>1.5）→{H}h"] = (np.where(np.abs(z) > 1.5, -np.sign(z), 0.0), H)
    for N in (24, 72):
        hi = pd.Series(h).rolling(N).max().shift(1).values
        lw = pd.Series(lo).rolling(N).min().shift(1).values
        out[f"ブレイクアウト {N}h→24h"] = (np.where(c > hi, 1.0, np.where(c < lw, -1.0, 0.0)), 24)
    r = rsi(c)
    out["RSI 30/70 逆張り→6h"] = (np.where(r < 30, 1.0, np.where(r > 70, -1.0, 0.0)), 6)
    ma = pd.Series(c).rolling(20).mean().values
    sd = pd.Series(c).rolling(20).std().values
    out["ボリンジャー 2σ 逆張り→6h"] = (np.where(c < ma - 2 * sd, 1.0, np.where(c > ma + 2 * sd, -1.0, 0.0)), 6)
    e50 = pd.Series(c).ewm(span=50).mean().values
    e200 = pd.Series(c).ewm(span=200).mean().values
    cross = np.sign(e50 - e200)
    chg = np.r_[0, np.diff(cross)] != 0
    out["移動平均 50/200 の交差→48h"] = (np.where(chg, cross, 0.0), 48)
    return out


def trades(pair):
    df = D.bars(pair, "1h")
    pip = D.pip_size(pair)
    cost = S.COST[pair]
    o = df["o"].values
    idx = df.index
    ny_h = df["ny_h"].values
    res = {}
    for name, (sig, H) in signals(df).items():
        i = np.where((sig != 0) & ~np.isnan(sig))[0]
        i = i[i + 1 + H < len(df)]
        # 同じ戦略の取引は重ならないように間引く（保有中の新しいシグナルは無視）
        keep, last = [], -10 ** 9
        for k in i:
            if k > last + H:
                keep.append(k)
                last = k
        i = np.array(keep, dtype=int)
        if len(i) == 0:
            continue
        a, b = i + 1, i + 1 + H
        ok = (idx.values[b] - idx.values[a]) == np.timedelta64(H, "h")  # 週末・欠けをまたがない
        bad = np.zeros(len(i), bool)
        for s_ in range(H + 1):
            hh = ny_h[np.minimum(a + s_, len(df) - 1)]
            bad |= (hh >= 16) & (hh <= 18)
        ok &= ~bad
        r = sig[i[ok]] * (o[b[ok]] - o[a[ok]]) / pip - cost
        res[name] = pd.Series(r, index=idx[a[ok]])
    return res


def system_monthly():
    out = []
    for run in ("0413", "0412"):
        t = open(os.path.join(D.ROOT, "reports", "runs", f"{run}.txt"), encoding="utf-8").read()
        out.append(pd.Series({k: float(v) for k, v in (x.split(":") for x in re.search(r"^MONTHLY (.*)$", t, re.M).group(1).split(",") if ":" in x)}))
    s = pd.concat(out)
    return s[~s.index.duplicated(keep="last")].sort_index()


def main():
    from multiprocessing import Pool
    with Pool(3) as pool:
        parts = pool.map(trades, PAIRS)
    sysm = system_monthly()
    weak = sysm[sysm < 0].index
    lines = ["# 汎用的なロジックの試算（1時間足、17ペア、コスト後）", "",
             "- 1回あたりの損益は、全ペアの取引をまとめた平均（pips、コスト後）。",
             "- 「システムが負けた月」は、今の設定（MT5 実行413＋412）の月ごとの損益率がマイナスだった月（" + str(len(weak)) + " か月）。",
             "- 月ごとの値は、1取引のばらつきでリスクをそろえ、全ペアで平均した値（単位）。", "",
             "| ロジック | 回数 | 15-21 pips | 前半 pips | 後半 pips | システムが負けた月の平均 | ほかの月の平均 | システムとの相関 |",
             "|---|---|---|---|---|---|---|---|"]
    names = list(parts[0].keys())
    for name in names:
        allr = pd.concat([p[name] for p in parts if name in p])
        per = []
        for _, a, b in PER:
            x = allr[(allr.index >= a) & (allr.index < b)]
            per.append(f"{x.mean():+.2f}")
        # 月ごと：ペアごとにばらつきでそろえて平均
        mons = []
        for p in parts:
            if name not in p:
                continue
            x = p[name]
            mons.append((x / x.std()).groupby(x.index.strftime("%Y-%m")).sum())
        m = pd.concat(mons, axis=1).fillna(0).mean(axis=1)
        m = m.reindex(sysm.index).fillna(0)
        lines.append(f"| {name} | {len(allr):,} | {per[0]} | {per[1]} | {per[2]} | {m[weak].mean():+.2f} | {m[~m.index.isin(weak)].mean():+.2f} | {np.corrcoef(m, sysm)[0, 1]:+.2f} |")
    text = "\n".join(lines) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "generic_panel.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

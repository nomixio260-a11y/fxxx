#!/usr/bin/env python3
"""ローソク足・チャートのパターンを、利確・損切りつきの取引としてまとめて調べる（「小さく多く勝つ」形も含む）。

パターン（確定した足で判定し、次の足の始値で入る）：
- 包み足（陽の包み足→買い／陰の包み足→売り）
- ピンバー（長い下ヒゲ→買い／長い上ヒゲ→売り。直前に下げ／上げがあるとき）
- はらみ足（インサイドバー）の後、親の足と同じ向きに入る
- 3本連続の陰線→買い（戻り）／3本連続の陽線→売り
- 二番底・二番天井（直近50本の安値・高値を試して反発した足）
- RSI(14) の行き過ぎからの戻り（30を下から上へ→買い、70を上から下へ→売り）
利確・損切り（1時間足の平均値幅 ATR の倍数）：
- 小さく多く勝つ形：利確 0.5 ATR／損切り 1.5 ATR
- 同じ幅：利確 1.0／損切り 1.0
- 大きく勝つ形：利確 2.0／損切り 1.0
保有は最大 24 本。同じ足の中で利確と損切りの両方に届いたら、損切りとみなす（控えめに見積もる）。
評価：コスト後の pips。設計・検証・2024年11月〜の3期間すべてでプラス（PF ≥ 1.1）のものを候補とする。

使い方: python3 tools/research/patterns.py [1h|5min]  → reports/research/patterns_<足>.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

TPSL = [(0.5, 1.5), (1.0, 1.0), (2.0, 1.0)]
MAXBARS = 24


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def signals(df):
    o, h, l, c = df["o"], df["h"], df["l"], df["c"]
    body = (c - o)
    rng = (h - l).replace(0, np.nan)
    up_w = h - np.maximum(o, c)
    lo_w = np.minimum(o, c) - l
    prev_body = body.shift(1)
    trend = c - c.shift(5)
    s = {}
    s["包み足"] = np.where((prev_body < 0) & (body > 0) & (c > o.shift(1)) & (o < c.shift(1)), 1,
                         np.where((prev_body > 0) & (body < 0) & (c < o.shift(1)) & (o > c.shift(1)), -1, 0))
    s["ピンバー"] = np.where((lo_w >= 2 * body.abs()) & (lo_w >= 0.6 * rng) & (trend < 0), 1,
                         np.where((up_w >= 2 * body.abs()) & (up_w >= 0.6 * rng) & (trend > 0), -1, 0))
    inside = (h < h.shift(1)) & (l > l.shift(1))
    s["はらみ足"] = np.where(inside & (prev_body > 0), 1, np.where(inside & (prev_body < 0), -1, 0))
    s["3本連続の逆張り"] = np.where((body < 0) & (body.shift(1) < 0) & (body.shift(2) < 0), 1,
                              np.where((body > 0) & (body.shift(1) > 0) & (body.shift(2) > 0), -1, 0))
    lo50 = l.shift(1).rolling(50).min()
    hi50 = h.shift(1).rolling(50).max()
    a = (h - l).rolling(24).mean()
    s["二番底・二番天井"] = np.where((l <= lo50 + 0.2 * a) & (l >= lo50 - 0.2 * a) & (body > 0), 1,
                              np.where((h >= hi50 - 0.2 * a) & (h <= hi50 + 0.2 * a) & (body < 0), -1, 0))
    r = rsi(c)
    s["RSIの戻り"] = np.where((r.shift(1) < 30) & (r >= 30), 1, np.where((r.shift(1) > 70) & (r <= 70), -1, 0))
    return {k: np.nan_to_num(np.asarray(v, float)) for k, v in s.items()}


def simulate(df, sig, atr_pips, tp_k, sl_k, pip, cost):
    """sig[i] != 0 の足 i（確定）の次の足の始値で入る。重ならないように、決済までは次を取らない。"""
    o, h, l, c = df["o"].values, df["h"].values, df["l"].values, df["c"].values
    n = len(df)
    res = np.full(n, np.nan)
    i = 0
    idx = np.nonzero(sig)[0]
    busy_until = -1
    for i in idx:
        e = i + 1
        if e <= busy_until or e >= n - 1 or np.isnan(atr_pips[i]) or atr_pips[i] <= 0:
            continue
        d = sig[i]
        tp = tp_k * atr_pips[i] * pip
        sl = sl_k * atr_pips[i] * pip
        entry = o[e]
        out = None
        last = min(n - 1, e + MAXBARS - 1)
        for k in range(e, last + 1):
            if d > 0:
                if l[k] <= entry - sl:
                    out = -sl
                    break
                if h[k] >= entry + tp:
                    out = tp
                    break
            else:
                if h[k] >= entry + sl:
                    out = -sl
                    break
                if l[k] <= entry - tp:
                    out = tp
                    break
        if out is None:
            out = d * (c[last] - entry)
            k = last
        res[i] = out / pip - cost
        busy_until = k
    return res


def st(x):
    x = x[~np.isnan(x)]
    if len(x) < 30:
        return None
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return {"n": len(x), "mean": x.mean(), "pf": gp / gl if gl > 0 else 9.99, "win": (x > 0).mean(),
            "t": x.mean() / x.std(ddof=1) * np.sqrt(len(x))}


def f(s):
    return "-" if s is None else f"{s['n']}回 勝率{s['win'] * 100:.0f}% {s['mean']:+.2f}pips PF {s['pf']:.2f} t {s['t']:.1f}"


def main(tf="1h"):
    rows = []
    for pair in D.PAIRS:
        df = D.bars(pair, tf)
        if tf != "1h":
            df = df[df.index >= "2015-01-01"]
        pip, cost = D.pip_size(pair), S.COST[pair]
        h1 = D.bars(pair, "1h")
        a = ((h1["h"] - h1["l"]).rolling(24).mean().shift(1) / pip).reindex(df.index.floor("1h")).values
        # 日付の変わり目（NY 16:00〜18:59）には入らない（スプレッドが広いため）
        ny = df["ny_h"].values
        ok_time = ~((ny >= 16) & (ny <= 18))
        sigs = signals(df)
        P = {k: D.period_mask(df.index, v) for k, v in (("設計", D.DESIGN), ("検証", D.VALID), ("2024/11〜", D.FINAL))}
        for name, s in sigs.items():
            s = np.where(ok_time, s, 0)
            for tp_k, sl_k in TPSL:
                r = simulate(df, s, a, tp_k, sl_k, pip, cost)
                rows.append((pair, name, tp_k, sl_k, {k: st(r[m]) for k, m in P.items()}))
        print(pair, "done", file=sys.stderr, flush=True)
    def good(x):
        return x is not None and x["mean"] > 0 and x["pf"] >= 1.1
    hits = [r for r in rows if all(good(r[4][k]) for k in ("設計", "検証", "2024/11〜")) and r[4]["設計"]["t"] >= 2]
    out = [f"# パターン分析（{tf}、コスト後、利確・損切りつき）", "", f"- 調べた組み合わせ：{len(rows)} 通り",
           f"- 3期間すべてでプラス（PF ≥ 1.1）かつ設計 t ≥ 2：{len(hits)} 通り", ""]
    out += [f"- {r[0]} {r[1]} 利確{r[2]}/損切り{r[3]}：設計 {f(r[4]['設計'])} ／ 検証 {f(r[4]['検証'])} ／ 2024/11〜 {f(r[4]['2024/11〜'])}" for r in hits]
    out += ["", "## すべて", "", "| ペア | パターン | 利確/損切り（ATR） | 設計 | 検証 | 2024/11〜 |", "|---|---|---|---|---|---|"]
    out += [f"| {r[0]} | {r[1]} | {r[2]}/{r[3]} | {f(r[4]['設計'])} | {f(r[4]['検証'])} | {f(r[4]['2024/11〜'])} |" for r in rows]
    text = "\n".join(out)
    open(os.path.join(D.ROOT, "reports", "research", f"patterns_{tf}.md"), "w", encoding="utf-8").write(text + "\n")
    print("\n".join(out[:6 + len(hits)]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "1h")

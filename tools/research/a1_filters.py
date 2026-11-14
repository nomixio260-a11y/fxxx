#!/usr/bin/env python3
"""A1（EURUSD ロンドン 11:00〜13:00 の売り）を、入る時点で分かる情報で分けて、負けやすい状態を探す。

分け方（すべて入る前のデータ）：
- 値動きの大きさ（1時間足の直近24本の平均値幅、pips の絶対値）
- 直近 N 日（5・20・60日）の EURUSD の動き（pips）
- 前日の A1 の結果（勝ち・負け）
期間：2015〜21/10、前半 21/11〜24/10、後半 24/11〜。コスト後 pips／回。
使い方: python3 tools/research/a1_filters.py  → reports/research/a1_filters.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

PERIODS = (("2015〜21/10", ("2015-01-01", "2021-11-01")), ("前半", ("2021-11-01", "2024-11-01")),
           ("後半", ("2024-11-01", "2026-11-14")))


def st(x):
    x = x[~np.isnan(x)]
    if len(x) < 20:
        return f"{len(x)}回"
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return f"{len(x)}回 {x.mean():+.2f} PF {gp / gl if gl > 0 else 9.99:.2f}"


def main():
    df = D.bars("EURUSD", "5min")
    pip, cost = 1e-4, S.COST["EURUSD"]
    o = df["o"]
    t = df.index[(df["ldn_h"].values == 11) & (df["ldn_m"].values == 0)]
    r = pd.Series(-(o.reindex(t + pd.Timedelta(minutes=120)).values - o.reindex(t).values) / pip - cost, index=t).dropna()
    t = r.index
    h1 = D.bars("EURUSD", "1h")
    atr = ((h1["h"] - h1["l"]).rolling(24).mean().shift(1) / pip).reindex(t.floor("1h")).values
    daily = o.resample("1D").first().dropna()
    feats = {"値動きの大きさ（1時間足の平均値幅 pips）": atr}
    for n in (5, 20, 60):
        prev = daily.shift(1).reindex(t.normalize()).values
        base = daily.shift(n + 1).reindex(t.normalize()).values
        feats[f"直近{n}日の EURUSD の動き（pips、＋＝ユーロ高）"] = (prev - base) / pip
    prev_res = r.shift(1).values
    feats["前日の A1 の結果（pips）"] = prev_res
    out = ["# A1 を入る前の情報で分ける（コスト後 pips／回）", ""]
    allm = np.ones(len(r), bool)
    out.append("全体：" + " ／ ".join(f"{n} {st(r.values[D.period_mask(t, p)])}" for n, p in PERIODS))
    out.append("")
    for name, v in feats.items():
        v = np.asarray(v, float)
        ok = ~np.isnan(v)
        q = np.nanquantile(v[ok & D.period_mask(t, PERIODS[0][1])], [0.25, 0.5, 0.75])
        out += [f"## {name}（境目は 2015〜21年の4分位：{q[0]:+.1f} / {q[1]:+.1f} / {q[2]:+.1f}）", "",
                "| 区分 | " + " | ".join(n for n, _ in PERIODS) + " |", "|---|---|---|---|"]
        bins = [(-np.inf, q[0]), (q[0], q[1]), (q[1], q[2]), (q[2], np.inf)]
        for k, (lo, hi) in enumerate(bins):
            m = ok & (v > lo) & (v <= hi)
            out.append(f"| 第{k + 1}（{lo:+.1f}〜{hi:+.1f}） | " + " | ".join(st(r.values[m & D.period_mask(t, p)]) for _, p in PERIODS) + " |")
        out.append("")
    text = "\n".join(out) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "a1_filters.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

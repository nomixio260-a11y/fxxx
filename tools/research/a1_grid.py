#!/usr/bin/env python3
"""A1（EURUSD ロンドン朝の売り）の入る時刻・保有時間を変えて、3つの期間すべてで安定する形を探す。

入る時刻：ロンドン 9:00〜12:30（30分ごと）、保有：60〜240分（60分ごと）、毎日。
選び方：3つの期間（2015〜21/10・前半・後半）の t 値の最小が大きいもの（どの期間でも崩れにくい）。
使い方: python3 tools/research/a1_grid.py  → reports/research/a1_grid.md
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
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return {"n": len(x), "mean": x.mean(), "pf": gp / gl if gl > 0 else 9.99, "t": x.mean() / x.std(ddof=1) * np.sqrt(len(x))}


def main(pair="EURUSD"):
    df = D.bars(pair, "5min")
    pip, cost = D.pip_size(pair), S.COST[pair]
    o = df["o"]
    rows = []
    for hh in range(9, 13):
        for mm in (0, 30):
            t = df.index[(df["ldn_h"].values == hh) & (df["ldn_m"].values == mm)]
            for hold in (60, 120, 180, 240):
                r = pd.Series(-(o.reindex(t + pd.Timedelta(minutes=hold)).values - o.reindex(t).values) / pip - cost, index=t).dropna()
                res = [st(r[D.period_mask(r.index, p)].values) for _, p in PERIODS]
                rows.append((f"{hh}:{mm:02d}", hold, res, min(s["t"] for s in res)))
    rows.sort(key=lambda x: -x[3])
    out = [f"# A1 の時刻・保有時間の比較（{pair} 売り、毎日、コスト後 pips／回）", "",
           "| 入る時刻（ロンドン） | 保有（分） | " + " | ".join(p for p, _ in PERIODS) + " | t の最小 |", "|---|---|---|---|---|---|"]
    for tm, hold, res, mt in rows:
        out.append(f"| {tm} | {hold} | " + " | ".join(f"{s['mean']:+.2f} PF {s['pf']:.2f} t {s['t']:.1f}" for s in res) + f" | {mt:.1f} |")
    text = "\n".join(out) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "a1_grid.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

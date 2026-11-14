#!/usr/bin/env python3
"""候補：東京時間 4:30（= UTC 19:30、ニューヨークの午後）の AUDJPY 買い、60分保有。曜日ごと・年ごとに確かめる。
（full_scan の |t| ≥ 2.5 の探索で、水曜（東京の日付）が3つの期間すべてでプラスだった）
使い方: python3 tools/research/audjpy_tue.py
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
    if len(x) < 10:
        return "-"
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return f"{len(x)}回 {x.mean():+.2f} PF {gp / gl if gl > 0 else 9.99:.2f} t {x.mean() / x.std(ddof=1) * np.sqrt(len(x)):.1f}"


def main(pair="AUDJPY", hh=4, mm=30, hold=60):
    df = D.bars(pair, "5min")
    pip, cost = D.pip_size(pair), S.COST[pair]
    t = df.index[(df["tky_h"].values == hh) & (df["tky_m"].values == mm)]
    o = df["o"]
    r = pd.Series((o.reindex(t + pd.Timedelta(minutes=hold)).values - o.reindex(t).values) / pip - cost, index=t).dropna()
    dow = pd.DatetimeIndex(df.loc[r.index, "tky_date"]).dayofweek
    print(f"{pair} 東京 {hh}:{mm:02d} 買い {hold}分（コスト後 pips）")
    for k, n in enumerate("月火水木金"):
        m = dow == k
        print(f"  {n}: " + " | ".join(st(r[m & D.period_mask(r.index, p)].values) for _, p in PERIODS))
    w = r[dow == 2]
    print("  水曜の年ごと:", " ".join(f"{y}:{v:+.1f}" for y, v in w.groupby(w.index.year).mean().items()))
    print("  水曜 +0.5pips:", " | ".join(st(w[D.period_mask(w.index, p)].values - 0.5) for _, p in PERIODS))


if __name__ == "__main__":
    main()
    main(hold=120, hh=3, mm=30)

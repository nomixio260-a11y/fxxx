#!/usr/bin/env python3
"""東京仲値（9:55）の前のドル買いが、ゴトー日以外の日にもあるか（5分足、コスト前 pips と t 値、3期間）。
使い方: python3 tools/research/prefix_daily.py"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

PER = (("15-21", "2015-01-01", "2021-11-01"), ("前半", "2021-11-01", "2024-11-01"), ("後半", "2024-11-01", "2027-01-01"))


def run(pair, sign=1):
    df = D.bars(pair, "5min")
    pip = D.pip_size(pair)
    f = S.day_filters(df, "tky")
    o = df["o"]
    wk = pd.DatetimeIndex(df["tky_date"]).dayofweek.values < 5
    for name, mask in (("ゴトー日", f["gotobi"]), ("ゴトー日以外", ~f["gotobi"] & wk)):
        for (h, m, mins) in ((8, 0, 115), (9, 0, 55), (9, 25, 30), (9, 40, 15), (9, 55, 15), (9, 55, 60)):
            sel = (df["tky_h"].values == h) & (df["tky_m"].values == m) & mask
            t = df.index[sel]
            r = pd.Series(sign * (o.reindex(t + pd.Timedelta(minutes=mins)).values - o.reindex(t).values) / pip, index=t).dropna()
            out = []
            for lab, a, b in PER:
                x = r[(r.index >= a) & (r.index < b)]
                out.append(f"{x.mean():+.2f}(t{x.mean() / x.std() * np.sqrt(len(x)):+.1f},n{len(x)})")
            print(f"{pair} {name} {h:02d}:{m:02d}+{mins}分 買い: " + " / ".join(out))


if __name__ == "__main__":
    run("USDJPY")
    run("EURJPY")

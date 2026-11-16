#!/usr/bin/env python3
"""仲値前の買い（P8：USDJPY 8:00 買い、P2：EURJPY 9:25 買い、ゴトー日）の決済の時刻を1分ずつ変えた成績（1分足、コスト前 pips、3期間＋直近1年）。
9:55 の仲値の直後に下げに変わるため、遅れて決済すると利益を返す。1分早めると遅れに強くなるかを調べる。
使い方: python3 tools/research/prefix_exit_minute.py"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

PER = (("15-21", "2015-01-01", "2021-11-01"), ("前半", "2021-11-01", "2024-11-01"), ("後半", "2024-11-01", "2025-11-01"), ("直近1年", "2025-11-01", "2027-01-01"))


def main():
    for pair, hh, mm in (("USDJPY", 8, 0), ("EURJPY", 9, 25)):
        m1 = D.load_m1(pair)
        if "tky_h" not in m1.columns:
            m1 = D.add_local_time(m1)
        g = S.gotobi_mask(pd.DatetimeIndex(m1["tky_date"]))
        o = m1["o"]
        t0 = m1.index[(m1["tky_h"].values == hh) & (m1["tky_m"].values == mm) & g]
        e = o.reindex(t0).values
        print(f"== {pair} ゴトー日 {hh}:{mm:02d} 買い：決済の時刻 | " + " | ".join(p[0] for p in PER))
        for xm in (52, 53, 54, 55, 56, 57):
            mins = (9 * 60 + xm) - (hh * 60 + mm)
            x = o.reindex(t0 + pd.Timedelta(minutes=mins)).values
            r = pd.Series((x - e) / 0.01, index=t0).dropna()
            cells = []
            for _, a, b in PER:
                y = r[(r.index >= a) & (r.index < b)]
                cells.append(f"{y.mean():+.2f}（t {y.mean() / y.std() * np.sqrt(len(y)):+.1f}）")
            print(f"  9:{xm} | " + " | ".join(cells))


if __name__ == "__main__":
    main()

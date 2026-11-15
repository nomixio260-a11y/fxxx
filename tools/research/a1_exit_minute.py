#!/usr/bin/env python3
"""A1（EURUSD ロンドン 11:00 売り）の決済の時刻を1分ずつ変えたときの成績（1分足、コスト前 pips と t 値、3期間）。
13:00 の直後にユーロの下げが反転するため、決済が遅れると利益を返す。少し早めに決済すると、遅れに強くなるかを調べる。
使い方: python3 tools/research/a1_exit_minute.py"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402

PER = (("15-21", "2015-01-01", "2021-11-01"), ("前半", "2021-11-01", "2024-11-01"), ("後半", "2024-11-01", "2027-01-01"))


def main():
    m1 = D.add_local_time(D.load_m1("EURUSD")) if "ldn_h" not in D.load_m1("EURUSD").columns else D.load_m1("EURUSD")
    o = m1["o"]
    wk = pd.DatetimeIndex(m1["ldn_date"]).dayofweek.values < 5
    t0 = m1.index[(m1["ldn_h"].values == 11) & (m1["ldn_m"].values == 0) & wk]
    e = o.reindex(t0).values
    print("決済の時刻（ロンドン） | 2015-21 | 前半 | 後半  （売りの利益、コスト前 pips）")
    for mins in (110, 115, 118, 119, 120, 121, 122, 125, 130):
        x = o.reindex(t0 + pd.Timedelta(minutes=mins)).values
        r = pd.Series(-(x - e) / 1e-4, index=t0).dropna()
        cells = []
        for _, a, b in PER:
            y = r[(r.index >= a) & (r.index < b)]
            cells.append(f"{y.mean():+.2f}（t {y.mean() / y.std() * np.sqrt(len(y)):+.1f}）")
        hh, mm = divmod(11 * 60 + mins, 60)
        print(f"{hh:02d}:{mm:02d} | " + " | ".join(cells))


if __name__ == "__main__":
    main()

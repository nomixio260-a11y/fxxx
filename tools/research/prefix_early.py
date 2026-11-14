#!/usr/bin/env python3
"""ゴトー日の仲値前の買いを、9:25 より早く始めた場合の成績（9:55 に決済）。USDJPY・EURJPY。

入る時刻：東京 7:00〜9:25、決済：9:55。コスト後 pips／回。期間：2015〜21/10、前半 21/11〜24/10、後半 24/11〜。
使い方: python3 tools/research/prefix_early.py  → reports/research/prefix_early.md
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
    return f"{x.mean():+.2f} PF {gp / gl if gl > 0 else 9.99:.2f} t {x.mean() / x.std(ddof=1) * np.sqrt(len(x)):.1f}"


def main():
    out = ["# ゴトー日の仲値前の買い：入る時刻の比較（9:55 に決済、コスト後 pips／回）", ""]
    for pair in ("USDJPY", "EURJPY"):
        df = D.bars(pair, "5min")
        pip, cost = D.pip_size(pair), S.COST[pair]
        o = df["o"]
        fix = df.index[(df["tky_h"].values == 9) & (df["tky_m"].values == 55)]
        fix = fix[S.gotobi_mask(pd.DatetimeIndex(df.loc[fix, "tky_date"]))]
        out += [f"## {pair}", "", "| 入る時刻 | " + " | ".join(p for p, _ in PERIODS) + " | 年ごと（2015→2026） |", "|---|---|---|---|---|"]
        for hh, mm in ((7, 0), (7, 30), (8, 0), (8, 30), (9, 0), (9, 25)):
            back = pd.Timedelta(minutes=(9 * 60 + 55) - (hh * 60 + mm))
            r = pd.Series((o.reindex(fix).values - o.reindex(fix - back).values) / pip - cost, index=fix).dropna()
            yr = r.groupby(r.index.year).mean()
            out.append(f"| {hh}:{mm:02d} | " + " | ".join(st(r[D.period_mask(r.index, p)].values) for _, p in PERIODS) +
                       " | " + " ".join(f"{v:+.1f}" for v in yr.values) + " |")
        out.append("")
    text = "\n".join(out) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "prefix_early.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

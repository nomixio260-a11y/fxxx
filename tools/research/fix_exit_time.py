#!/usr/bin/env python3
"""ゴトー日の仲値後の売り（G3F・Q2）と仲値前の買い（P2）の、入る時刻・決済の時刻を変えたときの成績を年ごとに比べる。

G3F：USDJPY、9:55 売り、仲値前30分の値動き > -0.07ATR の日だけ
Q2 ：EURJPY、9:55 売り、仲値前30分の値動き > 0.33ATR の日だけ
P2 ：EURJPY、9:25 買い
コスト後の pips（1回あたり）。期間：2015〜21/10、前半 21/11〜24/10、後半 24/11〜。
使い方: python3 tools/research/fix_exit_time.py  → reports/research/fix_exit_time.md
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
RULES = [("G3F", "USDJPY", (9, 55), -1, -0.07, [5, 10, 15, 20, 35, 65, 125]),
         ("Q2", "EURJPY", (9, 55), -1, 0.33, [5, 10, 15, 20, 35, 65, 125]),
         ("P2", "EURJPY", (9, 25), 1, None, [10, 20, 25, 30, 35, 40])]


def st(x):
    x = x[~np.isnan(x)]
    if len(x) < 10:
        return "-"
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return f"{x.mean():+.2f} PF {gp / gl if gl > 0 else 9.99:.2f} t {x.mean() / x.std(ddof=1) * np.sqrt(len(x)):.1f}"


def main():
    out = ["# 仲値のルールの決済時刻の比較（コスト後 pips／回）", ""]
    for name, pair, (hh, mm), d, pre, holds in RULES:
        df = D.bars(pair, "5min")
        pip, cost = D.pip_size(pair), S.COST[pair]
        t = df.index[(df["tky_h"].values == hh) & (df["tky_m"].values == mm)]
        t = t[S.gotobi_mask(pd.DatetimeIndex(df.loc[t, "tky_date"]))]
        o = df["o"]
        if pre is not None:
            h1 = D.bars(pair, "1h")
            a = ((h1["h"] - h1["l"]).rolling(24).mean().shift(1) / pip).reindex(t.floor("1h")).values
            z = (o.reindex(t).values - o.reindex(t - pd.Timedelta(minutes=30)).values) / pip / a
            t = t[z > pre]
        e = o.reindex(t).values
        out += [f"## {name}（{pair}、{hh}:{mm:02d} に入る）", "", "| 保有（分） | " + " | ".join(p for p, _ in PERIODS) + " | 年ごとの平均（2015→2026） |",
                "|---|---|---|---|---|"]
        for H in holds:
            r = pd.Series(d * (o.reindex(t + pd.Timedelta(minutes=H)).values - e) / pip - cost, index=t)
            yr = r.groupby(r.index.year).mean()
            out.append(f"| {H} | " + " | ".join(st(r[D.period_mask(r.index, p)].values) for _, p in PERIODS) +
                       " | " + " ".join(f"{v:+.1f}" for v in yr.values) + " |")
        out.append("")
    text = "\n".join(out) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "fix_exit_time.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

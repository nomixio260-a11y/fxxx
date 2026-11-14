#!/usr/bin/env python3
"""ゴトー日の仲値（9:55）の前後の値動きを1分単位で調べる（入る時刻を1〜2分早めると、遅れの影響を減らせるか）。

USDJPY・EURJPY について、東京 9:45〜10:05 の各分の始値を、9:55 の始値を 0 とした pips で年ごとに平均する。
あわせて、G3F（売り）を 9:53・9:54・9:55・9:56 に入って 12:00 に決済した場合のコスト後 pips を比べる。
使い方: python3 tools/research/fix_minute.py  → reports/research/fix_minute.md
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
    out = ["# 仲値の前後の1分ごとの値動き（ゴトー日、9:55 の始値を 0 とした pips）", ""]
    for pair in ("USDJPY", "EURJPY"):
        m1 = D.load_m1(pair)
        pip, cost = D.pip_size(pair), S.COST[pair]
        loc = m1.index.tz_localize("UTC").tz_convert("Asia/Tokyo").tz_localize(None)
        o = pd.Series(m1["o"].values, index=loc)
        days = pd.DatetimeIndex(sorted(set(loc.normalize())))
        days = days[(days.dayofweek < 5) & S.gotobi_mask(days)]
        mins = list(range(-10, 11))
        mat = {}
        for d in days:
            base = d + pd.Timedelta(hours=9, minutes=55)
            v = o.reindex([base + pd.Timedelta(minutes=k) for k in mins]).values
            if np.isnan(v[10]):
                continue
            mat[d] = (v - v[10]) / pip
        df = pd.DataFrame(mat, index=[f"{(9 * 60 + 55 + k) // 60}:{(9 * 60 + 55 + k) % 60:02d}" for k in mins]).T
        out += [f"## {pair}", "", "| 年 | " + " | ".join(df.columns) + " |", "|---|" + "---|" * len(df.columns)]
        for y, g in df.groupby(df.index.year):
            out.append(f"| {y} | " + " | ".join(f"{x:+.1f}" for x in g.mean().values) + " |")
        out.append("")
        if pair == "USDJPY":
            out += ["### G3F（売り、12:00 に決済）の入る時刻の比較（仲値前30分の条件なし）", "", "| 入る時刻 | " + " | ".join(p for p, _ in PERIODS) + " |", "|---|---|---|---|"]
            for k in (-2, -1, 0, 1, 2):
                ent = pd.DatetimeIndex([d + pd.Timedelta(hours=9, minutes=55 + k) for d in days])
                ex = pd.DatetimeIndex([d + pd.Timedelta(hours=12) for d in days])
                r = pd.Series(-(o.reindex(ex).values - o.reindex(ent).values) / pip - cost, index=days)
                out.append(f"| 9:{55 + k:02d} | " + " | ".join(st(r[D.period_mask(r.index, p)].values) for _, p in PERIODS) + " |")
            out.append("")
    text = "\n".join(out) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "fix_minute.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

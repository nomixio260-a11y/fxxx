#!/usr/bin/env python3
"""なぜ直近は利益が少なく負けるのか：各ルールの偏りの強さを年ごとに調べる。

各ルールについて、年ごとに次を出す（コスト前の pips）：
- 平均の値動き（取引の向き）と t 値
- 値動きの大きさ（1時間足の平均値幅、pips）
- 「偏り ÷ 値動きの大きさ」（値動きが大きくなっただけなのか、偏りそのものが弱まったのか）
あわせて、ゴトー日の仲値前（9:25→9:55）の USDJPY の上昇（実需のドル買いの強さ）も年ごとに出す。

使い方: python3 tools/research/decay.py  → reports/research/decay.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

RULES = [  # 名前, 銘柄, 時計, 時, 分, 保有, 向き, 日
    ("G3F（仲値後の売り、ゴトー日）", "USDJPY", "tky", 9, 55, 125, -1, "gotobi"),
    ("仲値前の買い（USDJPY、ゴトー日）", "USDJPY", "tky", 9, 25, 30, 1, "gotobi"),
    ("P2（EURJPY 仲値前の買い、ゴトー日）", "EURJPY", "tky", 9, 25, 30, 1, "gotobi"),
    ("P4（EURJPY 仲値前の買い、ゴトー日以外の金曜）", "EURJPY", "tky", 9, 25, 30, 1, "fri_ng"),
    ("Q2（EURJPY 仲値後の売り、ゴトー日）", "EURJPY", "tky", 9, 55, 125, -1, "gotobi"),
    ("C3（EURJPY 月末 10:00 売り）", "EURJPY", "tky", 10, 0, 60, -1, "monthend"),
    ("C4（GBPJPY 月初 22:00 売り）", "GBPJPY", "tky", 22, 0, 120, -1, "monthstart"),
    ("A1（EURUSD ロンドン11:00 売り）", "EURUSD", "ldn", 11, 0, 120, -1, "all"),
]


def main():
    out = ["# 偏りの強さの年ごとの変化（コスト前の pips）", "",
           "- 平均：取引の向きの平均の値動き（pips）",
           "- 値幅：1時間足の平均値幅（pips）。相場の値動きの大きさ",
           "- 比：平均 ÷ 値幅（値動きの大きさをそろえた偏りの強さ）", ""]
    for name, pair, clock, hh, mm, hold, d, day in RULES:
        df = D.bars(pair, "5min")
        pip = D.pip_size(pair)
        t = df.index[(df[f"{clock}_h"].values == hh) & (df[f"{clock}_m"].values == mm)]
        dates = pd.DatetimeIndex(df.loc[t, f"{clock}_date"])
        got = S.gotobi_mask(pd.DatetimeIndex(df.loc[t, "tky_date"]))
        f = S.day_filters(df.loc[t], clock)
        m = {"gotobi": got, "fri_ng": (dates.dayofweek == 4) & ~got, "monthend": f["monthend"],
             "monthstart": f["monthstart"], "all": np.ones(len(t), bool)}[day]
        t = t[m]
        o = df["o"]
        r = pd.Series(d * (o.reindex(t + pd.Timedelta(minutes=hold)).values - o.reindex(t).values) / pip, index=t).dropna()
        h1 = D.bars(pair, "1h")
        a = ((h1["h"] - h1["l"]).rolling(24).mean().shift(1) / pip).reindex(r.index.floor("1h"))
        a.index = r.index
        out += [f"## {name}", "", "| 年 | 回数 | 平均 | t | 値幅 | 比 | コスト後 |", "|---|---|---|---|---|---|---|"]
        for y, g in r.groupby(r.index.year):
            n = len(g)
            tt = g.mean() / g.std(ddof=1) * np.sqrt(n) if n > 2 else 0
            aa = a[g.index].mean()
            out.append(f"| {y} | {n} | {g.mean():+.2f} | {tt:+.1f} | {aa:.1f} | {g.mean() / aa:+.3f} | {g.mean() - S.COST[pair]:+.2f} |")
        out.append("")
    text = "\n".join(out) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "decay.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

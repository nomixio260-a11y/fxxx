#!/usr/bin/env python3
"""バックテストの「年ごとに、1つのルールにどれだけ頼っているか」を測る。

月 × ルールの損益（NNNN_rulemonth.csv）を、その月の月初の残高で割った損益率（%）にしてから、年ごとに足す。
年ごとに次を出す：
- 全体の損益率の合計
- 最も稼いだルールと、その割合（そのルールの損益 ÷ 全体）
- そのルールが ±0 だったと仮定した場合の、その年の損益率（1つのロジックが崩れても耐えられるか）
- プラスだったルールの数
使い方: python3 tools/rule_dependency.py NNNN [初期資金]
"""
import os
import re
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(run, deposit):
    d = pd.read_csv(os.path.join(ROOT, "reports", "runs", f"{run}_rulemonth.csv"))
    d[["month", "rule"]] = d.month_rule.str.split("|", expand=True)
    p = d.pivot_table(index="month", columns="rule", values="profit", aggfunc="sum").fillna(0)
    t = open(os.path.join(ROOT, "reports", "runs", f"{run}.txt"), encoding="utf-8").read()
    mon = {k: float(v) for k, v in (x.split(":") for x in re.search(r"^MONTHLY (.*)$", t, re.M).group(1).split(",") if ":" in x)}
    bal, start = deposit, {}
    for m in sorted(mon):
        start[m] = bal
        bal *= 1 + mon[m] / 100
    pct = p.div(pd.Series(start), axis=0) * 100
    pct["year"] = [m[:4] for m in pct.index]
    yr = pct.groupby("year").sum()
    print(f"| 年 | 合計 | 最も稼いだルール（割合） | そのルールが ±0 なら | プラスのルール数 |\n|---|---|---|---|---|")
    for y, row in yr.iterrows():
        tot = row.sum()
        top = row.idxmax()
        share = row[top] / tot * 100 if tot > 0 else float("nan")
        print(f"| {y} | {tot:+.1f}% | {top}（{share:.0f}%） | {tot - row[top]:+.1f}% | {(row > 0).sum()}/{len(row)} |")


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 1_000_000)

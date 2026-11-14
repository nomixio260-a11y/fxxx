#!/usr/bin/env python3
"""ルールごとの配分を「最近の成績」で変えたら、マイナスの月が減るかを試算する。

入力：MT5 のバックテストの月 × ルールの損益（NNNN_rulemonth.csv）を、月初の残高で割った損益率（%）。
2015〜21年（実行413）と 2021年11月〜（実行412）をつなげて使う。
配分 w（0.3〜1.0。1.0 を超える配分は、証拠金の上限のため実際にはできないので使わない）を、
その月より前の成績だけで決める（未来の情報は使わない）：
- 基準：すべて 1.0
- A：直近 N か月の合計がマイナスのルールは 0.5
- B：直近 N か月の合計がマイナスのルールは 0.3
- C：直近 N か月の「平均 ÷ ばらつき」に応じて 0.3〜1.0
月の損益率 = Σ w × ルールの損益率（複利・証拠金の取り合いは無視した概算）。
使い方: python3 tools/research/rule_weights.py
"""
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def contrib(run, deposit):
    d = pd.read_csv(os.path.join(ROOT, "reports", "runs", f"{run}_rulemonth.csv"))
    d[["month", "rule"]] = d.month_rule.str.split("|", expand=True)
    p = d.pivot_table(index="month", columns="rule", values="profit", aggfunc="sum").fillna(0)
    t = open(os.path.join(ROOT, "reports", "runs", f"{run}.txt"), encoding="utf-8").read()
    mon = {k: float(v) for k, v in (x.split(":") for x in re.search(r"^MONTHLY (.*)$", t, re.M).group(1).split(",") if ":" in x)}
    bal, start = deposit, {}
    for m in sorted(mon):
        start[m] = bal
        bal *= 1 + mon[m] / 100
    return p.div(pd.Series(start), axis=0) * 100


def stats(r, label):
    r = np.asarray(r)
    g = np.prod(1 + r / 100)
    return f"{label}: 月平均 {r.mean():+.2f}% 負け月 {int((r < 0).sum())}/{len(r)} 最悪 {r.min():+.1f}% 複利 {g:,.0f}倍"


def main():
    a = contrib("0413", 300000)
    b = contrib("0412", 300000)
    c = pd.concat([a, b]).fillna(0)
    c = c[~c.index.duplicated(keep="last")].sort_index()
    out = ["# ルールの配分を最近の成績で変える試算（2015年1月〜2026年11月、月 × ルールの損益率）", ""]
    base = c.sum(axis=1)
    out.append("- " + stats(base.values, "基準（すべて 1.0）"))
    for N in (6, 12):
        trail = c.rolling(N, min_periods=N).sum().shift(1)
        trail_sd = c.rolling(N, min_periods=N).std().shift(1)
        for name, w in (
            (f"A（直近{N}か月がマイナスなら 0.5）", np.where(trail < 0, 0.5, 1.0)),
            (f"B（直近{N}か月がマイナスなら 0.3）", np.where(trail < 0, 0.3, 1.0)),
            (f"C（直近{N}か月の平均÷ばらつきで 0.3〜1.0）", np.clip(0.65 + 0.35 * (trail / N) / trail_sd.replace(0, np.nan), 0.3, 1.0)),
        ):
            w = pd.DataFrame(w, index=c.index, columns=c.columns).fillna(1.0)
            r = (w * c).sum(axis=1)
            out.append("- " + stats(r.values, name))
            for lab, lo, hi in (("2015〜21/10", "2015-01", "2021-10"), ("21/11〜24/10", "2021-11", "2024-10"), ("24/11〜", "2024-11", "2099")):
                m = (r.index >= lo) & (r.index <= hi)
                bm = (base.index >= lo) & (base.index <= hi)
                out.append(f"  - {lab}：{stats(r.values[m], '変更後')} ／ {stats(base.values[bm], '基準')}")
    text = "\n".join(out) + "\n"
    open(os.path.join(ROOT, "reports", "research", "rule_weights.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

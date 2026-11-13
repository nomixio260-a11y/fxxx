#!/usr/bin/env python3
"""ゴトー日以外の日の東京仲値：仲値前30分の動きで絞ると、仲値後の売りが使えるか。

- 対象：東京の営業日のうちゴトー日でない日。USDJPY・EURJPY。
- 仲値前30分（9:25〜9:55）の値動き ÷ 1時間足の平均値幅 で3つに分ける（境目は設計期間で決める）。
- 仲値後に売り、30分 / 60分 / 125分後に決済（コスト後）。

使い方: python3 tools/research/fix_nongotobi.py  → reports/research/fix_nongotobi.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402


def st(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 15:
        return f"{len(x)}回"
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return f"{len(x)}回 {x.mean():+.2f}pips PF {gp / gl if gl > 0 else 9.99:.2f} t {x.mean() / x.std(ddof=1) * np.sqrt(len(x)):.1f}"


def main():
    out = ["# ゴトー日以外の東京仲値：仲値前30分の動きで絞った仲値後の売り（コスト後）", ""]
    hol = S.load_jp_holidays()
    for pair in ("USDJPY", "EURJPY"):
        df = D.bars(pair, "5min")
        o = df["o"]
        pip = D.pip_size(pair)
        cost = S.COST[pair]
        fix = df.index[(df["tky_h"].values == 9) & (df["tky_m"].values == 55)]
        dates = pd.DatetimeIndex(df.loc[fix, "tky_date"])
        got = S.gotobi_mask(dates)
        biz = np.array([S.jp_business(d, hol) for d in dates])
        fix = fix[~got & biz]
        p = lambda t: o.reindex(t).values  # noqa: E731
        h1 = D.bars(pair, "1h")
        a = (h1["h"] - h1["l"]).rolling(24).mean().shift(1).reindex(fix.floor("1h")).values / pip
        z = (p(fix) - p(fix - pd.Timedelta(minutes=30))) / pip / a
        des = D.period_mask(fix, D.DESIGN)
        val = D.period_mask(fix, D.VALID)
        lo, hi = np.nanquantile(z[des], [1 / 3, 2 / 3])
        out += [f"## {pair}（境目：{lo:+.2f} / {hi:+.2f}）", "", "| 保有 | 仲値前の動き | 設計 | 検証 |", "|---|---|---|---|"]
        for hold in (30, 60, 125):
            post = -(p(fix + pd.Timedelta(minutes=hold)) - p(fix)) / pip - cost
            for lab, m in (("全部", np.ones(len(z), bool)), ("下1/3", z <= lo), ("中", (z > lo) & (z <= hi)), ("上1/3（上げが大きい）", z > hi)):
                out.append(f"| {hold}分 | {lab} | {st(post[des & m])} | {st(post[val & m])} |")
        out.append("")
    text = "\n".join(out)
    open(os.path.join(D.ROOT, "reports", "research", "fix_nongotobi.md"), "w", encoding="utf-8").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

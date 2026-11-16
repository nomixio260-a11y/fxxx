#!/usr/bin/env python3
"""途中の時点の値動きを見て、持ち続けるか決める形（G3F で効いた CUT）を、A1・Q2 にも試す（5分足、コスト +0.5 pips 込み、pips／回）。
決めるときに使うのは、その時点までの値動きだけ。
使い方: python3 tools/research/conditional_hold.py"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

PER = (("15-21", "2015-01-01", "2021-11-01"), ("前半", "2021-11-01", "2024-11-01"), ("後半", "2024-11-01", "2025-11-01"), ("直近1年", "2025-11-01", "2027-01-01"))


def run(name, pair, clock, hh, mm, filt, sign, hold, checks, ks, pre_filter=None):
    df = D.bars(pair, "5min")
    pip, cost = D.pip_size(pair), S.COST[pair] + 0.5
    f = S.day_filters(df, clock)[filt]
    o = df["o"]
    t = df.index[(df[f"{clock}_h"].values == hh) & (df[f"{clock}_m"].values == mm) & f]
    p0 = o.reindex(t).values
    pend = o.reindex(t + pd.Timedelta(minutes=hold)).values
    keep = ~np.isnan(p0 + pend)
    if pre_filter is not None:
        keep &= pre_filter(df, t, p0, pip)
    print(f"== {name}（今：{hold}分持つ）  形 | " + " | ".join(p[0] for p in PER) + " | マイナスの年")
    rfull = sign * (pend - p0) / pip - cost

    def show(lab, r):
        r = pd.Series(r, index=t)[keep]
        cells = []
        for _, a, b in PER:
            x = r[(r.index >= a) & (r.index < b)]
            cells.append(f"{x.mean():+.2f}")
        yr = r.groupby(r.index.year).mean()
        print(f"  {lab} | " + " | ".join(cells) + f" | {(yr < 0).sum()}/{len(yr)}")
    show("今のまま", rfull)
    for cm in checks:
        pc = o.reindex(t + pd.Timedelta(minutes=cm)).values
        gain = sign * (pc - p0) / pip
        rcut = gain - cost
        for k in ks:
            show(f"{cm}分後に {k:+g} pips 以上なら最後まで、でなければ決済", np.where(gain >= k, rfull, rcut))


def q2_pre(df, t, p0, pip):
    # Q2：仲値前30分（9:25〜9:55）に大きく上げた日だけ（今の EA は 1時間足の平均値幅の 0.33倍。ここでは 8 pips 以上で近似）
    pre = df["o"].reindex(t - pd.Timedelta(minutes=30)).values
    return (p0 - pre) / pip >= 8


if __name__ == "__main__":
    run("A1 EURUSD ロンドン 11:00 売り", "EURUSD", "ldn", 11, 0, "all", -1, 120, [60, 90], [-5, 0, 3])
    run("Q2 EURJPY ゴトー日 9:55 売り", "EURJPY", "tky", 9, 55, "gotobi", -1, 125, [20], [0, 3, 6], q2_pre)

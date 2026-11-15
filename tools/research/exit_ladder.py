#!/usr/bin/env python3
"""決済の時刻を1つに決めず、数本に分けた場合（はしご決済）の、年ごとの安定性を比べる（5分足、コスト後 pips／回）。

使い方: python3 tools/research/exit_ladder.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402


def entries(df, clock, hh, mm, filt):
    m = (df[f"{clock}_h"].values == hh) & (df[f"{clock}_m"].values == mm)
    f = S.day_filters(df, clock)[filt]
    return df.index[m & f]


def legs(pair, clock, hh, mm, filt, sign, holds):
    df = D.bars(pair, "5min")
    pip = D.pip_size(pair)
    cost = S.COST[pair] + 0.5
    t = entries(df, clock, hh, mm, filt)
    o = df["o"]
    e = o.reindex(t).values
    out = {}
    for h in holds:
        x = o.reindex(t + pd.Timedelta(minutes=h)).values
        out[h] = pd.Series(sign * (x - e) / pip - cost, index=t)
    return pd.DataFrame(out).dropna()


def show(name, L, base_hold):
    L = L.copy()
    L["はしご"] = L.mean(axis=1)
    yr = L.groupby(L.index.year).mean()
    per = {}
    for lab, p in (("15-21", ("2015-01-01", "2021-11-01")), ("前半", ("2021-11-01", "2024-11-01")), ("後半", ("2024-11-01", "2026-12-01"))):
        per[lab] = L[(L.index >= p[0]) & (L.index < p[1])].mean()
    print(f"== {name}（今の決済：{base_hold}分）")
    t = pd.DataFrame(per).T
    t.loc["年の最小"] = yr.min()
    t.loc["マイナスの年"] = (yr < 0).sum()
    t.loc["2026"] = yr.loc[2026]
    t.loc["ばらつき(1回)"] = L.std()
    print(t.round(2).to_string())


if __name__ == "__main__":
    show("G3F USDJPY ゴトー日 9:55 売り", legs("USDJPY", "tky", 9, 55, "gotobi", -1, [20, 35, 65, 95, 125]), 125)
    show("Q2 EURJPY ゴトー日 9:55 売り", legs("EURJPY", "tky", 9, 55, "gotobi", -1, [20, 35, 65, 95, 125]), 125)
    show("A1 EURUSD ロンドン 11:00 売り", legs("EURUSD", "ldn", 11, 0, "all", -1, [60, 90, 120, 150, 180]), 120)
    show("P8 USDJPY ゴトー日 8:00 買い", legs("USDJPY", "tky", 8, 0, "gotobi", 1, [55, 85, 115]), 115)

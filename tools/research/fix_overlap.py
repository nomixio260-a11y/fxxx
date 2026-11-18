#!/usr/bin/env python3
"""ゴトー日の 9:55 に G3F（USDJPY 売り）と Q2（EURJPY 売り）の両方が条件を満たす日に、証拠金をどちらに回すのがよいかの試算。
今の EA は書いた順（G3F が先）に証拠金を使うので、両方が条件を満たす日は Q2 にほとんど回らない。
- G3F：9:25〜9:55 の USDJPY の値動き ÷ 1時間足の直近24本の平均値幅 > -0.07 のとき 9:55 に売り、10:15 の時点で 3 pips 以上勝っていれば 12:00 まで、そうでなければ 10:15 に決済。
- Q2：同じ物差しで EURJPY が > 0.33 のとき 9:55 に売り、12:00 に決済。
- 5分足の始値、コスト（S.COST + 0.5 pips）後の pips／回。Q2 は、証拠金あたりにそろえるため USDJPY ÷ EURJPY の値段の比を掛けた値も出す。
使い方: python3 tools/research/fix_overlap.py"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

PER = (("15-21", "2015-01-01", "2021-11-01"), ("前半", "2021-11-01", "2024-11-01"),
       ("後半", "2024-11-01", "2025-11-01"), ("直近1年", "2025-11-01", "2027-01-01"))


def legs(pair):
    df = D.bars(pair, "5min")
    h1 = D.bars(pair, "1h")
    g = S.day_filters(df, "tky")["gotobi"]
    o = df["o"]
    t = df.index[(df["tky_h"].values == 9) & (df["tky_m"].values == 55) & g]
    p0 = o.reindex(t).values
    pre = o.reindex(t - pd.Timedelta(minutes=30)).values
    p20 = o.reindex(t + pd.Timedelta(minutes=20)).values
    p125 = o.reindex(t + pd.Timedelta(minutes=125)).values
    rng = (h1["h"] - h1["l"]).rolling(24, min_periods=12).mean()
    last_done = t.floor("1h") - pd.Timedelta(hours=1)            # いまの足より前に確定した1時間足
    atr = rng.reindex(last_done).values
    z = (p0 - pre) / atr
    return pd.DataFrame({"p0": p0, "p20": p20, "p125": p125, "z": z}, index=t)


def main():
    u, e = legs("USDJPY"), legs("EURJPY")
    x = u.join(e, lsuffix="_u", rsuffix="_e", how="inner").dropna()
    pip = 0.01
    cu, ce = S.COST["USDJPY"] + 0.5, S.COST["EURJPY"] + 0.5
    m20 = -(x["p20_u"] - x["p0_u"]) / pip
    g3f = np.where(m20 >= 3, -(x["p125_u"] - x["p0_u"]) / pip, m20) - cu
    q2 = -(x["p125_e"] - x["p0_e"]) / pip - ce
    q2m = q2 * x["p0_u"] / x["p0_e"]                                # 証拠金あたり（USDJPY の1ロットの証拠金にそろえる）
    r = pd.DataFrame({"g3f": g3f, "q2": q2, "q2m": q2m}, index=x.index)
    tu, te = x["z_u"] > -0.07, x["z_e"] > 0.33
    groups = {"両方が条件を満たす日": tu & te, "G3F だけ": tu & ~te, "Q2 だけ": ~tu & te}
    for name, m in groups.items():
        print(f"## {name}")
        print("| | " + " | ".join(p[0] for p in PER) + " | プラスの年 |")
        print("|---|" + "---|" * (len(PER) + 1))
        cols = [("G3F", "g3f")] + ([("Q2", "q2"), ("Q2（証拠金あたり）", "q2m"), ("半分ずつ", None)] if name != "G3F だけ" else [])
        for lab, c in cols:
            s = (0.5 * (r["g3f"] + r["q2m"]) if c is None else r[c])[m]
            cells = []
            for _, a, b in PER:
                v = s[(s.index >= a) & (s.index < b)]
                cells.append(f"{v.mean():+.2f}（{len(v)}）" if len(v) else "—")
            yr = s.groupby(s.index.year).sum()
            print(f"| {lab} | " + " | ".join(cells) + f" | {(yr > 0).sum()}/{len(yr)} |")
        print()


if __name__ == "__main__":
    main()

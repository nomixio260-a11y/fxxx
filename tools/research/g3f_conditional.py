#!/usr/bin/env python3
"""G3F（ゴトー日の USDJPY 9:55 売り）を、10:15 の時点の値動きを見て「12:00 まで持つか、10:15 で決済するか」を決める形の試算。
決めるときに使うのは 10:15 までの値動きだけ（未来の情報は使わない）。5分足、コスト（0.8 + 0.5 pips）後の pips／回。
使い方: python3 tools/research/g3f_conditional.py"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

PER = (("15-21", "2015-01-01", "2021-11-01"), ("前半", "2021-11-01", "2024-11-01"), ("後半", "2024-11-01", "2025-11-01"), ("直近1年", "2025-11-01", "2027-01-01"))


def main():
    df = D.bars("USDJPY", "5min")
    g = S.day_filters(df, "tky")["gotobi"]
    o = df["o"]
    pip, cost = 0.01, S.COST["USDJPY"] + 0.5
    t = df.index[(df["tky_h"].values == 9) & (df["tky_m"].values == 55) & g]
    p0 = o.reindex(t).values
    pre = o.reindex(t - pd.Timedelta(minutes=30)).values
    p20 = o.reindex(t + pd.Timedelta(minutes=20)).values
    p125 = o.reindex(t + pd.Timedelta(minutes=125)).values
    ok = ~np.isnan(p0 + pre + p20 + p125)
    t, p0, pre, p20, p125 = t[ok], p0[ok], pre[ok], p20[ok], p125[ok]
    # 仲値前30分の条件（今の G3F：9:25〜9:55 に大きく下げていた日は見送り。ここでは 10 pips 以上の下げで近似）
    keep = (p0 - pre) / pip > -10
    r20 = -(p20 - p0) / pip - cost          # 10:15 で決済
    r125 = -(p125 - p0) / pip - cost        # 12:00 まで
    m20 = -(p20 - p0) / pip                 # 10:15 までの利益（コスト前、決めるときに分かっている）
    forms = {"10:15 で決済（20分）": r20, "12:00 まで（125分）": r125}
    for k in (0, 3, 6):
        forms[f"10:15 までに {k} pips 以上勝っていれば12:00まで"] = np.where(m20 >= k, r125, r20)
        forms[f"10:15 までに {k} pips 以上勝っていなければ12:00まで"] = np.where(m20 < k, r125, r20)
    forms["半分ずつ（20分と125分）"] = 0.5 * (r20 + r125)
    print("形 | " + " | ".join(p[0] for p in PER) + " | マイナスの年")
    s_idx = pd.DatetimeIndex(t)
    for name, r in forms.items():
        r = pd.Series(r, index=s_idx)[keep]
        cells = []
        for _, a, b in PER:
            x = r[(r.index >= a) & (r.index < b)]
            cells.append(f"{x.mean():+.2f}（{len(x)}）")
        yr = r.groupby(r.index.year).mean()
        print(f"{name} | " + " | ".join(cells) + f" | {(yr < 0).sum()}/{len(yr)}")


if __name__ == "__main__":
    main()

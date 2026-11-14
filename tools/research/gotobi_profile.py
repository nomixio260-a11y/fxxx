#!/usr/bin/env python3
"""ゴトー日の朝の USDJPY の平均的な値動きの形を、年ごとに比べる（偏りが消えたのか、時間がずれたのか）。

東京時間 8:00〜13:00 の5分足の始値を、9:55 の価格を基準（0）にした pips で、年ごとに平均する。
比べるため、ゴトー日以外の平日の平均も出す。
使い方: python3 tools/research/gotobi_profile.py [USDJPY]  → reports/research/gotobi_profile_<ペア>.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

TIMES = ["08:00", "08:30", "09:00", "09:25", "09:40", "09:50", "09:55", "10:00", "10:10", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00"]


def main(pair="USDJPY"):
    df = D.bars(pair, "5min")
    pip = D.pip_size(pair)
    loc = df.index.tz_localize("UTC").tz_convert("Asia/Tokyo").tz_localize(None)
    s = pd.Series(df["o"].values, index=loc)
    days = pd.DatetimeIndex(sorted(set(loc.normalize())))
    days = days[days.dayofweek < 5]
    got = S.gotobi_mask(days)
    out = [f"# ゴトー日の朝の {pair} の平均の値動き（9:55 の価格を 0 とした pips、東京時間）", ""]
    for lab, sel in (("ゴトー日", got), ("ゴトー日以外", ~got)):
        out += [f"## {lab}", "", "| 年 | 日数 | " + " | ".join(TIMES) + " |", "|---|---|" + "---|" * len(TIMES)]
        for y in range(2015, 2027):
            dd = days[sel & (days.year == y)]
            mat = []
            for d in dd:
                v = s.reindex([d + pd.Timedelta(hours=int(t[:2]), minutes=int(t[3:])) for t in TIMES]).values
                if np.isnan(v[TIMES.index("09:55")]) or np.isnan(v).sum() > 2:
                    continue
                mat.append((v - v[TIMES.index("09:55")]) / pip)
            if not mat:
                continue
            m = np.nanmean(np.array(mat), axis=0)
            out.append(f"| {y} | {len(mat)} | " + " | ".join(f"{x:+.1f}" for x in m) + " |")
        out.append("")
    text = "\n".join(out) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", f"gotobi_profile_{pair}.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "USDJPY")

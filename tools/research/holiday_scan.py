#!/usr/bin/env python3
"""祝日・連休・指標日など「暦の出来事」の日だけで、30分ごとの時間帯の偏りを調べる（full_scan と同じ厳しさ）。

日の条件（各時計の現地の日付で判定）：
- jp_pre_hol：日本の休業日（土日以外の祝日・年末年始）の前の営業日。連休前の実需（輸入企業のドル買いなど）を想定
- jp_post_hol：日本の祝日明けの営業日
- jp_long_pre：次の営業日まで3日以上空く日（金曜で月曜が祝日、など）
- us_hol：米国の祝日（市場が薄い）
- us_pre_hol：米国の祝日の前の営業日
- nfp：毎月最初の金曜日（米雇用統計の日）
設計期間で |t| ≥ 4、検証期間で PF ≥ 1.2・t ≥ 2。2024年11月〜の成績も表に出す（新しい条件なので、この期間はまだ見ていない期間として扱う）。

使い方: python3 tools/research/holiday_scan.py  → reports/research/full_scan_holiday.md
"""
import os
import sys

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
import full_scan as F  # noqa: E402

JP = S.load_jp_holidays()
US = set(USFederalHolidayCalendar().holidays("2010-01-01", "2028-12-31").strftime("%Y%m%d"))


def is_jp_bd(x):
    return x.dayofweek < 5 and x.strftime("%Y%m%d") not in JP


def next_bd(x, f):
    k = x + pd.Timedelta(days=1)
    while not f(k):
        k += pd.Timedelta(days=1)
    return k


def prev_bd(x, f):
    k = x - pd.Timedelta(days=1)
    while not f(k):
        k -= pd.Timedelta(days=1)
    return k


def is_us_bd(x):
    return x.dayofweek < 5 and x.strftime("%Y%m%d") not in US


def day_filters(df, clock):
    d = pd.DatetimeIndex(df[f"{clock}_date"]).normalize()
    days = pd.DatetimeIndex(sorted(set(d)))
    jp_pre, jp_post, jp_long, us_hol, us_pre, nfp = set(), set(), set(), set(), set(), set()
    for x in days:
        if x.dayofweek >= 5:
            continue
        s = x.strftime("%Y%m%d")
        if s in US:
            us_hol.add(x)
        if is_us_bd(x) and next_bd(x, lambda k: k.dayofweek < 5) .strftime("%Y%m%d") in US:
            us_pre.add(x)
        if x.dayofweek == 4 and x.day <= 7:
            nfp.add(x)
        if not is_jp_bd(x):
            continue
        n = next_bd(x, is_jp_bd)
        gap_hol = any((x + pd.Timedelta(days=i)).strftime("%Y%m%d") in JP for i in range(1, (n - x).days))
        if gap_hol:
            jp_pre.add(x)
        if (n - x).days >= 4 or ((n - x).days >= 3 and x.dayofweek != 4):
            jp_long.add(x)
        p = prev_bd(x, is_jp_bd)
        if any((p + pd.Timedelta(days=i)).strftime("%Y%m%d") in JP for i in range(1, (x - p).days)):
            jp_post.add(x)
    out = {}
    for name, st in (("jp_pre_hol", jp_pre), ("jp_post_hol", jp_post), ("jp_long_pre", jp_long),
                     ("us_hol", us_hol), ("us_pre_hol", us_pre), ("nfp", nfp)):
        out[name] = np.isin(d.values, np.array(sorted(st), dtype="datetime64[ns]"))
    return out


def main():
    S.day_filters = day_filters
    os.environ["AMS_TAG"] = "_holiday"
    F.main()
    res = pd.read_csv(os.path.join(D.ROOT, "reports", "research", "full_scan_holiday_all.csv"))
    if len(res):
        ok = res[(res.val_net > 0) & (res.val_pf >= 1.2) & (res.val_t >= 2.0)]
        print("\n2024年11月〜の成績（検証通過分）")
        for _, r in ok.iterrows():
            print(f"{r.pair} {r.clock} {r.time} {r.hold}分 {r['filter']} {r.dir}: 回数 {r.fin_n} 平均 {r.fin_net:+.2f} PF {r.fin_pf:.2f}")


if __name__ == "__main__":
    main()

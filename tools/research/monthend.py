#!/usr/bin/env python3
"""月末の株式ヘッジの調整（Melvin & Prins, Journal of Financial Markets 2015）を、自分のデータで確かめる。

論文の主張：その月に株価が上がった国の通貨ほど、月末のロンドン16時フィックス（WM/R）の前に安くなる。
（海外株を持つ投資家が、増えた外貨建て資産の為替ヘッジを月末に積み増すため）

ここでの検証：
- 月の最終営業日（ロンドンの日付）に、月初からの株価の伸び（米国 − 相手国）を計算する。
  - EURUSD：S&P500（SPXUSD）と DAX（GRXEUR）
  - GBPUSD：S&P500 と FTSE100（UKXGBP）
  - USDJPY：S&P500 と 日経平均（JPXJPY）
- 米国株が相手国より上がっていれば、米ドル売り（EURUSD・GBPUSD は買い、USDJPY は売り）。逆なら米ドル買い。
- 入る時刻：ロンドン 14:00 / 15:00、出る時刻：ロンドン 16:00（フィックス）。フィックス後の戻し（16:00→17:00 の逆向き）も見る。
- 株価の伸びは、入る時刻の直前の値で計算する（未来の値は使わない）。
- 設計期間で調べ、向きと条件を固定したまま検証期間で確かめる。最終確認期間は見ない。

使い方: python3 tools/research/monthend.py  → reports/research/monthend.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

PAIRS = {"EURUSD": ("GRXEUR", +1.0), "GBPUSD": ("UKXGBP", +1.0), "USDJPY": ("JPXJPY", -1.0)}
# 符号：米国株が相対的に上がった（米ドル売り）ときに、そのペアを買うなら +1、売るなら -1


def price_at(df, t):
    """t より前の最後の5分足の終値。"""
    i = df.index.searchsorted(t) - 1
    return df["c"].values[i] if i >= 0 else np.nan


def month_ends(idx):
    """各月の最終平日（ロンドンの日付）。"""
    days = pd.Series(pd.DatetimeIndex(idx.normalize().unique()))
    wd = days[days.dt.dayofweek < 5]
    return list(wd.groupby([wd.dt.year, wd.dt.month]).max())


def st(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 8:
        return f"{len(x)}回"
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    t = x.mean() / x.std(ddof=1) * np.sqrt(len(x)) if x.std(ddof=1) > 0 else 0.0
    return f"{len(x)}回 {x.mean():+.1f}pips PF {gp / gl if gl > 0 else 9.99:.2f} t {t:.1f}"


def main():
    spx = D.bars("SPXUSD", "5min")
    out = ["# 月末の株式ヘッジの調整（Melvin & Prins 2015）の確認", "",
           "米国株が相手国の株より上がった月は、米ドル売り（逆なら米ドル買い）。コスト後の pips。", ""]
    for pair, (eq, sgn) in PAIRS.items():
        fx = D.bars(pair, "5min")
        loc = D.bars(eq, "5min")
        pip = D.pip_size(pair)
        cost = S.COST[pair]
        ldn = fx.index.tz_localize("UTC").tz_convert("Europe/London")
        rows = []
        ends = month_ends(pd.DatetimeIndex(ldn.tz_localize(None)))
        prev_end = None
        for me in ends:
            if prev_end is None:
                prev_end = me
                continue
            rec = {"date": me}
            for hh in (14, 15):
                t_in = pd.Timestamp(me + pd.Timedelta(hours=hh)).tz_localize("Europe/London").tz_convert("UTC").tz_localize(None)
                t_base = pd.Timestamp(prev_end + pd.Timedelta(hours=hh)).tz_localize("Europe/London").tz_convert("UTC").tz_localize(None)
                r_us = np.log(price_at(spx, t_in) / price_at(spx, t_base))
                r_lc = np.log(price_at(loc, t_in) / price_at(loc, t_base))
                rec[f"rel{hh}"] = r_us - r_lc
                rec[f"us{hh}"] = r_us
                t_fix = pd.Timestamp(me + pd.Timedelta(hours=16)).tz_localize("Europe/London").tz_convert("UTC").tz_localize(None)
                o = fx["o"]
                p_in, p_fix = o.get(t_in, np.nan), o.get(t_fix, np.nan)
                rec[f"pre{hh}"] = (p_fix - p_in) / pip
            t_fix = pd.Timestamp(me + pd.Timedelta(hours=16)).tz_localize("Europe/London").tz_convert("UTC").tz_localize(None)
            t_out = t_fix + pd.Timedelta(hours=1)
            rec["post"] = (fx["o"].get(t_out, np.nan) - fx["o"].get(t_fix, np.nan)) / pip
            rows.append(rec)
            prev_end = me
        df = pd.DataFrame(rows).set_index("date")
        des = D.period_mask(df.index, D.DESIGN)
        val = D.period_mask(df.index, D.VALID)
        out += [f"## {pair}（相手国の株：{eq}）", "",
                "| 時間帯 | 使う株価の差 | 設計 | 検証 |", "|---|---|---|---|"]
        for hh in (14, 15):
            for key, lab in ((f"rel{hh}", "米国 − 相手国"), (f"us{hh}", "米国のみ")):
                side = sgn * np.sign(df[key].values)            # 米国株が上がった → 米ドル売りの向き
                pnl = side * df[f"pre{hh}"].values - cost
                out.append(f"| ロンドン {hh}:00→16:00 | {lab} | {st(pnl[des])} | {st(pnl[val])} |")
        for key, lab in (("rel15", "米国 − 相手国"),):
            side = -sgn * np.sign(df[key].values)               # フィックス後は逆向きに戻る、とみる
            pnl = side * df["post"].values - cost
            out.append(f"| ロンドン 16:00→17:00（戻し） | {lab} | {st(pnl[des])} | {st(pnl[val])} |")
        # 株価の差の大きさで分ける（境目は設計期間の中央値）
        thr = np.nanmedian(np.abs(df["rel15"].values[des]))
        big = np.abs(df["rel15"].values) > thr
        side = sgn * np.sign(df["rel15"].values)
        pnl = side * df["pre15"].values - cost
        out += [f"| ロンドン 15:00→16:00 | 差が大きい月だけ（> {thr * 100:.1f}%） | {st(pnl[des & big])} | {st(pnl[val & big])} |", ""]
        c = np.corrcoef(np.nan_to_num(df["rel15"].values[des]), np.nan_to_num(sgn * df["pre15"].values[des]))[0, 1]
        out += [f"- 設計期間の相関（株価の差 と フィックス前の動き）：{c:+.3f}", ""]
    text = "\n".join(out)
    open(os.path.join(D.ROOT, "reports", "research", "monthend.md"), "w", encoding="utf-8").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

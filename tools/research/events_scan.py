#!/usr/bin/env python3
"""時刻の偏り以外の「出来事」による値動きを調べる。

1. 週明けの窓（ギャップ）埋め
   - 窓：週明けの最初の足の始値 − 金曜の最後の足の終値（÷ 1時間足の平均値幅）
   - 月曜の東京 8:00 / 9:00 に、窓と逆向きに入り、2 / 4 / 8 時間後に決済（スプレッドが落ち着いてから入る）
   - 窓が大きい週だけ（|窓| が設計期間の上位 1/3）も見る
2. 米雇用統計（毎月第1金曜の NY 8:30。祝日などでずれる月は無視）
   - 発表後 5 / 15 分の動きの向きに、8:45 / 8:35 から入り、1 / 2 / 4 時間後に決済（続くか）
   - 逆向き（戻るか）も見る
3. 祝日の前後（日本・米国）
   - 日本の祝日の前の営業日と、後の営業日の、東京 9:00〜15:00 の値動き
   - 米国の主な祝日（独立記念日・感謝祭）の前の営業日の、NY 8:00〜12:00 の値動き
評価：設計期間で調べ、検証期間で確かめる。コスト後の pips。

使い方: python3 tools/research/events_scan.py  → reports/research/events_scan.md
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


def gap_fill(out):
    out += ["## 1. 週明けの窓埋め", "", "| ペア | 入る時刻 | 保有 | 対象 | 設計 | 検証 |", "|---|---|---|---|---|---|"]
    for pair in D.PAIRS:
        df = D.bars(pair, "5min")
        pip, cost = D.pip_size(pair), S.COST[pair]
        o = df["o"]
        gaps = np.diff(df.index.values).astype("timedelta64[h]").astype(float)
        first = df.index[1:][gaps >= 30]                      # 週明けの最初の足
        last_c = df["c"].values[:-1][gaps >= 30]
        h1 = D.bars(pair, "1h")
        rng = (h1["h"] - h1["l"]).rolling(24).mean().shift(1)
        a = rng.reindex(first.floor("1h"), method="ffill").values / pip
        gap = (df["o"].reindex(first).values - last_c) / pip
        z = gap / a
        for hh in (8, 9):
            # 週明け後の最初の東京 hh:00
            t_in = []
            for t in first:
                cand = df.index[(df.index >= t) & (df.index < t + pd.Timedelta(hours=30))]
                sub = cand[(df.loc[cand, "tky_h"].values == hh) & (df.loc[cand, "tky_m"].values == 0)]
                t_in.append(sub[0] if len(sub) else pd.NaT)
            t_in = pd.DatetimeIndex(t_in)
            des = D.period_mask(first, D.DESIGN)
            val = D.period_mask(first, D.VALID)
            big_thr = np.nanquantile(np.abs(z[des]), 2 / 3)
            for hold in (2, 4, 8):
                r = (o.reindex(t_in + pd.Timedelta(hours=hold)).values - o.reindex(t_in).values) / pip
                pnl = -np.sign(gap) * r - cost
                for lab, m in (("全部", np.ones(len(z), bool)), ("窓が大きい週", np.abs(z) > big_thr)):
                    out.append(f"| {pair} | 月曜 東京{hh}:00 | {hold}時間 | {lab} | {st(pnl[des & m])} | {st(pnl[val & m])} |")
    out.append("")


def nfp(out):
    out += ["## 2. 米雇用統計（第1金曜 NY 8:30）", "", "| ペア | 最初の動き | 保有 | 向き | 設計 | 検証 |", "|---|---|---|---|---|---|"]
    for pair in ("EURUSD", "USDJPY", "GBPUSD"):
        df = D.bars(pair, "5min")
        pip, cost = D.pip_size(pair), S.COST[pair]
        o = df["o"]
        t0 = df.index[(df["ny_h"].values == 8) & (df["ny_m"].values == 30)]
        d = pd.DatetimeIndex(df.loc[t0, "ny_date"])
        first_fri = (d.dayofweek == 4) & (d.day <= 7)
        t0 = t0[first_fri]
        des = D.period_mask(t0, D.DESIGN)
        val = D.period_mask(t0, D.VALID)
        for first in (5, 15):
            sig = np.sign(o.reindex(t0 + pd.Timedelta(minutes=first)).values - o.reindex(t0).values)
            for hold in (60, 120, 240):
                t_in = t0 + pd.Timedelta(minutes=first)
                r = (o.reindex(t_in + pd.Timedelta(minutes=hold)).values - o.reindex(t_in).values) / pip
                for lab, s in (("続く", 1.0), ("戻る", -1.0)):
                    pnl = s * sig * r - cost
                    out.append(f"| {pair} | {first}分 | {hold}分 | {lab} | {st(pnl[des])} | {st(pnl[val])} |")
    out.append("")


def holidays(out):
    out += ["## 3. 祝日の前後", "", "| ペア | 対象 | 時間帯 | 設計（買い） | 検証（買い） |", "|---|---|---|---|---|"]
    hol = S.load_jp_holidays()
    us = set()
    for y in range(2015, 2027):
        us.add(pd.Timestamp(f"{y}-07-04"))
        nov = pd.date_range(f"{y}-11-01", f"{y}-11-30")
        us.add(nov[nov.dayofweek == 3][3])                    # 感謝祭（11月第4木曜）
    for pair in D.PAIRS:
        df = D.bars(pair, "1h")
        pip, cost = D.pip_size(pair), S.COST[pair]
        o = df["o"]
        t9 = df.index[(df["tky_h"].values == 9)]
        d = pd.DatetimeIndex(df.loc[t9, "tky_date"])
        nxt = d + pd.offsets.BDay(1)
        prv = d - pd.offsets.BDay(1)
        before = np.array([n.strftime("%Y%m%d") in hol for n in nxt])
        after = np.array([p.strftime("%Y%m%d") in hol for p in prv])
        r = (o.reindex(t9 + pd.Timedelta(hours=6)).values - o.reindex(t9).values) / pip
        des, val = D.period_mask(t9, D.DESIGN), D.period_mask(t9, D.VALID)
        for lab, m in (("日本の祝日の前の営業日", before), ("日本の祝日の後の営業日", after)):
            out.append(f"| {pair} | {lab} | 東京 9〜15時 | {st(r[des & m] - cost)} | {st(r[val & m] - cost)} |")
        t8 = df.index[(df["ny_h"].values == 8)]
        dn = pd.DatetimeIndex(df.loc[t8, "ny_date"])
        bu = np.array([(x + pd.offsets.BDay(1)) in us for x in dn])
        r = (o.reindex(t8 + pd.Timedelta(hours=4)).values - o.reindex(t8).values) / pip
        des, val = D.period_mask(t8, D.DESIGN), D.period_mask(t8, D.VALID)
        out.append(f"| {pair} | 米国の祝日の前の営業日 | NY 8〜12時 | {st(r[des & bu] - cost)} | {st(r[val & bu] - cost)} |")
    out += ["", "- 買いの損益です。売りの場合は、符号を逆にしてコストを2倍引いた値になります。", ""]


def main():
    out = ["# 時刻以外の出来事による値動き（コスト後）", ""]
    gap_fill(out)
    nfp(out)
    holidays(out)
    text = "\n".join(out)
    open(os.path.join(D.ROOT, "reports", "research", "events_scan.md"), "w", encoding="utf-8").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

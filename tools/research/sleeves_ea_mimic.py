#!/usr/bin/env python3
"""確認：EA の方式 8（指数の層）の MT5 での結果が、研究（Python）と同じ計算になっているかを確かめるための「写し」。

- MT5 のテスター（仮の銘柄 US500_HD・US100_HD、tools/ci/backtest.ps1）と同じ条件を、Python でそのまま計算する：
  同じ1分足（histdata）、同じ日足の区切り（サーバーの日付 = NY 17:00 区切り）、同じルール（R2・D7・IBS）、
  新しい日足の最初の値段から5分後の値段で売買、スプレッド固定（S&P500 1.0・NASDAQ100 2.5 ポイント）、
  持ち越しのコスト 年率一定（-3.0%・-3.8%、360日で割り、金曜は3日分）、建玉は 0.01 lot 刻み（1 lot = 100 単位）、
  ルールの出入りがあったときだけ建玉を目標に合わせる（差が25%を超えたときも）。
- MT5 の結果（総損益・取引数・月ごとの損益）と比べて、ほぼ同じなら、EA は研究どおりに動いている。
使い方: python3 tools/research/sleeves_ea_mimic.py [開始日 終了日 初期資金 1つ分の値動き%]
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import index_reversion as IR  # noqa: E402
import index_reversion_cfd as IC  # noqa: E402

SYMS = {"US500_HD": ("SPXUSD", 1.0, -3.0), "US100_HD": ("NSXUSD", 2.5, -3.8)}       # histdata の銘柄, スプレッド, 買いの持ち越し（年 %）
CONTRACT, STEP, BAND, DELAY_MIN = 100.0, 0.01, 0.25, 5


def server_m1(pair):
    """1分足（サーバー時刻 = NY + 7時間）。"""
    m = IC.load_any(pair)
    ny = m.index.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    out = m.copy()
    out.index = ny + pd.Timedelta(hours=7)
    return out[~out.index.duplicated()].sort_index()


def prepare(pair):
    m = server_m1(pair)
    day = m.index.normalize()
    g = m.groupby(day)
    d = pd.DataFrame({"open": g["o"].first(), "high": g["h"].max(), "low": g["l"].min(), "close": g["c"].last()})
    first = pd.Series(m.index, index=m.index).groupby(day).first()
    # 売買の値段：その日の最初の足から5分後以降の、最初の足の始値
    want = first + pd.Timedelta(minutes=DELAY_MIN)
    pos = np.searchsorted(m.index.values, want.values, side="left")
    pos = np.minimum(pos, len(m) - 1)
    d["px"] = m["o"].values[pos]
    d["px_time"] = m.index.values[pos]
    d.loc[pd.DatetimeIndex(d["px_time"]).normalize() != d.index, "px"] = np.nan        # その日のうちに足がなければ、売買しない
    return d


def signals(d):
    """日足 d の各行について、「その日足が確定したあと」のルールの状態（R2・D7・IBS）。EA と同じ計算。"""
    return IR.rules(d)


def main():
    a = sys.argv[1:]
    start, end = (a[0], a[1]) if len(a) >= 2 else ("2011-09-01", "2026-10-30")
    deposit = float(a[2]) if len(a) >= 3 else 1e7
    unit = float(a[3]) if len(a) >= 4 else 1.667
    D, ST, VOL = {}, {}, {}
    for s, (pair, _, _) in SYMS.items():
        d = prepare(pair)
        D[s] = d
        r = signals(d)
        ST[s] = (r["R2<10"] + r["D7"] + r["IBS"])
        ST[s + "_chg"] = (r["R2<10"].diff().abs() + r["D7"].diff().abs() + r["IBS"].diff().abs()).fillna(0) > 0
        ret = d["close"].pct_change()
        VOL[s] = (ret.rolling(60).std() * np.sqrt(252)).clip(lower=0.025)
        n200 = d["close"].rolling(215).count() >= 215          # EA は確定した日足が215本以上になってから判定する
        ST[s] = ST[s].where(n200, 0.0)
    days = sorted(set().union(*[set(D[s].index) for s in SYMS]))
    days = [x for x in days if pd.Timestamp(start) <= x <= pd.Timestamp(end)]
    cash = deposit
    units = {s: 0.0 for s in SYMS}
    last_close = {s: np.nan for s in SYMS}
    trades = 0
    eq_days, eq_vals = [], []
    prev_day = None
    for day in days:
        # 日付の変わり目：前の日に持っていた建玉に、持ち越しのコスト（金曜は3日分）
        if prev_day is not None:
            mult = 3 if prev_day.dayofweek == 4 else 1
            for s, (_, _, swl) in SYMS.items():
                if units[s] > 0 and not np.isnan(last_close[s]):
                    cash += units[s] * last_close[s] * swl / 100.0 / 360.0 * mult
        for s, (_, spread, _) in SYMS.items():
            d = D[s]
            if day not in d.index:
                continue
            row = d.loc[day]
            i = d.index.get_loc(day)
            if i == 0 or np.isnan(row["px"]):
                continue
            prev = d.index[i - 1]                                  # 確定した最後の日足
            n = ST[s].loc[prev]
            chg = bool(ST[s + "_chg"].loc[prev]) if i >= 2 else True
            vol = VOL[s].loc[prev]
            if np.isnan(vol):
                continue
            bid = row["px"]
            # 口座の有効証拠金（すべての建玉を、今の値段で評価）
            eq = cash
            for q in SYMS:
                if units[q] > 0:
                    pq = D[q].loc[day, "px"] if day in D[q].index and not np.isnan(D[q].loc[day, "px"]) else last_close[q]
                    eq += units[q] * pq
            tgt = eq * n * unit / 100.0 / vol
            lots = np.floor(tgt / (bid * CONTRACT) / STEP + 1e-9) * STEP
            cur = units[s] / CONTRACT
            if lots <= 0:
                if cur > 0:
                    cash += units[s] * bid
                    units[s] = 0.0
                    trades += 1
            elif chg or abs(cur - lots) > BAND * max(cur, lots):
                if lots > cur:
                    cash -= (lots - cur) * CONTRACT * (bid + spread)
                    trades += 1
                elif cur > lots:
                    cash += (cur - lots) * CONTRACT * bid
                units[s] = lots * CONTRACT
        for s in SYMS:
            if day in D[s].index:
                last_close[s] = D[s].loc[day, "close"]
        eq_days.append(day)
        eq_vals.append(cash + sum(units[s] * last_close[s] for s in SYMS if units[s] > 0))
        prev_day = day
    eq = pd.Series(eq_vals, index=pd.DatetimeIndex(eq_days))
    m = eq.resample("ME").last()
    mret = (m / m.shift(1).fillna(deposit) - 1) * 100
    y = eq.resample("YE").last()
    yret = (y / y.shift(1).fillna(deposit) - 1) * 100
    dd = (eq / eq.cummax() - 1).min() * 100
    print(f"期間 {eq.index[0].date()}〜{eq.index[-1].date()}、初期資金 {deposit:,.0f} 円、ルール1つ分の値動き {unit}%")
    print(f"最終の有効証拠金 {eq.iloc[-1]:,.0f} 円（損益 {eq.iloc[-1] - deposit:+,.0f} 円、{(eq.iloc[-1] / deposit - 1) * 100:+.1f}%）、買いの注文 {trades} 回、最大の下落（日次の終値）{dd:.1f}%")
    print("年ごと（%）：" + "、".join(f"{k.year}年 {v:+.1f}" for k, v in yret.items()))
    print("MONTHLY " + ",".join(f"{k.strftime('%Y-%m')}:{v:.2f}" for k, v in mret.items()))


if __name__ == "__main__":
    main()

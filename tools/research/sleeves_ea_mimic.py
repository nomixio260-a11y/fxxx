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

ALL = {"US500_HD": ("SPXUSD", 1.0, -3.0), "US100_HD": ("NSXUSD", 2.5, -3.8), "XAU_HD": ("XAUUSD", 0.5, -4.4)}   # histdata の銘柄, スプレッド, 買いの持ち越し（年 %）
SYMS = {k: ALL[k] for k in ("US500_HD", "US100_HD")}
TREND_DAYS = 7
CONTRACT, STEP, BAND, DELAY_MIN = 100.0, 0.01, 0.25, 5
# OANDA の株価指数 CFD の条件で計算するとき（環境変数 AMS_OANDA=1）：1 lot = 指数 × 1ドル、最小の取引単位と刻みは銘柄ごと、
# スプレッドは S&P500 0.6・NASDAQ100 2.5 ポイント、買いの持ち越しは 年 -4.79%（実行624 で確かめた値）。円への換算は、その日の USDJPY。
OANDA = os.environ.get("AMS_OANDA") == "1"
LOTS = {"US500_HD": (1.0, 0.01), "US100_HD": (0.1, 0.1)}        # 最小の取引単位, 刻み
if OANDA:
    ALL = {"US500_HD": ("SPXUSD", 0.6, -4.79), "US100_HD": ("NSXUSD", 2.5, -4.79), "XAU_HD": ("XAUUSD", 0.5, -4.4)}


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
    """引数：開始日 終了日 初期資金 戻りの1つ分の値動き% 順張りの1銘柄の値動き% 銘柄（カンマ区切り）"""
    global SYMS
    a = sys.argv[1:]
    start, end = (a[0], a[1]) if len(a) >= 2 else ("2011-09-01", "2026-10-30")
    deposit = float(a[2]) if len(a) >= 3 else 1e7
    unit = float(a[3]) if len(a) >= 4 else 1.667
    tunit = float(a[4]) if len(a) >= 5 else 0.0
    if len(a) >= 6:
        SYMS = {k: ALL[k] for k in a[5].split(",")}
    D, ST, CHG, VOL, ABOVE, OK = {}, {}, {}, {}, {}, {}
    for s, (pair, _, _) in SYMS.items():
        d = prepare(pair)
        D[s] = d
        r = signals(d)
        ST[s] = (r["R2<10"] + r["D7"] + r["IBS"]) if unit > 0 else r["IBS"] * 0.0
        ret = d["close"].pct_change()
        VOL[s] = (ret.rolling(60).std() * np.sqrt(252)).clip(lower=0.025)
        ABOVE[s] = (d["close"] > d["close"].rolling(200).mean()).astype(float)
        OK[s] = d["close"].rolling(215).count() >= 215          # EA は、確定した日足が215本以上になってから判定する
    if OANDA:
        import fred_data as F
        uj = F.fetch("DEXJPUS").dropna()
    days = sorted(set().union(*[set(D[s].index) for s in SYMS]))
    if OANDA:
        uj = uj.reindex(uj.index.union(days)).ffill().reindex(days)
    worst_day = 0.0
    days = [x for x in days if pd.Timestamp(start) <= x <= pd.Timestamp(end)]
    cash = deposit
    units = {s: 0.0 for s in SYMS}
    last_close = {s: np.nan for s in SYMS}
    prev_n = {s: 0.0 for s in SYMS}
    trend = {s: 0.0 for s in SYMS}
    trend_check = {s: None for s in SYMS}
    started = {s: False for s in SYMS}
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
            if not OK[s].loc[prev] or np.isnan(VOL[s].loc[prev]):
                continue
            n = ST[s].loc[prev]
            chg = (n != prev_n[s]) or not started[s]
            # 同じ数でも、中身が入れ替わった日（あるルールが出て、別のルールが入った日）は、EA も建玉を直す。ここでは数の変化だけを見る
            prev_n[s] = n
            if tunit > 0 and (trend_check[s] is None or (prev - trend_check[s]).days >= TREND_DAYS):
                trend_check[s] = prev
                st = ABOVE[s].loc[prev]
                if st != trend[s]:
                    trend[s] = st
                    chg = True
            started[s] = True
            vol = VOL[s].loc[prev]
            bid = row["px"]
            eq = cash
            for q in SYMS:
                if units[q] > 0:
                    pq = D[q].loc[day, "px"] if day in D[q].index and not np.isnan(D[q].loc[day, "px"]) else last_close[q]
                    eq += units[q] * pq
            tgt = eq * (n * unit + trend[s] * tunit) / 100.0 / vol
            if OANDA:
                CONTRACT_ = float(uj.loc[day])                     # 1 lot = 指数 × 1ドル → 円では 指数 × USDJPY
                mn, st = LOTS.get(s, (0.01, 0.01))
                lots = np.floor(tgt / (bid * CONTRACT_) / st + 1e-9) * st
                if lots < mn:
                    lots = 0.0
            else:
                CONTRACT_ = CONTRACT
                lots = np.floor(tgt / (bid * CONTRACT_) / STEP + 1e-9) * STEP
            cur = units[s] / CONTRACT_
            if lots <= 0:
                if cur > 0:
                    cash += units[s] * bid
                    units[s] = 0.0
            elif chg or abs(cur - lots) > BAND * max(cur, lots):
                if lots > cur:
                    cash -= (lots - cur) * CONTRACT_ * (bid + spread)
                    trades += 1
                elif cur > lots:
                    cash += (cur - lots) * CONTRACT_ * bid
                units[s] = lots * CONTRACT_
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
    dr = eq.pct_change().dropna()
    print(f"銘柄 {','.join(SYMS)}、期間 {eq.index[0].date()}〜{eq.index[-1].date()}、初期資金 {deposit:,.0f} 円、戻り {unit}%・順張り {tunit}%")
    print(f"最終の有効証拠金 {eq.iloc[-1]:,.0f} 円（損益 {eq.iloc[-1] - deposit:+,.0f} 円、{(eq.iloc[-1] / deposit - 1) * 100:+.1f}%）、買いの注文 {trades} 回、"
          f"最大の下落（日次の終値）{dd:.1f}%、年率シャープ {dr.mean() / dr.std() * np.sqrt(252):+.2f}、値動き 年{dr.std() * np.sqrt(252) * 100:.1f}%")
    print("年ごと（%）：" + "、".join(f"{k.year}年 {v:+.1f}" for k, v in yret.items()))
    print(f"最悪の日 {dr.min() * 100:+.1f}%（{dr.idxmin().date()}）、最悪の月 {mret.min():+.1f}%（{mret.idxmin().strftime('%Y-%m')}）、最悪の年 {yret.min():+.1f}%")
    print("MONTHLY " + ",".join(f"{k.strftime('%Y-%m')}:{v:.2f}" for k, v in mret.items()))


if __name__ == "__main__":
    main()

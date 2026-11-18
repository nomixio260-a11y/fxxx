#!/usr/bin/env python3
"""金利差＋トレンド（82章）の改良（時刻・曜日・日付は使わない）。

- 対象を広げる：17ペア（histdata）に、OANDA から書き出した G10 のクロス（EURAUD など）と新興国（MXNJPY・ZARJPY・USDMXN・USDZAR）を加える。
  新興国の金利は年平均の目安（2025〜26年はおおよそ）。業者の上乗せは G10 年1%、新興国 年2%（払う側に寄せる）。
- 改良の候補：値動きの大きさに合わせて全体の建玉を調整（目標の年率ボラティリティ）、急変の回避（直近10日の値動きが120日の2倍を超えたペアは持たない）、
  金利差の効率（金利差 ÷ 値動きの大きさ）の上位だけを持つ、トレンドの測り方（60日の上げ幅 / 移動平均の向き）。
- 設定は 21年11月〜24年10月（選ぶ期間）だけで選び、24年11月〜25年10月・25年11月〜26年10月は答え合わせにだけ使う。
- 比べる物差し：年率シャープ（建玉の倍率に関係しない）と、年率ボラティリティを 10% にそろえたときの年率・最大の下落。
使い方: python3 tools/research/carry_trend.py  → reports/research/carry_trend.md
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
import daily_strats as DS  # noqa: E402
from multiday_scan import RATES  # noqa: E402

EXTRA_RATES = {
    "MXN": {2015: 3.0, 2016: 4.5, 2017: 7.0, 2018: 7.8, 2019: 8.0, 2020: 5.0, 2021: 4.6, 2022: 8.5, 2023: 11.2, 2024: 10.8, 2025: 8.6, 2026: 7.2},
    "ZAR": {2015: 6.0, 2016: 7.0, 2017: 6.9, 2018: 6.6, 2019: 6.6, 2020: 4.0, 2021: 3.6, 2022: 5.3, 2023: 8.0, 2024: 8.1, 2025: 7.3, 2026: 6.9},
}
ALL_RATES = {**RATES, **EXTRA_RATES}
EM = {"MXN", "ZAR"}
OANDA_PAIRS = ["EURAUD", "EURCAD", "EURNZD", "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD", "AUDCHF", "CADCHF", "NZDCHF",
               "MXNJPY", "ZARJPY", "USDMXN", "USDZAR"]
PER = (("選ぶ期間 21/11〜24/10", "2021-11-01", "2024-11-01"), ("答え合わせ 24/11〜25/10", "2024-11-01", "2025-11-01"),
       ("答え合わせ 25/11〜26/10", "2025-11-01", "2026-11-14"))


def load_universe(extended):
    px = DS.daily_prices()
    cost = {p: (S.COST.get(p, 2.0) + 0.5) * D.pip_size(p) for p in DS.PAIRS}
    if extended:
        for p in OANDA_PAIRS:
            f = os.path.join(D.CACHE, f"oanda_{p}_M30.parquet")
            if not os.path.exists(f):
                continue
            d = pd.read_parquet(f)
            s = d.loc[d["ny_h"].values == 17, "o"]
            s.index = pd.DatetimeIndex(s.index).normalize()
            s = s[~s.index.duplicated()]
            px[p] = s.reindex(px.index)
            # 価格の小数点以下の桁数から、1ポイントの大きさを決める（銘柄によって 3桁・5桁などが違う）
            dec = d["o"].tail(2000).map(lambda v: len(f"{v:.6f}".rstrip("0").split(".")[1]) if "." in f"{v:.6f}".rstrip("0") else 0)
            point = 10.0 ** -int(dec.max())
            cost[p] = 2.0 * float(d["spread_pt"].median()) * point      # 中央値のスプレッドの2倍（ずれも見込む）
    px = px.ffill(limit=2)
    cost_frac = pd.DataFrame({p: cost[p] / px[p] for p in px.columns})
    return px, cost_frac


def carry_table(px):
    yrs = px.index.year
    c, mk = {}, {}
    for p in px.columns:
        b, q = p[:3], p[3:]
        c[p] = np.array([ALL_RATES[b].get(y, ALL_RATES[b][2026]) - ALL_RATES[q].get(y, ALL_RATES[q][2026]) for y in yrs])
        mk[p] = 2.0 if (b in EM or q in EM) else 1.0
    return pd.DataFrame(c, index=px.index), pd.Series(mk)


def run(px, cost_frac, carry, markup, L=60, thr=1.0, rb=5, trend="ret", crash=None, topk=None, voltarget=None):
    ret = px.pct_change().shift(-1)
    r_past = px.pct_change()
    vol = r_past.rolling(60, min_periods=40).std()
    net_carry = carry.abs() - markup                       # 上乗せを引いた、受け取れる金利差（年 %）
    sig = np.sign(carry).where(net_carry >= thr, 0.0)
    if trend == "ret":
        tr = np.sign(px / px.shift(L) - 1.0)
    else:
        tr = np.sign(px.ewm(span=L // 3).mean() - px.ewm(span=L).mean())
    sig = sig.where(np.sign(sig) == tr, 0.0)
    if crash:
        v10 = r_past.rolling(10, min_periods=8).std()
        v120 = r_past.rolling(120, min_periods=80).std()
        sig = sig.where(v10 <= crash * v120, 0.0)
    w = sig / vol
    if topk:
        score = (net_carry / 100.0 / 261.0 / vol).where(sig != 0)
        rk = score.rank(axis=1, ascending=False)
        w = w.where(rk <= topk, 0.0)
    w = w.fillna(0.0)
    keep = np.zeros(len(w), bool)
    keep[::rb] = True
    w = w.where(pd.Series(keep, index=w.index), np.nan).ffill().fillna(0.0)
    g = w.abs().sum(axis=1).replace(0, np.nan)
    w = w.div(g, axis=0).fillna(0.0)
    pnl = (w * ret).sum(axis=1) + (w * (carry - np.sign(w) * markup) / 100.0 / 261.0).sum(axis=1)
    tc = ((w - w.shift(1).fillna(0.0)).abs() * cost_frac.fillna(0.01)).sum(axis=1)
    tot = pnl - tc
    if voltarget:
        rv = tot.rolling(60, min_periods=40).std().shift(1) * np.sqrt(261)
        scale = (voltarget / rv).clip(0, 3.0).fillna(1.0)
        tot = tot * scale
    return tot


def describe(tot, label):
    cells = []
    for _, a, b in PER:
        x = tot[(tot.index >= a) & (tot.index < b)]
        sh = x.mean() / x.std() * np.sqrt(261) if x.std() > 0 else 0
        cells.append(f"{sh:+.2f}")
    x = tot[tot.index >= "2021-11-01"]
    k = 0.10 / (x.std() * np.sqrt(261))                   # 年率ボラティリティ 10% にそろえる
    eq = (1 + k * x).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    yrs = (x.index[-1] - x.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    mo = (k * x).groupby(x.index.to_period("M")).sum()
    return f"| {label} | " + " | ".join(cells) + f" | {cagr * 100:+.1f}% | {dd * 100:.0f}% | {(mo < 0).sum()}/{len(mo)} | {k:.1f}倍 |"


def main():
    head = ["# 金利差＋トレンドの改良（`tools/research/carry_trend.py`）", "",
            "年率シャープ（期間ごと）と、21年11月〜26年10月を年率ボラティリティ 10% にそろえたときの年率・最大の下落・マイナスの月・必要な建玉の倍率（合計）。",
            "設定は「選ぶ期間」だけで選ぶ。答え合わせの2期間は、選んだあとに見るだけ。", "",
            "| 形 | " + " | ".join(p[0] for p in PER) + " | 年率（ボラ10%） | 最大の下落 | マイナスの月 | 建玉 |",
            "|---|" + "---|" * (len(PER) + 4)]
    lines = list(head)
    for ext in (False, True):
        px, cf = load_universe(ext)
        carry, mk = carry_table(px)
        markup = pd.DataFrame({p: mk[p] for p in px.columns}, index=px.index)
        tag = "広げた対象" if ext else "17ペア"
        for L in (60, 90):
            for thr in (0.5, 1.0, 2.0):
                lines.append(describe(run(px, cf, carry, markup, L=L, thr=thr - 1.0 if False else thr), f"{tag} トレンド{L}日 金利差≥{thr}%（上乗せ後）"))
        lines.append(describe(run(px, cf, carry, markup, L=60, thr=1.0, trend="ema"), f"{tag} 移動平均の向き（60日） 金利差≥1%"))
        lines.append(describe(run(px, cf, carry, markup, L=60, thr=1.0, crash=2.0), f"{tag} トレンド60日 金利差≥1% 急変の回避"))
        lines.append(describe(run(px, cf, carry, markup, L=60, thr=1.0, voltarget=0.10), f"{tag} トレンド60日 金利差≥1% 値動きに合わせて調整"))
        lines.append(describe(run(px, cf, carry, markup, L=60, thr=1.0, crash=2.0, voltarget=0.10), f"{tag} トレンド60日 金利差≥1% 急変の回避＋調整"))
        for k in (3, 5):
            lines.append(describe(run(px, cf, carry, markup, L=60, thr=1.0, topk=k), f"{tag} トレンド60日 効率の上位{k}つ"))
            lines.append(describe(run(px, cf, carry, markup, L=60, thr=1.0, topk=k, crash=2.0, voltarget=0.10), f"{tag} トレンド60日 効率の上位{k}つ＋急変の回避＋調整"))
        print(tag, "done", flush=True)
    out = os.path.join(DS.ROOT, "reports", "research", "carry_trend.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

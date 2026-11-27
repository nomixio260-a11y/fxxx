#!/usr/bin/env python3
"""研究：為替以外（株価指数）に、日付・時刻を使わない数学的な優位性があるか（長い期間の日次データ、CFD のコスト込み）。

- データ：FRED の日次の株価指数（NASDAQ100：1986年〜、日経225：1986年〜で使用、S&P500・ダウ：2016年〜）と短期金利。
- CFD のコスト（業者で買い建てを持つ場合の実際の負担に近い形）：
  買い：毎日、（短期金利 + 上乗せ 年2.5%）を払い、配当（年率の目安）を受け取る。売り：（短期金利 − 上乗せ）を受け取り、配当を払う。
  売買のたびにスプレッド 0.03%。
- 形：
  A ずっと買い持ち（株式の値上がりそのもの）
  B 終値が200日の平均より上のときだけ買い持ち（週1回見直し）
  C 過去250日の向きに、買いまたは売り（週1回見直し）
- どれも、前日までの自分の値動きから年率10%にそろえる。判定は終値、売買は次の日。
- 物差し：期間ごとの年率シャープ、全体の t 値、1年で負ける確率（Φ(−シャープ)）。
使い方: python3 tools/research/multi_asset.py  → reports/research/multi_asset.md
"""
import os
import sys
from math import erf, sqrt

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import fred_data as F  # noqa: E402
import styles_long as SL  # noqa: E402

PER = (("1986〜1999", "1986-01-01", "2000-01-01"), ("2000〜2007", "2000-01-01", "2008-01-01"), ("2008〜2014", "2008-01-01", "2015-01-01"),
       ("2015〜21/10", "2015-01-01", "2021-11-01"), ("21/11〜24/10", "2021-11-01", "2024-11-01"),
       ("24/11〜25/10", "2024-11-01", "2025-11-01"), ("25/11〜26/11", "2025-11-01", "2026-12-01"))
MARKUP, SPREAD, ANN = 2.5, 0.0003, 261
ASSETS = {"NASDAQ100": ("NASDAQ100", "USD", 0.9), "日経225": ("NIKKEI225", "JPY", 1.7),
          "S&P500": ("SP500", "USD", 1.5), "ダウ": ("DJIA", "USD", 1.9)}


def Phi(x):
    return 0.5 * (1 + erf(x / sqrt(2)))


def short_rate(ccy, index):
    if ccy == "USD":
        s = F.fetch("DTB3").dropna()
        return s.reindex(s.index.union(index)).ffill().reindex(index)
    m = F.fetch("IR3TIB01JPM156N").dropna()
    old = pd.Series({pd.Timestamp("1986-01-01"): 6.0, pd.Timestamp("1988-01-01"): 4.0, pd.Timestamp("1990-01-01"): 7.0,
                     pd.Timestamp("1992-01-01"): 4.5, pd.Timestamp("1994-01-01"): 2.2, pd.Timestamp("1996-01-01"): 0.6,
                     pd.Timestamp("1999-01-01"): 0.2})          # 2002年より前の日本の短期金利（おおよその水準）
    m = pd.concat([old, m]).sort_index()
    return m.reindex(m.index.union(index)).ffill().reindex(index)


def pnl(pos, px, rate, div):
    """pos（-1/0/+1、終値で判定）を次の日から持つ。CFD の金利・配当・スプレッド込みの日次の損益。
    建玉の大きさは、その指数の直近60日の値動きから、年率10%になるようにする（前日までの値だけを使う。上限4倍）。"""
    vol = px.pct_change().rolling(60, min_periods=40).std() * np.sqrt(ANN)
    w = (pos * (0.10 / vol).clip(upper=4.0)).shift(1).fillna(0.0)
    ret = px.pct_change().fillna(0.0)
    fin_long = (div - rate - MARKUP) / 100.0 / ANN
    fin_short = (rate - MARKUP - div) / 100.0 / ANN
    carry = np.where(w > 0, w * fin_long, np.where(w < 0, -w * fin_short, 0.0))
    tc = (w - w.shift(1).fillna(0.0)).abs() * SPREAD
    return w * ret + carry - tc


def weekly(sig):
    keep = np.zeros(len(sig), bool)
    keep[::5] = True
    return sig.where(pd.Series(keep, index=sig.index), np.nan).ffill().fillna(0.0)


def stats(label, r, start):
    r = r[r.index >= start]
    cells = []
    for _, a, b in PER:
        x = r[(r.index >= a) & (r.index < b)]
        s = SL.sharpe(x)
        cells.append("—" if np.isnan(s) or x.abs().sum() == 0 else f"{s:+.2f}")
    sr = SL.sharpe(r)
    T = len(r) / ANN
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    return f"| {label} | " + " | ".join(cells) + f" | {sr:+.2f} | {sr * np.sqrt(T):+.1f} | {Phi(-sr) * 100:.0f}% | {dd * 100:.0f}% |"


def main():
    lines = ["# 研究：株価指数に、日付・時刻を使わない優位性があるか（`tools/research/multi_asset.py`）", "",
             "CFD のコスト込み（買いは 短期金利＋年2.5% を払い配当を受け取る、スプレッド 0.03%）。建玉は、各指数の値動きが年10%になる大きさ。年率シャープ。",
             "右の4列：全体のシャープ、t 値、1年で負ける確率、最大の下落。", "",
             "| 形 | " + " | ".join(p[0] for p in PER) + " | 全体 | t 値 | 負ける年 | 最大の下落 |", "|---|" + "---|" * (len(PER) + 4)]
    R = {}
    for name, (sid, ccy, div) in ASSETS.items():
        px = F.fetch(sid).dropna()
        px = px[px.index >= "1985-01-01"]
        rate = short_rate(ccy, px.index)
        start = "1986-01-01" if len(px) > 5000 else str(px.index[260].date())
        one = pd.Series(1.0, index=px.index)
        ma = (px > px.rolling(200).mean()).astype(float)
        ts = np.sign(px / px.shift(250) - 1.0).fillna(0.0)
        for key, lab, pos in (("A", "ずっと買い持ち", one), ("B", "200日の平均より上のときだけ買い", weekly(ma)), ("C", "過去250日の向きに買い・売り", weekly(ts))):
            r = pnl(pos, px, rate, div)
            R[(name, key)] = r
            lines.append(stats(f"{name}：{lab}", r, start))
    # 組み合わせ（NASDAQ100 と 日経225、1986年〜）
    for key, lab in (("A", "ずっと買い持ち"), ("B", "200日の平均より上のときだけ買い")):
        r = pd.concat([R[("NASDAQ100", key)], R[("日経225", key)]], axis=1).fillna(0.0).mean(axis=1)
        R[("combo", key)] = r
        lines.append(stats(f"NASDAQ100 と 日経225 を半分ずつ：{lab}", r, "1986-01-01"))
    # 為替の金利差の層との組み合わせ（2000年〜）
    cr = pd.read_parquet(os.path.join(D.CACHE, "carry_long_returns.parquet"))["C60+"]
    eqb = R[("combo", "B")]
    idx = cr.index.union(eqb.index)
    both = pd.concat([cr.reindex(idx).fillna(0.0), eqb.reindex(idx).fillna(0.0)], axis=1)
    both = both[both.index >= "2000-01-01"]
    lines += ["", f"為替の金利差の層（今の EA の形）と、株価指数の B（半分ずつ）の相関（2000年以降、日次）：{both.iloc[:, 0].corr(both.iloc[:, 1]):+.2f}", "",
              "| 形 | " + " | ".join(p[0] for p in PER) + " | 全体 | t 値 | 負ける年 | 最大の下落 |", "|---|" + "---|" * (len(PER) + 4)]
    lines.append(stats("為替の金利差の層だけ", both.iloc[:, 0], "2000-01-01"))
    lines.append(stats("株価指数の B だけ", both.iloc[:, 1], "2000-01-01"))
    lines.append(stats("為替の金利差 と 株価指数の B（半分ずつ）", both.mean(axis=1), "2000-01-01"))
    cra = pd.read_parquet(os.path.join(D.CACHE, "carry_long_returns.parquet"))["A1"]
    eqa = R[("combo", "A")]
    both2 = pd.concat([cra.reindex(idx).fillna(0.0), eqa.reindex(idx).fillna(0.0)], axis=1)
    both2 = both2[both2.index >= "2000-01-01"]
    lines.append(stats("株価指数の A（ずっと買い持ち）だけ", both2.iloc[:, 1], "2000-01-01"))
    lines.append(stats("為替の金利差（すべてのペア）と 株価指数の A（半分ずつ）", both2.mean(axis=1), "2000-01-01"))
    # 金（histdata の XAUUSD の1分足から作った日足、2009年〜。CFD：買いは 短期金利＋年2.5% を払う。配当はない）
    gpath = os.path.join(F.ROOT, "data", "XAUUSD_M1_2009.csv")
    if os.path.exists(gpath):
        g = pd.read_csv(gpath, header=None, usecols=[0, 5], names=["d", "c"])
        gp = g.groupby("d")["c"].last()
        gp.index = pd.to_datetime(gp.index, format="%Y.%m.%d")
        gp = gp[gp.index.dayofweek < 5]
        rate = short_rate("USD", gp.index)
        one = pd.Series(1.0, index=gp.index)
        ma = (gp > gp.rolling(200).mean()).astype(float)
        ts = np.sign(gp / gp.shift(250) - 1.0).fillna(0.0)
        gstart = str(gp.index[260].date())
        lines += ["", f"## 金（XAUUSD、{gp.index[0].date()}〜{gp.index[-1].date()}）", "",
                  "| 形 | " + " | ".join(p[0] for p in PER) + " | 全体 | t 値 | 負ける年 | 最大の下落 |", "|---|" + "---|" * (len(PER) + 4)]
        for key, lab, pos in (("A", "ずっと買い持ち", one), ("B", "200日の平均より上のときだけ買い", weekly(ma)), ("C", "過去250日の向きに買い・売り", weekly(ts))):
            r = pnl(pos, gp, rate, 0.0)
            R[("金", key)] = r
            lines.append(stats(f"金：{lab}", r, gstart))
        # 3つの層（為替の金利差・株価指数・金）を同じ重みで（2010年〜）
        gb = R[("金", "B")]
        idx3 = idx.union(gb.index)
        three = pd.concat([cr.reindex(idx3).fillna(0.0), eqb.reindex(idx3).fillna(0.0), gb.reindex(idx3).fillna(0.0)], axis=1)
        three = three[three.index >= gstart]
        three.columns = ["為替の金利差", "株価指数", "金"]
        c3 = three.corr().round(2)
        lines += ["", f"3つの層の相関（{gstart}〜、日次）：為替の金利差と株価指数 {c3.iloc[0, 1]:+.2f}、為替の金利差と金 {c3.iloc[0, 2]:+.2f}、株価指数と金 {c3.iloc[1, 2]:+.2f}", "",
                  "| 形 | " + " | ".join(p[0] for p in PER) + " | 全体 | t 値 | 負ける年 | 最大の下落 |", "|---|" + "---|" * (len(PER) + 4)]
        for c in three.columns:
            lines.append(stats(f"{c}の層だけ（{gstart[:4]}年〜）", three[c], gstart))
        lines.append(stats("為替の金利差と株価指数（半分ずつ）", three.iloc[:, :2].mean(axis=1), gstart))
        lines.append(stats("3つの層を同じ重みで", three.mean(axis=1), gstart))
    out = os.path.join(F.ROOT, "reports", "research", "multi_asset.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""長期の層：27年分（1999〜2026年）の日次データで、為替の代表的な手法を同じ物差しで比べる（日付・時刻のクセは使わない）。

- データ：FRED の日次の為替と月次の短期金利（tools/research/fred_data.py）。取引する17ペア。
- コスト：建玉を変えるたびにスプレッド（S.COST + 0.5 pips）。持っているあいだは、金利差 − 業者の上乗せ（年1%、払う側に寄せる）。
- 重み：値動きの大きさ（直近60日）で割ってそろえ、合計を1にする。全体は、直近60日の自分の値動きから年率10%にそろえる（前日までの値だけを使う）。
- 手法：
  金利差（金利の高い側を持つ）／トレンド（過去 L 日の向き）／金利差＋トレンド（今の EA の形）／
  割安・割高（5年前の水準に比べて上がりすぎた通貨を売る。購買力平価の考え方の簡易版）／それらの組み合わせ（リスクを等しく配分）。
- 期間ごとの年率シャープ（リスクあたりの利益。建玉の倍率に関係しない）で比べる。
使い方: python3 tools/research/styles_long.py  → reports/research/styles_long.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
import fred_data as F  # noqa: E402

ROOT = F.ROOT
PER = (("1999〜2007", "1999-01-01", "2008-01-01"), ("2008〜2014", "2008-01-01", "2015-01-01"),
       ("2015〜21/10", "2015-01-01", "2021-11-01"), ("21/11〜24/10", "2021-11-01", "2024-11-01"),
       ("24/11〜25/10", "2024-11-01", "2025-11-01"), ("25/11〜26/11", "2025-11-01", "2026-12-01"))
MARKUP = 1.0
ANN = 261


def load():
    px = F.prices()
    carry = F.carry_daily(px.index)
    cost = pd.DataFrame({p: (S.COST.get(p, 2.0) + 0.5) * D.pip_size(p) / px[p] for p in px.columns})
    return px, carry, cost


def hold(w, rb):
    """rb 営業日ごとにだけ入れ替える。"""
    w = w.fillna(0.0)
    if rb <= 1:
        return w
    keep = np.zeros(len(w), bool)
    keep[::rb] = True
    return w.where(pd.Series(keep, index=w.index), np.nan).ffill().fillna(0.0)


def norm(w):
    g = w.abs().sum(axis=1).replace(0, np.nan)
    return w.div(g, axis=0).fillna(0.0)


def pnl(w, px, carry, cost):
    """その日の終わりに決めた建玉 w で、翌日の値動きを受ける。コストとスワップ込みの日次の損益（建玉の合計1あたり）。"""
    ret = px.pct_change().shift(-1)
    gross = (w * ret).sum(axis=1) + (w * (carry - np.sign(w) * MARKUP) / 100.0 / ANN).sum(axis=1)
    tc = ((w - w.shift(1).fillna(0.0)).abs() * cost).sum(axis=1)
    return (gross - tc).fillna(0.0)


def voltarget(r, target=0.10, cap=4.0):
    rv = r.rolling(60, min_periods=40).std().shift(1) * np.sqrt(ANN)
    return r * (target / rv).clip(0, cap).fillna(0.0)


def sharpe(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 50 and x.std() > 0 else np.nan


def row(label, r):
    cells = []
    for _, a, b in PER:
        x = r[(r.index >= a) & (r.index < b)]
        s = sharpe(x)
        cells.append("—" if np.isnan(s) else f"{s:+.2f}")
    x = r[r.index >= "2000-01-01"]
    eq = (1 + x).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    yr = x.groupby(x.index.year).sum()
    return (f"| {label} | " + " | ".join(cells) + f" | {sharpe(x):+.2f} | {x.mean() * ANN * 100:+.1f}% | {dd * 100:.0f}% | "
            f"{(yr > 0).sum()}/{len(yr)} |")


# ---- 手法 ----
def s_carry(px, carry, thr=1.0):
    vol = px.pct_change().rolling(60, min_periods=40).std()
    sig = np.sign(carry).where(carry.abs() - MARKUP >= thr, 0.0)
    return norm(sig / vol)


def s_trend(px, L):
    vol = px.pct_change().rolling(60, min_periods=40).std()
    return norm(np.sign(px / px.shift(L) - 1.0) / vol)


def s_carry_trend(px, carry, L=60, thr=1.0, topk=5, crash=2.0):
    r = px.pct_change()
    vol = r.rolling(60, min_periods=40).std()
    net = carry.abs() - MARKUP
    sig = np.sign(carry).where(net >= thr, 0.0)
    sig = sig.where(np.sign(sig) == np.sign(px / px.shift(L) - 1.0), 0.0)
    if crash:
        sig = sig.where(r.rolling(10, min_periods=8).std() <= crash * r.rolling(120, min_periods=80).std(), 0.0)
    w = sig / vol
    if topk:
        score = (net / vol).where(sig != 0)
        w = w.where(score.rank(axis=1, ascending=False) <= topk, 0.0)
    return norm(w.fillna(0.0))


def s_value(px, years=5.0, band=0.0):
    """5年前（前後半年の平均）の水準に比べて上がりすぎたペアを売り、下がりすぎたペアを買う。"""
    lp = np.log(px)
    n = int(years * ANN)
    ref = lp.rolling(ANN, min_periods=200).mean().shift(n - ANN // 2)
    dev = lp - ref
    vol = px.pct_change().rolling(60, min_periods=40).std()
    z = dev / (vol * np.sqrt(n))
    sig = -np.sign(z).where(z.abs() >= band, 0.0)
    return norm(sig / vol)


def main():
    px, carry, cost = load()
    lines = ["# 長期の層：27年分のデータでの手法の比較（`tools/research/styles_long.py`）", "",
             f"データ：FRED の日次の為替（{px.index[0].date()}〜{px.index[-1].date()}）と月次の短期金利。17ペア、コストとスワップ（上乗せ 年1%）込み。",
             "各セル：年率シャープ（リスクあたりの利益。0.5 で「まずまず」、1.0 で「良い」）。右の4列は 2000年以降の全体：シャープ、年率（値動きを年10%にそろえたとき）、最大の下落、プラスの年。", "",
             "| 手法 | " + " | ".join(p[0] for p in PER) + " | 全体 | 年率 | 最大の下落 | プラスの年 |",
             "|---|" + "---|" * (len(PER) + 4)]
    R = {}

    def add(key, label, w, rb):
        r = voltarget(pnl(hold(w, rb), px, carry, cost))
        R[key] = r
        lines.append(row(label, r))

    add("carry", "金利差（差が年1%以上、週1回）", s_carry(px, carry), 5)
    add("carry0", "金利差（上乗せ後プラスならすべて、週1回）", s_carry(px, carry, 0.0), 5)
    for L in (20, 60, 120, 250):
        add(f"trend{L}", f"トレンド {L}日（週1回）", s_trend(px, L), 5)
    add("ct60", "金利差＋トレンド60日（今の EA の形）", s_carry_trend(px, carry, 60), 5)
    add("ct120", "金利差＋トレンド120日", s_carry_trend(px, carry, 120), 5)
    add("ct250", "金利差＋トレンド250日", s_carry_trend(px, carry, 250), 5)
    add("ct60all", "金利差＋トレンド60日（上位を選ばず、急変の回避なし）", s_carry_trend(px, carry, 60, topk=None, crash=None), 5)
    for y in (3.0, 5.0):
        add(f"value{y:.0f}", f"割安・割高（{y:.0f}年前との比べ、月1回）", s_value(px, y), 21)
    add("value5b", "割安・割高（5年、ずれが大きいペアだけ）", s_value(px, 5.0, 1.0), 21)

    def blend(keys):
        return voltarget(sum(R[k] for k in keys) / len(keys))
    lines.append(row("組み合わせ：金利差＋トレンド250日（半分ずつ）", blend(["carry", "trend250"])))
    lines.append(row("組み合わせ：金利差・トレンド250日・割安割高5年（3等分）", blend(["carry", "trend250", "value5"])))
    lines.append(row("組み合わせ：金利差＋トレンド60日（EA の形）と 割安割高5年（半分ずつ）", blend(["ct60", "value5"])))
    lines.append(row("組み合わせ：EA の形・割安割高5年・トレンド250日（3等分）", blend(["ct60", "value5", "trend250"])))
    # 手法どうしの関係（2000年以降の日次の相関）
    keys = ["carry", "trend60", "trend250", "ct60", "value5"]
    names = {"carry": "金利差", "trend60": "トレンド60日", "trend250": "トレンド250日", "ct60": "金利差＋トレンド60日", "value5": "割安割高5年"}
    c = pd.DataFrame({names[k]: R[k] for k in keys})
    c = c[c.index >= "2000-01-01"].corr().round(2)
    lines += ["", "## 手法どうしの相関（2000年以降、日次）", "", "| | " + " | ".join(c.columns) + " |", "|---|" + "---|" * len(c.columns)]
    for k in c.index:
        lines.append(f"| {k} | " + " | ".join(f"{v:+.2f}" for v in c.loc[k]) + " |")
    out = os.path.join(ROOT, "reports", "research", "styles_long.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    pd.DataFrame(R).to_parquet(os.path.join(D.CACHE, "styles_long_returns.parquet"))


if __name__ == "__main__":
    main()

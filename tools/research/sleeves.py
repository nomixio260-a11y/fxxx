#!/usr/bin/env python3
"""研究：互いに無関係な「層」を重ねたときの成績（日付・時刻を使わない。コスト込み。`reports/research/sleeves.md`）。

層（どれも、公表済みの考え方をそのまま使う。数値は選び直さない）：
  1 為替の金利差（今の EA の形。tools/research/carry_long.py の C60+）
  2 株価指数の順張り：終値が200日の平均より上のときだけ買い持ち（週1回見直し。Faber 2007年）
  3 金の順張り：同じルールを金に
  4 株価指数の売られすぎの戻り：R2<10・D7・IBS の3つのルール（tools/research/index_reversion.py）を同じ重みで
- 株価指数は、OANDA の CFD にある6つ（米国 S&P500・NASDAQ100・ダウ、日経225、DAX、FTSE100）。
  売られすぎの戻りは、ルールが公表された対象（米国の3指数）だけの形と、6指数すべての形の両方を出す。
- 建玉：各指数（金）の直近60日の値動きから、持っているときの値動きが年10%になる大きさ（前日までの値だけを使う。上限4倍）。
- コスト（CFD）：売買は片道 0.02%（金・順張りは 0.03%）、持ち越しは 短期金利＋年2.5% を払い、配当を受け取る。
- 層ごとの成績は、全期間の値動きが年10%になるようにそろえてから比べる（シャープは倍率に関係しない）。
- 物差し：年率シャープ、t 値、1年で負ける確率、最大の下落、株式そのものとの関係（ベータ）を除いた残り（アルファ）の t 値。
使い方: python3 tools/research/sleeves.py
"""
import os
import sys
from math import erf, sqrt

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
START = "2000-10-01"
TRADABLE = ["S&P500", "NASDAQ100", "ダウ", "日経225", "DAX", "FTSE100"]
US3 = ["S&P500", "NASDAQ100", "ダウ"]
PER = (("2000〜2008", START, "2009-01-01"), ("2009〜2014", "2009-01-01", "2015-01-01"), ("2015〜21/10", "2015-01-01", "2021-11-01"),
       ("21/11〜24/10", "2021-11-01", "2024-11-01"), ("24/11〜25/10", "2024-11-01", "2025-11-01"), ("25/11〜26/11", "2025-11-01", "2026-12-01"))


def Phi(x):
    return 0.5 * (1 + erf(x / sqrt(2)))


def sharpe(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 50 and x.std() > 0 else np.nan


def vol_weight(c, target=0.10, cap=4.0):
    """その指数の直近60日の値動きから、年率 target になる建玉の大きさ（その日の終値までの値だけを使う）。"""
    vol = c.pct_change().rolling(60, min_periods=40).std() * np.sqrt(ANN)
    return (target / vol).clip(upper=cap).fillna(0.0)


def weekly(sig):
    keep = np.zeros(len(sig), bool)
    keep[::5] = True
    return sig.where(pd.Series(keep, index=sig.index), np.nan).ffill().fillna(0.0)


def pnl_w(w, d, rate, div, cost, at_open=False):
    """建玉 w（終値で決めた大きさ、0 以上）の日次の損益。CFD の金利・配当・売買のコスト込み。"""
    c, o = d["close"], d["open"]
    days = pd.Series(c.index, index=c.index).diff().dt.days.fillna(1.0)
    fin = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
    if not at_open:
        held = w.shift(1).fillna(0.0)
        return held * (c.pct_change().fillna(0.0) + fin) - (w - held).abs() * cost
    held_on, held_day = w.shift(2).fillna(0.0), w.shift(1).fillna(0.0)
    gap = (o / c.shift(1) - 1.0).fillna(0.0)
    day = (c / o - 1.0).fillna(0.0)
    return held_on * (gap + fin) + held_day * day - (held_day - held_on).abs() * cost


def trend_sleeve(names):
    out = {}
    for n in names:
        yn, ccy, div, _ = IR.INDEX[n]
        d = Y.fetch(yn)
        d = d[d.index >= "1990-01-01"]
        c = d["close"]
        pos = weekly((c > c.rolling(200).mean()).astype(float))
        out[n] = pnl_w(pos * vol_weight(c), d, IR.short_rate(ccy, d.index), div, 0.0003)
    return out


def gold_sleeve():
    d = Y.fetch("GC")
    c = d["close"]
    pos = weekly((c > c.rolling(200).mean()).astype(float))
    return pnl_w(pos * vol_weight(c), d, IR.short_rate("USD", d.index), 0.0, 0.0003)


def reversion_sleeve(names, etf=False, at_open=False):
    """ルール3つ × 指数。etf=True なら、米国の3指数を ETF（SPY・QQQ・DIA、実際に売買された値段）で計算する。"""
    out = {}
    for n in names:
        yn, ccy, div, _ = IR.INDEX[n]
        if etf:
            yn, div = {"S&P500": "SPY", "NASDAQ100": "QQQ", "ダウ": "DIA"}[n], 0.0
        d = Y.fetch(yn)
        d = d[d.index >= "1990-01-01"]
        rate = IR.short_rate(ccy, d.index)
        vw = vol_weight(d["close"])
        for key, p in IR.rules(d).items():
            if key == "R2<5":
                continue
            out[(n, key)] = pnl_w(p * vw, d, rate, div, IR.COST, at_open=at_open)
    return out


def combine(parts):
    """層の中の部品を、同じ重みで足す（日付の和集合。値のない日は 0）。"""
    df = pd.DataFrame(parts).sort_index()
    return df.fillna(0.0).mean(axis=1)


def scale10(r, start=START):
    x = r[r.index >= start]
    return x * (0.10 / (x.std() * np.sqrt(ANN)))


def row(label, r):
    cells = []
    for _, a, b in PER:
        x = r[(r.index >= a) & (r.index < b)]
        s = sharpe(x)
        cells.append("—" if np.isnan(s) or x.abs().sum() == 0 else f"{s:+.2f}")
    s = sharpe(r)
    T = len(r) / ANN
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    yr = r.groupby(r.index.year).sum()
    return (f"| {label} | " + " | ".join(cells) + f" | {s:+.2f} | {s * np.sqrt(T):+.1f} | {Phi(-s) * 100:.0f}% | {r.mean() * ANN * 100:+.1f}% | {dd * 100:.0f}% | "
            f"{(yr > 0).sum()}/{len(yr)} |")


HEAD = "| 層 | " + " | ".join(p[0] for p in PER) + " | 全体 | t 値 | 負ける年 | 年率 | 最大の下落 | プラスの年 |"
SEP = "|---|" + "---|" * (len(PER) + 6)


def alpha_row(label, r, mkt):
    """株式そのもの（mkt）との関係を除いた残り（アルファ）。r = α + β·mkt + ε。"""
    x = pd.concat([r, mkt], axis=1).dropna()
    y, m = x.iloc[:, 0].values, x.iloc[:, 1].values
    X = np.column_stack([np.ones(len(m)), m])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    se = np.sqrt(e.var(ddof=2) * np.linalg.inv(X.T @ X)[0, 0])
    return f"| {label} | {b[1]:+.2f} | {np.corrcoef(y, m)[0, 1]:+.2f} | {b[0] * ANN * 100:+.1f}% | {b[0] / se:+.1f} | {sharpe(pd.Series(e + b[0])):+.2f} |"


def main():
    idx_all = pd.bdate_range(START, "2026-11-27")
    carry = pd.read_parquet(os.path.join(D.CACHE, "carry_long_returns.parquet"))["C60+"]
    S = {"為替の金利差": carry,
         "指数の順張り（6指数）": combine(trend_sleeve(TRADABLE)),
         "金の順張り": gold_sleeve(),
         "指数の戻り（米国3指数）": combine(reversion_sleeve(US3)),
         "指数の戻り（6指数）": combine(reversion_sleeve(TRADABLE)),
         "指数の戻り（米国3指数・ETF・翌日の始値）": combine(reversion_sleeve(US3, etf=True, at_open=True))}
    # すべての層を、同じ日付の並び（平日）にそろえる。平日でない日付の損益（祝日の夜間取引など）は、次の平日に寄せる
    def align(v):
        v = v[v.index >= START]
        pos = np.minimum(idx_all.searchsorted(v.index), len(idx_all) - 1)
        return v.groupby(idx_all[pos]).sum().reindex(idx_all).fillna(0.0)
    S = {k: scale10(align(v)) for k, v in S.items()}
    lines = ["# 研究：互いに無関係な層を重ねたときの成績（`tools/research/sleeves.py`）", "",
             f"期間：{START}〜2026年11月。コスト込み。各層は、全期間の値動きが年10%になるようにそろえてある。期間ごとの列は年率シャープ。", "",
             "## 層ごとの成績", "", HEAD, SEP]
    for k, v in S.items():
        lines.append(row(k, v))
    # 株式そのものとの関係
    spx = Y.fetch("SPX")["close"].pct_change()
    lines += ["", "## 株式そのもの（S&P500 の日次の値動き）との関係を除くと、何が残るか", "",
              "ベータ = S&P500 が 1% 動いたときの、その層の動き。アルファ = ベータの分を除いた残りの年率と、その t 値。", "",
              "| 層 | ベータ | 相関 | アルファ（年率） | アルファの t 値 | アルファだけのシャープ |", "|---|---|---|---|---|---|"]
    for k, v in S.items():
        lines.append(alpha_row(k, v, spx.reindex(v.index)))
    # 層どうしの相関
    main_keys = ["為替の金利差", "指数の順張り（6指数）", "金の順張り", "指数の戻り（米国3指数）"]
    c = pd.DataFrame({k: S[k] for k in main_keys}).corr()
    lines += ["", "## 層どうしの相関（日次）", "", "| | " + " | ".join(main_keys) + " |", "|---|" + "---|" * len(main_keys)]
    for k in main_keys:
        lines.append(f"| {k} | " + " | ".join(f"{c.loc[k, j]:+.2f}" for j in main_keys) + " |")
    # 組み合わせ
    lines += ["", "## 組み合わせ（各層を同じ重みで足し、全体の値動きを年10%にそろえる）", "", HEAD, SEP]
    combos = [("為替の金利差だけ（今の口座でできること）", ["為替の金利差"]),
              ("＋指数の順張り", ["為替の金利差", "指数の順張り（6指数）"]),
              ("＋指数の順張り＋指数の戻り（指数の CFD の口座があればできること）", ["為替の金利差", "指数の順張り（6指数）", "指数の戻り（米国3指数）"]),
              ("＋金の順張り（商品の CFD の口座もあればできること）", ["為替の金利差", "指数の順張り（6指数）", "指数の戻り（米国3指数）", "金の順張り"]),
              ("同じ4層で、戻りを厳しめ（ETF・翌日の始値）に置きかえた場合", ["為替の金利差", "指数の順張り（6指数）", "指数の戻り（米国3指数・ETF・翌日の始値）", "金の順張り"]),
              ("同じ4層で、戻りを6指数にした場合", ["為替の金利差", "指数の順張り（6指数）", "指数の戻り（6指数）", "金の順張り"])]
    keep = {}
    for label, keys in combos:
        r = scale10(sum(S[k] for k in keys) / len(keys))
        keep[label] = r
        lines.append(row(label, r))
    # 年ごとの成績
    four = keep["＋金の順張り（商品の CFD の口座もあればできること）"]
    yr = pd.DataFrame({k: S[k].groupby(S[k].index.year).sum() * 100 for k in main_keys})
    yr["4層の組み合わせ"] = four.groupby(four.index.year).sum() * 100
    lines += ["", "## 年ごとの成績（%、値動きを年10%にそろえたとき）", "", "| 年 | " + " | ".join(yr.columns) + " |", "|---|" + "---|" * len(yr.columns)]
    for y, r_ in yr.iterrows():
        lines.append(f"| {y} | " + " | ".join(f"{v:+.1f}" for v in r_.values) + " |")
    out = os.path.join(F.ROOT, "reports", "research", "sleeves.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    pd.DataFrame(S).to_parquet(os.path.join(D.CACHE, "sleeves_returns.parquet"))


if __name__ == "__main__":
    main()

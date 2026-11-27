#!/usr/bin/env python3
"""確認：株価指数の「売られすぎの戻り」は、公表された数値のまわりでも成り立つか（数値を少し変えても崩れないか）。

- 公表された数値（RSI(2) < 10、200日の平均、5日の平均／過去7日／IBS < 0.2）だけがたまたま良いのなら、信用できない。
  まわりの数値でも同じようにプラスなら、数値の選び方に頼っていないと言える。**数値を選び直すためではなく、崩れにくさを見るための表**。
- 対象：米国の3指数（S&P500・NASDAQ100・ダウ）の平均。公表後（2009年〜）。判定した日の終値で売買。コストは index_reversion.py と同じ。
使い方: python3 tools/research/index_reversion_neighbors.py  → reports/research/index_reversion_neighbors.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import yahoo_data as Y  # noqa: E402

US3 = ["S&P500", "NASDAQ100", "ダウ"]


def run(make):
    """make(d) → 建玉（0/1）。3指数それぞれの、2009年以降の（1回の平均 %, t 値, シャープ）を返し、平均する。"""
    out = []
    for n in US3:
        yn, ccy, div, _ = IR.INDEX[n]
        d = Y.fetch(yn)
        d = d[d.index >= "1990-01-01"]
        p = make(d)
        r = IR.pnl(p, d, IR.short_rate(ccy, d.index), div)
        r, p = r[r.index >= "2009-01-01"], p[p.index >= "2009-01-01"]
        tr = IR.trades(p, r)
        out.append((tr.mean() * 100, tr.mean() / tr.std() * np.sqrt(len(tr)), IR.sharpe(r), len(tr)))
    a = np.array(out)
    return a[:, 0].mean(), a[:, 1].mean(), a[:, 2].mean(), a[:, 3].mean()


def cell(x):
    return f"{x[0]:+.2f}%（t {x[1]:+.1f}、シャープ {x[2]:+.2f}、{x[3]:.0f}回）"


def main():
    lines = ["# 確認：売られすぎの戻りは、公表された数値のまわりでも成り立つか（`tools/research/index_reversion_neighbors.py`）", "",
             "米国の3指数の平均、2009年〜、コスト込み。各セル：取引1回の平均（t 値、年率シャープ、取引数）。**太字**が公表された数値。", ""]
    # R2：RSI のしきい値 × 上昇の流れを見る平均の日数
    lines += ["## R2：RSI(2) のしきい値（行）× 上昇の流れを見る平均の日数（列）。手じまいは5日の平均", "",
              "| RSI(2) | 150日 | 200日 | 250日 |", "|---|---|---|---|"]
    for th in (5, 10, 15, 20, 30):
        row = []
        for ma in (150, 200, 250):
            def make(d, th=th, ma=ma):
                c = d["close"]
                return IR.positions((c > c.rolling(ma).mean()) & (IR.rsi_wilder(c, 2) < th), c > c.rolling(5).mean())
            x = cell(run(make))
            row.append(f"**{x}**" if (th, ma) == (10, 200) else x)
        lines.append(f"| < {th} | " + " | ".join(row) + " |")
    lines += ["", "## R2：手じまいに使う平均の日数（RSI(2) < 10、200日の平均）", "", "| 3日 | 5日 | 8日 | 10日 |", "|---|---|---|---|"]
    row = []
    for ex in (3, 5, 8, 10):
        def make(d, ex=ex):
            c = d["close"]
            return IR.positions((c > c.rolling(200).mean()) & (IR.rsi_wilder(c, 2) < 10), c > c.rolling(ex).mean())
        x = cell(run(make))
        row.append(f"**{x}**" if ex == 5 else x)
    lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## D7：過去 N 日の最安値で買い、最高値で手じまい（200日の平均より上）", "", "| 5日 | 7日 | 10日 | 15日 |", "|---|---|---|---|"]
    row = []
    for n in (5, 7, 10, 15):
        def make(d, n=n):
            c = d["close"]
            return IR.positions((c > c.rolling(200).mean()) & (c <= c.rolling(n).min()), c >= c.rolling(n).max())
        x = cell(run(make))
        row.append(f"**{x}**" if n == 7 else x)
    lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## IBS：しきい値（この値より小さい日の終値で買い、次の日に見直す）", "", "| 0.1 | 0.2 | 0.3 | 0.4 | 0.5（参考：下半分の日すべて） |", "|---|---|---|---|---|"]
    row = []
    for th in (0.1, 0.2, 0.3, 0.4, 0.5):
        def make(d, th=th):
            rng = d["high"] - d["low"]
            ibs = ((d["close"] - d["low"]) / rng.where(rng > 0)).fillna(0.5)
            return (ibs < th).astype(float)
        x = cell(run(make))
        row.append(f"**{x}**" if th == 0.2 else x)
    lines.append("| " + " | ".join(row) + " |")
    # 参考：条件なしで持った場合（株式そのもの）
    def hold(d):
        return pd.Series(1.0, index=d.index)
    def above(d):
        c = d["close"]
        return (c > c.rolling(200).mean()).astype(float)
    out = []
    for n in US3:
        yn, ccy, div, _ = IR.INDEX[n]
        d = Y.fetch(yn)
        d = d[d.index >= "1990-01-01"]
        for lab, mk in (("ずっと持つ", hold), ("200日の平均より上の日だけ持つ", above)):
            p = mk(d)
            r = IR.pnl(p, d, IR.short_rate(ccy, d.index), div)
            r, p2 = r[r.index >= "2009-01-01"], p[p.index >= "2009-01-01"]
            out.append((lab, r.sum() / max(p2.shift(1).sum(), 1) * 100, IR.sharpe(r)))
    df = pd.DataFrame(out, columns=["形", "1日あたり", "シャープ"]).groupby("形").mean()
    lines += ["", "## 参考：条件を付けずに持った場合（同じコスト、2009年〜、3指数の平均）", "", "| 形 | 持っている1日あたりの平均 | 年率シャープ |", "|---|---|---|"]
    for k, r_ in df.iterrows():
        lines.append(f"| {k} | {r_['1日あたり']:+.3f}% | {r_['シャープ']:+.2f} |")
    out_path = os.path.join(F.ROOT, "reports", "research", "index_reversion_neighbors.md")
    open(out_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

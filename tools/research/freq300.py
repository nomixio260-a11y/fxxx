#!/usr/bin/env python3
"""研究：「1年で +300%」の年を、どのくらいの頻度で出せるか ― 数式と、20年の実績（106章）。

1 数式（1年の成績が対数正規分布に近い、という前提。一定の割合で持ち続ける場合）：
   シャープ S の手法を、口座の値動き（年）σ で持つと、1年の成績の対数は 平均 Sσ − σ²/2・標準偏差 σ の正規分布。
   +300%（4倍）以上になる確率 = Φ( S − σ/2 − ln4/σ )。これは σ = √(2 ln 4) = 1.665（年 166%）のとき最大で、最大値は Φ( S − 1.665 )。
   つまり、どれだけ大きく持っても、+300% の年の頻度は Φ(S − 1.665) を超えない。
2 口座の値動きの上限：株価指数の CFD はレバレッジ 10倍までなので、指数の口座の値動きは年 50% 前後が上限（104・105章の「大きい設定」）。
   σ に上限があるときの頻度は、上の式に σ の上限を入れた値。
3 20年の実績（2007〜2026年）：composite_20y.py の日々の損益に倍率をかけて（建玉の上限がなかったとしたら、という仮の計算）、
   +300% 以上の年の数・マイナスの年・最大の下落を数える。
使い方: python3 tools/research/freq300.py  → reports/research/freq300.md
"""
import os
import sys
from math import erf, exp, log, sqrt

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import composite_20y as C20  # noqa: E402
import composite_accounts as CA  # noqa: E402
import fred_data as F  # noqa: E402
import index_trend_combo as ITC  # noqa: E402
import target300 as T  # noqa: E402

LN4 = log(4.0)


def Phi(x):
    return 0.5 * (1 + erf(x / sqrt(2)))


def p300(S, sig):
    return Phi(S - sig / 2 - LN4 / sig)


def main():
    lines = ["# 研究：+300% の年を出せる頻度（`tools/research/freq300.py`）", "",
             "## 1 数式：シャープ S と、口座の値動き σ で決まる", "",
             "+300% 以上の年の確率 = Φ(S − σ/2 − ln4/σ)。σ = 166% のとき最大で、最大値は Φ(S − 1.665)。", "",
             "| シャープ S | 0.5 | 0.75 | 1.0 | 1.05（今の2つの層） | 1.25 | 1.67 | 2.0 | 3.0 |", "|---|---|---|---|---|---|---|---|---|"]
    SS = (0.5, 0.75, 1.0, 1.05, 1.25, 1.67, 2.0, 3.0)
    sm = sqrt(2 * LN4)
    lines.append("| どれだけ大きく持っても超えられない頻度（σ = 166%） | " + " | ".join(f"{p300(S, sm) * 100:.0f}%" for S in SS) + " |")
    lines.append("| そのときの、1年の成績の真ん中 | " + " | ".join(f"{(exp(S * sm - sm * sm / 2) - 1) * 100:+.0f}%" for S in SS) + " |")
    lines.append("| そのときの、資産が半分以下で終わる年の確率 | " + " | ".join(f"{Phi((log(0.5) - (S * sm - sm * sm / 2)) / sm) * 100:.0f}%" for S in SS) + " |")
    for sig in (0.5, 0.75, 1.0):
        lines.append(f"| 口座の値動きが年 {sig * 100:.0f}% までの場合の頻度 | " + " | ".join(f"{p300(S, sig) * 100:.1f}%" for S in SS) + " |")
        lines.append(f"| 　そのときの1年の成績の真ん中 | " + " | ".join(f"{(exp(S * sig - sig * sig / 2) - 1) * 100:+.0f}%" for S in SS) + " |")
    lines += ["", "- 20年のうち何回か、に直すには、頻度に 20 をかける（頻度 5% なら、20年に1回）。",
              "- 毎年のように（90% の年で）+300% を出すには、シャープ 2.95 が必要：Φ(S − 1.665) = 0.9 を解くと S = 2.95。", ""]
    print("\n".join(lines[-12:]), flush=True)
    # ---------- 20年の実績に、倍率をかける
    cat = CA.catalog()
    E = {k: CA.rel(c) for k, c in cat.items()}
    rev = {u: T.cash_returns(u) for u in (8.75,)}
    tr = {u: ITC.trend_returns("NASDAQ100", u) for u in (20.0,)}
    idx = C20.spliced(E[("Index_Growth", 0.0, "long")], rev[8.75].add(tr[20.0], fill_value=0.0))[0]
    idx = idx[idx.index >= "2007-01-01"]
    gold = E[("金", 50.0, "long")].pct_change().dropna()
    gold = gold[gold.index >= "2007-01-01"]
    lines += ["## 2 20年の実績（2007〜2026年）に倍率をかけた、仮の計算（建玉の上限がなかったとしたら）", "",
              "| 設定 | 倍率 | 口座の値動き（年） | 年率 | 最大の下落 | +300% 以上の年 | +100% 以上の年 | マイナスの年 | −50% 以下の年 | 最悪の年 | 最高の年 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for lab, r in (("指数の口座（大きい設定）", idx), ("金の口座（最大の設定）", gold), ("2つを半分ずつ（毎日そろえる。仮の計算）", pd.concat([idx, gold], axis=1, sort=True).fillna(0.0).mean(axis=1))):
        for L in (1.0, 1.5, 2.0, 3.0, 4.0):
            x = (r * L).clip(lower=-0.999)
            e = (1 + x).cumprod()
            e = pd.concat([pd.Series([1.0], index=[e.index[0] - pd.Timedelta(days=1)]), e])
            y = C20.yearly(e)
            yrs = (e.index[-1] - e.index[0]).days / 365.25
            lines.append(f"| {lab} | {L:g} | {x.std() * np.sqrt(252) * 100:.0f}% | {(e.iloc[-1] ** (1 / yrs) - 1) * 100:+.0f}% | {(e / e.cummax() - 1).min() * 100:.0f}% | {int((y >= 3).sum())} | {int((y >= 1).sum())} | "
                         f"{int((y < 0).sum())} | {int((y <= -0.5).sum())} | {y.min() * 100:+.0f}% | {y.max() * 100:+.0f}% |")
            print(lines[-1], flush=True)
    lines += ["", "- 倍率 1 が、実際に検証した設定（指数は「大きい設定」、金は「最大の設定」）。指数の口座は、レバレッジの上限（10倍）のため、倍率 1 より大きくは持てません（101章）。",
              "- 倍率を上げると +300% の年は増えますが、同時に、資産の大半を失う年が出て、20年を通した成績は悪くなります。"]
    out = os.path.join(F.ROOT, "reports", "research", "freq300.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

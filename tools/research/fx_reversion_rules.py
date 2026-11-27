#!/usr/bin/env python3
"""確認：株価指数で公表されている「売られすぎの戻り」のルール（R2・D7）を、為替の17ペアにそのまま当てはめると、どうなるか。

- 今の為替の口座だけで同じ優位性が使えるなら、口座を増やす必要がない。そこで、数値を変えずに確かめる。
- 買い：終値が200日の平均より上で、RSI(2) < 10（R2）／過去7日の最安値（D7）。売り：その逆（200日の平均より下で、RSI(2) > 90／過去7日の最高値）。
- データ：FRED の日次（1999〜2026年）。判定の次の日の値段で売買する。コスト：スプレッド、スワップ（金利差 − 上乗せ 年1%）。
使い方: python3 tools/research/fx_reversion_rules.py  → reports/research/fx_reversion_rules.md
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import index_reversion as IR  # noqa: E402
import styles_long as SL  # noqa: E402

ANN = 261


def main():
    px, carry, cost = SL.load()
    tot, per_pair = {}, []
    for p in px.columns:
        c = px[p].dropna()
        up, dn = c > c.rolling(200).mean(), c < c.rolling(200).mean()
        r2 = IR.rsi_wilder(c, 2)
        pos = {("R2", "買い"): (IR.positions(up & (r2 < 10), c > c.rolling(5).mean()), 1.0),
               ("R2", "売り"): (IR.positions(dn & (r2 > 90), c < c.rolling(5).mean()), -1.0),
               ("D7", "買い"): (IR.positions(up & (c <= c.rolling(7).min()), c >= c.rolling(7).max()), 1.0),
               ("D7", "売り"): (IR.positions(dn & (c >= c.rolling(7).max()), c <= c.rolling(7).min()), -1.0)}
        ret = c.pct_change().fillna(0.0)
        cy = carry[p].reindex(c.index).fillna(0.0)
        for k, (q, sgn) in pos.items():
            held, w = q.shift(2).fillna(0.0), q.shift(1).fillna(0.0)
            r = held * sgn * ret + held * (sgn * cy - SL.MARKUP) / 100.0 / ANN - (w - held).abs() * cost[p].reindex(c.index)
            r = r[r.index >= "2000-01-01"]
            tot.setdefault(k, {})[p] = r
            n = int(((w - held) > 0).sum())
            per_pair.append((p, k[0], k[1], r.sum() / max(n, 1) * 100))
    lines = ["# 確認：株価指数の「売られすぎの戻り」のルールを、為替の17ペアに当てはめる（`tools/research/fx_reversion_rules.py`）", "",
             "コスト・スワップ込み。判定の次の日の値段で売買。期間ごとの列は年率シャープ（17ペアを同じ重みで足した層）。", "",
             "| ルール | " + " | ".join(x[0] for x in SL.PER) + " | 全体（2000年〜） | プラスの年 |", "|---|" + "---|" * (len(SL.PER) + 2)]

    def add(label, parts):
        r = pd.concat(parts, axis=1).fillna(0.0).mean(axis=1)
        yr = r.groupby(r.index.year).sum()
        cells = [f"{SL.sharpe(r[(r.index >= a) & (r.index < b)]):+.2f}" for _, a, b in SL.PER]
        lines.append(f"| {label} | " + " | ".join(cells) + f" | {SL.sharpe(r):+.2f} | {(yr > 0).sum()}/{len(yr)} |")
    for k, v in tot.items():
        add(f"{k[0]}・{k[1]}（17ペア）", list(v.values()))
    for key in ("R2", "D7"):
        add(f"{key}・買い（AUDJPY・NZDJPY・CADJPY だけ。株価と一緒に動きやすいペア）", [tot[(key, "買い")][p] for p in ("AUDJPY", "NZDJPY", "CADJPY")])
    df = pd.DataFrame(per_pair, columns=["ペア", "ルール", "向き", "avg"])
    pv = df.pivot_table(index="ペア", columns=["ルール", "向き"], values="avg")
    lines += ["", "## ペアごとの、取引1回あたりの平均の損益（%）", "", "| ペア | " + " | ".join(f"{a}・{b}" for a, b in pv.columns) + " |", "|---|" + "---|" * len(pv.columns)]
    for p, row in pv.iterrows():
        lines.append(f"| {p} | " + " | ".join(f"{v:+.2f}" for v in row.values) + " |")
    out = os.path.join(SL.ROOT, "reports", "research", "fx_reversion_rules.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[:14]))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""研究：米国の指数どうしの相対的な動き（出遅れた指数を買い、先行した指数を売る）に優位性があるか。

- 市場全体の上げ下げに左右されない形（買いと売りを同じ額）なら、暴落の日の損失を避けられる。
- 4つの指数（S&P500・NASDAQ100・ダウ・ラッセル2000）。過去 k 日の値動き（値動きの大きさで割った値）が、4指数の平均より低い指数を買い、
  高い指数を売る。重みは平均からの差に比例、買いの合計と売りの合計を同じにする。h 日ごとに入れ替える。
- コスト：売買は片道 0.02%。持ち越しは、買いが 年 −4.79%、売りが 年 −0.21%（OANDA の実際の値）、配当は買いで受け取り・売りで払う。
- 期間：1990年〜2026年（ラッセル2000 は 1988年〜）。現物の指数の日足。判定した日の終値で売買。
使い方: python3 tools/research/index_relative.py  → reports/research/index_relative.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
NAMES = ["S&P500", "NASDAQ100", "ダウ", "ラッセル2000"]
PER = (("1990〜99", "1990-01-01", "2000-01-01"), ("2000〜08", "2000-01-01", "2009-01-01"), ("2009〜14", "2009-01-01", "2015-01-01"),
       ("2015〜21/10", "2015-01-01", "2021-11-01"), ("21/11〜26/11", "2021-11-01", "2026-12-01"))


def main():
    px = pd.DataFrame({n: Y.fetch(IR.INDEX[n][0])["close"] for n in NAMES}).dropna()
    px = px[px.index >= "1989-01-01"]
    div = pd.Series({n: IR.INDEX[n][2] for n in NAMES})
    ret = px.pct_change()
    sd = ret.rolling(60, min_periods=40).std()
    lines = ["# 研究：米国の指数どうしの相対的な動き（`tools/research/index_relative.py`）", "",
             "出遅れた指数を買い、先行した指数を売る（買いと売りは同じ額）。期間ごとの列は年率シャープ。コスト・持ち越し込み。", "",
             "| 見る日数 k・入れ替え h | コスト前のシャープ | コスト後 | " + " | ".join(p[0] for p in PER) + " | 1年あたりの入れ替え（建玉の合計に対する倍率） |",
             "|---|---|---|" + "---|" * (len(PER) + 1)]
    for k in (1, 2, 5, 10, 20):
        for h in (1, 5):
            z = (np.log(px).diff(k)) / (sd * np.sqrt(k))
            rel = z.sub(z.mean(axis=1), axis=0)
            w = -rel.div(sd, axis=0)                                   # 出遅れ（rel < 0）を買い。値動きの大きさでそろえる
            w = w.sub(w.mean(axis=1), axis=0)
            w = w.div(w.abs().sum(axis=1), axis=0).fillna(0.0)          # 建玉の合計 = 1（買い 0.5、売り 0.5）
            if h > 1:
                keep = np.zeros(len(w), bool)
                keep[::h] = True
                w = w.where(pd.Series(keep, index=w.index), np.nan).ffill().fillna(0.0)
            held = w.shift(1).fillna(0.0)
            gross = (held * ret).sum(axis=1)
            fin = (held.clip(lower=0) * (div - 4.79) + (-held.clip(upper=0)) * (-0.21 - div)).sum(axis=1) / 100.0 / 360.0 * \
                pd.Series(px.index, index=px.index).diff().dt.days.fillna(1.0)
            tc = (w - held).abs().sum(axis=1) * IR.COST
            net = gross + fin - tc
            x = net[net.index >= "1990-01-01"]
            gx = gross[gross.index >= "1990-01-01"]
            cells = [f"{IR.sharpe(x[(x.index >= a) & (x.index < b)]):+.2f}" for _, a, b in PER]
            lines.append(f"| k={k}・h={h} | {IR.sharpe(gx):+.2f} | {IR.sharpe(x):+.2f} | " + " | ".join(cells) + f" | {((w - held).abs().sum(axis=1)).mean() * ANN:.0f} |")
            print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_relative.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

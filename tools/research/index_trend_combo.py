#!/usr/bin/env python3
"""研究：指数の戻りの層に、NASDAQ100 の順張りの層を重ねる。26年の現物のデータで、時代ごとに確かめる（104章）。

- 戻りの層：現物の3指数、EA と同じ形（target300.py の cash_returns。強制ロスカットを避ける上限あり）。
- 順張りの層：NASDAQ100 の終値が200日の平均より上のあいだだけ買い持ち（7日ごとに見直す）。建玉は、値動きの見積もり（HAR 型）で
  口座の年 x% になる大きさ。逆指値 4×σ（EA は、同じ口座の建玉すべてに同じ逆指値を使う）。コストは CFD と同じ形（短期金利＋年2.5%、配当相当額あり）。
- 2つの層の損益を、同じ資金に対して足す（上限の取り合いは無視。順張りの建玉は資金の1倍前後なので、影響は小さい）。
使い方: python3 tools/research/index_trend_combo.py  → reports/research/index_trend_combo.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_stop as IS  # noqa: E402
import index_vix_sizing as V  # noqa: E402
import target300 as T  # noqa: E402

ANN = 252
PER = (("2000〜08", IRK.START, "2009-01-01"), ("2009〜14", "2009-01-01", "2015-01-01"), ("2015〜19", "2015-01-01", "2020-01-01"), ("2020〜22", "2020-01-01", "2023-01-01"),
       ("2023〜26", "2023-01-01", "2027-01-01"))


def trend_returns(name, unit, check=7):
    d, n, sg, rate, div = V.load_sets("cash")[name]
    c = d["close"]
    sma = c.rolling(200).mean()
    st = np.zeros(len(d))
    last, cur = None, 0.0
    for i, t in enumerate(d.index):
        if i >= 200 and (last is None or (t - last).days >= check):
            cur, last = float(c.iloc[i] > sma.iloc[i]), t
        st[i] = cur
    w = (pd.Series(st, index=d.index) * unit / 100.0 / np.maximum(sg * np.sqrt(ANN), 0.025)).fillna(0.0)
    r, _, _ = IS.run(d, w, sg, rate, div, 4.0, "close")
    return r[r.index >= IRK.START]


def cell(r):
    if len(r) < 200:
        return "—"
    eq = (1 + r.clip(lower=-0.99)).cumprod()
    yrs = len(r) / ANN
    return f"{(eq.iloc[-1] ** (1 / yrs) - 1) * 100:+.0f}%・{r.mean() / r.std() * np.sqrt(ANN):+.2f}・{(eq / eq.cummax() - 1).min() * 100:.0f}%"


def main():
    lines = ["# 研究：戻りの層 ＋ NASDAQ100 の順張りの層、26年（`tools/research/index_trend_combo.py`）", "",
             "表の値は「年率の伸び・シャープ・最大の下落」。現物の指数、2000年10月〜2026年11月。", "",
             "| 形 | 全期間 | " + " | ".join(p[0] for p in PER) + " | プラスの年 | 最悪の年 |", "|---|---|" + "---|" * (len(PER) + 2)]
    rev = {u: T.cash_returns(u) for u in (5.0, 8.75)}
    tr = {u: trend_returns("NASDAQ100", u) for u in (10.0, 20.0, 40.0)}
    forms = (("戻り 5% だけ", rev[5.0]), ("戻り 5% ＋ 順張り 10%", rev[5.0].add(tr[10.0], fill_value=0.0)), ("戻り 8.75% だけ", rev[8.75]),
             ("戻り 8.75% ＋ 順張り 20%", rev[8.75].add(tr[20.0], fill_value=0.0)), ("戻り 8.75% ＋ 順張り 40%", rev[8.75].add(tr[40.0], fill_value=0.0)),
             ("順張り 20% だけ", tr[20.0]))
    for label, r in forms:
        yr = (1 + r).groupby(r.index.year).prod() - 1
        lines.append(f"| {label} | {cell(r)} | " + " | ".join(cell(r[(r.index >= a) & (r.index < b)]) for _, a, b in PER)
                     + f" | {int((yr > 0).sum())} / {len(yr)} | {yr.min() * 100:+.0f}%（{int(yr.idxmin())}年） |")
        print(lines[-1], flush=True)
    lines += ["", f"- 2つの層の、日々の損益の相関：{pd.concat([rev[8.75], tr[20.0]], axis=1, sort=True).fillna(0.0).corr().iloc[0, 1]:+.2f}。"]
    print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_trend_combo.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

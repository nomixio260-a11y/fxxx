#!/usr/bin/env python3
"""FOMC（米国の金融政策の発表、NY 14:00）の日の前後で、ドルが決まった向きに動くかを調べる（5分足、コスト前 pips と t 値）。

発表日は tools/research/events/fomc.txt（米連邦準備制度の公式ページの日程から作った、定例会合の声明の日。臨時会合は除く）。
調べる時間帯（NY 時間）：
  A 前日 14:00 → 当日 13:55（発表前の24時間）
  B 当日  8:00 → 当日 13:55（発表前の朝から）
  C 当日 14:30 → 翌日  8:00（発表の直後を除いた後）
向きは「ドル買い」をプラスとする（EURUSD などは売り、USDJPY などは買い）。
使い方: python3 tools/research/fomc_drift.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402

USD_BASE = {"USDJPY": 1, "USDCAD": 1, "USDCHF": 1, "EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1}
PER = (("15-21", "2015-01-01", "2021-11-01"), ("前半", "2021-11-01", "2024-11-01"), ("後半", "2024-11-01", "2027-01-01"))
WIN = {"A 前日14:00→当日13:55": (-1, 14, 0, 0, 13, 55), "B 当日8:00→13:55": (0, 8, 0, 0, 13, 55), "C 当日14:30→翌日8:00": (0, 14, 30, 1, 8, 0)}


def price_at(df, day, h, m):
    """NY の日付 day の h:m の足の始値（なければ NaN）。"""
    sel = (df["ny_date"].values == np.datetime64(day)) & (df["ny_h"].values == h) & (df["ny_m"].values == m)
    i = np.where(sel)[0]
    return df["o"].values[i[0]] if len(i) else np.nan


def bday(d, k):
    return (pd.Timestamp(d) + pd.offsets.BDay(k)).normalize()


def main():
    days = [pd.Timestamp(x.strip()) for x in open(os.path.join(D.ROOT, "tools", "research", "events", "fomc.txt")) if x.strip()]
    days = [d for d in days if d < pd.Timestamp("2026-11-13")]
    rows = []
    for pair, sg in USD_BASE.items():
        df = D.bars(pair, "5min")
        pip = D.pip_size(pair)
        for d in days:
            for wname, (k0, h0, m0, k1, h1, m1) in WIN.items():
                a = price_at(df, bday(d, k0), h0, m0)
                b = price_at(df, bday(d, k1), h1, m1)
                rows.append({"pair": pair, "day": d, "win": wname, "r": sg * (b - a) / pip})
    res = pd.DataFrame(rows).dropna()
    # ペアごとのばらつきでそろえた「ドル全体」の動き
    res["z"] = res.groupby(["pair", "win"])["r"].transform(lambda x: x / x.std())
    lines = ["# FOMC の日のドルの動き（ドル買いをプラス、コスト前）", "", f"- 発表日：{len(days)} 回（2015年1月〜2026年10月）", ""]
    for wname in WIN:
        lines += [f"## {wname}", "", "| ペア | 15-21（pips, t） | 前半 | 後半 |", "|---|---|---|---|"]
        for pair in list(USD_BASE) + ["ドル全体（そろえた値の平均）"]:
            x = res[res.win == wname]
            if pair in USD_BASE:
                x = x[x.pair == pair].set_index("day")["r"]
            else:
                x = x.groupby("day")["z"].mean()
            cells = []
            for _, a, b in PER:
                y = x[(x.index >= a) & (x.index < b)]
                cells.append(f"{y.mean():+.2f}（t {y.mean() / y.std() * np.sqrt(len(y)):+.1f}, n {len(y)}）")
            lines.append(f"| {pair} | " + " | ".join(cells) + " |")
        lines.append("")
    text = "\n".join(lines)
    open(os.path.join(D.ROOT, "reports", "research", "fomc_drift.md"), "w", encoding="utf-8").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

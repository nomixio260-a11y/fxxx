#!/usr/bin/env python3
"""A1（ロンドン 11:00〜13:00 の EURUSD 売り）と同じ「ロンドンの昼前後のドル高」が、ほかのペアでも起きているかを調べる。

各ペアで、ロンドン時間 11:00 に「ドルを買う向き」に入り、120分後に決済したときのコスト後 pips と、
EURUSD（A1）との相関を出す。期間：2015〜21/10、前半 21/11〜24/10、後半 24/11〜。
使い方: python3 tools/research/ldn_usd.py  → reports/research/ldn_usd.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

PAIRS = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1, "USDJPY": 1, "USDCHF": 1, "USDCAD": 1,
         "EURJPY": -1, "EURGBP": -1}
PERIODS = (("2015〜21/10", ("2015-01-01", "2021-11-01")), ("前半", ("2021-11-01", "2024-11-01")),
           ("後半", ("2024-11-01", "2026-11-14")))


def st(x):
    x = x[~np.isnan(x)]
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return f"{len(x)}回 {x.mean():+.2f} PF {gp / gl if gl > 0 else 9.99:.2f} t {x.mean() / x.std(ddof=1) * np.sqrt(len(x)):.1f}"


def main():
    res = {}
    for pair, d in PAIRS.items():
        df = D.bars(pair, "5min")
        pip = D.pip_size(pair)
        t = df.index[(df["ldn_h"].values == 11) & (df["ldn_m"].values == 0)]
        o = df["o"]
        r = pd.Series(d * (o.reindex(t + pd.Timedelta(minutes=120)).values - o.reindex(t).values) / pip - S.COST.get(pair, 2.0), index=t).dropna()
        res[pair] = r
    base = res["EURUSD"]
    out = ["# ロンドン 11:00〜13:00 の「ドルを買う向き」の成績（コスト後 pips／回）", "",
           "（EURJPY・EURGBP は「ユーロを売る向き」）", "",
           "| ペア | " + " | ".join(p for p, _ in PERIODS) + " | EURUSD との相関 |", "|---|---|---|---|---|"]
    for pair, r in res.items():
        c = pd.concat([base, r], axis=1, sort=True).dropna().corr().iloc[0, 1]
        out.append(f"| {pair} | " + " | ".join(st(r[D.period_mask(r.index, p)].values) for _, p in PERIODS) + f" | {c:+.2f} |")
    text = "\n".join(out) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "ldn_usd.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

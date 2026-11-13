#!/usr/bin/env python3
"""論文で報告されている偏りを、自分のデータ（histdata の5分足）で確かめる。

1. フィキシング前後の米ドルの W 字型（Krohn, Mueller & Whelan, Journal of Finance 2024）
   - 米ドルは、主要なフィキシング（東京仲値 9:55、ECB 14:15 中欧時間＝ロンドン 13:15、WM/R ロンドン 16:00）の
     前に上がり、後に下がる。
   - 米ドルを含む3ペア（USDJPY・EURUSD・GBPUSD）で、「米ドル買い」の向きにそろえた値動きを調べる。
2. 日中モメンタム（Gao, Han, Li & Zhou, JFE 2018。為替では Elaut, Frömmel & Lampaert, JFM 2018）
   - 取引時間の最初の30分の値動きが、最後の30分の値動きを予測する。
   - 東京（9:00〜15:00）・ロンドン（8:00〜16:30）・NY（8:00〜16:00）の取引時間で、
     最後の30分に、最初の30分と同じ向きに入る。

評価：設計期間で調べ、向きと条件を固定したまま検証期間で確かめる。最終確認期間は見ない。
コストは seasonality.COST（通常スプレッドの目安＋0.5 pips）。

使い方: python3 tools/research/papers.py  → reports/research/papers.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

USD_SIGN = {"USDJPY": 1.0, "EURUSD": -1.0, "GBPUSD": -1.0}   # 米ドル買い＝この向き


def at(df, clock, hh, mm):
    return df.index[(df[f"{clock}_h"].values == hh) & (df[f"{clock}_m"].values == mm)]


def move(o, t0, a, b, pip):
    p0 = o.reindex(t0 + pd.Timedelta(minutes=a)).values
    p1 = o.reindex(t0 + pd.Timedelta(minutes=b)).values
    return (p1 - p0) / pip


def st(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 20:
        return {"n": len(x), "mean": 0.0, "t": 0.0, "pf": 0.0}
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return {"n": len(x), "mean": x.mean(), "t": x.mean() / x.std(ddof=1) * np.sqrt(len(x)), "pf": gp / gl if gl > 0 else 9.99}


def fmt(s):
    return f"{s['n']}回 {s['mean']:+.2f}pips t {s['t']:.1f} PF {s['pf']:.2f}"


def w_shape():
    out = ["## 1. フィキシング前後の米ドル（Krohn ほか 2024）", "",
           "米ドル買いの向きにそろえた値動き（pips）。「コスト後」は1取引あたりのコストを引いた値です。", "",
           "| ペア | フィキシング | 時間帯 | 設計（コスト前） | 設計（コスト後） | 検証（コスト前） | 検証（コスト後） |",
           "|---|---|---|---|---|---|---|"]
    fixes = [("tky", 9, 55, "東京仲値"), ("ldn", 13, 15, "ECB"), ("ldn", 16, 0, "WM/R")]
    wins = [(-120, 0, "前2時間"), (-60, 0, "前1時間"), (0, 60, "後1時間"), (0, 120, "後2時間")]
    for pair, sgn in USD_SIGN.items():
        df = D.bars(pair, "5min")
        o = df["o"]
        pip = D.pip_size(pair)
        cost = S.COST[pair]
        for clock, hh, mm, name in fixes:
            t0 = at(df, clock, hh, mm)
            des = D.period_mask(t0, D.DESIGN)
            val = D.period_mask(t0, D.VALID)
            for a, b, wn in wins:
                r = move(o, t0, a, b, pip) * sgn
                d = 1.0 if np.nanmean(r[des]) >= 0 else -1.0     # 設計期間の平均の向き
                out.append(f"| {pair} | {name} | {wn} | {fmt(st(r[des]))} | {fmt(st(r[des] * d - cost))} | "
                           f"{fmt(st(r[val]))} | {fmt(st(r[val] * d - cost))} |")
    out += ["", "- 「コスト後」は、設計期間の平均の向き（米ドル買い/売り）に取引した場合です。検証期間でも同じ向きを使います。", ""]
    return out


def intraday_momentum():
    out = ["## 2. 日中モメンタム（Gao ほか 2018 / Elaut ほか 2018）", "",
           "最初の30分の値動きの向きに、最後の30分で入ったときの損益（pips）。", "",
           "| ペア | 取引時間 | 設計（コスト前） | 設計（コスト後） | 検証（コスト前） | 検証（コスト後） | 設計の相関 |",
           "|---|---|---|---|---|---|---|"]
    sessions = [("tky", (9, 0), (14, 30), "東京 9:00〜15:00"), ("ldn", (8, 0), (16, 0), "ロンドン 8:00〜16:30"),
                ("ny", (8, 0), (15, 30), "NY 8:00〜16:00")]
    for pair in D.PAIRS:
        df = D.bars(pair, "5min")
        o = df["o"]
        pip = D.pip_size(pair)
        cost = S.COST[pair]
        for clock, (h0, m0), (h1, m1), name in sessions:
            t_open = at(df, clock, h0, m0)
            t_last = at(df, clock, h1, m1)
            d_open = pd.Series(t_open, index=pd.DatetimeIndex(df.loc[t_open, f"{clock}_date"]))
            d_last = pd.Series(t_last, index=pd.DatetimeIndex(df.loc[t_last, f"{clock}_date"]))
            common = d_open.index.intersection(d_last.index)
            d_open, d_last = d_open[~d_open.index.duplicated()], d_last[~d_last.index.duplicated()]
            common = d_open.index.intersection(d_last.index)
            first = move(o, pd.DatetimeIndex(d_open[common].values), 0, 30, pip)
            last = move(o, pd.DatetimeIndex(d_last[common].values), 0, 30, pip)
            sig = np.sign(first)
            pnl = sig * last
            pnl[sig == 0] = np.nan
            des = D.period_mask(pd.DatetimeIndex(d_last[common].values), D.DESIGN)
            val = D.period_mask(pd.DatetimeIndex(d_last[common].values), D.VALID)
            ok = ~np.isnan(first) & ~np.isnan(last)
            corr = np.corrcoef(first[des & ok], last[des & ok])[0, 1] if (des & ok).sum() > 30 else 0.0
            out.append(f"| {pair} | {name} | {fmt(st(pnl[des]))} | {fmt(st(pnl[des] - cost))} | {fmt(st(pnl[val]))} | {fmt(st(pnl[val] - cost))} | {corr:+.3f} |")
    out += [""]
    return out


def main():
    lines = ["# 論文で報告されている偏りの確認（5分足）", ""] + w_shape() + intraday_momentum()
    text = "\n".join(lines)
    open(os.path.join(D.ROOT, "reports", "research", "papers.md"), "w", encoding="utf-8").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

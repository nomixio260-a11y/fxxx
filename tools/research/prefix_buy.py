#!/usr/bin/env python3
"""ゴトー日の仲値前の買い（9:25→9:55）：直前の値動きで成績が分かれるか。

- 対象：USDJPY（P1、条件なしでは検証期間で不合格）・EURJPY（P2）・GBPJPY（P3、条件なしでは不合格）。
- 条件（9:25 の時点で分かるもの）：
  - 早い時間の動き：8:55→9:25 の値動き ÷ 1時間足の平均値幅
  - 夜間の動き：NY 17:00 → 東京 9:25 の値動き ÷ 1時間足の平均値幅
- 境目は設計期間の3分の1ずつで決め、検証期間にそのまま当てはめる。コスト後の pips。

使い方: python3 tools/research/prefix_buy.py  → reports/research/prefix_buy.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402


def st(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 15:
        return f"{len(x)}回"
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return f"{len(x)}回 {x.mean():+.2f}pips PF {gp / gl if gl > 0 else 9.99:.2f} t {x.mean() / x.std(ddof=1) * np.sqrt(len(x)):.1f}"


def main():
    out = ["# ゴトー日の仲値前の買い（9:25→9:55）を直前の値動きで分ける（コスト後）", ""]
    for pair in ("USDJPY", "EURJPY", "GBPJPY"):
        df = D.bars(pair, "5min")
        o = df["o"]
        pip = D.pip_size(pair)
        cost = S.COST[pair]
        t0 = df.index[(df["tky_h"].values == 9) & (df["tky_m"].values == 25)]
        t0 = t0[S.gotobi_mask(pd.DatetimeIndex(df.loc[t0, "tky_date"]))]
        p = lambda t: o.reindex(t).values  # noqa: E731
        h1 = D.bars(pair, "1h")
        a = (h1["h"] - h1["l"]).rolling(24).mean().shift(1).reindex(t0.floor("1h")).values / pip
        pnl = (p(t0 + pd.Timedelta(minutes=30)) - p(t0)) / pip - cost
        early = (p(t0) - p(t0 - pd.Timedelta(minutes=30))) / pip / a
        ny = t0.tz_localize("UTC").tz_convert("America/New_York")
        nyc = ny.normalize() + pd.Timedelta(hours=17)
        nyc = nyc.where(nyc < ny, nyc - pd.Timedelta(days=1)).tz_convert("UTC").tz_localize(None)
        night = (p(t0) - o.reindex(nyc, method="ffill").values) / pip / a
        des = D.period_mask(t0, D.DESIGN)
        val = D.period_mask(t0, D.VALID)
        out += [f"## {pair}", "", f"- 条件なし：設計 {st(pnl[des])} ／ 検証 {st(pnl[val])}", ""]
        for name, z in (("早い時間の動き（8:55→9:25）", early), ("夜間の動き（NY 17:00→9:25）", night)):
            lo, hi = np.nanquantile(z[des], [1 / 3, 2 / 3])
            out += [f"### {name}（境目 {lo:+.2f} / {hi:+.2f}）", "", "| 区分 | 設計 | 検証 |", "|---|---|---|"]
            for lab, m in (("下げ（下1/3）", z <= lo), ("中", (z > lo) & (z <= hi)), ("上げ（上1/3）", z > hi)):
                out.append(f"| {lab} | {st(pnl[des & m])} | {st(pnl[val & m])} |")
            out.append("")
    text = "\n".join(out)
    open(os.path.join(D.ROOT, "reports", "research", "prefix_buy.md"), "w", encoding="utf-8").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

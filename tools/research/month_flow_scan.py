#!/usr/bin/env python3
"""月初（最初の2営業日）・月末（最終営業日）の需給の偏りを、6ペア × 東京時間の30分ごとの時刻 × 保有 60/120分で調べる。

選ぶ条件（偶然の当たりを減らすため、年ごとの安定性を重視）：
- 2015〜21/10・前半 21/11〜24/10・後半 24/11〜 のすべてで、+0.5pips 込みでもプラス・PF ≥ 1.15
- 12年のうち 10年以上でプラス（コスト後）
- 日付の変わり目（NY 16:00〜18:59）にかかる取引は除く
使い方: python3 tools/research/month_flow_scan.py  → reports/research/month_flow_scan.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

PAIRS = ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "EURUSD", "GBPUSD"]
PERIODS = (("2015〜21/10", ("2015-01-01", "2021-11-01")), ("前半", ("2021-11-01", "2024-11-01")),
           ("後半", ("2024-11-01", "2026-11-14")))


def pf(x):
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return gp / gl if gl > 0 else 9.99


def main():
    rows = []
    for pair in PAIRS:
        df = D.bars(pair, "5min")
        pip, cost = D.pip_size(pair), S.COST[pair]
        o = df["o"]
        ny = df["ny_h"]
        for day in ("monthstart", "monthend"):
            for hh in range(24):
                for mm in (0, 30):
                    t = df.index[(df["tky_h"].values == hh) & (df["tky_m"].values == mm)]
                    if len(t) == 0:
                        continue
                    f = S.day_filters(df.loc[t], "tky")[day]
                    t = t[f]
                    for hold in (60, 120):
                        # 日付の変わり目にかかるものを除く
                        bad = np.zeros(len(t), bool)
                        for k in range(0, hold + 1, 30):
                            h = ny.reindex(t + pd.Timedelta(minutes=k)).values
                            bad |= (h >= 16) & (h <= 18)
                        tt = t[~bad]
                        raw = pd.Series((o.reindex(tt + pd.Timedelta(minutes=hold)).values - o.reindex(tt).values) / pip, index=tt).dropna()
                        if len(raw) < 60:
                            continue
                        des = raw[D.period_mask(raw.index, PERIODS[0][1])]
                        d = 1.0 if des.mean() > 0 else -1.0
                        r = d * raw - cost
                        ok = True
                        cells = []
                        for _, p in PERIODS:
                            x = r[D.period_mask(r.index, p)].values
                            if len(x) < 15 or (x - 0.5).mean() <= 0 or pf(x - 0.5) < 1.15:
                                ok = False
                            cells.append(f"{len(x)}回 {x.mean():+.2f} PF {pf(x):.2f}")
                        yr = r.groupby(r.index.year).mean()
                        pos = int((yr > 0).sum())
                        if ok and pos >= 10:
                            rows.append((pair, day, f"{hh}:{mm:02d}", hold, "買い" if d > 0 else "売り", cells, pos, len(yr)))
        print(pair, "done", file=sys.stderr, flush=True)
    out = ["# 月初・月末の需給の偏り（東京時間、コスト後 pips／回）", "",
           f"- 条件を満たしたもの：{len(rows)} 通り（3期間すべてで +0.5pips 込みでもプラス・PF ≥ 1.15、12年中10年以上プラス）", "",
           "| ペア | 日 | 東京時間 | 保有 | 向き | " + " | ".join(n for n, _ in PERIODS) + " | プラスの年 |", "|---|---|---|---|---|---|---|---|---|"]
    out += [f"| {r[0]} | {'月初' if r[1] == 'monthstart' else '月末'} | {r[2]} | {r[3]}分 | {r[4]} | " + " | ".join(r[5]) + f" | {r[6]}/{r[7]} |" for r in rows]
    text = "\n".join(out) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "month_flow_scan.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

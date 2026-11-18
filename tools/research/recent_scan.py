#!/usr/bin/env python3
"""直近を重視した全時間帯の探索（ユーザーの方針「昔より今が大事」）。

仮説 = 銘柄 × 時計（東京/ロンドン/NY）× 入る時刻（30分ごと）× 保有時間（30/60/120分）× 日の条件
- 2015〜21年は使わない。直近を3つの独立した期間に分ける：
  R1 = 2021年11月〜2024年10月、R2 = 2024年11月〜2025年10月、R3 = 2025年11月〜2026年11月
- 向きは R1 だけで決める。合格：R1・R2・R3 のそれぞれで、コスト（S.COST + 0.5 pips）を引いた損益の t 値が 2 以上。
  偶然だけで通る数の目安：仮説の数 × 0.046 × 0.023 × 0.023（約5万通りなら 1〜2通り）。
- NY 16:00〜18:59（日付の変わり目）にかかる時間帯と、週明けの最初の3時間は除く（full_scan.py と同じ）。
使い方: python3 tools/research/recent_scan.py  → reports/research/recent_scan.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
from full_scan import HOLDS, SLOT, CLOCKS, stats_vec, pf  # noqa: E402

PERIODS = (("2021-11-01", "2024-11-01"), ("2024-11-01", "2025-11-01"), ("2025-11-01", "2026-11-14"))
T_MIN = float(os.environ.get("AMS_RECENT_T", "2.0"))


def scan_pair(pair):
    rows, n_tests = [], 0
    df = D.bars(pair, "5min")
    pip, cost = D.pip_size(pair), S.COST[pair] + 0.5
    idx, o, ny_h = df.index, df["o"].values, df["ny_h"].values
    gap = np.r_[np.inf, np.diff(idx.values).astype("timedelta64[m]").astype(float)]
    wk = np.zeros(len(df), bool)
    for i in np.where(gap >= 30 * 60)[0]:
        wk[i:i + 36] = True
    masks = [D.period_mask(idx, p) for p in PERIODS]
    rets, pos = {}, np.arange(len(df))
    for hold in HOLDS:
        k = hold // 5
        j = pos + k
        ok = j < len(df)
        r = np.full(len(df), np.nan)
        same = (idx.values[j[ok]] - idx.values[pos[ok]]) == np.timedelta64(hold, "m")
        rr = (o[j[ok]] - o[pos[ok]]) / pip
        rr[~same] = np.nan
        r[ok] = rr
        bad = wk.copy()
        for s_ in range(0, k + 1):
            h = np.r_[ny_h[s_:], np.full(s_, -1)]
            bad |= (h >= 16) & (h <= 18)
        r[bad] = np.nan
        rets[hold] = r
    for clock in CLOCKS:
        hh, mm = df[f"{clock}_h"].values, df[f"{clock}_m"].values
        nsl = 1440 // SLOT
        slot = np.where(mm % SLOT == 0, (hh * 60 + mm) // SLOT, -1)
        filters = S.day_filters(df, clock)
        slot_idx = {sl: np.where(slot == sl)[0] for sl in range(nsl)}
        for fname, fm in filters.items():
            for sl in range(nsl):
                ii = slot_idx[sl]
                ii = ii[fm[ii]]
                parts = [ii[m[ii]] for m in masks]
                for hold in HOLDS:
                    r = rets[hold]
                    n_tests += 1
                    n1, m1, _ = stats_vec(r[parts[0]])
                    if n1 < 30 or m1 == 0:
                        continue
                    sign = 1.0 if m1 > 0 else -1.0
                    res = []
                    for p in parts:
                        net = sign * r[p] - cost
                        res.append(stats_vec(net) + (pf(net),))
                    if min(x[2] for x in res) < T_MIN or min(x[0] for x in res) < 20:
                        continue
                    rows.append({"pair": pair, "clock": clock, "time": f"{sl * SLOT // 60:02d}:{sl * SLOT % 60:02d}",
                                 "hold": hold, "filter": fname, "dir": "買い" if sign > 0 else "売り",
                                 **{f"r{k + 1}_{nm}": x[i] for k, x in enumerate(res) for i, nm in enumerate(("n", "net", "t", "pf"))}})
    print(pair, "done", file=sys.stderr, flush=True)
    return rows, n_tests


def main():
    from multiprocessing import Pool
    with Pool(3) as pool:
        parts = pool.map(scan_pair, D.PAIRS)
    df = pd.DataFrame([r for p in parts for r in p[0]])
    n = sum(p[1] for p in parts)
    lines = ["# 直近を重視した全時間帯の探索（`tools/research/recent_scan.py`）", "",
             f"仮説 {n:,} 通り。向きは R1（2021年11月〜2024年10月）で決め、R1・R2（2024年11月〜25年10月）・R3（2025年11月〜26年11月）のそれぞれで、"
             f"コスト（目安 + 0.5 pips）後の t 値が {T_MIN} 以上のものだけ。偶然だけで通る数の目安：{n * 0.046 * 0.023 * 0.023:.1f} 通り。", ""]
    if len(df):
        df["min_t"] = df[["r1_t", "r2_t", "r3_t"]].min(axis=1)
        df = df.sort_values("min_t", ascending=False)
        lines += ["| 銘柄 | 時計 | 時刻 | 保有 | 日 | 向き | R1 pips（t、回数） | R2 | R3 |", "|---|---|---|---|---|---|---|---|---|"]
        for _, r in df.iterrows():
            cells = [f"{r[f'r{k}_net']:+.2f}（t {r[f'r{k}_t']:.1f}、{int(r[f'r{k}_n'])}）" for k in (1, 2, 3)]
            lines.append(f"| {r.pair} | {r.clock} | {r.time} | {r.hold} | {r['filter']} | {r.dir} | " + " | ".join(cells) + " |")
    else:
        lines.append("合格はありませんでした。")
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reports", "research", "recent_scan.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""5分足で、1日のすべての時間帯（30分ごと）の値動きの偏りを、まとめて調べる。

仮説 = 銘柄 × 時計（東京/ロンドン/NY）× 入る時刻（30分ごと）× 保有時間（30/60/120分）× 日の条件
- 調べる数が多いので、偶然の当たりを減らすため、条件を厳しくする。
  - 設計期間：|t| ≥ 4 かつコスト込みでプラス
  - 検証期間：向きを固定したまま、コスト込みでプラス・PF 1.2 以上・t ≥ 2
  （これまでの教訓：検証期間でぎりぎりだったルールは、その後の期間で続かなかった）
- NY 16:00〜18:59（日付の変わり目）にかかる時間帯と、週明けの最初の3時間は除外する。
- 最終確認期間（2024年11月〜）は見ない。

使い方: python3 tools/research/full_scan.py  → reports/research/full_scan.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

HOLDS = [30, 60, 120]          # 分
CLOCKS = ["tky", "ldn", "ny"]
DES_T = 4.0


def stats_vec(x):
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 30:
        return n, 0.0, 0.0
    sd = x.std(ddof=1)
    return n, x.mean(), (x.mean() / sd * np.sqrt(n) if sd > 0 else 0.0)


def pf(x):
    x = x[~np.isnan(x)]
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return gp / gl if gl > 0 else 9.99


def scan_pair(pair):
    rows = []
    n_tests = 0
    df = D.bars(pair, "5min")
    pip = D.pip_size(pair)
    cost = S.COST[pair]
    idx = df.index
    o = df["o"].values
    ny_h = df["ny_h"].values
    # 週明け（前の足から30時間以上空いた足）から3時間以内
    gap = np.r_[np.inf, np.diff(idx.values).astype("timedelta64[m]").astype(float)]
    wk = np.zeros(len(df), bool)
    for i in np.where(gap >= 30 * 60)[0]:
        wk[i:i + 36] = True
    m_des = D.period_mask(idx, D.DESIGN)
    m_val = D.period_mask(idx, D.VALID)
    m_fin = D.period_mask(idx, D.FINAL)
    # 保有時間ごとの値動き（足が欠けていない場合だけ。日付の変わり目にかかるものは除外）
    rets = {}
    pos = np.arange(len(df))
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
        hh = df[f"{clock}_h"].values
        mm = df[f"{clock}_m"].values
        slot = np.where((mm == 0) | (mm == 30), hh * 2 + mm // 30, -1)
        filters = S.day_filters(df, clock)
        slot_idx = {sl: np.where(slot == sl)[0] for sl in range(48)}
        for fname, fm in filters.items():
            for sl in range(48):
                ii = slot_idx[sl]
                ii = ii[fm[ii]]
                des_i, val_i, fin_i = ii[m_des[ii]], ii[m_val[ii]], ii[m_fin[ii]]
                for hold in HOLDS:
                    r = rets[hold]
                    n_tests += 1
                    n, mean, t = stats_vec(r[des_i])
                    if n < 60 or abs(t) < DES_T:
                        continue
                    sign = 1.0 if mean > 0 else -1.0
                    d = sign * r[des_i] - cost
                    if np.nanmean(d) <= 0:
                        continue
                    v = sign * r[val_i] - cost
                    vn, vraw, _ = stats_vec(r[val_i])
                    vt = stats_vec(v)[2]
                    rows.append({"pair": pair, "clock": clock, "time": f"{sl // 2:02d}:{(sl % 2) * 30:02d}",
                                 "hold": hold, "filter": fname, "dir": "買い" if sign > 0 else "売り",
                                 "des_n": n, "des_mean": abs(mean), "des_t": abs(t), "des_pf": pf(d),
                                 "val_n": vn, "val_mean": sign * vraw if vn else 0.0, "val_t": vt,
                                 "val_net": np.nanmean(v) if vn else 0.0, "val_pf": pf(v) if vn else 0.0,
                                 "fin_n": int((~np.isnan(r[fin_i])).sum()), "fin_net": float(np.nanmean(sign * r[fin_i] - cost)) if len(fin_i) else 0.0,
                                 "fin_pf": pf(sign * r[fin_i] - cost) if len(fin_i) else 0.0})
    print(pair, "done", file=sys.stderr, flush=True)
    return rows, n_tests


def scan():
    from multiprocessing import Pool
    with Pool(3) as pool:
        parts = pool.map(scan_pair, D.PAIRS)
    rows = [r for p in parts for r in p[0]]
    return pd.DataFrame(rows), sum(p[1] for p in parts)


def main():
    res, n_tests = scan()
    out_dir = os.path.join(D.ROOT, "reports", "research")
    res.to_csv(os.path.join(out_dir, "full_scan_all.csv"), index=False)
    ok = (res["val_net"] > 0) & (res["val_pf"] >= 1.2) & (res["val_t"] >= 2.0) if len(res) else []
    passed = res[ok] if len(res) else res
    lines = ["# 5分足・全時間帯の偏りの探索", "",
             f"- 調べた仮説の数：{n_tests:,} 通り（銘柄 × 時計 × 30分ごとの時刻 × 保有 30/60/120分 × 日の条件）",
             f"- 設計期間で |t| ≥ {DES_T:.0f} かつコスト込みでプラス：**{len(res)} 通り**",
             f"- そのうち検証期間でも、コスト込みでプラス・PF 1.2 以上・t ≥ 2：**{len(passed)} 通り**",
             "- 最終確認期間（2024年11月〜）は見ていません。", "",
             "| 銘柄 | 時計 | 入る時刻 | 保有 | 日の条件 | 向き | 設計 回数 | 設計 平均pips | 設計 t | 設計 PF | 検証 回数 | 検証 平均pips | 検証 t | 検証 PF | 検証通過 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in res.sort_values("des_t", ascending=False).iterrows():
        mark = "○" if (r.val_net > 0 and r.val_pf >= 1.2 and r.val_t >= 2.0) else ""
        lines.append(f"| {r.pair} | {r.clock} | {r.time} | {r.hold}分 | {r['filter']} | {r.dir} | {r.des_n} | {r.des_mean:+.1f} | {r.des_t:.1f} | "
                     f"{r.des_pf:.2f} | {r.val_n} | {r.val_mean:+.1f} | {r.val_t:.1f} | {r.val_pf:.2f} | {mark} |")
    text = "\n".join(lines) + "\n"
    open(os.path.join(out_dir, "full_scan.md"), "w", encoding="utf-8").write(text)
    print("\n".join(lines[:6]))
    print("\n".join(l for l in lines[8:] if l.endswith("○ |")))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""値動きの小さい相場（低ボラティリティ）だけで使える偏りを探す。

2019〜2021年のような値動きの小さい年は、時刻ルールの利益が小さくなる。そこで、値動きが小さいときだけ
働くルールがあれば、弱い年を補える。
- 値動きの大きさ：1時間足の平均値幅（24本）÷ その500本平均。設計期間の下位3分の1を「小さい」とする。
- 仮説：銘柄 × 入る時刻（UTC の時）× 保有 1/2/4 時間 × 「直前 N 時間（2/4/8）の動き」に逆張り または 順張り
- 設計期間で |t| ≥ 4 かつコスト後プラス、検証期間でもコスト後プラス・PF ≥ 1.2・t ≥ 2 を残す。
- 日付の変わり目（NY 16:00〜18:59）と週明けは除外。最終確認期間は見ない。

使い方: python3 tools/research/lowvol_scan.py  → reports/research/lowvol_scan.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402


def stats(x):
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 60:
        return n, 0.0, 0.0, 0.0
    sd = x.std(ddof=1)
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return n, x.mean(), (x.mean() / sd * np.sqrt(n) if sd > 0 else 0.0), (gp / gl if gl > 0 else 9.99)


def main():
    rows, n_tests = [], 0
    for pair in D.PAIRS:
        df = D.bars(pair, "1h")
        pip = D.pip_size(pair)
        cost = S.COST[pair]
        rng = (df["h"] - df["l"]).rolling(24).mean().shift(1)
        rel = rng / rng.rolling(500).mean()
        des = D.period_mask(df.index, D.DESIGN)
        val = D.period_mask(df.index, D.VALID)
        thr = np.nanquantile(rel[des], 1 / 3)
        low = (rel <= thr).values
        hour = df.index.hour.values
        c = df["c"].values
        for hold in (1, 2, 4):
            r = S.window_returns(df, hold, pip)
            r[S.rollover_mask(df, hold)] = np.nan
            for back in (2, 4, 8):
                prev = (df["o"].values - np.r_[np.full(back, np.nan), c[:-back]]) / pip   # 直前 back 時間の動き（確定足まで）
                sig = np.sign(prev)
                for mode, sgn in (("逆張り", -1.0), ("順張り", 1.0)):
                    pnl = sgn * sig * r - cost
                    for h0 in range(24):
                        m = low & (hour == h0) & (sig != 0)
                        n_tests += 1
                        n, mean, t, pf = stats(pnl[m & des])
                        if n < 60 or t < 4.0:
                            continue
                        vn, vmean, vt, vpf = stats(pnl[m & val])
                        rows.append((pair, h0, hold, back, mode, n, mean, t, pf, vn, vmean, vt, vpf))
        print(pair, "done", file=sys.stderr, flush=True)
    out = ["# 値動きの小さい相場だけの偏りの探索（1時間足）", "", f"- 調べた仮説：{n_tests:,} 通り",
           f"- 設計期間で t ≥ 4 かつコスト後プラス：{len(rows)} 通り", "",
           "| 銘柄 | 入る時刻（UTC） | 保有 | 直前の動き | 向き | 設計 回数 | 設計 損益 | 設計 t | 設計 PF | 検証 回数 | 検証 損益 | 検証 t | 検証 PF | 検証通過 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: -x[7]):
        ok = "○" if (r[10] > 0 and r[12] >= 1.2 and r[11] >= 2) else ""
        out.append(f"| {r[0]} | {r[1]}時 | {r[2]}時間 | {r[3]}時間 | {r[4]} | {r[5]} | {r[6]:+.2f} | {r[7]:.1f} | {r[8]:.2f} | {r[9]} | {r[10]:+.2f} | {r[11]:.1f} | {r[12]:.2f} | {ok} |")
    text = "\n".join(out)
    open(os.path.join(D.ROOT, "reports", "research", "lowvol_scan.md"), "w", encoding="utf-8").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""長期の層の改良：金利の「変化」と長短の金利差を材料にした手法（27年分、日付・時刻のクセは使わない）。

- 金利の勢い：短期金利の差（基準の通貨 − 相手の通貨）が、過去 k か月で広がったペアを買い、縮んだペアを売る（利上げが進む通貨を買う）。
- 10年金利の勢い：同じことを10年国債の利回りの差で。
- 10年金利の差（水準）：10年金利の高い側を持つ。
- 長短の金利差：（10年 − 3か月）の差。
- 金利差（水準）と金利の勢いの両方が同じ向きのときだけ持つ形、など。
- 月次のデータは1か月遅らせて使う（その月の平均は、月が終わるまで分からないため）。
使い方: python3 tools/research/macro_signals.py  → reports/research/macro_signals.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import styles_long as SL  # noqa: E402


def pair_diff(m, index, pairs, lag=1):
    d = F.monthly_to_daily(m, index, lag)
    return pd.DataFrame({p: d[p[:3]] - d[p[3:]] for p in pairs}, index=index)


def main():
    px, carry, cost = SL.load()
    pairs = list(px.columns)
    vol = px.pct_change().rolling(60, min_periods=40).std()
    r3 = F.rates_monthly()
    y10 = F.yields10_monthly()
    lines = ["# 長期の層の改良：金利の変化・長短の金利差（`tools/research/macro_signals.py`）", "",
             "各セル：年率シャープ。右の4列は 2000年以降の全体：シャープ、年率（値動きを年10%にそろえたとき）、最大の下落、プラスの年。", "",
             "| 手法 | " + " | ".join(p[0] for p in SL.PER) + " | 全体 | 年率 | 最大の下落 | プラスの年 |",
             "|---|" + "---|" * (len(SL.PER) + 4)]
    R = {}

    def add(key, label, sig, rb=5):
        w = SL.norm((sig / vol).fillna(0.0))
        r = SL.voltarget(SL.pnl(SL.hold(w, rb), px, carry, cost))
        R[key] = r
        lines.append(SL.row(label, r))

    lvl = np.sign(carry).where(carry.abs() - SL.MARKUP >= 1.0, 0.0)
    add("carry", "（参考）金利差の水準（差が年1%以上）", lvl)
    for k in (1, 3, 6, 12):
        d = pair_diff(r3 - r3.shift(k), px.index, pairs)
        add(f"rm{k}", f"金利の勢い：短期金利の差の {k} か月の変化の向き", np.sign(d).where(d.abs() >= 0.10, 0.0))
    for k in (1, 3, 6, 12):
        d = pair_diff(y10 - y10.shift(k), px.index, pairs)
        add(f"ym{k}", f"10年金利の勢い：10年金利の差の {k} か月の変化の向き", np.sign(d).where(d.abs() >= 0.10, 0.0))
    d10 = pair_diff(y10, px.index, pairs)
    add("c10", "10年金利の差の水準（差が年1%以上）", np.sign(d10).where(d10.abs() >= 1.0, 0.0))
    ts = pair_diff(y10 - r3, px.index, pairs)
    add("slope+", "長短の金利差が大きい側を買う", np.sign(ts).where(ts.abs() >= 0.5, 0.0))
    add("slope-", "長短の金利差が小さい側を買う", -np.sign(ts).where(ts.abs() >= 0.5, 0.0))
    # 水準と勢いの組み合わせ
    for k in (3, 6):
        d = pair_diff(r3 - r3.shift(k), px.index, pairs)
        mom = np.sign(d).where(d.abs() >= 0.10, 0.0)
        add(f"lv_rm{k}", f"金利差の水準と、{k} か月の金利の勢いが同じ向きのときだけ", lvl.where(lvl == mom, 0.0))
        add(f"lv_notagainst{k}", f"金利差の水準（勢いが逆向きのペアは外す、{k} か月）", lvl.where(lvl != -mom, 0.0))
        dy = pair_diff(y10 - y10.shift(k), px.index, pairs)
        momy = np.sign(dy).where(dy.abs() >= 0.10, 0.0)
        add(f"lv_ym{k}", f"金利差の水準と、{k} か月の10年金利の勢いが同じ向きのときだけ", lvl.where(lvl == momy, 0.0))
    out = os.path.join(SL.ROOT, "reports", "research", "macro_signals.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    c = pd.DataFrame(R)
    c = c[c.index >= "2000-01-01"]
    print("\ncorr with carry:", {k: round(c["carry"].corr(c[k]), 2) for k in c.columns if k != "carry"})


if __name__ == "__main__":
    main()

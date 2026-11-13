#!/usr/bin/env python3
"""ECB（ロンドン 13:15）と WM/R（ロンドン 16:00）のフィキシング：フィキシング前の値動きで、後の戻しが使えるか。

東京仲値で効いた考え方（Krohn ほか 2024：フィキシング前の動きは、後で戻される）を、ロンドンのフィキシングに当てはめる。
- フィキシング前の動き：フィキシングの 30分前 / 60分前 から フィキシングまで（÷ 1時間足の平均値幅）
- フィキシング後：その動きと逆向きに入り、30 / 60 / 120 分後に決済（コスト後）
- 前の動きの大きさで3つに分け（境目は設計期間で決める）、検証期間にそのまま当てはめる。

使い方: python3 tools/research/fix_reversal_eu.py  → reports/research/fix_reversal_eu.md
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
    if len(x) < 30:
        return f"{len(x)}回"
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return f"{len(x)}回 {x.mean():+.2f} PF {gp / gl if gl > 0 else 9.99:.2f} t {x.mean() / x.std(ddof=1) * np.sqrt(len(x)):.1f}"


def main():
    out = ["# ロンドンのフィキシング前の動きと、フィキシング後の戻し（コスト後の pips）", "",
           "「上1/3」はフィキシング前に大きく上げた日で、フィキシング後に売る。「下1/3」は大きく下げた日で、フィキシング後に買う。", ""]
    hits = []
    for pair in ("EURUSD", "GBPUSD", "USDJPY", "EURJPY", "GBPJPY"):
        df = D.bars(pair, "5min")
        o = df["o"]
        pip = D.pip_size(pair)
        cost = S.COST[pair]
        h1 = D.bars(pair, "1h")
        rng = (h1["h"] - h1["l"]).rolling(24).mean().shift(1)
        for hh, mm, name in ((13, 15, "ECB"), (16, 0, "WM/R")):
            fix = df.index[(df["ldn_h"].values == hh) & (df["ldn_m"].values == mm)]
            p = lambda t: o.reindex(t).values  # noqa: E731
            a = rng.reindex(fix.floor("1h")).values / pip
            des = D.period_mask(fix, D.DESIGN)
            val = D.period_mask(fix, D.VALID)
            out += [f"## {pair} {name}", "", "| 前の時間 | 後の保有 | 上1/3 → 売り（設計） | 上1/3 → 売り（検証） | 下1/3 → 買い（設計） | 下1/3 → 買い（検証） |",
                    "|---|---|---|---|---|---|"]
            for pre in (30, 60):
                z = (p(fix) - p(fix - pd.Timedelta(minutes=pre))) / pip / a
                lo, hi = np.nanquantile(z[des], [1 / 3, 2 / 3])
                for hold in (30, 60, 120):
                    post = (p(fix + pd.Timedelta(minutes=hold)) - p(fix)) / pip
                    up = -post - cost
                    dn = post - cost
                    mu, md = z > hi, z <= lo
                    out.append(f"| {pre}分 | {hold}分 | {st(up[des & mu])} | {st(up[val & mu])} | {st(dn[des & md])} | {st(dn[val & md])} |")
                    for lab, x, m in (("上→売り", up, mu), ("下→買い", dn, md)):
                        d, v = x[des & m], x[val & m]
                        d, v = d[~np.isnan(d)], v[~np.isnan(v)]
                        if len(d) > 30 and len(v) > 30:
                            td = d.mean() / d.std(ddof=1) * np.sqrt(len(d))
                            pv = v[v > 0].sum() / max(-v[v < 0].sum(), 1e-9)
                            if td >= 3 and v.mean() > 0 and pv >= 1.2:
                                hits.append(f"- {pair} {name} 前{pre}分 後{hold}分 {lab}：設計 {st(d)} ／ 検証 {st(v)}")
            out.append("")
    out = ["# 候補（設計 t ≥ 3、検証でコスト後プラス・PF ≥ 1.2）", ""] + (hits or ["なし"]) + [""] + out
    text = "\n".join(out)
    open(os.path.join(D.ROOT, "reports", "research", "fix_reversal_eu.md"), "w", encoding="utf-8").write(text + "\n")
    print("\n".join(out[:len(hits) + 4]))


if __name__ == "__main__":
    main()

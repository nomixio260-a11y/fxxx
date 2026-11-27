#!/usr/bin/env python3
"""研究：売られすぎの戻りの強さは、相場の状態で変わるか（変わるなら、建玉の大きさを状態で変える）。

- 仮説（公表済み）：短期の戻りの利益は、「売りたい人の相手をして、流動性を提供することへの対価」であり、相場が荒れているとき（VIX が高いとき）ほど
  大きい（Nagel「Evaporating Liquidity」2012年。データは 2010年まで）。→ 2011年以降が「公表後」。
- 確かめ方（米国3指数、現物の日足、2000年10月〜2026年11月。建玉は HAR 型の見積もりで決める = どの状態でも、持っているときの値動きの大きさは同じ）：
  1 状態ごとの「持った日の、値動きの大きさあたりの利益」：
    a VIX の水準（その日までの過去の分布での位置。3つに分ける。VIX は1日前の値）
    b 値動きの見積もり（HAR）の水準（同じく過去の分布での位置。値段だけで計算できる）
    c 200日の平均より上か下か
  2 状態で建玉を変える形（事前に決めた1通りだけ）：低い状態 0.5 倍・中 1.0 倍・高い状態 1.5 倍。全期間と 2011年以降で、シャープ・最悪の日を比べる。
使い方: python3 tools/research/index_regime.py  → reports/research/index_regime.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_stop as IS  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252


def past_rank(s, minp=500):
    """その日までの過去の分布での位置（0〜1）。その日の値までしか使わない。"""
    return s.expanding(min_periods=minp).rank(pct=True)


def main():
    vix = Y.fetch("VIX")["close"]
    rows = []
    sets = {}
    for name in IRK.US3:
        d, st, rate, div, vols, above = IRK.load(name)
        sg = IS.har_sigma(d)
        n = st.sum(axis=1)
        vx = vix.reindex(vix.index.union(d.index)).ffill(limit=3).reindex(d.index).shift(1)      # 1日前の VIX
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
        fin = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
        nxt = (d["close"].pct_change() + fin).shift(-1)                                              # 翌日の損益（建玉1あたり、持ち越しのコスト込み）
        df = pd.DataFrame({"name": name, "n": n, "y": nxt / sg, "vixr": past_rank(vx), "sigr": past_rank(sg), "above": above.astype(float)})
        rows.append(df[df.index >= IRK.START])
        sets[name] = (d, st, rate, div, sg, n, past_rank(vx), past_rank(sg), above)
    P = pd.concat(rows).dropna(subset=["y"])
    lines = ["# 研究：売られすぎの戻りの強さと、相場の状態（`tools/research/index_regime.py`）", "",
             "米国3指数、2000年10月〜2026年11月。値は「持った日の翌日の損益 ÷ その日の値動きの見積もり」（1 = 1日の標準偏差ぶん）。"
             "ルールが1つ以上出ている日だけ。t 値は、日付ごとにまとめてから計算。", ""]

    def cell(x):
        if len(x) < 30:
            return "—"
        by = x.groupby(level=0).mean()
        return f"{x.mean():+.3f}（t {by.mean() / by.std() * np.sqrt(len(by)):+.1f}、{len(x)} 件）"
    for title, col, cuts in (("a VIX の水準（1日前の値。過去の分布での位置）", "vixr", ((0, 1 / 3, "低い"), (1 / 3, 2 / 3, "中"), (2 / 3, 1.01, "高い"))),
                             ("b 値動きの見積もりの水準（過去の分布での位置）", "sigr", ((0, 1 / 3, "低い"), (1 / 3, 2 / 3, "中"), (2 / 3, 1.01, "高い"))),
                             ("c 200日の平均", "above", ((0.5, 1.5, "上"), (-0.5, 0.5, "下")))):
        lines += [f"## 1{title}", "", "| 状態 | 全期間：ルール1つ以上 | 2つ以上 | 2011年〜（公表後）：1つ以上 | 2つ以上 | 参考：ルールなしの日（全期間） |", "|---|---|---|---|---|---|"]
        for lo, hi, lab in cuts:
            m = (P[col] >= lo) & (P[col] < hi)
            post = P.index >= "2011-01-01"
            lines.append(f"| {lab} | {cell(P['y'][m & (P['n'] >= 1)])} | {cell(P['y'][m & (P['n'] >= 2)])} | {cell(P['y'][m & post & (P['n'] >= 1)])} | "
                         f"{cell(P['y'][m & post & (P['n'] >= 2)])} | {cell(P['y'][m & (P['n'] == 0)])} |")
            print(lines[-1], flush=True)
        lines.append("")
    # 2 状態で建玉を変える
    head = "| 形 | 全期間：シャープ | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 2000〜10 のシャープ | 2011年〜のシャープ | 2011年〜の最悪の日 |"
    lines += ["## 2 状態で建玉を変える（低い 0.5 倍・中 1.0 倍・高い 1.5 倍。全期間の値動きを年10%にそろえる）", "", head, "|---|" + "---|" * 7]
    for label, key in (("変えない", None), ("VIX の水準で変える", 6), ("値動きの見積もりの水準で変える", 7), ("逆（低い 1.5 倍・高い 0.5 倍）：VIX", -6),
                       ("逆（低い 1.5 倍・高い 0.5 倍）：値動きの見積もり", -7), ("200日の平均より下では 0.5 倍", 8), ("200日の平均より下では持たない", 9)):
        parts = []
        for name, t in sets.items():
            d, st, rate, div, sg, n = t[:6]
            mult = pd.Series(1.0, index=d.index)
            if key in (6, 7, -6, -7):
                rk = t[abs(key)]
                lo_m, hi_m = (0.5, 1.5) if key > 0 else (1.5, 0.5)
                mult = pd.Series(np.where(rk < 1 / 3, lo_m, np.where(rk >= 2 / 3, hi_m, 1.0)), index=d.index).where(rk.notna(), 1.0)
            elif key == 8:
                mult = pd.Series(np.where(t[8], 1.0, 0.5), index=d.index)
            elif key == 9:
                mult = pd.Series(np.where(t[8], 1.0, 0.0), index=d.index)
            w = (mult * n / 3.0 * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0) / len(sets)
            r, _, _ = IS.run(d, w, sg, rate, div, None, "close")
            parts.append(r)
        rr = pd.concat(parts, axis=1, sort=True).fillna(0.0).sum(axis=1)
        rr = rr[rr.index >= IRK.START]
        z = rr * (0.10 / (rr.std() * np.sqrt(ANN)))

        def sh(x):
            return x.mean() / x.std() * np.sqrt(ANN)
        eq = (1 + z).cumprod()
        q = z.quantile(0.01)
        a, b = z[z.index < "2011-01-01"], z[z.index >= "2011-01-01"]
        lines.append(f"| {label} | {sh(z):+.2f} | {z.min() * 100:.1f}%（{z.idxmin().date()}） | {z[z <= q].mean() * 100:.2f}% | {(eq / eq.cummax() - 1).min() * 100:.0f}% | "
                     f"{sh(a):+.2f} | {sh(b):+.2f} | {b.min() * 100:.1f}% |")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_regime.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

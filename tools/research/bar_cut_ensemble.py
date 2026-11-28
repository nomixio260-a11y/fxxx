#!/usr/bin/env python3
"""研究：日足の区切りを等間隔に複数重ねると、戻りの層は良くなるか（106章）。特定の時刻に頼らない形の検証。

- 今の形：業者の日足（区切りは NY 17時）で1日1回だけ判定する。
- 候補：区切りを等間隔にずらした形（12時間おきに2つ／6時間おきに4つ／3時間おきに8つ）を、同じ資金で等分に持つ。
  判定の回数が増え、1つの時刻の値段に頼らなくなる。区切りは「等間隔」だけを試す（成績の良い時刻を選ぶことは、時刻のクセに頼ることになるので、しない）。
- データと計算は bar_cut_robustness.py と同じ（S&P500・NASDAQ100 の1分足、2011年9月〜2026年10月、EA と同じ形、ルール1つ分 8.75%、コスト込み）。
- 区切りが違うと、日々の損益を測る時刻がずれる。ずれの影響を除くため、週ごとの損益で比べる。
- 判定（結果を見る前に決めた）：等間隔の組み合わせのどれかが、今の形より、シャープが前半・後半の両方で高く、最大の下落（週ごと）が浅いこと。
使い方: python3 tools/research/bar_cut_ensemble.py  → reports/research/bar_cut_ensemble.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AMS_OANDA", "1")
import bar_cut_robustness as BC  # noqa: E402
import fred_data as F  # noqa: E402
import lot_rounding as LR  # noqa: E402
import sleeves_ea_mimic as M  # noqa: E402

CUTS = (0, 3, 6, 9, 12, 15, 18, 21)
SETS = (("今の形（NY 17時だけ）", (0,)), ("12時間おきに2つ", (0, 12)), ("6時間おきに4つ", (0, 6, 12, 18)), ("3時間おきに8つ", CUTS))


def main():
    eqs = {}
    orig = M.server_m1
    try:
        for k in CUTS:
            M.server_m1 = lambda pair, kk=k: BC.shifted(pair, kk)
            eqs[k] = LR.simulate("floor", "2011-09-01", "2026-10-30", 1e10, 8.75, return_eq=True)
            print(k, len(eqs[k]), flush=True)
    finally:
        M.server_m1 = orig
    W = pd.DataFrame({k: v.resample("W-FRI").last().pct_change() for k, v in eqs.items()}).dropna()
    sh = lambda x: x.mean() / x.std() * np.sqrt(52)          # noqa: E731
    h = pd.Timestamp("2019-04-01")
    c = W.corr()
    off = c.values[np.triu_indices(len(CUTS), 1)]
    lines = ["# 研究：日足の区切りを等間隔に重ねる（`tools/research/bar_cut_ensemble.py`）", "",
             "S&P500・NASDAQ100 の1分足、2011年9月〜2026年10月。週ごとの損益で比べる。", "",
             f"- 区切りの違う形どうしの、週ごとの損益の相関：平均 {off.mean():+.2f}（{off.min():+.2f} 〜 {off.max():+.2f}）。",
             "- 区切りごとのシャープ（NY の時刻）：" + "、".join(f"{(17 - k) % 24}時 {sh(W[k]):+.2f}" for k in CUTS), "",
             "| 形 | シャープ | 前半（〜2019年3月） | 後半 | 口座の値動き（年） | 最大の下落（週ごと） | 最悪の週 | 判定 |", "|---|---|---|---|---|---|---|---|"]
    base = None
    for lab, ks in SETS:
        e = W[list(ks)].mean(axis=1)
        eq = (1 + e).cumprod()
        st = dict(a=sh(e[e.index < h]), b=sh(e[e.index >= h]), dd=(eq / eq.cummax() - 1).min())
        if base is None:
            base, verdict = st, "—"
        else:
            verdict = "**合格**" if (st["a"] > base["a"] and st["b"] > base["b"] and st["dd"] > base["dd"]) else "不合格"
        lines.append(f"| {lab} | {sh(e):+.2f} | {st['a']:+.2f} | {st['b']:+.2f} | {e.std() * np.sqrt(52) * 100:.1f}% | {st['dd'] * 100:.0f}% | {e.min() * 100:.1f}% | {verdict} |")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "bar_cut_ensemble.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

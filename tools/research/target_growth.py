#!/usr/bin/env python3
"""確認：「1年で元金の3倍・4倍（+200%・+300%）」は、株価指数の売られすぎの戻りで、どのくらいの確率で起きるか。

- 層の日次の損益（値動き年10%にそろえたもの。tools/research/sleeves.py が data/cache に保存）を、20日のかたまりで並べ替えて、1年分の道筋を2万通り作る。
  建玉を k 倍（値動きは 年10% × k）にしたときの、1年後の結果の分布を出す。口座が元金の2割を下回ったら、証拠金不足で続けられないとみなす。
- 理屈：リスクあたりの利益（シャープ）が S の手法は、建玉をどれだけ大きくしても、長い目での伸びは 年 S²/2（対数）が上限
  （建玉を大きくしすぎると、負けたときの減りが勝ったときの増えを上回る）。S = 0.6 なら年 +20% ほど、S = 1.0 でも年 +65% ほどが、中央値の上限。
  1年で4倍（対数で 1.39）を「ふつうに」出すには、S が 1.7 以上必要。
使い方: python3 tools/research/target_growth.py  → reports/research/target_growth.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import fred_data as F  # noqa: E402


def sim(base, k, rng, n_paths=20000, days=252, block=20):
    n = len(base)
    starts = rng.integers(0, n - block, size=(n_paths, days // block + 1))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_paths, -1)[:, :days]
    eq = np.cumprod(np.maximum(1.0 + k * base[idx], 0.0), axis=1)
    alive = (eq > 0.2).all(axis=1)
    end = np.where(alive, eq[:, -1], np.minimum.accumulate(eq, axis=1)[:, -1])
    return end, 1 - alive.mean()


def main():
    S = pd.read_parquet(os.path.join(D.CACHE, "sleeves_returns.parquet"))["指数の戻り（米国3指数）"]
    rng = np.random.default_rng(1)
    lines = ["# 確認：1年で元金の3倍・4倍になる確率（`tools/research/target_growth.py`）", "",
             "株価指数の売られすぎの戻り（米国3指数）の日次の損益を並べ替えた、2万通りの1年。k = 建玉の倍率（値動きは 年10% × k）。", ""]
    for name, base in (("26年分（2000年10月〜2026年11月）", S.values), ("直近3年分（2023年11月〜）だけ", S["2023-11-01":].values)):
        sh = base.mean() / base.std() * np.sqrt(252)
        lines += [f"## 元にした期間：{name}（年率シャープ {sh:+.2f}。伸びの上限の目安 年 {(np.exp(sh * sh / 2) - 1) * 100:+.0f}%）", "",
                  "| 値動き（年） | 1年後の中央値 | +200% 以上（3倍） | +300% 以上（4倍） | 半分以下になる | 続けられなくなる |", "|---|---|---|---|---|---|"]
        for k in (1, 2, 3, 5, 8, 12, 20):
            end, ruin = sim(base, k, rng)
            lines.append(f"| {10 * k}% | {np.median(end) * 100 - 100:+.0f}% | {(end >= 3).mean() * 100:.1f}% | {(end >= 4).mean() * 100:.1f}% | {(end <= 0.5).mean() * 100:.1f}% | {ruin * 100:.1f}% |")
        lines.append("")
    out = os.path.join(F.ROOT, "reports", "research", "target_growth.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""確認：金利差の層の利益は、どの通貨から出ていたのか（ペアの選び方を変えて比べる）。

- carry_long.py の A1（差が年1%以上のペアをすべて持つ）と EA の形を、ペアの範囲だけを変えて計算する。
  いまの17ペア／主要8通貨のすべての組み合わせ（28ペア）／円のペアだけ／スイスフランのペアを除く／円のペアを除く。
- 円のペアを除くと利益が消えるなら、この27年の「金利差の利益」は、実質的に「円を売る」取引の利益だったことになる。
使い方: python3 tools/research/carry_universe.py  → reports/research/carry_universe.md
"""
import itertools
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carry_breadth as CB  # noqa: E402
import carry_long as CL  # noqa: E402
import fred_data as F  # noqa: E402
import styles_long as SL  # noqa: E402


def main():
    v, rate = CB.load()
    order = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]
    all28 = [a + b for a, b in itertools.combinations(order, 2)]
    sets = (("いまの17ペア", F.PAIRS), ("主要8通貨のすべての組み合わせ（28ペア）", all28), ("円のペアだけ（7ペア）", [p for p in all28 if "JPY" in p]),
            ("28ペアからスイスフランのペアを除く（21ペア）", [p for p in all28 if "CHF" not in p]), ("28ペアから円のペアを除く（21ペア）", [p for p in all28 if "JPY" not in p]),
            ("28ペアから円とスイスフランのペアを除く（15ペア）", [p for p in all28 if "JPY" not in p and "CHF" not in p]))
    lines = ["# 確認：金利差の層の利益は、どの通貨から出ていたのか（`tools/research/carry_universe.py`）", "",
             "各セル：年率シャープ（5通りの入れ替えのずれの平均。括弧内は最小〜最大）。右の5列は 2000年以降。コスト・スワップ（上乗せ 年1%）込み。", "",
             "| ペアの範囲・形 | " + " | ".join(p[0] for p in SL.PER) + " | 全体 | 年率 | 最大の下落 | 最悪の年 | プラスの年 |", "|---|" + "---|" * (len(SL.PER) + 5)]
    for label, pairs in sets:
        px = pd.DataFrame({p: v[p[:3]] / v[p[3:]] for p in pairs})
        carry = pd.DataFrame({p: rate[p[:3]] - rate[p[3:]] for p in pairs})
        cost = pd.DataFrame({p: pd.Series(CB.COST_CCY[p[:3]] + CB.COST_CCY[p[3:]], index=px.index) for p in pairs})
        for fl, kw in (("すべて持つ（A1）", dict(thr=1.0)), ("EA の形", dict(thr=1.0, trend=60, topk=5, crash=2.0))):
            line, _ = CL.summarize(f"{label}：{fl}", CL.run(px, carry, cost, **kw))
            lines.append(line)
            print(line, flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "carry_universe.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

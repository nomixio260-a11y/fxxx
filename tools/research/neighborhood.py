#!/usr/bin/env python3
"""今の10ルールの「入る時刻」と「保有時間」を前後にずらしたときの成績（1分足、損切りは今の幅、コスト +0.5 pips 込み、pips／回）。
今の値が、たまたま当たった1点（崩れやすい）なのか、広い安定した範囲の中（崩れにくい）なのかを確かめる。
- 各セル：4つの期間（2015〜21年／5年の前半／24/11〜25/10／直近1年）の平均のうち、いちばん悪い期間の値と、4期間の平均。
- 仲値（9:55）など、時刻そのものに理由があるルールは、入る時刻をずらすと別のルールになる。保有時間のずれを主に見る。
使い方: python3 tools/research/neighborhood.py  → reports/research/neighborhood.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
import sl_width as W  # noqa: E402

ENTRY_OFF = [-10, -5, 0, 5, 10]
HOLD_OFF = [-30, -15, 0, 15, 30]


def shifted(hh, mm, off):
    m = (hh * 60 + mm + off) % 1440
    return m // 60, m % 60


def main():
    lines = ["# 入る時刻と保有時間をずらしたときの成績（1分足、今の損切り、コスト +0.5 pips 込み、pips／回）", "",
             "各セル：4期間のうち最も悪い期間の平均 ／ 4期間の平均。行＝入る時刻のずれ（分）、列＝保有時間のずれ（分）。中央が今の値。", ""]
    m1c = {}
    summary = []
    for name, pair, clock, hh, mm, hold, sign, filt, sl0, pre, cut, early in W.RULES:
        if pair not in m1c:
            m1c[pair] = pd.read_parquet(os.path.join(D.CACHE, f"{pair}_M1.parquet"))
        m1 = m1c[pair]
        pip, cost = D.pip_size(pair), S.COST[pair] + 0.5
        lines += [f"## {name}（{pair} {clock.upper()} {hh:02d}:{mm:02d} から {hold} 分）", "",
                  "| 入る時刻＼保有 | " + " | ".join(f"{h:+d}" for h in HOLD_OFF) + " |", "|---|" + "---|" * len(HOLD_OFF)]
        grid = {}
        for eo in ENTRY_OFF:
            h2, m2 = shifted(hh, mm, eo)
            t = W.entries(pair, clock, h2, m2, filt, pre, sign)
            cells = []
            for ho in HOLD_OFF:
                hd = hold + ho
                if hd < 10 or (cut and hd <= cut[0]):
                    cells.append("—")
                    continue
                r, _ = W.simulate(m1, t, hd, sign, sl0, cut, early, pip)
                s = pd.Series(r - cost, index=t).dropna()
                per = [s[(s.index >= a) & (s.index < b)].mean() for _, a, b in W.PER]
                grid[(eo, ho)] = (min(per), float(np.mean(per)))
                txt = f"{min(per):+.2f} ／ {np.mean(per):+.2f}"
                cells.append(f"**{txt}**" if eo == 0 and ho == 0 else txt)
            lines.append(f"| {eo:+d} | " + " | ".join(cells) + " |")
        cur = grid[(0, 0)]
        near = [v for k, v in grid.items() if abs(k[0]) <= 5 and abs(k[1]) <= 15 and k != (0, 0)]
        holdrow = [grid[(0, h)] for h in HOLD_OFF if (0, h) in grid and h != 0]
        summary.append((name, cur, np.mean([v[1] for v in near]), sum(v[0] > 0 for v in near), len(near),
                        np.mean([v[1] for v in holdrow]), sum(v[0] > 0 for v in holdrow), len(holdrow)))
        lines.append("")
        print(f"{name} done", flush=True)
    lines += ["## まとめ", "",
              "| ルール | 今：最悪の期間／平均 | 近く（入る時刻 ±5分・保有 ±15分）の平均 | 近くで4期間ともプラス | 保有だけずらした平均 | 保有だけで4期間ともプラス |",
              "|---|---|---|---|---|---|"]
    for name, cur, nm, npos, nn, hm, hpos, hn in summary:
        lines.append(f"| {name} | {cur[0]:+.2f}／{cur[1]:+.2f} | {nm:+.2f} | {npos}/{nn} | {hm:+.2f} | {hpos}/{hn} |")
    out = os.path.join(W.ROOT, "reports", "research", "neighborhood.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

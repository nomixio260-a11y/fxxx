#!/usr/bin/env python3
"""バックテストの結果を、5年の前半（2021/11〜2024/10）と後半（2024/11〜）に分けて比べる。

それぞれの半分で、月ごとの損益率から「その半分だけで運用した場合の増え方（倍率）」を計算する。
（後半は残高が大きいので、金額のままでは比べられないため）

使い方: python3 tools/halves.py 0305 0306 ...
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def summary(run):
    t = open(os.path.join(ROOT, "reports", "runs", f"{run}.txt"), encoding="utf-8").read()
    v = [(k, float(x)) for k, x in (s.split(":") for s in re.search(r"^MONTHLY (.*)$", t, re.M).group(1).split(",") if ":" in s)]
    out = []
    for name, lo, hi in (("前半", "2021-11", "2024-10"), ("後半", "2024-11", "2099-12"), ("5年", "2021-11", "2099-12")):
        p = [x for k, x in v if lo <= k <= hi]
        if not p:
            continue
        g = 1.0
        peak, dd = 1.0, 0.0
        for x in p:
            g *= 1 + x / 100
            peak = max(peak, g)
            dd = max(dd, 1 - g / peak)
        out.append(f"{name}: {g:5.2f}倍 月平均{sum(p) / len(p):+5.2f}% 負け月{sum(x < 0 for x in p) / len(p) * 100:3.0f}% "
                   f"+5%以上{sum(x >= 5 for x in p) / len(p) * 100:3.0f}% 最悪{min(p):+5.1f}% DD{dd * 100:3.0f}%")
    return out


if __name__ == "__main__":
    for r in sys.argv[1:]:
        print(r, *summary(r), sep="\n  ")

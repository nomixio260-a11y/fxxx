#!/usr/bin/env python3
"""確認：通貨3つの組み合わせ（為替の持ち高がゼロになる3つのペア）で、スワップの合計がプラスになる組がないか。

- もしあれば、値動きに関係なくスワップだけを受け取れる（値動きの予想がいらない、確実な利益）。
- デモ口座のログ（reports/live/logs/*.log）に残っている、OANDA の実際のスワップの値を使う。
  スワップは「ポイント」で示される。年率 % = スワップ × 1ポイントの大きさ × 365 ÷ 値段 × 100。
- 複数日分がまとめて付く日の値は使わない（USDCAD の 2026年11月27日の値は3日分なので、11月20日の値を使う）。
使い方: python3 tools/research/swap_triangle.py  → reports/research/swap_triangle.md
"""
import glob
import itertools
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402

PAT = re.compile(r"金利差＋トレンド：([A-Z]{6}) .*?口座のスワップ（方式=(\d)）買い (-?[\d.]+) / 売り (-?[\d.]+)")


def read_swaps():
    """ログから、日付ごとの {ペア: (買い, 売り)}（ポイント）。値が両方 0 の行（読み込み前）は捨てる。"""
    rows = {}
    for f in sorted(glob.glob(os.path.join(F.ROOT, "reports", "live", "logs", "*.log"))):
        d = os.path.basename(f)[:8]
        for line in open(f, encoding="utf-8", errors="replace"):
            m = PAT.search(line)
            if m and not (float(m.group(3)) == 0 and float(m.group(4)) == 0):
                rows.setdefault(d, {})[m.group(1)] = (float(m.group(3)), float(m.group(4)))
    return rows


def main():
    rows = read_swaps()
    last = sorted(rows)[-1]
    sw_pt = dict(rows[last])
    if "USDCAD" in rows.get("20261120", {}):
        sw_pt["USDCAD"] = rows["20261120"]["USDCAD"]          # 11月27日の値は3日分
    px = F.prices().iloc[-1]
    sw = {}
    for s, (lo, sh) in sw_pt.items():
        pt = 0.001 if s.endswith("JPY") else 0.00001
        sw[s] = (lo * pt * 365 / px[s] * 100, sh * pt * 365 / px[s] * 100)
    lines = ["# 確認：通貨3つの組み合わせで、スワップの合計がプラスになる組はあるか（`tools/research/swap_triangle.py`）", "",
             f"OANDA のデモ口座のスワップ（{last[:4]}年{last[4:6]}月{last[6:]}日のログ）。年率 %（値段に対する割合）。", "",
             "## ペアごとのスワップ（年率）", "", "| ペア | 買い | 売り | 買いと売りの合計（業者の取り分） |", "|---|---|---|---|"]
    for s in sorted(sw):
        lines.append(f"| {s} | {sw[s][0]:+.2f}% | {sw[s][1]:+.2f}% | {sw[s][0] + sw[s][1]:+.2f}% |")

    def leg(a, b):
        """通貨 a を買い、b を売るときの年率。そのペアがなければ None。"""
        if a + b in sw:
            return sw[a + b][0]
        if b + a in sw:
            return sw[b + a][1]
        return None
    res = []
    for a, b, c in itertools.permutations(F.ALL_CCY, 3):
        x, y, z = leg(a, b), leg(b, c), leg(c, a)
        if None in (x, y, z) or a != min(a, b, c):
            continue
        res.append((x + y + z, f"{a}買い{b}売り・{b}買い{c}売り・{c}買い{a}売り", x, y, z))
    res.sort(reverse=True)
    lines += ["", f"## 3つのペアの組み合わせ（{len(res)} 通り）", "",
              f"スワップの合計がプラスになる組：**{sum(1 for r in res if r[0] > 0)} 通り**。最も良い組でも {res[0][0]:+.2f}%。", "",
              "| 組み合わせ | 合計（年率） | 内訳 |", "|---|---|---|"]
    for r in res[:6] + res[-3:]:
        lines.append(f"| {r[1]} | {r[0]:+.2f}% | {r[2]:+.2f} / {r[3]:+.2f} / {r[4]:+.2f} |")
    out = os.path.join(F.ROOT, "reports", "research", "swap_triangle.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

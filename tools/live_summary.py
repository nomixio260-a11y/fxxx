#!/usr/bin/env python3
"""デモ口座での実運用（フォワードテスト）の成績をまとめる。

入力：reports/live/AMS_live_deals.csv（EA が書き出す取引の記録）と AMS_live_account.csv（残高の推移）
出力：reports/live/summary.md（スマホでも読みやすい形）と balance.svg（残高の推移のグラフ。追加の部品なしで作る）

使い方: python3 tools/live_summary.py [reports/live]
"""
import csv
import os
import sys
from collections import defaultdict


def balance_svg(points, path):
    """残高の推移を折れ線の SVG にする（GitHub の画面やスマホでそのまま見られる）。points = [(時刻の文字列, 残高, 有効証拠金)]"""
    # 同じ値が続く記録はまとめる（グラフを軽くする）
    pts = [p for i, p in enumerate(points) if i == 0 or i == len(points) - 1 or p[1:] != points[i - 1][1:]]
    W, H, L, R, T, B = 720, 360, 78, 16, 40, 44
    vals = [v for _, b, e in pts for v in (b, e)]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1:
        lo, hi = lo * 0.98, hi * 1.02 + 1
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    n = max(len(pts) - 1, 1)
    X = lambda i: L + (W - L - R) * i / n  # noqa: E731
    Y = lambda v: T + (H - T - B) * (1 - (v - lo) / (hi - lo))  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" font-family="sans-serif" font-size="12">',
           f'<rect width="{W}" height="{H}" fill="#fcfcfb"/>',
           f'<text x="{L}" y="22" font-size="15" fill="#0b0b0b">デモ口座の残高（円）　青＝残高、灰＝有効証拠金</text>']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        y = Y(v)
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e4e3df"/>')
        out.append(f'<text x="{L - 6}" y="{y + 4:.1f}" text-anchor="end" fill="#52514e">{v:,.0f}</text>')
    for k in sorted({0, n // 2, n}):
        out.append(f'<text x="{X(k):.1f}" y="{H - 18}" text-anchor="middle" fill="#52514e">{pts[k][0][:10]}</text>')
    for idx, color, width in ((2, "#9a9994", 1.2), (1, "#2a78d6", 2.2)):
        d = " ".join(f"{X(i):.1f},{Y(p[idx]):.1f}" for i, p in enumerate(pts))
        out.append(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="{width}"/>')
    lx, ly = X(len(pts) - 1), Y(pts[-1][1])
    out.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" fill="#2a78d6"/>')
    out.append(f'<text x="{lx - 8:.1f}" y="{ly - 10:.1f}" text-anchor="end" fill="#0b0b0b" font-size="13">{pts[-1][1]:,.0f} 円</text>')
    out.append("</svg>")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else os.path.join("reports", "live")
    deals_path = os.path.join(d, "AMS_live_deals.csv")
    acc_path = os.path.join(d, "AMS_live_account.csv")
    lines = ["# デモ口座での実運用の成績", ""]
    if not os.path.exists(deals_path):
        lines.append("まだ取引の記録がありません。")
        open(os.path.join(d, "summary.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
        return
    rows = list(csv.DictReader(open(deals_path, encoding="utf-8-sig", errors="ignore")))
    rule_of = {}
    for r in rows:
        if r.get("entry") == "0" and "|" in (r.get("comment") or ""):
            rule_of[r["position"]] = r["comment"].split("|")[-1]
    closed = [r for r in rows if r.get("entry") in ("1", "3")]
    by_month = defaultdict(float)
    by_rule = defaultdict(lambda: [0, 0, 0.0])
    for r in closed:
        p = float(r["profit"] or 0)
        by_month[r["time"][:7]] += p
        k = rule_of.get(r["position"], "?")
        by_rule[k][0] += 1
        by_rule[k][1] += 1 if p > 0 else 0
        by_rule[k][2] += p
    bal = []
    if os.path.exists(acc_path):
        for line in open(acc_path, encoding="utf-8-sig", errors="ignore"):
            parts = line.strip().split(",")
            if len(parts) >= 3 and parts[1].replace(".", "").isdigit():
                bal.append((parts[0], float(parts[1]), float(parts[2])))
    if bal:
        lines += [f"- 最新の残高：{bal[-1][1]:,.0f} 円（有効証拠金 {bal[-1][2]:,.0f} 円、{bal[-1][0]} 時点）", ""]
        balance_svg(bal, os.path.join(d, "balance.svg"))
        lines += ["![残高の推移](balance.svg)", ""]
    # 月ごとの損益率：その月の最初に記録した残高を基準にする
    start_bal = {}
    for t, b, _ in bal:
        start_bal.setdefault(t[:7].replace(".", "-"), b)
    lines += ["## 月ごとの損益", "", "| 月 | 損益（円） | 損益率 |", "|---|---|---|"]
    for m in sorted(by_month):
        key = m.replace(".", "-")
        sb = start_bal.get(key)
        rate = f"{by_month[m] / sb * 100:+.2f}%" if sb else "-"
        lines.append(f"| {key} | {by_month[m]:+,.0f} | {rate} |")
    lines += ["", "## ルールごとの成績", "", "| ルール | 取引数 | 勝ち | 損益（円） |", "|---|---|---|---|"]
    for k, (n, w, p) in sorted(by_rule.items()):
        lines.append(f"| {k} | {n} | {w} | {p:+,.0f} |")
    lines += ["", f"- 決済した取引：{len(closed)} 回", ""]
    open(os.path.join(d, "summary.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

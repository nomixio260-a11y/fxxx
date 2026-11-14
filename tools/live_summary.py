#!/usr/bin/env python3
"""デモ口座での実運用（フォワードテスト）の成績をまとめる。

入力：reports/live/AMS_live_deals.csv（EA が書き出す取引の記録）と AMS_live_account.csv（残高の推移）
出力：reports/live/summary.md（スマホでも読みやすい形）

使い方: python3 tools/live_summary.py [reports/live]
"""
import csv
import os
import sys
from collections import defaultdict


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

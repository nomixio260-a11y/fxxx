#!/usr/bin/env python3
"""MT5 ストラテジーテスターの HTML レポートと AMS_breakdown.csv から reports/summary.md を作る。

使い方: python3 tools/summarize_report.py reports/
"""
import csv
import glob
import html
import os
import re
import sys

# Windows のコンソールでも日本語を出力できるようにする
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# (英語ラベル, 日本語ラベルの候補, 表示名)
METRICS = [
    ("Total Net Profit", ("総損益", "純益"), "総損益"),
    ("Gross Profit", ("総利益",), "総利益"),
    ("Gross Loss", ("総損失",), "総損失"),
    ("Profit Factor", ("プロフィットファクター",), "プロフィットファクター"),
    ("Expected Payoff", ("期待利得",), "期待利得"),
    ("Recovery Factor", ("リカバリファクター", "リカバリーファクター"), "リカバリーファクター"),
    ("Sharpe Ratio", ("シャープレシオ",), "シャープレシオ"),
    ("Equity Drawdown Maximal", ("証拠金最大ドローダウン", "最大ドローダウン(有効証拠金)"), "最大ドローダウン（有効証拠金）"),
    ("Equity Drawdown Relative", ("証拠金相対ドローダウン",), "相対ドローダウン（有効証拠金）"),
    ("Total Trades", ("取引数", "総取引数"), "取引数"),
    ("Profit Trades (% of total)", ("勝ちトレード",), "勝ちトレード（勝率）"),
    ("Loss Trades (% of total)", ("負けトレード",), "負けトレード"),
    ("Largest profit trade", ("最大勝ちトレード",), "最大の勝ち"),
    ("Largest loss trade", ("最大負けトレード",), "最大の負け"),
    ("Maximum consecutive losses ($)", ("最大連敗",), "最大連敗"),
]


def read_text(path):
    raw = open(path, "rb").read()
    for bom, enc in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"), (b"\xef\xbb\xbf", "utf-8-sig")):
        if raw.startswith(bom):
            return raw[len(bom):].decode(enc, errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-16-le", errors="replace")


def table_cells(text):
    cells = re.findall(r"<td[^>]*>(.*?)</td>", text, flags=re.S | re.I)
    out = []
    for c in cells:
        c = re.sub(r"<[^>]+>", "", c)
        c = html.unescape(c).replace("\xa0", " ").strip()
        out.append(c)
    return out


def extract_metrics(cells):
    pairs = {}
    for i, c in enumerate(cells[:-1]):
        if c.endswith(":") or c.endswith("："):
            label = c.rstrip(":：").strip()
            if label not in pairs and cells[i + 1]:
                pairs[label] = cells[i + 1]
    result = []
    for en, ja_list, name in METRICS:
        value = pairs.get(en)
        if value is None:
            for ja in ja_list:
                value = next((v for k, v in pairs.items() if k.startswith(ja)), None)
                if value is not None:
                    break
        if value is not None:
            result.append((name, value))
    return result


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "reports"
    reports = sorted(glob.glob(os.path.join(out_dir, "AMS_*.htm*")))
    if not reports:
        print("HTML レポートが見つかりません:", out_dir)
        return 1

    lines = ["# バックテスト結果の要約", ""]
    for rep in reports:
        lines.append(f"## {os.path.basename(rep)}")
        lines.append("")
        metrics = extract_metrics(table_cells(read_text(rep)))
        if metrics:
            lines += ["| 項目 | 値 |", "|---|---|"]
            lines += [f"| {k} | {v} |" for k, v in metrics]
        else:
            lines.append("（レポートから数値を読み取れませんでした。HTML を直接開いて確認してください）")
        lines.append("")

    bd = os.path.join(out_dir, "AMS_breakdown.csv")
    if os.path.exists(bd):
        rows = list(csv.DictReader(open(bd, encoding="utf-8")))
        for kind, title in (("symbol", "銘柄別"), ("regime", "相場状況別"), ("strategy", "ロジック別（エントリーを主導したロジック）")):
            sub = [r for r in rows if r.get("kind") == kind]
            if not sub:
                continue
            lines += [f"## {title}", "", "| 名前 | 取引数 | 勝ち | 勝率(%) | 損益 |", "|---|---|---|---|---|"]
            lines += [f"| {r['name']} | {r['trades']} | {r['wins']} | {r['win_rate']} | {r['profit']} |" for r in sub]
            lines.append("")

    mp = os.path.join(out_dir, "AMS_monthly.csv")
    if os.path.exists(mp):
        rows = list(csv.DictReader(open(mp, encoding="utf-8")))
        if rows:
            rets = [float(r["return_pct"]) for r in rows]
            growth = 1.0
            for r in rets:
                growth *= max(1.0 + r / 100.0, 0.0)
            geo = (growth ** (1.0 / len(rets)) - 1.0) * 100.0 if growth > 0 else -100.0
            lines += ["## 月ごとの損益率（確定損益ベース）", "",
                      f"- 平均 **{sum(rets) / len(rets):+.2f}%**、幾何平均 **{geo:+.2f}%**、最低 {min(rets):+.2f}%、最高 {max(rets):+.2f}%、"
                      f"+10%以上の月 {sum(1 for r in rets if r >= 10)} / {len(rets)}", "",
                      "| 月 | 月初の残高 | 損益 | 損益率 |", "|---|---|---|---|"]
            lines += [f"| {r['month']} | {float(r['start_balance']):,.0f} | {float(r['profit']):,.0f} | {float(r['return_pct']):+.2f}% |" for r in rows]
            lines.append("")

    lines += [
        "---",
        "※ 過去の成績は将来の利益を保証しません。実運用の前に、必ずデモ口座で十分に検証してください。",
        "",
    ]
    path = os.path.join(out_dir, "summary.md")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))
    print("保存:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

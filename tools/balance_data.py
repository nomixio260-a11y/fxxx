#!/usr/bin/env python3
"""残高ボード（スマホで見るグラフのページ）用に、バックテストの月ごとの残高を JSON にまとめる。

使い方: python3 tools/balance_data.py 出力.json 系列名=実行番号 [系列名=実行番号 ...]
  例: python3 tools/balance_data.py board.json "直近5年・遅れ0.5秒=0412" "直近5年・遅れランダム=0411" "2015〜21年=0413"
各実行の reports/runs/NNNN.txt（月ごとの損益率・初期資金）と NNNN_rulemonth.csv（月 × ルールの損益）を使う。
"""
import csv
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def series(run):
    txt = open(os.path.join(ROOT, "reports", "runs", f"{run}.txt"), encoding="utf-8").read()
    deposit = float(re.search(r"deposit=(\d+)", txt).group(1))
    pct = {k: float(v) for k, v in (x.split(":") for x in re.search(r"^MONTHLY (.*)$", txt, re.M).group(1).split(",") if ":" in x)}
    yen = defaultdict(float)
    for r in csv.DictReader(open(os.path.join(ROOT, "reports", "runs", f"{run}_rulemonth.csv"), encoding="utf-8")):
        yen[r["month_rule"].split("|")[0]] += float(r["profit"])
    bal, rows = deposit, []
    for m in sorted(pct):
        p = yen.get(m, 0.0)
        rows.append({"month": m, "start_balance": round(bal), "profit": round(p), "pct": pct[m], "end_balance": round(bal + p)})
        bal += p
    return deposit, rows


def main():
    out, rows = sys.argv[1], []
    for arg in sys.argv[2:]:
        name, run = arg.rsplit("=", 1)
        deposit, rs = series(run)
        rows += [{"series": name, "run": int(run), "deposit": round(deposit), **r} for r in rs]
    code = open(os.path.abspath(__file__), encoding="utf-8").read()
    meta = [{"label": "balance_data.py", "value": code, "type": "code", "lang": "python"},
            {"label": "入力", "value": "reports/runs/NNNN.txt と NNNN_rulemonth.csv（" + ", ".join(sys.argv[2:]) + "）"}]
    json.dump({"rows": rows, "meta": meta}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(out, len(rows))


if __name__ == "__main__":
    main()

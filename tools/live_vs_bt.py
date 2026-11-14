#!/usr/bin/env python3
"""デモ口座の実運用の取引と、同じ期間のバックテストの取引を突き合わせる。

入力：
- 実運用：reports/live/AMS_live_deals.csv
- バックテスト：reports/runs/NNNN_deals.csv（mt5-backtest を InpExportDeals=true・同じ設定で実行したもの。
  短い期間ではテスターが履歴を読み込めないことがあるため、2024.11.01 から実運用の最後の日までを流す）
突き合わせ：ルール名（コメントの最後）と銘柄が同じで、入った時刻の差が5分以内の取引を同じ取引とみなす。
出力：取引ごとの入値・決済値・pips の差、片方にしかない取引、ルールごとの合計 → reports/live/compare_NNNN.md

使い方: python3 tools/live_vs_bt.py NNNN
"""
import csv
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig", errors="ignore")))
    pos = {}
    for r in rows:
        p = pos.setdefault((r["symbol"], r["position"]), {"in": [], "out": []})
        (p["in"] if r["entry"] == "0" else p["out"]).append(r)
    trades = []
    for (sym, _), p in pos.items():
        if not p["in"]:
            continue
        e = p["in"][0]
        rule = (e.get("comment") or "").split("|")[-1]
        t_in = datetime.strptime(e["time"], "%Y.%m.%d %H:%M:%S")
        is_buy = e["type"] == "0"
        vol_in = sum(float(x["volume"]) for x in p["in"])
        px_in = sum(float(x["price"]) * float(x["volume"]) for x in p["in"]) / vol_in
        if p["out"]:
            vol_out = sum(float(x["volume"]) for x in p["out"])
            px_out = sum(float(x["price"]) * float(x["volume"]) for x in p["out"]) / vol_out
            t_out = datetime.strptime(p["out"][-1]["time"], "%Y.%m.%d %H:%M:%S")
        else:
            px_out, t_out = None, None
        pip = 0.01 if sym.startswith(("USDJPY", "EURJPY", "GBPJPY", "AUDJPY")) or "JPY" in sym[3:6] else 0.0001
        pips = None if px_out is None else ((px_out - px_in) if is_buy else (px_in - px_out)) / pip
        profit = sum(float(x["profit"]) for x in p["out"])
        trades.append({"sym": sym, "rule": rule, "t_in": t_in, "t_out": t_out, "buy": is_buy, "px_in": px_in,
                       "px_out": px_out, "pips": pips, "profit": profit, "pip": pip})
    return sorted(trades, key=lambda x: x["t_in"])


def main(run):
    live = load(os.path.join(ROOT, "reports", "live", "AMS_live_deals.csv"))
    bt = load(os.path.join(ROOT, "reports", "runs", f"{run}_deals.csv"))
    if live:
        lo, hi = live[0]["t_in"], live[-1]["t_in"]
        bt = [b for b in bt if lo.date() <= b["t_in"].date() <= hi.date()]
    used = set()
    out = [f"# 実運用とバックテスト（実行{run}）の突き合わせ", "",
           "| ルール | 銘柄 | 入った時刻 | 実運用 pips | バックテスト pips | 差 | 入値の差（pips） |", "|---|---|---|---|---|---|---|"]
    only_live = []
    diffs = {}
    for t in live:
        match = None
        for i, b in enumerate(bt):
            if i in used or b["rule"] != t["rule"] or b["sym"][:6] != t["sym"][:6]:
                continue
            if abs((b["t_in"] - t["t_in"]).total_seconds()) <= 300:
                match = i
                break
        if match is None:
            only_live.append(t)
            continue
        used.add(match)
        b = bt[match]
        if t["pips"] is None or b["pips"] is None:
            continue
        d = t["pips"] - b["pips"]
        din = ((b["px_in"] - t["px_in"]) if t["buy"] else (t["px_in"] - b["px_in"])) / t["pip"]
        diffs.setdefault(t["rule"], []).append(d)
        out.append(f"| {t['rule']} | {t['sym']} | {t['t_in']:%m/%d %H:%M} | {t['pips']:+.1f} | {b['pips']:+.1f} | {d:+.1f} | {din:+.1f} |")
    only_bt = [b for i, b in enumerate(bt) if i not in used]
    out += ["", "## ルールごとの差（実運用 − バックテスト、pips／回）", "", "| ルール | 一致した取引 | 平均の差 |", "|---|---|---|"]
    for k, v in sorted(diffs.items()):
        out.append(f"| {k} | {len(v)} | {sum(v) / len(v):+.2f} |")
    out += ["", f"## 実運用だけにある取引：{len(only_live)} 回", ""]
    out += [f"- {t['rule']} {t['sym']} {t['t_in']:%m/%d %H:%M}" for t in only_live]
    out += ["", f"## バックテストだけにある取引（実運用で入らなかった）：{len(only_bt)} 回", ""]
    out += [f"- {b['rule']} {b['sym']} {b['t_in']:%m/%d %H:%M} {b['pips']:+.1f}pips" for b in only_bt if b["pips"] is not None]
    text = "\n".join(out) + "\n"
    open(os.path.join(ROOT, "reports", "live", f"compare_{run}.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1])

#!/usr/bin/env python3
"""MT5 の最適化結果（*.xml と *.forward.xml）から、フォワード検証の成績が良い設定を一覧にする。

使い方: python3 tools/summarize_opt.py reports/
出力: reports/optimize_summary.md

方針（過剰適合を避けるため）:
  - 最適化期間（バック）でも検証期間（フォワード）でも利益が出ている設定だけを候補にする
  - 並べ替えはフォワード期間のプロフィットファクター → 損益の順
"""
import glob
import os
import sys
import xml.etree.ElementTree as ET

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MIN_FWD_TRADES = 10


def read_rows(path):
    raw = open(path, "rb").read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        raw = raw.decode("utf-16").encode("utf-8")
        raw = raw.replace(b'encoding="UTF-16"', b'encoding="UTF-8"').replace(b"encoding='UTF-16'", b"encoding='UTF-8'")
    root = ET.fromstring(raw)
    rows = []
    for row in root.iter():
        if not row.tag.endswith("Row"):
            continue
        cells = []
        for cell in row:
            if not cell.tag.endswith("Cell"):
                continue
            data = next((d for d in cell if d.tag.endswith("Data")), None)
            cells.append(data.text.strip() if data is not None and data.text else "")
        rows.append(cells)
    if not rows:
        return []
    header = rows[0]
    return [dict(zip(header, r)) for r in rows[1:] if r]


def num(v, default=0.0):
    try:
        return float(str(v).replace(" ", "").replace(",", ""))
    except (TypeError, ValueError):
        return default


METRIC_COLS = {"Pass", "Result", "Forward Result", "Back Result", "Profit", "Expected Payoff",
               "Profit Factor", "Recovery Factor", "Sharpe Ratio", "Custom", "Equity DD %", "Trades"}


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "reports"
    back_files = [f for f in glob.glob(os.path.join(out_dir, "AMS_opt_*.xml")) if not f.endswith(".forward.xml")]
    if not back_files:
        print("最適化結果（AMS_opt_*.xml）が見つかりません:", out_dir)
        return 1
    back_path = back_files[0]
    fwd_path = back_path[:-4] + ".forward.xml"

    back = {r.get("Pass"): r for r in read_rows(back_path)}
    fwd = {r.get("Pass"): r for r in read_rows(fwd_path)} if os.path.exists(fwd_path) else {}

    candidates = []
    for p, b in back.items():
        f = fwd.get(p)
        if f is None:
            continue
        if num(b.get("Profit")) <= 0 or num(f.get("Profit")) <= 0 or num(f.get("Trades")) < MIN_FWD_TRADES:
            continue
        candidates.append((p, b, f))
    candidates.sort(key=lambda x: (num(x[2].get("Profit Factor")), num(x[2].get("Profit"))), reverse=True)

    params = [k for k in (next(iter(back.values())).keys() if back else []) if k not in METRIC_COLS]
    lines = [
        "# 最適化とフォワード検証の結果",
        "",
        f"- 最適化した組み合わせ: {len(back)} 通り（フォワード結果あり: {len(fwd)} 通り）",
        f"- 候補の条件: バック・フォワードとも利益、フォワードの取引数 {MIN_FWD_TRADES} 回以上 → **{len(candidates)} 通り**",
        "",
    ]
    if candidates:
        head = "| # | フォワード損益 | フォワードPF | フォワード取引 | フォワードDD% | バック損益 | バックPF | " + " | ".join(params) + " |"
        lines += [head, "|" + "---|" * (7 + len(params))]
        for i, (p, b, f) in enumerate(candidates[:15], 1):
            vals = " | ".join(b.get(k, "") for k in params)
            lines.append(f"| {i} | {num(f.get('Profit')):,.0f} | {f.get('Profit Factor')} | {f.get('Trades')} | "
                         f"{f.get('Equity DD %')} | {num(b.get('Profit')):,.0f} | {b.get('Profit Factor')} | {vals} |")
    else:
        lines.append("バック・フォワードの両方で利益が出た設定はありませんでした。")
        # 参考：フォワード損益の上位
        ranked = sorted(((p, b, fwd[p]) for p, b in back.items() if p in fwd),
                        key=lambda x: num(x[2].get("Profit")), reverse=True)[:10]
        if ranked:
            lines += ["", "参考：フォワード損益の上位", "",
                      "| # | フォワード損益 | フォワードPF | フォワード取引 | バック損益 | バックPF | " + " | ".join(params) + " |",
                      "|" + "---|" * (6 + len(params))]
            for i, (p, b, f) in enumerate(ranked, 1):
                vals = " | ".join(b.get(k, "") for k in params)
                lines.append(f"| {i} | {num(f.get('Profit')):,.0f} | {f.get('Profit Factor')} | {f.get('Trades')} | "
                             f"{num(b.get('Profit')):,.0f} | {b.get('Profit Factor')} | {vals} |")
    lines += ["", "※ 過去の成績は将来の利益を保証しません。", ""]

    path = os.path.join(out_dir, "optimize_summary.md")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

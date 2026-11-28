#!/usr/bin/env python3
"""研究：金・銀についての、文献から出た2つの確認（105章）。日付・時刻は使わない。

A 株価指数の「売られすぎの戻り」のルール（R2・D7・IBS）を、金・銀にそのまま当てはめる。
  文献（Portnaya 2026）は、金・銀・原油の ETF の日々の値動きは「でたらめな動き」と区別できない、としている。事前の予想は「優位性なし」。
  判定（事前に決めた基準。101章の指数と同じ）：その銘柄だけの層（コスト後）の t 値が 2.0 以上、かつ、前半・後半の両方でプラス。
B 金の順張り（200日の平均より上）に、「米国債も上がっている（中期国債の ETF の過去252日の値動きがプラス）」という条件を足す
  （Quantpedia 2026 の記事の形。査読なし）。文献の調査では「2022年以降、金と金利の関係は崩れた」とされ、事前の予想は「効かない」。
  判定（事前に決めた基準）：シャープが、前半・後半の両方で、今の形より高い。
データ：金・銀は OANDA の商品CFDの口座の実際の日足（注文を出さない観察で書き出したもの。リポジトリには入れていない）。米国債は ETF（IEF、2002年〜）。
使い方: python3 -I tools/research/gold_checks.py <商品の口座の書き出しのフォルダ>  → reports/research/gold_checks.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_others as IO  # noqa: E402
import trend_signal as TS  # noqa: E402
import yahoo_data as Y  # noqa: E402


def main():
    folder = sys.argv[1]
    data, props = IO.load(folder)
    lines = ["# 研究：金・銀についての確認（`tools/research/gold_checks.py`）", "",
             "## A 指数の「売られすぎの戻り」のルールを、金・銀に当てはめる（コスト後。VIX の倍率なし）", "",
             "| 銘柄 | シャープ | t 値 | 前半 | 後半 | 持つ日の割合 | ルールごとの t 値（R2・D7・IBS） | 判定（t ≥ 2.0 かつ 前半・後半ともプラス） |", "|---|---|---|---|---|---|---|---|"]
    for sym, name in (("XAUUSD", "金"), ("XAGUSD", "銀")):
        d = data[sym]
        r, w, spread, swap = IO.sleeve(d, sym, props, use_vix=False)
        r, w = r.iloc[320:], w.iloc[320:]
        mid = r.index[len(r) // 2]
        tv = []
        for key in ("R2<10", "D7", "IBS"):
            rk, _, _, _ = IO.sleeve(d, sym, props, use_vix=False, only=key)
            tv.append(IO.tval(rk.iloc[320:]))
        a, b = IO.sh(r[r.index <= mid]), IO.sh(r[r.index > mid])
        ok = IO.tval(r) >= 2.0 and a > 0 and b > 0
        lines.append(f"| {name}（{r.index[0].date()}〜{r.index[-1].date()}） | {IO.sh(r):+.2f} | {IO.tval(r):+.1f} | {a:+.2f} | {b:+.2f} | {(w > 0).mean() * 100:.0f}% | "
                     f"{tv[0]:+.1f}・{tv[1]:+.1f}・{tv[2]:+.1f} | {'**合格**' if ok else '不合格'} |")
        print(lines[-1], flush=True)
    # ---------- B
    d = data["XAUUSD"]
    costs = dict(spread=float(props.loc["XAUUSD", "spread_points"]) * float(props.loc["XAUUSD", "point"]) / float(props.loc["XAUUSD", "bid"]),
                 swap_long=float(props.loc["XAUUSD", "swap_long"]), swap_short=float(props.loc["XAUUSD", "swap_short"]))
    ief = Y.fetch("IEF")["adj"].dropna()
    bond_up = (ief / ief.shift(252) - 1.0 > 0).astype(float).where(ief.shift(252).notna())
    bond_up = bond_up.reindex(bond_up.index.union(d.index)).ffill(limit=5).reindex(d.index).shift(1)      # 米国の日付の値は、次の日足から使う（先を見ない）
    base = TS.raw_signal(d["close"], "T0")
    lines += ["", "## B 金の順張りに、「米国債も上がっている」という条件を足す", "",
              "| 形 | 全期間 | 前半 | 後半 | 2022年〜 | 最大の下落 | 持っていた日の割合 |", "|---|---|---|---|---|---|---|"]
    res = {}
    start = d.index[560]
    for lab, sig in (("今の形（金が200日の平均より上）", base), ("金が上 かつ 米国債の過去252日がプラス", (base * bond_up).where(base.notna() & bond_up.notna()))):
        r, hd, _ = TS.simulate(d, TS.reviewed(sig), **costs)
        r, hd = r[(r.index >= start)].iloc[:-1], hd[(hd.index >= start)].iloc[:-1]
        mid = start + (r.index[-1] - start) / 2
        res[lab] = (TS.sh(r[r.index <= mid]), TS.sh(r[r.index > mid]))
        lines.append(f"| {lab} | {TS.sh(r):+.2f} | {res[lab][0]:+.2f} | {res[lab][1]:+.2f} | {TS.sh(r[r.index >= '2022-01-01']):+.2f} | {TS.mdd(r) * 100:.0f}% | {(hd != 0).mean() * 100:.0f}% |")
        print(lines[-1], flush=True)
    k = list(res)
    ok = res[k[1]][0] > res[k[0]][0] and res[k[1]][1] > res[k[0]][1]
    lines += ["", f"- 判定：{'**合格**' if ok else '不合格'}（前半・後半の両方で今の形より高いこと）。"]
    # ---------- B の追加の確認：たまたまでないか（債券の種類と、見る期間の長さを変える。基準を厳しくする向きの確認）
    lines += ["", "### B の追加の確認：債券の種類（中期 IEF・長期 TLT）と、見る期間（63・126・252日）を変えても同じか", "",
              "| 条件 | 全期間 | 前半 | 後半 | 2022年〜 | 最大の下落 | 前半・後半とも今の形より高い |", "|---|---|---|---|---|---|---|"]
    n_ok = 0
    for etf in ("IEF", "TLT"):
        px = Y.fetch(etf)["adj"].dropna()
        for n in (63, 126, 252):
            up = (px / px.shift(n) - 1.0 > 0).astype(float).where(px.shift(n).notna())
            up = up.reindex(up.index.union(d.index)).ffill(limit=5).reindex(d.index).shift(1)
            r, _, _ = TS.simulate(d, TS.reviewed((base * up).where(base.notna() & up.notna())), **costs)
            r = r[(r.index >= start)].iloc[:-1]
            mid = start + (r.index[-1] - start) / 2
            a2, b2 = TS.sh(r[r.index <= mid]), TS.sh(r[r.index > mid])
            good = a2 > res[k[0]][0] and b2 > res[k[0]][1]
            n_ok += int(good)
            lines.append(f"| {etf} の過去 {n} 日がプラス | {TS.sh(r):+.2f} | {a2:+.2f} | {b2:+.2f} | {TS.sh(r[r.index >= '2022-01-01']):+.2f} | {TS.mdd(r) * 100:.0f}% | {'○' if good else '×'} |")
            print(lines[-1], flush=True)
    lines += ["", f"- 6通りのうち、基準を満たしたのは {n_ok} 通り。債券の種類や期間で結果が変わるので、たまたまの可能性が高い（EA に入れるには、債券の値段を外から取り込む仕組みも必要になる）。"]
    out = os.path.join(F.ROOT, "reports", "research", "gold_checks.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

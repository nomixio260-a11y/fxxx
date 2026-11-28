#!/usr/bin/env python3
"""研究：資金の一部だけを、金の口座に「大きく賭ける枠」として置く形（106章）。

- 考え方：2つの口座は証拠金が別なので、金の口座に置いた資金より多くは、金で失わない（逆指値と、強制ロスカットを避ける上限あり）。
  金の口座に資金の s（10〜30%）だけを置き、そこで金の順張りを大きく（建玉の値動き 年75〜125%。レバレッジ 5〜10倍）持つ。
  残り（1 − s）は指数の口座。年が変わるたびに、資金を s：1 − s に戻す（手作業の資金移動）。
  負ける年の損は「枠の中」に限られ、金に強い流れが出た年は、枠が何倍にもなる（勝っているあいだは建玉が増え、負けると減る形）。
- 105章の「半分ずつ」との違い：同じだけ金の値動きを取るのに、金の口座に置く資金が少なくて済み、その分を、成績の安定している指数の口座に回せる。
- データ：金の枠は MT5（OANDA の実際の値段、300万円、口座の実際のレバレッジ。20年は1分足の四本値、直近3年は実際のティック）。
  指数の口座は composite_20y.py と同じ（2019年11月〜は MT5、それ以前は現物の写し）。
- 注意：この形の20年の成績は、金が大きく動いた1年（2025年）に強く頼る。2025年を除いた成績も並べる。
使い方: python3 tools/research/gold_pocket.py  → reports/research/gold_pocket.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import composite_20y as C20  # noqa: E402
import composite_accounts as CA  # noqa: E402
import fred_data as F  # noqa: E402
import index_trend_combo as ITC  # noqa: E402
import target300 as T  # noqa: E402

RUNS = {50.0: (892, 880), 75.0: (905, 906), 100.0: (907, 908), 125.0: (909, 910)}      # 建玉の値動き（年 %）：（20年の実行、直近3年の実行）


def eq(run):
    e = pd.read_csv(os.path.join(CA.RUNS, f"{run:04d}_equity.csv"))
    e.index = pd.to_datetime(e["date"], format="%Y.%m.%d")
    e = e["equity"].astype(float)
    e = e[e.index.dayofweek < 5]
    e = pd.concat([pd.Series([3000000.0], index=[e.index[0] - pd.Timedelta(days=1)]), e])
    return e.pct_change().dropna()


def total(ri, rg, s, reset=True):
    days = ri.index.union(rg.index)
    a, b = ri.reindex(days).fillna(0.0).values, rg.reindex(days).fillna(0.0).values
    vi, vg, year, out = 1 - s, s, days[0].year, []
    for t, x, g in zip(days, a, b):
        if reset and t.year != year:
            tot, year = vi + vg, t.year
            vi, vg = (1 - s) * tot, s * tot
        vi, vg = vi * (1 + x), max(vg * (1 + g), 0.0)
        out.append(vi + vg)
    e = pd.Series(out, index=days)
    return pd.concat([pd.Series([1.0], index=[days[0] - pd.Timedelta(days=1)]), e])


def row(label, e):
    y = C20.yearly(e)
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    ex = y.drop(2025, errors="ignore")
    g_ex = (np.prod(1 + ex.values) ** (1 / len(ex)) - 1) if len(ex) else np.nan
    return (f"| {label} | {(e.iloc[-1] ** (1 / yrs) - 1) * 100:+.0f}% | {g_ex * 100:+.0f}% | {(e / e.cummax() - 1).min() * 100:.0f}% | {int((y >= 3).sum())} | {int((y >= 1).sum())} | {int((y < 0).sum())} | "
            f"{y.min() * 100:+.0f}%（{int(y.idxmin())}年） | {y.max() * 100:+.0f}%（{int(y.idxmax())}年） | {y.median() * 100:+.0f}% |"), y


def main():
    cat = CA.catalog()
    E = {k: CA.rel(c) for k, c in cat.items()}
    rev = {u: T.cash_returns(u) for u in (5.0, 8.75)}
    tr = {u: ITC.trend_returns("NASDAQ100", u) for u in (10.0, 20.0)}
    rep = {"Index_Demo": rev[5.0].add(tr[10.0], fill_value=0.0), "Index_Growth": rev[8.75].add(tr[20.0], fill_value=0.0)}
    IDX = {n: C20.spliced(E[(n, 0.0, "long")], rep[n])[0] for n in rep}
    IDX = {n: v[v.index >= "2007-01-01"] for n, v in IDX.items()}
    G20 = {u: eq(r[0]) for u, r in RUNS.items()}
    G3 = {u: eq(r[1]) for u, r in RUNS.items()}
    lines = ["# 研究：金の口座に「大きく賭ける枠」を置く形（`tools/research/gold_pocket.py`）", "",
             "## 1 金の枠だけの成績（MT5・OANDA の実際の値段・300万円）", "",
             "| 建玉の値動き（年） | 20年：年率 | 最大の下落 | 最悪の日 | +300% 以上の年 | +100% 以上の年 | マイナスの年 | 2025年（20年の実行／実際のティック） | 年ごと（2007〜2026年、%） |", "|---|---|---|---|---|---|---|---|---|"]
    for u in RUNS:
        e = pd.concat([pd.Series([1.0], index=[G20[u].index[0] - pd.Timedelta(days=1)]), (1 + G20[u]).cumprod()])
        y = C20.yearly(e)
        e3 = pd.concat([pd.Series([1.0], index=[G3[u].index[0] - pd.Timedelta(days=1)]), (1 + G3[u]).cumprod()])
        y3 = C20.yearly(e3)
        yrs = (e.index[-1] - e.index[0]).days / 365.25
        lines.append(f"| {u:g}%（実行 {RUNS[u][0]}・{RUNS[u][1]}） | {(e.iloc[-1] ** (1 / yrs) - 1) * 100:+.0f}% | {(e / e.cummax() - 1).min() * 100:.0f}% | {G20[u].min() * 100:.1f}% | {int((y >= 3).sum())} | {int((y >= 1).sum())} | {int((y < 0).sum())} | "
                     f"{y.get(2025, np.nan) * 100:+.0f}%／{y3.get(2025, np.nan) * 100:+.0f}% | " + " ".join(f"{v * 100:+.0f}" for v in y.values) + " |")
        print(lines[-1], flush=True)
    head = "| 設定 | 年率（20年） | 2025年を除いた19年の年率 | 最大の下落 | +300% 以上の年 | +100% 以上の年 | マイナスの年 | 最悪の年 | 最高の年 | 年ごとの成績の真ん中 |"
    for name, lab in (("Index_Growth", "指数の口座：大きい設定"), ("Index_Demo", "指数の口座：デモの既定")):
        lines += ["", f"## 2 {lab} ＋ 金の枠（20年。年が変わるたびに、資金の割合を戻す）", "", head, "|---|" + "---|" * 9]
        r0, _ = row("指数の口座だけ", pd.concat([pd.Series([1.0], index=[IDX[name].index[0] - pd.Timedelta(days=1)]), (1 + IDX[name]).cumprod()]))
        lines.append(r0)
        print(r0, flush=True)
        r1, _ = row("（比べ）半分ずつ・金は最大の設定 50%", total(IDX[name], G20[50.0], 0.5))
        lines.append(r1)
        print(r1, flush=True)
        for s in (0.1, 0.2, 0.3):
            for u in (50.0, 75.0, 100.0, 125.0):
                r, y = row(f"金の枠 {s * 100:.0f}%・建玉 {u:g}%", total(IDX[name], G20[u], s))
                lines.append(r)
                print(r, flush=True)
    # ---------- 直近3年（実際のティック）
    lines += ["", "## 3 直近3年（実際のティック。指数の口座も MT5）", "",
              "| 指数の口座 | 金の枠 | 3年の損益 | 年率 | 最大の下落 | 2024年 | 2025年 | 2026年 | 12か月の成績（最高〜最低） |", "|---|---|---|---|---|---|---|---|---|"]
    for name, lab in (("Index_Growth", "大きい設定"), ("Index_Demo", "デモの既定")):
        ri = E[(name, 0.0, "tick")].pct_change().dropna()
        for s, u in ((0.0, 50.0), (0.2, 75.0), (0.2, 100.0), (0.3, 100.0), (0.3, 125.0)):
            e = total(ri, G3[u], s)
            y = C20.yearly(e)
            ro = CA.roll12(e)
            yrs = (e.index[-1] - e.index[0]).days / 365.25
            lines.append(f"| {lab} | {'なし' if s == 0 else f'{s * 100:.0f}%・建玉 {u:g}%'} | {(e.iloc[-1] - 1) * 100:+.0f}% | {(e.iloc[-1] ** (1 / yrs) - 1) * 100:+.0f}% | {(e / e.cummax() - 1).min() * 100:.0f}% | "
                         f"{y.get(2024, np.nan) * 100:+.0f}% | {y.get(2025, np.nan) * 100:+.0f}% | {y.get(2026, np.nan) * 100:+.0f}% | {ro.max() * 100:+.0f}% 〜 {ro.min() * 100:+.0f}% |")
            print(lines[-1], flush=True)
    lines += ["", "- 「最大の下落」が大きく出る設定は、勝った年の途中で、ふくらんだ金の枠が大きく戻した場面を含みます（年の初めから見れば、まだ大きなプラスの途中）。",
              "- 金の枠は、建玉の上限（OANDA の金は 1銘柄 20 lot まで）の中で動かした結果です。口座が数億円になると、この上限に当たります。"]
    out = os.path.join(F.ROOT, "reports", "research", "gold_pocket.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

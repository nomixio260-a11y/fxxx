#!/usr/bin/env python3
"""バックテスト1本の月ごとの成績（損益率・金額）と残高の推移をグラフにする。

使い方: python3 tools/plot_monthly.py 0303 [初期資金]  → reports/charts/run_0303.png と表（標準出力）
"""
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for f in ("/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf", "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"):
    if os.path.exists(f):
        font_manager.fontManager.addfont(f)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
        break

BLUE, RED, INK, INK2, GRID, SURF = "#2a78d6", "#e34948", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def main(run, deposit=1_000_000):
    txt = open(os.path.join(ROOT, "reports", "runs", f"{run}.txt"), encoding="utf-8").read()
    pct = {k: float(v) for k, v in (x.split(":") for x in re.search(r"^MONTHLY (.*)$", txt, re.M).group(1).split(",") if ":" in x)}
    rm = pd.read_csv(os.path.join(ROOT, "reports", "runs", f"{run}_rulemonth.csv"))
    yen = rm.assign(m=rm.month_rule.str.split("|").str[0]).groupby("m").profit.sum()
    months = sorted(pct)
    bal, rows = deposit, []
    for m in months:
        p = float(yen.get(m, 0.0))
        rows.append((m, bal, p, pct[m], bal + p))
        bal += p
    df = pd.DataFrame(rows, columns=["月", "月初残高", "損益", "損益率", "月末残高"])
    print("| 月 | 損益率 | 損益（円） | 月末の残高（円） |\n|---|---|---|---|")
    for r in df.itertuples():
        print(f"| {r.月} | {r.損益率:+.1f}% | {r.損益:+,.0f} | {r.月末残高:,.0f} |")

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 8), dpi=150, facecolor=SURF, gridspec_kw={"height_ratios": [1, 1]})
    x = range(len(months))
    labels = [m[2:].replace("-", "/") for m in months]
    for ax in (a1, a2):
        ax.set_facecolor(SURF)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=8, length=0)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=90)
    # 残高の推移（月末）
    yb = [deposit] + list(df["月末残高"])
    a1.plot(range(-1, len(months)), [v / 1e4 for v in yb], color=BLUE, linewidth=2)
    a1.scatter([len(months) - 1], [yb[-1] / 1e4], color=BLUE, s=30, zorder=3)
    a1.annotate(f"{yb[-1] / 1e4:,.0f}万円", (len(months) - 1, yb[-1] / 1e4), textcoords="offset points", xytext=(-8, -16),
                ha="right", color=INK, fontsize=10)
    a1.set_xlim(-1.5, len(months) - 0.5)
    a1.set_title(f"月末の残高（初期資金 {deposit / 1e4:,.0f}万円、単位：万円）", loc="left", color=INK, fontsize=12)
    # 月ごとの損益率
    cols = [BLUE if v >= 0 else RED for v in df["損益率"]]
    a2.bar(list(x), df["損益率"], color=cols, width=0.7)
    a2.axhline(0, color=INK2, linewidth=0.8)
    a2.axhline(5, color=INK2, linewidth=1, linestyle=(0, (4, 3)))
    a2.text(len(months) - 0.5, 5.3, "目標 +5%", ha="right", va="bottom", color=INK2, fontsize=9)
    a2.set_xlim(-0.6, len(months) - 0.4)
    a2.set_title("月ごとの損益率（%）　青＝プラス、赤＝マイナス", loc="left", color=INK, fontsize=12)
    fig.tight_layout()
    out = os.path.join(ROOT, "reports", "charts", f"run_{run}.png")
    fig.savefig(out, facecolor=SURF)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 1_000_000)

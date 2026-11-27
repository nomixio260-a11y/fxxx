#!/usr/bin/env python3
"""研究：複利を活かしながら損失を抑える、建玉の大きさの決め方（100章）。

今の形は「有効証拠金 × 一定の割合」（残高が増えれば建玉も増える＝複利）。ここでは、資産の下落の深さに応じて建玉を変える形を、同じ物差しで比べる。

- const  今の形：一定の割合 L
- GZ     Grossman・Zhou（1993年）：最高値からの下落を D 以内に抑えるという条件で、長期の伸び率が最大になる形（値動きが独立なら、数学的に最適）。
         建玉 = L ×（1 − 今の下落 ÷ D）。最高値のとき L、下落が D に届くと 0。最高値は、これまでの全期間。
- REDD   Yang・Zhong（2012年）の「直近の下落」版：最高値を直近250日で数える（下落が続いても、1年たてば元の大きさに戻る）。
- ANTI   逆の形（独自）：下落しているあいだは、建玉を増やす。戻りの手法は、負けた直後ほど期待値が高い（VIX が高い・売られすぎが深い）ので、
         下落 ÷ D に比例して最大 +50% まで増やす。危険を増やす形なので、採用の基準は厳しくする（参考として載せる）。
- 層の日次の損益：現物の3指数、99章の形（重み 1:2:4・VIX の倍率・逆指値 4×σ、持ち越しのコスト込み）。2000年10月〜2026年11月。
  値動きを年10%にそろえた損益 z に、倍率 L をかけて口座の資産の道筋を作る：資産(t+1) = 資産(t) ×（1 + L(t) × z(t)）。
  L(t) は、前の日までの資産だけで決める。
- 物差し：同じ「最大の下落」になる L どうしで、年率の伸びを比べる（全期間・前半・後半）。
  さらに、損益の並びを20日のかたまりで並べ替えた 3年間の道筋を 4,000 本作り（ブロック・ブートストラップ）、
  「3年間の伸びの中央値」「下位5%」「下落が30%を超える確率」を比べる。
使い方: python3 tools/research/drawdown_control.py  → reports/research/drawdown_control.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_model2 as M2  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_vix_sizing as V  # noqa: E402

ANN = 252


def path(z, L, kind, D, look=250, boost=0.5):
    """z：日次の損益（年10%にそろえたもの）。戻り値：資産の道筋（最初 = 1）と、使った倍率の平均。"""
    n = len(z)
    eq = np.empty(n + 1)
    eq[0] = 1.0
    peak = 1.0
    used = 0.0
    for t in range(n):
        if kind == "REDD":
            lo = max(0, t - look + 1)
            peak = eq[lo:t + 1].max()
        else:
            peak = max(peak, eq[t])
        dd = 1.0 - eq[t] / peak
        if kind == "const":
            k = L
        elif kind in ("GZ", "REDD"):
            k = L * max(0.0, 1.0 - dd / D)
        else:                                   # ANTI
            k = L * (1.0 + boost * min(dd / D, 1.0))
        used += k
        eq[t + 1] = eq[t] * (1.0 + k * z[t])
        if eq[t + 1] <= 0.0:
            eq[t + 1:] = 1e-9
            break
    return eq, used / n


def stats(eq, years):
    e = pd.Series(eq)
    return e.iloc[-1] ** (1.0 / years) - 1.0, (e / e.cummax() - 1.0).min()


def frontier(z, kind, D, grid):
    yrs = len(z) / ANN
    rows = []
    for L in grid:
        eq, used = path(z, L, kind, D)
        c, dd = stats(eq, yrs)
        rows.append((L, c, -dd, used))
    return rows


def at_dd(rows, target):
    """最大の下落が target になる L のときの、年率の伸び（線形に補間）。"""
    for a, b in zip(rows[:-1], rows[1:]):
        if a[2] <= target <= b[2] and b[2] > a[2]:
            w = (target - a[2]) / (b[2] - a[2])
            return a[1] + w * (b[1] - a[1]), a[0] + w * (b[0] - a[0])
    return np.nan, np.nan


def boot(z, kind, D, L, n_path=4000, days=756, block=20, seed=7, look=250, boost=0.5):
    """ブロック・ブートストラップ（道筋をまとめて計算する）。戻り値：3年後の資産（最初 = 1）と、最大の下落。"""
    rng = np.random.default_rng(seed)
    n = len(z)
    starts = rng.integers(0, n, size=(n_path, days // block + 1))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(n_path, -1)[:, :days]
    zz = z[idx]                                        # 道筋 × 日
    hist = np.ones((n_path, days + 1))
    peak = np.ones(n_path)
    for t in range(days):
        eq = hist[:, t]
        if kind == "REDD":
            peak = hist[:, max(0, t - look + 1):t + 1].max(axis=1)
        else:
            peak = np.maximum(peak, eq)
        dd = 1.0 - eq / peak
        if kind == "const":
            k = np.full(n_path, L)
        elif kind in ("GZ", "REDD"):
            k = L * np.clip(1.0 - dd / D, 0.0, None)
        else:
            k = L * (1.0 + boost * np.minimum(dd / D, 1.0))
        hist[:, t + 1] = np.maximum(eq * (1.0 + k * zz[:, t]), 1e-9)
    run_max = np.maximum.accumulate(hist, axis=1)
    return hist[:, -1], (1.0 - hist / run_max).max(axis=1)


def main():
    sets = V.load_sets("cash")
    rk = {n: V.vix_rank(t[0].index)[0] for n, t in sets.items()}
    vm = {n: V.mult_of(rk[n], M2.MULT) for n in sets}
    r = M2.sleeve_w(sets, vm, "cash")
    r = r[r.index >= IRK.START]
    z = (r * (0.10 / (r.std() * np.sqrt(ANN)))).values
    dates = r.index
    half = len(z) // 2
    lines = ["# 研究：複利を活かしながら損失を抑える、建玉の大きさの決め方（`tools/research/drawdown_control.py`）", "",
             f"現物の3指数、99章の形。{dates[0].date()}〜{dates[-1].date()}。値動きを年10%にそろえた損益に、倍率 L をかける（L = 2 なら、口座の値動きは年20%ほど）。", "",
             f"層の損益の自己相関（1日・5日の合計・20日の合計）：{pd.Series(z).autocorr(1):+.3f}、"
             f"{pd.Series(z).rolling(5).sum().iloc[::5].autocorr(1):+.3f}、{pd.Series(z).rolling(20).sum().iloc[::20].autocorr(1):+.3f}"
             "（プラスなら負けが続きやすく、下落で縮める形が効く。マイナスなら負けたあとに取り返しやすく、縮める形は損をする）", ""]
    print(lines[-2], flush=True)
    grid = np.arange(0.25, 8.01, 0.25)
    forms = (("今の形（一定の割合）", "const", 1.0), ("GZ：下落 30% で 0", "GZ", 0.30), ("GZ：下落 40% で 0", "GZ", 0.40), ("GZ：下落 50% で 0", "GZ", 0.50),
             ("REDD（直近250日）：下落 30% で 0", "REDD", 0.30), ("REDD：下落 40% で 0", "REDD", 0.40), ("ANTI：下落 20% で +50%", "ANTI", 0.20))
    for title, zz in (("全期間", z), (f"前半（〜{dates[half].date()}）", z[:half]), (f"後半（{dates[half].date()}〜）", z[half:])):
        lines += [f"## {title}：同じ最大の下落になる大きさで比べた、年率の伸び", "",
                  "| 形 | 最大の下落 15% | 20% | 30% | 40% |", "|---|---|---|---|---|"]
        for label, kind, D in forms:
            rows = frontier(zz, kind, D, grid)
            cells = []
            for tgt in (0.15, 0.20, 0.30, 0.40):
                c, L = at_dd(rows, tgt)
                cells.append("—" if np.isnan(c) else f"{c * 100:+.1f}%（L {L:.2f}）")
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
            print(lines[-1], flush=True)
        lines.append("")
    # ブートストラップ：3年間。const の L を決め、ほかの形は「下落の中央値が同じ」になる L を探して比べる
    lines += ["## 3年間の道筋 4,000 本（20日のかたまりで並べ替え）", "",
              "ほかの形の L は、「3年間の最大の下落の中央値」が、今の形と同じになるように決めた。", "",
              "| 今の形の L | 形 | L | 3年間の伸び：中央値 | 下位5% | 上位5% | 最大の下落：中央値 | 95%点 | 下落が30%を超える確率 | 3年で元金を割る確率 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for L0 in (2.0, 3.0, 4.0):
        f0, d0 = boot(z, "const", 1.0, L0)
        med0 = np.median(d0)
        lines.append(f"| {L0:.1f} | 今の形（一定の割合） | {L0:.2f} | {np.median(f0) * 100 - 100:+.0f}% | {np.quantile(f0, 0.05) * 100 - 100:+.0f}% | {np.quantile(f0, 0.95) * 100 - 100:+.0f}% | "
                     f"{med0 * 100:.0f}% | {np.quantile(d0, 0.95) * 100:.0f}% | {(d0 > 0.30).mean() * 100:.1f}% | {(f0 < 1.0).mean() * 100:.1f}% |")
        print(lines[-1], flush=True)
        for label, kind, D in forms[1:]:
            lo, hi = 0.2 * L0, 6.0 * L0
            for _ in range(14):                                   # 下落の中央値が同じになる L を二分法で探す
                mid = 0.5 * (lo + hi)
                _, dm = boot(z, kind, D, mid)
                if np.median(dm) < med0:
                    lo = mid
                else:
                    hi = mid
            L1 = 0.5 * (lo + hi)
            f1, d1 = boot(z, kind, D, L1)
            lines.append(f"| {L0:.1f} | {label} | {L1:.2f} | {np.median(f1) * 100 - 100:+.0f}% | {np.quantile(f1, 0.05) * 100 - 100:+.0f}% | {np.quantile(f1, 0.95) * 100 - 100:+.0f}% | "
                         f"{np.median(d1) * 100:.0f}% | {np.quantile(d1, 0.95) * 100:.0f}% | {(d1 > 0.30).mean() * 100:.1f}% | {(f1 < 1.0).mean() * 100:.1f}% |")
            print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "drawdown_control.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

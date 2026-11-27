#!/usr/bin/env python3
"""研究：売られすぎの戻りの層の「改良後の形」をまとめて確かめ、建玉の大きさを数式で決める。

改良後の形（利益の出どころ = 公表済みの3つのルールは変えない）：
  1 建玉 = 目標 ÷ 翌日の値動きの見積もり（HAR 型：当日・5日・22日の値幅から。係数は 2018年までの先物のデータで決めて固定）
  2 VIX の状態で倍率（過去の分布の下 1/3 なら 0.5 倍、中 1.0 倍、上 1/3 なら 1.5 倍。VIX は1日前の終値）
  3 毎日、その日の値動きの見積もりの 3 倍下に、逆指値を置き直す
確かめること：
  A 改良を1つずつ足したときの成績（現物の3指数 26年、CFD の2指数 15年。全期間の値動きを年10%にそろえる）
  B 建玉の大きさの数式：
    - 伸びが最大になる大きさ（ケリー）：E[log(1 + λ·r)] が最大になる λ。r は「値動き年10%」のときの日次の損益
    - 下落を抑える条件つきのケリー（Busseti・Ryu・Boyd 2016年）：
      「資産が元の α 倍を下回る確率を β 以下にする」には、E[(1 + λ·r)^(−γ)] ≤ 1（γ = log β ÷ log α）を満たす最大の λ を使う
    - 過去の日次の損益を、かたまり（平均20日）ごとに並べ替えた 2万通りの3年間で、年率の中央値・最大の下落の分布を確かめる
使い方: python3 tools/research/index_final.py  → reports/research/index_final.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import fred_data as F  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_vix_sizing as V  # noqa: E402

ANN = 252
MULT = (0.5, 1.0, 1.5)
K_STOP = 3.0


def v60_sets(sets):
    """同じ組で、値動きの見積もりだけを「直近60日」に置きかえたもの（今の EA の形）。"""
    out = {}
    for name, (d, n, sg, rate, div) in sets.items():
        s60 = (d["close"].pct_change().rolling(60, min_periods=40).std()).clip(lower=0.025 / np.sqrt(ANN))
        out[name] = (d, n, s60, rate, div)
    return out


def block_bootstrap(z, years, n_paths, block=20, seed=7):
    """日次の損益 z を、かたまり（長さは平均 block 日の幾何分布）ごとに並べ替えた道筋。戻り値は (n_paths, 日数) の配列。"""
    rng = np.random.default_rng(seed)
    T = int(years * ANN)
    zv = z.values
    N = len(zv)
    out = np.empty((n_paths, T))
    for p in range(n_paths):
        i = 0
        pos = rng.integers(0, N)
        while i < T:
            if rng.random() < 1.0 / block:
                pos = rng.integers(0, N)
            out[p, i] = zv[pos % N]
            pos += 1
            i += 1
    return out


def main():
    lines = ["# 研究：売られすぎの戻りの層の改良後の形と、建玉の大きさの数式（`tools/research/index_final.py`）", ""]
    keep = {}
    for kind, title, start, per in (("cash", "現物の3指数（S&P500・NASDAQ100・ダウ）、2000年10月〜2026年11月", IRK.START, IRK.PER),
                                    ("cfd", "EA と同じ形（CFD の日足、S&P500 と NASDAQ100）、2011年9月〜2026年10月", "2011-09-01", V.PER_C)):
        sets = V.load_sets(kind)
        old = v60_sets(sets)
        rk = {n: V.vix_rank(t[0].index)[0] for n, t in sets.items()}
        one = {n: V.mult_of(rk[n], None) for n in sets}
        vm = {n: V.mult_of(rk[n], MULT) for n in sets}
        head = "| 形 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | プラスの年 | " + " | ".join(p[0] for p in per) + " |"
        lines += [f"## A {title}", "", head, "|---|" + "---|" * (7 + len(per))]
        for label, ss, mm, k in (("今の EA（直近60日の値動きで建玉を決める）", old, one, None), ("1 HAR 型の見積もりで建玉を決める", sets, one, None),
                                 ("1＋2 VIX の状態で倍率", sets, vm, None), ("1＋3 逆指値 3×σ", sets, one, K_STOP),
                                 ("**1＋2＋3（改良後の形）**", sets, vm, K_STOP)):
            s, z = V.stat(V.sleeve(ss, mm, kind, k), start, per)
            lines.append(f"| {label} | {s} |")
            keep[f"{kind}|{label}"] = z
            print(lines[-1], flush=True)
        lines.append("")
    # B 建玉の大きさの数式（現物の26年の、改良後の形の日次の損益を使う）
    z = keep["cash|**1＋2＋3（改良後の形）**"].dropna()
    z0 = keep["cash|今の EA（直近60日の値動きで建玉を決める）"].dropna()
    lam = np.arange(0.25, 12.01, 0.25)

    def growth(zz, la):
        x = 1.0 + la * zz.values
        return -np.inf if (x <= 0).any() else np.mean(np.log(x)) * ANN

    def rck(zz, alpha, beta):
        gam = np.log(beta) / np.log(alpha)
        best = 0.0
        for la in np.arange(0.05, 12.01, 0.05):
            x = 1.0 + la * zz.values
            if (x <= 0).any() or np.mean(x ** (-gam)) > 1.0:
                break
            best = la
        return best
    lines += ["## B 建玉の大きさの数式（現物の26年の日次の損益から）", "",
              "λ = 口座の値動きを年 (10 × λ)% にする倍率。伸び = E[log(1 + λ·r)] × 252（年率、対数）。", "",
              "| 形 | シャープ | 伸びが最大になる λ（ケリー） | そのときの値動き | 伸び（年率） | 半分のケリー：値動き・伸び | 条件つき：30%の下落を10%以下に | 50%の下落を5%以下に | 20%の下落を10%以下に |",
              "|---|---|---|---|---|---|---|---|---|"]
    for label, zz in (("今の EA", z0), ("改良後の形", z)):
        gs = np.array([growth(zz, la) for la in lam])
        i = int(np.nanargmax(gs))
        half = lam[i] / 2.0
        cells = []
        for a, b in ((0.7, 0.10), (0.5, 0.05), (0.8, 0.10)):
            la = rck(zz, a, b)
            cells.append(f"λ {la:.2f}（値動き 年{la * 10:.0f}%、伸び {(np.exp(growth(zz, la)) - 1) * 100:+.1f}%）")
        sh = zz.mean() / zz.std() * np.sqrt(ANN)
        lines.append(f"| {label} | {sh:+.2f} | {lam[i]:.2f} | 年{lam[i] * 10:.0f}% | {(np.exp(gs[i]) - 1) * 100:+.1f}% | 年{half * 10:.0f}%・{(np.exp(growth(zz, half)) - 1) * 100:+.1f}% | "
                     + " | ".join(cells) + " |")
        print(lines[-1], flush=True)
    # 並べ替えた3年間・10年間
    lines += ["", "### 過去の日次の損益を並べ替えた 2万通り（改良後の形。かたまりの長さは平均20日）", "",
              "| 口座の値動き（年） | 3年後：年率の中央値 | 下位10% | 上位10% | 3年のあいだの最大の下落：中央値 | 下落が 20% を超える | 30% を超える | 50% を超える | 3年後に元本割れ | 過去26年の実際：最悪の日・最大の下落 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    paths = block_bootstrap(z, 3, 20000)
    for vol in (5, 10, 15, 20, 30, 40, 60):
        la = vol / 10.0
        x = 1.0 + la * paths
        x = np.maximum(x, 1e-9)
        eq = np.cumprod(x, axis=1)
        cagr = eq[:, -1] ** (1 / 3.0) - 1
        dd = (eq / np.maximum.accumulate(np.maximum(eq, 1.0), axis=1) - 1).min(axis=1)
        ez = (1 + la * z).cumprod()
        lines.append(f"| {vol}% | {np.median(cagr) * 100:+.1f}% | {np.quantile(cagr, 0.1) * 100:+.1f}% | {np.quantile(cagr, 0.9) * 100:+.1f}% | {np.median(dd) * 100:.0f}% | "
                     f"{(dd < -0.2).mean() * 100:.0f}% | {(dd < -0.3).mean() * 100:.0f}% | {(dd < -0.5).mean() * 100:.1f}% | {(eq[:, -1] < 1).mean() * 100:.0f}% | "
                     f"{z.min() * la * 100:.1f}%・{(ez / ez.cummax() - 1).min() * 100:.0f}% |")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_final.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    pd.DataFrame(keep).to_parquet(os.path.join(D.CACHE, "index_final_returns.parquet"))


if __name__ == "__main__":
    main()

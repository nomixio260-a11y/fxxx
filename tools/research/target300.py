#!/usr/bin/env python3
"""研究：「1年で +300%（資産が4倍）」は達成できるか。数学と、EA と同じ制約での確率（101章）。

1 理論（値動きが正規分布に近いとして）
  - ケリー基準：年率シャープ S の手法を、ケリーの c 倍の大きさで持つと、1年の伸び（対数）の期待値は S²（c − c²/2）、ばらつきは c×S。
    伸びが最大になるのは c = 1（期待値 S²/2）。それ以上に大きくしても、伸びは下がる。
  - 1年後に4倍以上になる確率（一定の大きさで持つ場合）：1 − Φ((ln 4 − 期待値) ÷ ばらつき)。
  - 「期限までに目標に届く確率」を最大にする持ち方（Browne 1999年）の上限：Φ(Φ⁻¹(今の資産 ÷ 目標) + S×√年数)。
    この持ち方は、届かなかったときに資産のほぼすべてを失う（目標か、ほぼゼロか、の二択になる）。
2 EA と同じ制約での計算（1分足から作った CFD の日足、S&P500 と NASDAQ100、2011年9月〜2026年10月。lot_rounding.py の計算）
  - 重み 1:2:4・VIX の倍率・逆指値 4×σ・強制ロスカットを避ける上限（余裕の係数 0.9）・スプレッド・スワップ込み。元金は大きくして、最小の取引単位の影響を除く。
  - ルール1つ分の大きさを 5%〜200% まで変える（大きくすると、ほとんどの日で「強制ロスカットを避ける上限」いっぱいまで持つ形になる）。
  - 物差し：年率の伸び、最大の下落、実際にあった12か月（1日ずつずらした窓）の最高・中央・最低、+300% 以上だった窓の割合。
    損益の並びを20日のかたまりで並べ替えた 1年間の道筋 20,000 本での、+300% 以上・+100% 以上・−50% 以下・−80% 以下の確率。
3 「1年後に4倍」に届く確率を最大にする持ち方（動的計画法）
  - 毎日、その時点の資産と残りの日数を見て、ルール1つ分の大きさを選び直す（負けているほど・期限が近いほど大きく賭ける形になる）。
  - 選べる大きさは 2 と同じ（EA の制約の中）。届く確率の上限と、そのときに資産を半分以下・2割以下にして終わる確率を出す。
  - 「資産が半分になったらやめる」という条件をつけた場合も計算する。
使い方: python3 tools/research/target300.py  → reports/research/target300.md
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AMS_OANDA", "1")
import fred_data as F  # noqa: E402
import lot_rounding as LR  # noqa: E402

ANN = 252
GOAL = 4.0
UNITS = (5.0, 8.75, 12.5, 17.5, 25.0, 35.0, 50.0, 75.0, 100.0, 200.0)
START, END = "2011-09-01", "2026-10-30"


def boot_paths(R, n_path=20000, days=252, block=20, seed=11):
    """R：日 × 設定 の日次の損益。同じ日の並び（20日のかたまり）を、すべての設定に共通で使う。戻り値：道筋 × 日 の、日の番号。"""
    rng = np.random.default_rng(seed)
    n = R.shape[0]
    starts = rng.integers(0, n, size=(n_path, days // block + 1))
    return ((starts[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(n_path, -1)[:, :days]


def main():
    lines = ["# 研究：「1年で +300%（資産が4倍）」は達成できるか（`tools/research/target300.py`）", ""]
    # ---------- 1 理論
    lines += ["## 1 理論：年率シャープ S の手法で、何ができるか", "",
              "| 年率シャープ S | 伸びが最大の持ち方（ケリー）での、1年の成績の中央値 | そのときの口座の値動き（年） | 一定の大きさで持つとき、1年で4倍以上になる確率の最大（そのときの値動き・半分以下になる確率） | "
              "届く確率を最大にする持ち方（Browne）の上限（届かなければ、ほぼ全額を失う） |", "|---|---|---|---|---|"]
    for S in (0.86, 1.10, 1.30, 1.665, 2.0, 3.0):
        best = (0.0, 0.0, 0.0)
        for c in np.arange(0.2, 8.01, 0.05):
            g, sd = S * S * (c - c * c / 2.0), c * S
            p = 1.0 - norm.cdf((np.log(GOAL) - g) / sd)
            if p > best[0]:
                best = (p, sd, norm.cdf((np.log(0.5) - g) / sd))
        browne = norm.cdf(norm.ppf(1.0 / GOAL) + S)
        note = {0.86: "（この手法の26年）", 1.10: "（この手法の直近3年）", 1.665: "（中央値がちょうど +300% になる水準）"}.get(S, "")
        lines.append(f"| {S:.2f}{note} | {np.exp(S * S / 2) * 100 - 100:+.0f}% | {S * 100:.0f}% | {best[0] * 100:.0f}%（値動き 年{best[1] * 100:.0f}%・{best[2] * 100:.0f}%） | {browne * 100:.0f}% |")
        print(lines[-1], flush=True)
    lines += ["", "- 「中央値」は、同じことを何度も繰り返したときの真ん中の結果。ケリーより大きく持つと、中央値は下がる（大きく勝つ年と、大きく負ける年に分かれるだけ）。",
              "- どの行でも、1年で4倍に**必ず**届く持ち方は存在しない。確率を上げる方法は、「届かなければほぼ全額を失う」賭け方だけ。", ""]

    # ---------- 2 EA と同じ制約
    eqs = {}
    for u in UNITS:
        eqs[u] = LR.simulate("floor", START, END, 1e10, u, return_eq=True)
        print("sim", u, f"{eqs[u].iloc[-1] / 1e10:.2f}", flush=True)
    idx = eqs[UNITS[0]].index
    R = np.column_stack([eqs[u].pct_change().fillna(0.0).values for u in UNITS])
    R = np.maximum(R, -0.999)
    yrs = (idx[-1] - idx[0]).days / 365.25
    P = boot_paths(R)
    lines += ["## 2 EA と同じ制約での、1年の成績（CFD の日足・2銘柄・15年。強制ロスカットを避ける上限あり）", "",
              "| ルール1つ分 | 15年の年率の伸び | 口座の値動き（年） | 最大の下落 | 最悪の日 | 実際にあった12か月：最高 | 中央 | 最低 | +300% 以上だった12か月の割合 | "
              "並べ替えた1年 20,000 本：+300% 以上 | +100% 以上 | −50% 以下 | −80% 以下 | 中央値 |", "|---|" + "---|" * 13]
    for k, u in enumerate(UNITS):
        e = eqs[u]
        r = R[:, k]
        roll = (e / e.shift(ANN) - 1.0).dropna()
        fin = np.prod(1.0 + R[P, k], axis=1)
        lines.append(f"| {u:g}% | {((e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1) * 100:+.1f}% | {r.std() * np.sqrt(ANN) * 100:.0f}% | {(e / e.cummax() - 1).min() * 100:.0f}% | {r.min() * 100:.1f}% | "
                     f"{roll.max() * 100:+.0f}% | {roll.median() * 100:+.0f}% | {roll.min() * 100:+.0f}% | {(roll >= GOAL - 1).mean() * 100:.1f}% | "
                     f"{(fin >= GOAL).mean() * 100:.2f}% | {(fin >= 2.0).mean() * 100:.1f}% | {(fin <= 0.5).mean() * 100:.1f}% | {(fin <= 0.2).mean() * 100:.1f}% | {np.median(fin) * 100 - 100:+.0f}% |")
        print(lines[-1], flush=True)

    # ---------- 3 目標に届く確率を最大にする持ち方（動的計画法）。日は独立に選ぶ（並びの影響は、あとで並べ替えた道筋で確かめる）
    grid = np.linspace(np.log(0.02), np.log(GOAL), 400)
    logR = np.log1p(R)                                   # 日 × 設定
    res = []
    for floor in (None, 0.5):
        V = (grid >= np.log(GOAL) - 1e-12).astype(float)
        pol = np.zeros((ANN, len(grid)), dtype=np.int8)
        for n in range(ANN):                             # 残り n+1 日
            best = np.full(len(grid), -1.0)
            for k in range(len(UNITS)):
                nxt = grid[:, None] + logR[None, :, k]   # 資産 × 日
                v = np.interp(nxt.ravel(), grid, V, left=0.0, right=1.0).reshape(nxt.shape).mean(axis=1)
                upd = v > best + 1e-12
                best[upd] = v[upd]
                pol[ANN - 1 - n, upd] = k
            best[grid >= np.log(GOAL) - 1e-12] = 1.0     # 届いたら、そこでやめる
            if floor is not None:
                best[grid <= np.log(floor)] = 0.0        # 半分になったら、そこでやめる
            V = best
        p0 = float(np.interp(0.0, grid, V))
        # 並べ替えた道筋（20日のかたまり）で、この持ち方を実際に動かす
        w = np.zeros(P.shape[0])
        done = np.zeros(P.shape[0], dtype=bool)
        used = []
        for t in range(ANN):
            gi = np.clip(np.searchsorted(grid, w), 0, len(grid) - 1)
            k = pol[t, gi]
            step = logR[P[:, t], k]
            used.append(np.array(UNITS)[k][~done].mean() if (~done).any() else 0.0)
            w = np.where(done, w, w + step)
            done |= (w >= np.log(GOAL))
            if floor is not None:
                done |= (w <= np.log(floor))
        fin = np.exp(w)
        res.append((floor, p0, (fin >= GOAL - 1e-9).mean(), (fin <= 0.5 + 1e-9).mean(), (fin <= 0.2).mean(), np.median(fin), np.mean(used[:20]), np.mean(used)))
        print(res[-1], flush=True)
    lines += ["", "## 3 「1年後に4倍」に届く確率を最大にする持ち方（毎日、資産と残りの日数を見て、大きさを選び直す）", "",
              "| 条件 | 届く確率（計算の上） | 届く確率（並べ替えた道筋で動かした結果） | 半分以下で終わる確率 | 2割以下で終わる確率 | 1年後の資産の中央値 | 最初の20日に選んだ大きさの平均 | 1年を通した平均 |",
              "|---|---|---|---|---|---|---|---|"]
    for floor, p0, pg, p50, p20, med, u0, ua in res:
        lines.append(f"| {'制限なし（EA の制約の中で、何をしてもよい）' if floor is None else '資産が半分になったら、そこでやめる'} | {p0 * 100:.1f}% | {pg * 100:.1f}% | {p50 * 100:.1f}% | {p20 * 100:.1f}% | "
                     f"{med * 100 - 100:+.0f}% | {u0:.0f}% | {ua:.0f}% |")
    lines += ["", "- 一定の大きさで持つ形（2 の表）と比べて、届く確率は上がるが、代わりに、届かなかったときの損失が大きくなる。",
              "- どの持ち方でも、届く確率は 100% にならない。"]
    out = os.path.join(F.ROOT, "reports", "research", "target300.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""研究：2つの口座（株価指数の口座 ＋ 商品の口座）を合わせた成績と、「1年で4倍（+300%）」に届く確率（105章）。

- 材料：MT5 のテスターが書き出した、日ごとの有効証拠金（reports/runs/NNNN_equity.csv。含み損益を含む資産の動き。
  OANDA の実際の値段・その口座の実際のレバレッジ・建玉の丸め・証拠金の上限・逆指値をすべて含んだ結果）。
- 1 口座ごとの成績（資産の動きで測る。決済の時点で測ると、長く持つ順張りは月ごとの数字が歪むため）。
- 2 口座を合わせた成績：最初に資金を分け、口座のあいだで資金は動かさない（OANDA では口座どうしの資金移動は手作業のため）。
  12か月の成績は、「その日に、決めた割合で資金を分けて始めた」ときの1年後の合計（始める日を1日ずつずらす）。
- 3 「12か月で4倍に届く確率」：日々の損益（資産の動き）を、20日のかたまりで並べ替えて、1年分の道筋を 20,000 本作る（ブロック・ブートストラップ）。
  指数の口座は約7年分（2019年11月〜）、商品の口座は約20年分（2007年〜）の日々の損益から、別々に取り出す（2つの相関は、ほぼ 0 のため）。
  あわせて、期待値（日々の損益の平均）を半分にした場合も計算する（過去の成績は、実力より良く出ている可能性があるため）。
- 対象の実行は、reports/runs の見出しから探す（874番以降）。
使い方: python3 tools/research/composite_accounts.py  → reports/research/composite_accounts.md
"""
import glob
import os
import re
import sys
from math import erf, sqrt

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402

RUNS = os.path.join(F.ROOT, "reports", "runs")
FIRST_RUN = 874
ANN = 252


def catalog():
    out = {}
    for f in sorted(glob.glob(os.path.join(RUNS, "*_equity.csv"))):
        run = int(os.path.basename(f)[:4])
        if run < FIRST_RUN:
            continue
        h = open(os.path.join(RUNS, f"{run:04d}.txt"), encoding="utf-8").read().split("\n")[0]
        g = lambda k: (re.search(k + r"=(\S+)", h) or [None, "?"])[1]  # noqa: E731
        u = re.search(r"InpIxTrendUnitVol=([\d.]+);InpIxSLVolMul=(\d)", g("inputs"))
        if g("account") == "commodity" and u:
            key = ("金", float(u.group(1)), "tick" if g("model") == "4" else "long")
        elif g("account") == "index" and g("inputs") == "default":
            key = (g("preset").replace("AMS_Sleeves_", "").replace(".set", ""), 0.0, "tick" if g("model") == "4" else "long")
        else:
            continue
        e = pd.read_csv(f)
        e.index = pd.to_datetime(e["date"], format="%Y.%m.%d")
        e = e["equity"].astype(float)
        e = e[e.index.dayofweek < 5]
        out[key] = dict(run=run, eq=e, dep=float(g("deposit")), frm=g("from"))    # 同じ設定の実行が複数あれば、新しいほうを使う
    return out


def rel(c):
    """最初の資金を 1 とした資産の動き（最初の取引の前の日から）。"""
    e = c["eq"] / c["dep"]
    e = pd.concat([pd.Series([1.0], index=[e.index[0] - pd.Timedelta(days=1)]), e])      # 最初の資金（1）から始める
    r = e.pct_change().fillna(0.0)
    first = r[r.abs() > 1e-12].index[0]
    return e[e.index >= first - pd.Timedelta(days=5)]


def roll12(e):
    """その日に始めたときの、365日後の成績（始める日を1日ずつずらす）。"""
    idx, v = e.index, e.values
    out, j = [], 0
    for i in range(len(idx)):
        while j < len(idx) and (idx[j] - idx[i]).days < 365:
            j += 1
        if j >= len(idx):
            break
        out.append(v[j] / v[i] - 1.0)
    return pd.Series(out, index=idx[:len(out)])


def stats(e):
    r = e.pct_change().dropna()
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    ro = roll12(e)
    return dict(tot=e.iloc[-1] / e.iloc[0] - 1, cagr=(e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1, sh=r.mean() / r.std() * np.sqrt(ANN), vol=r.std() * np.sqrt(ANN),
                dd=(e / e.cummax() - 1).min(), wday=r.min(), best=ro.max() if len(ro) else np.nan, worst=ro.min() if len(ro) else np.nan,
                ge300=(ro >= 3.0).mean() if len(ro) else np.nan, best_at=ro.idxmax() if len(ro) else None)


def row(label, e):
    s = stats(e)
    by = e.groupby(e.index.year).last()
    prev = pd.concat([pd.Series([e.iloc[0]]), by]).values[:-1]
    yr = " ".join(f"{y}:{v * 100:+.0f}" for y, v in zip(by.index, by.values / prev - 1))
    return (f"| {label} | {e.index[0].date()}〜{e.index[-1].date()} | {s['tot'] * 100:+.0f}% | {s['cagr'] * 100:+.0f}% | {s['vol'] * 100:.0f}% | {s['sh']:.2f} | {s['dd'] * 100:.0f}% | {s['wday'] * 100:.1f}% | "
            f"{s['best'] * 100:+.0f}%（{s['best_at'].date() if s['best_at'] is not None else '—'}〜） | {s['worst'] * 100:+.0f}% | {s['ge300'] * 100:.0f}% | {yr} |")


def combo(ei, eg, a):
    """資金の a を指数の口座、1−a を商品の口座に分けて始め、動かさない。戻り値：合計の資産（最初 = 1）。"""
    idx = ei.index.intersection(eg.index)
    return a * ei.reindex(idx) / ei.reindex(idx).iloc[0] + (1 - a) * eg.reindex(idx) / eg.reindex(idx).iloc[0]


def combo_roll(ei, eg, a):
    """その日に a：1−a に分けて始めたときの、365日後の合計の成績。"""
    idx = ei.index.intersection(eg.index)
    ri, rg = roll12(ei.reindex(idx)), roll12(eg.reindex(idx))
    return a * ri + (1 - a) * rg


def combo_rebal(ei, eg, a):
    """年が変わるたびに、資金を a：1−a に戻す（口座のあいだで手作業で資金を動かす）。戻り値：合計の資産（最初 = 1）。"""
    idx = ei.index.intersection(eg.index)
    ri, rg = ei.reindex(idx).pct_change().fillna(0.0), eg.reindex(idx).pct_change().fillna(0.0)
    tot, vi, vg, year, out = 1.0, a, 1 - a, idx[0].year, []
    for t, x, y in zip(idx, ri.values, rg.values):
        if t.year != year:
            tot, year = vi + vg, t.year
            vi, vg = a * tot, (1 - a) * tot
        vi, vg = vi * (1 + x), vg * (1 + y)
        out.append(vi + vg)
    return pd.Series(out, index=idx)


def boot(r, n_path=20000, days=252, block=20, seed=11):
    rng = np.random.default_rng(seed)
    v = r.values
    n = len(v)
    starts = rng.integers(0, n, size=(n_path, days // block + 1))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(n_path, -1)[:, :days]
    return np.cumprod(1.0 + v[idx], axis=1)


def prob_row(label, paths):
    fin = paths[:, -1]
    return (f"| {label} | {np.median(fin) * 100 - 100:+.0f}% | {np.quantile(fin, 0.05) * 100 - 100:+.0f}% | {np.quantile(fin, 0.95) * 100 - 100:+.0f}% | {(fin >= 4.0).mean() * 100:.1f}% | "
            f"{(paths.max(axis=1) >= 4.0).mean() * 100:.1f}% | {(fin >= 2.0).mean() * 100:.0f}% | {(fin < 1.0).mean() * 100:.0f}% | {(paths.min(axis=1) <= 0.5).mean() * 100:.0f}% | {(paths.min(axis=1) <= 0.25).mean() * 100:.1f}% |")


def Phi(x):
    return 0.5 * (1 + erf(x / sqrt(2)))


def Phi_inv(p):
    lo, hi = -10.0, 10.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if Phi(mid) < p else (lo, mid)
    return 0.5 * (lo + hi)


def main():
    cat = catalog()
    E = {k: rel(c) for k, c in cat.items()}
    lines = ["# 研究：2つの口座を合わせた成績と、「1年で4倍」に届く確率（`tools/research/composite_accounts.py`）", "",
             "材料は、MT5 のテスターが書き出した日ごとの有効証拠金（含み損益を含む資産の動き）。「実際のティック」は直近3年、「長い期間」は1分足の四本値。", "",
             "## 1 口座ごとの成績（資産の動きで測ったもの）", "",
             "| 口座・設定 | 期間 | 合計 | 年率 | 値動き（年） | シャープ | 最大の下落（日ごとの資産） | 最悪の日 | 12か月：最高（始めた日） | 12か月：最低 | 12か月で +300% 以上だった割合 | 年ごと（%） |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    order = [k for k in (("Index_Demo", 0.0), ("Index_Growth", 0.0), ("Index", 0.0), ("金", 11.2), ("金", 22.4), ("金", 33.6), ("金", 50.0))]
    name = lambda k: (f"商品の口座：金の順張り {k[1]:g}%" + ("（逆指値なし）" if k[1] < 12 else "（逆指値 4×σ）")) if k[0] == "金" else f"指数の口座：{k[0]}"  # noqa: E731
    for mode, lab in (("tick", "実際のティック"), ("long", "長い期間")):
        for k in order:
            key = (k[0], k[1], mode)
            if key in E:
                lines.append(row(f"{name(k)}・{lab}（実行 {cat[key]['run']}）", E[key]))
                print(lines[-1], flush=True)
    # ---------- 相関
    lines += ["", "## 2 2つの口座の、日々の損益の相関", ""]
    for mode, lab in (("tick", "実際のティック（直近3年）"), ("long", "長い期間（重なる時期）")):
        ki, kg = ("Index_Demo", 0.0, mode), ("金", 22.4, mode)
        if ki in E and kg in E:
            z = pd.concat([E[ki].pct_change(), E[kg].pct_change()], axis=1, sort=True).dropna()
            lines.append(f"- {lab}：{z.corr().iloc[0, 1]:+.2f}（{len(z)} 日）")
            print(lines[-1], flush=True)
    # ---------- 合わせた成績
    lines += ["", "## 3 2つの口座を合わせた成績（最初に分けて、動かさない）", "",
              "| 指数の口座 | 商品の口座 | 資金の分け方（指数：商品） | データ | 期間 | 合計 | 年率 | シャープ | 最大の下落 | 最悪の日 | 12か月：最高 | 12か月：最低 | 12か月で +300% 以上だった割合 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for mode, lab in (("tick", "実際のティック"), ("long", "長い期間")):
        for ip in ("Index_Demo", "Index_Growth"):
            for gu in (11.2, 22.4, 33.6, 50.0):
                ki, kg = (ip, 0.0, mode), ("金", gu, mode)
                if ki not in E or kg not in E:
                    continue
                for a in (0.5, 0.7, 0.3):
                    e = combo(E[ki], E[kg], a)
                    s = stats(e)
                    ro = combo_roll(E[ki], E[kg], a)
                    lines.append(f"| {ip} | 金 {gu:g}% | {a * 100:.0f}：{(1 - a) * 100:.0f} | {lab} | {e.index[0].date()}〜{e.index[-1].date()} | {s['tot'] * 100:+.0f}% | {s['cagr'] * 100:+.0f}% | {s['sh']:.2f} | "
                                 f"{s['dd'] * 100:.0f}% | {s['wday'] * 100:.1f}% | {ro.max() * 100:+.0f}%（{ro.idxmax().date()}〜） | {ro.min() * 100:+.0f}% | {(ro >= 3.0).mean() * 100:.0f}% |")
                    print(lines[-1], flush=True)
    # ---------- 年に1回、割合を戻す
    lines += ["", "### 年に1回、資金を決めた割合に戻した場合（長い期間。口座のあいだの資金移動は手作業）", "",
              "| 指数の口座 | 商品の口座 | 資金の分け方 | 動かさない：年率・最大の下落 | 年に1回戻す：年率・最大の下落 |", "|---|---|---|---|---|"]
    for ip in ("Index_Demo", "Index_Growth"):
        for gu in (22.4, 33.6, 50.0):
            ki, kg = (ip, 0.0, "long"), ("金", gu, "long")
            if ki not in E or kg not in E:
                continue
            for a in (0.5, 0.7):
                s0, s1 = stats(combo(E[ki], E[kg], a)), stats(combo_rebal(E[ki], E[kg], a))
                lines.append(f"| {ip} | 金 {gu:g}% | {a * 100:.0f}：{(1 - a) * 100:.0f} | {s0['cagr'] * 100:+.0f}%・{s0['dd'] * 100:.0f}% | {s1['cagr'] * 100:+.0f}%・{s1['dd'] * 100:.0f}% |")
                print(lines[-1], flush=True)
    # ---------- ケリーの計算
    lines += ["", "## 5 ケリーの計算（今の大きさは、資産の伸び率が最大になる大きさの何倍か）", "",
              "値動きが正規分布に近く、いつでも建玉を直せるという前提の式：伸び率が最大になるのは「口座の値動き（年）= シャープ」のとき。その c 倍の大きさでは、",
              "伸び率は最大の c ×（2 − c）倍、資産が一度でも半分になる確率は 0.5 の（2 ÷ c − 1）乗。c が 2 を超えると、長い目では資産が減る。", "",
              "| 設定（長い期間の実行から） | 値動き（年） | シャープ | c（測ったシャープのとき） | 伸び率（最大に対する割合） | 半分になる確率 | c（本当のシャープが半分だったとき） | 伸び率 | 半分になる確率 |", "|---|---|---|---|---|---|---|---|---|"]
    for k in order:
        key = (k[0], k[1], "long")
        if key not in E:
            continue
        st = stats(E[key])
        row_k = f"| {name(k)} | {st['vol'] * 100:.0f}% | {st['sh']:.2f} |"
        for shp in (st["sh"], st["sh"] / 2):
            c = st["vol"] / shp if shp > 0 else float("inf")
            row_k += f" {c:.2f} | {c * (2 - c) * 100:+.0f}% | {min(1.0, 0.5 ** (2 / c - 1)) * 100:.0f}% |"
        lines.append(row_k)
        print(lines[-1], flush=True)
    # ---------- 確率
    lines += ["", "## 4 これから先の12か月についての確率（日々の損益を20日のかたまりで並べ替えた 20,000 本）", "",
              "| 設定 | 12か月後：中央値 | 下位5% | 上位5% | 12か月後に4倍以上（+300%） | 途中で一度でも4倍に届く | 2倍以上 | 元金割れ | 途中で一度でも −50% | 途中で一度でも −75% |", "|---|---|---|---|---|---|---|---|---|---|"]
    R = {k: E[k].pct_change().dropna() for k in E if k[2] == "long"}
    P = {}
    for k in order:
        key = (k[0], k[1], "long")
        if key in R:
            P[key] = boot(R[key], seed=11 if k[0] == "金" else 23)
            lines.append(prob_row(f"{name(k)}（{len(R[key])} 日分から）", P[key]))
            print(lines[-1], flush=True)
    for ip in ("Index_Demo", "Index_Growth"):
        for gu in (22.4, 33.6, 50.0):
            ki, kg = (ip, 0.0, "long"), ("金", gu, "long")
            if ki in P and kg in P:
                for a in (0.5, 0.3):
                    lines.append(prob_row(f"{ip} ＋ 金 {gu:g}%（{a * 100:.0f}：{(1 - a) * 100:.0f}）", a * P[ki] + (1 - a) * P[kg]))
                    print(lines[-1], flush=True)
    lines += ["", "### 期待値（日々の損益の平均）を半分にした場合", "",
              "| 設定 | 12か月後：中央値 | 下位5% | 上位5% | 12か月後に4倍以上（+300%） | 途中で一度でも4倍に届く | 2倍以上 | 元金割れ | 途中で一度でも −50% | 途中で一度でも −75% |", "|---|---|---|---|---|---|---|---|---|---|"]
    P2 = {}
    for k in order:
        key = (k[0], k[1], "long")
        if key in R:
            P2[key] = boot(R[key] - 0.5 * R[key].mean(), seed=11 if k[0] == "金" else 23)
            lines.append(prob_row(f"{name(k)}", P2[key]))
            print(lines[-1], flush=True)
    for ip in ("Index_Growth",):
        for gu in (33.6, 50.0):
            ki, kg = (ip, 0.0, "long"), ("金", gu, "long")
            if ki in P2 and kg in P2:
                lines.append(prob_row(f"{ip} ＋ 金 {gu:g}%（50：50）", 0.5 * P2[ki] + 0.5 * P2[kg]))
                print(lines[-1], flush=True)
    # ---------- 理論上の上限（Browne 1999）
    lines += ["", "### 参考：理論上の上限（Browne 1999。期限までに目標に届く確率を最大にする賭け方をしたときの確率 = Φ(Φ⁻¹(今の資産 ÷ 目標) + シャープ × √年数)）", "",
              "| シャープ | 0.5 | 0.75 | 1.0 | 1.25 | 1.5 | 2.0 |", "|---|---|---|---|---|---|---|",
              "| 1年で4倍に届く確率の上限 | " + " | ".join(f"{Phi(Phi_inv(0.25) + s) * 100:.0f}%" for s in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)) + " |",
              "", "- この上限は、建玉の大きさに制限がなく、いつでも連続して売買でき、値動きが飛ばない、という前提の値です（届かなかった場合は、資金のほとんどを失う賭け方です）。"]
    out = os.path.join(F.ROOT, "reports", "research", "composite_accounts.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

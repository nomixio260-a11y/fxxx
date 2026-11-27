#!/usr/bin/env python3
"""研究：学習モデルで「建玉の大きさ」を決める（メタラベリング）。98章の「向きの予想」は公表済みのルールに勝てなかったので、形を変えて確かめる。

- 入るかどうかは、公表済みのルール（R2・D7・IBS）が決める。モデルは、ルールが出ている日だけを見て、「その日の建玉をどれだけ厚くするか」だけを決める。
- 予想するもの：翌日の損益 ÷ 値動きの見積もり（持ち越しのコスト込み）。
- 説明に使う値（どれも、その日の終値までに分かる値。VIX は1日前）：
  ルールの数と中身（R2・D7・IBS）、VIX の水準（過去の分布での位置）、VIX の5日の変化、値動きの見積もりの水準・直近60日との比、
  過去1・2・5日の値動き、IBS の値、RSI(2) の値、200日の平均からの離れ、20日の高値からの下げ、持ち始めてからの日数、200日の平均より上か
- モデル：リッジ回帰と、勾配ブースティング（小さな木に固定）。学習は 1999年4月〜（指数の値動きの性質が変わったあと。98章の 1）、
  **毎年、前の年までのデータで学習して、その年を予想**（最初の予想は 2006年）。
- 使い方：建玉 = ルールの数 ÷ 3 × 倍率。倍率 = 予想 ÷ 学習データでの予想の平均（0.5〜1.5 に収める／0〜2 に収める）。
- 比べる相手：同じ期間の、98章の改良後の形（VIX の状態で 0.5／1／1.5 倍）と、倍率なしの形。
使い方: python3 tools/research/index_meta.py  → reports/research/index_meta.md
"""
import os
import sys

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_vix_sizing as V  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
FIRST = 2006
TRAIN_FROM = "1999-04-01"
PER = (("2006〜10", "2006-01-01", "2011-01-01"), ("2011〜14", "2011-01-01", "2015-01-01"), ("2015〜21/10", "2015-01-01", "2021-11-01"),
       ("21/11〜26/11", "2021-11-01", "2026-12-01"))


def build(sets):
    vix = np.log(Y.fetch("VIX")["close"])
    rows = []
    for i, (name, (d, n, sg, rate, div)) in enumerate(sets.items()):
        c = d["close"]
        st = IR.rules(d)
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
        fin = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
        lc = np.log(c)
        f = pd.DataFrame(index=d.index)
        f["n"] = n
        f["R2"], f["D7"], f["IBSr"] = st["R2<10"], st["D7"], st["IBS"]
        rk, _ = V.vix_rank(d.index)
        f["vix_rank"] = rk
        dv5 = vix.diff(5)
        f["dvix5"] = dv5.reindex(dv5.index.union(d.index)).ffill(limit=3).reindex(d.index).shift(1)
        f["sig_rank"] = sg.expanding(min_periods=500).rank(pct=True)
        f["sig_ratio"] = (sg / c.pct_change().rolling(60).std()).clip(0.2, 5)
        for k in (1, 2, 5):
            f[f"r{k}"] = ((lc - lc.shift(k)) / (sg.shift(k) * np.sqrt(k))).clip(-8, 8)
        rng = d["high"] - d["low"]
        f["ibs"] = ((c - d["low"]) / rng.where(rng > 0)).fillna(0.5)
        f["rsi2"] = IR.rsi_wilder(c, 2) / 100.0
        f["ma200"] = (np.log(c / c.rolling(200).mean()) / (sg * 10.0)).clip(-8, 8)
        f["dd20"] = (np.log(c / c.rolling(20).max()) / (sg * np.sqrt(10.0))).clip(-8, 0)
        on = (n >= 1).astype(int)
        f["age"] = on.groupby((on == 0).cumsum()).cumsum().clip(upper=15)
        f["above"] = (c > c.rolling(200).mean()).astype(float)
        f["idx"] = i
        f["name"] = name
        f["y"] = ((c.pct_change() + fin).shift(-1) / sg)
        rows.append(f)
    P = pd.concat(rows)
    return P[(P.index >= TRAIN_FROM)]


def walk_forward(P, feats, model):
    Q = P[(P["n"] >= 1)].copy()
    Q["pred"] = np.nan
    Q["ref"] = np.nan
    yrs = Q.index.year.values
    for yr in range(FIRST, 2027):
        tr = (yrs < yr) & Q["y"].notna().values & Q[feats].notna().all(axis=1).values
        te = (yrs == yr) & Q[feats].notna().all(axis=1).values
        if tr.sum() < 1500 or te.sum() == 0:
            continue
        Xtr, ytr = Q.loc[tr, feats], Q.loc[tr, "y"].clip(-6, 6)
        if model == "ridge":
            mu, sd = Xtr.mean(), Xtr.std().replace(0, 1.0)
            Z = ((Xtr - mu) / sd).values
            b = np.linalg.solve(Z.T @ Z + 300.0 * np.eye(Z.shape[1]), Z.T @ (ytr.values - ytr.mean()))
            ptr = Z @ b + ytr.mean()
            pte = ((Q.loc[te, feats] - mu) / sd).values @ b + ytr.mean()
        else:
            m = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.03, max_depth=3, num_leaves=6, subsample=0.7, subsample_freq=1,
                                  colsample_bytree=0.7, min_child_samples=150, reg_lambda=10.0, random_state=1, verbose=-1)
            m.fit(Xtr, ytr)
            ptr, pte = m.predict(Xtr), m.predict(Q.loc[te, feats])
        Q.loc[te, "pred"] = pte
        Q.loc[te, "ref"] = max(float(np.mean(ptr)), 1e-6)
    return Q


def main():
    sets = V.load_sets("cash")
    P = build(sets)
    feats = [c for c in P.columns if c not in ("y", "name")]
    rk = {n: V.vix_rank(t[0].index)[0] for n, t in sets.items()}
    one = {n: V.mult_of(rk[n], None) for n in sets}
    vm = {n: V.mult_of(rk[n], (0.5, 1.0, 1.5)) for n in sets}
    lines = ["# 研究：学習モデルで建玉の大きさを決める（`tools/research/index_meta.py`）", "",
             f"米国3指数、学習は {TRAIN_FROM[:7]}〜、予想は {FIRST}年〜2026年11月（毎年、前の年までのデータで学習）。逆指値 4×σ、コスト込み、値動きを年10%にそろえる。", "",
             "## 予想と実際の関係（ルールが出ている日。見ていない期間）", "", "| モデル | 予想と実際の相関 | 予想が上位 1/3 の日の平均 | 中 | 下位 1/3 |", "|---|---|---|---|---|"]
    head = "| 形 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | プラスの年 | " + " | ".join(p[0] for p in PER) + " |"
    res = []
    start = f"{FIRST}-01-01"
    for label, mm in (("倍率なし", one), ("98章の形（VIX の状態で 0.5／1／1.5 倍）", vm)):
        s, _ = V.stat(V.sleeve(sets, mm, "cash", 4.0), start, PER)
        res.append(f"| {label} | {s} |")
    for mlabel, model in (("リッジ回帰", "ridge"), ("勾配ブースティング", "gbm")):
        Q = walk_forward(P, feats, model)
        ok = Q["pred"].notna() & Q["y"].notna()
        q1, q2 = Q.loc[ok, "pred"].quantile(1 / 3), Q.loc[ok, "pred"].quantile(2 / 3)
        ic = np.corrcoef(Q.loc[ok, "pred"], Q.loc[ok, "y"].clip(-6, 6))[0, 1]
        lines.append(f"| {mlabel} | {ic:+.4f}（{int(ok.sum())} 件） | {Q.loc[ok & (Q['pred'] >= q2), 'y'].mean():+.3f} | "
                     f"{Q.loc[ok & (Q['pred'] >= q1) & (Q['pred'] < q2), 'y'].mean():+.3f} | {Q.loc[ok & (Q['pred'] < q1), 'y'].mean():+.3f} |")
        print(lines[-1], flush=True)
        for clab, lo, hi in (("0.5〜1.5 倍", 0.5, 1.5), ("0〜2 倍", 0.0, 2.0)):
            mults = {}
            for name in sets:
                q = Q[Q["name"] == name]
                m = (q["pred"] / q["ref"]).clip(lo, hi)
                mults[name] = m.reindex(sets[name][0].index).fillna(1.0)
            s, _ = V.stat(V.sleeve(sets, mults, "cash", 4.0), start, PER)
            res.append(f"| {mlabel}：{clab} | {s} |")
            # モデルの倍率 × VIX の倍率（両方を使う）
            both = {n: (mults[n] * vm[n]).clip(0.0, 2.5) for n in sets}
            s, _ = V.stat(V.sleeve(sets, both, "cash", 4.0), start, PER)
            res.append(f"| {mlabel}：{clab} × VIX の倍率 | {s} |")
    lines += ["", "## 取引の成績（同じ期間・同じコスト）", "", head, "|---|" + "---|" * (7 + len(PER))] + res
    for x in res:
        print(x, flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_meta.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""複合システム：予想の確率を合成し、「確率に比例して持つ」売買を、コスト込みで検証する。日付・時刻・曜日は使わない。

- 入力：tools/eco/ml.py が出した、学習に使っていない年の予想（data/eco/preds_v1.parquet。2005〜2026年）。
- 合成のしかた（どれも、その日より前の結果だけで決める）：
   AVG   3つのモデルの確率の平均（対数オッズの平均）
   META  上位のモデル：3つの確率 ＋ 既存のルールの状態 ＋ 200日の平均の上下 ＋ VIX の位置 ＋ 銘柄の種類 から、確率を作り直す（毎年、前の年までの「予想と答え」で学習）
   HEDGE 専門家の重みづけ：3つのモデルと「既存のルール」を専門家とみなし、直近の当たり具合（対数損失。半減期250日でならす）が良いものほど重くする
         （相場の性質が変わったら、当たっているものに自動で重みが移る。重みは銘柄の種類ごと）
- 売買：その日の確率 p から、建玉 ＝ 目標の値動き × clip((p − b) ÷ s, −2, 2) ÷ その銘柄の値動きの大きさ。b はその種類の確率のふだんの水準、s はばらつき
  （どちらも前の年までの予想から計算）。「確率がふだんより高いほど大きく買い、低いほど売る」形。買いだけの形（マイナスは 0）も測る。
  コスト：スプレッド（片道：指数 0.01%・為替 0.006%・金属 0.02%）とスワップ（指数：買い 年 −4.79%・売り −0.21%、為替：年 −1.5%、金属：買い −3.6%・売り 0）。
- 比べる相手：指数は、いまの戻りの層（ルールの数に応じて 1:2:4 で買う。VIX の倍率なしの素の形）。金属は、200日の平均より上なら買い。
- 判定（モデルの結果を見る前に決めた）。確率のエンジンを、実際の売買の既定にする（いまの層と置き換える・混ぜる）のは、次をすべて満たすときだけ：
   (A) OANDA の CFD（US500・US100・US30。2018年〜、学習に使っていない年の予想）で、「いまの層と半分ずつ混ぜた形」のシャープが、
       いまの層だけより、前半（2018〜21年）・後半（2022年〜）の両方で 0.05 以上高い。または、エンジンだけで、両方の期間で、いまの層以上
   (B) 現物の米国3指数（2008年〜）でも、前半（2008〜16年）・後半（2017年〜）の両方で (A) と同じことが成り立つ
   (C) 確率が当たっている：確率の高さで10等分したとき、実際に上がった割合が、確率の順に並ぶ（順位の相関 0.8 以上。全銘柄）
   (D) 3つのモデルのうち2つ以上で、指数について、予想と答えの相関がはっきりプラス（t 値 2 以上）
  為替・金属は、エンジンだけのシャープ（コスト後）が前半・後半とも 0.4 以上なら「エンジンで売買できる」とする。
  満たさないあいだは、エンジンは「影」で動かす（毎日、確率と当たり外れを記録するが、資金は既存の層のまま）。記録がたまり、基準を満たしたら昇格させる。
  ※ 評価の計算の直し（基準は変えていない）：META・HEDGE の確率は、はじめは「前の年までの予想が2万行たまってから」作っていたため、2012年からしか
     なかった（現物の前半 2008〜16年が、ほかと違う期間になっていた）。8千行に下げて、2008年からそろえた。
使い方: python3 tools/eco/evaluate.py [v1|v2]  → reports/eco/v1.md・v2.md
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402

ANN = 252
SPREAD = {"index": 0.0001, "fx": 0.00006, "metal": 0.0002}                  # 片道
SWAP_L = {"index": -4.79, "fx": -1.5, "metal": -3.6}
SWAP_S = {"index": -0.21, "fx": -1.5, "metal": 0.0}
W_RULE = {0: 0.0, 1: 0.25, 2: 0.5, 3: 1.0}
US_CASH, US_CFD = ("SPX", "NDX", "DJI"), ("CFD_US500", "CFD_US100", "CFD_US30")


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def sig(x):
    return 1.0 / (1.0 + np.exp(-x))


EXPERTS = ("p_lr", "p_gbm", "p_cnn", "p_reg", "p_knn")
EXPERT_LABEL = {"p_lr": "LR 線形", "p_gbm": "GBM 勾配ブースティング", "p_cnn": "CNN チャートを読むモデル", "p_reg": "REG 期待値のモデル", "p_knn": "KNN 形の似た場面を探すモデル"}
MIN_ROWS = 8000


def add_ensembles(P):
    """AVG・META・HEDGE の確率を足す。"""
    from sklearn.linear_model import LogisticRegression
    P = P.sort_values(["date", "inst"]).reset_index(drop=True)
    exps = [k for k in EXPERTS if k in P.columns]
    L = np.column_stack([logit(P[k].values) for k in exps])
    P["p_avg"] = sig(np.nanmean(L, axis=1))
    L = np.nan_to_num(L)
    yr = P["date"].dt.year.values
    # ルールを「専門家」にする：その種類の、前の年までの「ルールの数 → 上がった割合」（ロジスティック）
    p_rule = np.full(len(P), np.nan)
    p_meta = np.full(len(P), np.nan)
    kd = pd.get_dummies(P["klass"]).reindex(columns=["index", "fx", "metal"], fill_value=0).values.astype(float)
    Xr = np.column_stack([P["st_n"].values, P["above200"].values, kd])
    Xm = np.column_stack([L, P["st_n"].values, P["above200"].values, np.nan_to_num(P["vix_rank"].values), kd])
    up = P["up"].values
    for Y in sorted(set(yr)):
        tr, te = yr < Y, yr == Y
        if tr.sum() < MIN_ROWS:
            continue
        m = LogisticRegression(C=1.0, max_iter=300).fit(Xr[tr], up[tr])
        p_rule[te] = m.predict_proba(Xr[te])[:, 1]
        if len(set(yr[tr])) >= 3:
            m2 = LogisticRegression(C=0.1, max_iter=300).fit(Xm[tr], up[tr])
            p_meta[te] = m2.predict_proba(Xm[te])[:, 1]
    P["p_rule"], P["p_meta"] = p_rule, p_meta
    # HEDGE：種類ごとに、専門家の直近の対数損失（半減期250日）で重みを決める。重みは、その日より前の結果だけから
    P["p_hedge"] = np.nan
    experts = exps + ["p_rule"]
    wrec = []
    for kl, g in P[P["p_rule"].notna()].groupby("klass"):
        g = g.copy()
        for e in experts:
            g[e] = g[e].fillna(0.5)
        loss = pd.DataFrame({e: -(g["up"] * np.log(g[e].clip(1e-4, 1 - 1e-4)) + (1 - g["up"]) * np.log((1 - g[e]).clip(1e-4, 1 - 1e-4))).groupby(g["date"]).mean() for e in experts})
        base = np.log(2.0)
        score = (base - loss).ewm(halflife=250).mean().shift(1).fillna(0.0)            # 前の日までの「コイン投げよりどれだけ良いか」
        w = np.exp(score * 400.0)
        w = w.div(w.sum(axis=1), axis=0)
        wrec.append(w.assign(klass=kl))
        wi = w.reindex(g["date"].values)
        P.loc[g.index, "p_hedge"] = sig((np.column_stack([logit(g[e].values) for e in experts]) * wi.values).sum(axis=1))
    return P, pd.concat(wrec), exps


def zscore(P, col):
    """確率 → 合図 z ＝（確率 − ふだんの水準 b）÷ ばらつき s を ±2 で打ち切ったもの。b・s は、その種類の、前の年までの予想から。"""
    yr = P["date"].dt.year.values
    z = np.full(len(P), np.nan)
    for kl in ("index", "fx", "metal"):
        mk = (P["klass"] == kl).values
        for Y in sorted(set(yr[mk])):
            tr, te = mk & (yr < Y) & P[col].notna().values, mk & (yr == Y)
            if tr.sum() < 3000:
                continue
            b, s = P.loc[tr, col].mean(), P.loc[tr, col].std()
            z[te] = ((P.loc[te, col] - b) / s).clip(-2, 2)
    return z


def positions(P, col, long_only=False):
    """確率 → 建玉（目標の値動き 年10% を 1 単位として、その何倍か ÷ 値動き）。"""
    z = zscore(P, col)
    if long_only:
        z = np.clip(z, 0, None)
    return z * 0.10 / (P["sig"].values * np.sqrt(ANN))


def pnl(P, w):
    """日々の損益（銘柄ごと）。w：その日の終値で決めた建玉（次の日の値動きを受ける）。"""
    g = P.assign(w=w)
    prev = g.groupby("inst")["w"].shift(1).fillna(0.0)
    sp = g["klass"].map(SPREAD).values
    sw = np.where(g["w"] > 0, g["klass"].map(SWAP_L).values, g["klass"].map(SWAP_S).values) / 100.0 / 360.0 * 1.45
    return g["w"] * g["r_next"] - (g["w"] - prev).abs() * sp + g["w"].abs() * sw


def port(P, r, insts=None, klass=None):
    m = P["inst"].isin(insts) if insts is not None else (P["klass"] == klass) & ~P["inst"].str.startswith("CFD_")
    x = pd.Series(r[m.values], index=P.loc[m, "date"]).dropna()
    return x.groupby(level=0).mean()


def sh(x, a=None, b=None):
    if a is not None:
        x = x[(x.index >= a) & (x.index < b)]
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 100 and x.std() > 0 else np.nan


def main():
    ver = sys.argv[1] if len(sys.argv) > 1 else "v1"
    P = pd.read_parquet(os.path.join(DS.CACHE, f"preds_{ver}.parquet"))
    P["date"] = pd.to_datetime(P["date"])
    P, W, exps = add_ensembles(P)
    singles = [(EXPERT_LABEL[c], c) for c in exps]
    engines = [("AVG 専門家の平均", "p_avg"), ("META 上位のモデル", "p_meta"), ("HEDGE 専門家の重みづけ", "p_hedge")]
    models = singles + engines
    L = [f"# 複合システム {ver}：予想の確率と、確率に比例して持つ売買の検証（`tools/eco/evaluate.py {ver}`）", "",
         f"学習に使っていない年の予想だけで測る（{P['date'].min().date()}〜{P['date'].max().date()}、{len(P):,} 行、{P['inst'].nunique()} 銘柄）。", "",
         "## 1 予想は当たっているか（予想の確率と、次の日の値動きの相関。t 値は日ごとの平均から）", "",
         "| モデル | 指数（現物11）：相関・t | 指数（OANDA の CFD 14）：相関・t | 為替17：相関・t | 金属3：相関・t | 当たった割合（全体） |", "|---|---|---|---|---|---|"]
    tstat = {}
    for lab, col in models + [("（参考）既存のルールだけ", "p_rule")]:
        cells = []
        for nm, mk in (("cash", (P["klass"] == "index") & ~P["inst"].str.startswith("CFD_")), ("cfd", P["inst"].str.startswith("CFD_")), ("fx", P["klass"] == "fx"), ("metal", P["klass"] == "metal")):
            g = P[mk & P[col].notna()]
            if len(g) < 500:
                cells.append("—")
                continue
            c = np.corrcoef(g[col], g["y"])[0, 1]
            dd = ((g[col] - g[col].mean()) * g["y"]).groupby(g["date"]).mean()
            t = dd.mean() / dd.std() * np.sqrt(len(dd))
            tstat[(col, nm)] = t
            cells.append(f"{c:+.3f}・{t:+.1f}")
        g = P[P[col].notna()]
        acc = ((g[col] > 0.5) == (g["up"] > 0.5)).mean()
        L.append(f"| {lab} | " + " | ".join(cells) + f" | {acc * 100:.1f}% |")
        print(L[-1], flush=True)
    base_up = P.groupby("klass")["up"].mean()
    L += ["", "（参考）上がった日の割合：" + "、".join(f"{k} {v * 100:.1f}%" for k, v in base_up.items())]
    # ---------- 較正
    L += ["", "## 2 確率は正しいか（確率の高さで10等分。全銘柄、HEDGE）", "", "| 区分（確率の低い順） | 予想の確率の平均 | 実際に上がった割合 | 次の日の値動きの平均（値動きの大きさ＝1） | 行数 |", "|---|---|---|---|---|"]
    g = P[P["p_hedge"].notna()].copy()
    g["dec"] = pd.qcut(g["p_hedge"], 10, labels=False, duplicates="drop")
    cal = g.groupby("dec").agg(p=("p_hedge", "mean"), up=("up", "mean"), y=("y", "mean"), n=("up", "size"))
    for k, r_ in cal.iterrows():
        L.append(f"| {int(k) + 1} | {r_.p * 100:.1f}% | {r_.up * 100:.1f}% | {r_.y:+.3f} | {int(r_.n):,} |")
    from scipy.stats import spearmanr
    rho_cal = spearmanr(cal["p"], cal["up"])[0]
    L.append(f"\n- 確率の順と、実際に上がった割合の順の相関：{rho_cal:+.2f}")
    # ---------- 売買
    R, RL = {}, {}
    for lab, col in models:
        R[col] = pnl(P, positions(P, col)).values
        RL[col] = pnl(P, positions(P, col, True)).values
    w_rule = P["st_n"].round().astype(int).map(W_RULE).values * 0.10 / (P["sig"].values * np.sqrt(ANN))
    r_rule = pnl(P, np.where(P["klass"] == "index", w_rule, 0.0)).values
    w_tr = np.where(P["above200"] > 0, 1.0, 0.0) * 0.10 / (P["sig"].values * np.sqrt(ANN))
    r_trend = pnl(P, w_tr).values
    sets = (("指数（現物の米国3指数）", dict(insts=US_CASH), "2008-01-01", "2017-01-01"), ("指数（OANDA の CFD：US500・US100・US30）", dict(insts=US_CFD), "2018-01-01", "2022-01-01"),
            ("指数（現物11）", dict(klass="index"), "2008-01-01", "2017-01-01"), ("指数（OANDA の CFD 14）", dict(insts=[i for i in P["inst"].unique() if i.startswith("CFD_")]), "2018-01-01", "2022-01-01"),
            ("為替17", dict(klass="fx"), "2012-01-01", "2019-01-01"), ("金属3", dict(klass="metal"), "2008-01-01", "2017-01-01"))
    short = lambda m: m[0].split(" ")[0]   # noqa: E731
    keep = {}
    for title, RR in (("## 3 確率に比例して持った場合の成績：買いと売り（コスト後のシャープ。全期間／前半／後半）", R), ("## 3b 同じく、買いだけ（確率がふだんより低いときは持たない）", RL)):
        L += ["", title, "", "| 銘柄の集まり（前半と後半の境目） | 比べる相手 | " + " | ".join(short(m) for m in models) + " |", "|---|---|" + "---|" * len(models)]
        for nm, kw, a, mid in sets:
            end = "2030-01-01"
            f3 = lambda x: f"{sh(x, a, end):+.2f}／{sh(x, a, mid):+.2f}／{sh(x, mid, end):+.2f}"   # noqa: E731
            is_metal, is_fx = "金属" in nm, "為替" in nm
            base = port(P, r_trend if is_metal else r_rule, **kw)
            bl = "なし" if is_fx else ("200日の平均より上で買い " if is_metal else "いまの戻りの層 ") + f3(base)
            cells = [f3(port(P, RR[c], **kw)) for _, c in models]
            keep[nm] = dict(base=base, a=a, mid=mid, kw=kw)
            L.append(f"| {nm}（{mid[:4]}年） | {bl} | " + " | ".join(cells) + " |")
            print(L[-1], flush=True)
    # ---------- いまの層と混ぜる（指数）
    L += ["", "## 4 指数：いまの戻りの層と、エンジン（買いだけ）を半分ずつ混ぜた場合（値動きをそろえて足す）", "",
          "| 銘柄の集まり | エンジン | いまの層だけ：全期間／前半／後半 | エンジンだけ | 半分ずつ | 2つの損益の相関 |", "|---|---|---|---|---|---|"]
    verdict = {}
    for nm in ("指数（現物の米国3指数）", "指数（OANDA の CFD：US500・US100・US30）"):
        k = keep[nm]
        a, mid, end = k["a"], k["mid"], "2030-01-01"
        for lab, col in engines:
            e = port(P, RL[col], **k["kw"])
            z = pd.concat([k["base"], e], axis=1).dropna()
            z = z[z.index >= a]
            mix = z.iloc[:, 0] / z.iloc[:, 0].std() + z.iloc[:, 1] / z.iloc[:, 1].std()
            f3 = lambda x: f"{sh(x, a, end):+.2f}／{sh(x, a, mid):+.2f}／{sh(x, mid, end):+.2f}"   # noqa: E731
            verdict[(nm, col)] = dict(b1=sh(z.iloc[:, 0], a, mid), b2=sh(z.iloc[:, 0], mid, end), e1=sh(z.iloc[:, 1], a, mid), e2=sh(z.iloc[:, 1], mid, end), m1=sh(mix, a, mid), m2=sh(mix, mid, end))
            L.append(f"| {nm} | {lab} | {f3(z.iloc[:, 0])} | {f3(z.iloc[:, 1])} | {f3(mix)} | {z.corr().iloc[0, 1]:+.2f} |")
            print(L[-1], flush=True)
    # ---------- 相場の状態ごと・急な値動きの翌日（米国3指数。HEDGE の買いだけ と、いまの層）
    L += ["", "## 5 相場の状態ごとの成績（米国3指数。1日あたりの損益の平均を年率に直したもの ÷ 全期間の値動き。エンジンは HEDGE の買いだけ）", "",
          "| 銘柄の集まり | 相場の状態（その日の朝に分かっているもの） | 日数の割合 | いまの層 | エンジン | 半分ずつ |", "|---|---|---|---|---|---|"]
    for nm, insts, a in (("現物の米国3指数（2008年〜）", US_CASH, "2008-01-01"), ("OANDA の CFD の米国3指数（2018年〜）", US_CFD, "2018-01-01")):
        m = P["inst"].isin(insts).values & (P["date"] >= a).values
        g = P[m].assign(rb=r_rule[m], re=RL["p_hedge"][m]).dropna(subset=["rb", "re"])
        sb, se = g.groupby("date")["rb"].mean().std(), g.groupby("date")["re"].mean().std()
        g["mix"] = (g["rb"] / sb + g["re"] / se) / 2.0
        hi_v = g["vix_rank"] > 1.0 / 3.0
        shock = g["ret1"].abs() >= 2.5
        states = (("200日の平均より上・VIX がふつう以下", (g["above200"] > 0) & ~hi_v), ("200日の平均より上・VIX が高い（上位 1/3）", (g["above200"] > 0) & hi_v),
                  ("200日の平均より下・VIX がふつう以下", (g["above200"] <= 0) & ~hi_v), ("200日の平均より下・VIX が高い", (g["above200"] <= 0) & hi_v),
                  ("前の日に急な値動き（ふだんの2.5倍以上）：下げ", shock & (g["ret1"] < 0)), ("前の日に急な値動き：上げ", shock & (g["ret1"] > 0)),
                  ("いまの層が持っている日（ルールが1つ以上）", g["st_n"] >= 0.5), ("いまの層が何も持っていない日", g["st_n"] < 0.5))
        nd = g["date"].nunique()
        cnt = g.groupby("date").size()                       # その日に値段がある銘柄の数（損益は、この数で割って足す）
        for lab, mk in states:
            x = g[mk]
            if len(x) < 30:
                L.append(f"| {nm} | {lab} | — | — | — | — |")
                continue
            f = lambda col, sd: (x.groupby("date")[col].sum() / cnt.reindex(x["date"].unique())).sum() / nd * ANN / (sd * np.sqrt(ANN))   # noqa: E731
            L.append(f"| {nm} | {lab} | {x['date'].nunique() / nd * 100:.0f}% | {f('rb', sb):+.2f} | {f('re', se):+.2f} | {f('mix', 1.0):+.2f} |")
            print(L[-1], flush=True)
    L += ["", "- 各行の数字を足すと（上の4行、または下の2行）、その列の全期間のシャープになる。どの状態で稼ぎ、どの状態で失っているかの内訳。",
          "- 下の2行：エンジンの利益が、いまの層と同じ日（ルールが出ている日）から来ているのか、いまの層が何も持っていない日からも来ているのか。"]
    # ---------- 銘柄どうしの比較（その日の全銘柄の平均より確率が高いものを買い、低いものを売る。相場全体の向きには賭けない）
    L += ["", "## 5b 銘柄どうしの比較で持った場合（z から、その日の全銘柄の平均を引く。買いと売りが同じ大きさ。コスト後のシャープ：全期間／前半／後半）", "",
          "| 銘柄の集まり | " + " | ".join(short(m) for m in engines) + " |", "|---|" + "---|" * len(engines)]
    for nm, kw, a, mid in (sets[3], sets[4]):               # 現物の指数は、国ごとに終値の時刻が違う（平均を引くと、あとで閉まる市場の情報が混ざる）ので、ここでは測らない
        m = (P["inst"].isin(kw["insts"]) if "insts" in kw else ((P["klass"] == kw["klass"]) & ~P["inst"].str.startswith("CFD_"))).values
        cells = []
        for lab, col in engines:
            z = pd.Series(zscore(P, col), index=P.index)
            zr = (z[m] - z[m].groupby(P.loc[m, "date"]).transform("mean"))
            w = np.zeros(len(P))
            w[m] = (zr * 0.10 / (P.loc[m, "sig"] * np.sqrt(ANN))).fillna(0.0).values
            x = port(P, pnl(P, w).values, **kw)
            x = x[x.index >= a]
            cells.append(f"{sh(x, a, '2030-01-01'):+.2f}／{sh(x, a, mid):+.2f}／{sh(x, mid, '2030-01-01'):+.2f}")
        L.append(f"| {nm} | " + " | ".join(cells) + " |")
        print(L[-1], flush=True)
    # ---------- 専門家の重みの移り変わり
    cols_w = exps + ["p_rule"]
    L += ["", "## 6 専門家の重み（HEDGE。年の平均。指数）", "", "| 年 | " + " | ".join(EXPERT_LABEL[c].split(" ")[0] for c in exps) + " | 既存のルール |", "|---|" + "---|" * len(cols_w)]
    wi = W[W["klass"] == "index"].drop(columns="klass")
    for y_, r_ in wi.groupby(wi.index.year).mean().iterrows():
        L.append(f"| {y_} | " + " | ".join(f"{r_[c] * 100:.0f}%" for c in cols_w) + " |")
    imp_f = os.path.join(DS.CACHE, f"gbm_importance_{ver}.csv")
    if os.path.exists(imp_f):
        imp = pd.read_csv(imp_f, index_col=0).iloc[:, 0]
        L += ["", "## 7 勾配ブースティングがよく使った特徴量（上位20" + ("。指数のモデル" if ver != "v1" else "") + "）", "", "、".join(f"{k}（{v:.0f}）" for k, v in imp.head(20).items())]
    # ---------- 判定
    def ab(nm, col):
        v = verdict[(nm, col)]
        return ((v["m1"] >= v["b1"] + 0.05 and v["m2"] >= v["b2"] + 0.05) or (v["e1"] >= v["b1"] and v["e2"] >= v["b2"]))
    L += ["", "## 8 判定（事前に決めた基準）", "", "| エンジン | (A) CFD の米国3指数 | (B) 現物の米国3指数 | (C) 確率の順が合っている | (D) 2つ以上のモデルが指数で t ≥ 2 | 判定 |", "|---|---|---|---|---|---|"]
    n_d = sum(tstat.get((c, "cash"), 0.0) >= 2.0 for c in ("p_lr", "p_gbm", "p_cnn"))
    for lab, col in engines:
        A, B = ab("指数（OANDA の CFD：US500・US100・US30）", col), ab("指数（現物の米国3指数）", col)
        C, D = rho_cal >= 0.8, n_d >= 2
        L.append(f"| {lab} | {'○' if A else '×'} | {'○' if B else '×'} | {'○' if C else '×'}（{rho_cal:+.2f}） | {'○' if D else '×'}（{n_d} / 3） | {'**昇格**' if (A and B and C and D) else '影で動かす（資金は既存の層のまま）'} |")
        print(L[-1], flush=True)
    fxm = {}
    for nm in ("為替17", "金属3"):
        k = keep[nm]
        cells = []
        for lab, col in engines:
            e = port(P, R[col], **k["kw"])
            s1, s2 = sh(e, k["a"], k["mid"]), sh(e, k["mid"], "2030-01-01")
            cells.append(f"{short((lab, col))} {s1:+.2f}／{s2:+.2f}{'（○）' if (s1 >= 0.4 and s2 >= 0.4) else ''}")
        fxm[nm] = "、".join(cells)
    L += ["", "- 為替・金属（エンジンだけ・買いと売り。前半／後半のシャープ。両方 0.4 以上で「売買できる」）：" + "。".join(f"{k}：{v}" for k, v in fxm.items())]
    os.makedirs(os.path.join(DS.F.ROOT, "reports", "eco"), exist_ok=True)
    open(os.path.join(DS.F.ROOT, "reports", "eco", f"{ver}.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    P.to_parquet(os.path.join(DS.CACHE, f"preds_{ver}_ens.parquet"))


if __name__ == "__main__":
    main()

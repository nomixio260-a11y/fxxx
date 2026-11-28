#!/usr/bin/env python3
"""複合システム：建玉の決め方の改良「期待値がコストを上回る分だけ持つ」の検証。日付・時刻・曜日は使わない。

- きっかけ（v2 の診断。reports/eco/v2.md の5）：エンジンは、いまの層が何も持っていない日に、少しずつ負けている（シャープの内訳で −0.06〜−0.10）。
  「確率がふだんより少し高い」だけの日にも小さく持つので、優位性がないのに持ち越しのコスト（指数の買いは年 −4.79%）を払っているからである。
  いまの層は、合図がはっきり出た日だけ持つ。エンジンにも「コストを上回る見込みがあるときだけ持つ」形が要る。
- 形（結果を見る前に決めた。これ以外は試さない。しきい値などの数字を、成績を見て選ぶことはしない）：
   1. 確率を、期待値に直す：その種類の、前の年までの「予想の確率と、実際の次の日の値動き」から、単調に増える関係 ŷ(p) を当てはめる
      （単調回帰。3年分以上の予想がたまってから。値動きは、値動きの大きさ＝1 の単位）。
   2. コストを引く：買いの1日の持ち越しコスト c（年 4.79% ÷ 360 × 1.45 を、その銘柄の値動きの大きさで割る。為替 1.5%、金属 3.6%）。
      見込み ＝ ŷ(p) − c。売りは、見込み ＝ −ŷ(p) − 売りのコスト。
   3. 建玉 ＝ 目標の値動き × clip(見込み ÷ s, 0, 2) ÷ 値動きの大きさ。s は、前の年までの ŷ のばらつき（v2 の z と同じ物差し）。
      見込みがマイナスなら持たない。
- 測るもの：v2 の3つのエンジン（AVG・META・HEDGE）。買いだけ、と、買いと売り。銘柄の集まり・前半と後半の境目・コストは evaluate.py と同じ。
- 判定：evaluate.py の (A)(B) と同じ（OANDA の CFD の米国3指数・現物の米国3指数の両方で、前半・後半とも、
  「いまの層と半分ずつ」が いまの層 ＋0.05 以上、または、エンジンだけで いまの層以上）。満たせば、EA に渡す z をこの形に替える。
使い方: python3 tools/eco/sizing.py [v2]  → reports/eco/sizing.md
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402
import evaluate as EV  # noqa: E402

ANN = 252


def ev_units(P, col):
    """戻り値：買いの単位（0〜2）と、売りの単位（0〜2）。どちらも、その日より前の年の予想だけで決まる。"""
    from sklearn.isotonic import IsotonicRegression
    yr = P["date"].dt.year.values
    ul, us = np.full(len(P), np.nan), np.full(len(P), np.nan)
    for kl in ("index", "fx", "metal"):
        mk = (P["klass"] == kl).values & P[col].notna().values
        cl = -EV.SWAP_L[kl] / 100.0 / 360.0 * 1.45
        cs = -EV.SWAP_S[kl] / 100.0 / 360.0 * 1.45
        for Y in sorted(set(yr[mk])):
            tr, te = mk & (yr < Y), mk & (yr == Y)
            if tr.sum() < EV.MIN_ROWS or len(set(yr[tr])) < 3:
                continue
            iso = IsotonicRegression(increasing=True, out_of_bounds="clip").fit(P.loc[tr, col].values, P.loc[tr, "y"].values)
            s = float(np.std(iso.predict(P.loc[tr, col].values)))
            if s <= 0:
                continue
            yh = iso.predict(P.loc[te, col].values)
            sg = P.loc[te, "sig"].values
            ul[te] = np.clip((yh - cl / sg) / s, 0, 2)
            us[te] = np.clip((-yh - cs / sg) / s, 0, 2)
    return ul, us


def main():
    ver = sys.argv[1] if len(sys.argv) > 1 else "v2"
    P = pd.read_parquet(os.path.join(DS.CACHE, f"preds_{ver}_ens.parquet"))
    P["date"] = pd.to_datetime(P["date"])
    P = P.sort_values(["date", "inst"]).reset_index(drop=True)
    engines = [("AVG", "p_avg"), ("META", "p_meta"), ("HEDGE", "p_hedge")]
    scale = 0.10 / (P["sig"].values * np.sqrt(ANN))
    w_rule = P["st_n"].round().astype(int).map(EV.W_RULE).values * scale
    r_rule = EV.pnl(P, np.where(P["klass"] == "index", w_rule, 0.0)).values
    sets = (("現物の米国3指数", dict(insts=EV.US_CASH), "2008-01-01", "2017-01-01"), ("OANDA の CFD の米国3指数", dict(insts=EV.US_CFD), "2018-01-01", "2022-01-01"),
            ("OANDA の CFD 14", dict(insts=[i for i in P["inst"].unique() if i.startswith("CFD_")]), "2018-01-01", "2022-01-01"),
            ("現物の指数11", dict(klass="index"), "2008-01-01", "2017-01-01"), ("為替17", dict(klass="fx"), "2015-01-01", "2020-01-01"), ("金属3", dict(klass="metal"), "2011-01-01", "2018-01-01"))
    end = "2030-01-01"
    L = [f"# 複合システム：建玉の決め方「期待値がコストを上回る分だけ持つ」（`tools/eco/sizing.py {ver}`）", "",
         "コスト後のシャープ（全期間／前半／後半）。「z に比例」は v2 のままの形（確率がふだんより高い分に比例）。「期待値」は、この検証の形。", "",
         "| 銘柄の集まり | エンジン | いまの戻りの層 | z に比例（買いだけ） | 期待値（買いだけ） | 期待値（買いと売り） | 持っている日の割合：z に比例 → 期待値 | いまの層と半分ずつ（期待値・買いだけ） | 損益の相関 |", "|---|---|---|---|---|---|---|---|---|"]
    verdict = {}
    for lab, col in engines:
        ul, us = ev_units(P, col)
        z = EV.zscore(P, col)
        r_z = EV.pnl(P, np.clip(z, 0, None) * scale).values
        r_l = EV.pnl(P, ul * scale).values
        r_ls = EV.pnl(P, (ul - us) * scale).values
        for nm, kw, a, mid in sets:
            f3 = lambda x: f"{EV.sh(x, a, end):+.2f}／{EV.sh(x, a, mid):+.2f}／{EV.sh(x, mid, end):+.2f}"   # noqa: E731
            base, e_z, e_l, e_ls = (EV.port(P, r, **kw) for r in (r_rule, r_z, r_l, r_ls))
            m = (P["inst"].isin(kw["insts"]) if "insts" in kw else ((P["klass"] == kw["klass"]) & ~P["inst"].str.startswith("CFD_"))).values & (P["date"] >= a).values & ~np.isnan(ul)
            share = f"{(z[m] > 0).mean() * 100:.0f}% → {(ul[m] > 0).mean() * 100:.0f}%"
            is_idx = "指数" in nm or "CFD" in nm
            if is_idx:
                q = pd.concat([base, e_l], axis=1).dropna()
                q = q[q.index >= a]
                mix = q.iloc[:, 0] / q.iloc[:, 0].std() + q.iloc[:, 1] / q.iloc[:, 1].std()
                verdict[(nm, col)] = dict(b1=EV.sh(q.iloc[:, 0], a, mid), b2=EV.sh(q.iloc[:, 0], mid, end), e1=EV.sh(q.iloc[:, 1], a, mid), e2=EV.sh(q.iloc[:, 1], mid, end),
                                          m1=EV.sh(mix, a, mid), m2=EV.sh(mix, mid, end))
                L.append(f"| {nm} | {lab} | {f3(q.iloc[:, 0])} | {f3(e_z[e_z.index >= q.index[0]])} | {f3(q.iloc[:, 1])} | {f3(e_ls[e_ls.index >= q.index[0]])} | {share} | {f3(mix)} | {q.corr().iloc[0, 1]:+.2f} |")
            else:
                L.append(f"| {nm} | {lab} | — | {f3(e_z)} | {f3(e_l)} | {f3(e_ls)} | {share} | — | — |")
            print(L[-1], flush=True)
    def ab(nm, col):
        v = verdict[(nm, col)]
        return ((v["m1"] >= v["b1"] + 0.05 and v["m2"] >= v["b2"] + 0.05) or (v["e1"] >= v["b1"] and v["e2"] >= v["b2"]))
    L += ["", "## 判定（事前に決めた基準）", "", "| エンジン | (A) CFD の米国3指数 | (B) 現物の米国3指数 | 判定 |", "|---|---|---|---|"]
    for lab, col in engines:
        A, B = ab("OANDA の CFD の米国3指数", col), ab("現物の米国3指数", col)
        L.append(f"| {lab} | {'○' if A else '×'} | {'○' if B else '×'} | {'**採用**' if (A and B) else '採用しない'} |")
        print(L[-1], flush=True)
    open(os.path.join(DS.F.ROOT, "reports", "eco", "sizing.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""複合システム：金属（とくに金）だけに絞った予想エンジンの検証。日付・時刻・曜日は使わない。

- きっかけ：v2 の銘柄ごとの内訳で、金だけは、エンジン（買いだけ）のシャープが、いまの金の層のルール（200日の平均より上なら買い）を上回っていた
  （2015〜26年。0.63 対 0.38）。ただし、17 銘柄 × 8 通りを見た中で目立った1つなので、偶然かもしれない。期間も 2015年からしかない。
  そこで、データを増やして学習し直し、長い期間で、基準を先に決めて確かめる。
- データ：金属の先物の日足（Yahoo Finance。金・銀・銅・プラチナ・パラジウム、2000年〜）＋ OANDA の日足（XAUUSD・XAGUSD・COPPER、2006〜07年〜。名前の頭に CM_）。
  先物の日足は、限月の切り替えの日に段差がある（年に金利分ほど、買いに有利に出る）。コストに、買いの持ち越し 年 −3.6% を入れて相殺している。
- モデル：v2 と同じ5つ（LR・GBM・CNN・REG・KNN）を、金属だけで学習（毎年、前の年までのデータで学習して、その年を予想。新しいデータを重く）。
  エンジンは AVG（5つの確率の平均）。v2 の結果を見る前から「既定は平均」と決めていた形で、ほかの合成は試さない。
- 売買：買いだけ。建玉 ＝ 目標の値動き × clip(z, 0, 2) ÷ 値動きの大きさ。z は、前の年までの金属の予想から（evaluate.py の zscore）。
  コスト：スプレッド 片道 0.02%、買いの持ち越し 年 −3.6%。
- 比べる相手：いまの金の層のルール（終値が200日の平均より上なら買い）。同じ値動きの物差し・同じコスト。
- 判定（結果を見る前に決めた）。金のエンジンを「採用の候補」にする（MT5 の実際のティックでの検証に進む）のは、次の両方を満たすときだけ：
   (G1) 金の先物（2007年〜。前半 〜2016年・後半 2017年〜）で、エンジンだけのシャープが前半・後半ともルール以上、
        または「ルールと半分ずつ」が前半・後半ともルール ＋0.05 以上
   (G2) OANDA の XAUUSD（2010年〜。前半 〜2017年・後半 2018年〜）で、同じことが成り立つ
  参考（判定には使わない）：ほかの金属（銀・銅・プラチナ・パラジウム）でも、エンジンがルールを上回るか。上回らないなら、金の結果は偶然の疑いが強い。
使い方: python3 tools/eco/metals.py  → reports/eco/metals.md、data/eco/preds_metals.parquet
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402
import evaluate as EV  # noqa: E402
import ml2 as M2  # noqa: E402

FUT = (("GC", "金"), ("SI", "銀"), ("HG", "銅"), ("PL", "プラチナ"), ("PA", "パラジウム"))
YEARS = list(range(2005, 2027))
OUT = os.path.join(DS.CACHE, "preds_metals.parquet")
ANN = 252


def build(refresh=False):
    pq, npy = os.path.join(DS.CACHE, "rows_metals.parquet"), os.path.join(DS.CACHE, "win_metals.npy")
    if not refresh and os.path.exists(pq) and os.path.exists(npy):
        return pd.read_parquet(pq), np.load(npy, mmap_mode="r")
    vix = DS.vix_features()
    parts, wins = [], []
    for nm, _ in FUT:
        d = DS.Y.fetch(nm) if nm in DS.Y.TICKERS else DS.Y.fetch_ticker(nm, nm + "=F")
        f, w = DS.one("FUT_" + nm, d, "metal", vix)
        parts.append(f), wins.append(w)
        print("FUT_" + nm, len(f), str(f["date"].min())[:10], flush=True)
    cm = os.environ.get("AMS_CM_EXPORT")
    if cm and os.path.isdir(cm):
        cmd = DS.IO.load(cm)[0]
        for sym in ("XAUUSD", "XAGUSD", "COPPER"):
            if sym in cmd:
                f, w = DS.one("CM_" + sym, cmd[sym], "metal", vix)
                parts.append(f), wins.append(w)
                print("CM_" + sym, len(f), str(f["date"].min())[:10], flush=True)
    rows = pd.concat(parts, ignore_index=True)
    win = np.concatenate(wins, axis=0)
    keep = (rows["sig"].notna() & rows["ret250"].notna() & rows["up"].notna()).values & ~np.isnan(win[:, 0, 0])
    rows, win = rows[keep].reset_index(drop=True), win[keep]
    rows.to_parquet(pq)
    np.save(npy, win)
    return rows, win


def train():
    rows, win = build()
    win = np.asarray(win)
    cols = DS.feature_cols()
    X = rows[cols].values.astype(np.float32)
    up, yv = rows["up"].values.astype(np.float32), rows["y"].values.astype(np.float32)
    dates = rows["date"].values
    year = pd.DatetimeIndex(rows["date"]).year.values
    names = ("p_lr", "p_gbm", "p_cnn", "p_reg", "p_knn")
    P = {k: np.full(len(rows), np.nan) for k in names}
    for Y in YEARS:
        a, b = np.datetime64(f"{Y}-01-01"), np.datetime64(f"{Y + 1}-01-01")
        tr = dates < a
        tr[rows.loc[tr].groupby("inst").tail(2).index.values] = False
        te = (dates >= a) & (dates < b)
        if tr.sum() < M2.MIN_TRAIN or te.sum() == 0:
            continue
        w = 0.5 ** ((Y - year[tr]) / M2.HALF_LIFE)
        P["p_lr"][te], _ = M2.fit_lr(X[tr], up[tr], w, X[te])
        P["p_gbm"][te], _ = M2.fit_gbm(X[tr], up[tr], w, X[te])
        P["p_reg"][te], _ = M2.fit_reg(X[tr], yv[tr], w, X[te])
        P["p_knn"][te] = M2.fit_knn(win[tr], up[tr], win[te])
        if (Y - YEARS[0]) % 2 == 0:
            te2 = (dates >= a) & (dates < np.datetime64(f"{Y + 2}-01-01"))
            P["p_cnn"][te2], _ = M2.fit_cnn(win[tr], up[tr], w, win[te2])
        print(f"{Y}: 学習 {int(tr.sum())} 行、予想 {int(te.sum())} 行", flush=True)
    out = rows[["date", "inst", "klass", "up", "y", "r_next", "sig", "above200", "ret1"]].copy()
    for k in names:
        out[k] = P[k]
    out = out[out["p_lr"].notna()].reset_index(drop=True)
    out["p_avg"] = EV.sig(np.nanmean(np.column_stack([EV.logit(out[k].values) for k in names]), axis=1))
    out.to_parquet(OUT)
    return out


def stats(x):
    e = (1 + x).cumprod()
    yrs = (x.index[-1] - x.index[0]).days / 365.25
    return dict(sh=x.mean() / x.std() * np.sqrt(ANN), cagr=e.iloc[-1] ** (1 / yrs) - 1, dd=(e / e.cummax() - 1).min())


def same_dd(x, dd0):
    lo, hi = 0.02, 50.0
    for _ in range(60):
        k = (lo + hi) / 2
        if stats(x * k)["dd"] < dd0:
            hi = k
        else:
            lo = k
    return stats(x * lo)["cagr"]


def main():
    P = train() if (len(sys.argv) > 1 and sys.argv[1] == "train") or not os.path.exists(OUT) else pd.read_parquet(OUT)
    P["date"] = pd.to_datetime(P["date"])
    P = P.sort_values(["date", "inst"]).reset_index(drop=True)
    scale = 0.10 / (P["sig"].values * np.sqrt(ANN))
    z = EV.zscore(P, "p_avg")
    P["z"] = z
    P["r_eng"] = EV.pnl(P, np.clip(z, 0, None) * scale).values
    P["r_rule"] = EV.pnl(P, np.where(P["above200"] > 0, 1.0, 0.0) * scale).values
    P.loc[np.isnan(z), ["r_eng", "r_rule"]] = np.nan
    L = ["# 複合システム：金属だけに絞った予想エンジン（`tools/eco/metals.py`）", "",
         f"学習に使っていない年の予想だけで測る（売買の合図がある期間：{P.loc[P['z'].notna(), 'date'].min().date()}〜{P['date'].max().date()}）。買いだけ。コスト後。", "",
         "## 1 予想は当たっているか（予想の確率と、次の日の値動きの相関・t 値。金属の全銘柄）", "", "| モデル | 相関・t |", "|---|---|"]
    for k, lab in (("p_lr", "LR"), ("p_gbm", "GBM"), ("p_cnn", "CNN"), ("p_reg", "REG"), ("p_knn", "KNN"), ("p_avg", "AVG（エンジン）")):
        g = P[P[k].notna()]
        dd = ((g[k] - g[k].mean()) * g["y"]).groupby(g["date"]).mean()
        L.append(f"| {lab} | {np.corrcoef(g[k], g['y'])[0, 1]:+.3f}・{dd.mean() / dd.std() * np.sqrt(len(dd)):+.1f} |")
    L += ["", "## 2 銘柄ごと：エンジンと、いまのルール（200日の平均より上で買い）", "",
          "| 銘柄 | 期間 | ルール：シャープ（全期間／前半／後半） | エンジン | 半分ずつ | 損益の相関 | 持っている日の割合：ルール → エンジン | 最大の下落をルールにそろえた年率：ルール → エンジン → 半分ずつ |", "|---|---|---|---|---|---|---|---|"]
    names = dict(FUT)
    res = {}
    for inst in sorted(P["inst"].unique(), key=lambda s: (s[:3] != "FUT", s)):
        g = P[(P["inst"] == inst) & P["z"].notna()].set_index("date")
        a = "2007-01-01" if inst.startswith("FUT_") else "2010-01-01"
        mid = "2017-01-01" if inst.startswith("FUT_") else "2018-01-01"
        g = g[g.index >= a]
        if len(g) < 1000:
            continue
        b, e = g["r_rule"], g["r_eng"]
        mix = (b / b.std() + e / e.std()) / 2.0
        f3 = lambda x: f"{EV.sh(x, a, '2030-01-01'):+.2f}／{EV.sh(x, a, mid):+.2f}／{EV.sh(x, mid, '2030-01-01'):+.2f}"   # noqa: E731
        dd0 = stats(b)["dd"]
        res[inst] = dict(b1=EV.sh(b, a, mid), b2=EV.sh(b, mid, "2030-01-01"), e1=EV.sh(e, a, mid), e2=EV.sh(e, mid, "2030-01-01"), m1=EV.sh(mix, a, mid), m2=EV.sh(mix, mid, "2030-01-01"),
                         b=EV.sh(b, a, "2030-01-01"), e=EV.sh(e, a, "2030-01-01"))
        lab = (names.get(inst[4:], inst[4:]) + "の先物") if inst.startswith("FUT_") else ("OANDA " + inst[3:])
        L.append(f"| {lab} | {str(g.index[0])[:7]}〜（境目 {mid[:4]}年） | {f3(b)} | {f3(e)} | {f3(mix)} | {np.corrcoef(b, e)[0, 1]:+.2f} | {(g['above200'] > 0).mean() * 100:.0f}% → {(g['z'] > 0).mean() * 100:.0f}% | "
                 f"{stats(b)['cagr'] * 100:+.1f}% → {same_dd(e, dd0) * 100:+.1f}% → {same_dd(mix, dd0) * 100:+.1f}% |")
        print(L[-1], flush=True)
    # ---------- 金：年ごと
    L += ["", "## 3 金（OANDA の XAUUSD）：年ごとの損益（値動きをそろえた大きさ。ルールの全期間の値動き＝年10%）", "", "| 年 | ルール | エンジン | 半分ずつ |", "|---|---|---|---|"]
    gi = "CM_XAUUSD" if "CM_XAUUSD" in res else "FUT_GC"
    g = P[(P["inst"] == gi) & P["z"].notna()].set_index("date")
    g = g[g.index >= ("2010-01-01" if gi.startswith("CM_") else "2007-01-01")]
    b, e = g["r_rule"], g["r_eng"]
    k_b, k_e = 0.10 / (b.std() * np.sqrt(ANN)), 0.10 / (e.std() * np.sqrt(ANN))
    mix = (b * k_b + e * k_e) / 2.0
    k_m = 0.10 / (mix.std() * np.sqrt(ANN))
    for y_ in sorted(set(g.index.year)):
        f = lambda x, k: (np.prod(1 + x[x.index.year == y_] * k) - 1) * 100   # noqa: E731
        L.append(f"| {y_} | {f(b, k_b):+.1f}% | {f(e, k_e):+.1f}% | {f(mix, k_m):+.1f}% |")
    # ---------- 判定
    def ok(i):
        v = res[i]
        return (v["e1"] >= v["b1"] and v["e2"] >= v["b2"]) or (v["m1"] >= v["b1"] + 0.05 and v["m2"] >= v["b2"] + 0.05)
    g1, g2 = ok("FUT_GC"), ok("CM_XAUUSD") if "CM_XAUUSD" in res else False
    others = [i for i in res if i not in ("FUT_GC", "CM_XAUUSD")]
    n_better = sum(res[i]["e"] > res[i]["b"] for i in others)
    L += ["", "## 4 判定（事前に決めた基準）", "",
          f"- (G1) 金の先物：{'○' if g1 else '×'}（ルール 前半 {res['FUT_GC']['b1']:+.2f}・後半 {res['FUT_GC']['b2']:+.2f}、エンジン {res['FUT_GC']['e1']:+.2f}・{res['FUT_GC']['e2']:+.2f}、半分ずつ {res['FUT_GC']['m1']:+.2f}・{res['FUT_GC']['m2']:+.2f}）"]
    if "CM_XAUUSD" in res:
        v = res["CM_XAUUSD"]
        L.append(f"- (G2) OANDA の XAUUSD：{'○' if g2 else '×'}（ルール 前半 {v['b1']:+.2f}・後半 {v['b2']:+.2f}、エンジン {v['e1']:+.2f}・{v['e2']:+.2f}、半分ずつ {v['m1']:+.2f}・{v['m2']:+.2f}）")
    L += [f"- 参考：ほかの金属 {len(others)} 銘柄のうち、全期間でエンジンがルールを上回ったもの：{n_better}",
          f"- **判定：{'採用の候補（MT5 の実際のティックでの検証に進む）' if (g1 and g2) else '採用しない'}**"]
    print("\n".join(L[-4:]))
    open(os.path.join(DS.F.ROOT, "reports", "eco", "metals.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    P.to_parquet(OUT)


if __name__ == "__main__":
    main()

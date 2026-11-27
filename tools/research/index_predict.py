#!/usr/bin/env python3
"""研究：株価指数の翌日の値動きを予想するモデル（過去だけで学習し、次の年を予想する）。公表済みのルールだけの形と比べる。

- 対象：米国の3指数（S&P500・NASDAQ100・ダウ）。現物の指数の日足（Yahoo Finance、1990年〜）。
- 予想するもの：翌日の値動き（終値 → 次の日の終値）を、その日の「値動きの大きさの見積もり」（HAR 型）で割った値。
- 説明に使う値：
  P（値段だけ。MT5 の日足だけで計算できる）：
    過去 1・2・3・5・10・20日の値動き（値動きの大きさで割った値）、RSI(2)・RSI(5)、IBS、5・10・20・50・200日の平均からの離れ、
    20日の高値からの下げ、続けて下げた日数・上げた日数、当日の値幅・始値の飛び、値動きの大きさの変化（速い見積もり ÷ 60日、20日 ÷ 250日）、
    公表済みのルールの状態（R2・D7・IBS とその数）、200日の平均より上か
  X（外の情報。**1日前の値**を使う：VIX の終値は 16:15 で、株の終値 16:00 より後のため）：
    VIX の水準（過去1年に対して）・1日と5日の変化・VIX ÷ 3か月の VIX、オプションに織り込まれた値動き − 実際の値動き、
    2年・10年の金利の1日と5日の変化、長短の金利差、SKEW、業種別 ETF のうち50日の平均より上の割合・RSI(2) が10未満の割合
- モデル：リッジ回帰（線形）と、勾配ブースティング（小さな木に固定：深さ3・葉8・300本・学習率0.03）。3指数をまとめて1つのモデル。
  学習は 1993年〜、**毎年、前の年までのデータで学習して、その年を予想**（最初の予想は 2003年）。数値は選び直さない。
- 取引：予想がプラスのときだけ買い（予想の大きさに比例、上限あり）。建玉 = 予想 × 目標 ÷ 値動きの見積もり。コストは index_reversion.py と同じ。
- 比べる相手：公表済みのルールの数に比例して持つ形（同じ値動きの見積もり、同じ期間）。
使い方: python3 tools/research/index_predict.py  → reports/research/index_predict.md
"""
import os
import sys

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_risk as IRK  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
FIRST_OOS = 2003
PER = (("2003〜08", "2003-01-01", "2009-01-01"), ("2009〜14", "2009-01-01", "2015-01-01"), ("2015〜21/10", "2015-01-01", "2021-11-01"),
       ("21/11〜26/11", "2021-11-01", "2026-12-01"))
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU"]


def price_features(name):
    d, st, rate, div, vols, above = IRK.load(name)
    c, o, h, l = d["close"], d["open"], d["high"], d["low"]
    lc = np.log(c)
    sd = (vols["v60"] / np.sqrt(ANN)).clip(lower=0.002)          # 1日の値動きの大きさ（直近60日）
    f = pd.DataFrame(index=d.index)
    for k in (1, 2, 3, 5, 10, 20):
        f[f"r{k}"] = (lc - lc.shift(k)) / (sd * np.sqrt(k))
    f["rsi2"] = IR.rsi_wilder(c, 2) / 100.0 - 0.5
    f["rsi5"] = IR.rsi_wilder(c, 5) / 100.0 - 0.5
    rng = (h - l)
    f["ibs"] = ((c - l) / rng.where(rng > 0)).fillna(0.5) - 0.5
    for k in (5, 10, 20, 50, 200):
        f[f"ma{k}"] = np.log(c / c.rolling(k).mean()) / (sd * np.sqrt(k / 2.0))
    f["dd20"] = np.log(c / c.rolling(20).max()) / (sd * np.sqrt(10.0))
    down = (c < c.shift(1)).astype(int)
    f["dstreak"] = down.groupby((down == 0).cumsum()).cumsum().clip(upper=6)
    up = (c > c.shift(1)).astype(int)
    f["ustreak"] = up.groupby((up == 0).cumsum()).cumsum().clip(upper=6)
    f["range"] = (np.log(h / l).where(rng > 0) / sd).fillna(1.0).clip(upper=8)
    f["gap"] = (np.log(o / c.shift(1)) / sd).fillna(0.0).clip(-6, 6)
    f["volr_fast"] = (vols["har"] / vols["v60"]).clip(0.2, 5)
    f["volr_slow"] = (vols["v20"] / vols["v250"]).clip(0.2, 5)
    f["R2"], f["D7"], f["IBSr"] = st["R2"], st["D7"], st["IBS"]
    f["n"] = st.sum(axis=1)
    f["above"] = above.astype(float)
    fore = (vols["har"] / np.sqrt(ANN)).clip(lower=0.002)        # 翌日の値動きの大きさの見積もり（1日）
    y = (lc.shift(-1) - lc)                                       # 翌日の値動き
    return d, f, y, fore, rate, div, st


def external_features(index):
    """外の情報（1日前の値にして使う）。"""
    g = pd.DataFrame(index=index)

    def al(s):
        return s.reindex(s.index.union(index)).ffill(limit=3).reindex(index)
    vix = np.log(Y.fetch("VIX")["close"])
    g["vix_z"] = al((vix - vix.rolling(250).mean()) / vix.rolling(250).std())
    g["dvix1"] = al(vix.diff())
    g["dvix5"] = al(vix.diff(5))
    try:
        v3 = np.log(Y.fetch("VIX3M")["close"])
        g["vix_ts"] = al((vix - v3.reindex(vix.index)))
    except Exception:  # noqa: BLE001
        g["vix_ts"] = np.nan
    spx = Y.fetch("SPX")["close"]
    rv = np.log(spx).diff().rolling(22).std() * np.sqrt(ANN) * 100
    g["vrp"] = al((np.exp(vix) ** 2 - rv.reindex(vix.index) ** 2) / 100.0)
    for sid, k in (("DGS2", "y2"), ("DGS10", "y10")):
        y = F.fetch(sid).dropna()
        g[f"d{k}_1"] = al(y.diff())
        g[f"d{k}_5"] = al(y.diff(5))
    g["curve"] = al(F.fetch("T10Y2Y").dropna())
    try:
        sk = Y.fetch("SKEW")["close"]
        g["skew"] = al((sk - sk.rolling(250).mean()) / sk.rolling(250).std())
    except Exception:  # noqa: BLE001
        g["skew"] = np.nan
    br50, brrsi = [], []
    for s in SECTORS:
        try:
            p = Y.fetch(s)["close"]
            br50.append((p > p.rolling(50).mean()).astype(float))
            brrsi.append((IR.rsi_wilder(p, 2) < 10).astype(float))
        except Exception:  # noqa: BLE001
            pass
    if br50:
        g["breadth50"] = al(pd.concat(br50, axis=1).mean(axis=1))
        g["breadth_os"] = al(pd.concat(brrsi, axis=1).mean(axis=1))
    return g.shift(1)                                              # 1日前の値


def build():
    rows, meta = [], {}
    for i, name in enumerate(IRK.US3):
        d, f, y, fore, rate, div, st = price_features(name)
        x = external_features(d.index)
        df = pd.concat([f, x.add_prefix("x_")], axis=1)
        df["idx"] = i
        df["y"] = y / fore
        df["name"] = name
        rows.append(df[df.index >= "1993-01-01"])
        meta[name] = (d, y, fore, rate, div, st)
    return pd.concat(rows), meta


def walk_forward(panel, feats, model):
    pred = pd.Series(np.nan, index=np.arange(len(panel)))
    yrs = panel.index.year.values
    P = panel.reset_index(drop=True)
    imp = None
    for yr in range(FIRST_OOS, 2027):
        tr = (yrs < yr) & P["y"].notna().values
        te = (yrs == yr)
        if tr.sum() < 3000 or te.sum() == 0:
            continue
        Xtr, ytr = P.loc[tr, feats], P.loc[tr, "y"].clip(-6, 6)
        if model == "ridge":
            Xn = Xtr.fillna(0.0).values
            mu, sd = Xn.mean(axis=0), Xn.std(axis=0)
            sd[sd == 0] = 1.0
            Z = (Xn - mu) / sd
            b = np.linalg.solve(Z.T @ Z + 300.0 * np.eye(Z.shape[1]), Z.T @ (ytr.values - ytr.mean()))
            pred[te] = ((P.loc[te, feats].fillna(0.0).values - mu) / sd) @ b + ytr.mean()
        else:
            m = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, max_depth=3, num_leaves=8, subsample=0.7, subsample_freq=1,
                                  colsample_bytree=0.7, min_child_samples=200, reg_lambda=10.0, random_state=1, verbose=-1)
            m.fit(Xtr, ytr)
            pred[te] = m.predict(P.loc[te, feats])
            g = m.booster_.feature_importance(importance_type="gain")
            imp = g if imp is None else imp + g
    out = pd.Series(pred.values, index=panel.index)
    return out, (pd.Series(imp, index=feats).sort_values(ascending=False) if imp is not None else None)


def strategy(panel, meta, signal, cap=3.0, long_only=True):
    """signal（予想。値動きの大きさで割った単位）に比例して持つ。3指数の合計の日次の損益。"""
    outs = []
    for name in IRK.US3:
        d, y, fore, rate, div, st = meta[name]
        s = signal[panel["name"] == name].reindex(d.index)
        w = s.clip(lower=0.0 if long_only else -cap, upper=cap).fillna(0.0)
        w = w * (0.10 / (fore * np.sqrt(ANN))).clip(upper=4.0) / len(IRK.US3)
        held = w.shift(1).fillna(0.0)
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
        fin_l = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
        fin_s = (rate - IR.MARKUP - div) / 100.0 / 360.0 * days
        fin = np.where(held >= 0, held * fin_l, -held * fin_s)
        outs.append(held * d["close"].pct_change().fillna(0.0) + fin - (w - held).abs() * IR.COST)
    r = pd.concat(outs, axis=1).fillna(0.0).sum(axis=1)
    return r[r.index >= f"{FIRST_OOS}-01-01"]


def stats(label, r):
    z = r * (0.10 / (r.std() * np.sqrt(ANN)))
    sh = z.mean() / z.std() * np.sqrt(ANN)
    eq = (1 + z).cumprod()
    yr = z.groupby(z.index.year).sum()
    q = z.quantile(0.01)
    per = [z[(z.index >= a) & (z.index < b)] for _, a, b in PER]
    return (f"| {label} | {sh:+.2f} | {sh * np.sqrt(len(z) / ANN):+.1f} | {z.min() * 100:.1f}% | {z[z <= q].mean() * 100:.2f}% | {(eq / eq.cummax() - 1).min() * 100:.0f}% | "
            f"{yr.min() * 100:.1f}% | {(yr > 0).sum()}/{len(yr)} | " + " | ".join(f"{x.mean() / x.std() * np.sqrt(ANN):+.2f}" for x in per) + f" | {(r != 0).mean() * 100:.0f}% |"), z


def main():
    panel, meta = build()
    P = [c for c in panel.columns if not c.startswith("x_") and c not in ("y", "name")]
    X = [c for c in panel.columns if c.startswith("x_")]
    lines = ["# 研究：株価指数の翌日の値動きを予想するモデル（`tools/research/index_predict.py`）", "",
             f"米国3指数、学習は 1993年〜、予想は {FIRST_OOS}年〜2026年11月（毎年、前の年までのデータで学習）。CFD のコスト込み。すべて、全期間の値動きを年10%にそろえて比べる。", "",
             "## 予想と実際の関係（見ていない期間）", "", "| モデル | 予想と実際の相関（すべての日） | ルールが1つ以上出ている日だけ | 2つ以上の日だけ |", "|---|---|---|---|"]
    preds = {}
    for label, feats, model in (("線形（値段だけ）", P, "ridge"), ("勾配ブースティング（値段だけ）", P, "gbm"),
                                ("線形（値段 ＋ 外の情報）", P + X, "ridge"), ("勾配ブースティング（値段 ＋ 外の情報）", P + X, "gbm")):
        p, imp = walk_forward(panel, feats, model)
        preds[label] = p
        ok = p.notna() & panel["y"].notna()
        cells = []
        for m in (ok, ok & (panel["n"] >= 1), ok & (panel["n"] >= 2)):
            cells.append(f"{np.corrcoef(p[m], panel['y'][m].clip(-6, 6))[0, 1]:+.4f}（{int(m.sum())} 件）")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
        print(lines[-1], flush=True)
        if imp is not None:
            print("   効いている順:", (imp / imp.sum() * 100).round(1).head(10).to_dict(), flush=True)
            lines.append(f"|   └ 効いている値（上位）| " + "、".join(f"{k} {v:.0f}%" for k, v in (imp / imp.sum() * 100).head(8).items()) + " | | |")
    head = ("| 形 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | プラスの年 | " + " | ".join(p[0] for p in PER) + " | 持つ日 |")
    lines += ["", "## 取引の成績（予想に比例して買い。同じ期間・同じコスト）", "", head, "|---|" + "---|" * (8 + len(PER) + 1)]
    keep = {}
    base = panel["n"] / 3.0
    for label, sig in [("比べる相手：ルールの数に比例（1:2:3）", base * 3.0 / 3.0), ("比べる相手：ルールが2つ以上のときだけ（0:1:2）", (panel["n"] - 1).clip(lower=0) / 2.0)]:
        line, z = stats(label, strategy(panel, meta, sig, cap=1.0))
        lines.append(line)
        keep[label] = z
        print(line, flush=True)
    for label, p in preds.items():
        sd = p.std()
        for vname, sig in (("予想に比例", p / sd), ("予想がプラスで、ルールが1つ以上の日だけ", (p / sd).where(panel["n"] >= 1, 0.0)),
                           ("ルールの数 × 予想（予想がプラスのとき）", (p / sd).clip(lower=0) * panel["n"] / 2.0)):
            line, z = stats(f"{label}：{vname}", strategy(panel, meta, sig))
            lines.append(line)
            keep[f"{label}：{vname}"] = z
            print(line, flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_predict.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    pd.DataFrame(keep).to_parquet(os.path.join(D.CACHE, "index_predict_returns.parquet"))
    pd.DataFrame(preds).assign(name=panel["name"].values, n=panel["n"].values, y=panel["y"].values).to_parquet(os.path.join(D.CACHE, "index_predict_preds.parquet"))


if __name__ == "__main__":
    main()

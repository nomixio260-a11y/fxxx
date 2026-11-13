#!/usr/bin/env python3
"""東京仲値（9:55）の後の値動きを、機械学習で予測する（イベントに絞ったモデル）。

これまでの G3F は「仲値前30分の動き」という1つの条件だけで入るかを決めていた。
ここでは、仲値前のいろいろな動きや日の条件を合わせて、仲値後（9:55→12:00）に USDJPY が下がるかを予測する。
- 対象：日本の全営業日（ゴトー日かどうかは特徴量の1つ）
- 特徴量（9:55 の時点で確定しているもの）：
  USDJPY と EURJPY の仲値前 5/15/30/60/120 分の動き、夜間（NY 17:00→9:25）の動き、前日の動き、
  値動きの大きさ、曜日、ゴトー日、月末、次のゴトー日までの営業日数
- モデル：ロジスティック回帰（L2）と LightGBM（浅い木）
- 取引：予測確率が学習期間の上位 q（q = 20% / 35% / 50%）の日だけ売る。損益はコスト後の pips。
- 評価：設計期間の中のウォークフォワード（前の年まで学習 → 2018〜2021年の各1年）。
  検証期間は、設計期間全体で学習したモデルで1回だけ。比較対象は G3F のルール。

使い方: python3 tools/research/fix_ml.py  → reports/research/fix_ml.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402


def build():
    u = D.bars("USDJPY", "5min")
    e = D.bars("EURJPY", "5min")
    fix = u.index[(u["tky_h"].values == 9) & (u["tky_m"].values == 55)]
    dates = pd.DatetimeIndex(u.loc[fix, "tky_date"])
    hol = S.load_jp_holidays()
    biz = np.array([S.jp_business(d, hol) for d in dates])
    fix, dates = fix[biz], dates[biz]
    pu = lambda t: u["o"].reindex(t).values  # noqa: E731
    pe = lambda t: e["o"].reindex(t).values  # noqa: E731
    h1 = D.bars("USDJPY", "1h")
    rng = (h1["h"] - h1["l"]).rolling(24).mean().shift(1)
    a = rng.reindex(fix.floor("1h")).values / 0.01
    he = D.bars("EURJPY", "1h")
    ae = (he["h"] - he["l"]).rolling(24).mean().shift(1).reindex(fix.floor("1h")).values / 0.01
    X = pd.DataFrame(index=fix)
    for m in (5, 15, 30, 60, 120):
        X[f"u{m}"] = (pu(fix) - pu(fix - pd.Timedelta(minutes=m))) / 0.01 / a
        X[f"e{m}"] = (pe(fix) - pe(fix - pd.Timedelta(minutes=m))) / 0.01 / ae
    ny = fix.tz_localize("UTC").tz_convert("America/New_York")
    nyc = ny.normalize() + pd.Timedelta(hours=17)
    nyc = nyc.where(nyc < ny, nyc - pd.Timedelta(days=1)).tz_convert("UTC").tz_localize(None)
    X["night"] = (pu(fix - pd.Timedelta(minutes=30)) - u["o"].reindex(nyc, method="ffill").values) / 0.01 / a
    X["prevday"] = (u["o"].reindex(nyc, method="ffill").values - u["o"].reindex(nyc - pd.Timedelta(days=1), method="ffill").values) / 0.01 / a
    X["vol"] = (rng / rng.rolling(500).mean()).reindex(fix.floor("1h")).values
    X["dow"] = dates.dayofweek
    X["gotobi"] = S.gotobi_mask(dates).astype(float)
    nxt = dates + pd.offsets.BDay(1)
    X["monthend"] = (nxt.month != dates.month).astype(float)
    g = X["gotobi"].values
    togo = np.zeros(len(g))
    k = 0
    for i in range(len(g) - 1, -1, -1):
        k = 0 if g[i] else k + 1
        togo[i] = k
    X["to_gotobi"] = np.minimum(togo, 5)
    post = -(pu(fix + pd.Timedelta(minutes=125)) - pu(fix)) / 0.01 - S.COST["USDJPY"]   # 売りのコスト後の損益
    return X, post


def stat(p):
    p = np.asarray(p, float)
    p = p[~np.isnan(p)]
    if len(p) < 20:
        return {"n": len(p), "mean": 0.0, "pf": 0.0, "t": 0.0}
    gp, gl = p[p > 0].sum(), -p[p < 0].sum()
    return {"n": len(p), "mean": p.mean(), "pf": gp / gl if gl > 0 else 9.99, "t": p.mean() / p.std(ddof=1) * np.sqrt(len(p))}


def fmt(s):
    return f"{s['n']}回 {s['mean']:+.2f}pips PF {s['pf']:.2f} t {s['t']:.1f}"


def models():
    import lightgbm as lgb
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return {
        "ロジスティック回帰": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=1000)),
        "LightGBM": lambda: lgb.LGBMClassifier(n_estimators=150, learning_rate=0.03, num_leaves=5, min_child_samples=40,
                                               subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0,
                                               random_state=0, verbose=-1),
    }


def main():
    X, post = build()
    ok = X.notna().all(axis=1).values & ~np.isnan(post)
    X, post = X[ok], post[ok]
    y = (post > 0).astype(int)
    t = X.index
    des = D.period_mask(t, D.DESIGN)
    val = D.period_mask(t, D.VALID)
    got = X["gotobi"].values > 0
    g3f = got & (X["u30"].values > -0.07)
    out = ["# 東京仲値の後の USDJPY 売りを機械学習で選ぶ（コスト後）", "",
           f"- 比較：G3F のルール（ゴトー日かつ仲値前30分 > -0.07）　設計 {fmt(stat(post[des & g3f]))} ／ 検証 {fmt(stat(post[val & g3f]))}",
           f"- 参考：ゴトー日すべて　設計 {fmt(stat(post[des & got]))} ／ 検証 {fmt(stat(post[val & got]))}",
           f"- 参考：全営業日　設計 {fmt(stat(post[des]))} ／ 検証 {fmt(stat(post[val]))}", ""]
    for name, mk in models().items():
        out += [f"## {name}", "", "| 上位 q | 設計WF（2018〜2021年） | 検証 |", "|---|---|---|"]
        for q in (0.20, 0.35, 0.50):
            wf = []
            for yr in (2018, 2019, 2020, 2021):
                tr = t < pd.Timestamp(f"{yr}-01-01")
                te = (t >= pd.Timestamp(f"{yr}-01-01")) & (t < pd.Timestamp(f"{yr + 1}-01-01"))
                m = mk().fit(X[tr].values, y[tr])
                thr = np.quantile(m.predict_proba(X[tr].values)[:, 1], 1 - q)
                wf.append(post[te][m.predict_proba(X[te].values)[:, 1] > thr])
            m = mk().fit(X[des].values, y[des])
            thr = np.quantile(m.predict_proba(X[des].values)[:, 1], 1 - q)
            pv = post[val][m.predict_proba(X[val].values)[:, 1] > thr]
            out.append(f"| {int(q * 100)}% | {fmt(stat(np.concatenate(wf)))} | {fmt(stat(pv))} |")
        if name == "LightGBM":
            m = mk().fit(X[des].values, y[des])
            imp = sorted(zip(m.feature_importances_, X.columns), reverse=True)[:8]
            out += ["", "重要な特徴量：" + "、".join(n for _, n in imp)]
        out.append("")
    # G3F と同じ期間（2018〜2021年）での G3F の成績（ウォークフォワードと比べるため）
    wfp = (t >= pd.Timestamp("2018-01-01")) & (t < pd.Timestamp("2022-01-01"))
    out.append(f"- 比較：G3F の 2018〜2021年 {fmt(stat(post[wfp & g3f]))}")
    text = "\n".join(out)
    open(os.path.join(D.ROOT, "reports", "research", "fix_ml.md"), "w", encoding="utf-8").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""狭い範囲で動きやすいクロス通貨（AUDNZD・AUDCAD・NZDCAD・EURGBP）の平均回帰と、機械学習による取引の選別。

時間帯の偏りとは別の仕組み（経済の結びつきの強い通貨どうしは、離れすぎると戻りやすい）を使う。

1. 基本ルール：72時間の平均（EMA）から、1時間足の平均値幅の K 倍以上離れたら、逆向きに入って H 時間保有する。
   K ∈ {1.5, 2.0, 2.5, 3.0}、H ∈ {6, 12, 24}。保有中は次の取引をしない。損切りは平均値幅の 4 倍（研究用の近似）。
   設計期間の t が最も高い組み合わせを選び、検証期間で1回だけ確かめる。
2. 機械学習（LightGBM の分類）：基本ルールの各取引が「コスト後に勝つか」を予測し、予測の下位を見送る。
   - ウォークフォワード：前の年までで学習 → 次の1年（2018〜2021年）
   - 検証期間：設計期間全体で学習したモデルで1回だけ
   - 特徴量はすべて、入る時点で確定している足から計算する。

使い方: python3 tools/research/mr_ml.py  → reports/research/mr_ml.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import ta as T  # noqa: E402

PAIRS = ["AUDNZD", "AUDCAD", "NZDCAD", "EURGBP"]
COST = {"AUDNZD": 3.0, "AUDCAD": 2.5, "NZDCAD": 3.5, "EURGBP": 1.5}   # OANDA の通常スプレッドの目安＋不利な約定 0.5
KS = [1.5, 2.0, 2.5, 3.0]
HS = [6, 12, 24]


def features(df):
    pip = 1e-4
    c, h, l = df["c"], df["h"], df["l"]
    rng = (h - l).rolling(24).mean()
    f = pd.DataFrame(index=df.index)
    c1 = c.shift(1)
    a = rng.shift(1)
    for n in (24, 72, 168):
        f[f"z{n}"] = (c1 - c.ewm(span=n, adjust=False).mean().shift(1)) / a
    for k in (1, 4, 24, 72):
        f[f"r{k}"] = (c1 - c.shift(1 + k)) / a
    f["atr_rel"] = a / rng.rolling(500).mean().shift(1)
    f["atr_pips"] = a / pip
    f["hour"] = df.index.hour
    f["dow"] = df.index.dayofweek
    ta = T.ta_features(df)
    for col in ("h1_rsi", "h1_bb_pb", "h1_adx", "h4_rsi", "h4_bb_pb", "h4_adx", "d1_rsi", "d1_bb_pb", "d1_adx", "d1_ema50_d", "d1_ema200_d", "pd_pos"):
        f[col] = ta[col]
    return f


def trades(df, f, K, H, pip, cost):
    """基本ルールの取引（重ならないように）。戻り値：入った足の位置、向き、損益（pips、コスト後）。"""
    z = f["z72"].values
    a = f["atr_pips"].values
    o, hi, lo = df["o"].values, df["h"].values, df["l"].values
    idx = df.index
    pos, side, pnl = [], [], []
    i, n = 0, len(df)
    while i < n - H - 1:
        if np.isnan(z[i]) or np.isnan(a[i]) or abs(z[i]) < K:
            i += 1
            continue
        s = -1.0 if z[i] > 0 else 1.0
        j = i + H
        if (idx[j] - idx[i]) != pd.Timedelta(hours=H):      # 週末などで足が欠けている
            i += 1
            continue
        sl = 4.0 * a[i]
        entry = o[i]
        # 保有中に損切りに当たったか（足の高値・安値で近似）
        path = range(i, j)
        res = None
        for k in path:
            adverse = (entry - lo[k]) / pip if s > 0 else (hi[k] - entry) / pip
            if adverse >= sl:
                res = -sl
                break
        if res is None:
            res = s * (o[j] - entry) / pip
        pos.append(i)
        side.append(s)
        pnl.append(res - cost)
        i = j
    return np.array(pos, int), np.array(side), np.array(pnl)


def stat(p):
    p = np.asarray(p, float)
    if len(p) < 20:
        return {"n": len(p), "mean": 0.0, "pf": 0.0, "t": 0.0}
    gp, gl = p[p > 0].sum(), -p[p < 0].sum()
    return {"n": len(p), "mean": p.mean(), "pf": gp / gl if gl > 0 else 9.99, "t": p.mean() / p.std(ddof=1) * np.sqrt(len(p))}


def fmt(s):
    return f"{s['n']}回 {s['mean']:+.2f}pips PF {s['pf']:.2f} t {s['t']:.1f}"


def ml_filter(df, f, pos, side, pnl):
    import lightgbm as lgb
    X = f.iloc[pos].copy()
    X["side"] = side
    # 向きをそろえた特徴量（逆張りの向きから見た値）
    for col in ("z24", "z72", "z168", "r1", "r4", "r24", "r72", "h1_bb_pb", "h4_bb_pb", "d1_bb_pb", "d1_ema50_d", "d1_ema200_d"):
        X[col + "_s"] = X[col] * side
    X = X.drop(columns=["side"])
    y = (pnl > 0).astype(int)
    t = df.index[pos]

    def model():
        return lgb.LGBMClassifier(n_estimators=150, learning_rate=0.03, num_leaves=7, min_child_samples=30,
                                  subsample=0.8, subsample_freq=1, colsample_bytree=0.6, reg_lambda=5.0,
                                  random_state=0, verbose=-1)
    out = []
    ok = X.notna().all(axis=1).values
    for q in (0.3, 0.5):
        wf = []
        for yr in (2018, 2019, 2020, 2021):
            tr = ok & (t < pd.Timestamp(f"{yr}-01-01"))
            te = ok & (t >= pd.Timestamp(f"{yr}-01-01")) & (t < pd.Timestamp(f"{yr + 1}-01-01"))
            if tr.sum() < 100 or te.sum() < 10:
                continue
            m = model().fit(X[tr].values, y[tr])
            thr = np.quantile(m.predict_proba(X[tr].values)[:, 1], q)
            keep = m.predict_proba(X[te].values)[:, 1] > thr
            wf.append(pnl[te][keep])
        des = ok & D.period_mask(t, D.DESIGN)
        val = ok & D.period_mask(t, D.VALID)
        m = model().fit(X[des].values, y[des])
        thr = np.quantile(m.predict_proba(X[des].values)[:, 1], q)
        keep = m.predict_proba(X[val].values)[:, 1] > thr
        out.append(f"- 下位{int(q * 100)}%を見送る：設計WF（2018〜2021年）{fmt(stat(np.concatenate(wf) if wf else []))} ／ 検証 {fmt(stat(pnl[val][keep]))}")
    return out


def main():
    lines = ["# クロス通貨の平均回帰と機械学習（1時間足、コスト後）", ""]
    for pair in PAIRS:
        df = D.bars(pair, "1h")
        pip = 1e-4
        cost = COST[pair]
        f = features(df)
        res = []
        for K in KS:
            for H in HS:
                pos, side, pnl = trades(df, f, K, H, pip, cost)
                t = df.index[pos]
                des = D.period_mask(t, D.DESIGN)
                res.append((stat(pnl[des])["t"], K, H, pos, side, pnl, t))
        lines += [f"## {pair}（コスト {cost} pips）", "", "| K | 保有 | 設計 | 検証 |", "|---|---|---|---|"]
        for tt, K, H, pos, side, pnl, t in res:
            des, val = D.period_mask(t, D.DESIGN), D.period_mask(t, D.VALID)
            lines.append(f"| {K} | {H}時間 | {fmt(stat(pnl[des]))} | {fmt(stat(pnl[val]))} |")
        best = max(res, key=lambda r: r[0])
        tt, K, H, pos, side, pnl, t = best
        des, val = D.period_mask(t, D.DESIGN), D.period_mask(t, D.VALID)
        lines += ["", f"- 設計期間で最も良い組み合わせ：K={K}、保有{H}時間 → 設計 {fmt(stat(pnl[des]))} ／ 検証 {fmt(stat(pnl[val]))}",
                  "- 機械学習で取引を選ぶ（LightGBM、選ぶ前の取引は上の組み合わせ）："]
        lines += ml_filter(df, f, pos, side, pnl)
        lines.append("")
        print(pair, "done", file=sys.stderr, flush=True)
    text = "\n".join(lines)
    open(os.path.join(D.ROOT, "reports", "research", "mr_ml.md"), "w", encoding="utf-8").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

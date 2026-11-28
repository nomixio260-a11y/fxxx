#!/usr/bin/env python3
"""複合システム v2：予想モデルの学習（過去だけで学習し、次の年を予想する）。日付・時刻・曜日は使わない。

v1（tools/eco/ml.py）の結果を受けて直した点（直す内容は、v2 の結果を見る前にここに書いて固定した。評価の基準は v1 と同じ tools/eco/evaluate.py）：
 1. 銘柄の種類ごとに別のモデルにする（v1 は指数・為替・金属をまとめて1つのモデルにしていた。指数は「下げたら戻る」、為替は戻らない、と性質が違うので、
    まとめると互いに薄め合う。とくにチャートを読むモデルは、銘柄の種類を知らされていなかった）。
 2. 新しいデータを重くする（重み ＝ 0.5 ^（何年前か ÷ 10）。10年前のデータは半分の重み）。株価指数の日々の値動きは、2000年ごろを境に
    「上げた次の日も上げやすい」から「下げた次の日に戻りやすい」に性質が変わった。古いデータを同じ重みで混ぜると、今の性質を学びにくい。
 3. 指数の学習用のチャートを増やす（米国の株式の ETF 21 本。学習だけに使い、成績の評価には使わない）。
 4. 専門家を2つ足す：
     REG  期待値のモデル：次の日の値動き（値動きの大きさ＝1）を当てる勾配ブースティング（外れ値に強い損失）。確率には Φ(予想) で直す
     KNN  形の似た場面を探すモデル：直近10本の4本値の形がいちばん近い過去の場面を200個探し、そのあと上がった割合を数える（50個分だけ 50% に寄せる）
 モデルの大きさ（木の深さ・層の数・学習の回数など）は v1 と同じ。成績を見て選び直さない。
- 出力：data/eco/preds_v2.parquet（1行＝1銘柄の1日。p_lr・p_gbm・p_cnn・p_reg・p_knn と、答え）。ETF の行は出力に含めない。
使い方: python3 tools/eco/ml2.py
"""
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402

YEARS = list(range(2005, 2027))
CLASSES = ("index", "fx", "metal")
HALF_LIFE = 10.0
MIN_TRAIN = 3000
KNN_K, KNN_BARS, KNN_PRIOR = 200, 10, 50
OUT = os.path.join(DS.CACHE, "preds_v2.parquet")


def fit_lr(Xtr, ytr, wtr, Xte):
    from sklearn.linear_model import LogisticRegression
    mu, sd = np.nanmean(Xtr, axis=0), np.nanstd(Xtr, axis=0)
    sd[sd == 0] = 1.0
    a = np.nan_to_num((Xtr - mu) / sd).clip(-5, 5)
    b = np.nan_to_num((Xte - mu) / sd).clip(-5, 5)
    m = LogisticRegression(C=0.02, max_iter=400)
    m.fit(a, ytr, sample_weight=wtr)
    return m.predict_proba(b)[:, 1], dict(mu=mu, sd=sd, coef=m.coef_[0], intercept=m.intercept_[0])


def gbm_params():
    return dict(n_estimators=300, learning_rate=0.03, num_leaves=8, max_depth=3, subsample=0.7, subsample_freq=1, colsample_bytree=0.7,
                min_child_samples=300, reg_lambda=5.0, random_state=7, n_jobs=4, verbose=-1)


def fit_gbm(Xtr, ytr, wtr, Xte):
    import lightgbm as lgb
    m = lgb.LGBMClassifier(**gbm_params())
    m.fit(Xtr, ytr, sample_weight=wtr)
    return m.predict_proba(Xte)[:, 1], m


def fit_reg(Xtr, ytr, wtr, Xte):
    import lightgbm as lgb
    from scipy.stats import norm
    m = lgb.LGBMRegressor(objective="huber", alpha=1.5, **gbm_params())
    m.fit(Xtr, np.clip(ytr, -4, 4), sample_weight=wtr)
    return norm.cdf(m.predict(Xte)), m


def make_net():
    import torch.nn as nn
    return nn.Sequential(nn.Conv1d(4, 16, 5, padding=2), nn.ReLU(), nn.Conv1d(16, 32, 5, stride=2, padding=2), nn.ReLU(),
                         nn.Conv1d(32, 32, 3, stride=2, padding=1), nn.ReLU(), nn.AdaptiveAvgPool1d(4), nn.Flatten(),
                         nn.Dropout(0.2), nn.Linear(128, 32), nn.ReLU(), nn.Linear(32, 1))


def fit_cnn(Wtr, ytr, wtr, Wte, seeds=(1, 2), epochs=6):
    import torch
    import torch.nn as nn
    torch.set_num_threads(4)
    xtr = torch.from_numpy(np.ascontiguousarray(Wtr.transpose(0, 2, 1))).float().clamp(-6, 6)      # (N, 4, 64)
    xte = torch.from_numpy(np.ascontiguousarray(Wte.transpose(0, 2, 1))).float().clamp(-6, 6)
    yt = torch.from_numpy(ytr.astype(np.float32))
    wt = torch.from_numpy((wtr / wtr.mean()).astype(np.float32))
    out = np.zeros(len(Wte))
    nets = []
    for seed in seeds:
        torch.manual_seed(seed)
        net = make_net()
        opt = torch.optim.Adam(net.parameters(), lr=1e-3, weight_decay=1e-4)
        lossf = nn.BCEWithLogitsLoss(reduction="none")
        n = len(xtr)
        g = torch.Generator().manual_seed(seed)
        for ep in range(epochs):
            net.train()
            perm = torch.randperm(n, generator=g)
            for i in range(0, n, 512):
                j = perm[i:i + 512]
                opt.zero_grad()
                loss = (lossf(net(xtr[j]).squeeze(1), yt[j]) * wt[j]).mean()
                loss.backward()
                opt.step()
        net.eval()
        with torch.no_grad():
            out += torch.sigmoid(net(xte).squeeze(1)).numpy()
        nets.append(net)
    return out / len(seeds), nets


def fit_knn(Wtr, ytr, Wte):
    """形の似た場面：直近 KNN_BARS 本の4本値（最後の終値を基準に、値動きの大きさでそろえたもの）の距離が近い順に KNN_K 個。"""
    import torch
    torch.set_num_threads(4)
    a = torch.from_numpy(np.ascontiguousarray(Wtr[:, -KNN_BARS:, :]).reshape(len(Wtr), -1)).float().clamp(-6, 6)
    b = torch.from_numpy(np.ascontiguousarray(Wte[:, -KNN_BARS:, :]).reshape(len(Wte), -1)).float().clamp(-6, 6)
    yt = torch.from_numpy(ytr.astype(np.float32))
    k = min(KNN_K, len(a))
    out = np.zeros(len(b))
    a2 = (a * a).sum(1)
    for i in range(0, len(b), 500):
        q = b[i:i + 500]
        d = a2[None, :] - 2.0 * q @ a.T                      # 距離の2乗から、問い合わせ側だけの項を除いたもの（順位は同じ）
        idx = torch.topk(d, k, dim=1, largest=False).indices
        out[i:i + 500] = ((yt[idx].sum(1) + KNN_PRIOR * 0.5) / (k + KNN_PRIOR)).numpy()
    return out


def load_all():
    rows, win = DS.build()
    er, ew = DS.build_etf()
    n0 = len(rows)
    allr = pd.concat([rows, er], ignore_index=True)
    allw = np.concatenate([np.asarray(win), np.asarray(ew)], axis=0)
    is_eval = np.arange(len(allr)) < n0
    return allr, allw, is_eval


def main(save_models=None):
    rows, win, is_eval = load_all()
    cols = DS.feature_cols()
    X = rows[cols].values.astype(np.float32)
    up = rows["up"].values.astype(np.float32)
    yv = rows["y"].values.astype(np.float32)
    dates = rows["date"].values
    year = pd.DatetimeIndex(rows["date"]).year.values
    klass = rows["klass"].values
    names = ("p_lr", "p_gbm", "p_cnn", "p_reg", "p_knn")
    P = {k: np.full(len(rows), np.nan) for k in names}
    imp = {c: np.zeros(len(cols)) for c in CLASSES}
    nfit = {c: 0 for c in CLASSES}
    t0 = time.time()
    for Y in YEARS:
        a, b = np.datetime64(f"{Y}-01-01"), np.datetime64(f"{Y + 1}-01-01")
        for c in CLASSES:
            tr = (klass == c) & (dates < a)
            last2 = rows.loc[tr].groupby("inst").tail(2).index.values       # 答えが次の年にかかる行を除く
            tr[last2] = False
            te = (klass == c) & (dates >= a) & (dates < b) & is_eval
            if tr.sum() < MIN_TRAIN or te.sum() == 0:
                continue
            w = 0.5 ** ((Y - year[tr]) / HALF_LIFE)
            P["p_lr"][te], _ = fit_lr(X[tr], up[tr], w, X[te])
            P["p_gbm"][te], m = fit_gbm(X[tr], up[tr], w, X[te])
            imp[c] += m.feature_importances_
            nfit[c] += 1
            P["p_reg"][te], _ = fit_reg(X[tr], yv[tr], w, X[te])
            P["p_knn"][te] = fit_knn(win[tr], up[tr], win[te])
            if (Y - YEARS[0]) % 2 == 0:                                      # チャートを読むモデルは2年ごとに学習し直す
                te2 = (klass == c) & (dates >= a) & (dates < np.datetime64(f"{Y + 2}-01-01")) & is_eval
                P["p_cnn"][te2], _ = fit_cnn(win[tr], up[tr], w, win[te2])
            print(f"{Y} {c}: 学習 {int(tr.sum())} 行、予想 {int(te.sum())} 行、経過 {time.time() - t0:.0f} 秒", flush=True)
    keep = ["date", "inst", "klass", "up", "y", "r_next", "sig", "st_r2", "st_d7", "st_ibs", "st_n", "above200", "vix_rank", "ret1", "rsi2", "ibs", "range_today", "atr_ratio"]
    out = rows[keep].copy()
    for k in names:
        out[k] = P[k]
    out = out[is_eval & out["p_lr"].notna().values].reset_index(drop=True)
    out.to_parquet(OUT)
    pd.DataFrame({c: imp[c] / max(nfit[c], 1) for c in CLASSES}, index=cols).sort_values("index", ascending=False).to_csv(os.path.join(DS.CACHE, "gbm_importance_v2.csv"))
    print("保存", OUT, len(out))


if __name__ == "__main__":
    main()

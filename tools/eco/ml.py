#!/usr/bin/env python3
"""複合システム：予想モデルの学習（過去だけで学習し、次の年を予想する）。日付・時刻・曜日は使わない。

- 3種類のモデルが、それぞれ「次の日に上がる確率」を出す：
   LR   線形（ロジスティック回帰）。特徴量 88 個（指標 78 ＋ ルールの状態 4 ＋ VIX 3 ＋ 銘柄の種類 3）
   GBM  勾配ブースティング（小さな木：深さ3・葉8・300本・学習率0.03。98章と同じ大きさに固定）。同じ特徴量
   CNN  チャートを読むモデル（畳み込みニューラルネット）。指標は使わず、直近64本の4本値（始値・高値・安値・終値）の形だけを見る
- 学習のしかた：テストする年 Y ごとに、Y 年より前のすべての銘柄のデータで学習し、Y 年の各日を予想する（2005〜2026年）。
  CNN は時間がかかるので、2年ごとに学習し直す（その2年を予想）。学習の最後の2日は、答えが予想の期間にかかるので除く。
- 設定（木の大きさ・層の数・学習の回数など）は、結果を見る前に決めて固定した。成績を見て選び直さない。
- 出力：data/eco/preds_v1.parquet（1行＝1銘柄の1日。p_lr・p_gbm・p_cnn と、答え）。評価は tools/eco/evaluate.py。
使い方: python3 tools/eco/ml.py
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
OUT = os.path.join(DS.CACHE, "preds_v1.parquet")


def fit_lr(Xtr, ytr, Xte):
    from sklearn.linear_model import LogisticRegression
    mu, sd = np.nanmean(Xtr, axis=0), np.nanstd(Xtr, axis=0)
    sd[sd == 0] = 1.0
    a = np.nan_to_num((Xtr - mu) / sd).clip(-5, 5)
    b = np.nan_to_num((Xte - mu) / sd).clip(-5, 5)
    m = LogisticRegression(C=0.02, max_iter=400)
    m.fit(a, ytr)
    return m.predict_proba(b)[:, 1]


def fit_gbm(Xtr, ytr, Xte):
    import lightgbm as lgb
    m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=8, max_depth=3, subsample=0.7, subsample_freq=1, colsample_bytree=0.7,
                           min_child_samples=300, reg_lambda=5.0, random_state=7, n_jobs=4, verbose=-1)
    m.fit(Xtr, ytr)
    return m.predict_proba(Xte)[:, 1], m


def fit_cnn(Wtr, ytr, Wte, seeds=(1, 2), epochs=6):
    import torch
    import torch.nn as nn
    torch.set_num_threads(4)
    xtr = torch.from_numpy(np.ascontiguousarray(Wtr.transpose(0, 2, 1))).float().clamp(-6, 6)      # (N, 4, 64)
    xte = torch.from_numpy(np.ascontiguousarray(Wte.transpose(0, 2, 1))).float().clamp(-6, 6)
    yt = torch.from_numpy(ytr.astype(np.float32))
    out = np.zeros(len(Wte))
    for seed in seeds:
        torch.manual_seed(seed)
        net = nn.Sequential(nn.Conv1d(4, 16, 5, padding=2), nn.ReLU(), nn.Conv1d(16, 32, 5, stride=2, padding=2), nn.ReLU(),
                            nn.Conv1d(32, 32, 3, stride=2, padding=1), nn.ReLU(), nn.AdaptiveAvgPool1d(4), nn.Flatten(),
                            nn.Dropout(0.2), nn.Linear(128, 32), nn.ReLU(), nn.Linear(32, 1))
        opt = torch.optim.Adam(net.parameters(), lr=1e-3, weight_decay=1e-4)
        lossf = nn.BCEWithLogitsLoss()
        n = len(xtr)
        g = torch.Generator().manual_seed(seed)
        for ep in range(epochs):
            net.train()
            perm = torch.randperm(n, generator=g)
            for i in range(0, n, 512):
                j = perm[i:i + 512]
                opt.zero_grad()
                loss = lossf(net(xtr[j]).squeeze(1), yt[j])
                loss.backward()
                opt.step()
        net.eval()
        with torch.no_grad():
            out += torch.sigmoid(net(xte).squeeze(1)).numpy()
    return out / len(seeds)


def main():
    rows, win = DS.build()
    cols = DS.feature_cols()
    X = rows[cols].values.astype(np.float32)
    y = rows["up"].values.astype(np.float32)
    dates = rows["date"].values
    # 学習から除く行：各銘柄の、テストの年の直前の2日（答えが次の年にかかる）
    order = rows.groupby("inst").cumcount(ascending=False).values            # 銘柄ごとに、後ろから数えた番号
    p_lr, p_gbm, p_cnn = (np.full(len(rows), np.nan) for _ in range(3))
    imp = np.zeros(len(cols))
    t0 = time.time()
    for Y in YEARS:
        a, b = np.datetime64(f"{Y}-01-01"), np.datetime64(f"{Y + 1}-01-01")
        tr = dates < a
        last2 = rows.loc[tr].groupby("inst").tail(2).index.values
        tr[last2] = False
        te = (dates >= a) & (dates < b)
        if te.sum() == 0:
            continue
        p_lr[te] = fit_lr(X[tr], y[tr], X[te])
        p_gbm[te], m = fit_gbm(X[tr], y[tr], X[te])
        imp += m.feature_importances_
        if (Y - YEARS[0]) % 2 == 0:
            te2 = (dates >= a) & (dates < np.datetime64(f"{Y + 2}-01-01"))
            p_cnn[te2] = fit_cnn(np.asarray(win[tr]), y[tr], np.asarray(win[te2]))
        print(f"{Y}: 学習 {int(tr.sum())} 行、予想 {int(te.sum())} 行、経過 {time.time() - t0:.0f} 秒", flush=True)
    keep = ["date", "inst", "klass", "up", "y", "r_next", "sig", "st_r2", "st_d7", "st_ibs", "st_n", "above200", "vix_rank", "ret1", "rsi2", "ibs"]
    out = rows[keep].copy()
    out["p_lr"], out["p_gbm"], out["p_cnn"] = p_lr, p_gbm, p_cnn
    out = out[out["p_lr"].notna()].reset_index(drop=True)
    out.to_parquet(OUT)
    pd.Series(imp / len(YEARS), index=cols).sort_values(ascending=False).to_csv(os.path.join(DS.CACHE, "gbm_importance_v1.csv"))
    print("保存", OUT, len(out))


if __name__ == "__main__":
    main()

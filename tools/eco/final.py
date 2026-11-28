#!/usr/bin/env python3
"""複合システム：毎日の予想に使うモデルを保存する（株価指数のモデル）。日付・時刻・曜日は使わない。

- 学習は tools/eco/ml2.py と同じ（同じデータ・同じ設定・同じ乱数の種）。Y 年の予想に使うモデル ＝ Y 年より前のデータだけで学習したもの。
  チャートを読むモデル（CNN）は2年ごとに学習し直す決まりなので、学習し直す年でなければ、前の年のものを使う（検証のときと同じ）。
- 保存するもの（models/eco/index/）：
   lr.npz    線形のモデル（特徴量の平均・標準偏差・係数）
   gbm.txt   勾配ブースティング（上がる確率）
   reg.txt   期待値のモデル（次の日の値動き。確率には Φ(予想) で直す）
   cnn.npz   チャートを読むモデルの重み（乱数の種2つ分）
   meta.json 特徴量の並び、z の物差し（b・s）、学習に使った最後の日付など
- 毎日のエンジンは、LR・GBM・CNN・REG の4つの確率の平均（AVG4）。KNN（形の似た場面を探すモデル）は、過去の全場面のデータ（数十 MB）を
  持ち歩く必要があるので、毎日の予想からは外す（検証での成績の違いは reports/eco/v2.md の後ろに載せる）。
- z の物差し：Y 年より前の「学習に使っていない年の予想」（data/eco/preds_v2.parquet の指数の行）の AVG4 の平均 b と標準偏差 s。
- 保存したモデルで Y 年を予想し直し、検証のときの予想（preds_v2.parquet）と同じ値になることを確かめる。
使い方: python3 tools/eco/final.py [年]   （年を省くと 2026）
"""
import datetime
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402
import ml2 as M2  # noqa: E402
import predict as PR  # noqa: E402

OUT_DIR = os.path.join(DS.F.ROOT, "models", "eco", "index")
E4 = ("p_lr", "p_gbm", "p_cnn", "p_reg")


def main():
    Y = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    Yc = Y if (Y - M2.YEARS[0]) % 2 == 0 else Y - 1                      # CNN を学習し直した年
    rows, win, is_eval = M2.load_all()
    cols = DS.feature_cols()
    X = rows[cols].values.astype(np.float32)
    up, yv = rows["up"].values.astype(np.float32), rows["y"].values.astype(np.float32)
    dates = rows["date"].values
    year = pd.DatetimeIndex(rows["date"]).year.values
    is_index = (rows["klass"] == "index").values

    def train_mask(yy):
        tr = is_index & (dates < np.datetime64(f"{yy}-01-01"))
        tr[rows.loc[tr].groupby("inst").tail(2).index.values] = False
        return tr
    tr = train_mask(Y)
    te = is_index & (dates >= np.datetime64(f"{Y}-01-01")) & (dates < np.datetime64(f"{Y + 1}-01-01")) & is_eval
    w = 0.5 ** ((Y - year[tr]) / M2.HALF_LIFE)
    os.makedirs(OUT_DIR, exist_ok=True)
    p_lr, lr = M2.fit_lr(X[tr], up[tr], w, X[te])
    np.savez(os.path.join(OUT_DIR, "lr.npz"), mu=lr["mu"], sd=lr["sd"], coef=lr["coef"], intercept=lr["intercept"])
    p_gbm, m = M2.fit_gbm(X[tr], up[tr], w, X[te])
    m.booster_.save_model(os.path.join(OUT_DIR, "gbm.txt"))
    p_reg, m = M2.fit_reg(X[tr], yv[tr], w, X[te])
    m.booster_.save_model(os.path.join(OUT_DIR, "reg.txt"))
    trc = train_mask(Yc)
    wc = 0.5 ** ((Yc - year[trc]) / M2.HALF_LIFE)
    p_cnn, nets = M2.fit_cnn(win[trc], up[trc], wc, win[te])
    arrs = {}
    for k, net in enumerate(nets):
        for name, t in net.state_dict().items():
            arrs[f"s{k}_{name.replace('.', '_')}"] = t.numpy()
    np.savez(os.path.join(OUT_DIR, "cnn.npz"), **arrs)
    # ---------- z の物差し（Y 年より前の、学習に使っていない年の予想から）
    W = pd.read_parquet(os.path.join(DS.CACHE, "preds_v2.parquet"))
    W["date"] = pd.to_datetime(W["date"])
    Wi = W[(W["klass"] == "index") & (W["date"].dt.year < Y)]
    avg4 = PR.sigmoid(np.nanmean(np.column_stack([PR.logit(Wi[k].values) for k in E4]), axis=1))
    meta = dict(version="v2", year=Y, cnn_year=Yc, features=cols, engine="AVG4 (LR, GBM, CNN, REG)", z_b=float(np.mean(avg4)), z_s=float(np.std(avg4, ddof=1)),
                train_last_date=str(pd.Timestamp(dates[tr].max()).date()), train_rows=int(tr.sum()), built=str(datetime.date.today()),
                win=DS.WIN, half_life=M2.HALF_LIFE)
    json.dump(meta, open(os.path.join(OUT_DIR, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"保存 {OUT_DIR}：学習 {int(tr.sum())} 行（〜{meta['train_last_date']}）、z の物差し b = {meta['z_b']:.4f}・s = {meta['z_s']:.4f}")
    # ---------- 確かめ1：保存したモデルを読み直して予想し、いま学習したものと同じ値になるか
    mdl = PR.load_models(OUT_DIR)
    q = PR.predict_matrix(mdl, X[te], np.asarray(win[te]))
    for k, ref in (("p_lr", p_lr), ("p_gbm", p_gbm), ("p_reg", p_reg), ("p_cnn", p_cnn)):
        print(f"  保存 → 読み直し {k}: 差の最大 {np.abs(q[k] - ref).max():.2e}")
    # ---------- 確かめ2：検証のときの予想（preds_v2.parquet）と同じ値になるか
    ref = W.merge(rows.loc[te, ["date", "inst"]].assign(i=np.arange(int(te.sum()))), on=["date", "inst"], how="inner")
    for k in E4:
        print(f"  検証のときの予想との差 {k}: 最大 {np.abs(q[k][ref['i'].values] - ref[k].values).max():.2e}（{len(ref)} 行）")


if __name__ == "__main__":
    main()

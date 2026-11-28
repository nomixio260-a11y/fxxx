#!/usr/bin/env python3
"""複合システム：毎日の予想を出す（EA の「確率の層」が読むファイルを作る）。日付・時刻・曜日は使わない。

- 流れ：EA（確率の層）が、新しい日足が始まるたびに、確定した日足を共通フォルダに書き出す（AMS_pb_bars_<銘柄>.csv）
  → このスクリプトが、指標・ルールの状態・チャートの形を数値にして、保存してあるモデル（models/eco/index/）に渡す
  → 4つのモデル（線形・勾配ブースティング・チャートを読むモデル・期待値のモデル）の確率を平均し、合図 z に直して、AMS_prob.csv に書く
  → EA がその行を読んで、建玉を合わせる（影のモードのあいだは、注文は出さず、記録だけ）。
- 必要なもの：numpy・pandas・lightgbm だけ（学習用のライブラリは要らない）。
- 予想の行は、どれも「その日足が確定した時点で分かっていること」だけで作る（VIX は1日前の値。学習のときと同じ）。
- 記録（--log）：最新の日足の予想を、モデルごとの確率・いまの層のルールの数・値動きの大きさ・終値と一緒に、1行ずつためていく
  （あとで当たり外れを採点する。tools/eco/shadow_score.py）。同じ日足・同じ銘柄の行は、最初に書いたものを残す（あとから書き換えない）。
使い方: python3 tools/eco/predict.py --bars <日足のフォルダ> --vix <AMS_vix.csv> --out <AMS_prob.csv> [--log <AMS_prob_log.csv>] [--models <フォルダ>]
"""
import argparse
import datetime
import glob
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import features as FT  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
_erf = np.frompyfunc(math.erf, 1, 1)


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def norm_cdf(x):
    return 0.5 * (1.0 + _erf(np.asarray(x, dtype=float) / math.sqrt(2.0)).astype(float))


# ---------------------------------------------------------------- モデル
def load_models(folder):
    import lightgbm as lgb
    lr = np.load(os.path.join(folder, "lr.npz"))
    cnn = np.load(os.path.join(folder, "cnn.npz"))
    seeds = sorted({k.split("_")[0] for k in cnn.files})
    return dict(meta=json.load(open(os.path.join(folder, "meta.json"), encoding="utf-8")),
                lr={k: lr[k] for k in lr.files}, gbm=lgb.Booster(model_file=os.path.join(folder, "gbm.txt")),
                reg=lgb.Booster(model_file=os.path.join(folder, "reg.txt")),
                cnn=[{k[len(s) + 1:]: cnn[k] for k in cnn.files if k.startswith(s + "_")} for s in seeds])


def _conv1d(x, w, b, stride, pad):
    """x：(N, C, L)、w：(O, C, K)。"""
    if pad:
        x = np.pad(x, ((0, 0), (0, 0), (pad, pad)))
    v = np.lib.stride_tricks.sliding_window_view(x, w.shape[2], axis=2)[:, :, ::stride, :]      # (N, C, L', K)
    return np.einsum("nclk,ock->nol", v, w, optimize=True) + b[None, :, None]


def cnn_forward(nets, win):
    """チャートを読むモデル（tools/eco/ml2.py の make_net と同じ形）を、numpy だけで計算する。win：(N, 64, 4)。"""
    x0 = np.clip(np.ascontiguousarray(win.transpose(0, 2, 1)).astype(np.float32), -6, 6)
    out = np.zeros(len(win))
    for p in nets:
        x = np.maximum(_conv1d(x0, p["0_weight"], p["0_bias"], 1, 2), 0)
        x = np.maximum(_conv1d(x, p["2_weight"], p["2_bias"], 2, 2), 0)
        x = np.maximum(_conv1d(x, p["4_weight"], p["4_bias"], 2, 1), 0)
        n, c, l = x.shape
        x = x.reshape(n, c, 4, l // 4).mean(axis=3).reshape(n, c * 4)                             # AdaptiveAvgPool1d(4) → Flatten
        x = np.maximum(x @ p["9_weight"].T + p["9_bias"], 0)
        out += sigmoid((x @ p["11_weight"].T + p["11_bias"])[:, 0])
    return out / len(nets)


def predict_matrix(mdl, X, win):
    lr = mdl["lr"]
    a = np.clip(np.nan_to_num((X - lr["mu"]) / lr["sd"]), -5, 5)
    out = dict(p_lr=sigmoid(a @ lr["coef"] + lr["intercept"]), p_gbm=mdl["gbm"].predict(X), p_reg=norm_cdf(mdl["reg"].predict(X)), p_cnn=cnn_forward(mdl["cnn"], win))
    out["p"] = sigmoid(np.mean(np.column_stack([logit(out[k]) for k in ("p_lr", "p_gbm", "p_cnn", "p_reg")]), axis=1))
    out["z"] = np.clip((out["p"] - mdl["meta"]["z_b"]) / mdl["meta"]["z_s"], -2, 2)
    return out


# ---------------------------------------------------------------- データ
def read_bars(path, drop_last=False):
    d = pd.read_csv(path)
    d.index = pd.to_datetime(d["date"].astype(str).str.slice(0, 10), format="%Y.%m.%d")
    d = d[["open", "high", "low", "close"]].astype(float).dropna()
    d = d[d.index.dayofweek < 5]                     # 土日の日付が付いた足（業者のデータにまれにある短い足）を除く。学習のときと同じデータの整理
    d = d[~d.index.duplicated(keep="last")].sort_index()
    if drop_last:
        d = d.iloc[:-1]
    return d[(d["close"] > 0) & (d["high"] >= d["low"])]


def read_vix(path):
    """行は「日付(yyyy.MM.dd),終値」。見出しがあってもよい。"""
    v = pd.read_csv(path, header=None, names=["date", "close"], usecols=[0, 1])
    v = v[v["date"].astype(str).str.match(r"^\d{4}\.\d{2}\.\d{2}")]
    s = pd.Series(v["close"].astype(float).values, index=pd.to_datetime(v["date"], format="%Y.%m.%d"))
    return s[~s.index.duplicated(keep="last")].sort_index().dropna()


def vix_features(v):
    lr = np.log(v).diff()
    return pd.DataFrame({"vix_rank": v.rolling(250).rank(pct=True) * 2 - 1, "vix_chg1": (lr / lr.rolling(250).std()).clip(-6, 6),
                         "vix_chg5": (np.log(v / v.shift(5)) / (lr.rolling(250).std() * np.sqrt(5))).clip(-6, 6)})


def build_rows(d, vixf, cols, win_len=64):
    """日足 d から、特徴量の表（cols の並び）と、チャートの窓を作る。tools/eco/dataset.py の one と同じ計算（答えの列がないだけ）。"""
    f = FT.build(d)
    st = FT.rule_states(d)
    for k in st.columns:
        f[k] = st[k].values
    vx = vixf.reindex(vixf.index.union(d.index)).ffill().shift(1).reindex(d.index)      # 1日前の VIX
    for k in vixf.columns:
        f[k] = vx[k].values
    f["is_index"], f["is_fx"], f["is_metal"] = 1.0, 0.0, 0.0
    lp = np.log(d[["open", "high", "low", "close"]].values)
    win = np.full((len(d), win_len, 4), np.nan, dtype=np.float32)
    if len(d) >= win_len:
        sw = np.lib.stride_tricks.sliding_window_view(lp, (win_len, 4))[:, 0]
        win[win_len - 1:] = ((sw - lp[win_len - 1:, 3][:, None, None]) / (f["sig"].values[win_len - 1:] * 8.0)[:, None, None]).astype(np.float32)
    ok = (f["sig"].notna() & f["ret250"].notna()).values & ~np.isnan(win[:, 0, 0])
    return f.loc[ok, cols].values.astype(np.float32), win[ok], d.index[ok], d["close"].values[ok], f.loc[ok, "sig"].values, f.loc[ok, "st_n"].values


def run(bars_dir, vix_path, out_path, log_path=None, models_dir=None, pattern="AMS_pb_bars_*.csv", drop_last=False, min_bars=400, log_all=False):
    mdl = load_models(models_dir or os.path.join(ROOT, "models", "eco", "index"))
    cols = mdl["meta"]["features"]
    vixf = vix_features(read_vix(vix_path))
    prefix = pattern.split("*")[0]
    out, last = [], []
    for path in sorted(glob.glob(os.path.join(bars_dir, pattern))):
        sym = os.path.basename(path)[len(prefix):-4]
        d = read_bars(path, drop_last)
        if len(d) < min_bars:
            print(f"{sym}: 日足が足りないため飛ばします（{len(d)} 本）")
            continue
        X, W, idx, close, sg, stn = build_rows(d, vixf, cols, mdl["meta"].get("win", 64))
        if len(idx) == 0:
            continue
        q = predict_matrix(mdl, X, W)
        out.append(pd.DataFrame({"date": idx.strftime("%Y.%m.%d"), "symbol": sym, "p": np.round(q["p"], 4), "z": np.round(q["z"], 3)}))
        made = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
        for k in (range(len(idx)) if log_all else [len(idx) - 1]):
            last.append(dict(date=idx[k].strftime("%Y.%m.%d"), symbol=sym, p_lr=round(float(q["p_lr"][k]), 4), p_gbm=round(float(q["p_gbm"][k]), 4),
                             p_cnn=round(float(q["p_cnn"][k]), 4), p_reg=round(float(q["p_reg"][k]), 4), p=round(float(q["p"][k]), 4), z=round(float(q["z"][k]), 3),
                             rules=int(round(float(stn[k]))), sig=round(float(sg[k]), 6), close=float(close[k]),
                             model=f"{mdl['meta']['version']}-{mdl['meta']['year']}", made_utc=made))
    if not out:
        print("予想を出せる銘柄がありません")
        return None, None
    allp = pd.concat(out, ignore_index=True).sort_values(["date", "symbol"])
    tmp = out_path + ".tmp"
    allp.to_csv(tmp, index=False, lineterminator="\n")
    os.replace(tmp, out_path)
    lastd = pd.DataFrame(last)
    if log_path:
        if os.path.exists(log_path):
            old = pd.read_csv(log_path, dtype={"date": str})
            lastd = pd.concat([old, lastd], ignore_index=True).drop_duplicates(["date", "symbol"], keep="first")
        lastd.sort_values(["date", "symbol"]).to_csv(log_path, index=False, lineterminator="\n")
    print(f"予想を書きました：{out_path}（{len(allp)} 行、{allp['symbol'].nunique()} 銘柄、最後の日足 {allp['date'].max()}）")
    for r in ([] if log_all else last):
        print(f"  {r['symbol']}: 日足 {r['date']} → 上がる確率 {r['p'] * 100:.1f}%（線形 {r['p_lr'] * 100:.1f}・勾配 {r['p_gbm'] * 100:.1f}・チャート {r['p_cnn'] * 100:.1f}・期待値 {r['p_reg'] * 100:.1f}）、z {r['z']:+.2f}")
    return allp, lastd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vix", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--log", default=None)
    ap.add_argument("--models", default=None)
    ap.add_argument("--pattern", default="AMS_pb_bars_*.csv")
    ap.add_argument("--drop-last", action="store_true", help="最後の足が作りかけのとき（研究用の書き出し AMS_d1_*.csv）")
    ap.add_argument("--log-all", action="store_true", help="記録に、最新の日足だけでなく、すべての日足の予想を書く（採点のスクリプトの動作確認用。実運用では使わない）")
    a = ap.parse_args()
    run(a.bars, a.vix, a.out, a.log, a.models, a.pattern, a.drop_last, log_all=a.log_all)


if __name__ == "__main__":
    main()

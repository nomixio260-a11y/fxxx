#!/usr/bin/env python3
"""6銘柄をまとめた1つの機械学習モデルで、次の数時間の値動きの向きを当てられるかを調べる（データを増やした版）。

- 1銘柄ずつのモデル（ml_train.py）は、データが少なく偶然の当たりを学習しやすかった。
  ここでは6銘柄の足をまとめて1つのモデルで学習する（銘柄の番号も特徴量に入れる）。
- 特徴量は ml_train.features と同じ（確定足だけ）＋ 時計（東京・ロンドン・NY の時）と銘柄番号。
- 予測対象：次の HOLD 時間の値動きを ATR で割った値。
- 損益は、銘柄ごとにコスト（pips）を引いてから ATR で割り、銘柄をまたいで足し合わせる。
- 設計期間の中でウォークフォワード（前の年までで学習 → 次の1年）、しきい値は3年すべてでプラスのものを採用。
- 設計期間全体で学習し直したモデルを、検証期間で1回だけ評価する。最終確認期間は使わない。

使い方: python3 tools/research/ml_pooled.py [保有時間]
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import ml_train as M  # noqa: E402
import seasonality as S  # noqa: E402


def dataset(hold: int) -> pd.DataFrame:
    frames = []
    for i, pair in enumerate(M.CROSS):
        X = M.features(pair)
        # 他銘柄の列名を「相手ごと」ではなく共通の名前にそろえる（銘柄によって相手が違うため、6銘柄すべての列を持たせる）
        base = D.bars(pair, "1h")
        for other in M.CROSS:
            for k in (1, 4, 24):
                col = f"{other}_r{k}"
                if col not in X.columns:
                    X[col] = X[f"r{k}"]          # 自分自身の列は自分の値動き
        X = X[sorted(X.columns)]
        X["ny_h"] = base["ny_h"]
        X["pair"] = i
        ret, a = M.target(pair, hold)
        X["_ret"] = ret
        X["_atr"] = a
        X["_cost"] = S.COST[pair]
        X["_pair"] = pair
        X["_excl"] = S.rollover_mask(base, hold)
        frames.append(X)
    df = pd.concat(frames)
    df = df[~df["_excl"]]
    feat = [c for c in df.columns if not c.startswith("_")]
    df = df[df[feat].notna().all(axis=1) & df["_ret"].notna() & (df["_atr"] > 0)]
    return df, feat


def evaluate(pred, d, thr):
    side = np.where(pred >= thr, 1.0, np.where(pred <= -thr, -1.0, 0.0))
    m = side != 0
    if m.sum() < 30:
        return {"n": int(m.sum()), "net": 0.0, "pf": 0.0, "t": 0.0, "pips": 0.0}
    pips = side[m] * d["_ret"].values[m] - d["_cost"].values[m]
    pnl = pips / d["_atr"].values[m]           # ATR 単位
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    t = pnl.mean() / pnl.std(ddof=1) * np.sqrt(len(pnl))
    return {"n": int(m.sum()), "net": float(pnl.mean()), "pf": float(gp / gl) if gl > 0 else 9.99,
            "t": float(t), "pips": float(pips.mean())}


def fmt(e):
    return f"{e['n']}回 1取引 {e['pips']:+.2f}pips（ATR比 {e['net']:+.3f}） PF {e['pf']:.2f} t {e['t']:.2f}"


def run(hold: int = 2):
    df, feat = dataset(hold)
    y = df["_ret"] / df["_atr"]
    step = (df.index.hour % hold) == 0          # 同じ銘柄で保有が重ならないように
    thrs = [0.05, 0.10, 0.15, 0.20, 0.30]
    out = [f"## 6銘柄まとめた LightGBM・保有 {hold} 時間", "",
           f"- 学習データ：{len(df):,} 本（6銘柄の1時間足、日付の変わり目と週明けは除外）", ""]
    wf = {t: [] for t in thrs}
    for yr in (2019, 2020, 2021):
        tr = df.index < pd.Timestamp(f"{yr}-01-01")
        te = (df.index >= pd.Timestamp(f"{yr}-01-01")) & (df.index < pd.Timestamp(f"{yr + 1}-01-01")) & step
        mdl = M.make_model("lgbm").fit(df.loc[tr, feat].values, y[tr].values)
        p = mdl.predict(df.loc[te, feat].values)
        for t in thrs:
            e = evaluate(p, df[te], t)
            wf[t].append(e)
            out.append(f"- {yr} しきい値 {t}: {fmt(e)}")
    best = None
    for t in thrs:
        if all(e["net"] > 0 and e["n"] >= 30 for e in wf[t]):
            s = sum(e["t"] for e in wf[t])
            if best is None or s > best[1]:
                best = (t, s)
    out.append("")
    if best is None:
        out.append("**ウォークフォワードの3年すべてでコスト込みプラスになるしきい値はありませんでした（不合格）。**")
        return "\n".join(out)
    thr = best[0]
    out.append(f"→ しきい値 {thr} を採用")
    des = D.period_mask(df.index, D.DESIGN)
    val = D.period_mask(df.index, D.VALID) & step
    mdl = M.make_model("lgbm").fit(df.loc[des, feat].values, y[des].values)
    p = mdl.predict(df.loc[val, feat].values)
    e = evaluate(p, df[val], thr)
    verdict = "合格" if (e["net"] > 0 and e["pf"] >= 1.10 and e["n"] >= 100) else "不合格"
    out += ["", f"### 検証期間：{fmt(e)} → **{verdict}**", ""]
    # 銘柄別
    side = np.where(p >= thr, 1, np.where(p <= -thr, -1, 0))
    dv = df[val]
    for pair in M.CROSS:
        mm = (dv["_pair"].values == pair)
        if mm.sum():
            out.append(f"- {pair}: {fmt(evaluate(p[mm], dv[mm], thr))}")
    imp = sorted(zip(mdl.feature_importances_, feat), reverse=True)[:10]
    out += ["", "重要な特徴量（上位10）：" + "、".join(f"{n}" for _, n in imp), ""]
    _ = side
    return "\n".join(out)


if __name__ == "__main__":
    hold = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    text = run(hold)
    print(text)
    path = os.path.join(D.ROOT, "reports", "research", f"ml_pooled_h{hold}.md")
    open(path, "w", encoding="utf-8").write(text + "\n")

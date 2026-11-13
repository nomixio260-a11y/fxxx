#!/usr/bin/env python3
"""機械学習（LightGBM / ニューラルネット）で、次の数時間の値動きを予測できるかを調べる。

- 特徴量は、MT5 でも同じ計算ができるものだけを使う（確定した足の値だけ。未来の値は使わない）
- 予測対象：次の HOLD 時間の値動き（ATR で割った値）
- 設計期間の中でウォークフォワード（前の年までで学習 → 次の1年で評価）を行い、しきい値を決める
- しきい値を決めたあと、設計期間全体で学習し直したモデルを、検証期間で1回だけ評価する
- 最終確認期間（2024年11月〜）は使わない

使い方: python3 tools/research/ml_train.py [銘柄] [保有時間] [model=lgbm|mlp]
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

CROSS = ["USDJPY", "EURUSD", "EURJPY", "GBPJPY", "AUDJPY", "GBPUSD"]


def atr(df: pd.DataFrame, n: int = 24) -> pd.Series:
    prev = df["c"].shift(1)
    tr = pd.concat([df["h"] - df["l"], (df["h"] - prev).abs(), (df["l"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def features(pair: str) -> pd.DataFrame:
    """各足の「始値の時点」で使える特徴量（= 1本前までの確定足から計算）。"""
    base = D.bars(pair, "1h")
    f = pd.DataFrame(index=base.index)
    a = atr(base).shift(1)
    c1 = base["c"].shift(1)                    # 直前の確定足の終値
    for k in (1, 2, 4, 8, 24, 72):
        f[f"r{k}"] = (c1 - base["c"].shift(1 + k)) / a
    hh = base["h"].rolling(24).max().shift(1)
    ll = base["l"].rolling(24).min().shift(1)
    f["pos24"] = (c1 - ll) / (hh - ll).replace(0, np.nan)
    f["atr_rel"] = a / a.rolling(24 * 20).mean()
    f["tky_h"] = base["tky_h"]
    f["ldn_h"] = base["ldn_h"]
    f["dow"] = base["tky_dow"]
    f["gotobi"] = S.gotobi_mask(pd.DatetimeIndex(base["tky_date"])).astype(float)
    dd = pd.DatetimeIndex(base["tky_date"])
    f["dom"] = dd.day
    f["monthend"] = ((dd + pd.Timedelta(days=3)).month != dd.month).astype(float)
    for other in CROSS:
        if other == pair:
            continue
        ob = D.bars(other, "1h").reindex(base.index)
        oa = atr(D.bars(other, "1h")).reindex(base.index).shift(1)
        oc1 = ob["c"].shift(1)
        for k in (1, 4, 24):
            f[f"{other}_r{k}"] = (oc1 - ob["c"].shift(1 + k)) / oa
    return f


def target(pair: str, hold: int) -> tuple:
    base = D.bars(pair, "1h")
    pip = D.pip_size(pair)
    r = S.window_returns(base, hold, pip)          # 始値で入り hold 時間後に出たときの pips
    a = atr(base).shift(1) / pip                  # ATR（pips）
    return pd.Series(r, index=base.index), a


def make_model(kind: str):
    if kind == "mlp":
        from sklearn.neural_network import MLPRegressor
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(StandardScaler(), MLPRegressor(hidden_layer_sizes=(32, 16), alpha=1e-3,
                                                            max_iter=200, early_stopping=True, random_state=0))
    import lightgbm as lgb
    return lgb.LGBMRegressor(n_estimators=300, learning_rate=0.02, num_leaves=15, min_child_samples=200,
                             subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0,
                             random_state=0, verbose=-1)


def evaluate(pred: np.ndarray, ret: np.ndarray, cost: float, thr: float) -> dict:
    """予測が +thr 以上なら買い、-thr 以下なら売り。1本ごとに1取引（hold 時間保有）。"""
    side = np.where(pred >= thr, 1.0, np.where(pred <= -thr, -1.0, 0.0))
    m = side != 0
    if m.sum() < 30:
        return {"n": int(m.sum()), "net": 0.0, "pf": 0.0, "t": 0.0}
    pnl = side[m] * ret[m] - cost
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    t = pnl.mean() / pnl.std(ddof=1) * np.sqrt(len(pnl))
    return {"n": int(m.sum()), "net": float(pnl.mean()), "pf": float(gp / gl) if gl > 0 else 9.99, "t": float(t)}


def run(pair: str = "USDJPY", hold: int = 4, kind: str = "lgbm"):
    X = features(pair)
    ret, a = target(pair, hold)
    y = ret / a                                     # ATR で割った値動き
    ok = X.notna().all(axis=1) & y.notna() & a.notna()
    X, y, ret, a = X[ok], y[ok], ret[ok], a[ok]
    cost = S.COST[pair]
    # 同じ時間帯に重ならないよう、hold 時間おきの足だけを取引の候補にする（評価用）
    step = (X.index.hour % hold) == 0
    thrs = [0.05, 0.10, 0.15, 0.20, 0.30]

    lines = [f"## {pair}・保有 {hold} 時間・モデル {kind}", ""]
    # --- 設計期間の中でのウォークフォワード
    wf = {t: [] for t in thrs}
    rows = []
    for test_year in (2019, 2020, 2021):
        tr = (X.index < pd.Timestamp(f"{test_year}-01-01"))
        te = (X.index >= pd.Timestamp(f"{test_year}-01-01")) & (X.index < pd.Timestamp(f"{test_year + 1}-01-01")) & step
        model = make_model(kind)
        model.fit(X[tr].values, y[tr].values)
        p = model.predict(X[te].values)
        for t in thrs:
            e = evaluate(p, ret[te].values, cost, t)
            wf[t].append(e)
            rows.append((test_year, t, e))
    lines += ["### 設計期間のウォークフォワード（コスト込み）", "",
              "| 評価年 | しきい値 | 取引数 | 1取引の損益(pips) | PF | t |", "|---|---|---|---|---|---|"]
    for yr, t, e in rows:
        lines.append(f"| {yr} | {t} | {e['n']} | {e['net']:+.2f} | {e['pf']:.2f} | {e['t']:.2f} |")
    # しきい値：3年すべてでコスト込みプラスのうち、合計 t が最大のもの
    best = None
    for t in thrs:
        if all(e["net"] > 0 and e["n"] >= 30 for e in wf[t]):
            score = sum(e["t"] for e in wf[t])
            if best is None or score > best[1]:
                best = (t, score)
    lines.append("")
    if best is None:
        lines += ["**ウォークフォワードの3年すべてでコスト込みプラスになるしきい値はありませんでした（不合格）。**", ""]
        return "\n".join(lines), None
    thr = best[0]
    lines.append(f"→ しきい値 {thr} を採用（3年すべてでコスト込みプラス）")
    # --- 設計期間全体で学習し、検証期間で1回だけ評価
    des = D.period_mask(X.index, D.DESIGN)
    val = D.period_mask(X.index, D.VALID) & step
    model = make_model(kind)
    model.fit(X[des].values, y[des].values)
    e = evaluate(model.predict(X[val].values), ret[val].values, cost, thr)
    verdict = "合格" if (e["net"] > 0 and e["pf"] >= 1.10 and e["n"] >= 100) else "不合格"
    lines += ["", f"### 検証期間（2022年〜2024年10月）：取引 {e['n']} 回、1取引 {e['net']:+.2f} pips、PF {e['pf']:.2f}、t {e['t']:.2f} → **{verdict}**", ""]
    return "\n".join(lines), (model, thr, list(X.columns), e, verdict)


if __name__ == "__main__":
    pair = sys.argv[1] if len(sys.argv) > 1 else "USDJPY"
    hold = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    kind = sys.argv[3] if len(sys.argv) > 3 else "lgbm"
    text, res = run(pair, hold, kind)
    print(text)
    out = os.path.join(D.ROOT, "reports", "research", f"ml_{pair}_h{hold}_{kind}.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(text)

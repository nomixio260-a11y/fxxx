#!/usr/bin/env python3
"""テクニカル指標（RSI・MACD・ボリンジャー・ADX・一目・ドンチャン・ローソク足の形など、H1/H4/D1）を
機械学習と時刻ルールに組み合わせて、成績が良くなるかを調べる。

モード
  pooled HOLD [lgbm|mlp]   : 6銘柄まとめたモデルで、次の HOLD 時間の値動きを予測（時刻・テクニカル・他銘柄の特徴量）
  filter PAIR CLOCK HOUR HOLD SIGN :
      時刻ルールの取引に、テクニカル指標で「入る／見送る」をかける。
      (a) 単純なフィルター（指標の向きが取引の向きと一致するときだけ入る）を、決めた少数の候補で比べる
      (b) LightGBM の分類（メタラベリング）
評価はいつも同じ：設計期間の中のウォークフォワード（前の年までで学習 → 2019/2020/2021 の各1年）で選び、
検証期間は1回だけ見る。最終確認期間（2024年11月〜）は使わない。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import ml_train as M  # noqa: E402
import seasonality as S  # noqa: E402
import ta as T  # noqa: E402

CACHE = os.path.join(D.ROOT, "data", "cache")


def feats(pair: str) -> pd.DataFrame:
    path = os.path.join(CACHE, f"{pair}_feat_ta.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)
    base = D.bars(pair, "1h")
    f = pd.concat([M.features(pair), T.ta_features(base)], axis=1)
    f["ny_h"] = base["ny_h"]
    f.to_parquet(path)
    return f


def stat(p):
    p = np.asarray(p, float)
    if len(p) < 20:
        return {"n": len(p), "mean": 0.0, "pf": 0.0, "t": 0.0}
    gp, gl = p[p > 0].sum(), -p[p < 0].sum()
    return {"n": len(p), "mean": p.mean(), "pf": gp / gl if gl > 0 else 9.99,
            "t": p.mean() / p.std(ddof=1) * np.sqrt(len(p))}


def fmt(s, unit="pips"):
    return f"{s['n']}回 1取引 {s['mean']:+.2f}{unit} PF {s['pf']:.2f} t {s['t']:.2f}"


# ---------------------------------------------------------------- pooled
def pooled(hold: int, kind: str = "lgbm") -> str:
    frames = []
    for i, pair in enumerate(M.CROSS):
        X = feats(pair).copy()
        for other in M.CROSS:                         # 他銘柄の列を6銘柄分そろえる
            for k in (1, 4, 24):
                col = f"{other}_r{k}"
                if col not in X.columns:
                    X[col] = X[f"r{k}"]
        X = X[sorted(X.columns)]
        X["pair"] = i
        base = D.bars(pair, "1h")
        ret, a = M.target(pair, hold)
        X["_ret"], X["_atr"], X["_cost"] = ret, a, S.COST[pair]
        X["_pair"] = pair
        X["_excl"] = S.rollover_mask(base, hold)
        frames.append(X)
    df = pd.concat(frames)
    df = df[~df["_excl"]]
    feat = [c for c in df.columns if not c.startswith("_")]
    df = df[df[feat].notna().all(axis=1) & df["_ret"].notna() & (df["_atr"] > 0)]
    y = (df["_ret"] / df["_atr"]).clip(-5, 5)
    step = (df.index.hour % hold) == 0
    thrs = [0.05, 0.10, 0.15, 0.20, 0.30]

    def ev(p, d, thr):
        side = np.where(p >= thr, 1.0, np.where(p <= -thr, -1.0, 0.0))
        m = side != 0
        return stat(side[m] * d["_ret"].values[m] - d["_cost"].values[m]), m

    out = [f"## 6銘柄まとめ・テクニカル指標つき・{kind}・保有 {hold} 時間", "",
           f"- 学習データ {len(df):,} 本、特徴量 {len(feat)} 個（時刻・過去の値動き・他銘柄・H1/H4/D1 のテクニカル指標）", ""]
    wf = {t: [] for t in thrs}
    for yr in (2019, 2020, 2021):
        tr = df.index < pd.Timestamp(f"{yr}-01-01")
        te = (df.index >= pd.Timestamp(f"{yr}-01-01")) & (df.index < pd.Timestamp(f"{yr + 1}-01-01")) & step
        mdl = M.make_model(kind).fit(df.loc[tr, feat].values, y[tr].values)
        p = mdl.predict(df.loc[te, feat].values)
        for t in thrs:
            s, _ = ev(p, df[te], t)
            wf[t].append(s)
            out.append(f"- {yr} しきい値 {t}: {fmt(s)}")
    best = None
    for t in thrs:
        if all(s["mean"] > 0 and s["n"] >= 30 for s in wf[t]):
            sc = sum(s["t"] for s in wf[t])
            if best is None or sc > best[1]:
                best = (t, sc)
    out.append("")
    if best is None:
        out.append("**ウォークフォワードの3年すべてでコスト込みプラスになるしきい値はありませんでした（不合格）。**")
        return "\n".join(out)
    thr = best[0]
    des = D.period_mask(df.index, D.DESIGN)
    val = D.period_mask(df.index, D.VALID) & step
    mdl = M.make_model(kind).fit(df.loc[des, feat].values, y[des].values)
    p = mdl.predict(df.loc[val, feat].values)
    s, m = ev(p, df[val], thr)
    ok = s["mean"] > 0 and s["pf"] >= 1.10 and s["n"] >= 100
    out += [f"→ しきい値 {thr} を採用", "", f"### 検証期間：{fmt(s)} → **{'合格' if ok else '不合格'}**", ""]
    dv = df[val]
    side = np.where(p >= thr, 1.0, np.where(p <= -thr, -1.0, 0.0))
    for pair in M.CROSS:
        mm = (dv["_pair"].values == pair) & (side != 0)
        out.append(f"- {pair}: {fmt(stat(side[mm] * dv['_ret'].values[mm] - dv['_cost'].values[mm]))}")
    if kind == "lgbm":
        imp = sorted(zip(mdl.feature_importances_, feat), reverse=True)[:12]
        out += ["", "重要な特徴量（上位12）：" + "、".join(n for _, n in imp)]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- filter
# 単純なフィルターの候補（少数に決め打ち。多く試すほど偶然の当たりが増えるため）
# 値 = (列, 向き)：向き +1 は「指標 × 取引の向き > 0 のときだけ入る」（順張り）、-1 は逆（逆張り）
SIMPLE = {
    "日足EMA50の傾きと同じ向き": ("d1_ema50_s", +1),
    "日足EMA200より取引の向き側": ("d1_ema200_d", +1),
    "4時間足MACDと同じ向き": ("h4_macd", +1),
    "4時間足の一目の雲と同じ向き": ("h4_kumo", +1),
    "1時間足RSIの逆張り": ("h1_rsi", -1),
    "1時間足ボリンジャーの逆張り": ("h1_bb_pb", -1),
    "当日の始値からの動きの逆張り": ("day_from_open", -1),
    "前日の高安の中の位置の逆張り": ("pd_pos", -1),
}


def rule_filter(pair, clock, hour, hold, sign) -> str:
    base = D.bars(pair, "1h")
    X = feats(pair)
    r = pd.Series(S.window_returns(base, hold, D.pip_size(pair)), index=base.index) * sign
    excl = pd.Series(S.rollover_mask(base, hold), index=base.index)
    cost = S.COST[pair]
    m = (base[f"{clock}_h"] == hour) & r.notna() & ~excl
    X, r = X[m], r[m] - cost
    des = D.period_mask(X.index, D.DESIGN)
    val = D.period_mask(X.index, D.VALID)
    yrs = [(X.index >= pd.Timestamp(f"{y}-01-01")) & (X.index < pd.Timestamp(f"{y + 1}-01-01")) for y in (2019, 2020, 2021)]
    out = [f"## テクニカル指標のフィルター：{pair} {clock} {hour}:00 {hold}時間 {'買い' if sign > 0 else '売り'}（コスト込み）", "",
           f"- フィルターなし：設計 {fmt(stat(r[des]))} ／ 検証 {fmt(stat(r[val]))}", "",
           "### (a) 単純なフィルター（候補は先に決めた8個）", "",
           "| フィルター | 設計 | 2019 | 2020 | 2021 | 検証 |", "|---|---|---|---|---|---|"]
    for name, (col, d) in SIMPLE.items():
        keep = (X[col] * sign * d > 0).fillna(False)
        cells = [fmt(stat(r[des & keep]))] + [f"{stat(r[y & keep])['mean']:+.2f}" for y in yrs] + [fmt(stat(r[val & keep]))]
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    # (b) メタラベリング（LightGBM 分類）
    import lightgbm as lgb
    feat = [c for c in X.columns if X[c].notna().mean() > 0.95]
    ok = X[feat].notna().all(axis=1)
    Xf, rf = X.loc[ok, feat], r[ok]
    y = (rf > 0).astype(int)

    def mdl():
        return lgb.LGBMClassifier(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=40,
                                  subsample=0.8, subsample_freq=1, colsample_bytree=0.5, reg_lambda=5.0,
                                  random_state=0, verbose=-1)
    out += ["", "### (b) LightGBM で「勝つ取引か」を予測し、予測の下位を見送る（メタラベリング）", ""]
    for q in (0.3, 0.5):
        res = []
        for yr in (2019, 2020, 2021):
            tr = Xf.index < pd.Timestamp(f"{yr}-01-01")
            te = (Xf.index >= pd.Timestamp(f"{yr}-01-01")) & (Xf.index < pd.Timestamp(f"{yr + 1}-01-01"))
            mm = mdl().fit(Xf[tr].values, y[tr].values)
            thr = np.quantile(mm.predict_proba(Xf[tr].values)[:, 1], q)
            res.append(rf[te].values[mm.predict_proba(Xf[te].values)[:, 1] > thr])
        d = D.period_mask(Xf.index, D.DESIGN)
        v = D.period_mask(Xf.index, D.VALID)
        mm = mdl().fit(Xf[d].values, y[d].values)
        thr = np.quantile(mm.predict_proba(Xf[d].values)[:, 1], q)
        pv = rf[v].values[mm.predict_proba(Xf[v].values)[:, 1] > thr]
        out.append(f"- 下位{int(q * 100)}%見送り：設計WF {fmt(stat(np.concatenate(res)))} ／ 検証 {fmt(stat(pv))}")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "pooled":
        hold = int(sys.argv[2])
        kind = sys.argv[3] if len(sys.argv) > 3 else "lgbm"
        text = pooled(hold, kind)
        name = f"ml_ta_pooled_h{hold}_{kind}.md"
    else:
        pair, clock, hour, hold, sign = sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
        text = rule_filter(pair, clock, hour, hold, sign)
        name = f"ta_filter_{pair}_{clock}{hour}_h{hold}.md"
    print(text)
    open(os.path.join(D.ROOT, "reports", "research", name), "w", encoding="utf-8").write(text)

#!/usr/bin/env python3
"""今の10ルールの全取引を1つにまとめ、「この取引はコスト後に勝てるか」を入る前の情報だけで予想するモデル（メタモデル）。
予想が悪い取引だけを見送ると、成績が上がるかを確かめる。

- 取引：sl_width.py と同じ作り方（1分足、今の損切り・途中の見直し・早めの決済、コスト +0.5 pips）。
- 損益は「建玉の額に対する %」（pips × pip ÷ 価格 × 100）にそろえる。EA のロットは証拠金の上限で決まり、
  どのルールも建玉の額がほぼ同じなので、口座の損益はこの値にほぼ比例する。
- 特徴量（すべて入る時点で分かるもの）：ルールの種類、直前30分・2時間・24時間の値動き（取引の向きで符号をそろえ、1時間足の平均値幅で割る）、
  値動きの大きさ（直近24時間 ÷ 直近20日）、値動きの大きさ（pips）、曜日、日付、関係の深いもう1つのペアの直前30分の動き、
  そのルールの直近20回の成績（その時点までの取引だけ）。
- ウォークフォワード：各年について、その年より前の取引だけで学習し、その年の取引を予想する（2017年から）。未来の情報は使わない。
使い方: python3 tools/research/meta_model.py  → reports/research/meta_model.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
import sl_width as W  # noqa: E402

CROSS = {"USDJPY": "EURJPY", "EURJPY": "USDJPY", "GBPJPY": "USDJPY", "EURUSD": "USDJPY"}
PER = (("17-21", "2017-01-01", "2021-11-01"), ("前半", "2021-11-01", "2024-11-01"),
       ("後半", "2024-11-01", "2025-11-01"), ("直近1年", "2025-11-01", "2027-01-01"))
FEATS = ["rule_id", "pre30", "pre120", "pre24h", "volratio", "atr_pips", "dow", "dom", "cross30", "recent"]


def zmove(o5, atr, t, minutes, sign):
    p0 = o5.reindex(t).values
    p1 = o5.reindex(t - pd.Timedelta(minutes=minutes)).values
    return sign * (p0 - p1) / atr


def build():
    rows = []
    m1c, b5, h1c = {}, {}, {}
    for k, (name, pair, clock, hh, mm, hold, sign, filt, sl0, pre, cut, early) in enumerate(W.RULES):
        for p in (pair, CROSS[pair]):
            if p not in b5:
                b5[p] = D.bars(p, "5min")["o"]
                h1 = D.bars(p, "1h")
                rng = h1["h"] - h1["l"]
                h1c[p] = (rng.rolling(24, min_periods=12).mean(), rng.rolling(480, min_periods=200).mean())
        if pair not in m1c:
            m1c[pair] = pd.read_parquet(os.path.join(D.CACHE, f"{pair}_M1.parquet"))
        pip, cost = D.pip_size(pair), S.COST[pair] + 0.5
        t = W.entries(pair, clock, hh, mm, filt, pre, sign)
        r, _ = W.simulate(m1c[pair], t, hold, sign, sl0, cut, early, pip)
        last = t.floor("1h") - pd.Timedelta(hours=1)
        a24 = h1c[pair][0].reindex(last).values
        a480 = h1c[pair][1].reindex(last).values
        ca24 = h1c[CROSS[pair]][0].reindex(last).values
        o5 = b5[pair]
        price = o5.reindex(t).values
        df = pd.DataFrame({
            "rule": name, "rule_id": k, "pair": pair,
            "net_pips": r - cost,
            "ret": (r - cost) * pip / price * 100.0,
            "pre30": zmove(o5, a24, t, 30, sign),
            "pre120": zmove(o5, a24, t, 120, sign),
            "pre24h": zmove(o5, a24, t, 1440, sign),
            "volratio": a24 / a480,
            "atr_pips": a24 / pip,
            "dow": t.dayofweek, "dom": t.day,
            "cross30": zmove(b5[CROSS[pair]], ca24, t, 30, sign),
        }, index=t)
        df = df.dropna(subset=["net_pips", "ret"])
        # そのルールの直近20回の平均（その取引より前の取引だけ）
        df["recent"] = df["ret"].shift(1).rolling(20, min_periods=5).mean()
        rows.append(df)
        print(f"{name}: {len(df)} 回", flush=True)
    return pd.concat(rows).sort_index()


def walk_forward(df, model_kind):
    import lightgbm as lgb
    from sklearn.linear_model import Ridge
    pred = pd.Series(np.nan, index=range(len(df)))
    thr_q = pd.Series(np.nan, index=range(len(df)))
    X = df[FEATS].copy()
    X = X.fillna(X.median(numeric_only=True))
    y = df["ret"].values
    years = df.index.year.values
    for yr in range(2017, 2027):
        tr, te = years < yr, years == yr
        if te.sum() == 0:
            continue
        if model_kind == "lgbm":
            m = lgb.LGBMRegressor(n_estimators=150, learning_rate=0.03, num_leaves=7, min_child_samples=80,
                                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, verbose=-1)
            m.fit(X[tr], y[tr], categorical_feature=["rule_id"])
            p_tr, p_te = m.predict(X[tr]), m.predict(X[te])
        else:
            Xd = pd.get_dummies(X, columns=["rule_id"], dtype=float)
            mu, sd = Xd[tr].mean(), Xd[tr].std().replace(0, 1)
            Z = (Xd - mu) / sd
            m = Ridge(alpha=50.0).fit(Z[tr], y[tr])
            p_tr, p_te = m.predict(Z[tr]), m.predict(Z[te])
        pred[np.where(te)[0]] = p_te
        thr_q[np.where(te)[0]] = np.quantile(p_tr, 0.2)   # 学習期間の予想の下位20%の境目
    return pred.values, thr_q.values


def summarize(df, take, label):
    cells = []
    for _, a, b in PER:
        m = (df.index >= a) & (df.index < b)
        allr, tk = df["ret"][m], df["ret"][m & take]
        cells.append(f"{tk.sum():+.1f}（{allr.sum():+.1f}、見送り {100 * (1 - (m & take).sum() / max(m.sum(), 1)):.0f}%）")
    yrs = df[take & (df.index >= "2017")].groupby(df[take & (df.index >= "2017")].index.year)["ret"].sum()
    return f"| {label} | " + " | ".join(cells) + f" | {(yrs > 0).sum()}/{len(yrs)} |"


def main():
    df = build()
    lines = ["# 10ルールの取引を予想して選ぶモデル（メタモデル、ウォークフォワード）", "",
             f"取引 {len(df)} 回（2015〜2026年）。各セル：選んだ取引の損益の合計（建玉の額に対する %、括弧内はすべて取った場合と見送った割合）。", "",
             "| 選び方 | " + " | ".join(p[0] for p in PER) + " | プラスの年（2017〜） |", "|---|" + "---|" * (len(PER) + 1)]
    base = np.ones(len(df), bool)
    lines.append(summarize(df, base, "すべて取る（今）"))
    # 比べるための単純な形：そのルールの直近20回がマイナスなら見送る
    lines.append(summarize(df, ~(df["recent"] < 0).values, "直近20回がマイナスのルールは見送る"))
    for kind in ("ridge", "lgbm"):
        p, q = walk_forward(df, kind)
        ok = ~np.isnan(p)
        lines.append(summarize(df, ~(ok & (p < 0)), f"{kind}：予想がマイナスなら見送る"))
        lines.append(summarize(df, ~(ok & (p < q)), f"{kind}：予想が下位20%なら見送る"))
        df[f"pred_{kind}"] = p
    # 予想の5分位ごとの実際の成績（2017年以降、予想の良し悪しが実際と合っているか）
    lines += ["", "## 予想の高さごとの実際の成績（2017年以降、1回あたりの % ×100）", ""]
    for kind in ("ridge", "lgbm"):
        d = df[df.index >= "2017"].dropna(subset=[f"pred_{kind}"])
        qb = pd.qcut(d[f"pred_{kind}"].rank(method="first"), 5, labels=False)
        cells = []
        for b in range(5):
            x = d["ret"][qb == b]
            cells.append(f"{x.mean() * 100:+.2f}（{len(x)}）")
        lines.append(f"- {kind}：低い → 高い：" + "、".join(cells))
    out = os.path.join(W.ROOT, "reports", "research", "meta_model.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    df.to_parquet(os.path.join(D.CACHE, "meta_trades.parquet"))
    print("\n".join(lines))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""時刻・曜日・日付を使わない、日をまたいで持つ方法の試算（ユーザーの指示：特定の日・時間帯のクセを使わず、パターン・分析・予想モデルで稼ぐ）。

- 17ペアの日足（ニューヨーク 17:00 の値。為替の1日の区切り）を使う。
- 各方法は、その日までの値動きだけで、次の日以降の建玉（ペアごとの重み）を決める。重みは、値動きの大きさ（直近60日）で割って、
  どのペアもリスクがそろうようにし、合計の大きさ（全ペアの |重み| の合計）が 1 になるようにそろえる。
- 損益は「建玉の額に対する %」。建玉を変えたときにスプレッド（S.COST + 0.5 pips）を払い、持っているあいだはスワップ
  （政策金利の差 − 業者の上乗せ 年1%）を受け取る／払う。
- 方法：トレンド（過去 L 日の向き）、通貨の強弱（過去 L 日の上げ幅の順位で上位を買い・下位を売り）、金利差、金利差＋トレンド、
  短い期間の行き過ぎの戻り、予想モデル（リッジ回帰・LightGBM、ウォークフォワード：毎年その年より前のデータだけで学習）。
- 結果は期間ごとの年率（建玉の合計が口座の1倍のとき）と、年率シャープ。
使い方: python3 tools/research/daily_strats.py  → reports/research/daily_strats.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
from multiday_scan import RATES, MARKUP  # noqa: E402

PAIRS = ["USDJPY", "EURUSD", "EURJPY", "GBPJPY", "AUDJPY", "GBPUSD", "AUDCAD", "AUDNZD", "AUDUSD", "CADJPY",
         "CHFJPY", "EURGBP", "NZDCAD", "NZDJPY", "NZDUSD", "USDCAD", "USDCHF"]
PER = (("2015〜21年", "2015-01-01", "2021-11-01"), ("21/11〜24/10", "2021-11-01", "2024-11-01"),
       ("24/11〜25/10", "2024-11-01", "2025-11-01"), ("25/11〜26/10", "2025-11-01", "2026-11-14"))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def daily_prices():
    out = {}
    for p in PAIRS:
        h = D.bars(p, "1h")
        m = h["ny_h"].values == 17
        s = h.loc[m, "o"]
        s.index = pd.DatetimeIndex(s.index).normalize()
        out[p] = s[~s.index.duplicated()]
    px = pd.DataFrame(out).sort_index()
    px = px[px.index.dayofweek < 5].ffill(limit=2)
    return px


def carry_table(px):
    """ペアを買ったときの金利差（年 %、上乗せ前）。"""
    yrs = px.index.year
    c = {}
    for p in PAIRS:
        b, q = p[:3], p[3:]
        c[p] = np.array([RATES[b].get(y, RATES[b][2026]) - RATES[q].get(y, RATES[q][2026]) for y in yrs])
    return pd.DataFrame(c, index=px.index)


def evaluate(w, px, ret, carry, cost_frac, label, rebalance=1):
    """w: 各日の終わりに決めた重み（翌日から持つ）。rebalance 日ごとにだけ入れ替える。"""
    w = w.reindex(px.index).fillna(0.0)
    if rebalance > 1:
        keep = np.zeros(len(w), bool)
        keep[::rebalance] = True
        w = w.where(pd.Series(keep, index=w.index), np.nan).ffill().fillna(0.0)
    # 合計の大きさを 1 に
    g = w.abs().sum(axis=1).replace(0, np.nan)
    w = w.div(g, axis=0).fillna(0.0)
    held = w                                   # その日の終わりに決めた建玉で、翌日の値動き（ret はすでに1日先）を受ける
    pnl = (held * ret).sum(axis=1)
    sw = (held * (carry - np.sign(held) * MARKUP) / 100.0 / 261.0).sum(axis=1)
    tc = ((w - w.shift(1).fillna(0.0)).abs() * cost_frac).sum(axis=1)
    tot = (pnl + sw - tc) * 100.0   # %
    cells = []
    for _, a, b in PER:
        x = tot[(tot.index >= a) & (tot.index < b)]
        if len(x) < 50:
            cells.append("—")
            continue
        ann = x.mean() * 261
        sh = x.mean() / x.std() * np.sqrt(261) if x.std() > 0 else 0
        cells.append(f"{ann:+.1f}%（{sh:+.2f}）")
    turnover = (w - w.shift(1)).abs().sum(axis=1).mean() * 261
    return f"| {label} | " + " | ".join(cells) + f" | {turnover:.0f} |", tot


def main():
    px = daily_prices()
    ret = px.pct_change().shift(-1)            # 翌日の値動き（その日の終わりに持った建玉に効く）
    ret_past = px.pct_change()
    vol = ret_past.rolling(60, min_periods=40).std()
    carry = carry_table(px)
    cost_frac = pd.DataFrame({p: (S.COST.get(p, 2.0) + 0.5) * D.pip_size(p) / px[p] for p in PAIRS})
    ivol = 1.0 / vol
    rows = []
    lines = ["# 時刻・曜日・日付を使わない、日をまたいで持つ方法（日足、17ペア、コストとスワップ込み）", "",
             "各セル：年率（全ペアの建玉の合計が口座の1倍のとき）と、括弧内は年率シャープ。最後の列は年間の売買の回転（建玉の何倍を入れ替えたか）。",
             "レバレッジを k 倍にすると年率もほぼ k 倍（シャープは同じ）。シャープが 0.5 未満は、手数料やずれで消える程度の弱さ。", "",
             "| 方法 | " + " | ".join(p[0] for p in PER) + " | 回転 |", "|---|" + "---|" * (len(PER) + 1)]
    # 1. トレンド
    for L in (20, 60, 120, 250):
        sig = np.sign(px / px.shift(L) - 1.0)
        for rb in (1, 5):
            r, _ = evaluate(sig * ivol, px, ret, carry, cost_frac, f"トレンド {L}日（{'毎日' if rb == 1 else '週1回'}入れ替え）", rb)
            lines.append(r)
    # 2. 通貨の強弱（上げ幅の順位）
    for L in (20, 60, 120):
        mom = (px / px.shift(L) - 1.0) / (vol * np.sqrt(L))
        rk = mom.rank(axis=1)
        n = rk.notna().sum(axis=1)
        sig = (rk.ge(n - 2, axis=0).astype(float) - rk.le(3, axis=0).astype(float))
        r, _ = evaluate(sig * ivol, px, ret, carry, cost_frac, f"強弱の順位 {L}日（上位3買い・下位3売り、週1回）", 5)
        lines.append(r)
    # 3. 金利差
    sig = np.sign(carry).where(carry.abs() >= 1.0, 0.0)
    r, _ = evaluate(sig * ivol, px, ret, carry, cost_frac, "金利差（差が年1%以上のペアで高金利側を買い、週1回）", 5)
    lines.append(r)
    for L in (60, 120):
        tr = np.sign(px / px.shift(L) - 1.0)
        s2 = sig.where(np.sign(sig) == tr, 0.0)
        r, _ = evaluate(s2 * ivol, px, ret, carry, cost_frac, f"金利差＋トレンド {L}日が同じ向きのときだけ（週1回）", 5)
        lines.append(r)
    # 4. 短い期間の行き過ぎの戻り
    for L in (1, 3, 5):
        z = (px / px.shift(L) - 1.0) / (vol * np.sqrt(L))
        sig = -np.sign(z).where(z.abs() >= 1.5, 0.0)
        r, _ = evaluate(sig * ivol, px, ret, carry, cost_frac, f"行き過ぎの戻り（{L}日で1.5σ以上動いたら逆、毎日）", 1)
        lines.append(r)
    # 5. 予想モデル（ウォークフォワード）
    feats = {}
    for L in (1, 5, 20, 60, 120, 250):
        feats[f"r{L}"] = (px / px.shift(L) - 1.0) / (vol * np.sqrt(L))
    feats["volratio"] = ret_past.rolling(20, min_periods=15).std() / vol
    feats["carry"] = carry
    for L in (20, 60):
        m = (px / px.shift(L) - 1.0) / (vol * np.sqrt(L))
        feats[f"xs{L}"] = m.rank(axis=1, pct=True)
    H = 5
    target = (px.shift(-H) / px - 1.0) / (vol * np.sqrt(H))
    long = []
    for p in PAIRS:
        df = pd.DataFrame({k: v[p] for k, v in feats.items()})
        df["y"] = target[p]
        df["pair"] = p
        df["date"] = px.index
        long.append(df)
    data = pd.concat(long).dropna(subset=list(feats.keys()))
    import lightgbm as lgb
    from sklearn.linear_model import Ridge
    fcols = list(feats.keys())
    for kind in ("ridge", "lgbm"):
        pred = pd.Series(np.nan, index=data.index)
        preds = []
        for yr in range(2017, 2027):
            tr = (data["date"] < pd.Timestamp(f"{yr}-01-01") - pd.Timedelta(days=10)) & data["y"].notna()
            te = (data["date"].dt.year == yr)
            if te.sum() == 0:
                continue
            X, y = data.loc[tr, fcols].values, data.loc[tr, "y"].clip(-4, 4).values
            if kind == "ridge":
                mu, sd = X.mean(0), X.std(0) + 1e-9
                m = Ridge(alpha=100.0).fit((X - mu) / sd, y)
                p_te = m.predict((data.loc[te, fcols].values - mu) / sd)
            else:
                m = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.03, num_leaves=15, min_child_samples=200,
                                      subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=10.0, verbose=-1).fit(X, y)
                p_te = m.predict(data.loc[te, fcols].values)
            preds.append(pd.DataFrame({"date": data.loc[te, "date"].values, "pair": data.loc[te, "pair"].values, "p": p_te}))
        pr = pd.concat(preds).pivot(index="date", columns="pair", values="p").reindex(px.index)
        for thr in (0.0, 0.1):
            sig = np.sign(pr).where(pr.abs() > thr, 0.0)
            r, _ = evaluate(sig * ivol, px, ret, carry, cost_frac, f"予想モデル {kind}（5日先、予想の大きさ>{thr}、週1回）", 5)
            lines.append(r)
    out = os.path.join(ROOT, "reports", "research", "daily_strats.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

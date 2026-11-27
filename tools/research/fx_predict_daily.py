#!/usr/bin/env python3
"""研究（FX だけで取引する）：株・金利・商品・為替そのものの値動きから、翌日（または翌5日）の為替を予想できるか。

- 個別の思いつきを1つずつ試す代わりに、「公開されている日次の情報で、翌日の為替が少しでも予想できるか」をまとめて確かめる。
  予想できるなら、取引は為替だけで、日付・曜日に頼らない「予想モデル」になる。予想できないなら、そう分かる。
- 対象：7通貨（JPY・EUR・GBP・AUD・NZD・CAD・CHF）の、対米ドルの値動き。値段は1分足の NY 16:30 の値（2010年〜2026年10月）。
  16:30 にしたのは、その日の米国株の終値（16:00）・金利・商品の値がすべて出たあとで、スプレッドがふつうの時間だから（時刻そのものを売買の理由にはしない）。
- 説明に使う値（すべて、その日の 16:30 までに分かるもの）：
  S&P500 の1日・5日の値動き、売られすぎの度合い（IBS・RSI(2)）、VIX の水準と1日・5日の変化、米国の2年・10年の金利の1日・5日の変化、
  原油・金・銅の1日・5日の値動き（前日まで。終値が NY 17:00 で、16:30 より後のため）、日経225・DAX の1日の値動き、米ドル全体の1日・5日の値動き、
  その通貨の1日・5日・20日の値動き、金利差（月次、1か月遅れ）。
- モデル：通貨ごとの線形の回帰（リッジ回帰）。**過去のデータだけで学習し、次の年を予想する**ことを、年ごとに繰り返す（最初の5年は学習だけ）。
  罰則の強さは、学習データの中だけで決める。
- 物差し：予想と実際の相関（見ていない期間）、予想に比例して持ったときの年率シャープ（コスト前・コスト後）、t 値。
使い方: python3 tools/research/fx_predict_daily.py  → reports/research/fx_predict_daily.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_reversion_cfd as IC  # noqa: E402
import fx_equity_signal_m1 as FM  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
CCY = {"JPY": ("USDJPY", -1), "EUR": ("EURUSD", 1), "GBP": ("GBPUSD", 1), "AUD": ("AUDUSD", 1), "NZD": ("NZDUSD", 1), "CAD": ("USDCAD", -1), "CHF": ("USDCHF", -1)}
LAMBDAS = (1.0, 10.0, 100.0, 1000.0)
FIRST_OOS = 2016


def fx_panel():
    """7通貨の、対米ドルの値（1通貨 = 何米ドル）。NY 16:30 の値、NY の日付。"""
    cache = os.path.join(D.CACHE, "fx_1630_usd.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    out = {}
    for c, (pair, sgn) in CCY.items():
        p = FM.price_at(IC.load_any(pair), 16, 30)
        out[c] = p if sgn > 0 else 1.0 / p
    df = pd.DataFrame(out).dropna(how="all")
    df.to_parquet(cache)
    return df


def features(fx):
    idx = fx.index
    g = pd.DataFrame(index=idx)

    def al(s):
        return s.reindex(s.index.union(idx)).ffill(limit=3).reindex(idx)
    spx = Y.fetch("SPX")
    c = spx["close"]
    g["eq1"] = al(np.log(c).diff())
    g["eq5"] = al(np.log(c).diff(5))
    rng = spx["high"] - spx["low"]
    g["eq_ibs"] = al(((c - spx["low"]) / rng.where(rng > 0)).fillna(0.5)) - 0.5
    g["eq_rsi2"] = al(IR.rsi_wilder(c, 2)) / 100.0 - 0.5
    vix = np.log(Y.fetch("VIX")["close"])
    g["vix"] = al(vix - vix.rolling(250).mean())
    g["dvix1"] = al(vix.diff())
    g["dvix5"] = al(vix.diff(5))
    for sid, k in (("DGS2", "y2"), ("DGS10", "y10")):
        y = F.fetch(sid).dropna()
        g[f"d{k}_1"] = al(y.diff())
        g[f"d{k}_5"] = al(y.diff(5))
    for nm, k in (("CL", "oil"), ("GC", "gold"), ("HG", "cop")):
        # 商品の先物の日足の終値は NY 17:00 で、為替の売買の時刻（16:30）より後。その日の値を使うと、30分ぶん先の情報が混ざる
        # （最初はその日の値を使っていて、非線形のモデルで「予想できている」ように見えた。前日の値に直すと消えた）。前日までの値を使う。
        p = np.log(Y.fetch(nm)["close"].where(lambda x: x > 0)).shift(1)
        g[f"{k}1"] = al(p.diff()).clip(-0.15, 0.15)
        g[f"{k}5"] = al(p.diff(5)).clip(-0.3, 0.3)
    for nm, k in (("N225", "nk"), ("DAX", "dax")):
        p = np.log(Y.fetch(nm)["close"])
        g[f"{k}1"] = al(p.diff())
    lr = np.log(fx).diff()
    g["usd1"] = -lr.mean(axis=1)
    g["usd5"] = -np.log(fx).diff(5).mean(axis=1)
    rate = F.monthly_to_daily(F.rates_monthly(), idx)
    own = {}
    for cc in fx.columns:
        o = pd.DataFrame(index=idx)
        o["own1"] = lr[cc]
        o["own5"] = np.log(fx[cc]).diff(5)
        o["own20"] = np.log(fx[cc]).diff(20)
        o["carry"] = (rate[cc] - rate["USD"]) / 100.0
        own[cc] = o
    return g, own


def ridge_fit(X, y, lam):
    A = X.T @ X + lam * np.eye(X.shape[1])
    return np.linalg.solve(A, X.T @ y)


def walk_forward(X, y, years):
    """年ごとに、前の年までのデータで学習して、その年を予想する。X・y は同じ並び（日付）。戻り値：予想（見ていない期間だけ）。"""
    pred = pd.Series(np.nan, index=y.index)
    for yr in years:
        tr = (y.index.year < yr) & y.notna() & X.notna().all(axis=1)
        te = (y.index.year == yr) & X.notna().all(axis=1)
        if tr.sum() < 500 or te.sum() == 0:
            continue
        Xtr, ytr = X[tr].values, y[tr].values
        mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0)
        sd[sd == 0] = 1.0
        Z = (Xtr - mu) / sd
        ym = ytr.mean()
        # 罰則の強さ：学習データの最後の2割を使って決める（それより前で学習）
        cut = int(len(Z) * 0.8)
        best, best_l = -np.inf, LAMBDAS[-1]
        for lam in LAMBDAS:
            b = ridge_fit(Z[:cut], ytr[:cut] - ytr[:cut].mean(), lam * cut / 1000.0)
            p = Z[cut:] @ b
            sc = np.corrcoef(p, ytr[cut:])[0, 1] if p.std() > 0 else -1
            if sc > best:
                best, best_l = sc, lam
        b = ridge_fit(Z, ytr - ym, best_l * len(Z) / 1000.0)
        pred[te] = ((X[te].values - mu) / sd) @ b + ym
    return pred


def evaluate(pred, y, vol, cost, label, horizon):
    """予想 pred に比例して持つ（通貨ごとに 予想 ÷ 分散）。horizon 日先を予想するときは、建玉を horizon 日で均す。"""
    ok = pred.notna().all(axis=1) & y.notna().all(axis=1) & RET1.notna().all(axis=1)
    p, r = pred[ok], y[ok]
    cost = cost.reindex(p.index)
    ic = np.corrcoef(p.values.ravel(), r.values.ravel())[0, 1]
    n = p.size
    w = (p / (vol[ok] ** 2))
    if horizon > 1:
        w = w.rolling(horizon, min_periods=1).mean()
    w = w.div(w.abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)          # 建玉の合計を 1 に
    r1 = RET1.reindex(w.index)
    gross = (w * r1).sum(axis=1)
    tc = ((w - w.shift(1).fillna(0.0)).abs() * cost).sum(axis=1)
    net = gross - tc
    sg, sn = gross.mean() / gross.std() * np.sqrt(ANN), net.mean() / net.std() * np.sqrt(ANN)
    yrs = len(net) / ANN
    by = net.groupby(net.index.year).sum()
    turn = (w - w.shift(1).fillna(0.0)).abs().sum(axis=1).mean()
    return (f"| {label} | {ic:+.4f}（{n} 件） | {sg:+.2f} | {sn:+.2f} | {sn * np.sqrt(yrs):+.1f} | {turn * 100:.0f}% | {(by > 0).sum()}/{len(by)} |", net)


def main():
    global RET1
    fx = fx_panel()
    fx = fx[fx.index >= "2010-06-01"]
    g, own = features(fx)
    lr = np.log(fx).diff()
    RET1 = lr.shift(-1)                                  # 翌日の値動き（16:30 → 次の日の 16:30）
    vol = lr.rolling(60, min_periods=40).std()
    cost = pd.Series({c: (S.COST.get(CCY[c][0], 2.0) + 0.5) * D.pip_size(CCY[c][0]) for c in fx.columns})
    px_pair = pd.DataFrame({c: (fx[c] if CCY[c][1] > 0 else 1.0 / fx[c]) for c in fx.columns})
    cost_frac = (cost / px_pair).reindex(fx.index)        # 売買1回のコスト（値段に対する割合）
    years = list(range(FIRST_OOS, 2027))
    lines = ["# 研究：公開されている日次の情報から、翌日の為替を予想できるか（取引は為替だけ。`tools/research/fx_predict_daily.py`）", "",
             f"7通貨の対米ドルの値動き（NY 16:30 の値、{fx.index[0].date()}〜{fx.index[-1].date()}）。過去のデータだけで学習し、次の年を予想する（{FIRST_OOS}年〜が、見ていない期間）。",
             "「予想と実際の相関」は、見ていない期間の、7通貨をまとめた値（0 なら予想できていない。±0.012 以内は、偶然の範囲）。",
             "シャープは、予想に比例して持ったとき（建玉の合計を口座の100%にそろえる）。", "",
             "| 予想に使う情報・予想する先 | 予想と実際の相関 | シャープ（コスト前） | シャープ（コスト後） | t 値（コスト後） | 1日に入れ替える割合 | プラスの年 |",
             "|---|---|---|---|---|---|---|"]
    sets = (("すべて", list(g.columns), True), ("株・VIX だけ", ["eq1", "eq5", "eq_ibs", "eq_rsi2", "vix", "dvix1", "dvix5"], False),
            ("金利だけ", ["dy2_1", "dy2_5", "dy10_1", "dy10_5"], False), ("商品だけ", ["oil1", "oil5", "gold1", "gold5", "cop1", "cop5"], False),
            ("為替そのものだけ（その通貨の値動きと金利差、米ドル全体）", ["usd1", "usd5"], True))
    keep = {}
    for horizon in (1, 5):
        yt = lr.shift(-1) if horizon == 1 else (np.log(fx).shift(-horizon) - np.log(fx)) / horizon
        for name, cols, use_own in sets:
            pred = pd.DataFrame(index=fx.index, columns=fx.columns, dtype=float)
            for c in fx.columns:
                X = g[cols].copy()
                if use_own:
                    X = pd.concat([X, own[c]], axis=1)
                pred[c] = walk_forward(X, yt[c], years)
            line, net = evaluate(pred, yt, vol, cost_frac, f"{name}・翌{'日' if horizon == 1 else '5日'}", horizon)
            lines.append(line)
            keep[(name, horizon)] = net
            print(line, flush=True)
    # 参考：予想を使わない、同じ期間の単純な形
    lines += ["", "## 比べる相手（同じ期間、同じコスト）", "",
              "| 形 | シャープ（コスト後） |", "|---|---|"]
    rate = F.monthly_to_daily(F.rates_monthly(), fx.index)
    cw = pd.DataFrame({c: np.sign(rate[c] - rate["USD"]) / vol[c] for c in fx.columns})
    cw = cw.div(cw.abs().sum(axis=1), axis=0).fillna(0.0)
    cw = cw[cw.index.year >= FIRST_OOS]
    cr = (cw * (RET1.reindex(cw.index) + (rate[fx.columns].sub(rate["USD"], axis=0).reindex(cw.index)) / 100.0 / 261.0)).sum(axis=1) \
        - ((cw - cw.shift(1).fillna(0.0)).abs() * cost_frac.reindex(cw.index)).sum(axis=1)
    lines.append(f"| 金利の高い側を持つ（7通貨 対 米ドル、スワップ込み・上乗せなし） | {cr.mean() / cr.std() * np.sqrt(ANN):+.2f} |")
    out = os.path.join(F.ROOT, "reports", "research", "fx_predict_daily.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[-4:]))


if __name__ == "__main__":
    main()

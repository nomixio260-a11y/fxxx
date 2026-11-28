"""下調べ：10 の商品で、売られすぎの戻りのルールを試す（107章 5）。引数：商品の口座の書き出しのフォルダ。
事前に基準を決めた正式な検証ではない（結果は不採用。数字は reports/experiments.md の 107章）。日付・時刻は使わない。"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np, pandas as pd
import index_others as IO, index_reversion as IR, index_stop as IS
ANN = 252
data, props = IO.load(sys.argv[1])
W = {0: 0.0, 1: 0.25, 2: 0.5, 3: 1.0}
sh = lambda x: x.mean() / x.std() * np.sqrt(ANN) if x.std() > 0 else np.nan
tv = lambda x: x.mean() / x.std() * np.sqrt(len(x)) if x.std() > 0 else np.nan
print("銘柄 | 期間 | コスト前（スプレッドだけ引く）：シャープ・t 値 | 前半 | 後半 | ルールごとの t 値（R2・D7・IBS） | 売り側（鏡の形）の t 値")
for sym in ("XAUUSD", "XAGUSD", "COPPER", "USOIL", "UKOIL", "NATGAS", "CORN", "WHEAT", "SOYBEANS", "SUGAR"):
    d = data[sym].copy()
    st = IR.rules(d); sg = IS.har_sigma(d)
    spread = float(props.loc[sym, "spread_points"]) * float(props.loc[sym, "point"]) / float(props.loc[sym, "bid"])
    c = d["close"]; ret = c.pct_change().shift(-1)                # 終値で決めて、次の終値まで（始値は使わない）
    def pnl(pos):
        w = (pos * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
        return (w * ret - (w - w.shift(1).fillna(0.0)).abs() * spread / 2.0).dropna().iloc[320:]
    n = (st["R2<10"] + st["D7"] + st["IBS"]).map(lambda v: W[int(round(v))])
    r = pnl(n); mid = r.index[len(r) // 2]
    ts = [tv(pnl(st[k])) for k in ("R2<10", "D7", "IBS")]
    # 売り側：200日の平均より下で RSI(2)>90 → 売り、5日の平均を下回ったら手じまい／IBS>0.8 → 売り
    up = c < c.rolling(200).mean(); r2 = IR.rsi_wilder(c, 2)
    ps = IR.positions(up & (r2 > 90), c < c.rolling(5).mean())
    rng = (d["high"] - d["low"]); ibs = ((c - d["low"]) / rng.where(rng > 0)).fillna(0.5)
    short = -(ps + (ibs > 0.8).astype(float)) / 2.0
    print(f"{sym:9s} | {r.index[0].date()}〜{r.index[-1].date()} | {sh(r):+.2f}・{tv(r):+.1f} | {sh(r[r.index <= mid]):+.2f} | {sh(r[r.index > mid]):+.2f} | {ts[0]:+.1f}・{ts[1]:+.1f}・{ts[2]:+.1f} | {tv(pnl(short)):+.1f}")

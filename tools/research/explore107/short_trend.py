"""下調べ：指数の売りの順張りを重ねた場合と、急落の損失の層ごとの内訳（107章 4）。
事前に基準を決めた正式な検証ではない（結果は不採用。数字は reports/experiments.md の 107章）。日付・時刻は使わない。"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np, pandas as pd
import index_trend_combo as ITC, target300 as T, index_vix_sizing as V, index_reversion as IR
ANN = 252
EP = (("2010年4〜7月", "2010-04-23", "2010-07-02"), ("2011年7〜10月", "2011-07-22", "2011-10-03"), ("2015年8月", "2015-08-17", "2015-08-25"), ("2018年1〜2月", "2018-01-26", "2018-02-08"), ("2018年9〜12月", "2018-09-20", "2018-12-24"),
      ("2020年2〜3月", "2020-02-19", "2020-03-23"), ("2022年1〜10月", "2022-01-03", "2022-10-12"), ("2024年7〜8月", "2024-07-16", "2024-08-05"), ("2025年2〜4月", "2025-02-19", "2025-04-08"))
def short_trend(name, unit, look=200, check=7, cost_div=True):
    d, n, sg, rate, div = V.load_sets("cash")[name]
    c = d["close"]; sma = c.rolling(look).mean()
    st = np.zeros(len(d)); last, cur = None, 0.0
    for i, t in enumerate(d.index):
        if i >= look and (last is None or (t - last).days >= check):
            cur, last = float(c.iloc[i] < sma.iloc[i]), t
        st[i] = cur
    w = (pd.Series(st, index=d.index) * unit / 100.0 / np.maximum(sg * np.sqrt(ANN), 0.025)).fillna(0.0)
    wh = w.shift(1).fillna(0.0)
    ret = c.pct_change().fillna(0.0)
    days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
    carry = wh * ((div if cost_div else 0.0) + 0.21) / 100.0 / 360.0 * days       # 売りは配当相当額と、売りのスワップ（年 0.21%）を払う
    cost = (wh - wh.shift(1).fillna(0.0)).abs() * IR.COST
    return (-wh * ret - carry - cost)
rev, tr = T.cash_returns(5.0), ITC.trend_returns("NASDAQ100", 10.0)
base = rev.add(tr, fill_value=0.0); base = base[base.index >= "2007-01-01"]
def show(lab, r):
    r = r[r.index >= "2007-01-01"]
    e = (1 + r).cumprod(); y = e.groupby(e.index.year).last(); y = y / np.concatenate([[1.0], y.values[:-1]]) - 1
    eps = sum(float(r[(r.index > a) & (r.index <= b)].sum()) for _, a, b in EP)
    print(f"{lab:44s} 年率 {(e.iloc[-1]**(252/len(r))-1)*100:+5.1f}% シャープ {r.mean()/r.std()*np.sqrt(ANN):+.2f} 下落 {(e/e.cummax()-1).min()*100:5.1f}% 最悪の年 {y.min()*100:+5.1f}% マイナスの年 {int((y<0).sum())} | 08:{y[2008]*100:+.0f} 18:{y[2018]*100:+.0f} 22:{y[2022]*100:+.0f} | 急落の合計 {eps*100:+.0f}%")
show("今の形（戻り 5% ＋ 順張り 10%）", base)
for nm in ("NASDAQ100", "S&P500"):
    for u in (5.0, 10.0, 20.0):
        s = short_trend(nm, u)
        show(f"＋ 売りの順張り {nm} {u:g}%（200日）", base.add(s, fill_value=0.0))
    s = short_trend(nm, 10.0); s = s[s.index >= "2007-01-01"]
    print(f"   売りの順張り {nm} 10% だけ：年率 {s.mean()*ANN*100:+.1f}% シャープ {s.mean()/s.std()*np.sqrt(ANN):+.2f} 層との相関 {pd.concat([base, s], axis=1).dropna().corr().iloc[0,1]:+.2f}")
for look in (50, 100):
    s = short_trend("NASDAQ100", 10.0, look=look)
    show(f"＋ 売りの順張り NASDAQ100 10%（{look}日）", base.add(s, fill_value=0.0))

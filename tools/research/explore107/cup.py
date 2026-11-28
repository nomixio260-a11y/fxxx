"""下調べ：大きく上げた日の次の日は見送る形（107章 3）。
事前に基準を決めた正式な検証ではない（結果は不採用。数字は reports/experiments.md の 107章）。日付・時刻は使わない。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np, pandas as pd
import index_reversion as IR, index_stop as IS, index_vix_sizing as V, yahoo_data as Y
ANN = 252
W = {0: 0.0, 1: 0.25, 2: 0.5, 3: 1.0}
EP = (("2010", "2010-04-23", "2010-07-02"), ("2011", "2011-07-22", "2011-10-03"), ("2015", "2015-08-17", "2015-08-25"), ("2018a", "2018-01-26", "2018-02-08"), ("2018b", "2018-09-20", "2018-12-24"),
      ("2020", "2020-02-19", "2020-03-23"), ("2022", "2022-01-03", "2022-10-12"), ("2024", "2024-07-16", "2024-08-05"), ("2025", "2025-02-19", "2025-04-08"),
      ("2000", "2000-09-01", "2002-10-09"), ("2007", "2007-10-09", "2009-03-09"), ("1998", "1998-07-17", "1998-10-08"))
sh = lambda x: x.mean() / x.std() * np.sqrt(ANN)
dd = lambda x: ((1 + x).cumprod() / (1 + x).cumprod().cummax() - 1).min()
eps = lambda x: sum(float(x[(x.index > a) & (x.index <= b)].sum()) for _, a, b in EP)
def sleeve(name, k=None, mult=0.0, dn=None):
    d = Y.fetch(name)[["open", "high", "low", "close"]].dropna()
    st = IR.rules(d); sg = IS.har_sigma(d)
    base = (st["R2<10"] + st["D7"] + st["IBS"]).map(lambda v: W[int(round(v))])
    vm = V.mult_of(V.vix_rank(d.index)[0], (0.5, 1.0, 1.5))
    w = (base * vm * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
    z = d["close"].pct_change() / sg.shift(1)
    if k is not None:
        w = w.where(~(z >= k), w * mult)
    r, _, _ = IS.run(d, w, sg, IR.short_rate("USD", d.index), 0.0, 4.0, "open")
    return r.iloc[260:], (w.iloc[260:] > 0).mean()
print("形 | 3本の層：シャープ | 前半(〜2013-08) | 後半 | 最大の下落 | 最悪の日 | 急落の局面の合計 | 持つ日 | SPY・QQQ・DIA のシャープ | 年率(同じ建玉)")
for lab, k, m in (("今の形", None, 0.0), ("+1.0σ 以上の上げの次の日は持たない", 1.0, 0.0), ("+0.75σ", 0.75, 0.0), ("+1.5σ", 1.5, 0.0), ("+0.5σ", 0.5, 0.0), ("+1.0σ：半分にする", 1.0, 0.5), ("+2.0σ", 2.0, 0.0)):
    parts, held = [], []
    for n in ("SPY", "QQQ", "DIA"):
        r, hd = sleeve(n, k, m); parts.append(r); held.append(hd)
    r = pd.concat(parts, axis=1, sort=True).fillna(0.0).mean(axis=1); r = r[r.index >= "2000-06-01"]
    mid = r.index[len(r) // 2]
    print(f"{lab:26s} | {sh(r):+.3f} | {sh(r[r.index <= mid]):+.3f} | {sh(r[r.index > mid]):+.3f} | {dd(r)*100:.2f}% | {r.min()*100:.2f}% | {eps(r)*100:+.1f}% | {np.mean(held)*100:.0f}% | " + "・".join(f"{sh(p):+.2f}" for p in parts) + f" | {r.mean()*ANN*100:+.2f}%")

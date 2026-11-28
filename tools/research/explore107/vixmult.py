"""下調べ：VIX の倍率の組み合わせの見直し（107章 3）。
事前に基準を決めた正式な検証ではない（結果は不採用。数字は reports/experiments.md の 107章）。日付・時刻は使わない。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np, pandas as pd
import index_reversion as IR, index_stop as IS, index_vix_sizing as V, yahoo_data as Y
ANN = 252
W = {0: 0.0, 1: 0.25, 2: 0.5, 3: 1.0}
EP = (("2010", "2010-04-23", "2010-07-02"), ("2011", "2011-07-22", "2011-10-03"), ("2015", "2015-08-17", "2015-08-25"), ("2018a", "2018-01-26", "2018-02-08"), ("2018b", "2018-09-20", "2018-12-24"),
      ("2020", "2020-02-19", "2020-03-23"), ("2022", "2022-01-03", "2022-10-12"), ("2024", "2024-07-16", "2024-08-05"), ("2025", "2025-02-19", "2025-04-08"))
def sleeve(name, form):
    d = Y.fetch(name)[["open", "high", "low", "close"]].dropna()
    st = IR.rules(d); sg = IS.har_sigma(d)
    base = (st["R2<10"] + st["D7"] + st["IBS"]).map(lambda v: W[int(round(v))])
    vm = V.mult_of(V.vix_rank(d.index)[0], form) if form else 1.0
    w = (base * vm * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
    r, _, _ = IS.run(d, w, sg, IR.short_rate("USD", d.index), 0.0, 4.0, "open")
    return r.iloc[260:]
sh = lambda x: x.mean() / x.std() * np.sqrt(ANN)
dd = lambda x: ((1 + x).cumprod() / (1 + x).cumprod().cummax() - 1).min()
eps = lambda x: sum(float(x[(x.index > a) & (x.index <= b)].sum()) for _, a, b in EP)
print("形 | 全期間(2000-06〜) シャープ・下落 | 2000〜2010 | 2011〜2026 | 2007〜2026 | 2017〜2026 | 急落の局面の合計(2010年〜) | 同じ値動きにそろえた急落の合計")
base_vol = None
for lab, form in (("VIX の倍率なし", None), ("今の形 0.5/1/1.5", (0.5, 1.0, 1.5)), ("高いときも 1 倍 0.5/1/1", (0.5, 1.0, 1.0)), ("低いときだけ 0.75/1/1", (0.75, 1.0, 1.0)), ("高いとき 1.25", (0.5, 1.0, 1.25))):
    r = pd.concat([sleeve(n, form) for n in ("SPY", "QQQ", "DIA")], axis=1, sort=True).fillna(0.0).mean(axis=1)
    r = r[r.index >= "2000-06-01"]
    if base_vol is None: base_vol = r.std()
    k = base_vol / r.std()
    seg = lambda a, b: r[(r.index >= a) & (r.index < b)]
    print(f"{lab:22s} | {sh(r):+.2f}・{dd(r*k)*100:.1f}% | {sh(seg('2000','2011')):+.2f} | {sh(seg('2011','2027')):+.2f} | {sh(seg('2007','2027')):+.2f} | {sh(seg('2017','2027')):+.2f} | {eps(r)*100:+.1f}% | {eps(r*k)*100:+.1f}% | 年率(同じ値動き) {r.mean()*k*ANN*100:+.2f}%")

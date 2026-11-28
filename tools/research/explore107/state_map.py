"""下調べ：戻りの層の損益を、11 の状態 × 5 つの区切りで分けた地図（前半・後半、急落の局面の内訳。107章 3）。
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
vix = Y.fetch("VIX")["close"].dropna()
rows = []
for name in ("SPY", "QQQ", "DIA"):
    d = Y.fetch(name)[["open", "high", "low", "close"]].dropna()
    st = IR.rules(d); sg = IS.har_sigma(d)
    nst = (st["R2<10"] + st["D7"] + st["IBS"]).round()
    vm = V.mult_of(V.vix_rank(d.index)[0], (0.5, 1.0, 1.5))
    w = (nst.map(lambda v: W[int(v)]) * vm * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
    c, o, l = d["close"], d["open"], d["low"]
    # その日の損益（建玉1単位あたり）：前の日の終値で決め、始値で買い、終値まで（持ち越しは終値→始値も）。簡単のため、始値→終値＋前日終値→始値を持っている分だけ
    held_prev = (w.shift(2) > 0)
    r_day = (c / o - 1.0)
    stop = l <= o * (1 - 4 * sg.shift(1))
    r_day = r_day.where(~stop, -4 * sg.shift(1))
    r_gap = (o / c.shift(1) - 1.0).where(held_prev & (w.shift(1) > 0), 0.0)
    unit = r_day + r_gap
    v = vix.reindex(vix.index.union(d.index)).ffill().reindex(d.index)
    f = pd.DataFrame({
        "w": w.shift(1), "u": unit, "name": name,
        "sma50": (c > c.rolling(50).mean()).astype(float).shift(1),
        "ret5": ((c / c.shift(5) - 1) / (sg * np.sqrt(5))).shift(1),
        "dvix3": (v / v.shift(3) - 1).shift(1),
        "dvix1": (v / v.shift(1) - 1).shift(1),
        "depth20": ((c / c.rolling(20).max() - 1) / (sg * np.sqrt(20))).shift(1),
        "volx": (sg / c.pct_change().rolling(60).std()).shift(1),
        "nrule": nst.shift(1),
        "ext200": ((c / c.rolling(200).mean() - 1) / (sg * np.sqrt(200))).shift(1),
        "ret1": (c.pct_change() / sg.shift(1)).shift(1),
        "vixlvl": v.shift(1),
    })
    run = (w > 0).astype(int); grp = (run != run.shift()).cumsum(); f["epday"] = run.groupby(grp).cumsum().shift(1)
    f = f[f["w"] > 0].dropna()
    rows.append(f)
A = pd.concat(rows).sort_index()
A["pnl"] = A["w"] * A["u"]
A["crash"] = False
for _, a, b in EP:
    A.loc[(A.index > a) & (A.index <= b), "crash"] = True
split = "2011-01-01"
DS, VS = A[A.index < split], A[A.index >= split]
print(f"持っている日：前半 {len(DS)}・後半 {len(VS)}。建玉で重みをつけた損益の合計（前半・後半）：{DS['pnl'].sum()*100:+.1f}%・{VS['pnl'].sum()*100:+.1f}%。うち急落の局面：{DS[DS.crash]['pnl'].sum()*100:+.1f}%・{VS[VS.crash]['pnl'].sum()*100:+.1f}%")
def table(feat, q=5):
    edges = DS[feat].quantile(np.linspace(0, 1, q + 1)).values if DS[feat].nunique() > q else None
    out = []
    for lab, X in (("前半", DS), ("後半", VS)):
        if edges is None:
            g = X.groupby(feat)
        else:
            e = edges.copy(); e[0], e[-1] = -np.inf, np.inf
            g = X.groupby(pd.cut(X[feat], np.unique(e), labels=False))
        cells = []
        for k, x in g:
            if len(x) < 30: cells.append("—"); continue
            cells.append(f"{x['pnl'].sum()*100:+6.1f}（t {x['pnl'].mean()/x['pnl'].std()*np.sqrt(len(x)):+.1f}・急落 {x[x.crash]['pnl'].sum()*100:+.1f}・n {len(x)}）")
        out.append(f"  {lab}: " + " | ".join(cells))
    rng = "" if edges is None else " 境目 " + ", ".join(f"{v:.2f}" for v in edges[1:-1])
    print(f"[{feat}]{rng}"); print("\n".join(out))
for feat in ("sma50", "nrule", "ret5", "ret1", "dvix1", "dvix3", "depth20", "volx", "ext200", "vixlvl", "epday"):
    table(feat)
A.to_pickle(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data", "state_map.pkl"))

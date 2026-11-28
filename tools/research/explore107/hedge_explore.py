"""下調べ：米国以外の指数・金・円を、戻りの層の保険として持った場合（107章 2）。引数：指数の口座の書き出しのフォルダ、商品の口座の書き出しのフォルダ。
事前に基準を決めた正式な検証ではない（結果は不採用。数字は reports/experiments.md の 107章）。日付・時刻は使わない。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np, pandas as pd
import index_others as IO, index_reversion as IR, index_stop as IS, index_vix_sizing as V, yahoo_data as Y
ANN = 252
folder = sys.argv[1]
data, props = IO.load(folder)
US = ("US500", "US100", "US30")
# 米国3指数の戻りの層：日々の損益（終値→終値）と、その日に持っていた建玉（資金に対する倍率）
parts, expo = [], []
for s in US:
    r, w, _, _ = IO.sleeve(data[s], s, props)
    parts.append(r / 3.0); expo.append(w.shift(1) / 3.0)     # w は前の日の終値で決めた建玉。その日の始値から持つ
rs = pd.concat(parts, axis=1, sort=True).fillna(0.0).sum(axis=1)
E = pd.concat(expo, axis=1, sort=True).fillna(0.0).sum(axis=1)
first = max(d.index[0] for d in data.values()) + pd.Timedelta(days=320)
rs, E = rs[rs.index >= first], E[E.index >= first]
sh = lambda x: x.mean() / x.std() * np.sqrt(ANN)
dd = lambda x: ((1 + x).cumprod() / (1 + x).cumprod().cummax() - 1).min()
EP = (("2018年1〜2月", "2018-01-26", "2018-02-08"), ("2018年9〜12月", "2018-09-20", "2018-12-24"), ("2020年2〜3月", "2020-02-19", "2020-03-23"), ("2022年1〜10月", "2022-01-03", "2022-10-12"), ("2024年7〜8月", "2024-07-16", "2024-08-05"), ("2025年2〜4月", "2025-02-19", "2025-04-08"))
eps = lambda x: sum(float(x[(x.index > a) & (x.index <= b)].sum()) for _, a, b in EP)
print(f"米国3指数の層（{rs.index[0].date()}〜{rs.index[-1].date()}）: シャープ {sh(rs):+.2f} 最大の下落 {dd(rs)*100:.1f}% 急落の局面の合計 {eps(rs)*100:+.1f}% 年率 {rs.mean()*ANN*100:+.1f}% 持つ日 {(E>0).mean()*100:.0f}% 平均の建玉 {E[E>0].mean():.2f}")
cands = {}
for s in data:
    if s in US: continue
    c = data[s]["close"]; cands[s] = (c.pct_change(), float(props.loc[s, "spread_points"]) * float(props.loc[s, "point"]) / float(props.loc[s, "bid"]), -float(props.loc[s, "swap_short"]))
for nm in ("AUDJPY", "USDJPY"):
    c = Y.fetch("FX_" + nm)["close"].dropna(); cands[nm] = (c.pct_change().shift(-1), 0.00007, 4.3 if nm == "AUDJPY" else 5.8)   # Yahoo の為替の日付は1日ずれているので合わせる
gold = pd.read_csv(os.path.join(sys.argv[2], "AMS_d1_XAUUSD.csv")); gold.index = pd.to_datetime(gold["date"], format="%Y.%m.%d")
cands["XAUUSD（買い）"] = (-gold["close"].astype(float).pct_change(), 0.0001, 3.62)   # 符号を逆にして「売り」と同じ式で扱う（＝金を買う保険）
print("候補 | 持つ日の値動きの平均（建玉で重み。年率換算、%/年。プラス＝売ると損） | 層の損益との相関（持つ日） | β（層の損益 ÷ 候補） | h=0.5: シャープ・下落・急落の合計 | h=1.0 | 最小分散の h")
for nm, (rh, spread, swap_cost) in cands.items():
    z = pd.concat([rs, E, rh], axis=1, sort=True).dropna(); z.columns = ["r", "E", "h"]
    held = z[z["E"] > 0]
    wmean = (held["E"] * held["h"]).sum() / held["E"].sum()
    hp = held["E"] * held["h"]                                  # 候補を建玉と同じ額だけ持ったときの損益
    rho = np.corrcoef(held["r"], hp)[0, 1]
    beta = np.cov(held["r"], hp)[0, 1] / hp.var()
    out = []
    for h in (0.5, 1.0):
        cost = (z["E"].diff().abs().fillna(0.0) * h * spread / 2.0) + z["E"] * h * swap_cost / 100.0 / 360.0 * 1.45
        rr = z["r"] - h * z["E"] * z["h"] - cost
        out.append(f"{sh(rr):+.2f}・{dd(rr)*100:.1f}%・{eps(rr)*100:+.1f}%")
    print(f"{nm:14s} | {wmean*ANN*100:+6.1f} | {rho:+.2f} | {beta:+.2f} | {out[0]} | {out[1]} | {beta:.2f}")

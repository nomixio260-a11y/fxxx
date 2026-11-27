#!/usr/bin/env python3
"""研究：売られすぎの戻りの層に、「その日のうちの急落」に備えた損切り（業者に預ける逆指値）を置くと、損失は減るか。

- index_risk.py の D では、「持ってからの下げが k% を超えたら手じまい、すべてのルールが出るまで休む」形の損切りは、成績を悪くした。
- ここでは別の形を確かめる：**毎日、その日の値動きの見積もり（1日の標準偏差 σ）の k 倍だけ下に、逆指値を置き直す**。
  - 建玉は 1 ÷ σ に比例するので、この逆指値は「1日の損失の上限を、口座の決まった割合にする」ことと同じ（上限 = k × 建玉の1日の値動き）。
  - 逆指値にかかった日は、その値段（＋すべり）で手じまい、その日は持たない。次の日足で、ルールが続いていれば持ち直す。
  - 逆指値は業者に預けるので、EA が止まっているあいだも効く。
- 2つのデータで確かめる：
  A CFD の日足（S&P500 と NASDAQ100、2011年9月〜2026年10月。EA と同じ形：日足の始まりで売買、その値段から k×σ 下に逆指値）
  B 現物の指数（米国3指数、2000年10月〜2026年11月。前の日の終値から k×σ 下。始値がそれより下なら、始値で手じまい）
- すべり：逆指値の約定は、指定の値段より 0.05% 悪いとする（急落の最中のため。ふだんの売買コスト 0.02% に上乗せ）。
- 物差し：全期間の値動きを年10%にそろえたあとの、シャープ・最悪の日・下位1%の日の平均・最大の下落。
使い方: python3 tools/research/index_stop.py  → reports/research/index_stop.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_reversion_cfd as IC  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_vol_forecast as VF  # noqa: E402

ANN = 252
HAR = (0.0, 0.37, 0.56, 0.20)          # 先物（ES・NQ、2000〜2018年）で決めた係数（index_cfd_sizing.py）
SLIP = 0.0005
CFD = {"S&P500": ("SPXUSD", "USD", 1.5), "NASDAQ100": ("NSXUSD", "USD", 0.7)}
KS = (None, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)


def har_sigma(d, co=HAR):
    """翌日の値動きの大きさの見積もり（1日の標準偏差）。その日の終値までの値だけを使う。"""
    dv = VF.daily_var(d)
    v = co[0] + co[1] * dv + co[2] * dv.rolling(5).mean() + co[3] * dv.rolling(22).mean()
    return np.sqrt(v.clip(lower=0)).clip(lower=0.025 / np.sqrt(ANN))


def run(d, w, sig_d, rate, div, k, ref="open"):
    """建玉 w（終値で決めた大きさ）の日次の損益。k が None なら逆指値なし。
    ref="open"：日足の始値で売買し、始値から k×σ 下に逆指値（CFD）。ref="close"：前の日の終値で売買し、終値から k×σ 下（現物）。"""
    o, h, l, c = (d[x].values for x in ("open", "high", "low", "close"))
    n = len(d)
    days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0).values
    fin = ((div - rate - IR.MARKUP) / 100.0 / 360.0).values * days
    wv, sg = w.values, sig_d.values
    out = np.zeros(n)
    stops = 0
    after = []                                # 逆指値にかかったあと、その日の終値までの値動き（持ち続けていたら得られた分）
    carried = 0.0                             # 前の日の終値をまたいで持っている建玉
    for t in range(2 if ref == "open" else 1, n):
        if ref == "open":
            target = wv[t - 1]                # t-1 の終値で決め、t の始値で売買
            pnl = carried * (o[t] / c[t - 1] - 1.0 + fin[t]) - abs(target - carried) * IR.COST
            base, s = o[t], sg[t - 1]
        else:
            target = wv[t - 1]                # t-1 の終値で決め、その終値で売買
            pnl = -abs(target - carried) * IR.COST + target * fin[t]
            base, s = c[t - 1], sg[t - 1]
        hit = False
        if k is not None and target > 0 and not np.isnan(s):
            level = base * (1.0 - k * s)
            if ref == "close" and o[t] <= level:
                hit, fill = True, o[t]
            elif l[t] <= level:
                hit, fill = True, level
        if hit:
            pnl += target * (fill * (1.0 - SLIP) / base - 1.0) - target * IR.COST
            after.append(c[t] / fill - 1.0)
            stops += 1
            carried = 0.0
        else:
            pnl += target * (c[t] / base - 1.0)
            carried = target
        out[t] = pnl
    return pd.Series(out, index=d.index), stops, after


def table(title, sets, start, per, ref):
    head = ("| 逆指値 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の月 | 最悪の年 | " + " | ".join(p[0] for p in per)
            + " | かかった回数 | かかったあと終値までの平均 |")
    lines = [f"## {title}", "", head, "|---|" + "---|" * (9 + len(per))]
    for k in KS:
        parts, stops, after = [], 0, []
        for d, w, sg, rate, div in sets:
            r, s, a = run(d, w, sg, rate, div, k, ref)
            parts.append(r)
            stops += s
            after += a
        rr = pd.concat(parts, axis=1, sort=True).fillna(0.0).sum(axis=1)
        rr = rr[rr.index >= start]
        z = rr * (0.10 / (rr.std() * np.sqrt(ANN)))
        sh = z.mean() / z.std() * np.sqrt(ANN)
        eq = (1 + z).cumprod()
        mo = z.groupby(z.index.to_period("M")).sum()
        yr = z.groupby(z.index.year).sum()
        q = z.quantile(0.01)
        lab = "なし" if k is None else f"{k:g} × σ"
        lines.append(f"| {lab} | {sh:+.2f} | {sh * np.sqrt(len(z) / ANN):+.1f} | {z.min() * 100:.1f}%（{z.idxmin().date()}） | {z[z <= q].mean() * 100:.2f}% | "
                     f"{(eq / eq.cummax() - 1).min() * 100:.0f}% | {mo.min() * 100:.1f}% | {yr.min() * 100:.1f}% | "
                     + " | ".join(f"{x.mean() / x.std() * np.sqrt(ANN):+.2f}" for x in (z[(z.index >= a) & (z.index < b)] for _, a, b in per))
                     + f" | {stops} | " + (f"{np.mean(after) * 100:+.2f}%" if after else "—") + " |")
        print(lines[-1], flush=True)
    return lines + [""]


def main():
    lines = ["# 研究：その日のうちの急落に備えた逆指値（`tools/research/index_stop.py`）", "",
             "毎日、その日の値動きの見積もり σ（HAR 型）の k 倍だけ下に逆指値を置き直す。建玉は HAR 型の見積もりで決め、ルールの数に比例（1:2:3）。", ""]
    sets = []
    for name, (pair, ccy, div) in CFD.items():
        d = IC.day_bars(IC.load_any(pair), 17)
        st = IR.rules(d)
        n = st["R2<10"] + st["D7"] + st["IBS"]
        sg = har_sigma(d)
        w = (n / 3.0 * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0) / len(CFD)
        sets.append((d, w, sg, IR.short_rate(ccy, d.index), div))
    per = (("2011/9〜14", "2011-09-01", "2015-01-01"), ("2015〜18", "2015-01-01", "2019-01-01"), ("2019〜21/10", "2019-01-01", "2021-11-01"),
           ("21/11〜26/10", "2021-11-01", "2026-12-01"))
    lines += table("A CFD の日足（S&P500 と NASDAQ100、2011年9月〜2026年10月。日足の始値から k×σ 下）", sets, "2011-09-01", per, "open")
    sets = []
    for name in IRK.US3:
        d, st, rate, div, vols, above = IRK.load(name)
        sg = har_sigma(d)
        w = (st.sum(axis=1) / 3.0 * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0) / len(IRK.US3)
        sets.append((d, w, sg, rate, div))
    lines += table("B 現物の指数（米国3指数、2000年10月〜2026年11月。前の日の終値から k×σ 下）", sets, IRK.START, IRK.PER, "close")
    out = os.path.join(F.ROOT, "reports", "research", "index_stop.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

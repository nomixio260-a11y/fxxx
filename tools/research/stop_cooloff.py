#!/usr/bin/env python3
"""研究：急落の局面の損失を減らす ― 逆指値にかかったあとの「入り直し」を見送る（106章）。日付・時刻は使わない。

- 20年の検証（composite_20y.py）で、指数の戻りの層の弱点は「高値からの急落」と分かった（2010年5月・2011年8月・2015年8月・2018年2月・
  2020年3月・2022年・2025年4月。下げが何日も続くあいだ、買い → 逆指値 → 次の日にまた買い、を繰り返して負けが重なる）。
- 今の形：逆指値（その日の始値から 4 × 1日の値動きの見積もり）にかかると、その日は手じまい、次の日足でルールがまだ出ていれば買い直す。
- 候補（結果を見る前に決めた。これ以外は試さない）：
   C1 逆指値にかかったら、ルールがすべて消える（その下げの局面が終わる）まで、その銘柄は買い直さない
   C2 逆指値にかかったら、次の1日は買い直さない
   C3 逆指値にかかったら、次の2日は買い直さない
- データ：実際に売買できた ETF（SPY 1993年〜・QQQ 1999年〜・DIA 1998年〜）。戻りの層は EA と同じ形（R2・D7・IBS、重み 1:2:4、HAR 型、VIX の倍率、
  判定は終値・売買は次の日の始値、コストは CFD と同じ形）。
- 判定（結果を見る前に決めた）。採用するのは、次をすべて満たす形だけ：
   (a) 3本の層のシャープが、前半・後半の両方で、今の形より低くない
   (b) 3本の層の最大の下落が、今の形より浅い（同じ建玉の大きさで）
   (c) 急落の局面（下の一覧。成績を見て選んだものではない）の損益の合計が、今の形より良い
   (d) 3本のうち2本以上で、その ETF だけの層のシャープが今の形より低くない
- あわせて、「逆指値にかかった次の日」の損益を、ほかの日と比べる（買い直す日の期待値がプラスかどうか）。
使い方: python3 tools/research/stop_cooloff.py  → reports/research/stop_cooloff.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_stop as IS  # noqa: E402
import index_vix_sizing as V  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
W = {0: 0.0, 1: 0.25, 2: 0.5, 3: 1.0}
ETFS = ("SPY", "QQQ", "DIA")
MODES = (("今の形（次の日に買い直す）", "none"), ("C1 その下げの局面が終わるまで買い直さない", "episode"), ("C2 次の1日は買い直さない", "skip1"), ("C3 次の2日は買い直さない", "skip2"))
EPISODES = (("2010年4〜7月", "2010-04-23", "2010-07-02"), ("2011年7〜10月", "2011-07-22", "2011-10-03"), ("2015年8月", "2015-08-17", "2015-08-25"),
            ("2018年1〜2月", "2018-01-26", "2018-02-08"), ("2018年9〜12月", "2018-09-20", "2018-12-24"), ("2020年2〜3月", "2020-02-19", "2020-03-23"),
            ("2022年1〜10月", "2022-01-03", "2022-10-12"), ("2024年7〜8月", "2024-07-16", "2024-08-05"), ("2025年2〜4月", "2025-02-19", "2025-04-08"),
            ("2000年9月〜02年10月", "2000-09-01", "2002-10-09"), ("2007年10月〜09年3月", "2007-10-09", "2009-03-09"))


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 200 and x.std() > 0 else np.nan


def run(d, w, nst, sg, rate, mode, k=4.0):
    """index_stop.run（ref="open"）と同じ計算に、逆指値のあとの見送りを足したもの。戻り値：日々の損益、逆指値の回数、買い直した日の損益（建玉1単位あたり）。"""
    o, h, l, c = (d[x].values for x in ("open", "high", "low", "close"))
    n = len(d)
    days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0).values
    fin = ((0.0 - rate - IR.MARKUP) / 100.0 / 360.0).values * days
    wv, s_, ns = w.values, sg.values, nst.values
    out = np.zeros(n)
    stops, carried, block, wait_reset = 0, 0.0, 0, False
    reentry, normal = [], []
    was_stop = False
    for t in range(2, n):
        target = wv[t - 1]
        if mode == "episode":
            if wait_reset and ns[t - 1] == 0:
                wait_reset = False
            if wait_reset:
                target = 0.0
        elif block > 0:
            target = 0.0
            block -= 1
        pnl = carried * (o[t] / c[t - 1] - 1.0 + fin[t]) - abs(target - carried) * IR.COST
        base, s = o[t], s_[t - 1]
        hit = False
        if target > 0 and not np.isnan(s):
            level = base * (1.0 - k * s)
            if l[t] <= level:
                hit, fill = True, level
        if hit:
            day = target * (fill * (1.0 - IS.SLIP) / base - 1.0) - target * IR.COST
            stops += 1
            carried = 0.0
        else:
            day = target * (c[t] / base - 1.0)
            carried = target
        if target > 0:
            (reentry if was_stop else normal).append(day / target)
        pnl += day
        out[t] = pnl
        if hit:
            if mode == "episode":
                wait_reset = True
            elif mode == "skip1":
                block = 1
            elif mode == "skip2":
                block = 2
        was_stop = hit
    return pd.Series(out, index=d.index), stops, np.array(reentry), np.array(normal)


def build(name):
    d = Y.fetch(name)[["open", "high", "low", "close"]].dropna()
    st = IR.rules(d)
    sg = IS.har_sigma(d)
    nst = (st["R2<10"] + st["D7"] + st["IBS"]).round()
    vm = V.mult_of(V.vix_rank(d.index)[0], (0.5, 1.0, 1.5))
    w = (nst.map(lambda v: W[int(v)]) * vm * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
    return d, w, nst, sg, IR.short_rate("USD", d.index)


def main():
    lines = ["# 研究：逆指値にかかったあとの入り直しを見送る（`tools/research/stop_cooloff.py`）", "",
             "ETF（SPY・QQQ・DIA）。戻りの層は EA と同じ形。コスト込み。建玉の大きさは、どの形も同じ（ルール3つのとき、その銘柄の値動きが年10%）。", ""]
    R, info = {m: {} for _, m in MODES}, {}
    for name in ETFS:
        d, w, nst, sg, rate = build(name)
        for _, mode in MODES:
            r, stops, re, no = run(d, w, nst, sg, rate, mode)
            R[mode][name] = r.iloc[260:]
            if mode == "none":
                info[name] = (stops, re, no, len(d) / ANN)
    # ---------- 買い直した日の損益
    lines += ["## 1 逆指値にかかった次の日（買い直した日）の損益（今の形。建玉1単位あたり）", "",
              "| ETF | 逆指値の回数（年） | 買い直した日：日数 | 平均（%） | t 値 | ほかの持っている日：平均（%） | t 値 |", "|---|---|---|---|---|---|---|"]
    allre, allno = [], []
    for name in ETFS:
        stops, re, no, yrs = info[name]
        allre.append(re)
        allno.append(no)
        lines.append(f"| {name} | {stops / yrs:.1f} | {len(re)} | {re.mean() * 100:+.3f} | {re.mean() / re.std() * np.sqrt(len(re)):+.1f} | {no.mean() * 100:+.3f} | {no.mean() / no.std() * np.sqrt(len(no)):+.1f} |")
        print(lines[-1], flush=True)
    re, no = np.concatenate(allre), np.concatenate(allno)
    lines.append(f"| 3本の合計 | — | {len(re)} | {re.mean() * 100:+.3f} | {re.mean() / re.std() * np.sqrt(len(re)):+.1f} | {no.mean() * 100:+.3f} | {no.mean() / no.std() * np.sqrt(len(no)):+.1f} |")
    print(lines[-1], flush=True)
    # ---------- 層の成績
    lines += ["", "## 2 層の成績", "", "| 形 | 3本の層：シャープ | 前半 | 後半 | 最大の下落 | 最悪の日 | 急落の局面の損益の合計 | SPY | QQQ | DIA |", "|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for lab, mode in MODES:
        all3 = pd.concat(R[mode].values(), axis=1, sort=True).fillna(0.0).mean(axis=1)
        all3 = all3[all3.index >= "2000-06-01"]
        mid = all3.index[len(all3) // 2]
        e = (1 + all3).cumprod()
        ep = sum(float(all3[(all3.index > a) & (all3.index <= b)].sum()) for _, a, b in EPISODES)
        res[mode] = dict(a=sh(all3[all3.index <= mid]), b=sh(all3[all3.index > mid]), dd=(e / e.cummax() - 1).min(), ep=ep, each={n: sh(R[mode][n]) for n in ETFS}, r=all3)
        lines.append(f"| {lab} | {sh(all3):+.2f} | {res[mode]['a']:+.2f} | {res[mode]['b']:+.2f} | {res[mode]['dd'] * 100:.1f}% | {all3.min() * 100:.2f}% | {ep * 100:+.1f}% | "
                     + " | ".join(f"{res[mode]['each'][n]:+.2f}" for n in ETFS) + " |")
        print(lines[-1], flush=True)
    lines += ["", "## 3 急落の局面ごとの損益（3本の層。%）", "", "| 局面 | " + " | ".join(m[0][:2] if m[1] != "none" else "今の形" for m in MODES) + " |", "|---|" + "---|" * len(MODES)]
    for lab, a, b in EPISODES:
        lines.append(f"| {lab} | " + " | ".join(f"{float(res[m]['r'][(res[m]['r'].index > a) & (res[m]['r'].index <= b)].sum()) * 100:+.1f}" for _, m in MODES) + " |")
    lines += ["", "## 4 判定", "", "| 形 | (a) シャープが前半・後半とも低くない | (b) 最大の下落が浅い | (c) 急落の局面の合計が良い | (d) 2本以上で低くない | 判定 |", "|---|---|---|---|---|---|"]
    b0 = res["none"]
    for lab, mode in MODES[1:]:
        x = res[mode]
        a = x["a"] >= b0["a"] and x["b"] >= b0["b"]
        b = x["dd"] > b0["dd"]
        c = x["ep"] > b0["ep"]
        dn = sum(x["each"][n] >= b0["each"][n] for n in ETFS)
        ok = a and b and c and dn >= 2
        lines.append(f"| {lab} | {'○' if a else '×'} | {'○' if b else '×'} | {'○' if c else '×'} | {'○' if dn >= 2 else '×'}（{dn} / 3） | {'**合格**' if ok else '不合格'} |")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "stop_cooloff.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

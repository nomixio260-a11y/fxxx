#!/usr/bin/env python3
"""研究：どの年代でも通用するか（102章）。

A 実際に売買できた商品（ETF：SPY 1993年〜、DIA 1998年〜、QQQ 1999年〜）で、年代ごとの成績を見る。
  指数そのもの（現物）は、昔は売買できなかった（先物は 1982年〜、ETF は 1993年〜）。指数の値には、その日に取引のなかった銘柄の古い値段が
  混ざるので、「前の日と同じ向きに動きやすい」性質が強く出る（とくに 1980年代まで）。この性質は、実際には売買で取れない。
  そこで、売買できた商品で、公表前の時期（1993〜2008年）も含めて確かめる。
  形は EA と同じ（重み 1:2:4・HAR 型・VIX の倍率・逆指値 4×σ）。判定は終値、売買は次の日の始値（実際に付いた値段）。
  コストは CFD と同じ形（買いは 短期金利＋年2.5% を払う。片道 0.02%）。分配金は入れていない（少し厳しめ）。
B 年ごとの成績（現物の3指数 2001年〜、ETF の3本 2000年〜）。プラスの年の数・最悪の年。
C 前提の監視を2段にする：
   1段目（100章）：順位の相関が 標準誤差1つ分 を超えたら IBS を止める。
   2段目（新しい案）：標準誤差3つ分 を超えたら、R2・D7 も止める（1962〜81年のように、はっきり「続きやすい」相場では、3つとも負けていたため）。
使い方: python3 tools/research/index_eras.py  → reports/research/index_eras.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_regime_monitor as RM  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_stop as IS  # noqa: E402
import index_vix_sizing as V  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
W = {0: 0.0, 1: 0.25, 2: 0.5, 3: 1.0}
PER = (("1993〜98", "1993-01-01", "1999-01-01"), ("1999〜2004", "1999-01-01", "2005-01-01"), ("2005〜10", "2005-01-01", "2011-01-01"),
       ("2011〜16", "2011-01-01", "2017-01-01"), ("2017〜21", "2017-01-01", "2022-01-01"), ("2022〜26", "2022-01-01", "2027-01-01"))


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 100 and x.std() > 0 else np.nan


def etf_sleeve(name, only=None, use_vix=True):
    d = Y.fetch(name)[["open", "high", "low", "close"]].dropna()
    st = IR.rules(d)
    sg = IS.har_sigma(d)
    base = (st["R2<10"] + st["D7"] + st["IBS"]).map(lambda v: W[int(round(v))]) if only is None else st[only]
    vm = V.mult_of(V.vix_rank(d.index)[0], (0.5, 1.0, 1.5)) if use_vix else 1.0
    w = (base * vm * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
    r, _, _ = IS.run(d, w, sg, IR.short_rate("USD", d.index), 0.0, 4.0, "open")
    return r.iloc[260:]                                   # 200日の平均と助走のあと


def cells(r, per=PER):
    return " | ".join(f"{sh(r[(r.index >= a) & (r.index < b)]):+.2f}" if len(r[(r.index >= a) & (r.index < b)]) > 200 else "—" for _, a, b in per)


def main():
    lines = ["# 研究：どの年代でも通用するか（`tools/research/index_eras.py`）", "",
             "## A 実際に売買できた商品（ETF）での、年代ごとのシャープ（EA と同じ形。コスト込み）", "",
             "| 商品 | 全期間 | " + " | ".join(p[0] for p in PER) + " |", "|---|---|" + "---|" * len(PER)]
    rets = {}
    for name, label in (("SPY", "SPY（S&P500。1993年〜）"), ("DIA", "DIA（ダウ。1998年〜）"), ("QQQ", "QQQ（NASDAQ100。1999年〜）")):
        rets[name] = etf_sleeve(name)
        lines.append(f"| {label} | {sh(rets[name]):+.2f} | {cells(rets[name])} |")
        print(lines[-1], flush=True)
    all3 = pd.concat(rets.values(), axis=1, sort=True).fillna(0.0).mean(axis=1)
    lines.append(f"| **3本の層**（そろう時期から。それまではある分だけ） | {sh(all3):+.2f} | {cells(all3)} |")
    print(lines[-1], flush=True)
    for key in ("R2<10", "D7", "IBS"):
        r = etf_sleeve("SPY", only=key, use_vix=False)
        lines.append(f"| SPY：{key} だけ（VIX の倍率なし） | {sh(r):+.2f} | {cells(r)} |")
        print(lines[-1], flush=True)
    # 現物（同じ時期の比べ）
    spx = RM.load("S&P500", "1961-01-01")
    d, st, rate, div, sg, rk = spx
    for label, n in (("現物の S&P500：3ルール（参考。指数は昔は売買できない）", st["R2<10"] + st["D7"] + st["IBS"]), ("現物の S&P500：IBS だけ", None)):
        if n is None:
            w = (st["IBS"] * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
        else:
            w = (n.map(lambda v: W[int(round(v))]) * V.mult_of(rk, (0.5, 1.0, 1.5)) * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
        r, _, _ = IS.run(d, w, sg, rate, div, 4.0, "close")
        lines.append(f"| {label} | {sh(r[r.index >= '1993-01-01']):+.2f} | {cells(r)} |")
        print(lines[-1], flush=True)
    # 前の日との相関（順位）：SPY と 現物
    lines += ["", "- 当日と直前4日の値動きの、順位の相関（1993〜98年）：" +
              "、".join(f"{lab} {RM.rank_mon(x['close'], 1500)[(lambda s: (s.index >= '1998-06-01') & (s.index < '1999-06-01'))(x)].mean():+.3f}"
                        for lab, x in (("SPY", Y.fetch("SPY")), ("現物の S&P500", d))) + "（1999年前後の1年の平均。マイナスなら反転しやすい）"]

    # ---------- B 年ごとの成績
    lines += ["", "## B 年ごとの成績（値動きを年10%にそろえたときの、1年の損益）", ""]
    for label, r, start in (("ETF の3本の層", all3, "2000-01-01"),):
        r = r[r.index >= start]
        z = r * (0.10 / (r.std() * np.sqrt(ANN)))
        yr = z.groupby(z.index.year).sum() * 100
        lines += [f"- {label}：プラスの年 {int((yr > 0).sum())} / {len(yr)}、最悪の年 {yr.min():+.1f}%（{int(yr.idxmin())}年）、最高の年 {yr.max():+.1f}%（{int(yr.idxmax())}年）、平均 {yr.mean():+.1f}%",
                  "", "| 年 | " + " | ".join(str(y) for y in yr.index) + " |", "|---|" + "---|" * len(yr), "| 損益 | " + " | ".join(f"{v:+.1f}%" for v in yr.values) + " |", ""]
        print(lines[-5], flush=True)
        # 5年ごと（始めた年をずらす）
        roll5 = z.rolling(5 * ANN).sum().dropna() * 100
        roll3 = z.rolling(3 * ANN).sum().dropna() * 100
        roll1 = z.rolling(ANN).sum().dropna() * 100
        lines.append(f"- どの時点から始めても：1年間の損益 {roll1.min():+.1f}% 〜 {roll1.max():+.1f}%（マイナスだった割合 {(roll1 < 0).mean() * 100:.0f}%）、"
                     f"3年間 {roll3.min():+.1f}% 〜 {roll3.max():+.1f}%（{(roll3 < 0).mean() * 100:.0f}%）、5年間 {roll5.min():+.1f}% 〜 {roll5.max():+.1f}%（{(roll5 < 0).mean() * 100:.0f}%）")
        print(lines[-1], flush=True)

    # ---------- C 前提の監視を2段にする
    data = {"S&P500": spx, "NASDAQ100": RM.load("NASDAQ100", "1985-10-01"), "ダウ": RM.load("ダウ", "1992-01-01")}
    mon = RM.rank_mon(data["S&P500"][0]["close"], 1500)
    se = 1.0 / np.sqrt(1500.0)

    def run(names, k1, k2):
        parts = []
        for name in names:
            dd, s2, rt, dv, sgg, rkk = data[name]
            mm = mon.reindex(mon.index.union(dd.index)).ffill().reindex(dd.index)
            ibs_on = pd.Series(1.0, index=dd.index) if k1 is None else (mm <= k1 * se).astype(float).where(mm.notna(), 1.0)
            all_on = pd.Series(1.0, index=dd.index) if k2 is None else (mm <= k2 * se).astype(float).where(mm.notna(), 1.0)
            n = (s2["R2<10"] + s2["D7"]) * all_on + s2["IBS"] * ibs_on * all_on
            w = (n.map(lambda v: W[int(round(v))]) * V.mult_of(rkk, (0.5, 1.0, 1.5)) * (0.10 / (sgg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0) / len(names)
            r, _, _ = IS.run(dd, w, sgg, rt, dv, 4.0, "close")
            parts.append(r)
        return pd.concat(parts, axis=1, sort=True).fillna(0.0).sum(axis=1)
    lines += ["", "## C 前提の監視を2段にする（現物。S&P500 の値で全指数を判定）", "",
              "| 指数 | 形 | 全期間 | " + " | ".join(e[0] for e in RM.ERAS) + " | 最大の下落 | R2・D7 も止めていた日：1967〜81 | 1982〜98 | 1999年〜 |", "|---|---|---|" + "---|" * (len(RM.ERAS) + 4)]
    x = mon.dropna()
    for names, nl in ((["S&P500"], "S&P500 だけ"), (["S&P500", "NASDAQ100", "ダウ"], "3指数")):
        for label, k1, k2 in (("監視なし", None, None), ("1段（IBS だけ。100章の形）", 1.0, None), ("2段：標準誤差2つ分で、すべて止める", 1.0, 2.0),
                              ("**2段：標準誤差3つ分で、すべて止める**", 1.0, 3.0), ("2段：標準誤差4つ分で、すべて止める", 1.0, 4.0)):
            r = run(names, k1, k2)
            r = r[r.index >= "1962-07-01"]
            z = r * (0.10 / (r.std() * np.sqrt(ANN)))
            eq = (1 + z).cumprod()
            fr = (lambda a, b: "—") if k2 is None else (lambda a, b: f"{(x[(x.index >= a) & (x.index < b)] > k2 * se).mean() * 100:.0f}%")
            lines.append(f"| {nl} | {label} | {sh(z):+.2f} | " + " | ".join(f"{sh(z[(z.index >= a) & (z.index < b)]):+.2f}" for _, a, b in RM.ERAS)
                         + f" | {(eq / eq.cummax() - 1).min() * 100:.0f}% | {fr('1967-01-01', '1982-01-01')} | {fr('1982-01-01', '1999-01-01')} | {fr('1999-01-01', '2027-01-01')} |")
            print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_eras.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

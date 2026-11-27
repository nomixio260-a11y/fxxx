#!/usr/bin/env python3
"""研究（FX だけで取引する）：物価の上がり方を引いた「実質の金利差」で通貨を選ぶと、金利差の層は崩れにくくなるか。

- 名目の金利が高くても、物価がそれ以上に上がっている通貨は、長い目では下がりやすい（物価の差の分だけ通貨の価値が減るため）。
  そこで、金利 − 物価の上昇率（過去1年）= 実質の金利 で比べ、実質の金利が高い通貨を買い、低い通貨を売る形を確かめる。
  受け取るスワップは名目の金利差のままなので、「スワップを払ってでも持つ」建玉も出る。
- データ：FRED。物価は各国の消費者物価指数の前年比（月次。豪州・NZ は四半期。日本は 2021年7月以降の月次がないため、年次の値で補う）。
  発表の遅れを見て、3か月遅らせて使う（年次の値は、翌年の4月から使う）。金利は3か月金利（1か月遅れ）。
- 形は carry_long.py の A1 と同じ（差が年1%以上のペアをすべて持つ、週1回、5通りのずれの平均）。選ぶ基準だけを、名目の金利差 → 実質の金利差 に替える。
使い方: python3 tools/research/fx_real_carry.py  → reports/research/fx_real_carry.md
"""
import itertools
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carry_breadth as CB  # noqa: E402
import carry_long as CL  # noqa: E402
import fred_data as F  # noqa: E402
import styles_long as SL  # noqa: E402

CPI = {"USD": ("CPIAUCSL", "m"), "EUR": ("CP0000EZ19M086NEST", "m"), "GBP": ("GBRCPIALLMINMEI", "m"), "CAD": ("CANCPIALLMINMEI", "m"),
       "CHF": ("CHECPIALLMINMEI", "m"), "JPY": ("JPNCPIALLMINMEI", "m"), "AUD": ("AUSCPIALLQINMEI", "q"), "NZD": ("NZLCPIALLQINMEI", "q")}


def inflation(index):
    """各通貨の物価の前年比（%、日次にそろえる。発表の遅れとして3か月遅らせる）。"""
    out = {}
    for c, (sid, freq) in CPI.items():
        s = F.fetch(sid).dropna()
        yoy = (s / s.shift(12 if freq == "m" else 4) - 1.0) * 100.0
        yoy.index = yoy.index + pd.DateOffset(months=3 if freq == "m" else 5)       # 四半期の値は、期末 + 発表の遅れ
        if c == "JPY":
            a = F.fetch("FPCPITOTLZGJPN").dropna()                                   # 年次の物価上昇率（その年の値。翌年の4月から使う）
            a.index = a.index + pd.DateOffset(months=15)
            yoy = pd.concat([yoy, a[a.index > yoy.index[-1]]])
        out[c] = yoy
    df = pd.DataFrame(out).sort_index().ffill()
    return df.reindex(df.index.union(index)).ffill().reindex(index)


def main():
    v, rate = CB.load()
    infl = inflation(v.index)
    real = rate[list(CPI)] - infl
    order = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]
    all28 = [a + b for a, b in itertools.combinations(order, 2)]
    lines = ["# 研究：実質の金利差（金利 − 物価の上昇率）で通貨を選ぶ（取引は為替だけ。`tools/research/fx_real_carry.py`）", "",
             "形は A1（差が年1%以上のペアをすべて持つ、週1回）。選ぶ基準を、名目の金利差・実質の金利差・両方が同じ向き、の3通りで比べる。コスト・スワップ（名目の金利差 − 上乗せ 年1%）込み。", "",
             "| 形 | " + " | ".join(p[0] for p in SL.PER) + " | 全体 | 年率 | 最大の下落 | 最悪の年 | プラスの年 |", "|---|" + "---|" * (len(SL.PER) + 5)]
    for uname, pairs in (("いまの17ペア", F.PAIRS), ("主要8通貨のすべての組み合わせ（28ペア）", all28)):
        px = pd.DataFrame({p: v[p[:3]] / v[p[3:]] for p in pairs})
        carry = pd.DataFrame({p: rate[p[:3]] - rate[p[3:]] for p in pairs})
        rdiff = pd.DataFrame({p: real[p[:3]] - real[p[3:]] for p in pairs})
        cost = pd.DataFrame({p: pd.Series(CB.COST_CCY[p[:3]] + CB.COST_CCY[p[3:]], index=px.index) for p in pairs})
        vol = px.pct_change().rolling(60, min_periods=40).std()

        def run(sig):
            w0 = SL.norm((sig / vol).fillna(0.0))
            outs = []
            for ph in range(CL.PH):
                w = CL.hold_phase(w0, 5, ph)
                ws = w.mul(SL.exante_scale(w, px), axis=0)
                outs.append(SL.pnl(ws, px, carry, cost))
            return outs
        nom = np.sign(carry).where(carry.abs() - SL.MARKUP >= 1.0, 0.0)
        rl = np.sign(rdiff).where(rdiff.abs() >= 1.0, 0.0)
        both = nom.where(np.sign(nom) == np.sign(rl), 0.0)
        for label, sig in (("名目の金利差（これまでの形）", nom), ("実質の金利差", rl), ("名目と実質が同じ向きのペアだけ", both)):
            line, _ = CL.summarize(f"{uname}：{label}", run(sig))
            lines.append(line)
            print(line, flush=True)
    last = pd.DataFrame({"金利": rate[list(CPI)].iloc[-1], "物価の上昇率": infl.iloc[-1], "実質の金利": real.iloc[-1]}).round(2)
    lines += ["", "## いまの値（年 %）", "", "| 通貨 | 金利 | 物価の上昇率（使っている値） | 実質の金利 |", "|---|---|---|---|"]
    for c, r_ in last.sort_values("実質の金利", ascending=False).iterrows():
        lines.append(f"| {c} | {r_['金利']:+.2f} | {r_['物価の上昇率']:+.2f} | {r_['実質の金利']:+.2f} |")
    out = os.path.join(F.ROOT, "reports", "research", "fx_real_carry.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[-11:]))


if __name__ == "__main__":
    main()

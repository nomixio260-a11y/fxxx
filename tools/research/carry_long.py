#!/usr/bin/env python3
"""長期の層：金利差の取り方を、27年分（1999〜2026年）で比べて、崩れにくい形を選ぶ（日付・時刻のクセは使わない）。

- 週1回の入れ替えは、どの曜日に入れ替えるか（ずれ）で結果が変わる。その偶然を除くため、5通りのずれの平均で比べ、ずれによる幅も示す。
- 形：
  A 金利差のあるペアをすべて持つ（上乗せ後の差が年 thr% 以上、値動きの大きさでそろえる）
  B その中で「金利差 ÷ 値動きの大きさ」の上位5つだけ
  C トレンド（60・250日）が同じ向きのペアだけ（今の EA の形は C60＋上位5つ＋急変の回避）
  D 金利差の取引全体の成績が、過去 N 日でマイナスのあいだは休む（手法そのものの調子で止める）
  E 為替全体の値動きが急に大きくなったら休む（全ペアの直近10日の値動き ÷ 120日 の平均が k 倍超）
- 物差し：期間ごとの年率シャープ、2000年以降の全体のシャープ・年率（値動き年10%）・最大の下落・最悪の年。
使い方: python3 tools/research/carry_long.py  → reports/research/carry_long.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import styles_long as SL  # noqa: E402

PH = 5


def hold_phase(w, rb, ph):
    w = w.fillna(0.0)
    keep = np.zeros(len(w), bool)
    keep[ph::rb] = True
    return w.where(pd.Series(keep, index=w.index), np.nan).ffill().fillna(0.0)


def weights(px, carry, thr=1.0, topk=None, trend=None, crash=None):
    r = px.pct_change()
    vol = r.rolling(60, min_periods=40).std()
    net = carry.abs() - SL.MARKUP
    sig = np.sign(carry).where(net >= thr, 0.0)
    if trend:
        sig = sig.where(np.sign(px / px.shift(trend) - 1.0) == np.sign(sig), 0.0)
    if crash:
        sig = sig.where(r.rolling(10, min_periods=8).std() <= crash * r.rolling(120, min_periods=80).std(), 0.0)
    w = sig / vol
    if topk:
        score = (net / vol).where(sig != 0)
        w = w.where(score.rank(axis=1, ascending=False) <= topk, 0.0)
    return SL.norm(w.fillna(0.0))


def run(px, carry, cost, own_trend=None, risk_off=None, **kw):
    """5通りのずれそれぞれの日次の損益（値動きを年10%にそろえたあと）。"""
    w0 = weights(px, carry, **kw)
    outs = []
    r = px.pct_change()
    stress = (r.rolling(10, min_periods=8).std() / r.rolling(120, min_periods=80).std()).mean(axis=1)
    for ph in range(PH):
        w = hold_phase(w0, 5, ph)
        ws = w.mul(SL.exante_scale(w, px), axis=0)          # 建玉から見積もった値動きで、年10%にそろえる
        raw = SL.pnl(ws, px, carry, cost)
        on = pd.Series(1.0, index=px.index)
        if own_trend:
            # 手法そのものの過去 N 日の成績（休んでいるあいだも、仮想の成績で判断する）。前日までの値だけを使う
            on = (raw.rolling(own_trend, min_periods=own_trend // 2).sum().shift(1) > 0).astype(float)
        if risk_off:
            on = on * (stress.shift(1) <= risk_off).astype(float)
        if own_trend or risk_off:
            raw = SL.pnl(ws.mul(on, axis=0), px, carry, cost)
        outs.append(raw)
    return outs


def summarize(label, outs):
    avg = sum(outs) / len(outs)
    cells = []
    for _, a, b in SL.PER:
        ss = [SL.sharpe(o[(o.index >= a) & (o.index < b)]) for o in outs]
        cells.append(f"{np.mean(ss):+.2f}（{min(ss):+.1f}〜{max(ss):+.1f}）")
    x = avg[avg.index >= "2000-01-01"]
    x = x * (0.10 / (x.std() * np.sqrt(SL.ANN)))          # ずれの平均（5つに分けて持つ形）を、年10%の値動きにそろえる
    eq = (1 + x).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    yr = x.groupby(x.index.year).sum()
    return (f"| {label} | " + " | ".join(cells) + f" | {SL.sharpe(x):+.2f} | {x.mean() * SL.ANN * 100:+.1f}% | {dd * 100:.0f}% | "
            f"{yr.min() * 100:+.0f}%（{yr.idxmin()}） | {(yr > 0).sum()}/{len(yr)} |"), x


def main():
    px, carry, cost = SL.load()
    lines = ["# 長期の層：金利差の取り方の比較（27年分、`tools/research/carry_long.py`）", "",
             "各セル：年率シャープ。5通りの入れ替えのずれの平均（括弧内は、ずれによる最小〜最大）。",
             "右の5列は 2000年以降の全体（5つのずれに分けて持つ形）：シャープ、年率（値動き年10%）、最大の下落、最悪の年、プラスの年。", "",
             "| 形 | " + " | ".join(p[0] for p in SL.PER) + " | 全体 | 年率 | 最大の下落 | 最悪の年 | プラスの年 |",
             "|---|" + "---|" * (len(SL.PER) + 5)]
    keep = {}
    forms = [
        ("A1 金利差 1%以上・すべて", dict(thr=1.0)),
        ("A0 金利差 0%以上・すべて", dict(thr=0.0)),
        ("A2 金利差 2%以上・すべて", dict(thr=2.0)),
        ("B 金利差 1%以上・上位5つ", dict(thr=1.0, topk=5)),
        ("C60 トレンド60日が同じ向き", dict(thr=1.0, trend=60)),
        ("C60+ 今の EA の形（上位5つ・急変の回避）", dict(thr=1.0, trend=60, topk=5, crash=2.0)),
        ("C120 トレンド120日が同じ向き", dict(thr=1.0, trend=120)),
        ("C250 トレンド250日が同じ向き", dict(thr=1.0, trend=250)),
        ("A1＋急変の回避（ペアごと）", dict(thr=1.0, crash=2.0)),
        ("D60 手法の過去60日がマイナスなら休む", dict(thr=1.0, own_trend=60)),
        ("D120 手法の過去120日がマイナスなら休む", dict(thr=1.0, own_trend=120)),
        ("D250 手法の過去250日がマイナスなら休む", dict(thr=1.0, own_trend=250)),
        ("E1.3 為替全体の値動きが1.3倍超なら休む", dict(thr=1.0, risk_off=1.3)),
        ("E1.5 為替全体の値動きが1.5倍超なら休む", dict(thr=1.0, risk_off=1.5)),
        ("D120＋E1.5", dict(thr=1.0, own_trend=120, risk_off=1.5)),
        ("A0＋D120", dict(thr=0.0, own_trend=120)),
    ]
    for label, kw in forms:
        line, x = summarize(label, run(px, carry, cost, **kw))
        lines.append(line)
        keep[label.split(" ")[0]] = x
        print(line, flush=True)
    out = os.path.join(SL.ROOT, "reports", "research", "carry_long.md")
    # 年ごとの成績（主な形）
    cols = ["A1", "C60+", "C250", "D120", "E1.5"]
    yr = pd.DataFrame({c: keep[c].groupby(keep[c].index.year).sum() * 100 for c in cols}).round(1)
    lines += ["", "## 年ごとの成績（%、値動きを年10%にそろえたとき）", "", "| 年 | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for y, r_ in yr.iterrows():
        lines.append(f"| {y} | " + " | ".join(f"{v:+.1f}" for v in r_.values) + " |")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[-(len(yr) + 4):]))
    pd.DataFrame(keep).to_parquet(os.path.join(D.CACHE, "carry_long_returns.parquet"))


if __name__ == "__main__":
    main()

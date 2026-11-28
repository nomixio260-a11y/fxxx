#!/usr/bin/env python3
"""研究：指数の順張りの層は、VIX の期間の並びが逆転しているあいだ降りると、急落の損失が減るか（108章）。日付・時刻は使わない。

- きっかけ：急落の損失の約4割は、指数の順張りの層から出ている（107章）。「過去21日の値動きがマイナスなら降りる」形（107章の K1〜K3）は、降りるのが遅く、利益も削った。
  速い急落を、もっと早く知らせる指標として、VIX の期間の並びがある：ふだんは「30日先までの VIX ＜ 3か月先までの VIX（VIX3M）」だが、
  急落が始まると、数日のうちに逆転する（VIX ＞ VIX3M）。逆転しているあいだだけ順張りの層が降り、戻りの層（急落のあとの戻りを取る層）はそのまま、という分担を試す。
- 形（結果を見る前に決めた。これ以外は試さない）：
   T0 今の形：終値が200日の平均より上なら持つ（7日ごとに見直す）
   Q1 T0 に加えて、前の日の終値で VIX ＞ VIX3M なら、その日は持たない（毎日確かめる。逆転が終われば、T0 の状態に戻る）
   Q2 同じ条件で、半分だけ持つ
   Q3 逆転の判定に余裕を持たせる：VIX ÷ VIX3M ＞ 1.05 で降り、＜ 0.95 に戻るまで降りたまま（出入りの繰り返しを減らす）
- データ：現物の3指数と、VIX・VIX3M（CBOE の公表値。Yahoo Finance から取得。VIX3M のある 2007年〜）。戻りの層 5% ＋ 順張りの層 10%（NASDAQ100）。計算は trend_correction.py と同じ。
- 判定（trend_correction.py と同じ。結果を見る前に決めた）。今の形を置き換えるのは、同じ形が次をすべて満たすときだけ：
   (a) 戻りの層 ＋ 順張りの層の合計で、最大の下落を今の形にそろえたときの年率の伸びが、今の形より低くない
   (b) 同じくそろえたとき、急落の局面の損益の合計が、今の形より1割以上良い
   (c) 合計のシャープが、前半・後半の両方で今の形より低くない
   (d) 順張りの層の銘柄を S&P500・ダウに替えても、(b) が両方で成り立ち、(a) が少なくとも片方で成り立つ
使い方: python3 tools/research/trend_vix_term.py  → reports/research/trend_vix_term.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_stop as IS  # noqa: E402
import index_vix_sizing as V  # noqa: E402
import target300 as T  # noqa: E402
import trend_correction as TC  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
START = "2008-01-02"
FORMS = (("T0 今の形", "T0"), ("Q1 逆転しているあいだは持たない", "Q1"), ("Q2 逆転しているあいだは半分", "Q2"), ("Q3 1.05 で降り、0.95 まで戻らない", "Q3"))


def ratio(index):
    """その日足より前の日の終値での VIX ÷ VIX3M（その日の建玉を決めるのに使える値）。"""
    v = Y.fetch("VIX")["close"].dropna()
    v3 = Y.fetch_ticker("VIX3M", "^VIX3M")["close"].dropna()
    r = (v / v3).dropna()
    r = r.reindex(r.index.union(index)).ffill().shift(1)
    return r.reindex(index)


def trend_returns(sets, name, form, unit=10.0, check=7):
    d, n, sg, rate, div = sets[name]
    c = d["close"]
    slow = (c > c.rolling(200).mean()).values
    q = ratio(d.index).values
    st = np.zeros(len(d))
    last, cur, off = None, 0.0, False
    for i, t in enumerate(d.index):
        if i < 200:
            continue
        if last is None or (t - last).days >= check:
            cur, last = float(slow[i]), t
        # st[i] は、i の終値で決め、次の日に持つ建玉。使える逆転の判定は、i の終値の VIX（q[i+1] に入っている値）
        qq = q[i + 1] if i + 1 < len(q) else np.nan
        m = 1.0
        if not np.isnan(qq):
            if form == "Q1":
                m = 0.0 if qq > 1.0 else 1.0
            elif form == "Q2":
                m = 0.5 if qq > 1.0 else 1.0
            elif form == "Q3":
                if qq > 1.05:
                    off = True
                elif qq < 0.95:
                    off = False
                m = 0.0 if off else 1.0
        st[i] = cur * m
    w = (pd.Series(st, index=d.index) * unit / 100.0 / np.maximum(sg * np.sqrt(ANN), 0.025)).fillna(0.0)
    r, _, _ = IS.run(d, w, sg, rate, div, 4.0, "close")
    return r[r.index >= START], float((pd.Series(st, index=d.index)[d.index >= START] > 0).mean())


def main():
    sets = V.load_sets("cash")
    rev = T.cash_returns(5.0)
    rev = rev[rev.index >= START]
    lines = ["# 研究：指数の順張りの層が、VIX の期間の並びの逆転で降りる形（`tools/research/trend_vix_term.py`）", "",
             f"現物の3指数、{START}〜。戻りの層 5% ＋ 順張りの層 10%。コスト込み。", ""]
    res = {}
    for name in ("NASDAQ100", "S&P500", "ダウ"):
        lines += [f"## 順張りの層の銘柄：{name}", "",
                  "| 形 | 順張りの層だけ：持っていた日の割合 | 年率 | シャープ | 最大の下落 | 急落の局面の合計 | 合計：シャープ | 前半 | 後半 | 年率 | 最大の下落 | 下落をそろえた：年率 | 急落の局面の合計 | 最悪の年 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        base_dd = None
        for lab, form in FORMS:
            tr, share = trend_returns(sets, name, form)
            tot = pd.concat([rev, tr], axis=1, sort=True).fillna(0.0).sum(axis=1)
            s_tr, s = TC.stats(tr), TC.stats(tot)
            if form == "T0":
                base_dd = s["dd"]
            k, s2 = TC.at_same_dd(tot, base_dd)
            res[(name, form)] = dict(s=s, s2=s2)
            lines.append(f"| {lab} | {share * 100:.0f}% | {s_tr['cagr'] * 100:+.1f}% | {s_tr['sh']:+.2f} | {s_tr['dd'] * 100:.1f}% | {s_tr['ep'] * 100:+.1f}% | {s['sh']:+.2f} | {s['a']:+.2f} | {s['b']:+.2f} | "
                         f"{s['cagr'] * 100:+.1f}% | {s['dd'] * 100:.1f}% | {s2['cagr'] * 100:+.1f}%（×{k:.2f}） | {s2['ep'] * 100:+.1f}% | {s2['wy'] * 100:+.1f}% |")
            print(name, lines[-1], flush=True)
        lines.append("")
    lines += ["## 判定", "", "| 形 | (a) 下落をそろえた年率が低くない | (b) 急落の局面の合計が1割以上良い | (c) シャープが前半・後半とも低くない | (d) S&P500・ダウでも | 判定 |", "|---|---|---|---|---|---|"]
    for lab, form in FORMS[1:]:
        def chk(name):
            x, b = res[(name, form)], res[(name, "T0")]
            return (x["s2"]["cagr"] >= b["s2"]["cagr"], x["s2"]["ep"] >= b["s2"]["ep"] + 0.10 * abs(b["s2"]["ep"]), x["s"]["a"] >= b["s"]["a"] and x["s"]["b"] >= b["s"]["b"])
        a, b_, c = chk("NASDAQ100")
        o = [chk(n) for n in ("S&P500", "ダウ")]
        d = all(x[1] for x in o) and any(x[0] for x in o)
        lines.append(f"| {lab} | {'○' if a else '×'} | {'○' if b_ else '×'} | {'○' if c else '×'} | {'○' if d else '×'} | {'**合格**' if (a and b_ and c and d) else '不合格'} |")
        print(lines[-1], flush=True)
    open(os.path.join(F.ROOT, "reports", "research", "trend_vix_term.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

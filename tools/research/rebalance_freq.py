#!/usr/bin/env python3
"""研究：2つの口座（指数・金）のあいだで資金の割合を戻す頻度を上げると、同じ売買のまま、伸びが上がるか（108章）。日付・時刻は使わない。

- 考え方：互いに無関係で値動きの大きい2つの口座を、決めた割合に戻し続けると、「上がったほうを少し売り、下がったほうを少し買う」ことになり、
  2つの値動きのばらつきの分だけ、長期の伸び率が上がる（割合を戻すことの上乗せ ≈ w₁w₂(σ₁² + σ₂² − 2ρσ₁σ₂) ÷ 2。値動きが年 50% どうし・無相関・半分ずつなら 年 +6%）。
  ただし、片方の勝ちが何年も続く（金の順張りには、数年単位の効く時期・効かない時期がある）ときは、戻すほど、勝っている口座から資金を抜くことになる。
  どちらが勝つかは、データで確かめる。106章までは「年に1回」と「戻さない」しか比べていない。
- 形（結果を見る前に決めた。これ以外は試さない）。暦ではなく、取引日の数と、割合のずれで決める：
   N0 戻さない／N252 252取引日ごと（今の形にあたる）／N63 63取引日ごと／N21 21取引日ごと／N5 5取引日ごと
   B10 割合が目標から 10ポイント以上ずれたら戻す／B5 5ポイント以上ずれたら戻す
- 組み合わせ（106章の表と同じ3つ）：
   C1 指数（デモの既定）＋ 金（中）、半分ずつ／C2 指数（大きい設定）＋ 金（大）、半分ずつ／C3 指数（大きい設定）70% ＋ 金（最大）30%
- データ：106章と同じ（2007年1月〜2026年11月。金は MT5 の日々の資産、指数は 2019年11月から MT5・それより前は現物の写し）。資金の移動にコストはかからないものとする
  （OANDA の口座間の振替は無料。ただし手作業で、反映に時間がかかる。頻度が高い形は、その手間に見合うかも合わせて見る）。
- 判定（結果を見る前に決めた）。今の「年に1回」より頻度の高い形を勧めるのは、同じ形が次をすべて満たすときだけ：
   (a) 20年の年率が N252 より高く、最大の下落が N252 より深くない
   (b) 前半（2007〜16年）・後半（2017〜26年）の両方で、年率が N252 より低くない
   (c) (a)(b) が、3つの組み合わせのうち2つ以上で成り立つ
使い方: python3 tools/research/rebalance_freq.py  → reports/research/rebalance_freq.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import composite_20y as C20  # noqa: E402
import composite_accounts as CA  # noqa: E402
import fred_data as F  # noqa: E402
import index_trend_combo as ITC  # noqa: E402
import target300 as T  # noqa: E402

RULES = (("N0 戻さない", ("n", 0)), ("N252 252取引日ごと（今の形）", ("n", 252)), ("N63 63取引日ごと", ("n", 63)), ("N21 21取引日ごと", ("n", 21)), ("N5 5取引日ごと", ("n", 5)),
         ("B10 10ポイントずれたら", ("b", 0.10)), ("B5 5ポイントずれたら", ("b", 0.05)))


def mix(ri, rg, a, rule):
    """戻り値：資金全体の日々の損益、戻した回数。"""
    idx = ri.index.union(rg.index)
    ri, rg = ri.reindex(idx).fillna(0.0).values, rg.reindex(idx).fillna(0.0).values
    kind, par = rule
    vi, vg, prev, out, since, n = a, 1 - a, 1.0, np.zeros(len(idx)), 0, 0
    for t in range(len(idx)):
        vi, vg = vi * (1 + ri[t]), vg * (1 + rg[t])
        tot = vi + vg
        out[t] = tot / prev - 1
        prev = tot
        since += 1
        do = (kind == "n" and par > 0 and since >= par) or (kind == "b" and abs(vi / tot - a) >= par)
        if do:                                               # その日の終わりに戻す（次の日から新しい割合）
            vi, vg, since, n = a * tot, (1 - a) * tot, 0, n + 1
    return pd.Series(out, index=idx), n


def st(r):
    e = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    y = (1 + r).groupby(r.index.year).prod() - 1
    return dict(cagr=e.iloc[-1] ** (1 / yrs) - 1, dd=(e / e.cummax() - 1).min(), sh=r.mean() / r.std() * np.sqrt(252), wy=y.min(), by=y.max(), n300=int((y >= 3).sum()))


def main():
    cat = CA.catalog()
    E = {k: CA.rel(c) for k, c in cat.items()}
    rev = {u: T.cash_returns(u) for u in (5.0, 8.75)}
    tr = {u: ITC.trend_returns("NASDAQ100", u) for u in (10.0, 20.0)}
    rep = {"Index_Demo": rev[5.0].add(tr[10.0], fill_value=0.0), "Index_Growth": rev[8.75].add(tr[20.0], fill_value=0.0)}
    IDX = {}
    for name in rep:
        r, _, _, _ = C20.spliced(E[(name, 0.0, "long")], rep[name])
        IDX[name] = r[r.index >= C20.START]
    GOLD = {u: E[("金", u, "long")].pct_change().dropna() for u in (22.4, 33.6, 50.0)}
    GOLD = {u: v[v.index >= C20.START] for u, v in GOLD.items()}
    combos = (("C1 指数（デモの既定）＋ 金（中）、半分ずつ", IDX["Index_Demo"], GOLD[22.4], 0.5), ("C2 指数（大きい設定）＋ 金（大）、半分ずつ", IDX["Index_Growth"], GOLD[33.6], 0.5),
              ("C3 指数（大きい設定）70% ＋ 金（最大）30%", IDX["Index_Growth"], GOLD[50.0], 0.7))
    lines = ["# 研究：口座のあいだで資金の割合を戻す頻度（`tools/research/rebalance_freq.py`）", "", "2007年1月〜2026年11月。資金の移動のコストは 0 としている。", ""]
    ok_count = {lab: 0 for lab, _ in RULES}
    for clab, ri, rg, a in combos:
        lines += [f"## {clab}", "", "| 形 | 戻した回数 | 年率 | シャープ | 最大の下落 | 最悪の年 | 最高の年 | +300% 以上の年 | 前半の年率 | 後半の年率 |", "|---|---|---|---|---|---|---|---|---|---|"]
        res = {}
        for lab, rule in RULES:
            r, n = mix(ri, rg, a, rule)
            s = st(r)
            h1, h2 = st(r[r.index < "2017-01-01"]), st(r[r.index >= "2017-01-01"])
            res[lab] = (s, h1, h2)
            lines.append(f"| {lab} | {n} | {s['cagr'] * 100:+.1f}% | {s['sh']:.2f} | {s['dd'] * 100:.1f}% | {s['wy'] * 100:+.0f}% | {s['by'] * 100:+.0f}% | {s['n300']} | {h1['cagr'] * 100:+.1f}% | {h2['cagr'] * 100:+.1f}% |")
            print(clab[:2], lines[-1], flush=True)
        b = res[RULES[1][0]]
        for lab, _ in RULES[2:]:
            s, h1, h2 = res[lab]
            if s["cagr"] > b[0]["cagr"] and s["dd"] >= b[0]["dd"] and h1["cagr"] >= b[1]["cagr"] and h2["cagr"] >= b[2]["cagr"]:
                ok_count[lab] += 1
        lines.append("")
    lines += ["## 判定", "", "| 形 | (a)(b) を満たした組み合わせの数（3つのうち） | 判定（2つ以上で ○） |", "|---|---|---|"]
    for lab, _ in RULES[2:]:
        lines.append(f"| {lab} | {ok_count[lab]} | {'**○**' if ok_count[lab] >= 2 else '×'} |")
        print(lines[-1], flush=True)
    open(os.path.join(F.ROOT, "reports", "research", "rebalance_freq.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""研究：順張りの層の建玉を決める「値動きの見積もり」に下限を置くと、同じ利益で損失が小さくなるか（107章）。日付・時刻は使わない。

- きっかけ：trend_correction.py の V1（急落の損失を減らす形の候補の1つ）は、急落の基準（急落の局面の損失が1割以上減る）には届かなかったが、
  米国の3指数すべてで、順張りの層だけのシャープが上がり（+0.46 → +0.55、+0.31 → +0.43、+0.22 → +0.27）、最大の下落が浅くなった。
  ただし、この3指数は互いによく似た動きをするので、実質は1つの標本。しかも結果を見たあとなので、そのままでは採用できない。
  ここでは、問いを「同じ利益で損失が小さくなるか」に改め、基準を先に決めて、まだ見ていないデータで確かめる。
- 考え方：建玉を「目標の値動き ÷ 値動きの見積もり」で決めると、値動きが小さい時期（高値圏の静かな上昇）ほど建玉が大きくなる。
  急落はそこから始まるので、いちばん大きく持っているときに最初の下げを受ける。下限を置くと、静かな時期の建玉が、ふだんの大きさで止まる。
  文献（Harvey ほか 2018、Bongaerts ほか 2020）：値動きで建玉を決める方法の効き目は、値動きが大きいときに減らす側にあり、小さいときに増やす側にはほとんどない。
- 形（trend_correction.py の V1 と同じ。これ以外は試さない）：
   T0 今の形：建玉 ＝ 目標の値動き（年10%）÷ 値動きの見積もり
   V1 値動きの見積もりが、過去1500日の見積もりの中央値より低いときは、中央値を使う（500日たまるまでは、今の形のまま）
  持つ条件は同じ（終値が200日の平均より上、7日ごとに見直し、逆指値 4×σ）。
- データ（どれも、V1 をまだ試していないもの）：
   指数8つ：ラッセル2000・日経225・DAX・FTSE100・CAC40・ユーロ・ストックス50・ハンセン・ASX200（Yahoo Finance の現物の指数。
     値動きの見積もりは HAR 型、コストは CFD と同じ形＝片道 0.02%・その通貨の短期金利＋年2.5%。配当は入れていない）
   金・銀・銅：OANDA の商品CFDの口座の実際の日足（値動きの見積もりは直近60日、コストは口座の値。trend_signal.py と同じ計算）
- 判定（結果を見る前に決めた）。順張りの層に V1 を採用するのは、次をすべて満たすとき：
   (i)   シャープが T0 より高い銘柄が、11 のうち 8 以上
   (ii)  最大の下落（同じ建玉の大きさで）が T0 より浅い銘柄が、11 のうち 8 以上
   (iii) 最大の下落を T0 にそろえたときの年率の伸びが T0 より高い銘柄が、11 のうち 7 以上で、差の中央値がプラス
   (iv)  金（商品の口座の主力）は別に見る：最大の下落をそろえたときの年率の伸びが、前半・後半の両方で T0 より低くない。
         (i)〜(iii) を満たして (iv) だけ満たさないときは、指数の順張りの層にだけ採用する
  （効き目がないとき、(i) がたまたま満たされる確率は 11%。）
使い方: python3 -I tools/research/trend_vol_floor.py <商品の口座の書き出しのフォルダ>  → reports/research/trend_vol_floor.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_others as IO  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_stop as IS  # noqa: E402
import trend_signal as TS  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
INDICES = (("RUT", "USD"), ("N225", "JPY"), ("DAX", "EUR"), ("FTSE", "GBP"), ("CAC", "EUR"), ("STOXX", "EUR"), ("HSI", "USD"), ("ASX", "AUD"))
METALS = (("XAUUSD", "金"), ("XAGUSD", "銀"), ("COPPER", "銅"))
WIN, MINP = 1500, 500


def floored(sig):
    return np.maximum(sig, sig.rolling(WIN, min_periods=MINP).median().fillna(0.0))


def stats(r):
    r = r.dropna()
    e = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    return dict(sh=r.mean() / r.std() * np.sqrt(ANN) if r.std() > 0 else np.nan, cagr=e.iloc[-1] ** (1 / yrs) - 1, dd=(e / e.cummax() - 1).min())


def same_dd(r, dd0):
    lo, hi = 0.05, 20.0
    for _ in range(50):
        k = (lo + hi) / 2
        if stats(r * k)["dd"] < dd0:
            hi = k
        else:
            lo = k
    return stats(r * lo)["cagr"]


def pair(d, sigma, costs):
    """T0 と V1 の日々の損益（同じ期間。見積もりがそろってから）。"""
    state = TS.reviewed(TS.raw_signal(d["close"], "T0"))
    out = {}
    for form, sg in (("T0", sigma), ("V1", floored(sigma))):
        r, held, _ = TS.simulate(d, state, stop=4.0, sigma=sg.values, **costs)
        out[form] = (r.iloc[260:-1], held.iloc[260:-1])
    return out


def main():
    folder = sys.argv[1]
    rows = []
    for name, ccy in INDICES:
        d = Y.fetch(name)[["open", "high", "low", "close"]].dropna()
        d = d[(d["close"] > 0) & (d["high"] >= d["low"])]
        sg = IS.har_sigma(d)
        fin = (IR.short_rate(ccy, d.index) + IR.MARKUP).values
        rows.append((Y.TICKERS[name][1], pair(d, sg, dict(spread=2 * IR.COST, fin=fin))))
    data, props = IO.load(folder)
    for sym, lab in METALS:
        d = data[sym]
        costs = dict(spread=float(props.loc[sym, "spread_points"]) * float(props.loc[sym, "point"]) / float(props.loc[sym, "bid"]),
                     swap_long=float(props.loc[sym, "swap_long"]), swap_short=float(props.loc[sym, "swap_short"]))
        sg = d["close"].pct_change().rolling(60).std()
        rows.append((f"{lab}（OANDA）", pair(d, sg, costs)))
    lines = ["# 研究：順張りの層の建玉を決める値動きの見積もりに、下限を置く（`tools/research/trend_vol_floor.py`）", "",
             "T0 ＝ 今の形、V1 ＝ 見積もりが過去1500日の中央値より低いときは中央値を使う。建玉の目標は年10%、コスト込み。", "",
             "| 銘柄 | 期間 | T0：シャープ | V1：シャープ | T0：年率 | V1：年率 | T0：最大の下落 | V1：最大の下落 | 下落を T0 にそろえた V1 の年率 | 差（そろえた年率 − T0） | 建玉の平均（V1 ÷ T0） |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    n_sh = n_dd = n_cg = 0
    diffs = []
    gold = None
    for lab, o in rows:
        r0, h0 = o["T0"]
        r1, h1 = o["V1"]
        s0, s1 = stats(r0), stats(r1)
        c1 = same_dd(r1, s0["dd"])
        n_sh += int(s1["sh"] > s0["sh"])
        n_dd += int(s1["dd"] > s0["dd"])
        n_cg += int(c1 > s0["cagr"])
        diffs.append(c1 - s0["cagr"])
        lines.append(f"| {lab} | {r0.index[0].date()}〜{r0.index[-1].date()} | {s0['sh']:+.2f} | {s1['sh']:+.2f} | {s0['cagr'] * 100:+.1f}% | {s1['cagr'] * 100:+.1f}% | {s0['dd'] * 100:.1f}% | {s1['dd'] * 100:.1f}% | "
                     f"{c1 * 100:+.1f}% | {(c1 - s0['cagr']) * 100:+.2f}% | {h1[h1 > 0].mean() / h0[h0 > 0].mean():.2f} |")
        print(lines[-1], flush=True)
        if lab.startswith("金"):
            gold = (r0, r1)
    n = len(rows)
    med = float(np.median(diffs))
    i_ok, ii_ok, iii_ok = n_sh >= 8, n_dd >= 8, (n_cg >= 7 and med > 0)
    r0, r1 = gold
    mid = r0.index[len(r0) // 2]
    halves = []
    for lab, a, b in (("前半", r0.index[0], mid), ("後半", mid, r0.index[-1])):
        x0, x1 = r0[(r0.index >= a) & (r0.index <= b)], r1[(r1.index >= a) & (r1.index <= b)]
        s0 = stats(x0)
        halves.append((lab, s0["cagr"], same_dd(x1, s0["dd"]), s0["sh"], stats(x1)["sh"]))
    iv_ok = all(c1 >= c0 for _, c0, c1, _, _ in halves)
    lines += ["", "## 判定", "",
              f"- (i) シャープが高い銘柄：{n_sh} / {n}（8 以上で ○）→ {'○' if i_ok else '×'}",
              f"- (ii) 最大の下落が浅い銘柄：{n_dd} / {n}（8 以上で ○）→ {'○' if ii_ok else '×'}",
              f"- (iii) 下落をそろえた年率が高い銘柄：{n_cg} / {n}（7 以上で ○）、差の中央値 {med * 100:+.2f}% → {'○' if iii_ok else '×'}",
              "- (iv) 金：下落をそろえた年率（T0 → V1）と、シャープ：" + "、".join(f"{lab} {c0 * 100:+.1f}% → {c1 * 100:+.1f}%（シャープ {a:+.2f} → {b:+.2f}）" for lab, c0, c1, a, b in halves) + f" → {'○' if iv_ok else '×'}",
              f"- 判定：{'**合格**（金の層にも採用）' if (i_ok and ii_ok and iii_ok and iv_ok) else '**指数の順張りの層にだけ採用**' if (i_ok and ii_ok and iii_ok) else '不合格'}"]
    print("\n".join(lines[-5:]), flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "trend_vol_floor.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

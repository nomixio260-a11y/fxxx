#!/usr/bin/env python3
"""研究：戻りの層の建玉を決める「値動きの見積もり」にも下限を置くと、急落の損失が減るか（107章）。日付・時刻は使わない。

- きっかけ：順張りの層では、値動きの見積もりに下限を置く形（V1）が、まだ見ていない11銘柄で基準を通った（trend_vol_floor.py。最大の下落は11銘柄すべてで浅くなった）。
  高値からの急落は、値動きが小さい静かな時期から始まる。建玉を「目標 ÷ 値動きの見積もり」で決めていると、その時期の建玉がいちばん大きい。
  戻りの層は急落の損失の約6割を占めるので、同じ考え方が戻りの層でも成り立つなら、効き目は大きい。
- ただし、戻りの層にはすでに VIX の倍率（VIX が低い 1/3 のときは半分）がある。静かな時期の建玉は、すでに半分になっている。
  さらに下限を置くと減らしすぎになるかもしれない（静かな上昇相場の小さな押し目は、戻りの層の利益のかなりの部分を占める）。データで確かめる。
- 形（結果を見る前に決めた。これ以外は試さない）：
   今の形：建玉 ＝ 重み × 目標の値動き × VIX の倍率 ÷ 値動きの見積もり（HAR 型）
   F1：値動きの見積もりが、過去1500日の見積もりの中央値より低いときは、中央値を使う（順張りの層の V1 と同じ。500日たまるまでは今の形）
   F2：F1 の下限を「中央値の 0.75 倍」にゆるめた形（減らしすぎになる場合に備えた、弱い版）
- データ：実際に売買できた ETF（SPY 1993年〜・QQQ 1999年〜・DIA 1998年〜）。計算は stop_cooloff.py と同じ（EA と同じ形、判定は終値・売買は次の日の始値、
  逆指値 4×σ、コストは CFD と同じ形）。3本を同じ大きさで持った層を、2000年6月〜で比べる。
- 判定（結果を見る前に決めた）。採用するのは、同じ形が次をすべて満たすときだけ：
   (a) 3本の層のシャープが、前半・後半の両方で、今の形より低くない
   (b) 最大の下落を今の形にそろえたときの年率の伸びが、今の形より高い
   (c) 同じくそろえたとき、急落の局面（stop_cooloff.py と同じ一覧）の損益の合計が、今の形より1割以上良い
   (d) 3本のうち2本以上で、その ETF だけの層のシャープが今の形より低くない
使い方: python3 tools/research/rev_vol_floor.py  → reports/research/rev_vol_floor.md
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
import stop_cooloff as SC  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
FORMS = (("今の形", None), ("F1 下限＝過去1500日の中央値", 1.0), ("F2 下限＝中央値の 0.75 倍", 0.75))


def sleeve(name, floor):
    d = Y.fetch(name)[["open", "high", "low", "close"]].dropna()
    st = IR.rules(d)
    sg = IS.har_sigma(d)
    nst = (st["R2<10"] + st["D7"] + st["IBS"]).round()
    vm = V.mult_of(V.vix_rank(d.index)[0], (0.5, 1.0, 1.5))
    size = sg if floor is None else np.maximum(sg, floor * sg.rolling(1500, min_periods=500).median().fillna(0.0))
    w = (nst.map(lambda v: SC.W[int(v)]) * vm * (0.10 / (size * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
    r, _, _, _ = SC.run(d, w, nst, sg, IR.short_rate("USD", d.index), "none")
    return r.iloc[260:], w.iloc[260:]


def stats(r):
    e = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    mid = r.index[len(r) // 2]
    sh = lambda x: x.mean() / x.std() * np.sqrt(ANN)  # noqa: E731
    return dict(sh=sh(r), a=sh(r[r.index <= mid]), b=sh(r[r.index > mid]), cagr=e.iloc[-1] ** (1 / yrs) - 1, dd=(e / e.cummax() - 1).min(),
                ep=sum(float(np.prod(1 + r[(r.index > a) & (r.index <= b)]) - 1) for _, a, b in SC.EPISODES), wd=r.min())


def same_dd(r, dd0):
    lo, hi = 0.05, 20.0
    for _ in range(50):
        k = (lo + hi) / 2
        if stats(r * k)["dd"] < dd0:
            hi = k
        else:
            lo = k
    return stats(r * lo)


def main():
    lines = ["# 研究：戻りの層の値動きの見積もりに下限を置く（`tools/research/rev_vol_floor.py`）", "",
             "ETF（SPY・QQQ・DIA）を同じ大きさで持った戻りの層、2000年6月〜。コスト込み。建玉の大きさは、ルール3つのとき、その銘柄の値動きが年10%（3本の平均）。", "",
             "| 形 | シャープ | 前半 | 後半 | 年率 | 最大の下落 | 最悪の日 | 下落をそろえた：年率 | 急落の局面の合計 | 建玉の平均（今の形 = 1） | SPY | QQQ | DIA |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    base_w = None
    for lab, floor in FORMS:
        parts, ws, each = [], [], {}
        for name in SC.ETFS:
            r, w = sleeve(name, floor)
            parts.append(r)
            ws.append(w[w > 0].mean())
            each[name] = r.mean() / r.std() * np.sqrt(ANN)
        all3 = pd.concat(parts, axis=1, sort=True).fillna(0.0).mean(axis=1)
        all3 = all3[all3.index >= "2000-06-01"]
        s = stats(all3)
        if floor is None:
            base_w, base_dd = np.mean(ws), s["dd"]
        s2 = same_dd(all3, base_dd)
        res[lab] = dict(s=s, s2=s2, each=each)
        lines.append(f"| {lab} | {s['sh']:+.2f} | {s['a']:+.2f} | {s['b']:+.2f} | {s['cagr'] * 100:+.1f}% | {s['dd'] * 100:.1f}% | {s['wd'] * 100:.2f}% | {s2['cagr'] * 100:+.1f}% | {s2['ep'] * 100:+.1f}% | "
                     f"{np.mean(ws) / base_w:.2f} | " + " | ".join(f"{each[n]:+.2f}" for n in SC.ETFS) + " |")
        print(lines[-1], flush=True)
    lines += ["", "## 判定", "", "| 形 | (a) シャープが前半・後半とも低くない | (b) 下落をそろえた年率が高い | (c) 急落の局面の合計が1割以上良い | (d) 2本以上で低くない | 判定 |", "|---|---|---|---|---|---|"]
    b0 = res["今の形"]
    for lab, floor in FORMS[1:]:
        x = res[lab]
        a = x["s"]["a"] >= b0["s"]["a"] and x["s"]["b"] >= b0["s"]["b"]
        b = x["s2"]["cagr"] > b0["s2"]["cagr"]
        c = x["s2"]["ep"] >= b0["s2"]["ep"] + 0.10 * abs(b0["s2"]["ep"])
        dn = sum(x["each"][n] >= b0["each"][n] for n in SC.ETFS)
        ok = a and b and c and dn >= 2
        lines.append(f"| {lab} | {'○' if a else '×'} | {'○' if b else '×'} | {'○' if c else '×'} | {'○' if dn >= 2 else '×'}（{dn} / 3） | {'**合格**' if ok else '不合格'} |")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "rev_vol_floor.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

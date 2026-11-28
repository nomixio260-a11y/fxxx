#!/usr/bin/env python3
"""研究：指数の順張りの層は、「長い流れは上・短い流れは下」（調整の局面）で降りると、急落の損失が減るか（107章）。日付・時刻は使わない。

- きっかけ：急落の9局面の損失を層ごとに分けると、戻りの層が約6割、指数の順張りの層が約4割だった（107章）。順張りの層は、
  年率の伸びへの寄与が戻りの層の約3割しかないのに、急落の損失の約4割を占める。高値からの急落では、値段が200日の平均を割るまで
  何週間も買い持ちのままだからである。
- 文献：Goulding・Harvey・Mazzoleni（2023）「Momentum turning points」。長い流れ（12か月）と短い流れ（1か月）の向きで相場を4つに分け、
  2つの向きが食い違う局面（調整＝長い流れは上・短い流れは下、戻り＝その逆）では、持つ量を変えるのが良いと報告している。
  105章の T4 は「戻り」の局面で買いを足す形（不合格）。ここで試すのは逆側で、「調整」の局面で順張りの層が降りる形。
  調整の局面の押し目は、戻りの層（そのための層）が買うので、順張りの層は重ねて持たない、という分担になる。
- 形（結果を見る前に決めた。これ以外は試さない）。どれも買いだけ：
   T0 今の形：終値が200日の平均より上なら持つ（7日ごとに見直す）
   K1 上の条件に加えて、過去21日の値動きがプラスのときだけ持つ（7日ごとに見直す）
   K2 K1 と同じ。ただし、持っているあいだに過去21日の値動きがマイナスになったら、その日の終値で降りる（入り直しは、7日ごとの見直しで）
   K3 調整の局面（200日の平均より上・過去21日がマイナス）では半分だけ持つ（7日ごとに見直す）
   V1 T0 のまま、建玉を決める値動きの見積もりに下限を置く（過去1500日の見積もりの中央値より低いときは、中央値を使う）。
      値動きが小さい時期（＝高値圏。急落の始まる場所）に建玉が膨らむのを止める形（Harvey ほか 2018・Bongaerts ほか 2020：
      値動きで建玉を決める方法の効き目は、値動きが大きいときに減らす側にあり、小さいときに増やす側にはほとんどない）
- データ：現物の3指数（2000年10月〜2026年11月）。戻りの層は EA と同じ形（target300.py の cash_returns、建玉 5%）。
  順張りの層は NASDAQ100、建玉 10%（index_trend_combo.py と同じ計算。逆指値 4×σ、コストは CFD と同じ形）。
- 判定（結果を見る前に決めた）。今の形（T0）を置き換えるのは、同じ形が次をすべて満たすときだけ：
   (a) 戻りの層 ＋ 順張りの層の合計で、最大の下落を今の形にそろえたときの年率の伸びが、今の形より低くない（全期間）
   (b) 同じくそろえたとき、急落の局面（stop_cooloff.py と同じ11局面）の損益の合計が、今の形より1割以上良い
   (c) 合計のシャープが、前半・後半の両方で今の形より低くない
   (d) 順張りの層の銘柄を S&P500・ダウに替えても、(b) が両方で成り立ち、(a) が少なくとも片方で成り立つ
使い方: python3 tools/research/trend_correction.py  → reports/research/trend_correction.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_stop as IS  # noqa: E402
import index_vix_sizing as V  # noqa: E402
import stop_cooloff as SC  # noqa: E402
import target300 as T  # noqa: E402

ANN = 252
FORMS = (("T0 今の形", "T0"), ("K1 過去21日もプラスのときだけ", "K1"), ("K2 K1 ＋ マイナスになった日に降りる", "K2"), ("K3 調整の局面は半分", "K3"), ("V1 値動きの見積もりに下限", "V1"))
REV_UNIT, TREND_UNIT = 5.0, 10.0


def trend_returns(sets, name, form, unit=TREND_UNIT, check=7):
    """順張りの層の日々の損益（口座に対する割合）と、持っていた日の割合。"""
    d, n, sg, rate, div = sets[name]
    c = d["close"]
    slow = (c > c.rolling(200).mean()).values
    fast = (c / c.shift(21) - 1.0 > 0).values
    st = np.zeros(len(d))
    last, cur = None, 0.0
    for i, t in enumerate(d.index):
        if i < 200:
            continue
        review = last is None or (t - last).days >= check
        if form in ("T0", "V1"):
            if review:
                cur, last = float(slow[i]), t
        elif form == "K1":
            if review:
                cur, last = float(slow[i] and fast[i]), t
        elif form == "K2":
            if review:
                cur, last = float(slow[i] and fast[i]), t
            elif cur > 0 and not fast[i]:
                cur = 0.0
        elif form == "K3":
            if review:
                cur, last = (1.0 if (slow[i] and fast[i]) else 0.5 if slow[i] else 0.0), t
        st[i] = cur
    ann = sg * np.sqrt(ANN)
    if form == "V1":
        ann = np.maximum(ann, ann.rolling(1500, min_periods=500).median().fillna(0.0))
    w = (pd.Series(st, index=d.index) * unit / 100.0 / np.maximum(ann, 0.025)).fillna(0.0)
    r, _, _ = IS.run(d, w, sg, rate, div, 4.0, "close")
    keep = r.index >= IRK.START
    return r[keep], float((pd.Series(st, index=d.index)[keep] > 0).mean())


def stats(r):
    e = (1 + r).cumprod()
    y = (1 + r).groupby(r.index.year).prod() - 1
    mid = r.index[len(r) // 2]
    sh = lambda x: x.mean() / x.std() * np.sqrt(ANN) if x.std() > 0 else np.nan  # noqa: E731
    return dict(cagr=e.iloc[-1] ** (ANN / len(r)) - 1, sh=sh(r), a=sh(r[r.index <= mid]), b=sh(r[r.index > mid]), dd=(e / e.cummax() - 1).min(), wy=y.min(),
                ep=sum(float(np.prod(1 + r[(r.index > a) & (r.index <= b)]) - 1) for _, a, b in SC.EPISODES if pd.Timestamp(b) > r.index[0]))


def at_same_dd(r, dd0):
    """最大の下落が dd0 になる倍率を探して（2分法）、その倍率での成績を返す。"""
    lo, hi = 0.05, 20.0
    for _ in range(50):
        k = (lo + hi) / 2
        if stats(r * k)["dd"] < dd0:                  # 下落が深すぎる → 小さく
            hi = k
        else:
            lo = k
    return lo, stats(r * lo)


def main():
    sets = V.load_sets("cash")
    rev = T.cash_returns(REV_UNIT)
    lines = ["# 研究：指数の順張りの層が、調整の局面で降りる形（`tools/research/trend_correction.py`）", "",
             f"現物の3指数、{IRK.START[:7]}〜。戻りの層 {REV_UNIT:g}% ＋ 順張りの層 {TREND_UNIT:g}%。コスト込み。急落の局面は `stop_cooloff.py` と同じ一覧。", ""]
    res = {}
    for name in ("NASDAQ100", "S&P500", "ダウ"):
        if name not in sets:
            continue
        lines += [f"## 順張りの層の銘柄：{name}", "",
                  "| 形 | 順張りの層だけ：持っていた日の割合 | 年率 | シャープ | 最大の下落 | 急落の局面の合計 | 合計（戻り＋順張り）：シャープ | 前半 | 後半 | 年率 | 最大の下落 | "
                  "下落をそろえた：年率 | 急落の局面の合計 | 最悪の年 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        base_dd = None
        for lab, form in FORMS:
            tr, share = trend_returns(sets, name, form)
            z = pd.concat([rev, tr], axis=1, sort=True).fillna(0.0)
            tot = z.sum(axis=1)
            s_tr, s = stats(tr), stats(tot)
            if form == "T0":
                base_dd = s["dd"]
            k, s2 = at_same_dd(tot, base_dd)
            res[(name, form)] = dict(s=s, s2=s2, tr=s_tr)
            lines.append(f"| {lab} | {share * 100:.0f}% | {s_tr['cagr'] * 100:+.1f}% | {s_tr['sh']:+.2f} | {s_tr['dd'] * 100:.1f}% | {s_tr['ep'] * 100:+.1f}% | {s['sh']:+.2f} | {s['a']:+.2f} | {s['b']:+.2f} | "
                         f"{s['cagr'] * 100:+.1f}% | {s['dd'] * 100:.1f}% | {s2['cagr'] * 100:+.1f}%（×{k:.2f}） | {s2['ep'] * 100:+.1f}% | {s2['wy'] * 100:+.1f}% |")
            print(name, lines[-1], flush=True)
        s_rev = stats(rev)
        k, s2 = at_same_dd(rev, base_dd)
        lines += [f"| （参考）戻りの層だけ | — | — | — | — | — | {s_rev['sh']:+.2f} | {s_rev['a']:+.2f} | {s_rev['b']:+.2f} | {s_rev['cagr'] * 100:+.1f}% | {s_rev['dd'] * 100:.1f}% | "
                  f"{s2['cagr'] * 100:+.1f}%（×{k:.2f}） | {s2['ep'] * 100:+.1f}% | {s2['wy'] * 100:+.1f}% |", ""]
        print(name, lines[-2], flush=True)
    # ---------- 判定
    lines += ["## 判定", "", "| 形 | (a) 下落をそろえた年率が低くない | (b) 急落の局面の合計が1割以上良い | (c) シャープが前半・後半とも低くない | (d) S&P500・ダウでも | 判定 |", "|---|---|---|---|---|---|"]
    for lab, form in FORMS[1:]:
        def chk(name):
            x, b = res[(name, form)], res[(name, "T0")]
            return (x["s2"]["cagr"] >= b["s2"]["cagr"], x["s2"]["ep"] >= b["s2"]["ep"] + 0.10 * abs(b["s2"]["ep"]), x["s"]["a"] >= b["s"]["a"] and x["s"]["b"] >= b["s"]["b"])
        a, b_, c = chk("NASDAQ100")
        o = [chk(n) for n in ("S&P500", "ダウ")]
        d = all(x[1] for x in o) and any(x[0] for x in o)
        ok = a and b_ and c and d
        lines.append(f"| {lab} | {'○' if a else '×'} | {'○' if b_ else '×'} | {'○' if c else '×'} | {'○' if d else '×'} | {'**合格**' if ok else '不合格'} |")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "trend_correction.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

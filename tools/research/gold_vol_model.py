#!/usr/bin/env python3
"""研究：金の層の「翌日の値動きの大きさの見積もり」を、HAR 型に替えると良くなるか（105章）。日付・時刻は使わない。

- 今の形（M0）：直近60日の、終値から終値までの値動きの大きさ。
- 候補（M1）：指数の層と同じ HAR 型（当日・直近5日・直近22日の「値幅から計算した分散＋前の終値から始値までの動きの2乗」を、0.37・0.56・0.20 で足す。
  係数は、株価指数の先物（2000〜2018年）で決めたもの。金に合わせて決め直さない＝金のデータには当てはめていない）。
  EA は、入力（InpIxVolModel）の切り替えだけで対応できる。
- 値動きの大きさの見積もりは、建玉の大きさ（目標の値動き ÷ 見積もり）と、逆指値までの距離（4 × 見積もり）に使う。
- データ：金（XAUUSD）の、OANDA の実際の日足（2006年〜。注文を出さない観察で書き出したもの。リポジトリには入れていない）。
- 判定（結果を見る前に決めた）。M1 を採用するのは、次をすべて満たすときだけ：
   (a) 予測の当たり方（QLIKE。小さいほど良い）が、前半・後半の両方で M0 より良い
   (b) 金の層（200日の平均より上のあいだ買い持ち。逆指値 4×σ あり）のシャープが、前半・後半の両方で M0 より低くない
   (c) 最大の下落が M0 より深くなく、最悪の日が M0 より悪くない（同じ大きさで比べる。全期間）
使い方: python3 -I tools/research/gold_vol_model.py <商品の口座の書き出しのフォルダ>  → reports/research/gold_vol_model.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_others as IO  # noqa: E402
import index_stop as IS  # noqa: E402
import trend_signal as TS  # noqa: E402
import index_vol_forecast as VF  # noqa: E402


def main():
    folder = sys.argv[1]
    data, props = IO.load(folder)
    lines = ["# 研究：金の層の、値動きの大きさの見積もり（`tools/research/gold_vol_model.py`）", ""]
    for sym, name in (("XAUUSD", "金"), ("XAGUSD", "銀（参考。判定には使わない）")):
        d = data[sym]
        costs = dict(spread=float(props.loc[sym, "spread_points"]) * float(props.loc[sym, "point"]) / float(props.loc[sym, "bid"]),
                     swap_long=float(props.loc[sym, "swap_long"]), swap_short=float(props.loc[sym, "swap_short"]))
        m0 = d["close"].pct_change().rolling(60).std()
        m1 = IS.har_sigma(d)
        dv = VF.daily_var(d)                                    # その日の実際の分散（値幅＋前の終値からの動き）
        nxt = dv.shift(-1)
        start = d.index[560]
        mid = start + (d.index[-2] - start) / 2
        lines += [f"## {name}", "", "| 見積もり | QLIKE：前半 | 後半 | 見積もりと実際の相関（1日の標準偏差） | 層のシャープ：全期間 | 前半 | 後半 | 最大の下落 | 最悪の日 | 逆指値にかかった日（年） | 売買（年） |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        res = {}
        for lab, sg in (("M0 直近60日", m0), ("M1 HAR 型", m1)):
            f = (sg ** 2).where(sg > 0)
            x = (nxt / f).where(nxt > 0)
            ql = (x - np.log(x) - 1.0).replace([np.inf, -np.inf], np.nan)
            ql = ql[(ql.index >= start)].dropna()
            qa, qb = ql[ql.index <= mid].mean(), ql[ql.index > mid].mean()
            cr = pd.concat([sg, np.sqrt(nxt)], axis=1).dropna()
            cr = cr[cr.index >= start].corr().iloc[0, 1]
            state = TS.reviewed(TS.raw_signal(d["close"], "T0"))
            r, hd, tr = TS.simulate(d, state, stop=4.0, sigma=sg.values, **costs)
            hits = r.attrs["stops"]
            r = r[(r.index >= start)].iloc[:-1]
            a, b = TS.sh(r[r.index <= mid]), TS.sh(r[r.index > mid])
            res[lab] = dict(qa=qa, qb=qb, a=a, b=b, dd=TS.mdd(r), wd=r.min())
            lines.append(f"| {lab} | {qa:.3f} | {qb:.3f} | {cr:+.2f} | {TS.sh(r):+.2f} | {a:+.2f} | {b:+.2f} | {TS.mdd(r) * 100:.0f}% | {r.min() * 100:.2f}% | {hits / (len(d) / 252):.1f} | {tr / (len(d) / 252):.1f} |")
            print(lines[-1], flush=True)
        k0, k1 = res["M0 直近60日"], res["M1 HAR 型"]
        a = k1["qa"] < k0["qa"] and k1["qb"] < k0["qb"]
        b = k1["a"] >= k0["a"] and k1["b"] >= k0["b"]
        c = k1["dd"] >= k0["dd"] - 1e-9 and k1["wd"] >= k0["wd"] - 1e-9
        lines += ["", f"- (a) 予測の当たり方が前半・後半とも良い：{'○' if a else '×'}　(b) シャープが前半・後半とも低くない：{'○' if b else '×'}　(c) 最大の下落・最悪の日が悪くない：{'○' if c else '×'}"
                  + ("　→ 判定：" + ('**合格**' if (a and b and c) else '不合格') if sym == "XAUUSD" else ""), ""]
        print(lines[-2], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "gold_vol_model.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

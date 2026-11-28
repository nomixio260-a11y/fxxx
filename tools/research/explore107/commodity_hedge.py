"""下調べ：戻りの層を持っているあいだ、商品（銅・原油・銀・天然ガス）を売って保険にした場合（107章 2）。引数：商品の口座の書き出しのフォルダ。
事前に基準を決めた正式な検証ではない（結果は不採用。数字は reports/experiments.md の 107章）。日付・時刻は使わない。"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import index_others as IO  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_stop as IS  # noqa: E402
import index_vix_sizing as V  # noqa: E402
import lot_rounding as LR  # noqa: E402
import stop_cooloff as SC  # noqa: E402

ANN = 252
W = {0: 0.0, 1: 1.0, 2: 2.0, 3: 4.0}
COST_YEAR = 2.5                                             # 売りの建玉にかかる持ち越しコスト（年 %。業者の取り分。控えめに、受け取りはないものとする）


def layer(unit=5.0):
    """戻りの層の日々の損益と、持っている建玉の合計（資金に対する倍率。その日の値動きを受ける分）。"""
    sets = V.load_sets("cash")
    frac, need = {}, None
    for name, (d, n, sg, rate, div) in sets.items():
        vm = V.mult_of(V.vix_rank(d.index)[0], (0.5, 1.0, 1.5))
        f = (n.map(lambda v: W[int(v)]) * (unit / 100.0) * vm / np.maximum(sg * np.sqrt(ANN), 0.025)).fillna(0.0)
        frac[name] = f
        x = (f * (LR.SL * sg + LR.MRATE)).fillna(0.0)
        need = x if need is None else need.add(x, fill_value=0.0)
    scale = (LR.GUARD / need).clip(upper=1.0).where(need > 0, 1.0)
    parts, expo = [], None
    for name, (d, n, sg, rate, div) in sets.items():
        w = frac[name] * scale.reindex(d.index).fillna(1.0)
        r, _, _ = IS.run(d, w, sg, rate, div, LR.SL, "close")
        parts.append(r)
        e = w.shift(1).fillna(0.0)                          # 前の日の終値で決めた建玉が、きょうの値動きを受ける
        expo = e if expo is None else expo.add(e, fill_value=0.0)
    r = pd.concat(parts, axis=1, sort=True).fillna(0.0).sum(axis=1)
    return r[r.index >= IRK.START], expo[expo.index >= IRK.START]


def stats(r):
    e = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    mid = r.index[len(r) // 2]
    sh = lambda x: x.mean() / x.std() * np.sqrt(ANN)  # noqa: E731
    y = (1 + r).groupby(r.index.year).prod() - 1
    return dict(sh=sh(r), a=sh(r[r.index <= mid]), b=sh(r[r.index > mid]), cagr=e.iloc[-1] ** (1 / yrs) - 1, dd=(e / e.cummax() - 1).min(), wy=y.min(),
                ep=sum(float(np.prod(1 + r[(r.index > a) & (r.index <= b)]) - 1) for _, a, b in SC.EPISODES if pd.Timestamp(b) > r.index[0] and pd.Timestamp(a) >= r.index[0] - pd.Timedelta(days=40)))


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
    data, props = IO.load(sys.argv[1])
    rev, expo = layer()
    print("形 | シャープ（前半／後半） | 年率・最大の下落 | 下落をそろえた年率 | 急落の局面の合計 | 最悪の年 | 持っている日の、商品の値動きの平均（年率）・層の損益との相関")
    for sym in ("COPPER", "USOIL", "UKOIL", "XAGUSD", "NATGAS", "XAUUSD"):
        c = data[sym]["close"]
        cr = c.pct_change()
        z = pd.concat([rev, expo, cr], axis=1, sort=True).dropna()
        z.columns = ["r", "w", "c"]
        base = stats(z["r"])
        held = z[z["w"] > 0]
        print(f"== {sym}（{z.index[0].date()}〜{z.index[-1].date()}）。保険なし | {base['sh']:+.2f}（{base['a']:+.2f}／{base['b']:+.2f}） | {base['cagr'] * 100:+.1f}%・{base['dd'] * 100:.1f}% | — | {base['ep'] * 100:+.1f}% | {base['wy'] * 100:+.1f}% | "
              f"{(held['c'] * held['w']).sum() / held['w'].sum() * ANN * 100:+.1f}%・{held['r'].corr(held['c']):+.2f}")
        for h in (0.25, 0.5, 1.0):
            hedge = -h * z["w"] * z["c"] - h * z["w"] * COST_YEAR / 100.0 / 360.0 * 1.45
            tot = z["r"] + hedge
            s = stats(tot)
            s2 = same_dd(tot, base["dd"])
            print(f"   売り {h:g} 倍 | {s['sh']:+.2f}（{s['a']:+.2f}／{s['b']:+.2f}） | {s['cagr'] * 100:+.1f}%・{s['dd'] * 100:.1f}% | {s2['cagr'] * 100:+.1f}% | {s2['ep'] * 100:+.1f}% | {s2['wy'] * 100:+.1f}% |")


if __name__ == "__main__":
    main()

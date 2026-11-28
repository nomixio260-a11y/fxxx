"""下調べ：米国の指数（US500）に出た「売られすぎ」の合図で、ほかの指数を買う形（108章）。引数：指数の口座の書き出しのフォルダ。
事前に基準を決めた正式な検証ではない。日付・時刻は使わない。"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import index_others as IO  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_stop as IS  # noqa: E402
import index_vix_sizing as V  # noqa: E402

ANN = 252
W = IO.W


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 60 and x.std() > 0 else np.nan


def tv(x):
    return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 60 and x.std() > 0 else np.nan


def main():
    data, props = IO.load(sys.argv[1])
    us = {s: IO.sleeve(data[s], s, props)[0] for s in IO.US3}
    base = pd.concat(us.values(), axis=1, sort=True).fillna(0.0).mean(axis=1)
    mid = base.index[len(base) // 2]
    print(f"米国3指数の層（{base.index[0].date()}〜{base.index[-1].date()}）：シャープ {sh(base):+.2f}（前半 {sh(base[base.index <= mid]):+.2f}・後半 {sh(base[base.index > mid]):+.2f}）")
    # US500 の合図（ルールの数）と VIX の倍率
    d0 = data["US500"]
    st0 = IR.rules(d0)
    n0 = (st0["R2<10"] + st0["D7"] + st0["IBS"]).round()
    vm = V.mult_of(V.vix_rank(d0.index)[0], (0.5, 1.0, 1.5))
    print("銘柄 | 自分の合図：シャープ・t | 米国の合図：シャープ・t（前半／後半） | 米国の層との相関 | 4つ目に足した層のシャープ：前半・後半（米国だけ " + f"{sh(base[base.index <= mid]):+.2f}・{sh(base[base.index > mid]):+.2f}）")
    for sym in data:
        if sym in IO.US3:
            continue
        d = data[sym]
        own = IO.sleeve(d, sym, props)[0]
        sg = IS.har_sigma(d)
        n = n0.reindex(d.index).fillna(0.0)
        w = (n.map(lambda v: W[int(v)]) * vm.reindex(d.index).fillna(1.0) * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
        spread = float(props.loc[sym, "spread_points"]) * float(props.loc[sym, "point"]) / float(props.loc[sym, "bid"])
        # index_others.sleeve と同じ損益の計算（始値で売買、逆指値 4σ、スワップ）
        o, h, l, c = (d[x].values for x in ("open", "high", "low", "close"))
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0).values
        swap = float(props.loc[sym, "swap_long"]) / 100.0 / 360.0
        wv, s_ = w.values, sg.values
        out = np.zeros(len(d))
        carried = 0.0
        for t in range(2, len(d)):
            target = wv[t - 1]
            pnl = carried * (o[t] / c[t - 1] - 1.0 + swap * days[t]) - abs(target - carried) * spread / 2.0
            if target > 0 and not np.isnan(s_[t - 1]) and l[t] <= o[t] * (1.0 - 4.0 * s_[t - 1]):
                pnl += target * (-4.0 * s_[t - 1]) - target * spread / 2.0
                carried = 0.0
            else:
                pnl += target * (c[t] / o[t] - 1.0)
                carried = target
            out[t] = pnl
        r = pd.Series(out, index=d.index).iloc[260:]
        z = pd.concat([base, r], axis=1, sort=True).dropna()
        four = pd.concat(list(us.values()) + [r], axis=1, sort=True).fillna(0.0).mean(axis=1)
        four = four[four.index >= base.index[0]]
        print(f"{sym:8s} | {sh(own):+.2f}・{tv(own):+.1f} | {sh(r):+.2f}・{tv(r):+.1f}（{sh(r[r.index <= mid]):+.2f}／{sh(r[r.index > mid]):+.2f}） | {z.corr().iloc[0, 1]:+.2f} | "
              f"{sh(four[four.index <= mid]):+.2f}・{sh(four[four.index > mid]):+.2f}")


if __name__ == "__main__":
    main()

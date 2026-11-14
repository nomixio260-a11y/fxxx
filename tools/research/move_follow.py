#!/usr/bin/env python3
"""大きく動いた後、その動きは続くか・戻るか（週明けの窓のルール GW の考え方を、毎日に広げる）。

- 判断する時刻：東京 9:00（前日の NY 17:00 からの動き）、ロンドン 8:00（東京 9:00 からの動き）、
  NY 8:00（ロンドン 8:00 からの動き）
- 動きの大きさ：その動き ÷ 1時間足の平均値幅（24本）。設計期間の上位1/3（上げ）と下位1/3（下げ）を「大きい」とする。
- 大きい日に、同じ向き（続く）または逆向き（戻る）に入り、2 / 4 / 8 時間後に決済（コスト後）。
- 候補：設計期間で t ≥ 3、検証期間でコスト後プラス・PF ≥ 1.2。

使い方: python3 tools/research/move_follow.py  → reports/research/move_follow.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402


def st(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 30:
        return None
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return {"n": len(x), "mean": x.mean(), "pf": gp / gl if gl > 0 else 9.99, "t": x.mean() / x.std(ddof=1) * np.sqrt(len(x))}


def f(s):
    return "-" if s is None else f"{s['n']}回 {s['mean']:+.2f}pips PF {s['pf']:.2f} t {s['t']:.1f}"


def main():
    rows, n = [], 0
    for pair in D.PAIRS:
        df = D.bars(pair, "5min")
        o = df["o"]
        pip, cost = D.pip_size(pair), S.COST[pair]
        h1 = D.bars(pair, "1h")
        rng = (h1["h"] - h1["l"]).rolling(24).mean().shift(1)
        for clock, hh, back_name, back in (("tky", 9, "前日NY17時から", None), ("ldn", 8, "東京9時から", ("tky", 9)), ("ny", 8, "ロンドン8時から", ("ldn", 8))):
            t0 = df.index[(df[f"{clock}_h"].values == hh) & (df[f"{clock}_m"].values == 0)]
            if back is None:
                ny = t0.tz_localize("UTC").tz_convert("America/New_York")
                tb = ny.normalize() + pd.Timedelta(hours=17)
                tb = tb.where(tb < ny, tb - pd.Timedelta(days=1)).tz_convert("UTC").tz_localize(None)
            else:
                c2, h2 = back
                cand = df.index[(df[f"{c2}_h"].values == h2) & (df[f"{c2}_m"].values == 0)]
                tb = pd.DatetimeIndex([cand[cand < t][-1] if (cand < t).any() else pd.NaT for t in t0])
                tb = tb.where((t0 - tb) < pd.Timedelta(hours=20))
            a = rng.reindex(t0.floor("1h")).values / pip
            z = (o.reindex(t0).values - o.reindex(tb, method="ffill").values) / pip / a
            des, val = D.period_mask(t0, D.DESIGN), D.period_mask(t0, D.VALID)
            lo, hi = np.nanquantile(z[des], [1 / 3, 2 / 3])
            big = (z > hi) | (z <= lo)
            sgn = np.sign(z)
            for hold in (2, 4, 8):
                r = (o.reindex(t0 + pd.Timedelta(hours=hold)).values - o.reindex(t0).values) / pip
                for mode, k in (("続く", 1.0), ("戻る", -1.0)):
                    pnl = k * sgn * r - cost
                    n += 1
                    sd, sv = st(pnl[des & big]), st(pnl[val & big])
                    rows.append((pair, clock, hh, back_name, hold, mode, sd, sv))
        print(pair, "done", file=sys.stderr, flush=True)
    hits = [r for r in rows if r[6] and r[7] and r[6]["t"] >= 3 and r[7]["mean"] > 0 and r[7]["pf"] >= 1.2]
    out = ["# 大きく動いた後の続き・戻り（コスト後）", "", f"- 調べた仮説：{n} 通り", f"- 候補（設計 t ≥ 3、検証でプラス・PF ≥ 1.2）：{len(hits)} 通り", ""]
    out += [f"- {r[0]} {r[1]} {r[2]}:00（{r[3]}）{r[4]}時間 {r[5]}：設計 {f(r[6])} ／ 検証 {f(r[7])}" for r in hits]
    out += ["", "## すべて", "", "| ペア | 時刻 | 動き | 保有 | 向き | 設計 | 検証 |", "|---|---|---|---|---|---|---|"]
    out += [f"| {r[0]} | {r[1]} {r[2]}:00 | {r[3]} | {r[4]}時間 | {r[5]} | {f(r[6])} | {f(r[7])} |" for r in rows]
    text = "\n".join(out)
    open(os.path.join(D.ROOT, "reports", "research", "move_follow.md"), "w", encoding="utf-8").write(text + "\n")
    print("\n".join(out[:6 + len(hits)]))


if __name__ == "__main__":
    main()

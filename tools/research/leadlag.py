#!/usr/bin/env python3
"""株価指数の値動きが、その後の為替の動きに先行するかを調べる（1時間足）。

毎時（UTC）の始まりに、株価指数の直前 L 時間の値動きの向きを見て、為替ペアを H 時間持つ。
- 向き（指数が上げたら買うか売るか）は、2015〜2021/10 の相関の符号で決める（あとの期間では変えない）。
- 指数の動きが小さい日は除くため、|値動き| が直前100回の中央値以上のときだけ取引する。
- 日付の変わり目（NY 16:00〜18:59）にかかる取引は除く（売値だけのデータの見かけを避ける）。
評価：2015〜21/10・5年の前半（21/11〜24/10）・後半（24/11〜）のすべてで、コスト後プラス・PF ≥ 1.1。

使い方: python3 tools/research/leadlag.py  → reports/research/leadlag.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

INDICES = ["SPXUSD", "JPXJPY", "UKXGBP", "GRXEUR"]
PAIRS = ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "EURUSD", "GBPUSD"]
PERIODS = (("2015〜21/10", ("2015-01-01", "2021-11-01")), ("前半", ("2021-11-01", "2024-11-01")),
           ("後半", ("2024-11-01", "2026-11-14")))


def st(x):
    x = x[~np.isnan(x)]
    if len(x) < 40:
        return None
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return {"n": len(x), "mean": x.mean(), "pf": gp / gl if gl > 0 else 9.99, "t": x.mean() / x.std(ddof=1) * np.sqrt(len(x))}


def main():
    rows = []
    for ix in INDICES:
        io = np.log(D.bars(ix, "1h")["o"])
        for pair in PAIRS:
            b = D.bars(pair, "1h")
            po = b["o"]
            pip = D.pip_size(pair)
            cost = S.COST[pair]
            idx = po.index.intersection(io.index)
            ii = io.reindex(idx)
            pp = po.reindex(idx)
            nyh = b["ny_h"].reindex(idx).values
            utch = idx.hour
            s_idx = idx.to_series()
            for L in (1, 2, 4):
                past = (ii - ii.shift(L)).values
                okp = (idx - s_idx.shift(L)).values == np.timedelta64(L, "h")
                mag = pd.Series(np.abs(past)).rolling(100, min_periods=50).median().shift(1).values
                for H in (1, 2, 4):
                    fut = (pp.shift(-H) - pp).values / pip
                    okf = (s_idx.shift(-H) - idx).values == np.timedelta64(H, "h")
                    bad = np.zeros(len(idx), bool)
                    for k in range(-L, H + 1):
                        hh = np.roll(nyh, -k)
                        bad |= (hh >= 16) & (hh <= 18)
                    base = okp & okf & ~bad & ~np.isnan(past) & ~np.isnan(fut) & (np.abs(past) >= np.nan_to_num(mag, nan=np.inf))
                    des = D.period_mask(idx, PERIODS[0][1])
                    for h in range(24):
                        m = base & (utch == h)
                        x = np.sign(past[m & des]) * fut[m & des]
                        if len(x) < 40:
                            continue
                        d = 1.0 if x.mean() > 0 else -1.0     # 向きは最初の期間で決める
                        r = d * np.sign(past) * fut - cost
                        res = {pn: st(r[m & D.period_mask(idx, pr)]) for pn, pr in PERIODS}
                        rows.append((ix, pair, h, L, H, "同じ向き" if d > 0 else "逆向き", res))
        print(ix, "done", file=sys.stderr, flush=True)

    def good(s):
        return s is not None and s["mean"] > 0 and s["pf"] >= 1.1
    hits = [r for r in rows if all(good(r[6][pn]) for pn, _ in PERIODS) and r[6][PERIODS[0][0]]["t"] >= 2.5]
    hits.sort(key=lambda r: -min(r[6][pn]["t"] for pn, _ in PERIODS))

    def f(s):
        return "-" if s is None else f"{s['n']}回 {s['mean']:+.2f}pips PF {s['pf']:.2f} t {s['t']:.1f}"
    out = ["# 株価指数の動きが為替に先行するか（1時間足、コスト後 pips）", "",
           f"- 調べた組み合わせ：{len(rows)} 通り（指数4 × ペア6 × 時刻 UTC 24 × 過去 L 3 × 保有 H 3）",
           f"- 3つの期間すべてでプラス・PF ≥ 1.1、かつ最初の期間で t ≥ 2.5：{len(hits)} 通り", "",
           "| 指数 | ペア | 時刻(UTC) | 過去L | 保有H | 向き | " + " | ".join(pn for pn, _ in PERIODS) + " |",
           "|---|---|---|---|---|---|---|---|---|"]
    out += [f"| {r[0]} | {r[1]} | {r[2]}:00 | {r[3]} | {r[4]} | {r[5]} | " + " | ".join(f(r[6][pn]) for pn, _ in PERIODS) + " |" for r in hits]
    text = "\n".join(out) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "leadlag.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

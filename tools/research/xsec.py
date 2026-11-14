#!/usr/bin/env python3
"""通貨の強弱の順位（クロスセクション）による取引を調べる。

決まった時刻 T（UTC の毎時）に、7通貨（EUR・GBP・AUD・NZD・JPY・CAD・CHF）の対ドルの値動きを、
直前 L 時間で比べる。最も強かった通貨と最も弱かった通貨を選び、次の H 時間で
- 戻り（逆張り）：弱い通貨を買い、強い通貨を売る
- 続伸（順張り）：強い通貨を買い、弱い通貨を売る
の損益（%）を計算する。実際の取引は、その2通貨のクロス（例：EURJPY）1本で行う想定。
コスト：クロス1往復で 0.02%（2bp、やや高めの見積もり）。

評価：5年の前半（2021/11〜2024/10）と後半（2024/11〜）、さらに 2015〜2021/10 の3つの期間で、すべてプラス・PF ≥ 1.1。
使い方: python3 tools/research/xsec.py  → reports/research/xsec.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402

LEGS = {"EUR": ("EURUSD", 1), "GBP": ("GBPUSD", 1), "AUD": ("AUDUSD", 1), "NZD": ("NZDUSD", 1),
        "JPY": ("USDJPY", -1), "CAD": ("USDCAD", -1), "CHF": ("USDCHF", -1)}
COST = 0.0002
PERIODS = (("2015〜21/10", ("2015-01-01", "2021-11-01")), ("前半 21/11〜24/10", ("2021-11-01", "2024-11-01")),
           ("後半 24/11〜", ("2024-11-01", "2026-11-14")))


def log_prices():
    cols = {}
    for c, (pair, s) in LEGS.items():
        h = D.bars(pair, "1h")["o"]
        cols[c] = s * np.log(h)
    p = pd.DataFrame(cols).dropna()
    return p


def st(x):
    x = x[~np.isnan(x)]
    if len(x) < 50:
        return None
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return {"n": len(x), "mean": x.mean() * 1e4, "pf": gp / gl if gl > 0 else 9.99, "t": x.mean() / x.std(ddof=1) * np.sqrt(len(x))}


def main():
    p = log_prices()
    idx = p.index
    rows = []
    for L in (1, 2, 4, 8, 24):
        past = p - p.shift(L)
        # 連続した時間足だけ（週末をまたがない）
        okp = (idx - idx.to_series().shift(L)).values == np.timedelta64(L, "h")
        for H in (1, 2, 4, 8):
            fut = p.shift(-H) - p
            okf = (idx.to_series().shift(-H) - idx).values == np.timedelta64(H, "h")
            lo = past.values.argmin(axis=1)
            hi = past.values.argmax(axis=1)
            f = fut.values
            r_rev = f[np.arange(len(f)), lo] - f[np.arange(len(f)), hi]   # 弱い方を買い、強い方を売る
            valid = okp & okf & ~np.isnan(r_rev)
            for hour in range(24):
                m = valid & (idx.hour == hour)
                for name, sgn in (("戻り", 1), ("続伸", -1)):
                    r = sgn * r_rev - COST
                    res = {pn: st(r[m & D.period_mask(idx, pr)]) for pn, pr in PERIODS}
                    rows.append((hour, L, H, name, res))
    def good(s):
        return s is not None and s["mean"] > 0 and s["pf"] >= 1.1
    hits = [r for r in rows if all(good(r[4][pn]) for pn, _ in PERIODS)]
    hits.sort(key=lambda r: -min(r[4][pn]["t"] for pn, _ in PERIODS))
    def f(s):
        return "-" if s is None else f"{s['n']}回 {s['mean']:+.1f}bp PF {s['pf']:.2f} t {s['t']:.1f}"
    out = ["# 通貨の強弱の順位による取引（コスト後、1回あたり bp = 0.01%）", "",
           f"- 調べた組み合わせ：{len(rows)} 通り（判断の時刻 UTC 24 × 過去 L 5 × 保有 H 4 × 向き 2）",
           f"- 3つの期間すべてでプラス・PF ≥ 1.1：{len(hits)} 通り", "",
           "| 時刻(UTC) | 過去L時間 | 保有H時間 | 向き | " + " | ".join(pn for pn, _ in PERIODS) + " |", "|---|---|---|---|---|---|---|"]
    out += [f"| {r[0]}:00 | {r[1]} | {r[2]} | {r[3]} | " + " | ".join(f(r[4][pn]) for pn, _ in PERIODS) + " |" for r in hits]
    text = "\n".join(out) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "xsec.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

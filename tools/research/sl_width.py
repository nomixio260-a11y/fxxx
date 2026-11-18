#!/usr/bin/env python3
"""今の10ルールの損切りの幅を変えたときの成績（1分足の高値・安値で損切りに当たったかを判定、コスト +0.5 pips 込み、pips／回）。
時刻で決済するルールでは、損切りが一時的な逆行で取引を切り、偏りの分を取りこぼしている可能性がある。
- 入る時刻・日の条件・直前の値動きの条件（PRE30）・G3F の途中の見直し（CUT20:3）・A1 の 1分早い決済（EXS:60）は、今のプリセットと同じ。
- 損切りに当たった取引は、損切りの値で決済したとみなす（実際には滑ることがある）。
使い方: python3 tools/research/sl_width.py  → reports/research/sl_width.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PER = (("15-21", "2015-01-01", "2021-11-01"), ("前半", "2021-11-01", "2024-11-01"),
       ("後半", "2024-11-01", "2025-11-01"), ("直近1年", "2025-11-01", "2027-01-01"))
SLS = [15, 20, 25, 30, 40, 50, 70, None]
# 名前, 銘柄, 時計, 時, 分, 保有分, 向き, 日の条件, 今の損切り, PRE30 の条件（z の下限）, CUT（分, pips）, 早めの決済（秒）
RULES = [
    ("G3F", "USDJPY", "tky", 9, 55, 125, -1, "gotobi", 30, -0.07, (20, 3), 0),
    ("P2", "EURJPY", "tky", 9, 25, 30, 1, "gotobi", 20, None, None, 0),
    ("P4", "EURJPY", "tky", 9, 25, 30, 1, "fri_ng", 20, None, None, 0),
    ("Q2", "EURJPY", "tky", 9, 55, 125, -1, "gotobi", 25, 0.33, None, 0),
    ("C3", "EURJPY", "tky", 10, 0, 60, -1, "monthend", 25, None, None, 0),
    ("C4", "GBPJPY", "tky", 22, 0, 120, -1, "monthstart", 40, None, None, 0),
    ("A1", "EURUSD", "ldn", 11, 0, 120, -1, "weekday", 30, None, None, 60),
    ("C7", "USDJPY", "tky", 17, 0, 120, 1, "monthend", 30, None, None, 0),
    ("C6", "GBPJPY", "tky", 17, 0, 60, -1, "monthstart", 40, None, None, 0),
    ("P8", "USDJPY", "tky", 8, 0, 115, 1, "gotobi", 30, None, None, 0),
]


def entries(pair, clock, hh, mm, filt, pre_thr, sign):
    df = D.bars(pair, "5min")
    f = S.day_filters(df, clock)
    if filt == "fri_ng":
        m = f["dow4"] & ~S.day_filters(df, "tky")["gotobi"]
    elif filt == "weekday":
        m = f["all"] & (pd.DatetimeIndex(df[f"{clock}_date"]).dayofweek.values < 5)
    else:
        m = f[filt]
    t = df.index[(df[f"{clock}_h"].values == hh) & (df[f"{clock}_m"].values == mm) & m]
    if pre_thr is not None:
        h1 = D.bars(pair, "1h")
        rng = (h1["h"] - h1["l"]).rolling(24, min_periods=12).mean()
        atr = rng.reindex(t.floor("1h") - pd.Timedelta(hours=1)).values
        o = df["o"]
        z = (o.reindex(t).values - o.reindex(t - pd.Timedelta(minutes=30)).values) / atr
        t = t[z > pre_thr]
    return t


def simulate(m1, t, hold, sign, sl, cut, early, pip):
    """各取引の pips（コスト前）。sl は pips（None = 損切りなし）。"""
    idx = m1.index.values
    o, h, l = m1["o"].values, m1["h"].values, m1["l"].values
    out = np.full(len(t), np.nan)
    hit = np.zeros(len(t), bool)
    for i, ts in enumerate(t.values):
        a = np.searchsorted(idx, ts)
        if a >= len(idx) or idx[a] != ts:
            continue
        p0 = o[a]
        end_t = ts + np.timedelta64(hold * 60 - early, "s")
        segs = []
        if cut:
            segs.append((ts, ts + np.timedelta64(cut[0], "m"), cut[1]))
            segs.append((ts + np.timedelta64(cut[0], "m"), end_t, None))
        else:
            segs.append((ts, end_t, None))
        res = None
        for s0, s1, need in segs:
            b0, b1 = np.searchsorted(idx, s0), np.searchsorted(idx, s1)
            if b1 <= b0:
                break
            if sl is not None:
                adv = (h[b0:b1].max() - p0) / pip if sign < 0 else (p0 - l[b0:b1].min()) / pip
                if adv >= sl:
                    res = -float(sl); hit[i] = True
                    break
            # 区切りの時刻の価格（その分の足の始値。早めの決済は秒単位なので直前の足の終値で近似）
            px = o[b1] if (b1 < len(idx) and idx[b1] == s1) else m1["c"].values[b1 - 1]
            g = sign * (px - p0) / pip
            if need is not None and g < need:
                res = g
                break
            res = g
        out[i] = res if res is not None else np.nan
    return out, hit


def main():
    lines = ["# 損切りの幅を変えたときの成績（1分足、コスト +0.5 pips 込み、pips／回）", "",
             "各セル：平均 pips（損切りに当たった割合）。「なし」は損切りを置かない場合。太字は今の幅。", ""]
    m1c = {}
    for name, pair, clock, hh, mm, hold, sign, filt, sl0, pre, cut, early in RULES:
        if pair not in m1c:
            m1c[pair] = pd.read_parquet(os.path.join(D.CACHE, f"{pair}_M1.parquet"))
        m1 = m1c[pair]
        pip, cost = D.pip_size(pair), S.COST[pair] + 0.5
        t = entries(pair, clock, hh, mm, filt, pre, sign)
        lines += [f"## {name}（{pair}、今の損切り {sl0} pips、{len(t)} 回）", "",
                  "| 損切り | " + " | ".join(p[0] for p in PER) + " | 全体 | 最悪の1回 | プラスの年 |", "|---|" + "---|" * (len(PER) + 3)]
        for sl in SLS:
            r, hit = simulate(m1, t, hold, sign, sl, cut, early, pip)
            s = pd.Series(r - cost, index=t).dropna()
            hs = pd.Series(hit, index=t)[s.index]
            cells = []
            for _, a, b in PER:
                x = s[(s.index >= a) & (s.index < b)]
                hx = hs[(hs.index >= a) & (hs.index < b)]
                cells.append(f"{x.mean():+.2f}（{hx.mean() * 100:.0f}%）")
            yr = s.groupby(s.index.year).sum()
            lab = "なし" if sl is None else f"{sl}"
            if sl == sl0:
                lab = f"**{lab}**"
            lines.append(f"| {lab} | " + " | ".join(cells) + f" | {s.mean():+.2f} | {s.min():+.1f} | {(yr > 0).sum()}/{len(yr)} |")
        lines.append("")
        print(f"{name} done", flush=True)
    out = os.path.join(ROOT, "reports", "research", "sl_width.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

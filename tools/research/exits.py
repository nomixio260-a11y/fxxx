#!/usr/bin/env python3
"""今の6ルールの「決済の仕方」を変えて、負けを減らせるかを1分足で調べる。

ルール（推奨プリセットと同じ。すべてクロス円なので、pips をそのまま足し合わせられる）：
  G3F USDJPY 東京9:55 125分 売り ゴトー日 SL30 仲値前30分 > -0.07ATR
  P2  EURJPY 東京9:25 30分 買い ゴトー日 SL20
  P4  EURJPY 東京9:25 30分 買い 金曜（ゴトー日は P2 が優先）SL20
  Q2  EURJPY 東京9:55 125分 売り ゴトー日 SL25 仲値前30分 > 0.33ATR
  C3  EURJPY 東京10:00 60分 売り 月末 SL25
  C4  GBPJPY 東京22:00 120分 売り 月初2営業日 SL40
決済の形（ATR = 1時間足の平均値幅、pips）：
  時間で決済（今の形）／建値ストップ／トレーリング／途中で負けていたら切る／半分を早めに利確／
  損切りを狭める／勝っているときは保有を延ばす
同じ1分足の中で損切りと利確の両方に届いたら、損切りとみなす。
評価：3期間（設計・検証・2024年11月〜）の1回あたりの pips、PF、勝率、6ルール合計の月ごとの pips がマイナスの月の割合。

使い方: python3 tools/research/exits.py  → reports/research/exits.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

RULES = [  # 名前, 銘柄, 時, 分, 保有分, 向き, 日, SL, PRE30 の下限
    ("G3F", "USDJPY", 9, 55, 125, -1, "gotobi", 30, -0.07),
    ("P2", "EURJPY", 9, 25, 30, 1, "gotobi", 20, None),
    ("P4", "EURJPY", 9, 25, 30, 1, "fri_not_gotobi", 20, None),
    ("Q2", "EURJPY", 9, 55, 125, -1, "gotobi", 25, 0.33),
    ("C3", "EURJPY", 10, 0, 60, -1, "monthend", 25, None),
    ("C4", "GBPJPY", 22, 0, 120, -1, "monthstart", 40, None),
]


def entries(pair, hh, mm, day, pre_thr):
    df = D.bars(pair, "5min")
    t = df.index[(df["tky_h"].values == hh) & (df["tky_m"].values == mm)]
    dates = pd.DatetimeIndex(df.loc[t, "tky_date"])
    f = S.day_filters(df.loc[t], "tky")
    got = S.gotobi_mask(dates)
    m = {"gotobi": got, "fri_not_gotobi": (dates.dayofweek == 4) & ~got,
         "monthend": f["monthend"], "monthstart": f["monthstart"]}[day]
    t = t[m]
    h1 = D.bars(pair, "1h")
    pip = D.pip_size(pair)
    a = ((h1["h"] - h1["l"]).rolling(24).mean().shift(1) / pip).reindex(t.floor("1h")).values
    if pre_thr is not None:
        o = df["o"]
        pre = (o.reindex(t).values - o.reindex(t - pd.Timedelta(minutes=30)).values) / pip / a
        keep = pre > pre_thr
        t, a = t[keep], a[keep]
    return t, a


def run(path_o, path_h, path_l, end_px, d, sl, a, v):
    """1回分の取引。値は入値からの pips（d=向き）。v = 決済の形。"""
    kind = v[0]
    stop = -sl
    if kind == "slk":
        stop = -min(sl, v[1] * a)
    n = len(path_o)
    half_done, half_pnl = False, 0.0
    best = 0.0
    for k in range(n):
        worst = (path_l[k] if d > 0 else -path_h[k])   # 不利な側の極値（pips、入値基準）
        bestk = (path_h[k] if d > 0 else -path_l[k])   # 有利な側の極値
        if worst <= stop:
            out = stop
            return (out if not half_done else 0.5 * out + half_pnl)
        if kind == "half" and not half_done and bestk >= v[1] * a:
            half_done, half_pnl = True, 0.5 * v[1] * a
        best = max(best, bestk)
        if kind == "be" and best >= v[1] * a:
            stop = max(stop, 0.5)
        if kind in ("trail", "ext") and best >= v[1] * a:
            stop = max(stop, best - v[2] * a)
        if kind == "cut" and k == n // 2:
            cur = path_o[k] if d > 0 else -path_o[k]
            if cur < -v[1] * a:
                return cur if not half_done else 0.5 * cur + half_pnl
    out = end_px if d > 0 else -end_px
    return out if not half_done else 0.5 * out + half_pnl


VARIANTS = [("時間で決済（今）", ("base",)),
            ("建値ストップ 0.3ATR", ("be", 0.3)), ("建値ストップ 0.6ATR", ("be", 0.6)),
            ("トレーリング 開始0.5・幅0.5ATR", ("trail", 0.5, 0.5)), ("トレーリング 開始1.0・幅0.7ATR", ("trail", 1.0, 0.7)),
            ("途中で -0.2ATR 以下なら切る", ("cut", 0.2)), ("途中で負けていたら切る", ("cut", 0.0)),
            ("半分を +0.3ATR で利確", ("half", 0.3)), ("半分を +0.6ATR で利確", ("half", 0.6)),
            ("損切りを 0.7ATR まで狭める", ("slk", 0.7)), ("損切りを 1.0ATR まで狭める", ("slk", 1.0)),
            ("勝っていれば最大2倍まで延長（幅0.5ATR）", ("ext", 0.0, 0.5))]


def main():
    res = {}  # (variant, rule) -> Series(pips, index=entry time)
    for name, pair, hh, mm, hold, d, day, sl, pre in RULES:
        m1 = D.load_m1(pair)
        idx = m1.index.values
        O, H, L = m1["o"].values, m1["h"].values, m1["l"].values
        pip = D.pip_size(pair)
        cost = S.COST[pair]
        t, a = entries(pair, hh, mm, day, pre)
        for lab, v in VARIANTS:
            out = []
            for ti, ai in zip(t, a):
                if np.isnan(ai):
                    out.append(np.nan)
                    continue
                hold2 = hold * 2 if v[0] == "ext" else hold
                i0 = np.searchsorted(idx, np.datetime64(ti))
                i1 = np.searchsorted(idx, np.datetime64(ti + pd.Timedelta(minutes=hold2)))
                i_end = np.searchsorted(idx, np.datetime64(ti + pd.Timedelta(minutes=hold)))
                if i0 >= len(idx) or idx[i0] != np.datetime64(ti) or i_end >= len(idx):
                    out.append(np.nan)
                    continue
                e = O[i0]
                po = (O[i0:i1] - e) / pip
                ph = (H[i0:i1] - e) / pip
                pl = (L[i0:i1] - e) / pip
                if v[0] == "ext":
                    # 本来の終わりで負けていれば、そこで終える。勝っていれば、トレーリングで最大2倍まで持つ
                    base_end = (O[i_end] - e) / pip
                    r0 = run(po[:i_end - i0], ph[:i_end - i0], pl[:i_end - i0], base_end, d, sl, ai, ("base",))
                    if r0 == (base_end if d > 0 else -base_end) and r0 > 0:
                        # 本来の終わりの時点から、そこでの損益 - 0.5ATR を損切りにしてトレーリングする
                        k0 = i_end - i0
                        stop, best, r = r0 - v[2] * ai, r0, None
                        for k in range(k0, len(po)):
                            worst = pl[k] if d > 0 else -ph[k]
                            if worst <= stop:
                                r = stop
                                break
                            best = max(best, ph[k] if d > 0 else -pl[k])
                            stop = max(stop, best - v[2] * ai)
                        if r is None:
                            end2 = (O[min(i1, len(O) - 1)] - e) / pip
                            r = end2 if d > 0 else -end2
                    else:
                        r = r0
                else:
                    r = run(po, ph, pl, (O[i_end] - e) / pip, d, sl, ai, v)
                out.append(r - cost)
            res[(lab, name)] = pd.Series(out, index=t)
        print(name, "done", file=sys.stderr, flush=True)
    periods = (("設計", D.DESIGN), ("検証", D.VALID), ("2024/11〜", D.FINAL))

    def st(x):
        x = x[~np.isnan(x)]
        if len(x) == 0:
            return "-"
        gp, gl = x[x > 0].sum(), -x[x < 0].sum()
        return f"{x.mean():+.2f} / PF {gp / gl if gl > 0 else 9.99:.2f} / 勝率{(x > 0).mean() * 100:.0f}%"
    lines = ["# 決済の仕方を変えたときの成績（1分足、コスト後、1回あたりの pips）", "",
             "6ルール合計：1回あたりの pips ／ PF ／ 勝率、合計 pips、月ごとの合計がマイナスの月の割合。", "",
             "| 決済の形 | " + " | ".join(p for p, _ in periods) + " |", "|---|---|---|---|"]
    detail = []
    for lab, v in VARIANTS:
        cells = []
        allr = pd.concat([res[(lab, r[0])] for r in RULES]).sort_index()
        for pn, pr in periods:
            x = allr[D.period_mask(allr.index, pr)].dropna()
            mon = x.groupby(x.index.to_period("M")).sum()
            cells.append(f"{st(x.values)} / 計{x.sum():+.0f} / 負け月{(mon < 0).mean() * 100:.0f}%")
        lines.append(f"| {lab} | " + " | ".join(cells) + " |")
        for r in RULES:
            s = res[(lab, r[0])]
            detail.append(f"| {r[0]} | {lab} | " + " | ".join(st(s[D.period_mask(s.index, pr)].values) for _, pr in periods) + " |")
    lines += ["", "## ルールごと", "", "| ルール | 決済の形 | " + " | ".join(p for p, _ in periods) + " |", "|---|---|---|---|---|"]
    lines += sorted(detail, key=lambda s: s.split("|")[1])
    text = "\n".join(lines) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "exits.md"), "w", encoding="utf-8").write(text)
    print("\n".join(lines[:6 + len(VARIANTS)]))


if __name__ == "__main__":
    main()

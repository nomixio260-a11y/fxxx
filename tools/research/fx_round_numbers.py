#!/usr/bin/env python3
"""研究（FX だけで取引する）：キリのよい値段（00・50）で、値動きが反転しやすいか。日付・曜日・時刻は使わない。

- 為替では、利益確定の注文がキリのよい値段に集まり、そこで値動きが止まりやすい、という研究がある（Osler 2000年・2003年）。
  もし今も成り立ち、スプレッドを超える大きさなら、「キリのよい値段に指値を置いて、反転を取る」という、注文の集まり方にもとづく取引になる。
- 確かめ方（1分足、17ペア、2010年〜2026年10月）：
  値段が、直前の60分は触れていなかった水準 L に、10 pips 以上離れたところから近づいて初めて触れたとき、L で逆向きに入る（上から来たら買い、下から来たら売り）。
  15分・60分・240分後に成行で手じまう。スプレッド（S.COST + 0.25 pips）を引く。
  L がキリのよい値段（50 pips 刻み：xx.00・xx.50）の場合と、キリの悪い値段（13 pips・37 pips ずらした水準）の場合を比べる。
  キリのよい値段だけが良ければ、注文の集まりの効果。どちらも同じなら、ただの「行き過ぎの戻り」（89章で、コストに負けると確認済み）。
使い方: python3 tools/research/fx_round_numbers.py  → reports/research/fx_round_numbers.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
import fred_data as F  # noqa: E402
import index_reversion_cfd as IC  # noqa: E402

PAIRS = ["USDJPY", "EURUSD", "EURJPY", "GBPJPY", "AUDJPY", "GBPUSD", "AUDCAD", "AUDNZD", "AUDUSD", "CADJPY", "CHFJPY", "EURGBP", "NZDCAD",
         "NZDJPY", "NZDUSD", "USDCAD", "USDCHF"]
HOLDS = (15, 60, 240)
STEP, APPROACH, QUIET = 50, 10, 60
GRIDS = {"キリのよい値段（00・50）": (0,), "キリの悪い値段（13・37 pips ずらし）": (13, 37)}
PER = (("2010〜2014", "2010-01-01", "2015-01-01"), ("2015〜2019", "2015-01-01", "2020-01-01"), ("2020〜2023", "2020-01-01", "2024-01-01"),
       ("2024〜26/10", "2024-01-01", "2026-12-01"))


def events(m, pip, off):
    """上から・下から、水準に初めて触れた足と、そのときの水準。戻り値：DataFrame（t の位置, 向き(+1=買い), 水準）。"""
    h, l, c = m["h"].values, m["l"].values, m["c"].values
    step = STEP * pip
    o = off * pip
    pc = np.roll(c, 1)
    pc[0] = c[0]
    up = (np.floor((pc - o) / step) + 1) * step + o               # 直前の終値より上の、最初の水準
    dn = (np.ceil((pc - o) / step) - 1) * step + o                # 直前の終値より下の、最初の水準
    hs, ls = pd.Series(h), pd.Series(l)
    rmax = hs.rolling(QUIET).max().shift(1).values
    rmin = ls.rolling(QUIET).min().shift(1).values
    e_up = (h >= up) & (rmax < up) & (rmin <= up - APPROACH * pip)              # 下から来て触れた → 売り
    e_dn = (l <= dn) & (rmin > dn) & (rmax >= dn + APPROACH * pip)              # 上から来て触れた → 買い
    iu, idn = np.where(e_up)[0], np.where(e_dn)[0]
    return (np.concatenate([iu, idn]), np.concatenate([-np.ones(len(iu)), np.ones(len(idn))]), np.concatenate([up[iu], dn[idn]]))


def main():
    rows = []
    for pair in PAIRS:
        m = IC.load_any(pair)
        if m is None:
            continue
        pip = D.pip_size(pair)
        cost = S.COST.get(pair, 2.0) + 0.25
        c = m["c"].values
        t_index = m.index
        gap_ok = pd.Series(t_index).diff().dt.total_seconds().fillna(60).values       # 週末・欠落をまたぐ足は使わない
        for gname, offs in GRIDS.items():
            for off in offs:
                idx, sgn, lvl = events(m, pip, off)
                for H in HOLDS:
                    ok = idx + H < len(c)
                    i2 = idx[ok] + H
                    span = (t_index[i2] - t_index[idx[ok]]).total_seconds() / 60.0
                    good = span <= H * 3 + 30                                         # 途中に大きな欠落（週末など）がないものだけ
                    pnl = sgn[ok] * (c[i2] - lvl[ok]) / pip - cost
                    rows.append(pd.DataFrame({"pair": pair, "grid": gname, "H": H, "t": t_index[idx[ok]][good], "pnl": pnl[good]}))
        print(pair, "done", flush=True)
    df = pd.concat(rows, ignore_index=True)
    lines = ["# 研究：キリのよい値段での反転（取引は為替だけ。`tools/research/fx_round_numbers.py`）", "",
             f"17ペア、1分足、2010年〜2026年10月。水準に、{APPROACH} pips 以上離れたところから近づいて、{QUIET} 分ぶりに触れたとき、その水準で逆向きに入る。スプレッド込み。",
             "各セル：取引1回の平均（pips）と t 値（日ごとの合計で計算）。", "",
             "| 水準 | 持つ時間 | 取引数 | 1回の平均（pips） | t 値 | " + " | ".join(p[0] for p in PER) + " |", "|---|---|---|---|---|" + "---|" * len(PER)]

    def tstat(x):
        d = x.groupby(x["t"].dt.normalize())["pnl"].sum()
        return d.mean() / d.std() * np.sqrt(len(d)) if len(d) > 5 and d.std() > 0 else np.nan
    summ = {}
    for gname in GRIDS:
        for H in HOLDS:
            x = df[(df["grid"] == gname) & (df["H"] == H)]
            cells = [f"{x[(x['t'] >= a) & (x['t'] < b)]['pnl'].mean():+.2f}" for _, a, b in PER]
            lines.append(f"| {gname} | {H}分 | {len(x)} | {x['pnl'].mean():+.2f} | {tstat(x):+.1f} | " + " | ".join(cells) + " |")
            summ[(gname, H)] = x
    lines += ["", "## キリのよい値段 と キリの悪い値段 の差（1回の平均、pips）", "", "| 持つ時間 | 差 | 差の t 値 |", "|---|---|---|"]
    g0, g1 = list(GRIDS)
    for H in HOLDS:
        a, b = summ[(g0, H)]["pnl"], summ[(g1, H)]["pnl"]
        t = (a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b))
        lines.append(f"| {H}分 | {a.mean() - b.mean():+.2f} | {t:+.1f} |")
    lines += ["", "## ペアごと（キリのよい値段、60分）", "", "| ペア | 取引数 | 1回の平均（pips） | t 値 |", "|---|---|---|---|"]
    x60 = summ[(g0, 60)]
    for pair in PAIRS:
        x = x60[x60["pair"] == pair]
        if len(x):
            lines.append(f"| {pair} | {len(x)} | {x['pnl'].mean():+.2f} | {tstat(x):+.1f} |")
    out = os.path.join(F.ROOT, "reports", "research", "fx_round_numbers.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

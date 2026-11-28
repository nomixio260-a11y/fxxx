#!/usr/bin/env python3
"""研究：指数の口座 ＋ 金の口座を、直近20年（2007〜2026年）で年ごとに測る（106章）。

- 金の口座：MT5 のテスターが書き出した日ごとの資産（OANDA の実際の値段、2007年1月〜2026年11月。reports/runs/NNNN_equity.csv）。
- 指数の口座：
   2019年11月〜：MT5 のテスターの日ごとの資産（OANDA の実際の値段。プリセットそのもの）。
   それより前（2007年1月〜2019年10月）：OANDA に指数の履歴がないため、現物の3指数での写し（104章の index_trend_combo.py と同じ計算：
   戻りの層 ＋ NASDAQ100 の順張りの層。コストは CFD と同じ形）。写しの大きさは、重なる時期（2019年11月〜）の口座の値動きが MT5 と同じになるように合わせる。
- 合わせ方：資金を半分ずつ。年が変わるたびに半分ずつに戻す形（手作業の資金移動）と、戻さない形の両方。
- 見るもの：年ごとの損益、+300% 以上・+100% 以上・マイナスの年の数、最悪の年、最大の下落、12か月の成績の最高〜最低。
使い方: python3 tools/research/composite_20y.py  → reports/research/composite_20y.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import composite_accounts as CA  # noqa: E402
import fred_data as F  # noqa: E402
import index_trend_combo as ITC  # noqa: E402
import target300 as T  # noqa: E402

ANN = 252
START = "2007-01-01"


def spliced(mt5_eq, replica):
    """2019年11月より前は写し（重なる時期の値動きを MT5 に合わせる）、それ以降は MT5。戻り値：日々の損益、合わせた倍率、重なる時期の相関。"""
    m = mt5_eq.pct_change().dropna()
    m = m[m.abs().cumsum() > 0]
    ov = pd.concat([m, replica], axis=1, sort=True).dropna()
    k = ov.iloc[:, 0].std() / ov.iloc[:, 1].std()
    pre = replica[(replica.index >= START) & (replica.index < m.index[0])] * k
    return pd.concat([pre, m]), k, ov.corr().iloc[0, 1], ov


def yearly(e):
    by = e.groupby(e.index.year).last()
    prev = np.concatenate([[e.iloc[0]], by.values[:-1]])
    return pd.Series(by.values / prev - 1, index=by.index)


def stats_row(label, r):
    e = (1 + r).cumprod()
    e = pd.concat([pd.Series([1.0], index=[e.index[0] - pd.Timedelta(days=1)]), e])
    y = yearly(e)
    ro = CA.roll12(e)
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    return (f"| {label} | {(e.iloc[-1] ** (1 / yrs) - 1) * 100:+.0f}% | {r.mean() / r.std() * np.sqrt(ANN):.2f} | {(e / e.cummax() - 1).min() * 100:.0f}% | {int((y >= 3).sum())} | {int((y >= 1).sum())} | "
            f"{int((y < 0).sum())} | {y.min() * 100:+.0f}%（{int(y.idxmin())}年） | {y.max() * 100:+.0f}%（{int(y.idxmax())}年） | {ro.max() * 100:+.0f}% 〜 {ro.min() * 100:+.0f}% | {(ro >= 3).mean() * 100:.1f}% |"), y


def rebal(ri, rg, a=0.5, yearly_reset=True):
    idx = ri.index.union(rg.index)
    ri, rg = ri.reindex(idx).fillna(0.0), rg.reindex(idx).fillna(0.0)
    vi, vg, year, out, prev = a, 1 - a, idx[0].year, [], 1.0
    for t, x, y in zip(idx, ri.values, rg.values):
        if yearly_reset and t.year != year:
            tot, year = vi + vg, t.year
            vi, vg = a * tot, (1 - a) * tot
        vi, vg = vi * (1 + x), vg * (1 + y)
        out.append((vi + vg) / prev - 1)
        prev = vi + vg
    return pd.Series(out, index=idx)


def main():
    cat = CA.catalog()
    E = {k: CA.rel(c) for k, c in cat.items()}
    rev = {u: T.cash_returns(u) for u in (5.0, 8.75)}
    tr = {u: ITC.trend_returns("NASDAQ100", u) for u in (10.0, 20.0)}
    rep = {"Index_Demo": rev[5.0].add(tr[10.0], fill_value=0.0), "Index_Growth": rev[8.75].add(tr[20.0], fill_value=0.0)}
    lines = ["# 研究：指数の口座 ＋ 金の口座、直近20年（`tools/research/composite_20y.py`）", "",
             "## 1 指数の口座の、2019年10月以前の写しの確かめ（重なる時期 2019年11月〜2026年11月で、MT5 と比べる）", "",
             "| 設定 | 写しの形 | 合わせた倍率 | 日々の損益の相関 | 重なる時期の年率：MT5 | 写し（倍率をかけたあと） | 最大の下落：MT5 | 写し |", "|---|---|---|---|---|---|---|---|"]
    IDX = {}
    for name, form in (("Index_Demo", "戻り 5% ＋ 順張り 10%（現物の3指数）"), ("Index_Growth", "戻り 8.75% ＋ 順張り 20%（現物の3指数）")):
        r, k, c, ov = spliced(E[(name, 0.0, "long")], rep[name])
        IDX[name] = r[r.index >= START]
        cg = lambda x: ((1 + x).prod() ** (ANN / len(x)) - 1) * 100            # noqa: E731
        dd = lambda x: ((1 + x).cumprod() / (1 + x).cumprod().cummax() - 1).min() * 100   # noqa: E731
        lines.append(f"| {name} | {form} | {k:.2f} | {c:+.2f} | {cg(ov.iloc[:, 0]):+.0f}% | {cg(ov.iloc[:, 1] * k):+.0f}% | {dd(ov.iloc[:, 0]):.0f}% | {dd(ov.iloc[:, 1] * k):.0f}% |")
        print(lines[-1], flush=True)
    GOLD = {u: E[("金", u, "long")].pct_change().dropna() for u in (11.2, 22.4, 33.6, 50.0)}
    GOLD = {u: v[v.index >= START] for u, v in GOLD.items()}
    gname = {11.2: "金 小", 22.4: "金 中", 33.6: "金 大", 50.0: "金 最大"}
    head = "| 設定 | 年率 | シャープ | 最大の下落 | +300% 以上の年 | +100% 以上の年 | マイナスの年 | 最悪の年 | 最高の年 | 12か月の成績（最高〜最低） | 12か月で +300% 以上だった割合 |"
    lines += ["", "## 2 直近20年（2007年1月〜2026年11月）", "", head, "|---|" + "---|" * 10]
    Y = {}
    sets = [("指数（デモの既定）だけ", IDX["Index_Demo"]), ("指数（大きい設定）だけ", IDX["Index_Growth"])] + [(f"{gname[u]}だけ", GOLD[u]) for u in (22.4, 33.6, 50.0)]
    for ip, gu in (("Index_Demo", 22.4), ("Index_Demo", 33.6), ("Index_Growth", 33.6), ("Index_Growth", 50.0)):
        nm = f"{'指数（デモの既定）' if ip == 'Index_Demo' else '指数（大きい設定）'} ＋ {gname[gu]}"
        sets.append((nm + "、半分ずつ（年に1回戻す）", rebal(IDX[ip], GOLD[gu], 0.5, True)))
        sets.append((nm + "、半分ずつ（戻さない）", rebal(IDX[ip], GOLD[gu], 0.5, False)))
    for label, r in sets:
        row, y = stats_row(label, r)
        Y[label] = y
        lines.append(row)
        print(row, flush=True)
    lines += ["", "## 3 年ごとの損益（%）", "", "| 設定 | " + " | ".join(str(y) for y in range(2007, 2027)) + " |", "|---|" + "---|" * 20]
    for label, y in Y.items():
        lines.append(f"| {label} | " + " | ".join(f"{y.get(yr, np.nan) * 100:+.0f}" for yr in range(2007, 2027)) + " |")
    print("\n".join(lines[-len(Y):]), flush=True)
    # ---------- 値が大きく動いた局面での成績（局面は、よく知られた急落・急騰の日付。成績を見て選んだものではない）
    import yahoo_data as YH
    spx, gld = YH.fetch("SPX")["close"].dropna(), YH.fetch("GLD")["close"].dropna()
    EP = (("2007年10月〜09年3月：世界金融危機", "2007-10-09", "2009-03-09"), ("うち 2008年9〜11月：リーマン・ショック", "2008-09-12", "2008-11-20"),
          ("2010年4〜7月：フラッシュ・クラッシュ、欧州債務", "2010-04-23", "2010-07-02"), ("2011年7〜10月：米国債の格下げ", "2011-07-22", "2011-10-03"),
          ("2013年4月：金の急落", "2013-04-10", "2013-06-28"), ("2015年8月：中国の通貨切り下げ", "2015-08-17", "2015-08-25"),
          ("2018年1〜2月：変動率の急騰", "2018-01-26", "2018-02-08"), ("2018年9〜12月", "2018-09-20", "2018-12-24"),
          ("2020年2〜3月：コロナ", "2020-02-19", "2020-03-23"), ("2022年1〜10月：利上げの下げ相場", "2022-01-03", "2022-10-12"),
          ("2024年7〜8月：円キャリーの巻き戻し", "2024-07-16", "2024-08-05"), ("2025年2〜4月：関税", "2025-02-19", "2025-04-08"),
          ("2026年1〜11月：金の下落", "2026-01-28", "2026-11-12"),
          ("（上げ）2009年3月〜12月", "2009-03-09", "2009-12-31"), ("（上げ）2020年3月〜8月", "2020-03-23", "2020-08-31"), ("（上げ）2025年1月〜26年1月：金の上昇", "2025-01-02", "2026-01-28"))
    cols = (("指数（デモの既定）", IDX["Index_Demo"]), ("指数（大きい設定）", IDX["Index_Growth"]), ("金 中", GOLD[22.4]), ("金 最大", GOLD[50.0]),
            ("指数（デモの既定）＋ 金 中", rebal(IDX["Index_Demo"], GOLD[22.4], 0.5, True)), ("指数（大きい設定）＋ 金 最大", rebal(IDX["Index_Growth"], GOLD[50.0], 0.5, True)))
    lines += ["", "## 4 値が大きく動いた局面での成績（その期間の損益）", "",
              "| 局面 | S&P500 | 金 | " + " | ".join(c[0] for c in cols) + " |", "|---|---|---|" + "---|" * len(cols)]

    def move(px, a, b):
        x = px[(px.index >= a) & (px.index <= b)]
        return f"{(x.iloc[-1] / x.iloc[0] - 1) * 100:+.0f}%" if len(x) > 1 else "—"
    for lab, a, b in EP:
        cells = []
        for _, r in cols:
            x = r[(r.index > a) & (r.index <= b)]
            cells.append(f"{((1 + x).prod() - 1) * 100:+.0f}%")
        lines.append(f"| {lab} | {move(spx, a, b)} | {move(gld, a, b)} | " + " | ".join(cells) + " |")
        print(lines[-1], flush=True)
    # 最悪の日・最悪の月
    lines += ["", "| 設定 | 最悪の日 | 最悪の月 | 最悪の3か月 | 最高の月 |", "|---|---|---|---|---|"]
    for lab, r in cols:
        m = (1 + r).groupby([r.index.year, r.index.month]).prod() - 1
        e = (1 + r).cumprod()
        q = (e / e.shift(63) - 1).dropna()
        lines.append(f"| {lab} | {r.min() * 100:.1f}%（{r.idxmin().date()}） | {m.min() * 100:+.0f}%（{m.idxmin()[0]}年{m.idxmin()[1]}月） | {q.min() * 100:+.0f}%（〜{q.idxmin().date()}） | {m.max() * 100:+.0f}%（{m.idxmax()[0]}年{m.idxmax()[1]}月） |")
        print(lines[-1], flush=True)
    z = pd.concat([IDX["Index_Growth"], GOLD[33.6]], axis=1, sort=True).dropna()
    lines += ["", f"- 指数の口座と金の口座の、日々の損益の相関（20年）：{z.corr().iloc[0, 1]:+.2f}。年ごとの損益の相関：{pd.concat([Y['指数（大きい設定）だけ'], Y['金 大だけ']], axis=1).corr().iloc[0, 1]:+.2f}。",
              "- 2019年10月以前の指数の口座は、現物の指数での写しです（OANDA の CFD の履歴がない時期）。写しは、重なる時期の日々の値動きが MT5 と同じになるように倍率をかけています。"]
    out = os.path.join(F.ROOT, "reports", "research", "composite_20y.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""研究：VIX の水準で、売られすぎの戻りの建玉を変える形が、どこまで確かか（index_regime.py の続き）。

- index_regime.py：戻りの利益（値動きの大きさあたり）は、VIX が高い状態ほど大きい（低い +0.03・中 +0.07・高い +0.14。2011年以降も同じ並び）。
  事前に決めた形（低い 0.5 倍・中 1.0 倍・高い 1.5 倍）で、26年のシャープが +0.71 → +0.83、最悪の日・下落も小さくなった。
- ここで確かめること：
  1 倍率を変えても同じか（まわりの数値）。区切りを変えても同じか（3つ・5つ・なめらかな形）。
  2 指数ごと・期間ごと。
  3 何が効いているのか：VIX の水準そのものか、VIX と実際の値動きの差（オプションの値段に上乗せされた「保険料」）か。
  4 予想モデルとして：「ルールの数 × VIX の状態」ごとの平均の利益を、**毎年、前の年までのデータだけで**計算し、それに比例して持つ形
    （建玉 ∝ 予想される利益 ÷ 分散。ケリーの考え方）。事前に決めた倍率と同じくらい良ければ、倍率の選び方に頼っていないことになる。
  5 EA と同じ形（CFD の日足、2011年9月〜2026年10月）でも同じか。
  6 逆指値（3×σ）と合わせた場合。
- VIX は、1日前の終値を使う（判定する日の VIX の終値 16:15 は、株の終値 16:00 より後のため。CFD の日足 17:00 区切りなら当日の値も使えるが、厳しめにする）。
  VIX の「水準」は、その日までの過去の VIX（1990年〜）の分布での位置（0〜1）。
使い方: python3 tools/research/index_vix_sizing.py  → reports/research/index_vix_sizing.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_reversion_cfd as IC  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_stop as IS  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
CFD = {"S&P500": ("SPXUSD", "USD", 1.5), "NASDAQ100": ("NSXUSD", "USD", 0.7)}
PER_C = (("2011/9〜14", "2011-09-01", "2015-01-01"), ("2015〜18", "2015-01-01", "2019-01-01"), ("2019〜21/10", "2019-01-01", "2021-11-01"),
         ("21/11〜26/10", "2021-11-01", "2026-12-01"))


def vix_rank(index, lag=1):
    """VIX の、その日までの過去の分布での位置（0〜1）。lag 日前の値。"""
    v = Y.fetch("VIX")["close"]
    rk = v.expanding(min_periods=500).rank(pct=True)
    return rk.reindex(rk.index.union(index)).ffill(limit=3).reindex(index).shift(lag), v.reindex(v.index.union(index)).ffill(limit=3).reindex(index).shift(lag)


def mult_of(rk, form):
    """状態 → 建玉の倍率。"""
    r = rk.fillna(0.5)
    if form is None:
        return pd.Series(1.0, index=rk.index)
    if isinstance(form, tuple) and len(form) == 3:
        return pd.Series(np.where(r < 1 / 3, form[0], np.where(r >= 2 / 3, form[2], form[1])), index=rk.index)
    if form == "linear":                    # 0.5 〜 1.5 のなめらかな形
        return 0.5 + r
    if form == "linear2":                   # 0 〜 2
        return 2.0 * r
    if form == "q5":                        # 5つに分ける：0.5・0.75・1・1.25・1.5
        return 0.5 + 0.25 * np.floor(r.clip(upper=0.999) * 5)
    raise ValueError(form)


def load_sets(kind):
    """(d, n, sg, rate, div) の組。kind = cash（現物3指数）／cfd（CFD 2指数、EA と同じ形）。"""
    sets = {}
    if kind == "cash":
        for name in IRK.US3:
            d, st, rate, div, vols, above = IRK.load(name)
            sets[name] = (d, st.sum(axis=1), IS.har_sigma(d), rate, div)
    else:
        for name, (pair, ccy, div) in CFD.items():
            d = IC.day_bars(IC.load_any(pair), 17)
            st = IR.rules(d)
            sets[name] = (d, st["R2<10"] + st["D7"] + st["IBS"], IS.har_sigma(d), IR.short_rate(ccy, d.index), div)
    return sets


def sleeve(sets, mults, kind, k=None, names=None):
    parts = []
    use = names or list(sets)
    for name in use:
        d, n, sg, rate, div = sets[name]
        w = (mults[name] * n / 3.0 * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0) / len(use)
        r, _, _ = IS.run(d, w, sg, rate, div, k, "close" if kind == "cash" else "open")
        parts.append(r)
    return pd.concat(parts, axis=1, sort=True).fillna(0.0).sum(axis=1)


def stat(rr, start, per):
    rr = rr[rr.index >= start]
    z = rr * (0.10 / (rr.std() * np.sqrt(ANN)))
    sh = z.mean() / z.std() * np.sqrt(ANN)
    eq = (1 + z).cumprod()
    yr = z.groupby(z.index.year).sum()
    q = z.quantile(0.01)
    return (f"{sh:+.2f} | {sh * np.sqrt(len(z) / ANN):+.1f} | {z.min() * 100:.1f}%（{z.idxmin().date()}） | {z[z <= q].mean() * 100:.2f}% | {(eq / eq.cummax() - 1).min() * 100:.0f}% | "
            f"{yr.min() * 100:.1f}% | {(yr > 0).sum()}/{len(yr)} | " + " | ".join(f"{x.mean() / x.std() * np.sqrt(ANN):+.2f}" for x in (z[(z.index >= a) & (z.index < b)] for _, a, b in per))), z


def kelly_table_mult(sets, ranks, first=2003):
    """ルールの数（1・2・3）× VIX の状態（低・中・高）ごとの「翌日の損益 ÷ 値動きの見積もり」の平均を、毎年、前の年までのデータで計算。
    倍率 = その升の平均 ÷ 全体の平均（マイナスは 0、上限 3）。升の件数が少ないときは、全体の平均に寄せる（件数 ÷ (件数 + 200)）。"""
    rows = []
    for name, (d, n, sg, rate, div) in sets.items():
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
        fin = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
        y = ((d["close"].pct_change() + fin).shift(-1) / sg)
        rk = ranks[name]
        reg = pd.Series(np.where(rk < 1 / 3, 0, np.where(rk >= 2 / 3, 2, 1)), index=d.index).where(rk.notna())
        rows.append(pd.DataFrame({"name": name, "n": n, "reg": reg, "y": y}))
    P = pd.concat(rows)
    P = P[(P["n"] >= 1) & P["reg"].notna()]
    out = {name: pd.Series(1.0, index=sets[name][0].index) for name in sets}
    tabs = {}
    for yr in range(first, 2027):
        tr = P[(P.index.year < yr) & P["y"].notna()]
        if len(tr) < 1500:
            continue
        # 建玉は n に比例するので、升の「1ルールあたり」の利益で比べる
        g = tr.assign(u=tr["y"]).groupby(["n", "reg"])["u"].agg(["mean", "count"])
        base = (tr["y"] * tr["n"]).sum() / (tr["n"] ** 2).sum()        # y ≈ base × n と見たときの傾き
        tab = {}
        for (nn, rg), row in g.iterrows():
            shrink = row["count"] / (row["count"] + 200.0)
            cell = shrink * row["mean"] + (1 - shrink) * base * nn
            tab[(int(nn), int(rg))] = float(np.clip(cell / (base * nn), 0.0, 3.0)) if base > 0 else 1.0
        tabs[yr] = tab
        for name in sets:
            d, n = sets[name][0], sets[name][1]
            rk = ranks[name]
            m = (d.index.year == yr)
            reg = np.where(rk[m] < 1 / 3, 0, np.where(rk[m] >= 2 / 3, 2, 1))
            out[name][m] = [tab.get((int(a), int(b)), 1.0) if a >= 1 else 1.0 for a, b in zip(n[m].values, reg)]
    return out, tabs


def main():
    lines = ["# 研究：VIX の水準で建玉を変える形の確かさ（`tools/research/index_vix_sizing.py`）", "",
             "建玉は HAR 型の見積もりで決め、ルールの数に比例（1:2:3）。VIX は1日前の終値の、過去の分布での位置。全期間の値動きを年10%にそろえて比べる。", ""]
    cash = load_sets("cash")
    rk_c, vx_c = {}, {}
    for name, t in cash.items():
        rk_c[name], vx_c[name] = vix_rank(t[0].index)
    head = "| 形 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | プラスの年 | " + " | ".join(p[0] for p in IRK.PER) + " |"
    sep = "|---|" + "---|" * (7 + len(IRK.PER))
    lines += ["## 1 倍率・区切りを変える（現物の3指数、2000年10月〜2026年11月）", "", head, sep]
    keep = {}
    forms = (("変えない", None), ("低 0.75・中 1・高 1.25", (0.75, 1.0, 1.25)), ("**低 0.5・中 1・高 1.5（事前に決めた形）**", (0.5, 1.0, 1.5)),
             ("低 0.25・中 1・高 1.75", (0.25, 1.0, 1.75)), ("低 0・中 1・高 2", (0.0, 1.0, 2.0)), ("低 0.5・中 1・高 1（低いときだけ減らす）", (0.5, 1.0, 1.0)),
             ("低 1・中 1・高 1.5（高いときだけ増やす）", (1.0, 1.0, 1.5)), ("5つに分ける（0.5〜1.5）", "q5"), ("なめらか（0.5〜1.5）", "linear"), ("なめらか（0〜2）", "linear2"))
    for label, form in forms:
        s, z = stat(sleeve(cash, {n: mult_of(rk_c[n], form) for n in cash}, "cash"), IRK.START, IRK.PER)
        lines.append(f"| {label} | {s} |")
        keep[label] = z
        print(lines[-1], flush=True)
    lines += ["", "## 2 指数ごと（事前に決めた形）", "", "| 指数 | 変えない：シャープ | 最悪の日 | VIX で変える：シャープ | 最悪の日 | 2011年〜：変えない | 2011年〜：変える |", "|---|---|---|---|---|---|---|"]
    for name in cash:
        a = sleeve(cash, {n: mult_of(rk_c[n], None) for n in cash}, "cash", names=[name])
        b = sleeve(cash, {n: mult_of(rk_c[n], (0.5, 1.0, 1.5)) for n in cash}, "cash", names=[name])
        cells = []
        for x in (a, b):
            x = x[x.index >= IRK.START]
            z = x * (0.10 / (x.std() * np.sqrt(ANN)))
            cells += [f"{z.mean() / z.std() * np.sqrt(ANN):+.2f}", f"{z.min() * 100:.1f}%"]
        for x in (a, b):
            x = x[x.index >= "2011-01-01"]
            cells.append(f"{x.mean() / x.std() * np.sqrt(ANN):+.2f}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
        print(lines[-1], flush=True)
    # 3 何が効いているのか
    lines += ["", "## 3 何が効いているのか（どれも、過去の分布での位置で 低 0.5・中 1・高 1.5）", "", head, sep]
    alts = {}
    for name, (d, n, sg, rate, div) in cash.items():
        vx = vx_c[name] / 100.0
        rv = sg.shift(1) * np.sqrt(ANN)                                   # 同じく1日前の、値動きの見積もり（年率）
        c = d["close"]
        alts.setdefault("VIX の水準", {})[name] = rk_c[name]
        alts.setdefault("VIX ÷ 実際の値動きの見積もり（保険料の厚さ）", {})[name] = (vx / rv).expanding(min_periods=500).rank(pct=True)
        alts.setdefault("VIX − 実際の値動きの見積もり", {})[name] = (vx - rv).expanding(min_periods=500).rank(pct=True)
        alts.setdefault("値動きの見積もりの水準（値段だけ）", {})[name] = sg.expanding(min_periods=500).rank(pct=True)
        alts.setdefault("250日の高値からの下げ（値段だけ。大きいほど「高い」）", {})[name] = (-(c / c.rolling(250).max() - 1)).expanding(min_periods=500).rank(pct=True)
        alts.setdefault("過去20日の下げ（値段だけ。大きいほど「高い」）", {})[name] = (-(c / c.shift(20) - 1)).expanding(min_periods=500).rank(pct=True)
        alts.setdefault("下向きの値動きの割合（過去22日。値段だけ）", {})[name] = (
            (c.pct_change().clip(upper=0) ** 2).rolling(22).sum() / (c.pct_change() ** 2).rolling(22).sum()).expanding(min_periods=500).rank(pct=True)
    for label, rks in alts.items():
        s, z = stat(sleeve(cash, {n: mult_of(rks[n], (0.5, 1.0, 1.5)) for n in cash}, "cash"), IRK.START, IRK.PER)
        lines.append(f"| {label} | {s} |")
        print(lines[-1], flush=True)
    # 4 予想モデルとして（毎年、前の年までのデータで升ごとの平均を計算）
    km, tabs = kelly_table_mult(cash, rk_c)
    per03 = (("2003〜08", "2003-01-01", "2009-01-01"),) + IRK.PER[1:]
    head3 = "| 形 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | プラスの年 | " + " | ".join(p[0] for p in per03) + " |"
    lines += ["", "## 4 予想モデルとして：升（ルールの数 × VIX の状態）ごとの平均の利益に比例して持つ（2003年〜。毎年、前の年までのデータで計算）", "", head3, sep]
    for label, mm in (("変えない", {n: mult_of(rk_c[n], None) for n in cash}), ("事前に決めた倍率（0.5・1・1.5）", {n: mult_of(rk_c[n], (0.5, 1.0, 1.5)) for n in cash}),
                      ("升ごとの平均に比例（過去のデータだけで計算）", km)):
        s, z = stat(sleeve(cash, mm, "cash"), "2003-01-01", per03)
        lines.append(f"| {label} | {s} |")
        keep["4 " + label] = z
        print(lines[-1], flush=True)
    last = tabs[max(tabs)]
    lines += ["", f"参考：{max(tabs)}年の時点の倍率の表（ルールの数 × VIX 低・中・高）：" + "、".join(
        f"{nn}つ [{last.get((nn, 0), 1):.2f}・{last.get((nn, 1), 1):.2f}・{last.get((nn, 2), 1):.2f}]" for nn in (1, 2, 3)), ""]
    # 5 EA と同じ形（CFD）
    cfd = load_sets("cfd")
    rk_f = {name: vix_rank(t[0].index)[0] for name, t in cfd.items()}
    rk_f0 = {name: vix_rank(t[0].index, lag=0)[0] for name, t in cfd.items()}
    headc = "| 形 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | プラスの年 | " + " | ".join(p[0] for p in PER_C) + " |"
    lines += ["## 5 EA と同じ形（CFD の日足、S&P500 と NASDAQ100、2011年9月〜2026年10月）", "", headc, sep]
    for label, mm, k in (("変えない", {n: mult_of(rk_f[n], None) for n in cfd}, None),
                         ("VIX で変える（0.5・1・1.5、1日前の VIX）", {n: mult_of(rk_f[n], (0.5, 1.0, 1.5)) for n in cfd}, None),
                         ("VIX で変える（当日の VIX。日足が 17:00 に閉じる時点で分かっている値）", {n: mult_of(rk_f0[n], (0.5, 1.0, 1.5)) for n in cfd}, None),
                         ("VIX で変える（0.75・1・1.25）", {n: mult_of(rk_f[n], (0.75, 1.0, 1.25)) for n in cfd}, None),
                         ("VIX で変える（0.25・1・1.75）", {n: mult_of(rk_f[n], (0.25, 1.0, 1.75)) for n in cfd}, None),
                         ("変えない ＋ 逆指値 3×σ", {n: mult_of(rk_f[n], None) for n in cfd}, 3.0),
                         ("VIX で変える（0.5・1・1.5）＋ 逆指値 3×σ", {n: mult_of(rk_f[n], (0.5, 1.0, 1.5)) for n in cfd}, 3.0)):
        s, z = stat(sleeve(cfd, mm, "cfd", k), "2011-09-01", PER_C)
        lines.append(f"| {label} | {s} |")
        keep["5 " + label] = z
        print(lines[-1], flush=True)
    lines += ["", "## 6 現物の3指数で、逆指値（3×σ）と合わせた場合（2000年10月〜2026年11月）", "", head, sep]
    for label, mm, k in (("変えない・逆指値なし", {n: mult_of(rk_c[n], None) for n in cash}, None), ("変えない ＋ 逆指値 3×σ", {n: mult_of(rk_c[n], None) for n in cash}, 3.0),
                         ("VIX で変える・逆指値なし", {n: mult_of(rk_c[n], (0.5, 1.0, 1.5)) for n in cash}, None),
                         ("**VIX で変える ＋ 逆指値 3×σ**", {n: mult_of(rk_c[n], (0.5, 1.0, 1.5)) for n in cash}, 3.0)):
        s, z = stat(sleeve(cash, mm, "cash", k), IRK.START, IRK.PER)
        lines.append(f"| {label} | {s} |")
        keep["6 " + label] = z
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_vix_sizing.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    pd.DataFrame(keep).to_parquet(os.path.join(D.CACHE, "index_vix_sizing_returns.parquet"))


if __name__ == "__main__":
    main()

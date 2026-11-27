#!/usr/bin/env python3
"""研究：関連研究の調査で挙がった案を、同じ物差しで確かめる（公表済みの形を、数値を変えずに使う。公表後の期間を分けて見る）。

1 加重した反転（Baltussen・van Bekkum・Da 2019年、JFE。データは 2016年まで → 2017年以降が公表後）
  建玉 ∝ −(4×当日 + 3×前日 + 2×2日前 + 1×3日前 の値動き) ÷ 値動きの大きさ。毎日作り直す。買いと売りの両方／買いだけ／売りだけ。
2 出来高（Campbell・Grossman・Wang 1993年、Lochstoer・Muir 2026年）：出来高が多い日の値動きほど、次の日に反転しやすい。
  出来高は ETF（SPY・QQQ・DIA）の出来高の対数 − 過去250日の平均。
3 VIX の期間の並び（Fassas・Hourvouliades 2019年。データは 2010〜2017年）：VIX ÷ 3か月の VIX が 1 を超える（短いほうが高い）と、その後の株は上がりやすい。
4 業種の動きのそろい方（Kritzman・Li・Page・Rigobon 2011年「吸収比率」。データは 1998〜2010年5月 → 2011年以降が公表後）：
  業種別の値動きが少数の要因で説明される割合が急に上がったら、株を減らす。
- 物差し：米国3指数、2000年10月〜2026年11月、CFD のコスト込み。建玉は HAR 型の見積もりで決める。全期間の値動きを年10%にそろえる。
  「今の層」= 公表済みの3ルール（R2・D7・IBS）を、ルールの数に比例して持つ形。
使い方: python3 tools/research/index_lit_tests.py  → reports/research/index_lit_tests.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_vix_sizing as V  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
ETF = {"S&P500": "SPY", "NASDAQ100": "QQQ", "ダウ": "DIA"}
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU"]


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 50 and x.std() > 0 else np.nan


def pnl_ls(d, w, rate, div, cost=IR.COST):
    """買いも売りもある建玉 w（終値で決め、終値で売買）の日次の損益。CFD の金利：買いは（金利 + 2.5%）を払い配当を受け取る。売りは（金利 − 2.5%）を受け取り配当を払う。"""
    held = w.shift(1).fillna(0.0)
    days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
    fl = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
    fs = (rate - IR.MARKUP - div) / 100.0 / 360.0 * days
    fin = held.clip(lower=0) * fl + (-held.clip(upper=0)) * fs
    return held * d["close"].pct_change().fillna(0.0) + fin - (w - held).abs() * cost


def expanding_rank(s, minp=500):
    return s.expanding(min_periods=minp).rank(pct=True)


def cell(x):
    if len(x) < 30:
        return "—"
    by = x.groupby(level=0).mean()
    return f"{x.mean():+.3f}（t {by.mean() / by.std() * np.sqrt(len(by)):+.1f}、{len(x)} 件）"


def main():
    sets = V.load_sets("cash")
    rk = {n: V.vix_rank(t[0].index)[0] for n, t in sets.items()}
    one = {n: V.mult_of(rk[n], None) for n in sets}
    vm = {n: V.mult_of(rk[n], (0.5, 1.0, 1.5)) for n in sets}
    base = V.sleeve(sets, one, "cash")
    base = base[base.index >= IRK.START]
    basev = V.sleeve(sets, vm, "cash")
    basev = basev[basev.index >= IRK.START]
    lines = ["# 研究：関連研究の調査で挙がった案の検証（`tools/research/index_lit_tests.py`）", "",
             "米国3指数、2000年10月〜2026年11月、CFD のコスト込み、建玉は HAR 型の見積もりで決める。シャープは年率。", ""]

    # ---------- 1 加重した反転
    lines += ["## 1 加重した反転（当日×4・前日×3・2日前×2・3日前×1 の値動きの逆）", "",
              "| 形 | コスト前：全期間 | 〜2016（公表前） | 2017年〜（公表後） | コスト後：全期間 | 〜2016 | 2017年〜 | 今の層との相関 | 持つ日の割合 |", "|---|---|---|---|---|---|---|---|---|"]
    mac = {}
    for side in ("両方", "買いだけ", "売りだけ"):
        gross, net = [], []
        for name, (d, n, sg, rate, div) in sets.items():
            r = np.log(d["close"]).diff()
            s = -(4 * r + 3 * r.shift(1) + 2 * r.shift(2) + r.shift(3)) / 10.0 / sg
            s = s.clip(-3, 3)
            if side == "買いだけ":
                s = s.clip(lower=0)
            elif side == "売りだけ":
                s = s.clip(upper=0)
            w = (s * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0) / len(sets)
            net.append(pnl_ls(d, w, rate, div))
            gross.append(w.shift(1).fillna(0.0) * d["close"].pct_change().fillna(0.0))
        g = pd.concat(gross, axis=1, sort=True).fillna(0.0).sum(axis=1)
        x = pd.concat(net, axis=1, sort=True).fillna(0.0).sum(axis=1)
        g, x = g[g.index >= IRK.START], x[x.index >= IRK.START]
        mac[side] = x
        lines.append(f"| {side} | {sh(g):+.2f} | {sh(g[g.index < '2017-01-01']):+.2f} | {sh(g[g.index >= '2017-01-01']):+.2f} | {sh(x):+.2f} | "
                     f"{sh(x[x.index < '2017-01-01']):+.2f} | {sh(x[x.index >= '2017-01-01']):+.2f} | {x.corr(base):+.2f} | {(x != 0).mean() * 100:.0f}% |")
        print(lines[-1], flush=True)

    def s10(x):
        return x * (0.10 / (x.std() * np.sqrt(ANN)))
    lines += ["", "| 組み合わせ（値動きを年10%にそろえてから、同じ重みで足す） | シャープ | 〜2016 | 2017年〜 | 最悪の日 | 最大の下落 |", "|---|---|---|---|---|---|"]
    for label, x in (("今の層だけ", s10(base)), ("今の層 ＋ 加重した反転（買いだけ）", s10(s10(base) + s10(mac["買いだけ"]))),
                     ("今の層 ＋ 加重した反転（両方）", s10(s10(base) + s10(mac["両方"])))):
        eq = (1 + x).cumprod()
        lines.append(f"| {label} | {sh(x):+.2f} | {sh(x[x.index < '2017-01-01']):+.2f} | {sh(x[x.index >= '2017-01-01']):+.2f} | {x.min() * 100:.1f}% | {(eq / eq.cummax() - 1).min() * 100:.0f}% |")
        print(lines[-1], flush=True)

    # ---------- 2 出来高
    rows = []
    vol_rank = {}
    for name, (d, n, sg, rate, div) in sets.items():
        e = Y.fetch(ETF[name])
        lv = np.log(e["volume"].where(e["volume"] > 0))
        Vt = (lv - lv.rolling(250, min_periods=120).mean()).reindex(d.index)
        r = np.log(d["close"]).diff()
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
        fin = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
        y = ((d["close"].pct_change() + fin).shift(-1) / sg)
        vol_rank[name] = expanding_rank(Vt)
        rows.append(pd.DataFrame({"name": name, "n": n, "y": y, "x": r / sg.shift(1), "V": Vt, "vr": vol_rank[name], "ynext": r.shift(-1) / sg}))
    P = pd.concat(rows)
    P = P[(P.index >= IRK.START)].dropna(subset=["y", "x", "V"])
    lines += ["", "## 2 出来高が多い日の値動きほど、次の日に反転しやすいか", "",
              "回帰：次の日の値動き = a + (b + g × 出来高) × 当日の値動き（どちらも値動きの大きさで割った値。t 値は日付ごとにまとめて計算）", "",
              "| 期間 | b（当日の値動きの係数） | g（出来高との掛け算の係数） | g の t 値 |", "|---|---|---|---|"]
    for lab, a, b in (("全期間", IRK.START, "2027-01-01"), ("2000〜10", IRK.START, "2011-01-01"), ("2011〜18", "2011-01-01", "2019-01-01"), ("2019〜26", "2019-01-01", "2027-01-01")):
        Q = P[(P.index >= a) & (P.index < b)]
        X = np.column_stack([np.ones(len(Q)), Q["x"].values, (Q["x"] * Q["V"]).values])
        co, *_ = np.linalg.lstsq(X, Q["ynext"].values, rcond=None)
        # 日付ごとにまとめた標準誤差
        e = Q["ynext"].values - X @ co
        G = pd.DataFrame(X * e[:, None], index=Q.index).groupby(level=0).sum().values
        bread = np.linalg.inv(X.T @ X)
        cov = bread @ (G.T @ G) @ bread
        lines.append(f"| {lab} | {co[1]:+.3f} | {co[2]:+.3f} | {co[2] / np.sqrt(cov[2, 2]):+.1f} |")
        print(lines[-1], flush=True)
    lines += ["", "ルールが出ている日の、翌日の損益 ÷ 値動きの見積もり（出来高の水準 = 過去の分布での位置）：", "",
              "| 出来高 | ルール1つ以上：全期間 | 2つ以上 | 2011年〜：1つ以上 | 2つ以上 |", "|---|---|---|---|---|"]
    for lo, hi, lab in ((0, 1 / 3, "少ない"), (1 / 3, 2 / 3, "中"), (2 / 3, 1.01, "多い")):
        m = (P["vr"] >= lo) & (P["vr"] < hi)
        post = P.index >= "2011-01-01"
        lines.append(f"| {lab} | {cell(P['y'][m & (P['n'] >= 1)])} | {cell(P['y'][m & (P['n'] >= 2)])} | {cell(P['y'][m & post & (P['n'] >= 1)])} | {cell(P['y'][m & post & (P['n'] >= 2)])} |")
        print(lines[-1], flush=True)
    volm = {n: V.mult_of(vol_rank[n], (0.5, 1.0, 1.5)) for n in sets}
    both = {n: vm[n] * volm[n] for n in sets}
    head = "| 形 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | プラスの年 | " + " | ".join(p[0] for p in IRK.PER) + " |"
    sep = "|---|" + "---|" * (7 + len(IRK.PER))
    lines += ["", head, sep]
    for label, mm in (("今の層（変えない）", one), ("出来高で倍率（少ない 0.5・中 1・多い 1.5）", volm), ("VIX で倍率（98章の形）", vm), ("VIX の倍率 × 出来高の倍率", both)):
        s, _ = V.stat(V.sleeve(sets, mm, "cash"), IRK.START, IRK.PER)
        lines.append(f"| {label} | {s} |")
        print(lines[-1], flush=True)

    # ---------- 3 VIX の期間の並び
    vix = Y.fetch("VIX")["close"]
    v3 = Y.fetch("VIX3M")["close"]
    ratio = (vix / v3.reindex(vix.index)).dropna()
    rows = []
    inv = {}
    for name, (d, n, sg, rate, div) in sets.items():
        rt = ratio.reindex(ratio.index.union(d.index)).ffill(limit=3).reindex(d.index).shift(1)
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
        fin = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
        y = ((d["close"].pct_change() + fin).shift(-1) / sg)
        inv[name] = rt
        rows.append(pd.DataFrame({"name": name, "n": n, "y": y, "ratio": rt, "vr": rk[name]}))
    P3 = pd.concat(rows).dropna(subset=["y", "ratio"])
    lines += ["", f"## 3 VIX ÷ 3か月の VIX（1日前の値。データは {ratio.index[0].date()}〜）", "",
              "ルールが出ている日の、翌日の損益 ÷ 値動きの見積もり：", "",
              "| 状態 | ルール1つ以上：全期間 | 2つ以上 | 2018年〜（公表後）：1つ以上 | ルールなしの日（全期間） |", "|---|---|---|---|---|"]
    for lab, m in (("1 以下（ふつう）", P3["ratio"] <= 1.0), ("1 を超える（短いほうが高い）", P3["ratio"] > 1.0),
                   ("VIX が高い状態で、1 以下", (P3["vr"] >= 2 / 3) & (P3["ratio"] <= 1.0)), ("VIX が高い状態で、1 を超える", (P3["vr"] >= 2 / 3) & (P3["ratio"] > 1.0))):
        post = P3.index >= "2018-01-01"
        lines.append(f"| {lab} | {cell(P3['y'][m & (P3['n'] >= 1)])} | {cell(P3['y'][m & (P3['n'] >= 2)])} | {cell(P3['y'][m & post & (P3['n'] >= 1)])} | {cell(P3['y'][m & (P3['n'] == 0)])} |")
        print(lines[-1], flush=True)
    start3 = str(ratio.index[0].date())
    per3 = (("2007〜14", "2007-01-01", "2015-01-01"),) + IRK.PER[2:]
    head3 = "| 形 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | プラスの年 | " + " | ".join(p[0] for p in per3) + " |"
    lines += ["", head3, "|---|" + "---|" * (7 + len(per3))]
    invm = {n: pd.Series(np.where(inv[n] > 1.0, 1.5, 1.0), index=inv[n].index) for n in sets}
    for label, mm in (("今の層（変えない）", one), ("1 を超えたら 1.5 倍", invm), ("VIX で倍率（98章の形）", vm), ("VIX の倍率 × （1 を超えたら 1.5 倍）", {n: vm[n] * invm[n] for n in sets})):
        s, _ = V.stat(V.sleeve(sets, mm, "cash"), max(start3, "2007-01-01"), per3)
        lines.append(f"| {label} | {s} |")
        print(lines[-1], flush=True)

    # ---------- 4 吸収比率
    R = pd.concat([Y.fetch(s)["adj"].pct_change().rename(s) for s in SECTORS], axis=1, sort=True).dropna()
    win, hl, k = 500, 250.0, 2
    wts = 0.5 ** (np.arange(win)[::-1] / hl)
    ar = pd.Series(np.nan, index=R.index)
    X = R.values
    for t in range(win, len(R)):
        Z = X[t - win:t]
        Z = Z - np.average(Z, axis=0, weights=wts)
        C = (Z * wts[:, None]).T @ Z / wts.sum()
        ev = np.linalg.eigvalsh(C)
        ar.iloc[t] = ev[-k:].sum() / ev.sum()
    shift = (ar.rolling(15).mean() - ar.rolling(250).mean()) / ar.rolling(250).std()
    spx = sets["S&P500"][0]["close"]
    fwd = {h: (spx.shift(-h) / spx - 1.0) for h in (1, 5, 20)}
    sig = shift.reindex(spx.index).shift(1)                         # 1日前の値
    lines += ["", f"## 4 業種の動きのそろい方（吸収比率：業種別 ETF 9本、500日。15日の平均 − 1年の平均を、1年の標準偏差で割った値。データは {shift.dropna().index[0].date()}〜）", "",
              "| 状態 | 2000年10月〜2010年：S&P500 のその後1日（年率） | 5日 | 20日 | 2011年〜（公表後）：1日（年率） | 5日 | 20日 | 日数の割合（2011年〜） |", "|---|---|---|---|---|---|---|---|"]
    for lab, m in (("+1 以上（急に上がった）", sig >= 1.0), ("−1〜+1", (sig > -1.0) & (sig < 1.0)), ("−1 以下（急に下がった）", sig <= -1.0)):
        cells = []
        for a, b in ((IRK.START, "2011-01-01"), ("2011-01-01", "2027-01-01")):
            mm = m & (sig.index >= a) & (sig.index < b)
            for h in (1, 5, 20):
                x = fwd[h][mm].dropna()
                cells.append(f"{x.mean() / h * ANN * 100:+.1f}%" if len(x) > 20 else "—")
        mm2 = (sig.index >= "2011-01-01") & sig.notna()
        lines.append(f"| {lab} | " + " | ".join(cells) + f" | {(m & mm2).sum() / mm2.sum() * 100:.0f}% |")
        print(lines[-1], flush=True)
    z = base * (0.10 / (base.std() * np.sqrt(ANN)))
    sg2 = sig.reindex(z.index)
    lines += ["", "今の層（値動き年10%）の損益を、1日前の状態で分けた場合：", "", "| 状態 | 2000年10月〜2010年：年率・シャープ | 2011年〜：年率・シャープ |", "|---|---|---|"]
    for lab, m in (("+1 以上", sg2 >= 1.0), ("−1〜+1", (sg2 > -1.0) & (sg2 < 1.0)), ("−1 以下", sg2 <= -1.0)):
        cells = []
        for a, b in ((IRK.START, "2011-01-01"), ("2011-01-01", "2027-01-01")):
            x = z[m & (z.index >= a) & (z.index < b)]
            cells.append(f"{x.mean() * ANN * 100:+.1f}%・{sh(x):+.2f}（{len(x)} 日）" if len(x) > 50 else "—")
        lines.append(f"| {lab} | " + " | ".join(cells) + " |")
        print(lines[-1], flush=True)
    hold = pd.Series(np.where(sg2 >= 1.0, 0.0, 1.0), index=z.index)
    half = pd.Series(np.where(sg2 >= 1.0, 0.5, 1.0), index=z.index)
    lines += ["", "| 形（今の層に、状態で倍率をかける） | 全期間のシャープ | 2000〜10 | 2011年〜 | 最悪の日 | 最大の下落 |", "|---|---|---|---|---|---|"]
    for label, mult in (("変えない", None), ("+1 以上のとき半分", half), ("+1 以上のとき持たない", hold)):
        x = base if mult is None else base * mult
        x = x * (0.10 / (x.std() * np.sqrt(ANN)))
        eq = (1 + x).cumprod()
        lines.append(f"| {label} | {sh(x):+.2f} | {sh(x[x.index < '2011-01-01']):+.2f} | {sh(x[x.index >= '2011-01-01']):+.2f} | {x.min() * 100:.1f}% | {(eq / eq.cummax() - 1).min() * 100:.0f}% |")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_lit_tests.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

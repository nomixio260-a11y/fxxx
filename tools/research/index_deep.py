#!/usr/bin/env python3
"""研究：売られすぎの戻りの層の深掘り（99章）。どれも、98章の改良後の形（HAR 型の見積もり・VIX の倍率・逆指値 4×σ）を土台に比べる。

A 売り側：下げの流れ（200日の平均より下）での「買われすぎの戻り」（公表済みのルールの鏡の形）。売りの持ち越しコストは安い（年 0.2%）。
  R2S：終値が200日の平均より下で RSI(2) > 90 → 売り、終値が5日の平均を下回ったら買い戻す
  D7S：終値が200日の平均より下で、過去7日の終値の最高値 → 売り、過去7日の最安値で買い戻す
  IBSS：(終値 − 安値) ÷ (高値 − 安値) > 0.8 → 売り、次の日に見直す（すべての日／200日の平均より下の日だけ）
B ルールがそろった数の重み：1:2:3（今の形）と、そろったときに厚くする形（1:2:4、1:2:5、1:3:6、0:1:3 など）
C 公表済みの別のルールを「票」として足す（Connors・Alvarez の 2009年の2冊から。選ばずに、すべて足す）：
  R2<5／累積 RSI（RSI(2) の2日の合計 < 35 → RSI(2) > 65 で手じまい）／3日続けて下げ（→ 5日の平均を上回ったら手じまい）／
  %b（ボリンジャー(5,1) の位置が 0.2 未満を3日 → 0.8 超で手じまい）／RSI(4) < 25（→ RSI(4) > 55 で手じまい）／5日の終値の最安値（→ 5日の平均を上回ったら手じまい）
D 持ってからの日数ごとの利益（利益は、持ち始めの数日に集まっているか）
- 物差し：現物の3指数（2000年10月〜2026年11月）と、EA と同じ形（CFD、S&P500 と NASDAQ100、2011年9月〜2026年10月）。コスト込み、値動きを年10%にそろえる。
使い方: python3 tools/research/index_deep.py  → reports/research/index_deep.md
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

ANN = 252
MULT = (0.5, 1.0, 1.5)


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 50 and x.std() > 0 else np.nan


def more_rules(d):
    """公表済みの別のルール（買いだけ、200日の平均より上のときに入る）。0/1 の建玉。"""
    c = d["close"]
    up = c > c.rolling(200).mean()
    r2 = IR.rsi_wilder(c, 2)
    r4 = IR.rsi_wilder(c, 4)
    ex5 = c > c.rolling(5).mean()
    out = {}
    out["R2<5"] = IR.positions(up & (r2 < 5), ex5)
    out["累積RSI"] = IR.positions(up & ((r2 + r2.shift(1)) < 35), r2 > 65)
    dn = c < c.shift(1)
    out["3日続落"] = IR.positions(up & dn & dn.shift(1) & dn.shift(2), ex5)
    sd = c.rolling(5).std(ddof=0)
    pb = (c - (c.rolling(5).mean() - sd)) / (2 * sd).replace(0, np.nan)
    lowb = pb < 0.2
    out["%b"] = IR.positions(up & lowb & lowb.shift(1) & lowb.shift(2), pb > 0.8)
    out["RSI4<25"] = IR.positions(up & (r4 < 25), r4 > 55)
    out["5日安値"] = IR.positions(up & (c <= c.rolling(5).min()), ex5)
    return out


def short_rules(d):
    """売り側（鏡の形）。0/1 の建玉（売りの大きさ）。"""
    c = d["close"]
    dnr = c < c.rolling(200).mean()
    r2 = IR.rsi_wilder(c, 2)
    out = {"R2S": IR.positions(dnr & (r2 > 90), c < c.rolling(5).mean()),
           "D7S": IR.positions(dnr & (c >= c.rolling(7).max()), c <= c.rolling(7).min())}
    rng = d["high"] - d["low"]
    ibs = ((c - d["low"]) / rng.where(rng > 0)).fillna(0.5)
    out["IBSS（すべての日）"] = (ibs > 0.8).astype(float)
    out["IBSS（200日の平均より下）"] = ((ibs > 0.8) & dnr).astype(float)
    return out


def pnl(d, w, rate, div, kind):
    """建玉 w（＋買い・−売り、終値で決める）の日次の損益。kind = cash（その終値で売買）／cfd（次の日足の始値で売買）。"""
    days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
    fl = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
    fs = (rate - IR.MARKUP - div) / 100.0 / 360.0 * days
    c, o = d["close"], d["open"]
    if kind == "cash":
        held = w.shift(1).fillna(0.0)
        fin = held.clip(lower=0) * fl + (-held.clip(upper=0)) * fs
        return held * c.pct_change().fillna(0.0) + fin - (w - held).abs() * IR.COST
    h_on, h_day = w.shift(2).fillna(0.0), w.shift(1).fillna(0.0)
    fin = h_on.clip(lower=0) * fl + (-h_on.clip(upper=0)) * fs
    return h_on * (o / c.shift(1) - 1.0).fillna(0.0) + h_day * (c / o - 1.0).fillna(0.0) + fin - (h_day - h_on).abs() * IR.COST


def stat_cells(r, start, per):
    r = r[r.index >= start]
    z = r * (0.10 / (r.std() * np.sqrt(ANN)))
    eq = (1 + z).cumprod()
    yr = z.groupby(z.index.year).sum()
    q = z.quantile(0.01)
    return (f"{sh(z):+.2f} | {sh(z) * np.sqrt(len(z) / ANN):+.1f} | {z.min() * 100:.1f}% | {z[z <= q].mean() * 100:.2f}% | {(eq / eq.cummax() - 1).min() * 100:.0f}% | {yr.min() * 100:.1f}% | "
            + " | ".join(f"{sh(z[(z.index >= a) & (z.index < b)]):+.2f}" for _, a, b in per)), z


def main():
    lines = ["# 研究：売られすぎの戻りの層の深掘り（`tools/research/index_deep.py`）", "",
             "土台は98章の改良後の形（HAR 型の見積もり・VIX の倍率 0.5／1／1.5・逆指値 4×σ）。コスト込み、値動きを年10%にそろえる。", ""]
    data = {}
    for kind, start, per in (("cash", IRK.START, IRK.PER), ("cfd", "2011-09-01", V.PER_C)):
        sets = V.load_sets(kind)
        rk = {n: V.vix_rank(t[0].index)[0] for n, t in sets.items()}
        vm = {n: V.mult_of(rk[n], MULT) for n in sets}
        data[kind] = (sets, vm, start, per)
    title = {"cash": "現物の3指数（2000年10月〜2026年11月）", "cfd": "EA と同じ形（CFD、2011年9月〜2026年10月）"}

    def base_long(kind, n_of=None, g=None, stop=4.0):
        """改良後の形の買いの層。n_of(name, d) で票の数を置きかえ、g で重み（票の数 → 重み）を置きかえる。"""
        sets, vm, start, per = data[kind]
        ss = {}
        for name, (d, n, sg, rate, div) in sets.items():
            nn = n if n_of is None else n_of(name, d, n)
            if g is not None:
                nn = nn.map(lambda v: g(v)) * 3.0            # sleeve() は n ÷ 3 を重みにするので、合わせる
            ss[name] = (d, nn, sg, rate, div)
        return V.sleeve(ss, vm, kind, stop)

    # ---------- A 売り側
    for kind in ("cash", "cfd"):
        sets, vm, start, per = data[kind]
        head = "| 形 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | " + " | ".join(p[0] for p in per) + " | 買いの層との相関 | 持つ日の割合 |"
        lines += [f"## A 売り側（{title[kind]}）", "", head, "|---|" + "---|" * (8 + len(per))]
        long_r = base_long(kind)
        long_r = long_r[long_r.index >= start]
        shorts = {}
        for key in ("R2S", "D7S", "IBSS（すべての日）", "IBSS（200日の平均より下）", "R2S＋D7S＋IBSS（200日の平均より下）"):
            parts, act = [], []
            for name, (d, n, sg, rate, div) in sets.items():
                sr = short_rules(d)
                p = (sr["R2S"] + sr["D7S"] + sr["IBSS（200日の平均より下）"]) / 3.0 if key.startswith("R2S＋") else sr[key]
                w = -(p * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0) / len(sets)
                parts.append(pnl(d, w, rate, div, kind))
                act.append((p > 0).reindex(long_r.index).fillna(False))
            r = pd.concat(parts, axis=1, sort=True).fillna(0.0).sum(axis=1)
            r = r[r.index >= start]
            shorts[key] = r
            cells, _ = stat_cells(r, start, per)
            lines.append(f"| {key} | {cells} | {r.corr(long_r):+.2f} | {pd.concat(act, axis=1).any(axis=1).mean() * 100:.0f}% |")
            print(kind, lines[-1], flush=True)

        def s10(x):
            return x * (0.10 / (x.std() * np.sqrt(ANN)))
        lines += ["", "| 組み合わせ（買いの層の値動き年10% に、売りの層を足す） | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | " + " | ".join(p[0] for p in per) + " |",
                  "|---|" + "---|" * (6 + len(per))]
        for label, r in (("買いの層だけ（改良後の形）", long_r),
                         ("＋ 売り 3ルール（200日の平均より下）：売りの層の値動き 年5%", s10(long_r) + 0.5 * s10(shorts["R2S＋D7S＋IBSS（200日の平均より下）"])),
                         ("＋ 売り 3ルール：売りの層の値動き 年10%", s10(long_r) + s10(shorts["R2S＋D7S＋IBSS（200日の平均より下）"])),
                         ("＋ IBSS（200日の平均より下）だけ：年5%", s10(long_r) + 0.5 * s10(shorts["IBSS（200日の平均より下）"]))):
            cells, _ = stat_cells(r, start, per)
            lines.append(f"| {label} | {cells} |")
            print(kind, lines[-1], flush=True)
        lines.append("")

    # ---------- B 重み
    for kind in ("cash", "cfd"):
        sets, vm, start, per = data[kind]
        head = "| ルールがそろった数の重み（1つ:2つ:3つ） | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | " + " | ".join(p[0] for p in per) + " |"
        lines += [f"## B ルールがそろった数の重み（{title[kind]}）", "", head, "|---|" + "---|" * (6 + len(per))]
        for g in ((1, 2, 3), (1, 2, 4), (1, 2, 5), (1, 3, 6), (1, 1.5, 4), (0, 1, 3), (0, 1, 2), (1, 1, 1), (1, 2, 2)):
            gm = float(max(g))
            r = base_long(kind, g=lambda v, g=g, gm=gm: {0: 0.0, 1: g[0] / gm, 2: g[1] / gm, 3: g[2] / gm}[int(v)])
            cells, _ = stat_cells(r, start, per)
            lines.append(f"| {g[0]:g}:{g[1]:g}:{g[2]:g}{'（今の形）' if g == (1, 2, 3) else ''} | {cells} |")
            print(kind, lines[-1], flush=True)
        lines.append("")

    # ---------- C 票を足す
    for kind in ("cash", "cfd"):
        sets, vm, start, per = data[kind]
        head = "| 票にするルール | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | " + " | ".join(p[0] for p in per) + " | 今の形との相関 |"
        lines += [f"## C 公表済みの別のルールを票として足す（{title[kind]}）", "", head, "|---|" + "---|" * (7 + len(per))]
        base = base_long(kind)
        base = base[base.index >= start]
        extra = {name: more_rules(t[0]) for name, t in sets.items()}
        keys = list(next(iter(extra.values())).keys())

        def votes(sel, with_base=True):
            def f(name, d, n):
                tot = (n if with_base else n * 0.0) + sum(extra[name][k] for k in sel)
                return tot * 3.0 / (len(sel) + (3 if with_base else 0))          # 重み = 票の数 ÷ 票の最大
            return f
        rows = [("R2・D7・IBS（今の形）", None)]
        rows += [(f"＋ {k}", votes([k])) for k in keys]
        rows += [("＋ 6つすべて（9票）", votes(keys)), ("6つだけ（今の3つを使わない）", votes(keys, with_base=False))]
        for label, f in rows:
            r = base_long(kind, n_of=f)
            cells, _ = stat_cells(r, start, per)
            rr = r[r.index >= start]
            lines.append(f"| {label} | {cells} | {rr.corr(base):+.2f} |")
            print(kind, lines[-1], flush=True)
        lines.append("")

    # ---------- D 持ってからの日数
    sets, vm, start, per = data["cash"]
    rows = []
    for name, (d, n, sg, rate, div) in sets.items():
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
        fin = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
        y = ((d["close"].pct_change() + fin).shift(-1) / sg)
        on = (n >= 1).astype(int)
        age = on.groupby((on == 0).cumsum()).cumsum()                      # 持ち始めてからの日数（1 = 持ち始めた日）
        rows.append(pd.DataFrame({"y": y, "n": n, "age": age}))
    P = pd.concat(rows)
    P = P[(P.index >= IRK.START) & (P["n"] >= 1)].dropna()
    lines += ["## D 持ってからの日数ごとの、翌日の損益 ÷ 値動きの見積もり（現物の3指数、持ち越しのコスト込み）", "",
              "| 持ち始めてからの日数 | 平均（t 値、件数） | そのうちルールが2つ以上 |", "|---|---|---|"]
    for lab, m in (("1日目（持ち始めた日の翌日の損益）", P["age"] == 1), ("2日目", P["age"] == 2), ("3日目", P["age"] == 3), ("4〜5日目", P["age"].between(4, 5)),
                   ("6〜10日目", P["age"].between(6, 10)), ("11日目〜", P["age"] >= 11)):
        def cell(x):
            if len(x) < 30:
                return "—"
            by = x.groupby(level=0).mean()
            return f"{x.mean():+.3f}（t {by.mean() / by.std() * np.sqrt(len(by)):+.1f}、{len(x)} 件）"
        lines.append(f"| {lab} | {cell(P['y'][m])} | {cell(P['y'][m & (P['n'] >= 2)])} |")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_deep.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

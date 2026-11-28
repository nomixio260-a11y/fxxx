#!/usr/bin/env python3
"""研究：順張りの合図の形を、文献の形に替えると良くなるか（105章）。日付・時刻は使わない。

- 今の形（T0）：終値が200日の平均より上のあいだだけ買い持ち（7日ごとに見直す）。
- 候補（結果を見る前に決めた。これ以外は試さない）：
   T1 過去252日の値動きがプラスなら買い（Moskowitz・Ooi・Pedersen 2012 の「時系列モメンタム」）
   T2 過去126日・252日・504日の値動きの符号の平均（遅い側に寄せた組み合わせ。2009年以降は遅い側が相対的に良い、という報告による）
   T3 過去21日・63日・252日の符号の平均（Hurst・Ooi・Pedersen 2017 の形）
   T4 状態の形（Garg ほか 2020）：252日がプラスなら 1（短期が下でも長期に従う）、252日がマイナスで21日がプラスなら 0.7、どちらもマイナスなら 0
  どれも、買いだけ（売りは持たない）・7日ごとに見直す・建玉は「その銘柄の値動き（過去60日）が口座の年10%になる大きさ」で、T0 と同じ。
- データ：
   金・銀・銅：OANDA の商品CFDの口座の、実際の日足（2005〜06年から。注文を出さない観察で書き出したもの。リポジトリには入れていない）
   指数：実際に売買できた ETF（SPY 1993年〜・QQQ 1999年〜・DIA 1998年〜）。コストは CFD と同じ形（片道 0.02%、短期金利＋年2.5%）
- 売買は次の日足の始値。建玉の直し方は EA と同じ（合図が変わったとき、または、目標との差が 25% を超えたとき）。
  コスト：スプレッド（書き出した時点の値。往復で1回分）、スワップ（今の買いの年率を全期間に使う。金利の低かった時期には厳しめ）。
- 判定（結果を見る前に決めた）。T0 を置き換えるのは、次をすべて満たす形だけ：
   (a) 金：シャープ（コスト後）が、前半・後半の両方で T0 より高い
   (b) 金：最大の下落（同じ大きさで比べる）が、全期間で T0 より深くない
   (c) ほかの5銘柄（銀・銅・SPY・QQQ・DIA）：シャープの平均が T0 より高く、5銘柄のうち4つ以上で T0 を上回る
- 追加（金だけ。これも事前に決めた）：T0 の「売りも持つ」形（200日の平均より下なら売り）。判定は (a)(b) と同じ。
- 追加（どの銘柄を持つか。事前に決めた）：金だけ／金＋銀／金＋銅／金＋銀＋銅（同じ値動きの大きさで持ち、合計を同じ値動きにそろえる）。
  銘柄を足すのは、層のシャープが前半・後半の両方で上がるときだけ。
使い方: python3 -I tools/research/trend_signal.py <商品の口座の書き出しのフォルダ>  → reports/research/trend_signal.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_others as IO  # noqa: E402
import index_reversion as IR  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
UNIT = 0.10
FORMS = ("T0", "T1", "T2", "T3", "T4")
LABEL = {"T0": "T0 今の形（200日の平均より上）", "T1": "T1 過去252日がプラス", "T2": "T2 126・252・504日の符号の平均",
         "T3": "T3 21・63・252日の符号の平均", "T4": "T4 状態の形（長期が下・短期が上なら 0.7）", "LS": "T0 の、売りも持つ形"}


def raw_signal(c, form):
    """その日の終値までで決まる合図（0〜1。LS は −1〜1）。"""
    up = lambda n: (c / c.shift(n) - 1.0 > 0).astype(float).where(c.shift(n).notna())  # noqa: E731
    if form == "T0":
        return (c > c.rolling(200).mean()).astype(float).where(c.rolling(200).mean().notna())
    if form == "LS":
        m = c.rolling(200).mean()
        return ((c > m).astype(float) * 2.0 - 1.0).where(m.notna())
    if form == "T1":
        return up(252)
    if form == "T2":
        return (up(126) + up(252) + up(504)) / 3.0
    if form == "T3":
        return (up(21) + up(63) + up(252)) / 3.0
    if form == "T4":
        l, s = up(252), up(21)
        return (l + (1.0 - l) * s * 0.7).where(l.notna() & s.notna())
    raise ValueError(form)


def reviewed(sig, days=7):
    """days 日ごとに見直す（EA と同じ：前に見直した日足から days 日以上たった日足で見直す）。"""
    out = np.full(len(sig), np.nan)
    last, cur = None, np.nan
    v = sig.values
    for i, t in enumerate(sig.index):
        if np.isnan(v[i]):
            continue
        if last is None or (t - last).days >= days:
            cur, last = v[i], t
        out[i] = cur
    return pd.Series(out, index=sig.index)


def simulate(d, state, spread=0.0, swap_long=0.0, swap_short=0.0, fin=None, unit=UNIT, band=0.25, stop=None, sigma=None):
    """d：日足（open, high, low, close）。state：その日の終値で決まった状態。戻り値：日次の損益（口座に対する割合）、持っていた建玉（資金に対する倍率）、売買の回数。
    swap_long / swap_short：年 %（受け取りがプラス）。fin：買いの建玉にかかる金利（年 %、日ごと。ETF 用）。
    sigma：翌日の値動きの大きさの見積もり（1日の標準偏差。日ごと）。None なら、直近60日の値動きの大きさ。"""
    o, h, lo, c = (d[k].values.astype(float) for k in ("open", "high", "low", "close"))
    n = len(d)
    sd = pd.Series(c).pct_change().rolling(60).std().values if sigma is None else np.asarray(sigma, dtype=float)
    st = state.values
    days = np.diff(d.index.values).astype("timedelta64[D]").astype(float)
    ret = np.zeros(n)
    held = np.zeros(n)
    hcur, sprev, trades, stops = 0.0, 0.0, 0, 0
    for t in range(1, n - 1):
        s = st[t - 1]
        if np.isnan(s) or np.isnan(sd[t - 1]):
            continue
        ann = max(sd[t - 1] * np.sqrt(ANN), 0.025)
        w = s * unit / ann
        cost = 0.0
        if s != sprev or abs(hcur - w) > band * max(abs(hcur), abs(w)):
            cost = abs(w - hcur) * spread / 2.0
            trades += 1 if abs(w - hcur) > 1e-12 else 0
            hcur = w
        sprev = s
        ra = o[t + 1] / o[t] - 1.0
        stopped = False
        if stop is not None and hcur != 0.0:
            lim = stop * sd[t - 1]
            if hcur > 0 and lo[t] <= o[t] * (1.0 - lim):
                ra, stopped = -lim, True
            elif hcur < 0 and h[t] >= o[t] * (1.0 + lim):
                ra, stopped = lim, True
        dd = days[t]
        if fin is not None:
            carry = -max(hcur, 0.0) * fin[t] / 100.0 / 360.0 * dd
        else:
            carry = (max(hcur, 0.0) * swap_long + max(-hcur, 0.0) * swap_short) / 100.0 / 360.0 * dd
        rp = hcur * ra - cost + carry
        ret[t] = rp
        held[t] = hcur
        stops += 1 if stopped else 0
        hcur = 0.0 if stopped else hcur * (1.0 + ra) / (1.0 + rp)
    out = pd.Series(ret, index=d.index)
    out.attrs["stops"] = stops                                # 逆指値にかかった回数
    return out, pd.Series(held, index=d.index), trades


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 200 and x.std() > 0 else np.nan


def mdd(x):
    e = (1 + x).cumprod()
    return (e / e.cummax() - 1.0).min()


def run_form(d, form, costs, stop=None):
    state = reviewed(raw_signal(d["close"], form))
    return simulate(d, state, stop=stop, **costs)


def main():
    folder = sys.argv[1]
    data, props = IO.load(folder)
    inst = {}
    for sym, name in (("XAUUSD", "金"), ("XAGUSD", "銀"), ("COPPER", "銅")):
        d = data[sym]
        spread = float(props.loc[sym, "spread_points"]) * float(props.loc[sym, "point"]) / float(props.loc[sym, "bid"])
        inst[name] = (d, dict(spread=spread, swap_long=float(props.loc[sym, "swap_long"]), swap_short=float(props.loc[sym, "swap_short"])))
    for etf in ("SPY", "QQQ", "DIA"):
        d = Y.fetch(etf)[["open", "high", "low", "close"]].dropna()
        fin = (IR.short_rate("USD", d.index) + IR.MARKUP).values
        inst[etf] = (d, dict(spread=2 * IR.COST, fin=fin))
    res = {}
    lines = ["# 研究：順張りの合図の形（`tools/research/trend_signal.py`）", "",
             "値は、コスト後。建玉は、その銘柄の値動き（過去60日）が口座の年10%になる大きさ。買いだけ・7日ごとに見直し・売買は次の日足の始値。", "",
             "## 1 銘柄 × 形：シャープ（全期間・前半・後半）、最大の下落、持っていた日の割合、1年あたりの売買の回数", "",
             "| 銘柄（期間） | 形 | 全期間 | 前半 | 後半 | 2009年〜 | 最大の下落 | 持っていた日の割合 | 売買（年） |", "|---|---|---|---|---|---|---|---|---|"]
    for name, (d, costs) in inst.items():
        start = d.index[560]                                   # どの形も合図が出そろってから
        end = d.index[-2]
        mid = start + (end - start) / 2
        for form in FORMS + (("LS",) if name == "金" else ()):
            r, hd, tr = run_form(d, form, costs)
            r, hd = r[(r.index >= start) & (r.index <= end)], hd[(hd.index >= start) & (hd.index <= end)]
            a, b = r[r.index <= mid], r[r.index > mid]
            res[(name, form)] = dict(sh=sh(r), a=sh(a), b=sh(b), dd=mdd(r), r=r, mid=mid, start=start, end=end)
            yrs = len(r) / ANN
            lines.append(f"| {name}（{start.date()}〜{end.date()}。前半は {mid.date()} まで） | {LABEL[form]} | {sh(r):+.2f} | {sh(a):+.2f} | {sh(b):+.2f} | "
                         f"{sh(r[r.index >= '2009-01-01']):+.2f} | {mdd(r) * 100:.0f}% | {(hd != 0).mean() * 100:.0f}% | {tr / (len(d) / ANN):.1f} |")
            print(lines[-1], flush=True)
    # ---------- 判定
    lines += ["", "## 2 判定（事前に決めた基準）", "",
              "| 形 | (a) 金：前半・後半とも T0 より高い | (b) 金：最大の下落が T0 より深くない | (c) ほかの5銘柄：シャープの平均（T0 の平均）・上回った数 | 判定 |", "|---|---|---|---|---|"]
    others = ("銀", "銅", "SPY", "QQQ", "DIA")
    base = res[("金", "T0")]
    for form in FORMS[1:] + ("LS",):
        g = res[("金", form)]
        a = g["a"] > base["a"] and g["b"] > base["b"]
        b = g["dd"] >= base["dd"] - 1e-9
        if form == "LS":
            ok = a and b
            lines.append(f"| {LABEL[form]} | {'○' if a else '×'}（{g['a']:+.2f} / {g['b']:+.2f}、T0 は {base['a']:+.2f} / {base['b']:+.2f}） | {'○' if b else '×'}（{g['dd'] * 100:.0f}%、T0 は {base['dd'] * 100:.0f}%） | —（金だけの判定） | {'**合格**' if ok else '不合格'} |")
        else:
            av = np.mean([res[(o, form)]["sh"] for o in others])
            av0 = np.mean([res[(o, "T0")]["sh"] for o in others])
            wins = sum(res[(o, form)]["sh"] > res[(o, "T0")]["sh"] for o in others)
            c = av > av0 and wins >= 4
            ok = a and b and c
            lines.append(f"| {LABEL[form]} | {'○' if a else '×'}（{g['a']:+.2f} / {g['b']:+.2f}、T0 は {base['a']:+.2f} / {base['b']:+.2f}） | {'○' if b else '×'}（{g['dd'] * 100:.0f}%、T0 は {base['dd'] * 100:.0f}%） | "
                         f"{'○' if c else '×'}（{av:+.2f}、T0 は {av0:+.2f}。{wins} / 5） | {'**合格**' if ok else '不合格'} |")
        print(lines[-1], flush=True)
    # ---------- 逆指値あり（EA の金の層の形）での確認：T0 と、合格した形（なければ T0 だけ）
    lines += ["", "## 3 金：逆指値（その日の始値から 4 × 1日の値動きの見積もり）を付けた場合", "",
              "| 形 | 全期間 | 前半 | 後半 | 最大の下落 | 逆指値にかかった日（年） |", "|---|---|---|---|---|---|"]
    d, costs = inst["金"]
    for form in FORMS:
        r, hd, tr = run_form(d, form, costs, stop=4.0)
        b0 = res[("金", form)]
        hits = r.attrs["stops"]
        r = r[(r.index >= b0["start"]) & (r.index <= b0["end"])]
        lines.append(f"| {LABEL[form]} | {sh(r):+.2f} | {sh(r[r.index <= b0['mid']]):+.2f} | {sh(r[r.index > b0['mid']]):+.2f} | {mdd(r) * 100:.0f}% | {hits / (len(d) / ANN):.1f} |")
        print(lines[-1], flush=True)
    # ---------- どの銘柄を持つか（T0 の形のまま）
    lines += ["", "## 4 どの銘柄を持つか（T0 の形。合計の値動きを、金だけのときと同じにそろえる）", "",
              "| 持つ銘柄 | 全期間 | 前半 | 後半 | 最大の下落 | 判定（前半・後半とも、金だけより高い） |", "|---|---|---|---|---|---|"]
    g = res[("金", "T0")]
    st, en, mid = g["start"], g["end"], g["mid"]
    base_r = g["r"]
    for combo in (("金",), ("金", "銀"), ("金", "銅"), ("金", "銀", "銅")):
        parts = pd.concat([res[(k, "T0")]["r"] for k in combo], axis=1, sort=True).fillna(0.0)
        parts = parts[(parts.index >= st) & (parts.index <= en)]
        r = parts.sum(axis=1)
        r = r * (base_r.std() / r.std())
        a, b = sh(r[r.index <= mid]), sh(r[r.index > mid])
        ok = len(combo) > 1 and a > g["a"] and b > g["b"]
        lines.append(f"| {'＋'.join(combo)} | {sh(r):+.2f} | {a:+.2f} | {b:+.2f} | {mdd(r) * 100:.0f}% | {'—' if len(combo) == 1 else ('**合格**' if ok else '不合格')} |")
        print(lines[-1], flush=True)
    cr = pd.concat([res[(k, "T0")]["r"] for k in ("金", "銀", "銅")], axis=1, sort=True).fillna(0.0).corr()
    lines += ["", f"- 層どうしの日々の損益の相関：金と銀 {cr.iloc[0, 1]:+.2f}、金と銅 {cr.iloc[0, 2]:+.2f}、銀と銅 {cr.iloc[1, 2]:+.2f}。",
              "- コスト：" + "、".join(f"{k} スプレッド {v[1].get('spread', 0) * 100:.3f}%・買いのスワップ 年 {v[1].get('swap_long', float('nan')):.2f}%" for k, v in inst.items() if k in ("金", "銀", "銅"))
              + "。ETF は 片道 0.02%・短期金利＋年2.5%。",
              "- 原油（USOIL・UKOIL）は、書き出した日足の始値が前の日の終値と大きくずれている日が多く（データの形の問題）、また先物を元にした商品CFDは、過去のスワップ（価格調整額）の記録がないため、この検証には入れていない。"]
    out = os.path.join(F.ROOT, "reports", "research", "trend_signal.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

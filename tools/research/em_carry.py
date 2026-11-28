#!/usr/bin/env python3
"""研究：為替の口座で、高金利の通貨（メキシコペソ・南アフリカランド・トルコリラ）の対円を「金利差の受け取り ＋ 流れ」で持つ層は成り立つか（108章）。日付・時刻は使わない。

- これまで：為替の金利差の層（EA の方式 7。主要通貨の 17 ペア）は、2007年以降のシャープが 0.08 で、足す価値がなかった（108章 3）。
  高金利の新興国通貨は、OANDA の為替の口座で売買できるが（MXNJPY・ZARJPY・TRYJPY）、まだ一度も検証していない。金利差は主要通貨よりずっと大きい
  （OANDA の買いのスワップ：MXNJPY 年 +6.2%、ZARJPY +3.1%、TRYJPY +20.9%。2026年11月27日の口座の値）。その代わり、通貨そのものが下がり続ける危険がある。
- 形（結果を見る前に決めた。これ以外は試さない）。買いだけ（売りはスワップの支払いが大きい）：
   H0 いつも買い持ち（参考）
   H1 過去60日の値動きがプラスのときだけ買い持ち（EA の方式 7 と同じ「流れ」の決め方）。5取引日ごとに見直し。
      直近10日の値動きが、直近120日の2倍を超えているあいだは持たない（方式 7 の「急変の回避」と同じ）
   H2 終値が200日の平均より上のときだけ買い持ち（指数・金の順張りの層と同じ決め方）。5取引日ごとに見直し
  建玉は、その通貨の値動き（直近60日）が口座の年10%になる大きさ（上限：資金の2倍）。
- コスト：スプレッド（往復。MXNJPY 0.07%・ZARJPY 0.12%・TRYJPY 0.6%）。スワップは、3か月金利の差（FRED、月次、1か月遅らせる）に、
  OANDA の今の受け取りの割合をかける（MXNJPY 1.0・ZARJPY 0.6・TRYJPY 0.6。今の口座の値と金利差の比）。
- データ：Yahoo Finance の日足（MXNJPY・ZARJPY 2003年12月〜、TRYJPY 2007年5月〜）。次の日にほぼ元に戻る 8% 超の値動きは、誤った値として除く。
- 判定（結果を見る前に決めた）。次の検証（EA・MT5）に進めるのは、同じ形が次をすべて満たすときだけ：
   (a) メキシコペソとランドを同じ値動きで合わせた層のシャープ（コスト後）が、全期間で 0.4 以上、前半・後半ともプラス
   (b) メキシコペソ・ランドとも、単独で全期間プラス
   (c) 指数の口座 ＋ 金の口座（半分ずつ。106章の形）に、この層を 20% 足したとき（指数 40・金 40・この層 20。値動きは指数の口座にそろえる）、
       最大の下落をそろえた年率の伸びが、足さない場合より高い。前半（2007〜16年）・後半（2017年〜）の両方で
使い方: python3 tools/research/em_carry.py  → reports/research/em_carry.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import composite_20y as C20  # noqa: E402
import composite_accounts as CA  # noqa: E402
import fred_data as F  # noqa: E402
import index_trend_combo as ITC  # noqa: E402
import target300 as T  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
PAIRS = {"MXNJPY": ("MXNJPY=X", "IR3TIB01MXM156N", 0.0007, 1.0), "ZARJPY": ("ZARJPY=X", "IR3TIB01ZAM156N", 0.0012, 0.6), "TRYJPY": ("TRYJPY=X", "IRSTCI01TRM156N", 0.006, 0.6)}
FORMS = (("H0 いつも買い持ち（参考）", "H0"), ("H1 過去60日がプラス・急変の回避", "H1"), ("H2 200日の平均より上", "H2"))


def load(name):
    tk, code, spread, k = PAIRS[name]
    c = Y.fetch_ticker(name, tk)["close"].dropna()
    c = c[c > 0]
    r = c.pct_change()
    bad = (r.abs() > 0.08) & ((r + r.shift(-1)).abs() < 0.02)
    bad = bad | bad.shift(1).fillna(False)
    r = r.where(~bad, 0.0).fillna(0.0)
    c = (1 + r).cumprod()
    m = (F.fetch(code).dropna() - F.fetch("IR3TIB01JPM156N").dropna().reindex(F.fetch(code).dropna().index, method="ffill")).dropna().shift(1).dropna()
    carry = m.reindex(m.index.union(c.index)).ffill().reindex(c.index) * k            # 買いで受け取る年率 %
    return c, r, carry, spread


def sleeve(name, form, unit=0.10, check=5):
    c, r, carry, spread = load(name)
    up60 = (c / c.shift(60) - 1.0) > 0
    calm = r.rolling(10).std() <= 2.0 * r.rolling(120).std()
    up200 = c > c.rolling(200).mean()
    raw = {"H0": pd.Series(True, index=c.index), "H1": up60 & calm, "H2": up200}[form]
    raw = raw.where(c.rolling(200).mean().notna())
    st = np.full(len(c), np.nan)
    last, cur = None, np.nan
    for i in range(len(c)):
        v = raw.iloc[i]
        if pd.isna(v):
            continue
        if last is None or i - last >= check:
            cur, last = float(v), i
        st[i] = cur
    st = pd.Series(st, index=c.index)
    vol = (r.rolling(60).std() * np.sqrt(ANN)).clip(lower=0.03)
    w = (st * unit / vol).clip(upper=2.0).shift(1).fillna(0.0)
    days = pd.Series(c.index, index=c.index).diff().dt.days.fillna(1.0).clip(upper=5)
    p = w * r + w * carry.fillna(0.0) / 100.0 / 365.0 * days - (w - w.shift(1).fillna(0.0)).abs() * spread / 2.0
    return p.iloc[260:], st.iloc[260:]


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 100 and x.std() > 0 else np.nan


def st20(r):
    e = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    return dict(cagr=e.iloc[-1] ** (1 / yrs) - 1, dd=(e / e.cummax() - 1).min(), sh=sh(r))


def same_dd(r, dd0):
    lo, hi = 0.05, 20.0
    for _ in range(50):
        k = (lo + hi) / 2
        if st20(r * k)["dd"] < dd0:
            hi = k
        else:
            lo = k
    return st20(r * lo)["cagr"]


def main():
    lines = ["# 研究：高金利の通貨の対円を、金利差の受け取り ＋ 流れで持つ（`tools/research/em_carry.py`）", "",
             "買いだけ。建玉は、その通貨の値動きが口座の年10%になる大きさ。コスト（スプレッド）・スワップ込み。", "",
             "## 1 通貨ごと・形ごと", "", "| 通貨（期間） | 形 | シャープ | 前半 | 後半 | 年率 | 最大の下落 | 持っている日の割合 | 2015年〜 | 2022年〜 |", "|---|---|---|---|---|---|---|---|---|---|"]
    R = {}
    for name in PAIRS:
        for lab, form in FORMS:
            p, st = sleeve(name, form)
            R[(name, form)] = p
            mid = p.index[len(p) // 2]
            e = (1 + p).cumprod()
            lines.append(f"| {name}（{p.index[0].date()}〜） | {lab} | {sh(p):+.2f} | {sh(p[p.index <= mid]):+.2f} | {sh(p[p.index > mid]):+.2f} | {p.mean() * ANN * 100:+.1f}% | {(e / e.cummax() - 1).min() * 100:.0f}% | "
                         f"{(st > 0).mean() * 100:.0f}% | {sh(p[p.index >= '2015-01-01']):+.2f} | {sh(p[p.index >= '2022-01-01']):+.2f} |")
            print(lines[-1], flush=True)
    # ---------- 合わせた層と、指数・金との組み合わせ
    cat = CA.catalog()
    E = {k: CA.rel(c) for k, c in cat.items()}
    rep = T.cash_returns(5.0).add(ITC.trend_returns("NASDAQ100", 10.0), fill_value=0.0)
    idx, _, _, _ = C20.spliced(E[("Index_Demo", 0.0, "long")], rep)
    idx = idx[idx.index >= C20.START]
    gold = E[("金", 22.4, "long")].pct_change().dropna()
    gold = gold[gold.index >= C20.START]
    lines += ["", "## 2 メキシコペソ ＋ ランド（同じ値動きで半分ずつ）と、指数・金の口座との組み合わせ", "",
              "| 形 | 層のシャープ | 前半 | 後半 | 最大の下落 | 指数の口座との相関（週ごとの損益） | 指数 50・金 50 → 指数 40・金 40・この層 20：下落をそろえた年率（全期間） | 前半（2007〜16年） | 後半（2017年〜） |", "|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for lab, form in FORMS:
        c2 = pd.concat([R[("MXNJPY", form)], R[("ZARJPY", form)]], axis=1, sort=True).dropna().mean(axis=1)
        mid = c2.index[len(c2) // 2]
        z = pd.concat([idx, gold, c2], axis=1, sort=True).fillna(0.0)
        z.columns = ["i", "g", "c"]
        z = z[(z.index >= C20.START) & (z.index <= idx.index[-1])]
        k = z["i"].std() / z["c"].std()
        wk = z.resample("W").sum()
        rho = wk[["i", "c"]].corr().iloc[0, 1]
        cells = []
        okc = True
        for a, b in ((C20.START, "2030-01-01"), (C20.START, "2017-01-01"), ("2017-01-01", "2030-01-01")):
            q = z[(z.index >= a) & (z.index < b)]
            base = 0.5 * q["i"] + 0.5 * q["g"]
            mix = 0.4 * q["i"] + 0.4 * q["g"] + 0.2 * k * q["c"]
            b0 = st20(base)
            c1 = same_dd(mix, b0["dd"])
            cells.append(f"{b0['cagr'] * 100:+.1f}% → {c1 * 100:+.1f}%")
            okc = okc and (c1 > b0["cagr"])
        e = (1 + c2).cumprod()
        res[form] = dict(sh=sh(c2), a=sh(c2[c2.index <= mid]), b=sh(c2[c2.index > mid]), each=(sh(R[("MXNJPY", form)]), sh(R[("ZARJPY", form)])), okc=okc)
        lines.append(f"| {lab} | {sh(c2):+.2f} | {res[form]['a']:+.2f} | {res[form]['b']:+.2f} | {(e / e.cummax() - 1).min() * 100:.0f}% | {rho:+.2f} | " + " | ".join(cells) + " |")
        print(lines[-1], flush=True)
    lines += ["", "## 3 判定（事前に決めた基準）", "", "| 形 | (a) シャープ 0.4 以上・前半後半ともプラス | (b) 2通貨とも単独でプラス | (c) 足すと、下落をそろえた年率が上がる（全期間・前半・後半） | 判定 |", "|---|---|---|---|---|"]
    for lab, form in FORMS[1:]:
        x = res[form]
        a = x["sh"] >= 0.4 and x["a"] > 0 and x["b"] > 0
        b = x["each"][0] > 0 and x["each"][1] > 0
        lines.append(f"| {lab} | {'○' if a else '×'}（{x['sh']:+.2f}、{x['a']:+.2f}／{x['b']:+.2f}） | {'○' if b else '×'}（{x['each'][0]:+.2f}・{x['each'][1]:+.2f}） | {'○' if x['okc'] else '×'} | "
                     f"{'**次の検証に進める**' if (a and b and x['okc']) else '不合格'} |")
        print(lines[-1], flush=True)
    open(os.path.join(F.ROOT, "reports", "research", "em_carry.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

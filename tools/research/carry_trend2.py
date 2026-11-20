#!/usr/bin/env python3
"""金利差＋トレンド（83〜85章）の改良の2回目（時刻・曜日・日付は判断に使わない）。

- 毎日の手じまい：新しく持つ・増やすのは週1回のまま。持っているペアのトレンドが逆向きになった、または急変（直近10日の値動き > 120日の2倍）
  になったら、次の入れ替えを待たずに、その日のうちに手じまう。
- 通貨ごとの偏りの上限：各通貨の買い・売りの合計（ペアの重みを通貨に分けて足したもの）が、全体の重みの合計の c 倍を超えたら、
  その通貨を含むペアの重みを縮める（1つの通貨の急変で全体が崩れないように）。
- 下落時の縮小：この方式の損益の最高値から d% 以上下げているあいだは、建玉を半分にする（その日までの損益だけで判断）。
- 設定は 21年11月〜24年10月で選び、24年11月〜25年10月・25年11月〜26年10月は答え合わせにだけ使う。
使い方: python3 tools/research/carry_trend2.py  → reports/research/carry_trend2.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carry_trend as CT  # noqa: E402
import daily_strats as DS  # noqa: E402


def ccy_cap(w, cap):
    """各通貨の正味の重みが、重みの合計の cap 倍を超えないように縮める（1回の調整）。"""
    if cap is None:
        return w
    w = w.copy()
    gross = w.abs().sum(axis=1)
    ccys = sorted({p[:3] for p in w.columns} | {p[3:] for p in w.columns})
    for c in ccys:
        expo = sum(w[p] for p in w.columns if p[:3] == c) - sum(w[p] for p in w.columns if p[3:] == c)
        lim = cap * gross
        over = expo.abs() > lim
        if not over.any():
            continue
        f = (lim / expo.abs()).where(over, 1.0).fillna(1.0)
        for p in w.columns:
            if p[:3] == c or p[3:] == c:
                w[p] = w[p] * f
    return w


def run2(px, cost_frac, carry, markup, L=60, thr=1.0, topk=5, crash=2.0, voltarget=0.10, rb=5,
         daily_exit=False, cap=None, dd=None):
    ret = px.pct_change().shift(-1)
    r_past = px.pct_change()
    vol = r_past.rolling(60, min_periods=40).std()
    net_carry = carry.abs() - markup
    sig = np.sign(carry).where(net_carry >= thr, 0.0)
    tr = np.sign(px / px.shift(L) - 1.0)
    sig = sig.where(np.sign(sig) == tr, 0.0)
    v10 = r_past.rolling(10, min_periods=8).std()
    v120 = r_past.rolling(120, min_periods=80).std()
    calm = v10 <= crash * v120
    sig = sig.where(calm, 0.0)
    w = (sig / vol)
    score = (net_carry / 100.0 / 261.0 / vol).where(sig != 0)
    rk = score.rank(axis=1, ascending=False)
    w = w.where(rk <= topk, 0.0).fillna(0.0)
    g = w.abs().sum(axis=1).replace(0, np.nan)
    target = w.div(g, axis=0).fillna(0.0)
    target = ccy_cap(target, cap)
    # 週1回だけ入れ替え。毎日の手じまいでは、トレンドが逆・急変のペアだけ 0 にする
    held = np.zeros_like(target.values)
    tv = target.values
    exit_ok = ((np.sign(carry) == tr) & calm).values      # 持ち続けてよい条件（その日の値動きだけで判断）
    cur = np.zeros(target.shape[1])
    for i in range(len(target)):
        if i % rb == 0:
            cur = tv[i].copy()
        elif daily_exit:
            bad = (cur != 0) & ~exit_ok[i]
            cur = np.where(bad, 0.0, cur)
        held[i] = cur
    w = pd.DataFrame(held, index=target.index, columns=target.columns)
    pnl = (w * ret).sum(axis=1) + (w * (carry - np.sign(w) * markup) / 100.0 / 261.0).sum(axis=1)
    tc = ((w - w.shift(1).fillna(0.0)).abs() * cost_frac.fillna(0.01)).sum(axis=1)
    tot = pnl - tc
    rv = tot.rolling(60, min_periods=40).std().shift(1) * np.sqrt(261)
    scale = (voltarget / rv).clip(0, 3.0).fillna(1.0)
    tot = tot * scale
    if dd is not None:
        out = np.zeros(len(tot))
        eq, peak = 1.0, 1.0
        for i, x in enumerate(tot.values):
            m = 0.5 if eq < peak * (1 - dd) else 1.0
            out[i] = m * x
            eq *= (1 + out[i])
            peak = max(peak, eq)
        tot = pd.Series(out, index=tot.index)
    return tot


def main():
    px, cf = CT.load_universe(False)
    carry, mk = CT.carry_table(px)
    markup = pd.DataFrame({p: mk[p] for p in px.columns}, index=px.index)
    lines = list(CT.__dict__.get("HEAD", [])) or [
        "# 金利差＋トレンドの改良の2回目（`tools/research/carry_trend2.py`）", "",
        "年率シャープ（期間ごと）と、21年11月〜26年10月を年率ボラティリティ 10% にそろえたときの年率・最大の下落・マイナスの月・建玉。", "",
        "| 形 | " + " | ".join(p[0] for p in CT.PER) + " | 年率（ボラ10%） | 最大の下落 | マイナスの月 | 建玉 |",
        "|---|" + "---|" * (len(CT.PER) + 4)]
    lines.append(CT.describe(run2(px, cf, carry, markup), "今の形（週1回の入れ替え）"))
    lines.append(CT.describe(run2(px, cf, carry, markup, daily_exit=True), "＋毎日の手じまい"))
    for cap in (0.3, 0.4, 0.5):
        lines.append(CT.describe(run2(px, cf, carry, markup, cap=cap), f"＋通貨ごとの偏りの上限 {cap:.0%}"))
        lines.append(CT.describe(run2(px, cf, carry, markup, cap=cap, daily_exit=True), f"＋偏りの上限 {cap:.0%}＋毎日の手じまい"))
    for d in (0.10, 0.15):
        lines.append(CT.describe(run2(px, cf, carry, markup, dd=d), f"＋下落 {d:.0%} で半分"))
        lines.append(CT.describe(run2(px, cf, carry, markup, dd=d, daily_exit=True), f"＋下落 {d:.0%} で半分＋毎日の手じまい"))
    out = os.path.join(DS.ROOT, "reports", "research", "carry_trend2.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""研究：戻りの層で、「上げを確かめてから買う」「上げたら買い増す」形は、今の形（区切りですぐ買う）より良いか（108章）。日付・時刻は使わない。

- きっかけ：intraday_tp.py で、日中の利益確定の指値（＋1σ で売る）は、年率を +23.8% → +15.5% に下げた。＋1σ に届いた日は、そのあとも上げ続けることが多い、ということ。
  99章では、少し下の指値で待つ形も悪かった（すぐ戻る取引を取り逃す）。98章では、近い逆指値も悪かった（下げたあとに戻る）。
  3つを合わせると、売られすぎの局面の1日の中では「下げは戻り、上げは続く」。それなら、上げを確かめてから買う形・上げたら買い増す形が、理にかなう。
- 形（結果を見る前に決めた。これ以外は試さない）：
   今の形：売買の時刻（日足の区切りの5分後）に、目標の建玉まですぐ買う
   Ea：買い増す分は、すぐ買わず、「その値段 ＋ a×σ」の逆指値の買いで待つ（その日のうちに届かなければ、買わない。次の日足で決め直す）。a = 0.25・0.5・1.0
       減らす分・手じまいは、今の形と同じ（区切りですぐ）。すでに持っている分は、そのまま。
   Pa：今の形のとおりすぐ買い、さらに「その値段 ＋ a×σ」に届いたら、建玉の半分を買い増す（強制ロスカットを避ける上限の範囲で）。
       買い増した分は、次の日足の区切りで、ふつうの決め方に戻す。a = 0.5・1.0
   逆指値は、どの形も今と同じ（売買の時刻の値段 − 4×σ）。買ったあとに届いたら、すべて手放す。
- データ・計算：intraday_tp.py と同じ（S&P500・NASDAQ100 の1分足、2011年9月〜2026年10月、EA の写し、ルール1つ分 8.75%、コスト込み）。
- 判定（結果を見る前に決めた）。採用するのは、同じ形が次をすべて満たすときだけ：
   (a) シャープが、前半（〜2019年3月）・後半の両方で、今の形より低くない
   (b) 最大の下落を今の形にそろえたときの年率の伸びが、今の形より高い
   (c) 急落の局面（7局面）の損益の合計が、今の形より良い
   (d) 同じ種類のとなりの形（E どうし・P どうし）も、(a)〜(c) を満たす
使い方: python3 tools/research/intraday_confirm.py  → reports/research/intraday_confirm.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AMS_OANDA", "1")
import fred_data as F  # noqa: E402
import fx_hedge as FH  # noqa: E402
import intraday_tp as TP  # noqa: E402
import lot_rounding as LR  # noqa: E402

FORMS = (("今の形", None), ("E0.25 ＋0.25σ を確かめてから買う", ("E", 0.25)), ("E0.5 ＋0.5σ", ("E", 0.5)), ("E1 ＋1σ", ("E", 1.0)),
         ("P0.5 ＋0.5σ で半分買い増す", ("P", 0.5)), ("P1 ＋1σ で半分買い増す", ("P", 1.0)))


def path(m1, t_from, day):
    t, hi, lo = m1
    a = np.searchsorted(t, np.datetime64(t_from), side="left")
    b = np.searchsorted(t, np.datetime64(day + pd.Timedelta(days=1)), side="left")
    return hi[a:b], lo[a:b]


def simulate(unit, form=None, start=FH.START, end=FH.END, deposit=1e10):
    D, ST, SIGD, OK, M1, days, uj, VM = TP.load()
    SY = LR.SYMS
    cash, lots = deposit, {s: 0.0 for s in SY}
    last_close = {s: np.nan for s in SY}
    prev_n = {s: -1.0 for s in SY}
    eqs, idx = [], []
    prev_day = None
    cnt = dict(wait=0, got=0, add=0, sl=0)
    cost = 1.0 + LR.SPREAD_BP / 1e4
    for day in [x for x in days if pd.Timestamp(start) <= x <= pd.Timestamp(end)]:
        fx = float(uj.loc[day])
        if prev_day is not None:
            mult = 3 if prev_day.dayofweek == 4 else 1
            for s in SY:
                if lots[s] > 0:
                    cash -= lots[s] * last_close[s] * fx * LR.SWAP / 100.0 / 360.0 * mult
        i = {s: D[s].index.get_loc(day) for s in SY}
        ok = all(i[s] > 0 and not np.isnan(D[s]["px"].iloc[i[s]]) and OK[s].iloc[i[s] - 1] and not np.isnan(SIGD[s].iloc[i[s] - 1]) for s in SY)
        if ok:
            px = {s: D[s]["px"].iloc[i[s]] for s in SY}
            eq = cash + sum(lots[s] * px[s] * fx for s in SY)
            n = {s: ST[s].iloc[i[s] - 1] for s in SY}
            sd = {s: SIGD[s].iloc[i[s] - 1] for s in SY}
            vm = VM.loc[D[SY[0]].index[i[SY[0]] - 1]]
            tgt = {s: eq * LR.W[int(round(n[s]))] * unit * vm / 100.0 / max(sd[s] * np.sqrt(252), 0.025) for s in SY}
            need = sum(tgt[s] * (LR.SL * sd[s] + LR.MRATE) for s in SY)
            room = 1.0                                           # 買い増しに使える余地（上限に対する、目標の建玉の割合の逆数）
            if need > LR.GUARD * eq > 0:
                for s in SY:
                    tgt[s] *= LR.GUARD * eq / need
            elif need > 0:
                room = LR.GUARD * eq / need
            changed = any(n[s] != prev_n[s] for s in SY)
            pend = {}                                            # 逆指値の買いで待つ分（lot）
            for s in SY:
                prev_n[s] = n[s]
                cur = lots[s]
                tl = LR.round_floor(tgt[s] / (px[s] * fx), *LR.LOTS[s])
                if tl <= 0:
                    if cur > 0:
                        cash += cur * px[s] * fx
                        lots[s] = 0.0
                elif changed or cur <= 0 or abs(cur - tl) > LR.BAND * max(cur, tl):
                    if tl > cur:
                        if form is not None and form[0] == "E":
                            pend[s] = tl - cur
                        else:
                            cash -= (tl - cur) * px[s] * fx * cost
                            lots[s] = tl
                    else:
                        cash += (cur - tl) * px[s] * fx
                        lots[s] = tl
            for s in SY:
                sl = px[s] * (1.0 - LR.SL * sd[s])
                hi, lo = path(M1[s], D[s]["px_time"].iloc[i[s]], day)
                if len(hi) == 0:
                    continue
                t_buy = None
                if form is not None:
                    lvl = px[s] * (1.0 + form[1] * sd[s])
                    extra = pend.get(s, 0.0) if form[0] == "E" else (LR.round_floor(lots[s] * min(0.5, max(room - 1.0, 0.0)), *LR.LOTS[s]) if lots[s] > 0 else 0.0)
                    if extra > 0:
                        cnt["wait"] += 1
                        if (hi >= lvl).any():
                            t_buy = int(np.argmax(hi >= lvl))
                # 逆指値：持っている分は最初から、買い増す分は買ったあとから
                isl = int(np.argmax(lo <= sl)) if (lo <= sl).any() else -1
                if t_buy is not None and not (0 <= isl <= t_buy):          # 逆指値が先（同じ足を含む）なら、買い増しは起きない（建玉がもうない）とみなす
                    cash -= extra * lvl * fx * cost
                    lots[s] += extra
                    cnt["got" if form[0] == "E" else "add"] += 1
                if lots[s] > 0 and isl >= 0:
                    if t_buy is not None and isl <= t_buy and form[0] == "E" and lots[s] == 0:
                        pass
                    cash += lots[s] * sl * fx
                    lots[s] = 0.0
                    cnt["sl"] += 1
        for s in SY:
            last_close[s] = D[s]["close"].iloc[i[s]]
        idx.append(day)
        eqs.append(cash + sum(lots[s] * last_close[s] * fx for s in SY))
        prev_day = day
    return pd.Series(eqs, index=pd.DatetimeIndex(idx)), cnt


def main():
    unit = 8.75
    lines = ["# 研究：上げを確かめてから買う・上げたら買い増す（`tools/research/intraday_confirm.py`）", "",
             f"S&P500・NASDAQ100 の1分足、{FH.START}〜{FH.END}。ルール1つ分 {unit}%。コスト込み。", "",
             "| 形 | 年率 | シャープ | 前半 | 後半 | 最大の下落 | 最悪の日 | 急落の局面の合計 | 下落をそろえた年率 | 待った回数 → 買えた回数（年） |", "|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for lab, form in FORMS:
        eq, cnt = simulate(unit, form)
        s, a, b = FH.st(eq), FH.st(eq, FH.START, FH.HALF), FH.st(eq, FH.HALF, FH.END)
        if form is None:
            dd0 = s["dd"]
        yrs = (eq.index[-1] - eq.index[0]).days / 365.25
        res[lab] = dict(sh=s["sh"], a=a["sh"], b=b["sh"], dd=s["dd"], ep=FH.ep_sum(eq), c2=TP.same_dd(eq, dd0))
        lines.append(f"| {lab} | {s['cagr'] * 100:+.1f}% | {s['sh']:+.2f} | {a['sh']:+.2f} | {b['sh']:+.2f} | {s['dd'] * 100:.1f}% | {s['wd'] * 100:.1f}% | {res[lab]['ep'] * 100:+.1f}% | {res[lab]['c2'] * 100:+.1f}% | "
                     f"{cnt['wait'] / yrs:.0f} → {(cnt['got'] + cnt['add']) / yrs:.0f} |")
        print(lines[-1], flush=True)
    base = res[FORMS[0][0]]
    ok = {lab: (res[lab]["a"] >= base["a"] and res[lab]["b"] >= base["b"]) and res[lab]["c2"] > base["c2"] and res[lab]["ep"] > base["ep"] for lab, _ in FORMS[1:]}
    labs = [lab for lab, _ in FORMS[1:]]
    lines += ["", "## 判定", "", "| 形 | (a)〜(c) | (d) となりの形も | 判定 |", "|---|---|---|---|"]
    for j, lab in enumerate(labs):
        kind = lab[0]
        nb = any(ok[labs[q]] for q in (j - 1, j + 1) if 0 <= q < len(labs) and labs[q][0] == kind)
        lines.append(f"| {lab} | {'○' if ok[lab] else '×'} | {'○' if nb else '×'} | {'**合格**' if (ok[lab] and nb) else '不合格'} |")
        print(lines[-1], flush=True)
    open(os.path.join(F.ROOT, "reports", "research", "intraday_confirm.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

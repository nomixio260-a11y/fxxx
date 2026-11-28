#!/usr/bin/env python3
"""研究：戻りの層に、日中の「利益確定の指値」を足すと、急落の損失が減り、利益が増えるか（108章）。日付・時刻は使わない。

- 考え方：98章で、近い逆指値（下げたら売る）は逆効果と分かった。売られすぎの局面では、日中の下げがすぐ戻るからである。
  同じ性質が上げにもあるなら（日中の急な上げも、その日のうちに戻りやすいなら）、「上げたら売る」指値は逆に効くはずである。
  とくに急落の局面は、1日の中の値動きが大きい（大きく戻してから、また下げる）。上げたところで手放せば、そのあとの下げを受けずに済む。
  一方、そのまま上げ続ける日（底打ちの日）は、利益を途中で手放すことになる。どちらが大きいかは、1分足で確かめるしかない。
- 形（結果を見る前に決めた。これ以外は試さない）：
   今の形：売買の時刻（日足の区切りの5分後）に建玉を合わせ、逆指値を「その値段 − 4×σ」に置く（σ：その日の値動きの見積もり）
   TPk：それに加えて、利益確定の指値を「その値段 ＋ k×σ」に置く。届いたらすべて手放し、次の日足の区切りまで持たない（次の区切りでルールが続いていれば、買い直す）。
        k = 0.5・1.0・1.5・2.0・3.0
   同じ1分足の中で逆指値と指値の両方に届いた場合は、逆指値が先とみなす（厳しめ）。
- データ：公開の1分足（S&P500・NASDAQ100 の CFD。2011年9月〜2026年10月）。計算は EA の写し（fx_hedge.py・lot_rounding.py と同じ：重み 1:2:4・HAR 型・VIX の倍率・
  強制ロスカットを避ける上限・スプレッド・スワップ）。ルール1つ分 8.75%。
- 判定（結果を見る前に決めた）。採用するのは、同じ k が次をすべて満たすときだけ：
   (a) シャープが、前半（〜2019年3月）・後半の両方で、今の形より低くない
   (b) 最大の下落を今の形にそろえたときの年率の伸びが、今の形より高い
   (c) 急落の局面（fx_hedge.py と同じ7局面）の損益の合計が、今の形より良い
   (d) となりの k（1つ上か下）も (a)〜(c) を満たす（たまたま1つだけ良い、を避ける）
使い方: python3 tools/research/intraday_tp.py  → reports/research/intraday_tp.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AMS_OANDA", "1")
import fred_data as F  # noqa: E402
import fx_hedge as FH  # noqa: E402
import lot_rounding as LR  # noqa: E402
import sleeves_ea_mimic as M  # noqa: E402

ANN = 252
KS = (0.5, 1.0, 1.5, 2.0, 3.0)
_cache = {}


def load():
    if "D" in _cache:
        return _cache["D"]
    D, ST, SIGD, OK, M1 = {}, {}, {}, {}, {}
    for s in LR.SYMS:
        pair = M.ALL[s][0]
        d = M.prepare(pair)
        r = M.signals(d)
        D[s], ST[s], SIGD[s] = d, r["R2<10"] + r["D7"] + r["IBS"], M.daily_sigma(d)
        OK[s] = d["close"].rolling(215).count() >= 215
        m = M.server_m1(pair)
        M1[s] = (m.index.values, m["h"].values, m["l"].values)
    days = sorted(set(D[LR.SYMS[0]].index) & set(D[LR.SYMS[1]].index))
    uj = F.fetch("DEXJPUS").dropna()
    uj = uj.reindex(uj.index.union(days)).ffill().reindex(days)
    VM = M.vix_mult(sorted(set(D[LR.SYMS[0]].index) | set(D[LR.SYMS[1]].index)))
    _cache["D"] = (D, ST, SIGD, OK, M1, days, uj, VM)
    return _cache["D"]


def first_touch(m1, t_from, day, tp, sl):
    """売買の時刻から、その日の終わりまでの1分足で、指値（tp 以上）と逆指値（sl 以下）のどちらに先に届いたか。戻り値：'tp'・'sl'・None。"""
    t, hi, lo = m1
    a = np.searchsorted(t, np.datetime64(t_from), side="left")
    b = np.searchsorted(t, np.datetime64(day + pd.Timedelta(days=1)), side="left")
    if b <= a:
        return None
    h, l = hi[a:b], lo[a:b]
    it = np.argmax(h >= tp) if tp is not None and (h >= tp).any() else -1
    isl = np.argmax(l <= sl) if (l <= sl).any() else -1
    if isl >= 0 and (it < 0 or isl <= it):
        return "sl"
    if it >= 0:
        return "tp"
    return None


def simulate(unit, k_tp=None, syms=None, start=FH.START, end=FH.END, deposit=1e10):
    D, ST, SIGD, OK, M1, days, uj, VM = load()
    SY = syms or LR.SYMS
    cash, lots = deposit, {s: 0.0 for s in SY}
    last_close = {s: np.nan for s in SY}
    prev_n = {s: -1.0 for s in SY}
    eqs, idx = [], []
    prev_day = None
    n_tp = n_sl = 0
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
            if need > LR.GUARD * eq > 0:
                for s in SY:
                    tgt[s] *= LR.GUARD * eq / need
            changed = any(n[s] != prev_n[s] for s in SY)
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
                        cash -= (tl - cur) * px[s] * fx * (1.0 + LR.SPREAD_BP / 1e4)
                    else:
                        cash += (cur - tl) * px[s] * fx
                    lots[s] = tl
            for s in SY:
                if lots[s] <= 0:
                    continue
                sl = px[s] * (1.0 - LR.SL * sd[s])
                tp = px[s] * (1.0 + k_tp * sd[s]) if k_tp is not None else None
                if k_tp is None:
                    hit = "sl" if D[s]["low_after"].iloc[i[s]] <= sl else None
                else:
                    hit = first_touch(M1[s], D[s]["px_time"].iloc[i[s]], day, tp, sl)
                if hit == "sl":
                    cash += lots[s] * sl * fx
                    lots[s] = 0.0
                    n_sl += 1
                elif hit == "tp":
                    cash += lots[s] * tp * fx
                    lots[s] = 0.0
                    n_tp += 1
        for s in SY:
            last_close[s] = D[s]["close"].iloc[i[s]]
        idx.append(day)
        eqs.append(cash + sum(lots[s] * last_close[s] * fx for s in SY))
        prev_day = day
    return pd.Series(eqs, index=pd.DatetimeIndex(idx)), n_tp, n_sl


def same_dd(eq, dd0):
    r = eq.pct_change().dropna()
    lo, hi = 0.05, 20.0
    for _ in range(50):
        k = (lo + hi) / 2
        e = (1 + r * k).cumprod()
        if (e / e.cummax() - 1).min() < dd0:
            hi = k
        else:
            lo = k
    e = (1 + r * lo).cumprod()
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    return e.iloc[-1] ** (1 / yrs) - 1


def main():
    unit = 8.75
    lines = ["# 研究：戻りの層に、日中の利益確定の指値を足す（`tools/research/intraday_tp.py`）", "",
             f"S&P500・NASDAQ100 の1分足、{FH.START}〜{FH.END}。ルール1つ分 {unit}%。コスト込み。", "",
             "| 形 | 年率 | シャープ | 前半 | 後半 | 最大の下落 | 最悪の日 | 急落の局面の合計 | 下落をそろえた年率 | 指値に届いた回数（年） | 逆指値（年） |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for lab, k in [("今の形（指値なし）", None)] + [(f"TP{k:g}（＋{k:g}×σ）", k) for k in KS]:
        eq, n_tp, n_sl = simulate(unit, k)
        s, a, b = FH.st(eq), FH.st(eq, FH.START, FH.HALF), FH.st(eq, FH.HALF, FH.END)
        if k is None:
            dd0 = s["dd"]
        yrs = (eq.index[-1] - eq.index[0]).days / 365.25
        res[k] = dict(sh=s["sh"], a=a["sh"], b=b["sh"], dd=s["dd"], ep=FH.ep_sum(eq), c2=same_dd(eq, dd0))
        lines.append(f"| {lab} | {s['cagr'] * 100:+.1f}% | {s['sh']:+.2f} | {a['sh']:+.2f} | {b['sh']:+.2f} | {s['dd'] * 100:.1f}% | {s['wd'] * 100:.1f}% | {res[k]['ep'] * 100:+.1f}% | {res[k]['c2'] * 100:+.1f}% | "
                     f"{n_tp / yrs:.0f} | {n_sl / yrs:.1f} |")
        print(lines[-1], flush=True)
    base = res[None]
    okk = {k: (res[k]["a"] >= base["a"] and res[k]["b"] >= base["b"], res[k]["c2"] > base["c2"], res[k]["ep"] > base["ep"]) for k in KS}
    lines += ["", "## 判定", "", "| k | (a) シャープが前半・後半とも低くない | (b) 下落をそろえた年率が高い | (c) 急落の局面の合計が良い | (d) となりの k も満たす | 判定 |", "|---|---|---|---|---|---|"]
    for j, k in enumerate(KS):
        me = all(okk[k])
        nb = any(all(okk[KS[q]]) for q in (j - 1, j + 1) if 0 <= q < len(KS))
        lines.append(f"| {k:g} | {'○' if okk[k][0] else '×'} | {'○' if okk[k][1] else '×'} | {'○' if okk[k][2] else '×'} | {'○' if nb else '×'} | {'**合格**' if (me and nb) else '不合格'} |")
        print(lines[-1], flush=True)
    open(os.path.join(F.ROOT, "reports", "research", "intraday_tp.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

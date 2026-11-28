#!/usr/bin/env python3
"""研究：弱点（高値からの急落）を、通貨の売りで保険をかけて減らす（107章）。日付・時刻は使わない。

- 弱点（106章）：指数が高値から速く下げる局面で、戻りの層は建玉が最大のまま負けが続く。負けだけを消す数式は、戻りの層の中には見つからなかった。
- 新しい考え方：戻りの利益は「株価指数」に固有（95章：株の売られすぎの合図で通貨を売買しても、利益は出なかった）。
  一方、リスク資産の通貨（豪ドル円など）は、株の急落では一緒に下がる。
  それなら、指数を買っているあいだだけ、その通貨を売っておけば、「下げが続く危険」は打ち消し、「戻りの利益」は残る、はず。
- 形（結果を見る前に決めた）：
   指数の戻りの層（EA と同じ形。S&P500・NASDAQ100、ルール1つ分 8.75%）を持っているあいだ、建玉の額（円）の h 倍だけ、豪ドル円（AUDJPY）を売る。
   指数の売買と同じ時刻に、大きさを合わせ直す（差が 25% を超えたとき）。h = 0.5・0.75・1.0。
   コスト：スプレッド（往復 2 pips）、スワップ（豪ドルと円の短期金利の差 ＋ 年1%。売りは支払い）。逆指値は付けない。
- データ：公開の1分足（S&P500・NASDAQ100 の CFD、豪ドル円。2011年9月〜2026年10月）。日足の区切り・売買の時刻は EA と同じ。
  この案を思いつくのに使ったのは 2017年4月以降の日足なので、**2011年9月〜2017年3月は、まだ見ていない期間**（確かめ用）。
- 判定（結果を見る前に決めた）。採用するのは、同じ h が次をすべて満たすときだけ：
   (a) まだ見ていない期間（2011年9月〜2017年3月）：シャープが保険なしより低くなく、最大の下落が浅い
   (b) 全期間：シャープが前半（〜2019年3月）・後半の両方で低くなく、最大の下落が浅く、最悪の日が悪くない
   (c) 急落の局面（2015年8月・2018年2月・2018年9〜12月・2020年2〜3月・2022年・2024年7〜8月・2025年2〜4月）の損益の合計が良い
   (d) 最大の下落が保険なしと同じになるまで建玉を大きくしたとき、年率の伸びが保険なしより高い（＝同じ損失で、利益が増える）
   (e) 通貨を替えても同じ向き：NZD円・カナダドル円・3つの平均のうち2つ以上で、最大の下落と急落の局面が良くなり、全期間のシャープが 0.03 より大きくは下がらない
使い方: python3 tools/research/fx_hedge.py  → reports/research/fx_hedge.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AMS_OANDA", "1")
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import lot_rounding as LR  # noqa: E402
import sleeves_ea_mimic as M  # noqa: E402

ANN = 252
START, END = "2011-09-01", "2026-10-30"
UNSEEN_END = "2017-03-31"
HALF = "2019-04-01"
PIP = 0.01
EP = (("2015年8月", "2015-08-17", "2015-08-25"), ("2018年1〜2月", "2018-01-26", "2018-02-08"), ("2018年9〜12月", "2018-09-20", "2018-12-24"),
      ("2020年2〜3月", "2020-02-19", "2020-03-23"), ("2022年1〜10月", "2022-01-03", "2022-10-12"), ("2024年7〜8月", "2024-07-16", "2024-08-05"),
      ("2025年2〜4月", "2025-02-19", "2025-04-08"))
_fx = {}


def fx_data(pair):
    """通貨の1分足（サーバー時刻）と、日足の終値。"""
    if pair not in _fx:
        m = M.server_m1(pair)
        _fx[pair] = (m.index.values, m["o"].values, m["c"].groupby(m.index.normalize()).last())
    return _fx[pair]


def rate_diff(pair, days):
    """売りのスワップ（年 %。支払い）：相手の通貨の短期金利 − 円の短期金利 ＋ 年1%。"""
    base = pair[:3]
    jpy = IR.short_rate("JPY", days)
    if base == "AUD":
        r = IR.short_rate("AUD", days)
    else:
        code = {"NZD": "NZ", "CAD": "CA"}[base]
        try:
            m = F.fetch(f"IR3TIB01{code}M156N").dropna().shift(1).dropna()
            r = m.reindex(m.index.union(days)).ffill().reindex(days)
        except Exception:
            r = IR.short_rate("AUD" if base == "NZD" else "USD", days)
        r = r.fillna(IR.short_rate("AUD" if base == "NZD" else "USD", days))
    return (r - jpy + 1.0).clip(lower=0.0)


def simulate(unit, hedge=(), h=0.0, start=START, end=END, deposit=1e10):
    """lot_rounding.simulate（切り捨て）と同じ計算に、通貨の売りを足したもの。hedge：売る通貨の組（等分）。戻り値：日ごとの資産。"""
    SYMS = LR.SYMS
    D, ST, SIGD, OK = {}, {}, {}, {}
    for s in SYMS:
        d = M.prepare(M.ALL[s][0])
        r = M.signals(d)
        D[s], ST[s], SIGD[s] = d, r["R2<10"] + r["D7"] + r["IBS"], M.daily_sigma(d)
        OK[s] = d["close"].rolling(215).count() >= 215
    days = sorted(set(D[SYMS[0]].index) & set(D[SYMS[1]].index))
    uj = F.fetch("DEXJPUS").dropna()
    uj = uj.reindex(uj.index.union(days)).ffill().reindex(days)
    VM = M.vix_mult(sorted(set(D[SYMS[0]].index) | set(D[SYMS[1]].index)))
    HX = {p: fx_data(p) for p in hedge}
    RD = {p: rate_diff(p, pd.DatetimeIndex(days)) for p in hedge}
    cash, lots = deposit, {s: 0.0 for s in SYMS}
    last_close = {s: np.nan for s in SYMS}
    prev_n = {s: -1.0 for s in SYMS}
    hN = {p: 0.0 for p in hedge}                 # 売っている通貨の量（相手の通貨の単位）
    hmark = {p: np.nan for p in hedge}           # 損益を数え終えた値段
    eqs, idx = [], []
    prev_day = None
    for day in [x for x in days if pd.Timestamp(start) <= x <= pd.Timestamp(end)]:
        fx = float(uj.loc[day])
        if prev_day is not None:
            mult = 3 if prev_day.dayofweek == 4 else 1
            for s in SYMS:
                if lots[s] > 0:
                    cash -= lots[s] * last_close[s] * fx * LR.SWAP / 100.0 / 360.0 * mult
            for p in hedge:
                if hN[p] > 0 and not np.isnan(hmark[p]):
                    cash -= hN[p] * hmark[p] * float(RD[p].loc[day]) / 100.0 / 360.0 * (day - prev_day).days
        i = {s: D[s].index.get_loc(day) for s in SYMS}
        ok = all(i[s] > 0 and not np.isnan(D[s]["px"].iloc[i[s]]) and OK[s].iloc[i[s] - 1] and not np.isnan(SIGD[s].iloc[i[s] - 1]) for s in SYMS)
        if ok:
            px = {s: D[s]["px"].iloc[i[s]] for s in SYMS}
            t_trade = max(D[s]["px_time"].iloc[i[s]] for s in SYMS)
            # 通貨：売買の時刻の値段で、ここまでの損益を数える
            pa = {}
            for p in hedge:
                tt, oo, _ = HX[p]
                j = min(np.searchsorted(tt, np.datetime64(t_trade), side="left"), len(tt) - 1)
                pa[p] = oo[j]
                if hN[p] > 0:
                    cash -= hN[p] * (pa[p] - hmark[p])
                hmark[p] = pa[p]
            eq = cash + sum(lots[s] * px[s] * fx for s in SYMS)
            n = {s: ST[s].iloc[i[s] - 1] for s in SYMS}
            sd = {s: SIGD[s].iloc[i[s] - 1] for s in SYMS}
            prevd = D[SYMS[0]].index[i[SYMS[0]] - 1]
            vm = VM.loc[prevd]
            tgt = {s: eq * LR.W[int(round(n[s]))] * unit * vm / 100.0 / max(sd[s] * np.sqrt(252), 0.025) for s in SYMS}
            need = sum(tgt[s] * (LR.SL * sd[s] + LR.MRATE) for s in SYMS)
            if need > LR.GUARD * eq > 0:
                for s in SYMS:
                    tgt[s] *= LR.GUARD * eq / need
            changed = any(n[s] != prev_n[s] for s in SYMS)
            for s in SYMS:
                prev_n[s] = n[s]
                cur = lots[s]
                tl = LR.round_floor(tgt[s] / (px[s] * fx), *LR.LOTS[s])
                if tl <= 0:
                    if cur > 0:
                        cash += cur * px[s] * fx
                        lots[s] = 0.0
                elif changed or abs(cur - tl) > LR.BAND * max(cur, tl):
                    if tl > cur:
                        cash -= (tl - cur) * px[s] * fx * (1.0 + LR.SPREAD_BP / 1e4)
                    else:
                        cash += (cur - tl) * px[s] * fx
                    lots[s] = tl
            # 通貨の売り：指数の建玉の額（円）の h 倍を、通貨の数で等分
            notional = sum(lots[s] * px[s] * fx for s in SYMS)
            for p in hedge:
                want = h * notional / len(hedge) / pa[p]
                cur = hN[p]
                if want <= 0:
                    if cur > 0:
                        cash -= cur * PIP * 1.0                       # 買い戻しのコスト（往復 2 pips の半分）
                        hN[p] = 0.0
                elif changed or abs(cur - want) > LR.BAND * max(cur, want):
                    cash -= abs(want - cur) * PIP * 1.0
                    hN[p] = want
            # 指数の逆指値（通貨の売りは、次の売買の時刻まで持ったまま）
            for s in SYMS:
                if lots[s] > 0 and D[s]["low_after"].iloc[i[s]] <= px[s] * (1.0 - LR.SL * sd[s]):
                    cash += lots[s] * px[s] * (1.0 - LR.SL * sd[s]) * fx
                    lots[s] = 0.0
        for s in SYMS:
            last_close[s] = D[s]["close"].iloc[i[s]]
        unreal = 0.0
        for p in hedge:
            if hN[p] > 0:
                cl = HX[p][2]
                c = float(cl.loc[day]) if day in cl.index else hmark[p]
                unreal -= hN[p] * (c - hmark[p])
        idx.append(day)
        eqs.append(cash + sum(lots[s] * last_close[s] * fx for s in SYMS) + unreal)
        prev_day = day
    return pd.Series(eqs, index=pd.DatetimeIndex(idx))


def st(eq, a=None, b=None):
    e = eq if a is None else eq[(eq.index >= a) & (eq.index <= b)]
    r = e.pct_change().dropna()
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    return dict(cagr=(e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1, sh=r.mean() / r.std() * np.sqrt(ANN), dd=(e / e.cummax() - 1).min(), wd=r.min(), vol=r.std() * np.sqrt(ANN))


def ep_sum(eq):
    r = eq.pct_change().dropna()
    return sum(float(r[(r.index > a) & (r.index <= b)].sum()) for _, a, b in EP)


def main():
    lines = ["# 研究：通貨の売りで保険をかける（`tools/research/fx_hedge.py`）", "",
             "S&P500・NASDAQ100 の1分足と、通貨の1分足（同じ時刻でそろえる）。2011年9月〜2026年10月。ルール1つ分 8.75%、コスト込み。", "",
             "## 1 豪ドル円（AUDJPY）を売る", "",
             "| 形 | 年率 | シャープ | 前半 | 後半 | 最大の下落 | 最悪の日 | 急落の局面の合計 | まだ見ていない期間（〜2017年3月）：シャープ・最大の下落 |", "|---|---|---|---|---|---|---|---|---|"]
    base = simulate(8.75)
    R = {"none": base}

    def row(lab, eq):
        s, a, b, u = st(eq), st(eq, START, HALF), st(eq, HALF, END), st(eq, START, UNSEEN_END)
        return (f"| {lab} | {s['cagr'] * 100:+.1f}% | {s['sh']:+.2f} | {a['sh']:+.2f} | {b['sh']:+.2f} | {s['dd'] * 100:.1f}% | {s['wd'] * 100:.1f}% | {ep_sum(eq) * 100:+.1f}% | "
                f"{u['sh']:+.2f}・{u['dd'] * 100:.1f}% |")
    lines.append(row("保険なし（今の形）", base))
    print(lines[-1], flush=True)
    for h in (0.5, 0.75, 1.0):
        R[h] = simulate(8.75, ("AUDJPY",), h)
        lines.append(row(f"AUDJPY を売る h = {h:g}", R[h]))
        print(lines[-1], flush=True)
    # ---------- (d) 同じ最大の下落になるまで大きくする
    lines += ["", "## 2 最大の下落が保険なしと同じになるまで、建玉を大きくした場合", "",
              "| 形 | ルール1つ分 | 年率 | シャープ | 最大の下落 | 最悪の日 |", "|---|---|---|---|---|---|"]
    b0 = st(base)
    lines.append(f"| 保険なし | 8.75% | {b0['cagr'] * 100:+.1f}% | {b0['sh']:+.2f} | {b0['dd'] * 100:.1f}% | {b0['wd'] * 100:.1f}% |")
    eqdd = {}
    for h in (0.5, 0.75, 1.0):
        grid = {}
        for u in (8.75, 10.0, 11.25, 12.5, 13.75, 15.0):
            grid[u] = st(R[h] if u == 8.75 else simulate(u, ("AUDJPY",), h))
            if grid[u]["dd"] <= b0["dd"]:
                break
        us = sorted(grid)
        best = None
        for u1, u2 in zip(us[:-1], us[1:]):
            if grid[u1]["dd"] >= b0["dd"] >= grid[u2]["dd"]:
                w = (b0["dd"] - grid[u1]["dd"]) / (grid[u2]["dd"] - grid[u1]["dd"])
                best = (u1 + w * (u2 - u1), grid[u1]["cagr"] + w * (grid[u2]["cagr"] - grid[u1]["cagr"]))
        if best is None:
            u = us[-1]
            best = (u, grid[u]["cagr"])
        eqdd[h] = best
        for u in us:
            g = grid[u]
            lines.append(f"| h = {h:g} | {u:g}% | {g['cagr'] * 100:+.1f}% | {g['sh']:+.2f} | {g['dd'] * 100:.1f}% | {g['wd'] * 100:.1f}% |")
            print(lines[-1], flush=True)
        lines.append(f"| h = {h:g}：最大の下落を {b0['dd'] * 100:.1f}% にそろえると | {best[0]:.2f}% | **{best[1] * 100:+.1f}%**（保険なしは {b0['cagr'] * 100:+.1f}%） | | | |")
        print(lines[-1], flush=True)
    # ---------- (e) 通貨を替える
    lines += ["", "## 3 通貨を替えた場合（h = 0.75）", "", "| 売る通貨 | 年率 | シャープ | 最大の下落 | 最悪の日 | 急落の局面の合計 |", "|---|---|---|---|---|---|"]
    alt = {}
    for lab, pairs in (("NZD円", ("NZDJPY",)), ("カナダドル円", ("CADJPY",)), ("3つ（豪ドル円・NZD円・カナダドル円）の平均", ("AUDJPY", "NZDJPY", "CADJPY")), ("（参考）ドル円", ("USDJPY",))):
        try:
            e = simulate(8.75, pairs, 0.75)
        except Exception as ex:                                  # データのない通貨
            lines.append(f"| {lab} | 計算できず（{ex}） | | | | |")
            continue
        s = st(e)
        alt[lab] = (s, ep_sum(e))
        lines.append(f"| {lab} | {s['cagr'] * 100:+.1f}% | {s['sh']:+.2f} | {s['dd'] * 100:.1f}% | {s['wd'] * 100:.1f}% | {ep_sum(e) * 100:+.1f}% |")
        print(lines[-1], flush=True)
    # ---------- 判定
    lines += ["", "## 4 判定（事前に決めた基準）", "", "| h | (a) まだ見ていない期間 | (b) 全期間 | (c) 急落の局面 | (d) 同じ下落での年率 | 判定（(e) は下） |", "|---|---|---|---|---|---|"]
    bu, ba, bb = st(base, START, UNSEEN_END), st(base, START, HALF), st(base, HALF, END)
    be = ep_sum(base)
    passed = []
    for h in (0.5, 0.75, 1.0):
        e = R[h]
        u, a, b, s = st(e, START, UNSEEN_END), st(e, START, HALF), st(e, HALF, END), st(e)
        ca = u["sh"] >= bu["sh"] and u["dd"] > bu["dd"]
        cb = a["sh"] >= ba["sh"] and b["sh"] >= bb["sh"] and s["dd"] > b0["dd"] and s["wd"] >= b0["wd"]
        cc = ep_sum(e) > be
        cd = eqdd[h][1] > b0["cagr"]
        ok = ca and cb and cc and cd
        if ok:
            passed.append(h)
        lines.append(f"| {h:g} | {'○' if ca else '×'} | {'○' if cb else '×'} | {'○' if cc else '×'} | {'○' if cd else '×'} | {'(a)〜(d) 合格' if ok else '不合格'} |")
        print(lines[-1], flush=True)
    good = 0
    for lab in ("NZD円", "カナダドル円", "3つ（豪ドル円・NZD円・カナダドル円）の平均"):
        if lab in alt:
            s, ep = alt[lab]
            good += int(s["dd"] > b0["dd"] and ep > be and s["sh"] >= b0["sh"] - 0.03)
    ce = good >= 2
    lines += ["", f"- (e) 通貨を替えても同じ向き（3つのうち2つ以上）：{'○' if ce else '×'}（{good} / 3）",
              f"- 判定：{'**合格**（h = ' + '・'.join(f'{x:g}' for x in passed) + '）' if (passed and ce) else '不合格'}"]
    print("\n".join(lines[-2:]), flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "fx_hedge.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""研究：小さい口座で複利を活かすための、建玉の丸め方（100章）。

- 建玉は「有効証拠金 × 割合」で決めるので、もともと複利で増える。ただし小さい口座では、最小の取引単位・刻みのせいで目標どおりに持てない：
  US500 は 1 lot（約100万円分）から、US100 は 0.1 lot 刻み（約39万円分）。50万円の口座では、目標が刻みの間に落ちて、持てない日・持ちすぎない日が多い。
- 比べる丸め方：
  floor  今の形：銘柄ごとに、目標を切り捨てる（最小の単位に届かなければ持たない）
  joint  まとめて丸める：ルールが出ている銘柄をまとめて、「目標とのずれの分散」が最小になるロットの組み合わせを選ぶ
         （米国の指数どうしは値動きがほぼ同じなので、ある銘柄で持てない分を、ほかの銘柄で持つ）。
         ずれの分散 = (N − N*)ᵀ Σ (N − N*)。N = 建玉の額、N* = 目標の額、Σ = 値動きの分散・共分散（1日の値動きの見積もりと、直近60日の相関）。
         条件：組み合わせ全体の値動きが、目標の値動きの (1 + ε) 倍を超えない（ε = 0.25）。ルールが出ていない銘柄は持たない。
- 計算は sleeves_ea_mimic.py と同じ材料（1分足から作った日足、ルール、HAR 型の見積もり、VIX の倍率、重み 1:2:4、逆指値 4×σ、強制ロスカットを避ける上限）。
  売買は日足の始まりの5分後。スプレッドは値段の 0.007%、スワップは 年4.79%（金曜は3日分）。銘柄は S&P500 と NASDAQ100（OANDA の最小単位・刻み、円換算は USDJPY）。
使い方: python3 tools/research/lot_rounding.py  → reports/research/lot_rounding.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AMS_OANDA", "1")
import fred_data as F  # noqa: E402
import sleeves_ea_mimic as M  # noqa: E402

SYMS = ("US500_HD", "US100_HD")
LOTS = {"US500_HD": (1.0, 0.01), "US100_HD": (0.1, 0.1)}
W = {0: 0.0, 1: 1.0, 2: 2.0, 3: 4.0}
SPREAD_BP, SWAP, SL, GUARD, MRATE, BAND, EPS = 0.7, 4.79, 4.0, 0.9, 0.1, 0.25, 0.25


def round_floor(x, mn, st):
    v = np.floor(x / st + 1e-9) * st
    return 0.0 if v < mn - 1e-9 else v


def joint_round(xs, npl, sig, corr, spec):
    """xs：目標のロット（銘柄ごと）。戻り値：ロット。ずれの分散が最小になるように、1刻みずつ動かして探す。"""
    k = len(xs)
    act = [i for i in range(k) if xs[i] > 0]
    x = np.array([round_floor(xs[i], *spec[i]) if i in act else 0.0 for i in range(k)])
    if not act:
        return x
    S = np.outer(sig, sig) * corr
    Nt = np.array(xs) * npl
    risk_t = np.sqrt(Nt @ S @ Nt)

    def te(xx):
        e = xx * npl - Nt
        return e @ S @ e

    def risk(xx):
        n = xx * npl
        return np.sqrt(n @ S @ n)
    best = te(x)
    for _ in range(400):
        cand = None
        for i in act:
            mn, st = spec[i]
            for dirn in (1, -1):
                y = x.copy()
                if dirn > 0:
                    y[i] = mn if y[i] < mn - 1e-9 else y[i] + st
                else:
                    if y[i] <= 0:
                        continue
                    y[i] = 0.0 if y[i] - st < mn - 1e-9 else y[i] - st
                if dirn > 0 and risk(y) > (1.0 + EPS) * risk_t + 1e-9:
                    continue
                t = te(y)
                if t < best - 1e-9 and (cand is None or t < cand[0]):
                    cand = (t, y)
        if cand is None:
            break
        best, x = cand
    return x


def simulate(method, start, end, deposit, unit, return_eq=False):
    """return_eq=True なら、日ごとの資産の推移（Series）を返す（target300.py で使う）。"""
    D, ST, SIGD, OK = {}, {}, {}, {}
    for s in SYMS:
        d = M.prepare(M.ALL[s][0])
        r = M.signals(d)
        D[s], ST[s], SIGD[s] = d, r["R2<10"] + r["D7"] + r["IBS"], M.daily_sigma(d)
        OK[s] = d["close"].rolling(215).count() >= 215
    import fred_data as FR
    days = sorted(set(D[SYMS[0]].index) & set(D[SYMS[1]].index))
    uj = FR.fetch("DEXJPUS").dropna()
    uj = uj.reindex(uj.index.union(days)).ffill().reindex(days)
    VM = M.vix_mult(sorted(set(D[SYMS[0]].index) | set(D[SYMS[1]].index)))
    R = pd.DataFrame({s: D[s]["close"].pct_change() for s in SYMS}).reindex(days)
    corr_roll = R[SYMS[0]].rolling(60, min_periods=40).corr(R[SYMS[1]])
    cash, lots = deposit, {s: 0.0 for s in SYMS}
    last_close = {s: np.nan for s in SYMS}
    prev_n = {s: -1.0 for s in SYMS}
    eqs, idx, expo, tgt_expo = [], [], [], []
    prev_day = None
    for day in [x for x in days if pd.Timestamp(start) <= x <= pd.Timestamp(end)]:
        fx = float(uj.loc[day])
        if prev_day is not None:
            mult = 3 if prev_day.dayofweek == 4 else 1
            for s in SYMS:
                if lots[s] > 0:
                    cash -= lots[s] * last_close[s] * fx * SWAP / 100.0 / 360.0 * mult
        i = {s: D[s].index.get_loc(day) for s in SYMS}
        ok = all(i[s] > 0 and not np.isnan(D[s]["px"].iloc[i[s]]) and OK[s].iloc[i[s] - 1] and not np.isnan(SIGD[s].iloc[i[s] - 1]) for s in SYMS)
        if ok:
            px = {s: D[s]["px"].iloc[i[s]] for s in SYMS}
            eq = cash + sum(lots[s] * px[s] * fx for s in SYMS)
            n = {s: ST[s].iloc[i[s] - 1] for s in SYMS}
            sd = {s: SIGD[s].iloc[i[s] - 1] for s in SYMS}
            prevd = D[SYMS[0]].index[i[SYMS[0]] - 1]
            vm = VM.loc[prevd]
            tgt = {s: eq * W[int(round(n[s]))] * unit * vm / 100.0 / max(sd[s] * np.sqrt(252), 0.025) for s in SYMS}
            # 強制ロスカットを避ける上限（目標の額に対して。まとめて同じ割合で縮める）
            need = sum(tgt[s] * (SL * sd[s] + MRATE) for s in SYMS)
            if need > GUARD * eq > 0:
                for s in SYMS:
                    tgt[s] *= GUARD * eq / need
            npl = np.array([px[s] * fx for s in SYMS])
            xs = [tgt[s] / npl[k] for k, s in enumerate(SYMS)]
            if method == "floor":
                tl = [round_floor(xs[k], *LOTS[s]) for k, s in enumerate(SYMS)]
            else:
                c = corr_roll.loc[prevd] if (prevd in corr_roll.index and not np.isnan(corr_roll.loc[prevd])) else 0.9
                tl = list(joint_round(xs, npl, np.array([sd[s] for s in SYMS]), np.array([[1.0, c], [c, 1.0]]), [LOTS[s] for s in SYMS]))
            changed = any(n[s] != prev_n[s] for s in SYMS)
            for k, s in enumerate(SYMS):
                prev_n[s] = n[s]
                cur = lots[s]
                if tl[k] <= 0:
                    if cur > 0:
                        cash += cur * px[s] * fx
                        lots[s] = 0.0
                elif changed or abs(cur - tl[k]) > BAND * max(cur, tl[k]):
                    if tl[k] > cur:
                        cash -= (tl[k] - cur) * px[s] * fx * (1.0 + SPREAD_BP / 1e4)
                    else:
                        cash += (cur - tl[k]) * px[s] * fx
                    lots[s] = tl[k]
                # 逆指値
                if lots[s] > 0 and D[s]["low_after"].iloc[i[s]] <= px[s] * (1.0 - SL * sd[s]):
                    cash += lots[s] * px[s] * (1.0 - SL * sd[s]) * fx
                    lots[s] = 0.0
            expo.append(sum(lots[s] * px[s] * fx for s in SYMS) / eq)
            tgt_expo.append(sum(tgt.values()) / eq)
        for s in SYMS:
            last_close[s] = D[s]["close"].iloc[i[s]]
        idx.append(day)
        eqs.append(cash + sum(lots[s] * last_close[s] * fx for s in SYMS))
        prev_day = day
    eq = pd.Series(eqs, index=pd.DatetimeIndex(idx))
    if return_eq:
        return eq
    dr = eq.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    e, t = np.array(expo), np.array(tgt_expo)
    return dict(final=eq.iloc[-1], cagr=(eq.iloc[-1] / deposit) ** (1 / yrs) - 1, sh=dr.mean() / dr.std() * np.sqrt(252), vol=dr.std() * np.sqrt(252),
                dd=(eq / eq.cummax() - 1).min(), worst=dr.min(), held=(e > 0).mean(), want=(t > 0).mean(), ratio=e[t > 0].mean() / t[t > 0].mean(),
                miss=((e == 0) & (t > 0)).sum() / max((t > 0).sum(), 1))


def main():
    lines = ["# 研究：小さい口座での建玉の丸め方（`tools/research/lot_rounding.py`）", "",
             "S&P500 と NASDAQ100、OANDA の最小単位・刻み。重み 1:2:4・VIX の倍率・逆指値 4×σ・強制ロスカットを避ける上限。", ""]
    head = ("| 丸め方 | ルール1つ分 | 最後の資産 | 年率 | シャープ | 口座の値動き（年） | 最大の下落 | 最悪の日 | 持った日の割合（目標がある日のうち、持てなかった日） | 実際の建玉 ÷ 目標 |")
    blocks = (("直近3年（2023年11月〜2026年10月）、元金50万円", "2023-11-01", "2026-10-30", 500000, (5.0, 6.5, 7.5, 8.75, 10.0)),
              ("直近3年、元金300万円", "2023-11-01", "2026-10-30", 3000000, (5.0, 7.5, 8.75)),
              ("直近8年（2018年11月〜2026年10月）、元金50万円", "2018-11-01", "2026-10-30", 500000, (5.0, 6.5, 7.5, 8.75)),
              ("15年（2011年9月〜2026年10月）、元金50万円（昔は指数も円安も低く、最小の単位が今よりずっと小さかった）", "2011-09-01", "2026-10-30", 500000, (5.0, 7.5, 8.75)))
    for title, start, end, dep, units in blocks:
        lines += [f"## {title}", "", head, "|---|" + "---|" * 9]
        for unit in units:
            for method in ("floor", "joint"):
                r = simulate(method, start, end, dep, unit)
                lines.append(f"| {'今の形（切り捨て）' if method == 'floor' else 'まとめて丸める'} | {unit}% | {r['final'] / 1e4:,.0f}万円 | {r['cagr'] * 100:+.1f}% | {r['sh']:+.2f} | {r['vol'] * 100:.1f}% | "
                             f"{r['dd'] * 100:.0f}% | {r['worst'] * 100:.1f}% | {r['held'] * 100:.0f}%（{r['miss'] * 100:.0f}%） | {r['ratio']:.2f} |")
                print(lines[-1], flush=True)
        lines.append("")
    out = os.path.join(F.ROOT, "reports", "research", "lot_rounding.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

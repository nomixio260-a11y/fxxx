#!/usr/bin/env python3
"""使うルールを、過去のデータだけで定期的に選び直す仕組み（ウォークフォワード）の検証。

考え方
- 固定のルールは、その癖が崩れると負け続ける。そこで、時刻の癖の候補（銘柄 × 時計 × 30分ごとの時刻 ×
  保有 30/60/120分 × 日の条件）を、決まった間隔で「直近 L 年」の成績だけから選び直し、次の期間だけ取引する。
- 選ぶときに使うのは、その時点より前のデータだけ（未来の情報は使わない）。
- 1つの候補に頼らないよう、多数（上限 K）を同じ大きさのリスクで持つ。

手順
1. build：銘柄ごとに、すべての候補の「月ごとの値動きの合計・2乗の合計・回数」を作り、data/cache/wf_<銘柄>.npz に保存する。
2. eval ：選び直しの間隔ごとに、直近 L 年の t 値などで候補を選び、次の期間の損益（1取引のリスクを1単位にそろえた値）を出す。

使い方
  python3 tools/research/walkforward.py build USDJPY EURJPY ...
  python3 tools/research/walkforward.py eval [L年=4] [t=3] [K=20] [選び直しの月数=6]
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

HOLDS = [30, 60, 120]
CLOCKS = ["tky", "ldn", "ny"]
M0 = pd.Timestamp("2015-01-01")
NM = 143  # 2015-01 〜 2026-11
EXTRA = 0.5  # 選ぶとき・評価するときに上乗せする不利な約定（pips）
CORE = ["USDJPY", "EURJPY", "GBPJPY", "EURUSD", "AUDJPY", "GBPUSD"]
MORE = ["NZDJPY", "CADJPY", "CHFJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP", "AUDCAD", "AUDNZD", "NZDCAD"]


def month_index(idx):
    return ((idx.year - 2015) * 12 + idx.month - 1).values


def build(pair):
    df = D.bars(pair, "5min")
    pip = D.pip_size(pair)
    idx = df.index
    o = df["o"].values
    ny_h = df["ny_h"].values
    gap = np.r_[np.inf, np.diff(idx.values).astype("timedelta64[m]").astype(float)]
    wk = np.zeros(len(df), bool)
    for i in np.where(gap >= 30 * 60)[0]:
        wk[i:i + 36] = True
    pos = np.arange(len(df))
    rets = {}
    for hold in HOLDS:
        k = hold // 5
        j = pos + k
        ok = j < len(df)
        r = np.full(len(df), np.nan)
        same = (idx.values[j[ok]] - idx.values[pos[ok]]) == np.timedelta64(hold, "m")
        rr = (o[j[ok]] - o[pos[ok]]) / pip
        rr[~same] = np.nan
        r[ok] = rr
        bad = wk.copy()
        for s_ in range(0, k + 1):
            h = np.r_[ny_h[s_:], np.full(s_, -1)]
            bad |= (h >= 16) & (h <= 18)
        r[bad] = np.nan
        rets[hold] = r
    mi = month_index(idx)
    meta, Ssum, Qsum, Ncnt = [], [], [], []
    for clock in CLOCKS:
        hh = df[f"{clock}_h"].values
        mm = df[f"{clock}_m"].values
        slot = np.where((mm == 0) | (mm == 30), hh * 2 + mm // 30, -1)
        filters = S.day_filters(df, clock)
        for fname, fm in filters.items():
            for sl in range(48):
                ii = np.where((slot == sl) & fm)[0]
                for hold in HOLDS:
                    r = rets[hold][ii]
                    ok = ~np.isnan(r)
                    if ok.sum() < 30:
                        continue
                    m = mi[ii][ok]
                    x = r[ok]
                    meta.append((pair, clock, sl, hold, fname))
                    Ssum.append(np.bincount(m, x, NM))
                    Qsum.append(np.bincount(m, x * x, NM))
                    Ncnt.append(np.bincount(m, None, NM))
    np.savez_compressed(os.path.join(D.CACHE, f"wf_{pair}.npz"), meta=np.array(meta, dtype=object),
                        S=np.array(Ssum), Q=np.array(Qsum), N=np.array(Ncnt))
    print(pair, len(meta), "候補", flush=True)


def load(pairs):
    metas, Ss, Qs, Ns, costs = [], [], [], [], []
    for p in pairs:
        z = np.load(os.path.join(D.CACHE, f"wf_{p}.npz"), allow_pickle=True)
        metas += [tuple(m) for m in z["meta"]]
        Ss.append(z["S"]); Qs.append(z["Q"]); Ns.append(z["N"])
        costs.append(np.full(len(z["meta"]), S.COST[p] + EXTRA))
    return metas, np.vstack(Ss), np.vstack(Qs), np.vstack(Ns), np.concatenate(costs)


def window(meta):
    """候補が建玉を持つ時間（その時計での分、0〜1440）。同じ銘柄で時間が重なる候補を同時に選ばないために使う。"""
    # 時計ごとの UTC とのおおよその差（夏時間は半分ずつ見込む）で、UTC の分に直す。時計が違っても同じ時間帯なら重なりとみなす
    _, clock, sl, hold, _ = meta
    off = {"tky": -540, "ldn": -30, "ny": 270}[clock]
    a = (sl * 30 + off) % 1440
    return "utc", a - 30, a + hold + 30


def select(metas, S_, Q_, N_, cost, lo, hi, tmin, K, nmin=40):
    s = S_[:, lo:hi].sum(1); q = Q_[:, lo:hi].sum(1); n = N_[:, lo:hi].sum(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = s / n
        sd = np.sqrt(np.maximum(q / n - mean ** 2, 1e-12))
        sign = np.sign(mean)
        net = np.abs(mean) - cost
        t = net / sd * np.sqrt(n)  # コスト後の t 値
        # 前半・後半の両方でコスト後プラス（一時的な偏りを除く）
        mid = (lo + hi) // 2
        s1 = S_[:, lo:mid].sum(1); n1 = N_[:, lo:mid].sum(1)
        s2 = S_[:, mid:hi].sum(1); n2 = N_[:, mid:hi].sum(1)
        ok = (n >= nmin) & (t >= tmin) & (sign * s1 / n1 - cost > 0) & (sign * s2 / n2 - cost > 0)
    order = np.argsort(-np.where(ok, t, -np.inf))
    chosen, used = [], {}
    for c in order[: 5000]:
        if not ok[c] or len(chosen) >= K:
            break
        pair = metas[c][0]
        clock, a, b = window(metas[c])
        clash = any(cl == clock and not (b <= a2 or b2 <= a) for cl, a2, b2 in used.get(pair, []))
        if clash:
            continue
        used.setdefault(pair, []).append((clock, a, b))
        chosen.append((c, sign[c], sd[c]))
    return chosen


def evaluate(pairs, L=4, tmin=3.0, K=20, step=6, start_year=2019, verbose=True):
    metas, S_, Q_, N_, cost = load(pairs)
    months = pd.period_range("2015-01", periods=NM, freq="M")
    out = np.full(NM, np.nan)
    picks = {}
    first = (start_year - 2015) * 12
    for m0 in range(first, NM, step):
        lo, hi = m0 - 12 * L, m0
        if lo < 0:
            continue
        ch = select(metas, S_, Q_, N_, cost, lo, hi, tmin, K)
        picks[str(months[m0])] = [metas[c] for c, _, _ in ch]
        for m in range(m0, min(m0 + step, NM)):
            tot = 0.0
            for c, sg, sd in ch:
                # 1取引のリスクを1単位（その候補の1取引の値動きのばらつき）にそろえる。全体の大きさは候補の数で割って一定にする
                tot += (sg * S_[c, m] - cost[c] * N_[c, m]) / sd
            out[m] = tot / max(len(ch), 1) if ch else 0.0
    res = pd.Series(out, index=months).dropna()
    return res, picks


def report(res, label):
    yr = res.groupby(res.index.year)
    lines = [f"### {label}", "", "| 年 | 月の合計（単位） | マイナスの月 | 最悪の月 |", "|---|---|---|---|"]
    for y, v in yr:
        lines.append(f"| {y} | {v.sum():+.2f} | {(v < 0).sum()} / {len(v)} | {v.min():+.2f} |")
    lines.append(f"| 全体 | {res.sum():+.2f} | {(res < 0).sum()} / {len(res)} | {res.min():+.2f} |")
    return "\n".join(lines)


if __name__ == "__main__":
    if sys.argv[1] == "build":
        from multiprocessing import Pool
        ps = sys.argv[2:] or CORE + MORE
        ps = [p for p in ps if not os.path.exists(os.path.join(D.CACHE, f"wf_{p}.npz"))]
        with Pool(3) as pool:
            pool.map(build, ps)
    else:
        L, t, K, step = (float(x) for x in (sys.argv[2:6] + ["4", "3", "20", "6"][len(sys.argv[2:6]):]))
        pairs = [p for p in CORE + MORE if os.path.exists(os.path.join(D.CACHE, f"wf_{p}.npz"))]
        res, picks = evaluate(pairs, int(L), t, int(K), int(step))
        print(report(res, f"L={L:.0f}年 t≥{t} K={K:.0f} 選び直し{step:.0f}か月 銘柄{len(pairs)}"))
        last = sorted(picks)[-1]
        print("最新の選択", last, picks[last][:10])

#!/usr/bin/env python3
"""OANDA の MT5 から書き出した足（EA の InpExportBars、30分足）で、1日のすべての時間帯の偏りを探す。

- 手元の histdata にない銘柄（CHF・AUD・NZD のクロス、北欧・新興国の通貨など）を調べるため。
- 足の時刻は OANDA のサーバー時間（ニューヨーク時間 + 7時間）。UTC に直してから、東京・ロンドン・NY の現地時刻を付ける。
- コストは、その銘柄・その時刻の実際のスプレッド（足の spread、ポイント）の中央値に、不利な約定 0.5 pips を足したもの。
- 判定は full_scan.py と同じ：設計（2015〜21年）で t ≥ T かつコスト後プラス → 検証（2022年〜24年10月）で
  コスト後プラス・PF ≥ 1.2・t ≥ 2。最終確認（2024年11月〜）と年ごとは、表に出すだけで選ぶのに使わない。

使い方:
  python3 tools/research/oanda_scan.py <CSV のあるフォルダ> [設計の t=3]  → reports/research/oanda_scan.md
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

HOLDS = [30, 60, 120]
CLOCKS = ["tky", "ldn", "ny"]
BAR = 30
EXTRA = 0.5


def pip_of(sym, price):
    if sym.endswith("JPY"):
        return 0.01
    return 0.0001


def load(path):
    sym = os.path.basename(path)[len("AMS_bars_"):-4]
    cache = os.path.join(D.CACHE, f"oanda_{sym}_M30.parquet")
    if os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(path):
        return sym, pd.read_parquet(cache)
    raw = pd.read_csv(path, encoding="latin-1")
    t = pd.to_datetime(raw["time"], format="%Y.%m.%d %H:%M")
    # サーバー時間 = NY 時間 + 7時間 → NY の現地時刻 → UTC
    ny = (t - pd.Timedelta(hours=7)).dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    ok = ny.notna()
    utc = ny[ok].dt.tz_convert("UTC").dt.tz_localize(None)
    df = pd.DataFrame({"o": raw["open"].values[ok], "spread_pt": raw["spread"].values[ok]}, index=pd.DatetimeIndex(utc))
    df = df[~df.index.duplicated()].sort_index()
    df = D.add_local_time(df)
    df.to_parquet(cache)
    return sym, df


def stats_vec(x):
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 30:
        return n, 0.0, 0.0
    sd = x.std(ddof=1)
    return n, x.mean(), (x.mean() / sd * np.sqrt(n) if sd > 0 else 0.0)


def pf(x):
    x = x[~np.isnan(x)]
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return gp / gl if gl > 0 else 9.99


def scan(sym, df, des_t):
    idx = df.index
    o = df["o"].values
    pip = pip_of(sym, np.nanmedian(o))
    # ポイント → pips（5桁・3桁の銘柄は 10ポイント = 1 pip）
    point = 10 ** -int(round(-np.log10(pip))) / 10
    spread_pips = df["spread_pt"].values * point / pip
    ny_h = df["ny_h"].values
    gap = np.r_[np.inf, np.diff(idx.values).astype("timedelta64[m]").astype(float)]
    wk = np.zeros(len(df), bool)
    for i in np.where(gap >= 30 * 60)[0]:
        wk[i:i + 6] = True
    m_des, m_val, m_fin = (D.period_mask(idx, p) for p in (D.DESIGN, D.VALID, D.FINAL))
    pos = np.arange(len(df))
    rets = {}
    for hold in HOLDS:
        k = hold // BAR
        j = np.minimum(pos + k, len(df) - 1)
        same = (idx.values[j] - idx.values) == np.timedelta64(hold, "m")
        r = (o[j] - o) / pip
        r[~same] = np.nan
        bad = wk.copy()
        for s_ in range(0, k + 1):
            h = np.r_[ny_h[s_:], np.full(s_, -1)]
            bad |= (h >= 16) & (h <= 18)
        r[bad] = np.nan
        rets[hold] = r
    rows, n_tests = [], 0
    for clock in CLOCKS:
        hh = df[f"{clock}_h"].values
        mm = df[f"{clock}_m"].values
        slot = np.where((mm == 0) | (mm == 30), hh * 2 + mm // 30, -1)
        filters = S.day_filters(df, clock)
        for sl in range(48):
            si = np.where(slot == sl)[0]
            if len(si) < 100:
                continue
            cost = float(np.nanmedian(spread_pips[si])) + EXTRA
            for fname, fm in filters.items():
                ii = si[fm[si]]
                des_i, val_i, fin_i = ii[m_des[ii]], ii[m_val[ii]], ii[m_fin[ii]]
                for hold in HOLDS:
                    r = rets[hold]
                    n_tests += 1
                    n, mean, t = stats_vec(r[des_i])
                    if n < 60:
                        continue
                    sign = 1.0 if mean > 0 else -1.0
                    d = sign * r[des_i] - cost
                    dn, dmu, dt = stats_vec(d)
                    if dt < des_t or dmu <= 0:
                        continue
                    v = sign * r[val_i] - cost
                    vn, vmu, vt = stats_vec(v)
                    f = sign * r[fin_i] - cost
                    fn, fmu, ft = stats_vec(f)
                    yr = pd.Series(sign * r[ii] - cost, index=idx[ii].year).dropna().groupby(level=0).mean()
                    rows.append({"pair": sym, "clock": clock, "time": f"{sl // 2:02d}:{(sl % 2) * 30:02d}", "hold": hold,
                                 "filter": fname, "dir": "買い" if sign > 0 else "売り", "cost": cost,
                                 "des_n": dn, "des_net": dmu, "des_t": dt, "des_pf": pf(d),
                                 "val_n": vn, "val_net": vmu, "val_t": vt, "val_pf": pf(v) if vn else 0.0,
                                 "fin_n": fn, "fin_net": fmu, "fin_pf": pf(f) if fn else 0.0,
                                 "years_pos": int((yr > 0).sum()), "years": len(yr), "first": str(idx[0].date())})
    return rows, n_tests


def one(path, des_t):
    sym, df = load(path)
    if len(df) < 1000:
        return [], 0, f"{sym}: 足が少ない（{len(df)} 本）"
    r, n = scan(sym, df, des_t)
    line = f"{sym}: {df.index[0].date()}〜{df.index[-1].date()}、{len(df):,} 本、候補 {len(r)}"
    print(line, flush=True)
    return r, n, line


def main():
    folder = sys.argv[1]
    des_t = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    from multiprocessing import Pool
    paths = sorted(glob.glob(os.path.join(folder, "AMS_bars_*.csv")))
    with Pool(3) as pool:
        parts = pool.starmap(one, [(p, des_t) for p in paths])
    rows, n_tests, info = [], 0, []
    for r, n, line in parts:
        rows += r
        n_tests += n
        info.append(line)
    res = pd.DataFrame(rows)
    out_dir = os.path.join(D.ROOT, "reports", "research")
    res.to_csv(os.path.join(out_dir, "oanda_scan_all.csv"), index=False)
    ok = (res.val_net > 0) & (res.val_pf >= 1.2) & (res.val_t >= 2.0) if len(res) else []
    passed = res[ok].sort_values("des_t", ascending=False) if len(res) else res
    lines = ["# OANDA の履歴（30分足）での全時間帯の探索", "",
             f"- 調べた仮説の数：{n_tests:,} 通り",
             f"- 設計期間でコスト後の t ≥ {des_t:g}：**{len(res)} 通り**",
             f"- そのうち検証期間でも、コスト後プラス・PF 1.2 以上・t ≥ 2：**{len(passed)} 通り**",
             "- コスト：その時刻の実際のスプレッドの中央値 + 0.5 pips。最終確認期間（2024年11月〜）は選ぶのに使っていません。", "",
             "## 銘柄ごとのデータ", ""] + [f"- {x}" for x in info] + ["",
             "## 検証期間も通った仮説", "",
             "| 銘柄 | 時計 | 時刻 | 保有 | 日の条件 | 向き | コスト | 設計 回数 | 設計 pips | 設計 t | 検証 回数 | 検証 pips | 検証 PF | 最終 回数 | 最終 pips | 最終 PF | プラスの年 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in passed.iterrows():
        lines.append(f"| {r.pair} | {r.clock} | {r.time} | {r.hold}分 | {r['filter']} | {r.dir} | {r.cost:.1f} | {r.des_n} | {r.des_net:+.2f} | {r.des_t:.1f} | "
                     f"{r.val_n} | {r.val_net:+.2f} | {r.val_pf:.2f} | {r.fin_n} | {r.fin_net:+.2f} | {r.fin_pf:.2f} | {r.years_pos}/{r.years} |")
    open(os.path.join(out_dir, "oanda_scan.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[:6]))
    print("\n".join(lines[-len(passed) - 2:] if len(passed) else ["なし"]))


if __name__ == "__main__":
    main()

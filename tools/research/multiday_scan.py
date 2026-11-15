#!/usr/bin/env python3
"""数日持つ取引（1〜4営業日）の偏りを、スワップのコスト込みで探す。

今のルールはすべて数時間で決済する。日をまたぐ需給（月の変わり目・曜日）の癖なら、今のルールと関係なく動く可能性がある。

仮説 = 銘柄 × 時計（東京/ロンドン/NY）× 入る時刻（1時間ごと）× 保有日数（1〜4営業日、同じ時刻に決済）× 日の条件
- 週末はまたがない（EA は金曜に全決済するため）。入る日の曜日 + 保有日数 ≤ 金曜。
- コスト = スプレッドの目安（seasonality.COST）＋ スワップ。
  スワップは、各国の政策金利の年平均の差から、業者の上乗せ（年1%、買い・売りのどちらでも払う側に寄せる）を引いて見積もる。
  ニューヨーク17時の日付の変わり目を1回またぐごとに1日分、水曜は3日分。厳しめの見積もり。
- 判定（今までと同じ決まり）：設計（2015〜21年）で t ≥ 3・コスト後プラス → 検証（2022年〜24年10月）で
  コスト後プラス・PF ≥ 1.2・t ≥ 2。最終確認（2024年11月〜）は、ここでは表に出すだけで選ぶのに使わない。

使い方: python3 tools/research/multiday_scan.py  → reports/research/multiday_scan.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

PAIRS = ["USDJPY", "EURJPY", "GBPJPY", "EURUSD", "AUDJPY", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP",
         "NZDJPY", "CADJPY", "CHFJPY"]
if os.environ.get("AMS_PAIRS"):
    PAIRS = [p.strip() for p in os.environ["AMS_PAIRS"].split(",") if p.strip()]
HOURS = {"tky": range(8, 16), "ldn": range(7, 13), "ny": range(8, 14)}
DAYS = [1, 2, 3, 4]
MARKUP = 1.0  # 業者の上乗せ（年 %）
# 政策金利の年平均（%、おおよその値）
RATES = {
    "JPY": {2015: -0.0, 2016: -0.1, 2017: -0.1, 2018: -0.1, 2019: -0.1, 2020: -0.1, 2021: -0.1, 2022: -0.1, 2023: -0.1, 2024: 0.1, 2025: 0.5, 2026: 0.75},
    "USD": {2015: 0.15, 2016: 0.4, 2017: 1.0, 2018: 1.8, 2019: 2.2, 2020: 0.4, 2021: 0.1, 2022: 1.7, 2023: 5.0, 2024: 5.1, 2025: 4.2, 2026: 3.6},
    "EUR": {2015: -0.2, 2016: -0.35, 2017: -0.4, 2018: -0.4, 2019: -0.45, 2020: -0.5, 2021: -0.5, 2022: 0.3, 2023: 3.3, 2024: 3.6, 2025: 2.2, 2026: 2.0},
    "GBP": {2015: 0.5, 2016: 0.4, 2017: 0.3, 2018: 0.6, 2019: 0.75, 2020: 0.2, 2021: 0.1, 2022: 1.5, 2023: 4.7, 2024: 5.0, 2025: 4.2, 2026: 3.8},
    "AUD": {2015: 2.1, 2016: 1.7, 2017: 1.5, 2018: 1.5, 2019: 1.0, 2020: 0.3, 2021: 0.1, 2022: 1.5, 2023: 3.9, 2024: 4.35, 2025: 3.9, 2026: 3.6},
    "NZD": {2015: 3.0, 2016: 2.1, 2017: 1.75, 2018: 1.75, 2019: 1.3, 2020: 0.3, 2021: 0.4, 2022: 2.5, 2023: 5.4, 2024: 5.2, 2025: 3.5, 2026: 2.5},
    "CAD": {2015: 0.6, 2016: 0.5, 2017: 0.7, 2018: 1.5, 2019: 1.75, 2020: 0.5, 2021: 0.25, 2022: 2.0, 2023: 4.8, 2024: 4.5, 2025: 2.8, 2026: 2.25},
    "CHF": {2015: -0.75, 2016: -0.75, 2017: -0.75, 2018: -0.75, 2019: -0.75, 2020: -0.75, 2021: -0.75, 2022: -0.1, 2023: 1.5, 2024: 1.3, 2025: 0.3, 2026: 0.0},
}


def swap_pips(pair, years, price, nights, sign):
    """sign=+1 買い / -1 売り。払う分をプラスの値（pips）で返す（受け取りなら負）。"""
    b, q = pair[:3], pair[3:]
    rb = np.array([RATES[b][y] for y in years])
    rq = np.array([RATES[q][y] for y in years])
    carry = sign * (rb - rq) - MARKUP  # 年 %（受け取りならプラス）
    return -carry / 100.0 / 365.0 * price * nights / D.pip_size(pair)


def daily_table(df, clock, hour):
    """その時計の各日付で、指定の時刻（毎時0分）の足の始値。index = 現地の日付。"""
    m = (df[f"{clock}_h"].values == hour)
    sub = df.loc[m, ["o", f"{clock}_date"]]
    sub = sub[~sub[f"{clock}_date"].duplicated()]
    return pd.Series(sub["o"].values, index=pd.DatetimeIndex(sub[f"{clock}_date"].values), name="o")


def conditions(dates):
    d = pd.DatetimeIndex(dates)
    s = pd.Series(d)
    ym = d.year * 100 + d.month
    k_start = s.groupby(ym).cumcount().values
    k_end = s.groupby(ym).cumcount(ascending=False).values
    f = {"all": np.ones(len(d), bool)}
    for k in range(5):
        f[f"dow{k}"] = d.dayofweek == k
    for k in range(3):
        f[f"me{k}"] = k_end == k   # 月の最後から k 番目の営業日（データのある平日）
    for k in range(2):
        f[f"ms{k}"] = k_start == k
    dom = d.day
    f["mid"] = (dom >= 10) & (dom <= 20)
    return f


def stats(x):
    n = len(x)
    if n < 30:
        return n, 0.0, 0.0, 0.0
    sd = x.std(ddof=1)
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return n, x.mean(), (x.mean() / sd * np.sqrt(n) if sd > 0 else 0.0), (gp / gl if gl > 0 else 9.99)


def scan_pair(pair):
    df = D.bars(pair, "1h")
    cost = S.COST[pair]
    pip = D.pip_size(pair)
    rows, n_tests = [], 0
    for clock, hours in HOURS.items():
        for hour in hours:
            px = daily_table(df, clock, hour)
            px = px[px.index.dayofweek < 5]
            dates = px.index
            f = conditions(dates)
            dow = dates.dayofweek.values
            years = dates.year.values
            for H in DAYS:
                if len(px) <= H:
                    continue
                o = px.values
                ex = np.r_[o[H:], np.full(H, np.nan)]
                exd = np.r_[dates[H:].values, np.full(H, np.datetime64("NaT"), dtype="datetime64[ns]")]
                # 週末をまたがず、ちょうど H 営業日後（間に欠けた日がない）
                ok = (dow + H <= 4) & ((exd - dates.values) == np.timedelta64(H, "D"))
                raw = (ex - o) / pip
                # またぐ日付の変わり目（入る日〜H-1日後）の数。水曜は3日分
                nights = np.zeros(len(o))
                for k in range(H):
                    nights += np.where((dow + k) == 2, 3, 1)
                m_des = D.period_mask(dates, D.DESIGN)
                m_val = D.period_mask(dates, D.VALID)
                m_fin = D.period_mask(dates, D.FINAL)
                for fname, fm in f.items():
                    base = ok & fm & ~np.isnan(raw)
                    n_tests += 1
                    di = base & m_des
                    if di.sum() < 60:
                        continue
                    mean_raw = raw[di].mean()
                    sign = 1.0 if mean_raw > 0 else -1.0
                    net = sign * raw - cost - swap_pips(pair, years, o, nights, sign)
                    n, mu, t, pf = stats(net[di])
                    if t < 3.0 or mu <= 0:
                        continue
                    vn, vmu, vt, vpf = stats(net[base & m_val])
                    fn, fmu, ft, fpf = stats(net[base & m_fin])
                    yr = pd.Series(net[base], index=years[base]).groupby(level=0).mean()
                    rows.append({"pair": pair, "clock": clock, "hour": hour, "days": H, "filter": fname,
                                 "dir": "買い" if sign > 0 else "売り", "des_n": n, "des_net": mu, "des_t": t, "des_pf": pf,
                                 "val_n": vn, "val_net": vmu, "val_t": vt, "val_pf": vpf,
                                 "fin_n": fn, "fin_net": fmu, "fin_pf": fpf,
                                 "years_pos": int((yr > 0).sum()), "years": len(yr),
                                 "swap_avg": float(np.mean(swap_pips(pair, years[base], o[base], nights[base], sign)))})
    print(pair, "done", n_tests, len(rows), file=sys.stderr, flush=True)
    return rows, n_tests


def main():
    from multiprocessing import Pool
    with Pool(3) as pool:
        parts = pool.map(scan_pair, PAIRS)
    res = pd.DataFrame([r for p in parts for r in p[0]])
    n_tests = sum(p[1] for p in parts)
    out_dir = os.path.join(D.ROOT, "reports", "research")
    res.to_csv(os.path.join(out_dir, "multiday_scan_all.csv"), index=False)
    ok = (res.val_net > 0) & (res.val_pf >= 1.2) & (res.val_t >= 2.0) if len(res) else []
    passed = res[ok].sort_values("des_t", ascending=False) if len(res) else res
    lines = ["# 数日持つ取引（1〜4営業日）の偏りの探索（スワップ込み）", "",
             f"- 調べた仮説の数：{n_tests:,} 通り（{len(PAIRS)}ペア × 時計 × 1時間ごとの時刻 × 保有1〜4営業日 × 日の条件）",
             f"- 設計期間でコスト・スワップ後の t ≥ 3：**{len(res)} 通り**",
             f"- そのうち検証期間でも、コスト後プラス・PF 1.2 以上・t ≥ 2：**{len(passed)} 通り**",
             "- スワップは政策金利の年平均の差から、業者の上乗せ年1%を払う側に寄せて見積もりました（厳しめ）。",
             "- 最終確認期間（2024年11月〜）は、選ぶのには使っていません（表に出すだけ）。", "",
             "| 銘柄 | 時計 | 時刻 | 保有 | 日の条件 | 向き | 設計 回数 | 設計 pips | 設計 t | 検証 回数 | 検証 pips | 検証 PF | 最終 回数 | 最終 pips | 最終 PF | プラスの年 | スワップ/回 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in passed.iterrows():
        lines.append(f"| {r.pair} | {r.clock} | {r.hour}:00 | {r.days}日 | {r['filter']} | {r.dir} | {r.des_n} | {r.des_net:+.1f} | {r.des_t:.1f} | "
                     f"{r.val_n} | {r.val_net:+.1f} | {r.val_pf:.2f} | {r.fin_n} | {r.fin_net:+.1f} | {r.fin_pf:.2f} | {r.years_pos}/{r.years} | {r.swap_avg:+.1f} |")
    open(os.path.join(out_dir, "multiday_scan.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

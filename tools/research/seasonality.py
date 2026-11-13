#!/usr/bin/env python3
"""時間帯・需給による値動きの偏り（季節性）を、まとめて調べる。

仮説 = 銘柄 × 時計（東京/ロンドン/NY）× 入る時刻（現地の時）× 保有時間 × 日の条件
- 向きは設計期間の平均から決める（買い/売り）
- 設計期間で |t| >= 3、かつコスト込みでプラスのものだけを残す
- 残ったものを、向きを固定したまま検証期間で確かめる
- 最終確認期間（2024年11月〜）は、ここでは一切見ない

使い方: python3 tools/research/seasonality.py  → reports/research/seasonality.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402

# 1取引あたりのコスト（pips）：OANDA の通常スプレッドの目安 + 不利な約定 0.5 pips
COST = {"USDJPY": 0.8, "EURUSD": 0.8, "EURJPY": 1.0, "GBPJPY": 1.6, "AUDJPY": 1.2, "GBPUSD": 1.4}
HOLDS = [1, 2, 3, 4, 6]
CLOCKS = ["tky", "ldn", "ny"]


def day_filters(df: pd.DataFrame, clock: str) -> dict:
    """日の条件（現地の日付で判定）。値は bool の配列。"""
    date = df[f"{clock}_date"]
    d = pd.DatetimeIndex(date)
    dow = d.dayofweek.values
    dom = d.day.values
    # 月の最終平日・最初の2平日
    days = pd.Series(d.normalize().unique())
    wd = days[days.dt.dayofweek < 5]
    by_month = wd.groupby([wd.dt.year, wd.dt.month])
    last_wd = set(by_month.max())
    first2 = set(pd.concat([g.sort_values().head(2) for _, g in by_month]))
    f = {
        "all": np.ones(len(df), bool),
        "monthend": np.isin(d.normalize(), list(last_wd)),
        "monthstart": np.isin(d.normalize(), list(first2)),
    }
    for k in range(5):
        f[f"dow{k}"] = dow == k
    if clock == "tky":
        f["gotobi"] = gotobi_mask(d)
    return f


def jp_business(day: pd.Timestamp, holidays: set) -> bool:
    return day.dayofweek < 5 and day.strftime("%Y%m%d") not in holidays


def gotobi_mask(d: pd.DatetimeIndex) -> np.ndarray:
    """東京の日付で、ゴトー日（休業日なら前の営業日に前倒し）か。祝日は EA に内蔵した表と同じものを使う。"""
    holidays = load_jp_holidays()
    days = sorted(set(d.normalize()))
    got = set()
    for day in days:
        if not jp_business(day, holidays):
            continue
        def target(x):
            return x.day % 5 == 0 or (x + pd.Timedelta(days=1)).month != x.month
        ok = target(day)
        k = day + pd.Timedelta(days=1)
        n = 0
        while not ok and not jp_business(k, holidays) and n < 10:
            if target(k):
                ok = True
            k += pd.Timedelta(days=1)
            n += 1
        if ok:
            got.add(day)
    return np.isin(d.normalize(), list(got))


def load_jp_holidays() -> set:
    """MQL5/Include/AMS/Modules.mqh の祝日表を読み取る（EA と同じ定義を使うため）。"""
    src = os.path.join(D.ROOT, "MQL5", "Include", "AMS", "Modules.mqh")
    txt = open(src, encoding="utf-8-sig").read()
    start = txt.index("AMS_JP_HOLIDAYS[]")
    body = txt[start: txt.index("};", start)]
    import re
    return set(re.findall(r"\b(20\d{6})\b", body))


def window_returns(df: pd.DataFrame, hold: int, pip: float) -> np.ndarray:
    """各足の始値で入り、hold 本後の足の始値（= hold-1 本後の終値）で出たときの値動き（pips）。
    途中に欠けた足（週末など）がある場合は NaN。"""
    o = df["o"].values
    c = df["c"].values
    idx = df.index.values
    out = np.full(len(df), np.nan)
    if len(df) <= hold:
        return out
    end = np.arange(len(df)) + hold - 1
    valid = end < len(df)
    e = end[valid]
    contiguous = (idx[e] - idx[np.arange(len(df))[valid]]) == np.timedelta64(hold - 1, "h")
    r = (c[e] - o[np.arange(len(df))[valid]]) / pip
    r[~contiguous] = np.nan
    out[valid] = r
    return out


def rollover_mask(df: pd.DataFrame, hold: int) -> np.ndarray:
    """保有する時間帯が、NY 16:00〜18:59（日付の変わり目＝スプレッドが大きく広がる時間）か、
    週明けの最初の3時間にかかる取引を除外するための印（True = 除外）。
    histdata は売値（Bid）だけなので、この時間帯はスプレッド拡大で見かけの値動きが出やすく、実際には取引できない。"""
    ny_h = df["ny_h"].values
    idx = df.index
    bad = np.zeros(len(df), bool)
    for k in range(hold):
        h = (ny_h + k) % 24
        bad |= (h >= 16) & (h <= 18)
    gap = np.r_[np.inf, np.diff(idx.values).astype("timedelta64[h]").astype(float)]
    week_open = gap >= 30
    wo = np.zeros(len(df), bool)
    for k in range(0, 3 + hold):
        wo[k:] |= week_open[: len(df) - k] if k > 0 else week_open
    return bad | wo


def stats(x: np.ndarray, cost: float) -> dict:
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 10:
        return {"n": n, "mean": 0.0, "t": 0.0, "net": 0.0, "pf": 0.0}
    m = x.mean()
    sd = x.std(ddof=1)
    t = m / sd * np.sqrt(n) if sd > 0 else 0.0
    net = x - cost
    gp, gl = net[net > 0].sum(), -net[net < 0].sum()
    return {"n": n, "mean": m, "t": t, "net": net.mean(), "pf": gp / gl if gl > 0 else 9.99}


def scan():
    rows = []
    for pair in D.PAIRS:
        df = D.bars(pair, "1h")
        pip = D.pip_size(pair)
        cost = COST[pair]
        m_des = D.period_mask(df.index, D.DESIGN)
        m_val = D.period_mask(df.index, D.VALID)
        rets = {h: window_returns(df, h, pip) for h in HOLDS}
        excl = {h: rollover_mask(df, h) for h in HOLDS}
        for clock in CLOCKS:
            filters = day_filters(df, clock)
            hour = df[f"{clock}_h"].values
            for fname, fmask in filters.items():
                for h0 in range(24):
                    base0 = fmask & (hour == h0)
                    for hold in HOLDS:
                        base = base0 & ~excl[hold]
                        r = rets[hold]
                        des = stats(r[base & m_des], 0.0)
                        if des["n"] < 60 or abs(des["t"]) < 3.0:
                            continue
                        sign = 1.0 if des["mean"] > 0 else -1.0
                        d2 = stats(sign * r[base & m_des], cost)
                        if d2["net"] <= 0:
                            continue
                        v = stats(sign * r[base & m_val], cost)
                        rows.append({
                            "pair": pair, "clock": clock, "filter": fname, "hour": h0, "hold": hold,
                            "dir": "買い" if sign > 0 else "売り",
                            "des_n": d2["n"], "des_mean": d2["mean"], "des_t": d2["t"], "des_net": d2["net"], "des_pf": d2["pf"],
                            "val_n": v["n"], "val_mean": v["mean"], "val_t": v["t"], "val_net": v["net"], "val_pf": v["pf"],
                        })
        print(pair, "done", file=sys.stderr)
    return pd.DataFrame(rows)


def main():
    res = scan()
    out_dir = os.path.join(D.ROOT, "reports", "research")
    os.makedirs(out_dir, exist_ok=True)
    res.to_csv(os.path.join(out_dir, "seasonality_all.csv"), index=False)
    n_tests = len(D.PAIRS) * len(HOLDS) * 24 * sum(len(day_filters(D.bars(p, "1h").head(3000), c)) for p in D.PAIRS[:1] for c in CLOCKS)
    passed = res[(res["val_net"] > 0) & (res["val_pf"] >= 1.10) & (res["val_t"] >= 1.5)] if len(res) else res
    passed = passed.sort_values("val_t", ascending=False) if len(passed) else passed

    lines = ["# 時間帯・需給の偏りの探索結果", "",
             f"- 調べた仮説の数：約 {n_tests:,} 通り（銘柄 × 時計 × 時刻 × 保有時間 × 日の条件）",
             f"- 設計期間（2015〜2021年）で |t| ≥ 3 かつコスト込みでプラス：**{len(res)} 通り**",
             f"- そのうち、向きを固定したまま検証期間（2022年〜2024年10月）でも、コスト込みでプラス・PF 1.10 以上・t ≥ 1.5：**{len(passed)} 通り**",
             "- コスト（1取引、pips）：" + "、".join(f"{k} {v}" for k, v in COST.items()) + "（通常スプレッドの目安 + 不利な約定 0.5）",
             "- 最終確認期間（2024年11月〜）は見ていません。",
             "- NY 16:00〜18:59（日付の変わり目）と週明けの最初の3時間にかかる取引は除外しています。",
             "  histdata は売値だけなので、この時間帯はスプレッド拡大による見かけの値動きが出やすく、実際には取引できないためです。", "",
             "## 検証期間も通った仮説", ""]
    if len(passed):
        lines += ["| 銘柄 | 時計 | 日の条件 | 入る時刻 | 保有 | 向き | 設計 回数 | 設計 平均pips | 設計 t | 設計 コスト後 | 検証 回数 | 検証 平均pips | 検証 t | 検証 コスト後 | 検証 PF |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in passed.iterrows():
            lines.append(f"| {r.pair} | {r.clock} | {r['filter']} | {r.hour}:00 | {r.hold}h | {r.dir} | {r.des_n} | {r.des_mean:+.1f} | {r.des_t:.1f} | {r.des_net:+.1f} | "
                         f"{r.val_n} | {r.val_mean:+.1f} | {r.val_t:.1f} | {r.val_net:+.1f} | {r.val_pf:.2f} |")
    else:
        lines.append("なし")
    lines += ["", "時計：tky = 東京時間、ldn = ロンドン時間、ny = ニューヨーク時間（いずれも夏時間を考慮）。",
              "日の条件：all = 毎日、gotobi = ゴトー日、monthend = 月の最終平日、monthstart = 月の最初の2平日、dow0〜4 = 月〜金。", ""]
    path = os.path.join(out_dir, "seasonality.md")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()

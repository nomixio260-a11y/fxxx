#!/usr/bin/env python3
"""G3F（ゴトー日 9:55 の USDJPY 売り、仲値前30分に下げた日は見送り）の成績を、ほかの条件で分けて調べる。

条件（どれも 9:55 の時点で分かるもの）：
- 夜間の米ドルの動き：前日の NY 17:00 → 東京 9:25 の値動き ÷ 1時間足の平均値幅
- 仲値前1時間（8:55〜9:55）の値動き
- 曜日（月〜金）
- 月末のゴトー日か（月の最終営業日）
- 値動きの大きさ（1時間足の平均値幅 ÷ その100本平均）
境目は設計期間で決め、検証期間にそのまま当てはめる。

使い方: python3 tools/research/fix_features.py  → reports/research/fix_features.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402


def st(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 15:
        return f"{len(x)}回"
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return f"{len(x)}回 {x.mean():+.2f}pips PF {gp / gl if gl > 0 else 9.99:.2f} t {x.mean() / x.std(ddof=1) * np.sqrt(len(x)):.1f}"


def main(pair="USDJPY"):
    df = D.bars(pair, "5min")
    o = df["o"]
    pip = D.pip_size(pair)
    cost = S.COST[pair]
    fix = df.index[(df["tky_h"].values == 9) & (df["tky_m"].values == 55)]
    fix = fix[S.gotobi_mask(pd.DatetimeIndex(df.loc[fix, "tky_date"]))]
    p = lambda t: o.reindex(t).values  # noqa: E731
    h1 = D.bars(pair, "1h")
    rng = (h1["h"] - h1["l"]).rolling(24).mean().shift(1)
    a = rng.reindex(fix.floor("1h")).values / pip
    vol = (rng / rng.rolling(100).mean()).reindex(fix.floor("1h")).values
    pre30 = (p(fix) - p(fix - pd.Timedelta(minutes=30))) / pip / a
    keep = pre30 > -0.07                                         # G3F の条件
    post = -(p(fix + pd.Timedelta(minutes=125)) - p(fix)) / pip - cost
    # 夜間：東京 9:25 の時点から見て、直前の NY 17:00（＝東京 6:00 または 7:00）
    ny = fix.tz_localize("UTC").tz_convert("America/New_York")
    ny_close = (ny.normalize() - pd.Timedelta(days=0) + pd.Timedelta(hours=17))
    ny_close = ny_close.where(ny_close < ny, ny_close - pd.Timedelta(days=1)).tz_convert("UTC").tz_localize(None)
    overnight = (p(fix - pd.Timedelta(minutes=30)) - o.reindex(ny_close, method="ffill").values) / pip / a
    pre60 = (p(fix) - p(fix - pd.Timedelta(minutes=60))) / pip / a
    dates = pd.DatetimeIndex(df.loc[fix, "tky_date"])
    dow = dates.dayofweek
    nxt = dates + pd.offsets.BDay(1)
    monthend = (nxt.month != dates.month)
    des = D.period_mask(fix, D.DESIGN) & keep
    val = D.period_mask(fix, D.VALID) & keep
    out = [f"# G3F の成績を条件で分ける（{pair}、コスト後）", "", f"- G3F 全体：設計 {st(post[des])} ／ 検証 {st(post[val])}", ""]

    def tert(name, z):
        lo, hi = np.nanquantile(z[des], [1 / 3, 2 / 3])
        out.extend([f"## {name}（境目：{lo:+.2f} / {hi:+.2f}）", "", "| 区分 | 設計 | 検証 |", "|---|---|---|"])
        for lab, m in (("小さい（下1/3）", z <= lo), ("中くらい", (z > lo) & (z <= hi)), ("大きい（上1/3）", z > hi)):
            out.append(f"| {lab} | {st(post[des & m])} | {st(post[val & m])} |")
        out.append("")
    tert("夜間の米ドルの動き（NY 17:00 → 東京 9:25）", overnight)
    tert("仲値前1時間の動き（8:55〜9:55）", pre60)
    tert("値動きの大きさ（平均値幅の比）", vol)
    out += ["## 曜日", "", "| 曜日 | 設計 | 検証 |", "|---|---|---|"]
    for k, n in enumerate("月火水木金"):
        out.append(f"| {n} | {st(post[des & (dow == k)])} | {st(post[val & (dow == k)])} |")
    out += ["", "## 月末のゴトー日か", "", "| 区分 | 設計 | 検証 |", "|---|---|---|",
            f"| 月末 | {st(post[des & monthend])} | {st(post[val & monthend])} |",
            f"| 月末以外 | {st(post[des & ~monthend])} | {st(post[val & ~monthend])} |", ""]
    text = "\n".join(out)
    open(os.path.join(D.ROOT, "reports", "research", "fix_features.md"), "w", encoding="utf-8").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

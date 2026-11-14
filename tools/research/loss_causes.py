#!/usr/bin/env python3
"""負けの原因を調べる：A1・G3F・P2 の取引を、入る時点で分かる相場の状態で分けて、成績の違いを見る。

状態（すべて入る時点までのデータ）：
- 日足のトレンド：前日の終値 ÷ 20日平均 − 1（ATR で割る）
- 直近5日の値動き（ATR で割る）
- 当日のここまでの値動き（その日の始まり NY17:00 → 入る時刻、ATR で割る）
- 直前2時間の値動き
- 値動きの大きさ：1時間足の平均値幅 ÷ その100本平均
- 曜日
各状態は「2024年11月〜」の期間の3分位で分け、同じ境目で設計・検証も表示する（参考）。

使い方: python3 tools/research/loss_causes.py  → reports/research/loss_causes.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

RULES = [("A1", "EURUSD", "ldn", 11, 0, 120, -1, None),
         ("G3F", "USDJPY", "tky", 9, 55, 125, -1, "gotobi"),
         ("P2", "EURJPY", "tky", 9, 25, 30, 1, "gotobi")]


def trade_table(name, pair, clock, hh, mm, hold, d, day):
    df = D.bars(pair, "5min")
    pip, cost = D.pip_size(pair), S.COST[pair]
    t = df.index[(df[f"{clock}_h"].values == hh) & (df[f"{clock}_m"].values == mm)]
    if day == "gotobi":
        t = t[S.gotobi_mask(pd.DatetimeIndex(df.loc[t, "tky_date"]))]
    o = df["o"]
    e = o.reindex(t).values
    r = d * (o.reindex(t + pd.Timedelta(minutes=hold)).values - e) / pip - cost
    h1 = D.bars(pair, "1h")
    atr = ((h1["h"] - h1["l"]).rolling(24).mean().shift(1))
    a = atr.reindex(t.floor("1h")).values
    vol = (atr / atr.rolling(100).mean()).reindex(t.floor("1h")).values
    # 日足（NY 17:00 区切り）
    ny = df.index.tz_localize("UTC").tz_convert("America/New_York")
    day_key = (ny + pd.Timedelta(hours=7)).normalize().tz_localize(None)
    dc = df["c"].groupby(day_key.values).last()
    dopen = df["o"].groupby(day_key.values).first()
    tk = (t.tz_localize("UTC").tz_convert("America/New_York") + pd.Timedelta(hours=7)).normalize().tz_localize(None)
    prev_close = dc.shift(1).reindex(tk).values
    ma20 = dc.rolling(20).mean().shift(1).reindex(tk).values
    c5 = dc.shift(6).reindex(tk).values
    today_open = dopen.reindex(tk).values
    dir_ = d  # 取引の向きに合わせる（＋なら取引の向きに動いていた）
    feat = pd.DataFrame({
        "日足トレンド（20日平均との差）": dir_ * (prev_close - ma20) / a,
        "直近5日の値動き": dir_ * (prev_close - c5) / a,
        "当日のここまでの値動き": dir_ * (e - today_open) / a,
        "直前2時間の値動き": dir_ * (e - o.reindex(t - pd.Timedelta(minutes=120)).values) / a,
        "値動きの大きさ": vol,
        "曜日": pd.DatetimeIndex(df.loc[t, f"{clock}_date"]).dayofweek,
    }, index=t)
    feat["r"] = r
    return feat.dropna()


def st(x):
    x = np.asarray(x)
    if len(x) < 10:
        return f"{len(x)}回"
    gp, gl = x[x > 0].sum(), -x[x < 0].sum()
    return f"{len(x)}回 {x.mean():+.2f} PF {gp / gl if gl > 0 else 9.99:.2f}"


def main():
    out = ["# 負けの原因：相場の状態で分けた成績（コスト後 pips、1回あたり）", "",
           "「＋」は、取引の向きと同じ方向に動いていたことを表します（売りなら下げていた）。", ""]
    P = (("2024/11〜", D.FINAL), ("設計", D.DESIGN), ("検証", D.VALID))
    for rule in RULES:
        f = trade_table(*rule)
        fin = f[D.period_mask(f.index, D.FINAL)]
        out += [f"## {rule[0]}（全体：" + " ／ ".join(f"{n} {st(f.r[D.period_mask(f.index, p)])}" for n, p in P) + "）", ""]
        for col in f.columns[:-1]:
            out += [f"### {col}", "", "| 区分 | " + " | ".join(n for n, _ in P) + " |", "|---|---|---|---|"]
            if col == "曜日":
                groups = [(n, f[col] == k) for k, n in enumerate("月火水木金")]
            else:
                lo, hi = np.quantile(fin[col], [1 / 3, 2 / 3])
                groups = [(f"下1/3（≤{lo:+.2f}）", f[col] <= lo), ("中", (f[col] > lo) & (f[col] <= hi)), (f"上1/3（>{hi:+.2f}）", f[col] > hi)]
            for n, m in groups:
                out.append(f"| {n} | " + " | ".join(st(f.r[m & D.period_mask(f.index, p)]) for _, p in P) + " |")
            out.append("")
    text = "\n".join(out) + "\n"
    open(os.path.join(D.ROOT, "reports", "research", "loss_causes.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""ゴトー日の東京仲値：仲値前の上昇が大きい日ほど、仲値後の下落も大きいか（Krohn ほか 2024 の「ディーラーのヘッジの戻し」の考え方）。

- 仲値前の値動き：東京 8:55〜9:55（ほかに 9:25〜9:55、前日終値〜9:55 も）
- 仲値後の値動き：9:55〜12:00（G3 と同じ）
- 設計期間で、仲値前の値動きの大きさ（ATR で割った値）を3つに分け、仲値後の売りの成績を比べる。
  分け方の境目は設計期間で決め、検証期間にそのまま当てはめる。

使い方: python3 tools/research/fix_reversal.py [銘柄]  → reports/research/fix_reversal_<銘柄>.md
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
    t = x.mean() / x.std(ddof=1) * np.sqrt(len(x))
    return f"{len(x)}回 {x.mean():+.2f}pips PF {gp / gl if gl > 0 else 9.99:.2f} t {t:.1f}"


def main(pair="USDJPY"):
    df = D.bars(pair, "5min")
    o = df["o"]
    pip = D.pip_size(pair)
    cost = S.COST[pair]
    fix = df.index[(df["tky_h"].values == 9) & (df["tky_m"].values == 55)]
    got = S.gotobi_mask(pd.DatetimeIndex(df.loc[fix, "tky_date"]))
    fix = fix[got]
    p = lambda t: o.reindex(t).values  # noqa: E731
    post = -(p(fix + pd.Timedelta(minutes=125)) - p(fix)) / pip - cost          # G3（売り）のコスト後の損益
    h1 = D.bars(pair, "1h")
    atr = (h1["h"] - h1["l"]).rolling(24).mean().shift(1)
    a = atr.reindex(fix.floor("1h")).values / pip
    pres = {"8:55〜9:55": (p(fix) - p(fix - pd.Timedelta(minutes=60))) / pip,
            "9:25〜9:55": (p(fix) - p(fix - pd.Timedelta(minutes=30))) / pip}
    des = D.period_mask(fix, D.DESIGN)
    val = D.period_mask(fix, D.VALID)
    out = [f"# ゴトー日・東京仲値：仲値前の動きと、仲値後の売り（{pair}、コスト後）", "",
           f"- 全体：設計 {st(post[des])} ／ 検証 {st(post[val])}", ""]
    for name, pre in pres.items():
        z = pre / a
        lo, hi = np.nanquantile(z[des], [1 / 3, 2 / 3])
        out += [f"## 仲値前 {name}（ATR で割った値。境目は設計期間で決定：{lo:+.2f} / {hi:+.2f}）", "",
                "| 仲値前の動き | 設計 | 検証 |", "|---|---|---|"]
        for lab, m in (("下げ・小さい（下1/3）", z <= lo), ("中くらい", (z > lo) & (z <= hi)), ("上げが大きい（上1/3）", z > hi)):
            out.append(f"| {lab} | {st(post[des & m])} | {st(post[val & m])} |")
        c = np.corrcoef(np.nan_to_num(z[des]), np.nan_to_num(post[des]))[0, 1]
        out += ["", f"- 設計期間の相関（仲値前の動き と 仲値後の売りの損益）：{c:+.3f}", ""]
    text = "\n".join(out)
    open(os.path.join(D.ROOT, "reports", "research", f"fix_reversal_{pair}.md"), "w", encoding="utf-8").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "USDJPY")

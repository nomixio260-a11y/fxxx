#!/usr/bin/env python3
"""研究：売買できる銘柄どうしの、日々の先行・遅行（108章）。ある銘柄のきのうの値動きが、別の銘柄のきょうの値動きを予告するか。日付・時刻は使わない。

- 銘柄：OANDA の株価指数 14・商品 6（金・銀・銅・原油2つ・天然ガス）の実際の日足（NY 17時区切り。2016年〜）と、為替 10 ペア（公開の1分足から、同じ NY 17時区切りの日足を作る）。
- 総当たり：X のきのうの値動き（その銘柄の直近60日の値動きの大きさで割ったもの）→ Y のきょうの値動き（同じく割ったもの）。X = Y（自分自身）も含む。
  損益は「X のきのうの値動き × Y のきょうの値動き」（X が上げたら Y を買い、下げたら売る。大きく動いた日ほど大きく持つ）。マイナスなら逆向き（X が下げたら Y を買う）。
- 期間：前半（設計）2016年7月〜2021年12月、後半（確認）2022年1月〜。
- 判定（結果を見る前に決めた）：前半で |t| ≥ 3.5、かつ、後半で同じ向きに |t| ≥ 2.0 の組だけを候補にする。約900通り調べるので、効き目がなくても
  たまたま両方を満たす組は 0.01 個ほど。候補が出たら、コスト（スプレッド・スワップ）を入れた実際の持ち方で、別に確かめる。
  すでに使っている「米国の指数の、自分自身の戻り」（US500・US100・US30 どうしのマイナスの関係）は、新しい発見には数えない。
使い方: python3 -I tools/research/lead_lag_screen.py <指数の口座の書き出し> <商品の口座の書き出し>  → reports/research/lead_lag_screen.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_others as IO  # noqa: E402
import index_reversion_cfd as IC  # noqa: E402

FX = ("USDJPY", "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURJPY", "GBPJPY", "AUDJPY")
COMM = ("XAUUSD", "XAGUSD", "COPPER", "USOIL", "UKOIL", "NATGAS")
SPLIT, START = "2022-01-01", "2016-07-01"


def tval(x):
    x = x.dropna()
    return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 100 and x.std() > 0 else np.nan


def main():
    ix, _ = IO.load(sys.argv[1])
    cm, _ = IO.load(sys.argv[2])
    C = {s: d["close"] for s, d in ix.items()}
    C.update({s: cm[s]["close"] for s in COMM})
    for p in FX:
        m = IC.load_any(p)
        d = IC.day_bars(m, 17)
        C[p] = d["close"]
    R = pd.DataFrame({k: v.pct_change() for k, v in C.items()})
    R = R[R.index >= "2016-03-01"]
    Z = R / R.rolling(60, min_periods=40).std().shift(1)        # きのうまでの値動きの大きさで割る
    Z = Z.clip(-5, 5)
    Z = Z[Z.index >= START]
    names = list(Z.columns)
    rows = []
    for x in names:
        lag = Z[x].shift(1)
        for y in names:
            p = lag * Z[y]
            a, b = p[p.index < SPLIT], p[p.index >= SPLIT]
            rows.append(dict(x=x, y=y, t1=tval(a), t2=tval(b), n1=int(a.notna().sum()), n2=int(b.notna().sum())))
    df = pd.DataFrame(rows).dropna()
    df.round(3).to_csv(os.path.join(F.ROOT, "reports", "research", "lead_lag_screen_all.csv"), index=False)
    hit = df[(df["t1"].abs() >= 3.5) & (np.sign(df["t1"]) == np.sign(df["t2"])) & (df["t2"].abs() >= 2.0)].sort_values("t1")
    us = {"US500", "US100", "US30"}
    lines = ["# 研究：銘柄どうしの日々の先行・遅行（`tools/research/lead_lag_screen.py`）", "",
             f"調べた組：{len(df)} 通り（{len(names)} 銘柄 × {len(names)} 銘柄）。前半 {START}〜{SPLIT}、後半 {SPLIT}〜。", "",
             f"- 前半の t 値の分布：最小 {df['t1'].min():+.1f}、中央 {df['t1'].median():+.1f}、最大 {df['t1'].max():+.1f}。|t| ≥ 3.5 は {int((df['t1'].abs() >= 3.5).sum())} 通り（たまたまなら {len(df) * 0.00047:.1f} 通り）。",
             f"- 前半で |t| ≥ 3.5、かつ、後半で同じ向きに |t| ≥ 2.0：**{len(hit)} 通り**（うち、すでに使っている米国の指数どうしの関係 {int((hit['x'].isin(us) & hit['y'].isin(us)).sum())} 通り）", "",
             "| きのうの値動き（X） | きょう売買する銘柄（Y） | 前半の t | 後半の t | 向き |", "|---|---|---|---|---|"]
    for _, r in hit.iterrows():
        lines.append(f"| {r.x} | {r.y} | {r.t1:+.1f} | {r.t2:+.1f} | {'X が上げたら Y を買う' if r.t1 > 0 else 'X が下げたら Y を買う'}{'（すでに使っている関係）' if (r.x in us and r.y in us) else ''} |")
    # 参考：自分自身（対角）
    diag = df[df["x"] == df["y"]].sort_values("t1")
    lines += ["", "## 参考：自分自身のきのうの値動き → きょう（マイナスは「戻り」、プラスは「続き」）", "", "| 銘柄 | 前半の t | 後半の t |", "|---|---|---|"]
    for _, r in diag.iterrows():
        lines.append(f"| {r.x} | {r.t1:+.1f} | {r.t2:+.1f} |")
    open(os.path.join(F.ROOT, "reports", "research", "lead_lag_screen.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[:9 + len(hit)]))
    print("\n".join(lines[-len(diag) - 3:]))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""研究：14の株価指数どうしの関係に、新しい利益の出どころはあるか（102章）。日付・時刻は使わない。

- データ：OANDA の株価指数の口座の、実際の CFD の日足（14銘柄、2016年〜。index_others.py と同じ。リポジトリには入れていない）。
- 事前に決めた9通り（結果を見る前に決めた。これ以外は試さない）：
  1 残差の戻り（市場の向きに左右されない形）：各指数の値動きから、US500 に連動する分（過去120日の回帰）を引いた残り（残差）が、
    直近 k 日（k = 1・3・5）で大きく下げた指数を買い、上げた指数を売る。US500 で、連動する分を打ち消す。
  2 指数どうしの順張り（クロスセクションのモメンタム）：過去 L 日（L = 60・120・250。直近5日は除く）で上がった上位4指数を買い、下位4指数を売る。5本ごとに組み直す。
  3 指数どうしの戻り：直近 k 日（k = 1・3・5）で下げた下位4指数を買い、上げた上位4指数を売る。毎日組み直す。
- 売買は次の日足の始値（始値から次の始値までの値動きで損益を計算）。建玉は、各指数の値動き（過去60日）が同じになる大きさ。
- コスト：スプレッド（売買のたび。往復で1回分）と、スワップ（買い・売りそれぞれの年率。OANDA では買いも売りも支払い）。
- 判定：前半（設計。〜2021年12月）で t 値が 3.0 以上（9通り試すため、基準を高くする）、かつ、後半（確認。2022年1月〜）でシャープ +0.5 以上。両方を満たすものだけを候補にする。
使い方: python3 -I tools/research/index_relval14.py <書き出したファイルのフォルダ>  → reports/research/index_relval14.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_others as IO  # noqa: E402

ANN = 252
SPLIT = "2022-01-01"


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 60 and x.std() > 0 else np.nan


def tval(x):
    return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 60 and x.std() > 0 else np.nan


def pnl(W, O, spread, swl, sws, days):
    """W：日 × 銘柄 の建玉（その日の終値で決め、次の日の始値で持つ。口座に対する割合）。戻り値：コスト前・コスト後の日次の損益。"""
    Wh = W.shift(1).fillna(0.0)                              # その日の始値から持っている建玉
    ret = (O.shift(-1) / O - 1.0).fillna(0.0)                # 始値 → 次の始値
    gross = (Wh * ret).sum(axis=1)
    turn = (Wh - Wh.shift(1).fillna(0.0)).abs()
    cost = (turn * (spread / 2.0)).sum(axis=1)
    carry = ((Wh.clip(lower=0) * swl + (-Wh.clip(upper=0)) * sws) / 100.0 / 360.0).sum(axis=1) * days
    return gross, gross - cost - carry


def main():
    folder = sys.argv[1]
    data, props = IO.load(folder)
    syms = list(data)
    idx = sorted(set().union(*[d.index for d in data.values()]))
    idx = pd.DatetimeIndex([t for t in idx if t >= pd.Timestamp("2016-06-10")])
    C = pd.DataFrame({s: data[s]["close"].reindex(idx).ffill() for s in syms})
    O = pd.DataFrame({s: data[s]["open"].reindex(idx) for s in syms}).fillna(C.shift(1))
    days = pd.Series(idx, index=idx).diff().dt.days.fillna(1.0)
    spread = pd.Series({s: float(props.loc[s, "spread_points"]) * float(props.loc[s, "point"]) / float(props.loc[s, "bid"]) for s in syms})
    swl = pd.Series({s: -float(props.loc[s, "swap_long"]) for s in syms})          # 年 %（支払いをプラスの数に）
    sws = pd.Series({s: -float(props.loc[s, "swap_short"]) for s in syms})
    R = np.log(C).diff()
    vol = R.rolling(60, min_periods=40).std()
    unit = (0.01 / vol).clip(upper=3.0)                       # 1銘柄の1日の値動きが、口座の 1% になる大きさ
    start = idx[0] + pd.Timedelta(days=400)
    out_rows = []

    def record(label, W):
        g, n = pnl(W, O, spread, swl, sws, days)
        g, n = g[g.index >= start], n[n.index >= start]
        a, b = n[n.index < SPLIT], n[n.index >= SPLIT]
        ok = (tval(a) >= 3.0) and (sh(b) >= 0.5)
        out_rows.append(f"| {label} | {sh(g):+.2f} | {sh(n):+.2f} | {tval(a):+.1f}（シャープ {sh(a):+.2f}） | {sh(b):+.2f}（t {tval(b):+.1f}） | {'**候補**' if ok else '不合格'} |")
        print(out_rows[-1], flush=True)

    # 1 残差の戻り
    others = [s for s in syms if s != "US500"]
    m = R["US500"]
    beta = pd.DataFrame({s: (R[s].rolling(120, min_periods=80).cov(m) / m.rolling(120, min_periods=80).var()).shift(1) for s in others})
    E = pd.DataFrame({s: R[s] - beta[s] * m for s in others})
    evol = E.rolling(60, min_periods=40).std().shift(1)
    for k in (1, 3, 5):
        z = (-(E.rolling(k).sum()) / (evol * np.sqrt(k))).clip(-2, 2)
        w_i = (z * (0.01 / evol).clip(upper=3.0) / len(others)).fillna(0.0)
        W = w_i.copy()
        W["US500"] = -(w_i * beta).sum(axis=1)
        record(f"残差の戻り：直近 {k} 日", W[syms])
    # 2 指数どうしの順張り
    for L in (60, 120, 250):
        mom = (np.log(C.shift(5)) - np.log(C.shift(L))) / (vol * np.sqrt(L))
        rk = mom.rank(axis=1)
        sel = ((rk > len(syms) - 4).astype(float) - (rk <= 4).astype(float)) * unit / 8.0
        hold = sel.copy()
        keep = np.arange(len(idx)) % 5 != 0                     # 5本ごとに組み直す（そのあいだは、そのまま持つ）
        hold[keep] = np.nan
        hold = hold.ffill().fillna(0.0)
        record(f"指数どうしの順張り：過去 {L} 日", hold)
    # 3 指数どうしの戻り
    for k in (1, 3, 5):
        rev = -(R.rolling(k).sum()) / (vol * np.sqrt(k))
        rk = rev.rank(axis=1)
        sel = ((rk > len(syms) - 4).astype(float) - (rk <= 4).astype(float)) * unit / 8.0
        record(f"指数どうしの戻り：直近 {k} 日", sel.fillna(0.0))

    lines = ["# 研究：14の株価指数どうしの関係（`tools/research/index_relval14.py`）", "",
             f"OANDA の実際の CFD の日足。{start.date()}〜{idx[-1].date()}。前半（設計）は {SPLIT} より前、後半（確認）はそれ以降。", "",
             "| 形 | 全期間のシャープ（コスト前） | コスト後 | 前半：t 値 | 後半：シャープ | 判定（前半 t ≥ 3.0 かつ 後半シャープ ≥ +0.5） |", "|---|---|---|---|---|---|"] + out_rows
    lines += ["", "- コスト：スプレッドは " + "、".join(f"{s} {spread[s] * 100:.3f}%" for s in syms) + "。",
              "- スワップ（年）は、買い " + "、".join(f"{s} {swl[s]:.2f}%" for s in syms) + "／売り " + "、".join(f"{s} {sws[s]:.2f}%" for s in syms) + "。"]
    out = os.path.join(F.ROOT, "reports", "research", "index_relval14.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

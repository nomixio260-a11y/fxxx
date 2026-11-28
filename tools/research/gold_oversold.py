#!/usr/bin/env python3
"""研究：金の「売られすぎの戻り」（日足の RSI(14) が 30 未満になったら買い、12日持つ）は、本物か（108章）。日付・時刻は使わない。

- きっかけ：金・原油の一斉検証（commodity_zoo.py、1,296 通り）で、基準（設計 2011〜18年 t ≥ 3、選ぶ 2019〜22年 t ≥ 2）を通ったのは、
  金の日足の「RSI14 が 30 未満で買い・12本持つ」の1通りだけだった。答え合わせ（2023年〜）も t +4.3。近い形（20日の安値の更新の逆・2σ の行き過ぎの戻りなど）も、
  3つの期間すべてでプラスだった。
- ただし、一斉検証の t 値は、重なった取引（毎日のシグナルを別々の12日の取引として数える）から計算しているので、強く出すぎている。
  ここでは、実際に持つ形（重ねて持たない。1つの建玉）の、日々の損益で測り直す。使っていない期間・別のデータでも確かめる。
- 形（一斉検証のまま。数値は変えない）：
   G1 終値で RSI(14)（上げ幅と下げ幅の単純平均の形）が 30 未満なら、次の日の始値で買う。最後にその条件を満たした日から12日たったら、始値で売る。
      建玉は、金の値動き（直近60日）が口座の年10%になる大きさ（ほかの層と同じ決め方）。逆指値なし。
- データ：
   OANDA の金の日足（商品の口座。2006年3月〜2026年11月。コスト：スプレッド 0.39ドル・買いのスワップ 年 −3.62%＝口座の今の値）
   金の先物の日足（Yahoo Finance の GC=F、2000年8月〜。2000〜06年を「どちらの検証にも使っていない期間」として使う。コストは同じ値を使う）
- 期間：P0 2000年9月〜06年2月（先物）／P1 2006年3月〜10年／P2 2011〜18年（一斉検証の設計）／P3 2019〜22年（選ぶ）／P4 2023年〜（答え合わせ）
- 判定（結果を見る前に決めた）。次の検証（EA への実装と MT5）に進めるのは、すべて満たすときだけ：
   (a) 一斉検証で使っていない P0・P1 の両方で、層のシャープがプラスで、かつ「いつも金を持っている形」に対する上乗せ（α）もプラス
   (b) OANDA の全期間（2006〜26年）で、日々の損益の t 値が 3.0 以上、α の t 値が 2.5 以上（コスト後）
   (c) 5つの期間のうち4つ以上でプラス
   (d) 金の順張りの層・指数の戻りの層との、日々の損益の相関が、どちらも ±0.3 以内
   (e) 持つ日数を 8日・16日に変えても、OANDA の全期間の t 値が 2.0 以上（近い形でも成り立つ）
- 参考（判定には使わない）：同じ形を、銀・銅（OANDA の日足）に当てはめた場合。売り側（RSI14 が 70 超で売り）。
使い方: python3 -I tools/research/gold_oversold.py <商品の口座の書き出しのフォルダ>  → reports/research/gold_oversold.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_others as IO  # noqa: E402
import pattern_zoo as PZ  # noqa: E402
import target300 as T  # noqa: E402
import trend_signal as TS  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
PER = (("P1 2006〜10年", "2006-03-01", "2011-01-01"), ("P2 2011〜18年（設計）", "2011-01-01", "2019-01-01"), ("P3 2019〜22年（選ぶ）", "2019-01-01", "2023-01-01"),
       ("P4 2023年〜（答え合わせ）", "2023-01-01", "2027-01-01"))


def state_of(d, hold=12, side=1):
    r = PZ.rsi(d["close"], 14)
    sig = (r < 30) if side > 0 else (r > 70)
    return (sig.astype(float).rolling(hold, min_periods=1).max() * side).where(r.notna())


def run(d, costs, hold=12, side=1):
    r, held, trades = TS.simulate(d, state_of(d, hold, side), **costs)
    return r.iloc[80:-1], held.iloc[80:-1], trades


def tstat(x):
    x = x.dropna()
    return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 30 and x.std() > 0 else np.nan


def sharpe(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 30 and x.std() > 0 else np.nan


def alpha(r, base):
    """層の日々の損益を、「いつも持っている形」の損益で説明したときの切片（年率）と、その t 値。"""
    z = pd.concat([r, base], axis=1).dropna()
    y, x = z.iloc[:, 0].values, z.iloc[:, 1].values
    X = np.column_stack([np.ones(len(x)), x])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ b
    se = np.sqrt(res.var(ddof=2) * np.linalg.inv(X.T @ X)[0, 0])
    return b[0] * ANN, b[0] / se, b[1]


def row(lab, r, base, held):
    a, ta, beta = alpha(r, base)
    e = (1 + r).cumprod()
    return (f"| {lab} | {sharpe(r):+.2f} | {tstat(r):+.1f} | {r.mean() * ANN * 100:+.1f}% | {(e / e.cummax() - 1).min() * 100:.0f}% | {(held != 0).mean() * 100:.0f}% | "
            f"{a * 100:+.1f}%（t {ta:+.1f}） | {sharpe(base):+.2f} |")


def main():
    folder = sys.argv[1]
    data, props = IO.load(folder)
    costs = dict(spread=0.39 / float(props.loc["XAUUSD", "bid"]), swap_long=float(props.loc["XAUUSD", "swap_long"]), swap_short=float(props.loc["XAUUSD", "swap_short"]))
    g = data["XAUUSD"]
    r, held, trades = run(g, costs)
    always, _, _ = TS.simulate(g, pd.Series(1.0, index=g.index), **costs)
    always = always.reindex(r.index)
    head = ["| 期間 | シャープ | 日々の損益の t 値 | 年率（建玉 年10%） | 最大の下落 | 持っている日の割合 | いつも持つ形に対する上乗せ（年率・t 値） | （参考）いつも持つ形のシャープ |", "|---|---|---|---|---|---|---|---|"]
    lines = ["# 研究：金の売られすぎの戻り（`tools/research/gold_oversold.py`）", "",
             "G1：終値で RSI(14) が 30 未満なら次の日の始値で買い、最後にその条件を満たした日から12日で売る。建玉は金の値動きが口座の年10%になる大きさ。コスト（スプレッド・スワップ）込み。", "",
             "## 1 OANDA の金の日足", ""] + head
    res = {}
    lines.append(row(f"全期間（{r.index[0].date()}〜{r.index[-1].date()}）", r, always, held))
    res["all"] = (sharpe(r), tstat(r), alpha(r, always))
    print(lines[-1], flush=True)
    for lab, a, b in PER:
        m = (r.index >= a) & (r.index < b)
        lines.append(row(lab, r[m], always[m], held[m]))
        res[lab] = (sharpe(r[m]), tstat(r[m]), alpha(r[m], always[m]))
        print(lines[-1], flush=True)
    # ---------- 先物（2000年〜）
    f = Y.fetch_ticker("GOLDF", "GC=F")[["open", "high", "low", "close"]].dropna()
    f = f[(f["close"] > 0) & (f["open"] > 0)]
    rf, hf, _ = run(f, costs)
    af, _, _ = TS.simulate(f, pd.Series(1.0, index=f.index), **costs)
    af = af.reindex(rf.index)
    lines += ["", "## 2 金の先物の日足（Yahoo Finance の GC=F）", ""] + head
    m = rf.index < "2006-03-01"
    lines.append(row(f"P0 {rf.index[0].date()}〜2006年2月（どの検証にも使っていない）", rf[m], af[m], hf[m]))
    res["P0"] = (sharpe(rf[m]), tstat(rf[m]), alpha(rf[m], af[m]))
    print(lines[-1], flush=True)
    lines.append(row(f"（参考）全期間 {rf.index[0].date()}〜{rf.index[-1].date()}", rf, af, hf))
    print(lines[-1], flush=True)
    both = pd.concat([r, rf], axis=1).dropna()
    lines += ["", f"- 重なる期間（2006年〜）の、OANDA の日足での損益と先物の日足での損益の相関：{both.corr().iloc[0, 1]:+.2f}"]
    # ---------- 持つ日数・売り側・ほかの金属
    lines += ["", "## 3 近い形（OANDA の日足、全期間）", "", "| 形 | シャープ | t 値 | 年率 | 最大の下落 | 持っている日の割合 |", "|---|---|---|---|---|---|"]
    near = {}
    for hold in (4, 8, 12, 16, 24):
        x, h, _ = run(g, costs, hold)
        near[hold] = tstat(x)
        e = (1 + x).cumprod()
        lines.append(f"| 金・買い・{hold}日持つ{'（G1）' if hold == 12 else ''} | {sharpe(x):+.2f} | {tstat(x):+.1f} | {x.mean() * ANN * 100:+.1f}% | {(e / e.cummax() - 1).min() * 100:.0f}% | {(h != 0).mean() * 100:.0f}% |")
        print(lines[-1], flush=True)
    x, h, _ = run(g, costs, 12, -1)
    lines.append(f"| （参考）金・売り側（RSI14 が 70 超で売り・12日） | {sharpe(x):+.2f} | {tstat(x):+.1f} | {x.mean() * ANN * 100:+.1f}% | — | {(h != 0).mean() * 100:.0f}% |")
    for sym, lab in (("XAGUSD", "銀"), ("COPPER", "銅")):
        d = data[sym]
        c2 = dict(spread=float(props.loc[sym, "spread_points"]) * float(props.loc[sym, "point"]) / float(props.loc[sym, "bid"]),
                  swap_long=float(props.loc[sym, "swap_long"]), swap_short=float(props.loc[sym, "swap_short"]))
        x, h, _ = run(d, c2)
        lines.append(f"| （参考）{lab}・買い・12日 | {sharpe(x):+.2f} | {tstat(x):+.1f} | {x.mean() * ANN * 100:+.1f}% | — | {(h != 0).mean() * 100:.0f}% |")
        print(lines[-1], flush=True)
    # ---------- ほかの層との相関
    trend, _, _ = TS.simulate(g, TS.reviewed(TS.raw_signal(g["close"], "T0")), **costs)
    rev = T.cash_returns(5.0)
    z = pd.concat([r, trend.reindex(r.index), rev], axis=1, sort=True).dropna()
    z.columns = ["g1", "trend", "rev"]
    c_tr, c_rev = z.corr().loc["g1", "trend"], z.corr().loc["g1", "rev"]
    on = z[z["g1"] != 0]
    lines += ["", "## 4 ほかの層との関係（日々の損益の相関）", "",
              f"- 金の順張りの層と：{c_tr:+.2f}（G1 が持っている日だけで見ると {on.corr().loc['g1', 'trend']:+.2f}）",
              f"- 指数の戻りの層と：{c_rev:+.2f}（同 {on.corr().loc['g1', 'rev']:+.2f}）",
              f"- G1 が持っている日のうち、金の順張りの層も持っている日の割合：{(on['trend'] != 0).mean() * 100:.0f}%"]
    # ---------- 判定
    a_ok = all(res[k][0] > 0 and res[k][2][0] > 0 for k in ("P0", PER[0][0]))
    b_ok = res["all"][1] >= 3.0 and res["all"][2][1] >= 2.5
    n_pos = sum(res[k][0] > 0 for k in ["P0"] + [p[0] for p in PER])
    c_ok = n_pos >= 4
    d_ok = abs(c_tr) <= 0.3 and abs(c_rev) <= 0.3
    e_ok = near[8] >= 2.0 and near[16] >= 2.0
    lines += ["", "## 5 判定（事前に決めた基準）", "",
              f"- (a) 使っていない期間（P0・P1）の両方で、シャープも上乗せもプラス：{'○' if a_ok else '×'}（P0 シャープ {res['P0'][0]:+.2f}・上乗せ {res['P0'][2][0] * 100:+.1f}%、P1 シャープ {res[PER[0][0]][0]:+.2f}・上乗せ {res[PER[0][0]][2][0] * 100:+.1f}%）",
              f"- (b) OANDA の全期間で t 値 3.0 以上・上乗せの t 値 2.5 以上：{'○' if b_ok else '×'}（t {res['all'][1]:+.1f}、上乗せの t {res['all'][2][1]:+.1f}）",
              f"- (c) 5つの期間のうち4つ以上でプラス：{'○' if c_ok else '×'}（{n_pos} / 5）",
              f"- (d) ほかの層との相関が ±0.3 以内：{'○' if d_ok else '×'}（順張り {c_tr:+.2f}、指数の戻り {c_rev:+.2f}）",
              f"- (e) 8日・16日でも t 値 2.0 以上：{'○' if e_ok else '×'}（8日 {near[8]:+.1f}、16日 {near[16]:+.1f}）",
              f"- 判定：{'**次の検証に進める**' if (a_ok and b_ok and c_ok and d_ok and e_ok) else '不合格'}"]
    print("\n".join(lines[-6:]), flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "gold_oversold.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

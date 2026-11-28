#!/usr/bin/env python3
"""研究：順張りの層は、資産の下落に応じて建玉を絞ると良くなるか（106章）。日付・時刻は使わない。

- 100章で、戻りの層については「下落で縮める形（Grossman・Zhou 1993）は、同じ下落の深さなら今の形より伸びが小さい」と分かった。
  理由は、戻りの層の損益が「負けた直後に取り返しやすい」（損益の自己相関がマイナス）ため。
- 順張りの層は、性質が逆のはず：流れが出ない時期には小さな負けが長く続き（金は 2012〜18年に7年続けてマイナス）、流れが出ると勝ちが続く。
  損益の自己相関がプラスなら、「負けているあいだは小さく、勝っているあいだは大きく」持つ形が、同じ下落の深さで伸びを大きくする。
  Grossman・Zhou の形は、最高値からの下落を D 以内に抑えるという条件の下で、長期の伸び率を最大にする（値動きが独立なら数学的に最適。
  負けが続きやすいなら、さらに有利）。下落の上限が、数式で決まる。
- 形（100章と同じ。結果を見る前に決めた。これ以外は試さない）：
   const  今の形：一定の割合 L
   GZ     建玉 = L ×（1 − 今の下落 ÷ D）。最高値は、これまでの全期間。D = 30%・40%・50%
   REDD   同じ式で、最高値を直近250日で数える（下落が続いても、1年たてば元の大きさに戻る）。D = 30%・40%
- データ（順張りの層の日々の損益。値動きを年10%にそろえ、倍率 L をかけて資産の道筋を作る。L は前の日までの資産だけで決める）：
   金：MT5 のテスターが書き出した日ごとの資産（OANDA の実際の値段、2007〜2026年、建玉 11.2%・逆指値なし。reports/runs/0875_equity.csv）
   確かめ用の5つ：銀・銅（OANDA の日足）、SPY・QQQ・DIA（ETF）の順張りの層（trend_signal.py と同じ計算）
- 物差し：同じ「最大の下落」になる L どうしで、年率の伸びを比べる（drawdown_control.py と同じ）。
- 判定（結果を見る前に決めた）。採用するのは、次の両方を満たす形が1つでもあるとき。形は、金ではなく「確かめ用の5つ」でいちばん良いものを選ぶ（金に合わせ込まないため）：
   (a) 金：最大の下落 30% にそろえたとき、年率の伸びが今の形より高い（全期間・前半・後半の3つとも）
   (b) 確かめ用の5つ：最大の下落 30% にそろえたとき、5つのうち4つ以上で今の形より高い（全期間）
- あわせて、「大きく持って、下落の上限を数式で決める」場合に、1年で +300% を超える年がいくつ出るかを数える（金、20年）。
使い方: python3 -I tools/research/trend_dd_control.py <商品の口座の書き出しのフォルダ>  → reports/research/trend_dd_control.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drawdown_control as DC  # noqa: E402
import fred_data as F  # noqa: E402
import index_others as IO  # noqa: E402
import index_reversion as IR  # noqa: E402
import trend_signal as TS  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
FORMS = (("今の形（一定の割合）", "const", 1.0), ("GZ：下落 30% で 0", "GZ", 0.30), ("GZ：下落 40% で 0", "GZ", 0.40), ("GZ：下落 50% で 0", "GZ", 0.50),
         ("REDD（直近250日）：下落 30% で 0", "REDD", 0.30), ("REDD：下落 40% で 0", "REDD", 0.40))
GRID = np.arange(0.25, 20.01, 0.25)


def unit_returns(r):
    """値動きを年10%にそろえた日々の損益。"""
    r = r.dropna()
    return r * (0.10 / (r.std() * np.sqrt(ANN)))


def gold_mt5():
    e = pd.read_csv(os.path.join(F.ROOT, "reports", "runs", "0875_equity.csv"))
    e.index = pd.to_datetime(e["date"], format="%Y.%m.%d")
    e = e["equity"].astype(float)
    e = e[e.index.dayofweek < 5]
    return e.pct_change().dropna()


def others(folder):
    data, props = IO.load(folder)
    out = {}
    for sym, name in (("XAGUSD", "銀"), ("COPPER", "銅")):
        d = data[sym]
        costs = dict(spread=float(props.loc[sym, "spread_points"]) * float(props.loc[sym, "point"]) / float(props.loc[sym, "bid"]),
                     swap_long=float(props.loc[sym, "swap_long"]), swap_short=float(props.loc[sym, "swap_short"]))
        r, _, _ = TS.simulate(d, TS.reviewed(TS.raw_signal(d["close"], "T0")), **costs)
        out[name] = r.iloc[560:-1]
    for etf in ("SPY", "QQQ", "DIA"):
        d = Y.fetch(etf)[["open", "high", "low", "close"]].dropna()
        fin = (IR.short_rate("USD", d.index) + IR.MARKUP).values
        r, _, _ = TS.simulate(d, TS.reviewed(TS.raw_signal(d["close"], "T0")), spread=2 * IR.COST, fin=fin)
        out[etf] = r.iloc[560:-1]
    return out


def at30(z, kind, D, target=0.30):
    rows = DC.frontier(z, kind, D, GRID)
    return DC.at_dd(rows, target)


def autocorr(z):
    s = pd.Series(z)
    return [s.autocorr(1)] + [s.rolling(n).sum().iloc[::n].autocorr(1) for n in (5, 20, 60, 250)]


def main():
    folder = sys.argv[1]
    gold = unit_returns(gold_mt5())
    oth = {k: unit_returns(v) for k, v in others(folder).items()}
    lines = ["# 研究：順張りの層を、資産の下落に応じて絞る（`tools/research/trend_dd_control.py`）", "",
             "## 1 損益の自己相関（プラスなら、負けが続きやすく勝ちも続きやすい。下落で絞る形に向く）", "",
             "| 層 | 期間 | 1日 | 5日の合計 | 20日の合計 | 60日の合計 | 250日の合計 |", "|---|---|---|---|---|---|---|"]
    for name, z in [("金（MT5・OANDA）", gold)] + list(oth.items()):
        a = autocorr(z.values)
        lines.append(f"| {name} | {z.index[0].date()}〜{z.index[-1].date()} | " + " | ".join(f"{x:+.2f}" for x in a) + " |")
        print(lines[-1], flush=True)
    # ---------- 同じ最大の下落で比べる
    lines += ["", "## 2 同じ最大の下落（30%）になる大きさで比べた、年率の伸び", "",
              "| 層 | " + " | ".join(f[0] for f in FORMS) + " |", "|---|" + "---|" * len(FORMS)]
    res = {}
    half = len(gold) // 2
    sets = [("金：全期間", gold.values), (f"金：前半（〜{gold.index[half].date()}）", gold.values[:half]), ("金：後半", gold.values[half:])] + [(k, v.values) for k, v in oth.items()]
    for name, z in sets:
        cells = []
        for lab, kind, D in FORMS:
            c, L = at30(z, kind, D)
            res[(name, lab)] = c
            cells.append("—" if np.isnan(c) else f"{c * 100:+.1f}%（L {L:.1f}）")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
        print(lines[-1], flush=True)
    # ---------- 判定：形は、確かめ用の5つで選ぶ
    base = FORMS[0][0]
    score = {}
    for lab, kind, D in FORMS[1:]:
        wins = sum((res[(k, lab)] > res[(k, base)]) for k in oth if not np.isnan(res[(k, lab)]) and not np.isnan(res[(k, base)]))
        gain = np.nanmean([res[(k, lab)] - res[(k, base)] for k in oth])
        score[lab] = (wins, gain)
    best = max(score, key=lambda k: (score[k][0], score[k][1]))
    ga = [res[(n, best)] > res[(n, base)] for n, _ in sets[:3]]
    a_ok, b_ok = all(ga), score[best][0] >= 4
    lines += ["", "## 3 判定", "",
              "- 確かめ用の5つで、今の形より高かった数（と、差の平均）：" + "、".join(f"{k} {v[0]} / 5（{v[1] * 100:+.1f}%）" for k, v in score.items()),
              f"- 確かめ用の5つでいちばん良い形：**{best}**",
              f"- (a) 金で、その形が今の形より高い（全期間・前半・後半）：{'○' if a_ok else '×'}（" + "、".join(f"{res[(n, best)] * 100:+.1f}% 対 {res[(n, base)] * 100:+.1f}%" for n, _ in sets[:3]) + "）",
              f"- (b) 確かめ用の5つのうち4つ以上：{'○' if b_ok else '×'}（{score[best][0]} / 5）",
              f"- 判定：{'**合格**' if (a_ok and b_ok) else '不合格'}"]
    print("\n".join(lines[-5:]), flush=True)
    # ---------- ほかの下落の深さでも
    lines += ["", "## 4 金：ほかの下落の深さにそろえた場合（全期間）", "",
              "| 形 | 最大の下落 20% | 30% | 40% | 50% |", "|---|---|---|---|---|"]
    for lab, kind, D in FORMS:
        rows = DC.frontier(gold.values, kind, D, GRID)
        cells = []
        for tgt in (0.20, 0.30, 0.40, 0.50):
            c, L = DC.at_dd(rows, tgt)
            cells.append("—" if np.isnan(c) else f"{c * 100:+.1f}%（L {L:.1f}）")
        lines.append(f"| {lab} | " + " | ".join(cells) + " |")
        print(lines[-1], flush=True)
    # ---------- 大きく持って、下落の上限を数式で決める：+300% の年の数
    lines += ["", "## 5 金：大きく持ち、下落の上限を数式で決めた場合の、年ごとの成績（20年）", "",
              "L は、値動きを年10%にそろえた損益にかける倍率（L = 4.3 が、今の「最大の設定」50% に当たる）。建玉の上限（証拠金）は入れていない計算。", "",
              "| 形 | L | 年率の伸び | 最大の下落 | +300% 以上の年 | +100% 以上の年 | マイナスの年 | 最悪の年 | 最高の年 | 20年後の資産（最初 = 1） |", "|---|---|---|---|---|---|---|---|---|---|"]
    z = gold.values
    yrs = len(z) / ANN
    for lab, kind, D in (("今の形（一定の割合）", "const", 1.0), ("GZ：下落 50% で 0", "GZ", 0.50), ("GZ：下落 40% で 0", "GZ", 0.40), ("REDD：下落 40% で 0", "REDD", 0.40), ("REDD：下落 50% で 0", "REDD", 0.50)):
        for L in (2.0, 4.3, 6.0, 8.0, 12.0, 16.0):
            eq, _ = DC.path(z, L, kind, D)
            e = pd.Series(eq[1:], index=gold.index)
            by = e.groupby(e.index.year).last()
            prev = np.concatenate([[1.0], by.values[:-1]])
            yr = by.values / prev - 1
            dd = (e / e.cummax() - 1).min()
            lines.append(f"| {lab} | {L:g} | {(e.iloc[-1] ** (1 / yrs) - 1) * 100:+.0f}% | {dd * 100:.0f}% | {int((yr >= 3.0).sum())} | {int((yr >= 1.0).sum())} | {int((yr < 0).sum())} | {yr.min() * 100:+.0f}% | {yr.max() * 100:+.0f}% | {e.iloc[-1]:.3g} |")
            print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "trend_dd_control.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""研究：2回目の文献調査で挙がった案の検証（99章）。土台は98章の改良後の形（HAR 型・VIX の倍率・逆指値 4×σ）。

1 値動きの「予想外の大きさ」（Bianco・Corsi・Renò 2008年）：予想できた値動きは反転を強め、予想外の値動きは継続を強める、という報告。
  u = log(その日の実際の分散) − log(前の日までの値で作った HAR 型の予想)。その日までの u の標準偏差で割る。
  事前に決めた形：u が +1 を超えた日は、建玉を半分にする（逆に、2倍にする形も比べる）。
2 VIX の伸び（Connors・Alvarez 2008年の「VIX stretch」）：VIX の終値が、その10日の平均より 5% 以上高い日が3日続く。
  今のルールが出ていない日の新しい合図になるか／今のルールが出ている日の上乗せになるか。
  VIX は当日の終値（株の終値の15分後に確定するので、現物の検証では少し先を見ている）と、1日前の終値の両方で見る。
3 ディーラーのガンマ（GEX）・ダークプールの空売りの割合（DIX）：SqueezeMetrics の公開の一覧（2011年5月〜）。1日前の値。
  引数に、その CSV の場所を渡す（なければ飛ばす）。
- 物差し：現物の3指数。翌日の損益 ÷ 値動きの見積もり（持ち越しのコスト込み）と、層の成績（値動きを年10%にそろえる）。
使い方: python3 -I tools/research/index_lit2_tests.py [DIX.csv の場所]  → reports/research/index_lit2_tests.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_vix_sizing as V  # noqa: E402
import index_vol_forecast as VF  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252


def cell(x):
    x = x.dropna()
    if len(x) < 30:
        return "—"
    by = x.groupby(level=0).mean()
    return f"{x.mean():+.3f}（t {by.mean() / by.std() * np.sqrt(len(by)):+.1f}、{len(x)} 件）"


def main():
    sets = V.load_sets("cash")
    rk = {n: V.vix_rank(t[0].index)[0] for n, t in sets.items()}
    vm = {n: V.mult_of(rk[n], (0.5, 1.0, 1.5)) for n in sets}
    vix = Y.fetch("VIX")
    vc = vix["close"]
    stretch = (vc >= 1.05 * vc.rolling(10).mean())
    v1 = (stretch & stretch.shift(1) & stretch.shift(2)).astype(float)
    rows, usd = [], {}
    for name, (d, n, sg, rate, div) in sets.items():
        c = d["close"]
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
        fin = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
        y = ((c.pct_change() + fin).shift(-1) / sg)
        rv = VF.daily_var(d)
        fc = (sg ** 2).shift(1)                                   # 前の日までの値で作った、その日の分散の予想
        u = np.log(rv.clip(lower=1e-10)) - np.log(fc)
        us = u / u.expanding(min_periods=500).std()
        usd[name] = us
        al = lambda s, lag: s.reindex(s.index.union(d.index)).ffill(limit=3).reindex(d.index).shift(lag)   # noqa: E731
        rows.append(pd.DataFrame({"name": name, "n": n, "y": y, "u": us, "v1_same": al(v1, 0), "v1_lag": al(v1, 1), "vr": rk[name],
                                  "above": (c > c.rolling(200).mean()).astype(float)}))
    P = pd.concat(rows)
    P = P[P.index >= IRK.START]
    lines = ["# 研究：2回目の文献調査で挙がった案の検証（`tools/research/index_lit2_tests.py`）", "",
             "米国3指数、2000年10月〜2026年11月。値は、翌日の損益 ÷ 値動きの見積もり（持ち越しのコスト込み）。t 値は日付ごとにまとめて計算。", "",
             "## 1 値動きの「予想外の大きさ」（u = その日の実際の分散が、予想より大きかった度合い）", "",
             "| u の水準 | ルールが出ている日：全期間 | 2011年〜 | ルールが2つ以上 | ルールなしの日 |", "|---|---|---|---|---|"]
    R = P[P["n"] >= 1]
    for lab, m in (("−0.5 未満（予想より静か）", P["u"] < -0.5), ("−0.5〜+0.5", (P["u"] >= -0.5) & (P["u"] <= 0.5)), ("+0.5〜+1", (P["u"] > 0.5) & (P["u"] <= 1.0)),
                   ("+1 を超える（予想よりずっと荒い）", P["u"] > 1.0)):
        post = P.index >= "2011-01-01"
        lines.append(f"| {lab} | {cell(P['y'][m & (P['n'] >= 1)])} | {cell(P['y'][m & post & (P['n'] >= 1)])} | {cell(P['y'][m & (P['n'] >= 2)])} | {cell(P['y'][m & (P['n'] == 0)])} |")
        print(lines[-1], flush=True)
    head = "| 形 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | プラスの年 | " + " | ".join(p[0] for p in IRK.PER) + " |"
    sep = "|---|" + "---|" * (7 + len(IRK.PER))
    lines += ["", head, sep]
    for label, f in (("98章の形（変えない）", None), ("u が +1 を超えた日は半分", lambda u: np.where(u > 1.0, 0.5, 1.0)),
                     ("u が +1 を超えた日は 1.5 倍（逆）", lambda u: np.where(u > 1.0, 1.5, 1.0)), ("u が −0.5 未満の日は半分", lambda u: np.where(u < -0.5, 0.5, 1.0))):
        mm = {n: vm[n] if f is None else vm[n] * pd.Series(f(usd[n].fillna(0.0).values), index=usd[n].index) for n in sets}
        s, _ = V.stat(V.sleeve(sets, mm, "cash", 4.0), IRK.START, IRK.PER)
        lines.append(f"| {label} | {s} |")
        print(lines[-1], flush=True)

    # ---------- 2 VIX の伸び
    lines += ["", "## 2 VIX の伸び（終値が10日の平均より 5% 以上高い日が3日続く。200日の平均より上の日だけ）", "",
              "| 今のルール | VIX の伸び | 当日の VIX で判定：全期間 | 2009年〜（公表後） | 1日前の VIX で判定：全期間 | 2009年〜 |", "|---|---|---|---|---|---|"]
    A = P[P["above"] > 0]
    post = A.index >= "2009-01-01"
    for pl, pm in (("出ている", A["n"] >= 1), ("出ていない", A["n"] == 0)):
        for vl, on in (("あり", 1.0), ("なし", 0.0)):
            cells = []
            for col in ("v1_same", "v1_lag"):
                m = pm & (A[col] == on)
                cells += [cell(A["y"][m]), cell(A["y"][m & post])]
            lines.append(f"| {pl} | {vl} | " + " | ".join(cells) + " |")
            print(lines[-1], flush=True)
    lines += ["", head, sep]
    for label, col, add in (("98章の形（変えない）", None, 0.0), ("VIX の伸びがある日は 1.5 倍（1日前の VIX）", "v1_lag", 0.5), ("VIX の伸びがある日は 1.5 倍（当日の VIX）", "v1_same", 0.5)):
        mm = {}
        for n in sets:
            if col is None:
                mm[n] = vm[n]
            else:
                q = P[P["name"] == n][col].reindex(sets[n][0].index).fillna(0.0)
                mm[n] = vm[n] * (1.0 + add * q)
        s, _ = V.stat(V.sleeve(sets, mm, "cash", 4.0), IRK.START, IRK.PER)
        lines.append(f"| {label} | {s} |")
        print(lines[-1], flush=True)

    # ---------- 3 GEX・DIX
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        g = pd.read_csv(sys.argv[1])
        g.index = pd.to_datetime(g["date"])
        lines += ["", f"## 3 ディーラーのガンマ（GEX）・ダークプールの空売りの割合（DIX）（1日前の値。{g.index[0].date()}〜{g.index[-1].date()}）", "",
                  "| 状態 | ルールが出ている日 | そのうち VIX が高い状態 | VIX が中・低の状態 | ルールなしの日 |", "|---|---|---|---|---|"]
        Q = P.copy()
        for col in ("gex", "dix"):
            s = g[col].astype(float)
            Q[col] = np.concatenate([s.reindex(s.index.union(sets[n][0].index)).ffill(limit=3).reindex(sets[n][0].index).shift(1).reindex(P[P["name"] == n].index).values
                                     for n in sets])
        Q = Q.dropna(subset=["gex", "dix"])
        dq1, dq2 = Q["dix"].quantile(1 / 3), Q["dix"].quantile(2 / 3)
        for lab, m in (("GEX がマイナス", Q["gex"] < 0), ("GEX がプラス", Q["gex"] >= 0), ("DIX が下 1/3", Q["dix"] < dq1), ("DIX が中", (Q["dix"] >= dq1) & (Q["dix"] < dq2)),
                       ("DIX が上 1/3", Q["dix"] >= dq2)):
            r = m & (Q["n"] >= 1)
            lines.append(f"| {lab} | {cell(Q['y'][r])} | {cell(Q['y'][r & (Q['vr'] >= 2 / 3)])} | {cell(Q['y'][r & (Q['vr'] < 2 / 3)])} | {cell(Q['y'][m & (Q['n'] == 0)])} |")
            print(lines[-1], flush=True)
        lines.append(f"\nGEX がマイナスの日の割合：{(Q['gex'] < 0).mean() * 100:.0f}%。そのうち VIX が高い状態の日：{((Q['gex'] < 0) & (Q['vr'] >= 2 / 3)).sum() / max((Q['gex'] < 0).sum(), 1) * 100:.0f}%。")
    out = os.path.join(F.ROOT, "reports", "research", "index_lit2_tests.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

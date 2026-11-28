#!/usr/bin/env python3
"""研究：OANDA で売買できる銘柄のうち、まだ日足のパターンを調べていないもの（銀・銅・指数11）の一斉検証（108章）。日付・時刻は使わない。

- パターン：pattern_zoo.py の 27 種類（勢い・行き過ぎの戻り・高値安値の更新・ボリンジャー・RSI・移動平均の交差・値幅の縮小からの放れ・足の形 など）。
  保有は 1・4・12 日、買いのシグナルと売りのシグナルを別々に評価する。
- 計算（金の検証 gold_oversold.py で分かった反省を入れる）：重なった取引を別々に数えない。「最後にシグナルが出た日から H 日のあいだ、1つの建玉を持つ」形の、
  日々の損益で測る。建玉は、その銘柄の値動き（直近60日）が口座の年10%になる大きさ。売買は次の日の始値。
  コスト：スプレッド（口座の値）と、スワップ（口座の今の値。買い・売りそれぞれ）。
  買いのシグナルは「いつも買って持っている形」に対する上乗せ（α）の t 値で、売りのシグナルは損益そのものの t 値で評価する（指数・金属は長い目で上がるため）。
- データ：OANDA の実際の日足。指数11（US2000・JP225・GER30・UK100・EU50・FRA40・NL25・AUS200・HK50・CHINA50・SING30。2016年〜）と、銀・銅（2006年〜）。
  先物を元にした原油・天然ガス・穀物は入れない（値段に、スワップで打ち消される分の値動きが入っているため。107章）。
- 期間：前半（設計）と後半（確認）に半分ずつ分ける（指数は 2021年末、金属は 2015年末が境目）。
- 判定（結果を見る前に決めた）：前半で t ≥ 3.0、かつ、後半で t ≥ 2.0。13銘柄 × 27 × 3 × 2 ＝ 約2,100通り調べるので、効き目がなくても、たまたま両方を満たすものが
  0.06 個ほど出る計算。合格が出たら、その銘柄に近い銘柄でも同じ向きかを確かめてから、次に進める。
使い方: python3 -I tools/research/daily_zoo_oanda.py <指数の口座の書き出し> <商品の口座の書き出し>  → reports/research/daily_zoo_oanda.md、daily_zoo_oanda_all.csv
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import gold_oversold as GO  # noqa: E402
import index_others as IO  # noqa: E402
import pattern_zoo as PZ  # noqa: E402
import trend_signal as TS  # noqa: E402

HOLDS = (1, 4, 12)
IDX = ("US2000", "JP225", "GER30", "UK100", "EU50", "FRA40", "NL25", "AUS200", "HK50", "CHINA50", "SING30")
MET = ("XAGUSD", "COPPER")


def main():
    ix, pi = IO.load(sys.argv[1])
    cm, pc = IO.load(sys.argv[2])
    rows = []
    for sym, data, props, split in [(s, ix, pi, "2022-01-01") for s in IDX] + [(s, cm, pc, "2016-01-01") for s in MET]:
        d = data[sym]
        costs = dict(spread=float(props.loc[sym, "spread_points"]) * float(props.loc[sym, "point"]) / float(props.loc[sym, "bid"]),
                     swap_long=float(props.loc[sym, "swap_long"]), swap_short=float(props.loc[sym, "swap_short"]))
        b = d.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c"})
        sig = {k: v for k, v in PZ.signals(b, pd.Series(dtype=float)).items() if "金利差" not in k}
        always, _, _ = TS.simulate(d, pd.Series(1.0, index=d.index), **costs)
        always = always.iloc[260:-1]
        for pname, s in sig.items():
            s = pd.Series(np.asarray(s, dtype=float), index=d.index)
            for side in (1, -1):
                for H in HOLDS:
                    on = ((s == side).astype(float).rolling(H, min_periods=1).max() * side).where(s.notna())
                    r, held, _ = TS.simulate(d, on, **costs)
                    r, held = r.iloc[260:-1], held.iloc[260:-1]
                    rec = dict(sym=sym, pattern=pname, hold=H, side="買い" if side > 0 else "売り", share=float((held != 0).mean()))
                    for lab, m in (("t1", r.index < split), ("t2", r.index >= split)):
                        x = r[m]
                        if side > 0:
                            rec[lab] = GO.alpha(x, always[m])[1] if (held[m] != 0).sum() > 20 else np.nan
                        else:
                            rec[lab] = GO.tstat(x) if (held[m] != 0).sum() > 20 else np.nan
                        rec[lab.replace("t", "sh")] = GO.sharpe(x)
                    rows.append(rec)
        print(sym, "done", flush=True)
    df = pd.DataFrame(rows)
    out_dir = os.path.join(F.ROOT, "reports", "research")
    df.round(3).to_csv(os.path.join(out_dir, "daily_zoo_oanda_all.csv"), index=False)
    v = df.dropna(subset=["t1", "t2"])
    hit = v[(v["t1"] >= 3.0) & (v["t2"] >= 2.0)].sort_values("t1", ascending=False)
    lines = ["# 研究：銀・銅・指数11の、日足のパターンの一斉検証（`tools/research/daily_zoo_oanda.py`）", "",
             f"調べた組み合わせ：{len(v)} 通り（シグナルが少なすぎて測れないものを除く）。t は、買いでは「いつも持つ形」に対する上乗せの t 値、売りでは損益の t 値（どちらもコスト後、重ねて持たない形）。", "",
             f"- 前半の t の分布：最大 {v['t1'].max():+.1f}、中央 {v['t1'].median():+.1f}、最小 {v['t1'].min():+.1f}。t ≥ 3.0 は {int((v['t1'] >= 3.0).sum())} 通り（たまたまなら {len(v) * 0.00135:.1f} 通り）。",
             f"- 前半 t ≥ 3.0 かつ 後半 t ≥ 2.0：**{len(hit)} 通り**", ""]
    if len(hit):
        lines += ["| 銘柄 | パターン | 保有 | 買い・売り | 前半の t（シャープ） | 後半の t（シャープ） | 持っている日の割合 |", "|---|---|---|---|---|---|---|"]
        for _, r in hit.iterrows():
            lines.append(f"| {r.sym} | {r.pattern} | {r.hold}日 | {r.side} | {r.t1:+.1f}（{r.sh1:+.2f}） | {r.t2:+.1f}（{r.sh2:+.2f}） | {r.share * 100:.0f}% |")
    top = v.sort_values("t1", ascending=False).head(12)
    lines += ["", "## 参考：前半の t が大きい順（上位12）", "", "| 銘柄 | パターン | 保有 | 買い・売り | 前半の t | 後半の t |", "|---|---|---|---|---|---|"]
    for _, r in top.iterrows():
        lines.append(f"| {r.sym} | {r.pattern} | {r.hold}日 | {r.side} | {r.t1:+.1f} | {r.t2:+.1f} |")
    open(os.path.join(out_dir, "daily_zoo_oanda.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[2:]))


if __name__ == "__main__":
    main()

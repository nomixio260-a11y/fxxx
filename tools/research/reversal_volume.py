#!/usr/bin/env python3
"""研究：出来高が多い日の下げほど、戻りやすいか（105章）。日付・時刻は使わない。

- 仮説（文献）：出来高をともなった値動きは、流動性を求める売買（急いで売りたい人の売り）による分が大きく、翌日以降に戻りやすい
  （Campbell・Grossman・Wang 1993。Lochstoer・Muir 2026 は、1955〜2025年の米国株で「出来高の多い日の値動きほど反転が強い」と報告）。
- 確かめ方：実際に売買された出来高がある ETF（SPY 1993年〜・QQQ 1999年〜・DIA 1998年〜）。戻りの層は EA と同じ形
  （R2・D7・IBS、重み 1:2:4、HAR 型、VIX の倍率、逆指値 4×σ、判定は終値・売買は次の日の始値、コストは CFD と同じ形）。
- 出来高の多さ：その日の出来高 ÷ 直前20日の出来高の中央値（その日より前の値だけで決まる）。1 より大きければ「多い」。
- 事前に決めた形（結果を見る前に決めた。これ以外は試さない）：
   V1 直近の確定した日足の出来高が「多い」なら、戻りの建玉を 1.3 倍、「少ない」なら 0.7 倍
   V2 なめらかな形：建玉 ×（出来高の多さ。0.5〜1.5 に収める）
- 判定（事前に決めた基準）。採用するのは、次をすべて満たす形だけ：
   (a) 持っている日の「建玉1単位あたりの翌日の損益」が、出来高の多い日のあとのほうが高く、その差の t 値が 2.0 以上（3本を合わせた全期間）
   (b) 3本の層のシャープが、前半・後半の両方で、今の形より高い
   (c) 3本のうち2本以上で、その ETF だけの層のシャープが今の形より高い
  採用する場合は、さらに、CFD の値動きの回数（ティック数）が ETF の出来高の代わりになるかを確かめる（EA は ETF の出来高を見られないため）。
使い方: python3 tools/research/reversal_volume.py  → reports/research/reversal_volume.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_stop as IS  # noqa: E402
import index_vix_sizing as V  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
W = {0: 0.0, 1: 0.25, 2: 0.5, 3: 1.0}
ETFS = ("SPY", "QQQ", "DIA")


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 200 and x.std() > 0 else np.nan


def build(name):
    d = Y.fetch(name)[["open", "high", "low", "close", "volume"]].dropna()
    d = d[d["volume"] > 0]
    st = IR.rules(d)
    sg = IS.har_sigma(d)
    base = (st["R2<10"] + st["D7"] + st["IBS"]).map(lambda v: W[int(round(v))])
    vm = V.mult_of(V.vix_rank(d.index)[0], (0.5, 1.0, 1.5))
    w = (base * vm * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
    rv = d["volume"] / d["volume"].shift(1).rolling(20).median()
    rate = IR.short_rate("USD", d.index)
    return d, w, sg, rate, rv


def run(d, w, sg, rate):
    r, _, _ = IS.run(d, w, sg, rate, 0.0, 4.0, "open")
    return r.iloc[260:]


def main():
    lines = ["# 研究：出来高が多い日の下げほど、戻りやすいか（`tools/research/reversal_volume.py`）", "",
             "ETF（実際に売買された値段と出来高）。戻りの層は EA と同じ形。コスト込み。", ""]
    rets = {k: {} for k in ("base", "V1", "V2")}
    unit_rows = []
    for name in ETFS:
        d, w, sg, rate, rv = build(name)
        m1 = pd.Series(np.where(rv > 1.0, 1.3, 0.7), index=d.index).where(rv.notna(), 1.0)
        m2 = rv.clip(lower=0.5, upper=1.5).fillna(1.0)
        rets["base"][name] = run(d, w, sg, rate)
        rets["V1"][name] = run(d, w * m1, sg, rate)
        rets["V2"][name] = run(d, w * m2, sg, rate)
        # 建玉1単位あたりの翌日の損益（持っている日だけ）。出来高は、建玉を決めた日（前の日足）の値
        r = rets["base"][name]
        wh = w.shift(1).reindex(r.index)
        u = (r / wh).where(wh > 0).dropna()
        g = rv.shift(1).reindex(u.index)
        unit_rows.append(pd.DataFrame({"u": u, "rv": g, "name": name}).dropna())
    U = pd.concat(unit_rows)
    hi, lo = U[U["rv"] > 1.0]["u"], U[U["rv"] <= 1.0]["u"]
    t_diff = (hi.mean() - lo.mean()) / np.sqrt(hi.var() / len(hi) + lo.var() / len(lo))
    lines += ["## 1 持っている日の、建玉1単位あたりの翌日の損益（3本を合わせて）", "",
              "| 建玉を決めた日の出来高 | 日数 | 平均（%） | 標準偏差（%） | t 値 |", "|---|---|---|---|---|",
              f"| 多い（直前20日の中央値より上） | {len(hi)} | {hi.mean() * 100:+.3f} | {hi.std() * 100:.2f} | {hi.mean() / hi.std() * np.sqrt(len(hi)):+.1f} |",
              f"| 少ない | {len(lo)} | {lo.mean() * 100:+.3f} | {lo.std() * 100:.2f} | {lo.mean() / lo.std() * np.sqrt(len(lo)):+.1f} |",
              "", f"- 差（多い − 少ない）：{(hi.mean() - lo.mean()) * 100:+.3f}%、t 値 {t_diff:+.2f}", ""]
    print("\n".join(lines[-8:]), flush=True)
    q = U.copy()
    q["bin"] = pd.qcut(q["rv"], 5, labels=False)
    lines += ["| 出来高の多さ（5つに分けた順位） | 範囲 | 日数 | 平均（%） | t 値 |", "|---|---|---|---|---|"]
    for b, x in q.groupby("bin"):
        lines.append(f"| {int(b) + 1} | {x['rv'].min():.2f}〜{x['rv'].max():.2f} | {len(x)} | {x['u'].mean() * 100:+.3f} | {x['u'].mean() / x['u'].std() * np.sqrt(len(x)):+.1f} |")
        print(lines[-1], flush=True)
    for per, a, b in (("1994〜2009年", "1994-01-01", "2010-01-01"), ("2010年〜", "2010-01-01", "2027-01-01")):
        x = U[(U.index >= a) & (U.index < b)]
        h2, l2 = x[x["rv"] > 1.0]["u"], x[x["rv"] <= 1.0]["u"]
        lines.append(f"- {per}：多い {h2.mean() * 100:+.3f}%（{len(h2)} 日）／少ない {l2.mean() * 100:+.3f}%（{len(l2)} 日）、差の t 値 {(h2.mean() - l2.mean()) / np.sqrt(h2.var() / len(h2) + l2.var() / len(l2)):+.2f}")
        print(lines[-1], flush=True)
    # ---------- 層の成績
    lines += ["", "## 2 層のシャープ（今の形・V1・V2）", "", "| 対象 | 形 | 全期間 | 前半 | 後半 |", "|---|---|---|---|---|"]
    out = {}
    for key, lab in (("base", "今の形"), ("V1", "V1（多い 1.3 倍・少ない 0.7 倍）"), ("V2", "V2（出来高の多さに比例。0.5〜1.5）")):
        all3 = pd.concat(rets[key].values(), axis=1, sort=True).fillna(0.0).mean(axis=1)
        all3 = all3[all3.index >= "2000-06-01"]                      # 3本がそろってから
        mid = all3.index[len(all3) // 2]
        out[key] = dict(all=sh(all3), a=sh(all3[all3.index <= mid]), b=sh(all3[all3.index > mid]), each={n: sh(rets[key][n]) for n in ETFS})
        lines.append(f"| 3本の層（2000年6月〜。前半は {mid.date()} まで） | {lab} | {out[key]['all']:+.2f} | {out[key]['a']:+.2f} | {out[key]['b']:+.2f} |")
        print(lines[-1], flush=True)
        for n in ETFS:
            x = rets[key][n]
            m2 = x.index[len(x) // 2]
            lines.append(f"| {n} だけ | {lab} | {sh(x):+.2f} | {sh(x[x.index <= m2]):+.2f} | {sh(x[x.index > m2]):+.2f} |")
    lines += ["", "## 3 判定", "", "| 形 | (a) 差の t 値 ≥ 2.0 | (b) 3本の層：前半・後半とも今の形より高い | (c) 2本以上で今の形より高い | 判定 |", "|---|---|---|---|---|"]
    for key in ("V1", "V2"):
        a = t_diff >= 2.0
        b = out[key]["a"] > out["base"]["a"] and out[key]["b"] > out["base"]["b"]
        wins = sum(out[key]["each"][n] > out["base"]["each"][n] for n in ETFS)
        ok = a and b and wins >= 2
        lines.append(f"| {key} | {'○' if a else '×'}（{t_diff:+.2f}） | {'○' if b else '×'}（{out[key]['a']:+.2f} / {out[key]['b']:+.2f}、今の形は {out['base']['a']:+.2f} / {out['base']['b']:+.2f}） | "
                     f"{'○' if wins >= 2 else '×'}（{wins} / 3） | {'**合格**' if ok else '不合格'} |")
        print(lines[-1], flush=True)
    path = os.path.join(F.ROOT, "reports", "research", "reversal_volume.md")
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

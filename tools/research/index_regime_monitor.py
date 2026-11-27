#!/usr/bin/env python3
"""研究：戻りの手法の「前提」が続いているかを、数式で監視する（100章）。相場の性質が変わっても、崩れにくくするため。

- 戻りの手法の前提は、「指数の日々の値動きは、反転しやすい」こと。これは 1999年ごろから続いている性質で、それより前は逆（続きやすい）だった
  （Baltussen・van Bekkum・Da 2019年）。将来、また逆に戻るかもしれない。
- 監視に使う値（同じ論文の物差し）：MAC5 = 当日の値動き ×（4×前日 + 3×2日前 + 2×3日前 + 1×4日前の値動き）÷（5 × 分散）。
  マイナスなら「反転しやすい」、プラスなら「続きやすい」。これを、過去 W 日の平均で見る（その日までの値だけを使う）。
- 仕組み：過去 W 日の MAC5 の平均がプラス（続きやすい相場）のあいだは、戻りのルールを止める。
  止める対象は、(a) 3つのルールすべて、(b) 200日の平均の条件がない IBS だけ、の2通りを比べる。
- データ：S&P500（1962年〜。高値・安値がそろう時期から）、NASDAQ100（1985年〜）、ダウ（1992年〜）。VIX がない時期（〜1989年）は、VIX の倍率を 1 にする。
- 期間ごとの成績（全期間の値動きを年10%にそろえる）：1962〜81／1982〜98／1999〜2010／2011〜26。
使い方: python3 tools/research/index_regime_monitor.py  → reports/research/index_regime_monitor.md
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
W124 = {0: 0.0, 1: 0.25, 2: 0.5, 3: 1.0}
ERAS = (("1962〜81", "1962-07-01", "1982-01-01"), ("1982〜98", "1982-01-01", "1999-01-01"), ("1999〜2010", "1999-01-01", "2011-01-01"),
        ("2011〜26", "2011-01-01", "2027-01-01"), ("うち 2023年11月〜", "2023-11-01", "2027-01-01"))


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 100 and x.std() > 0 else np.nan


def mac5(c):
    r = np.log(c).diff()
    var = r.rolling(250, min_periods=120).var()
    return r * (4 * r.shift(1) + 3 * r.shift(2) + 2 * r.shift(3) + r.shift(4)) / (5.0 * var)


def load(name, start):
    yn, ccy, div, _ = IR.INDEX[name]
    d = Y.fetch(yn)
    d = d[d.index >= start].copy()
    st = IR.rules(d)
    rate = IR.short_rate(ccy, d.index)
    sg = IS.har_sigma(d)
    rk = V.vix_rank(d.index)[0]
    return d, st, rate, div, sg, rk


def main():
    data = {"S&P500": load("S&P500", "1961-01-01"), "NASDAQ100": load("NASDAQ100", "1985-10-01"), "ダウ": load("ダウ", "1992-01-01")}
    lines = ["# 研究：戻りの手法の前提の監視（`tools/research/index_regime_monitor.py`）", "",
             "## 過去 750 日の MAC5 の平均（マイナス = 反転しやすい）", "", "| 指数 | " + " | ".join(e[0] for e in ERAS) + " | プラスだった日の割合（1999年〜） |", "|---|" + "---|" * (len(ERAS) + 1)]
    mon = {}
    for name, (d, st, rate, div, sg, rk) in data.items():
        m = mac5(d["close"])
        mon[name] = {W: m.rolling(W, min_periods=W // 2).mean() for W in (500, 750, 1000)}
        x = mon[name][750]
        lines.append(f"| {name} | " + " | ".join(f"{x[(x.index >= a) & (x.index < b)].mean():+.3f}" if len(x[(x.index >= a) & (x.index < b)].dropna()) > 100 else "—" for _, a, b in ERAS)
                     + f" | {(x[x.index >= '1999-01-01'] > 0).mean() * 100:.0f}% |")
        print(lines[-1], flush=True)

    def run(names, which, W, thr, ref=None):
        parts = []
        for name in names:
            d, st, rate, div, sg, rk = data[name]
            if W is None:
                on = pd.Series(1.0, index=d.index)
            else:
                # ref があれば、その指数の監視の値を、すべての指数に使う（市場全体の性質として1つの値で判定する）
                mm = mon[name][W] if ref is None else mon[ref][W].reindex(mon[ref][W].index.union(d.index)).ffill().reindex(d.index)
                on = (mm <= thr).astype(float).where(mm.notna(), 1.0)
            r2, d7, ibs = st["R2<10"], st["D7"], st["IBS"]
            if which == "all":
                n = (r2 + d7 + ibs) * on
            elif which == "ibs":
                n = r2 + d7 + ibs * on
            else:
                n = r2 + d7 + ibs
            w = (n.map(lambda v: W124[int(round(v))]) * V.mult_of(rk, (0.5, 1.0, 1.5)) * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0) / len(names)
            r, _, _ = IS.run(d, w, sg, rate, div, 4.0, "close")
            parts.append(r)
        return pd.concat(parts, axis=1, sort=True).fillna(0.0).sum(axis=1)
    for title, names, start in (("S&P500 だけ（1962年7月〜）", ["S&P500"], "1962-07-01"), ("3指数（そろう時期から。1992年〜はすべて）", ["S&P500", "NASDAQ100", "ダウ"], "1962-07-01")):
        lines += ["", f"## {title}", "", "| 形 | 全期間のシャープ | " + " | ".join(e[0] for e in ERAS) + " | 最悪の日 | 最大の下落 | 止めていた日の割合（1999年〜） |", "|---|" + "---|" * (len(ERAS) + 4)]
        for label, which, W, thr, ref in (("監視なし（99章の形）", "none", None, 0.0, None), ("3つのルールすべてを止める：過去 750 日", "all", 750, 0.0, None),
                                     ("IBS だけを止める：過去 500 日", "ibs", 500, 0.0, None),
                                     ("IBS だけを止める：過去 750 日", "ibs", 750, 0.0, None), ("IBS だけを止める：過去 1000 日", "ibs", 1000, 0.0, None),
                                     ("IBS だけを止める：過去 750 日・+0.02 を超えたら", "ibs", 750, 0.02, None),
                                     ("S&P500 の値で、すべての指数を判定：過去 750 日・0 を超えたら", "ibs", 750, 0.0, "S&P500"),
                                     ("**S&P500 の値で、すべての指数を判定：過去 750 日・+0.02 を超えたら**", "ibs", 750, 0.02, "S&P500")):
            r = run(names, which, W, thr, ref)
            r = r[r.index >= start]
            z = r * (0.10 / (r.std() * np.sqrt(ANN)))
            eq = (1 + z).cumprod()
            off = "—" if W is None else f"{np.mean([(mon[ref or n][W][mon[ref or n][W].index >= '1999-01-01'] > thr).mean() for n in names]) * 100:.0f}%"
            lines.append(f"| {label} | {sh(z):+.2f} | " + " | ".join(f"{sh(z[(z.index >= a) & (z.index < b)]):+.2f}" for _, a, b in ERAS)
                         + f" | {z.min() * 100:.1f}% | {(eq / eq.cummax() - 1).min() * 100:.0f}% | {off} |")
            print(lines[-1], flush=True)
    # ルールごとの、時期ごとの成績（S&P500）
    d, st, rate, div, sg, rk = data["S&P500"]
    lines += ["", "## 参考：S&P500 のルールごとの成績（監視なし。ルール1つだけを持った場合のシャープ）", "", "| ルール | " + " | ".join(e[0] for e in ERAS) + " |", "|---|" + "---|" * len(ERAS)]
    for key in ("R2<10", "D7", "IBS"):
        w = (st[key] * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
        r, _, _ = IS.run(d, w, sg, rate, div, None, "close")
        lines.append(f"| {key} | " + " | ".join(f"{sh(r[(r.index >= a) & (r.index < b)]):+.2f}" for _, a, b in ERAS) + " |")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_regime_monitor.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

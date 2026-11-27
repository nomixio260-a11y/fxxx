#!/usr/bin/env python3
"""研究（FX だけで取引する）：商品（原油・金・銅）の流れに合わせて、資源国の通貨を持つと、期待値はプラスか。日付・曜日は使わない。

- 資源国の通貨（豪ドル・NZドル・カナダドル・ノルウェークローネ）は、商品の値段と一緒に動きやすい。
  商品には「上がっている流れは続きやすい」という性質があるとされるので、商品の過去250日（または60日）の向きに合わせて、
  資源国の通貨を対米ドルで買う・売る形を確かめる（取引は為替だけ）。
- 判定は前日までの商品の終値。週1回の入れ替え。コスト・スワップ（金利差 − 上乗せ 年1%）込み。データは FRED の日次（NY 正午）。
使い方: python3 tools/research/fx_commodity_link.py  → reports/research/fx_commodity_link.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carry_breadth as CB  # noqa: E402
import fred_data as F  # noqa: E402
import styles_long as SL  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 261
LINKS = {"原油 → CAD・NOK": (["oil"], ["CAD", "NOK"]), "金・銅 → AUD": (["gold", "cop"], ["AUD"]),
         "原油・金・銅 の平均 → AUD・NZD・CAD・NOK": (["oil", "gold", "cop"], ["AUD", "NZD", "CAD", "NOK"])}


def commodity():
    out = {}
    oil = F.fetch("DCOILWTICO").dropna()
    out["oil"] = np.log(oil.where(oil > 1))
    out["gold"] = np.log(Y.fetch("GC")["close"].where(lambda x: x > 0))
    out["cop"] = np.log(Y.fetch("HG")["close"].where(lambda x: x > 0))
    return out


def main():
    v, rate = CB.load()
    com = commodity()
    lines = ["# 研究：商品の流れに合わせて、資源国の通貨を持つ（取引は為替だけ。`tools/research/fx_commodity_link.py`）", "",
             "商品の過去 L 日の向きがプラスなら資源国の通貨を対米ドルで買い、マイナスなら売る。週1回の入れ替え、コスト・スワップ込み。期間ごとの列は年率シャープ。", "",
             "| 形 | " + " | ".join(p[0] for p in SL.PER) + " | 全体（2000年〜） | t 値 | プラスの年 |", "|---|" + "---|" * (len(SL.PER) + 3)]
    for name, (cs, ccys) in LINKS.items():
        for L in (60, 250):
            sig = None
            for c in cs:
                s = np.sign(com[c].diff(L)).shift(1)                 # 前日までの値で判定
                s = s.reindex(s.index.union(v.index)).ffill().reindex(v.index)
                sig = s if sig is None else sig + s
            sig = np.sign(sig)
            keep = np.zeros(len(v), bool)
            keep[::5] = True
            sig = sig.where(pd.Series(keep, index=v.index), np.nan).ffill().fillna(0.0)
            parts = []
            for cc in ccys:
                ret = v[cc].pct_change().shift(-1)
                vol = v[cc].pct_change().rolling(60, min_periods=40).std() * np.sqrt(ANN)
                w = sig * (0.10 / vol).clip(upper=4.0).fillna(0.0)
                carry = (w * (rate[cc] - rate["USD"]) - w.abs() * 1.0) / 100.0 / ANN
                tc = (w - w.shift(1).fillna(0.0)).abs() * (CB.COST_CCY[cc] + CB.COST_CCY["USD"])
                parts.append((w * ret + carry - tc).fillna(0.0))
            r = pd.concat(parts, axis=1).mean(axis=1)
            cells = [f"{SL.sharpe(r[(r.index >= a) & (r.index < b)]):+.2f}" for _, a, b in SL.PER]
            z = r[r.index >= "2000-01-01"]
            yr = z.groupby(z.index.year).sum()
            s_ = SL.sharpe(z)
            lines.append(f"| {name}（過去{L}日） | " + " | ".join(cells) + f" | {s_:+.2f} | {s_ * np.sqrt(len(z) / ANN):+.1f} | {(yr > 0).sum()}/{len(yr)} |")
    out = os.path.join(F.ROOT, "reports", "research", "fx_commodity_link.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

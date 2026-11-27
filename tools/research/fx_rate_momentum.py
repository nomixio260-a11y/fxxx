#!/usr/bin/env python3
"""研究（FX）：金利の「変化」で通貨を選ぶ（Ang・Chen 2010年の報告。2回目の文献調査で挙がった案）。日付・曜日は使わない。

- 金利差の「水準」で選ぶのが金利差の層（キャリー）。ここでは、各通貨の短期金利が過去 k か月でどれだけ上がったか（下がったか）の順位で選ぶ：
  金利が相対的に上がっている通貨を買い、下がっている通貨を売る。重み・コストは carry_breadth.py と同じ
  （値動きでそろえる、買いと売りの合計を同じにする、スプレッドとスワップの上乗せ込み、全体は年10%）。
- データ：FRED の日次の為替と、月次の短期金利（1か月遅れで使う）。8通貨（米ドルを含む）、1999年〜2026年。
- 公表は 2010年なので、2011年以降が「公表後」。
使い方: python3 tools/research/fx_rate_momentum.py  → reports/research/fx_rate_momentum.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carry_breadth as CB  # noqa: E402
import fred_data as F  # noqa: E402

ANN = CB.ANN
PER = (("1999〜2010（公表前）", "1999-06-01", "2011-01-01"), ("2011〜18", "2011-01-01", "2019-01-01"), ("2019〜21/10", "2019-01-01", "2021-11-01"),
       ("21/11〜26/11", "2021-11-01", "2026-12-01"))


def weights_from(sig_raw, v, ccys):
    """順位に比例する重み（carry_breadth.weights の mode="rank" と同じ作り）。sig_raw は、通貨ごとの元の値（大きいほど買い）。"""
    allc = ccys + ["USD"]
    ret = v[ccys].pct_change()
    dollar = -ret.mean(axis=1)
    vol = ret.rolling(60, min_periods=40).std()
    vol["USD"] = dollar.rolling(60, min_periods=40).std()
    ok = v[ccys].notna() & vol[ccys].notna() & sig_raw[ccys].notna()
    ok["USD"] = vol["USD"].notna() & sig_raw["USD"].notna()
    rr = sig_raw[allc].where(ok)
    n = rr.notna().sum(axis=1)
    sig = rr.rank(axis=1).sub((n + 1) / 2.0, axis=0).div(((n - 1) / 2.0).replace(0, np.nan), axis=0)
    w = (sig / vol[allc]).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    lo, sh = w.clip(lower=0), w.clip(upper=0)
    lo = lo.div(lo.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0) * 0.5
    sh = sh.div(sh.abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0) * 0.5
    both = (lo.sum(axis=1) > 0) & (sh.abs().sum(axis=1) > 0)
    return (lo + sh).where(both, 0.0)


def run(w0, v, rate):
    outs = []
    for ph in range(5):
        keep = np.zeros(len(w0), bool)
        keep[ph::5] = True
        w = w0.where(pd.Series(keep, index=w0.index), np.nan).ffill().fillna(0.0)
        ws = w.mul(CB.exante(w, v), axis=0)
        outs.append(CB.pnl(ws, v, rate))
    return sum(outs) / len(outs)


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 50 and x.std() > 0 else np.nan


def main():
    v, rate = CB.load()
    ccys = CB.G8
    allc = ccys + ["USD"]
    lines = ["# 研究（FX）：金利の変化で通貨を選ぶ（`tools/research/fx_rate_momentum.py`）", "",
             "8通貨（米ドルを含む）、1999年6月〜2026年11月。コスト・スワップの上乗せ込み、値動きを年10%にそろえる。", "",
             "| 形 | 全期間のシャープ | t 値 | 最大の下落 | " + " | ".join(p[0] for p in PER) + " | 金利差の水準の層との相関 |", "|---|---|---|---|" + "---|" * (len(PER) + 1)]
    lvl = run(CB.weights(v, rate, ccys), v, rate)
    res = {"金利差の水準（今の層と同じ考え方）": lvl}
    for k in (63, 126, 252):
        d = rate[allc] - rate[allc].shift(k)
        res[f"金利の変化（過去 {k // 21} か月）"] = run(weights_from(d, v, ccys), v, rate)
    # 水準と変化の両方（順位の平均）
    d6 = rate[allc] - rate[allc].shift(126)
    both = rate[allc].rank(axis=1) + d6.rank(axis=1)
    res["水準の順位 ＋ 変化（6か月）の順位"] = run(weights_from(both, v, ccys), v, rate)
    for label, x in res.items():
        x = x[(x.index >= "1999-06-01")]
        z = x * (0.10 / (x.std() * np.sqrt(ANN)))
        eq = (1 + z).cumprod()
        lines.append(f"| {label} | {sh(z):+.2f} | {sh(z) * np.sqrt(len(z) / ANN):+.1f} | {(eq / eq.cummax() - 1).min() * 100:.0f}% | "
                     + " | ".join(f"{sh(z[(z.index >= a) & (z.index < b)]):+.2f}" for _, a, b in PER) + f" | {x.corr(lvl.reindex(x.index)):+.2f} |")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "fx_rate_momentum.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

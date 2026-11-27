#!/usr/bin/env python3
"""研究：株価指数の「翌日の値動きの大きさ」を、どの見積もりが最もよく当てるか（建玉の大きさを決めるため）。

- 売られすぎの戻りは、相場が荒れ始めた直後に買うことが多い。直近60日の値動きから建玉を決めると、荒れ始めを見落として建玉が大きくなりすぎる
  （2018年2月5日）。翌日の値動きの大きさ（分散）をもっと正確に見積もれれば、同じ利益で、最悪の日を小さくできる。
- 比べる見積もり（どれも、その日の終値までに分かる値だけを使う）：
  v60     直近60日の日次の値動きの標準偏差（今の形）
  ewma94  指数平滑（RiskMetrics、λ = 0.94）
  ewma85  指数平滑（λ = 0.85。より速い）
  har     HAR 型（Corsi 2009年）：1日・5日・22日の「値幅から計算した分散」（始値・高値・安値・終値を使う Garman–Klass の式に、
          前日終値から始値までの動きを足したもの）の一次式。係数は、過去のデータだけで毎年決め直す
  vix     VIX（NASDAQ100 は VXN）の2乗 ÷ 252。オプションの値段に織り込まれた見積もり
  harvix  har の3つの値に VIX を加えた一次式（係数は同じく毎年決め直す）
- 物差し：翌日の値動きの2乗に対する当てはまり（見ていない期間の R²）、QLIKE（分散の見積もりの標準的な損失。小さいほど良い）、
  売られすぎの信号が2つ以上出ている日だけで見た場合。
使い方: python3 tools/research/index_vol_forecast.py  → reports/research/index_vol_forecast.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import fred_data as F  # noqa: E402
import index_risk as IRK  # noqa: E402

ANN = 252
FIRST = 2000


def daily_var(d):
    """その日の分散の見積もり：前日終値→始値の動きの2乗 + Garman–Klass（始値→終値のあいだ）。"""
    o, h, l, c = np.log(d["open"]), np.log(d["high"]), np.log(d["low"]), np.log(d["close"])
    gk = 0.5 * (h - l) ** 2 - (2 * np.log(2) - 1) * (c - o) ** 2
    on = (o - c.shift(1)) ** 2
    v = (gk.clip(lower=0) + on.fillna(0.0))
    # 始値・高値・安値が終値と同じ日（古いデータ）は、終値どうしの動きの2乗で代用する
    cc = (c - c.shift(1)) ** 2
    bad = (d["high"] <= d["low"]) | v.isna()
    return v.where(~bad, cc)


def walk_forward_ols(X, y, first=FIRST):
    """毎年、前の年までのデータで係数を決め、その年の見積もりを作る。係数はマイナスにしない（見積もりが負にならないように）。"""
    pred = pd.Series(np.nan, index=y.index)
    for yr in range(first, 2027):
        tr = (y.index.year < yr) & X.notna().all(axis=1) & y.notna()
        te = (y.index.year == yr) & X.notna().all(axis=1)
        if tr.sum() < 750 or te.sum() == 0:
            continue
        A = np.column_stack([np.ones(tr.sum()), X[tr].values])
        b, *_ = np.linalg.lstsq(A, y[tr].values, rcond=None)
        b = np.maximum(b, 0.0)
        pred[te] = np.column_stack([np.ones(te.sum()), X[te].values]) @ b
    return pred


def forecasts(name):
    """その指数の、翌日の分散（日次）の見積もりの表と、翌日の値動きの2乗。"""
    d, st, rate, div, vols, above = IRK.load(name)
    r = np.log(d["close"]).diff()
    y = (r ** 2).shift(-1)                                   # 翌日の値動きの2乗
    dv = daily_var(d)
    f = pd.DataFrame(index=d.index)
    f["v60"] = (vols["v60"] ** 2) / ANN
    f["ewma94"] = (r ** 2).ewm(alpha=0.06, adjust=False).mean()
    f["ewma85"] = (r ** 2).ewm(alpha=0.15, adjust=False).mean()
    X = pd.DataFrame({"d": dv, "w": dv.rolling(5).mean(), "m": dv.rolling(22).mean()})
    f["har"] = walk_forward_ols(X, y)
    vx = (vols["vix"] ** 2) / ANN
    f["vix"] = vx
    X2 = X.copy()
    X2["vix"] = vx
    f["harvix"] = walk_forward_ols(X2, y)
    n = st.sum(axis=1)
    return f, y, n


def main():
    lines = ["# 研究：翌日の値動きの大きさの見積もり（`tools/research/index_vol_forecast.py`）", "",
             f"米国3指数、{FIRST}年〜2026年（HAR 型の係数は、前の年までのデータで毎年決め直す）。R² は、翌日の値動きの2乗に対する当てはまり。QLIKE は小さいほど良い。", ""]
    keep = {}
    for name in IRK.US3:
        f, y, n = forecasts(name)
        ok = f.notna().all(axis=1) & y.notna() & (f.index.year >= FIRST)
        lines += [f"## {name}", "", "| 見積もり | すべての日：R² | QLIKE | 信号が2つ以上の日：R² | QLIKE | 見積もり ÷ 実際（2つ以上の日、中央値） |", "|---|---|---|---|---|---|"]
        for k in f.columns:
            row = []
            for mask in (ok, ok & (n >= 2)):
                a, b = f[k][mask].values, y[mask].values
                r2 = 1 - ((b - a) ** 2).sum() / ((b - b.mean()) ** 2).sum()
                ql = np.mean(b / a - np.log(np.maximum(b, 1e-12) / a) - 1)
                row += [f"{r2:+.3f}", f"{ql:.3f}"]
            m2 = ok & (n >= 2)
            ratio = np.median(np.sqrt(f[k][m2].values) / np.maximum(np.abs(np.sqrt(y[m2].values)), 1e-6))
            lines.append(f"| {k} | " + " | ".join(row) + f" | {ratio:.2f} |")
        lines.append("")
        keep[name] = f
        print("\n".join(lines[-(len(f.columns) + 4):]), flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_vol_forecast.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    for name, f in keep.items():
        f.to_parquet(os.path.join(D.CACHE, f"volfc_{IRK.IR.INDEX[name][0]}.parquet"))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""研究：EA が実際に見る日足（CFD の24時間の値段、NY 17:00 区切り）で、「翌日の値動きの大きさ」の見積もりを決める。

- index_vol_forecast.py・index_risk.py（現物の指数、26年）で、HAR 型の見積もり（当日・5日・22日の「値幅から計算した分散」の一次式）で
  建玉を決めると、同じ値動きの大きさで、シャープが上がり、最悪の日が小さくなった。
- EA に入れるには、係数を固定する必要がある。ここでは、**2018年までのデータだけで係数を決めて固定**し、2019年以降の CFD の日足で確かめる：
  cash  現物の指数（S&P500・NASDAQ100・ダウ、1990〜2018年）で決めた係数
  fut   先物（ES・NQ、2000年9月〜2018年。CFD と同じく、ほぼ24時間の足）で決めた係数
  cfd   CFD の日足（S&P500・NASDAQ100、2010年11月〜2018年）で決めた係数
- 確かめ方：
  1 CFD の日足（2019年〜2026年10月）で、翌日の値動きの2乗への当てはまり（R²・QLIKE）。
  2 EA と同じ形（MT5 の日足で判定し、次の足の最初の値段で売買。S&P500 と NASDAQ100、3ルール）の層の成績（2011年9月〜2026年10月、
    値動きを年10%にそろえる）：シャープ、最悪の日、下位1%の日の平均、最大の下落。
使い方: python3 tools/research/index_cfd_sizing.py  → reports/research/index_cfd_sizing.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_reversion_cfd as IC  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_vol_forecast as VF  # noqa: E402
import sleeves as SV  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
FIT_END = "2019-01-01"
CFD = {"S&P500": ("SPXUSD", "USD", 1.5), "NASDAQ100": ("NSXUSD", "USD", 0.7)}
PER = (("2011/9〜14", "2011-09-01", "2015-01-01"), ("2015〜18", "2015-01-01", "2019-01-01"), ("2019〜21/10", "2019-01-01", "2021-11-01"),
       ("21/11〜26/10", "2021-11-01", "2026-12-01"))


def xy(d):
    """HAR の説明の値（当日・5日平均・22日平均の分散）と、翌日の値動きの2乗。"""
    dv = VF.daily_var(d)
    X = pd.DataFrame({"d": dv, "w": dv.rolling(5).mean(), "m": dv.rolling(22).mean()})
    y = (np.log(d["close"]).diff() ** 2).shift(-1)
    return X, y


def fit(frames, end=FIT_END):
    """いくつかの日足をまとめて、係数（定数・当日・5日・22日）を最小二乗で決める。マイナスの係数は 0 にする。"""
    A, b = [], []
    for d in frames:
        X, y = xy(d)
        ok = X.notna().all(axis=1) & y.notna() & (X.index < end)
        A.append(np.column_stack([np.ones(ok.sum()), X[ok].values]))
        b.append(y[ok].values)
    A, b = np.vstack(A), np.concatenate(b)
    co, *_ = np.linalg.lstsq(A, b, rcond=None)
    return np.maximum(co, 0.0), len(b)


def apply(d, co):
    X, _ = xy(d)
    return co[0] + X["d"] * co[1] + X["w"] * co[2] + X["m"] * co[3]


def main():
    cash = [IRK.load(n)[0] for n in IRK.US3]
    fut = [Y.fetch("ES"), Y.fetch("NQ")]
    bars = {n: IC.day_bars(IC.load_any(v[0]), 17) for n, v in CFD.items()}
    cos = {"cash": fit(cash), "fut": fit(fut), "cfd": fit(list(bars.values()))}
    lines = ["# 研究：EA が見る日足（CFD）での、翌日の値動きの大きさの見積もり（`tools/research/index_cfd_sizing.py`）", "",
             "## 係数（2018年までのデータだけで決めて固定）", "",
             "翌日の分散 = 定数 + a × 当日の分散 + b × 5日の平均 + c × 22日の平均（分散は、日足の始値・高値・安値・終値から計算）", "",
             "| 決めたデータ | 件数 | 定数（年率の値動きに直すと） | a（当日） | b（5日） | c（22日） |", "|---|---|---|---|---|---|"]
    lab = {"cash": "現物の指数（3指数、1990〜2018年）", "fut": "先物（ES・NQ、2000〜2018年）", "cfd": "CFD（S&P500・NASDAQ100、2010〜2018年）"}
    for k, (co, n) in cos.items():
        lines.append(f"| {lab[k]} | {n} | {co[0]:.2e}（{np.sqrt(co[0] * ANN) * 100:.1f}%） | {co[1]:.3f} | {co[2]:.3f} | {co[3]:.3f} |")
        print(lines[-1], flush=True)
    # 先物と CFD の「その日の分散」が同じものを測っているか
    dv_c = VF.daily_var(bars["S&P500"])
    dv_f = VF.daily_var(fut[0]).reindex(dv_c.index)
    ok = dv_c.notna() & dv_f.notna()
    lines += ["", f"参考：S&P500 の「その日の分散」は、CFD の日足と先物の日足で、相関 {np.corrcoef(np.sqrt(dv_c[ok]), np.sqrt(dv_f[ok]))[0, 1]:+.3f}、"
              f"平均の比（CFD ÷ 先物）{dv_c[ok].mean() / dv_f[ok].mean():.2f}。", ""]
    print(lines[-2], flush=True)

    # 1 当てはまり（CFD の日足、2019年〜）
    lines += ["## 1 翌日の値動きの2乗への当てはまり（CFD の日足、2019年1月〜2026年10月 = 係数を決めたあとの期間）", "",
              "| 指数 | 見積もり | すべての日：R² | QLIKE | ルールが2つ以上の日：R² | QLIKE |", "|---|---|---|---|---|---|"]
    FC = {}
    for name, d in bars.items():
        r = np.log(d["close"]).diff()
        y = (r ** 2).shift(-1)
        st = IR.rules(d)
        n = st["R2<10"] + st["D7"] + st["IBS"]
        f = pd.DataFrame(index=d.index)
        f["v60"] = r.rolling(60, min_periods=40).var()
        f["ewma94"] = (r ** 2).ewm(alpha=0.06, adjust=False).mean()
        f["ewma85"] = (r ** 2).ewm(alpha=0.15, adjust=False).mean()
        for k, (co, _) in cos.items():
            f[f"har_{k}"] = apply(d, co)
        FC[name] = (d, f, n)
        ok = f.notna().all(axis=1) & y.notna() & (f.index >= FIT_END)
        for k in f.columns:
            cells = []
            for m in (ok, ok & (n >= 2)):
                a, b = f[k][m].values, y[m].values
                cells += [f"{1 - ((b - a) ** 2).sum() / ((b - b.mean()) ** 2).sum():+.3f}", f"{np.mean(b / a - np.log(np.maximum(b, 1e-12) / a) - 1):.3f}"]
            lines.append(f"| {name} | {k} | " + " | ".join(cells) + " |")
            print(lines[-1], flush=True)
    # 2 層の成績（EA と同じ形）
    head = ("| 建玉を決める見積もり | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の月 | 最悪の年 | プラスの年 | " + " | ".join(p[0] for p in PER) + " |")
    lines += ["", "## 2 層の成績（EA と同じ形：MT5 の日足で判定し、次の足の最初の値段で売買。S&P500 と NASDAQ100、3ルール、2011年9月〜2026年10月）", "",
              "ルールの数に比例して持つ（1:2:3）。全期間の値動きを年10%にそろえて比べる。", "", head, "|---|" + "---|" * (8 + len(PER))]
    keep = {}
    for kind, g in (("v60", (0, 1, 2, 3)), ("ewma85", (0, 1, 2, 3)), ("har_cash", (0, 1, 2, 3)), ("har_fut", (0, 1, 2, 3)), ("har_cfd", (0, 1, 2, 3)),
                    ("v60", (0, 0, 1, 2)), ("har_fut", (0, 0, 1, 2))):
        parts = []
        for name, (d, f, n) in FC.items():
            _, ccy, div = CFD[name]
            sig = np.sqrt(f[kind].clip(lower=0) * ANN).clip(lower=0.025)
            gw = n.map({0: g[0], 1: g[1], 2: g[2], 3: g[3]}).astype(float) / float(max(g))
            w = (gw * (0.10 / sig).clip(upper=4.0)).fillna(0.0) / len(FC)
            parts.append(SV.pnl_w(w, d, IR.short_rate(ccy, d.index), div, IR.COST, at_open=True))
        rr = pd.concat(parts, axis=1, sort=True).fillna(0.0).sum(axis=1)
        rr = rr[rr.index >= "2011-09-01"]
        z = rr * (0.10 / (rr.std() * np.sqrt(ANN)))
        sh = z.mean() / z.std() * np.sqrt(ANN)
        eq = (1 + z).cumprod()
        mo = z.groupby(z.index.to_period("M")).sum()
        yr = z.groupby(z.index.year).sum()
        q = z.quantile(0.01)
        label = {"v60": "直近60日（今の EA）", "ewma85": "速い指数平滑（λ = 0.85）", "har_cash": "HAR 型（現物で決めた係数）", "har_fut": "HAR 型（先物で決めた係数）",
                 "har_cfd": "HAR 型（CFD で決めた係数）"}[kind] + ("" if g[1] else "、ルールが2つ以上のときだけ（0:1:2）")
        lines.append(f"| {label} | {sh:+.2f} | {sh * np.sqrt(len(z) / ANN):+.1f} | {z.min() * 100:.1f}%（{z.idxmin().date()}） | {z[z <= q].mean() * 100:.2f}% | "
                     f"{(eq / eq.cummax() - 1).min() * 100:.0f}% | {mo.min() * 100:.1f}% | {yr.min() * 100:.1f}% | {(yr > 0).sum()}/{len(yr)} | "
                     + " | ".join(f"{x.mean() / x.std() * np.sqrt(ANN):+.2f}" for x in (z[(z.index >= a) & (z.index < b)] for _, a, b in PER)) + " |")
        keep[label] = z
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_cfd_sizing.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    pd.DataFrame(keep).to_parquet(os.path.join(D.CACHE, "index_cfd_sizing_returns.parquet"))


if __name__ == "__main__":
    main()

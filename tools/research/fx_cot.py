#!/usr/bin/env python3
"""研究（FX だけで取引する）：投機筋の建玉の偏り（米国 CFTC が毎週公表する COT 報告）から、為替を予想できるか。

- 値動き・日付以外の情報として、通貨先物の「投機筋（非商業）の買い − 売り」を使う。よく言われる使い方は2つ：
  逆張り：投機筋の建玉が、過去3年の中で大きく片寄ったら、逆向きに持つ（片寄りは、いずれ巻き戻される）
  順張り：投機筋の建玉が、この4週間で増えた向きに持つ
- データ：CFTC の公開ファイル（先物のみ、1999年〜）。7通貨（JPY・EUR・GBP・AUD・NZD・CAD・CHF）の対米ドル。
  報告は火曜の時点の建玉で、金曜に公表される。**公表の次の月曜から1週間持つ**（公表前の情報は使わない）。
- 取引は為替だけ（FRED の日次の値）。コスト・スワップ（金利差 − 上乗せ）込み。値動きを年10%にそろえる。
使い方: python3 tools/research/fx_cot.py  → reports/research/fx_cot.md
"""
import io
import os
import subprocess
import sys
import zipfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carry_breadth as CB  # noqa: E402
import fred_data as F  # noqa: E402
import styles_long as SL  # noqa: E402

ANN = 261
DIR = os.path.join(F.ROOT, "data", "cot")
NAMES = {"JPY": "JAPANESE YEN", "EUR": "EURO FX", "GBP": "BRITISH POUND", "AUD": "AUSTRALIAN DOLLAR", "NZD": "NEW ZEALAND DOLLAR", "NZD2": "NZ DOLLAR",
         "CAD": "CANADIAN DOLLAR", "CHF": "SWISS FRANC"}


def load_cot():
    os.makedirs(DIR, exist_ok=True)
    cache = os.path.join(DIR, "cot_fx.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    rows = []
    for y in range(1999, 2027):
        z = os.path.join(DIR, f"deacot{y}.zip")
        if not os.path.exists(z) or os.path.getsize(z) < 10000:
            subprocess.run(["curl", "-sS", "-m", "120", "-A", "Mozilla/5.0", "-o", z, f"https://www.cftc.gov/files/dea/history/deacot{y}.zip"], check=False)
        try:
            with zipfile.ZipFile(z) as zf:
                df = pd.read_csv(io.BytesIO(zf.read(zf.namelist()[0])), low_memory=False)
        except Exception as e:  # noqa: BLE001
            print(y, "読めません", e)
            continue
        df.columns = [c.strip() for c in df.columns]
        name = df["Market and Exchange Names"].astype(str).str.upper()
        date = pd.to_datetime(df["As of Date in Form YYYY-MM-DD"])
        for c, key in NAMES.items():
            m = name.str.startswith(key) & name.str.contains("CHICAGO MERCANTILE") & ~name.str.contains("E-MINI|MICRO|CROSS|/")
            if not m.any():
                continue
            x = df[m]
            rows.append(pd.DataFrame({"date": date[m].values, "ccy": c[:3], "oi": x["Open Interest (All)"].values,
                                      "ncl": x["Noncommercial Positions-Long (All)"].values, "ncs": x["Noncommercial Positions-Short (All)"].values}))
    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["ccy", "date", "oi"]).drop_duplicates(["ccy", "date"], keep="last")
    out.to_parquet(cache)
    return out


def main():
    cot = load_cot()
    net = (cot.assign(net=(cot["ncl"] - cot["ncs"]) / cot["oi"]).pivot(index="date", columns="ccy", values="net")).sort_index()
    v, rate = CB.load()
    ccys = [c for c in ["JPY", "EUR", "GBP", "AUD", "NZD", "CAD", "CHF"] if c in net.columns]
    z = (net - net.rolling(156, min_periods=104).mean()) / net.rolling(156, min_periods=104).std()
    sig = {"逆張り（片寄りの大きさに比例。過去3年の中での位置）": -(z / 2.0).clip(-1, 1),
           "逆張り（片寄りが 1.5σ を超えた通貨だけ）": -np.sign(z).where(z.abs() > 1.5, 0.0),
           "順張り（この4週間で建玉が増えた向き）": np.sign(net.diff(4)),
           "順張り（投機筋の建玉の向きそのもの）": np.sign(net)}
    lines = ["# 研究：投機筋の建玉の偏り（COT 報告）から、為替を予想できるか（取引は為替だけ。`tools/research/fx_cot.py`）", "",
             f"7通貨の対米ドル。報告（火曜の時点、{net.index[0].date()}〜{net.index[-1].date()}）の公表の次の月曜から1週間持つ。コスト・スワップ込み。期間ごとの列は年率シャープ。", "",
             "| 形 | " + " | ".join(p[0] for p in SL.PER) + " | 全体（2002年〜） | t 値 | プラスの年 |", "|---|" + "---|" * (len(SL.PER) + 3)]
    ret = v[ccys].pct_change().shift(-1)
    vol = v[ccys].pct_change().rolling(60, min_periods=40).std() * np.sqrt(ANN)
    for name, s in sig.items():
        s = s[ccys].copy()
        s.index = s.index + pd.Timedelta(days=6)              # 火曜の建玉 → 金曜に公表 → 次の月曜から使う
        w = s.reindex(s.index.union(v.index)).ffill(limit=7).reindex(v.index).fillna(0.0)
        w = w * (0.10 / vol).clip(upper=4.0).fillna(0.0) / len(ccys)
        diff = rate[ccys].sub(rate["USD"], axis=0)
        carry = ((w * diff).sum(axis=1) - (w.abs() * 1.0).sum(axis=1)) / 100.0 / ANN
        tc = ((w - w.shift(1).fillna(0.0)).abs() * pd.Series({c: CB.COST_CCY[c] + CB.COST_CCY["USD"] for c in ccys})).sum(axis=1)
        r = ((w * ret).sum(axis=1) + carry - tc).fillna(0.0)
        cells = [f"{SL.sharpe(r[(r.index >= a) & (r.index < b)]):+.2f}" for _, a, b in SL.PER]
        x = r[r.index >= "2002-01-01"]
        yr = x.groupby(x.index.year).sum()
        s_ = SL.sharpe(x)
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {s_:+.2f} | {s_ * np.sqrt(len(x) / ANN):+.1f} | {(yr > 0).sum()}/{len(yr)} |")
    out = os.path.join(F.ROOT, "reports", "research", "fx_cot.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

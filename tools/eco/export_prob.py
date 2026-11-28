#!/usr/bin/env python3
"""複合システム：EA の「確率の層」に渡す予想のファイルを作る（検証用。学習に使っていない年の予想だけ）。

- 入力：data/eco/preds_<版>_ens.parquet（tools/eco/evaluate.py が、合成した確率を足して保存したもの）
- 出力：MQL5/Files/AMS_prob_<版>_<エンジン>.csv。行は「日付(yyyy.MM.dd),銘柄,確率,z」。銘柄は OANDA の指数の CFD（名前の頭の CFD_ を外したもの）。
  日付は、その予想に使った日足（確定した最後の日足）の日付。EA は、その日足の次の日足が始まったときに、この行を読んで建玉を合わせる。
- z ＝（確率 − ふだんの水準）÷ ばらつき を ±2 で打ち切ったもの。水準とばらつきは、前の年までの指数の予想から計算する（evaluate.py の zscore と同じ）。
  つまり、どの行も、その日までに分かっていたことだけで作られている。
- あわせて、EA と同じ形（毎日、z に比例した大きさに合わせる・買いだけ・コスト込み）で計算した資産の動きを出す。MT5 のテスターの結果と突き合わせるため。
使い方: python3 tools/eco/export_prob.py v2 hedge [開始日 終了日 単位]
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402
import evaluate as EV  # noqa: E402


def load(ver):
    P = pd.read_parquet(os.path.join(DS.CACHE, f"preds_{ver}_ens.parquet"))
    P["date"] = pd.to_datetime(P["date"])
    return P.sort_values(["date", "inst"]).reset_index(drop=True)


def export(ver, engine, since="2017-01-01"):
    P = load(ver)
    col = "p_" + engine
    z = EV.zscore(P, col)
    m = P["inst"].str.startswith("CFD_").values & ~np.isnan(z) & (P["date"] >= since).values
    out = pd.DataFrame({"date": P.loc[m, "date"].dt.strftime("%Y.%m.%d"), "symbol": P.loc[m, "inst"].str[4:], "p": P.loc[m, col].round(4), "z": np.round(z[m], 3)})
    dst = os.path.join(DS.F.ROOT, "MQL5", "Files", f"AMS_prob_{ver}_{engine}.csv")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    out.to_csv(dst, index=False, lineterminator="\n")
    return dst, len(out), P.assign(z=z)


def mimic(P, syms, start, end, unit, long_only=True, swap_long=-4.79, spread=0.0001):
    """EA と同じ形の計算（毎日そろえる・帯なし・丸めなし）。戻り値：資産の動き（1 から）。"""
    g = P[P["inst"].isin(["CFD_" + s for s in syms]) & (P["date"] >= start) & (P["date"] <= end)].copy()
    z = g["z"].clip(lower=0) if long_only else g["z"]
    g["w"] = (z * unit / 100.0 / np.maximum(g["sig"] * np.sqrt(252), 0.025)).fillna(0.0)
    prev = g.groupby("inst")["w"].shift(1).fillna(0.0)
    g["r"] = g["w"] * g["r_next"] - (g["w"] - prev).abs() * spread + g["w"].clip(lower=0) * swap_long / 100.0 / 360.0 * 1.45
    r = g.groupby("date")["r"].sum()
    return (1.0 + r).cumprod()


def main():
    ver = sys.argv[1] if len(sys.argv) > 1 else "v2"
    engine = sys.argv[2] if len(sys.argv) > 2 else "hedge"
    dst, n, P = export(ver, engine)
    print(f"{dst}: {n} 行")
    if len(sys.argv) > 5:
        start, end, unit = sys.argv[3], sys.argv[4], float(sys.argv[5])
        for syms in (("US500", "US100", "US30"), ("US500", "US100", "US30", "JP225")):
            e = mimic(P, syms, start, end, unit)
            dd = (e / e.cummax() - 1).min()
            mth = e.resample("ME").last().pct_change().dropna()
            print(f"{'・'.join(syms)}、単位 {unit:g}%、{start}〜{end}：{(e.iloc[-1] - 1) * 100:+.1f}%、最大の下落 {dd * 100:.1f}%、プラスの月 {int((mth > 0).sum())} / {len(mth)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""複合システム：指標ごとの成績表（その指標の値と、次の日の値動きとの関係）。日付・時刻・曜日は使わない。

- 目的：よく使われる指標（移動平均・RSI・MACD・一目均衡表・ボリンジャーバンド、TradingView で広く使われている SuperTrend・UT Bot・
  Squeeze Momentum・WaveTrend・QQE・SSL・Hull など）を、1つずつ数値にして、「その値が高い日の次の日は上がりやすいか」を同じ物差しで測る。
  モデルに入れる前に、どの指標に予想の力があり、どれにないかを見えるようにする。
- 測り方：指標の値と、次の日の値動き（値動きの大きさ＝1）の相関。t 値は「その日の全銘柄の平均」を1つの観測として計算する
  （同じ日の銘柄どうしは一緒に動くので、行の数で数えると t 値が大きく出すぎる）。2005年〜。OANDA の CFD と ETF の行は、同じ指数の重複になるので除く。
- 読み方：相関がプラスなら「値が高いほど、次の日は上がりやすい」（流れに乗る指標として効く）、マイナスなら「値が高いほど、次の日は下がりやすい」
  （行きすぎの戻りとして効く）。80 個以上を一度に見ているので、|t| が 3 未満のものは偶然と区別できない。
- これは説明のための表で、売買の判定には使わない（モデルは、毎年、その年より前のデータだけで学習する。tools/eco/ml2.py）。
使い方: python3 tools/eco/scoreboard.py  → reports/eco/indicators.md
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402

DESC = {
    "ret1": "1日の値動き", "ret2": "2日の値動き", "ret3": "3日の値動き", "ret5": "5日の値動き", "ret10": "10日の値動き", "ret20": "20日の値動き",
    "ret60": "60日の値動き", "ret120": "120日の値動き", "ret250": "250日の値動き",
    "ma5": "5日の平均からの離れ", "ma10": "10日の平均からの離れ", "ma20": "20日の平均からの離れ", "ma50": "50日の平均からの離れ",
    "ma100": "100日の平均からの離れ", "ma200": "200日の平均からの離れ", "above200": "200日の平均より上か", "ma50_200": "50日と200日の平均の位置（ゴールデンクロス）",
    "rsi2": "RSI（2日）", "rsi5": "RSI（5日）", "rsi14": "RSI（14日）", "stoch_k": "ストキャスティクス %K", "stoch_d": "ストキャスティクス %D",
    "stochrsi": "ストキャスティクス RSI", "willr": "ウィリアムズ %R", "cci": "CCI", "macd": "MACD", "macd_hist": "MACD のヒストグラム", "tsi": "TSI",
    "ao": "オーサム・オシレーター", "fisher": "フィッシャー変換", "wt1": "WaveTrend（TradingView）", "wt_cross": "WaveTrend の交差", "qqe": "QQE（TradingView）",
    "qqe_dist": "QQE の線からの離れ", "adx": "ADX（流れの強さ）", "di_diff": "+DI − −DI", "aroon": "アルーン", "supertrend": "SuperTrend の向き（TradingView）",
    "supertrend_dist": "SuperTrend の線からの離れ", "utbot": "UT Bot の向き（TradingView）", "chandelier": "シャンデリア・エグジットの向き",
    "chandelier_dist": "シャンデリア・エグジットの線からの離れ", "psar": "パラボリック SAR の向き", "psar_dist": "パラボリック SAR からの離れ",
    "ssl": "SSL チャネルの向き（TradingView）", "hull_slope": "ハル移動平均の傾き", "hull_dist": "ハル移動平均からの離れ",
    "ichi_tk": "一目：転換線 − 基準線", "ichi_kijun": "一目：基準線からの離れ", "ichi_cloud": "一目：雲の上か下か", "ichi_cloud_dist": "一目：雲からの離れ",
    "ichi_chikou": "一目：遅行スパン", "donch20": "20日の高値・安値の中の位置（ドンチャン）", "donch55": "55日の高値・安値の中の位置（タートル）",
    "heikin_streak": "平均足の連続", "bb_pos": "ボリンジャーバンドの中の位置", "bb_width": "ボリンジャーバンドの幅", "kc_pos": "ケルトナー・チャネルの中の位置",
    "squeeze_on": "スクイーズ（値動きの縮み）", "squeeze_mom": "Squeeze Momentum（TradingView）", "atr_ratio": "ATR の比（短期 ÷ 長期）",
    "vol_5_60": "値動きの大きさ：5日 ÷ 60日", "vol_20_250": "値動きの大きさ：20日 ÷ 250日", "range_today": "その日の値幅の大きさ", "gap": "窓（前の終値 → 始値）",
    "ibs": "IBS（その日の値幅の中の終値の位置）", "body": "ローソク足の実体", "upper_wick": "上ひげ", "lower_wick": "下ひげ", "streak": "続けて上げた・下げた日数",
    "dd250": "250日の高値からの下落", "dd20": "20日の高値からの下落", "up20": "20日の安値からの上昇", "pivot": "ピボットからの離れ",
    "rule_r2": "ルール：RSI（2日）が 10 未満", "rule_d7": "ルール：7日の安値", "rule_ibs": "ルール：IBS が低い", "rule_n": "上の3つのルールの数",
    "st_r2": "いまの層：R2 を持っている", "st_d7": "いまの層：D7 を持っている", "st_ibs": "いまの層：IBS を持っている", "st_n": "いまの層：持っているルールの数",
    "vix_rank": "VIX の位置（過去250日の中）", "vix_chg1": "VIX の1日の変化", "vix_chg5": "VIX の5日の変化",
}


def tcorr(g, col):
    x = g[col].astype(float)
    ok = x.notna() & g["y"].notna()
    x, y, d = x[ok], g["y"][ok], g["date"][ok]
    if len(x) < 2000 or x.std() == 0:
        return np.nan, np.nan
    z = ((x - x.mean()) / x.std()).clip(-5, 5)
    dd = (z * y).groupby(d).mean()
    return float(np.corrcoef(z, y)[0, 1]), float(dd.mean() / dd.std() * np.sqrt(len(dd)))


def main():
    rows, _ = DS.build()
    rows = rows[(rows["date"] >= "2005-01-01") & ~rows["inst"].str.startswith("CFD_")]
    cols = [c for c in DS.feature_cols() if not c.startswith("is_")]
    out = []
    for c in cols:
        r = dict(name=c)
        for kl in ("index", "fx", "metal"):
            g = rows[rows["klass"] == kl]
            r[kl + "_c"], r[kl + "_t"] = tcorr(g, c)
            if kl == "index":
                _, r["t1"] = tcorr(g[g["date"] < "2016-01-01"], c)
                _, r["t2"] = tcorr(g[g["date"] >= "2016-01-01"], c)
        out.append(r)
    T = pd.DataFrame(out).sort_values("index_t", key=lambda s: -s.abs())
    f = lambda c, t: "—" if np.isnan(t) else f"{c:+.3f}・{t:+.1f}"   # noqa: E731
    L = ["# 複合システム：指標ごとの成績表（`tools/eco/scoreboard.py`）", "",
         f"2005年〜、現物の指数 11・為替 17・金属 3。数字は「相関・t 値」。相関がプラス＝値が高いほど次の日は上がりやすい、マイナス＝値が高いほど次の日は下がりやすい。", "",
         "| 指標 | 指数：相関・t | うち 2005〜15年の t | 2016年〜の t | 為替：相関・t | 金属：相関・t |", "|---|---|---|---|---|---|"]
    for _, r in T.iterrows():
        L.append(f"| {DESC.get(r['name'], r['name'])}（`{r['name']}`） | {f(r.index_c, r.index_t)} | {r.t1:+.1f} | {r.t2:+.1f} | {f(r.fx_c, r.fx_t)} | {f(r.metal_c, r.metal_t)} |")
    n3 = {k: int((T[k + "_t"].abs() >= 3).sum()) for k in ("index", "fx", "metal")}
    both = int(((T["t1"].abs() >= 2) & (T["t2"].abs() >= 2) & (np.sign(T["t1"]) == np.sign(T["t2"]))).sum())
    pos = T[(T["index_t"] >= 3)]["name"].tolist()
    neg = T[(T["index_t"] <= -3)]["name"].tolist()
    L += ["", "## まとめ", "",
          f"- |t| が 3 以上の指標の数（{len(T)} 個のうち）：指数 {n3['index']}、為替 {n3['fx']}、金属 {n3['metal']}。",
          f"- 指数で、前半（2005〜15年）と後半（2016年〜）の両方で同じ向きに |t| ≥ 2 だった指標：{both} 個。",
          f"- 指数で、はっきりマイナス（値が高いほど次の日は下がりやすい＝行きすぎの戻り）：{'、'.join(DESC.get(x, x) for x in neg) or 'なし'}。",
          f"- 指数で、はっきりプラス：{'、'.join(DESC.get(x, x) for x in pos) or 'なし'}。"]
    os.makedirs(os.path.join(DS.F.ROOT, "reports", "eco"), exist_ok=True)
    open(os.path.join(DS.F.ROOT, "reports", "eco", "indicators.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:30]))
    print("\n".join(L[-6:]))


if __name__ == "__main__":
    main()

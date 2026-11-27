#!/usr/bin/env python3
"""研究：米国以外の株価指数でも、売られすぎの戻り（R2・D7・IBS）は成り立つか（101章）。

- データ：OANDA の株価指数の口座の、実際の CFD の日足（14銘柄、2016年〜。観察モード＝注文なしで書き出したもの。リポジトリには入れていない）。
  EA が実際に見る足（サーバーの日付の区切り = NY 17時）と同じ。
- ルールは公表されたまま（数値は変えない）。形は EA と同じ：重み 1:2:4、HAR 型の値動きの見積もり、逆指値 4×σ（その日の始値から）、VIX の倍率。
  売買は次の日足の始値。コスト：スプレッド（書き出した時点の値。往復で1回分）と、スワップ（銘柄ごとの買いの年率。持ち越した日数分。週末は3日分として計算）。
  配当相当額（買いの建玉に付く）は入れていない（少し厳しめ）。
- 事前に決めた基準（結果を見る前に決めた）。ある指数を EA に足すのは、次の3つをすべて満たすときだけ：
   (a) その指数だけの層（コスト後）の t 値が 2.0 以上（全期間）
   (b) 前半・後半（期間を半分に分ける）の両方でプラス
   (c) 米国の3指数の層に、4つ目として足したとき、シャープが前半・後半の両方で上がる
  候補は 11 あるので、たまたま (a) を満たす指数が 0.25 個ほど出る計算になる（基準を満たしても、すぐには信用しない）。
使い方: python3 -I tools/research/index_others.py <書き出したファイルのフォルダ>  → reports/research/index_others.md
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

ANN = 252
W = {0: 0.0, 1: 0.25, 2: 0.5, 3: 1.0}             # 重み 1:2:4（3つそろったときを 1 とする）
US3 = ("US500", "US100", "US30")
NAMES = {"US500": "S&P500", "US100": "NASDAQ100", "US30": "ダウ", "US2000": "ラッセル2000", "JP225": "日経225", "GER30": "ドイツ（DAX）", "UK100": "英国（FTSE100）",
         "EU50": "欧州50", "FRA40": "フランス（CAC40）", "NL25": "オランダ（AEX）", "AUS200": "オーストラリア", "HK50": "香港（ハンセン）", "CHINA50": "中国A50",
         "SING30": "シンガポール"}


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 60 and x.std() > 0 else np.nan


def tval(x):
    return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 60 and x.std() > 0 else np.nan


def load(folder):
    props = pd.read_csv(os.path.join(folder, "AMS_ix_symbols.csv")).drop_duplicates("symbol", keep="last").set_index("symbol")
    out = {}
    for sym in props.index:
        f = os.path.join(folder, f"AMS_d1_{sym}.csv")
        if not os.path.exists(f):
            continue
        d = pd.read_csv(f)
        d.index = pd.to_datetime(d["date"], format="%Y.%m.%d")
        d = d[["open", "high", "low", "close"]].astype(float)
        d = d[d.index.dayofweek < 5].iloc[:-1]                 # 土日の日付の足（あれば）と、作りかけの最後の足を除く
        out[sym] = d
    return out, props


def sleeve(d, sym, props, use_vix=True, only=None):
    """その指数だけの層の日次の損益（口座に対する割合。値動きは、ルール3つのとき年10%になる大きさ）。only：ルールを1つだけ使う。"""
    st = IR.rules(d)
    sg = IS.har_sigma(d)
    if only is None:
        n = st["R2<10"] + st["D7"] + st["IBS"]
        base = n.map(lambda v: W[int(round(v))])
    else:
        base = st[only]
    vm = V.mult_of(V.vix_rank(d.index)[0], (0.5, 1.0, 1.5)) if use_vix else 1.0
    w = (base * vm * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
    spread = float(props.loc[sym, "spread_points"]) * float(props.loc[sym, "point"]) / float(props.loc[sym, "bid"])
    swap = -float(props.loc[sym, "swap_long"])                 # 年 %（プラスの数にする）
    keep = IR.COST
    IR.COST = spread / 2.0                                      # 片道。往復でスプレッド1回分
    try:
        r, stops, _ = IS.run(d, w, sg, pd.Series(swap - IR.MARKUP, index=d.index), 0.0, 4.0, "open")
    finally:
        IR.COST = keep
    return r, w, spread, swap


def main():
    folder = sys.argv[1]
    data, props = load(folder)
    first = max(d.index[0] for d in data.values()) + pd.Timedelta(days=320)        # 200日の平均と助走のあと
    last = min(d.index[-1] for d in data.values())
    mid = first + (last - first) / 2
    lines = ["# 研究：米国以外の株価指数での、売られすぎの戻り（`tools/research/index_others.py`）", "",
             f"OANDA の株価指数の口座の、実際の CFD の日足。成績を測る期間は {first.date()}〜{last.date()}（前半は {mid.date()} まで）。コスト（スプレッド・スワップ）込み。", "",
             "## 指数ごと：その指数だけの層（EA と同じ形。重み 1:2:4・HAR 型・逆指値 4×σ・VIX の倍率）", "",
             "| 指数 | スプレッド（値段に対する %） | 買いのスワップ（年） | シャープ | t 値 | 前半 | 後半 | 持つ日の割合 | VIX の倍率なし：シャープ・t 値 | ルールごとの t 値（R2・D7・IBS） | 米国3指数の層との相関 |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    res, rets = {}, {}
    for sym, d in data.items():
        r, w, spread, swap = sleeve(d, sym, props)
        r = r[(r.index >= first) & (r.index <= last)]
        rets[sym] = r
        r0, _, _, _ = sleeve(d, sym, props, use_vix=False)
        r0 = r0[(r0.index >= first) & (r0.index <= last)]
        tv = []
        for key in ("R2<10", "D7", "IBS"):
            rk, _, _, _ = sleeve(d, sym, props, use_vix=False, only=key)
            tv.append(tval(rk[(rk.index >= first) & (rk.index <= last)]))
        res[sym] = dict(spread=spread, swap=swap, sh=sh(r), t=tval(r), h1=sh(r[r.index <= mid]), h2=sh(r[r.index > mid]),
                        hold=(w[(w.index >= first) & (w.index <= last)] > 0).mean(), sh0=sh(r0), t0=tval(r0), tv=tv)
    us = pd.concat([rets[s] for s in US3], axis=1, sort=True).fillna(0.0).sum(axis=1) / 3.0
    for sym in data:
        x = res[sym]
        c = "—" if sym in US3 else f"{pd.concat([rets[sym], us], axis=1, sort=True).fillna(0.0).corr().iloc[0, 1]:+.2f}"
        lines.append(f"| {NAMES.get(sym, sym)}（{sym}） | {x['spread'] * 100:.3f}% | −{x['swap']:.2f}% | {x['sh']:+.2f} | {x['t']:+.1f} | {x['h1']:+.2f} | {x['h2']:+.2f} | {x['hold'] * 100:.0f}% | "
                     f"{x['sh0']:+.2f}・{x['t0']:+.1f} | {x['tv'][0]:+.1f}・{x['tv'][1]:+.1f}・{x['tv'][2]:+.1f} | {c} |")
        print(lines[-1], flush=True)
    # 米国3指数の層に、4つ目として足す
    lines += ["", "## 米国の3指数の層に、4つ目として足した場合（4銘柄を同じ重みで持つ）", "",
              f"米国の3指数だけ：シャープ {sh(us):+.2f}（前半 {sh(us[us.index <= mid]):+.2f}、後半 {sh(us[us.index > mid]):+.2f}）", "",
              "| 足す指数 | 全期間 | 前半 | 後半 | (a) t 値 ≥ 2 | (b) 前半・後半ともプラス | (c) 足して前半・後半とも上がる | 判定 |", "|---|---|---|---|---|---|---|---|"]
    base = (sh(us), sh(us[us.index <= mid]), sh(us[us.index > mid]))
    passed = []
    for sym in data:
        if sym in US3:
            continue
        cmb = pd.concat([rets[s] for s in US3] + [rets[sym]], axis=1, sort=True).fillna(0.0).sum(axis=1) / 4.0
        v = (sh(cmb), sh(cmb[cmb.index <= mid]), sh(cmb[cmb.index > mid]))
        a = res[sym]["t"] >= 2.0
        b = res[sym]["h1"] > 0 and res[sym]["h2"] > 0
        c = v[1] > base[1] and v[2] > base[2]
        ok = a and b and c
        if ok:
            passed.append(sym)
        lines.append(f"| {NAMES.get(sym, sym)}（{sym}） | {v[0]:+.2f} | {v[1]:+.2f} | {v[2]:+.2f} | {'○' if a else '×'} | {'○' if b else '×'} | {'○' if c else '×'} | {'**合格**' if ok else '不合格'} |")
        print(lines[-1], flush=True)
    # すべての候補を足した場合・合格だけを足した場合
    others = [s for s in data if s not in US3]
    allc = pd.concat([rets[s] for s in data], axis=1, sort=True).fillna(0.0).sum(axis=1) / len(data)
    lines += ["", f"- 14 指数すべてを同じ重みで持った場合：シャープ {sh(allc):+.2f}（前半 {sh(allc[allc.index <= mid]):+.2f}、後半 {sh(allc[allc.index > mid]):+.2f}）",
              f"- 米国以外の 11 指数だけ：シャープ {sh(pd.concat([rets[s] for s in others], axis=1, sort=True).fillna(0.0).sum(axis=1)):+.2f}"]
    if passed:
        cmb = pd.concat([rets[s] for s in list(US3) + passed], axis=1, sort=True).fillna(0.0).sum(axis=1) / (3 + len(passed))
        lines.append(f"- 基準を満たした指数（{'、'.join(passed)}）を足した場合：シャープ {sh(cmb):+.2f}（前半 {sh(cmb[cmb.index <= mid]):+.2f}、後半 {sh(cmb[cmb.index > mid]):+.2f}）")
    else:
        lines.append("- 基準を3つとも満たした指数は、ありませんでした。")
    out = os.path.join(F.ROOT, "reports", "research", "index_others.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""研究（FX だけで取引する）：金利差の層を、OANDA で取引できるほかの通貨に広げると、崩れにくくなるか。日付・曜日は使わない。

- いまの17ペアは、8通貨（USD・JPY・EUR・GBP・AUD・NZD・CAD・CHF）の組み合わせ。OANDA には、ほかに
  ノルウェークローネ（NOK）・スウェーデンクローナ（SEK）・メキシコペソ（MXN）・南アフリカランド（ZAR）・中国人民元（CNH）・トルコリラ（TRY）のペアがある。
  金利差の取引は「互いに無関係な通貨の数」が多いほど安定する、とされる（通貨ごとの偶然の値動きが打ち消し合うため）。
- 通貨ごとに考える：各通貨を対米ドルで持つ（買い = その通貨の金利を受け取り、米ドルの金利を払う）。
  毎週、金利が「全体の真ん中」より高い通貨を買い、低い通貨を売る。重みは、値動きの大きさで割ってそろえ、買いの合計と売りの合計を同じにする
  （米ドルそのものの上げ下げは打ち消す）。全体は、建玉から見積もった値動きで年10%にそろえる。
- データ：FRED の日次の為替（NY 正午）と月次の短期金利（1か月遅れで使う）。TRY の為替は Yahoo Finance、金利は翌日物。
  CNH は、本土の人民元（CNY）の値と金利で代用する。
- コスト：スプレッド（対米ドルのペアの OANDA の実際の値。主要通貨は S.COST + 0.5 pips）、スワップの上乗せ（通貨ごとに年 MARKUP %。払う側に寄せる）。
使い方: python3 tools/research/carry_breadth.py  → reports/research/carry_breadth.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import fred_data as F  # noqa: E402
import styles_long as SL  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 261
G8 = ["JPY", "EUR", "GBP", "AUD", "NZD", "CAD", "CHF"]                 # 米ドル以外（米ドルは基準）
FX_EXT = {"NOK": "DEXNOUS", "SEK": "DEXSDUS", "MXN": "DEXMXUS", "ZAR": "DEXSFUS", "CNH": "DEXCHUS"}   # 1米ドルあたりの値
RATE_EXT = {"NOK": "IR3TIB01NOM156N", "SEK": "IR3TIB01SEM156N", "MXN": "IR3TIB01MXM156N", "ZAR": "IR3TIB01ZAM156N",
            "CNH": "IR3TIB01CNM156N", "TRY": "IRSTCI01TRM156N"}
# 売買のコストと、スワップの上乗せは「通貨ごと」に置く。ペア（2つの通貨の組）を1回売買すると、2つの通貨の分がかかる。
#   例：AUDJPY を売買 → AUD の分 + JPY の分。主要通貨どうしのペアのスプレッド（約 0.9 pips = 0.008%）が、通貨ごと 0.004% × 2 になるように置く。
#   それ以外の通貨は、OANDA の履歴のスプレッドの中央値（data/cache/oanda_spreads.csv、2024年11月〜。相手が米ドルか円のペア）から、相手の分 0.004% を引き、2割を足した値。
COST_CCY = {c: 0.00004 for c in G8 + ["USD"]}
COST_CCY.update({"NOK": (0.00042 - 0.00004) * 1.2, "SEK": (0.00040 - 0.00004) * 1.2, "MXN": (0.00019 - 0.00004) * 1.2,
                 "ZAR": (0.00104 - 0.00004) * 1.2, "CNH": (0.000135 - 0.00004) * 1.2, "TRY": 0.0030})
# スワップの上乗せ（年 %、通貨ごと。ペアでは2つの通貨の合計）。主要通貨どうしのペアで年1%（これまでの検証と同じ）になるように、通貨ごと 0.5%。
# それ以外の通貨は、OANDA の実際のスワップから見積もる（下の calibrate_markup）。見積もれないときの置き方：
MARKUP = {c: 0.5 for c in G8 + ["USD"]}
MARKUP.update({"NOK": 1.0, "SEK": 1.0, "MXN": 1.5, "ZAR": 2.0, "CNH": 1.0, "TRY": 8.0})
UNIVERSES = (("いまの8通貨", G8), ("＋北欧（NOK・SEK）", G8 + ["NOK", "SEK"]), ("＋メキシコ・南ア（MXN・ZAR）", G8 + ["NOK", "SEK", "MXN", "ZAR"]),
             ("＋人民元（CNH）", G8 + ["NOK", "SEK", "MXN", "ZAR", "CNH"]), ("＋トルコ（TRY）", G8 + ["NOK", "SEK", "MXN", "ZAR", "CNH", "TRY"]))


def load(start="1999-01-01"):
    """各通貨の米ドルでの値（1通貨 = 何米ドル）と、金利（年 %、日次、1か月遅れ）。"""
    v = F.usd_value()
    for c, sid in FX_EXT.items():
        v[c] = 1.0 / F.fetch(sid).dropna()
    t = Y.fetch_ticker("TRY", "TRY=X")["close"]
    t = t[(t > 0.5) & (t.pct_change().abs().fillna(0) < 0.3)]
    v["TRY"] = 1.0 / t.reindex(v.index.union(t.index)).reindex(v.index)
    v = v[v.index >= start]
    v = v[v.index.dayofweek < 5].ffill(limit=3)
    m = F.rates_monthly()
    for c, sid in RATE_EXT.items():
        m[c] = F.fetch(sid)
    m = m.ffill()
    rate = F.monthly_to_daily(m, v.index)
    return v, rate


def weights(v, rate, ccys, mode="rank", trend=None, thr=0.0):
    """通貨ごとの重み。米ドルも1つの通貨として数える（N = len(ccys) + 1）。重みの合計は 0（買いの合計 0.5、売りの合計 0.5）。
    返すのは、すべての通貨（米ドルを含む）の重み。米ドル以外の重みが、そのまま対米ドルの建玉になる。
    mode="rank"：金利の順位に比例（真ん中が 0、最高が +1、最低が −1）。mode="median"：真ん中より上は +1、下は −1。
    thr：金利が真ん中から thr（年 %）以上離れていない通貨は持たない。"""
    allc = ccys + ["USD"]
    r = rate[allc]
    ret = v[ccys].pct_change()
    dollar = -ret.mean(axis=1)                               # 米ドルの、ほかの通貨の平均に対する値動き
    vol = ret.rolling(60, min_periods=40).std()
    vol["USD"] = dollar.rolling(60, min_periods=40).std()
    ok = v[ccys].notna() & vol[ccys].notna() & r[ccys].notna()
    ok["USD"] = vol["USD"].notna()
    rr = r.where(ok)
    mid = rr.median(axis=1)
    if mode == "median":
        sig = np.sign(rr.sub(mid, axis=0))
    else:
        n = rr.notna().sum(axis=1)
        sig = rr.rank(axis=1).sub((n + 1) / 2.0, axis=0).div(((n - 1) / 2.0).replace(0, np.nan), axis=0)
    if thr > 0:
        sig = sig.where(rr.sub(mid, axis=0).abs() >= thr, 0.0)
    if trend:
        # その通貨の、通貨全体の平均に対する過去 trend 日の値動きが、同じ向きのときだけ持つ
        rel = ret.add(dollar, axis=0)
        rel["USD"] = dollar
        mom = rel.rolling(trend, min_periods=trend // 2).sum()
        sig = sig.where(np.sign(mom) == np.sign(sig), 0.0)
    w = (sig / vol[allc]).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    lo, sh = w.clip(lower=0), w.clip(upper=0)
    lo = lo.div(lo.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0) * 0.5
    sh = sh.div(sh.abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0) * 0.5
    both = (lo.sum(axis=1) > 0) & (sh.abs().sum(axis=1) > 0)
    return (lo + sh).where(both, 0.0)


def pnl(w, v, rate):
    """通貨の重み w（米ドルを含む、合計 0）の日次の損益。金利 − 上乗せ、売買のコスト込み。"""
    allc = list(w.columns)
    ccys = [c for c in allc if c != "USD"]
    ret = v[ccys].pct_change().shift(-1)
    mk = pd.Series({c: MARKUP[c] for c in allc})
    cc = pd.Series({c: COST_CCY[c] for c in allc})
    carry = ((w * rate[allc]).sum(axis=1) - (w.abs() * mk).sum(axis=1)) / 100.0 / ANN
    tc = ((w - w.shift(1).fillna(0.0)).abs() * cc).sum(axis=1)
    return ((w[ccys] * ret).sum(axis=1) + carry - tc).fillna(0.0)


def exante(w, v, target=0.10, cap=6.0, win=60):
    ccys = [c for c in w.columns if c != "USD"]
    R = v[ccys].pct_change().fillna(0.0).values
    W = w[ccys].values
    out = np.zeros(len(w))
    for t in range(win, len(w)):
        wt = W[t]
        if not wt.any():
            continue
        sd = (R[t - win + 1:t + 1] @ wt).std()
        if sd > 0:
            out[t] = min(target / (sd * np.sqrt(ANN)), cap)
    return pd.Series(out, index=w.index)


def run(v, rate, ccys, **kw):
    w0 = weights(v, rate, ccys, **kw)
    outs = []
    for ph in range(5):
        keep = np.zeros(len(w0), bool)
        keep[ph::5] = True
        w = w0.where(pd.Series(keep, index=w0.index), np.nan).ffill().fillna(0.0)
        ws = w.mul(exante(w, v), axis=0)
        outs.append(pnl(ws, v, rate))
    return sum(outs) / len(outs)


def row(label, x):
    cells = []
    for _, a, b in SL.PER:
        z = x[(x.index >= a) & (x.index < b)]
        s = SL.sharpe(z)
        cells.append("—" if np.isnan(s) or z.abs().sum() == 0 else f"{s:+.2f}")
    z = x[x.index >= "2000-01-01"]
    z = z * (0.10 / (z.std() * np.sqrt(ANN)))
    eq = (1 + z).cumprod()
    yr = z.groupby(z.index.year).sum()
    s = SL.sharpe(z)
    return (f"| {label} | " + " | ".join(cells) + f" | {s:+.2f} | {s * np.sqrt(len(z) / ANN):+.1f} | {(eq / eq.cummax() - 1).min() * 100:.0f}% | "
            f"{yr.min() * 100:+.0f}%（{yr.idxmin()}） | {(yr > 0).sum()}/{len(yr)} |"), z


def main():
    v, rate = load()
    head = "| 通貨の範囲 | " + " | ".join(p[0] for p in SL.PER) + " | 全体 | t 値 | 最大の下落 | 最悪の年 | プラスの年 |"
    sep = "|---|" + "---|" * (len(SL.PER) + 5)
    lines = ["# 研究：金利差の層を、ほかの通貨に広げる（取引は為替だけ。`tools/research/carry_breadth.py`）", "",
             "通貨ごとの重みで組む形（米ドルも1つの通貨として数える。買いの合計と売りの合計を同じにする）。週1回の入れ替え（5通りのずれの平均）。",
             "売買のコストと、スワップの上乗せ込み。期間ごとの列は年率シャープ。右の5列は 2000年以降：シャープ、t 値、最大の下落（値動き年10%）、最悪の年、プラスの年。", "",
             "スワップの上乗せ（年 %、通貨ごと。ペアでは2通貨の合計）：" + "、".join(f"{c} {MARKUP[c]:.1f}" for c in MARKUP), ""]
    keep = {}
    forms = (("A 金利の順位に比例", dict(mode="rank")), ("B 真ん中より上を買い・下を売り", dict(mode="median")),
             ("C 金利の順位に比例＋通貨ごとのトレンド60日が同じ向きのときだけ", dict(mode="rank", trend=60)),
             ("D 真ん中から年1%以上離れた通貨だけ（順位に比例）", dict(mode="rank", thr=1.0)))
    for fname, kw in forms:
        lines += [f"## {fname}", "", head, sep]
        for label, ccys in UNIVERSES:
            line, z = row(f"{label}（{len(ccys) + 1}通貨）", run(v, rate, ccys, **kw))
            lines.append(line)
            keep[(fname[0], label)] = z
            print(fname[0], line, flush=True)
        lines.append("")
    # 通貨ごとの「買い持ち」の成績（対米ドル、金利差込み）
    lines += ["## 参考：各通貨を、対米ドルで買い持ちした場合（金利差 − 上乗せ込み、2000年〜）", "",
              "| 通貨 | 年率 | 値動き（年） | シャープ | 最大の下落 | 金利差の平均（対米ドル、年 %） |", "|---|---|---|---|---|---|"]
    for c in ["NOK", "SEK", "MXN", "ZAR", "CNH", "TRY", "AUD", "NZD", "JPY", "CHF"]:
        x = (v[c].pct_change() + (rate[c] - rate["USD"] - MARKUP[c] - MARKUP["USD"]) / 100.0 / ANN)
        x = x[x.index >= "2000-01-01"].dropna()
        eq = (1 + x).cumprod()
        lines.append(f"| {c} | {x.mean() * ANN * 100:+.1f}% | {x.std() * np.sqrt(ANN) * 100:.1f}% | {SL.sharpe(x):+.2f} | {(eq / eq.cummax() - 1).min() * 100:.0f}% | "
                     f"{(rate[c] - rate['USD'])[rate.index >= '2000-01-01'].mean():+.1f} |")
    yr = pd.DataFrame({k[1]: z.groupby(z.index.year).sum() * 100 for k, z in keep.items() if k[0] == "A"}).round(1)
    lines += ["", "## 年ごとの成績（A の形、%、値動きを年10%にそろえたとき）", "", "| 年 | " + " | ".join(yr.columns) + " |", "|---|" + "---|" * len(yr.columns)]
    for y, r_ in yr.iterrows():
        lines.append(f"| {y} | " + " | ".join(f"{x:+.1f}" for x in r_.values) + " |")
    out = os.path.join(F.ROOT, "reports", "research", "carry_breadth.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    pd.DataFrame({f"{k[0]}|{k[1]}": z for k, z in keep.items()}).to_parquet(os.path.join(D.CACHE, "carry_breadth_returns.parquet"))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""研究（FX だけで取引する）：米国株の「売られすぎ」の直後に通貨を買う形を、1分足の正確な時刻で確かめる。

- fx_equity_signal.py は、為替の値が NY 正午しかないデータ（判定の20時間後に売買）で、ほぼ効果なしだった。
  ここでは、判定（NY 16:00 の S&P500 の終値）の直後に売買した場合を、為替の1分足で確かめる。
- 判定：S&P500 の CFD の1分足から作った日足（NY 16:00 区切り）に、R2・D7・IBS（公表されたまま）。
  どれかが「持つ」のあいだ、為替を事前に決めた向きに持つ。
- 売買の時刻（NY 時刻）：判定の直後の 16:05、17:05（日付の変わり目のあと）、18:05、20:05 の4通り。手じまいも同じ時刻。
  （時刻は「株の終値から何分後に売買できるか」を見るためのもので、時刻そのものを売買の理由にはしない。）
- コスト：スプレッド（S.COST + 0.5 pips）。スワップは入れない（買い・売りの向きで得も損もあるが、数日の取引では小さい）。
- データ：histdata の1分足（為替は 2010年〜、S&P500 は 2010年11月〜）。
使い方: python3 tools/research/fx_equity_signal_m1.py  → reports/research/fx_equity_signal_m1.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_reversion_cfd as IC  # noqa: E402

PAIRS = {"AUDJPY": 1, "NZDJPY": 1, "CADJPY": 1, "GBPJPY": 1, "EURJPY": 1, "USDJPY": 1, "CHFJPY": 1, "AUDUSD": 1, "NZDUSD": 1, "USDCAD": -1,
         "EURUSD": 1, "GBPUSD": 1, "USDCHF": 1, "AUDNZD": 1, "AUDCAD": 1, "NZDCAD": 1, "EURGBP": 1}
BASKETS = {"円に対する6ペア": ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CADJPY"],
           "資源国通貨 対 円": ["AUDJPY", "NZDJPY", "CADJPY"],
           "資源国通貨 対 米ドル": ["AUDUSD", "NZDUSD", "USDCAD"]}
TIMES = ((16, 5), (17, 5), (18, 5), (20, 5))
PER = (("2010〜2014", "2010-01-01", "2015-01-01"), ("2015〜21/10", "2015-01-01", "2021-11-01"), ("21/11〜24/10", "2021-11-01", "2024-11-01"),
       ("24/11〜26/10", "2024-11-01", "2026-12-01"))


def price_at(m, hh, mm):
    """各営業日（NY の日付）の hh:mm 以降の最初の1分足の始値。日付 → 値段。"""
    ny = m.index.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    s = pd.Series(m["o"].values, index=ny)
    t = s[(s.index.hour * 60 + s.index.minute >= hh * 60 + mm) & (s.index.hour * 60 + s.index.minute < hh * 60 + mm + 30)]
    out = t.groupby(t.index.normalize()).first()
    return out[out.index.dayofweek < 5]


def main():
    spx = IC.load_any("SPXUSD")
    d = IC.day_bars(spx, 16)                           # NY 16:00 区切りの日足（日付は足が閉じる日）
    r = IR.rules(d)
    st = pd.DataFrame({"R2": r["R2<10"], "D7": r["D7"], "IBS": r["IBS"]})
    st["どれか"] = (st.sum(axis=1) > 0).astype(float)
    st = st[st.index >= d.index[215]]
    # S&P500 そのもの（16:05 に売買）を、比べる相手として用意
    lines = ["# 研究：米国株の「売られすぎ」の直後に通貨を買う（1分足の正確な時刻。`tools/research/fx_equity_signal_m1.py`）", "",
             f"判定：S&P500 の CFD の日足（NY 16:00 区切り、{st.index[0].date()}〜{st.index[-1].date()}）。為替は、判定の直後の決まった時刻に売買。スプレッド込み。",
             "各セル：取引1回の平均（t 値）。「どれか」= R2・D7・IBS のどれかが持つあいだ持つ。", ""]
    res = {}
    rows_basket = []
    for hh, mm in TIMES:
        px = {}
        for pair in PAIRS:
            m = IC.load_any(pair)
            if m is None:
                continue
            px[pair] = price_at(m, hh, mm)
        px = pd.DataFrame(px)
        if hh == 16:
            sp = price_at(spx, hh, mm)
        for rule in ("R2", "D7", "IBS", "どれか"):
            p = st[rule].reindex(px.index).ffill().fillna(0.0)          # p[t] = t 日の 16:00 の判定のあとに持つか
            # t 日の hh:mm に売買 → t 日 hh:mm 〜 次の営業日 hh:mm の値動きを、p[t] で受ける
            for pair, sign in PAIRS.items():
                if pair not in px.columns:
                    continue
                c = px[pair].dropna()
                ret = (c.shift(-1) / c - 1.0)
                pp = p.reindex(c.index).fillna(0.0)
                cost = (S.COST.get(pair, 2.0) + 0.5) * D.pip_size(pair) / c
                day = pp * sign * ret - (pp - pp.shift(1).fillna(0.0)).abs() * cost
                res[(hh, rule, pair)] = day.dropna()
    def tstats(day, p):
        on = p > 0
        grp = (on & ~on.shift(1, fill_value=False)).cumsum()
        t = day[on].groupby(grp[on]).sum()
        if len(t) < 5:
            return np.nan, np.nan, 0
        return t.mean() * 100, t.mean() / t.std() * np.sqrt(len(t)), len(t)
    for bname, members in BASKETS.items():
        lines += [f"## {bname}（{'・'.join(members)}、同じ重み）", "",
                  "| ルール | " + " | ".join(f"{hh}:{mm:02d} に売買" for hh, mm in TIMES) + " | 16:05 のときの期間ごとのシャープ（" + "・".join(x[0] for x in PER) + "） | 取引数 |",
                  "|---|" + "---|" * (len(TIMES) + 2)]
        for rule in ("R2", "D7", "IBS", "どれか"):
            cells = []
            n0 = 0
            per = ""
            for hh, mm in TIMES:
                parts = [res[(hh, rule, m)] for m in members if (hh, rule, m) in res]
                if not parts:
                    cells.append("—")
                    continue
                day = pd.concat(parts, axis=1).mean(axis=1)
                p = st[rule].reindex(day.index).ffill().fillna(0.0)
                avg, t, n = tstats(day, p)
                cells.append(f"{avg:+.3f}%（t {t:+.1f}）")
                if hh == 16:
                    n0 = n
                    per = "・".join(f"{IR.sharpe(day[(day.index >= a) & (day.index < b)]):+.2f}" for _, a, b in PER)
                    rows_basket.append((bname, rule, IR.sharpe(day), day))
            lines.append(f"| {rule} | " + " | ".join(cells) + f" | {per} | {n0} |")
        lines.append("")
    # ペアごと（16:05、どれか）
    lines += ["## ペアごと（16:05 に売買、どれかのルールが持つあいだ）", "", "| ペア・向き | 1回の平均 | t 値 | 取引数 | 年率シャープ |", "|---|---|---|---|---|"]
    for pair, sign in PAIRS.items():
        if (16, "どれか", pair) not in res:
            continue
        day = res[(16, "どれか", pair)]
        p = st["どれか"].reindex(day.index).ffill().fillna(0.0)
        avg, t, n = tstats(day, p)
        lines.append(f"| {pair} {'買い' if sign > 0 else '売り'} | {avg:+.3f}% | {t:+.1f} | {n} | {IR.sharpe(day):+.2f} |")
    # 比べる相手：S&P500 そのものを同じ時刻（16:05）で売買した場合
    c = sp.dropna()
    ret = c.shift(-1) / c - 1.0
    lines += ["", "## 比べる相手：S&P500 そのものを、同じ判定・同じ時刻（16:05）で売買した場合（片道 0.02% のコスト）", "",
              "| ルール | 1回の平均 | t 値 | 取引数 | 年率シャープ |", "|---|---|---|---|---|"]
    for rule in ("R2", "D7", "IBS", "どれか"):
        p = st[rule].reindex(c.index).ffill().fillna(0.0)
        day = (p * ret - (p - p.shift(1).fillna(0.0)).abs() * 0.0002).dropna()
        avg, t, n = tstats(day, p)
        lines.append(f"| {rule} | {avg:+.3f}% | {t:+.1f} | {n} | {IR.sharpe(day):+.2f} |")
    # 同じ窓での、通貨と S&P500 の値動きの関係
    lines += ["", "## 同じ窓（16:05〜翌 16:05）での、通貨のかごと S&P500 の値動きの関係（ふだんの日すべて）", "",
              "| かご | S&P500 が 1% 動いた日の、かごの動き（ベータ） | 相関 |", "|---|---|---|"]
    for bname, members in BASKETS.items():
        parts = []
        for m in members:
            mm_ = IC.load_any(m)
            cc = price_at(mm_, 16, 5)
            parts.append(PAIRS[m] * (cc.shift(-1) / cc - 1.0))
        b = pd.concat(parts, axis=1).mean(axis=1)
        x = pd.concat([b, ret], axis=1).dropna()
        beta = np.cov(x.iloc[:, 0], x.iloc[:, 1])[0, 1] / x.iloc[:, 1].var()
        lines.append(f"| {bname} | {beta:+.2f} | {x.iloc[:, 0].corr(x.iloc[:, 1]):+.2f} |")
    out = os.path.join(F.ROOT, "reports", "research", "fx_equity_signal_m1.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

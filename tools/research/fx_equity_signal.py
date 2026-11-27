#!/usr/bin/env python3
"""研究（FX だけで取引する）：米国株が「売られすぎ」になった直後に、リスクに敏感な通貨を買うと、期待値はプラスか。

- 93章で、米国の株価指数には「上昇の流れの中で急に売られた直後は、数日のあいだ、ふだんの2〜3倍のペースで上がる」性質があった。
  株が戻るときには、リスクに敏感な通貨（豪ドル・NZドル・カナダドル）が、安全とされる通貨（円・スイスフラン・米ドル）に対して上がりやすい。
  そこで、**判定には S&P500 の日足を使い、取引は為替だけ**で行う形を確かめる。曜日・日付は使わない。
- 判定（index_reversion.py と同じ、公表済みのルールのまま）：R2・D7・IBS。どれかが「持つ」のあいだ、為替を持つ。
- データ：S&P500 は Yahoo Finance の日足（1970年〜）。為替は FRED の日次（NY 正午の値、1971年〜。EUR は 1999年〜）。
  判定は NY 16:00 の終値で出るが、FRED の為替は正午の値しかないので、**判定の次の日の正午に売買する**（20時間遅れ。厳しめ）。
  正確な時刻での検証（1分足、2010年〜）は fx_equity_signal_m1.py で行う。
- コスト：スプレッド（S.COST + 0.5 pips）、スワップ（金利差 − 上乗せ 年1%。金利は月次、1か月遅れ。1998年より前は金利のデータがないので 0 と置く）。
- 物差し：取引1回の平均と t 値、年率シャープ、期間ごとのシャープ。
使い方: python3 tools/research/fx_equity_signal.py  → reports/research/fx_equity_signal.md
"""
import os
import sys
from math import erf, sqrt

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
MARKUP = 1.0
# ペア: 株が戻るときに上がりやすい向き（+1 = 買い、-1 = 売り）。事前に決めた向き（リスクに敏感な通貨を買い、安全とされる通貨を売る）
PAIRS = {"AUDJPY": 1, "NZDJPY": 1, "CADJPY": 1, "GBPJPY": 1, "EURJPY": 1, "USDJPY": 1, "AUDUSD": 1, "NZDUSD": 1, "USDCAD": -1,
         "CHFJPY": 1, "USDCHF": 1, "EURUSD": 1, "GBPUSD": 1, "AUDNZD": 1, "AUDCAD": 1, "NZDCAD": 1, "EURGBP": 1}
BASKETS = {"円に対する6ペア（USD・EUR・GBP・AUD・NZD・CAD）": ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CADJPY"],
           "資源国通貨 対 円（AUD・NZD・CAD）": ["AUDJPY", "NZDJPY", "CADJPY"],
           "資源国通貨 対 米ドル（AUDUSD・NZDUSD 買い、USDCAD 売り）": ["AUDUSD", "NZDUSD", "USDCAD"]}
PER = (("1975〜1989", "1975-01-01", "1990-01-01"), ("1990〜1999", "1990-01-01", "2000-01-01"), ("2000〜2008", "2000-01-01", "2009-01-01"),
       ("2009〜21/10", "2009-01-01", "2021-11-01"), ("21/11〜24/10", "2021-11-01", "2024-11-01"), ("24/11〜26/11", "2024-11-01", "2026-12-01"))


def Phi(x):
    return 0.5 * (1 + erf(x / sqrt(2)))


def sharpe(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 50 and x.std() > 0 else np.nan


def load_fx():
    px = F.prices(start="1974-01-01")
    carry = F.carry_daily(px.index).reindex(px.index).fillna(0.0)
    cost = pd.DataFrame({p: (S.COST.get(p, 2.0) + 0.5) * D.pip_size(p) / px[p] for p in px.columns})
    return px, carry, cost


def spx_states():
    d = Y.fetch("SPX")
    d = d[d.index >= "1972-01-01"]
    r = IR.rules(d)
    st = pd.DataFrame({"R2": r["R2<10"], "D7": r["D7"], "IBS": r["IBS"]})
    st["どれか"] = (st.sum(axis=1) > 0).astype(float)
    st["合計"] = st[["R2", "D7", "IBS"]].sum(axis=1) / 3.0
    return st, d


def fx_pnl(state, px, carry, cost, pair, sign):
    """S&P500 の状態 state（その日の終値のあとに持つか、0〜1）で、為替 pair を sign の向きに持つ。売買は次の日の正午。"""
    p = state.reindex(px.index.union(state.index)).ffill().reindex(px.index).fillna(0.0)
    c = px[pair]
    ret = c.pct_change().fillna(0.0)
    held = p.shift(2).fillna(0.0)          # t 日の終値の判定 → t+1 日の正午に売買 → t+1 正午〜t+2 正午の値動き
    w = p.shift(1).fillna(0.0)
    cy = carry[pair] if pair in carry.columns else 0.0
    r = held * sign * ret + held * (sign * cy - MARKUP) / 100.0 / 261.0 - (w - held).abs() * cost[pair]
    return r, held


def trade_stats(r, held):
    on = held > 0
    grp = (on & ~on.shift(1, fill_value=False)).cumsum()
    t = r[on | on.shift(1, fill_value=False)].groupby(grp[on | on.shift(1, fill_value=False)]).sum()
    t = t[t.index > 0]
    if len(t) < 5:
        return 0, np.nan, np.nan
    return len(t), t.mean() * 100, t.mean() / t.std() * np.sqrt(len(t))


def row(label, r, held, start="1975-01-01"):
    r, held = r[r.index >= start], held[held.index >= start]
    cells = []
    for _, a, b in PER:
        x = r[(r.index >= a) & (r.index < b)]
        s = sharpe(x)
        cells.append("—" if np.isnan(s) or x.abs().sum() == 0 else f"{s:+.2f}")
    n, avg, t = trade_stats(r, held)
    s = sharpe(r)
    yr = r.groupby(r.index.year).sum()
    yr = yr[yr != 0]
    return (f"| {label} | {n} | {avg:+.3f}% | {t:+.1f} | " + " | ".join(cells) + f" | {s:+.2f} | {s * np.sqrt(len(r) / ANN):+.1f} | {Phi(-s) * 100:.0f}% | {(yr > 0).sum()}/{len(yr)} |")


HEAD = "| 形 | 取引数 | 1回の平均 | t 値 | " + " | ".join(p[0] for p in PER) + " | 全体のシャープ | 全体の t 値 | 負ける年 | プラスの年 |"
SEP = "|---|" + "---|" * (len(PER) + 7)


def main():
    px, carry, cost = load_fx()
    st, spx = spx_states()
    lines = ["# 研究：米国株の「売られすぎ」の直後に、リスクに敏感な通貨を買う（取引は為替だけ。`tools/research/fx_equity_signal.py`）", "",
             "判定は S&P500 の日足（R2・D7・IBS、公表されたまま）。為替は FRED の NY 正午の値で、判定の次の日の正午に売買（20時間遅れ）。コスト・スワップ込み。",
             "期間ごとの列は年率シャープ。建玉は、持っているあいだ口座の100%（持っていない日は 0）。", ""]
    R = {}
    # 1) ペアごと（「どれかのルールが持つ」あいだ持つ）
    lines += ["## ペアごと：3つのルールのどれかが「持つ」のあいだ、事前に決めた向きに持つ", "", HEAD, SEP]
    for pair, sign in PAIRS.items():
        if pair not in px.columns:
            continue
        r, held = fx_pnl(st["どれか"], px, carry, cost, pair, sign)
        first = px[pair].first_valid_index()
        R[pair] = (r, held)
        lines.append(row(f"{pair} {'買い' if sign > 0 else '売り'}（{first.year}年〜）", r, held, start=max(pd.Timestamp("1975-01-01"), first)))
    # 2) かご × ルール
    lines += ["", "## かご（同じ重み）× ルール", "", HEAD, SEP]
    for bname, members in BASKETS.items():
        for rule in ("R2", "D7", "IBS", "どれか", "合計"):
            parts, helds = [], []
            for pair in members:
                r, held = fx_pnl(st[rule], px, carry, cost, pair, PAIRS[pair])
                parts.append(r)
                helds.append(held)
            r = pd.concat(parts, axis=1).mean(axis=1)
            held = pd.concat(helds, axis=1).max(axis=1)
            R[(bname, rule)] = (r, held)
            lab = {"どれか": "どれかが持つあいだ", "合計": "持つルールの数に比例"}.get(rule, rule)
            lines.append(row(f"{bname}：{lab}", r, held, start="1999-01-01" if "EUR" in "".join(members) else "1975-01-01"))
    # 3) 比べる相手：いつも持った場合（同じかごを、条件なしで持つ）と、S&P500 そのもの
    lines += ["", "## 比べる相手：同じかごを、条件を付けずにずっと持った場合", "", HEAD, SEP]
    one = pd.Series(1.0, index=st.index)
    for bname, members in BASKETS.items():
        parts = [fx_pnl(one, px, carry, cost, pair, PAIRS[pair])[0] for pair in members]
        r = pd.concat(parts, axis=1).mean(axis=1)
        lines.append(row(f"{bname}：ずっと持つ", r, pd.Series(0.0, index=r.index), start="1999-01-01" if "EUR" in "".join(members) else "1975-01-01"))
    # 4) 条件あり・なしの、持っている1日あたりの平均の比較（主なかご）
    lines += ["", "## 持っている1日あたりの平均（コスト・スワップを除く、値動きだけ）", "",
              "| かご | 売られすぎのあと（どれかが持つ日） | それ以外の日 | 差の t 値 |", "|---|---|---|---|"]
    p_any = st["どれか"].reindex(px.index.union(st.index)).ffill().reindex(px.index).fillna(0.0).shift(2).fillna(0.0)
    for bname, members in BASKETS.items():
        ret = pd.concat([PAIRS[m] * px[m].pct_change() for m in members], axis=1).mean(axis=1)
        ret = ret[ret.index >= ("1999-01-01" if "EUR" in "".join(members) else "1975-01-01")]
        a, b = ret[p_any.reindex(ret.index) > 0].dropna(), ret[p_any.reindex(ret.index) == 0].dropna()
        t = (a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b))
        lines.append(f"| {bname} | {a.mean() * 100:+.4f}%（{len(a)} 日） | {b.mean() * 100:+.4f}%（{len(b)} 日） | {t:+.1f} |")
    out = os.path.join(F.ROOT, "reports", "research", "fx_equity_signal.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    keep = {f"{k[0]}|{k[1]}": v[0] for k, v in R.items() if isinstance(k, tuple)}
    pd.DataFrame(keep).to_parquet(os.path.join(D.CACHE, "fx_equity_signal_returns.parquet"))


if __name__ == "__main__":
    main()

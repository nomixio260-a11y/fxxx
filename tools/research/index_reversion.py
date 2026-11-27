#!/usr/bin/env python3
"""研究：株価指数の「売られすぎの戻り」に、日付・時刻を使わない数学的な優位性があるか（公表済みのルールを、公表後の期間で確かめる）。

- 自分でルールを探すと、たまたま良く見えるものを拾ってしまう。そこで、書籍・論文で公表済みのルールを、数値を変えずにそのまま使い、
  「公表より後の期間」の成績を見る（公表後のデータは、ルールを作った人も見ていない）。
  R2：終値が200日の平均より上で、RSI(2) が 10 未満（または 5 未満）になったら終値で買い、終値が5日の平均を上回ったら終値で売る
      （Connors & Alvarez『Short Term Trading Strategies That Work』2008年。公表後 = 2009年〜）
  D7：終値が200日の平均より上で、過去7日の終値の最安値になったら買い、過去7日の終値の最高値になったら売る（同書）
  IBS：(終値 − 安値) ÷ (高値 − 安値) が 0.2 未満の日の終値で買い、次の日の終値で売る（2012〜13年に広く知られた。公表後 = 2014年〜）
- データ：Yahoo Finance の日足（tools/research/yahoo_data.py）。
- コスト（CFD で持つ場合）：売買のたびに片道 0.02%（往復 0.04%）。持ち越すたびに（短期金利 + 年2.5%）÷ 360 を払い、配当（年率の目安）を受け取る。
- 売買の値段：
  「終値」= 判定した日の終値で売買する（CFD は現物の取引が終わる前後も取引できる）。
  「翌日の始値」= 判定した次の日の始値で売買する（厳しめの見方。指数の始値は実際に売買できる値段ではないので、ETF で確かめる）。
- 物差し：取引ごとの平均の損益と t 値、年率シャープ、1年で負ける確率（Φ(−シャープ)）。
使い方: python3 tools/research/index_reversion.py  → reports/research/index_reversion.md
"""
import os
import sys
from math import erf, sqrt

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import fred_data as F  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
COST = 0.0002          # 片道
MARKUP = 2.5           # 業者の金利の上乗せ（年 %）
# 名前: (Yahoo の名前, 通貨, 配当の目安（年 %）, OANDA の CFD の名前)
INDEX = {"S&P500": ("SPX", "USD", 1.5, "US500"), "NASDAQ100": ("NDX", "USD", 0.7, "US100"), "ダウ": ("DJI", "USD", 1.9, "US30"),
         "ラッセル2000": ("RUT", "USD", 1.3, "US2000"), "日経225": ("N225", "JPY", 1.7, "JP225"), "DAX": ("DAX", "EUR", 0.0, "DE30"),
         "FTSE100": ("FTSE", "GBP", 3.5, "UK100"), "CAC40": ("CAC", "EUR", 3.0, "FR40"), "ハンセン": ("HSI", "USD", 3.0, "HK33"),
         "ASX200": ("ASX", "AUD", 4.0, "AU200")}
ETF = {"SPY（S&P500）": ("SPY", "USD", 0.0), "QQQ（NASDAQ100）": ("QQQ", "USD", 0.0), "DIA（ダウ）": ("DIA", "USD", 0.0),
       "IWM（ラッセル2000）": ("IWM", "USD", 0.0)}
PER = (("〜2008（公表前）", "1980-01-01", "2009-01-01"), ("2009〜21/10", "2009-01-01", "2021-11-01"),
       ("21/11〜24/10", "2021-11-01", "2024-11-01"), ("24/11〜25/10", "2024-11-01", "2025-11-01"), ("25/11〜26/11", "2025-11-01", "2026-12-01"))


def Phi(x):
    return 0.5 * (1 + erf(x / sqrt(2)))


def short_rate(ccy, index):
    """その通貨の短期金利（年 %、日次にそろえる。月次の値は1か月遅らせて使う）。"""
    if ccy == "USD":
        s = F.fetch("DTB3").dropna()
        return s.reindex(s.index.union(index)).ffill().reindex(index).fillna(5.0)
    code = {"JPY": "JP", "EUR": "EZ", "GBP": "GB", "AUD": "AU"}[ccy]
    m = F.fetch(f"IR3TIB01{code}M156N").dropna().shift(1).dropna()
    s = m.reindex(m.index.union(index)).ffill().reindex(index)
    return s.fillna({"JPY": 4.0, "EUR": 5.0, "GBP": 8.0, "AUD": 8.0}[ccy])


def rsi_wilder(c, n=2):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1.0 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1.0 / n, adjust=False).mean()
    return 100.0 - 100.0 / (1.0 + up / dn.replace(0, np.nan))


def positions(entry, exit_):
    """entry が真の日の終値で持ち始め、exit_ が真の日の終値で手放す。p[t] = t 日の終値のあとに持っているか（0/1）。"""
    e, x = entry.values, exit_.values
    p = np.zeros(len(e))
    cur = 0.0
    for i in range(len(e)):
        if cur == 0.0:
            if e[i]:
                cur = 1.0
        elif x[i]:
            cur = 0.0
        p[i] = cur
    return pd.Series(p, index=entry.index)


def rules(d):
    """公表済みのルールごとの建玉（0/1）。d は日足（open/high/low/close）。"""
    c = d["close"]
    up = c > c.rolling(200).mean()
    r2 = rsi_wilder(c, 2)
    ex5 = c > c.rolling(5).mean()
    out = {"R2<10": positions(up & (r2 < 10), ex5), "R2<5": positions(up & (r2 < 5), ex5),
           "D7": positions(up & (c <= c.rolling(7).min()), c >= c.rolling(7).max())}
    rng = (d["high"] - d["low"])
    ibs = ((c - d["low"]) / rng.where(rng > 0)).fillna(0.5)
    out["IBS"] = (ibs < 0.2).astype(float)          # その日の終値で買い、次の日の終値で売る（条件が続けば持ち続ける）
    return out


def pnl(p, d, rate, div, at_open=False):
    """建玉 p（0/1、終値で判定）の日次の損益（建玉の大きさ = 口座の100%）。CFD の金利・配当・売買のコスト込み。
    at_open=True なら、判定した次の日の始値で売買する。"""
    c, o = d["close"], d["open"]
    days = pd.Series(c.index, index=c.index).diff().dt.days.fillna(1.0)
    fin = (div - rate - MARKUP) / 100.0 / 360.0 * days            # 持ち越し1回（前日の終値→当日）あたり
    if not at_open:
        held = p.shift(1).fillna(0.0)
        tc = (p - held).abs() * COST
        return held * (c.pct_change().fillna(0.0) + fin) - tc
    held_on = p.shift(2).fillna(0.0)          # 前日の終値→当日の始値に持っている建玉
    held_day = p.shift(1).fillna(0.0)         # 当日の始値→終値に持っている建玉
    gap = (o / c.shift(1) - 1.0).fillna(0.0)
    day = (c / o - 1.0).fillna(0.0)
    tc = (held_day - held_on).abs() * COST
    return held_on * (gap + fin) + held_day * day - tc


def trades(p, r):
    """建玉の区切りごとの損益（%）。"""
    held = (p.shift(1).fillna(0.0) > 0) | (p > 0)
    grp = (p.shift(1).fillna(0.0).eq(0) & p.gt(0)).cumsum()
    t = r[held].groupby(grp[held]).sum()
    return t[t.index > 0]


def sharpe(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 50 and x.std() > 0 else np.nan


def stat_row(label, p, r):
    tr = trades(p, r)
    cells = []
    for _, a, b in PER:
        x = r[(r.index >= a) & (r.index < b)]
        s = sharpe(x)
        cells.append("—" if np.isnan(s) or x.abs().sum() == 0 else f"{s:+.2f}")
    post = r[r.index >= "2009-01-01"]
    tp = trades(p[p.index >= "2009-01-01"], post)
    tt = tp.mean() / tp.std() * np.sqrt(len(tp)) if len(tp) > 5 and tp.std() > 0 else np.nan
    sp = sharpe(post)
    return (f"| {label} | {len(tr)} | {(tr > 0).mean() * 100:.0f}% | {tr.mean() * 100:+.2f}% | {p.mean() * 100:.0f}% | " + " | ".join(cells)
            + f" | {len(tp)} | {tp.mean() * 100:+.2f}% | {tt:+.1f} | {sp:+.2f} | {Phi(-sp) * 100:.0f}% |")


HEAD = ("| 指数・ルール | 取引数 | 勝率 | 1回の平均 | 持っている日 | " + " | ".join(x[0] for x in PER)
        + " | 2009年〜の取引数 | 1回の平均 | t 値 | シャープ | 負ける年 |")


def main():
    lines = ["# 研究：株価指数の「売られすぎの戻り」（公表済みのルールを、公表後の期間で確かめる。`tools/research/index_reversion.py`）", "",
             "コスト込み（売買は片道 0.02%、持ち越しは 短期金利＋年2.5% を払い配当を受け取る）。建玉の大きさは口座の100%（持っていない日は 0）。",
             "期間ごとの列は年率シャープ。右の5列は、ルールの公表より後（2009年〜）だけの成績。", ""]
    R, P = {}, {}
    for mode, title in ((False, "判定した日の終値で売買"), (True, "判定した次の日の始値で売買（指数の始値は目安。下の ETF の表が実際に売買できる値段）")):
        lines += [f"## 指数：{title}", "", HEAD, "|---|" + "---|" * (len(PER) + 9)]
        for name, (yn, ccy, div, _) in INDEX.items():
            d = Y.fetch(yn)
            d = d[d.index >= "1980-01-01"]
            rate = short_rate(ccy, d.index)
            for key, p in rules(d).items():
                if key == "IBS":
                    ok = d["high"] > d["low"]
                    p = p.where(ok.rolling(20).min().fillna(0) > 0, 0.0)       # 高値・安値のない時期は使わない
                r = pnl(p, d, rate, div, at_open=mode)
                R[(name, key, mode)], P[(name, key, mode)] = r, p
                lines.append(stat_row(f"{name}：{key}", p, r))
        lines.append("")
    lines += ["## ETF（実際に売買された値段）：判定した次の日の始値で売買", "",
              "ETF は、配当を含まない値段で計算（配当の分だけ厳しめ）。", "", HEAD, "|---|" + "---|" * (len(PER) + 9)]
    for name, (yn, ccy, div) in ETF.items():
        d = Y.fetch(yn)
        rate = short_rate(ccy, d.index)
        for key, p in rules(d).items():
            r = pnl(p, d, rate, div, at_open=True)
            R[(name, key, True)], P[(name, key, True)] = r, p
            lines.append(stat_row(f"{name}：{key}", p, r))
    lines += ["", "## ETF：判定した日の終値で売買", "", HEAD, "|---|" + "---|" * (len(PER) + 9)]
    for name, (yn, ccy, div) in ETF.items():
        d = Y.fetch(yn)
        rate = short_rate(ccy, d.index)
        for key, p in rules(d).items():
            r = pnl(p, d, rate, div, at_open=False)
            R[(name, key, False)], P[(name, key, False)] = r, p
            lines.append(stat_row(f"{name}：{key}", p, r))
    out = os.path.join(F.ROOT, "reports", "research", "index_reversion.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    pd.DataFrame({f"{k[0]}|{k[1]}|{int(k[2])}": v for k, v in R.items()}).to_parquet(os.path.join(D.CACHE, "index_reversion_returns.parquet"))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""FRED（セントルイス連銀の公開データ）から、長い期間の為替（日次、ニューヨーク正午）と各国の短期金利（月次、3か月の銀行間金利）を取得する。

- 為替：DEXJPUS など（1971年〜、EUR は 1999年〜）。8通貨（USD・JPY・EUR・GBP・AUD・NZD・CAD・CHF）から、取引する17ペアを作る。
- 金利：IR3TIB01xxM156N（OECD の月次。JPY は 2002年4月〜、CHF は 1999年7月〜。それより前は、当時の水準のおおよその値で埋める）。
  EUR・GBP は 2026年1月で更新が止まっているため、最後の値を引き延ばす。
- 取得したファイルは data/fred/ に置く（リポジトリには入れない）。なければ取得する。
使い方: python3 tools/research/fred_data.py   （取得して、期間と最新の値を表示）
"""
import os
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(ROOT, "data", "fred")
FX = {"JPY": ("DEXJPUS", False), "EUR": ("DEXUSEU", True), "GBP": ("DEXUSUK", True), "AUD": ("DEXUSAL", True),
      "NZD": ("DEXUSNZ", True), "CAD": ("DEXCAUS", False), "CHF": ("DEXSZUS", False)}   # True = 「1通貨あたりの USD」
RATE = {"USD": "US", "JPY": "JP", "EUR": "EZ", "GBP": "GB", "AUD": "AU", "NZD": "NZ", "CAD": "CA", "CHF": "CH"}
PAIRS = ["USDJPY", "EURUSD", "EURJPY", "GBPJPY", "AUDJPY", "GBPUSD", "AUDCAD", "AUDNZD", "AUDUSD", "CADJPY",
         "CHFJPY", "EURGBP", "NZDCAD", "NZDJPY", "NZDUSD", "USDCAD", "USDCHF"]
ALL_CCY = ["USD", "JPY", "EUR", "GBP", "AUD", "NZD", "CAD", "CHF"]


def fetch(series):
    os.makedirs(DIR, exist_ok=True)
    path = os.path.join(DIR, f"{series}.csv")
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
        subprocess.run(["curl", "-sS", "-m", "90", "-o", path, url], check=True)
    s = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
    return pd.to_numeric(s, errors="coerce")


def usd_value():
    """各通貨の USD での値段（1通貨 = 何 USD）。日次。"""
    out = {"USD": None}
    for c, (sid, direct) in FX.items():
        s = fetch(sid).dropna()
        out[c] = s if direct else 1.0 / s
    df = pd.DataFrame({c: v for c, v in out.items() if v is not None})
    df["USD"] = 1.0
    return df.sort_index()


def prices(pairs=None, start="1999-01-01"):
    """ペアの値段（日次）。pairs を省くと、取引する17ペア。"""
    v = usd_value()
    v = v[v.index >= start]
    pairs = pairs or PAIRS
    px = pd.DataFrame({p: v[p[:3]] / v[p[3:]] for p in pairs})
    px = px[px.index.dayofweek < 5].ffill(limit=3)
    return px.dropna(how="all")


def rates_monthly():
    """各通貨の短期金利（月次の平均、年率 %）。"""
    m = {c: fetch(f"IR3TIB01{k}M156N") for c, k in RATE.items()}
    df = pd.DataFrame(m).sort_index()
    df = df[df.index >= "1998-01-01"]
    # データのない初めの時期：JPY はゼロ金利（約 0.2%）、CHF は 1999年前半の約 1.2%
    df["JPY"] = df["JPY"].where(df["JPY"].notna() | (df.index >= "2002-04-01"), 0.2)
    df["CHF"] = df["CHF"].where(df["CHF"].notna() | (df.index >= "1999-07-01"), 1.2)
    return df.ffill()


def yields10_monthly():
    """各通貨の10年国債の利回り（月次の平均、年率 %）。EUR は 2026年1月で止まっているため、最後の値を引き延ばす。"""
    m = {c: fetch(f"IRLTLT01{k}M156N") for c, k in RATE.items()}
    df = pd.DataFrame(m).sort_index()
    return df[df.index >= "1997-01-01"].ffill()


def monthly_to_daily(m, index, lag=1):
    """月次の値を日次にする。その月の判断には、lag か月前までの値だけを使う（未来の情報を使わない）。"""
    r = m.shift(lag)
    return r.reindex(r.index.union(index)).ffill().reindex(index)


def carry_daily(index, pairs=None):
    """ペアを買ったときの金利差（基準の通貨 − 相手の通貨、年率 %）。その月の判断には、前の月までの金利だけを使う。"""
    r = rates_monthly().shift(1)                    # 前の月の平均（未来の情報を使わない）
    r = r.reindex(r.index.union(index)).ffill().reindex(index)
    pairs = pairs or PAIRS
    return pd.DataFrame({p: r[p[:3]] - r[p[3:]] for p in pairs}, index=index)


if __name__ == "__main__":
    px = prices()
    print("為替：", px.index[0].date(), "〜", px.index[-1].date(), len(px), "日、", len(px.columns), "ペア")
    r = rates_monthly()
    print("金利（最新の月、年率 %）：", r.index[-1].date(), r.iloc[-1].round(2).to_dict())
    ann = r[r.index >= "2015"].groupby(r[r.index >= "2015"].index.year).mean().round(2)
    print(ann.T.to_string())

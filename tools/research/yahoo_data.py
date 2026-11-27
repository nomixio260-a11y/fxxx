#!/usr/bin/env python3
"""Yahoo Finance の公開データから、株価指数・先物・ETF の日足（始値・高値・安値・終値・調整後終値）を取得する。

- 研究用（為替以外の層の検証）。取得したファイルは data/yahoo/ に置く（リポジトリには入れない）。なければ取得する。
- 日付は、その取引所の現地の日付。
- 注意：
  指数（^GSPC など）の「始値」は、寄り付きの直後にまだ値の付いていない銘柄を前日の終値で数えるため、実際に売買できる値段とは違う。
  始値で売買する検証には、ETF（SPY・QQQ など、実際に売買された値段）を使う。
  先物（GC=F など）は、期近をそのままつないだ値で、乗り換えの日の段差を含む。
  ETF の調整後終値は、分配金を含めた値（持ち続けたときの成績）。
使い方: python3 tools/research/yahoo_data.py   （取得して、期間を表示）
"""
import json
import os
import subprocess
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(ROOT, "data", "yahoo")
# 名前: (ティッカー, 説明)
TICKERS = {
    "SPX": ("^GSPC", "S&P500"), "NDX": ("^NDX", "NASDAQ100"), "DJI": ("^DJI", "ダウ"), "RUT": ("^RUT", "ラッセル2000"),
    "N225": ("^N225", "日経225"), "DAX": ("^GDAXI", "DAX（配当込みの指数）"), "FTSE": ("^FTSE", "FTSE100"),
    "CAC": ("^FCHI", "CAC40"), "STOXX": ("^STOXX50E", "ユーロ・ストックス50"), "HSI": ("^HSI", "ハンセン"), "ASX": ("^AXJO", "ASX200"),
    "SPY": ("SPY", "S&P500 の ETF"), "QQQ": ("QQQ", "NASDAQ100 の ETF"), "DIA": ("DIA", "ダウの ETF"), "IWM": ("IWM", "ラッセル2000 の ETF"),
    "EWJ": ("EWJ", "日本株の ETF（米国上場）"), "EWG": ("EWG", "ドイツ株の ETF（米国上場）"), "EWU": ("EWU", "英国株の ETF（米国上場）"),
    "GLD": ("GLD", "金の ETF"), "SLV": ("SLV", "銀の ETF"), "USO": ("USO", "原油の ETF"), "DBC": ("DBC", "商品全体の ETF"),
    "TLT": ("TLT", "米国の長期国債の ETF"), "IEF": ("IEF", "米国の中期国債の ETF"),
    "GC": ("GC=F", "金の先物"), "SI": ("SI=F", "銀の先物"), "CL": ("CL=F", "原油の先物"), "HG": ("HG=F", "銅の先物"),
    "VIX": ("^VIX", "VIX"),
}


def fetch(name):
    """日足の DataFrame（open, high, low, close, adj, volume）。索引は現地の日付。"""
    os.makedirs(DIR, exist_ok=True)
    path = os.path.join(DIR, f"{name}.csv")
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        tk = TICKERS[name][0].replace("^", "%5E")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?period1=0&period2=1900000000&interval=1d"
        raw = os.path.join(DIR, f"{name}.json")
        subprocess.run(["curl", "-sS", "-m", "120", "-A", "Mozilla/5.0", "-o", raw, url], check=True)
        r = json.load(open(raw, encoding="utf-8"))["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        # 取引所の現地時刻（夏時間あり）の日付にする。先物は現地の 0:00 の時刻が付いているため、固定の時差で直すと夏の日付が1日ずれる
        tz = r["meta"].get("exchangeTimezoneName", "UTC")
        idx = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert(tz).tz_localize(None).normalize()
        df = pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
                           "adj": r["indicators"].get("adjclose", [{"adjclose": q["close"]}])[0]["adjclose"], "volume": q["volume"]},
                          index=idx)
        df = df[~df.index.duplicated(keep="last")].dropna(subset=["close"])
        df.index.name = "date"
        df.to_csv(path)
        os.remove(raw)
    return pd.read_csv(path, index_col=0, parse_dates=True)


def fetch_ticker(name, ticker):
    """TICKERS にないティッカーを、名前を付けて取得する（例：fetch_ticker("TRY", "TRY=X")）。"""
    if name not in TICKERS:
        TICKERS[name] = (ticker, name)
    return fetch(name)


def main():
    for name, (tk, desc) in TICKERS.items():
        try:
            d = fetch(name)
            real = d[(d["high"] > d["low"])]
            print(f"{name:6s} {tk:10s} {desc}：{d.index[0].date()}〜{d.index[-1].date()} {len(d)} 日、"
                  f"高値と安値が別の値になる最初の日 {real.index[0].date() if len(real) else '—'}、最新の終値 {d['close'].iloc[-1]:.2f}")
        except Exception as e:  # noqa: BLE001
            print(f"{name:6s} {tk:10s} 取得できませんでした（{e}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

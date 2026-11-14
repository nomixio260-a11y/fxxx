#!/usr/bin/env python3
"""研究用データの共通処理。

histdata.com の1分足（tools/fetch_histdata.sh の出力。時刻は EST 固定 + 7時間 = UTC+2 固定）を読み込み、
- UTC に直す
- 東京・ロンドン・ニューヨークの現地時刻（夏時間あり）を付ける
- 任意の時間足（5分・1時間など）にまとめる
を行う。結果は data/cache/*.parquet にキャッシュする。
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "cache")

PAIRS = ["USDJPY", "EURUSD", "EURJPY", "GBPJPY", "AUDJPY", "GBPUSD"]
# 環境変数 AMS_PAIRS（カンマ区切り）で、調べる銘柄を差し替えられる（例：AMS_PAIRS=NZDJPY,CADJPY）
if os.environ.get("AMS_PAIRS"):
    PAIRS = [p.strip() for p in os.environ["AMS_PAIRS"].split(",") if p.strip()]

# 期間の役割（固定。変えない）
DESIGN = ("2015-01-01", "2022-01-01")
VALID = ("2022-01-01", "2024-11-01")
FINAL = ("2024-11-01", "2026-11-13")


def pip_size(pair: str) -> float:
    return 0.01 if pair.endswith("JPY") else 0.0001


def load_m1(pair: str) -> pd.DataFrame:
    """1分足を読み込む（index は UTC）。"""
    os.makedirs(CACHE, exist_ok=True)
    cache = os.path.join(CACHE, f"{pair}_M1.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    src = os.path.join(DATA, f"{pair}_M1_2015.csv")
    df = pd.read_csv(src, header=None, names=["d", "t", "o", "h", "l", "c", "v"],
                     dtype={"d": str, "t": str})
    ts = pd.to_datetime(df["d"] + " " + df["t"], format="%Y.%m.%d %H:%M")
    # fetch_histdata.sh は histdata の時刻に +7h して保存している。
    # histdata の時刻は「ニューヨークの現地時刻（夏時間あり）」と一致する
    # （週明けの最初の足が、夏でも冬でも 17:00 になっている）。
    # → 7時間戻して NY 時刻とし、UTC に変換する。夏時間の切り替わりで重複・欠落する時刻は捨てる。
    ny = pd.DatetimeIndex(ts - pd.Timedelta(hours=7))
    utc = ny.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT").tz_convert("UTC").tz_localize(None)
    keep = ~pd.isna(utc)
    out = pd.DataFrame({"o": df["o"].values[keep], "h": df["h"].values[keep], "l": df["l"].values[keep],
                        "c": df["c"].values[keep]}, index=pd.DatetimeIndex(utc[keep], name="utc"))
    out = out[~out.index.duplicated()].sort_index()
    out.to_parquet(cache)
    return out


def resample(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    """1分足を rule（'5min', '1h' など）の足にまとめる。足の時刻は始まりの時刻（UTC）。"""
    agg = m1.resample(rule, label="left", closed="left").agg({"o": "first", "h": "max", "l": "min", "c": "last"})
    return agg.dropna()


def add_local_time(df: pd.DataFrame) -> pd.DataFrame:
    """東京・ロンドン・ニューヨークの現地時刻の列を付ける（夏時間は tz データベースで正確に扱う）。"""
    idx = df.index.tz_localize("UTC")
    out = df.copy()
    for name, tz in (("tky", "Asia/Tokyo"), ("ldn", "Europe/London"), ("ny", "America/New_York")):
        loc = idx.tz_convert(tz)
        out[f"{name}_h"] = loc.hour
        out[f"{name}_m"] = loc.minute
        out[f"{name}_date"] = loc.tz_localize(None).normalize()
    out["tky_dow"] = idx.tz_convert("Asia/Tokyo").dayofweek
    return out


def bars(pair: str, rule: str) -> pd.DataFrame:
    """キャッシュ付きで、指定の時間足＋現地時刻の列を返す。"""
    os.makedirs(CACHE, exist_ok=True)
    cache = os.path.join(CACHE, f"{pair}_{rule}.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    df = add_local_time(resample(load_m1(pair), rule))
    df.to_parquet(cache)
    return df


def period_mask(index: pd.DatetimeIndex, period) -> np.ndarray:
    return (index >= pd.Timestamp(period[0])) & (index < pd.Timestamp(period[1]))


if __name__ == "__main__":
    for p in (sys.argv[1:] or PAIRS):
        b = bars(p, "1h")
        print(p, len(b), b.index.min(), b.index.max())

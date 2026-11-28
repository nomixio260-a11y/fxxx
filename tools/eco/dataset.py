#!/usr/bin/env python3
"""複合システム：学習・検証に使うデータを組み立てる。日付・時刻・曜日は特徴量に入れない。

- 銘柄（日足）：
   株価指数（現物。Yahoo Finance）11：S&P500・NASDAQ100・ダウ・ラッセル2000・日経225・DAX・FTSE100・CAC40・ユーロ・ストックス50・ハンセン・ASX200
   為替（公開の1分足から作った NY 17時区切りの日足。2010年〜）17 ペア
   金属：金・銀・銅（OANDA の日足があればそれを、なければ Yahoo Finance の先物）
   OANDA の指数の CFD（14銘柄、2016年〜。書き出しのフォルダがあるとき）… 実際に売買する値段での確かめ用（名前の頭に CFD_ を付ける）
   （v2 から）米国の株式の ETF 21 本（学習だけに使う追加のチャート。build_etf。名前の頭に ETF_ を付ける）
- 1行＝1銘柄の1日。特徴量は tools/eco/features.py の 78 個 ＋ 既存のルールの「持っている状態」（R2・D7・IBS とその数）＋ VIX の3つ（1日前の値）＋ 銘柄の種類。
- 予想する相手：次の日の値動き（終値 → 次の終値）。y ＝ 値動き ÷ その日の値動きの大きさ、up ＝ 上がったかどうか。
- 書き出しのフォルダは、環境変数 AMS_IX_EXPORT（指数の口座）・AMS_CM_EXPORT（商品の口座）で渡す（リポジトリには入れていない）。
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "research"))
import features as FT  # noqa: E402
import fred_data as F  # noqa: E402
import index_others as IO  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_reversion_cfd as IC  # noqa: E402
import yahoo_data as Y  # noqa: E402

CACHE = os.path.join(F.ROOT, "data", "eco")
INDICES = ("SPX", "NDX", "DJI", "RUT", "N225", "DAX", "FTSE", "CAC", "STOXX", "HSI", "ASX")
FX = ("USDJPY", "EURUSD", "EURJPY", "GBPJPY", "AUDJPY", "GBPUSD", "AUDCAD", "AUDNZD", "AUDUSD", "CADJPY", "CHFJPY", "EURGBP", "NZDCAD", "NZDJPY", "NZDUSD", "USDCAD", "USDCHF")
METALS = (("XAUUSD", "GC"), ("XAGUSD", "SI"), ("COPPER", "HG"))
WIN = 64                                                    # チャートを読むモデルに見せる本数
ETFS = ("SPY", "QQQ", "DIA", "IWM", "MDY", "IJR", "VTI", "IWF", "IWD", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "IYR", "SMH", "IBB")
EXTRA = ("st_r2", "st_d7", "st_ibs", "st_n", "vix_rank", "vix_chg1", "vix_chg5", "is_index", "is_fx", "is_metal")


def vix_close():
    """VIX の日次の終値。CBOE の公表値（実運用の tools/ci/fetch_vix.ps1・毎日の予想 tools/eco/predict.py と同じ出どころ）。取れなければ Yahoo Finance。
    Yahoo Finance の値は、米国の祝日の行がなく（CFD は祝日も動く）、終値が公表値と違う日もあるため、検証と実運用をそろえる目的で公表値を使う。"""
    import re
    import subprocess
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, "vix_cboe.csv")
    if not os.path.exists(f) or os.path.getsize(f) < 100000:
        try:
            subprocess.run(["curl", "-sS", "-L", "-m", "120", "-A", "Mozilla/5.0", "-o", f, "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"], check=True)
        except Exception as e:                                  # noqa: BLE001
            print("VIX（CBOE）の取得に失敗:", e)
    rows = {}
    if os.path.exists(f):
        for line in open(f, encoding="ascii", errors="ignore"):
            m = re.match(r"^\s*(\d{2})/(\d{2})/(\d{4}),[^,]*,[^,]*,[^,]*,\s*([0-9.]+)\s*$", line)
            if m:
                rows[pd.Timestamp(int(m.group(3)), int(m.group(1)), int(m.group(2)))] = float(m.group(4))
    if len(rows) < 5000:
        print("注意：VIX は Yahoo Finance の値を使います（CBOE の公表値が取れませんでした）")
        return Y.fetch("VIX")["close"].dropna()
    return pd.Series(rows).sort_index()


def vix_features():
    v = vix_close()
    lr = np.log(v).diff()
    out = pd.DataFrame({"vix_rank": v.rolling(250).rank(pct=True) * 2 - 1, "vix_chg1": (lr / lr.rolling(250).std()).clip(-6, 6),
                        "vix_chg5": (np.log(v / v.shift(5)) / (lr.rolling(250).std() * np.sqrt(5))).clip(-6, 6)})
    return out


def one(name, d, klass, vix):
    d = d[["open", "high", "low", "close"]].astype(float).dropna()
    d = d[(d["close"] > 0) & (d["high"] >= d["low"])]
    f = FT.build(d)
    st = IR.rules(d)
    f["st_r2"], f["st_d7"], f["st_ibs"] = st["R2<10"].values, st["D7"].values, st["IBS"].values
    f["st_n"] = f["st_r2"] + f["st_d7"] + f["st_ibs"]
    vx = vix.reindex(vix.index.union(d.index)).ffill().shift(1).reindex(d.index)      # 1日前の VIX
    for k in vix.columns:
        f[k] = vx[k].values
    for k in ("index", "fx", "metal"):
        f[f"is_{k}"] = float(klass == k)
    c = d["close"]
    f["r_next"] = (c.shift(-1) / c - 1.0).values                 # 次の日の値動き（終値 → 次の終値）
    f["y"] = (np.log(c.shift(-1) / c) / f["sig"]).clip(-8, 8)
    f["up"] = (f["r_next"] > 0).astype(float).where(f["r_next"].notna())
    f["inst"], f["klass"] = name, klass
    # チャートを読むモデル用：直近 WIN 本の4本値（最後の終値を基準に、値動きの大きさでそろえる）
    lp = np.log(d[["open", "high", "low", "close"]].values)
    win = np.full((len(d), WIN, 4), np.nan, dtype=np.float32)
    if len(d) >= WIN:
        sw = np.lib.stride_tricks.sliding_window_view(lp, (WIN, 4))[:, 0]          # (T-WIN+1, WIN, 4)
        base = lp[WIN - 1:, 3][:, None, None]
        scale = (f["sig"].values[WIN - 1:] * 8.0)[:, None, None]
        win[WIN - 1:] = ((sw - base) / scale).astype(np.float32)
    f = f.reset_index().rename(columns={f.index.name or "index": "date"})
    f.columns = ["date"] + list(f.columns[1:])
    return f, win


def build(refresh=False):
    """戻り値：表（1行＝1銘柄の1日）と、同じ並びの「チャートの窓」（N × WIN × 4）。"""
    os.makedirs(CACHE, exist_ok=True)
    pq, npy = os.path.join(CACHE, "rows_v1.parquet"), os.path.join(CACHE, "win_v1.npy")
    if not refresh and os.path.exists(pq) and os.path.exists(npy):
        return pd.read_parquet(pq), np.load(npy, mmap_mode="r")
    vix = vix_features()
    parts, wins = [], []
    for nm in INDICES:
        f, w = one(nm, Y.fetch(nm), "index", vix)
        parts.append(f), wins.append(w)
        print(nm, len(f), flush=True)
    for nm in FX:
        f, w = one(nm, IC.day_bars(IC.load_any(nm), 17), "fx", vix)
        parts.append(f), wins.append(w)
        print(nm, len(f), flush=True)
    cm = os.environ.get("AMS_CM_EXPORT")
    cmd = IO.load(cm)[0] if cm and os.path.isdir(cm) else {}
    for sym, fut in METALS:
        d = cmd[sym] if sym in cmd else Y.fetch_ticker(fut, fut + "=F")
        f, w = one(sym, d, "metal", vix)
        parts.append(f), wins.append(w)
        print(sym, len(f), flush=True)
    ix = os.environ.get("AMS_IX_EXPORT")
    if ix and os.path.isdir(ix):
        for sym, d in IO.load(ix)[0].items():
            f, w = one("CFD_" + sym, d, "index", vix)
            parts.append(f), wins.append(w)
            print("CFD_" + sym, len(f), flush=True)
    rows = pd.concat(parts, ignore_index=True)
    win = np.concatenate(wins, axis=0)
    keep = (rows["sig"].notna() & rows["ret250"].notna() & rows["up"].notna()).values & ~np.isnan(win[:, 0, 0])
    rows, win = rows[keep].reset_index(drop=True), win[keep]
    rows.to_parquet(pq)
    np.save(npy, win)
    return rows, win


def build_etf(refresh=False):
    """学習だけに使う追加のチャート：米国の株式の ETF（市場全体・規模別・業種別の 21 本）。成績の評価には使わない。名前の頭に ETF_ を付ける。"""
    os.makedirs(CACHE, exist_ok=True)
    pq, npy = os.path.join(CACHE, "rows_etf_v1.parquet"), os.path.join(CACHE, "win_etf_v1.npy")
    if not refresh and os.path.exists(pq) and os.path.exists(npy):
        return pd.read_parquet(pq), np.load(npy, mmap_mode="r")
    vix = vix_features()
    parts, wins = [], []
    for nm in ETFS:
        d = Y.fetch(nm) if nm in Y.TICKERS else Y.fetch_ticker(nm, nm)
        f, w = one("ETF_" + nm, d, "index", vix)
        parts.append(f), wins.append(w)
        print("ETF_" + nm, len(f), str(f["date"].min())[:10], flush=True)
    rows = pd.concat(parts, ignore_index=True)
    win = np.concatenate(wins, axis=0)
    keep = (rows["sig"].notna() & rows["ret250"].notna() & rows["up"].notna()).values & ~np.isnan(win[:, 0, 0])
    rows, win = rows[keep].reset_index(drop=True), win[keep]
    rows.to_parquet(pq)
    np.save(npy, win)
    return rows, win


def feature_cols():
    return FT.names() + list(EXTRA)


if __name__ == "__main__":
    r, w = build(refresh=True)
    print(len(r), w.shape, r.groupby("klass").size().to_dict(), r["date"].min(), r["date"].max())
    print(r.groupby("inst")["date"].agg(["min", "max", "count"]).to_string())

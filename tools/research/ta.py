#!/usr/bin/env python3
"""テクニカル指標の特徴量（MT5 でも同じ計算ができるもの）。

- すべて「その足の始値の時点」で分かる値にする（= 1本前までの確定足から計算し、shift(1) する）。
- 値は銘柄をまたいで比べられるよう、ATR で割るか 0〜1 / -1〜1 の範囲にそろえる。
- 1時間足に加えて、4時間足・日足の指標も（確定した足だけを）1時間足に並べる。
"""
import numpy as np
import pandas as pd


def _atr(h, l, c, n):
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def _rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1.0 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1.0 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def _adx(h, l, c, n=14):
    up = h.diff()
    dn = -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = _atr(h, l, c, n)
    pdi = 100 * pd.Series(pdm, index=h.index).ewm(alpha=1.0 / n, adjust=False).mean() / atr
    ndi = 100 * pd.Series(ndm, index=h.index).ewm(alpha=1.0 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / n, adjust=False).mean(), (pdi - ndi) / 100


def indicators(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """確定足ごとの指標（shift なし。呼び出し側で並べ方を決める）。"""
    o, h, l, c = df["o"], df["h"], df["l"], df["c"]
    a = _atr(h, l, c, 14)
    f = pd.DataFrame(index=df.index)
    f[f"{prefix}rsi"] = _rsi(c, 14) / 100 - 0.5
    lo14, hi14 = l.rolling(14).min(), h.rolling(14).max()
    f[f"{prefix}stoch"] = (c - lo14) / (hi14 - lo14).replace(0, np.nan) - 0.5
    tp = (h + l + c) / 3
    sma_tp = tp.rolling(20).mean()
    mad = (tp - sma_tp).abs().rolling(20).mean()
    f[f"{prefix}cci"] = ((tp - sma_tp) / (0.015 * mad.replace(0, np.nan)) / 200).clip(-2, 2)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    f[f"{prefix}macd"] = macd / a
    f[f"{prefix}macdh"] = (macd - macd.ewm(span=9, adjust=False).mean()) / a
    for n in (20, 50, 200):
        e = c.ewm(span=n, adjust=False).mean()
        f[f"{prefix}ema{n}_d"] = (c - e) / a
        f[f"{prefix}ema{n}_s"] = (e - e.shift(5)) / a
    sma, sd = c.rolling(20).mean(), c.rolling(20).std()
    f[f"{prefix}bb_pb"] = ((c - sma) / (2 * sd.replace(0, np.nan))).clip(-3, 3)
    f[f"{prefix}bb_w"] = (4 * sd / a)
    adx, di = _adx(h, l, c, 14)
    f[f"{prefix}adx"] = adx / 100
    f[f"{prefix}di"] = di
    for n in (20, 55):
        hh, ll = h.rolling(n).max(), l.rolling(n).min()
        f[f"{prefix}don{n}"] = (c - ll) / (hh - ll).replace(0, np.nan) - 0.5
    # 一目均衡表：雲（26本先に描く値＝26本前に計算した値）との位置
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    spa = ((tenkan + kijun) / 2).shift(26)
    spb = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    top, bot = np.maximum(spa, spb), np.minimum(spa, spb)
    f[f"{prefix}kumo"] = np.where(c > top, (c - top) / a, np.where(c < bot, (c - bot) / a, 0.0))
    f[f"{prefix}tk"] = (tenkan - kijun) / a
    # ローソク足の形（実体の比率、上ヒゲ・下ヒゲ）
    rng = (h - l).replace(0, np.nan)
    f[f"{prefix}body"] = (c - o) / rng
    f[f"{prefix}uw"] = (h - np.maximum(o, c)) / rng
    f[f"{prefix}lw"] = (np.minimum(o, c) - l) / rng
    f[f"{prefix}atr_rel"] = a / a.rolling(100).mean()
    return f


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"o": "first", "h": "max", "l": "min", "c": "last"}
    return df[["o", "h", "l", "c"]].resample(rule, label="left", closed="left").agg(agg).dropna()


def ta_features(base: pd.DataFrame) -> pd.DataFrame:
    """1時間足 base（UTC の index）に、H1・H4・D1 の指標を「足の始値の時点で分かる値」として並べる。"""
    out = [indicators(base, "h1_").shift(1)]            # 1本前の確定足まで
    for rule, pre in (("4h", "h4_"), ("1D", "d1_")):
        hi = resample(base, rule)
        ind = indicators(hi, pre)
        # 上位足の足は、その足が終わった時刻（= 次の足の始まり）から使える
        ind.index = ind.index + pd.Timedelta(rule)
        out.append(ind.reindex(base.index, method="ffill"))
    f = pd.concat(out, axis=1)
    # 当日（UTC）の始値からの位置、前日の高安からの位置
    day = base.index.floor("1D")
    d1 = resample(base, "1D")
    prev = d1.shift(1).reindex(day)
    prev.index = base.index
    a = _atr(base["h"], base["l"], base["c"], 24).shift(1)
    c1 = base["c"].shift(1)
    dopen = base["o"].groupby(day).transform("first")
    f["day_from_open"] = (c1 - dopen) / a
    f["pd_pos"] = (c1 - prev["l"]) / (prev["h"] - prev["l"]).replace(0, np.nan) - 0.5
    return f

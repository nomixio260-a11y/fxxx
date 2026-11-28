#!/usr/bin/env python3
"""複合システム：値動きの「見方」を、すべて数値（特徴量）にする。日付・時刻・曜日は使わない。

- 入力は日足（open・high・low・close）だけ。どの値も、その足の終値までの情報だけで決まる（未来の値は使わない）。
- 値段の水準や銘柄の値動きの大きさに左右されないよう、値動きの大きさ（σ：直近20日の値動きの標準偏差）や ATR で割ってそろえる。
- 参考にしたもの：
   既存の手法 … 売られすぎの戻り（RSI(2)・7日の安値・IBS。93章）、順張り（200日の平均。104章）、値動きの見積もり（98章）
   TradingView の公開インジケータ … SuperTrend、Squeeze Momentum［LazyBear］、WaveTrend［LazyBear］、UT Bot Alerts（ATR の追従線）、SSL Channel、QQE、
     Hull 移動平均、Chandelier Exit、一目均衡表、パラボリック SAR、ドンチャン、ケルトナー、平均足 など
   定番の指標 … RSI・ストキャスティクス・MACD・CCI・ADX/DMI・アルーン・ボリンジャーバンド・ウィリアムズ %R・TSI・フィッシャー変換・オーサム・オシレーター
   ローソク足の形 … 実体とヒゲの割合、連続して上げた・下げた日数、飛び（窓）
- 戻り値：特徴量の DataFrame（列の名前は FEATURES の順）。使い方は tools/eco/dataset.py。
"""
import numpy as np
import pandas as pd


def _ema(x, n):
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def _rma(x, n):
    return x.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def _rsi(c, n):
    d = c.diff()
    up, dn = _rma(d.clip(lower=0), n), _rma((-d).clip(lower=0), n)
    return 100.0 - 100.0 / (1.0 + up / dn.replace(0, np.nan))


def _wma(x, n):
    w = np.arange(1, n + 1, dtype=float)
    return x.rolling(n).apply(lambda v: np.dot(v, w) / w.sum(), raw=True)


def _streak(sign):
    """同じ符号が続いた本数（符号つき）。"""
    s = sign.fillna(0.0).values
    out = np.zeros(len(s))
    for i in range(1, len(s)):
        out[i] = out[i - 1] + s[i] if (s[i] != 0 and np.sign(out[i - 1]) == s[i]) else s[i]
    return pd.Series(out, index=sign.index)


def _trail(c, up_line, dn_line):
    """SuperTrend 型の追従線。up_line：下側の線の候補、dn_line：上側の線の候補。戻り値：向き（+1/−1）、線の値。"""
    cv, uv, dv = c.values, up_line.values, dn_line.values
    n = len(cv)
    dirn, line = np.zeros(n), np.full(n, np.nan)
    fu, fd, d = np.nan, np.nan, 1.0
    for i in range(n):
        if np.isnan(uv[i]) or np.isnan(dv[i]):
            continue
        if np.isnan(fu):
            fu, fd = uv[i], dv[i]
        else:
            fu = max(uv[i], fu) if cv[i - 1] > fu else uv[i]
            fd = min(dv[i], fd) if cv[i - 1] < fd else dv[i]
            if d > 0 and cv[i] < fu:
                d = -1.0
            elif d < 0 and cv[i] > fd:
                d = 1.0
        dirn[i], line[i] = d, (fu if d > 0 else fd)
    return pd.Series(dirn, index=c.index), pd.Series(line, index=c.index)


def _psar(h, l, af0=0.02, afmax=0.2):
    hv, lv = h.values, l.values
    n = len(hv)
    sar, dirn = np.full(n, np.nan), np.zeros(n)
    if n < 3:
        return pd.Series(dirn, index=h.index), pd.Series(sar, index=h.index)
    up, ep, af, s = True, hv[0], af0, lv[0]
    for i in range(1, n):
        s = s + af * (ep - s)
        if up:
            s = min(s, lv[i - 1], lv[i - 2] if i > 1 else lv[i - 1])
            if lv[i] < s:
                up, s, ep, af = False, ep, lv[i], af0
            elif hv[i] > ep:
                ep, af = hv[i], min(af + af0, afmax)
        else:
            s = max(s, hv[i - 1], hv[i - 2] if i > 1 else hv[i - 1])
            if hv[i] > s:
                up, s, ep, af = True, ep, hv[i], af0
            elif lv[i] < ep:
                ep, af = lv[i], min(af + af0, afmax)
        sar[i], dirn[i] = s, (1.0 if up else -1.0)
    return pd.Series(dirn, index=h.index), pd.Series(sar, index=h.index)


def build(d):
    """d：日足（open, high, low, close）。戻り値：特徴量（その足の終値の時点）。"""
    o, h, l, c = (d[k].astype(float) for k in ("open", "high", "low", "close"))
    r = np.log(c).diff()
    sig = r.rolling(20).std().clip(lower=1e-5)                      # 1日の値動きの大きさ
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = _rma(tr, 14).clip(lower=c * 1e-5)
    hl2, hlc3 = (h + l) / 2.0, (h + l + c) / 3.0
    F = {}
    # ---------- 値動き（勢い・戻り）
    for n in (1, 2, 3, 5, 10, 20, 60, 120, 250):
        F[f"ret{n}"] = (np.log(c) - np.log(c.shift(n))) / (sig * np.sqrt(n))
    for n in (5, 10, 20, 50, 100, 200):
        F[f"ma{n}"] = (c / c.rolling(n).mean() - 1.0) / (sig * np.sqrt(n))
    F["above200"] = (c > c.rolling(200).mean()).astype(float).where(c.rolling(200).mean().notna())
    F["ma50_200"] = (c.rolling(50).mean() / c.rolling(200).mean() - 1.0) / (sig * np.sqrt(200))
    # ---------- オシレーター
    for n in (2, 5, 14):
        F[f"rsi{n}"] = _rsi(c, n) / 50.0 - 1.0
    lo14, hi14 = l.rolling(14).min(), h.rolling(14).max()
    k = (c - lo14) / (hi14 - lo14).replace(0, np.nan)
    F["stoch_k"] = k * 2 - 1
    F["stoch_d"] = k.rolling(3).mean() * 2 - 1
    r14 = _rsi(c, 14)
    sr = (r14 - r14.rolling(14).min()) / (r14.rolling(14).max() - r14.rolling(14).min()).replace(0, np.nan)
    F["stochrsi"] = sr.rolling(3).mean() * 2 - 1
    F["willr"] = ((hi14 - c) / (hi14 - lo14).replace(0, np.nan)) * -2 + 1
    tp_ma = hlc3.rolling(20).mean()
    F["cci"] = ((hlc3 - tp_ma) / (0.015 * (hlc3 - tp_ma).abs().rolling(20).mean().replace(0, np.nan))).clip(-300, 300) / 100.0
    macd = _ema(c, 12) - _ema(c, 26)
    F["macd"] = macd / atr
    F["macd_hist"] = (macd - _ema(macd, 9)) / atr
    m = c.diff()
    F["tsi"] = _ema(_ema(m, 25), 13) / _ema(_ema(m.abs(), 25), 13).replace(0, np.nan)
    F["ao"] = (hl2.rolling(5).mean() - hl2.rolling(34).mean()) / atr
    hh, ll = hl2.rolling(10).max(), hl2.rolling(10).min()
    v = (2 * ((hl2 - ll) / (hh - ll).replace(0, np.nan) - 0.5)).clip(-0.999, 0.999)
    v = v.ewm(alpha=0.33, adjust=False).mean().clip(-0.999, 0.999)
    F["fisher"] = (0.5 * np.log((1 + v) / (1 - v))).ewm(alpha=0.5, adjust=False).mean()
    esa = _ema(hlc3, 10)                                            # WaveTrend［LazyBear］
    ci = (hlc3 - esa) / (0.015 * _ema((hlc3 - esa).abs(), 10).replace(0, np.nan))
    wt1 = _ema(ci, 21)
    F["wt1"] = wt1 / 60.0
    F["wt_cross"] = (wt1 - wt1.rolling(4).mean()) / 20.0
    rs = _ema(r14, 5)                                               # QQE：ならした RSI と、その追従線
    dar = _ema(_ema(rs.diff().abs(), 27), 27) * 4.236
    qd, ql = _trail(rs, rs - dar, rs + dar)
    F["qqe"] = qd.where(dar.notna())
    F["qqe_dist"] = ((rs - ql) / 10.0).clip(-5, 5)
    # ---------- 流れ（トレンド）の強さと向き
    up_m, dn_m = h.diff(), -l.diff()
    pdm = up_m.where((up_m > dn_m) & (up_m > 0), 0.0)
    mdm = dn_m.where((dn_m > up_m) & (dn_m > 0), 0.0)
    pdi, mdi = 100 * _rma(pdm, 14) / atr, 100 * _rma(mdm, 14) / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    F["adx"] = _rma(dx, 14) / 25.0 - 1.0
    F["di_diff"] = (pdi - mdi) / 25.0
    F["aroon"] = (h.rolling(26).apply(np.argmax, raw=True) - l.rolling(26).apply(np.argmin, raw=True)) / 25.0
    st_d, st_l = _trail(c, hl2 - 3 * _rma(tr, 10), hl2 + 3 * _rma(tr, 10))                 # SuperTrend(10, 3)
    F["supertrend"] = st_d.where(st_l.notna())
    F["supertrend_dist"] = ((c - st_l) / atr).clip(-10, 10)
    ut_d, ut_l = _trail(c, c - 1.0 * _rma(tr, 10), c + 1.0 * _rma(tr, 10))                 # UT Bot Alerts（ATR の追従線）
    F["utbot"] = ut_d.where(ut_l.notna())
    ce_d, ce_l = _trail(c, h.rolling(22).max() - 3 * _rma(tr, 22), l.rolling(22).min() + 3 * _rma(tr, 22))   # Chandelier Exit(22, 3)
    F["chandelier"] = ce_d.where(ce_l.notna())
    F["chandelier_dist"] = ((c - ce_l) / atr).clip(-10, 10)
    ps_d, ps_l = _psar(h, l)
    F["psar"] = ps_d.where(ps_l.notna())
    F["psar_dist"] = ((c - ps_l) / atr).clip(-10, 10)
    sh, sl_ = h.rolling(10).mean(), l.rolling(10).mean()            # SSL Channel
    hlv = pd.Series(np.where(c > sh, 1.0, np.where(c < sl_, -1.0, np.nan)), index=c.index).ffill()
    F["ssl"] = hlv
    hull = _wma(2 * _wma(c, 10) - _wma(c, 20), 4)                   # Hull 移動平均(20)
    F["hull_slope"] = hull.diff() / atr
    F["hull_dist"] = (c - hull) / atr
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2          # 一目均衡表
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    spa = ((tenkan + kijun) / 2).shift(26)
    spb = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    top, bot = pd.concat([spa, spb], axis=1).max(axis=1), pd.concat([spa, spb], axis=1).min(axis=1)
    F["ichi_tk"] = (tenkan - kijun) / atr
    F["ichi_kijun"] = (c - kijun) / atr
    F["ichi_cloud"] = pd.Series(np.where(c > top, 1.0, np.where(c < bot, -1.0, 0.0)), index=c.index).where(top.notna())
    F["ichi_cloud_dist"] = ((c - (top + bot) / 2) / atr).clip(-15, 15)
    F["ichi_chikou"] = (c - c.shift(26)) / (atr * 5)
    for n in (20, 55):
        hn, ln = h.rolling(n).max(), l.rolling(n).min()
        F[f"donch{n}"] = ((c - ln) / (hn - ln).replace(0, np.nan)) * 2 - 1
    ha_c = (o + h + l + c) / 4                                       # 平均足
    ha_o = ha_c.copy()
    hov, hcv = ha_o.values.copy(), ha_c.values
    for i in range(1, len(hov)):
        hov[i] = (hov[i - 1] + hcv[i - 1]) / 2
    F["heikin_streak"] = _streak(pd.Series(np.sign(hcv - hov), index=c.index)).clip(-10, 10) / 5.0
    # ---------- 値動きの大きさ（広がり・縮み）
    ma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    F["bb_pos"] = ((c - ma20) / (2 * sd20).replace(0, np.nan)).clip(-3, 3)
    bw = (4 * sd20 / ma20)
    F["bb_width"] = np.log(bw / bw.rolling(250).median()).clip(-3, 3)
    kc_mid, kc_rng = _ema(c, 20), _rma(tr, 20)
    F["kc_pos"] = ((c - kc_mid) / (1.5 * kc_rng)).clip(-4, 4)
    F["squeeze_on"] = ((ma20 + 2 * sd20 < kc_mid + 1.5 * kc_rng) & (ma20 - 2 * sd20 > kc_mid - 1.5 * kc_rng)).astype(float).where(sd20.notna())
    base = c - ((h.rolling(20).max() + l.rolling(20).min()) / 2 + ma20) / 2       # Squeeze Momentum［LazyBear］
    x = np.arange(20, dtype=float)
    xm = x - x.mean()
    F["squeeze_mom"] = (base.rolling(20).apply(lambda v_: v_.mean() + np.dot(xm, v_ - v_.mean()) / np.dot(xm, xm) * 9.5, raw=True) / atr).clip(-10, 10)
    F["atr_ratio"] = np.log((atr / c) / (atr / c).rolling(250).median()).clip(-3, 3)
    F["vol_5_60"] = np.log(r.rolling(5).std() / r.rolling(60).std()).clip(-3, 3)
    F["vol_20_250"] = np.log(r.rolling(20).std() / r.rolling(250).std()).clip(-3, 3)
    F["range_today"] = ((h - l) / atr).clip(0, 6)
    F["gap"] = ((o - pc) / atr).clip(-5, 5)
    # ---------- ローソク足の形・位置
    rng = (h - l).replace(0, np.nan)
    F["ibs"] = ((c - l) / rng).fillna(0.5) * 2 - 1
    F["body"] = ((c - o) / rng).fillna(0.0)
    F["upper_wick"] = ((h - pd.concat([o, c], axis=1).max(axis=1)) / rng).fillna(0.0)
    F["lower_wick"] = ((pd.concat([o, c], axis=1).min(axis=1) - l) / rng).fillna(0.0)
    F["streak"] = _streak(np.sign(r)).clip(-8, 8) / 4.0
    F["dd250"] = (np.log(c / c.rolling(250).max()) / (sig * np.sqrt(60))).clip(-10, 0)
    F["dd20"] = (np.log(c / h.rolling(20).max()) / (sig * np.sqrt(10))).clip(-10, 0)
    F["up20"] = (np.log(c / l.rolling(20).min()) / (sig * np.sqrt(10))).clip(0, 10)
    piv = (h.shift(1) + l.shift(1) + pc) / 3
    F["pivot"] = ((c - piv) / atr).clip(-5, 5)
    # ---------- 既存のルールの状態（93章と同じ定義）
    ma200, ma5 = c.rolling(200).mean(), c.rolling(5).mean()
    F["rule_r2"] = ((_rsi(c, 2) < 10) & (c > ma200)).astype(float)
    F["rule_d7"] = ((c <= c.rolling(7).min()) & (c > ma200)).astype(float)
    F["rule_ibs"] = (((c - l) / rng).fillna(0.5) < 0.2).astype(float)
    F["rule_n"] = F["rule_r2"] + F["rule_d7"] + F["rule_ibs"]
    out = pd.DataFrame(F)
    out = out.replace([np.inf, -np.inf], np.nan).clip(-15, 15)
    out["sig"] = sig                                                 # 値動きの大きさ（特徴量ではなく、建玉と目的変数に使う）
    return out


FEATURES = None


def names():
    global FEATURES
    if FEATURES is None:
        idx = pd.date_range("2000-01-03", periods=400, freq="B")
        rs = np.random.default_rng(0)
        cl = 100 * np.exp(np.cumsum(rs.normal(0, 0.01, 400)))
        dd = pd.DataFrame({"open": cl * (1 + rs.normal(0, 0.002, 400)), "close": cl}, index=idx)
        dd["high"] = dd[["open", "close"]].max(axis=1) * 1.004
        dd["low"] = dd[["open", "close"]].min(axis=1) * 0.996
        FEATURES = [x for x in build(dd).columns if x != "sig"]
    return FEATURES


if __name__ == "__main__":
    print(len(names()), names())

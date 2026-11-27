#!/usr/bin/env python3
"""研究：株価指数の「売られすぎの戻り」で、損失（最悪の日・最大の下落）を小さくする方法を比べる。

- 93章の層（米国3指数 × R2・D7・IBS）は、26年でシャープ +0.62 だが、1日で大きく負ける日がある
  （値動きを年10%にそろえたとき、2018年2月5日に −10.7%）。原因は、直前の値動きが異常に小さく、建玉が大きくなっていたこと。
- ここでは、**利益の出どころ（ルール）は変えず**、建玉の決め方と持ち方だけを変えて、同じ物差しで比べる：
  A 値動きの見積もり：直近60日だけ／下限を付ける（その指数の過去の中央値）／短い・中くらい・長い期間の最大／速い見積もり（EWMA）も合わせた最大／VIX も合わせた最大
  B ルールがそろった数での重み：1つ・2つ・3つ → 1:2:3（今の形）／0:1:2／0:1:3／0:0:1 など
  C 建玉の合計の上限：3指数の建玉の合計を、口座の X 倍までに抑える
  D 損切り：持ってからの下げが k% を超えたら手じまい、すべてのルールが出るまで休む
  E 条件：IBS も200日の平均より上のときだけ／持つ日数の上限
- 物差し（すべて、全期間の値動きを年10%にそろえたあとの値）：
  年率シャープ、t 値、最悪の日、下位1%の日の平均（CVaR）、最大の下落、最悪の月・年、期間ごとのシャープ。
  「同じ値動きの大きさ（年10%）で比べて、最悪の日と下落が小さく、シャープが落ちない」ものが良い形。
使い方: python3 tools/research/index_risk.py  → reports/research/index_risk.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
START = "2000-10-01"
US3 = ["S&P500", "NASDAQ100", "ダウ"]
VIXOF = {"S&P500": "VIX", "NASDAQ100": "VXN", "ダウ": "VIX"}
PER = (("2000〜08", START, "2009-01-01"), ("2009〜14", "2009-01-01", "2015-01-01"), ("2015〜21/10", "2015-01-01", "2021-11-01"),
       ("21/11〜26/11", "2021-11-01", "2026-12-01"))
_cache = {}


def load(name):
    if name in _cache:
        return _cache[name]
    yn, ccy, div, _ = IR.INDEX[name]
    d = Y.fetch(yn)
    d = d[d.index >= "1990-01-01"].copy()
    r = IR.rules(d)
    st = pd.DataFrame({"R2": r["R2<10"], "D7": r["D7"], "IBS": r["IBS"]})
    rate = IR.short_rate(ccy, d.index)
    ret = d["close"].pct_change()
    vols = pd.DataFrame(index=d.index)
    vols["v20"] = ret.rolling(20, min_periods=15).std() * np.sqrt(ANN)
    vols["v60"] = ret.rolling(60, min_periods=40).std() * np.sqrt(ANN)
    vols["v250"] = ret.rolling(250, min_periods=150).std() * np.sqrt(ANN)
    vols["ewma"] = np.sqrt((ret ** 2).ewm(alpha=0.06, adjust=False).mean() * ANN)           # RiskMetrics（λ = 0.94）
    vols["lr"] = vols["v60"].expanding(min_periods=500).median()                              # その指数の、過去の値動きの中央値（その日までの値だけ）
    try:
        vx = Y.fetch(VIXOF[name])["close"] / 100.0
        vols["vix"] = vx.reindex(vx.index.union(d.index)).ffill(limit=3).reindex(d.index)
    except Exception:  # noqa: BLE001
        vols["vix"] = np.nan
    # 翌日の値動きの大きさの見積もり（index_vol_forecast.py が保存したもの。年率の標準偏差に直す）
    fc = os.path.join(D.CACHE, f"volfc_{yn}.parquet")
    if os.path.exists(fc):
        f = pd.read_parquet(fc).reindex(d.index)
        for k in ("har", "harvix", "ewma85"):
            vols[k] = np.sqrt(f[k].clip(lower=0) * ANN)
        vols["har"] = vols["har"].fillna(vols["ewma"])              # 係数が決まる前の時期は、指数平滑で代用
        vols["harvix"] = vols["harvix"].fillna(vols["har"])
    above = d["close"] > d["close"].rolling(200).mean()
    _cache[name] = (d, st, rate, div, vols, above)
    return _cache[name]


def sigma(vols, kind):
    if kind == "v60":
        s = vols["v60"]
    elif kind == "floor":
        s = np.maximum(vols["v60"], vols["lr"].fillna(0.0))
    elif kind == "max3":
        s = vols[["v20", "v60", "v250"]].max(axis=1)
    elif kind == "max3e":
        s = vols[["v20", "v60", "v250", "ewma"]].max(axis=1)
    elif kind == "max3e_floor":
        s = np.maximum(vols[["v20", "v60", "v250", "ewma"]].max(axis=1), vols["lr"].fillna(0.0))
    elif kind == "vix":
        s = np.maximum(vols["v60"], vols["vix"].fillna(0.0))
    elif kind == "max3e_vix":
        s = np.maximum(vols[["v20", "v60", "v250", "ewma"]].max(axis=1), vols["vix"].fillna(0.0))
    elif kind in ("har", "har_floor", "har_max60", "ewma85", "harvix"):
        s = vols[{"har_floor": "har", "har_max60": "har"}.get(kind, kind)]
        if kind == "har_floor":
            s = np.maximum(s, vols["lr"].fillna(0.0))
        if kind == "har_max60":
            s = np.maximum(s, vols["v60"])
    else:
        raise ValueError(kind)
    return s.clip(lower=0.025)


def count_with_rules(d, st, above, ibs_filter=False, max_hold=None, stop=None):
    """持っているルールの数 n（0〜3）。損切り・持つ日数の上限・IBS の条件を入れる。"""
    s = st.copy()
    if ibs_filter:
        s["IBS"] = s["IBS"].where(above, 0.0)
    n = s.sum(axis=1)
    if max_hold is None and stop is None:
        return n
    c = d["close"].values
    nv = n.values.copy()
    held, entry, blocked = 0, np.nan, False
    for i in range(len(nv)):
        if nv[i] == 0:
            held, blocked, entry = 0, False, np.nan
            continue
        if blocked:
            nv[i] = 0
            continue
        if held == 0:
            entry = c[i]
        held += 1
        if (stop is not None and c[i] <= entry * (1.0 - stop)) or (max_hold is not None and held > max_hold):
            nv[i] = 0
            blocked = True                     # すべてのルールが出る（n = 0 になる）まで休む
    return pd.Series(nv, index=n.index)


def simulate(vol="v60", g=(0, 1, 2, 3), cap=None, ibs_filter=False, max_hold=None, stop=None, names=US3, cost=IR.COST):
    """層の日次の損益（全期間を年10%にそろえる前の値）と、建玉の合計（口座に対する倍率）。"""
    gmax = float(max(g))
    W, parts = {}, {}
    for name in names:
        d, st, rate, div, vols, above = load(name)
        n = count_with_rules(d, st, above, ibs_filter, max_hold, stop)
        gw = n.map({0: g[0], 1: g[1], 2: g[2], 3: g[3]}).astype(float) / gmax
        W[name] = gw * (0.10 / sigma(vols, vol)).clip(upper=4.0).fillna(0.0) / len(names)
        parts[name] = (d, rate, div)
    Wd = pd.DataFrame(W).fillna(0.0)
    if cap is not None:
        tot = Wd.sum(axis=1)
        Wd = Wd.mul((cap / tot).clip(upper=1.0).fillna(1.0), axis=0)
    out = []
    for name in names:
        d, rate, div = parts[name]
        w = Wd[name].reindex(d.index).fillna(0.0)
        held = w.shift(1).fillna(0.0)
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
        fin = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
        out.append(held * (d["close"].pct_change().fillna(0.0) + fin) - (w - held).abs() * cost)
    r = pd.concat(out, axis=1).fillna(0.0).sum(axis=1)
    return r[r.index >= START], Wd.sum(axis=1)[Wd.index >= START]


def metrics(r, gross):
    k = 0.10 / (r.std() * np.sqrt(ANN))
    z = r * k
    sh = z.mean() / z.std() * np.sqrt(ANN)
    eq = (1 + z).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    q = z.quantile(0.01)
    cvar = z[z <= q].mean()
    mo = z.groupby(z.index.to_period("M")).sum()
    yr = z.groupby(z.index.year).sum()
    per = [z[(z.index >= a) & (z.index < b)] for _, a, b in PER]
    pers = [x.mean() / x.std() * np.sqrt(ANN) for x in per]
    g = gross * k
    return dict(sh=sh, t=sh * np.sqrt(len(z) / ANN), worst=z.min(), wday=z.idxmin(), cvar=cvar, dd=dd, wmo=mo.min(), wyr=yr.min(), pos=(yr > 0).sum(), nyr=len(yr),
                pers=pers, gmax=g.max(), gavg=g[g > 0].mean(), kurt=z.kurt(), k=k, z=z)


HEAD = ("| 形 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の月 | 最悪の年 | プラスの年 | " + " | ".join(p[0] for p in PER)
        + " | 建玉の合計の最大（倍） |")
SEP = "|---|" + "---|" * (9 + len(PER) + 1)


def row(label, r, gross):
    m = metrics(r, gross)
    return (f"| {label} | {m['sh']:+.2f} | {m['t']:+.1f} | {m['worst'] * 100:.1f}%（{m['wday'].date()}） | {m['cvar'] * 100:.2f}% | {m['dd'] * 100:.0f}% | {m['wmo'] * 100:.1f}% | "
            f"{m['wyr'] * 100:.1f}% | {m['pos']}/{m['nyr']} | " + " | ".join(f"{x:+.2f}" for x in m["pers"]) + f" | {m['gmax']:.1f} |"), m


def main():
    lines = ["# 研究：売られすぎの戻りで、損失を小さくする方法（`tools/research/index_risk.py`）", "",
             f"米国3指数 × R2・D7・IBS、{START}〜2026年11月、CFD のコスト込み。**どの形も、全期間の値動きを年10%にそろえてから比べる**",
             "（建玉を小さくすれば損が小さくなるのは当たり前なので、同じ値動きの大きさで、最悪の日・下落がどれだけ違うかを見る）。", ""]
    keep = {}

    def block(title, forms):
        lines.extend([f"## {title}", "", HEAD, SEP])
        for label, kw in forms:
            r, g = simulate(**kw)
            line, m = row(label, r, g)
            lines.append(line)
            keep[label] = m
            print(line, flush=True)
        lines.append("")
    block("A 値動きの見積もり（建玉 = 目標 ÷ 見積もり）", [
        ("直近60日だけ（今の形）", dict(vol="v60")),
        ("下限を付ける（その指数の過去の中央値）", dict(vol="floor")),
        ("20日・60日・250日の最大", dict(vol="max3")),
        ("20日・60日・250日・速い見積もり（EWMA）の最大", dict(vol="max3e")),
        ("同上 ＋ 過去の中央値の下限", dict(vol="max3e_floor")),
        ("直近60日と VIX の大きいほう", dict(vol="vix")),
        ("20日・60日・250日・EWMA・VIX の最大", dict(vol="max3e_vix")),
        ("速い指数平滑（λ = 0.85）", dict(vol="ewma85")),
        ("HAR 型（当日・5日・22日の値幅から。値段だけで計算できる）", dict(vol="har")),
        ("HAR 型 ＋ 過去の中央値の下限", dict(vol="har_floor")),
        ("HAR 型と直近60日の大きいほう", dict(vol="har_max60")),
        ("HAR 型 ＋ VIX", dict(vol="harvix"))])
    block("B ルールがそろった数での重み（値動きの見積もりは「20日・60日・250日・EWMA の最大」）", [
        ("1つ:2つ:3つ = 1:2:3（今の形）", dict(vol="max3e", g=(0, 1, 2, 3))),
        ("0:1:2（1つだけの日は持たない）", dict(vol="max3e", g=(0, 0, 1, 2))),
        ("0:1:3", dict(vol="max3e", g=(0, 0, 1, 3))),
        ("0:2:3", dict(vol="max3e", g=(0, 0, 2, 3))),
        ("0:1:1（2つ以上なら同じ大きさ）", dict(vol="max3e", g=(0, 0, 1, 1))),
        ("0:0:1（3つそろったときだけ）", dict(vol="max3e", g=(0, 0, 0, 1))),
        ("1:1:1（1つでも出たら同じ大きさ）", dict(vol="max3e", g=(0, 1, 1, 1)))])
    block("C 建玉の合計の上限（0:1:2、値動きの見積もりは同じ）。上限は、年10%にそろえる前の倍率", [
        ("上限なし", dict(vol="max3e", g=(0, 0, 1, 2))),
        ("合計 0.6 倍まで", dict(vol="max3e", g=(0, 0, 1, 2), cap=0.6)),
        ("合計 0.45 倍まで", dict(vol="max3e", g=(0, 0, 1, 2), cap=0.45)),
        ("合計 0.3 倍まで", dict(vol="max3e", g=(0, 0, 1, 2), cap=0.3))])
    block("D 損切り・持つ日数の上限（0:1:2、値動きの見積もりは同じ）", [
        ("なし", dict(vol="max3e", g=(0, 0, 1, 2))),
        ("持ってから −3% で手じまい", dict(vol="max3e", g=(0, 0, 1, 2), stop=0.03)),
        ("持ってから −5% で手じまい", dict(vol="max3e", g=(0, 0, 1, 2), stop=0.05)),
        ("持ってから −8% で手じまい", dict(vol="max3e", g=(0, 0, 1, 2), stop=0.08)),
        ("最長10日で手じまい", dict(vol="max3e", g=(0, 0, 1, 2), max_hold=10)),
        ("最長5日で手じまい", dict(vol="max3e", g=(0, 0, 1, 2), max_hold=5))])
    block("E IBS の条件（0:1:2、値動きの見積もりは同じ）", [
        ("IBS は条件なし（今の形）", dict(vol="max3e", g=(0, 0, 1, 2))),
        ("IBS も200日の平均より上のときだけ", dict(vol="max3e", g=(0, 0, 1, 2), ibs_filter=True))])
    out = os.path.join(F.ROOT, "reports", "research", "index_risk.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    pd.DataFrame({k: v["z"] for k, v in keep.items()}).to_parquet(os.path.join(D.CACHE, "index_risk_returns.parquet"))


if __name__ == "__main__":
    main()

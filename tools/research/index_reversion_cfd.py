#!/usr/bin/env python3
"""研究：株価指数の「売られすぎの戻り」が、CFD の24時間の値段（1分足）で、EA が実際に売買できる形でも残るか。

- index_reversion.py は、現物の指数の日足（終値）で確かめた。CFD は24時間近く動き、MT5 の日足の区切りは現物の終値（NY 16:00）ではない。
  そこで、histdata の CFD の1分足（S&P500 など）から日足を作り直し、売買の値段も CFD の値段で確かめる。
- 日足の作り方と売買の値段（どれも、判定に使った足が閉じたあとの、最初の値段で売買する）：
  A MT5 の日足そのまま：NY 17:00 で区切る（サーバーの日付）。判定の次の日足の最初の値段（NY 18:00 の再開の直後）で売買
  B 現物の終値で区切る：NY 16:00 で区切る24時間の足。判定の直後（NY 16:00 過ぎ）の最初の値段で売買
- ルールは index_reversion.py と同じ（R2<10・D7・IBS。数値は公表されたまま）。
- コスト：売買は片道 0.02%（S&P500 が 7,000 のとき 1.4 ポイント。業者の通常のスプレッド 0.5 ポイント前後より厳しめ）、
  持ち越しは 短期金利＋年2.5% を払い配当を受け取る。建玉は口座の100%。
使い方: python3 tools/research/index_reversion_cfd.py  → reports/research/index_reversion_cfd.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402

# 名前: (histdata の銘柄, 通貨, 配当の目安, 現物の終値の NY 時刻からのずれ（時間。B の区切りに使う）)
CFD = {"S&P500": ("SPXUSD", "USD", 1.5), "NASDAQ100": ("NSXUSD", "USD", 0.7), "日経225": ("JPXJPY", "JPY", 1.7),
       "DAX": ("GRXEUR", "EUR", 0.0), "FTSE100": ("UKXGBP", "GBP", 3.5)}
PER = (("2010〜2014", "2010-01-01", "2015-01-01"), ("2015〜21/10", "2015-01-01", "2021-11-01"), ("21/11〜24/10", "2021-11-01", "2024-11-01"),
       ("24/11〜25/10", "2024-11-01", "2025-11-01"), ("25/11〜26/10", "2025-11-01", "2026-12-01"))


def read_csv_m1(src):
    """tools/fetch_histdata.sh の出力（時刻は NY + 7時間）を読み、UTC の1分足にする。結果は data/cache に置く。"""
    cache = os.path.join(D.CACHE, os.path.basename(src).replace(".csv", ".parquet"))
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    df = pd.read_csv(src, header=None, names=["d", "t", "o", "h", "l", "c", "v"], dtype={"d": str, "t": str})
    ny = pd.DatetimeIndex(pd.to_datetime(df["d"] + " " + df["t"], format="%Y.%m.%d %H:%M") - pd.Timedelta(hours=7))
    utc = ny.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT").tz_convert("UTC").tz_localize(None)
    keep = ~pd.isna(utc)
    e = pd.DataFrame({"o": df["o"].values[keep], "h": df["h"].values[keep], "l": df["l"].values[keep], "c": df["c"].values[keep]},
                     index=pd.DatetimeIndex(utc[keep], name="utc"))
    e = e[~e.index.duplicated()].sort_index()
    os.makedirs(D.CACHE, exist_ok=True)
    e.to_parquet(cache)
    return e


def load_any(pair):
    """その銘柄の1分足（UTC）。2015年からのファイルと、それより前のファイルがあれば、つなぐ。なければ None。"""
    parts = []
    for name in (f"{pair}_M1_2010.csv", f"{pair}_M1_2010_2014.csv", f"{pair}_M1_2009.csv"):
        src = os.path.join(D.DATA, name)
        if os.path.exists(src):
            parts.append(read_csv_m1(src))
    if os.path.exists(os.path.join(D.DATA, f"{pair}_M1_2015.csv")):
        m = D.load_m1(pair)
        parts = [x[x.index < m.index[0]] for x in parts] + [m]
    if not parts:
        return None
    out = pd.concat(parts).sort_index()
    return out[~out.index.duplicated()]


def day_bars(m, cut_hour_ny):
    """NY の cut_hour_ny 時で区切る日足。日付は、足が閉じる日の NY の日付。"""
    ny = m.index.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    day = (ny + pd.Timedelta(hours=24 - cut_hour_ny)).normalize()
    g = m.groupby(day)
    d = pd.DataFrame({"open": g["o"].first(), "high": g["h"].max(), "low": g["l"].min(), "close": g["c"].last(), "n": g["c"].size()})
    d = d[(d.index.dayofweek < 5) & (d["n"] >= 300)]          # 取引の少ない日（祝日など）は足にしない
    return d.drop(columns="n")


def sleeve_section():
    """S&P500 と NASDAQ100 の3ルールを1つの層にまとめた成績（A の形 = MT5 の日足そのまま）と、ほかの層との組み合わせ。"""
    import sleeves as SV
    import yahoo_data as Y
    ann = 252
    parts = {}
    for name in ("S&P500", "NASDAQ100"):
        pair, ccy, div = CFD[name]
        d = day_bars(load_any(pair), 17)
        rate = IR.short_rate(ccy, d.index)
        vw = SV.vol_weight(d["close"])
        for key, p in IR.rules(d).items():
            if key != "R2<5":
                parts[(name, key)] = SV.pnl_w(p * vw, d, rate, div, IR.COST, at_open=True)
    df = pd.DataFrame(parts).fillna(0.0)
    df = df[df.index >= "2011-09-01"]          # 200日の平均がそろってから
    r = df.mean(axis=1)

    def sh(x):
        return x.mean() / x.std() * np.sqrt(ann)
    eq = (1 + r).cumprod()
    yr = r.groupby(r.index.year).sum()
    spx = Y.fetch("SPX")["close"].pct_change().reindex(r.index).fillna(0.0)
    X = np.column_stack([np.ones(len(r)), spx.values])
    b, *_ = np.linalg.lstsq(X, r.values, rcond=None)
    e = r.values - X @ b
    se = np.sqrt(e.var(ddof=2) * np.linalg.inv(X.T @ X)[0, 0])
    out = ["## 1つの層にまとめる（S&P500 と NASDAQ100、3つのルールを同じ重み、A の形）", "",
           f"期間：{df.index[0].date()}〜{df.index[-1].date()}。建玉は、持っているときの各指数の値動きが年10%になる大きさ。", "",
           f"- 年率シャープ {sh(r):+.2f}（t 値 {sh(r) * np.sqrt(len(r) / ann):+.1f}）、年率 {r.mean() * ann * 100:+.1f}%、値動き 年{r.std() * np.sqrt(ann) * 100:.1f}%、"
           f"最大の下落 {(eq / eq.cummax() - 1).min() * 100:.1f}%、最悪の日 {r.min() * 100:.1f}%（{r.idxmin().date()}）、プラスの年 {(yr > 0).sum()}/{len(yr)}",
           "- 期間ごとのシャープ：" + "、".join(f"{lab} {sh(r[(r.index >= a) & (r.index < b)]):+.2f}" for lab, a, b in PER if len(r[(r.index >= a) & (r.index < b)]) > 50),
           "- 年ごと（%）：" + "、".join(f"{int(k)}年 {v * 100:+.1f}" for k, v in yr.items()),
           f"- S&P500 そのものとの関係：ベータ {b[1]:+.2f}、ベータの分を除いた残り（アルファ）年率 {b[0] * ann * 100:+.1f}%（t 値 {b[0] / se:+.1f}）", ""]
    spath = os.path.join(D.CACHE, "sleeves_returns.parquet")
    if os.path.exists(spath):
        S = pd.read_parquet(spath)
        idx = S.index[(S.index >= df.index[0]) & (S.index <= df.index[-1])]

        def s10(x):
            return x * (0.10 / (x.std() * np.sqrt(ann)))
        rv = s10(r.reindex(idx).fillna(0.0))
        A = {k: s10(S[k].reindex(idx)) for k in ("為替の金利差", "指数の順張り（6指数）", "金の順張り")}
        out += ["## ほかの層との組み合わせ（同じ期間。各層を同じ重みで足し、値動きを年10%にそろえる）", "",
                "| 組み合わせ | シャープ | t 値 | 最大の下落 | プラスの年 |", "|---|---|---|---|---|"]
        for lab, keys in (("為替の金利差だけ", ["為替の金利差"]), ("為替の金利差＋指数の戻り（この層）", ["為替の金利差", "rv"]),
                          ("＋指数の順張り", ["為替の金利差", "rv", "指数の順張り（6指数）"]),
                          ("＋金の順張り（4層）", ["為替の金利差", "rv", "指数の順張り（6指数）", "金の順張り"])):
            x = s10(sum((rv if k == "rv" else A[k]) for k in keys) / len(keys))
            q = (1 + x).cumprod()
            y = x.groupby(x.index.year).sum()
            out.append(f"| {lab} | {sh(x):+.2f} | {sh(x) * np.sqrt(len(x) / ann):+.1f} | {(q / q.cummax() - 1).min() * 100:.0f}% | {(y > 0).sum()}/{len(y)} |")
        out += ["", f"相関（日次）：この層と 為替の金利差 {rv.corr(A['為替の金利差']):+.2f}、指数の順張り {rv.corr(A['指数の順張り（6指数）']):+.2f}、金の順張り {rv.corr(A['金の順張り']):+.2f}", ""]
    return out


def main():
    lines = ["# 研究：株価指数の「売られすぎの戻り」を、CFD の24時間の値段で確かめる（`tools/research/index_reversion_cfd.py`）", "",
             "CFD の1分足（histdata）から日足を作り、判定の足が閉じたあとの最初の値段で売買する。コスト込み（片道 0.02%、持ち越しは 短期金利＋年2.5%、配当を受け取る）。",
             "建玉の大きさは口座の100%。期間ごとの列は年率シャープ。", ""]
    head = ("| 指数・ルール | 取引数 | 勝率 | 1回の平均 | 持っている日 | " + " | ".join(x[0] for x in PER) + " | 全体のシャープ | 1回の平均の t 値 |")
    R = {}
    for cut, title in ((17, "A：MT5 の日足そのまま（NY 17:00 区切り、次の足の最初の値段 = NY 18:00 過ぎに売買）"),
                       (16, "B：現物の終値で区切る（NY 16:00 区切り、その直後の値段で売買）")):
        lines += [f"## {title}", "", head, "|---|" + "---|" * (len(PER) + 6)]
        for name, (pair, ccy, div) in CFD.items():
            m = load_any(pair)
            if m is None:
                continue
            d = day_bars(m, cut)
            rate = IR.short_rate(ccy, d.index)
            for key, p in IR.rules(d).items():
                if key == "R2<5":
                    continue
                r = IR.pnl(p, d, rate, div, at_open=True)
                R[(name, key, cut)] = r
                tr = IR.trades(p.shift(1).fillna(0.0), r)
                cells = []
                for _, a, b in PER:
                    x = r[(r.index >= a) & (r.index < b)]
                    s = IR.sharpe(x)
                    cells.append("—" if np.isnan(s) or x.abs().sum() == 0 else f"{s:+.2f}")
                tt = tr.mean() / tr.std() * np.sqrt(len(tr)) if len(tr) > 5 else np.nan
                lines.append(f"| {name}：{key}（{d.index[0].year}年〜） | {len(tr)} | {(tr > 0).mean() * 100:.0f}% | {tr.mean() * 100:+.2f}% | {p.mean() * 100:.0f}% | "
                             + " | ".join(cells) + f" | {IR.sharpe(r):+.2f} | {tt:+.1f} |")
        lines.append("")
    lines += sleeve_section()
    out = os.path.join(F.ROOT, "reports", "research", "index_reversion_cfd.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    pd.DataFrame({f"{k[0]}|{k[1]}|{k[2]}": v for k, v in R.items()}).to_parquet(os.path.join(D.CACHE, "index_reversion_cfd_returns.parquet"))


if __name__ == "__main__":
    main()

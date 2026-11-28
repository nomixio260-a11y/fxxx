#!/usr/bin/env python3
"""確かめ：OANDA の原油・天然ガスの CFD の値段は、公式の説明どおりに作られているか。口座に表示されるスワップは、その作りと合っているか（107章）。

- OANDA の公式の説明（海外法人のヘルプ「commodity financing cost variation」ほか。日本法人も同じ商品）：
   (1) 商品 CFD には期限がない。値段は「いま参照している先物（1つ）の値段」に、割増・割引（ベーシス率）をかけて作る。
   (2) 参照している先物の期限が近づくと、その先物と次の先物の値段の差からベーシス率を計算し、以後は次の先物を参照する。
       CFD の値段は、参照する先物の値段を、ベーシス率で「現在の価値」に直したもの。乗り換えの時点で値段は飛ばず、期限に向けて先物の値段に近づいていく。
   (3) ファイナンシングコスト（スワップ）は、ベーシス率 ± 業者の取り分（年2.5%）。ベーシス率の部分は、(2) の「近づいていく値動き」を打ち消すためのもの。
  つまり、買いの損益（値段の変化 ＋ スワップ）＝ 参照している先物を持った損益 − 年2.5%。売りは、その逆 − 年2.5%。
- ここで確かめること（成績を見て手法を選ぶ計算ではない。事実の確認）：
   A 値段の作り（2006年〜2024年4月、EIA の先物の日々の終値と、OANDA の日足）
      A1 1つの限月を参照している期間ごとに、「CFD の値動き − 参照している先物の値動き」が、乗り換えの時点の2つの先物の差（対数）と一致するか（傾き 1 なら説明どおり）
      A2 CFD の日々の値動きが、期近と2番目のどちらに付いているか（乗り換えまでの残りの営業日ごと）。参照の切り替えが期限の何日前かを見る
   B スワップ（2026年11月27日の1日だけ。口座の表示と、その日の先物の値段）
      口座の表示から逆算したベーシス率（買いと売りの真ん中）と、CFD の値段と先物の値段から逆算したベーシス率（A の作りによる）を、8つの商品で比べる
- B の先物の値段は Yahoo Finance の限月ごとの終値（公開データ）。期限が来た限月はあとから取れなくなるので、取った値を
  reports/research/cfd_construction_quotes.csv に残し、あれば読み直さない。
使い方: python3 -I tools/research/cfd_construction.py <商品の口座の書き出しのフォルダ>  → reports/research/cfd_construction.md
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commodity_carry as CC  # noqa: E402
import fred_data as F  # noqa: E402

LEADS = (0, 1, 2, 3, 5, 7)                                    # 参照の切り替えが、期限の何営業日前か（候補）
QUOTES = os.path.join(F.ROOT, "reports", "research", "cfd_construction_quotes.csv")
SNAP_DAY = "2026-11-27"
# 銘柄、Yahoo の記号の頭、取引所、(参照していると見られる限月, その期限, 次の限月)、値段の倍率（OANDA の表示に合わせる）
SNAP = (("USOIL", "CL", ".NYM", ("F27", "2026-12-21", "G27"), 1.0), ("UKOIL", "BZ", ".NYM", ("G27", "2026-12-31", "H27"), 1.0),
        ("NATGAS", "NG", ".NYM", ("F27", "2026-12-29", "G27"), 1.0), ("COPPER", "HG", ".CMX", ("Z26", "2026-12-29", "F27"), 1.0),
        ("CORN", "ZC", ".CBT", ("H27", "2027-03-12", "K27"), 0.01), ("SOYBEANS", "ZS", ".CBT", ("F27", "2027-01-14", "H27"), 0.01),
        ("WHEAT", "ZW", ".CBT", ("H27", "2027-03-12", "K27"), 0.01), ("SUGAR", "SB", ".NYB", ("H27", "2027-02-26", "K27"), 0.01))


def load_cfd(folder, sym):
    c = pd.read_csv(os.path.join(folder, f"AMS_d1_{sym}.csv"))
    c.index = pd.to_datetime(c["date"], format="%Y.%m.%d")
    return c[c.index.dayofweek < 5]["close"].astype(float)


def active_series(D, is_roll, lead):
    """参照している先物の日々の値動き（対数）と、切り替えの日。期限の lead 営業日前の終値で、期近から2番目に乗り換える。"""
    lg = np.log(D.where(D > 0))
    r1, r2 = lg[1].diff(), lg[2].diff()
    rroll = lg[1] - lg[2].shift(1)                             # 乗り換えの日：きのうの2番目が、きょうの期近
    pos = np.flatnonzero(is_roll.values)
    use2 = np.zeros(len(D), dtype=bool)                        # その日の値動きを「2番目」で数える日
    sw = []
    for p in pos:
        s = max(p - lead, 1)
        use2[s:p] = True                                      # s … p−1 は2番目を持っている
        sw.append(s if lead > 0 else p)
    r = r1.copy()
    r[use2] = r2[use2]
    r[is_roll.values] = rroll[is_roll.values] if lead > 0 else rroll[is_roll.values]
    return r, np.array(sw)


def part_a(folder, lines):
    lines += ["## A 値段の作り（2006年〜2024年4月）", "",
              "### A1 1つの限月を参照している期間ごと：「CFD の値動き − 参照している先物の値動き」を、乗り換えの時点の2つの先物の差（対数）で説明する", "",
              "傾きが 1・当てはまりが高ければ、公式の説明どおり（乗り換えで値段は飛ばず、次の期限までに先物の値段へ近づく）。切り替えの日（期限の何営業日前か）は候補を並べる。", "",
              "| 銘柄 | 切り替え：期限の何営業日前 | 期間の数 | 傾き | 当てはまり（決定係数） | 残りのばらつき（標準偏差） | 2つの先物の差の平均（年率に直す前、1期間あたり） |", "|---|---|---|---|---|---|---|"]
    best = {}
    for name, sym in (("原油（WTI）", "USOIL"), ("天然ガス", "NATGAS")):
        group, code, _ = CC.SERIES[name]
        D = CC.fetch(group, code)
        _, is_roll = CC.held_returns(D, group)
        cfd = np.log(load_cfd(folder, sym).reindex(D.index))
        lg = np.log(D.where(D > 0))
        for lead in LEADS:
            ra, sw = active_series(D, is_roll, lead)
            cum_a = ra.fillna(0.0).cumsum()
            xs, ys = [], []
            for a, b in zip(sw[:-1], sw[1:]):
                t0, t1 = D.index[a - 1], D.index[b - 1]       # 切り替えの直前の終値から、次の切り替えの直前の終値まで
                if t0 < pd.Timestamp("2006-01-01") or np.isnan(cfd.iloc[a - 1]) or np.isnan(cfd.iloc[b - 1]):
                    continue
                x = lg[2].iloc[a - 1] - lg[1].iloc[a - 1]     # 乗り換えの時点の差：次の先物 ÷ いまの先物
                y = (cfd.iloc[b - 1] - cfd.iloc[a - 1]) - (cum_a.iloc[b - 1] - cum_a.iloc[a - 1])
                if np.isfinite(x) and np.isfinite(y) and abs(x) < 0.5:
                    xs.append(x)
                    ys.append(y)
            xs, ys = np.array(xs), np.array(ys)
            A = np.column_stack([xs, np.ones(len(xs))])
            (k, c0), *_ = np.linalg.lstsq(A, ys, rcond=None)
            res = ys - A @ np.array([k, c0])
            r2 = 1.0 - res.var() / ys.var()
            lines.append(f"| {sym} | {lead} | {len(xs)} | {k:+.2f} | {r2:.2f} | {res.std() * 100:.2f}% | {xs.mean() * 100:+.2f}% |")
            print(lines[-1], flush=True)
            if sym not in best or r2 > best[sym][1]:
                best[sym] = (lead, r2)
    lines += ["", "### A2 CFD の日々の値動きは、期近と2番目のどちらに付いているか（乗り換え＝期近が消える日までの、残りの営業日ごと）", "",
              "CFD の日々の値動き ＝ a × 期近の値動き ＋ b × 2番目の値動き、と置いたときの a・b（合計はほぼ 1）。b が大きい日は、もう次の先物を参照している。", "",
              "| 銘柄 | 残りの営業日 | 日数 | a（期近） | b（2番目） |", "|---|---|---|---|---|"]
    for name, sym in (("原油（WTI）", "USOIL"), ("天然ガス", "NATGAS")):
        group, code, _ = CC.SERIES[name]
        D = CC.fetch(group, code)
        _, is_roll = CC.held_returns(D, group)
        lg = np.log(D.where(D > 0))
        z = pd.DataFrame({"y": np.log(load_cfd(folder, sym).reindex(D.index)).diff(), "x1": lg[1].diff(), "x2": lg[2].diff()})
        pos = np.arange(len(D))
        rpos = pos[is_roll.values]
        nxt = np.searchsorted(rpos, pos, side="left")
        z["tau"] = np.where(nxt < len(rpos), rpos[np.minimum(nxt, len(rpos) - 1)] - pos, np.nan)
        z = z[(z.index >= "2006-01-01") & (z["tau"] > 0)].dropna()
        z = z[(z["x1"].abs() < 0.25) & (z["x2"].abs() < 0.25) & (z["y"].abs() < 0.25)]
        for lo, hi in ((1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, 12), (13, 30)):
            g = z[(z["tau"] >= lo) & (z["tau"] <= hi)]
            (a, b), *_ = np.linalg.lstsq(g[["x1", "x2"]].values, g["y"].values, rcond=None)
            lines.append(f"| {sym} | {lo}〜{hi} | {len(g)} | {a:+.2f} | {b:+.2f} |")
            print(lines[-1], flush=True)
    return best


def yahoo_close(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1mo&interval=1d"
    j = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30))
    r = j["chart"]["result"][0]
    return {dt.datetime.fromtimestamp(a, dt.timezone.utc).strftime("%Y-%m-%d"): b for a, b in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if b is not None}


def quotes():
    if os.path.exists(QUOTES):
        return pd.read_csv(QUOTES)
    rows = []
    for sym, root, suf, (act, exp, nxt), scale in SNAP:
        for m in (act, nxt):
            q = yahoo_close(f"{root}{m}{suf}")
            time.sleep(0.4)
            for day, v in q.items():
                if day >= "2026-11-16":
                    rows.append(dict(symbol=sym, contract=f"{root}{m}", date=day, close=round(v * scale, 6)))
    out = pd.DataFrame(rows)
    out.to_csv(QUOTES, index=False)
    return out


def part_b(folder, lines):
    q = quotes()
    sw = pd.read_csv(os.path.join(F.ROOT, "reports", "live_commodity", "AMS_swaps.csv"))
    sw = sw[sw["date"] == SNAP_DAY.replace("-", ".")].set_index("symbol")
    lines += ["", f"## B 口座に表示されているスワップと、その日の先物の値段（{SNAP_DAY} の1日だけ）", "",
              "- 「表示から逆算したベーシス率」＝（売りのスワップ − 買いのスワップ）÷ 2。公式の説明では、買いは −（ベーシス率 ＋ 2.5%）、売りは ＋（ベーシス率 − 2.5%）なので、こう逆算できる。",
              "  プラスは「CFD の値段が先物より安く、期限に向けて上がっていく」（買いが払う側）、マイナスはその逆（買いが受け取る側）。",
              "- 「値段から逆算したベーシス率」＝ ln(参照している先物 ÷ CFD) ÷ 期限までの年数。A の作りが正しければ、これが実際に値段に入っているベーシス率。",
              "- 「先物どうしの傾き」＝ ln(次の先物 ÷ 参照している先物) を年率に直したもの（参考。次に乗り換えたあとのベーシス率の目安）。", "",
              "| 銘柄 | 表示：買い | 表示：売り | 表示から逆算したベーシス率 | 参照している先物（期限） | 先物の終値 | CFD の終値 | 値段から逆算したベーシス率 | 先物どうしの傾き（次の限月） | 向きは合っているか |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    n_ok = 0
    for sym, root, suf, (act, exp, nxt), scale in SNAP:
        g = q[(q["symbol"] == sym) & (q["date"] == SNAP_DAY)].set_index("contract")["close"]
        fa, fn = float(g[f"{root}{act}"]), float(g[f"{root}{nxt}"])
        cfd = float(load_cfd(folder, sym).loc[SNAP_DAY])
        yrs = (pd.Timestamp(exp) - pd.Timestamp(SNAP_DAY)).days / 365.0
        b_px = np.log(fa / cfd) / yrs * 100.0
        b_sw = (float(sw.loc[sym, "short_pct_year"]) - float(sw.loc[sym, "long_pct_year"])) / 2.0
        months = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6, "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
        gap = ((months[nxt[0]] - months[act[0]]) % 12) / 12.0
        slope = np.log(fn / fa) / gap * 100.0
        ok = np.sign(b_px) == np.sign(b_sw)
        n_ok += int(ok)
        lines.append(f"| {sym} | {float(sw.loc[sym, 'long_pct_year']):+.1f}% | {float(sw.loc[sym, 'short_pct_year']):+.1f}% | {b_sw:+.1f}% | {root}{act}（{exp}） | {fa:.4g} | {cfd:.4g} | {b_px:+.0f}% | "
                     f"{slope:+.0f}%（{root}{nxt}） | {'○' if ok else '**×**'} |")
        print(lines[-1], flush=True)
    lines += ["", f"- 向きが合っていたのは 8 銘柄のうち {n_ok}。CFD の終値（NY 17時）と先物の終値は時刻が少し違うので、値段から逆算した率には ±10% 前後の誤差がある（期限までが短い銘柄ほど大きい）。"]
    return n_ok


def main():
    folder = sys.argv[1]
    lines = ["# 確かめ：OANDA の商品 CFD の値段の作りと、表示されているスワップ（`tools/research/cfd_construction.py`）", ""]
    part_a(folder, lines)
    part_b(folder, lines)
    out = os.path.join(F.ROOT, "reports", "research", "cfd_construction.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

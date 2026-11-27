#!/usr/bin/env python3
"""研究：戻りの手法の「前提」が続いているかを、数式で監視する（100章）。相場の性質が変わっても、崩れにくくするため。

- 戻りの手法の前提は、「指数の日々の値動きは、反転しやすい」こと。これは 1999年ごろから続いている性質で、それより前は逆（続きやすい）だった
  （Baltussen・van Bekkum・Da 2019年）。将来、また逆に戻るかもしれない。
- 監視に使う値は2通り：
  1 最初の形（同じ論文の物差し）：MAC5 = 当日の値動き ×（4×前日 + 3×2日前 + 2×3日前 + 1×4日前の値動き）÷（5 × 分散）の、過去 W 日の平均。
    マイナスなら「反転しやすい」、プラスなら「続きやすい」。
  2 順位の形（独自。採用）：「当日の値動き」と「4×前日 + 3×2日前 + 2×3日前 + 1×4日前」の、過去 W 日の順位の相関（スピアマン）。
    採用した形は W = 1,500 日で、値が標準誤差1つ分（1 ÷ √1500 = 0.026）を超えたら「続きやすい」と判定する。
    1 は、飛び抜けて大きい1日（急落が続いた日）に引っ張られる：1日で値が 0.06 動くことがあり、急落の当日だけ「続きやすい」と誤って判定する
    （MT5 の長期の検証で、まさに戻りの利益が大きい日に IBS を止めていた）。順位で測れば、1日の影響は小さい。
  どちらも、その日までの値だけを使う。
- 仕組み：監視の値がしきい値を超えている（続きやすい相場）あいだは、戻りのルールを止める。
  止める対象は、(a) 3つのルールすべて、(b) 200日の平均の条件がない IBS だけ。判定は、指数ごと／S&P500 の値で全指数まとめて、の2通り。
- データ：S&P500（1962年〜。高値・安値がそろう時期から）、NASDAQ100（1985年〜）、ダウ（1992年〜）。VIX がない時期（〜1989年）は、VIX の倍率を 1 にする。
  誤作動の確認には、EA が実際に使う形の日足（1分足から作った CFD の日足、2010年11月〜）も使う。
- 期間ごとの成績（全期間の値動きを年10%にそろえる）：1962〜81／1982〜98／1999〜2010／2011〜26／うち 2023年11月〜。
使い方: python3 tools/research/index_regime_monitor.py  → reports/research/index_regime_monitor.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_stop as IS  # noqa: E402
import index_vix_sizing as V  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
SE1 = 1.0 / np.sqrt(1500.0)                  # 1,500日の順位の相関の標準誤差（しきい値に使う）
W124 = {0: 0.0, 1: 0.25, 2: 0.5, 3: 1.0}
ERAS = (("1962〜81", "1962-07-01", "1982-01-01"), ("1982〜98", "1982-01-01", "1999-01-01"), ("1999〜2010", "1999-01-01", "2011-01-01"),
        ("2011〜26", "2011-01-01", "2027-01-01"), ("うち 2023年11月〜", "2023-11-01", "2027-01-01"))


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 100 and x.std() > 0 else np.nan


def mac5(c):
    r = np.log(c).diff()
    var = r.rolling(250, min_periods=120).var()
    return r * (4 * r.shift(1) + 3 * r.shift(2) + 2 * r.shift(3) + r.shift(4)) / (5.0 * var)


def rank_mon(c, W):
    """順位の形：当日の値動きと、直前4日の重みつきの合計の、過去 W 日の順位の相関（スピアマン）。W 日そろうまでは NaN。"""
    from scipy.stats import rankdata
    r = np.log(c).diff()
    q = 4 * r.shift(1) + 3 * r.shift(2) + 2 * r.shift(3) + r.shift(4)
    rr, qq = r.values, q.values
    out = np.full(len(rr), np.nan)
    for t in range(W + 4, len(rr)):
        x, y = rr[t - W + 1:t + 1], qq[t - W + 1:t + 1]
        if np.isnan(x).any() or np.isnan(y).any():
            continue
        out[t] = np.corrcoef(rankdata(x), rankdata(y))[0, 1]
    return pd.Series(out, index=c.index)


def load(name, start):
    yn, ccy, div, _ = IR.INDEX[name]
    d = Y.fetch(yn)
    d = d[d.index >= start].copy()
    st = IR.rules(d)
    rate = IR.short_rate(ccy, d.index)
    sg = IS.har_sigma(d)
    rk = V.vix_rank(d.index)[0]
    return d, st, rate, div, sg, rk


def main():
    data = {"S&P500": load("S&P500", "1961-01-01"), "NASDAQ100": load("NASDAQ100", "1985-10-01"), "ダウ": load("ダウ", "1992-01-01")}
    lines = ["# 研究：戻りの手法の前提の監視（`tools/research/index_regime_monitor.py`）", "",
             "## 監視の値（マイナス = 反転しやすい）", "",
             "| 指数 | 値 | " + " | ".join(e[0] for e in ERAS) + " | しきい値 0 を超えた日の割合（1999年〜） | 1日で動いた幅の最大 |", "|---|---|" + "---|" * (len(ERAS) + 2)]
    mon, rnk = {}, {}
    for name, (d, st, rate, div, sg, rk) in data.items():
        m = mac5(d["close"])
        mon[name] = {W: m.rolling(W, min_periods=W // 2).mean() for W in (500, 750, 1000)}
        rnk[name] = {W: rank_mon(d["close"], W) for W in ((750, 1000, 1500) if name == "S&P500" else (1500,))}
        for label, x in (("最初の形：MAC5 の 750日の平均", mon[name][750]), ("順位の形：1500日の順位の相関", rnk[name][1500])):
            lines.append(f"| {name} | {label} | " + " | ".join(f"{x[(x.index >= a) & (x.index < b)].mean():+.3f}" if len(x[(x.index >= a) & (x.index < b)].dropna()) > 100 else "—" for _, a, b in ERAS)
                         + f" | {(x[x.index >= '1999-01-01'].dropna() > 0).mean() * 100:.1f}% | {x.diff().abs().max():.3f} |")
            print(lines[-1], flush=True)

    def run(names, which, series_of, thr):
        """series_of(name)：その指数の判定に使う監視の値（None なら監視なし）。"""
        parts = []
        for name in names:
            d, st, rate, div, sg, rk = data[name]
            if series_of is None:
                on = pd.Series(1.0, index=d.index)
            else:
                x = series_of(name)
                mm = x.reindex(x.index.union(d.index)).ffill().reindex(d.index)
                on = (mm <= thr).astype(float).where(mm.notna(), 1.0)
            r2, d7, ibs = st["R2<10"], st["D7"], st["IBS"]
            n = (r2 + d7 + ibs) * on if which == "all" else r2 + d7 + ibs * on
            w = (n.map(lambda v: W124[int(round(v))]) * V.mult_of(rk, (0.5, 1.0, 1.5)) * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0) / len(names)
            r, _, _ = IS.run(d, w, sg, rate, div, 4.0, "close")
            parts.append(r)
        return pd.concat(parts, axis=1, sort=True).fillna(0.0).sum(axis=1)
    forms = (("監視なし（99章の形）", "ibs", None, 0.0, None),
             ("最初の形・3つのルールすべてを止める：指数ごと・750日・0", "all", lambda n: mon[n][750], 0.0, lambda n: mon[n][750]),
             ("最初の形・IBS だけ：指数ごと・500日・0", "ibs", lambda n: mon[n][500], 0.0, lambda n: mon[n][500]),
             ("最初の形・IBS だけ：指数ごと・750日・0", "ibs", lambda n: mon[n][750], 0.0, lambda n: mon[n][750]),
             ("最初の形・IBS だけ：指数ごと・1000日・0", "ibs", lambda n: mon[n][1000], 0.0, lambda n: mon[n][1000]),
             ("最初の形・IBS だけ：指数ごと・750日・+0.02", "ibs", lambda n: mon[n][750], 0.02, lambda n: mon[n][750]),
             ("最初の形・IBS だけ：S&P500 の値で全指数・750日・+0.02", "ibs", lambda n: mon["S&P500"][750], 0.02, lambda n: mon["S&P500"][750]),
             ("順位の形・IBS だけ：S&P500 の値で全指数・750日・0", "ibs", lambda n: rnk["S&P500"][750], 0.0, lambda n: rnk["S&P500"][750]),
             ("順位の形・IBS だけ：S&P500 の値で全指数・1000日・0", "ibs", lambda n: rnk["S&P500"][1000], 0.0, lambda n: rnk["S&P500"][1000]),
             ("順位の形・IBS だけ：S&P500 の値で全指数・1500日・0", "ibs", lambda n: rnk["S&P500"][1500], 0.0, lambda n: rnk["S&P500"][1500]),
             ("**順位の形・IBS だけ：S&P500 の値で全指数・1500日・標準誤差1つ分（+0.026）（採用）**", "ibs", lambda n: rnk["S&P500"][1500], SE1,
              lambda n: rnk["S&P500"][1500]))
    for title, names, start in (("S&P500 だけ（1962年7月〜）", ["S&P500"], "1962-07-01"), ("3指数（そろう時期から。1992年〜はすべて）", ["S&P500", "NASDAQ100", "ダウ"], "1962-07-01")):
        lines += ["", f"## {title}", "", "| 形 | 全期間のシャープ | " + " | ".join(e[0] for e in ERAS) + " | 最悪の日 | 最大の下落 | 止めていた日の割合（1999年〜） |", "|---|" + "---|" * (len(ERAS) + 4)]
        for label, which, series_of, thr, ser in forms:
            r = run(names, which, series_of, thr)
            r = r[r.index >= start]
            z = r * (0.10 / (r.std() * np.sqrt(ANN)))
            eq = (1 + z).cumprod()
            off = "—" if ser is None else f"{np.mean([(ser(n)[ser(n).index >= '1999-01-01'].dropna() > thr).mean() for n in names]) * 100:.1f}%"
            lines.append(f"| {label} | {sh(z):+.2f} | " + " | ".join(f"{sh(z[(z.index >= a) & (z.index < b)]):+.2f}" for _, a, b in ERAS)
                         + f" | {z.min() * 100:.1f}% | {(eq / eq.cummax() - 1).min() * 100:.0f}% | {off} |")
            print(lines[-1], flush=True)
    # しきい値の感度（順位の形・1500日・S&P500 の値で全指数）
    lines += ["", "## 順位の形（1,500日）のしきい値を変えた場合（3指数）", "",
              "標準誤差は 1 ÷ √1500 = 0.026。しきい値が 0〜+0.04 のあいだは、結果がほぼ同じ（しきい値の選び方に左右されない）。", "",
              "| しきい値 | 全期間のシャープ | " + " | ".join(e[0] for e in ERAS) + " | 最大の下落 | 止めていた日：1967〜81 | 1982〜98 | 1999年〜 |", "|---|" + "---|" * (len(ERAS) + 5)]
    x = rnk["S&P500"][1500].dropna()
    names3 = ["S&P500", "NASDAQ100", "ダウ"]
    for thr in (-0.01, 0.0, 0.01, 0.02, SE1, 0.03, 0.04, 0.05):
        r = run(names3, "ibs", lambda n: rnk["S&P500"][1500], thr)
        r = r[r.index >= "1962-07-01"]
        z = r * (0.10 / (r.std() * np.sqrt(ANN)))
        eq = (1 + z).cumprod()
        fr = lambda a, b: (x[(x.index >= a) & (x.index < b)] > thr).mean() * 100          # noqa: E731
        lab = f"**{thr:+.3f}（標準誤差1つ分。採用）**" if thr == SE1 else f"{thr:+.2f}"
        lines.append(f"| {lab} | {sh(z):+.2f} | " + " | ".join(f"{sh(z[(z.index >= a) & (z.index < b)]):+.2f}" for _, a, b in ERAS)
                     + f" | {(eq / eq.cummax() - 1).min() * 100:.0f}% | {fr('1967-01-01', '1982-01-01'):.0f}% | {fr('1982-01-01', '1999-01-01'):.0f}% | {fr('1999-01-01', '2027-01-01'):.1f}% |")
        print(lines[-1], flush=True)
    # IBS を止めているあいだに失うもの（1999年〜。IBS をずっと止めた場合との比べ）
    base = run(names3, "ibs", None, 0.0)
    noibs = run(names3, "ibs", lambda n: pd.Series(1.0, index=data[n][0].index), 0.0)      # 値が 1 > 0 なので、ずっと止まる
    lines += ["", "## 参考：IBS を止めているあいだに失うもの（3指数。同じ設定のまま、IBS をずっと止めた場合）", "",
              "| 期間 | IBS あり：損益の合計・シャープ・値動き | IBS なし：損益の合計・シャープ・値動き | 損益の比 |", "|---|---|---|---|"]
    for lab, a, b in (("1999〜2010", "1999-01-01", "2011-01-01"), ("2011〜26", "2011-01-01", "2027-01-01"), ("うち 2023年11月〜", "2023-11-01", "2027-01-01")):
        u, v = base[(base.index >= a) & (base.index < b)], noibs[(noibs.index >= a) & (noibs.index < b)]
        lines.append(f"| {lab} | {u.sum() * 100:+.1f}%・{sh(u):+.2f}・{u.std() * np.sqrt(ANN) * 100:.1f}% | {v.sum() * 100:+.1f}%・{sh(v):+.2f}・{v.std() * np.sqrt(ANN) * 100:.1f}% | {v.sum() / u.sum():.2f} |")
        print(lines[-1], flush=True)
    # EA が実際に使う形の日足（CFD）での誤作動
    try:
        os.environ.setdefault("AMS_OANDA", "1")
        import sleeves_ea_mimic as M
        lines += ["", "## EA が実際に使う形の日足（1分足から作った CFD の日足）での作動", "",
                  "| 銘柄 | 形 | 計算できた期間 | 平均 | 最大 | しきい値を超えた日数 | 超え始めた日（最初の12回） | 最後の値 |", "|---|---|---|---|---|---|---|---|"]
        for sym in ("US500_HD", "US100_HD"):
            c = M.prepare(M.ALL[sym][0])["close"]
            cands = [("最初の形：750日の平均が +0.02 を超える", mac5(c).rolling(750, min_periods=750).mean(), 0.02)]
            cands += [(f"順位の形：{W}日の順位の相関が 0 を超える", rank_mon(c, W), 0.0) for W in (750, 1000, 1500)]
            cands += [("**順位の形：1500日の順位の相関が +0.026 を超える（採用）**", rank_mon(c, 1500), SE1)]
            for label, x, thr in cands:
                x = x.dropna()
                on = x > thr
                st = on.astype(int).diff().fillna(float(on.iloc[0]))
                first = [str(t.date()) for t in st[st == 1].index][:12]
                lines.append(f"| {sym} | {label} | {x.index[0].date()}〜{x.index[-1].date()} | {x.mean():+.3f} | {x.max():+.3f} | {int(on.sum())}（{on.mean() * 100:.1f}%） | {'、'.join(first) if first else 'なし'} | {x.iloc[-1]:+.3f} |")
                print(lines[-1], flush=True)
    except Exception as e:                      # 1分足のデータがない環境では飛ばす
        lines += ["", f"（CFD の日足での確認は飛ばしました：{e}）"]
    # ルールごとの、時期ごとの成績（S&P500）
    d, st, rate, div, sg, rk = data["S&P500"]
    lines += ["", "## 参考：S&P500 のルールごとの成績（監視なし。ルール1つだけを持った場合のシャープ）", "", "| ルール | " + " | ".join(e[0] for e in ERAS) + " |", "|---|" + "---|" * len(ERAS)]
    for key in ("R2<10", "D7", "IBS"):
        w = (st[key] * (0.10 / (sg * np.sqrt(ANN))).clip(upper=4.0)).fillna(0.0)
        r, _, _ = IS.run(d, w, sg, rate, div, None, "close")
        lines.append(f"| {key} | " + " | ".join(f"{sh(r[(r.index >= a) & (r.index < b)]):+.2f}" for _, a, b in ERAS) + " |")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_regime_monitor.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

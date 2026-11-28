#!/usr/bin/env python3
"""研究：株価指数の CFD で、日中〜数日の値動きのパターンに優位性があるか（時刻・曜日・日付は判断に使わない）。

- 為替の一斉検証（pattern_zoo.py、89章）と同じ約30種類のパターンを、株価指数の1分足（histdata の CFD、2010年11月〜2026年10月）に当てはめる。
  5つの指数（S&P500・NASDAQ100・日経225・DAX・FTSE100）× 4つの時間足（15分・1時間・4時間・1日）× パターン × 保有（1・4・12本）。
- 株価指数は長い目で上がるので、**買いのシグナルだけ・売りのシグナルだけ**を分けて評価する。
- パターンは足の終値で判定し、次の足の始値で入り、決めた本数の後の始値で出る。コストは指数ごとのスプレッド（下の SPREAD、指数のポイント）。
  1日の取引の切れ目（NY 16:00〜18:59）に始まる足では入らない（スプレッドが広がるため。判断の材料には使わない）。
- 評価：損益を各指数の1日の値動きの大きさで割ってそろえ、日ごとの合計にしてから t 値を出す（シグナルをすべて同じ大きさで取引した場合）。
- 期間：設計 2011〜2018年 → 選ぶ 2019〜2022年 → 答え合わせ 2023年〜2026年10月。合格：設計で t ≥ 3、選ぶ期間で t ≥ 2（どちらもコスト後）。
- 注意：買いのシグナルは、何もしなくても上がる分（株式の値上がり）を含む。そこで「同じ本数を、条件なしで買った場合」との差も出す。
使い方: python3 tools/research/index_zoo.py  → reports/research/index_zoo.md、index_zoo_all.csv
"""
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_reversion_cfd as IC  # noqa: E402
import pattern_zoo as PZ  # noqa: E402

SYMS = {"S&P500": ("SPXUSD", 0.6), "NASDAQ100": ("NSXUSD", 2.5), "日経225": ("JPXJPY", 12.0), "DAX": ("GRXEUR", 4.0), "FTSE100": ("UKXGBP", 3.0)}   # スプレッド（ポイント）
TFS = (("15分", 15), ("1時間", 60), ("4時間", 240), ("1日", 1440))
HOLDS = (1, 4, 12)
PER = (("設計", "2011-01-01", "2019-01-01"), ("選ぶ", "2019-01-01", "2023-01-01"), ("答え合わせ", "2023-01-01", "2026-11-01"))


def load(sym):
    """1分足。株価指数のファイル名の形にないもの（原油など）は、data の中の、その銘柄の1分足のファイルを読む。"""
    m = IC.load_any(sym)
    if m is None:
        import glob
        import data as D
        parts = [IC.read_csv_m1(f) for f in sorted(glob.glob(os.path.join(D.DATA, f"{sym}_M1_*.csv")))]
        m = pd.concat(parts).sort_index()
        m = m[~m.index.duplicated()]
    return m


def bars(sym, minutes):
    m = load(sym)[["o", "h", "l", "c"]]
    if minutes == 1440:
        g = m.resample("24h", offset="22h", label="left", closed="left")
    else:
        g = m.resample(f"{minutes}min", label="left", closed="left")
    return pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last()}).dropna()


def main(syms=None, out="index_zoo", title="株価指数", note="5つの指数をまとめて評価。"):
    syms = syms or SYMS
    acc = defaultdict(lambda: [None, None, None])       # (tf, sig, H, side) → [日ごとの合計(コスト後), 件数, 条件なしとの差の合計]
    zero = pd.Series(dtype=float)
    for name, (sym, spread) in syms.items():
        for tfname, mins in TFS:
            b = bars(sym, mins)
            sig = PZ.signals(b, zero)
            sig = {k: v for k, v in sig.items() if "金利差" not in k}
            o = b["o"].values
            idx = b.index
            ny_h = idx.tz_localize("UTC").tz_convert("America/New_York").hour.values
            ok_entry = np.ones(len(b), bool)
            if mins < 1440:
                nh = np.r_[ny_h[1:], -1]
                ok_entry = ~((nh >= 16) & (nh <= 18))
            r1 = b["c"].pct_change()
            per_day = max(1, int(round(len(b) / max(1, b.index.normalize().nunique()))))
            dvol = (r1.rolling(per_day * 20, min_periods=per_day * 10).std() * np.sqrt(per_day)).values
            entry = np.r_[o[1:], np.nan]
            for H in HOLDS:
                exit_ = np.r_[o[1 + H:], np.full(1 + H, np.nan)]
                exit_t = np.r_[idx.values[1 + H:], np.full(1 + H, np.datetime64("NaT"))]
                raw = (exit_ / entry - 1.0)
                base_ok = ok_entry & ~np.isnan(raw) & ~np.isnan(dvol) & (dvol > 0)
                # 条件なしで買った場合の、1回あたりの平均（同じ指数・同じ時間足・同じ保有。年ごと）
                yrs = pd.DatetimeIndex(idx).year.values
                base_mean = pd.Series(raw[base_ok]).groupby(yrs[base_ok]).mean()
                bm = pd.Series(yrs).map(base_mean).values
                for pname, s in sig.items():
                    for side, sgn in (("買い", 1.0), ("売り", -1.0)):
                        m = (s == sgn) & base_ok
                        if m.sum() == 0:
                            continue
                        g = sgn * raw[m]
                        net = g - spread / entry[m]
                        ex = sgn * (raw[m] - bm[m])                     # 条件なしとの差（コスト前）
                        day = pd.DatetimeIndex(exit_t[m]).normalize()
                        dfe = pd.DataFrame({"n": net / dvol[m], "c": 1.0, "x": ex / dvol[m]}, index=day).groupby(level=0).sum()
                        a = acc[(tfname, pname, H, side)]
                        for i, col in enumerate(("n", "c", "x")):
                            a[i] = dfe[col] if a[i] is None else a[i].add(dfe[col], fill_value=0.0)
        print(name, "done", flush=True)
    rows = []
    for (tf, pname, H, side), (n, c, x) in acc.items():
        rec = {"tf": tf, "pattern": pname, "hold": H, "side": side}
        for per, a, b in PER:
            days = pd.bdate_range(a, min(pd.Timestamp(b) - pd.Timedelta(days=1), n.index.max()))
            v = n.reindex(days, fill_value=0.0)
            vx = x.reindex(days, fill_value=0.0)
            cnt = c.reindex(days, fill_value=0.0).sum()
            rec[f"{per}_t"] = v.mean() / v.std() * np.sqrt(len(v)) if v.std() > 0 else 0.0
            rec[f"{per}_tx"] = vx.mean() / vx.std() * np.sqrt(len(vx)) if vx.std() > 0 else 0.0
            rec[f"{per}_n"] = int(cnt)
            rec[f"{per}_mean"] = v.sum() / cnt if cnt else 0.0
        rows.append(rec)
    df = pd.DataFrame(rows)
    out_dir = os.path.join(F.ROOT, "reports", "research")
    df.round(4).to_csv(os.path.join(out_dir, f"{out}_all.csv"), index=False)
    lines = [f"# 研究：{title}の日中〜数日の値動きのパターン（`tools/research/{'index_zoo' if out == 'index_zoo' else 'commodity_zoo'}.py`）", "",
             f"調べた組み合わせ：{len(df)} 通り（時間足 4 × パターン {df['pattern'].nunique()} × 保有 3 × 買い・売り）。{note}",
             "t = コスト後の損益（1日の値動きの大きさで割った値）の日ごとの合計から計算。「差の t」= 同じ本数を条件なしで買った場合との差（コスト前）。", ""]
    for side in ("買い", "売り"):
        d = df[df["side"] == side]
        pas = d[(d["設計_t"] >= 3.0) & (d["選ぶ_t"] >= 2.0)].sort_values("設計_t", ascending=False)
        pas2 = pas[(pas["設計_tx"] >= 2.0) & (pas["選ぶ_tx"] >= 1.0)]
        lines += [f"## {side}のシグナル", "",
                  f"- コスト後で合格（設計 t ≥ 3 かつ 選ぶ t ≥ 2）：**{len(pas)} 通り** / {len(d)}。そのうち、条件なしとの差もはっきりあるもの（設計の差の t ≥ 2、選ぶ ≥ 1）：**{len(pas2)} 通り**",
                  f"- コスト後の t の分布（設計）：最大 {d['設計_t'].max():+.1f}、中央 {d['設計_t'].median():+.1f}、最小 {d['設計_t'].min():+.1f}。プラスは {int((d['設計_t'] > 0).sum())}/{len(d)}", ""]
        if len(pas):
            lines += ["| 時間足 | パターン | 保有 | 設計 t（差の t、件数） | 選ぶ t（差の t） | 答え合わせ t（差の t） | 答え合わせの1回の平均 |", "|---|---|---|---|---|---|---|"]
            for _, r in pas.head(25).iterrows():
                lines.append(f"| {r.tf} | {r.pattern} | {r.hold}本 | {r['設計_t']:+.1f}（{r['設計_tx']:+.1f}、{r['設計_n']}） | {r['選ぶ_t']:+.1f}（{r['選ぶ_tx']:+.1f}） | "
                             f"{r['答え合わせ_t']:+.1f}（{r['答え合わせ_tx']:+.1f}） | {r['答え合わせ_mean']:+.3f} |")
            lines.append("")
    open(os.path.join(out_dir, f"{out}.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return df


if __name__ == "__main__":
    main()

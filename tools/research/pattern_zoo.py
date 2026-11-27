#!/usr/bin/env python3
"""短期・中期の層：値動きのパターンの一斉検証（時刻・曜日・日付は判断に使わない）。

- 17ペア × 4つの時間足（15分・1時間・4時間・1日）× 約30種類のパターン × 保有（1・4・12本）。
- パターン：勢いに乗る／行き過ぎの戻り／高値・安値の更新（とその失敗）／ボリンジャーバンド／RSI／移動平均の交差／
  値幅の縮小からの放れ／大きな足の後／包み足・はらみ足／連続した上げ下げ／値動きの拡大・縮小時の勢い／
  金利差の向きへの押し目・勢い（金利差は FRED の月次の短期金利、1か月遅れで使用）。
- パターンは足の終値で判定し、次の足の始値で入り、決めた本数の後の始値で出る。コストは S.COST + 0.5 pips。
  日付の変わり目（NY 16:00〜18:59）に始まる足では入らない（スプレッドが広がるため。判断の材料には使わない）。
- 17ペアをまとめて評価する（本物のパターンなら、多くのペアで通用するはず）。損益は各ペアの1日の値動きの大きさで割ってそろえ、
  日ごとの平均にしてから t 値を出す。
- 期間：設計 2015年1月〜21年10月 → 選ぶ 21年11月〜24年10月 → 答え合わせ 24年11月〜25年10月、25年11月〜26年10月。
  合格：設計で t ≥ 3、選ぶ期間で t ≥ 2（どちらもコスト後プラス）。答え合わせは、合格したものだけを見る。
使い方: python3 tools/research/pattern_zoo.py  → reports/research/pattern_zoo.md、pattern_zoo_all.csv
"""
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
import fred_data as F  # noqa: E402

PAIRS = F.PAIRS
TFS = (("15分", 15), ("1時間", 60), ("4時間", 240), ("1日", 1440))
HOLDS = (1, 4, 12)
PER = (("設計", "2015-01-01", "2021-11-01"), ("選ぶ", "2021-11-01", "2024-11-01"),
       ("答え合わせ1", "2024-11-01", "2025-11-01"), ("答え合わせ2", "2025-11-01", "2026-11-14"))
ROOT = F.ROOT


def bars(pair, minutes):
    df = D.bars(pair, "5min")[["o", "h", "l", "c"]]
    if minutes == 1440:
        g = df.resample("24h", offset="22h", label="left", closed="left")
    else:
        g = df.resample(f"{minutes}min", label="left", closed="left")
    out = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last()}).dropna()
    return out


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    return 100.0 * up / (up + dn).replace(0, np.nan)


def signals(b, carry_dir):
    """名前 → 向き（-1/0/+1）の配列。すべて、その足の終値までの値だけで決める。"""
    o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    r1 = c.pct_change()
    sd = r1.rolling(100, min_periods=60).std()
    out = {}

    def z(L):
        return (c / c.shift(L) - 1.0) / (sd * np.sqrt(L))
    for L in (4, 12, 48):
        zz = z(L)
        out[f"勢い{L}本（1σ超）"] = np.sign(zz).where(zz.abs() > 1.0, 0.0)
    for L in (1, 4, 12):
        zz = z(L)
        out[f"行き過ぎの戻り{L}本（2σ超）"] = -np.sign(zz).where(zz.abs() > 2.0, 0.0)
    for N in (20, 55):
        hi, lo = h.rolling(N).max().shift(1), l.rolling(N).min().shift(1)
        brk = (c > hi).astype(float) - (c < lo).astype(float)
        out[f"高値安値の更新{N}本に乗る"] = brk
        out[f"高値安値の更新{N}本の逆"] = -brk
    ma20, s20 = c.rolling(20).mean(), c.rolling(20).std()
    bb = (c > ma20 + 2 * s20).astype(float) - (c < ma20 - 2 * s20).astype(float)
    out["ボリンジャー2σの戻り"] = -bb
    out["ボリンジャー2σに乗る"] = bb
    r14, r2 = rsi(c, 14), rsi(c, 2)
    out["RSI14（30/70）の戻り"] = (r14 < 30).astype(float) - (r14 > 70).astype(float)
    out["RSI2（10/90）の戻り"] = (r2 < 10).astype(float) - (r2 > 90).astype(float)
    ma200 = c.rolling(200).mean()
    up, dn = c > ma200, c < ma200
    out["RSI2 の押し目（長い平均の向きだけ）"] = ((r2 < 10) & up).astype(float) - ((r2 > 90) & dn).astype(float)
    f, s = c.rolling(10).mean(), c.rolling(50).mean()
    cross = np.sign(f - s)
    out["移動平均の交差（10/50）"] = cross.where(cross != cross.shift(1), 0.0).fillna(0.0)
    bw = (4 * s20 / ma20)
    tight = bw <= bw.rolling(120, min_periods=80).quantile(0.10)
    out["値幅の縮小からの放れ"] = bb.where(tight.shift(1).fillna(False).astype(bool), 0.0)
    big = r1.abs() > 3 * sd.shift(1)
    out["大きな足に乗る"] = np.sign(r1).where(big, 0.0)
    out["大きな足の逆"] = -np.sign(r1).where(big, 0.0)
    body, pbody = c - o, (c - o).shift(1)
    eng_up = (body > 0) & (pbody < 0) & (c > o.shift(1)) & (o < c.shift(1))
    eng_dn = (body < 0) & (pbody > 0) & (c < o.shift(1)) & (o > c.shift(1))
    out["包み足に乗る"] = eng_up.astype(float) - eng_dn.astype(float)
    inside = (h.shift(1) < h.shift(2)) & (l.shift(1) > l.shift(2))
    out["はらみ足からの放れ"] = (inside & (c > h.shift(2))).astype(float) - (inside & (c < l.shift(2))).astype(float)
    zz = (c - c.rolling(100).mean()) / c.rolling(100).std()
    out["平均からのずれ2.5σの戻り"] = -np.sign(zz).where(zz.abs() > 2.5, 0.0)
    s_up = (r1 > 0).astype(int)
    st_up = s_up.rolling(4).sum() == 4
    st_dn = (r1 < 0).astype(int).rolling(4).sum() == 4
    out["4本連続の逆"] = st_dn.astype(float) - st_up.astype(float)
    out["4本連続に乗る"] = st_up.astype(float) - st_dn.astype(float)
    vr = r1.rolling(20).std() / r1.rolling(200, min_periods=120).std()
    m12 = np.sign(z(12)).where(z(12).abs() > 1.0, 0.0)
    out["値動きが拡大中の勢い12本"] = m12.where(vr > 1.2, 0.0)
    out["値動きが縮小中の勢い12本"] = m12.where(vr < 0.8, 0.0)
    out["値動きが縮小中の戻り（ボリンジャー）"] = (-bb).where(vr < 0.8, 0.0)
    # 金利差の向き（そのペアに金利差があるときだけ）
    cd = carry_dir.reindex(c.index.normalize()).values
    cd = pd.Series(cd, index=c.index).fillna(0.0)
    out["金利差の向きへの押し目（RSI2）"] = ((r2 < 10) & (cd > 0)).astype(float) - ((r2 > 90) & (cd < 0)).astype(float)
    out["金利差の向きの勢い12本"] = m12.where(m12 == cd, 0.0)
    out["金利差の向きへの押し目（ボリンジャー）"] = ((bb < 0) & (cd > 0)).astype(float) - ((bb > 0) & (cd < 0)).astype(float)
    return {k: v.fillna(0.0).values for k, v in out.items()}


def main():
    carry = None
    acc = defaultdict(lambda: [None, None, None])      # (tf, sig, H) → [日ごとの合計(コスト後), 件数, 合計(コスト前)]
    for pair in PAIRS:
        pip = D.pip_size(pair)
        cost_p = (S.COST.get(pair, 2.0) + 0.5) * pip
        for tfname, mins in TFS:
            b = bars(pair, mins)
            if carry is None:
                import styles_long as SL
                px_d = F.prices()
                cr = F.carry_daily(px_d.index)
                carry = np.sign(cr).where(cr.abs() - SL.MARKUP >= 1.0, 0.0)
            cdir = carry[pair]
            sig = signals(b, cdir)
            o = b["o"].values
            idx = b.index
            ny_h = idx.tz_localize("UTC").tz_convert("America/New_York").hour.values
            ok_entry = np.ones(len(b), bool)
            if mins < 1440:
                nh = np.r_[ny_h[1:], -1]                      # 入る足（次の足）の NY の時
                ok_entry = ~((nh >= 16) & (nh <= 18))
            r1 = b["c"].pct_change()
            per_day = {15: 96, 60: 24, 240: 6, 1440: 1}[mins]
            dvol = (r1.rolling(per_day * 20, min_periods=per_day * 10).std() * np.sqrt(per_day)).values
            entry = np.r_[o[1:], np.nan]
            for H in HOLDS:
                exit_ = np.r_[o[1 + H:], np.full(1 + H, np.nan)]
                exit_t = np.r_[idx.values[1 + H:], np.full(1 + H, np.datetime64("NaT"))]
                raw = (exit_ / entry - 1.0)
                for name, s in sig.items():
                    m = (s != 0) & ok_entry & ~np.isnan(raw) & ~np.isnan(dvol) & (dvol > 0)
                    if m.sum() == 0:
                        continue
                    g = s[m] * raw[m]
                    net = g - cost_p / entry[m]
                    day = pd.DatetimeIndex(exit_t[m]).normalize()
                    dfe = pd.DataFrame({"n": net / dvol[m], "g": g / dvol[m], "c": 1.0}, index=day).groupby(level=0).sum()
                    a = acc[(tfname, name, H)]
                    for i, col in enumerate(("n", "c", "g")):
                        a[i] = dfe[col] if a[i] is None else a[i].add(dfe[col], fill_value=0.0)
        print(pair, "done", flush=True)
    rows = []
    for (tf, name, H), (n, c, g) in acc.items():
        rec = {"tf": tf, "pattern": name, "hold": H}
        for pname, a, b in PER:
            # 日ごとの損益の「合計」で評価する（シグナルをすべて同じ大きさで取引した場合の損益。シグナルのない日は 0）。
            # 最初の版は日ごとの「平均」で評価していたが、多くのペアが同時に動いて大きく負ける日を軽く数えてしまい、
            # 実際の取引の損益と逆の結果になった（mr_deepdive.py で確認）。
            days = pd.bdate_range(a, min(pd.Timestamp(b) - pd.Timedelta(days=1), n.index.max()))
            x = n.reindex(days, fill_value=0.0)
            y = g.reindex(days, fill_value=0.0)
            cnt = c.reindex(days, fill_value=0.0).sum()
            t = x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 30 and x.std() > 0 else 0.0
            tg = y.mean() / y.std() * np.sqrt(len(y)) if len(y) > 30 and y.std() > 0 else 0.0
            rec.update({f"{pname}_t": t, f"{pname}_tg": tg, f"{pname}_mean": x.sum() / cnt if cnt else 0.0, f"{pname}_n": int(cnt)})
        rows.append(rec)
    df = pd.DataFrame(rows)
    out_dir = os.path.join(ROOT, "reports", "research")
    df.round(4).to_csv(os.path.join(out_dir, "pattern_zoo_all.csv"), index=False)
    n_all = len(df)
    pas = df[(df["設計_t"] >= 3.0) & (df["選ぶ_t"] >= 2.0)].sort_values("設計_t", ascending=False)
    gross = df[(df["設計_tg"] >= 3.0) & (df["選ぶ_tg"] >= 2.0)]
    lines = ["# 短期・中期の層：値動きのパターンの一斉検証（`tools/research/pattern_zoo.py`）", "",
             f"調べた組み合わせ：{n_all} 通り（時間足 4 × パターン {df['pattern'].nunique()} × 保有 3、17ペアをまとめて評価）。",
             "t 値は、コスト後の損益（各ペアの1日の値動きの大きさで割ったもの）の日ごとの合計から計算（シグナルをすべて同じ大きさで取引した場合）。3 以上で「偶然ではなさそう」。", "",
             f"- コスト後で合格（設計 t ≥ 3 かつ 選ぶ期間 t ≥ 2）：**{len(pas)} 通り**",
             f"- 参考：コストを引く前なら同じ基準を満たすもの：{len(gross)} 通り", ""]
    if len(pas):
        lines += ["## コスト後で合格したもの", "", "| 時間足 | パターン | 保有 | 設計 t（件数） | 選ぶ t | 答え合わせ1 t | 答え合わせ2 t |", "|---|---|---|---|---|---|---|"]
        for _, r in pas.iterrows():
            lines.append(f"| {r.tf} | {r.pattern} | {r.hold}本 | {r['設計_t']:+.1f}（{r['設計_n']}） | {r['選ぶ_t']:+.1f} | {r['答え合わせ1_t']:+.1f} | {r['答え合わせ2_t']:+.1f} |")
        lines.append("")
    lines += ["## コストを引く前の t 値が大きいもの（上位15、設計期間）", "",
              "| 時間足 | パターン | 保有 | 設計：コスト前 t → コスト後 t | 選ぶ：前 → 後 | 答え合わせ1：前 → 後 | 答え合わせ2：前 → 後 |", "|---|---|---|---|---|---|---|"]
    for _, r in df.sort_values("設計_tg", ascending=False).head(15).iterrows():
        lines.append(f"| {r.tf} | {r.pattern} | {r.hold}本 | {r['設計_tg']:+.1f} → {r['設計_t']:+.1f} | {r['選ぶ_tg']:+.1f} → {r['選ぶ_t']:+.1f} | "
                     f"{r['答え合わせ1_tg']:+.1f} → {r['答え合わせ1_t']:+.1f} | {r['答え合わせ2_tg']:+.1f} → {r['答え合わせ2_t']:+.1f} |")
    lines += ["", "## コスト後の t 値の分布（設計期間）", ""]
    q = df["設計_t"]
    lines.append(f"- 最大 {q.max():+.1f}、上位10% {q.quantile(0.9):+.1f}、中央 {q.median():+.1f}、下位10% {q.quantile(0.1):+.1f}、最小 {q.min():+.1f}。プラスは {int((q > 0).sum())}/{n_all} 通り。")
    open(os.path.join(out_dir, "pattern_zoo.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""研究：当局が動きをならしている通貨（人民元など）は、流れに乗る形で利益が出るか（108章）。日付・時刻は使わない。

- 考え方：主要通貨の順張りは、この20年ほとんど利益がない（88章）。値段が自由に動く市場では、流れはすぐ消える。
  一方、人民元（USDCNH）やシンガポールドル（USDSGD）は、当局が毎日の動きをならしながら、ゆっくり誘導している。動きをならすと、
  同じ向きの小さな動きが続きやすくなる（値動きの自己相関がプラスになる）。それなら、「流れに乗る」形が理屈の上で有利になる。
  どちらも OANDA の為替の口座で売買できるが、まだ一度も検証していない（OANDA の今のスワップ：USDCNH 買い 年 +2.90%・売り −2.91%）。
- 形（結果を見る前に決めた。これ以外は試さない）：
   Y1 流れだけ：終値が200日の平均より上なら米ドル買い、下なら米ドル売り（指数・金の順張りの層と同じ決め方）。5取引日ごとに見直す
   Y2 金利差 ＋ 流れ（人民元だけ）：金利差を受け取れる向き（米国と中国の3か月金利の差が 0.5% を超える側）で、かつ流れが同じ向きのときだけ持つ
  建玉は、その通貨の値動き（直近60日）が口座の年10%になる大きさ。上限は資金の4倍（人民元は値動きが年3〜4%と小さいため）。
- 損益の数え方：為替の損益から、スプレッド（往復 0.03%）を引く。金利差は控えめに扱う：受け取る側のときは 0（数えない）、払う側のときは全額を払う
  （香港で取引される人民元の金利は、中国本土の金利と違い、過去の値が手に入らないため。受け取りを数えた場合は参考として並べる）。
- データ：FRED の日々の為替レート（米国の公表値。USD/CNY は 2005年7月の切り上げ以降、USD/SGD は 1999年〜）。香港の人民元（CNH）の値段は、本土（CNY）とほぼ同じに動く。
  確かめ用（売買はできない。「ならされた通貨では流れが続く」が一般に成り立つかを見る）：インドルピー・韓国ウォン・タイバーツ・マレーシアリンギ・台湾ドル。
- 判定（結果を見る前に決めた）。次の検証（MT5）に進めるのは、すべて満たすときだけ：
   (a) 人民元の Y1 が、全期間でシャープ 0.4 以上、4つの期間（2005〜10・2011〜15・2016〜21・2022年〜）のうち3つ以上でプラス
   (b) シンガポールドルの Y1 がプラス。確かめ用の5通貨の Y1 のうち、4つ以上がプラス
   (c) 人民元の Y1 と指数の口座の、週ごとの損益の相関が ±0.2 以内
   (d) 指数 ＋ 金の口座（半分ずつ）に 20% 足したとき（指数 40・金 40・この層 20）、最大の下落をそろえた年率が、前半（2007〜16年）・後半（2017年〜）の両方で上がる
使い方: python3 tools/research/cnh_trend.py  → reports/research/cnh_trend.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import composite_20y as C20  # noqa: E402
import composite_accounts as CA  # noqa: E402
import em_carry as EC  # noqa: E402
import fred_data as F  # noqa: E402
import index_trend_combo as ITC  # noqa: E402
import target300 as T  # noqa: E402

ANN = 252
PER = (("2005〜10年", "2005-08-01", "2011-01-01"), ("2011〜15年", "2011-01-01", "2016-01-01"), ("2016〜21年", "2016-01-01", "2022-01-01"), ("2022年〜", "2022-01-01", "2030-01-01"))
MAIN = (("人民元（USD/CNY）", "DEXCHUS", "2005-08-01"), ("シンガポールドル（USD/SGD）", "DEXSIUS", "1999-01-01"))
CHECK = (("インドルピー", "DEXINUS"), ("韓国ウォン", "DEXKOUS"), ("タイバーツ", "DEXTHUS"), ("マレーシアリンギ", "DEXMAUS"), ("台湾ドル", "DEXTAUS"))
SPREAD, CAP = 0.0003, 4.0


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 100 and x.std() > 0 else np.nan


def sleeve(code, start, form="Y1", carry=None, receive=0.0, unit=0.10, check=5):
    """戻り値：日々の損益（口座に対する割合）、建玉（倍率）。carry：米ドル買いで受け取る年率 %（日ごと）。receive：受け取る側のとき、その何倍を数えるか。"""
    c = F.fetch(code).dropna()
    c = c[c.index >= pd.Timestamp(start) - pd.Timedelta(days=420)]
    r = c.pct_change().fillna(0.0)
    sma = c.rolling(200).mean()
    tr = pd.Series(np.where(c > sma, 1.0, -1.0), index=c.index).where(sma.notna())
    if form == "Y2":
        cs = carry.reindex(c.index).ffill()
        side = np.sign(cs).where(cs.abs() > 0.5, 0.0)
        tr = side.where(side == tr, 0.0).where(sma.notna())
    st = np.full(len(c), np.nan)
    last, cur = None, np.nan
    for i in range(len(c)):
        v = tr.iloc[i]
        if pd.isna(v):
            continue
        if last is None or i - last >= check:
            cur, last = float(v), i
        st[i] = cur
    st = pd.Series(st, index=c.index)
    vol = (r.rolling(60).std() * np.sqrt(ANN)).clip(lower=0.01)
    w = (st * unit / vol).clip(-CAP, CAP).shift(1).fillna(0.0)
    days = pd.Series(c.index, index=c.index).diff().dt.days.fillna(1.0).clip(upper=5)
    p = w * r - (w - w.shift(1).fillna(0.0)).abs() * SPREAD / 2.0
    if carry is not None:
        cs = carry.reindex(c.index).ffill().fillna(0.0)
        earn = np.where(np.sign(w) == np.sign(cs), cs.abs() * receive, -cs.abs())
        p = p + w.abs() * pd.Series(earn, index=c.index) / 100.0 / 365.0 * days
    keep = p.index >= start
    return p[keep], w[keep]


def main():
    us = F.fetch("IR3TIB01USM156N").dropna()
    cn = F.fetch("IR3TIB01CNM156N").dropna()
    carry_cn = (us - cn.reindex(us.index, method="ffill")).dropna().shift(1).dropna()
    daily = pd.date_range(carry_cn.index[0], "2026-12-31", freq="D")
    carry_cn = carry_cn.reindex(daily).ffill()
    lines = ["# 研究：当局が動きをならしている通貨の順張り（`tools/research/cnh_trend.py`）", "",
             "建玉は、その通貨の値動きが口座の年10%になる大きさ（上限 4倍）。スプレッド込み。金利差は、受け取りを数えず、支払いだけを引く（控えめ）。", "",
             "## 1 売買できる2つの通貨", "",
             "| 通貨 | 形 | シャープ（全期間） | " + " | ".join(p[0] for p in PER) + " | 年率 | 最大の下落 | 建玉の平均（倍） | 持っている日の割合 | （参考）金利差の受け取りも数えた場合のシャープ |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    R = {}
    for name, code, start in MAIN:
        forms = (("Y1 流れだけ", "Y1"), ("Y2 金利差 ＋ 流れ", "Y2")) if code == "DEXCHUS" else (("Y1 流れだけ", "Y1"),)
        for lab, form in forms:
            cr = carry_cn if code == "DEXCHUS" else None
            p, w = sleeve(code, start, form, cr, 0.0)
            ref = sh(sleeve(code, start, form, cr, 1.0)[0]) if cr is not None else np.nan
            R[(code, form)] = p
            e = (1 + p).cumprod()
            lines.append(f"| {name} | {lab} | {sh(p):+.2f} | " + " | ".join(f"{sh(p[(p.index >= a) & (p.index < b)]):+.2f}" for _, a, b in PER) +
                         f" | {p.mean() * ANN * 100:+.1f}% | {(e / e.cummax() - 1).min() * 100:.0f}% | {w.abs().mean():.1f} | {(w != 0).mean() * 100:.0f}% | {'—' if np.isnan(ref) else f'{ref:+.2f}'} |")
            print(lines[-1], flush=True)
    lines += ["", "## 2 確かめ用の5通貨（Y1。為替の損益だけ）", "", "| 通貨 | シャープ（2000年〜） | " + " | ".join(p[0] for p in PER) + " | 値動き（年率） |", "|---|---|---|---|---|---|---|"]
    npos = 0
    for name, code in CHECK:
        p, _ = sleeve(code, "2000-01-01")
        r0 = F.fetch(code).dropna().pct_change()
        npos += int(sh(p) > 0)
        lines.append(f"| {name} | {sh(p):+.2f} | " + " | ".join(f"{sh(p[(p.index >= a) & (p.index < b)]):+.2f}" for _, a, b in PER) + f" | {r0[r0.index >= '2000'].std() * np.sqrt(ANN) * 100:.1f}% |")
        print(lines[-1], flush=True)
    # ---------- 指数・金の口座との関係
    cat = CA.catalog()
    E = {k: CA.rel(c) for k, c in cat.items()}
    rep = T.cash_returns(5.0).add(ITC.trend_returns("NASDAQ100", 10.0), fill_value=0.0)
    idx, _, _, _ = C20.spliced(E[("Index_Demo", 0.0, "long")], rep)
    idx = idx[idx.index >= C20.START]
    gold = E[("金", 22.4, "long")].pct_change().dropna()
    gold = gold[gold.index >= C20.START]
    p = R[("DEXCHUS", "Y1")]
    z = pd.concat([idx, gold, p], axis=1, sort=True).fillna(0.0)
    z.columns = ["i", "g", "c"]
    z = z[(z.index >= C20.START) & (z.index <= min(idx.index[-1], p.index[-1]))]
    k = z["i"].std() / z["c"].std()
    wk = z.resample("W").sum()
    rho = wk[["i", "c"]].corr().iloc[0, 1]
    import stop_cooloff as SC
    ep = [(lab, float(p[(p.index > a) & (p.index <= b)].sum())) for lab, a, b in SC.EPISODES if pd.Timestamp(a) >= p.index[0]]
    cells, okd = [], True
    for a, b in ((C20.START, "2030-01-01"), (C20.START, "2017-01-01"), ("2017-01-01", "2030-01-01")):
        q = z[(z.index >= a) & (z.index < b)]
        b0 = EC.st20(0.5 * q["i"] + 0.5 * q["g"])
        c1 = EC.same_dd(0.4 * q["i"] + 0.4 * q["g"] + 0.2 * k * q["c"], b0["dd"])
        cells.append(f"{b0['cagr'] * 100:+.1f}% → {c1 * 100:+.1f}%")
        if a != C20.START or b != "2030-01-01":
            okd = okd and c1 > b0["cagr"]
    lines += ["", "## 3 人民元の Y1 と、指数・金の口座", "",
              f"- 指数の口座との相関（週ごとの損益）：{rho:+.2f}。金の口座との相関：{wk[['g', 'c']].corr().iloc[0, 1]:+.2f}",
              "- 株の急落の局面の損益（建玉 年10%。%）：" + "、".join(f"{lab} {v * 100:+.1f}" for lab, v in ep) + f"。合計 {sum(v for _, v in ep) * 100:+.1f}%",
              f"- 指数 50・金 50 → 指数 40・金 40・この層 20（値動きは指数の口座にそろえる）：最大の下落をそろえた年率 全期間 {cells[0]}、前半（2007〜16年）{cells[1]}、後半（2017年〜）{cells[2]}",
              "- 年ごとの損益（建玉 年10%。%）：" + " ".join(f"{y % 100:02d}:{v * 100:+.0f}" for y, v in ((1 + p).groupby(p.index.year).prod() - 1).items())]
    print("\n".join(lines[-4:]), flush=True)
    y1 = R[("DEXCHUS", "Y1")]
    npp = sum(sh(y1[(y1.index >= a) & (y1.index < b)]) > 0 for _, a, b in PER)
    a_ok = sh(y1) >= 0.4 and npp >= 3
    b_ok = sh(R[("DEXSIUS", "Y1")]) > 0 and npos >= 4
    c_ok = abs(rho) <= 0.2
    lines += ["", "## 4 判定（事前に決めた基準）", "",
              f"- (a) 人民元の Y1：シャープ 0.4 以上・4期間のうち3つ以上でプラス：{'○' if a_ok else '×'}（{sh(y1):+.2f}、{npp} / 4）",
              f"- (b) シンガポールドルがプラス・確かめ用の5通貨のうち4つ以上がプラス：{'○' if b_ok else '×'}（{sh(R[('DEXSIUS', 'Y1')]):+.2f}、{npos} / 5）",
              f"- (c) 指数の口座との相関が ±0.2 以内：{'○' if c_ok else '×'}（{rho:+.2f}）",
              f"- (d) 足すと、最大の下落をそろえた年率が前半・後半とも上がる：{'○' if okd else '×'}",
              f"- 判定：{'**次の検証（MT5）に進める**' if (a_ok and b_ok and c_ok and okd) else '不合格'}"]
    print("\n".join(lines[-5:]), flush=True)
    open(os.path.join(F.ROOT, "reports", "research", "cnh_trend.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

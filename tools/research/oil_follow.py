#!/usr/bin/env python3
"""研究：原油は、きのうの株・銅の値動きに、1日遅れて付いていくか。それを売買すると、コスト後に残るか（108章）。日付・時刻は使わない。

- きっかけ：銘柄どうしの先行・遅行の総当たり（lead_lag_screen.py、900 通り）で、基準（前半 |t| ≥ 3.5・後半 同じ向きに |t| ≥ 2）を通った5組のうち3組が
  「中国株（CHINA50）・銅のきのうの値動き → 原油（USOIL・UKOIL）のきょうの値動き」だった。日足の区切りのずれによる見かけの関係ではないことは、
  別の業者の1分足（区切りを自分でそろえたもの）と、公開の日足（中国・香港の現物の終値 → 半日あとから始まる原油の値動き）で確かめた。
  ただし、公開の日足では、2000年〜2016年6月には、この関係はまったく無い（相関 −0.02〜0.00）。2016年7月以降だけの性質である。
- 形（結果を見る前に決めた。これ以外は試さない）：
   合図 S：きのうの値動き（それぞれ直近60日の値動きの大きさで割り、±2.5 で打ち切る）の、US500・銅・CHINA50 の3つの平均。日足は NY 17時区切り。
   建玉：きょう1日、原油（USOIL と UKOIL を半分ずつ）を S に比例して持つ（S がプラスなら買い、マイナスなら売り）。
         大きさは、S = 1 のとき、原油の値動き（直近60日）が口座の年10%になる大きさ。毎日、区切りで合わせ直す。
   F1：上のとおり／F2：|S| が 0.5 未満の日は持たない（小さな合図での売買をやめて、コストを減らす）
- コスト：スプレッド（USOIL・UKOIL とも 0.05ドル。建玉を変えた分にかかる）、業者の取り分 年2.5%（持っている建玉の額に対して。買い・売りとも）。
  値段に入っている割増・割引（ベーシス）は、公式の説明どおりスワップで打ち消されるものとする（107章。買い・売りを毎日入れ替えるので、打ち消しが不完全でも、ほぼ相殺される）。
- データ：OANDA の実際の日足（指数の口座・商品の口座。2016年7月〜2026年11月）。
- 判定（結果を見る前に決めた）。次の検証（EA への実装と MT5）に進めるのは、同じ形が次をすべて満たすときだけ：
   (a) コスト後のシャープが、前半（2016年7月〜2021年）・後半（2022年〜）の両方で 0.5 以上
   (b) 2022年以降の5つの年のうち、4つ以上でプラス
   (c) 指数の戻りの層との、日々の損益の相関が +0.2 以下
   (d) 株の急落の局面（2018年2月・2018年9〜12月・2020年2〜3月・2022年・2024年7〜8月・2025年2〜4月）の損益の合計が、マイナスでない
   (e) スプレッドを2倍にしても、全期間のシャープが 0.3 以上
- 参考（判定には使わない）：公開の日足（S&P500・銅の先物・ハンセン → 原油の先物）で、同じ形を 2000年〜2016年6月に当てはめた場合（この関係が無かった時期の成績）。
- 追加（上の判定のあとで決めた。実際に売買できる形での確かめ。結果を見る前に決めた）：
   上の計算は、日足の終値から次の終値までの値動きで損益を数えている。実際には、合図が決まる NY 17時には原油は取引が止まっていて、買えるのは 18時の再開のあと。
   また、OANDA の原油の日足の終値・始値には、スプレッドが広がった瞬間の値段が入っていて、1〜2% の雑音がある（終値から次の始値までの「飛び」の大きさが、1日の値動きより大きい）。
   そこで、(1) 損益を「始値から次の始値まで」で数える形、(2) 別の業者の原油の1分足で「18:05 に合わせ、次の 18:05 まで持つ」形、の2つで測り直す。
   合図は、商品の口座で実際に読める銘柄だけにする：X2 ＝ US500 と銅の平均（CHINA50 は商品の口座にない）。X3 ＝ US500・銅・CHINA50（上と同じ。比較用）。
   判定は X2 に、上の (a)〜(e) と同じ基準を当てる（(1) の OANDA の日足・USOIL と UKOIL 半分ずつ で判定。(2) は、同じ向き＝前半・後半ともプラスであることを確かめる）。
使い方: python3 -I tools/research/oil_follow.py <指数の口座の書き出し> <商品の口座の書き出し>  → reports/research/oil_follow.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_others as IO  # noqa: E402
import target300 as T  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
SPLIT = "2022-01-01"
EP = (("2018年1〜2月", "2018-01-26", "2018-02-08"), ("2018年9〜12月", "2018-09-20", "2018-12-24"), ("2020年2〜3月", "2020-02-19", "2020-03-23"),
      ("2022年1〜10月", "2022-01-03", "2022-10-12"), ("2024年7〜8月", "2024-07-16", "2024-08-05"), ("2025年2〜4月", "2025-02-19", "2025-04-08"))


def zret(c):
    r = c.pct_change()
    return (r / r.rolling(60, min_periods=40).std().shift(1)).clip(-2.5, 2.5)


def sleeve(sig, oils, spreads, unit=0.10, dead=0.0, markup=2.5, spread_mult=1.0):
    """sig：きのうまでに決まった合図（その日の終値で確定）。oils：原油の終値（銘柄 → 日足）。戻り値：日々の損益（口座に対する割合）、建玉（倍率）。"""
    out, hold = None, None
    for name, c in oils.items():
        r = c.pct_change()
        vol = (r.rolling(60, min_periods=40).std() * np.sqrt(ANN)).clip(lower=0.05)
        s = sig.reindex(c.index)
        s = s.where(s.abs() >= dead, 0.0)
        w = (s * unit / vol / len(oils)).shift(1).fillna(0.0)        # きのうの終値で決めた建玉を、きょう1日持つ
        days = pd.Series(c.index, index=c.index).diff().dt.days.fillna(1.0)
        cost = (w - w.shift(1).fillna(0.0)).abs() * spreads[name] * spread_mult / 2.0 + w.abs() * markup / 100.0 / 360.0 * days
        p = w * r.fillna(0.0) - cost
        out = p if out is None else out.add(p, fill_value=0.0)
        hold = w.abs() if hold is None else hold.add(w.abs(), fill_value=0.0)
    return out, hold


def sleeve_open(sig, bars, spreads, unit=0.10, dead=0.0, markup=2.5, spread_mult=1.0):
    """実際に売買できる形：きのうの終値で決まった合図で、きょうの始値（18時の再開）に建玉を合わせ、次の日の始値まで持つ。bars：銘柄 → 日足（open・close）。"""
    out, hold = None, None
    for name, d in bars.items():
        o, c = d["open"], d["close"]
        vol = (c.pct_change().rolling(60, min_periods=40).std() * np.sqrt(ANN)).clip(lower=0.05)
        s = sig.reindex(d.index)
        s = s.where(s.abs() >= dead, 0.0)
        w = (s * unit / vol / len(bars)).shift(1).fillna(0.0)        # きのうの終値で決め、きょうの始値から持つ
        r = (o.shift(-1) / o - 1.0).fillna(0.0)                       # きょうの始値 → 次の日の始値
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
        cost = (w - w.shift(1).fillna(0.0)).abs() * spreads[name] * spread_mult / 2.0 + w.abs() * markup / 100.0 / 360.0 * days
        p = w * r - cost
        out = p if out is None else out.add(p, fill_value=0.0)
        hold = w.abs() if hold is None else hold.add(w.abs(), fill_value=0.0)
    return out, hold


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 60 and x.std() > 0 else np.nan


def main():
    ix, _ = IO.load(sys.argv[1])
    cm, pc = IO.load(sys.argv[2])
    sig = pd.concat([zret(ix["US500"]["close"]), zret(cm["COPPER"]["close"]), zret(ix["CHINA50"]["close"])], axis=1, sort=True).dropna().mean(axis=1)
    oils = {s: cm[s]["close"] for s in ("USOIL", "UKOIL")}
    spreads = {s: 0.05 / float(pc.loc[s, "bid"]) for s in oils}
    rev = T.cash_returns(5.0)
    lines = ["# 研究：原油は、きのうの株・銅の値動きに付いていくか（`tools/research/oil_follow.py`）", "",
             "合図 S ＝ きのうの US500・銅・CHINA50 の値動き（値動きの大きさで割ったもの）の平均。S に比例して、きょう1日、原油（USOIL・UKOIL 半分ずつ）を持つ。コスト込み。", "",
             "## 1 OANDA の実際の日足（2016年7月〜）", "",
             "| 形 | シャープ（全期間） | 前半（〜2021年） | 後半（2022年〜） | 年率（S = 1 で年10%） | 最大の下落 | 建玉の平均（資金に対する倍率） | 指数の戻りの層との相関 | 急落の局面の合計 | スプレッド2倍のシャープ | コスト前のシャープ |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for lab, dead in (("F1 S に比例", 0.0), ("F2 |S| が 0.5 未満の日は持たない", 0.5)):
        r, hold = sleeve(sig, oils, spreads, dead=dead)
        r = r[r.index >= "2016-07-01"]
        r2, _ = sleeve(sig, oils, spreads, dead=dead, spread_mult=2.0)
        r0, _ = sleeve(sig, oils, {k: 0.0 for k in spreads}, dead=dead, markup=0.0)
        a, b = r[r.index < SPLIT], r[r.index >= SPLIT]
        z = pd.concat([r, rev], axis=1, sort=True).dropna()
        rho = z.corr().iloc[0, 1]
        ep = [float(r[(r.index > x) & (r.index <= y)].sum()) for _, x, y in EP]
        yr = (1 + r).groupby(r.index.year).prod() - 1
        e = (1 + r).cumprod()
        res[lab] = dict(a=sh(a), b=sh(b), rho=rho, ep=sum(ep), yr=yr, s2=sh(r2[r2.index >= "2016-07-01"]), eplist=ep, r=r)
        lines.append(f"| {lab} | {sh(r):+.2f} | {sh(a):+.2f} | {sh(b):+.2f} | {r.mean() * ANN * 100:+.1f}% | {(e / e.cummax() - 1).min() * 100:.0f}% | {hold[hold.index >= '2016-07-01'].mean():.2f} | {rho:+.2f} | {sum(ep) * 100:+.1f}% | "
                     f"{res[lab]['s2']:+.2f} | {sh(r0[r0.index >= '2016-07-01']):+.2f} |")
        print(lines[-1], flush=True)
    lines += ["", "年ごとの損益（%）：", "", "| 形 | " + " | ".join(str(y) for y in range(2016, 2027)) + " |", "|---|" + "---|" * 11]
    for lab, x in res.items():
        lines.append(f"| {lab} | " + " | ".join(f"{x['yr'].get(y, np.nan) * 100:+.1f}" for y in range(2016, 2027)) + " |")
        print(lines[-1], flush=True)
    lines += ["", "株の急落の局面ごとの損益（%）：", "", "| 形 | " + " | ".join(e[0] for e in EP) + " |", "|---|" + "---|" * len(EP)]
    for lab, x in res.items():
        lines.append(f"| {lab} | " + " | ".join(f"{v * 100:+.1f}" for v in x["eplist"]) + " |")
        print(lines[-1], flush=True)
    # ---------- 参考：公開の日足で、2000年〜2016年6月
    cl = Y.fetch_ticker("CLF", "CL=F")["close"].dropna()
    cl = cl[cl > 0]
    pub = pd.concat([zret(Y.fetch("SPX")["close"].dropna()), zret(Y.fetch_ticker("HGF", "HG=F")["close"].dropna()), zret(Y.fetch("HSI")["close"].dropna())], axis=1, sort=True).dropna().mean(axis=1)
    rp, _ = sleeve(pub, {"CL": cl}, {"CL": 0.0006})
    lines += ["", "## 2 参考：公開の日足（S&P500・銅の先物・ハンセン → 原油の先物）で、同じ形", "",
              "現物の終値・先物の清算値は時刻がそろっていない（株の終値のほうが原油の清算より遅い）ので、この表は実際より良く出る側にずれる。それでも 2016年より前は 0 に近い。", "",
              "| 期間 | シャープ（コスト後） |", "|---|---|"]
    for lab, a, b in (("2000年9月〜2008年", "2000-09-01", "2009-01-01"), ("2009年〜2016年6月", "2009-01-01", "2016-07-01"), ("2016年7月〜2021年", "2016-07-01", "2022-01-01"), ("2022年〜", "2022-01-01", "2030-01-01")):
        x = rp[(rp.index >= a) & (rp.index < b)]
        lines.append(f"| {lab} | {sh(x):+.2f} |")
        print(lines[-1], flush=True)
    # ---------- 判定
    lines += ["", "## 3 判定（事前に決めた基準）", "", "| 形 | (a) 前半・後半とも 0.5 以上 | (b) 2022年以降の5年のうち4年以上プラス | (c) 相関 +0.2 以下 | (d) 急落の局面の合計がマイナスでない | (e) スプレッド2倍で 0.3 以上 | 判定 |", "|---|---|---|---|---|---|---|"]
    for lab, x in res.items():
        a = x["a"] >= 0.5 and x["b"] >= 0.5
        npos = int(sum(x["yr"].get(y, -1) > 0 for y in range(2022, 2027)))
        b = npos >= 4
        c = x["rho"] <= 0.2
        d = x["ep"] >= 0
        e = x["s2"] >= 0.3
        lines.append(f"| {lab} | {'○' if a else '×'}（{x['a']:+.2f}・{x['b']:+.2f}） | {'○' if b else '×'}（{npos} / 5） | {'○' if c else '×'}（{x['rho']:+.2f}） | {'○' if d else '×'}（{x['ep'] * 100:+.1f}%） | "
                     f"{'○' if e else '×'}（{x['s2']:+.2f}） | {'**次の検証に進める**' if (a and b and c and d and e) else '不合格'} |")
        print(lines[-1], flush=True)
    # ---------- 実際に売買できる形（始値から次の始値まで。合図は商品の口座で読める銘柄だけ）
    sig2 = pd.concat([zret(ix["US500"]["close"]), zret(cm["COPPER"]["close"])], axis=1, sort=True).dropna().mean(axis=1)
    bars = {s_: cm[s_] for s_ in ("USOIL", "UKOIL")}
    lines += ["", "## 4 実際に売買できる形：始値（NY 18時の再開）に建玉を合わせ、次の日の始値まで持つ", "",
              "| 合図 | 売買する銘柄 | シャープ（全期間） | 前半 | 後半 | 年率 | 最大の下落 | 指数の戻りの層との相関 | 急落の局面の合計（局面ごと） | スプレッド2倍 | 2022年以降のプラスの年 | 年ごと（%） |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    res2 = {}
    for slab, sg in (("X2 US500・銅", sig2), ("X3 US500・銅・CHINA50", sig)):
        for blab, bb in (("USOIL・UKOIL 半分ずつ", bars), ("USOIL だけ", {"USOIL": cm["USOIL"]}), ("UKOIL だけ", {"UKOIL": cm["UKOIL"]})):
            r, hold = sleeve_open(sg, bb, spreads)
            r = r[(r.index >= "2016-07-01")].iloc[:-1]
            r2, _ = sleeve_open(sg, bb, spreads, spread_mult=2.0)
            r2 = r2[r2.index >= "2016-07-01"].iloc[:-1]
            a, b = r[r.index < SPLIT], r[r.index >= SPLIT]
            z = pd.concat([r, rev], axis=1, sort=True).dropna()
            ep = [float(r[(r.index > x) & (r.index <= y)].sum()) for _, x, y in EP]
            yr = (1 + r).groupby(r.index.year).prod() - 1
            e = (1 + r).cumprod()
            npos = int(sum(yr.get(y, -1) > 0 for y in range(2022, 2027)))
            res2[(slab, blab)] = dict(a=sh(a), b=sh(b), rho=z.corr().iloc[0, 1], ep=sum(ep), s2=sh(r2), npos=npos)
            lines.append(f"| {slab} | {blab} | {sh(r):+.2f} | {sh(a):+.2f} | {sh(b):+.2f} | {r.mean() * ANN * 100:+.1f}% | {(e / e.cummax() - 1).min() * 100:.0f}% | {z.corr().iloc[0, 1]:+.2f} | "
                         f"{sum(ep) * 100:+.1f}%（{'・'.join(f'{v * 100:+.1f}' for v in ep)}） | {sh(r2):+.2f} | {npos} / 5 | " + " ".join(f"{str(y)[2:]}:{v * 100:+.0f}" for y, v in yr.items()) + " |")
            print(lines[-1], flush=True)
    # 別の業者の1分足（原油 WTI）で、18:05 に合わせ、次の 18:05 まで持つ
    import index_zoo as IZ
    m = IZ.load("WTIUSD")
    ny = m.index.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    o1 = pd.Series(m["o"].values, index=ny)
    dayk = (o1.index + pd.Timedelta(hours=7)).normalize()
    el = ((o1.index.hour * 60 + o1.index.minute) - 17 * 60) % 1440
    ent = o1[el >= 65].groupby(dayk[el >= 65]).first()
    ent = ent[ent.index.dayofweek < 5]
    hd = pd.DataFrame({"open": ent, "close": ent.shift(-1)}).dropna()                      # close は使うのは値動きの大きさの見積もりだけ
    lines += ["", "別の業者の原油（WTI）の1分足で、NY 18:05 に建玉を合わせ、次の日の 18:05 まで持った場合（スプレッド 0.06%・業者の取り分 年2.5% 込み。2024〜25年はデータなし）：", "",
              "| 合図 | シャープ（全期間） | 前半 | 後半 | 年ごと（%） |", "|---|---|---|---|---|"]
    hd_ok = {}
    for slab, sg in (("X2 US500・銅", sig2), ("X3 US500・銅・CHINA50", sig)):
        r, _ = sleeve_open(sg, {"WTI": hd}, {"WTI": 0.0006})
        r = r[r.index >= "2016-07-01"].iloc[:-1]
        r = r[r != 0.0] if False else r
        a, b = r[r.index < SPLIT], r[r.index >= SPLIT]
        yr = (1 + r).groupby(r.index.year).prod() - 1
        hd_ok[slab] = sh(a) > 0 and sh(b) > 0
        lines.append(f"| {slab} | {sh(r):+.2f} | {sh(a):+.2f} | {sh(b):+.2f} | " + " ".join(f"{str(y)[2:]}:{v * 100:+.0f}" for y, v in yr.items()) + " |")
        print(lines[-1], flush=True)
    x = res2[("X2 US500・銅", "USOIL・UKOIL 半分ずつ")]
    ok = (x["a"] >= 0.5 and x["b"] >= 0.5, x["npos"] >= 4, x["rho"] <= 0.2, x["ep"] >= 0, x["s2"] >= 0.3, hd_ok["X2 US500・銅"])
    lines += ["", "判定（X2・USOIL と UKOIL 半分ずつ。基準は 3 と同じ）：",
              f"- (a) 前半・後半とも 0.5 以上：{'○' if ok[0] else '×'}（{x['a']:+.2f}・{x['b']:+.2f}）／(b) 2022年以降の5年のうち4年以上プラス：{'○' if ok[1] else '×'}（{x['npos']} / 5）／"
              f"(c) 相関 +0.2 以下：{'○' if ok[2] else '×'}（{x['rho']:+.2f}）／(d) 急落の局面の合計がマイナスでない：{'○' if ok[3] else '×'}（{x['ep'] * 100:+.1f}%）／"
              f"(e) スプレッド2倍で 0.3 以上：{'○' if ok[4] else '×'}（{x['s2']:+.2f}）／別の業者の1分足でも前半・後半ともプラス：{'○' if ok[5] else '×'}",
              f"- 判定：{'**次の検証（EA への実装と MT5）に進める**' if all(ok) else '不合格'}"]
    print("\n".join(lines[-2:]), flush=True)
    open(os.path.join(F.ROOT, "reports", "research", "oil_follow.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

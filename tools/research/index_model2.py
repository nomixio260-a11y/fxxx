#!/usr/bin/env python3
"""研究：予測モデルの数学的な強化（100章）。土台は99章の形（HAR 型・VIX の倍率・重み 1:2:4・逆指値 4×σ）。

A 値動きの大きさ（翌日の分散）の予測を強くする：
  har     今の形：0.37×当日 + 0.56×5日の平均 + 0.20×22日の平均（係数は固定）
  harL    下げた日の非対称性を足す（レバレッジ効果。Corsi・Renò 2012年）：＋ a×（当日の分散 × 下げた日）＋ b×（5日の平均のうち下げた日の分）
  harV    VIX の2乗を足す（Bekaert・Hoerova 2014年。VIX は1日前の終値）
  harLV   両方
  係数は、**毎年、前の年までのデータで決め直す**（マイナスの係数は 0）。現物の3指数をまとめて決める。
  物差し：見ていない期間での当てはまり（R²・QLIKE。すべての日／ルールが出ている日）、ルールが出ている日の「実際 ÷ 予測」（1 に近いほど偏りがない）、
          その予測で建玉を決めたときの層の成績（シャープ・最悪の日・下位1%の日の平均・最大の下落）。
B 状態ごとの期待値（翌日の利益 ÷ 値動きの見積もり）を左右するもの：
  B1 恐怖の上乗せ G = （VIX の水準の順位）−（実際の値動きの見積もりの順位）。メタラベリング（99章）の線形モデルが、前半・後半とも同じ符号で使っていた
  B2 3指数の同時の売られすぎ（ほかの指数にもルールが出ているか）
  B3 R2 の手じまいの形（5日の平均を上回る／RSI(2) > 65／RSI(2) > 70／前の日の高値を上回る／上げて終わった最初の日）
C 状態ごとの期待値を、毎年、前の年までのデータで計算し直す「ケリー型」の建玉（経験ベイズの縮小推定）：
  升 = ルールの数（1・2・3）× VIX の状態（低・中・高）。升の平均を、「数の効果 × VIX の効果」の掛け算の形に縮める（縮める強さは升の件数で決まる）。
  建玉 ∝ max(升の期待値, 0) ÷ 値動きの見積もり。固定の倍率（1:2:4 × 0.5/1/1.5）と比べる。学習は 1999年4月〜、予想は 2006年〜。
使い方: python3 tools/research/index_model2.py  → reports/research/index_model2.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import index_reversion as IR  # noqa: E402
import index_risk as IRK  # noqa: E402
import index_stop as IS  # noqa: E402
import index_vix_sizing as V  # noqa: E402
import index_vol_forecast as VF  # noqa: E402
import yahoo_data as Y  # noqa: E402

ANN = 252
MULT = (0.5, 1.0, 1.5)
W124 = {0: 0.0, 1: 0.25, 2: 0.5, 3: 1.0}


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 50 and x.std() > 0 else np.nan


def cell(x):
    x = x.dropna()
    if len(x) < 30:
        return "—"
    by = x.groupby(level=0).mean()
    return f"{x.mean():+.3f}（t {by.mean() / by.std() * np.sqrt(len(by)):+.1f}、{len(x)} 件）"


def sleeve_w(sets, mults, kind, sig_of=None, wmap=W124, k=4.0):
    """重み wmap（ルールの数 → 単位）と倍率 mults で、層の日次の損益。sig_of があれば、値動きの見積もりを置きかえる。"""
    ss = {}
    for name, (d, n, sg, rate, div) in sets.items():
        s2 = sg if sig_of is None else sig_of[name]
        ss[name] = (d, n.map(lambda v: wmap[int(v)]) * 3.0, s2, rate, div)
    return V.sleeve(ss, mults, kind, k)


def stat_cells(r, start, per):
    r = r[r.index >= start]
    z = r * (0.10 / (r.std() * np.sqrt(ANN)))
    eq = (1 + z).cumprod()
    yr = z.groupby(z.index.year).sum()
    q = z.quantile(0.01)
    return (f"{sh(z):+.2f} | {sh(z) * np.sqrt(len(z) / ANN):+.1f} | {z.min() * 100:.1f}% | {z[z <= q].mean() * 100:.2f}% | {(eq / eq.cummax() - 1).min() * 100:.0f}% | {yr.min() * 100:.1f}% | "
            + " | ".join(f"{sh(z[(z.index >= a) & (z.index < b)]):+.2f}" for _, a, b in per))


def var_features(d, vix2):
    dv = VF.daily_var(d)
    r = np.log(d["close"]).diff()
    dn = (r < 0).astype(float)
    X = pd.DataFrame({"d": dv, "w": dv.rolling(5).mean(), "m": dv.rolling(22).mean(), "Ld": dv * dn, "Lw": (dv * dn).rolling(5).mean(), "V": vix2})
    y = (r ** 2).shift(-1)
    return X, y


def main():
    sets = V.load_sets("cash")
    rk = {n: V.vix_rank(t[0].index)[0] for n, t in sets.items()}
    vm = {n: V.mult_of(rk[n], MULT) for n in sets}
    vixc = Y.fetch("VIX")["close"]
    lines = ["# 研究：予測モデルの数学的な強化（`tools/research/index_model2.py`）", "",
             "現物の3指数、2000年10月〜2026年11月。土台は99章の形（重み 1:2:4・VIX の倍率・逆指値 4×σ）。値動きを年10%にそろえて比べる。", ""]

    # ---------- A 分散の予測
    feats = {}
    for name, (d, n, sg, rate, div) in sets.items():
        v2 = ((vixc / 100.0) ** 2 / ANN)
        v2 = v2.reindex(v2.index.union(d.index)).ffill(limit=3).reindex(d.index).shift(1)
        feats[name] = var_features(d, v2)
    models = {"harL（下げた日の非対称性）": ["d", "w", "m", "Ld", "Lw"], "harV（＋VIX）": ["d", "w", "m", "V"], "harLV（両方）": ["d", "w", "m", "Ld", "Lw", "V"],
              "har（係数を毎年決め直す）": ["d", "w", "m"]}
    preds = {k: {name: pd.Series(np.nan, index=sets[name][0].index) for name in sets} for k in models}
    coefs = {k: None for k in models}
    for yr in range(2000, 2027):
        for k, cols in models.items():
            A, b = [], []
            for name in sets:
                X, y = feats[name]
                ok = (X.index.year < yr) & X[cols].notna().all(axis=1) & y.notna() & (X.index >= "1990-01-01")
                A.append(np.column_stack([np.ones(ok.sum()), X.loc[ok, cols].values]))
                b.append(y[ok].values)
            A, b = np.vstack(A), np.concatenate(b)
            if len(b) < 2000:
                continue
            co, *_ = np.linalg.lstsq(A, b, rcond=None)
            co = np.maximum(co, 0.0)
            coefs[k] = co
            for name in sets:
                X, _ = feats[name]
                te = (X.index.year == yr) & X[cols].notna().all(axis=1)
                preds[k][name][te] = np.column_stack([np.ones(te.sum()), X.loc[te, cols].values]) @ co
    lines += ["## A 翌日の分散の予測", "", "最後の年（2026年）の係数：" + "；".join(
        f"{k}：定数 {c[0]:.1e}、" + "・".join(f"{n} {v:.2f}" for n, v in zip(models[k], c[1:])) for k, c in coefs.items() if c is not None), "",
        "| 予測 | すべての日：R² | QLIKE | ルールが出ている日：R² | QLIKE | 実際 ÷ 予測（ルールが出ている日、平均） | ルールが2つ以上：実際 ÷ 予測 |", "|---|---|---|---|---|---|---|"]
    allp = {"har（今の形・係数は固定）": {name: sets[name][2] ** 2 for name in sets}}
    allp.update(preds)
    for k, pp in allp.items():
        aa, bb, nn = [], [], []
        for name, (d, n, sg, rate, div) in sets.items():
            y = feats[name][1]
            ok = pp[name].notna() & y.notna() & (d.index >= IRK.START) & (pp[name] > 0)
            aa.append(pp[name][ok].values)
            bb.append(y[ok].values)
            nn.append(n[ok].values)
        a, b, nn = np.concatenate(aa), np.concatenate(bb), np.concatenate(nn)
        cells = []
        for m in (np.ones(len(a), bool), nn >= 1):
            cells += [f"{1 - ((b[m] - a[m]) ** 2).sum() / ((b[m] - b[m].mean()) ** 2).sum():+.3f}", f"{np.mean(b[m] / a[m] - np.log(np.maximum(b[m], 1e-12) / a[m]) - 1):.3f}"]
        lines.append(f"| {k} | " + " | ".join(cells) + f" | {b[nn >= 1].mean() / a[nn >= 1].mean():.2f} | {b[nn >= 2].mean() / a[nn >= 2].mean():.2f} |")
        print(lines[-1], flush=True)
    head = "| 建玉を決める予測 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | " + " | ".join(p[0] for p in IRK.PER) + " |"
    sep = "|---|" + "---|" * (6 + len(IRK.PER))
    lines += ["", head, sep]
    floor = 0.025 / np.sqrt(ANN)
    for k, pp in allp.items():
        sig_of = {name: np.sqrt(pp[name].clip(lower=0)).fillna(sets[name][2]).clip(lower=floor) for name in sets}
        lines.append(f"| {k} | {stat_cells(sleeve_w(sets, vm, 'cash', sig_of), IRK.START, IRK.PER)} |")
        print(lines[-1], flush=True)

    # ---------- B 状態
    rows = []
    for name, (d, n, sg, rate, div) in sets.items():
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
        fin = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
        y = ((d["close"].pct_change() + fin).shift(-1) / sg)
        sig_rank = sg.expanding(min_periods=500).rank(pct=True)
        rows.append(pd.DataFrame({"name": name, "n": n, "y": y, "vr": rk[name], "sr": sig_rank, "G": rk[name] - sig_rank}))
    P = pd.concat(rows)
    P = P[P.index >= IRK.START]
    P["others"] = P.groupby(level=0)["n"].transform(lambda x: (x >= 1).sum()) - (P["n"] >= 1).astype(int)
    R = P[P["n"] >= 1]
    lines += ["", "## B1 恐怖の上乗せ G =（VIX の水準の順位）−（実際の値動きの見積もりの順位）", "",
              "ルールが出ている日の、翌日の利益 ÷ 値動きの見積もり：", "", "| G | 全期間 | 〜2010年 | 2011年〜 | VIX が高い状態の中 | VIX が中・低の状態の中 |", "|---|---|---|---|---|---|"]
    g1, g2 = R["G"].quantile(1 / 3), R["G"].quantile(2 / 3)
    for lab, m in ((f"下 1/3（G < {g1:+.2f}）", R["G"] < g1), ("中", (R["G"] >= g1) & (R["G"] < g2)), (f"上 1/3（G ≥ {g2:+.2f}）", R["G"] >= g2)):
        lines.append(f"| {lab} | {cell(R['y'][m])} | {cell(R['y'][m & (R.index < '2011-01-01')])} | {cell(R['y'][m & (R.index >= '2011-01-01')])} | "
                     f"{cell(R['y'][m & (R['vr'] >= 2 / 3)])} | {cell(R['y'][m & (R['vr'] < 2 / 3)])} |")
        print(lines[-1], flush=True)
    lines += ["", head.replace("建玉を決める予測", "形"), sep]
    gm = {}
    for name, (d, n, sg, rate, div) in sets.items():
        G = rk[name] - sg.expanding(min_periods=500).rank(pct=True)
        gm[name] = G
    for label, f in (("99章の形（変えない）", None), ("G で倍率：G < −0.1 で 0.75、G ≥ +0.1 で 1.25（事前に決めた形）", (-0.1, 0.1, 0.75, 1.25)),
                     ("G で倍率：G < −0.1 で 0.5、G ≥ +0.1 で 1.5", (-0.1, 0.1, 0.5, 1.5)), ("逆（G < −0.1 で 1.25、G ≥ +0.1 で 0.75）", (-0.1, 0.1, 1.25, 0.75))):
        mm = {n: vm[n] if f is None else vm[n] * pd.Series(np.where(gm[n] < f[0], f[2], np.where(gm[n] >= f[1], f[3], 1.0)), index=gm[n].index).where(gm[n].notna(), 1.0)
              for n in sets}
        lines.append(f"| {label} | {stat_cells(sleeve_w(sets, mm, 'cash'), IRK.START, IRK.PER)} |")
        print(lines[-1], flush=True)
    lines += ["", "## B2 3指数の同時の売られすぎ（ほかの2指数のうち、ルールが出ている数）", "", "| ほかの指数 | 全期間 | 〜2010年 | 2011年〜 | ルールが2つ以上の日 |", "|---|---|---|---|---|"]
    for k in (0, 1, 2):
        m = R["others"] == k
        lines.append(f"| {k} つ | {cell(R['y'][m])} | {cell(R['y'][m & (R.index < '2011-01-01')])} | {cell(R['y'][m & (R.index >= '2011-01-01')])} | {cell(R['y'][m & (R['n'] >= 2)])} |")
        print(lines[-1], flush=True)

    # ---------- B3 R2 の手じまい
    lines += ["", "## B3 R2 の手じまいの形（R2 だけを、値動き年10%で持った場合。コスト込み）", "", "| 手じまい | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | "
              + " | ".join(p[0] for p in IRK.PER) + " | 取引数 | 持つ日の割合 |", "|---|" + "---|" * (8 + len(IRK.PER))]
    for label in ("5日の平均を上回る（今の形）", "RSI(2) > 65", "RSI(2) > 70", "前の日の高値を上回る", "上げて終わった最初の日"):
        ss, ntr, held = {}, 0, []
        for name, (d, n, sg, rate, div) in sets.items():
            c = d["close"]
            up = c > c.rolling(200).mean()
            r2 = IR.rsi_wilder(c, 2)
            ex = {"5日の平均を上回る（今の形）": c > c.rolling(5).mean(), "RSI(2) > 65": r2 > 65, "RSI(2) > 70": r2 > 70,
                  "前の日の高値を上回る": c > d["high"].shift(1), "上げて終わった最初の日": c > c.shift(1)}[label]
            p = IR.positions(up & (r2 < 10), ex)
            ntr += int(((p > 0) & (p.shift(1).fillna(0) == 0) & (p.index >= IRK.START)).sum())
            held.append((p[p.index >= IRK.START] > 0).mean())
            ss[name] = (d, p * 3.0, sg, rate, div)
        r = V.sleeve(ss, {n: V.mult_of(rk[n], None) for n in sets}, "cash", None)
        lines.append(f"| {label} | {stat_cells(r, IRK.START, IRK.PER)} | {ntr} | {np.mean(held) * 100:.0f}% |")
        print(lines[-1], flush=True)

    # ---------- C 経験ベイズのケリー型
    Q = P[(P["n"] >= 1) & P["vr"].notna() & P["y"].notna()].copy()
    Q["reg"] = np.where(Q["vr"] < 1 / 3, 0, np.where(Q["vr"] >= 2 / 3, 2, 1))
    full = []
    for name, (d, n, sg, rate, div) in sets.items():
        days = pd.Series(d.index, index=d.index).diff().dt.days.fillna(1.0)
        fin = (div - rate - IR.MARKUP) / 100.0 / 360.0 * days
        y = ((d["close"].pct_change() + fin).shift(-1) / sg)
        full.append(pd.DataFrame({"name": name, "n": n, "y": y, "vr": rk[name]}))
    Fu = pd.concat(full)
    Fu = Fu[(Fu.index >= "1999-04-01") & (Fu["n"] >= 1) & Fu["vr"].notna() & Fu["y"].notna()].copy()
    Fu["reg"] = np.where(Fu["vr"] < 1 / 3, 0, np.where(Fu["vr"] >= 2 / 3, 2, 1))
    eb = {name: pd.Series(np.nan, index=sets[name][0].index) for name in sets}
    last_tab = None
    for yr in range(2006, 2027):
        tr = Fu[Fu.index.year < yr]
        g = tr.groupby(["n", "reg"])["y"].agg(["mean", "var", "count"])
        mu = tr["y"].mean()
        an = tr.groupby("n")["y"].mean() / mu
        bv = tr.groupby("reg")["y"].mean() / mu
        s2 = tr["y"].var()
        tab = {}
        resid = []
        for (nn, rg), row in g.iterrows():
            prior = mu * an[nn] * bv[rg]
            resid.append((row["mean"] - prior) ** 2 - s2 / row["count"])
        tau2 = max(float(np.mean(resid)), 1e-6)                      # 升ごとの「本当の値」が、掛け算の形からどれだけ離れているかの分散（モーメント法）
        for (nn, rg), row in g.iterrows():
            prior = mu * an[nn] * bv[rg]
            wgt = tau2 / (tau2 + s2 / row["count"])
            tab[(int(nn), int(rg))] = max(wgt * row["mean"] + (1 - wgt) * prior, 0.0)
        ref = tab.get((3, 2), max(tab.values()))
        last_tab = {k: v / ref for k, v in tab.items()} if ref > 0 else None
        for name, (d, n, sg, rate, div) in sets.items():
            m = d.index.year == yr
            reg = np.where(rk[name][m] < 1 / 3, 0, np.where(rk[name][m] >= 2 / 3, 2, 1))
            eb[name][m] = [tab.get((int(a), int(b)), 0.0) / ref if a >= 1 and ref > 0 else 0.0 for a, b in zip(n[m].values, reg)]
    per06 = (("2006〜10", "2006-01-01", "2011-01-01"), ("2011〜14", "2011-01-01", "2015-01-01"), ("2015〜21/10", "2015-01-01", "2021-11-01"), ("21/11〜26/11", "2021-11-01", "2026-12-01"))
    head06 = "| 形 | シャープ | t 値 | 最悪の日 | 下位1%の日の平均 | 最大の下落 | 最悪の年 | " + " | ".join(p[0] for p in per06) + " |"
    lines += ["", "## C 状態ごとの期待値を毎年計算し直すケリー型の建玉（2006年〜。学習は 1999年4月〜）", "", head06, sep]
    one = {n: V.mult_of(rk[n], None) for n in sets}
    lines.append(f"| 固定の倍率（重み 1:2:4 × VIX 0.5/1/1.5。99章の形） | {stat_cells(sleeve_w(sets, vm, 'cash'), '2006-01-01', per06)} |")
    ss = {name: (t[0], eb[name].fillna(0.0) * 3.0, t[2], t[3], t[4]) for name, t in sets.items()}
    lines.append(f"| 経験ベイズの升の期待値に比例（毎年計算し直す） | {stat_cells(V.sleeve(ss, one, 'cash', 4.0), '2006-01-01', per06)} |")
    # 半分ずつ混ぜる
    mix = {}
    for name, (d, n, sg, rate, div) in sets.items():
        fixed = n.map(lambda v: W124[int(v)]) * vm[name] / 1.5
        mix[name] = (d, (0.5 * fixed + 0.5 * eb[name].fillna(0.0)) * 3.0, sg, rate, div)
    lines.append(f"| 固定の倍率と経験ベイズの半々 | {stat_cells(V.sleeve(mix, one, 'cash', 4.0), '2006-01-01', per06)} |")
    for x in lines[-3:]:
        print(x, flush=True)
    if last_tab:
        lines += ["", "最後の年の升の表（ルール3つ・VIX 高 = 1 としたときの比）：" + "、".join(
            f"{nn}つ [低 {last_tab.get((nn, 0), 0):.2f}・中 {last_tab.get((nn, 1), 0):.2f}・高 {last_tab.get((nn, 2), 0):.2f}]" for nn in (1, 2, 3)),
            "（固定の倍率を同じ形で書くと：1つ [0.08・0.17・0.25]、2つ [0.17・0.33・0.50]、3つ [0.33・0.67・1.00]）"]
        print(lines[-2], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "index_model2.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

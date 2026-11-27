#!/usr/bin/env python3
"""研究（FX だけで取引する）：金利差を「数学的に」取る形 ― 受け取るスワップ ÷ 値動きの大きさ が最大になる組み合わせ。

考え方
- 為替の値動きは、数日〜数か月の先については「予想できない（上がるか下がるかは五分五分）」というのが、統計的に最もよく支持されている見方
  （89章・今回の回帰の結果とも合う）。もしそうなら、**建玉の期待値は「受け取るスワップ」そのもの**で、値動きは平均ゼロの揺れになる。
- すると、口座全体の「期待できる利益 ÷ 揺れの大きさ」は、(建玉ごとのスワップの合計) ÷ (建玉全体の値動きの大きさ) で、取引の前に計算できる。
  これが最大になる建玉の組み合わせは、金利差（年率）のベクトル μ と、通貨どうしの値動きの関係（共分散）Σ から、w ∝ Σ⁻¹ μ で求まる（平均・分散の最適化）。
  金利差は「予想」ではなく、分かっている値なので、ふつうの最適化の弱点（期待値の見積もりの誤差）が小さい。
  （公表：Ackermann・Pohl・Schmedders 2017年「Optimal and naive diversification in currency markets」）
- ここで確かめること：その組み方が、単純な組み方（金利の順位で持つ／金利差のあるペアを同じ重みで持つ）より、見ていない期間で良いか。
  取引前に計算した「期待できるシャープ」と、実際のシャープが、どのくらい合うか。

方法
- 通貨ごとの対米ドルの値動きで計算する（どのペアの組み合わせも、通貨ごとの重みに直せる）。週1回の入れ替え、5通りのずれの平均。
- Σ：直近250日の日次の共分散。半分を、相関のない形（対角）に寄せる（見積もりの誤差を減らすため。数値は 0.5 に固定）。
- 全体は、取引前の見積もりの値動きが年10%になる大きさ（上限：建玉の合計が口座の6倍）。
- コスト：売買のコスト、スワップの上乗せ（carry_breadth.py と同じ、通貨ごと）。
使い方: python3 tools/research/carry_optimal.py  → reports/research/carry_optimal.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import carry_breadth as CB  # noqa: E402
import fred_data as F  # noqa: E402
import styles_long as SL  # noqa: E402

ANN = 261
SHRINK = 0.5
WIN = 250
CAP = 6.0


def optimal_weights(v, rate, ccys, start_at=None, mu_thr=0.0):
    """各日の、対米ドルの建玉（通貨ごと）。w ∝ Σ⁻¹ μ を、見積もりの値動きが年10%になる大きさにしたもの。
    start_at：{通貨: その日より前は使わない}（市場ができる前の期間を除くため）。"""
    ret = v[ccys].pct_change()
    diff = rate[ccys].sub(rate["USD"], axis=0)
    R = ret.values
    M = diff.values
    n = len(ret)
    W = np.zeros((n, len(ccys)))
    exp_sr = np.full(n, np.nan)
    first = {c: (pd.Timestamp(start_at[c]) if start_at and c in start_at else None) for c in ccys}
    for t in range(WIN, n):
        if t % 5 != 0 and t > WIN:
            # 入れ替えは週1回（ずれは呼ぶ側で処理する）。ここでは毎日計算せず、あとで前の値を引き継ぐ
            pass
        win = R[t - WIN + 1:t + 1]
        ok = ~np.isnan(win).any(axis=0) & ~np.isnan(M[t])
        for j, c in enumerate(ccys):
            if first[c] is not None and ret.index[t] < first[c]:
                ok[j] = False
        if ok.sum() < 3:
            continue
        S_ = np.cov(win[:, ok].T) * ANN
        S_ = (1 - SHRINK) * S_ + SHRINK * np.diag(np.diag(S_))
        mu = M[t, ok] / 100.0
        # 払う側は上乗せのぶん不利：受け取る側 = 金利差 − 上乗せ、払う側 = 金利差 + 上乗せ（絶対値が小さくなる向きに寄せる）
        mk = np.array([CB.MARKUP[c] + CB.MARKUP["USD"] for c, o in zip(ccys, ok) if o]) / 100.0
        mu_net = np.sign(mu) * np.maximum(np.abs(mu) - mk, 0.0)
        if mu_thr > 0:
            mu_net = np.where(np.abs(mu_net) >= mu_thr / 100.0, mu_net, 0.0)
        if not mu_net.any():
            continue
        try:
            w = np.linalg.solve(S_, mu_net)
        except np.linalg.LinAlgError:
            continue
        sd = np.sqrt(w @ S_ @ w)
        if sd <= 0:
            continue
        k = 0.10 / sd
        if np.abs(w * k).sum() > CAP:
            k = CAP / np.abs(w).sum()
        W[t, ok] = w * k
        exp_sr[t] = (w @ mu_net) / sd
    return pd.DataFrame(W, index=ret.index, columns=ccys), pd.Series(exp_sr, index=ret.index)


def pnl(w, v, rate):
    """対米ドルの建玉 w（通貨ごと）の日次の損益。金利差 − 上乗せ（通貨ごと + 米ドルの分）、売買のコスト込み。"""
    ccys = list(w.columns)
    ret = v[ccys].pct_change().shift(-1)
    diff = rate[ccys].sub(rate["USD"], axis=0)
    mk = pd.Series({c: CB.MARKUP[c] + CB.MARKUP["USD"] for c in ccys})
    cc = pd.Series({c: CB.COST_CCY[c] + CB.COST_CCY["USD"] for c in ccys})
    carry = ((w * diff).sum(axis=1) - (w.abs() * mk).sum(axis=1)) / 100.0 / ANN
    tc = ((w - w.shift(1).fillna(0.0)).abs() * cc).sum(axis=1)
    return ((w * ret).sum(axis=1) + carry - tc).fillna(0.0)


def run_opt(v, rate, ccys, **kw):
    W, esr = optimal_weights(v, rate, ccys, **kw)
    outs = []
    for ph in range(5):
        keep = np.zeros(len(W), bool)
        keep[ph::5] = True
        w = W.where(pd.Series(keep, index=W.index), np.nan).ffill().fillna(0.0)
        outs.append(pnl(w, v, rate))
    return sum(outs) / len(outs), esr, W


def main():
    v, rate = CB.load()
    head = "| 形 | " + " | ".join(p[0] for p in SL.PER) + " | 全体 | t 値 | 最大の下落 | 最悪の年 | プラスの年 |"
    sep = "|---|" + "---|" * (len(SL.PER) + 5)
    lines = ["# 研究：受け取るスワップ ÷ 値動き が最大になる組み合わせ（取引は為替だけ。`tools/research/carry_optimal.py`）", "",
             "週1回の入れ替え（5通りのずれの平均）、コスト・スワップの上乗せ込み。期間ごとの列は年率シャープ。右の5列は 2000年以降（値動きを年10%にそろえて）。", "",
             head, sep]
    keep = {}
    G8 = CB.G8
    starts = {"CNH": "2011-06-01", "MXN": "1999-01-01"}
    forms = (("最適な組み合わせ：いまの8通貨", G8, {}),
             ("最適な組み合わせ：＋北欧（10通貨）", G8 + ["NOK", "SEK"], {}),
             ("最適な組み合わせ：＋メキシコ・南ア（12通貨）", G8 + ["NOK", "SEK", "MXN", "ZAR"], {}),
             ("最適な組み合わせ：＋人民元（13通貨、人民元は 2011年6月〜）", G8 + ["NOK", "SEK", "MXN", "ZAR", "CNH"], {"start_at": starts}))
    esrs = {}
    for label, ccys, kw in forms:
        x, esr, W = run_opt(v, rate, ccys, **kw)
        line, z = CB.row(label, x)
        lines.append(line)
        keep[label] = z
        esrs[label] = (esr, x, W)
        print(line, flush=True)
    for label, ccys in (("単純な組み方（金利の順位に比例）：いまの8通貨", G8), ("単純な組み方（金利の順位に比例）：12通貨", G8 + ["NOK", "SEK", "MXN", "ZAR"])):
        line, z = CB.row(label, CB.run(v, rate, ccys, mode="rank"))
        lines.append(line)
        keep[label] = z
        print(line, flush=True)
    # 取引前に計算した「期待できるシャープ」と、実際
    lines += ["", "## 取引の前に計算した「期待できるシャープ」（受け取るスワップ ÷ 値動き）と、実際のシャープ", "",
              "もし為替の値動きが本当に「平均ゼロの揺れ」なら、2つは同じくらいになるはず。", "",
              "| 形 | 期間 | 取引前の見積もり（平均） | 実際 |", "|---|---|---|---|"]
    for label in list(esrs)[:1] + list(esrs)[2:3]:
        esr, x, _ = esrs[label]
        for pname, a, b in SL.PER:
            e = esr[(esr.index >= a) & (esr.index < b)].mean()
            s = SL.sharpe(x[(x.index >= a) & (x.index < b)])
            lines.append(f"| {label} | {pname} | {e:+.2f} | {s:+.2f} |")
        e = esr[esr.index >= "2000-01-01"].mean()
        lines.append(f"| {label} | 2000年〜の全体 | {e:+.2f} | {SL.sharpe(x[x.index >= '2000-01-01']):+.2f} |")
    # いま（最新の日）の建玉の例
    label = list(esrs)[2]
    esr, x, W = esrs[label]
    last = W.iloc[-1]
    lines += ["", f"## いまの建玉の例（{label}、{W.index[-1].date()}、値動き年10%の大きさ。プラス = その通貨を対米ドルで買い）", "",
              "、".join(f"{c} {last[c]:+.2f}" for c in W.columns if abs(last[c]) > 0.005) + f"、米ドル {-last.sum():+.2f}",
              f"取引前の見積もりのシャープ：{esr.dropna().iloc[-1]:+.2f}"]
    yr = pd.DataFrame({k: z.groupby(z.index.year).sum() * 100 for k, z in keep.items()}).round(1)
    cols = [list(keep)[0], list(keep)[2], list(keep)[4]]
    lines += ["", "## 年ごとの成績（%、値動きを年10%にそろえたとき）", "", "| 年 | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for y, r_ in yr[cols].iterrows():
        lines.append(f"| {y} | " + " | ".join(f"{q:+.1f}" for q in r_.values) + " |")
    out = os.path.join(F.ROOT, "reports", "research", "carry_optimal.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    pd.DataFrame(keep).to_parquet(os.path.join(D.CACHE, "carry_optimal_returns.parquet"))
    print("\n".join(lines[len(forms) + 9:]))


if __name__ == "__main__":
    main()

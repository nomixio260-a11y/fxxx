#!/usr/bin/env python3
"""研究：指数の戻りの層に、金の順張りの層を重ねる（104章）。直近3年を重視しつつ、どの時代でも崩れないかを見る。

- 指数の戻りの層：lot_rounding.py の計算（S&P500・NASDAQ100 の2銘柄。EA は3銘柄なので、EA の設定 u% は、ここでは u × 1.5 に当たる）。
- 金の順張りの層：EA（方式 8）と同じ形。終値が200日の平均より上のあいだだけ買い持ち（7日ごとに見直す）。
  建玉は、金の値動き（過去60日）が口座の年 x% になる大きさ。公開の1分足（XAUUSD）。売買は日足の始まりの5分後。
  コスト：スプレッド 0.5 ドル、スワップ 年5.5%（OANDA の金の買いは「ドルの短期金利＋約1%」）。
  逆指値あり の形：毎日、売買の値段から 4 ×（1日の値動きの見積もり）下に置き直す。
- 合わせ方は2通り：
  A 1つの資金として合わせる（毎日、同じ資金に対して両方の建玉を決める）。口座が分かれているので、実際にはこのとおりにはならない（上限の目安）。
  B 口座を2つに分ける（資金を半分ずつ。それぞれの口座の資産に対して建玉を決め、口座のあいだで資金は動かさない）。
    A と同じ建玉の額にするため、それぞれの口座の設定は A の2倍にする。
- 期間：2011年9月〜2026年10月／うち 2011年9月〜2020年1月／2020年2月〜／直近3年（2023年11月〜）。
使い方: python3 tools/research/portfolio_recent.py  → reports/research/portfolio_recent.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AMS_OANDA", "1")
import fred_data as F  # noqa: E402
import lot_rounding as LR  # noqa: E402
import sleeves_ea_mimic as M  # noqa: E402

ANN = 252
PER = (("2011年9月〜26年10月", "2011-09-01", "2026-10-30"), ("うち 〜2020年1月", "2011-09-01", "2020-01-31"), ("2020年2月〜", "2020-02-01", "2026-10-30"),
       ("直近3年", "2023-11-01", "2026-10-30"))
_gold = {}


def gold_returns(unit, stop=None, swap=5.5, check=7):
    """金の順張りの層の、日次の損益（口座に対する割合）。"""
    if "d" not in _gold:
        _gold["d"] = M.prepare("XAUUSD")
    d = _gold["d"]
    c = d["close"]
    sma = c.rolling(200).mean()
    st = np.zeros(len(d))
    last, cur = None, 0.0
    for i, t in enumerate(d.index):
        if i >= 200 and (last is None or (t - last).days >= check):
            cur, last = float(c.iloc[i] > sma.iloc[i]), t
        st[i] = cur
    sd = c.pct_change().rolling(60).std()
    w = (pd.Series(st, index=d.index) * unit / 100.0 / (sd * np.sqrt(ANN)).clip(lower=0.025)).fillna(0.0)
    px = d["px"]
    wh = w.shift(1).fillna(0.0)                               # 前の日足で決めた建玉を、その日の売買の値段から持つ
    sdh = sd.shift(1)
    ret = px.shift(-1) / px - 1.0
    if stop is not None:
        hit = d["low_after"] <= px * (1.0 - stop * sdh)
        ret = ret.where(~hit, -stop * sdh)
    days = pd.Series(d.index, index=d.index).diff().dt.days.shift(-1).fillna(1.0)
    r = wh * ret - wh * swap / 100.0 / 360.0 * days - (wh - wh.shift(1).fillna(0.0)).abs() * (0.5 / c) / 2.0
    return r.fillna(0.0), wh


def cell(r):
    r = r.dropna()
    if len(r) < 200:
        return "—"
    eq = (1 + r.clip(lower=-0.99)).cumprod()
    yrs = len(r) / ANN
    roll = (eq / eq.shift(ANN) - 1).dropna()
    return (f"{(eq.iloc[-1] ** (1 / yrs) - 1) * 100:+.0f}%・{r.mean() / r.std() * np.sqrt(ANN):+.2f}・{(eq / eq.cummax() - 1).min() * 100:.0f}%・"
            f"{roll.max() * 100:+.0f}% 〜 {roll.min() * 100:+.0f}%")


def cut(r, a, b):
    return r[(r.index >= a) & (r.index <= b)]


def main():
    lines = ["# 研究：指数の戻りの層 ＋ 金の順張りの層（`tools/research/portfolio_recent.py`）", "",
             "表の値は「年率の伸び・シャープ・最大の下落・12か月の成績（最高 〜 最低）」。", "",
             "## 1 金の順張りの層だけ", "", "| 金の層の大きさ（年 %） | 逆指値 | " + " | ".join(p[0] for p in PER) + " | 最悪の日 | 建玉の平均（資金に対する倍率、直近3年） |", "|---|---|" + "---|" * (len(PER) + 2)]
    G = {}
    for u in (11.2, 22.4, 33.6, 50.0):
        for stop in (None, 4.0):
            g, w = gold_returns(u, stop)
            G[(u, stop)] = g
            lines.append(f"| {u:g}% | {'なし' if stop is None else '4×σ'} | " + " | ".join(cell(cut(g, a, b)) for _, a, b in PER)
                         + f" | {g.min() * 100:.1f}% | {cut(w, PER[3][1], PER[3][2]).mean():.2f} |")
            print(lines[-1], flush=True)
    idx = {}
    for ea_u in (5.0, 8.75, 12.5):
        idx[ea_u] = {k: LR.simulate("floor", "2011-09-01", "2026-10-30", 1e10, ea_u * 1.5 * k, return_eq=True).pct_change().fillna(0.0) for k in (1, 2)}
    lines += ["", "## 2 指数の戻りの層 ＋ 金の順張りの層（金は逆指値 4×σ あり）", "",
              "| 指数の層（EA の設定に直した値） | 金の層 | 合わせ方 | " + " | ".join(p[0] for p in PER) + " | 最悪の日 |", "|---|---|---|" + "---|" * (len(PER) + 1)]
    for ea_u in (5.0, 8.75, 12.5):
        for ug in (0.0, 11.2, 22.4, 33.6):
            # A：1つの資金
            g1 = G[(ug, 4.0)] if ug > 0 else G[(11.2, 4.0)] * 0.0
            a = pd.concat([idx[ea_u][1], g1], axis=1, sort=True).fillna(0.0).sum(axis=1)
            lines.append(f"| {ea_u:g}% | {ug:g}% | A：1つの資金 | " + " | ".join(cell(cut(a, x, y)) for _, x, y in PER) + f" | {a.min() * 100:.1f}% |")
            print(lines[-1], flush=True)
            if ug > 0:
                # B：口座を2つに分ける（半分ずつ。設定は2倍。資金は動かさない）
                g2, _ = gold_returns(ug * 2.0, 4.0)
                cells = []
                worst = 0.0
                for _, x, y in PER:
                    ri, rg = cut(idx[ea_u][2], x, y), cut(g2, x, y)
                    z = pd.concat([ri, rg], axis=1, sort=True).fillna(0.0)
                    e = 0.5 * (1 + z.iloc[:, 0].clip(lower=-0.99)).cumprod() + 0.5 * (1 + z.iloc[:, 1].clip(lower=-0.99)).cumprod()
                    rr = e.pct_change().fillna(e.iloc[0] - 1.0)
                    cells.append(cell(rr))
                    worst = min(worst, rr.min())
                lines.append(f"| {ea_u:g}%（口座の設定は {ea_u * 2:g}%） | {ug:g}%（口座の設定は {ug * 2:g}%） | B：口座を2つに分ける | " + " | ".join(cells) + f" | {worst * 100:.1f}% |")
                print(lines[-1], flush=True)
    c = _gold["d"]["close"]
    lines += ["", f"- 金の値段：2011年9月 {c[c.index >= '2011-09-01'].iloc[0]:.0f} ドル → 2020年1月 {c[c.index <= '2020-01-31'].iloc[-1]:.0f} → 2023年11月 {c[c.index >= '2023-11-01'].iloc[0]:.0f} → 2026年10月 {c.iloc[-1]:.0f}。",
              f"- 指数の層と金の層の、日々の損益の相関：{pd.concat([idx[8.75][1], G[(11.2, 4.0)]], axis=1, sort=True).fillna(0.0).corr().iloc[0, 1]:+.2f}。"]
    out = os.path.join(F.ROOT, "reports", "research", "portfolio_recent.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

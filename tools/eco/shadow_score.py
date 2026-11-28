#!/usr/bin/env python3
"""複合システム：影のモードの予想の記録を採点する。日付・時刻・曜日は使わない。

- 入力：予想の記録（reports/live_index/AMS_prob_log.csv。tools/eco/predict.py が、実際の口座の日足から毎日1行ずつ書いたもの）。
  1行 ＝ 1銘柄の1日：モデルごとの確率（線形・勾配ブースティング・チャートを読むモデル・期待値のモデル）、合成した確率 p、合図 z、
  その日のルールの数（いまの戻りの層が持っているルール）、値動きの大きさ、終値、予想を作った時刻。
- 採点：同じ銘柄の次の行（次の営業日）の終値から、次の日の値動きを出す（あいだが4日を超えて空いている行は採点しない）。
  予想を作った時刻が、答えが出る時刻より後だった行（週末の動作確認などで、あとから作った行）も採点しない。
   当たった割合（確率が 50% より上で上がった・下で下がった）、確率と値動きの相関と t 値、
   確率に比例して買った場合の損益（値動きをそろえた単位）と、同じ日のいまの層（ルールの数に応じて 1:2:4）の損益。
- 昇格を提案する条件（記録を見る前に決めた。自動では切り替えない。満たしたら報告して、判断を仰ぐ）：
   米国3指数（US500・US100・US30）の採点済みの行が、それぞれ 250 日以上あり、
   (1) 合成した確率と次の日の値動きの相関がプラスで、t 値が 2 以上（日ごとの平均から）
   (2) 確率に比例して買った場合の損益（1日あたり ÷ ばらつき）が、同じ日のいまの層以上
  どちらかを満たさないあいだは、影のモードのまま続ける。500 日たっても (1) を満たさないときは、モデルを作り直す。
使い方: python3 tools/eco/shadow_score.py [記録のファイル]  → reports/eco/shadow.md
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
W_RULE = {0: 0.0, 1: 0.25, 2: 0.5, 3: 1.0}
US3 = ("US500", "US100", "US30")


def score(log_path):
    L = pd.read_csv(log_path, dtype={"date": str})
    L["d"] = pd.to_datetime(L["date"], format="%Y.%m.%d")
    L = L.sort_values(["symbol", "d"]).drop_duplicates(["symbol", "d"], keep="first")
    nxt = L.groupby("symbol")[["close", "d"]].shift(-1)
    L["r"] = nxt["close"] / L["close"] - 1.0
    L.loc[(nxt["d"] - L["d"]).dt.days > 4, "r"] = np.nan
    # 予想を作った時刻が、答え（次の日足の終値）が出る時刻より後の行は、採点しない（週末の動作確認などで、あとから作った行）。
    # 日足は、その日付の 21〜22時（UTC）ごろに確定するので、余裕を見て「次の日足の日付の 20時（UTC）」より前に作った行だけを採点する
    made = pd.to_datetime(L["made_utc"], errors="coerce")
    L.loc[~(made < nxt["d"] + pd.Timedelta(hours=20)), "r"] = np.nan
    S = L.dropna(subset=["r"]).copy()
    unit = 0.10 / (S["sig"] * np.sqrt(252))
    S["y"] = np.log1p(S["r"]) / S["sig"]
    S["e"] = S["z"].clip(lower=0, upper=2) * unit * S["r"]
    S["b"] = S["rules"].map(W_RULE).fillna(0.0) * unit * S["r"]
    return L, S


def table(S, syms=None):
    g = S if syms is None else S[S["symbol"].isin(syms)]
    if len(g) < 20:
        return None
    dd = ((g["p"] - g["p"].mean()) * g["y"]).groupby(g["d"]).mean()
    t = dd.mean() / dd.std() * np.sqrt(len(dd)) if dd.std() > 0 else np.nan
    de, db = g.groupby("d")["e"].mean(), g.groupby("d")["b"].mean()
    sh = lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan   # noqa: E731
    return dict(n=len(g), days=g["d"].nunique(), hit=float(((g["p"] > 0.5) == (g["r"] > 0)).mean()), corr=float(np.corrcoef(g["p"], g["y"])[0, 1]), t=float(t),
                e=float(sh(de)), b=float(sh(db)), e_sum=float(de.sum()), b_sum=float(db.sum()), per=g.groupby("symbol").size().to_dict())


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "reports", "live_index", "AMS_prob_log.csv")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "reports", "eco", "shadow.md")
    if not os.path.exists(path):
        print("予想の記録がまだありません:", path)
        return
    L, S = score(path)
    lines = ["# 複合システム：影のモードの予想の採点（`tools/eco/shadow_score.py`）", "",
             f"記録：{len(L)} 行（{L['symbol'].nunique()} 銘柄、{L['date'].min()}〜{L['date'].max()}）。うち、次の日の値動きが出て採点できた行：{len(S)}。", "",
             "| 銘柄の集まり | 採点した行（日数） | 当たった割合 | 確率と値動きの相関・t | 確率に比例して買った場合（年率に直したシャープ） | 同じ日のいまの層 |", "|---|---|---|---|---|---|"]
    res = {}
    for lab, syms in (("米国3指数（US500・US100・US30）", US3), ("全銘柄", None)):
        r = table(S, syms)
        res[lab] = r
        lines.append(f"| {lab} | — | — | — | — | — |" if r is None else
                     f"| {lab} | {r['n']}（{r['days']} 日） | {r['hit'] * 100:.1f}% | {r['corr']:+.3f}・{r['t']:+.1f} | {r['e']:+.2f} | {r['b']:+.2f} |")
    r = res["米国3指数（US500・US100・US30）"]
    enough = r is not None and all(r["per"].get(s, 0) >= 250 for s in US3)
    c1 = enough and r["corr"] > 0 and r["t"] >= 2.0
    c2 = enough and r["e"] >= r["b"]
    lines += ["", "## 昇格を提案する条件（事前に決めたもの）", "",
              f"- 採点済みの行が米国3指数のそれぞれで 250 日以上：{'○' if enough else '×（まだ足りない）'}",
              f"- (1) 確率と値動きの相関がプラスで t ≥ 2：{'○' if c1 else '×'}",
              f"- (2) 確率に比例して買った場合の損益が、いまの層以上：{'○' if c2 else '×'}",
              f"- **判定：{'昇格を提案する（切り替えは、報告して判断を仰いでから）' if (c1 and c2) else '影のモードのまま続ける'}**"]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

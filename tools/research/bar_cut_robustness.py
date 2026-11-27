#!/usr/bin/env python3
"""検証：日足の区切りの時刻を変えても、成績は保たれるか（103章）。特定の時刻に頼っていないことの確認。

- EA は、業者のサーバーの日足（区切りは NY 17時。取引の休みの直前）でルールを判定し、次の日足が始まった5分後（NY 18時5分）に売買する。
  公表されたルールは、現物の終値（NY 16時）で判定する。区切りの時刻が1時間ずれている。
- ここでは、1分足から、区切りを k 時間早めた日足を作り直し（k = 0 が今の形、k = 1 が NY 16時 = 現物の終値）、同じルール・同じ建玉の決め方で計算する。
  売買は、新しい日足が始まった5分後。金曜の区切りのあとの足は、月曜の日足に入れる。
- 計算は lot_rounding.py と同じ（S&P500・NASDAQ100、2011年9月〜2026年10月、重み 1:2:4・VIX の倍率・逆指値 4×σ・強制ロスカットを避ける上限・コスト込み。元金は大きくして丸めの影響を除く）。
- 見るもの：区切りの時刻によって成績が大きく変わるなら、時刻に頼った手法ということになる。どの区切りでも同じくらいなら、頼っていない。
使い方: python3 tools/research/bar_cut_robustness.py  → reports/research/bar_cut_robustness.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AMS_OANDA", "1")
import fred_data as F  # noqa: E402
import index_reversion_cfd as IC  # noqa: E402
import lot_rounding as LR  # noqa: E402
import sleeves_ea_mimic as M  # noqa: E402

ANN = 252
CUTS = (0, 1, 2, 3, 5, 8, 11, 14, 17, 20)
_raw = {}


def shifted(pair, k):
    """区切りを k 時間早めた1分足（時刻を k 時間進めて、日付の変わり目をずらす）。土曜になった足は月曜に送る。"""
    if pair not in _raw:
        m = IC.load_any(pair)
        ny = m.index.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
        m = m.copy()
        m.index = ny
        _raw[pair] = m[~m.index.duplicated()].sort_index()
    m = _raw[pair]
    idx = m.index + pd.Timedelta(hours=7 + k)
    idx = idx.where(idx.dayofweek != 5, idx + pd.Timedelta(days=2))
    idx = idx.where(idx.dayofweek != 6, idx + pd.Timedelta(days=1))
    out = m.copy()
    out.index = idx
    return out[~out.index.duplicated()].sort_index()


def main():
    lines = ["# 検証：日足の区切りの時刻を変える（`tools/research/bar_cut_robustness.py`）", "",
             "S&P500・NASDAQ100 の1分足、2011年9月〜2026年10月。EA と同じ形（ルール1つ分 8.75%、コスト込み）。", "",
             "| 区切り（NY の時刻） | 売買の時刻（NY） | 年率の伸び | シャープ | 口座の値動き（年） | 最大の下落 | 最悪の日 | 前半（〜2019年3月）のシャープ | 後半 |", "|---|---|---|---|---|---|---|---|---|"]
    orig = M.server_m1
    try:
        for k in CUTS:
            M.server_m1 = lambda pair, kk=k: shifted(pair, kk)
            eq = LR.simulate("floor", "2011-09-01", "2026-10-30", 1e10, 8.75, return_eq=True)
            r = eq.pct_change().dropna()
            yrs = (eq.index[-1] - eq.index[0]).days / 365.25
            h = pd.Timestamp("2019-04-01")
            cut = (17 - k) % 24
            sh = lambda x: x.mean() / x.std() * np.sqrt(ANN)        # noqa: E731
            note = "（今の形）" if k == 0 else ("（現物の終値）" if k == 1 else "")
            ent = f"{(cut + 1) % 24}:05" if k == 0 else f"{cut}:05"
            lines.append(f"| {cut}:00{note} | {ent} | {((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100:+.1f}% | {sh(r):+.2f} | {r.std() * np.sqrt(ANN) * 100:.1f}% | "
                         f"{(eq / eq.cummax() - 1).min() * 100:.0f}% | {r.min() * 100:.1f}% | {sh(r[r.index < h]):+.2f} | {sh(r[r.index >= h]):+.2f} |")
            print(lines[-1], flush=True)
    finally:
        M.server_m1 = orig
    out = os.path.join(F.ROOT, "reports", "research", "bar_cut_robustness.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

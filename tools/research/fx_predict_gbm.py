#!/usr/bin/env python3
"""研究（FX だけで取引する）：fx_predict_daily.py と同じ情報で、非線形のモデル（勾配ブースティング、LightGBM）なら翌日の為替を予想できるか。

- 線形の回帰では予想できなかった。条件の組み合わせ（例：株が大きく下げ、かつ VIX が高い日だけ）で効く関係があれば、木のモデルなら拾える。
- 設定は、過学習しにくい小さなモデルに固定する（木の深さ3、葉8、学習率0.03、300本、行・列の間引き0.7）。数値は選び直さない。
- 過去のデータだけで学習し、次の年を予想する（2016年〜が、見ていない期間）。7通貨をまとめて1つのモデルにする（通貨の種類も説明に入れる）。
使い方: python3 tools/research/fx_predict_gbm.py  → reports/research/fx_predict_gbm.md
"""
import os
import sys

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import fx_predict_daily as P  # noqa: E402

ANN = 252


def main():
    fx = P.fx_panel()
    fx = fx[fx.index >= "2010-06-01"]
    g, own = P.features(fx)
    lr = np.log(fx).diff()
    vol = lr.rolling(60, min_periods=40).std()
    px_pair = pd.DataFrame({c: (fx[c] if P.CCY[c][1] > 0 else 1.0 / fx[c]) for c in fx.columns})
    cost = pd.Series({c: (P.S.COST.get(P.CCY[c][0], 2.0) + 0.5) * P.D.pip_size(P.CCY[c][0]) for c in fx.columns})
    cost_frac = (cost / px_pair).reindex(fx.index)
    lines = ["# 研究：非線形のモデル（勾配ブースティング）で、翌日の為替を予想できるか（`tools/research/fx_predict_gbm.py`）", "",
             "fx_predict_daily.py と同じ情報・同じ期間。7通貨をまとめた1つのモデル。過去だけで学習し、次の年を予想（2016年〜）。", "",
             "| 予想する先 | 予想と実際の相関（見ていない期間） | シャープ（コスト前） | シャープ（コスト後） | t 値（コスト後） | プラスの年 |", "|---|---|---|---|---|---|"]
    for horizon in (1, 5):
        yt = lr.shift(-1) if horizon == 1 else (np.log(fx).shift(-horizon) - np.log(fx)) / horizon
        rows = []
        for i, c in enumerate(fx.columns):
            X = pd.concat([g, own[c]], axis=1)
            X["ccy"] = i
            X["y"] = yt[c] / vol[c]                       # 値動きの大きさでそろえた値を予想する
            X["c"] = c
            rows.append(X)
        panel = pd.concat(rows).dropna()
        feats = [k for k in panel.columns if k not in ("y", "c")]
        pred = pd.DataFrame(index=fx.index, columns=fx.columns, dtype=float)
        for yr in range(P.FIRST_OOS, 2027):
            tr = panel[panel.index.year < yr]
            if horizon > 1:
                tr = tr[tr.index < pd.Timestamp(f"{yr}-01-01") - pd.Timedelta(days=10)]     # 先の値が、予想する年にかからないようにする
            te = panel[panel.index.year == yr]
            if len(tr) < 3000 or len(te) == 0:
                continue
            m = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, max_depth=3, num_leaves=8, subsample=0.7, subsample_freq=1,
                                  colsample_bytree=0.7, min_child_samples=100, reg_lambda=10.0, random_state=1, verbose=-1)
            m.fit(tr[feats], tr["y"], categorical_feature=["ccy"])
            p = pd.Series(m.predict(te[feats]), index=te.index)
            for c in fx.columns:
                sel = te["c"] == c
                pred.loc[te.index[sel], c] = p[sel].values
        P.RET1 = lr.shift(-1)
        line, net = P.evaluate(pred * vol, yt, vol, cost_frac, f"翌{'日' if horizon == 1 else '5日'}", horizon)
        parts = line.split("|")
        lines.append("|" + "|".join([parts[1], parts[2], parts[3], parts[4], parts[5], parts[7]]) + "|")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "fx_predict_gbm.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

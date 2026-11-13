#!/usr/bin/env python3
"""時刻ルールの取引に、機械学習で「入る／見送る」のフィルターをかけて成績が良くなるかを調べる。

例：R1（EURUSD をロンドン 9:00 に売り、4時間保有）の各取引について、
入る時点で分かる特徴量から「その取引がコスト込みで勝つか」を予測し、
予測が良いときだけ入る。

評価は設計期間の中のウォークフォワード（前の年までで学習 → 次の1年）と、
設計期間全体で学習したモデルの検証期間での1回だけの評価。

使い方: python3 tools/research/ml_filter.py EURUSD ldn 9 4 -1
        （銘柄 時計 入る時 保有時間 向き(+1買い/-1売り)）
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import ml_train as M  # noqa: E402
import seasonality as S  # noqa: E402


def run(pair, clock, hour, hold, sign):
    base = D.bars(pair, "1h")
    X = M.features(pair)
    r = pd.Series(S.window_returns(base, hold, D.pip_size(pair)), index=base.index) * sign
    cost = S.COST[pair]
    m = (base[f"{clock}_h"] == hour) & r.notna() & X.notna().all(axis=1)
    X, r = X[m], r[m]
    y = (r - cost > 0).astype(int)

    import lightgbm as lgb

    def model():
        return lgb.LGBMClassifier(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=40,
                                  subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0,
                                  random_state=0, verbose=-1)

    def summary(pnl):
        pnl = np.asarray(pnl)
        if len(pnl) < 10:
            return f"{len(pnl)}回"
        gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
        t = pnl.mean() / pnl.std(ddof=1) * np.sqrt(len(pnl))
        return f"{len(pnl)}回 1取引 {pnl.mean():+.2f}pips PF {gp / gl if gl > 0 else 9.99:.2f} t {t:.2f}"

    out = [f"## フィルター：{pair} {clock} {hour}:00 {hold}時間 {'買い' if sign > 0 else '売り'}", ""]
    qs = [0.0, 0.3, 0.5]       # 予測確率の下位この割合を見送る
    wf = {q: [] for q in qs}
    for yr in (2019, 2020, 2021):
        tr = X.index < pd.Timestamp(f"{yr}-01-01")
        te = (X.index >= pd.Timestamp(f"{yr}-01-01")) & (X.index < pd.Timestamp(f"{yr + 1}-01-01"))
        mdl = model().fit(X[tr].values, y[tr].values)
        p_tr = mdl.predict_proba(X[tr].values)[:, 1]
        p = mdl.predict_proba(X[te].values)[:, 1]
        for q in qs:
            thr = np.quantile(p_tr, q) if q > 0 else -1
            pnl = (r[te] - cost).values[p > thr]
            wf[q].append(pnl)
            out.append(f"- {yr} 見送り下位{int(q * 100)}%: {summary(pnl)}")
    out.append("")
    for q in qs:
        out.append(f"- 設計期間WF合計 見送り下位{int(q * 100)}%: {summary(np.concatenate(wf[q]))}")
    # 検証期間：フィルターなし と 下位30%見送り を比べる（ここで初めて見る）
    des = D.period_mask(X.index, D.DESIGN)
    val = D.period_mask(X.index, D.VALID)
    mdl = model().fit(X[des].values, y[des].values)
    p_des = mdl.predict_proba(X[des].values)[:, 1]
    p_val = mdl.predict_proba(X[val].values)[:, 1]
    out.append("")
    for q in qs:
        thr = np.quantile(p_des, q) if q > 0 else -1
        out.append(f"- 検証期間 見送り下位{int(q * 100)}%: {summary((r[val] - cost).values[p_val > thr])}")
    return "\n".join(out)


if __name__ == "__main__":
    pair, clock, hour, hold, sign = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
    text = run(pair, clock, hour, hold, sign)
    print(text)
    path = os.path.join(D.ROOT, "reports", "research", f"ml_filter_{pair}_{clock}{hour}_h{hold}.md")
    open(path, "w", encoding="utf-8").write(text + "\n")

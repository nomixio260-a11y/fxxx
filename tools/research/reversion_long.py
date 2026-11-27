#!/usr/bin/env python3
"""中期の層の候補：日足の「行き過ぎの戻り」を、27年分（1999〜2026年）で確かめる（日付・時刻のクセは使わない）。

- pattern_zoo.py で、日足の戻り（2週間ほど持つ形）だけが、弱いながら4期間ともコスト後でプラスだった。
  27年分で「トレンドに乗る手法が一貫して負ける」ことの裏返しでもある。別の長いデータ（FRED）で確かめる。
- 形（すべて日足の終値だけで判定）：
  RSI：RSI(14) が 30 未満で買い・70 超で売り
  BRK：過去 N 日の高値（安値）を終値で更新したら、逆向きに入る
  Z：終値が過去 N 日の平均から k σ 以上離れたら、戻る向きに入る
  出口：H 日後（または、RSI・Z が真ん中に戻ったら）。
- 売買は、判定した日の「次の日」の値段で行う（判定に使った値段そのものでは売買できないため）。
- 重み：値動きの大きさでそろえる。1つのシグナルの大きさは一定（同時に出るシグナルが多い日は、建玉の合計が増える）。
  建玉の合計は上限 cap まで（超える日は、全体を縮める）。全体は、前日までの自分の値動きから年率10%にそろえる。
- コスト：スプレッド（S.COST + 0.5 pips）、スワップ（金利差 − 上乗せ 年1%）。
使い方: python3 tools/research/reversion_long.py  → reports/research/reversion_long.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import styles_long as SL  # noqa: E402


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    return 100.0 * up / (up + dn).replace(0, np.nan)


def hold_signal(entry, H, exit_mask=None):
    """entry（-1/0/+1）が出たら、その向きを H 日持つ。持っているあいだの新しいシグナルは、向きが同じなら延長、逆なら入れ替え。
    exit_mask（その向きの建玉を閉じる条件）が真になったら閉じる。"""
    e = entry.values
    n, m = e.shape
    pos = np.zeros((n, m))
    left = np.zeros(m, int)
    cur = np.zeros(m)
    xl = exit_mask[0].values if exit_mask is not None else None      # 買いを閉じる条件
    xs = exit_mask[1].values if exit_mask is not None else None      # 売りを閉じる条件
    for i in range(n):
        if xl is not None:
            close = ((cur > 0) & xl[i]) | ((cur < 0) & xs[i])
            cur = np.where(close, 0.0, cur)
            left = np.where(close, 0, left)
        new = e[i] != 0
        cur = np.where(new, e[i], cur)
        left = np.where(new, H, left)
        pos[i] = cur
        left = left - 1
        cur = np.where(left <= 0, 0.0, cur)
    return pd.DataFrame(pos, index=entry.index, columns=entry.columns)


def run(px, carry, cost, entry, H, exit_mask=None, unit=0.2, cap=3.0):
    vol = px.pct_change().rolling(60, min_periods=40).std()
    pos = hold_signal(entry.fillna(0.0), H, exit_mask)
    w = pos * (unit * 0.01 / vol)                    # 1つの建玉 = 1日の値動き（1σ）が口座の unit % になる大きさ
    w = w.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    g = w.abs().sum(axis=1)
    w = w.mul((cap / g).clip(upper=1.0).fillna(1.0), axis=0)
    w = w.shift(1).fillna(0.0)                       # 次の日の値段で売買する
    return SL.pnl(w, px, carry, cost), w


def main():
    px, carry, cost = SL.load()
    c = px
    lines = ["# 中期の層の候補：日足の行き過ぎの戻り（27年分、`tools/research/reversion_long.py`）", "",
             "各セル：年率シャープ。右の4列は 2000年以降の全体：シャープ、年率（値動きを年10%にそろえたとき）、最大の下落、プラスの年。", "",
             "| 形 | " + " | ".join(p[0] for p in SL.PER) + " | 全体 | 年率 | 最大の下落 | プラスの年 |",
             "|---|" + "---|" * (len(SL.PER) + 4)]
    R = {}

    def add(key, label, entry, H, exit_mask=None):
        raw, w = run(px, carry, cost, entry, H, exit_mask)
        r = SL.voltarget(raw)
        R[key] = r
        lines.append(SL.row(label, r))
        print(lines[-1], flush=True)

    r14 = rsi(c, 14)
    e_rsi = (r14 < 30).astype(float) - (r14 > 70).astype(float)
    for H in (5, 12, 25):
        add(f"rsi{H}", f"RSI(14) 30/70 の戻り・{H}日持つ", e_rsi, H)
    add("rsi_x50", "RSI(14) 30/70 の戻り・RSI が50に戻るまで（最長25日）", e_rsi, 25, (r14 >= 50, r14 <= 50))
    r14b = (r14 < 25).astype(float) - (r14 > 75).astype(float)
    add("rsi25_12", "RSI(14) 25/75 の戻り・12日持つ", r14b, 12)
    for N in (20, 55):
        hi, lo = c.rolling(N).max().shift(1), c.rolling(N).min().shift(1)
        e = (c < lo).astype(float) - (c > hi).astype(float)
        for H in (5, 12):
            add(f"brk{N}_{H}", f"過去{N}日の高値・安値の更新の逆・{H}日持つ", e, H)
    for N, k in ((20, 2.0), (60, 2.0), (60, 2.5)):
        z = (c - c.rolling(N).mean()) / c.rolling(N).std()
        e = -np.sign(z).where(z.abs() > k, 0.0)
        add(f"z{N}_{k}", f"過去{N}日の平均から{k}σの戻り・12日持つ", e, 12)
        add(f"z{N}_{k}x", f"過去{N}日の平均から{k}σの戻り・平均に戻るまで（最長25日）", e, 25, (z >= 0, z <= 0))
    # 参考：逆（同じ条件でトレンドに乗る）
    hi, lo = c.rolling(55).max().shift(1), c.rolling(55).min().shift(1)
    add("brk55_follow", "（参考）過去55日の高値・安値の更新に乗る・12日持つ", (c > hi).astype(float) - (c < lo).astype(float), 12)
    # 金利差との関係
    import carry_long as CL
    cr = pd.read_parquet(os.path.join(D.CACHE, "carry_long_returns.parquet"))
    x = pd.DataFrame({"rsi12": R["rsi12"], "brk55_12": R["brk55_12"], "z60_2.0": R["z60_2.0"], "carry": cr["C60+"].reindex(R["rsi12"].index)})
    x = x[x.index >= "2000-01-01"]
    lines += ["", "## 金利差の層（今の EA の形）との相関（2000年以降、日次）", "",
              "、".join(f"{k}: {x[k].corr(x['carry']):+.2f}" for k in ("rsi12", "brk55_12", "z60_2.0"))]
    for k in ("rsi12", "brk55_12", "z60_2.0"):
        b = SL.voltarget((x[k] + x["carry"]) / 2)
        lines.append(SL.row(f"組み合わせ：金利差の層 と {k}（半分ずつ）", b))
    yr = pd.DataFrame({k: R[k].groupby(R[k].index.year).sum() * 100 for k in ("rsi12", "brk55_12", "z60_2.0")}).round(1)
    lines += ["", "## 年ごとの成績（%、値動きを年10%にそろえたとき）", "", "| 年 | RSI・12日 | 55日の更新の逆・12日 | 60日・2σの戻り・12日 |", "|---|---|---|---|"]
    for y, r_ in yr.iterrows():
        lines.append(f"| {y} | " + " | ".join(f"{v:+.1f}" for v in r_.values) + " |")
    out = os.path.join(SL.ROOT, "reports", "research", "reversion_long.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[-(len(yr) + 12):]))
    pd.DataFrame(R).to_parquet(os.path.join(D.CACHE, "reversion_long_returns.parquet"))


if __name__ == "__main__":
    main()

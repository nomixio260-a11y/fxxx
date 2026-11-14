#!/usr/bin/env python3
"""仲値・フィキシングなど「決まった時刻」の前後の値動きの偏りを、5分足で調べる。

1時間足の探索（seasonality.py）では、9:55 の東京仲値のような「時刻ちょうど」の需給を捉えにくい。
ここでは、実需の注文が集まることが知られている時刻に絞り、その前後の決まった時間帯の値動きを調べる。

- 時刻：東京仲値 9:55、ロンドン寄り付き 8:00、ECB 参照レート 13:15（ロンドン時間）、
        WM/R ロンドン・フィックス 16:00、米指標 8:30（NY）、NY オプションカット 10:00（NY）
- 時間帯：時刻の 60分前〜時刻、30分前〜時刻、時刻〜30分後、時刻〜60分後、時刻〜120分後
- 日の条件：毎日、ゴトー日（東京仲値のみ）、月末、月初、曜日
- 向きは設計期間の平均で決め、設計期間で |t| ≥ 3 かつコスト込みでプラスのものだけを残す。
- 残ったものを、向きを固定したまま検証期間で確かめる。最終確認期間は見ない。

使い方: python3 tools/research/fix_scan.py    → reports/research/fix_scan.md
        python3 tools/research/fix_scan.py 2  → 追加の時刻で reports/research/fix_scan2.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402

EVENTS = [("tky", 9, 55, "東京仲値"), ("ldn", 8, 0, "ロンドン寄り付き"), ("ldn", 13, 15, "ECB参照レート"),
          ("ldn", 16, 0, "WM/Rフィックス"), ("ny", 8, 30, "米指標"), ("ny", 10, 0, "NYオプションカット")]
# 2回目の探索で加えた時刻（1回目とは別に記録する）
EVENTS2 = [("tky", 9, 0, "東京寄り付き"), ("tky", 10, 15, "人民元基準値"), ("tky", 15, 0, "東京引け"),
           ("ldn", 7, 0, "フランクフルト寄り付き"), ("ldn", 16, 30, "ロンドン引け"), ("ny", 12, 0, "NY昼")]
WINDOWS = [(-60, 0), (-30, 0), (0, 30), (0, 60), (0, 120)]


def scan(events=None):
    events = events or EVENTS
    rows = []
    for pair in D.PAIRS:
        df = D.bars(pair, "5min")
        pip = D.pip_size(pair)
        cost = S.COST[pair]
        o = df["o"]
        for clock, hh, mm, name in events:
            fix = df.index[(df[f"{clock}_h"].values == hh) & (df[f"{clock}_m"].values == mm)]
            if len(fix) == 0:
                continue
            fdf = df.loc[fix]
            filters = S.day_filters(fdf, clock)
            if clock != "tky":
                filters.pop("gotobi", None)
            for a, b in WINDOWS:
                t_in = fix + pd.Timedelta(minutes=a)
                t_out = fix + pd.Timedelta(minutes=b)
                p_in = o.reindex(t_in).values
                p_out = o.reindex(t_out).values
                r = (p_out - p_in) / pip
                # 日付の変わり目（NY 16:00〜18:59）にかかる時間帯は除外
                ny_in = df["ny_h"].reindex(t_in).values
                ny_out = df["ny_h"].reindex(t_out).values
                bad = ((ny_in >= 16) & (ny_in <= 18)) | ((ny_out >= 16) & (ny_out <= 18))
                r = np.where(bad, np.nan, r)
                m_des = D.period_mask(fix, D.DESIGN)
                m_val = D.period_mask(fix, D.VALID)
                m_fin = D.period_mask(fix, D.FINAL)
                for fname, fm in filters.items():
                    des = S.stats(r[fm & m_des], 0.0)
                    if des["n"] < 60 or abs(des["t"]) < 3.0:
                        continue
                    sign = 1.0 if des["mean"] > 0 else -1.0
                    d2 = S.stats(sign * r[fm & m_des], cost)
                    if d2["net"] <= 0:
                        continue
                    v = S.stats(sign * r[fm & m_val], cost)
                    fn = S.stats(sign * r[fm & m_fin], cost)
                    rows.append({"pair": pair, "event": name, "clock": clock, "fix": f"{hh:02d}:{mm:02d}",
                                 "win": f"{a:+d}〜{b:+d}分", "filter": fname, "dir": "買い" if sign > 0 else "売り",
                                 "des_n": d2["n"], "des_mean": d2["mean"], "des_t": d2["t"], "des_pf": d2["pf"],
                                 "val_n": v["n"], "val_mean": v["mean"], "val_t": v["t"], "val_net": v["net"], "val_pf": v["pf"],
                                 "fin_n": fn["n"], "fin_net": fn["net"], "fin_pf": fn["pf"], "fin_t": fn["t"]})
        print(pair, "done", file=sys.stderr, flush=True)
    return pd.DataFrame(rows)


def main():
    second = len(sys.argv) > 1 and sys.argv[1] == "2"
    events = EVENTS2 if second else EVENTS
    tag = ("fix_scan2" if second else "fix_scan") + os.environ.get("AMS_TAG", "")   # 例：AMS_TAG=_new で別のファイルに出す
    res = scan(events)
    n_tests = len(D.PAIRS) * len(WINDOWS) * (len(events) * 8 + 1)
    out_dir = os.path.join(D.ROOT, "reports", "research")
    res.to_csv(os.path.join(out_dir, f"{tag}_all.csv"), index=False)
    passed = res[(res["val_net"] > 0) & (res["val_pf"] >= 1.10) & (res["val_t"] >= 1.5)] if len(res) else res
    lines = ["# 仲値・フィキシング前後の偏りの探索（5分足）", "",
             f"- 調べた仮説の数：約 {n_tests:,} 通り",
             f"- 設計期間で |t| ≥ 3 かつコスト込みでプラス：**{len(res)} 通り**",
             f"- そのうち検証期間でも、コスト込みでプラス・PF 1.10 以上・t ≥ 1.5：**{len(passed)} 通り**",
             "- 最終確認期間（2024年11月〜）は見ていません。", "",
             "| 銘柄 | 時刻 | 時間帯 | 日の条件 | 向き | 設計 回数 | 設計 平均pips | 設計 t | 設計 PF | 検証 回数 | 検証 平均pips | 検証 t | 検証 PF | 検証通過 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    if len(res):
        for _, r in res.sort_values("des_t", key=abs, ascending=False).iterrows():
            ok = "○" if (r.val_net > 0 and r.val_pf >= 1.10 and r.val_t >= 1.5) else ""
            lines.append(f"| {r.pair} | {r.event} {r.fix}（{r.clock}） | {r.win} | {r['filter']} | {r.dir} | {r.des_n} | {r.des_mean:+.1f} | "
                         f"{r.des_t:.1f} | {r.des_pf:.2f} | {r.val_n} | {r.val_mean:+.1f} | {r.val_t:.1f} | {r.val_pf:.2f} | {ok} |")
    text = "\n".join(lines) + "\n"
    open(os.path.join(out_dir, f"{tag}.md"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()

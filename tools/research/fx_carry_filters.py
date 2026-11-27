#!/usr/bin/env python3
"""研究（FX だけで取引する）：金利差の層を、良くする余地があるか。日付・曜日は使わない。

1. ドル・キャリー（Lustig・Roussanov・Verdelhan 2014年に公表）：
   ほかの7通貨の短期金利の平均が米国より高いときは、7通貨を同じ重みで買って米ドルを売る。低いときは、その逆。
   ふつうの金利差の取引（金利の高い通貨を買い、低い通貨を売る）とは別の動きをする、とされている。
2. 株式の流れで止める：金利差の取引は、株が大きく下げる局面で一緒に崩れる（2008年）。
   そこで、S&P500 が200日の平均より下のあいだ（または、過去250日の値動きがマイナスのあいだ）は、金利差の建玉を持たない。
   判定は前日までの終値、数値はよく使われる値のまま（選び直さない）。
- データ・コストは carry_long.py と同じ（FRED の日次、17ペア、スプレッド、スワップ = 金利差 − 上乗せ 年1%）。週1回の入れ替え（5通りのずれの平均）。
使い方: python3 tools/research/fx_carry_filters.py  → reports/research/fx_carry_filters.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import carry_long as CL  # noqa: E402
import fred_data as F  # noqa: E402
import styles_long as SL  # noqa: E402
import yahoo_data as Y  # noqa: E402

USD_PAIRS = {"EURUSD": 1, "GBPUSD": 1, "AUDUSD": 1, "NZDUSD": 1, "USDCAD": -1, "USDCHF": -1, "USDJPY": -1}    # +1 = ペアを買うと、米ドル売り・相手の通貨の買い


def dollar_carry_weights(px, carry):
    """7つの対ドルのペアを同じ重みで持つ。向きは、ほかの通貨の金利の平均 − 米国の金利 の符号。"""
    # carry[p] = 基準通貨の金利 − 相手通貨の金利。相手の通貨から見た「外国 − 米国」にそろえる
    fd = pd.DataFrame({p: s * carry[p] for p, s in USD_PAIRS.items()})
    afd = fd.mean(axis=1)                      # 外国の金利の平均 − 米国の金利
    sig = np.sign(afd)
    vol = px[list(USD_PAIRS)].pct_change().rolling(60, min_periods=40).std()
    w = pd.DataFrame({p: s * sig / vol[p] for p, s in USD_PAIRS.items()})
    out = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    out[list(USD_PAIRS)] = SL.norm(w.fillna(0.0))
    return out, afd


def equity_on(index, kind):
    c = Y.fetch("SPX")["close"]
    if kind == "ma200":
        on = (c > c.rolling(200).mean()).astype(float)
    else:
        on = (c / c.shift(250) - 1.0 > 0).astype(float)
    on = on.shift(1)                              # 前日までの終値で判定する
    return on.reindex(on.index.union(index)).ffill().reindex(index).fillna(0.0)


def run(px, carry, cost, w0, on=None):
    outs = []
    for ph in range(CL.PH):
        w = CL.hold_phase(w0, 5, ph)
        if on is not None:
            w = w.mul(CL.hold_phase(on.to_frame("x"), 5, ph)["x"], axis=0)       # 止める・再開するのも、週1回の入れ替えのときだけ
        ws = w.mul(SL.exante_scale(w, px), axis=0)
        outs.append(SL.pnl(ws, px, carry, cost))
    return outs


def main():
    px, carry, cost = SL.load()
    lines = ["# 研究：金利差の層を良くする余地（取引は為替だけ。`tools/research/fx_carry_filters.py`）", "",
             "各セル：年率シャープ。5通りの入れ替えのずれの平均（括弧内は最小〜最大）。右の5列は 2000年以降の全体。", "",
             "| 形 | " + " | ".join(p[0] for p in SL.PER) + " | 全体 | 年率 | 最大の下落 | 最悪の年 | プラスの年 |", "|---|" + "---|" * (len(SL.PER) + 5)]
    keep = {}

    def add(key, label, outs):
        line, x = CL.summarize(label, outs)
        lines.append(line)
        keep[key] = x
        print(line, flush=True)
    wa1 = CL.weights(px, carry, thr=1.0)
    wea = CL.weights(px, carry, thr=1.0, trend=60, topk=5, crash=2.0)
    wdc, afd = dollar_carry_weights(px, carry)
    on_ma, on_ts = equity_on(px.index, "ma200"), equity_on(px.index, "ts250")
    add("A1", "金利差（1%以上・すべて）", run(px, carry, cost, wa1))
    add("A1_ma", "　＋S&P500 が200日の平均より下のあいだは休む", run(px, carry, cost, wa1, on_ma))
    add("A1_ts", "　＋S&P500 の過去250日がマイナスのあいだは休む", run(px, carry, cost, wa1, on_ts))
    add("EA", "金利差＋トレンド60日（今の EA の形）", run(px, carry, cost, wea))
    add("EA_ma", "　＋S&P500 が200日の平均より下のあいだは休む", run(px, carry, cost, wea, on_ma))
    add("DC", "ドル・キャリー（7通貨の平均の金利と米国の金利の比べ）", run(px, carry, cost, wdc))
    add("DC_ma", "　＋S&P500 が200日の平均より下のあいだは休む", run(px, carry, cost, wdc, on_ma))
    df = pd.DataFrame(keep)
    c = df.corr()
    lines += ["", f"相関（2000年以降、日次）：金利差とドル・キャリー {c.loc['A1', 'DC']:+.2f}、金利差と金利差＋株式の流れ {c.loc['A1', 'A1_ma']:+.2f}", "",
              "## 組み合わせ（同じ重み、値動きを年10%にそろえる）", "",
              "| 組み合わせ | " + " | ".join(p[0] for p in SL.PER) + " | 全体 | 年率 | 最大の下落 | プラスの年 |", "|---|" + "---|" * (len(SL.PER) + 4)]
    for lab, keys in (("金利差 ＋ ドル・キャリー", ["A1", "DC"]), ("金利差（株式の流れで休む）＋ ドル・キャリー", ["A1_ma", "DC"]),
                      ("金利差（株式の流れで休む）＋ ドル・キャリー（株式の流れで休む）", ["A1_ma", "DC_ma"])):
        x = df[keys].mean(axis=1)
        x = x * (0.10 / (x.std() * np.sqrt(SL.ANN)))
        lines.append(SL.row(lab, x))
    yr = pd.DataFrame({k: df[k].groupby(df.index.year).sum() * 100 for k in ("A1", "A1_ma", "DC")}).round(1)
    lines += ["", "## 年ごとの成績（%、値動きを年10%にそろえたとき）", "", "| 年 | 金利差 | 金利差（株式の流れで休む） | ドル・キャリー |", "|---|---|---|---|"]
    for y, r_ in yr.iterrows():
        lines.append(f"| {y} | " + " | ".join(f"{v:+.1f}" for v in r_.values) + " |")
    days_on = on_ma[on_ma.index >= "2000-01-01"].mean() * 100
    lines += ["", f"S&P500 が200日の平均より上だった日の割合（2000年〜）：{days_on:.0f}%。ほかの通貨の金利の平均が米国より高かった日の割合：{(afd[afd.index >= '2000-01-01'] > 0).mean() * 100:.0f}%"]
    out = os.path.join(SL.ROOT, "reports", "research", "fx_carry_filters.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[-(len(yr) + 14):]))
    df.to_parquet(os.path.join(D.CACHE, "fx_carry_filters_returns.parquet"))


if __name__ == "__main__":
    main()

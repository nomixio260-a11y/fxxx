#!/usr/bin/env python3
"""短期の層の候補「平均からの大きなずれの戻り」を、1ペア1建玉の取引として詳しく確かめる（時刻・曜日・日付は判断に使わない）。

- パターン（pattern_zoo.py で通ったもの）：
  Z：終値が、直近100本の平均から 2.5σ 以上離れたら、戻る向きに入る
  BRK：直近55本の高値・安値を終値で更新したら、逆向きに入る
  CBB：金利差のあるペアで、金利差の向きと逆にボリンジャーバンド（20本・2σ）を越えたら、金利差の向きに入る
- 取引の決まり：足の終値で判定 → 次の足の始値で入る（そのペアに建玉がないときだけ）→ H 本後の始値で出る。
  日付の変わり目（NY 16:00〜18:59）に始まる足では入らない。コストは S.COST + 0.5 pips。
- 見かけの利益でないかの確認：
  買いと売りを分ける（手元のデータは売値だけなので、スプレッドが広がった瞬間の見かけの下げを拾うと、買いだけが勝つ）／
  入った時刻（NY の時）ごと／ペアごと／年ごと。
使い方: python3 tools/research/mr_deepdive.py  → reports/research/mr_deepdive.md
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import seasonality as S  # noqa: E402
import fred_data as F  # noqa: E402
import pattern_zoo as Z  # noqa: E402

PER = Z.PER


def trig(b, kind, carry_dir=None):
    c, h, l = b["c"], b["h"], b["l"]
    if kind == "Z":
        z = (c - c.rolling(100).mean()) / c.rolling(100).std()
        return (-np.sign(z).where(z.abs() > 2.5, 0.0)).fillna(0.0).values
    if kind == "BRK":
        hi, lo = h.rolling(55).max().shift(1), l.rolling(55).min().shift(1)
        return ((c < lo).astype(float) - (c > hi).astype(float)).values
    if kind == "CBB":
        ma, sd = c.rolling(20).mean(), c.rolling(20).std()
        bb = (c > ma + 2 * sd).astype(float) - (c < ma - 2 * sd).astype(float)
        cd = pd.Series(carry_dir.reindex(c.index.normalize()).values, index=c.index).fillna(0.0)
        return (((bb < 0) & (cd > 0)).astype(float) - ((bb > 0) & (cd < 0)).astype(float)).values
    raise ValueError(kind)


def simulate(pair, mins, kind, H, carry_dir=None):
    b = Z.bars(pair, mins)
    s = trig(b, kind, carry_dir)
    o = b["o"].values
    idx = b.index
    ny = idx.tz_localize("UTC").tz_convert("America/New_York")
    ny_h = ny.hour.values
    pip = D.pip_size(pair)
    cost = S.COST.get(pair, 2.0) + 0.5
    per_day = {60: 24, 240: 6}[mins]
    dvol = (b["c"].pct_change().rolling(per_day * 20, min_periods=per_day * 10).std() * np.sqrt(per_day)).values
    rows = []
    i, n = 0, len(b)
    while i < n - H - 1:
        if s[i] != 0:
            e = i + 1
            if mins < 1440 and 16 <= ny_h[e] <= 18:
                i += 1
                continue
            x = e + H
            g = s[i] * (o[x] - o[e]) / pip
            rows.append((idx[e], pair, int(s[i]), g, g - cost, (g - cost) * pip / o[e] / dvol[i] if dvol[i] > 0 else np.nan, int(ny_h[e])))
            i = x            # 出るまで、次の取引はしない
        else:
            i += 1
    return pd.DataFrame(rows, columns=["t", "pair", "dir", "gross", "net", "netn", "ny_h"]).set_index("t")


def tstat(x):
    x = x.dropna()
    return x.mean() / x.std() * np.sqrt(len(x)) if len(x) > 20 and x.std() > 0 else 0.0


def by_period(tr, col="net"):
    cells = []
    for _, a, b in PER:
        x = tr[(tr.index >= a) & (tr.index < b)][col]
        cells.append(f"{x.mean():+.2f}（t {tstat(x):+.1f}、{len(x)}）" if len(x) else "—")
    return cells


def main():
    import styles_long as SL
    px_d = F.prices()
    cr = F.carry_daily(px_d.index)
    cdir = np.sign(cr).where(cr.abs() - SL.MARKUP >= 1.0, 0.0)
    lines = ["# 短期の層の候補：平均からの大きなずれの戻り（`tools/research/mr_deepdive.py`）", "",
             "1ペア1建玉の取引として試算。各セル：1回あたりの損益（コスト後、pips）と t 値・回数。", ""]
    forms = (("Z 1時間足・4本", 60, "Z", 4), ("Z 1時間足・12本", 60, "Z", 12), ("Z 4時間足・4本", 240, "Z", 4),
             ("BRK 1時間足・12本", 60, "BRK", 12), ("CBB 1時間足・4本", 60, "CBB", 4))
    for label, mins, kind, H in forms:
        tr = pd.concat([simulate(p, mins, kind, H, cdir[p]) for p in F.PAIRS]).sort_index()
        lines += [f"## {label}（全 {len(tr)} 回）", "", "| 分け方 | " + " | ".join(p[0] for p in PER) + " |", "|---|" + "---|" * len(PER)]
        lines.append("| すべて（コスト後） | " + " | ".join(by_period(tr)) + " |")
        lines.append("| すべて（コスト前） | " + " | ".join(by_period(tr, "gross")) + " |")
        lines.append("| 買いだけ | " + " | ".join(by_period(tr[tr["dir"] > 0])) + " |")
        lines.append("| 売りだけ | " + " | ".join(by_period(tr[tr["dir"] < 0])) + " |")
        # 入った時刻（NY）ごと：4時間ごとにまとめる
        for lo in range(0, 24, 4):
            m = (tr["ny_h"] >= lo) & (tr["ny_h"] < lo + 4)
            lines.append(f"| NY {lo}〜{lo + 3}時に入ったもの | " + " | ".join(by_period(tr[m])) + " |")
        lines += ["", "| ペア | " + " | ".join(p[0] for p in PER) + " | 全期間の合計 pips |", "|---|" + "---|" * (len(PER) + 1)]
        for p in F.PAIRS:
            x = tr[tr["pair"] == p]
            lines.append(f"| {p} | " + " | ".join(by_period(x)) + f" | {x['net'].sum():+.0f} |")
        yr = tr.groupby(tr.index.year)["net"].agg(["mean", "count", "sum"])
        lines += ["", "年ごと（1回あたり pips／回数）：" + "、".join(f"{y}: {r['mean']:+.2f}／{int(r['count'])}" for y, r in yr.iterrows()), ""]
        print(label, "done", flush=True)
        tr.to_parquet(os.path.join(D.CACHE, f"mr_trades_{kind}_{mins}_{H}.parquet"))
    out = os.path.join(F.ROOT, "reports", "research", "mr_deepdive.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

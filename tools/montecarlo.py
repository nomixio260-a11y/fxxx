#!/usr/bin/env python3
"""月ごとの損益率から、モンテカルロ法でリスクと目標達成の見込みを見積もる。

バックテストは「たまたま起きた1通りの月の並び」の結果にすぎない。
月ごとの損益率を、戻しながら無作為に選び直して（ブートストラップ）、同じ長さの成績を何千通りも作り、
- 最大ドローダウン（最高値からの下落）の分布
- 1年後の損益率の分布
- 月平均（幾何平均）が +5% 以上になる確率
を出す。

使い方:
  python3 tools/montecarlo.py reports/runs/0221.txt [reports/runs/0222.txt ...] [--months 12] [--n 20000]
  （実行結果のファイルにある "MONTHLY 年-月:損益率,..." の行を読みます。複数のファイルを渡すと、月をまとめて使います）
"""
import argparse
import sys

import numpy as np


def read_monthly(path):
    for line in open(path, encoding="utf-8", errors="ignore"):
        if line.startswith("MONTHLY "):
            pairs = line[len("MONTHLY "):].strip().split(",")
            return [float(p.split(":")[1]) / 100.0 for p in pairs if ":" in p]
    raise SystemExit(f"{path} に MONTHLY の行がありません（ワークフローの更新後に実行した結果が必要です）")


def max_dd(path):
    peak = np.maximum.accumulate(path, axis=1)
    return ((peak - path) / peak).max(axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--months", type=int, default=12, help="1回の試行の長さ（か月）")
    ap.add_argument("--n", type=int, default=20000, help="試行の回数")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    r = np.concatenate([read_monthly(f) for f in a.files])
    rng = np.random.default_rng(a.seed)
    idx = rng.integers(0, len(r), size=(a.n, a.months))
    growth = np.cumprod(1.0 + r[idx], axis=1)
    path = np.concatenate([np.ones((a.n, 1)), growth], axis=1)
    dd = max_dd(path)
    final = growth[:, -1] - 1.0
    geo = growth[:, -1] ** (1.0 / a.months) - 1.0
    q = lambda x, p: np.quantile(x, p) * 100  # noqa: E731
    print(f"# モンテカルロ分析（月 {len(r)} か月分から、{a.months} か月の成績を {a.n:,} 通り作成）")
    print()
    print(f"- 元の月平均 {r.mean() * 100:+.2f}%、標準偏差 {r.std(ddof=1) * 100:.2f}%、最悪の月 {r.min() * 100:+.2f}%")
    print(f"- {a.months} か月後の損益率：中央値 {q(final, .5):+.1f}%、悪いほうから5% {q(final, .05):+.1f}%、良いほうから5% {q(final, .95):+.1f}%")
    print(f"- {a.months} か月後に損失になっている確率：{(final < 0).mean() * 100:.1f}%")
    print(f"- 月平均（幾何平均）が +5% 以上になる確率：{(geo >= 0.05).mean() * 100:.1f}%")
    print(f"- 最大ドローダウン：中央値 {q(dd, .5):.1f}%、悪いほうから5% {q(dd, .95):.1f}%、悪いほうから1% {q(dd, .99):.1f}%")
    print(f"- 最大ドローダウンが 30% を超える確率：{(dd > 0.30).mean() * 100:.1f}%、50% を超える確率：{(dd > 0.50).mean() * 100:.1f}%")
    print()
    print("※ 月どうしの関係（負けが続きやすい、など）は考えていません。実際のドローダウンはこれより大きくなることがあります。")


if __name__ == "__main__":
    sys.exit(main())

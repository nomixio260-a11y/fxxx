#!/usr/bin/env python3
"""研究：金・原油の CFD で、日中〜数日の値動きのパターンに優位性があるか（108章）。時刻・曜日・日付は判断に使わない。

- 株価指数の一斉検証（index_zoo.py、98章）と同じ 27 種類のパターン × 4つの時間足（15分・1時間・4時間・1日）× 保有（1・4・12本）× 買い・売りを、
  金（XAUUSD、2009年3月〜）と原油（WTIUSD、2011年1月〜）の1分足（histdata の CFD、2026年10月まで）に当てはめる。銘柄ごとに別々に評価する。
- 計算は index_zoo.py と同じ（足の終値で判定 → 次の足の始値で入り → 決めた本数の後の始値で出る。コストはスプレッド：金 0.39ドル、原油 0.05ドル＝
  商品の口座で確かめた値。持ち越しのコストは入れていない＝数日持つ形には甘い）。
- 期間と合格の基準は index_zoo.py と同じ（結果を見る前に決めた）：設計 2011〜2018年で t ≥ 3、選ぶ 2019〜2022年で t ≥ 2（どちらもコスト後）。
  買い・売りそれぞれ 324 通り × 2銘柄 = 1,296 通りを調べるので、たまたま設計で t ≥ 3 になるものが 2 つほど出る計算。答え合わせ（2023年〜）でも
  プラスで、かつ「条件なしで持った場合との差」がはっきりあるものだけを、次の検証（OANDA の実際の値段・持ち越しのコスト込み）に進める。
使い方: python3 tools/research/commodity_zoo.py  → reports/research/commodity_zoo_gold.md、commodity_zoo_oil.md
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import index_zoo as IZ  # noqa: E402


def main():
    IZ.main({"金": ("XAUUSD", 0.39)}, out="commodity_zoo_gold", title="金", note="金（XAUUSD）だけで評価。")
    IZ.main({"原油": ("WTIUSD", 0.05)}, out="commodity_zoo_oil", title="原油", note="原油（WTIUSD）だけで評価。")


if __name__ == "__main__":
    main()

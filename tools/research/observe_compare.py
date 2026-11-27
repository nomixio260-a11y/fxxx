#!/usr/bin/env python3
"""実際の口座（観察モード・注文なし）とテスターの「判定」を、日付ごとに突き合わせる（100章）。

- 実際の口座のログ：`mt5-live-index.yml` を trading=false・プリセット `AMS_Sleeves_Index_Observe.set` で動かしたときの EA のログ
  （`reports/live_index/logs/`）。EA は、口座の日足の履歴から、過去30日分の判定をやり直してログに出す。
- テスターのログ：同じプリセットで `mt5-backtest.yml` を動かしたときの、テスターのログ（EA は毎日の判定をログに出す）。
- 比べるもの（銘柄 × 判定に使った最後の日足の日付ごと）：持つルール、VIX の倍率、目標の建玉の割合（有効証拠金に対する）、
  1日の値動きの見積もり、その日足の始値・高値・安値・終値。
使い方: python3 tools/research/observe_compare.py 実口座のログ テスターのログ
"""
import re
import sys

live_f, test_f = sys.argv[1], sys.argv[2]
pat_l = re.compile(r"過去の判定）(\S+) (\d{4}\.\d\d\.\d\d) までの日足で判定：持つルール：(.*?)、目標の割合 ([\d.]+)、1日の値動きの見積もり ([\d.]+)%、VIX の倍率 ([\d.]+)、その日足 始 ([\d.]+) 高 ([\d.]+) 安 ([\d.]+) 終 ([\d.]+)")
pat_t = re.compile(r"観察モード）(\S+) 判定に使った最後の日足 (\d{4}\.\d\d\.\d\d) 始 ([\d.]+) 高 ([\d.]+) 安 ([\d.]+) 終 ([\d.]+)、持つルール：(.*?)、目標の割合 ([\d.]+)、1日の値動きの見積もり ([\d.]+)%、VIX の倍率 ([\d.]+)")
live, test = {}, {}
for line in open(live_f, encoding="utf-8", errors="replace"):
    m = pat_l.search(line)
    if m:
        sym, d, st, fr, dv, vm, o, h, l, c = m.groups()
        live[(sym, d)] = (st.strip(), float(fr), float(dv), float(vm), float(o), float(h), float(l), float(c))
    m = pat_t.search(line)
    if m:
        sym, d, o, h, l, c, st, fr, dv, vm = m.groups()
        live[(sym, d)] = (st.strip(), float(fr), float(dv), float(vm), float(o), float(h), float(l), float(c))
for line in open(test_f, encoding="utf-8", errors="replace"):
    m = pat_t.search(line)
    if m:
        sym, d, o, h, l, c, st, fr, dv, vm = m.groups()
        test[(sym, d)] = (st.strip(), float(fr), float(dv), float(vm), float(o), float(h), float(l), float(c))
keys = sorted(set(live) & set(test), key=lambda k: (k[1], k[0]))
print(f"実口座 {len(live)} 件、テスター {len(test)} 件、両方にある（銘柄×日）{len(keys)} 件、日付 {keys[0][1]}〜{keys[-1][1]}")
nstate = nfr = nbar = nvm = 0
worst_fr = worst_dv = worst_px = 0.0
bad = []
for k in keys:
    a, b = live[k], test[k]
    same_state = a[0] == b[0]
    dfr = abs(a[1] - b[1]) / max(abs(b[1]), 1e-9) if (a[1] or b[1]) else 0.0
    ddv = abs(a[2] - b[2]) / max(b[2], 1e-9)
    dpx = max(abs(a[i] - b[i]) / b[i] for i in (4, 5, 6, 7))
    nstate += same_state; nvm += (a[3] == b[3]); nfr += (dfr < 0.005); nbar += (dpx < 1e-6)
    worst_fr, worst_dv, worst_px = max(worst_fr, dfr), max(worst_dv, ddv), max(worst_px, dpx)
    if not same_state or dfr >= 0.005 or dpx >= 1e-6:
        bad.append((k, a, b))
print(f"持つルールが同じ：{nstate}/{len(keys)}、VIX の倍率が同じ：{nvm}/{len(keys)}、目標の割合の差が 0.5% 未満：{nfr}/{len(keys)}、日足の4つの値が完全に同じ：{nbar}/{len(keys)}")
print(f"差の最大：目標の割合 {worst_fr*100:.3f}%、値動きの見積もり {worst_dv*100:.3f}%、日足の値 {worst_px*100:.4f}%")
for k, a, b in bad[:40]:
    print("  ", k, "実口座", a, "| テスター", b)

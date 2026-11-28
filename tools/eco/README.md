# 複合システム（確率で売買するための予想エンジン）

指標・ルール・チャートの形をすべて数値にして、複数の予想モデルに渡し、「次の日に上がる確率」を合成して、確率に比例した大きさで売買する仕組み。
記録は `reports/experiments.md` の 109章、成績は `reports/eco/`。

## 全体の流れ

```
日足（4本値）
  │
  ├─ 1 数値にする ……… features.py（指標 78 個）＋ いまの層のルールの状態 4 ＋ VIX 3
  │                     dataset.py（学習用のデータ：指数・為替・金属・OANDA の CFD、チャートの窓 64 本）
  │
  ├─ 2 予想する ………… 5つの専門家（どれも「次の日に上がる確率」を出す）
  │                     LR  線形             GBM 勾配ブースティング      CNN チャートを読むモデル（4本値の形だけを見る）
  │                     REG 期待値のモデル    KNN 形の似た過去の場面を探すモデル
  │                     ml.py（v1）・ml2.py（v2：銘柄の種類ごと・新しいデータを重く）
  │
  ├─ 3 合成する ………… AVG（平均）・META（上位のモデル）・HEDGE（直近よく当たっている専門家を重くする）
  │                     evaluate.py（検証と、昇格の判定。基準は、結果を見る前にファイルの先頭に書いてある）
  │
  ├─ 4 建玉にする ……… 合図 z ＝（確率 − ふだんの水準）÷ ばらつき（±2 まで）。建玉 ＝ 単位 × z ÷ 値動きの大きさ
  │                     EA の「確率の層」（MQL5/Include/AMS/ProbSleeve.mqh）。毎日、4×1日の値動き の逆指値を置き直す
  │
  └─ 5 毎日まわす ……… EA が確定した日足を書き出す → predict.py が確率を計算して AMS_prob.csv に書く → EA が読む
                        影のモード（注文は出さず、記録だけ）→ shadow_score.py が当たり外れを採点 → 基準を満たしたら昇格を提案
```

## ファイル

| ファイル | 役割 |
|---|---|
| `features.py` | 指標を数値にする（移動平均・RSI・MACD・一目均衡表・ボリンジャーバンド、TradingView で広く使われている SuperTrend・UT Bot・Squeeze Momentum・WaveTrend・QQE・SSL・Hull など 78 個）。どれも、その日までの値だけで計算し、値段の水準によらない形にしてある |
| `dataset.py` | 学習・検証用のデータを組み立てる（1行 ＝ 1銘柄の1日）。VIX は CBOE の公表値 |
| `scoreboard.py` | 指標ごとの成績表（その指標の値と、次の日の値動きの関係）→ `reports/eco/indicators.md` |
| `ml.py`・`ml2.py` | 予想モデルの学習。毎年、その年より前のデータだけで学習して、その年を予想する（2005〜2026年） |
| `evaluate.py` | 確率の合成、コスト込みの売買の検証、相場の状態ごとの内訳、昇格の判定 → `reports/eco/v1.md`・`v2.md` |
| `sizing.py` | 建玉の決め方の改良（期待値がコストを上回る分だけ持つ）の検証 → `reports/eco/sizing.md` |
| `metals.py` | 金属だけに絞ったエンジンの検証 → `reports/eco/metals.md` |
| `export_prob.py` | 検証用の予想のファイル（`MQL5/Files/AMS_prob_*.csv`）を作る。MT5 のテスターが読む |
| `final.py` | 毎日の予想に使うモデルを保存する（`models/eco/index/`）。保存したモデルが、検証のときの予想と同じ値を出すことを確かめる |
| `predict.py` | 毎日の予想を出す（numpy・pandas・lightgbm だけで動く）。EA が書き出した日足 → `AMS_prob.csv` |
| `shadow_score.py` | 影のモードの記録を採点する → `reports/eco/shadow.md` |

## 動かし方

```
# 学習と検証（OANDA の日足の書き出しがあるとき。なければ、公開のデータだけで動く）
AMS_IX_EXPORT=<指数の口座の書き出し> AMS_CM_EXPORT=<商品の口座の書き出し> python3 tools/eco/dataset.py
python3 tools/eco/ml2.py && python3 tools/eco/evaluate.py v2
python3 tools/eco/scoreboard.py

# 毎日の予想に使うモデルを作り直す（年に1回、年の初めに。チャートを読むモデルは2年に1回）
python3 tools/eco/final.py 2027

# MT5 のテスターで確かめる（予想のファイルを作って、コミットしてから、ワークフローを起動する）
python3 tools/eco/export_prob.py v2 avg4
#   入力：InpPbSymbols=US500,US100,US30;InpPbFile=AMS_prob_v2_avg4.csv;InpPbShadow=false

# 影のモードの記録を採点する
python3 tools/eco/shadow_score.py
```

## 決まり

- 日付・曜日・時刻は、判断に使わない（特徴量に入れていない）。
- 予想は、いつも「その年より前のデータだけで学習したモデル」で出す。成績は、学習に使っていない年の予想だけで測る。
- 合否の基準は、結果を見る前に、スクリプトの先頭に書く。あとから基準を下げない。試した回数も記録する。
- 基準を満たすまでは、エンジンは影のモード（注文を出さない）。昇格は、報告して判断を仰いでから。

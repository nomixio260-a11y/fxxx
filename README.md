# Adaptive Multi-Strategy EA（MT5）

相場状況（トレンド／レンジ／中立／高ボラティリティ）を自動で判定し、
4つの売買ロジックの重みを切り替えて売買する MetaTrader 5 用 EA です。
デフォルトは **USDJPY / H1**、ブローカーは **OANDA（デモ口座）** を想定しています。

> ⚠️ このEAは利益を保証するものではありません。FX は元本を超える損失が出る可能性があります。
> 必ず **デモ口座** で十分に検証してから、自己責任でお使いください。

---

## 仕組み

### 1. 相場状況の判定（`MQL5/Include/AMS/Regime.mqh`）
確定足を使って、次の順番で判定します。

| 判定 | 条件（デフォルト） |
|---|---|
| 高ボラティリティ | ATR(14) が直近100本の上位10%（順位 ≥ 0.90） |
| 強いトレンド | ADX(14) ≥ 25、かつ EMA50/EMA200 の傾き・並び・終値の位置がそろっている |
| レンジ | ADX(14) < 20、かつ BB(20, 2σ) の幅が直近100本の中央値以下 |
| 中立 | 上のどれでもない |

### 2. 売買ロジック（`MQL5/Include/AMS/Strategies.mqh`）
各ロジックは -1（強い売り）〜 +1（強い買い）のシグナルを出します。

| ロジック | 内容 |
|---|---|
| トレンドフォロー (TF) | EMA20/EMA50 のクロス（±1）、クロス後の押し目・戻り（±0.5）。H4 EMA200 に逆らう方向は無視 |
| ブレイクアウト (BO) | 直近20本の高値/安値を終値で抜けた（±1）。H4 の方向に逆らう場合は半分 |
| 逆張り (MR) | BB の外から内側へ戻り、RSI も極端（±1）。RSI 30/70 の抜け戻しのみ（±0.5） |
| モメンタム (MO) | MACD ヒストグラムの 0 ラインクロス。ストキャスティクスが同じ向きなら ±1、違えば ±0.5 |

### 3. 使い分け（重み）
相場状況ごとに重みを付け、`スコア = Σ(重み×シグナル) ÷ Σ重み` が
`InpEntryThreshold`（0.45）以上で買い、−0.45 以下で売りです。

| 相場状況 | TF | BO | MR | MO |
|---|---|---|---|---|
| トレンド | 0.50 | 0.30 | 0.00 | 0.20 |
| レンジ | 0.00 | 0.00 | 0.80 | 0.20 |
| 中立 | 0.30 | 0.25 | 0.15 | 0.30 |
| 高ボラ | 中立と同じ重み。ロットは半分（`InpHighVolMode` で「停止」にも変更可） |

- 判定は **新しい足ができたときだけ** 行います。
- 逆方向のシグナルが出たら、保有中のポジションを決済します（`InpCloseOnOpposite`）。
- ナンピンや積み増しはしません（最大ポジション数のデフォルトは 1）。

### 4. 資金管理（`MQL5/Include/AMS/RiskManager.mqh`）
- **ロット**：有効証拠金の 1%（`InpRiskPercent`）を、SL に掛かったときの損失額とします。
  - 損失額は `OrderCalcProfit` で計算するので、円口座でも正しく計算されます。
  - ロットはブローカーの最小ロット・最大ロット・刻み幅に合わせて調整します。
- **SL / TP**：SL = ATR×1.5、TP = ATR×3.0。
- **建値ストップ**：含み益が ATR×1.0 に達したら、SL を建値＋0.5pips に移します。
- **トレーリング**：含み益が ATR×1.5 を超えたら、現在値から ATR×1.0 の位置で SL を追いかけます。
- **1日の損失上限**：損失が 3% に達したら、その日は新規エントリーをしません。

### 5. フィルター（`MQL5/Include/AMS/TradeFilters.mqh`）
- スプレッドが 2.0 pips を超えたら見送り
- 取引時間の指定（デフォルトは終日）
- 金曜 22時（サーバー時間）以降は全決済（週末持ち越しなし）
- 月曜 2時までは新規エントリーなし

---

## Windows の MT5 で使う手順

1. MT5 を起動し、メニューの「ファイル」→「データフォルダを開く」を選びます。
2. このリポジトリの `MQL5` フォルダの中身を、データフォルダの `MQL5` に上書きコピーします。
   - `MQL5/Experts/AdaptiveMultiStrategyEA.mq5`
   - `MQL5/Include/AMS/*.mqh`
3. MetaEditor（F4）で `AdaptiveMultiStrategyEA.mq5` を開き、「コンパイル」（F7）を押します。
   - エラー0になることを確認してください。
4. MT5 の「ナビゲーター」→「エキスパートアドバイザ」から、USDJPY の **1時間足** チャートにドラッグします。
5. 「アルゴ取引を許可」にチェックを入れ、ツールバーの「アルゴ取引」ボタンをONにします。

### OANDA の注意点
- 銘柄名に接尾辞が付く口座があります（例：`USDJPY.oj1m`）。
  - EA は貼り付けたチャートの銘柄（`_Symbol`）で動くので、そのまま使えます。
- 最小ロットや刻み幅はコースによって違います。
  - EA は口座の設定を読み取って自動で合わせます。
  - 計算したロットが最小ロット未満になる場合は、エントリーを見送ります。
  - それでも最小ロットで入りたい場合は、`InpAllowMinLot = true` にしてください（リスクが設定より大きくなります）。
- 取引時間・金曜クローズの時刻は **サーバー時間** です。OANDA のサーバー時間に合わせて調整してください。

### MT5 の画面でバックテストする
1. 「表示」→「ストラテジーテスター」（Ctrl+R）を開きます。
2. 次のように設定します。

   | 項目 | 設定 |
   |---|---|
   | エキスパート | `AdaptiveMultiStrategyEA` |
   | 銘柄 | `USDJPY`（接尾辞付きの場合はその名前） |
   | 時間足 | H1 |
   | 期間 | 直近2年など |
   | モデル | 「1分足OHLC」または「全ティック」 |
   | 初期証拠金 | 1,000,000 JPY |

3. 「開始」を押します。
   - 終了後、「操作ログ」に相場状況別・ロジック別の成績が `[AMS]` で表示されます。
   - 同じ内容が `Common/Files/AMS_breakdown.csv` にも出力されます。
4. 最適化をするときは、「最適化基準」を「カスタム最大」にしてください。
   - EA の `OnTester` が「PF × √取引数 ÷ (1 + 最大DD%/10)」を返すので、DD が小さく安定した設定が上位に来ます。
   - 過去データに合わせすぎないよう、期間の後半をフォワードテストに分けることをおすすめします。

---

## Linux（Wine）で動かすスクリプト

画面のない Linux サーバーでも、Wine と Xvfb で MT5 を動かせます。

```bash
bash tools/install_mt5.sh          # Wine・Xvfb・MT5 を導入
bash tools/compile.sh              # MetaEditor でコンパイル（エラー0・警告0を確認）

cp tester/credentials.env.example tester/credentials.env
# tester/credentials.env に OANDA デモ口座の ID・パスワード・サーバー名・銘柄名を書く（git 管理外）
bash tools/backtest.sh             # 直近2年をバックテスト → reports/ に保存
bash tools/backtest.sh 2023.01.01 2025.12.31   # 期間を指定する場合
```

- 結果は `reports/summary.md`（要約）、HTML レポート、`AMS_breakdown.csv` に保存されます。
- OANDA の MT5 インストーラーを使いたい場合は、`MT5_INSTALLER_URL` にその URL を指定して `install_mt5.sh` を実行してください。
- ログイン情報は、`tester/credentials.env`（`.gitignore` で除外）と、実行中だけ作る一時ファイルにしか書きません。
  - 一時ファイルは、終了時に削除します。

---

## GitHub Actions でバックテストする（PC不要・スマホから実行可）

`.github/workflows/mt5-backtest.yml` は、Windows ランナー上で次の3つを行います。
1. MT5 をインストールする
2. EA をコンパイルする（エラー0・警告0を確認）
3. OANDA デモ口座にログインして、ストラテジーテスターを実行する

### 初回だけの設定（スマホのブラウザでも可）
1. GitHub でリポジトリを開き、**Settings → Secrets and variables → Actions** に進みます。
2. 「**New repository secret**」で、次の3つを登録します。

   | 名前 | 内容 |
   |---|---|
   | `MT5_LOGIN` | OANDA デモ口座のログインID（数字） |
   | `MT5_PASSWORD` | デモ口座のパスワード |
   | `MT5_SERVER` | MT5 のログイン画面に表示されるサーバー名（例：`OANDA-Japan MT5 Demo`） |

3. （任意）**Variables** タブで、次の変数を登録できます。
   - `MT5_SYMBOL`：銘柄名に接尾辞がある場合（例：`USDJPY.oj1m`）
   - `MT5_INSTALLER_URL`：別の MT5 インストーラーを使う場合
     - 既定は OANDA 版（`oanda.corporation/mt5/oanda5setup.exe`）です。
     - OANDA のサーバー一覧が入っているので、サーバー名でログインできます。

### 実行
1. **Actions** タブで「MT5 Backtest」を選び、「**Run workflow**」を押します。
   - 期間・銘柄・モデルは、その場で指定できます。
2. 終わったら、実行結果の **Summary** に成績の要約が表示されます。
   - HTML レポートやログは「**mt5-backtest-reports**」からダウンロードできます。

### 補足
- シークレットが未設定の場合は、コンパイルだけ行います。
- `MQL5/` を変更してプッシュすると、自動で実行されます。
- シークレットの値は GitHub がログ上で伏せ字にします。テスターの設定ファイル（パスワードを含む）は、実行後に削除します。

---

## 主なパラメータ

| パラメータ | 既定値 | 説明 |
|---|---|---|
| `InpTimeframe` | H1 | 判定に使う時間足 |
| `InpEntryThreshold` | 0.45 | エントリーに必要なスコア |
| `InpRiskPercent` | 1.0 | 1回の許容損失（%） |
| `InpSLATR` / `InpTPATR` | 1.5 / 3.0 | SL/TP の ATR 倍率 |
| `InpMaxDailyLossPct` | 3.0 | 1日の損失上限（%） |
| `InpMaxSpreadPips` | 2.0 | 最大スプレッド |
| `InpHighVolMode` | ロット半分 | 高ボラ時の扱い（停止 / ロット半分） |
| `InpUseTrend` ほか | true | 各ロジックの ON/OFF |
| `InpWTrend_TF` ほか | 上の表 | 相場状況ごとの重み |
| `InpVerbose` | false | 毎バーの判定内容をログに出す（検証用） |

## ファイル構成

```
MQL5/Experts/AdaptiveMultiStrategyEA.mq5   EA 本体（入力パラメータ・売買の流れ・OnTester）
MQL5/Include/AMS/Common.mqh                共通の定義（列挙型・pips 換算など）
MQL5/Include/AMS/Regime.mqh                相場状況の判定
MQL5/Include/AMS/Strategies.mqh            4つの売買ロジック
MQL5/Include/AMS/RiskManager.mqh           ロット計算・建値/トレーリング・決済
MQL5/Include/AMS/TradeFilters.mqh          スプレッド・時間のフィルター
tools/                                     Wine での導入・コンパイル・バックテスト
tester/                                    テスター設定のテンプレート
reports/                                   バックテスト結果
```

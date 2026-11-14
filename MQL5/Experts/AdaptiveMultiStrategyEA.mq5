//+------------------------------------------------------------------+
//|                                     AdaptiveMultiStrategyEA.mq5  |
//|  相場状況（トレンド/レンジ/中立/高ボラ）を判定し、                      |
//|  4つの売買ロジックの重みを切り替えて売買する EA                         |
//|  複数の銘柄を1つのEAで同時に売買できる（InpSymbols）                   |
//+------------------------------------------------------------------+
#property copyright "fxxx"
#property version   "2.00"
#property description "Adaptive Multi-Strategy EA (multi-symbol)"
#property description "相場状況に応じて、トレンドフォロー/ブレイクアウト/逆張り/モメンタムを使い分けます。"
#property description "利益を保証するものではありません。必ずデモ口座で検証してから使ってください。"

#include <Trade\Trade.mqh>
#include <AMS\Common.mqh>
#include <AMS\Regime.mqh>
#include <AMS\Strategies.mqh>
#include <AMS\RiskManager.mqh>
#include <AMS\TradeFilters.mqh>
#include <AMS\Modules.mqh>

//==================================================================
// 入力パラメータ
//==================================================================
input group "=== 基本設定 ==="
input ulong            InpMagic             = 20261112;    // マジックナンバー
input string           InpSymbols           = "USDJPY,EURUSD,GBPJPY,EURJPY,AUDJPY,GBPUSD"; // 取引する銘柄（カンマ区切り。空ならチャートの銘柄のみ）
input ENUM_TIMEFRAMES  InpTimeframe         = PERIOD_H1;   // 判定に使う時間足
input string           InpComment           = "AMS";       // 注文コメントの先頭
input int              InpSlippagePoints    = 20;          // 許容スリッページ（point）
input bool             InpVerbose           = false;       // 毎バーの判定内容をログに出す

input group "=== エントリーの方式 ==="
input ENUM_AMS_ENTRY_MODE InpEntryMode      = ENTRY_WEIGHTED; // エントリーの方式
input int              InpDTEntryDays       = 55;          // [日足トレンド] この本数の高値/安値を抜けたら入る
input int              InpDTExitDays        = 20;          // [日足トレンド] 反対側のこの本数の高値/安値で決済
input int              InpAsiaStartNY       = 19;          // [時間帯] アジア時間の開始（ニューヨーク時間の時）
input int              InpLondonOpenNY      = 3;           // [時間帯] ロンドン開始（ニューヨーク時間の時）
input int              InpLBEntryEndNY      = 7;           // [ロンドンBO] エントリーを受け付ける終了時刻（NY時）
input int              InpLBExitNY          = 12;          // [ロンドンBO] この時刻以降に決済（NY時）
input int              InpAsiaMREndNY       = 1;           // [アジア逆張り] エントリーを受け付ける終了時刻（NY時）
input double           InpPBRsiLow          = 40.0;        // [押し目] RSI がこの値を上に抜けたら買い
input double           InpPBRsiHigh         = 60.0;        // [押し目] RSI がこの値を下に抜けたら売り
input int              InpPBEmaFast         = 50;          // [押し目] 日足EMA（短）
input int              InpPBEmaSlow         = 200;         // [押し目] 日足EMA（長）
input int              InpFixEntryHHMM      = 800;         // [東京仲値] エントリー時刻（東京時間。800 = 8:00）
input int              InpFixExitHHMM       = 955;         // [東京仲値] 決済時刻（東京時間。955 = 9:55）
input bool             InpFixGotobiOnly     = true;        // [東京仲値] ゴトー日（5・10日など）だけ取引する
input int              InpFixDirection      = 1;           // [東京仲値] 1 = 買い / -1 = 売り
input double           InpFixStopPips       = 30.0;        // [東京仲値] SL の幅（pips）
input double           InpFixMaxSpreadPips  = 1.5;         // [東京仲値] スプレッドがこの pips を超えていたら待つ
input string           InpCalendarRules     = "";          // [時刻ルール] "名前:銘柄|時計|HHMM|保有分|BUY/SELL|日の条件|SLpips" を ; で区切る
input string           InpCalendarRules2    = "";          // [時刻ルール] 続き（テスターの入力は1つ255文字までのため、分けて書ける）
input string           InpCalendarRules3    = "";          // [時刻ルール] 続き
input int              InpAdaptWindow       = 0;           // [自動調整] 直近何回の仮想取引の成績で、ルールを止める/再開するか（0で無効）
input int              InpAdaptMinTrades    = 20;          // [自動調整] この回数に満たないルールは止めない
input double           InpAdaptMinPF        = 1.0;         // [自動調整] 直近の PF（コスト後）がこれ未満のルールは止める
input int              InpEntryDelaySec     = 15;          // [時刻ルール] 足の始まりから注文までの待ち（秒）。全銘柄の足がそろってから優先順に注文する
input string           InpJPHolidays        = "";          // [東京仲値] 追加の休業日（例 2027.01.01,2027.01.11。2015〜2026年は内蔵）

input group "=== 相場状況（レジーム）判定 ==="
input int              InpADXPeriod         = 14;          // ADX 期間
input int              InpATRPeriod         = 14;          // ATR 期間
input int              InpRegimeBBPeriod    = 20;          // BB幅 期間
input double           InpRegimeBBDev       = 2.0;         // BB幅 偏差
input int              InpRegimeEMAFast     = 50;          // 方向判定 EMA（短）
input int              InpRegimeEMASlow     = 200;         // 方向判定 EMA（長）
input int              InpRegimeLookback    = 100;         // ATR/BB幅の順位を見る本数
input int              InpSlopeBars         = 5;           // EMAの傾きを見る本数
input double           InpADXTrend          = 25.0;        // ADX がこれ以上でトレンド
input double           InpADXRange          = 22.0;        // ADX がこれ未満でレンジ候補
input double           InpHighVolPct        = 0.90;        // ATR順位がこれ以上で高ボラ（0〜1）
input double           InpRangeBWPct        = 0.60;        // BB幅順位がこれ以下でレンジ候補（0〜1）
input ENUM_AMS_HIGHVOL_MODE InpHighVolMode  = HIGHVOL_HALF; // 高ボラ時の扱い
input bool             InpTradeNeutral      = true;        // 中立相場でも新規エントリーする

input group "=== ロジック1：トレンドフォロー ==="
input bool             InpUseTrend          = true;        // 使う
input int              InpTrendEMAFast      = 20;          // 短期EMA
input int              InpTrendEMASlow      = 50;          // 長期EMA
input bool             InpUseHTFFilter      = true;        // 上位足EMAで方向を確認
input ENUM_TIMEFRAMES  InpHTF               = PERIOD_H4;   // 上位足
input int              InpHTFEMA            = 200;         // 上位足EMA 期間

input group "=== ロジック2：ブレイクアウト ==="
input bool             InpUseBreakout       = true;        // 使う
input int              InpDonchian          = 20;          // 高値/安値を見る本数

input group "=== ロジック3：逆張り ==="
input bool             InpUseMeanRev        = true;        // 使う
input int              InpRSIPeriod         = 14;          // RSI 期間
input double           InpRSILow            = 30.0;        // RSI 売られすぎ
input double           InpRSIHigh           = 70.0;        // RSI 買われすぎ
input int              InpMRBBPeriod        = 20;          // BB 期間
input double           InpMRBBDev           = 2.0;         // BB 偏差

input group "=== ロジック4：モメンタム ==="
input bool             InpUseMomentum       = true;        // 使う
input int              InpMACDFast          = 12;          // MACD 短期
input int              InpMACDSlow          = 26;          // MACD 長期
input int              InpMACDSignal        = 9;           // MACD シグナル
input int              InpStochK            = 14;          // ストキャス %K
input int              InpStochD            = 3;           // ストキャス %D
input int              InpStochSlowing      = 3;           // ストキャス スロー

input group "=== 重み：トレンド相場 ==="
input double           InpWTrend_TF         = 0.50;        // トレンドフォロー
input double           InpWTrend_BO         = 0.30;        // ブレイクアウト
input double           InpWTrend_MR         = 0.00;        // 逆張り
input double           InpWTrend_MO         = 0.20;        // モメンタム

input group "=== 重み：レンジ相場 ==="
input double           InpWRange_TF         = 0.00;        // トレンドフォロー
input double           InpWRange_BO         = 0.00;        // ブレイクアウト
input double           InpWRange_MR         = 0.80;        // 逆張り
input double           InpWRange_MO         = 0.20;        // モメンタム

input group "=== 重み：中立（高ボラ時も使用） ==="
input double           InpWNeutral_TF       = 0.30;        // トレンドフォロー
input double           InpWNeutral_BO       = 0.25;        // ブレイクアウト
input double           InpWNeutral_MR       = 0.15;        // 逆張り
input double           InpWNeutral_MO       = 0.30;        // モメンタム

input group "=== エントリー/決済 ==="
input double           InpEntryThreshold    = 0.45;        // 合計スコアがこれ以上でエントリー（0〜1）
input bool             InpCloseOnOpposite   = true;        // 逆方向のシグナルで決済
input int              InpMaxPositions      = 6;           // 全銘柄合計の最大ポジション数
input int              InpMaxPerSymbol      = 1;           // 1銘柄あたりの最大ポジション数（分けた注文は1つと数える）
input bool             InpSplitOrders       = true;        // 1回の注文の上限を超えるロットは、分けて注文する（複利で残高が大きくなったとき用）
input bool             InpExportDeals       = false;       // バックテストの終わりに、全取引を AMS_bt_deals.csv に書き出す（実運用との突き合わせ用）

input group "=== 資金管理 ==="
input double           InpRiskPercent       = 3.0;         // 1回の許容損失（有効証拠金の%）
input bool             InpAllowMinLot       = false;       // 計算ロットが最小未満なら最小ロットで入る
input double           InpSLATR             = 2.0;         // SL = ATR × この値
input double           InpTPATR             = 2.0;         // TP = ATR × この値（0でTPなし）
input double           InpBETriggerATR      = 0.5;         // 含み益が ATR×この値 で建値へ（0で無効）
input double           InpBEOffsetPips      = 0.5;         // 建値ストップの上乗せ（pips）
input double           InpTrailStartATR     = 1.5;         // 含み益が ATR×この値 でトレーリング開始
input double           InpTrailDistATR      = 1.0;         // トレーリング幅 ATR×この値（0で無効）
input double           InpTrailStepPips     = 1.0;         // SLを動かす最小幅（pips）
input double           InpMaxDailyLossPct   = 15.0;        // 1日の損失上限（%、0で無効）
input double           InpDDRiskCutPct      = 0.0;         // 最高値からの下落がこの%を超えているあいだは、リスクを下の倍率にする（0で無効）
input double           InpDDRiskMul         = 0.5;         // 上の条件のときのリスクの倍率
input double           InpMonthTargetPct    = 0.0;         // [月間目標] その月の利益（月初の残高比）がこの%に届いたら、月末までリスクを下げる（0で無効）
input double           InpMonthLockMul      = 0.0;         // [月間目標] 届いた後のリスクの倍率（0 = その月は新規エントリーをしない）
input double           InpMaxDDStopPct      = 50.0;        // 最高値からの下落がこの%を超えたら全決済して停止（0で無効）
input double           InpMaxMarginUsePct   = 40.0;        // 必要証拠金の合計の上限（有効証拠金の%。強制ロスカット防止）
input double           InpMinLevelAfterSL   = 150.0;       // すべての建玉が損切りに達しても残す証拠金維持率（%。OANDA のロスカットは100%）

input group "=== フィルター ==="
input double           InpMaxSpreadATR      = 0.25;        // スプレッドが ATR×この値を超えたら見送り（0で無効）
input int              InpStartHour         = 0;           // 取引開始（サーバー時間）
input int              InpEndHour           = 0;           // 取引終了（開始と同じなら終日）
input int              InpFridayCloseMin    = 120;         // 金曜の取引終了の何分前に全決済するか（セッション情報から判定。0で無効）
input int              InpFridayCloseHour   = 22;          // 金曜この時刻以降は全決済（セッション情報が無いときの予備。-1で無効）
input int              InpMondayStartHour   = 2;           // 月曜この時刻までは新規なし（0で無効）
input int              InpSessionEdgeMin    = 15;          // 取引開始直後・終了直前のこの分数は新規なし（ロールオーバー時のスプレッド拡大を避ける。0で無効）

input group "=== 実運用向け ==="
input int              InpOrderRetries      = 3;           // 注文が一時的なエラーで失敗したときの再試行回数
input bool             InpUseTimer          = true;        // 実運用時、タイマーでも全銘柄を処理する（チャート銘柄のティックが止まっても動く）

input group "=== バックテストの評価 ==="
input int              InpScoreMinTrades    = 20;          // 評価値を出す最低取引数
input double           InpScoreMaxDD        = 60.0;        // 最大DD（%）がこれを超えたら評価値 0

//==================================================================
// 銘柄ごとの売買
//==================================================================
CTrade g_trade;
double g_weights[4][AMS_STRATEGY_COUNT];   // [REGIME][STRATEGY]
double g_peakEquity = 0.0;
double g_monthStartBal = 0.0;   // 月初の残高（月間目標の判定用）
int    g_monthKey      = 0;     // いまの月（YYYYMM、サーバー時間）
int    g_sigLock       = 0;     // 月間目標に届いたため見送ったシグナルの数

//+------------------------------------------------------------------+
//| その月の損益率（%、月初の残高比。含み損益も含める）                     |
//+------------------------------------------------------------------+
double MonthToDatePct(void)
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   const int key = dt.year * 100 + dt.mon;
   if(key != g_monthKey || g_monthStartBal <= 0.0)
     {
      g_monthKey      = key;
      g_monthStartBal = AccountInfoDouble(ACCOUNT_BALANCE);
     }
   return(g_monthStartBal > 0.0 ? (AccountInfoDouble(ACCOUNT_EQUITY) / g_monthStartBal - 1.0) * 100.0 : 0.0);
  }

//+------------------------------------------------------------------+
//| 実運用：状態（最高値・停止・月初の残高）をファイルに保存／読み込み。       |
//| ターミナルを入れ直した環境（GitHub Actions など）でも引き継ぐため、       |
//| 共通フォルダに置く                                                    |
//+------------------------------------------------------------------+
string StateFile(void) { return(StringFormat("AMS_state_%I64d.csv", AccountInfoInteger(ACCOUNT_LOGIN))); }

void SaveState(void)
  {
   const int fh = FileOpen(StateFile(), FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fh == INVALID_HANDLE)
      return;
   FileWrite(fh, DoubleToString(g_peakEquity, 2), g_halted ? 1 : 0, g_monthKey, DoubleToString(g_monthStartBal, 2));
   FileClose(fh);
  }

void LoadState(void)
  {
   const int fh = FileOpen(StateFile(), FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fh == INVALID_HANDLE)
      return;
   const double peak  = StringToDouble(FileReadString(fh));
   const int    halt  = (int)StringToInteger(FileReadString(fh));
   const int    mkey  = (int)StringToInteger(FileReadString(fh));
   const double mbal  = StringToDouble(FileReadString(fh));
   FileClose(fh);
   g_peakEquity = MathMax(g_peakEquity, peak);
   if(halt > 0)
      g_halted = true;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(mkey == dt.year * 100 + dt.mon && mbal > 0.0)
     {
      g_monthKey      = mkey;
      g_monthStartBal = mbal;
     }
   PrintFormat("[AMS] 状態を読み込みました：最高値 %.0f、停止 %s、月初の残高 %.0f（%d）", g_peakEquity, g_halted ? "あり" : "なし",
               g_monthStartBal, g_monthKey);
  }

//+------------------------------------------------------------------+
//| 実運用：取引の記録と口座の状態を CSV に書き出す（成績の確認用）          |
//+------------------------------------------------------------------+
void WriteDeals(const string file, const datetime from)
  {
   if(!HistorySelect(from, TimeCurrent() + 86400))
      return;
   const int fh = FileOpen(file, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fh != INVALID_HANDLE)
     {
      FileWrite(fh, "time", "symbol", "entry", "type", "volume", "price", "profit", "comment", "position");
      const int total = HistoryDealsTotal();
      for(int i = 0; i < total; i++)
        {
         const ulong d = HistoryDealGetTicket(i);
         if(d == 0 || (ulong)HistoryDealGetInteger(d, DEAL_MAGIC) != InpMagic)
            continue;
         const double pl = HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_SWAP) + HistoryDealGetDouble(d, DEAL_COMMISSION);
         FileWrite(fh, TimeToString((datetime)HistoryDealGetInteger(d, DEAL_TIME), TIME_DATE | TIME_SECONDS),
                   HistoryDealGetString(d, DEAL_SYMBOL), (int)HistoryDealGetInteger(d, DEAL_ENTRY),
                   (int)HistoryDealGetInteger(d, DEAL_TYPE), DoubleToString(HistoryDealGetDouble(d, DEAL_VOLUME), 2),
                   DoubleToString(HistoryDealGetDouble(d, DEAL_PRICE), 5), DoubleToString(pl, 0),
                   HistoryDealGetString(d, DEAL_COMMENT), (long)HistoryDealGetInteger(d, DEAL_POSITION_ID));
        }
      FileClose(fh);
     }
  }

//+------------------------------------------------------------------+
//| 実運用：取引の記録と口座の状態を書き出す                               |
//+------------------------------------------------------------------+
void ExportLive(void)
  {
   WriteDeals("AMS_live_deals.csv", TimeCurrent() - 400 * 86400);
   //--- 口座の状態は追記していく（残高の推移を見るため）
   const int fa = FileOpen("AMS_live_account.csv", FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fa != INVALID_HANDLE)
     {
      FileSeek(fa, 0, SEEK_END);
      FileWrite(fa, TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS), DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 0),
                DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 0), DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_LEVEL), 0),
                PositionsTotal());
      FileClose(fa);
     }
  }
bool   g_stopOut    = false;   // バックテスト中に強制ロスカットがあったか
bool   g_halted     = false;
int    g_sigTotal   = 0;       // 注文を試みる対象になったシグナルの数
int    g_sigSpread  = 0;       // スプレッドが広いまま期限切れになり、見送ったシグナルの数
int    g_sigOther   = 0;       // その他の理由（取引時間外・上限など）で見送ったシグナルの数

int CountAllPositions(void);

class CSymbolTrader
  {
public:
   string            symbol;
   CRegimeDetector   regime;
   CStrategySet      strategies;
   CRiskManager      risk;
   CModuleSet        modules;         // 単独検証用のエントリー方式
   datetime          lastBar;
   double            lastATR;
   datetime          lastCloseTry;    // 決済を最後に試みた時刻（失敗時の連続リトライを抑える）

   //--- 保留中のエントリー（スプレッド拡大など一時的な理由で入れないとき、少し待って再試行する）
   int               pendDir;         // +1 買い / -1 売り / 0 なし
   ENUM_AMS_REGIME   pendReg;
   string            pendTag;
   double            pendMul;
   double            pendSLPips;      // 固定の SL（pips）。0 なら ATR で決める
   datetime          pendUntil;       // この時刻を過ぎたら古いシグナルとして捨てる
   bool              pendSpreadWait;  // スプレッドが広くて待っているか（見送りの集計用）
   datetime          lastEntryTry;
   bool              noLots;          // 直前の Open が「証拠金の余裕がなくロット0」で見送ったか
   int               pendPrio;        // 保留中のシグナルの優先順位（時刻ルール。小さいほど先）
   datetime          pendBarTime;     // 保留中のシグナルを出した足の始まり

   //--- 保留中の決済（日付の変わり目など、市場が閉じていて決済できないときに再試行する）
   bool              pendCloseBuy;
   bool              pendCloseSell;
   string            pendCloseReason;
   datetime          lastExitTry;

                     CSymbolTrader(void) : symbol(""), lastBar(0), lastATR(0.0), lastCloseTry(0),
                                           pendDir(0), pendReg(REGIME_NEUTRAL), pendTag(""), pendMul(1.0), pendSLPips(0.0),
                                           pendSpreadWait(false),
                                           pendUntil(0), lastEntryTry(0), noLots(false), pendPrio(1000000), pendBarTime(0),
                                           pendCloseBuy(false), pendCloseSell(false), pendCloseReason(""),
                                           lastExitTry(0) {}

   bool              Init(const string sym);
   void              Release(void) { regime.Release(); strategies.Release(); modules.Release(); }
   void              OnTick(void);       // 段階1：週末前の決済・新しい足の判定・決済
   void              OnTickEnter(void);  // 段階2：新規注文・ストップの管理（全銘柄の決済が済んでから）
   int               PendingPrio(void) const { return(pendDir != 0 ? pendPrio : 1000000); }
   int               AdaptSkips(void) const { return(modules.AdaptSkips()); }
   void              AdaptiveReport(void) const { modules.AdaptiveReport(); }
   void              CloseAll(const string reason) { g_trade.SetTypeFillingBySymbol(symbol); risk.CloseAll(reason); }
   bool              WeekendCloseTime(void);

private:
   bool              IsNewBar(void);
   void              OnBar(void);
   double            CalcScore(const ENUM_AMS_REGIME reg, const double &signals[], int &dominant);
   void              TryEnter(void);
   void              TryClose(void);
   void              RequestClose(const ENUM_POSITION_TYPE type, const string reason);
   bool              Open(const ENUM_ORDER_TYPE type, const ENUM_AMS_REGIME reg, const string tag, const double riskMul);
  };

//+------------------------------------------------------------------+
bool CSymbolTrader::Init(const string sym)
  {
   symbol = sym;
   if(!regime.Init(sym, InpTimeframe, InpADXPeriod, InpATRPeriod,
                   InpRegimeBBPeriod, InpRegimeBBDev, InpRegimeEMAFast, InpRegimeEMASlow,
                   InpRegimeLookback, InpSlopeBars, InpADXTrend, InpADXRange,
                   InpHighVolPct, InpRangeBWPct))
      return(false);
   if(!strategies.Init(sym, InpTimeframe, InpTrendEMAFast, InpTrendEMASlow,
                       InpHTF, InpHTFEMA, InpUseHTFFilter, InpDonchian,
                       InpRSIPeriod, InpRSILow, InpRSIHigh, InpMRBBPeriod, InpMRBBDev,
                       InpMACDFast, InpMACDSlow, InpMACDSignal,
                       InpStochK, InpStochD, InpStochSlowing))
      return(false);
   risk.Init(sym, InpMagic, GetPointer(g_trade), InpRiskPercent, InpMaxDailyLossPct, InpAllowMinLot,
             InpMaxMarginUsePct, InpMinLevelAfterSL);
   risk.SetSplitOrders(InpSplitOrders);
   if(InpEntryMode != ENTRY_WEIGHTED)
     {
      if(!modules.Init(sym, InpTimeframe, InpEntryMode, InpDTEntryDays, InpDTExitDays,
                       InpAsiaStartNY, InpLondonOpenNY, InpLBEntryEndNY, InpLBExitNY, InpAsiaMREndNY,
                       InpRSIPeriod, InpPBRsiLow, InpPBRsiHigh, InpPBEmaFast, InpPBEmaSlow))
         return(false);
      modules.SetTokyoFix(InpFixEntryHHMM, InpFixExitHHMM, InpFixGotobiOnly, InpFixDirection);
      modules.AddHolidays(InpJPHolidays);
      if(InpEntryMode == ENTRY_CALENDAR && modules.SetRules(InpCalendarRules + "/" + InpCalendarRules2 + "/" + InpCalendarRules3) == 0)
        {
         PrintFormat("[AMS] %s に当てはまる時刻ルールがないため、この銘柄は取引しません", sym);
         return(false);
        }
      modules.SetAdaptive(InpEntryMode == ENTRY_CALENDAR ? InpAdaptWindow : 0, InpAdaptMinTrades, InpAdaptMinPF);
      //--- 時間帯の基準（確認用）：この時刻をニューヨーク 17:00 として扱う
      const int tod = modules.OpenTOD();
      if(tod >= 0)
         PrintFormat("[AMS] %s 週明けの最初の足=サーバー時間 %02d:%02d（NY 17:00 として扱う） いまの東京時間=%s",
                     sym, tod / 3600, (tod % 3600) / 60, TimeToString(modules.TokyoTime(TimeCurrent())));
      else
         PrintFormat("[AMS] %s 週明けの最初の足を特定できません（時間帯を使うロジックは動きません）", sym);
     }
   //--- 起動した時点の足は処理済みとして扱う（EAの再起動直後に、足の途中で飛び乗らないため）
   lastBar = iTime(sym, InpTimeframe, 0);
   return(true);
  }

//+------------------------------------------------------------------+
//| 週末前の決済時刻か。銘柄のセッション情報を優先し、無ければ時刻指定を使う   |
//+------------------------------------------------------------------+
bool CSymbolTrader::WeekendCloseTime(void)
  {
   if(IsBeforeWeekendClose(symbol, InpFridayCloseMin))
      return(true);
   return(IsFridayCloseTime(InpFridayCloseHour));
  }

//+------------------------------------------------------------------+
bool CSymbolTrader::IsNewBar(void)
  {
   const datetime t = iTime(symbol, InpTimeframe, 0);
   if(t == 0 || t == lastBar)
      return(false);
   lastBar = t;
   return(true);
  }

//+------------------------------------------------------------------+
void CSymbolTrader::OnTick(void)
  {
   g_trade.SetTypeFillingBySymbol(symbol);

   //--- 週末前は全決済（失敗した場合は10秒おきに再試行）
   if(WeekendCloseTime() && TimeCurrent() - lastCloseTry >= 10)
     {
      int b = 0, s = 0;
      if(risk.CountPositions(b, s) > 0)
        {
         lastCloseTry = TimeCurrent();
         risk.CloseAll("週末前クローズ");
        }
     }

   if(IsNewBar())
      OnBar();
   if(pendCloseBuy || pendCloseSell)
      TryClose();
  }

//+------------------------------------------------------------------+
//| 段階2：新規注文とストップの管理。                                     |
//| 同じ時刻に、別の銘柄の決済と新規が重なる場合（例：9:55 に EURJPY を決済し  |
//| USDJPY を新規）、先に全銘柄の決済を済ませてから証拠金を計算するため、      |
//| ProcessAll で全銘柄の OnTick のあとに呼ぶ。                            |
//+------------------------------------------------------------------+
void CSymbolTrader::OnTickEnter(void)
  {
   g_trade.SetTypeFillingBySymbol(symbol);
   if(pendDir != 0)
      TryEnter();

   //--- 再起動直後など ATR が未取得のときは取得する（保有ポジションの建値/トレーリングを止めないため）
   if(lastATR <= 0.0)
     {
      ENUM_AMS_REGIME tmp = REGIME_NEUTRAL;
      if(regime.Detect(tmp))
         lastATR = regime.ATR();
     }

   risk.ManageStops(lastATR, InpBETriggerATR, InpBEOffsetPips,
                    InpTrailStartATR, InpTrailDistATR, InpTrailStepPips);
  }

//+------------------------------------------------------------------+
double CSymbolTrader::CalcScore(const ENUM_AMS_REGIME reg, const double &signals[], int &dominant)
  {
   double sum = 0.0, wsum = 0.0, best = 0.0;
   dominant = -1;
   for(int s = 0; s < AMS_STRATEGY_COUNT; s++)
     {
      const double w = g_weights[reg][s];
      if(w <= 0.0)
         continue;
      wsum += w;
      sum  += w * signals[s];
     }
   if(wsum <= 0.0)
      return(0.0);
   const double score = sum / wsum;
   for(int s = 0; s < AMS_STRATEGY_COUNT; s++)
     {
      const double contrib = g_weights[reg][s] * signals[s];
      if(contrib * score > 0.0 && MathAbs(contrib) > best)
        {
         best     = MathAbs(contrib);
         dominant = s;
        }
     }
   return(score);
  }

//+------------------------------------------------------------------+
//| 新しい足ができたときの判定と売買                                      |
//+------------------------------------------------------------------+
void CSymbolTrader::OnBar(void)
  {
   risk.UpdateDay();
   pendDir = 0;   // 前の足のシグナルは持ち越さない

   ENUM_AMS_REGIME reg = REGIME_NEUTRAL;
   if(!regime.Detect(reg))
      return;
   lastATR = regime.ATR();

   double signals[];
   if(!strategies.Evaluate(signals))
      return;

   int buys = 0, sells = 0;
   risk.CountPositions(buys, sells);

   double score     = 0.0;
   double threshold = InpEntryThreshold;
   string tag       = "";
   if(InpEntryMode == ENTRY_WEIGHTED)
     {
      int dominant = -1;
      score = CalcScore(reg, signals, dominant);
      tag   = StrategyShortName(dominant);
     }
   else
     {
      //--- 単独検証用の方式：ロジックごとの決済条件を先に確認する
      if(buys > 0 && modules.ExitSignal(POSITION_TYPE_BUY))
         RequestClose(POSITION_TYPE_BUY, "ロジックの決済条件");
      if(sells > 0 && modules.ExitSignal(POSITION_TYPE_SELL))
         RequestClose(POSITION_TYPE_SELL, "ロジックの決済条件");
      score     = modules.EntrySignal(signals[STRAT_MEANREV]);
      threshold = 0.5;
      tag       = EntryModeShortName(InpEntryMode);
      if(InpEntryMode == ENTRY_CALENDAR && score != 0.0)
         tag = modules.PendingRuleName();
     }

   if(InpVerbose)
      PrintFormat("[AMS] %s %s regime=%s ADX=%.1f ATR%%=%.2f BW%%=%.2f | TF=%.1f BO=%.1f MR=%.1f MO=%.1f | score=%.2f",
                  symbol, TimeToString(iTime(symbol, InpTimeframe, 1)), RegimeShortName(reg),
                  regime.ADX(), regime.ATRPct(), regime.BWPct(),
                  signals[STRAT_TREND], signals[STRAT_BREAKOUT], signals[STRAT_MEANREV],
                  signals[STRAT_MOMENTUM], score);

   //--- 逆方向のシグナルで決済
   if(InpCloseOnOpposite)
     {
      if(score <= -threshold && buys > 0)
         RequestClose(POSITION_TYPE_BUY, "逆シグナル");
      if(score >= threshold && sells > 0)
         RequestClose(POSITION_TYPE_SELL, "逆シグナル");
     }

   //--- 新規エントリーのシグナルがあるか
   if(g_halted || MathAbs(score) < threshold)
      return;
   if(InpEntryMode == ENTRY_WEIGHTED && reg == REGIME_NEUTRAL && !InpTradeNeutral)
      return;

   double riskMul = 1.0;
   if(reg == REGIME_HIGHVOL)
     {
      if(InpHighVolMode == HIGHVOL_BLOCK)
         return;
      riskMul = 0.5;
     }

   //--- シグナルを保留にして、入れる状態になりしだい注文する。
   //    足の確定から「足の長さの1/4」を過ぎたら、古いシグナルとして捨てる。
   pendDir   = (score > 0.0) ? 1 : -1;
   pendReg   = reg;
   pendTag   = tag;
   pendMul   = riskMul;
   pendUntil = iTime(symbol, InpTimeframe, 0) + PeriodSeconds(InpTimeframe) / 4;
   pendSpreadWait = false;
   pendPrio       = (InpEntryMode == ENTRY_CALENDAR) ? modules.PendingRulePrio() : 1000000;
   pendBarTime    = iTime(symbol, InpTimeframe, 0);
   pendSLPips     = (InpEntryMode == ENTRY_CALENDAR) ? modules.PendingRuleSL()
                    : ((InpEntryMode == ENTRY_TOKYO_FIX) ? InpFixStopPips : 0.0);
   g_sigTotal++;
  }

//+------------------------------------------------------------------+
//| 保留中のシグナルで注文を試みる                                        |
//|  - もう入るべきでない条件（期限切れ・週末前・上限超過など）なら捨てる      |
//|  - 一時的な条件（スプレッド拡大・取引開始直後・接続切れ）なら待つ          |
//+------------------------------------------------------------------+
void CSymbolTrader::TryEnter(void)
  {
   if(pendDir == 0)
      return;
   if(g_halted || TimeCurrent() > pendUntil || WeekendCloseTime() ||
      !WithinTradingHours(InpStartHour, InpEndHour) || risk.DailyLossHit())
     {
      string why = "";
      if(g_halted)                                         why = "停止中";
      else if(TimeCurrent() > pendUntil && pendSpreadWait) why = "スプレッド拡大のまま期限切れ";
      else if(TimeCurrent() > pendUntil && noLots)         why = "証拠金の余裕がないまま期限切れ";
      else if(TimeCurrent() > pendUntil)                   why = "期限切れ";
      else if(WeekendCloseTime())                          why = "週末前";
      else if(!WithinTradingHours(InpStartHour, InpEndHour)) why = "取引時間外";
      else                                                 why = "日次損失の上限";
      PrintFormat("[AMS] 見送り %s [%s] 理由=%s", symbol, pendTag, why);
      if(pendSpreadWait && TimeCurrent() > pendUntil)
         g_sigSpread++;
      else
         g_sigOther++;
      pendDir = 0;
      noLots  = false;
      return;
     }
   //--- 決済待ちのポジションがあるあいだは、新規エントリーを待つ
   if(pendCloseBuy || pendCloseSell)
      return;
   int buys = 0, sells = 0;
   risk.CountPositions(buys, sells);
   if(buys + sells >= InpMaxPerSymbol || CountAllPositions() >= InpMaxPositions ||
      (pendDir > 0 && buys > 0) || (pendDir < 0 && sells > 0))
     {
      PrintFormat("[AMS] 見送り %s [%s] 理由=建玉あり（この銘柄 %d / 全体 %d）", symbol, pendTag, buys + sells, CountAllPositions());
      pendDir = 0;
      return;
     }

   //--- ここから下は一時的な条件。満たされるまで待つ
   if(IsMondayOpenGap(InpMondayStartHour))
      return;
   string why = "";
   if(!CanTradeNow(symbol, why))
      return;
   //--- 取引開始直後・終了直前（ロールオーバー前後）はスプレッドが広がりやすい
   if(InpSessionEdgeMin > 0)
     {
      const int toEnd = SecondsToSessionEnd(symbol), fromStart = SecondsFromSessionStart(symbol);
      if(toEnd < InpSessionEdgeMin * 60 || fromStart < InpSessionEdgeMin * 60)
         return;
     }
   const double spread = SymbolInfoDouble(symbol, SYMBOL_ASK) - SymbolInfoDouble(symbol, SYMBOL_BID);
   if(InpEntryMode == ENTRY_TOKYO_FIX || InpEntryMode == ENTRY_CALENDAR)
     {
      //--- 短い時間足の ATR は小さすぎて基準にならないので、pips で上限を決める
      if(InpFixMaxSpreadPips > 0.0 && spread > InpFixMaxSpreadPips * PipSize(symbol))
        {
         pendSpreadWait = true;
         return;
        }
     }
   else
      if(InpMaxSpreadATR > 0.0 && lastATR > 0.0 && spread > lastATR * InpMaxSpreadATR)
        {
         pendSpreadWait = true;
         return;
        }
   pendSpreadWait = false;
   //--- 時刻ルール：同じ時刻に複数の銘柄のルールが出る場合、ティックの届く順番に左右されないよう、
   //    全銘柄の足がそろうまで少し待ってから、優先順位の順に注文する（ProcessAll で並べ替える）
   if(InpEntryMode == ENTRY_CALENDAR && InpEntryDelaySec > 0 && TimeCurrent() < pendBarTime + InpEntryDelaySec)
      return;
   //--- 優先順位の高いルールが保留中（スプレッドの戻り待ちなど）のあいだは、低いルールは待つ
   //    （先に入ると、高いルールの証拠金の余裕を使ってしまうため）
   if(InpEntryMode == ENTRY_CALENDAR && pendPrio > g_minPendPrio)
      return;
   if(TimeCurrent() - lastEntryTry < 5)
      return;
   lastEntryTry = TimeCurrent();

   const int dir = pendDir;
   pendDir = 0;   // 注文は1回だけ試みる（Open の中で、一時的なエラーには再試行する）
   noLots  = false;
   //--- 最高値から大きく下落しているあいだは、リスクを小さくする（DD を深くしないため）
   double mul = pendMul;
   if(InpDDRiskCutPct > 0.0 && g_peakEquity > 0.0 &&
      AccountInfoDouble(ACCOUNT_EQUITY) < g_peakEquity * (1.0 - InpDDRiskCutPct / 100.0))
      mul *= InpDDRiskMul;
   //--- 月間目標：その月の利益が目標に届いたら、月末までリスクを下げる（または新規をやめる）。利益を守るため
   if(InpMonthTargetPct > 0.0 && MonthToDatePct() >= InpMonthTargetPct)
     {
      if(InpMonthLockMul <= 0.0)
        {
         g_sigLock++;
         return;
        }
      mul *= InpMonthLockMul;
     }
   if(Open(dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, pendReg, pendTag, mul))
     {
      if(InpEntryMode != ENTRY_WEIGHTED)
         modules.MarkEntered();
     }
   else
      if(noLots)
         pendDir = dir;   // 証拠金の余裕がないだけなら、ほかの決済を待って期限まで再試行する（期限切れは skip_other）
  }

//+------------------------------------------------------------------+
//| 決済を依頼する。実際の決済は TryClose が、できる状態になりしだい行う       |
//+------------------------------------------------------------------+
void CSymbolTrader::RequestClose(const ENUM_POSITION_TYPE type, const string reason)
  {
   if(type == POSITION_TYPE_BUY)
      pendCloseBuy = true;
   else
      pendCloseSell = true;
   pendCloseReason = reason;
   lastExitTry     = 0;
  }

//+------------------------------------------------------------------+
//| 保留中の決済を行う。                                                |
//|  日足の変わり目（ロールオーバー）は数分間市場が閉じるので、               |
//|  閉じているあいだは待ち、失敗したら10秒おきに再試行する。                 |
//+------------------------------------------------------------------+
void CSymbolTrader::TryClose(void)
  {
   int buys = 0, sells = 0;
   risk.CountPositions(buys, sells);
   if(buys == 0)
      pendCloseBuy = false;
   if(sells == 0)
      pendCloseSell = false;
   if(!pendCloseBuy && !pendCloseSell)
      return;
   if(SecondsToSessionEnd(symbol) < 0)          // 取引時間外
      return;
   if(TimeCurrent() - lastExitTry < 10)
      return;
   lastExitTry = TimeCurrent();
   if(pendCloseBuy && risk.CloseDirection(POSITION_TYPE_BUY, pendCloseReason))
      pendCloseBuy = false;
   if(pendCloseSell && risk.CloseDirection(POSITION_TYPE_SELL, pendCloseReason))
      pendCloseSell = false;
  }

//+------------------------------------------------------------------+
bool CSymbolTrader::Open(const ENUM_ORDER_TYPE type, const ENUM_AMS_REGIME reg,
                         const string tag, const double riskMul)
  {
   const double atr = lastATR;
   if(atr <= 0.0)
      return(false);

   const int    digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   const bool   isBuy  = (type == ORDER_TYPE_BUY);
   const string comment = StringFormat("%s|%s|%s|%s", InpComment, symbol, RegimeShortName(reg), tag);
   g_trade.SetTypeFillingBySymbol(symbol);

   //--- リクオートなどの一時的なエラーは、価格を取り直して再試行する
   const int attempts = MathMax(InpOrderRetries, 0) + 1;
   for(int a = 0; a < attempts; a++)
     {
      MqlTick tick;
      if(!SymbolInfoTick(symbol, tick))
         return(false);
      const double entry = isBuy ? tick.ask : tick.bid;
      //--- 東京仲値は保有時間が短く決まっているので、SL は固定の pips、TP なし（時刻で決済）
      const bool   fixMode = (pendSLPips > 0.0);
      const double slDist  = fixMode ? pendSLPips * PipSize(symbol) : atr * InpSLATR;
      double sl = isBuy ? entry - slDist : entry + slDist;
      double tp = 0.0;
      if(InpTPATR > 0.0 && !fixMode)
         tp = isBuy ? entry + atr * InpTPATR : entry - atr * InpTPATR;
      if(!risk.AdjustStops(type, entry, sl, tp))
         return(false);

      const double lots = risk.CalcLots(type, entry, sl, riskMul);
      if(lots <= 0.0)
        {
         noLots = true;
         if(InpVerbose)
            PrintFormat("[AMS] %s ロットが最小ロット未満（または証拠金不足）のため見送り", symbol);
         return(false);
        }

      //--- 1回の注文の上限を超える分は、残りを分けて注文する（最初の1本が通ったら成功とみなす）
      const double maxLot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      const double first  = (maxLot > 0.0 && lots > maxLot) ? maxLot : lots;
      const bool sent = isBuy ? g_trade.Buy(first, symbol, entry, sl, tp, comment)
                              : g_trade.Sell(first, symbol, entry, sl, tp, comment);
      const uint rc = g_trade.ResultRetcode();
      if(sent && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED || rc == TRADE_RETCODE_DONE_PARTIAL))
        {
         double rest = lots - first;
         int    parts = 1;
         while(rest > 1e-9 && parts < 50)
           {
            const double v = risk.NormalizeVolume(MathMin(rest, maxLot));
            if(v <= 0.0)
               break;
            MqlTick t2;
            SymbolInfoTick(symbol, t2);
            const bool ok = isBuy ? g_trade.Buy(v, symbol, t2.ask, sl, tp, comment)
                                  : g_trade.Sell(v, symbol, t2.bid, sl, tp, comment);
            if(!ok)
              {
               PrintFormat("[AMS] 分けた注文の %d 本目が失敗 %s %.2f lot retcode=%u", parts + 1, symbol, v, g_trade.ResultRetcode());
               break;
              }
            rest -= v;
            parts++;
           }
         if(parts > 1)
            PrintFormat("[AMS] %s 合計 %.2f lot を %d 本に分けて注文（1回の上限 %.2f lot）", symbol, lots - rest, parts, maxLot);
         //--- 実際の約定価格と、注文時の価格とのずれ（スリッページ）を記録する
         const double fill = g_trade.ResultPrice();
         const double slip = (fill > 0.0) ? (isBuy ? fill - entry : entry - fill) / PipSize(symbol) : 0.0;
         PrintFormat("[AMS] %s %s %.2f lot @%s SL=%s TP=%s ずれ=%+.1fpips [%s]", symbol, isBuy ? "BUY" : "SELL", lots,
                     DoubleToString(fill > 0.0 ? fill : entry, digits), DoubleToString(sl, digits),
                     DoubleToString(tp, digits), slip, comment);
         return(true);
        }

      const bool transient = (rc == TRADE_RETCODE_REQUOTE || rc == TRADE_RETCODE_PRICE_CHANGED ||
                              rc == TRADE_RETCODE_PRICE_OFF || rc == TRADE_RETCODE_TIMEOUT ||
                              rc == TRADE_RETCODE_CONNECTION || rc == TRADE_RETCODE_TOO_MANY_REQUESTS);
      PrintFormat("[AMS] 注文失敗 %s %s %.2f lot retcode=%u %s（%d/%d 回目）", symbol, isBuy ? "BUY" : "SELL", lots,
                  rc, g_trade.ResultRetcodeDescription(), a + 1, attempts);
      if(!transient)
         return(false);
      if(!MQLInfoInteger(MQL_TESTER))
         Sleep(500);
     }
   return(false);
  }

//==================================================================
// グローバル
//==================================================================
CSymbolTrader *g_traders[];
int            g_minPendPrio = 1000000;   // 保留中のシグナルのうち、最も高い優先順位（時刻ルール）

//+------------------------------------------------------------------+
int CountAllPositions(void)
  {
   //--- 分けて注文した建玉は1つと数えるため、建玉のある銘柄の数を返す
   string seen[];
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      const string sym = PositionGetString(POSITION_SYMBOL);
      bool dup = false;
      for(int k = 0; k < n; k++)
         if(seen[k] == sym)
            dup = true;
      if(dup)
         continue;
      ArrayResize(seen, n + 1);
      seen[n++] = sym;
     }
   return(n);
  }

//+------------------------------------------------------------------+
bool ValidateInputs(void)
  {
   if(InpRiskPercent <= 0.0 || InpRiskPercent > 20.0)
     {
      Print("[AMS] InpRiskPercent は 0 より大きく 20 以下にしてください");
      return(false);
     }
   if(InpSLATR <= 0.0)
     {
      Print("[AMS] InpSLATR は 0 より大きくしてください");
      return(false);
     }
   if(InpEntryThreshold <= 0.0 || InpEntryThreshold > 1.0)
     {
      Print("[AMS] InpEntryThreshold は 0 より大きく 1 以下にしてください");
      return(false);
     }
   if(InpMaxMarginUsePct <= 0.0 || InpMaxMarginUsePct > 90.0)
     {
      Print("[AMS] InpMaxMarginUsePct は 0 より大きく 90 以下にしてください");
      return(false);
     }
   if(InpMaxPositions < 1 || InpMaxPerSymbol < 1)
     {
      Print("[AMS] InpMaxPositions / InpMaxPerSymbol は 1 以上にしてください");
      return(false);
     }
   if(InpStartHour < 0 || InpStartHour > 23 || InpEndHour < 0 || InpEndHour > 23)
     {
      Print("[AMS] 取引時間は 0〜23 で指定してください");
      return(false);
     }
   if(!InpUseTrend && !InpUseBreakout && !InpUseMeanRev && !InpUseMomentum)
     {
      Print("[AMS] 少なくとも1つのロジックを有効にしてください");
      return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
void BuildWeights(void)
  {
   bool   use[AMS_STRATEGY_COUNT];
   double trend[AMS_STRATEGY_COUNT], range[AMS_STRATEGY_COUNT], neutral[AMS_STRATEGY_COUNT];

   use[STRAT_TREND]    = InpUseTrend;     trend[STRAT_TREND]    = InpWTrend_TF;
   use[STRAT_BREAKOUT] = InpUseBreakout;  trend[STRAT_BREAKOUT] = InpWTrend_BO;
   use[STRAT_MEANREV]  = InpUseMeanRev;   trend[STRAT_MEANREV]  = InpWTrend_MR;
   use[STRAT_MOMENTUM] = InpUseMomentum;  trend[STRAT_MOMENTUM] = InpWTrend_MO;

   range[STRAT_TREND]    = InpWRange_TF;  neutral[STRAT_TREND]    = InpWNeutral_TF;
   range[STRAT_BREAKOUT] = InpWRange_BO;  neutral[STRAT_BREAKOUT] = InpWNeutral_BO;
   range[STRAT_MEANREV]  = InpWRange_MR;  neutral[STRAT_MEANREV]  = InpWNeutral_MR;
   range[STRAT_MOMENTUM] = InpWRange_MO;  neutral[STRAT_MOMENTUM] = InpWNeutral_MO;

   for(int s = 0; s < AMS_STRATEGY_COUNT; s++)
     {
      g_weights[REGIME_TREND][s]   = use[s] ? MathMax(trend[s], 0.0)   : 0.0;
      g_weights[REGIME_RANGE][s]   = use[s] ? MathMax(range[s], 0.0)   : 0.0;
      g_weights[REGIME_NEUTRAL][s] = use[s] ? MathMax(neutral[s], 0.0) : 0.0;
      g_weights[REGIME_HIGHVOL][s] = g_weights[REGIME_NEUTRAL][s];
     }
  }

//+------------------------------------------------------------------+
//| 銘柄名の解決：口座の銘柄名に接尾辞（例 .oj1m）があれば合わせる          |
//+------------------------------------------------------------------+
string ResolveSymbol(const string name)
  {
   string base = name;
   StringTrimLeft(base);
   StringTrimRight(base);
   if(base == "")
      return("");
   if(SymbolInfoInteger(base, SYMBOL_DIGITS) > 0 || SymbolSelect(base, true))
      return(base);
   //--- チャートの銘柄の接尾辞を付けて試す（例：USDJPY.oj1m → .oj1m）
   const int clen = StringLen(_Symbol);
   if(clen > 6)
     {
      const string withSuffix = base + StringSubstr(_Symbol, 6);
      if(SymbolSelect(withSuffix, true))
         return(withSuffix);
     }
   return("");
  }

//+------------------------------------------------------------------+
int OnInit(void)
  {
   if(!ValidateInputs())
      return(INIT_PARAMETERS_INCORRECT);

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints((ulong)MathMax(InpSlippagePoints, 0));
   g_trade.LogLevel(LOG_LEVEL_ERRORS);
   BuildWeights();

   //--- 銘柄リスト
   string names[];
   if(StringLen(InpSymbols) == 0)
     {
      ArrayResize(names, 1);
      names[0] = _Symbol;
     }
   else
      StringSplit(InpSymbols, ',', names);

   for(int i = 0; i < ArraySize(names); i++)
     {
      const string sym = ResolveSymbol(names[i]);
      if(sym == "")
        {
         PrintFormat("[AMS] 銘柄 %s は口座に無いため除外します", names[i]);
         continue;
        }
      bool dup = false;
      for(int j = 0; j < ArraySize(g_traders); j++)
         if(g_traders[j].symbol == sym)
            dup = true;
      if(dup)
         continue;

      CSymbolTrader *t = new CSymbolTrader();
      if(!t.Init(sym))
        {
         PrintFormat("[AMS] 銘柄 %s の初期化に失敗したため除外します", sym);
         delete t;
         continue;
        }
      const int n = ArraySize(g_traders);
      ArrayResize(g_traders, n + 1);
      g_traders[n] = t;
      PrintFormat("[AMS] 銘柄を追加: %s digits=%d 最小ロット=%.2f", sym,
                  (int)SymbolInfoInteger(sym, SYMBOL_DIGITS), SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN));
     }

   if(ArraySize(g_traders) == 0)
     {
      Print("[AMS] 取引できる銘柄がありません");
      return(INIT_FAILED);
     }
   g_peakEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_halted     = false;
   //--- 実運用では、最高値と停止状態をターミナルに保存しておく（EAやPCを再起動しても引き継ぐ）
   if(!MQLInfoInteger(MQL_TESTER))
     {
      if(GlobalVariableCheck(GVName("peak")))
         g_peakEquity = MathMax(g_peakEquity, GlobalVariableGet(GVName("peak")));
      if(GlobalVariableCheck(GVName("halted")) && GlobalVariableGet(GVName("halted")) > 0.5)
        {
         g_halted = true;
         Print("[AMS] 注意：前回、ドローダウン上限で停止しています。再開するには、MT5 の「ツール → グローバル変数」で ",
               GVName("halted"), " を削除してください");
        }
      LoadState();
      if(InpUseTimer)
         EventSetTimer(2);
     }
   PrintFormat("[AMS] エントリーの方式: %s", EnumToString(InpEntryMode));
   PrintFormat("[AMS] 開始 %d 銘柄 %s リスク %.1f%% 口座=%s レバレッジ=1:%d ストップアウト=%.0f%s",
               ArraySize(g_traders), EnumToString(InpTimeframe), InpRiskPercent,
               AccountInfoString(ACCOUNT_CURRENCY), (int)AccountInfoInteger(ACCOUNT_LEVERAGE),
               AccountInfoDouble(ACCOUNT_MARGIN_SO_SO),
               AccountInfoInteger(ACCOUNT_MARGIN_SO_MODE) == ACCOUNT_STOPOUT_MODE_PERCENT ? "%" : "");
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(!MQLInfoInteger(MQL_TESTER))
     {
      SaveState();
      ExportLive();
     }
   for(int i = 0; i < ArraySize(g_traders); i++)
     {
      if(CheckPointer(g_traders[i]) == POINTER_DYNAMIC)
        {
         g_traders[i].Release();
         delete g_traders[i];
        }
     }
   ArrayResize(g_traders, 0);
  }

//+------------------------------------------------------------------+
//| ターミナルのグローバル変数名（口座番号とマジックナンバーごとに分ける）      |
//+------------------------------------------------------------------+
string GVName(const string key)
  {
   return(StringFormat("AMS_%I64d_%I64u_%s", AccountInfoInteger(ACCOUNT_LOGIN), InpMagic, key));
  }

//+------------------------------------------------------------------+
//| 全銘柄の処理（ティックとタイマーの両方から呼ぶ）                        |
//+------------------------------------------------------------------+
void ProcessAll(void)
  {
   if(InpMonthTargetPct > 0.0)
      MonthToDatePct();   // 月が変わった最初のティックで、月初の残高を記録する
   //--- 口座全体のドローダウンによる停止
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity > g_peakEquity)
     {
      g_peakEquity = equity;
      if(!MQLInfoInteger(MQL_TESTER))
         GlobalVariableSet(GVName("peak"), g_peakEquity);
     }
   if(!g_halted && InpMaxDDStopPct > 0.0 && equity < g_peakEquity * (1.0 - InpMaxDDStopPct / 100.0))
     {
      g_halted = true;
      if(!MQLInfoInteger(MQL_TESTER))
         GlobalVariableSet(GVName("halted"), 1.0);
      PrintFormat("[AMS] 最高値から %.1f%% 下落したため、全決済して新規エントリーを停止します", InpMaxDDStopPct);
      for(int i = 0; i < ArraySize(g_traders); i++)
         g_traders[i].CloseAll("DD上限");
     }

   for(int i = 0; i < ArraySize(g_traders); i++)
      g_traders[i].OnTick();
   //--- 新規注文は、保留中のシグナルの優先順位の順に行う（同じ時刻のルールが証拠金を取り合う場合に、結果を決まったものにする）
   const int n = ArraySize(g_traders);
   int order[];
   ArrayResize(order, n);
   for(int i = 0; i < n; i++)
      order[i] = i;
   for(int i = 1; i < n; i++)
     {
      const int v = order[i];
      int j = i - 1;
      while(j >= 0 && g_traders[order[j]].PendingPrio() > g_traders[v].PendingPrio())
        {
         order[j + 1] = order[j];
         j--;
        }
      order[j + 1] = v;
     }
   g_minPendPrio = (n > 0) ? g_traders[order[0]].PendingPrio() : 1000000;
   for(int i = 0; i < n; i++)
      g_traders[order[i]].OnTickEnter();
  }

//+------------------------------------------------------------------+
void OnTick(void)
  {
   ProcessAll();
  }

//+------------------------------------------------------------------+
//| 実運用のみ：チャート銘柄のティックが止まっていても、他の銘柄を処理する     |
//+------------------------------------------------------------------+
void OnTimer(void)
  {
   ProcessAll();
   //--- 実運用：1分ごとに状態を保存し、1時間ごとに取引の記録を書き出す
   static datetime lastSave = 0, lastExport = 0;
   const datetime now = TimeCurrent();
   if(now - lastSave >= 60)
     {
      lastSave = now;
      SaveState();
     }
   if(now - lastExport >= 3600)
     {
      lastExport = now;
      ExportLive();
     }
  }

//==================================================================
// バックテストの集計
//==================================================================
//+------------------------------------------------------------------+
//| 名前ごとの集計に1件加える                                             |
//+------------------------------------------------------------------+
void AddStat(string &names[], int &trades[], int &wins[], double &profit[], const string name, const double p)
  {
   int idx = -1;
   for(int i = 0; i < ArraySize(names); i++)
      if(names[i] == name)
        {
         idx = i;
         break;
        }
   if(idx < 0)
     {
      idx = ArraySize(names);
      ArrayResize(names, idx + 1);
      ArrayResize(trades, idx + 1);
      ArrayResize(wins, idx + 1);
      ArrayResize(profit, idx + 1);
      names[idx]  = name;
      trades[idx] = 0;
      wins[idx]   = 0;
      profit[idx] = 0.0;
     }
   trades[idx]++;
   profit[idx] += p;
   if(p > 0.0)
      wins[idx]++;
  }

//+------------------------------------------------------------------+
void WriteStats(const int fh, const string kind, string &names[], int &trades[], int &wins[], double &profit[])
  {
   for(int i = 0; i < ArraySize(names); i++)
     {
      const double wr = trades[i] > 0 ? 100.0 * wins[i] / trades[i] : 0.0;
      PrintFormat("[AMS] %-8s %-12s 取引=%d 勝率=%.1f%% 損益=%.0f", kind, names[i], trades[i], wr, profit[i]);
      if(fh != INVALID_HANDLE)
         FileWrite(fh, kind, names[i], trades[i], wins[i], DoubleToString(wr, 1), DoubleToString(profit[i], 0));
     }
  }

//+------------------------------------------------------------------+
//| 銘柄別・相場状況別・ロジック別の成績                                   |
//+------------------------------------------------------------------+
void ReportBreakdown(void)
  {
   if(!HistorySelect(0, TimeCurrent()))
      return;

   string sN[], rN[], lN[], mN[];
   int    sT[], sW[], rT[], rW[], lT[], lW[], mT[], mW[];
   double sP[], rP[], lP[], mP[];
   double netProfit = 0.0, costPerPip = 0.0;   // costPerPip: 全取引で1pipsずつ不利に約定した場合の損失額
   double tP[], tC[];                           // 取引ごとの損益と、1pips 不利になったときの金額（コスト込み PF の計算用）
   int    nT = 0;

   const int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      const ulong deal = HistoryDealGetTicket(i);
      if(deal == 0 || (ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagic)
         continue;
      const ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
         continue;

      double profit = HistoryDealGetDouble(deal, DEAL_PROFIT) +
                      HistoryDealGetDouble(deal, DEAL_SWAP) +
                      HistoryDealGetDouble(deal, DEAL_COMMISSION);
      const long posId = HistoryDealGetInteger(deal, DEAL_POSITION_ID);
      string comment = "";
      for(int j = 0; j < total; j++)
        {
         const ulong d2 = HistoryDealGetTicket(j);
         if(d2 == 0 || HistoryDealGetInteger(d2, DEAL_POSITION_ID) != posId)
            continue;
         if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(d2, DEAL_ENTRY) == DEAL_ENTRY_IN)
           {
            comment = HistoryDealGetString(d2, DEAL_COMMENT);
            profit += HistoryDealGetDouble(d2, DEAL_COMMISSION);
            break;
           }
        }
      //--- コストを上乗せした場合の試算用：この取引で 1pips 不利になったときの金額
      const string dsym   = HistoryDealGetString(deal, DEAL_SYMBOL);
      const double tickSz = SymbolInfoDouble(dsym, SYMBOL_TRADE_TICK_SIZE);
      double c1 = 0.0;
      if(tickSz > 0.0)
         c1 = HistoryDealGetDouble(deal, DEAL_VOLUME) * PipSize(dsym) / tickSz *
              SymbolInfoDouble(dsym, SYMBOL_TRADE_TICK_VALUE);
      costPerPip += c1;
      netProfit += profit;
      ArrayResize(tP, nT + 1, 1024);
      ArrayResize(tC, nT + 1, 1024);
      tP[nT] = profit;
      tC[nT] = c1;
      nT++;

      string parts[];
      if(StringSplit(comment, '|', parts) < 4)
         continue;
      AddStat(sN, sT, sW, sP, parts[1], profit);
      AddStat(rN, rT, rW, rP, parts[2], profit);
      AddStat(lN, lT, lW, lP, parts[3], profit);
      //--- 月 × ルールの損益（どの月にどのルールが負けたかを調べるため）
      MqlDateTime md;
      TimeToStruct((datetime)HistoryDealGetInteger(deal, DEAL_TIME), md);
      AddStat(mN, mT, mW, mP, StringFormat("%04d-%02d|%s", md.year, md.mon, parts[3]), profit);
     }

   int fh = INVALID_HANDLE;
   if(!MQLInfoInteger(MQL_OPTIMIZATION))
      fh = FileOpen("AMS_breakdown.csv", FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fh != INVALID_HANDLE)
     {
      FileWrite(fh, "kind", "name", "trades", "wins", "win_rate", "profit");
      //--- シグナルの件数と、見送った件数（スプレッド拡大・その他）
      FileWrite(fh, "signal", "total", g_sigTotal, 0, "", "0");
      FileWrite(fh, "signal", "skip_spread", g_sigSpread, 0, "", "0");
      FileWrite(fh, "signal", "skip_other", g_sigOther, 0, "", "0");
     }
   //--- 自動調整：止めていたために見送ったシグナルの数と、ルールごとの状態
   int adaptSkips = 0;
   for(int i = 0; i < ArraySize(g_traders); i++)
     {
      adaptSkips += g_traders[i].AdaptSkips();
      g_traders[i].AdaptiveReport();
     }
   if(fh != INVALID_HANDLE)
      FileWrite(fh, "signal", "skip_adapt", adaptSkips, 0, "", "0");
   if(fh != INVALID_HANDLE)
      FileWrite(fh, "signal", "skip_monthlock", g_sigLock, 0, "", "0");
   Print("[AMS] ===== 銘柄別・相場状況別・ロジック別の成績 =====");
   WriteStats(fh, "symbol", sN, sT, sW, sP);
   WriteStats(fh, "regime", rN, rT, rW, rP);
   WriteStats(fh, "strategy", lN, lT, lW, lP);
   //--- 実運用ではスリッページやスプレッド拡大で成績が悪化する。その影響の目安を出す
   Print("[AMS] ===== 約定が不利にずれた場合の試算（1取引あたり） =====");
   const double extra[4] = {0.0, 0.5, 1.0, 2.0};
   for(int e = 0; e < 4; e++)
     {
      const double adj = netProfit - costPerPip * extra[e];
      //--- 追加コストを引いた後の PF（総利益 ÷ 総損失）
      double gp = 0.0, gl = 0.0;
      for(int k = 0; k < nT; k++)
        {
         const double v = tP[k] - tC[k] * extra[e];
         if(v > 0.0)
            gp += v;
         else
            gl -= v;
        }
      const double pf = (gl > 0.0 ? gp / gl : 99.0);
      PrintFormat("[AMS] 追加コスト %.1f pips → 総損益 %.0f  PF %.2f", extra[e], adj, pf);
      if(fh != INVALID_HANDLE)
         FileWrite(fh, "cost", StringFormat("+%.1fpips", extra[e]), nT, 0, DoubleToString(pf, 2), DoubleToString(adj, 0));
     }
   if(fh != INVALID_HANDLE)
      FileClose(fh);
   //--- 月 × ルールの損益（"MM|ルール,取引数,損益"）
   if(!MQLInfoInteger(MQL_OPTIMIZATION))
     {
      const int fm = FileOpen("AMS_rulemonth.csv", FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
      if(fm != INVALID_HANDLE)
        {
         FileWrite(fm, "month_rule", "trades", "profit");
         for(int i = 0; i < ArraySize(mN); i++)
            FileWrite(fm, mN[i], mT[i], DoubleToString(mP[i], 0));
         FileClose(fm);
        }
     }
  }

//+------------------------------------------------------------------+
//| 月ごとの損益率（確定損益ベース）を計算し、月利の幾何平均（%）を返す       |
//+------------------------------------------------------------------+
double MonthlyReturns(const bool output)
  {
   if(!HistorySelect(0, TimeCurrent()))
      return(0.0);
   const int total = HistoryDealsTotal();
   if(total == 0)
      return(0.0);

   const datetime first = (datetime)HistoryDealGetInteger(HistoryDealGetTicket(0), DEAL_TIME);
   MqlDateTime d0, d1;
   TimeToStruct(first, d0);
   TimeToStruct(TimeCurrent(), d1);
   const int months = (d1.year - d0.year) * 12 + (d1.mon - d0.mon) + 1;
   if(months <= 0)
      return(0.0);

   g_stopOut = false;
   double pnl[];
   ArrayResize(pnl, months);
   ArrayInitialize(pnl, 0.0);
   for(int i = 0; i < total; i++)
     {
      const ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      const ENUM_DEAL_TYPE type = (ENUM_DEAL_TYPE)HistoryDealGetInteger(deal, DEAL_TYPE);
      if(type != DEAL_TYPE_BUY && type != DEAL_TYPE_SELL)
         continue;
      if((ENUM_DEAL_REASON)HistoryDealGetInteger(deal, DEAL_REASON) == DEAL_REASON_SO)
         g_stopOut = true;
      MqlDateTime dt;
      TimeToStruct((datetime)HistoryDealGetInteger(deal, DEAL_TIME), dt);
      const int idx = (dt.year - d0.year) * 12 + (dt.mon - d0.mon);
      if(idx < 0 || idx >= months)
        continue;
      pnl[idx] += HistoryDealGetDouble(deal, DEAL_PROFIT) + HistoryDealGetDouble(deal, DEAL_SWAP) +
                  HistoryDealGetDouble(deal, DEAL_COMMISSION);
     }

   double balance = TesterStatistics(STAT_INITIAL_DEPOSIT);
   if(balance <= 0.0)
      balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double growth = 1.0, sum = 0.0, minR = DBL_MAX, maxR = -DBL_MAX;
   int over10 = 0;

   int fh = INVALID_HANDLE;
   if(output && !MQLInfoInteger(MQL_OPTIMIZATION))
     {
      fh = FileOpen("AMS_monthly.csv", FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
      if(fh != INVALID_HANDLE)
         FileWrite(fh, "month", "start_balance", "profit", "return_pct");
     }

   for(int m = 0; m < months; m++)
     {
      const double r = (balance > 0.0) ? pnl[m] / balance * 100.0 : -100.0;
      const int y  = d0.year + (d0.mon - 1 + m) / 12;
      const int mo = (d0.mon - 1 + m) % 12 + 1;
      if(output)
         PrintFormat("[AMS] 月利 %04d-%02d  %+.2f%%  （損益 %.0f）", y, mo, r, pnl[m]);
      if(fh != INVALID_HANDLE)
         FileWrite(fh, StringFormat("%04d-%02d", y, mo), DoubleToString(balance, 0),
                   DoubleToString(pnl[m], 0), DoubleToString(r, 2));
      sum += r;
      if(r < minR)
         minR = r;
      if(r > maxR)
         maxR = r;
      if(r >= 10.0)
         over10++;
      growth *= MathMax(1.0 + r / 100.0, 0.0);
      balance += pnl[m];
     }
   if(fh != INVALID_HANDLE)
      FileClose(fh);

   const double geo = (growth > 0.0) ? (MathPow(growth, 1.0 / months) - 1.0) * 100.0 : -100.0;
   if(output)
      PrintFormat("[AMS] 月利まとめ: %d か月 平均 %+.2f%% 幾何平均 %+.2f%% 最低 %+.2f%% 最高 %+.2f%% 10%%以上の月 %d",
                  months, sum / months, geo, minR, maxR, over10);
   return(geo);
  }

//+------------------------------------------------------------------+
//| 最適化の評価値：月利の幾何平均（%）。取引数不足・DD超過は 0             |
//+------------------------------------------------------------------+
double OnTester(void)
  {
   const bool output = !MQLInfoInteger(MQL_OPTIMIZATION);
   if(output)
      ReportBreakdown();
   if(output && InpExportDeals)
      WriteDeals("AMS_bt_deals.csv", 0);
   if(output)
      PrintFormat("[AMS] シグナル %d 件のうち、スプレッドが広いまま見送り %d 件、その他の理由で見送り %d 件",
                  g_sigTotal, g_sigSpread, g_sigOther);
   const double geo    = MonthlyReturns(output);
   const double trades = TesterStatistics(STAT_TRADES);
   const double dd     = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   if(g_stopOut)
     {
      if(output)
         Print("[AMS] 警告：強制ロスカット（ストップアウト）が発生しました。評価値は 0 にします");
      return(0.0);
     }
   if(trades < InpScoreMinTrades || dd > InpScoreMaxDD)
      return(0.0);
   return(geo);
  }
//+------------------------------------------------------------------+

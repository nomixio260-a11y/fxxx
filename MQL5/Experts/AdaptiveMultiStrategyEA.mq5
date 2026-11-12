//+------------------------------------------------------------------+
//|                                     AdaptiveMultiStrategyEA.mq5  |
//|  相場状況（トレンド/レンジ/中立/高ボラ）を判定し、                      |
//|  4つの売買ロジックの重みを切り替えて売買する EA                         |
//|  推奨：USDJPY / H1（OANDA の接尾辞付き銘柄にも対応）                   |
//+------------------------------------------------------------------+
#property copyright "fxxx"
#property version   "1.00"
#property description "Adaptive Multi-Strategy EA"
#property description "相場状況に応じて、トレンドフォロー/ブレイクアウト/逆張り/モメンタムを使い分けます。"
#property description "利益を保証するものではありません。必ずデモ口座で検証してから使ってください。"

#include <Trade\Trade.mqh>
#include <AMS\Common.mqh>
#include <AMS\Regime.mqh>
#include <AMS\Strategies.mqh>
#include <AMS\RiskManager.mqh>
#include <AMS\TradeFilters.mqh>

//==================================================================
// 入力パラメータ
//==================================================================
input group "=== 基本設定 ==="
input ulong            InpMagic             = 20261112;    // マジックナンバー
input ENUM_TIMEFRAMES  InpTimeframe         = PERIOD_H1;   // 判定に使う時間足
input string           InpComment           = "AMS";       // 注文コメントの先頭
input int              InpSlippagePoints    = 20;          // 許容スリッページ（point）
input bool             InpVerbose           = false;       // 毎バーの判定内容をログに出す

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
input double           InpADXRange          = 20.0;        // ADX がこれ未満でレンジ候補
input double           InpHighVolPct        = 0.90;        // ATR順位がこれ以上で高ボラ（0〜1）
input double           InpRangeBWPct        = 0.50;        // BB幅順位がこれ以下でレンジ候補（0〜1）
input ENUM_AMS_HIGHVOL_MODE InpHighVolMode  = HIGHVOL_HALF; // 高ボラ時の扱い

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
input int              InpMaxPositions      = 1;           // 最大ポジション数

input group "=== 資金管理 ==="
input double           InpRiskPercent       = 1.0;         // 1回の許容損失（有効証拠金の%）
input bool             InpAllowMinLot       = false;       // 計算ロットが最小未満なら最小ロットで入る
input double           InpSLATR             = 1.5;         // SL = ATR × この値
input double           InpTPATR             = 3.0;         // TP = ATR × この値（0でTPなし）
input double           InpBETriggerATR      = 1.0;         // 含み益が ATR×この値 で建値へ（0で無効）
input double           InpBEOffsetPips      = 0.5;         // 建値ストップの上乗せ（pips）
input double           InpTrailStartATR     = 1.5;         // 含み益が ATR×この値 でトレーリング開始
input double           InpTrailDistATR      = 1.0;         // トレーリング幅 ATR×この値（0で無効）
input double           InpTrailStepPips     = 1.0;         // SLを動かす最小幅（pips）
input double           InpMaxDailyLossPct   = 3.0;         // 1日の損失上限（%、0で無効）

input group "=== フィルター ==="
input double           InpMaxSpreadPips     = 2.0;         // 最大スプレッド（pips、0で無効）
input int              InpStartHour         = 0;           // 取引開始（サーバー時間）
input int              InpEndHour           = 0;           // 取引終了（開始と同じなら終日）
input int              InpFridayCloseHour   = 22;          // 金曜この時刻以降は全決済（-1で無効）
input int              InpMondayStartHour   = 2;           // 月曜この時刻までは新規なし（0で無効）

//==================================================================
// グローバル
//==================================================================
CTrade          g_trade;
CRegimeDetector g_regime;
CStrategySet    g_strategies;
CRiskManager    g_risk;

datetime        g_lastBarTime = 0;
double          g_lastATR     = 0.0;
double          g_weights[4][AMS_STRATEGY_COUNT];   // [REGIME][STRATEGY]

//+------------------------------------------------------------------+
//| 入力値のチェック                                                    |
//+------------------------------------------------------------------+
bool ValidateInputs(void)
  {
   if(InpRiskPercent <= 0.0 || InpRiskPercent > 10.0)
     {
      Print("[AMS] InpRiskPercent は 0 より大きく 10 以下にしてください");
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
   if(InpMaxPositions < 1)
     {
      Print("[AMS] InpMaxPositions は 1 以上にしてください");
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
//| 重み表を作る（無効にしたロジックは 0）                                |
//+------------------------------------------------------------------+
void BuildWeights(void)
  {
   bool   use[AMS_STRATEGY_COUNT];
   double trend[AMS_STRATEGY_COUNT], range[AMS_STRATEGY_COUNT], neutral[AMS_STRATEGY_COUNT];

   use[STRAT_TREND]    = InpUseTrend;     trend[STRAT_TREND]    = InpWTrend_TF;
   use[STRAT_BREAKOUT] = InpUseBreakout;  trend[STRAT_BREAKOUT] = InpWTrend_BO;
   use[STRAT_MEANREV]  = InpUseMeanRev;   trend[STRAT_MEANREV]  = InpWTrend_MR;
   use[STRAT_MOMENTUM] = InpUseMomentum;  trend[STRAT_MOMENTUM] = InpWTrend_MO;

   range[STRAT_TREND]   = InpWRange_TF;   neutral[STRAT_TREND]    = InpWNeutral_TF;
   range[STRAT_BREAKOUT] = InpWRange_BO;  neutral[STRAT_BREAKOUT] = InpWNeutral_BO;
   range[STRAT_MEANREV] = InpWRange_MR;   neutral[STRAT_MEANREV]  = InpWNeutral_MR;
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
//| 重み付きスコア（-1〜+1）と、いちばん効いたロジックを求める              |
//+------------------------------------------------------------------+
double CalcScore(const ENUM_AMS_REGIME regime, const double &signals[], int &dominant)
  {
   double sum = 0.0, wsum = 0.0, best = 0.0;
   dominant = -1;
   for(int s = 0; s < AMS_STRATEGY_COUNT; s++)
     {
      const double w = g_weights[regime][s];
      if(w <= 0.0)
         continue;
      wsum += w;
      sum  += w * signals[s];
     }
   if(wsum <= 0.0)
      return(0.0);
   const double score = sum / wsum;

   //--- スコアと同じ向きで、寄与がいちばん大きいロジック
   for(int s = 0; s < AMS_STRATEGY_COUNT; s++)
     {
      const double contrib = g_weights[regime][s] * signals[s];
      if(contrib * score > 0.0 && MathAbs(contrib) > best)
        {
         best     = MathAbs(contrib);
         dominant = s;
        }
     }
   return(score);
  }

//+------------------------------------------------------------------+
bool IsNewBar(void)
  {
   const datetime t = iTime(_Symbol, InpTimeframe, 0);
   if(t == 0 || t == g_lastBarTime)
      return(false);
   g_lastBarTime = t;
   return(true);
  }

//+------------------------------------------------------------------+
//| 新規注文                                                           |
//+------------------------------------------------------------------+
bool OpenPosition(const ENUM_ORDER_TYPE type, const ENUM_AMS_REGIME regime,
                  const int dominant, const double riskMultiplier)
  {
   const double atr = g_lastATR;
   if(atr <= 0.0)
      return(false);

   const bool   isBuy = (type == ORDER_TYPE_BUY);
   const double entry = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl = isBuy ? entry - atr * InpSLATR : entry + atr * InpSLATR;
   double tp = 0.0;
   if(InpTPATR > 0.0)
      tp = isBuy ? entry + atr * InpTPATR : entry - atr * InpTPATR;

   if(!g_risk.AdjustStops(type, entry, sl, tp))
      return(false);

   const double lots = g_risk.CalcLots(type, entry, sl, riskMultiplier);
   if(lots <= 0.0)
     {
      Print("[AMS] ロットが最小ロット未満のため見送り（資金に対してSLが広すぎます）");
      return(false);
     }

   const string comment = StringFormat("%s|%s|%s", InpComment, RegimeShortName(regime), StrategyShortName(dominant));
   const bool sent = isBuy ? g_trade.Buy(lots, _Symbol, entry, sl, tp, comment)
                           : g_trade.Sell(lots, _Symbol, entry, sl, tp, comment);
   const uint rc = g_trade.ResultRetcode();
   if(!sent || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_PLACED && rc != TRADE_RETCODE_DONE_PARTIAL))
     {
      PrintFormat("[AMS] 注文失敗 %s %.2f lot retcode=%u %s", isBuy ? "BUY" : "SELL", lots,
                  rc, g_trade.ResultRetcodeDescription());
      return(false);
     }
   PrintFormat("[AMS] %s %.2f lot @%s SL=%s TP=%s [%s]", isBuy ? "BUY" : "SELL", lots,
               DoubleToString(entry, _Digits), DoubleToString(sl, _Digits),
               DoubleToString(tp, _Digits), comment);
   return(true);
  }

//+------------------------------------------------------------------+
//| 新しい足ができたときの判定と売買                                      |
//+------------------------------------------------------------------+
void OnNewBar(void)
  {
   g_risk.UpdateDay();

   ENUM_AMS_REGIME regime = REGIME_NEUTRAL;
   if(!g_regime.Detect(regime))
      return;
   g_lastATR = g_regime.ATR();

   double signals[];
   if(!g_strategies.Evaluate(signals))
      return;

   int dominant = -1;
   const double score = CalcScore(regime, signals, dominant);

   if(InpVerbose)
      PrintFormat("[AMS] %s regime=%s ADX=%.1f ATR%%=%.2f BW%%=%.2f | TF=%.1f BO=%.1f MR=%.1f MO=%.1f | score=%.2f",
                  TimeToString(iTime(_Symbol, InpTimeframe, 1)), RegimeShortName(regime),
                  g_regime.ADX(), g_regime.ATRPct(), g_regime.BWPct(),
                  signals[STRAT_TREND], signals[STRAT_BREAKOUT], signals[STRAT_MEANREV],
                  signals[STRAT_MOMENTUM], score);

   //--- 逆方向のシグナルで決済
   int buys = 0, sells = 0;
   g_risk.CountPositions(buys, sells);
   if(InpCloseOnOpposite)
     {
      if(score <= -InpEntryThreshold && buys > 0)
         g_risk.CloseDirection(POSITION_TYPE_BUY, "逆シグナル");
      if(score >= InpEntryThreshold && sells > 0)
         g_risk.CloseDirection(POSITION_TYPE_SELL, "逆シグナル");
      g_risk.CountPositions(buys, sells);
     }

   //--- 新規エントリーの条件
   if(MathAbs(score) < InpEntryThreshold)
      return;
   if(IsFridayCloseTime(InpFridayCloseHour) || IsMondayOpenGap(InpMondayStartHour))
      return;
   if(!WithinTradingHours(InpStartHour, InpEndHour))
      return;
   if(g_risk.DailyLossHit())
     {
      if(InpVerbose)
         Print("[AMS] 1日の損失上限に達したため新規エントリーを停止中");
      return;
     }
   if(!SpreadOK(_Symbol, InpMaxSpreadPips))
     {
      if(InpVerbose)
         PrintFormat("[AMS] スプレッドが広いため見送り (%.1f pips)", CurrentSpreadPips(_Symbol));
      return;
     }

   double riskMultiplier = 1.0;
   if(regime == REGIME_HIGHVOL)
     {
      if(InpHighVolMode == HIGHVOL_BLOCK)
         return;
      riskMultiplier = 0.5;
     }

   if(buys + sells >= InpMaxPositions)
      return;
   //--- 同じ方向のポジションがあるときは追加しない（ナンピン/積み増しなし）
   if(score > 0.0 && buys > 0)
      return;
   if(score < 0.0 && sells > 0)
      return;

   OpenPosition(score > 0.0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, regime, dominant, riskMultiplier);
  }

//+------------------------------------------------------------------+
int OnInit(void)
  {
   if(!ValidateInputs())
      return(INIT_PARAMETERS_INCORRECT);

   if(!SymbolInfoInteger(_Symbol, SYMBOL_SELECT))
      SymbolSelect(_Symbol, true);

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints((ulong)MathMax(InpSlippagePoints, 0));
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.LogLevel(LOG_LEVEL_ERRORS);

   if(!g_regime.Init(_Symbol, InpTimeframe, InpADXPeriod, InpATRPeriod,
                     InpRegimeBBPeriod, InpRegimeBBDev, InpRegimeEMAFast, InpRegimeEMASlow,
                     InpRegimeLookback, InpSlopeBars, InpADXTrend, InpADXRange,
                     InpHighVolPct, InpRangeBWPct))
      return(INIT_FAILED);

   if(!g_strategies.Init(_Symbol, InpTimeframe, InpTrendEMAFast, InpTrendEMASlow,
                         InpHTF, InpHTFEMA, InpUseHTFFilter, InpDonchian,
                         InpRSIPeriod, InpRSILow, InpRSIHigh, InpMRBBPeriod, InpMRBBDev,
                         InpMACDFast, InpMACDSlow, InpMACDSignal,
                         InpStochK, InpStochD, InpStochSlowing))
      return(INIT_FAILED);

   g_risk.Init(_Symbol, InpMagic, GetPointer(g_trade), InpRiskPercent, InpMaxDailyLossPct, InpAllowMinLot);
   BuildWeights();

   PrintFormat("[AMS] 開始 %s %s digits=%d pip=%s 最小ロット=%.2f 刻み=%.2f",
               _Symbol, EnumToString(InpTimeframe), _Digits,
               DoubleToString(PipSize(_Symbol), _Digits),
               SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP));
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   g_regime.Release();
   g_strategies.Release();
  }

//+------------------------------------------------------------------+
void OnTick(void)
  {
   //--- 週末前は全決済
   if(IsFridayCloseTime(InpFridayCloseHour))
     {
      int buys = 0, sells = 0;
      if(g_risk.CountPositions(buys, sells) > 0)
         g_risk.CloseAll("金曜クローズ");
     }

   if(IsNewBar())
      OnNewBar();

   //--- 建値ストップ / トレーリング（毎ティック）
   g_risk.ManageStops(g_lastATR, InpBETriggerATR, InpBEOffsetPips,
                      InpTrailStartATR, InpTrailDistATR, InpTrailStepPips);
  }

//+------------------------------------------------------------------+
//| バックテスト終了時：相場状況別・ロジック別の成績を出力                   |
//+------------------------------------------------------------------+
void ReportBreakdown(void)
  {
   if(!HistorySelect(0, TimeCurrent()))
      return;

   const string regimeNames[4] = { "NEUT", "TREND", "RANGE", "HVOL" };
   const string stratNames[AMS_STRATEGY_COUNT] = { "TF", "BO", "MR", "MO" };
   int    rTrades[4], rWins[4], sTrades[AMS_STRATEGY_COUNT], sWins[AMS_STRATEGY_COUNT];
   double rProfit[4], sProfit[AMS_STRATEGY_COUNT];
   ArrayInitialize(rTrades, 0);
   ArrayInitialize(rWins, 0);
   ArrayInitialize(rProfit, 0.0);
   ArrayInitialize(sTrades, 0);
   ArrayInitialize(sWins, 0);
   ArrayInitialize(sProfit, 0.0);

   const int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      const ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      if((ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagic)
         continue;
      const ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
         continue;

      double profit = HistoryDealGetDouble(deal, DEAL_PROFIT) +
                      HistoryDealGetDouble(deal, DEAL_SWAP) +
                      HistoryDealGetDouble(deal, DEAL_COMMISSION);
      const long posId = HistoryDealGetInteger(deal, DEAL_POSITION_ID);

      //--- 同じポジションのエントリー約定からコメント（レジーム|ロジック）を得る
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

      string parts[];
      if(StringSplit(comment, '|', parts) < 3)
         continue;
      for(int r = 0; r < 4; r++)
         if(parts[1] == regimeNames[r])
           {
            rTrades[r]++;
            rProfit[r] += profit;
            if(profit > 0.0)
               rWins[r]++;
           }
      for(int s = 0; s < AMS_STRATEGY_COUNT; s++)
         if(parts[2] == stratNames[s])
           {
            sTrades[s]++;
            sProfit[s] += profit;
            if(profit > 0.0)
               sWins[s]++;
           }
     }

   const int fh = FileOpen("AMS_breakdown.csv", FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fh != INVALID_HANDLE)
      FileWrite(fh, "kind", "name", "trades", "wins", "win_rate", "profit");

   Print("[AMS] ===== 相場状況別の成績 =====");
   for(int r = 0; r < 4; r++)
     {
      const double wr = rTrades[r] > 0 ? 100.0 * rWins[r] / rTrades[r] : 0.0;
      PrintFormat("[AMS] %-5s 取引=%d 勝率=%.1f%% 損益=%.0f", regimeNames[r], rTrades[r], wr, rProfit[r]);
      if(fh != INVALID_HANDLE)
         FileWrite(fh, "regime", regimeNames[r], rTrades[r], rWins[r], DoubleToString(wr, 1), DoubleToString(rProfit[r], 0));
     }
   Print("[AMS] ===== ロジック別の成績（エントリーを主導したロジック） =====");
   for(int s = 0; s < AMS_STRATEGY_COUNT; s++)
     {
      const double wr = sTrades[s] > 0 ? 100.0 * sWins[s] / sTrades[s] : 0.0;
      PrintFormat("[AMS] %-5s 取引=%d 勝率=%.1f%% 損益=%.0f", stratNames[s], sTrades[s], wr, sProfit[s]);
      if(fh != INVALID_HANDLE)
         FileWrite(fh, "strategy", stratNames[s], sTrades[s], sWins[s], DoubleToString(wr, 1), DoubleToString(sProfit[s], 0));
     }
   if(fh != INVALID_HANDLE)
      FileClose(fh);
  }

//+------------------------------------------------------------------+
//| 最適化用の評価値：PF × √取引数 ÷ (1 + 最大DD%/10)                     |
//+------------------------------------------------------------------+
double OnTester(void)
  {
   ReportBreakdown();

   const double trades = TesterStatistics(STAT_TRADES);
   const double profit = TesterStatistics(STAT_PROFIT);
   const double pf     = TesterStatistics(STAT_PROFIT_FACTOR);
   const double dd     = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   if(trades < 30.0 || profit <= 0.0)
      return(0.0);
   return(pf * MathSqrt(trades) / (1.0 + dd / 10.0));
  }
//+------------------------------------------------------------------+

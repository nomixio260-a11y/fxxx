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
input int              InpMaxPerSymbol      = 1;           // 1銘柄あたりの最大ポジション数

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
input double           InpMaxDDStopPct      = 50.0;        // 最高値からの下落がこの%を超えたら全決済して停止（0で無効）
input double           InpMaxMarginUsePct   = 40.0;        // 必要証拠金の合計の上限（有効証拠金の%。強制ロスカット防止）

input group "=== フィルター ==="
input double           InpMaxSpreadATR      = 0.25;        // スプレッドが ATR×この値を超えたら見送り（0で無効）
input int              InpStartHour         = 0;           // 取引開始（サーバー時間）
input int              InpEndHour           = 0;           // 取引終了（開始と同じなら終日）
input int              InpFridayCloseHour   = 22;          // 金曜この時刻以降は全決済（-1で無効）
input int              InpMondayStartHour   = 2;           // 月曜この時刻までは新規なし（0で無効）

input group "=== バックテストの評価 ==="
input int              InpScoreMinTrades    = 20;          // 評価値を出す最低取引数
input double           InpScoreMaxDD        = 60.0;        // 最大DD（%）がこれを超えたら評価値 0

//==================================================================
// 銘柄ごとの売買
//==================================================================
CTrade g_trade;
double g_weights[4][AMS_STRATEGY_COUNT];   // [REGIME][STRATEGY]
double g_peakEquity = 0.0;
bool   g_stopOut    = false;   // バックテスト中に強制ロスカットがあったか
bool   g_halted     = false;

int CountAllPositions(void);

class CSymbolTrader
  {
public:
   string            symbol;
   CRegimeDetector   regime;
   CStrategySet      strategies;
   CRiskManager      risk;
   datetime          lastBar;
   double            lastATR;

                     CSymbolTrader(void) : symbol(""), lastBar(0), lastATR(0.0) {}

   bool              Init(const string sym);
   void              Release(void) { regime.Release(); strategies.Release(); }
   void              OnTick(void);
   void              CloseAll(const string reason) { g_trade.SetTypeFillingBySymbol(symbol); risk.CloseAll(reason); }

private:
   bool              IsNewBar(void);
   void              OnBar(void);
   double            CalcScore(const ENUM_AMS_REGIME reg, const double &signals[], int &dominant);
   bool              Open(const ENUM_ORDER_TYPE type, const ENUM_AMS_REGIME reg, const int dominant, const double riskMul);
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
             InpMaxMarginUsePct);
   return(true);
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

   //--- 週末前は全決済
   if(IsFridayCloseTime(InpFridayCloseHour))
     {
      int b = 0, s = 0;
      if(risk.CountPositions(b, s) > 0)
         risk.CloseAll("金曜クローズ");
     }

   if(IsNewBar())
      OnBar();

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

   ENUM_AMS_REGIME reg = REGIME_NEUTRAL;
   if(!regime.Detect(reg))
      return;
   lastATR = regime.ATR();

   double signals[];
   if(!strategies.Evaluate(signals))
      return;

   int dominant = -1;
   const double score = CalcScore(reg, signals, dominant);

   if(InpVerbose)
      PrintFormat("[AMS] %s %s regime=%s ADX=%.1f ATR%%=%.2f BW%%=%.2f | TF=%.1f BO=%.1f MR=%.1f MO=%.1f | score=%.2f",
                  symbol, TimeToString(iTime(symbol, InpTimeframe, 1)), RegimeShortName(reg),
                  regime.ADX(), regime.ATRPct(), regime.BWPct(),
                  signals[STRAT_TREND], signals[STRAT_BREAKOUT], signals[STRAT_MEANREV],
                  signals[STRAT_MOMENTUM], score);

   //--- 逆方向のシグナルで決済
   int buys = 0, sells = 0;
   risk.CountPositions(buys, sells);
   if(InpCloseOnOpposite)
     {
      if(score <= -InpEntryThreshold && buys > 0)
         risk.CloseDirection(POSITION_TYPE_BUY, "逆シグナル");
      if(score >= InpEntryThreshold && sells > 0)
         risk.CloseDirection(POSITION_TYPE_SELL, "逆シグナル");
      risk.CountPositions(buys, sells);
     }

   //--- 新規エントリーの条件
   if(g_halted || MathAbs(score) < InpEntryThreshold)
      return;
   if(reg == REGIME_NEUTRAL && !InpTradeNeutral)
      return;
   if(IsFridayCloseTime(InpFridayCloseHour) || IsMondayOpenGap(InpMondayStartHour))
      return;
   if(!WithinTradingHours(InpStartHour, InpEndHour))
      return;
   if(risk.DailyLossHit())
      return;
   if(InpMaxSpreadATR > 0.0 && lastATR > 0.0)
     {
      const double spread = SymbolInfoDouble(symbol, SYMBOL_ASK) - SymbolInfoDouble(symbol, SYMBOL_BID);
      if(spread > lastATR * InpMaxSpreadATR)
        {
         if(InpVerbose)
            PrintFormat("[AMS] %s スプレッドが広いため見送り", symbol);
         return;
        }
     }

   double riskMul = 1.0;
   if(reg == REGIME_HIGHVOL)
     {
      if(InpHighVolMode == HIGHVOL_BLOCK)
         return;
      riskMul = 0.5;
     }

   if(buys + sells >= InpMaxPerSymbol || CountAllPositions() >= InpMaxPositions)
      return;
   if(score > 0.0 && buys > 0)
      return;
   if(score < 0.0 && sells > 0)
      return;

   Open(score > 0.0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, reg, dominant, riskMul);
  }

//+------------------------------------------------------------------+
bool CSymbolTrader::Open(const ENUM_ORDER_TYPE type, const ENUM_AMS_REGIME reg,
                         const int dominant, const double riskMul)
  {
   const double atr = lastATR;
   if(atr <= 0.0)
      return(false);

   const int    digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   const bool   isBuy  = (type == ORDER_TYPE_BUY);
   const double entry  = isBuy ? SymbolInfoDouble(symbol, SYMBOL_ASK) : SymbolInfoDouble(symbol, SYMBOL_BID);
   double sl = isBuy ? entry - atr * InpSLATR : entry + atr * InpSLATR;
   double tp = 0.0;
   if(InpTPATR > 0.0)
      tp = isBuy ? entry + atr * InpTPATR : entry - atr * InpTPATR;

   if(!risk.AdjustStops(type, entry, sl, tp))
      return(false);

   const double lots = risk.CalcLots(type, entry, sl, riskMul);
   if(lots <= 0.0)
     {
      if(InpVerbose)
         PrintFormat("[AMS] %s ロットが最小ロット未満（または証拠金不足）のため見送り", symbol);
      return(false);
     }

   const string comment = StringFormat("%s|%s|%s|%s", InpComment, symbol, RegimeShortName(reg), StrategyShortName(dominant));
   g_trade.SetTypeFillingBySymbol(symbol);
   const bool sent = isBuy ? g_trade.Buy(lots, symbol, entry, sl, tp, comment)
                           : g_trade.Sell(lots, symbol, entry, sl, tp, comment);
   const uint rc = g_trade.ResultRetcode();
   if(!sent || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_PLACED && rc != TRADE_RETCODE_DONE_PARTIAL))
     {
      PrintFormat("[AMS] 注文失敗 %s %s %.2f lot retcode=%u %s", symbol, isBuy ? "BUY" : "SELL", lots,
                  rc, g_trade.ResultRetcodeDescription());
      return(false);
     }
   PrintFormat("[AMS] %s %s %.2f lot @%s SL=%s TP=%s [%s]", symbol, isBuy ? "BUY" : "SELL", lots,
               DoubleToString(entry, digits), DoubleToString(sl, digits),
               DoubleToString(tp, digits), comment);
   return(true);
  }

//==================================================================
// グローバル
//==================================================================
CSymbolTrader *g_traders[];

//+------------------------------------------------------------------+
int CountAllPositions(void)
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic)
         n++;
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
   PrintFormat("[AMS] 開始 %d 銘柄 %s リスク %.1f%%", ArraySize(g_traders), EnumToString(InpTimeframe), InpRiskPercent);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
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
void OnTick(void)
  {
   //--- 口座全体のドローダウンによる停止
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity > g_peakEquity)
      g_peakEquity = equity;
   if(!g_halted && InpMaxDDStopPct > 0.0 && equity < g_peakEquity * (1.0 - InpMaxDDStopPct / 100.0))
     {
      g_halted = true;
      PrintFormat("[AMS] 最高値から %.1f%% 下落したため、全決済して新規エントリーを停止します", InpMaxDDStopPct);
      for(int i = 0; i < ArraySize(g_traders); i++)
         g_traders[i].CloseAll("DD上限");
     }

   for(int i = 0; i < ArraySize(g_traders); i++)
      g_traders[i].OnTick();
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

   string sN[], rN[], lN[];
   int    sT[], sW[], rT[], rW[], lT[], lW[];
   double sP[], rP[], lP[];

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
      string parts[];
      if(StringSplit(comment, '|', parts) < 4)
         continue;
      AddStat(sN, sT, sW, sP, parts[1], profit);
      AddStat(rN, rT, rW, rP, parts[2], profit);
      AddStat(lN, lT, lW, lP, parts[3], profit);
     }

   int fh = INVALID_HANDLE;
   if(!MQLInfoInteger(MQL_OPTIMIZATION))
      fh = FileOpen("AMS_breakdown.csv", FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fh != INVALID_HANDLE)
      FileWrite(fh, "kind", "name", "trades", "wins", "win_rate", "profit");
   Print("[AMS] ===== 銘柄別・相場状況別・ロジック別の成績 =====");
   WriteStats(fh, "symbol", sN, sT, sW, sP);
   WriteStats(fh, "regime", rN, rT, rW, rP);
   WriteStats(fh, "strategy", lN, lT, lW, lP);
   if(fh != INVALID_HANDLE)
      FileClose(fh);
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

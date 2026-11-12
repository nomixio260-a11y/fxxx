//+------------------------------------------------------------------+
//|                                               AMS/Strategies.mqh |
//|  4つの売買ロジック。いずれも確定足で判定し、                          |
//|  -1.0（強い売り）〜 +1.0（強い買い）のシグナルを返す。                 |
//+------------------------------------------------------------------+
#ifndef AMS_STRATEGIES_MQH
#define AMS_STRATEGIES_MQH

#include "Common.mqh"

class CStrategySet
  {
private:
   string            m_symbol;
   ENUM_TIMEFRAMES   m_tf;

   int               m_hEMAFast;      // トレンドフォロー：短期EMA
   int               m_hEMASlow;      // トレンドフォロー：長期EMA
   int               m_hHTFEMA;       // 上位足EMA（方向フィルター）
   int               m_hRSI;          // 逆張り
   int               m_hBB;           // 逆張り
   int               m_hMACD;         // モメンタム
   int               m_hStoch;        // モメンタム確認

   int               m_donchian;      // ブレイクアウトの期間
   double            m_rsiLow;
   double            m_rsiHigh;
   bool              m_useHTFFilter;

   double            TrendFollow(void);
   double            Breakout(void);
   double            MeanReversion(void);
   double            Momentum(void);
   int               HTFDirection(void);

public:
                     CStrategySet(void);
                    ~CStrategySet(void) { Release(); }

   bool              Init(const string symbol, const ENUM_TIMEFRAMES tf,
                          const int emaFast, const int emaSlow,
                          const ENUM_TIMEFRAMES htf, const int htfEma, const bool useHTFFilter,
                          const int donchian,
                          const int rsiPeriod, const double rsiLow, const double rsiHigh,
                          const int bbPeriod, const double bbDev,
                          const int macdFast, const int macdSlow, const int macdSignal,
                          const int stochK, const int stochD, const int stochSlowing);
   void              Release(void);
   bool              Evaluate(double &signals[]);
  };

//+------------------------------------------------------------------+
CStrategySet::CStrategySet(void) : m_symbol(""),
                                   m_tf(PERIOD_CURRENT),
                                   m_hEMAFast(INVALID_HANDLE),
                                   m_hEMASlow(INVALID_HANDLE),
                                   m_hHTFEMA(INVALID_HANDLE),
                                   m_hRSI(INVALID_HANDLE),
                                   m_hBB(INVALID_HANDLE),
                                   m_hMACD(INVALID_HANDLE),
                                   m_hStoch(INVALID_HANDLE),
                                   m_donchian(20),
                                   m_rsiLow(30.0),
                                   m_rsiHigh(70.0),
                                   m_useHTFFilter(true)
  {
  }

//+------------------------------------------------------------------+
bool CStrategySet::Init(const string symbol, const ENUM_TIMEFRAMES tf,
                        const int emaFast, const int emaSlow,
                        const ENUM_TIMEFRAMES htf, const int htfEma, const bool useHTFFilter,
                        const int donchian,
                        const int rsiPeriod, const double rsiLow, const double rsiHigh,
                        const int bbPeriod, const double bbDev,
                        const int macdFast, const int macdSlow, const int macdSignal,
                        const int stochK, const int stochD, const int stochSlowing)
  {
   m_symbol       = symbol;
   m_tf           = tf;
   m_donchian     = MathMax(donchian, 2);
   m_rsiLow       = rsiLow;
   m_rsiHigh      = rsiHigh;
   m_useHTFFilter = useHTFFilter;

   m_hEMAFast = iMA(symbol, tf, emaFast, 0, MODE_EMA, PRICE_CLOSE);
   m_hEMASlow = iMA(symbol, tf, emaSlow, 0, MODE_EMA, PRICE_CLOSE);
   m_hHTFEMA  = iMA(symbol, htf, htfEma, 0, MODE_EMA, PRICE_CLOSE);
   m_hRSI     = iRSI(symbol, tf, rsiPeriod, PRICE_CLOSE);
   m_hBB      = iBands(symbol, tf, bbPeriod, 0, bbDev, PRICE_CLOSE);
   m_hMACD    = iMACD(symbol, tf, macdFast, macdSlow, macdSignal, PRICE_CLOSE);
   m_hStoch   = iStochastic(symbol, tf, stochK, stochD, stochSlowing, MODE_SMA, STO_LOWHIGH);

   if(m_hEMAFast == INVALID_HANDLE || m_hEMASlow == INVALID_HANDLE || m_hHTFEMA == INVALID_HANDLE ||
      m_hRSI == INVALID_HANDLE || m_hBB == INVALID_HANDLE || m_hMACD == INVALID_HANDLE ||
      m_hStoch == INVALID_HANDLE)
     {
      PrintFormat("[AMS] Strategies: インジケーターの作成に失敗 (err=%d)", GetLastError());
      return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
void CStrategySet::Release(void)
  {
   if(m_hEMAFast != INVALID_HANDLE) { IndicatorRelease(m_hEMAFast); m_hEMAFast = INVALID_HANDLE; }
   if(m_hEMASlow != INVALID_HANDLE) { IndicatorRelease(m_hEMASlow); m_hEMASlow = INVALID_HANDLE; }
   if(m_hHTFEMA != INVALID_HANDLE)  { IndicatorRelease(m_hHTFEMA);  m_hHTFEMA = INVALID_HANDLE; }
   if(m_hRSI != INVALID_HANDLE)     { IndicatorRelease(m_hRSI);     m_hRSI = INVALID_HANDLE; }
   if(m_hBB != INVALID_HANDLE)      { IndicatorRelease(m_hBB);      m_hBB = INVALID_HANDLE; }
   if(m_hMACD != INVALID_HANDLE)    { IndicatorRelease(m_hMACD);    m_hMACD = INVALID_HANDLE; }
   if(m_hStoch != INVALID_HANDLE)   { IndicatorRelease(m_hStoch);   m_hStoch = INVALID_HANDLE; }
  }

//+------------------------------------------------------------------+
//| 全ロジックを評価。signals[STRAT_xxx] に -1〜+1 を入れる              |
//+------------------------------------------------------------------+
bool CStrategySet::Evaluate(double &signals[])
  {
   ArrayResize(signals, AMS_STRATEGY_COUNT);
   ArrayInitialize(signals, 0.0);

   if(BarsCalculated(m_hEMASlow) <= 0 || BarsCalculated(m_hMACD) <= 0 ||
      BarsCalculated(m_hStoch) <= 0 || BarsCalculated(m_hHTFEMA) <= 0)
      return(false);

   signals[STRAT_TREND]    = TrendFollow();
   signals[STRAT_BREAKOUT] = Breakout();
   signals[STRAT_MEANREV]  = MeanReversion();
   signals[STRAT_MOMENTUM] = Momentum();
   return(true);
  }

//+------------------------------------------------------------------+
//| 上位足の方向：終値が上位足EMAの上なら +1、下なら -1                    |
//+------------------------------------------------------------------+
int CStrategySet::HTFDirection(void)
  {
   if(!m_useHTFFilter)
      return(0);
   double ema[];
   ArraySetAsSeries(ema, true);
   if(CopyBuffer(m_hHTFEMA, 0, 1, 1, ema) != 1)
      return(0);
   const double close = iClose(m_symbol, m_tf, 1);
   if(close > ema[0])
      return(1);
   if(close < ema[0])
      return(-1);
   return(0);
  }

//+------------------------------------------------------------------+
//| 1. トレンドフォロー：EMAクロス（+1/-1）、並び順の継続（±0.5）          |
//|    上位足の方向に逆らうシグナルは 0 にする                             |
//+------------------------------------------------------------------+
double CStrategySet::TrendFollow(void)
  {
   double fast[], slow[];
   ArraySetAsSeries(fast, true);
   ArraySetAsSeries(slow, true);
   if(CopyBuffer(m_hEMAFast, 0, 1, 2, fast) != 2 || CopyBuffer(m_hEMASlow, 0, 1, 2, slow) != 2)
      return(0.0);

   double signal = 0.0;
   if(fast[1] <= slow[1] && fast[0] > slow[0])
      signal = 1.0;                       // ゴールデンクロス
   else
      if(fast[1] >= slow[1] && fast[0] < slow[0])
         signal = -1.0;                   // デッドクロス
      else
        {
         //--- クロス後の押し目/戻り：並び順どおりで、終値が短期EMAに戻ってきた
         const double close = iClose(m_symbol, m_tf, 1);
         const double low   = iLow(m_symbol, m_tf, 1);
         const double high  = iHigh(m_symbol, m_tf, 1);
         if(fast[0] > slow[0] && low <= fast[0] && close > fast[0])
            signal = 0.5;
         else
            if(fast[0] < slow[0] && high >= fast[0] && close < fast[0])
               signal = -0.5;
        }

   const int htf = HTFDirection();
   if(htf != 0 && signal * htf < 0.0)
      signal = 0.0;
   return(signal);
  }

//+------------------------------------------------------------------+
//| 2. ブレイクアウト：直近 N 本（確定足の1本前まで）の高値/安値を終値で抜けた |
//+------------------------------------------------------------------+
double CStrategySet::Breakout(void)
  {
   const int hiIdx = iHighest(m_symbol, m_tf, MODE_HIGH, m_donchian, 2);
   const int loIdx = iLowest(m_symbol, m_tf, MODE_LOW, m_donchian, 2);
   if(hiIdx < 0 || loIdx < 0)
      return(0.0);

   const double channelHigh = iHigh(m_symbol, m_tf, hiIdx);
   const double channelLow  = iLow(m_symbol, m_tf, loIdx);
   const double close       = iClose(m_symbol, m_tf, 1);

   double signal = 0.0;
   if(close > channelHigh)
      signal = 1.0;
   else
      if(close < channelLow)
         signal = -1.0;

   const int htf = HTFDirection();
   if(htf != 0 && signal * htf < 0.0)
      signal *= 0.5;                      // 上位足に逆らうブレイクは弱める
   return(signal);
  }

//+------------------------------------------------------------------+
//| 3. 逆張り：BBの外側から内側へ戻った（+1/-1）                          |
//|            RSIの売られすぎ/買われすぎからの戻り（±0.5）                |
//+------------------------------------------------------------------+
double CStrategySet::MeanReversion(void)
  {
   double rsi[], upper[], lower[];
   ArraySetAsSeries(rsi, true);
   ArraySetAsSeries(upper, true);
   ArraySetAsSeries(lower, true);
   if(CopyBuffer(m_hRSI, 0, 1, 2, rsi) != 2 ||
      CopyBuffer(m_hBB, 1, 1, 2, upper) != 2 ||
      CopyBuffer(m_hBB, 2, 1, 2, lower) != 2)
      return(0.0);

   const double close1 = iClose(m_symbol, m_tf, 1);
   const double close2 = iClose(m_symbol, m_tf, 2);

   //--- BB下限の外から内へ戻り、RSIも低い → 買い
   if(close2 < lower[1] && close1 > lower[0] && rsi[1] < m_rsiLow + 5.0)
      return(1.0);
   //--- BB上限の外から内へ戻り、RSIも高い → 売り
   if(close2 > upper[1] && close1 < upper[0] && rsi[1] > m_rsiHigh - 5.0)
      return(-1.0);
   //--- RSIのみ：売られすぎ水準を上抜け / 買われすぎ水準を下抜け
   if(rsi[1] < m_rsiLow && rsi[0] >= m_rsiLow)
      return(0.5);
   if(rsi[1] > m_rsiHigh && rsi[0] <= m_rsiHigh)
      return(-0.5);
   return(0.0);
  }

//+------------------------------------------------------------------+
//| 4. モメンタム：MACDヒストグラムの 0 ラインクロス                       |
//|    ストキャスティクスが同じ向きなら ±1、そうでなければ ±0.5            |
//+------------------------------------------------------------------+
double CStrategySet::Momentum(void)
  {
   double macdMain[], macdSig[], stMain[], stSig[];
   ArraySetAsSeries(macdMain, true);
   ArraySetAsSeries(macdSig, true);
   ArraySetAsSeries(stMain, true);
   ArraySetAsSeries(stSig, true);
   if(CopyBuffer(m_hMACD, 0, 1, 2, macdMain) != 2 ||
      CopyBuffer(m_hMACD, 1, 1, 2, macdSig) != 2 ||
      CopyBuffer(m_hStoch, 0, 1, 1, stMain) != 1 ||
      CopyBuffer(m_hStoch, 1, 1, 1, stSig) != 1)
      return(0.0);

   const double hist0 = macdMain[0] - macdSig[0];   // 確定足
   const double hist1 = macdMain[1] - macdSig[1];   // その1本前

   if(hist1 <= 0.0 && hist0 > 0.0)
     {
      if(stMain[0] > stSig[0] && stMain[0] < 80.0)
         return(1.0);
      return(0.5);
     }
   if(hist1 >= 0.0 && hist0 < 0.0)
     {
      if(stMain[0] < stSig[0] && stMain[0] > 20.0)
         return(-1.0);
      return(-0.5);
     }
   return(0.0);
  }

#endif // AMS_STRATEGIES_MQH
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//|                                                   AMS/Regime.mqh |
//|  相場状況（レジーム）の判定                                         |
//|   - ADX           : トレンドの強さ                                 |
//|   - ATR の水準      : ボラティリティ（直近 N 本の中での順位）           |
//|   - BB 幅の水準     : 値幅の収縮/拡大                                |
//|   - EMA50/EMA200 の傾き : トレンドの向き                            |
//+------------------------------------------------------------------+
#ifndef AMS_REGIME_MQH
#define AMS_REGIME_MQH

#include "Common.mqh"

class CRegimeDetector
  {
private:
   string            m_symbol;
   ENUM_TIMEFRAMES   m_tf;
   int               m_hADX;
   int               m_hATR;
   int               m_hBB;
   int               m_hEMAFast;
   int               m_hEMASlow;

   int               m_lookback;       // ATR/BB幅の順位を見る本数
   int               m_slopeBars;      // EMAの傾きを見る本数
   double            m_adxTrend;       // これ以上でトレンド
   double            m_adxRange;       // これ未満でレンジ候補
   double            m_highVolPct;     // ATRの順位がこれ以上で高ボラ
   double            m_rangeBwPct;     // BB幅の順位がこれ以下でレンジ候補

   //--- 直近の判定値（ログ・SL計算用）
   double            m_atr;
   double            m_adx;
   double            m_atrPct;
   double            m_bwPct;
   int               m_trendDir;       // +1 上昇 / -1 下降 / 0 不明

public:
                     CRegimeDetector(void);
                    ~CRegimeDetector(void) { Release(); }

   bool              Init(const string symbol, const ENUM_TIMEFRAMES tf,
                          const int adxPeriod, const int atrPeriod,
                          const int bbPeriod, const double bbDev,
                          const int emaFast, const int emaSlow,
                          const int lookback, const int slopeBars,
                          const double adxTrend, const double adxRange,
                          const double highVolPct, const double rangeBwPct);
   void              Release(void);
   bool              Detect(ENUM_AMS_REGIME &regime);

   double            ATR(void)      const { return(m_atr); }
   double            ADX(void)      const { return(m_adx); }
   double            ATRPct(void)   const { return(m_atrPct); }
   double            BWPct(void)    const { return(m_bwPct); }
   int               TrendDir(void) const { return(m_trendDir); }
  };

//+------------------------------------------------------------------+
CRegimeDetector::CRegimeDetector(void) : m_symbol(""),
                                         m_tf(PERIOD_CURRENT),
                                         m_hADX(INVALID_HANDLE),
                                         m_hATR(INVALID_HANDLE),
                                         m_hBB(INVALID_HANDLE),
                                         m_hEMAFast(INVALID_HANDLE),
                                         m_hEMASlow(INVALID_HANDLE),
                                         m_lookback(100),
                                         m_slopeBars(5),
                                         m_adxTrend(25.0),
                                         m_adxRange(20.0),
                                         m_highVolPct(0.90),
                                         m_rangeBwPct(0.50),
                                         m_atr(0.0),
                                         m_adx(0.0),
                                         m_atrPct(0.5),
                                         m_bwPct(0.5),
                                         m_trendDir(0)
  {
  }

//+------------------------------------------------------------------+
bool CRegimeDetector::Init(const string symbol, const ENUM_TIMEFRAMES tf,
                           const int adxPeriod, const int atrPeriod,
                           const int bbPeriod, const double bbDev,
                           const int emaFast, const int emaSlow,
                           const int lookback, const int slopeBars,
                           const double adxTrend, const double adxRange,
                           const double highVolPct, const double rangeBwPct)
  {
   m_symbol     = symbol;
   m_tf         = tf;
   m_lookback   = MathMax(lookback, 20);
   m_slopeBars  = MathMax(slopeBars, 1);
   m_adxTrend   = adxTrend;
   m_adxRange   = adxRange;
   m_highVolPct = highVolPct;
   m_rangeBwPct = rangeBwPct;

   m_hADX     = iADX(symbol, tf, adxPeriod);
   m_hATR     = iATR(symbol, tf, atrPeriod);
   m_hBB      = iBands(symbol, tf, bbPeriod, 0, bbDev, PRICE_CLOSE);
   m_hEMAFast = iMA(symbol, tf, emaFast, 0, MODE_EMA, PRICE_CLOSE);
   m_hEMASlow = iMA(symbol, tf, emaSlow, 0, MODE_EMA, PRICE_CLOSE);

   if(m_hADX == INVALID_HANDLE || m_hATR == INVALID_HANDLE || m_hBB == INVALID_HANDLE ||
      m_hEMAFast == INVALID_HANDLE || m_hEMASlow == INVALID_HANDLE)
     {
      PrintFormat("[AMS] Regime: インジケーターの作成に失敗 (err=%d)", GetLastError());
      return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
void CRegimeDetector::Release(void)
  {
   if(m_hADX != INVALID_HANDLE)     { IndicatorRelease(m_hADX);     m_hADX = INVALID_HANDLE; }
   if(m_hATR != INVALID_HANDLE)     { IndicatorRelease(m_hATR);     m_hATR = INVALID_HANDLE; }
   if(m_hBB != INVALID_HANDLE)      { IndicatorRelease(m_hBB);      m_hBB = INVALID_HANDLE; }
   if(m_hEMAFast != INVALID_HANDLE) { IndicatorRelease(m_hEMAFast); m_hEMAFast = INVALID_HANDLE; }
   if(m_hEMASlow != INVALID_HANDLE) { IndicatorRelease(m_hEMASlow); m_hEMASlow = INVALID_HANDLE; }
  }

//+------------------------------------------------------------------+
//| 確定足（shift=1）を基準に相場状況を判定する                          |
//+------------------------------------------------------------------+
bool CRegimeDetector::Detect(ENUM_AMS_REGIME &regime)
  {
   regime = REGIME_NEUTRAL;

   double adx[], atr[], upper[], lower[], middle[], emaF[], emaS[];
   ArraySetAsSeries(adx, true);
   ArraySetAsSeries(atr, true);
   ArraySetAsSeries(upper, true);
   ArraySetAsSeries(lower, true);
   ArraySetAsSeries(middle, true);
   ArraySetAsSeries(emaF, true);
   ArraySetAsSeries(emaS, true);

   const int n = m_lookback;
   if(CopyBuffer(m_hADX, 0, 1, 1, adx) != 1)                     return(false);
   if(CopyBuffer(m_hATR, 0, 1, n, atr) != n)                     return(false);
   if(CopyBuffer(m_hBB, 0, 1, n, middle) != n)                   return(false);
   if(CopyBuffer(m_hBB, 1, 1, n, upper) != n)                    return(false);
   if(CopyBuffer(m_hBB, 2, 1, n, lower) != n)                    return(false);
   if(CopyBuffer(m_hEMAFast, 0, 1, m_slopeBars + 1, emaF) != m_slopeBars + 1) return(false);
   if(CopyBuffer(m_hEMASlow, 0, 1, m_slopeBars + 1, emaS) != m_slopeBars + 1) return(false);

   double width[];
   ArrayResize(width, n);
   for(int i = 0; i < n; i++)
      width[i] = (middle[i] > 0.0) ? (upper[i] - lower[i]) / middle[i] : 0.0;

   m_adx    = adx[0];
   m_atr    = atr[0];
   m_atrPct = PercentRank(atr, n, atr[0]);
   m_bwPct  = PercentRank(width, n, width[0]);

   //--- トレンドの向き：EMA50とEMA200の傾きと、終値の位置がそろっているか
   const double close     = iClose(m_symbol, m_tf, 1);
   const double slopeFast = emaF[0] - emaF[m_slopeBars];
   const double slopeSlow = emaS[0] - emaS[m_slopeBars];
   m_trendDir = 0;
   if(slopeFast > 0.0 && slopeSlow > 0.0 && close > emaS[0] && emaF[0] > emaS[0])
      m_trendDir = 1;
   else
      if(slopeFast < 0.0 && slopeSlow < 0.0 && close < emaS[0] && emaF[0] < emaS[0])
         m_trendDir = -1;

   //--- 判定（高ボラ → トレンド → レンジ → 中立 の優先順）
   if(m_atrPct >= m_highVolPct)
      regime = REGIME_HIGHVOL;
   else
      if(m_adx >= m_adxTrend && m_trendDir != 0)
         regime = REGIME_TREND;
      else
         if(m_adx < m_adxRange && m_bwPct <= m_rangeBwPct)
            regime = REGIME_RANGE;
         else
            regime = REGIME_NEUTRAL;

   return(true);
  }

#endif // AMS_REGIME_MQH
//+------------------------------------------------------------------+

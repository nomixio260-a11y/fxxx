//+------------------------------------------------------------------+
//|                                                  AMS/Modules.mqh |
//|  単独で検証するためのエントリー方式（InpEntryMode で選ぶ）              |
//|   - 日足トレンドフォロー：直近N日の高値/安値抜けで順張り                 |
//|   - ロンドン・ブレイクアウト：アジア時間のレンジを抜けたら順張り           |
//|   - 押し目買い/戻り売り：日足の方向に合わせ、RSIの戻りで入る             |
//|   - アジア時間の逆張り：値動きの小さい時間帯だけ逆張り                   |
//|                                                                  |
//|  時間帯は「ニューヨーク時間」で指定する。                              |
//|  サーバー時間とのずれは、週明けの最初の足の時刻（NY 17:00）から自動で     |
//|  求めるので、サーバーのタイムゾーンや夏時間の設定は不要。                 |
//+------------------------------------------------------------------+
#ifndef AMS_MODULES_MQH
#define AMS_MODULES_MQH

#include "Common.mqh"

class CModuleSet
  {
private:
   string            m_symbol;
   ENUM_TIMEFRAMES   m_tf;
   ENUM_AMS_ENTRY_MODE m_mode;

   int               m_hRSI;          // 押し目用 RSI
   int               m_hEmaFast;      // 押し目用 日足EMA（短）
   int               m_hEmaSlow;      // 押し目用 日足EMA（長）

   int               m_dtEntry;       // 日足トレンド：エントリーに使う日数
   int               m_dtExit;        // 日足トレンド：決済に使う日数
   int               m_asiaStart;     // アジア時間の開始（NY時）
   int               m_londonOpen;    // ロンドン開始（NY時）
   int               m_lbEntryEnd;    // ロンドン・ブレイクアウトのエントリー終了（NY時）
   int               m_lbExit;        // ロンドン・ブレイクアウトの決済（NY時）
   int               m_asiaMREnd;     // アジア時間の逆張りのエントリー終了（NY時）
   double            m_pbLow;         // 押し目：RSI の下の基準
   double            m_pbHigh;        // 戻り　：RSI の上の基準

   int               m_openTOD;       // 週明けの最初の足の「サーバー時間の0時からの秒数」。不明なら -1
   datetime          m_openChecked;
   long              m_lastEntryDay;  // 最後にエントリーした取引日（1日1回に制限するため）

   void              UpdateWeeklyOpen(void);
   bool              HourIn(const int h, const int from, const int to) const;
   long              NYDay(const datetime t) const;
   double            DailyTrend(void);
   double            LondonBreakout(void);
   double            Pullback(void);

public:
                     CModuleSet(void);
                    ~CModuleSet(void) { Release(); }

   bool              Init(const string symbol, const ENUM_TIMEFRAMES tf, const ENUM_AMS_ENTRY_MODE mode,
                          const int dtEntry, const int dtExit,
                          const int asiaStart, const int londonOpen, const int lbEntryEnd, const int lbExit,
                          const int asiaMREnd,
                          const int rsiPeriod, const double pbLow, const double pbHigh,
                          const int pbEmaFast, const int pbEmaSlow);
   void              Release(void);
   int               NYHour(const datetime t) const;
   int               OpenTOD(void) const { return(m_openTOD); }
   double            EntrySignal(const double meanRevSignal);
   bool              ExitSignal(const ENUM_POSITION_TYPE type);
   void              MarkEntered(void);
  };

//+------------------------------------------------------------------+
CModuleSet::CModuleSet(void) : m_symbol(""),
                               m_tf(PERIOD_CURRENT),
                               m_mode(ENTRY_WEIGHTED),
                               m_hRSI(INVALID_HANDLE),
                               m_hEmaFast(INVALID_HANDLE),
                               m_hEmaSlow(INVALID_HANDLE),
                               m_dtEntry(55),
                               m_dtExit(20),
                               m_asiaStart(19),
                               m_londonOpen(3),
                               m_lbEntryEnd(7),
                               m_lbExit(12),
                               m_asiaMREnd(1),
                               m_pbLow(40.0),
                               m_pbHigh(60.0),
                               m_openTOD(-1),
                               m_openChecked(0),
                               m_lastEntryDay(-1)
  {
  }

//+------------------------------------------------------------------+
bool CModuleSet::Init(const string symbol, const ENUM_TIMEFRAMES tf, const ENUM_AMS_ENTRY_MODE mode,
                      const int dtEntry, const int dtExit,
                      const int asiaStart, const int londonOpen, const int lbEntryEnd, const int lbExit,
                      const int asiaMREnd,
                      const int rsiPeriod, const double pbLow, const double pbHigh,
                      const int pbEmaFast, const int pbEmaSlow)
  {
   m_symbol     = symbol;
   m_tf         = tf;
   m_mode       = mode;
   m_dtEntry    = MathMax(dtEntry, 2);
   m_dtExit     = MathMax(dtExit, 2);
   m_asiaStart  = asiaStart;
   m_londonOpen = londonOpen;
   m_lbEntryEnd = lbEntryEnd;
   m_lbExit     = lbExit;
   m_asiaMREnd  = asiaMREnd;
   m_pbLow      = pbLow;
   m_pbHigh     = pbHigh;

   if(mode == ENTRY_PULLBACK)
     {
      m_hRSI     = iRSI(symbol, tf, rsiPeriod, PRICE_CLOSE);
      m_hEmaFast = iMA(symbol, PERIOD_D1, pbEmaFast, 0, MODE_EMA, PRICE_CLOSE);
      m_hEmaSlow = iMA(symbol, PERIOD_D1, pbEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
      if(m_hRSI == INVALID_HANDLE || m_hEmaFast == INVALID_HANDLE || m_hEmaSlow == INVALID_HANDLE)
        {
         PrintFormat("[AMS] Modules: インジケーターの作成に失敗 (err=%d)", GetLastError());
         return(false);
        }
     }
   UpdateWeeklyOpen();
   return(true);
  }

//+------------------------------------------------------------------+
void CModuleSet::Release(void)
  {
   if(m_hRSI != INVALID_HANDLE)     { IndicatorRelease(m_hRSI);     m_hRSI = INVALID_HANDLE; }
   if(m_hEmaFast != INVALID_HANDLE) { IndicatorRelease(m_hEmaFast); m_hEmaFast = INVALID_HANDLE; }
   if(m_hEmaSlow != INVALID_HANDLE) { IndicatorRelease(m_hEmaSlow); m_hEmaSlow = INVALID_HANDLE; }
  }

//+------------------------------------------------------------------+
//| 週明けの最初の足の時刻を調べる（1日1回）。                             |
//| FX は NY 17:00 に週が始まるので、この時刻が「NY 17:00」に当たる。         |
//+------------------------------------------------------------------+
void CModuleSet::UpdateWeeklyOpen(void)
  {
   if(m_openTOD >= 0 && TimeCurrent() - m_openChecked < 86400)
      return;
   datetime times[];
   const int n = CopyTime(m_symbol, PERIOD_H1, 0, 500, times);
   if(n < 50)
      return;
   for(int i = n - 1; i > 0; i--)
     {
      //--- 40時間以上あいていれば週末（祝日の休みはこれより短い）
      if(times[i] - times[i - 1] >= 40 * 3600)
        {
         m_openTOD = (int)((long)times[i] % 86400);
         break;
        }
     }
   m_openChecked = TimeCurrent();
  }

//+------------------------------------------------------------------+
//| サーバー時間 t の、ニューヨーク時間での「時」（0〜23）。不明なら -1       |
//+------------------------------------------------------------------+
int CModuleSet::NYHour(const datetime t) const
  {
   if(m_openTOD < 0)
      return(-1);
   const long sec = (((long)t % 86400) - m_openTOD + 86400) % 86400;   // NY 17:00 からの秒数
   return((int)((sec / 3600 + 17) % 24));
  }

//+------------------------------------------------------------------+
//| 取引日の通し番号（NY 17:00 で日付が変わる）                           |
//+------------------------------------------------------------------+
long CModuleSet::NYDay(const datetime t) const
  {
   return(((long)t - m_openTOD) / 86400);
  }

//+------------------------------------------------------------------+
//| h が [from, to) の時間帯に入っているか（日付をまたぐ指定も可）           |
//+------------------------------------------------------------------+
bool CModuleSet::HourIn(const int h, const int from, const int to) const
  {
   if(h < 0 || from == to)
      return(false);
   if(from < to)
      return(h >= from && h < to);
   return(h >= from || h < to);
  }

//+------------------------------------------------------------------+
void CModuleSet::MarkEntered(void)
  {
   const datetime t = iTime(m_symbol, m_tf, 1);
   if(t > 0 && m_openTOD >= 0)
      m_lastEntryDay = NYDay(t);
  }

//+------------------------------------------------------------------+
//| エントリーのシグナル（確定足で判定）。+1 買い / -1 売り / 0 なし         |
//| アジア時間の逆張りは、既存の逆張りシグナル（±0.5 / ±1）をそのまま返す     |
//+------------------------------------------------------------------+
double CModuleSet::EntrySignal(const double meanRevSignal)
  {
   UpdateWeeklyOpen();
   switch(m_mode)
     {
      case ENTRY_DAILY_TREND:
         return(DailyTrend());
      case ENTRY_LONDON_BO:
         return(LondonBreakout());
      case ENTRY_PULLBACK:
         return(Pullback());
      case ENTRY_ASIA_MR:
        {
         const int h = NYHour(iTime(m_symbol, m_tf, 0));
         return(HourIn(h, m_asiaStart, m_asiaMREnd) ? meanRevSignal : 0.0);
        }
      default:
         return(0.0);
     }
  }

//+------------------------------------------------------------------+
//| ロジックごとの決済条件（新しい足ごとに判定）                            |
//+------------------------------------------------------------------+
bool CModuleSet::ExitSignal(const ENUM_POSITION_TYPE type)
  {
   UpdateWeeklyOpen();
   const int h = NYHour(iTime(m_symbol, m_tf, 0));
   switch(m_mode)
     {
      case ENTRY_LONDON_BO:
         //--- 当日中（NY の昼〜引け）に決済する
         return(HourIn(h, m_lbExit, 17));
      case ENTRY_ASIA_MR:
         //--- ロンドンが始まったら決済する
         return(HourIn(h, m_londonOpen, m_asiaStart));
      case ENTRY_DAILY_TREND:
        {
         const double close = iClose(m_symbol, m_tf, 1);
         if(type == POSITION_TYPE_BUY)
           {
            const int loIdx = iLowest(m_symbol, m_tf, MODE_LOW, m_dtExit, 2);
            return(loIdx >= 0 && close < iLow(m_symbol, m_tf, loIdx));
           }
         const int hiIdx = iHighest(m_symbol, m_tf, MODE_HIGH, m_dtExit, 2);
         return(hiIdx >= 0 && close > iHigh(m_symbol, m_tf, hiIdx));
        }
      default:
         return(false);
     }
  }

//+------------------------------------------------------------------+
//| 日足トレンドフォロー：直近 N 本の高値/安値を終値で抜けた                 |
//+------------------------------------------------------------------+
double CModuleSet::DailyTrend(void)
  {
   if(Bars(m_symbol, m_tf) < m_dtEntry + 3)
      return(0.0);
   const int hiIdx = iHighest(m_symbol, m_tf, MODE_HIGH, m_dtEntry, 2);
   const int loIdx = iLowest(m_symbol, m_tf, MODE_LOW, m_dtEntry, 2);
   if(hiIdx < 0 || loIdx < 0)
      return(0.0);
   const double close = iClose(m_symbol, m_tf, 1);
   if(close > iHigh(m_symbol, m_tf, hiIdx))
      return(1.0);
   if(close < iLow(m_symbol, m_tf, loIdx))
      return(-1.0);
   return(0.0);
  }

//+------------------------------------------------------------------+
//| ロンドン・ブレイクアウト：                                           |
//|  その取引日のアジア時間の高値/安値を、ロンドン時間の確定足が抜けた        |
//|  1銘柄につき1日1回まで                                              |
//+------------------------------------------------------------------+
double CModuleSet::LondonBreakout(void)
  {
   const datetime sig = iTime(m_symbol, m_tf, 1);
   if(sig == 0 || m_openTOD < 0)
      return(0.0);
   if(!HourIn(NYHour(sig), m_londonOpen, m_lbEntryEnd))
      return(0.0);
   const long day = NYDay(sig);
   if(day == m_lastEntryDay)
      return(0.0);

   const int barSec  = PeriodSeconds(m_tf);
   const int maxBars = 86400 / barSec + 2;
   double hi = -DBL_MAX, lo = DBL_MAX;
   int    count = 0;
   for(int i = 2; i <= maxBars; i++)
     {
      const datetime t = iTime(m_symbol, m_tf, i);
      if(t == 0 || NYDay(t) != day)
         break;
      if(!HourIn(NYHour(t), m_asiaStart, m_londonOpen))
         continue;
      hi = MathMax(hi, iHigh(m_symbol, m_tf, i));
      lo = MathMin(lo, iLow(m_symbol, m_tf, i));
      count++;
     }
   //--- アジア時間の足が4時間分に満たない日（祝日など）は見送る
   if(count * barSec < 4 * 3600)
      return(0.0);

   const double close = iClose(m_symbol, m_tf, 1);
   if(close > hi)
      return(1.0);
   if(close < lo)
      return(-1.0);
   return(0.0);
  }

//+------------------------------------------------------------------+
//| 押し目買い/戻り売り：                                               |
//|  日足が上向き（EMA短 > EMA長、終値が EMA長 の上）で、                   |
//|  RSI が基準を下から上に抜けたら買い。下向きはその逆。                    |
//+------------------------------------------------------------------+
double CModuleSet::Pullback(void)
  {
   double rsi[], ef[], es[];
   ArraySetAsSeries(rsi, true);
   ArraySetAsSeries(ef, true);
   ArraySetAsSeries(es, true);
   if(CopyBuffer(m_hRSI, 0, 1, 2, rsi) != 2 ||
      CopyBuffer(m_hEmaFast, 0, 1, 1, ef) != 1 ||
      CopyBuffer(m_hEmaSlow, 0, 1, 1, es) != 1)
      return(0.0);
   const double close = iClose(m_symbol, m_tf, 1);
   if(ef[0] > es[0] && close > es[0] && rsi[1] < m_pbLow && rsi[0] >= m_pbLow)
      return(1.0);
   if(ef[0] < es[0] && close < es[0] && rsi[1] > m_pbHigh && rsi[0] <= m_pbHigh)
      return(-1.0);
   return(0.0);
  }

#endif // AMS_MODULES_MQH
//+------------------------------------------------------------------+

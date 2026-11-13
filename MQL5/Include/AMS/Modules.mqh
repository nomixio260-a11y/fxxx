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

//--- 東京の銀行の休業日（日本の祝日・振替休日、1/2・1/3・12/31）。2015〜2028年。
//    これ以外の年や臨時の休日は、入力 InpJPHolidays で追加する。
const int AMS_JP_HOLIDAYS[] =
  {
   20150101, 20150102, 20150103, 20150112, 20150211, 20150321, 20150429, 20150503, 20150504, 20150505,
   20150506, 20150720, 20150921, 20150922, 20150923, 20151012, 20151103, 20151123, 20151223, 20151231,
   20160101, 20160103, 20160111, 20160211, 20160320, 20160321, 20160429, 20160503, 20160504, 20160505,
   20160718, 20160811, 20160919, 20160922, 20161010, 20161103, 20161123, 20161223, 20161231, 20170101,
   20170102, 20170103, 20170109, 20170211, 20170320, 20170429, 20170503, 20170504, 20170505, 20170717,
   20170811, 20170918, 20170923, 20171009, 20171103, 20171123, 20171223, 20171231, 20180101, 20180102,
   20180103, 20180108, 20180211, 20180212, 20180321, 20180429, 20180430, 20180503, 20180504, 20180505,
   20180716, 20180811, 20180917, 20180923, 20180924, 20181008, 20181103, 20181123, 20181223, 20181224,
   20181231, 20190101, 20190102, 20190103, 20190114, 20190211, 20190321, 20190429, 20190430, 20190501,
   20190502, 20190503, 20190504, 20190505, 20190506, 20190715, 20190811, 20190812, 20190916, 20190923,
   20191014, 20191022, 20191103, 20191104, 20191123, 20191231, 20200101, 20200102, 20200103, 20200113,
   20200211, 20200223, 20200224, 20200320, 20200429, 20200503, 20200504, 20200505, 20200506, 20200723,
   20200724, 20200810, 20200921, 20200922, 20201103, 20201123, 20201231, 20210101, 20210103, 20210111,
   20210211, 20210223, 20210320, 20210429, 20210503, 20210504, 20210505, 20210722, 20210723, 20210808,
   20210809, 20210920, 20210923, 20211103, 20211123, 20211231, 20220101, 20220103, 20220110, 20220211,
   20220223, 20220321, 20220429, 20220503, 20220504, 20220505, 20220718, 20220811, 20220919, 20220923,
   20221010, 20221103, 20221123, 20221231, 20230101, 20230102, 20230103, 20230109, 20230211, 20230223,
   20230321, 20230429, 20230503, 20230504, 20230505, 20230717, 20230811, 20230918, 20230923, 20231009,
   20231103, 20231123, 20231231, 20240101, 20240102, 20240103, 20240108, 20240211, 20240212, 20240223,
   20240320, 20240429, 20240503, 20240504, 20240505, 20240506, 20240715, 20240811, 20240812, 20240916,
   20240922, 20240923, 20241014, 20241103, 20241104, 20241123, 20241231, 20250101, 20250102, 20250103,
   20250113, 20250211, 20250223, 20250224, 20250320, 20250429, 20250503, 20250504, 20250505, 20250506,
   20250721, 20250811, 20250915, 20250923, 20251013, 20251103, 20251123, 20251124, 20251231, 20260101,
   20260102, 20260103, 20260112, 20260211, 20260223, 20260320, 20260429, 20260503, 20260504, 20260505,
   20260506, 20260720, 20260811, 20260921, 20260922, 20260923, 20261012, 20261103, 20261123, 20261231,
   20270101, 20270102, 20270103, 20270111, 20270211, 20270223, 20270321, 20270322, 20270429, 20270503,
   20270504, 20270505, 20270719, 20270811, 20270920, 20270923, 20271011, 20271103, 20271123, 20271231,
   20280101, 20280102, 20280103, 20280110, 20280211, 20280223, 20280320, 20280429, 20280503, 20280504,
   20280505, 20280717, 20280811, 20280918, 20280922, 20281009, 20281103, 20281123, 20281231
  };

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

   int               m_fixEntry;      // 東京仲値：エントリー時刻（東京時間 HHMM）
   int               m_fixExit;       // 東京仲値：決済時刻（東京時間 HHMM）
   bool              m_fixGotobiOnly; // 東京仲値：ゴトー日だけ取引する
   int               m_fixDir;        // 東京仲値：+1 買い / -1 売り

   //--- 時刻ルール（ENTRY_CALENDAR）。この銘柄に当てはまるルールだけを持つ
   int               m_ruleCount;
   int               m_ruleClock[];   // 0 = 東京, 1 = ロンドン, 2 = ニューヨーク
   int               m_ruleHHMM[];    // 入る時刻（現地時間 HHMM）
   int               m_ruleHold[];    // 保有時間（分）
   int               m_ruleDir[];     // +1 買い / -1 売り
   int               m_ruleFilter[];  // 日の条件（下の RULE_* ）
   double            m_ruleSL[];      // SL（pips）
   int               m_rulePreMin[];  // 直前の値動きの条件：何分前からの値動きを見るか（0 = 条件なし）
   double            m_rulePreThr[];  // その値動き（1時間足の平均値幅で割った値）がこれより大きいときだけ入る
   bool              m_rulePreBelow[]; // true のときは「これより小さいときだけ入る」（"PRE30:<-0.37"）
   string            m_ruleName[];
   int               m_rulePrio[];    // 優先順位（入力に書いた順。小さいほど先に注文する）
   int               m_pendRule;      // シグナルを出したルール（エントリー待ち）
   int               m_activeRule;    // 保有中のポジションのルール
   datetime          m_activeUntil;   // 保有中のポジションを決済する時刻（サーバー時間）

   void              UpdateWeeklyOpen(void);
   bool              HourIn(const int h, const int from, const int to) const;
   long              NYDay(const datetime t) const;
   double            DailyTrend(void);
   double            LondonBreakout(void);
   double            Pullback(void);
   double            TokyoFix(void);
   bool              IsUSDST(const datetime t) const;
   bool              IsGotobiTarget(const datetime tokyo) const;
   bool              IsGotobi(const datetime tokyo) const;
   bool              IsTokyoBusinessDay(const datetime tokyo) const;
   int               m_extraHolidays[];   // 入力で追加した休業日（YYYYMMDD）
   int               TokyoHHMM(const datetime tokyo) const;
   datetime          UTCTime(const datetime serverTime) const;
   bool              IsUKDST(const datetime utc) const;
   datetime          LocalTime(const datetime serverTime, const int clock) const;
   bool              RuleDayOK(const int filter, const datetime local, const int clock) const;
   double            CalendarSignal(void);

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
   void              SetTokyoFix(const int entryHHMM, const int exitHHMM, const bool gotobiOnly, const int dir);
   void              AddHolidays(const string list);
   int               SetRules(const string rules);
   double            PendingRuleSL(void) const { return(m_pendRule >= 0 ? m_ruleSL[m_pendRule] : 0.0); }
   bool              PreMoveOK(const int minutes, const double thr, const bool below) const;
   string            PendingRuleName(void) const { return(m_pendRule >= 0 ? m_ruleName[m_pendRule] : ""); }
   int               PendingRulePrio(void) const { return(m_pendRule >= 0 ? m_rulePrio[m_pendRule] : 1000000); }
   datetime          TokyoTime(const datetime serverTime) const;
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
                               m_lastEntryDay(-1),
                               m_fixEntry(800),
                               m_fixExit(955),
                               m_fixGotobiOnly(true),
                               m_fixDir(1),
                               m_ruleCount(0),
                               m_pendRule(-1),
                               m_activeRule(-1),
                               m_activeUntil(0)
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
   if(m_mode == ENTRY_CALENDAR && m_pendRule >= 0)
     {
      //--- 決済の時刻 = シグナルを出した足の始まり + 保有時間
      m_activeRule  = m_pendRule;
      m_activeUntil = iTime(m_symbol, m_tf, 0) + m_ruleHold[m_pendRule] * 60;
     }
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
      case ENTRY_TOKYO_FIX:
         return(TokyoFix());
      case ENTRY_CALENDAR:
         return(CalendarSignal());
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
      case ENTRY_CALENDAR:
         //--- ルールの保有時間が過ぎたら決済する（決済時刻が不明なポジションも決済する）
         return(m_activeUntil == 0 || iTime(m_symbol, m_tf, 0) >= m_activeUntil);
      case ENTRY_LONDON_BO:
         //--- 当日中（NY の昼〜引け）に決済する
         return(HourIn(h, m_lbExit, 17));
      case ENTRY_ASIA_MR:
         //--- ロンドンが始まったら決済する
         return(HourIn(h, m_londonOpen, m_asiaStart));
      case ENTRY_TOKYO_FIX:
        {
         //--- 保有してよい時間帯（エントリー時刻〜決済時刻）を外れたら決済する
         if(m_openTOD < 0)
            return(true);
         const int hhmm = TokyoHHMM(TokyoTime(iTime(m_symbol, m_tf, 0)));
         return(!(hhmm >= m_fixEntry && hhmm < m_fixExit));
        }
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

//+------------------------------------------------------------------+
void CModuleSet::SetTokyoFix(const int entryHHMM, const int exitHHMM, const bool gotobiOnly, const int dir)
  {
   m_fixEntry      = entryHHMM;
   m_fixExit       = exitHHMM;
   m_fixGotobiOnly = gotobiOnly;
   m_fixDir        = (dir >= 0) ? 1 : -1;
  }

//+------------------------------------------------------------------+
//| アメリカの夏時間か（3月第2日曜〜11月第1日曜。日付単位で判定）            |
//+------------------------------------------------------------------+
bool CModuleSet::IsUSDST(const datetime t) const
  {
   MqlDateTime dt, m;
   TimeToStruct(t, dt);
   //--- 3月8日が何曜日かを調べ、第2日曜の日付を求める
   m.year = dt.year; m.mon = 3; m.day = 8; m.hour = 0; m.min = 0; m.sec = 0;
   m.day_of_week = 0; m.day_of_year = 0;
   MqlDateTime w;
   TimeToStruct(StructToTime(m), w);
   const int marSecondSun = 8 + (7 - w.day_of_week) % 7;
   //--- 11月1日が何曜日かを調べ、第1日曜の日付を求める
   m.mon = 11; m.day = 1;
   TimeToStruct(StructToTime(m), w);
   const int novFirstSun = 1 + (7 - w.day_of_week) % 7;

   const int md = dt.mon * 100 + dt.day;
   return(md >= 300 + marSecondSun && md < 1100 + novFirstSun);
  }

//+------------------------------------------------------------------+
//| サーバー時間を東京時間に直す。                                        |
//|  週明けの最初の足（NY 17:00）は、UTC では「前日の」冬 22:00 / 夏 21:00。   |
//|  東京は UTC+9（夏時間なし）。                                         |
//|  例）サーバー 0:00 が NY 17:00 の場合、東京はサーバー +7時間（夏は +6時間） |
//+------------------------------------------------------------------+
datetime CModuleSet::TokyoTime(const datetime serverTime) const
  {
   const int nyCloseUTC = IsUSDST(serverTime) ? 21 : 22;
   return((datetime)((long)serverTime - m_openTOD + (nyCloseUTC + 9 - 24) * 3600));
  }

//+------------------------------------------------------------------+
int CModuleSet::TokyoHHMM(const datetime tokyo) const
  {
   MqlDateTime dt;
   TimeToStruct(tokyo, dt);
   return(dt.hour * 100 + dt.min);
  }

//+------------------------------------------------------------------+
//| ゴトー日の対象日か：5・10・15・20・25・30日と月末                      |
//+------------------------------------------------------------------+
bool CModuleSet::IsGotobiTarget(const datetime tokyo) const
  {
   MqlDateTime dt, next;
   TimeToStruct(tokyo, dt);
   if(dt.day % 5 == 0)
      return(true);
   TimeToStruct(tokyo + 86400, next);
   return(next.mon != dt.mon);     // 月末
  }

//+------------------------------------------------------------------+
//| 入力で追加の休業日を受け取る（"2027.01.01,2027.01.11" の形式）          |
//+------------------------------------------------------------------+
void CModuleSet::AddHolidays(const string list)
  {
   string parts[];
   const int n = StringSplit(list, ',', parts);
   for(int i = 0; i < n; i++)
     {
      string d = parts[i];
      StringTrimLeft(d);
      StringTrimRight(d);
      StringReplace(d, ".", "");
      StringReplace(d, "-", "");
      StringReplace(d, "/", "");
      if(StringLen(d) != 8)
         continue;
      const int v = (int)StringToInteger(d);
      const int k = ArraySize(m_extraHolidays);
      ArrayResize(m_extraHolidays, k + 1);
      m_extraHolidays[k] = v;
     }
  }

//+------------------------------------------------------------------+
//| 東京の銀行の営業日か（土日・祝日・年末年始を除く）                      |
//+------------------------------------------------------------------+
bool CModuleSet::IsTokyoBusinessDay(const datetime tokyo) const
  {
   MqlDateTime dt;
   TimeToStruct(tokyo, dt);
   if(dt.day_of_week == 0 || dt.day_of_week == 6)
      return(false);
   const int key = dt.year * 10000 + dt.mon * 100 + dt.day;
   for(int i = 0; i < ArraySize(AMS_JP_HOLIDAYS); i++)
      if(AMS_JP_HOLIDAYS[i] == key)
         return(false);
   for(int i = 0; i < ArraySize(m_extraHolidays); i++)
      if(m_extraHolidays[i] == key)
         return(false);
   return(true);
  }

//+------------------------------------------------------------------+
//| 今日がゴトー日か。                                                  |
//|  対象日（5・10・15・20・25・30日と月末）が休業日のときは、               |
//|  直前の営業日に前倒しする（土日だけでなく、日本の祝日も考慮する）。         |
//+------------------------------------------------------------------+
bool CModuleSet::IsGotobi(const datetime tokyo) const
  {
   if(!IsTokyoBusinessDay(tokyo))
      return(false);
   if(IsGotobiTarget(tokyo))
      return(true);
   //--- 翌日から次の営業日の前日までに対象日があれば、今日に前倒しされる
   for(int k = 1; k <= 10; k++)
     {
      const datetime d = tokyo + k * 86400;
      if(IsTokyoBusinessDay(d))
         break;
      if(IsGotobiTarget(d))
         return(true);
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| 東京仲値：決まった時刻（東京時間）に入り、決まった時刻に決済する          |
//|  例）ゴトー日の 8:00 に買い、仲値の 9:55 に決済                        |
//+------------------------------------------------------------------+
double CModuleSet::TokyoFix(void)
  {
   if(m_openTOD < 0)
      return(0.0);
   const datetime now   = iTime(m_symbol, m_tf, 0);
   const datetime tokyo = TokyoTime(now);
   if(TokyoHHMM(tokyo) != m_fixEntry)
      return(0.0);
   if(m_fixGotobiOnly && !IsGotobi(tokyo))
      return(0.0);
   //--- 東京が休業日の日は仲値が無いので取引しない
   if(!IsTokyoBusinessDay(tokyo))
      return(0.0);
   return((double)m_fixDir);
  }

//+------------------------------------------------------------------+
//| 時刻ルールを読み込む（この銘柄のものだけ）。                            |
//| 書式："名前:銘柄|時計|HHMM|保有分|向き|日の条件|SLpips" を ; で区切る     |
//|   （| の代わりに , 、; の代わりに / でもよい）                          |
//|   時計：TKY / LDN / NY    向き：BUY / SELL                            |
//|   日の条件：ALL / GOTOBI / MONTHEND / MONTHSTART / MON〜FRI            |
//|   8つ目（任意）：PRE30:-0.07 ＝ 直前30分の値動き÷1時間足の平均値幅>-0.07 |
//|                  PRE30:<-0.37 ＝ 同じ値が -0.37 より小さいとき            |
//|   例）"R1:EURUSD|NY|0200|360|SELL|ALL|25;R2:USDJPY|TKY|0955|125|SELL|GOTOBI|30" |
//| 戻り値：読み込んだルールの数                                           |
//+------------------------------------------------------------------+
#define RULE_ALL        0
#define RULE_GOTOBI     1
#define RULE_MONTHEND   2
#define RULE_MONTHSTART 3
#define RULE_DOW_BASE   10   // 10 + 曜日（1 = 月 〜 5 = 金）

int CModuleSet::SetRules(const string rules)
  {
   m_ruleCount = 0;
   //--- テスターの設定ファイルでは | と ; が使えないので、区切りに , と / も受け付ける
   string all = rules;
   StringReplace(all, "/", ";");
   string items[];
   const int n = StringSplit(all, ';', items);
   for(int i = 0; i < n; i++)
     {
      string item = items[i];
      StringTrimLeft(item);
      StringTrimRight(item);
      if(item == "")
         continue;
      string name = StringFormat("R%d", i + 1);
      const int colon = StringFind(item, ":");
      if(colon > 0)
        {
         name = StringSubstr(item, 0, colon);
         item = StringSubstr(item, colon + 1);
        }
      StringReplace(item, ",", "|");
      string f[];
      const int nf = StringSplit(item, '|', f);
      if(nf != 7 && nf != 8)
        {
         PrintFormat("[AMS] 時刻ルールの書式が正しくありません: %s", items[i]);
         continue;
        }
      for(int k = 0; k < nf; k++)
        {
         StringTrimLeft(f[k]);
         StringTrimRight(f[k]);
         StringToUpper(f[k]);
        }
      //--- 銘柄名は接尾辞（.oj1m など）を無視して比べる
      if(StringFind(m_symbol, f[0]) != 0)
         continue;
      int clock = -1;
      if(f[1] == "TKY") clock = 0;
      if(f[1] == "LDN") clock = 1;
      if(f[1] == "NY")  clock = 2;
      int filter = -1;
      if(f[5] == "ALL")        filter = RULE_ALL;
      if(f[5] == "GOTOBI")     filter = RULE_GOTOBI;
      if(f[5] == "MONTHEND")   filter = RULE_MONTHEND;
      if(f[5] == "MONTHSTART") filter = RULE_MONTHSTART;
      const string dows[5] = {"MON", "TUE", "WED", "THU", "FRI"};
      for(int k = 0; k < 5; k++)
         if(f[5] == dows[k])
            filter = RULE_DOW_BASE + k + 1;
      const int dir = (f[4] == "BUY") ? 1 : ((f[4] == "SELL") ? -1 : 0);
      if(clock < 0 || filter < 0 || dir == 0)
        {
         PrintFormat("[AMS] 時刻ルールの値が正しくありません: %s", items[i]);
         continue;
        }
      const int k = m_ruleCount++;
      ArrayResize(m_ruleClock, m_ruleCount);
      ArrayResize(m_ruleHHMM, m_ruleCount);
      ArrayResize(m_ruleHold, m_ruleCount);
      ArrayResize(m_ruleDir, m_ruleCount);
      ArrayResize(m_ruleFilter, m_ruleCount);
      ArrayResize(m_ruleSL, m_ruleCount);
      ArrayResize(m_rulePreMin, m_ruleCount);
      ArrayResize(m_rulePreThr, m_ruleCount);
      ArrayResize(m_rulePreBelow, m_ruleCount);
      ArrayResize(m_ruleName, m_ruleCount);
      ArrayResize(m_rulePrio, m_ruleCount);
      m_ruleClock[k]  = clock;
      m_ruleHHMM[k]   = (int)StringToInteger(f[2]);
      m_ruleHold[k]   = (int)StringToInteger(f[3]);
      m_ruleDir[k]    = dir;
      m_ruleFilter[k] = filter;
      m_ruleSL[k]     = StringToDouble(f[6]);
      //--- 8つ目（任意）：直前の値動きの条件 "PRE30:-0.07" ＝ 30分前からの値動き ÷ 1時間足の平均値幅 が -0.07 より大きいとき
      m_rulePreMin[k] = 0;
      m_rulePreThr[k] = 0.0;
      m_rulePreBelow[k] = false;
      if(nf == 8 && StringFind(f[7], "PRE") == 0)
        {
         const int c = StringFind(f[7], ":");
         if(c > 3)
           {
            m_rulePreMin[k] = (int)StringToInteger(StringSubstr(f[7], 3, c - 3));
            string v = StringSubstr(f[7], c + 1);
            if(StringFind(v, "<") == 0)
              {
               m_rulePreBelow[k] = true;
               v = StringSubstr(v, 1);
              }
            else
               if(StringFind(v, ">") == 0)
                  v = StringSubstr(v, 1);
            m_rulePreThr[k] = StringToDouble(v);
           }
        }
      m_ruleName[k]   = name;
      m_rulePrio[k]   = i;
      PrintFormat("[AMS] %s 時刻ルール %s: %s %04d から %d 分 %s（%s）SL %.0f pips%s",
                  m_symbol, name, f[1], m_ruleHHMM[k], m_ruleHold[k], f[4], f[5], m_ruleSL[k],
                  m_rulePreMin[k] > 0 ? StringFormat(" 直前%d分の値動き%s%.2f", m_rulePreMin[k], m_rulePreBelow[k] ? "<" : ">", m_rulePreThr[k]) : "");
     }
   return(m_ruleCount);
  }

//+------------------------------------------------------------------+
//| サーバー時間 → UTC（週明けの最初の足 = NY 17:00 を基準にする）           |
//+------------------------------------------------------------------+
datetime CModuleSet::UTCTime(const datetime serverTime) const
  {
   const int nyCloseUTC = IsUSDST(serverTime) ? 21 : 22;
   return((datetime)((long)serverTime - m_openTOD + (nyCloseUTC - 24) * 3600));
  }

//+------------------------------------------------------------------+
//| イギリスの夏時間か（3月最終日曜〜10月最終日曜。日付単位で判定）           |
//+------------------------------------------------------------------+
bool CModuleSet::IsUKDST(const datetime utc) const
  {
   MqlDateTime dt, m, w;
   TimeToStruct(utc, dt);
   m.year = dt.year; m.hour = 0; m.min = 0; m.sec = 0; m.day_of_week = 0; m.day_of_year = 0;
   m.mon = 3; m.day = 31;
   TimeToStruct(StructToTime(m), w);
   const int marLastSun = 31 - w.day_of_week;
   m.mon = 10; m.day = 31;
   TimeToStruct(StructToTime(m), w);
   const int octLastSun = 31 - w.day_of_week;
   const int md = dt.mon * 100 + dt.day;
   return(md >= 300 + marLastSun && md < 1000 + octLastSun);
  }

//+------------------------------------------------------------------+
//| サーバー時間 → 現地時間（0 = 東京, 1 = ロンドン, 2 = ニューヨーク）       |
//+------------------------------------------------------------------+
datetime CModuleSet::LocalTime(const datetime serverTime, const int clock) const
  {
   const datetime utc = UTCTime(serverTime);
   if(clock == 0)
      return(utc + 9 * 3600);
   if(clock == 1)
      return(utc + (IsUKDST(utc) ? 3600 : 0));
   return(utc - (IsUSDST(utc) ? 4 : 5) * 3600);
  }

//+------------------------------------------------------------------+
//| 日の条件を満たすか（現地の日付で判定。ゴトー日は東京の日付）              |
//+------------------------------------------------------------------+
bool CModuleSet::RuleDayOK(const int filter, const datetime local, const int clock) const
  {
   MqlDateTime dt;
   TimeToStruct(local, dt);
   if(dt.day_of_week == 0 || dt.day_of_week == 6)
      return(false);
   if(filter == RULE_ALL)
      return(true);
   if(filter == RULE_GOTOBI)
      return(IsGotobi(clock == 0 ? local : local));   // ゴトー日は東京の時計のルールで使う
   if(filter >= RULE_DOW_BASE)
      return(dt.day_of_week == filter - RULE_DOW_BASE);
   //--- 月末＝その月の最終平日、月初＝最初の2平日
   if(filter == RULE_MONTHEND)
     {
      for(int k = 1; k <= 3; k++)
        {
         MqlDateTime nx;
         TimeToStruct(local + k * 86400, nx);
         if(nx.mon != dt.mon)
            return(true);
         if(nx.day_of_week >= 1 && nx.day_of_week <= 5)
            return(false);
        }
      return(false);
     }
   if(filter == RULE_MONTHSTART)
     {
      int weekdaysBefore = 0;
      for(int d = 1; d < dt.day; d++)
        {
         MqlDateTime p;
         TimeToStruct(local - (dt.day - d) * 86400, p);
         if(p.day_of_week >= 1 && p.day_of_week <= 5)
            weekdaysBefore++;
        }
      return(weekdaysBefore < 2);
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| 時刻ルールのシグナル：いまの足の始まりが、ルールの入る時刻と一致したら     |
//+------------------------------------------------------------------+
double CModuleSet::CalendarSignal(void)
  {
   m_pendRule = -1;
   if(m_openTOD < 0 || m_ruleCount == 0)
      return(0.0);
   const datetime now = iTime(m_symbol, m_tf, 0);
   for(int k = 0; k < m_ruleCount; k++)
     {
      const datetime local = LocalTime(now, m_ruleClock[k]);
      MqlDateTime dt;
      TimeToStruct(local, dt);
      if(dt.hour * 100 + dt.min != m_ruleHHMM[k])
         continue;
      if(!RuleDayOK(m_ruleFilter[k], local, m_ruleClock[k]))
         continue;
      if(m_rulePreMin[k] > 0 && !PreMoveOK(m_rulePreMin[k], m_rulePreThr[k], m_rulePreBelow[k]))
         continue;
      m_pendRule = k;
      return((double)m_ruleDir[k]);
     }
   return(0.0);
  }

//+------------------------------------------------------------------+
//| 直前の値動きの条件：いまの足の始値 − minutes 分前の足の始値 を、       |
//| 1時間足の直近24本（確定足）の平均値幅で割った値が thr より大きいか     |
//+------------------------------------------------------------------+
bool CModuleSet::PreMoveOK(const int minutes, const double thr, const bool below) const
  {
   const int per = PeriodSeconds(m_tf) / 60;
   if(per <= 0 || minutes % per != 0)
      return(false);
   const double now  = iOpen(m_symbol, m_tf, 0);
   const double prev = iOpen(m_symbol, m_tf, minutes / per);
   double rng = 0.0;
   int    n   = 0;
   for(int i = 1; i <= 24; i++)
     {
      const double h = iHigh(m_symbol, PERIOD_H1, i), l = iLow(m_symbol, PERIOD_H1, i);
      if(h > 0.0 && l > 0.0)
        {
         rng += h - l;
         n++;
        }
     }
   if(now <= 0.0 || prev <= 0.0 || n < 12 || rng <= 0.0)
      return(false);
   const double z = (now - prev) / (rng / n);
   return(below ? (z < thr) : (z > thr));
  }

#endif // AMS_MODULES_MQH
//+------------------------------------------------------------------+

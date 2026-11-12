//+------------------------------------------------------------------+
//|                                             AMS/TradeFilters.mqh |
//|  取引してよい状況かを判定するフィルター                               |
//+------------------------------------------------------------------+
#ifndef AMS_TRADEFILTERS_MQH
#define AMS_TRADEFILTERS_MQH

#include "Common.mqh"

//+------------------------------------------------------------------+
//| 現在のスプレッド（pips）                                            |
//+------------------------------------------------------------------+
double CurrentSpreadPips(const string symbol)
  {
   const double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   const double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   const double pip = PipSize(symbol);
   if(pip <= 0.0 || ask <= 0.0 || bid <= 0.0)
      return(DBL_MAX);
   return((ask - bid) / pip);
  }

//+------------------------------------------------------------------+
bool SpreadOK(const string symbol, const double maxSpreadPips)
  {
   if(maxSpreadPips <= 0.0)
      return(true);
   return(CurrentSpreadPips(symbol) <= maxSpreadPips);
  }

//+------------------------------------------------------------------+
//| サーバー時間で取引時間内か。start==end なら終日。                      |
//| start > end のときは日付をまたぐ時間帯（例 22→6）として扱う。           |
//+------------------------------------------------------------------+
bool WithinTradingHours(const int startHour, const int endHour)
  {
   if(startHour == endHour)
      return(true);
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   const int h = dt.hour;
   if(startHour < endHour)
      return(h >= startHour && h < endHour);
   return(h >= startHour || h < endHour);
  }

//+------------------------------------------------------------------+
//| 金曜の指定時刻以降（週末持ち越しを避ける）。hour<0 で無効。              |
//+------------------------------------------------------------------+
bool IsFridayCloseTime(const int fridayCloseHour)
  {
   if(fridayCloseHour < 0)
      return(false);
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return(dt.day_of_week == 5 && dt.hour >= fridayCloseHour);
  }

//+------------------------------------------------------------------+
//| 週明け直後（月曜の指定時刻まで）はスプレッドが広がりやすいので見送る      |
//+------------------------------------------------------------------+
bool IsMondayOpenGap(const int mondayStartHour)
  {
   if(mondayStartHour <= 0)
      return(false);
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return(dt.day_of_week == 1 && dt.hour < mondayStartHour);
  }

//+------------------------------------------------------------------+
//| その銘柄の「今日の取引セッション」の、次の終了までの秒数。              |
//| セッション外なら -1、セッション情報が無ければ INT_MAX を返す。           |
//+------------------------------------------------------------------+
int SecondsToSessionEnd(const string symbol)
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   const int now = dt.hour * 3600 + dt.min * 60 + dt.sec;
   bool any = false;
   for(uint i = 0; i < 10; i++)
     {
      datetime from = 0, to = 0;
      if(!SymbolInfoSessionTrade(symbol, (ENUM_DAY_OF_WEEK)dt.day_of_week, i, from, to))
         break;
      any = true;
      const int f = (int)from, t = (int)to;     // 0時からの秒数
      if(now >= f && now < t)
         return(t - now);
     }
   return(any ? -1 : INT_MAX);
  }

//+------------------------------------------------------------------+
//| その銘柄の今日のセッションが始まってからの秒数（セッション外は -1）       |
//+------------------------------------------------------------------+
int SecondsFromSessionStart(const string symbol)
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   const int now = dt.hour * 3600 + dt.min * 60 + dt.sec;
   bool any = false;
   for(uint i = 0; i < 10; i++)
     {
      datetime from = 0, to = 0;
      if(!SymbolInfoSessionTrade(symbol, (ENUM_DAY_OF_WEEK)dt.day_of_week, i, from, to))
         break;
      any = true;
      const int f = (int)from, t = (int)to;
      if(now >= f && now < t)
         return(now - f);
     }
   return(any ? -1 : INT_MAX);
  }

//+------------------------------------------------------------------+
//| 金曜の最後のセッション終了まで minutes 分以内か（週末持ち越しの回避）     |
//| サーバー時間のずれ（GMT+0 / GMT+2 など）に左右されないよう、             |
//| 時刻の決め打ちではなく、銘柄のセッション情報から判定する。               |
//+------------------------------------------------------------------+
bool IsBeforeWeekendClose(const string symbol, const int minutes)
  {
   if(minutes <= 0)
      return(false);
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_week != 5)
      return(false);
   const int now = dt.hour * 3600 + dt.min * 60 + dt.sec;
   int lastEnd = -1;
   for(uint i = 0; i < 10; i++)
     {
      datetime from = 0, to = 0;
      if(!SymbolInfoSessionTrade(symbol, FRIDAY, i, from, to))
         break;
      if((int)to > lastEnd)
         lastEnd = (int)to;
     }
   if(lastEnd < 0)
      return(false);          // セッション情報が無い → 時刻指定（IsFridayCloseTime）に任せる
   return(now >= lastEnd - minutes * 60);
  }

//+------------------------------------------------------------------+
//| 今その銘柄を新規に売買できる状態か（実運用での確認）                    |
//| reason に、できない理由を入れる。                                    |
//+------------------------------------------------------------------+
bool CanTradeNow(const string symbol, string &reason)
  {
   reason = "";
   if(!MQLInfoInteger(MQL_TESTER))
     {
      if(!TerminalInfoInteger(TERMINAL_CONNECTED))      { reason = "サーバーに未接続"; return(false); }
      if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))  { reason = "ターミナルのアルゴ取引がOFF"; return(false); }
      if(!MQLInfoInteger(MQL_TRADE_ALLOWED))            { reason = "EAの取引許可がOFF"; return(false); }
      if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))    { reason = "口座の取引が不許可"; return(false); }
      if(!AccountInfoInteger(ACCOUNT_TRADE_EXPERT))     { reason = "口座でEA取引が不許可"; return(false); }
     }
   const ENUM_SYMBOL_TRADE_MODE mode = (ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE);
   if(mode != SYMBOL_TRADE_MODE_FULL)                   { reason = "銘柄が新規取引不可（決済のみ等）"; return(false); }
   if(SecondsToSessionEnd(symbol) < 0)                  { reason = "取引時間外"; return(false); }
   //--- 価格が古い（最後のティックから時間が経っている）ときは見送る
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick) || tick.ask <= 0.0 || tick.bid <= 0.0)
     { reason = "価格が取得できない"; return(false); }
   if(TimeCurrent() - tick.time > 120)                  { reason = "価格が古い（2分以上更新なし）"; return(false); }
   return(true);
  }

#endif // AMS_TRADEFILTERS_MQH
//+------------------------------------------------------------------+

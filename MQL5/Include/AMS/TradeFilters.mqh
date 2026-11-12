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

#endif // AMS_TRADEFILTERS_MQH
//+------------------------------------------------------------------+

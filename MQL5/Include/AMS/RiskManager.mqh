//+------------------------------------------------------------------+
//|                                              AMS/RiskManager.mqh |
//|  資金管理とポジション管理                                           |
//|   - 許容損失(%) と SL 幅からのロット計算（口座通貨に自動で対応）         |
//|   - 1日の損失上限                                                  |
//|   - 建値ストップ / トレーリングストップ                               |
//+------------------------------------------------------------------+
#ifndef AMS_RISKMANAGER_MQH
#define AMS_RISKMANAGER_MQH

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include "Common.mqh"

class CRiskManager
  {
private:
   string            m_symbol;
   ulong             m_magic;
   CTrade           *m_trade;
   CPositionInfo     m_pos;

   double            m_riskPct;          // 1回の取引の許容損失（口座残高の%）
   double            m_maxDailyLossPct;  // 1日の損失上限（%）。0で無効
   bool              m_allowMinLot;      // 計算ロットが最小ロット未満でも最小ロットで入るか
   double            m_maxMarginPct;     // 口座全体の必要証拠金の上限（有効証拠金の%）
   double            m_minLevelAfterSL;  // すべての建玉が損切りに達しても残す証拠金維持率（%）
   bool              m_split;           // 1回の注文の上限を超えるロットを、分けて注文するか
   double            m_maxLots;         // 1回の取引の最大ロット（0 = 上限なし）
   bool              m_asyncClose;      // 複数の建玉の決済を同時に出すか
   int               m_dayKey;           // 日付（YYYYMMDD）
   double            m_dayStartEquity;

   int               DayKey(const datetime t) const;
   double            MinStopDistance(void) const;

public:
                     CRiskManager(void);

   void              Init(const string symbol, const ulong magic, CTrade *trade,
                          const double riskPct, const double maxDailyLossPct, const bool allowMinLot,
                          const double maxMarginPct = 40.0, const double minLevelAfterSL = 150.0);
   double            OpenLossToSL(void) const;

   //--- 資金管理
   void              UpdateDay(void);
   bool              DailyLossHit(void);
   double            NormalizeVolume(const double lots) const;
   //--- true のとき、1回の注文の上限（SYMBOL_VOLUME_MAX）でロットを切らない（呼び出し側で注文を分ける）
   void              SetSplitOrders(const bool split) { m_split = split; }
   //--- 1回の取引（1銘柄）の最大ロット（0 = 上限なし）。残高が大きくなっても、現実的に約定できる量に抑えるため
   void              SetMaxLots(const double lots) { m_maxLots = lots; }
   //--- 複数の建玉を決済するとき、約定を待たずに同時に出す（遅れが積み重ならないように）
   void              SetAsyncClose(const bool async) { m_asyncClose = async; }
   double            CalcLots(const ENUM_ORDER_TYPE type, const double entry, const double sl,
                              const double riskMultiplier);
   bool              AdjustStops(const ENUM_ORDER_TYPE type, const double entry, double &sl, double &tp) const;

   //--- ポジション管理
   int               CountPositions(int &buys, int &sells);
   bool              CloseAll(const string reason);
   bool              CloseDirection(const ENUM_POSITION_TYPE type, const string reason);
   void              ManageStops(const double atr, const double beTriggerAtr, const double beOffsetPips,
                                 const double trailStartAtr, const double trailDistAtr,
                                 const double trailStepPips);
  };

//+------------------------------------------------------------------+
CRiskManager::CRiskManager(void) : m_symbol(""),
                                   m_magic(0),
                                   m_trade(NULL),
                                   m_riskPct(1.0),
                                   m_maxDailyLossPct(3.0),
                                   m_allowMinLot(false),
                                   m_maxMarginPct(40.0),
                                   m_minLevelAfterSL(150.0),
                                   m_split(false),
                                   m_maxLots(0.0),
                                   m_asyncClose(false),
                                   m_dayKey(0),
                                   m_dayStartEquity(0.0)
  {
  }

//+------------------------------------------------------------------+
void CRiskManager::Init(const string symbol, const ulong magic, CTrade *trade,
                        const double riskPct, const double maxDailyLossPct, const bool allowMinLot,
                        const double maxMarginPct, const double minLevelAfterSL)
  {
   m_symbol          = symbol;
   m_magic           = magic;
   m_trade           = trade;
   m_riskPct         = riskPct;
   m_maxDailyLossPct = maxDailyLossPct;
   m_allowMinLot     = allowMinLot;
   m_maxMarginPct    = maxMarginPct;
   m_minLevelAfterSL = minLevelAfterSL;
   m_dayKey          = 0;
   UpdateDay();
  }

//+------------------------------------------------------------------+
int CRiskManager::DayKey(const datetime t) const
  {
   MqlDateTime dt;
   TimeToStruct(t, dt);
   return(dt.year * 10000 + dt.mon * 100 + dt.day);
  }

//+------------------------------------------------------------------+
//| 日付が変わったら、その日の開始時の有効証拠金を記録する                  |
//+------------------------------------------------------------------+
void CRiskManager::UpdateDay(void)
  {
   const int key = DayKey(TimeCurrent());
   if(key != m_dayKey)
     {
      m_dayKey         = key;
      m_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
     }
  }

//+------------------------------------------------------------------+
bool CRiskManager::DailyLossHit(void)
  {
   if(m_maxDailyLossPct <= 0.0 || m_dayStartEquity <= 0.0)
      return(false);
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   return(equity <= m_dayStartEquity * (1.0 - m_maxDailyLossPct / 100.0));
  }

//+------------------------------------------------------------------+
//| ロットを刻み幅に切り捨て、最小/最大の範囲に収める                       |
//+------------------------------------------------------------------+
double CRiskManager::NormalizeVolume(const double lots) const
  {
   const double minLot = SymbolInfoDouble(m_symbol, SYMBOL_VOLUME_MIN);
   const double maxLot = SymbolInfoDouble(m_symbol, SYMBOL_VOLUME_MAX);
   const double step   = SymbolInfoDouble(m_symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0)
      return(0.0);

   double v = MathFloor(lots / step + 1e-9) * step;
   if(v < minLot)
      v = m_allowMinLot ? minLot : 0.0;
   if(v > maxLot && !m_split)
      v = maxLot;

   const int volDigits = (int)MathMax(0.0, MathCeil(-MathLog10(step)));
   return(NormalizeDouble(v, volDigits));
  }

//+------------------------------------------------------------------+
//| 許容損失額 ÷ 1ロットあたりの損失額 でロットを決める                     |
//| OrderCalcProfit を使うので、口座通貨が円でもドルでも正しく計算できる      |
//+------------------------------------------------------------------+
double CRiskManager::CalcLots(const ENUM_ORDER_TYPE type, const double entry, const double sl,
                              const double riskMultiplier)
  {
   if(entry <= 0.0 || sl <= 0.0 || MathAbs(entry - sl) <= 0.0)
      return(0.0);

   const double equity    = AccountInfoDouble(ACCOUNT_EQUITY);
   const double riskMoney = equity * m_riskPct / 100.0 * riskMultiplier;
   if(riskMoney <= 0.0)
      return(0.0);

   double lossPerLot = 0.0;
   if(!OrderCalcProfit(type, m_symbol, 1.0, entry, sl, lossPerLot))
     {
      PrintFormat("[AMS] OrderCalcProfit 失敗 (err=%d)", GetLastError());
      return(0.0);
     }
   lossPerLot = MathAbs(lossPerLot);
   if(lossPerLot <= 0.0)
      return(0.0);

   double lots = NormalizeVolume(riskMoney / lossPerLot);
   if(lots <= 0.0)
      return(0.0);

   //--- 証拠金の上限：口座全体の必要証拠金が「有効証拠金 × m_maxMarginPct%」を超えないようにする
   //    （上限を設けないと、高リスク設定でロットが大きくなりすぎ、強制ロスカットになる）
   double margin = 0.0;
   if(!OrderCalcMargin(type, m_symbol, lots, entry, margin) || margin <= 0.0)
      return(lots);
   const double used       = AccountInfoDouble(ACCOUNT_MARGIN);
   const double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double budget = equity * m_maxMarginPct / 100.0 - used;
   if(budget > freeMargin)
      budget = freeMargin;
   if(budget <= 0.0)
      return(0.0);
   if(margin > budget)
      lots = NormalizeVolume(lots * budget / margin);
   if(lots <= 0.0)
      return(0.0);
   //--- ロスカット（証拠金維持率100%）への余裕：すべての建玉（この取引を含む）が損切りに達しても、
   //    維持率が m_minLevelAfterSL% 以上残るロットまでに抑える
   //    (equity - 既存の損切りまでの損失 - l1*x) >= k * (used + m1*x)  →  x <= (equity - Lx - k*used) / (l1 + k*m1)
   if(m_minLevelAfterSL > 0.0)
     {
      const double k  = m_minLevelAfterSL / 100.0;
      const double m1 = margin / MathMax(NormalizeVolume(riskMoney / lossPerLot), 1e-9);
      const double room = equity - OpenLossToSL() - k * used;
      if(room <= 0.0)
         return(0.0);
      const double xmax = room / (lossPerLot + k * m1);
      if(lots > xmax)
         lots = NormalizeVolume(xmax);
     }
   if(m_maxLots > 0.0 && lots > m_maxLots)
      lots = NormalizeVolume(m_maxLots);
   return(lots);
  }

//+------------------------------------------------------------------+
//| 口座のすべての建玉が損切りに達したときの損失の合計（SL がない建玉は、    |
//| 安全のため必要証拠金の全額を損失とみなす）                             |
//+------------------------------------------------------------------+
double CRiskManager::OpenLossToSL(void) const
  {
   double total = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      const string sym  = PositionGetString(POSITION_SYMBOL);
      const double vol  = PositionGetDouble(POSITION_VOLUME);
      const double sl   = PositionGetDouble(POSITION_SL);
      const double cur  = PositionGetDouble(POSITION_PRICE_CURRENT);
      const ENUM_ORDER_TYPE t = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      double pl = 0.0;
      if(sl > 0.0 && OrderCalcProfit(t, sym, vol, cur, sl, pl))
        {
         if(pl < 0.0)
            total -= pl;
        }
      else
        {
         double mg = 0.0;
         if(OrderCalcMargin(t, sym, vol, cur, mg))
            total += mg;
        }
     }
   return(total);
  }

//+------------------------------------------------------------------+
//| ブローカーの最小ストップ距離（価格）                                  |
//+------------------------------------------------------------------+
double CRiskManager::MinStopDistance(void) const
  {
   const double point  = SymbolInfoDouble(m_symbol, SYMBOL_POINT);
   const long   stops  = SymbolInfoInteger(m_symbol, SYMBOL_TRADE_STOPS_LEVEL);
   const long   freeze = SymbolInfoInteger(m_symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   const long   level  = (stops > freeze) ? stops : freeze;
   return((double)(level + 1) * point);
  }

//+------------------------------------------------------------------+
//| SL/TP が最小ストップ距離より近ければ広げ、ティックサイズに丸める          |
//+------------------------------------------------------------------+
bool CRiskManager::AdjustStops(const ENUM_ORDER_TYPE type, const double entry, double &sl, double &tp) const
  {
   const double minDist = MinStopDistance();
   if(type == ORDER_TYPE_BUY)
     {
      if(entry - sl < minDist)
         sl = entry - minDist;
      if(tp > 0.0 && tp - entry < minDist)
         tp = entry + minDist;
     }
   else
     {
      if(sl - entry < minDist)
         sl = entry + minDist;
      if(tp > 0.0 && entry - tp < minDist)
         tp = entry - minDist;
     }
   sl = NormalizePrice(m_symbol, sl);
   tp = (tp > 0.0) ? NormalizePrice(m_symbol, tp) : 0.0;
   return(sl > 0.0);
  }

//+------------------------------------------------------------------+
int CRiskManager::CountPositions(int &buys, int &sells)
  {
   buys  = 0;
   sells = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!m_pos.SelectByIndex(i))
         continue;
      if(m_pos.Symbol() != m_symbol || (ulong)m_pos.Magic() != m_magic)
         continue;
      if(m_pos.PositionType() == POSITION_TYPE_BUY)
         buys++;
      else
         sells++;
     }
   return(buys + sells);
  }

//+------------------------------------------------------------------+
bool CRiskManager::CloseAll(const string reason)
  {
   bool ok = true;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!m_pos.SelectByIndex(i))
         continue;
      if(m_pos.Symbol() != m_symbol || (ulong)m_pos.Magic() != m_magic)
         continue;
      const ulong ticket = m_pos.Ticket();
      if(!m_trade.PositionClose(ticket))
        {
         PrintFormat("[AMS] 決済失敗 #%I64u (%s) retcode=%u %s", ticket, reason,
                     m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
         ok = false;
        }
      else
         PrintFormat("[AMS] 決済 #%I64u (%s)", ticket, reason);
     }
   return(ok);
  }

//+------------------------------------------------------------------+
bool CRiskManager::CloseDirection(const ENUM_POSITION_TYPE type, const string reason)
  {
   bool ok = true;
   if(m_asyncClose)
      m_trade.SetAsyncMode(true);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!m_pos.SelectByIndex(i))
         continue;
      if(m_pos.Symbol() != m_symbol || (ulong)m_pos.Magic() != m_magic || m_pos.PositionType() != type)
         continue;
      const ulong ticket = m_pos.Ticket();
      if(!m_trade.PositionClose(ticket))
        {
         PrintFormat("[AMS] 決済失敗 #%I64u (%s) retcode=%u %s", ticket, reason,
                     m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
         ok = false;
        }
      else
         PrintFormat("[AMS] 決済 #%I64u (%s)", ticket, reason);
     }
   m_trade.SetAsyncMode(false);
   return(ok);
  }

//+------------------------------------------------------------------+
//| 建値ストップとトレーリングストップ                                     |
//|  beTriggerAtr  : 含み益が ATR×この値 になったら SL を建値＋offset へ     |
//|  trailStartAtr : 含み益が ATR×この値 を超えたらトレーリング開始          |
//|  trailDistAtr  : 現在値から ATR×この値 離れた位置に SL を置く            |
//|  trailStepPips : SL をこの pips 以上動かせるときだけ変更する             |
//+------------------------------------------------------------------+
void CRiskManager::ManageStops(const double atr, const double beTriggerAtr, const double beOffsetPips,
                               const double trailStartAtr, const double trailDistAtr,
                               const double trailStepPips)
  {
   if(atr <= 0.0)
      return;

   const double pip     = PipSize(m_symbol);
   const double minDist = MinStopDistance();
   const double step    = MathMax(trailStepPips * pip, SymbolInfoDouble(m_symbol, SYMBOL_POINT));

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!m_pos.SelectByIndex(i))
         continue;
      if(m_pos.Symbol() != m_symbol || (ulong)m_pos.Magic() != m_magic)
         continue;

      const ulong  ticket = m_pos.Ticket();
      const double open   = m_pos.PriceOpen();
      const double sl     = m_pos.StopLoss();
      const double tp     = m_pos.TakeProfit();
      double newSL = sl;

      if(m_pos.PositionType() == POSITION_TYPE_BUY)
        {
         const double bid    = SymbolInfoDouble(m_symbol, SYMBOL_BID);
         const double profit = bid - open;
         if(beTriggerAtr > 0.0 && profit >= atr * beTriggerAtr)
           {
            const double be = open + beOffsetPips * pip;
            if(sl < be)
               newSL = be;
           }
         if(trailDistAtr > 0.0 && profit >= atr * trailStartAtr)
           {
            const double trail = bid - atr * trailDistAtr;
            if(trail > newSL)
               newSL = trail;
           }
         newSL = NormalizePrice(m_symbol, newSL);
         if(newSL > sl + step * 0.999 || (sl <= 0.0 && newSL > 0.0))
           {
            if(bid - newSL < minDist)
               continue;
            if(!m_trade.PositionModify(ticket, newSL, tp))
               PrintFormat("[AMS] SL変更失敗 #%I64u retcode=%u %s", ticket,
                           m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
           }
        }
      else
        {
         const double ask    = SymbolInfoDouble(m_symbol, SYMBOL_ASK);
         const double profit = open - ask;
         if(beTriggerAtr > 0.0 && profit >= atr * beTriggerAtr)
           {
            const double be = open - beOffsetPips * pip;
            if(sl <= 0.0 || sl > be)
               newSL = be;
           }
         if(trailDistAtr > 0.0 && profit >= atr * trailStartAtr)
           {
            const double trail = ask + atr * trailDistAtr;
            if(newSL <= 0.0 || trail < newSL)
               newSL = trail;
           }
         newSL = NormalizePrice(m_symbol, newSL);
         if((sl > 0.0 && newSL > 0.0 && newSL < sl - step * 0.999) || (sl <= 0.0 && newSL > 0.0))
           {
            if(newSL - ask < minDist)
               continue;
            if(!m_trade.PositionModify(ticket, newSL, tp))
               PrintFormat("[AMS] SL変更失敗 #%I64u retcode=%u %s", ticket,
                           m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
           }
        }
     }
  }

#endif // AMS_RISKMANAGER_MQH
//+------------------------------------------------------------------+

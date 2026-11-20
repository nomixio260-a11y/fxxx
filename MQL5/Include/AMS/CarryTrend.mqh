//+------------------------------------------------------------------+
//| CarryTrend.mqh                                                   |
//| 売買の方式 7：金利差＋トレンド（83章）                                |
//| 判断に使うのは、口座の実際のスワップ（金利差）と、日足の値動きだけ。       |
//| 時刻・曜日・日付は、売買の判断には使わない（入れ替えを行う時刻は、日付の    |
//| 変わり目のスプレッド拡大を避けるためだけに使う）。                       |
//|  1. 各ペアで、スワップを受け取れる向きと、その年率（% ）を口座の値から計算 |
//|  2. その向きと、過去 N 日の値動きの向きが同じペアだけを候補にする         |
//|  3. 直近10日の値動きが120日の値動きの k 倍を超えたペアは外す（急変の回避） |
//|  4. 金利差 ÷ 値動きの大きさ の上位 K ペアを持つ（値動きの大きさで割った重み）|
//|  5. 全体の年率ボラティリティが目標になるよう、建玉の合計を決める           |
//+------------------------------------------------------------------+
#ifndef AMS_CARRYTREND_MQH
#define AMS_CARRYTREND_MQH

#include <Trade\Trade.mqh>

#define CT_DAYS 120   // 値動きの大きさ・相関に使う日数（日足の本数）

//--- テスターでは、スワップの値が今のもので固定されるため、過去の判断に未来の金利差を使ってしまう。
//    それを避けるため、テスターでは年ごとの政策金利（年平均の目安、tools/research/multiday_scan.py と同じ）で判断する。
//    実運用では、口座の実際のスワップを使う。
string CT_CCY[8] = {"JPY", "USD", "EUR", "GBP", "AUD", "NZD", "CAD", "CHF"};
double CT_RATE[8][12] =   // 2015〜2026年
  {
     {-0.0, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, 0.1, 0.5, 0.75},
     {0.15, 0.4, 1.0, 1.8, 2.2, 0.4, 0.1, 1.7, 5.0, 5.1, 4.2, 3.6},
     {-0.2, -0.35, -0.4, -0.4, -0.45, -0.5, -0.5, 0.3, 3.3, 3.6, 2.2, 2.0},
     {0.5, 0.4, 0.3, 0.6, 0.75, 0.2, 0.1, 1.5, 4.7, 5.0, 4.2, 3.8},
     {2.1, 1.7, 1.5, 1.5, 1.0, 0.3, 0.1, 1.5, 3.9, 4.35, 3.9, 3.6},
     {3.0, 2.1, 1.75, 1.75, 1.3, 0.3, 0.4, 2.5, 5.4, 5.2, 3.5, 2.5},
     {0.6, 0.5, 0.7, 1.5, 1.75, 0.5, 0.25, 2.0, 4.8, 4.5, 2.8, 2.25},
     {-0.75, -0.75, -0.75, -0.75, -0.75, -0.75, -0.75, -0.1, 1.5, 1.3, 0.3, 0.0}
  };

class CCarryTrend
  {
private:
   CTrade           *m_trade;
   ulong             m_magic;
   string            m_sym[];
   int               m_n;
   int               m_trendDays;
   double            m_minCarry;
   int               m_topK;
   double            m_crashMul;
   double            m_volTarget;
   double            m_maxLev;
   double            m_maxMarginPct;
   int               m_rbDays;
   int               m_hour;
   double            m_band;
   double            m_slVolMul;
   datetime          m_lastRebalance;
   datetime          m_initAt;        // 起動した時刻（実運用：銘柄の情報がそろうまで、5分は入れ替えない）
   string            m_gvKey;
   string            m_stateFile;    // 前回の入れ替えの時刻（共通フォルダ。デモ口座の回をまたいで引き継ぐ）
   bool              m_dailyExit;     // 毎日の手じまい（トレンドが逆・急変のペアは、次の入れ替えを待たずに手じまう。86章）
   datetime          m_lastExitDay;

   bool              DailyReturns(const string sym, double &r[]);
   double            Std(const double &x[], const int from, const int count);
   double            SwapAnnualPct(const string sym, const bool isLong);
   double            TesterCarryPct(const string sym, const bool isLong);
   double            CarryPct(const string sym, const bool isLong);
   double            NotionalPerLot(const string sym);
   double            CurrentLots(const string sym, int &dir);
   void              CloseSymbol(const string sym, const string why);
   void              OpenLots(const string sym, const int dir, double lots, const double vol);
   void              ReduceLots(const string sym, double lots);
   double            NormalizeLots(const string sym, const double lots);
   void              DailyExits(void);

public:
                     CCarryTrend(void) : m_trade(NULL), m_magic(0), m_n(0), m_lastRebalance(0), m_initAt(0), m_dailyExit(false), m_lastExitDay(0) {}
   void              SetDailyExit(const bool on) { m_dailyExit = on; }
   bool              Init(CTrade *trade, const ulong magic, const string &syms[], const int trendDays, const double minCarry,
                          const int topK, const double crashMul, const double volTarget, const double maxLev,
                          const double maxMarginPct, const int rbDays, const int hour, const double band,
                          const double slVolMul, const string gvKey);
   void              OnTick(void);
   bool              Rebalance(void);
  };

//+------------------------------------------------------------------+
bool CCarryTrend::Init(CTrade *trade, const ulong magic, const string &syms[], const int trendDays, const double minCarry,
                       const int topK, const double crashMul, const double volTarget, const double maxLev,
                       const double maxMarginPct, const int rbDays, const int hour, const double band,
                       const double slVolMul, const string gvKey)
  {
   m_trade        = trade;
   m_magic        = magic;
   m_trendDays    = (int)MathMax(5, MathMin(trendDays, CT_DAYS));
   m_minCarry     = minCarry;
   m_topK         = (int)MathMax(1, topK);
   m_crashMul     = crashMul;
   m_volTarget    = volTarget;
   m_maxLev       = maxLev;
   m_maxMarginPct = maxMarginPct;
   m_rbDays       = (int)MathMax(1, rbDays);
   m_hour         = hour;
   m_band         = band;
   m_slVolMul     = slVolMul;
   m_gvKey        = gvKey;
   m_stateFile    = StringFormat("AMS_ct_state3_%I64u.txt", magic);   // 2026-11-20：判断の不具合を直したため、記録を新しくした（2回目）
   m_initAt       = TimeCurrent();
   m_n            = ArraySize(syms);
   ArrayResize(m_sym, m_n);
   for(int i = 0; i < m_n; i++)
     {
      m_sym[i] = syms[i];
      if(!SymbolSelect(m_sym[i], true))
         PrintFormat("[AMS] 金利差＋トレンド：%s を気配値表示に追加できません", m_sym[i]);
      PrintFormat("[AMS] 金利差＋トレンド：%s 判断に使う金利差（政策金利の表、上乗せ後）買い %.2f%% / 売り %.2f%%、口座のスワップ（方式=%d）買い %.2f / 売り %.2f",
                  m_sym[i], TesterCarryPct(m_sym[i], true), TesterCarryPct(m_sym[i], false), (int)SymbolInfoInteger(m_sym[i], SYMBOL_SWAP_MODE),
                  SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_LONG), SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_SHORT));
     }
   if(!MQLInfoInteger(MQL_TESTER))
     {
      if(GlobalVariableCheck(m_gvKey))
         m_lastRebalance = (datetime)GlobalVariableGet(m_gvKey);
      const int fh = FileOpen(m_stateFile, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
      if(fh != INVALID_HANDLE)
        {
         const datetime t = (datetime)StringToInteger(FileReadString(fh));
         FileClose(fh);
         if(t > m_lastRebalance)
            m_lastRebalance = t;
        }
      if(m_lastRebalance > 0)
         PrintFormat("[AMS] 金利差＋トレンド：前回の入れ替え %s", TimeToString(m_lastRebalance, TIME_DATE));
     }
   PrintFormat("[AMS] 金利差＋トレンド：%d ペア、トレンド %d 日、金利差 %.1f%% 以上、上位 %d、急変 %.1f 倍、目標の年率ボラティリティ %.1f%%、"
               "建玉の合計の上限 %.1f 倍、入れ替え %d 日ごと（サーバー時刻 %d 時以降）",
               m_n, m_trendDays, m_minCarry, m_topK, m_crashMul, m_volTarget, m_maxLev, m_rbDays, m_hour);
   return(m_n > 0);
  }

//+------------------------------------------------------------------+
//| 確定した日足の終値から、直近 CT_DAYS 日の日ごとの値動き（古い順）       |
//+------------------------------------------------------------------+
bool CCarryTrend::DailyReturns(const string sym, double &r[])
  {
   double c[];
   ArraySetAsSeries(c, false);
   const int got = CopyClose(sym, PERIOD_D1, 1, CT_DAYS + 1, c);
   if(got < CT_DAYS + 1)
      return(false);
   ArrayResize(r, CT_DAYS);
   for(int k = 0; k < CT_DAYS; k++)
     {
      if(c[k] <= 0.0)
         return(false);
      r[k] = c[k + 1] / c[k] - 1.0;
     }
   return(true);
  }

//+------------------------------------------------------------------+
double CCarryTrend::Std(const double &x[], const int from, const int count)
  {
   if(count < 2)
      return(0.0);
   double s = 0.0, s2 = 0.0;
   for(int k = from; k < from + count; k++)
     {
      s  += x[k];
      s2 += x[k] * x[k];
     }
   const double m = s / count;
   const double v = (s2 - count * m * m) / (count - 1);
   return(v > 0.0 ? MathSqrt(v) : 0.0);
  }

//+------------------------------------------------------------------+
//| 1ロットの建玉の額（口座通貨）                                         |
//+------------------------------------------------------------------+
double CCarryTrend::NotionalPerLot(const string sym)
  {
   const double tv    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   const double ts    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   const double price = SymbolInfoDouble(sym, SYMBOL_BID);
   if(ts <= 0.0 || tv <= 0.0 || price <= 0.0)
      return(0.0);
   return(price / ts * tv);
  }

//+------------------------------------------------------------------+
//| スワップを、建玉の額に対する年率（%）にする。受け取りならプラス          |
//+------------------------------------------------------------------+
double CCarryTrend::SwapAnnualPct(const string sym, const bool isLong)
  {
   const double sw       = SymbolInfoDouble(sym, isLong ? SYMBOL_SWAP_LONG : SYMBOL_SWAP_SHORT);
   const int    mode     = (int)SymbolInfoInteger(sym, SYMBOL_SWAP_MODE);
   const double contract = SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE);
   const double notional = NotionalPerLot(sym);
   if(contract <= 0.0 || notional <= 0.0)
      return(0.0);
   double perDay = 0.0;   // 1ロット・1日あたり（口座通貨）
   if(mode == SYMBOL_SWAP_MODE_POINTS)
     {
      const double tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
      const double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
      const double pt = SymbolInfoDouble(sym, SYMBOL_POINT);
      if(ts <= 0.0)
         return(0.0);
      perDay = sw * pt / ts * tv;
     }
   else if(mode == SYMBOL_SWAP_MODE_CURRENCY_DEPOSIT)
      perDay = sw;
   else if(mode == SYMBOL_SWAP_MODE_CURRENCY_SYMBOL || mode == SYMBOL_SWAP_MODE_CURRENCY_MARGIN)
      return(sw / contract * 365.0 * 100.0);
   else if(mode == SYMBOL_SWAP_MODE_INTEREST_CURRENT || mode == SYMBOL_SWAP_MODE_INTEREST_OPEN)
      return(sw);
   else
      return(0.0);
   return(perDay * 365.0 / notional * 100.0);
  }

//+------------------------------------------------------------------+
//| テスター用：年ごとの政策金利の差から、受け取れる金利差（年率 %、業者の上乗せ 年1% を引く） |
//+------------------------------------------------------------------+
double CCarryTrend::TesterCarryPct(const string sym, const bool isLong)
  {
   const string b = StringSubstr(sym, 0, 3), q = StringSubstr(sym, 3, 3);
   int ib = -1, iq = -1;
   for(int k = 0; k < 8; k++)
     {
      if(CT_CCY[k] == b)
         ib = k;
      if(CT_CCY[k] == q)
         iq = k;
     }
   if(ib < 0 || iq < 0)
      return(0.0);
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   const int y = (int)MathMax(0, MathMin(11, dt.year - 2015));
   const double diff = CT_RATE[ib][y] - CT_RATE[iq][y];
   return((isLong ? diff : -diff) - 1.0);
  }

//+------------------------------------------------------------------+
//| 判断に使う金利差：実運用は口座のスワップ、テスターは年ごとの政策金利      |
//+------------------------------------------------------------------+
double CCarryTrend::CarryPct(const string sym, const bool isLong)
  {
   //--- 判断は、テスターでも実運用でも、年ごとの政策金利の表で行う（バックテストと同じ動きにするため）。
   //    口座のスワップの年率への換算は、業者の値の単位がはっきりしないため（2026年11月19日のデモ口座で、
   //    実際の金利差の2〜3倍に出た）、判断には使わない。実運用では、その向きの口座のスワップが
   //    プラス（受け取り）であることだけを、追加の条件にする（払いになる向きは持たない）。
   const double t = TesterCarryPct(sym, isLong);
   if(MQLInfoInteger(MQL_TESTER))
      return(t);
   //--- 0 は「まだ値を受け取っていない」ことがある（2026-11-20、起動直後に円のペアがすべて 0 だった）ので、
   //    はっきりマイナス（払い）のときだけ外す
   const double sw = SymbolInfoDouble(sym, isLong ? SYMBOL_SWAP_LONG : SYMBOL_SWAP_SHORT);
   if(sw < 0.0)
      return(MathMin(t, -1.0));
   return(t);
  }

//+------------------------------------------------------------------+
//| この方式の建玉（ロット、向き）。買いと売りがあれば差し引き                |
//+------------------------------------------------------------------+
double CCarryTrend::CurrentLots(const string sym, int &dir)
  {
   double buy = 0.0, sell = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != m_magic)
         continue;
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
         buy += PositionGetDouble(POSITION_VOLUME);
      else
         sell += PositionGetDouble(POSITION_VOLUME);
     }
   const double net = buy - sell;
   dir = (net > 0.0) ? 1 : ((net < 0.0) ? -1 : 0);
   return(MathAbs(net));
  }

//+------------------------------------------------------------------+
double CCarryTrend::NormalizeLots(const string sym, const double lots)
  {
   const double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   const double mn   = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   if(step <= 0.0)
      return(0.0);
   const double v = MathFloor(lots / step + 1e-9) * step;
   if(v < mn)
      return(0.0);
   const int digits = (int)MathMax(0.0, MathCeil(-MathLog10(step)));
   return(NormalizeDouble(v, digits));
  }

//+------------------------------------------------------------------+
void CCarryTrend::CloseSymbol(const string sym, const string why)
  {
   m_trade.SetTypeFillingBySymbol(sym);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != m_magic)
         continue;
      if(m_trade.PositionClose(tk))
         PrintFormat("[AMS] 金利差＋トレンド：決済 %s #%I64u（%s）", sym, tk, why);
     }
  }

//+------------------------------------------------------------------+
//| 新規に lots を持つ（1回の注文の上限を超える分は分けて注文）。             |
//| 損切りは、急変に備えた安全のためだけに、日々の値動きの m 倍に置く         |
//+------------------------------------------------------------------+
void CCarryTrend::OpenLots(const string sym, const int dir, double lots, const double vol)
  {
   m_trade.SetTypeFillingBySymbol(sym);
   const double mx    = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   const int    dg    = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   const string cmt   = StringFormat("AMS|%s|CARRY|CT", sym);
   while(lots > 0.0)
     {
      const double v = NormalizeLots(sym, (mx > 0.0) ? MathMin(lots, mx) : lots);
      if(v <= 0.0)
         break;
      const double price = (dir > 0) ? SymbolInfoDouble(sym, SYMBOL_ASK) : SymbolInfoDouble(sym, SYMBOL_BID);
      double sl = 0.0;
      if(m_slVolMul > 0.0 && vol > 0.0)
         sl = NormalizeDouble((dir > 0) ? price * (1.0 - m_slVolMul * vol) : price * (1.0 + m_slVolMul * vol), dg);
      const bool ok = (dir > 0) ? m_trade.Buy(v, sym, 0.0, sl, 0.0, cmt) : m_trade.Sell(v, sym, 0.0, sl, 0.0, cmt);
      if(!ok)
        {
         PrintFormat("[AMS] 金利差＋トレンド：%s の注文に失敗（%d %s）", sym, m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
         break;
        }
      PrintFormat("[AMS] 金利差＋トレンド：%s %s %.2f lot @%.5f SL=%.5f", sym, dir > 0 ? "BUY" : "SELL", v, m_trade.ResultPrice(), sl);
      lots -= v;
     }
  }

//+------------------------------------------------------------------+
void CCarryTrend::ReduceLots(const string sym, double lots)
  {
   m_trade.SetTypeFillingBySymbol(sym);
   for(int i = PositionsTotal() - 1; i >= 0 && lots > 0.0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != m_magic)
         continue;
      const double pv = PositionGetDouble(POSITION_VOLUME);
      if(pv <= lots + 1e-9)
        {
         if(m_trade.PositionClose(tk))
            lots -= pv;
        }
      else
        {
         const double v = NormalizeLots(sym, lots);
         if(v > 0.0 && m_trade.PositionClosePartial(tk, v))
            lots -= v;
         break;
        }
     }
  }

//+------------------------------------------------------------------+
//| 入れ替え。データがそろわないペアが半分を超えるときは何もしない（false）    |
//+------------------------------------------------------------------+
bool CCarryTrend::Rebalance(void)
  {
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity <= 0.0)
      return(false);
   int    dir[];
   double vol[], score[], w[], lots[];
   double R[][CT_DAYS];
   ArrayResize(dir, m_n);
   ArrayResize(vol, m_n);
   ArrayResize(score, m_n);
   ArrayResize(w, m_n);
   ArrayResize(lots, m_n);
   ArrayResize(R, m_n);
   int valid = 0;
   for(int i = 0; i < m_n; i++)
     {
      dir[i] = 0;
      vol[i] = 0.0;
      score[i] = 0.0;
      w[i] = 0.0;
      lots[i] = 0.0;
      double r[];
      if(!DailyReturns(m_sym[i], r))
         continue;
      valid++;
      for(int k = 0; k < CT_DAYS; k++)
         R[i][k] = r[k];
      const double v60  = Std(r, CT_DAYS - 60, 60);
      const double v10  = Std(r, CT_DAYS - 10, 10);
      const double v120 = Std(r, 0, CT_DAYS);
      double g = 1.0;
      for(int k = CT_DAYS - m_trendDays; k < CT_DAYS; k++)
         g *= (1.0 + r[k]);
      const int trend = (g > 1.0) ? 1 : ((g < 1.0) ? -1 : 0);
      const double cL = CarryPct(m_sym[i], true);
      const double cS = CarryPct(m_sym[i], false);
      int d = 0;
      double carry = 0.0;
      if(cL >= m_minCarry && cL >= cS)
        {
         d = 1;
         carry = cL;
        }
      else if(cS >= m_minCarry)
        {
         d = -1;
         carry = cS;
        }
      if(d == 0 || trend != d || v60 <= 0.0)
         continue;
      if(m_crashMul > 0.0 && v10 > m_crashMul * v120)
        {
         PrintFormat("[AMS] 金利差＋トレンド：%s は値動きが急に大きくなっているため外す（10日 %.3f%% / 120日 %.3f%%）",
                     m_sym[i], v10 * 100.0, v120 * 100.0);
         continue;
        }
      dir[i]   = d;
      vol[i]   = v60;
      score[i] = carry / (v60 * MathSqrt(261.0) * 100.0);
     }
   if(valid * 2 < m_n)
     {
      PrintFormat("[AMS] 金利差＋トレンド：日足がそろったペアが %d / %d のため、入れ替えを見送ります", valid, m_n);
      return(false);
     }
   //--- 効率（金利差 ÷ 値動きの大きさ）の上位 K だけを残す
   for(int kth = 0; kth < m_n; kth++)
     {
      int cnt = 0;
      for(int i = 0; i < m_n; i++)
         if(dir[i] != 0)
            cnt++;
      if(cnt <= m_topK)
         break;
      int worst = -1;
      for(int i = 0; i < m_n; i++)
         if(dir[i] != 0 && (worst < 0 || score[i] < score[worst]))
            worst = i;
      dir[worst] = 0;
     }
   //--- 重み（値動きの大きさで割り、合計の大きさを 1 に）
   double sumAbs = 0.0;
   for(int i = 0; i < m_n; i++)
      if(dir[i] != 0)
         sumAbs += 1.0 / vol[i];
   if(sumAbs > 0.0)
      for(int i = 0; i < m_n; i++)
         if(dir[i] != 0)
            w[i] = dir[i] / vol[i] / sumAbs;
   //--- 全体の年率ボラティリティ（直近60日の共分散）から、建玉の合計の倍率を決める
   double var = 0.0;
   for(int i = 0; i < m_n; i++)
     {
      if(w[i] == 0.0)
         continue;
      for(int j = 0; j < m_n; j++)
        {
         if(w[j] == 0.0)
            continue;
         double mi = 0.0, mj = 0.0;
         for(int k = CT_DAYS - 60; k < CT_DAYS; k++)
           {
            mi += R[i][k];
            mj += R[j][k];
           }
         mi /= 60.0;
         mj /= 60.0;
         double cov = 0.0;
         for(int k = CT_DAYS - 60; k < CT_DAYS; k++)
            cov += (R[i][k] - mi) * (R[j][k] - mj);
         cov /= 59.0;
         var += w[i] * w[j] * cov;
        }
     }
   double lev = 0.0;
   if(var > 0.0)
      lev = MathMin(m_volTarget / 100.0 / (MathSqrt(var) * MathSqrt(261.0)), m_maxLev);
   //--- ロットにする。必要証拠金が上限を超えるときは、全体を小さくする
   double margin = 0.0;
   for(int i = 0; i < m_n; i++)
     {
      if(w[i] == 0.0)
         continue;
      const double npl = NotionalPerLot(m_sym[i]);
      if(npl <= 0.0)
         continue;
      lots[i] = lev * equity * MathAbs(w[i]) / npl;
      double m = 0.0;
      const double price = (dir[i] > 0) ? SymbolInfoDouble(m_sym[i], SYMBOL_ASK) : SymbolInfoDouble(m_sym[i], SYMBOL_BID);
      if(OrderCalcMargin(dir[i] > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, m_sym[i], lots[i], price, m))
         margin += m;
     }
   const double cap = equity * m_maxMarginPct / 100.0;
   const double shrink = (margin > cap && margin > 0.0) ? cap / margin : 1.0;
   //--- 先に決済・縮小（証拠金を空ける）、そのあと新規・追加
   int    cdir[];
   double cl[], tl[];
   ArrayResize(cdir, m_n);
   ArrayResize(cl, m_n);
   ArrayResize(tl, m_n);
   for(int i = 0; i < m_n; i++)
     {
      cl[i] = CurrentLots(m_sym[i], cdir[i]);
      tl[i] = (dir[i] != 0) ? NormalizeLots(m_sym[i], lots[i] * shrink) : 0.0;
      if(tl[i] <= 0.0)
        {
         if(cl[i] > 0.0)
            CloseSymbol(m_sym[i], "対象から外れた");
         cl[i] = 0.0;
         continue;
        }
      if(cl[i] > 0.0 && cdir[i] != dir[i])
        {
         CloseSymbol(m_sym[i], "向きが変わった");
         cl[i] = 0.0;
         continue;
        }
      if(cl[i] > tl[i] && (cl[i] - tl[i]) > m_band * cl[i])
        {
         ReduceLots(m_sym[i], cl[i] - tl[i]);
         cl[i] = tl[i];
        }
     }
   for(int i = 0; i < m_n; i++)
     {
      if(tl[i] <= 0.0)
         continue;
      if(cl[i] <= 0.0)
         OpenLots(m_sym[i], dir[i], tl[i], vol[i]);
      else if(tl[i] > cl[i] && (tl[i] - cl[i]) > m_band * tl[i])
         OpenLots(m_sym[i], dir[i], tl[i] - cl[i], vol[i]);
     }
   string held = "";
   for(int i = 0; i < m_n; i++)
      if(tl[i] > 0.0)
         held += StringFormat(" %s%s%.2f", m_sym[i], dir[i] > 0 ? "+" : "-", tl[i]);
   PrintFormat("[AMS] 金利差＋トレンド：入れ替え 建玉の合計 %.2f 倍（証拠金で %.0f%% に縮小）、持つもの:%s",
               lev * shrink, shrink * 100.0, held == "" ? " なし" : held);
   return(true);
  }

//+------------------------------------------------------------------+
//| 毎日の手じまい：持っているペアのトレンドが逆向きになった、または急変した   |
//| ら、次の入れ替えを待たずに手じまう（その日までの日足だけで判断）          |
//+------------------------------------------------------------------+
void CCarryTrend::DailyExits(void)
  {
   for(int i = 0; i < m_n; i++)
     {
      int d = 0;
      if(CurrentLots(m_sym[i], d) <= 0.0)
         continue;
      double r[];
      if(!DailyReturns(m_sym[i], r))
         continue;
      double g = 1.0;
      for(int k = CT_DAYS - m_trendDays; k < CT_DAYS; k++)
         g *= (1.0 + r[k]);
      const int trend = (g > 1.0) ? 1 : ((g < 1.0) ? -1 : 0);
      const double v10  = Std(r, CT_DAYS - 10, 10);
      const double v120 = Std(r, 0, CT_DAYS);
      if(trend != d)
         CloseSymbol(m_sym[i], "毎日の確認：トレンドが逆向きになった");
      else if(m_crashMul > 0.0 && v10 > m_crashMul * v120)
         CloseSymbol(m_sym[i], "毎日の確認：値動きが急に大きくなった");
     }
  }

//+------------------------------------------------------------------+
//| 毎ティック：入れ替えの時期なら入れ替える                               |
//+------------------------------------------------------------------+
void CCarryTrend::OnTick(void)
  {
   const datetime now = TimeCurrent();
   MqlDateTime dt;
   TimeToStruct(now, dt);
   if(dt.day_of_week == 0 || dt.day_of_week == 6 || dt.hour < m_hour)
      return;
   if(!MQLInfoInteger(MQL_TESTER) && (long)now - (long)m_initAt < 300)
      return;
   const datetime today = (datetime)((long)now - (long)now % 86400);
   //--- 毎日の手じまい（1日1回。新しく持つ・増やすのは週1回の入れ替えだけ）
   if(m_dailyExit && today != m_lastExitDay)
     {
      DailyExits();
      m_lastExitDay = today;
     }
   if(m_lastRebalance > 0 && (long)today - (long)m_lastRebalance < (long)m_rbDays * 86400)
      return;
   if(!Rebalance())
      return;
   m_lastRebalance = today;
   if(!MQLInfoInteger(MQL_TESTER))
     {
      GlobalVariableSet(m_gvKey, (double)m_lastRebalance);
      const int fh = FileOpen(m_stateFile, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
      if(fh != INVALID_HANDLE)
        {
         FileWriteString(fh, IntegerToString((long)m_lastRebalance));
         FileClose(fh);
        }
     }
  }

#endif // AMS_CARRYTREND_MQH

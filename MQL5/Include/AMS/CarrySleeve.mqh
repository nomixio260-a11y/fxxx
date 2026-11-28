//+------------------------------------------------------------------+
//| CarrySleeve.mqh                                                  |
//| キャリーの層（107章）：先物を元にした商品CFD（原油・天然ガスなど）で、     |
//|  「スワップが受け取りになる向き」と「流れ（200日の平均）」がそろったとき   |
//|  だけ、買いまたは売りで持つ。日付・時刻は判断に使わない。                 |
//|                                                                  |
//| 考え方：                                                           |
//|  - 先物の期近が期先より高い（逆ざや）商品は、持ち続けるだけで利益になり、   |
//|    安い（順ざや）商品は、売り続けるだけで利益になる（キャリー）。          |
//|  - OANDA の商品CFD は、この差を毎日のスワップで受け払いする             |
//|    （スワップ ＝ 限月どうしの差 − 業者の取り分）。                       |
//|    つまり「スワップが受け取りになる向き」が、キャリーがプラスの向き。       |
//|  - 値段の流れも同じ向きのときだけ持つ（買い：終値が200日の平均より上、     |
//|    売り：下）。どちらもそろわなければ、持たない。                        |
//|  - 建玉は、その銘柄の値動き（過去60日）が口座の年 x% になる大きさ。        |
//|    毎日、今の値段から k × 1日の値動き だけ離して逆指値を置き直す。         |
//|  - 指数の戻りの層とは無関係に動き、株の急落の局面でプラスになりやすい       |
//|    （原油は、景気の急な悪化のとき順ざや・下げの流れになり、売りになる）。    |
//|                                                                  |
//| 注意：テスターは「今日のスワップ」を全期間に使うので、この層の損益は        |
//|  テスターでは検証できない（動作の確認だけ）。成績の検証は、先物の値段での    |
//|  計算（tools/research/commodity_carry.py）で行った。                  |
//+------------------------------------------------------------------+
#property strict

#include <Trade\Trade.mqh>

class CCarrySleeve
  {
private:
   CTrade            m_tr;
   ulong             m_magic;
   string            m_sym[];
   int               m_n;
   double            m_unit;          // 1銘柄の建玉の値動き（口座に対する年率 %）
   double            m_minSwap;       // 持つために必要な、スワップの受け取り（年 %）
   int               m_look;          // 流れを見る日数
   int               m_checkDays;     // 見直しの間隔（日）
   double            m_slVolMul;      // 逆指値：1日の値動きの何倍か（0 で置かない）
   double            m_maxLev;        // 1銘柄の建玉の額 ÷ 有効証拠金 の上限
   double            m_band;          // 今の建玉と目標の差がこの割合未満なら、大きさは直さない
   int               m_delaySec;
   double            m_maxSpreadPct;
   bool              m_dryRun;
   double            m_eqOffset;
   int               m_state[];       // +1 買い / −1 売り / 0 持たない
   datetime          m_check[];       // 最後に見直した日足
   datetime          m_lastBar[];     // 処理した日足
   datetime          m_seenBar[];
   datetime          m_seenAt[];
   datetime          m_retryAt[];
   int               m_retryCount[];
   datetime          m_warnAt[];
   bool              m_tradeFail;
   string            m_stateFile;
   int               m_cntOpen, m_cntClose, m_cntRetry, m_cntStopFail;

   double            SizingEquity(void) { return(MathMax(0.0, AccountInfoDouble(ACCOUNT_EQUITY) - m_eqOffset)); }
   double            NotionalPerLot(const string sym);
   double            NormalizeLots(const string sym, const double lots);
   double            SignedLots(const string sym);
   double            SwapAnnualPct(const string sym, const bool isLong);
   double            ToTick(const string sym, const double price);
   void              CloseAll(const string sym, const string why);
   void              Open(const string sym, const int dir, double lots, const double dailyVol);
   void              Reduce(const string sym, const int dir, double lots);
   void              ApplyStops(const string sym, const double dailyVol);
   bool              Process(const int i, const datetime t0);
   void              Warn(const int i, const string msg);
   void              SaveState(void);
   void              LoadState(void);

public:
                     CCarrySleeve(void) : m_n(0), m_tradeFail(false), m_cntOpen(0), m_cntClose(0), m_cntRetry(0), m_cntStopFail(0) {}
   bool              Init(const ulong magic, const string &syms[], const double unitVol, const double minSwapPct, const int trendDays,
                          const int checkDays, const double slVolMul, const double maxLev, const double band, const int delayMin,
                          const double maxSpreadPct, const bool dryRun, const double equityOffset);
   void              OnTick(void);
   void              Summary(void);
   int               Count(void) const { return(m_n); }
  };

//+------------------------------------------------------------------+
bool CCarrySleeve::Init(const ulong magic, const string &syms[], const double unitVol, const double minSwapPct, const int trendDays,
                        const int checkDays, const double slVolMul, const double maxLev, const double band, const int delayMin,
                        const double maxSpreadPct, const bool dryRun, const double equityOffset)
  {
   m_magic        = magic;
   m_unit         = MathMax(0.0, unitVol);
   m_minSwap      = minSwapPct;
   m_look         = (int)MathMax(20, trendDays);
   m_checkDays    = (int)MathMax(1, checkDays);
   m_slVolMul     = slVolMul;
   m_maxLev       = maxLev;
   m_band         = band;
   m_delaySec     = (int)MathMax(0, delayMin) * 60;
   m_maxSpreadPct = maxSpreadPct;
   m_dryRun       = dryRun;
   m_eqOffset     = MathMax(0.0, equityOffset);
   m_tr.SetExpertMagicNumber(magic);
   m_stateFile    = StringFormat("AMS_carry_state_%I64u.csv", magic);
   m_n = ArraySize(syms);
   ArrayResize(m_sym, m_n);
   ArrayResize(m_state, m_n);
   ArrayResize(m_check, m_n);
   ArrayResize(m_lastBar, m_n);
   ArrayResize(m_seenBar, m_n);
   ArrayResize(m_seenAt, m_n);
   ArrayResize(m_retryAt, m_n);
   ArrayResize(m_retryCount, m_n);
   ArrayResize(m_warnAt, m_n);
   for(int i = 0; i < m_n; i++)
     {
      m_sym[i]        = syms[i];
      m_state[i]      = 0;
      m_check[i]      = 0;
      m_lastBar[i]    = 0;
      m_seenBar[i]    = 0;
      m_seenAt[i]     = 0;
      m_retryAt[i]    = 0;
      m_retryCount[i] = 0;
      m_warnAt[i]     = 0;
      SymbolSelect(m_sym[i], true);
      const string s = m_sym[i];
      PrintFormat("[AMS] キャリーの層：%s 最小 %.2f lot・刻み %.2f、1 lot の額 %.0f、スワップ（方式=%d）買い %.4f / 売り %.4f → 年率に直すと 買い %+.2f%% / 売り %+.2f%%、取引の可否（方式）%d",
                  s, SymbolInfoDouble(s, SYMBOL_VOLUME_MIN), SymbolInfoDouble(s, SYMBOL_VOLUME_STEP), NotionalPerLot(s),
                  (int)SymbolInfoInteger(s, SYMBOL_SWAP_MODE), SymbolInfoDouble(s, SYMBOL_SWAP_LONG), SymbolInfoDouble(s, SYMBOL_SWAP_SHORT),
                  SwapAnnualPct(s, true), SwapAnnualPct(s, false), (int)SymbolInfoInteger(s, SYMBOL_TRADE_MODE));
     }
   if(m_n > 0)
     {
      PrintFormat("[AMS] キャリーの層：%d 銘柄、1銘柄の値動き 口座の年 %.2f%%、持つ条件：スワップの受け取りが年 %.2f%% より大きい向きで、終値が %d 日の平均の同じ側（%d 日ごとに見直し）、逆指値 1日の値動き × %.1f、建玉の上限 %.1f 倍%s",
                  m_n, m_unit, m_minSwap, m_look, m_checkDays, m_slVolMul, m_maxLev, m_dryRun ? "、**観察モード（注文は出しません）**" : "");
      if(MQLInfoInteger(MQL_TESTER))
         Print("[AMS] キャリーの層：注意：テスターは今日のスワップを全期間に使うため、この層の損益はテスターでは検証できません（動作の確認だけ）");
      else
        {
         LoadState();
         //--- その日のスワップを書き出す（回ごとに記録をためて、「スワップ ＝ 先物の限月どうしの差 − 業者の取り分」をあとで確かめるため）
         const int fh = FileOpen("AMS_swaps_today.csv", FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
         if(fh != INVALID_HANDLE)
           {
            FileWrite(fh, "date", "symbol", "swap_mode", "swap_long", "swap_short", "long_pct_year", "short_pct_year", "bid");
            for(int i = 0; i < m_n; i++)
              {
               const string s = m_sym[i];
               const double pl = SwapAnnualPct(s, true), ps = SwapAnnualPct(s, false);
               FileWrite(fh, TimeToString(TimeCurrent(), TIME_DATE), s, IntegerToString((int)SymbolInfoInteger(s, SYMBOL_SWAP_MODE)),
                         DoubleToString(SymbolInfoDouble(s, SYMBOL_SWAP_LONG), 4), DoubleToString(SymbolInfoDouble(s, SYMBOL_SWAP_SHORT), 4),
                         pl == EMPTY_VALUE ? "" : DoubleToString(pl, 3), ps == EMPTY_VALUE ? "" : DoubleToString(ps, 3),
                         DoubleToString(SymbolInfoDouble(s, SYMBOL_BID), (int)SymbolInfoInteger(s, SYMBOL_DIGITS)));
              }
            FileClose(fh);
           }
        }
     }
   return(m_n > 0);
  }

//+------------------------------------------------------------------+
double CCarrySleeve::NotionalPerLot(const string sym)
  {
   const double tv    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   const double ts    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   const double price = SymbolInfoDouble(sym, SYMBOL_BID);
   if(ts <= 0.0 || tv <= 0.0 || price <= 0.0)
      return(0.0);
   return(price / ts * tv);
  }

//+------------------------------------------------------------------+
double CCarrySleeve::NormalizeLots(const string sym, const double lots)
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
//| この層の建玉（買い − 売り、ロット）                                    |
//+------------------------------------------------------------------+
double CCarrySleeve::SignedLots(const string sym)
  {
   double net = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != m_magic)
         continue;
      const double v = PositionGetDouble(POSITION_VOLUME);
      net += (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? v : -v;
     }
   return(net);
  }

//+------------------------------------------------------------------+
//| スワップを、値段に対する年率（%）に直す。受け取りがプラス。              |
//| 計算できない方式のときは EMPTY_VALUE                                  |
//+------------------------------------------------------------------+
double CCarrySleeve::SwapAnnualPct(const string sym, const bool isLong)
  {
   const double v    = SymbolInfoDouble(sym, isLong ? SYMBOL_SWAP_LONG : SYMBOL_SWAP_SHORT);
   const int    mode = (int)SymbolInfoInteger(sym, SYMBOL_SWAP_MODE);
   const double bid  = SymbolInfoDouble(sym, SYMBOL_BID);
   if(mode == SYMBOL_SWAP_MODE_DISABLED)
      return(0.0);
   if(mode == SYMBOL_SWAP_MODE_INTEREST_CURRENT || mode == SYMBOL_SWAP_MODE_INTEREST_OPEN)
      return(v);                                             // 年率（%）で決まっている
   if(mode == SYMBOL_SWAP_MODE_POINTS && bid > 0.0)
      return(v * SymbolInfoDouble(sym, SYMBOL_POINT) / bid * 100.0 * 360.0);   // 1日あたりのポイント
   if(mode == SYMBOL_SWAP_MODE_CURRENCY_DEPOSIT)
     {
      const double npl = NotionalPerLot(sym);                 // 1 lot・1日あたりの額（口座の通貨）
      if(npl > 0.0)
         return(v / npl * 100.0 * 360.0);
     }
   return(EMPTY_VALUE);
  }

//+------------------------------------------------------------------+
//| 値段を、その銘柄の呼び値の刻みに合わせる（刻みが小数点以下の桁数より粗い銘柄がある。|
//| 例：原油は表示が小数3桁でも、刻みは 0.01。合っていないと、逆指値が拒否される）       |
//+------------------------------------------------------------------+
double CCarrySleeve::ToTick(const string sym, const double price)
  {
   const double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   const int    dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   if(ts <= 0.0)
      return(NormalizeDouble(price, dg));
   return(NormalizeDouble(MathRound(price / ts) * ts, dg));
  }

//+------------------------------------------------------------------+
void CCarrySleeve::Warn(const int i, const string msg)
  {
   const datetime now = TimeCurrent();
   if((long)now - (long)m_warnAt[i] < 6 * 3600)
      return;
   m_warnAt[i] = now;
   PrintFormat("[AMS] キャリーの層：%s %s", m_sym[i], msg);
  }

//+------------------------------------------------------------------+
void CCarrySleeve::CloseAll(const string sym, const string why)
  {
   if(m_dryRun)
     {
      PrintFormat("[AMS] キャリーの層：（観察モード）%s を決済するところ（%s）", sym, why);
      return;
     }
   m_tr.SetTypeFillingBySymbol(sym);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != m_magic)
         continue;
      if(m_tr.PositionClose(tk))
        {
         m_cntClose++;
         PrintFormat("[AMS] キャリーの層：決済 %s #%I64u（%s）", sym, tk, why);
        }
      else
        {
         m_tradeFail = true;
         PrintFormat("[AMS] キャリーの層：%s の決済に失敗（%d %s）", sym, m_tr.ResultRetcode(), m_tr.ResultRetcodeDescription());
        }
     }
  }

//+------------------------------------------------------------------+
//| dir の向き（+1 買い / −1 売り）に lots 増やす                          |
//+------------------------------------------------------------------+
void CCarrySleeve::Open(const string sym, const int dir, double lots, const double dailyVol)
  {
   const double bid = SymbolInfoDouble(sym, SYMBOL_BID), ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   const int    dg  = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   if(m_dryRun)
     {
      PrintFormat("[AMS] キャリーの層：（観察モード）%s を %.2f lot %s ところ（買値 %s・売値 %s）", sym, lots, dir > 0 ? "買う" : "売る",
                  DoubleToString(ask, dg), DoubleToString(bid, dg));
      return;
     }
   m_tr.SetTypeFillingBySymbol(sym);
   const double mx  = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   const string cmt = StringFormat("AMS|%s|SLEEVE|CR", sym);
   while(lots > 0.0)
     {
      const double v = NormalizeLots(sym, (mx > 0.0) ? MathMin(lots, mx) : lots);
      if(v <= 0.0)
         break;
      double sl = 0.0;
      if(m_slVolMul > 0.0 && dailyVol > 0.0)
         sl = ToTick(sym, dir > 0 ? SymbolInfoDouble(sym, SYMBOL_BID) * (1.0 - m_slVolMul * dailyVol)
                                  : SymbolInfoDouble(sym, SYMBOL_ASK) * (1.0 + m_slVolMul * dailyVol));
      const bool ok = (dir > 0) ? m_tr.Buy(v, sym, 0.0, sl, 0.0, cmt) : m_tr.Sell(v, sym, 0.0, sl, 0.0, cmt);
      if(!ok)
        {
         m_tradeFail = true;
         PrintFormat("[AMS] キャリーの層：%s の注文に失敗（%d %s）", sym, m_tr.ResultRetcode(), m_tr.ResultRetcodeDescription());
         break;
        }
      m_cntOpen++;
      PrintFormat("[AMS] キャリーの層：%s %s %.2f lot @%s", sym, dir > 0 ? "BUY" : "SELL", v, DoubleToString(m_tr.ResultPrice(), dg));
      lots -= v;
     }
  }

//+------------------------------------------------------------------+
//| dir の向きの建玉を lots 減らす                                        |
//+------------------------------------------------------------------+
void CCarrySleeve::Reduce(const string sym, const int dir, double lots)
  {
   if(m_dryRun)
     {
      PrintFormat("[AMS] キャリーの層：（観察モード）%s を %.2f lot 減らすところ", sym, lots);
      return;
     }
   m_tr.SetTypeFillingBySymbol(sym);
   const long want = (dir > 0) ? POSITION_TYPE_BUY : POSITION_TYPE_SELL;
   for(int i = PositionsTotal() - 1; i >= 0 && lots > 1e-9; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != m_magic)
         continue;
      if(PositionGetInteger(POSITION_TYPE) != want)
         continue;
      const double pv = PositionGetDouble(POSITION_VOLUME);
      if(pv <= lots + 1e-9)
        {
         if(m_tr.PositionClose(tk))
            lots -= pv;
         else
           {
            m_tradeFail = true;
            PrintFormat("[AMS] キャリーの層：%s の決済に失敗（%d %s）", sym, m_tr.ResultRetcode(), m_tr.ResultRetcodeDescription());
           }
        }
      else
        {
         const double v = NormalizeLots(sym, lots);
         if(v <= 0.0)
            break;
         if(m_tr.PositionClosePartial(tk, v))
            lots -= v;
         else
           {
            m_tradeFail = true;
            PrintFormat("[AMS] キャリーの層：%s の一部の決済に失敗（%d %s）", sym, m_tr.ResultRetcode(), m_tr.ResultRetcodeDescription());
            break;
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| 逆指値を、今の値段から「1日の値動き × k」だけ離して置き直す              |
//+------------------------------------------------------------------+
void CCarrySleeve::ApplyStops(const string sym, const double dailyVol)
  {
   if(m_slVolMul <= 0.0 || dailyVol <= 0.0 || m_dryRun)
      return;
   const double bid = SymbolInfoDouble(sym, SYMBOL_BID), ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   const double pt  = SymbolInfoDouble(sym, SYMBOL_POINT);
   const int    dg  = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   if(bid <= 0.0 || ask <= 0.0 || pt <= 0.0)
      return;
   const double minDist = (double)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL) * pt;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != m_magic)
         continue;
      double sl;
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
        {
         sl = bid * (1.0 - m_slVolMul * dailyVol);
         if(bid - sl < minDist)
            sl = bid - minDist;
        }
      else
        {
         sl = ask * (1.0 + m_slVolMul * dailyVol);
         if(sl - ask < minDist)
            sl = ask + minDist;
        }
      sl = ToTick(sym, sl);
      if(MathAbs(PositionGetDouble(POSITION_SL) - sl) < 0.5 * MathMax(pt, SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE)))
         continue;
      if(!m_tr.PositionModify(tk, sl, PositionGetDouble(POSITION_TP)))
        {
         m_cntStopFail++;
         PrintFormat("[AMS] キャリーの層：%s #%I64u の逆指値を置き直せません（%d %s、指定 %s）。前の逆指値のまま持ち、次の日足でまた置き直します", sym, tk,
                     m_tr.ResultRetcode(), m_tr.ResultRetcodeDescription(), DoubleToString(sl, dg));
        }
     }
  }

//+------------------------------------------------------------------+
//| 状態の保存・読み込み（行：銘柄,処理した日足,見直した日足,状態）           |
//+------------------------------------------------------------------+
void CCarrySleeve::SaveState(void)
  {
   if(MQLInfoInteger(MQL_TESTER) || m_dryRun)
      return;
   const int fh = FileOpen(m_stateFile, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fh == INVALID_HANDLE)
      return;
   for(int i = 0; i < m_n; i++)
      FileWrite(fh, m_sym[i], IntegerToString((long)m_lastBar[i]), IntegerToString((long)m_check[i]), IntegerToString(m_state[i]));
   FileClose(fh);
  }

//+------------------------------------------------------------------+
void CCarrySleeve::LoadState(void)
  {
   if(m_dryRun)
      return;
   const int fh = FileOpen(m_stateFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fh == INVALID_HANDLE)
      return;
   while(!FileIsEnding(fh))
     {
      const string s  = FileReadString(fh);
      const string lb = FileReadString(fh);
      const string ck = FileReadString(fh);
      const string st = FileReadString(fh);
      for(int i = 0; i < m_n; i++)
         if(m_sym[i] == s)
           {
            m_lastBar[i] = (datetime)StringToInteger(lb);
            m_check[i]   = (datetime)StringToInteger(ck);
            m_state[i]   = (int)StringToInteger(st);
            PrintFormat("[AMS] キャリーの層：%s 状態を読み込み（%s、見直した日足 %s）", s,
                        m_state[i] > 0 ? "買い" : (m_state[i] < 0 ? "売り" : "持たない"), TimeToString(m_check[i], TIME_DATE));
           }
     }
   FileClose(fh);
  }

//+------------------------------------------------------------------+
//| 新しい日足が始まった銘柄を処理する                                     |
//+------------------------------------------------------------------+
bool CCarrySleeve::Process(const int i, const datetime t0)
  {
   const string sym = m_sym[i];
   MqlRates rt[];
   ArraySetAsSeries(rt, false);
   const int need = m_look + 62;
   const int got  = CopyRates(sym, PERIOD_D1, 1, need, rt);        // 確定した日足だけ
   if(got < m_look + 2)
     {
      Warn(i, StringFormat("日足が足りないため、まだ判定できません（%d 本、必要 %d 本）", got, m_look + 2));
      return(false);
     }
   double sum = 0.0;
   for(int k = got - m_look; k < got; k++)
      sum += rt[k].close;
   const double sma = sum / m_look;
   const double c   = rt[got - 1].close;
   //--- 1日の値動きの大きさ（直近60日。足りなければ、ある分だけ）
   const int nv = (int)MathMin(60, got - 1);
   double s1 = 0.0, s2 = 0.0;
   for(int k = got - nv; k < got; k++)
     {
      const double r = rt[k].close / rt[k - 1].close - 1.0;
      s1 += r;
      s2 += r * r;
     }
   const double var      = (nv > 1) ? (s2 - s1 * s1 / nv) / (nv - 1) : 0.0;
   const double dailyVol = (var > 0.0) ? MathSqrt(var) : 0.0;
   const double annVol   = MathMax(dailyVol * MathSqrt(252.0), 0.05);
   //--- スワップ（年率。受け取りがプラス）
   const double swL = SwapAnnualPct(sym, true), swS = SwapAnnualPct(sym, false);
   bool   changed = false;
   string note    = "";
   if(m_check[i] == 0 || (long)rt[got - 1].time - (long)m_check[i] >= (long)m_checkDays * 86400)
     {
      int st = 0;
      if(swL != EMPTY_VALUE && swL > m_minSwap && c > sma)
         st = 1;
      else if(swS != EMPTY_VALUE && swS > m_minSwap && c < sma)
         st = -1;
      m_check[i] = rt[got - 1].time;
      if(st != m_state[i])
        {
         m_state[i] = st;
         changed = true;
         note = StringFormat(" %s（スワップ 買い %+.2f%%・売り %+.2f%%、終値 %s、%d日の平均 %s）", st > 0 ? "買い" : (st < 0 ? "売り" : "手じまい"),
                             swL == EMPTY_VALUE ? 0.0 : swL, swS == EMPTY_VALUE ? 0.0 : swS,
                             DoubleToString(c, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)), m_look,
                             DoubleToString(sma, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)));
        }
     }
   if(swL == EMPTY_VALUE || swS == EMPTY_VALUE)
      Warn(i, "スワップの方式が読めないため、持ちません");
   //--- 目標の建玉
   const double equity = SizingEquity();
   const double npl    = NotionalPerLot(sym);
   if(npl <= 0.0)
     {
      Warn(i, "1 lot の額が計算できないため、まだ売買できません");
      return(false);
     }
   double frac = m_unit / 100.0 / annVol;
   if(m_maxLev > 0.0 && frac > m_maxLev)
      frac = m_maxLev;
   const int    dir = m_state[i];
   const double tl  = (dir != 0) ? NormalizeLots(sym, equity * frac / npl) : 0.0;
   m_tradeFail = false;
   double cur = SignedLots(sym);
   if(dir == 0 || tl <= 0.0)
     {
      if(MathAbs(cur) > 1e-9)
         CloseAll(sym, dir == 0 ? "条件がそろわなくなった" : "目標が最小の取引単位に届かない");
     }
   else
     {
      if(cur * dir < -1e-9)                                   // 逆の向きを持っている → すべて決済してから建て直す
        {
         CloseAll(sym, "向きが変わった");
         cur = m_dryRun ? 0.0 : SignedLots(sym);
        }
      const double have = MathAbs(cur);
      if(!m_tradeFail && (changed || MathAbs(have - tl) > m_band * MathMax(have, tl)))
        {
         if(tl > have)
            Open(sym, dir, tl - have, dailyVol);
         else if(have > tl)
            Reduce(sym, dir, have - tl);
        }
      ApplyStops(sym, dailyVol);
     }
   if(changed || note != "" || m_dryRun)
      PrintFormat("[AMS] キャリーの層：%s%s → %s、目標 %.2f lot（値動きの見積もり 年 %.1f%%、スワップ 買い %+.2f%%・売り %+.2f%%、終値 %s／%d日の平均 %s、今の建玉 %+.2f lot）",
                  sym, note, dir > 0 ? "買い" : (dir < 0 ? "売り" : "持たない"), tl, annVol * 100.0,
                  swL == EMPTY_VALUE ? 0.0 : swL, swS == EMPTY_VALUE ? 0.0 : swS,
                  DoubleToString(c, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)), m_look,
                  DoubleToString(sma, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)), cur);
   if(m_tradeFail)
     {
      m_tradeFail = false;
      m_cntRetry++;
      m_retryCount[i]++;
      if(m_retryCount[i] <= 120)
        {
         m_retryAt[i] = TimeCurrent() + 30;                   // 30秒後からやり直す（最大 120 回 = 約1時間）
         return(false);
        }
      PrintFormat("[AMS] キャリーの層：%s 売買のやり直しが上限（120回）に達したため、この日足ではあきらめます", sym);
     }
   m_retryCount[i] = 0;
   return(true);
  }

//+------------------------------------------------------------------+
void CCarrySleeve::OnTick(void)
  {
   const datetime now = TimeCurrent();
   bool saved = false;
   for(int i = 0; i < m_n; i++)
     {
      const datetime t0 = iTime(m_sym[i], PERIOD_D1, 0);
      if(t0 <= 0 || t0 == m_lastBar[i])
         continue;
      if(m_seenBar[i] != t0)
        {
         m_seenBar[i] = t0;
         m_seenAt[i]  = now;
        }
      if((long)now - (long)m_seenAt[i] < m_delaySec)
         continue;
      if(now < m_retryAt[i])
         continue;
      MqlTick tk;
      if(!SymbolInfoTick(m_sym[i], tk) || tk.bid <= 0.0 || tk.ask <= 0.0)
         continue;
      if((long)now - (long)tk.time > 600)
         continue;
      if(m_maxSpreadPct > 0.0 && (tk.ask - tk.bid) / tk.bid * 100.0 > m_maxSpreadPct)
        {
         Warn(i, StringFormat("スプレッドが広いため待ちます（%.3f%%、上限 %.3f%%）", (tk.ask - tk.bid) / tk.bid * 100.0, m_maxSpreadPct));
         continue;
        }
      if(Process(i, t0))
        {
         m_lastBar[i] = t0;
         saved = true;
        }
     }
   if(saved)
      SaveState();
  }

//+------------------------------------------------------------------+
void CCarrySleeve::Summary(void)
  {
   if(m_n <= 0)
      return;
   PrintFormat("[AMS] キャリーの層：新しく建てた回数 %d、決済した回数 %d、注文の失敗でやり直した回数 %d、逆指値を置き直せなかった回数 %d", m_cntOpen, m_cntClose, m_cntRetry, m_cntStopFail);
  }
//+------------------------------------------------------------------+

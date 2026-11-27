//+------------------------------------------------------------------+
//| IndexSleeves.mqh                                                 |
//| 売買の方式 8：株価指数・金の層（93章）                                |
//| 判断に使うのは、その銘柄の日足（終値・高値・安値）だけ。                 |
//| 時刻・曜日・日付は、売買の判断には使わない。                           |
//|                                                                  |
//| 売られすぎの戻り（買いだけ。数値は公表されたまま）：                     |
//|  R2  終値が200日の平均より上で RSI(2) が 10 未満 → 買い。              |
//|      終値が5日の平均を上回ったら手じまい                              |
//|  D7  終値が200日の平均より上で、過去7日の終値の最安値 → 買い。          |
//|      過去7日の終値の最高値になったら手じまい                           |
//|  IBS (終値 − 安値) ÷ (高値 − 安値) が 0.2 未満 → 買い。次の日足で見直す  |
//| 順張り（買いだけ）：                                                |
//|  TREND 終値が200日の平均より上のあいだだけ持つ（N 日ごとに見直す）       |
//|                                                                  |
//| 判定は、日足が確定したあと（次の日足が始まってから）に行い、その時点の     |
//| 値段で売買する。建玉は、その銘柄の直近60日の値動きから、ルール1つ分の     |
//| 値動きが「口座の年 x %」になる大きさにする。                           |
//| ルールごとに別々の建玉は持たず、銘柄ごとの合計（目標のロット）に合わせる。 |
//+------------------------------------------------------------------+
#ifndef AMS_INDEXSLEEVES_MQH
#define AMS_INDEXSLEEVES_MQH

#include <Trade\Trade.mqh>

#define IX_R2     0
#define IX_D7     1
#define IX_IBS    2
#define IX_TREND  3
#define IX_NR     4
#define IX_BARS   262    // 判定に使う日足の本数（200日の平均と、RSI の計算の助走）
#define IX_REPLAY 30     // 止まっていたあいだの日足を、さかのぼって確かめる本数の上限

class CIndexSleeves
  {
private:
   CTrade           *m_trade;
   ulong             m_magic;
   string            m_sym[];
   int               m_n;
   bool              m_rev[];          // 売られすぎの戻りを使う銘柄か
   bool              m_trd[];          // 順張りを使う銘柄か
   bool              m_ruleOn[3];      // R2・D7・IBS を使うか
   double            m_revUnit;        // 戻り：ルール1つ分の建玉の値動き（口座に対する年率 %）
   double            m_trendUnit;      // 順張り：1銘柄の建玉の値動き（口座に対する年率 %）
   int               m_trendDays;      // 順張りの見直しの間隔（日）
   double            m_maxLev;         // 建玉の合計 ÷ 有効証拠金 の上限
   double            m_maxMarginPct;   // 必要証拠金 ÷ 有効証拠金 の上限（%）
   double            m_band;           // 今の建玉と目標の差がこの割合未満なら、大きさは直さない
   double            m_slVolMul;       // 急変に備えた損切り：日々の値動きの何倍か（0 で置かない）
   int               m_delaySec;       // 新しい日足が始まってから、売買するまで待つ秒数
   double            m_maxSpreadPct;   // スプレッドがこの割合（値段に対する %）を超えているあいだは待つ
   int               m_state[][IX_NR]; // ルールごとの状態（1 = 持つ）
   datetime          m_lastBar[];      // 最後に処理したときの、作りかけの日足の時刻
   datetime          m_seenBar[];      // 新しい日足を見つけたときの、その日足の時刻
   datetime          m_seenAt[];       // 見つけた時刻
   datetime          m_trendCheck[];   // 順張りを最後に見直した日足の時刻
   double            m_target[];       // 銘柄ごとの目標の建玉の額（口座通貨）
   datetime          m_warnAt[];       // 同じ注意を何度も出さないための時刻
   string            m_stateFile;

   double            NotionalPerLot(const string sym);
   double            CurrentLots(const string sym, int &dir);
   double            NormalizeLots(const string sym, const double lots);
   void              CloseSymbol(const string sym, const string why);
   void              OpenLots(const string sym, double lots, const double dailyVol);
   void              ReduceLots(const string sym, double lots);
   bool              Process(const int i, const datetime t0);
   void              Warn(const int i, const string msg);
   void              SaveState(void);
   void              LoadState(void);
   string            StateText(const int i);

public:
                     CIndexSleeves(void) : m_trade(NULL), m_magic(0), m_n(0) {}
   bool              Init(CTrade *trade, const ulong magic, const string &revSyms[], const string &trendSyms[],
                          const bool useR2, const bool useD7, const bool useIBS, const double revUnit, const double trendUnit,
                          const int trendDays, const double maxLev, const double maxMarginPct, const double band,
                          const double slVolMul, const int delayMin, const double maxSpreadPct);
   void              OnTick(void);
  };

//+------------------------------------------------------------------+
bool CIndexSleeves::Init(CTrade *trade, const ulong magic, const string &revSyms[], const string &trendSyms[],
                         const bool useR2, const bool useD7, const bool useIBS, const double revUnit, const double trendUnit,
                         const int trendDays, const double maxLev, const double maxMarginPct, const double band,
                         const double slVolMul, const int delayMin, const double maxSpreadPct)
  {
   m_trade        = trade;
   m_magic        = magic;
   m_ruleOn[IX_R2]  = useR2;
   m_ruleOn[IX_D7]  = useD7;
   m_ruleOn[IX_IBS] = useIBS;
   m_revUnit      = MathMax(0.0, revUnit);
   m_trendUnit    = MathMax(0.0, trendUnit);
   m_trendDays    = (int)MathMax(1, trendDays);
   m_maxLev       = maxLev;
   m_maxMarginPct = maxMarginPct;
   m_band         = band;
   m_slVolMul     = slVolMul;
   m_delaySec     = (int)MathMax(0, delayMin) * 60;
   m_maxSpreadPct = maxSpreadPct;
   m_stateFile    = StringFormat("AMS_ix_state_%I64u.csv", magic);
   //--- 銘柄の一覧（戻りと順張りの両方に出てくる銘柄は、1つにまとめる）
   m_n = 0;
   for(int pass = 0; pass < 2; pass++)
     {
      const int cnt = (pass == 0) ? ArraySize(revSyms) : ArraySize(trendSyms);
      for(int k = 0; k < cnt; k++)
        {
         const string s = (pass == 0) ? revSyms[k] : trendSyms[k];
         int at = -1;
         for(int i = 0; i < m_n; i++)
            if(m_sym[i] == s)
               at = i;
         if(at < 0)
           {
            at = m_n++;
            ArrayResize(m_sym, m_n);
            ArrayResize(m_rev, m_n);
            ArrayResize(m_trd, m_n);
            m_sym[at] = s;
            m_rev[at] = false;
            m_trd[at] = false;
           }
         if(pass == 0)
            m_rev[at] = true;
         else
            m_trd[at] = true;
        }
     }
   ArrayResize(m_state, m_n);
   ArrayResize(m_lastBar, m_n);
   ArrayResize(m_seenBar, m_n);
   ArrayResize(m_seenAt, m_n);
   ArrayResize(m_trendCheck, m_n);
   ArrayResize(m_target, m_n);
   ArrayResize(m_warnAt, m_n);
   for(int i = 0; i < m_n; i++)
     {
      for(int r = 0; r < IX_NR; r++)
         m_state[i][r] = 0;
      m_lastBar[i] = 0;
      m_seenBar[i] = 0;
      m_seenAt[i] = 0;
      m_trendCheck[i] = 0;
      m_target[i] = 0.0;
      m_warnAt[i] = 0;
      if(!SymbolSelect(m_sym[i], true))
         PrintFormat("[AMS] 指数の層：%s を気配値表示に追加できません", m_sym[i]);
      PrintFormat("[AMS] 指数の層：%s（%s%s）最小 %.2f lot・刻み %.2f、1 lot の額 %.0f、スワップ（方式=%d）買い %.4f / 売り %.4f",
                  m_sym[i], m_rev[i] ? "戻り" : "", m_trd[i] ? (m_rev[i] ? "・順張り" : "順張り") : "",
                  SymbolInfoDouble(m_sym[i], SYMBOL_VOLUME_MIN), SymbolInfoDouble(m_sym[i], SYMBOL_VOLUME_STEP), NotionalPerLot(m_sym[i]),
                  (int)SymbolInfoInteger(m_sym[i], SYMBOL_SWAP_MODE), SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_LONG),
                  SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_SHORT));
     }
   if(!MQLInfoInteger(MQL_TESTER))
      LoadState();
   //--- 使わないルール・使わない層の状態は、前回の記録に残っていても 0 に戻す
   for(int i = 0; i < m_n; i++)
     {
      for(int r = 0; r < 3; r++)
         if(!m_ruleOn[r] || !m_rev[i])
            m_state[i][r] = 0;
      if(!m_trd[i])
         m_state[i][IX_TREND] = 0;
     }
   PrintFormat("[AMS] 指数の層：%d 銘柄、戻りのルール %s%s%s（1つ分の値動き 口座の年 %.2f%%）、順張り（1銘柄 年 %.2f%%、%d 日ごとに見直し）、"
               "建玉の合計の上限 %.1f 倍、待ち %d 秒、スプレッドの上限 %.3f%%",
               m_n, m_ruleOn[IX_R2] ? "R2 " : "", m_ruleOn[IX_D7] ? "D7 " : "", m_ruleOn[IX_IBS] ? "IBS" : "", m_revUnit,
               m_trendUnit, m_trendDays, m_maxLev, m_delaySec, m_maxSpreadPct);
   return(m_n > 0);
  }

//+------------------------------------------------------------------+
//| 1ロットの建玉の額（口座通貨）                                         |
//+------------------------------------------------------------------+
double CIndexSleeves::NotionalPerLot(const string sym)
  {
   const double tv    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   const double ts    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   const double price = SymbolInfoDouble(sym, SYMBOL_BID);
   if(ts <= 0.0 || tv <= 0.0 || price <= 0.0)
      return(0.0);
   return(price / ts * tv);
  }

//+------------------------------------------------------------------+
//| この方式の建玉（ロット、向き）。買いと売りがあれば差し引き                |
//+------------------------------------------------------------------+
double CIndexSleeves::CurrentLots(const string sym, int &dir)
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
double CIndexSleeves::NormalizeLots(const string sym, const double lots)
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
void CIndexSleeves::CloseSymbol(const string sym, const string why)
  {
   m_trade.SetTypeFillingBySymbol(sym);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != m_magic)
         continue;
      if(m_trade.PositionClose(tk))
         PrintFormat("[AMS] 指数の層：決済 %s #%I64u（%s）", sym, tk, why);
      else
         PrintFormat("[AMS] 指数の層：%s の決済に失敗（%d %s）", sym, m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
     }
  }

//+------------------------------------------------------------------+
//| 買いを lots 増やす（1回の注文の上限を超える分は分けて注文）              |
//+------------------------------------------------------------------+
void CIndexSleeves::OpenLots(const string sym, double lots, const double dailyVol)
  {
   m_trade.SetTypeFillingBySymbol(sym);
   const double mx  = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   const int    dg  = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   const string cmt = StringFormat("AMS|%s|SLEEVE|IX", sym);
   while(lots > 0.0)
     {
      const double v = NormalizeLots(sym, (mx > 0.0) ? MathMin(lots, mx) : lots);
      if(v <= 0.0)
         break;
      const double price = SymbolInfoDouble(sym, SYMBOL_ASK);
      double sl = 0.0;
      if(m_slVolMul > 0.0 && dailyVol > 0.0)
         sl = NormalizeDouble(price * (1.0 - m_slVolMul * dailyVol), dg);
      if(!m_trade.Buy(v, sym, 0.0, sl, 0.0, cmt))
        {
         PrintFormat("[AMS] 指数の層：%s の注文に失敗（%d %s）", sym, m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
         break;
        }
      PrintFormat("[AMS] 指数の層：%s BUY %.2f lot @%s", sym, v, DoubleToString(m_trade.ResultPrice(), dg));
      lots -= v;
     }
  }

//+------------------------------------------------------------------+
void CIndexSleeves::ReduceLots(const string sym, double lots)
  {
   m_trade.SetTypeFillingBySymbol(sym);
   for(int i = PositionsTotal() - 1; i >= 0 && lots > 1e-9; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != m_magic)
         continue;
      if(PositionGetInteger(POSITION_TYPE) != POSITION_TYPE_BUY)
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
         else
            break;
        }
     }
  }

//+------------------------------------------------------------------+
void CIndexSleeves::Warn(const int i, const string msg)
  {
   const datetime now = TimeCurrent();
   if((long)now - (long)m_warnAt[i] < 6 * 3600)
      return;
   m_warnAt[i] = now;
   PrintFormat("[AMS] 指数の層：%s %s", m_sym[i], msg);
  }

//+------------------------------------------------------------------+
string CIndexSleeves::StateText(const int i)
  {
   string s = "";
   if(m_state[i][IX_R2] > 0)
      s += "R2 ";
   if(m_state[i][IX_D7] > 0)
      s += "D7 ";
   if(m_state[i][IX_IBS] > 0)
      s += "IBS ";
   if(m_state[i][IX_TREND] > 0)
      s += "TREND ";
   return(s == "" ? "なし" : s);
  }

//+------------------------------------------------------------------+
//| 状態の保存（実運用。共通フォルダ。デモ口座の回をまたいで引き継ぐ）         |
//| 行：銘柄,最後に処理した日足,順張りを見直した日足,R2,D7,IBS,TREND,目標の額  |
//+------------------------------------------------------------------+
void CIndexSleeves::SaveState(void)
  {
   if(MQLInfoInteger(MQL_TESTER))
      return;
   const int fh = FileOpen(m_stateFile, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fh == INVALID_HANDLE)
      return;
   for(int i = 0; i < m_n; i++)
      FileWrite(fh, m_sym[i], IntegerToString((long)m_lastBar[i]), IntegerToString((long)m_trendCheck[i]),
                IntegerToString(m_state[i][IX_R2]), IntegerToString(m_state[i][IX_D7]), IntegerToString(m_state[i][IX_IBS]),
                IntegerToString(m_state[i][IX_TREND]), DoubleToString(m_target[i], 0));
   FileClose(fh);
  }

//+------------------------------------------------------------------+
void CIndexSleeves::LoadState(void)
  {
   const int fh = FileOpen(m_stateFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fh == INVALID_HANDLE)
      return;
   int rows = 0;
   while(!FileIsEnding(fh))
     {
      const string sy = FileReadString(fh);
      const string lb = FileReadString(fh);
      const string tc = FileReadString(fh);
      const string s0 = FileReadString(fh);
      const string s1 = FileReadString(fh);
      const string s2 = FileReadString(fh);
      const string s3 = FileReadString(fh);
      const string tg = FileReadString(fh);
      if(sy == "")
         continue;
      for(int i = 0; i < m_n; i++)
        {
         if(m_sym[i] != sy)
            continue;
         m_lastBar[i]         = (datetime)StringToInteger(lb);
         m_trendCheck[i]      = (datetime)StringToInteger(tc);
         m_state[i][IX_R2]    = (int)StringToInteger(s0);
         m_state[i][IX_D7]    = (int)StringToInteger(s1);
         m_state[i][IX_IBS]   = (int)StringToInteger(s2);
         m_state[i][IX_TREND] = (int)StringToInteger(s3);
         m_target[i]          = StringToDouble(tg);
         rows++;
         PrintFormat("[AMS] 指数の層：%s 前回の状態 %s（最後に処理した日足 %s）", sy, StateText(i), TimeToString(m_lastBar[i], TIME_DATE));
        }
     }
   FileClose(fh);
  }

//+------------------------------------------------------------------+
//| 新しい日足が始まった銘柄を処理する：確定した日足でルールの状態を更新し、   |
//| 目標のロットに合わせる。日足がそろわないときは false（あとでやり直す）    |
//+------------------------------------------------------------------+
bool CIndexSleeves::Process(const int i, const datetime t0)
  {
   const string sym = m_sym[i];
   MqlRates rt[];
   ArraySetAsSeries(rt, false);
   const int got = CopyRates(sym, PERIOD_D1, 1, IX_BARS, rt);
   if(got < 215)
     {
      Warn(i, StringFormat("確定した日足が %d 本しかないため、まだ判定できません（215 本以上が必要）", got));
      return(false);
     }
   //--- 前回の処理のあとに確定した日足（ふつうは1本）。止まっていたあいだの分は、手じまいの条件だけを古い順に確かめる
   int jStart = got - 1;
   if(m_lastBar[i] > 0)
      for(int j = got - 1; j >= 0 && j >= got - IX_REPLAY; j--)
         if(rt[j].time >= m_lastBar[i])
            jStart = j;
   if(jStart < 205)
      jStart = 205;
   bool changed = false;
   string note = "";
   for(int j = jStart; j < got; j++)
     {
      const bool newest = (j == got - 1);
      const double c = rt[j].close;
      double s200 = 0.0, s5 = 0.0, mn7 = c, mx7 = c;
      for(int k = j - 199; k <= j; k++)
         s200 += rt[k].close;
      s200 /= 200.0;
      for(int k = j - 4; k <= j; k++)
         s5 += rt[k].close;
      s5 /= 5.0;
      for(int k = j - 6; k <= j; k++)
        {
         mn7 = MathMin(mn7, rt[k].close);
         mx7 = MathMax(mx7, rt[k].close);
        }
      //--- RSI(2)（ワイルダーの方式。直近60本で計算すれば、十分に収束する）
      double up = 0.0, dn = 0.0;
      bool first = true;
      for(int k = j - 59; k <= j; k++)
        {
         const double d = rt[k].close - rt[k - 1].close;
         const double u = (d > 0.0) ? d : 0.0;
         const double w = (d < 0.0) ? -d : 0.0;
         if(first)
           {
            up = u;
            dn = w;
            first = false;
           }
         else
           {
            up = 0.5 * up + 0.5 * u;
            dn = 0.5 * dn + 0.5 * w;
           }
        }
      const double rsi2 = (dn > 0.0) ? 100.0 - 100.0 / (1.0 + up / dn) : 100.0;
      const double rng  = rt[j].high - rt[j].low;
      const double ibs  = (rng > 0.0) ? (c - rt[j].low) / rng : 0.5;
      const bool   above = (c > s200);
      if(m_rev[i])
        {
         if(m_ruleOn[IX_R2])
           {
            if(m_state[i][IX_R2] > 0)
              {
               if(c > s5)
                 {
                  m_state[i][IX_R2] = 0;
                  changed = true;
                  note += StringFormat(" R2 手じまい（終値 %.2f > 5日の平均 %.2f）", c, s5);
                 }
              }
            else if(newest && above && rsi2 < 10.0)
              {
               m_state[i][IX_R2] = 1;
               changed = true;
               note += StringFormat(" R2 買い（終値 %.2f > 200日の平均 %.2f、RSI(2) %.1f）", c, s200, rsi2);
              }
           }
         if(m_ruleOn[IX_D7])
           {
            if(m_state[i][IX_D7] > 0)
              {
               if(c >= mx7)
                 {
                  m_state[i][IX_D7] = 0;
                  changed = true;
                  note += " D7 手じまい（過去7日の終値の最高値）";
                 }
              }
            else if(newest && above && c <= mn7)
              {
               m_state[i][IX_D7] = 1;
               changed = true;
               note += StringFormat(" D7 買い（終値 %.2f > 200日の平均 %.2f、過去7日の終値の最安値）", c, s200);
              }
           }
         if(m_ruleOn[IX_IBS] && newest)
           {
            const int st = (ibs < 0.2) ? 1 : 0;
            if(st != m_state[i][IX_IBS])
              {
               m_state[i][IX_IBS] = st;
               changed = true;
               note += StringFormat(" IBS %s（%.2f）", st > 0 ? "買い" : "手じまい", ibs);
              }
           }
        }
      if(m_trd[i] && newest && (m_trendCheck[i] == 0 || (long)rt[j].time - (long)m_trendCheck[i] >= (long)m_trendDays * 86400))
        {
         m_trendCheck[i] = rt[j].time;
         const int st = above ? 1 : 0;
         if(st != m_state[i][IX_TREND])
           {
            m_state[i][IX_TREND] = st;
            changed = true;
            note += StringFormat(" 順張り %s（終値 %.2f、200日の平均 %.2f）", st > 0 ? "買い" : "手じまい", c, s200);
           }
        }
     }
   //--- 直近60日の値動きの大きさ（1日あたり、年率）
   double sum = 0.0, sum2 = 0.0;
   for(int k = got - 60; k < got; k++)
     {
      const double r = rt[k].close / rt[k - 1].close - 1.0;
      sum  += r;
      sum2 += r * r;
     }
   const double var = (sum2 - sum * sum / 60.0) / 59.0;
   const double dailyVol = (var > 0.0) ? MathSqrt(var) : 0.0;
   const double annVol = MathMax(dailyVol * MathSqrt(252.0), 0.025);
   //--- 目標の建玉の額
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   const int nRev = m_state[i][IX_R2] + m_state[i][IX_D7] + m_state[i][IX_IBS];
   double tgt = equity * (nRev * m_revUnit + m_state[i][IX_TREND] * m_trendUnit) / 100.0 / annVol;
   double others = 0.0;
   for(int k = 0; k < m_n; k++)
      if(k != i)
         others += m_target[k];
   if(m_maxLev > 0.0 && others + tgt > m_maxLev * equity)
     {
      tgt = MathMax(0.0, m_maxLev * equity - others);
      note += " （建玉の合計の上限のため縮小）";
     }
   m_target[i] = tgt;
   const double npl = NotionalPerLot(sym);
   if(npl <= 0.0)
     {
      Warn(i, "1 lot の額が計算できないため、まだ売買できません");
      return(false);
     }
   const double want = tgt / npl;
   double tl = NormalizeLots(sym, want);
   if(want > 0.0 && tl <= 0.0)
      note += StringFormat(" （目標 %.3f lot が最小の取引単位 %.2f lot に届かないため、持たない）", want, SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN));
   int cdir = 0;
   double cur = CurrentLots(sym, cdir);
   if(cdir < 0)
     {
      CloseSymbol(sym, "売りの建玉は持たない");
      cur = 0.0;
     }
   if(tl <= 0.0)
     {
      if(cur > 0.0)
         CloseSymbol(sym, "持つルールがなくなった");
     }
   else if(changed || MathAbs(cur - tl) > m_band * MathMax(cur, tl))
     {
      if(tl > cur)
        {
         double add = tl - cur;
         //--- 必要証拠金が上限を超えるときは、増やす分を小さくする
         double need = 0.0;
         if(m_maxMarginPct > 0.0 && OrderCalcMargin(ORDER_TYPE_BUY, sym, add, SymbolInfoDouble(sym, SYMBOL_ASK), need) && need > 0.0)
           {
            const double room = equity * m_maxMarginPct / 100.0 - AccountInfoDouble(ACCOUNT_MARGIN);
            if(room <= 0.0)
               add = 0.0;
            else if(need > room)
               add = NormalizeLots(sym, add * room / need);
            if(add < tl - cur)
               note += " （証拠金の上限のため縮小）";
           }
         if(add > 0.0)
            OpenLots(sym, add, dailyVol);
        }
      else if(cur > tl)
         ReduceLots(sym, cur - tl);
     }
   if(changed || note != "")
      PrintFormat("[AMS] 指数の層：%s%s → 持つルール：%s、目標 %.2f lot（額 %.0f、値動き 年 %.1f%%）", sym, note, StateText(i), tl, tgt, annVol * 100.0);
   return(true);
  }

//+------------------------------------------------------------------+
//| 毎ティック：新しい日足が始まった銘柄を処理する                          |
//+------------------------------------------------------------------+
void CIndexSleeves::OnTick(void)
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
      //--- 値段が動いていること（市場が開いていること）と、スプレッドを確かめる
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
      if(!Process(i, t0))
         continue;
      m_lastBar[i] = t0;
      saved = true;
     }
   if(saved)
      SaveState();
  }

#endif // AMS_INDEXSLEEVES_MQH

//+------------------------------------------------------------------+
//| ProbSleeve.mqh                                                   |
//| 確率の層（109章。複合システム）：外で計算した「上がる確率」から決めた合図 z を  |
//|  ファイルから読み、z に比例して買い（または売り）で持つ。                    |
//|  日付・時刻は判断に使わない（日付は、予想の行と日足を結びつけるためだけに使う）。 |
//|                                                                  |
//| 考え方：                                                           |
//|  - 指標・ルール・チャートの形を、すべて数値にして、複数の予想モデルに渡す       |
//|    （tools/eco/）。モデルは「次の日に上がる確率」を出し、それを合成する。      |
//|  - 合図 z ＝（確率 − ふだんの水準）÷ ばらつき を ±2 で打ち切ったもの。         |
//|    確率がふだんより高いほど大きく買い、低いほど小さく（または売りで）持つ。     |
//|  - 建玉 ＝ 有効証拠金 × 単位（年率 %）× |z| ÷ その銘柄の値動き（年率）。       |
//|  - 予想は、判定に使う日足（確定した最後の日足）の日付の行を読む。              |
//|    その日付の行がなければ、持たない（実運用では、ファイルが新しくなるのを        |
//|    決めた分数だけ待つ）。                                              |
//|  - 毎日、今の値段から k × 1日の値動き だけ離して逆指値を置き直す              |
//|    （急な値動きへの備え。ほかの層と同じ）。                               |
//|                                                                  |
//| ファイル（共通フォルダ）：1行目は見出し、以降は「日付(yyyy.MM.dd),銘柄,確率,z」。 |
//|  同じ銘柄の行は、日付の古い順に並んでいること。                            |
//+------------------------------------------------------------------+
#property strict

#include <Trade\Trade.mqh>

class CProbSleeve
  {
private:
   CTrade            m_tr;
   ulong             m_magic;
   string            m_sym[];         // 口座の銘柄名
   string            m_key[];         // ファイルの中の銘柄名
   int               m_n;
   string            m_file;
   double            m_unit;          // |z| = 1 のときの建玉の値動き（口座に対する年率 %）
   bool              m_longOnly;      // 買いだけ（z がマイナスのときは持たない）
   int               m_volDays;       // 値動きの大きさを測る日数
   double            m_slVolMul;      // 逆指値：1日の値動きの何倍か（0 で置かない）
   double            m_maxLev;        // 1銘柄の建玉の額 ÷ 有効証拠金 の上限
   double            m_band;          // 今の建玉と目標の差がこの割合未満なら、大きさは直さない
   int               m_delaySec;
   int               m_waitSec;       // 実運用：その日足の予想がファイルに届くのを待つ秒数
   double            m_maxSpreadPct;
   bool              m_dryRun;
   double            m_eqOffset;
   //--- 予想の表（ファイルの並びのまま）
   datetime          m_pd[];
   int               m_ps[];
   double            m_pz[];
   double            m_pp[];
   int               m_pn;
   int               m_cur[];         // 銘柄ごとの、表の読み進めた位置
   long              m_fileStamp;
   datetime          m_fileCheck;
   double            m_z[];           // いまの合図
   datetime          m_lastBar[];
   datetime          m_seenBar[];
   datetime          m_seenAt[];
   datetime          m_retryAt[];
   int               m_retryCount[];
   datetime          m_warnAt[];
   bool              m_tradeFail;
   int               m_cntOpen, m_cntClose, m_cntRetry, m_cntStopFail, m_cntMiss, m_cntDays, m_cntLong, m_cntShort;

   double            SizingEquity(void) { return(MathMax(0.0, AccountInfoDouble(ACCOUNT_EQUITY) - m_eqOffset)); }
   double            NotionalPerLot(const string sym);
   double            NormalizeLots(const string sym, const double lots);
   double            SignedLots(const string sym);
   double            ToTick(const string sym, const double price);
   void              CloseAll(const string sym, const string why);
   void              Open(const string sym, const int dir, double lots, const double dailyVol);
   void              Reduce(const string sym, const int dir, double lots);
   void              ApplyStops(const string sym, const double dailyVol);
   bool              Process(const int i, const datetime t0);
   void              Warn(const int i, const string msg);
   bool              LoadFile(void);
   void              ReloadIfChanged(void);
   bool              Lookup(const int i, const datetime day, double &z, double &p);

public:
                     CProbSleeve(void) : m_n(0), m_pn(0), m_fileStamp(0), m_fileCheck(0), m_tradeFail(false), m_cntOpen(0), m_cntClose(0), m_cntRetry(0),
                                         m_cntStopFail(0), m_cntMiss(0), m_cntDays(0), m_cntLong(0), m_cntShort(0) {}
   bool              Init(const ulong magic, const string &syms[], const string &keys[], const string file, const double unitVol, const bool longOnly,
                          const int volDays, const double slVolMul, const double maxLev, const double band, const int delayMin, const int waitMin,
                          const double maxSpreadPct, const bool dryRun, const double equityOffset);
   void              OnTick(void);
   void              Summary(void);
   int               Count(void) const { return(m_n); }
  };

//+------------------------------------------------------------------+
bool CProbSleeve::Init(const ulong magic, const string &syms[], const string &keys[], const string file, const double unitVol, const bool longOnly,
                       const int volDays, const double slVolMul, const double maxLev, const double band, const int delayMin, const int waitMin,
                       const double maxSpreadPct, const bool dryRun, const double equityOffset)
  {
   m_magic        = magic;
   m_file         = file;
   m_unit         = MathMax(0.0, unitVol);
   m_longOnly     = longOnly;
   m_volDays      = (int)MathMax(5, volDays);
   m_slVolMul     = slVolMul;
   m_maxLev       = maxLev;
   m_band         = band;
   m_delaySec     = (int)MathMax(0, delayMin) * 60;
   m_waitSec      = (int)MathMax(0, waitMin) * 60;
   m_maxSpreadPct = maxSpreadPct;
   m_dryRun       = dryRun;
   m_eqOffset     = MathMax(0.0, equityOffset);
   m_tr.SetExpertMagicNumber(magic);
   m_n = ArraySize(syms);
   ArrayResize(m_sym, m_n);
   ArrayResize(m_key, m_n);
   ArrayResize(m_cur, m_n);
   ArrayResize(m_z, m_n);
   ArrayResize(m_lastBar, m_n);
   ArrayResize(m_seenBar, m_n);
   ArrayResize(m_seenAt, m_n);
   ArrayResize(m_retryAt, m_n);
   ArrayResize(m_retryCount, m_n);
   ArrayResize(m_warnAt, m_n);
   for(int i = 0; i < m_n; i++)
     {
      m_sym[i]        = syms[i];
      m_key[i]        = keys[i];
      m_cur[i]        = 0;
      m_z[i]          = 0.0;
      m_lastBar[i]    = 0;
      m_seenBar[i]    = 0;
      m_seenAt[i]     = 0;
      m_retryAt[i]    = 0;
      m_retryCount[i] = 0;
      m_warnAt[i]     = 0;
      SymbolSelect(m_sym[i], true);
     }
   if(m_n <= 0)
      return(false);
   const bool ok = LoadFile();
   PrintFormat("[AMS] 確率の層：%d 銘柄、予想のファイル %s（%d 行%s）、|z| = 1 のときの値動き 口座の年 %.2f%%、%s、値動きは直近 %d 日、逆指値 1日の値動き × %.1f、建玉の上限 %.1f 倍%s",
               m_n, m_file, m_pn, ok ? "" : "。**読めません。予想がないあいだは持ちません**", m_unit, m_longOnly ? "買いだけ" : "買いと売り", m_volDays, m_slVolMul, m_maxLev,
               m_dryRun ? "、**影のモード（注文は出さず、確率と判定を記録するだけ）**" : "");
   return(true);
  }

//+------------------------------------------------------------------+
//| 予想のファイルを読む（見出しの次の行から。行：日付,銘柄,確率,z）          |
//+------------------------------------------------------------------+
bool CProbSleeve::LoadFile(void)
  {
   m_pn = 0;
   for(int i = 0; i < m_n; i++)
      m_cur[i] = 0;
   const int fh = FileOpen(m_file, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE, ',');
   if(fh == INVALID_HANDLE)
      return(false);
   m_fileStamp = (long)FileGetInteger(fh, FILE_MODIFY_DATE);
   int cap = 0;
   bool first = true;
   while(!FileIsEnding(fh))
     {
      const string sd = FileReadString(fh);
      const string ss = FileReadString(fh);
      const string sp = FileReadString(fh);
      const string sz = FileReadString(fh);
      if(first)
        {
         first = false;
         if(StringFind(sd, "date") >= 0)
            continue;
        }
      if(sd == "" || ss == "")
         continue;
      int k = -1;
      for(int i = 0; i < m_n; i++)
         if(m_key[i] == ss)
           {
            k = i;
            break;
           }
      if(k < 0)
         continue;
      if(m_pn >= cap)
        {
         cap += 4096;
         ArrayResize(m_pd, cap);
         ArrayResize(m_ps, cap);
         ArrayResize(m_pz, cap);
         ArrayResize(m_pp, cap);
        }
      m_pd[m_pn] = StringToTime(sd);
      m_ps[m_pn] = k;
      m_pp[m_pn] = StringToDouble(sp);
      m_pz[m_pn] = MathMax(-2.0, MathMin(2.0, StringToDouble(sz)));
      m_pn++;
     }
   FileClose(fh);
   return(m_pn > 0);
  }

//+------------------------------------------------------------------+
//| 実運用：ファイルが新しくなっていたら読み直す（1分に1回だけ確かめる）       |
//+------------------------------------------------------------------+
void CProbSleeve::ReloadIfChanged(void)
  {
   if(MQLInfoInteger(MQL_TESTER))
      return;
   const datetime now = TimeCurrent();
   if((long)now - (long)m_fileCheck < 60)
      return;
   m_fileCheck = now;
   const int fh = FileOpen(m_file, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE, ',');
   if(fh == INVALID_HANDLE)
      return;
   const long stamp = (long)FileGetInteger(fh, FILE_MODIFY_DATE);
   FileClose(fh);
   if(stamp != m_fileStamp)
      LoadFile();
  }

//+------------------------------------------------------------------+
//| 銘柄 i の、日足の日付 day の予想を探す（同じ銘柄の行は日付の古い順）       |
//+------------------------------------------------------------------+
bool CProbSleeve::Lookup(const int i, const datetime day, double &z, double &p)
  {
   const datetime d0 = day - (day % 86400);
   int k = m_cur[i];
   while(k < m_pn && (m_ps[k] != i || m_pd[k] < d0))
      k++;
   m_cur[i] = k;
   if(k < m_pn && m_pd[k] == d0)
     {
      z = m_pz[k];
      p = m_pp[k];
      return(true);
     }
   return(false);
  }

//+------------------------------------------------------------------+
double CProbSleeve::NotionalPerLot(const string sym)
  {
   const double tv    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   const double ts    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   const double price = SymbolInfoDouble(sym, SYMBOL_BID);
   if(ts <= 0.0 || tv <= 0.0 || price <= 0.0)
      return(0.0);
   return(price / ts * tv);
  }

//+------------------------------------------------------------------+
double CProbSleeve::NormalizeLots(const string sym, const double lots)
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
double CProbSleeve::SignedLots(const string sym)
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
double CProbSleeve::ToTick(const string sym, const double price)
  {
   const double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   const int    dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   if(ts <= 0.0)
      return(NormalizeDouble(price, dg));
   return(NormalizeDouble(MathRound(price / ts) * ts, dg));
  }

//+------------------------------------------------------------------+
void CProbSleeve::Warn(const int i, const string msg)
  {
   const datetime now = TimeCurrent();
   if((long)now - (long)m_warnAt[i] < 6 * 3600)
      return;
   m_warnAt[i] = now;
   PrintFormat("[AMS] 確率の層：%s %s", m_sym[i], msg);
  }

//+------------------------------------------------------------------+
void CProbSleeve::CloseAll(const string sym, const string why)
  {
   if(m_dryRun)
      return;
   m_tr.SetTypeFillingBySymbol(sym);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != m_magic)
         continue;
      if(m_tr.PositionClose(tk))
         m_cntClose++;
      else
        {
         m_tradeFail = true;
         PrintFormat("[AMS] 確率の層：%s の決済に失敗（%d %s。%s）", sym, m_tr.ResultRetcode(), m_tr.ResultRetcodeDescription(), why);
        }
     }
  }

//+------------------------------------------------------------------+
//| dir の向き（+1 買い / −1 売り）に lots 増やす                          |
//+------------------------------------------------------------------+
void CProbSleeve::Open(const string sym, const int dir, double lots, const double dailyVol)
  {
   if(m_dryRun)
      return;
   m_tr.SetTypeFillingBySymbol(sym);
   const double mx  = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   const string cmt = StringFormat("AMS|%s|SLEEVE|PB", sym);
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
         PrintFormat("[AMS] 確率の層：%s の注文に失敗（%d %s）", sym, m_tr.ResultRetcode(), m_tr.ResultRetcodeDescription());
         break;
        }
      m_cntOpen++;
      lots -= v;
     }
  }

//+------------------------------------------------------------------+
//| dir の向きの建玉を lots 減らす                                        |
//+------------------------------------------------------------------+
void CProbSleeve::Reduce(const string sym, const int dir, double lots)
  {
   if(m_dryRun)
      return;
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
            PrintFormat("[AMS] 確率の層：%s の決済に失敗（%d %s）", sym, m_tr.ResultRetcode(), m_tr.ResultRetcodeDescription());
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
            PrintFormat("[AMS] 確率の層：%s の一部の決済に失敗（%d %s）", sym, m_tr.ResultRetcode(), m_tr.ResultRetcodeDescription());
            break;
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| 逆指値を、今の値段から「1日の値動き × k」だけ離して置き直す              |
//+------------------------------------------------------------------+
void CProbSleeve::ApplyStops(const string sym, const double dailyVol)
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
         PrintFormat("[AMS] 確率の層：%s #%I64u の逆指値を置き直せません（%d %s、指定 %s）。前の逆指値のまま持ち、次の日足でまた置き直します", sym, tk,
                     m_tr.ResultRetcode(), m_tr.ResultRetcodeDescription(), DoubleToString(sl, dg));
        }
     }
  }

//+------------------------------------------------------------------+
//| 新しい日足が始まった銘柄を処理する                                     |
//+------------------------------------------------------------------+
bool CProbSleeve::Process(const int i, const datetime t0)
  {
   const string sym = m_sym[i];
   MqlRates raw[], rt[];
   ArraySetAsSeries(raw, false);
   const int gotRaw = CopyRates(sym, PERIOD_D1, 1, m_volDays + 8, raw);      // 確定した日足だけ
   //--- 土日の日付が付いた足（業者のデータにまれにある、取引時間外の短い足）は、予想を作る側と同じように除く
   //    （売買の判断ではなく、日足と予想の行を正しく結びつけるためのデータの整理）
   ArrayResize(rt, MathMax(gotRaw, 0));
   int got = 0;
   for(int k = 0; k < gotRaw; k++)
     {
      MqlDateTime dt;
      TimeToStruct(raw[k].time, dt);
      if(dt.day_of_week == 0 || dt.day_of_week == 6)
         continue;
      rt[got++] = raw[k];
     }
   if(got < m_volDays + 1)
     {
      Warn(i, StringFormat("日足が足りないため、まだ判定できません（%d 本）", got));
      return(false);
     }
   //--- 1日の値動きの大きさ（直近 m_volDays 日の、対数の値動きの標準偏差。研究の計算と同じ形）
   double s1 = 0.0, s2 = 0.0;
   for(int k = got - m_volDays; k < got; k++)
     {
      const double r = MathLog(rt[k].close / rt[k - 1].close);
      s1 += r;
      s2 += r * r;
     }
   const double var      = (s2 - s1 * s1 / m_volDays) / (m_volDays - 1);
   const double dailyVol = (var > 0.0) ? MathSqrt(var) : 0.0;
   const double annVol   = MathMax(dailyVol * MathSqrt(252.0), 0.025);
   //--- 予想（確定した最後の日足の日付の行）
   ReloadIfChanged();
   double z = 0.0, p = 0.0;
   const bool found = Lookup(i, rt[got - 1].time, z, p);
   if(!found && !MQLInfoInteger(MQL_TESTER) && (long)TimeCurrent() - (long)m_seenAt[i] < m_delaySec + m_waitSec)
     {
      m_retryAt[i] = TimeCurrent() + 30;                                    // 実運用：予想がファイルに届くのを待つ
      return(false);
     }
   m_cntDays++;
   if(!found)
     {
      m_cntMiss++;
      z = 0.0;
      Warn(i, StringFormat("日足 %s の予想がファイルにないため、持ちません", TimeToString(rt[got - 1].time, TIME_DATE)));
     }
   if(m_longOnly && z < 0.0)
      z = 0.0;
   const int  dir     = (z > 1e-9) ? 1 : ((z < -1e-9) ? -1 : 0);
   const int  prevDir = (m_z[i] > 1e-9) ? 1 : ((m_z[i] < -1e-9) ? -1 : 0);
   const bool changed = (dir != prevDir);
   //--- 目標の建玉
   const double equity = SizingEquity();
   const double npl    = NotionalPerLot(sym);
   if(npl <= 0.0)
     {
      Warn(i, "1 lot の額が計算できないため、まだ売買できません");
      m_cntDays--;
      if(!found)
         m_cntMiss--;
      return(false);
     }
   m_z[i] = z;
   if(dir > 0)
      m_cntLong++;
   else if(dir < 0)
      m_cntShort++;
   double frac = m_unit / 100.0 * MathAbs(z) / annVol;
   if(m_maxLev > 0.0 && frac > m_maxLev)
      frac = m_maxLev;
   const double tl = (dir != 0) ? NormalizeLots(sym, equity * frac / npl) : 0.0;
   m_tradeFail = false;
   double cur = SignedLots(sym);
   if(dir == 0 || tl <= 0.0)
     {
      if(MathAbs(cur) > 1e-9)
         CloseAll(sym, dir == 0 ? "合図がなくなった" : "目標が最小の取引単位に届かない");
     }
   else
     {
      if(cur * dir < -1e-9)                                   // 逆の向きを持っている → すべて決済してから建て直す
        {
         CloseAll(sym, "向きが変わった");
         cur = m_dryRun ? 0.0 : SignedLots(sym);
        }
      const double have = MathAbs(cur);
      if(!m_tradeFail && (changed || have <= 0.0 || MathAbs(have - tl) > m_band * MathMax(have, tl)))
        {
         if(tl > have)
            Open(sym, dir, tl - have, dailyVol);
         else if(have > tl)
            Reduce(sym, dir, have - tl);
        }
      ApplyStops(sym, dailyVol);
     }
   if(m_dryRun || !MQLInfoInteger(MQL_TESTER))
      PrintFormat("[AMS] 確率の層：%s 日足 %s の予想 %s → %s、目標 %.2f lot（値動きの見積もり 年 %.1f%%、今の建玉 %+.2f lot、値段 %s）", sym,
                  TimeToString(rt[got - 1].time, TIME_DATE), found ? StringFormat("確率 %.1f%%・z %+.2f", p * 100.0, z) : "なし",
                  dir > 0 ? "買い" : (dir < 0 ? "売り" : "持たない"), tl, annVol * 100.0, cur,
                  DoubleToString(SymbolInfoDouble(sym, SYMBOL_BID), (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)));
   if(m_tradeFail)
     {
      m_tradeFail = false;
      m_cntRetry++;
      m_retryCount[i]++;
      if(m_retryCount[i] <= 120)
        {
         m_retryAt[i] = TimeCurrent() + 30;
         m_cntDays--;
         return(false);
        }
      PrintFormat("[AMS] 確率の層：%s 売買のやり直しが上限（120回）に達したため、この日足ではあきらめます", sym);
     }
   m_retryCount[i] = 0;
   return(true);
  }

//+------------------------------------------------------------------+
void CProbSleeve::OnTick(void)
  {
   const datetime now = TimeCurrent();
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
         m_lastBar[i] = t0;
     }
  }

//+------------------------------------------------------------------+
void CProbSleeve::Summary(void)
  {
   if(m_n <= 0)
      return;
   PrintFormat("[AMS] 確率の層：判定した日足 %d（買い %d・売り %d・予想がなかった日足 %d）、新しく建てた回数 %d、決済した回数 %d、注文の失敗でやり直した回数 %d、逆指値を置き直せなかった回数 %d",
               m_cntDays, m_cntLong, m_cntShort, m_cntMiss, m_cntOpen, m_cntClose, m_cntRetry, m_cntStopFail);
  }
//+------------------------------------------------------------------+

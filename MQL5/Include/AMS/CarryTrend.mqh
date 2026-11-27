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

//--- 各通貨の短期金利（3か月の銀行間金利、月次の平均、年率 %）。FRED（OECD の統計）の実際の値（tools/research/fred_data.py）。
//    テスターでは、スワップの値が今のもので固定されるため、過去の判断に未来の金利差を使ってしまう。それを避けるため、
//    テスターでの判断にはこの表を使う（その月の判断には、前の月までの値だけを使う）。
//    実運用では、口座の実際のスワップ（受け取れる年率）を使い、スワップの値が読めないときだけ、この表の最後の値を使う。
//    EUR・GBP は 2026年1月で統計の更新が止まっているため、最後の値を引き延ばしている。
string CT_CCY[8] = {"JPY", "USD", "EUR", "GBP", "AUD", "NZD", "CAD", "CHF"};
#define CT_MONTHS 143   // 2014年12月〜2026年10月（月次）
double CT_RATE_M[8][CT_MONTHS] =
  {
     {0.18, 0.17, 0.17, 0.17, 0.17, 0.17, 0.17, 0.17, 0.17, 0.17, 0.17, 0.17, 0.17, 0.17, 0.10, 0.10, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.07, 0.06, 0.06, 0.06, 0.06, 0.06, 0.07, 0.07, 0.10, 0.10, 0.08, 0.08, 0.09, 0.09, 0.05, 0.05, 0.05, 0.05, 0.03, 0.03, 0.05, 0.05, 0.05, 0.05, 0.05, 0.01, 0.01, 0.01, 0.02, 0.02, 0.02, 0.02, 0.01, -0.04, -0.04, -0.04, -0.07, -0.07, -0.06, -0.06, -0.06, -0.06, -0.06, -0.06, -0.07, -0.07, -0.07, -0.07, -0.07, -0.07, -0.07, -0.07, -0.07, -0.05, -0.05, -0.05, -0.05, -0.05, -0.05, 0.01, -0.03, -0.02, -0.02, -0.02, -0.02, -0.01, -0.01, 0.00, -0.01, -0.00, -0.02, -0.00, -0.00, -0.00, 0.02, -0.01, 0.02, 0.05, 0.03, 0.03, 0.11, 0.11, 0.13, 0.15, 0.17, 0.26, 0.26, 0.26, 0.36, 0.39, 0.77, 0.79, 0.82, 0.78, 0.78, 0.77, 0.77, 0.77, 0.82, 0.81, 0.81, 1.07, 1.12, 1.23, 1.27, 1.24, 1.27, 1.41, 1.46, 1.56, 1.68, 1.68},
     {0.15, 0.16, 0.15, 0.14, 0.13, 0.15, 0.18, 0.19, 0.26, 0.27, 0.25, 0.30, 0.54, 0.57, 0.54, 0.55, 0.55, 0.57, 0.55, 0.62, 0.73, 0.75, 0.72, 0.71, 0.87, 0.90, 0.87, 0.98, 1.03, 1.05, 1.16, 1.22, 1.25, 1.25, 1.26, 1.32, 1.54, 1.63, 1.78, 2.08, 2.20, 2.16, 2.19, 2.17, 2.19, 2.24, 2.37, 2.56, 2.69, 2.59, 2.49, 2.48, 2.47, 2.44, 2.30, 2.22, 2.06, 2.03, 1.88, 1.77, 1.76, 1.65, 1.59, 1.35, 1.35, 0.17, 0.20, 0.18, 0.15, 0.13, 0.12, 0.16, 0.17, 0.14, 0.11, 0.10, 0.11, 0.10, 0.09, 0.10, 0.10, 0.10, 0.11, 0.14, 0.17, 0.22, 0.38, 0.73, 0.91, 1.33, 1.87, 2.50, 2.76, 3.21, 3.85, 4.46, 4.51, 4.61, 4.74, 4.91, 5.03, 5.15, 5.22, 5.35, 5.44, 5.49, 5.46, 5.41, 5.32, 5.26, 5.22, 5.29, 5.33, 5.33, 5.28, 5.31, 5.12, 4.86, 4.62, 4.53, 4.46, 4.33, 4.34, 4.29, 4.32, 4.29, 4.31, 4.28, 4.22, 4.10, 3.98, 3.86, 3.74, 3.63, 3.66, 3.69, 3.77, 3.72, 3.77, 3.82, 3.82, 3.94, 4.12},
     {0.08, 0.06, 0.05, 0.03, 0.00, -0.01, -0.01, -0.02, -0.03, -0.04, -0.05, -0.09, -0.13, -0.15, -0.18, -0.23, -0.25, -0.26, -0.27, -0.29, -0.30, -0.30, -0.31, -0.31, -0.32, -0.33, -0.33, -0.33, -0.33, -0.33, -0.33, -0.33, -0.33, -0.33, -0.33, -0.33, -0.33, -0.33, -0.33, -0.33, -0.33, -0.33, -0.32, -0.32, -0.32, -0.32, -0.32, -0.32, -0.31, -0.31, -0.31, -0.31, -0.31, -0.31, -0.33, -0.36, -0.41, -0.42, -0.41, -0.40, -0.39, -0.39, -0.41, -0.42, -0.25, -0.27, -0.38, -0.44, -0.48, -0.49, -0.51, -0.52, -0.54, -0.55, -0.54, -0.54, -0.54, -0.54, -0.54, -0.54, -0.55, -0.55, -0.55, -0.57, -0.58, -0.56, -0.53, -0.50, -0.45, -0.39, -0.24, 0.04, 0.39, 1.01, 1.43, 1.83, 2.06, 2.34, 2.64, 2.91, 3.17, 3.37, 3.54, 3.67, 3.78, 3.88, 3.97, 3.97, 3.93, 3.93, 3.92, 3.92, 3.89, 3.81, 3.72, 3.68, 3.55, 3.43, 3.17, 3.01, 2.82, 2.70, 2.52, 2.44, 2.25, 2.09, 1.98, 1.99, 2.02, 2.03, 2.03, 2.04, 2.05, 2.03, 2.03, 2.03, 2.03, 2.03, 2.03, 2.03, 2.03, 2.03, 2.03},
     {0.56, 0.56, 0.56, 0.56, 0.57, 0.57, 0.57, 0.58, 0.59, 0.59, 0.58, 0.57, 0.58, 0.59, 0.59, 0.59, 0.59, 0.59, 0.57, 0.51, 0.41, 0.38, 0.40, 0.40, 0.37, 0.36, 0.36, 0.35, 0.34, 0.31, 0.29, 0.29, 0.28, 0.31, 0.38, 0.52, 0.52, 0.52, 0.55, 0.63, 0.76, 0.64, 0.64, 0.75, 0.81, 0.80, 0.81, 0.87, 0.90, 0.92, 0.88, 0.84, 0.82, 0.80, 0.78, 0.77, 0.76, 0.77, 0.78, 0.79, 0.79, 0.74, 0.75, 0.53, 0.65, 0.33, 0.19, 0.10, 0.07, 0.06, 0.05, 0.04, 0.03, 0.03, 0.05, 0.08, 0.09, 0.08, 0.08, 0.08, 0.07, 0.07, 0.16, 0.13, 0.16, 0.53, 0.81, 0.99, 1.13, 1.31, 1.57, 1.84, 2.23, 2.91, 3.39, 3.52, 3.78, 4.01, 4.21, 4.33, 4.52, 4.73, 5.09, 5.49, 5.53, 5.52, 5.40, 5.36, 5.22, 5.20, 5.21, 5.20, 5.18, 5.16, 5.16, 5.09, 4.91, 4.84, 4.75, 4.68, 4.64, 4.55, 4.44, 4.39, 4.26, 4.19, 4.15, 4.05, 3.98, 3.97, 3.93, 3.84, 3.75, 3.71, 3.71, 3.71, 3.71, 3.71, 3.71, 3.71, 3.71, 3.71, 3.71},
     {2.75, 2.70, 2.36, 2.30, 2.25, 2.15, 2.15, 2.14, 2.14, 2.17, 2.15, 2.22, 2.34, 2.30, 2.28, 2.31, 2.26, 2.00, 1.99, 1.93, 1.76, 1.73, 1.74, 1.76, 1.78, 1.78, 1.78, 1.79, 1.77, 1.73, 1.72, 1.70, 1.70, 1.72, 1.70, 1.72, 1.77, 1.79, 1.77, 1.93, 2.06, 1.96, 2.07, 2.02, 1.96, 1.93, 1.93, 1.94, 2.02, 2.07, 1.96, 1.83, 1.68, 1.54, 1.29, 1.11, 0.98, 0.98, 0.88, 0.91, 0.90, 0.89, 0.89, 0.53, 0.17, 0.10, 0.10, 0.10, 0.10, 0.09, 0.07, 0.02, 0.02, 0.01, 0.01, 0.03, 0.04, 0.04, 0.03, 0.02, 0.01, 0.01, 0.04, 0.04, 0.06, 0.07, 0.07, 0.17, 0.41, 1.00, 1.60, 2.07, 2.31, 2.76, 2.95, 3.06, 3.17, 3.32, 3.46, 3.64, 3.66, 3.90, 4.25, 4.30, 4.15, 4.13, 4.21, 4.38, 4.35, 4.35, 4.34, 4.35, 4.37, 4.36, 4.39, 4.46, 4.38, 4.42, 4.41, 4.42, 4.44, 4.33, 4.17, 4.12, 4.02, 3.78, 3.69, 3.68, 3.61, 3.58, 3.56, 3.65, 3.71, 3.77, 3.96, 4.19, 4.34, 4.43, 4.46, 4.48, 4.51, 4.67, 4.80},
     {3.67, 3.67, 3.63, 3.63, 3.63, 3.53, 3.33, 3.13, 2.95, 2.85, 2.86, 2.89, 2.79, 2.73, 2.62, 2.43, 2.34, 2.38, 2.37, 2.37, 2.24, 2.23, 2.15, 2.07, 2.03, 1.98, 2.02, 1.98, 1.97, 1.98, 1.95, 1.96, 1.95, 1.95, 1.94, 1.93, 1.88, 1.88, 1.91, 1.93, 2.01, 2.01, 2.01, 1.94, 1.90, 1.90, 1.89, 1.98, 1.98, 1.91, 1.90, 1.88, 1.81, 1.72, 1.60, 1.55, 1.25, 1.15, 1.05, 1.18, 1.22, 1.27, 1.18, 0.71, 0.39, 0.26, 0.28, 0.30, 0.29, 0.30, 0.27, 0.27, 0.26, 0.28, 0.28, 0.33, 0.34, 0.35, 0.33, 0.40, 0.54, 0.57, 0.70, 0.83, 0.91, 1.03, 1.21, 1.49, 1.81, 2.22, 2.68, 3.03, 3.31, 3.64, 4.00, 4.24, 4.53, 4.81, 5.01, 5.15, 5.49, 5.67, 5.68, 5.67, 5.64, 5.68, 5.68, 5.63, 5.63, 5.64, 5.71, 5.64, 5.63, 5.62, 5.62, 5.55, 5.30, 5.05, 4.65, 4.42, 4.27, 4.05, 3.81, 3.67, 3.49, 3.34, 3.30, 3.25, 3.10, 2.93, 2.58, 2.47, 2.49, 2.50, 2.49, 2.51, 2.56, 2.63, 2.68, 2.85, 2.98, 3.13, 3.25},
     {0.90, 0.77, 0.53, 0.55, 0.62, 0.66, 0.61, 0.47, 0.39, 0.40, 0.40, 0.45, 0.48, 0.43, 0.46, 0.46, 0.51, 0.51, 0.51, 0.50, 0.51, 0.51, 0.49, 0.48, 0.48, 0.45, 0.47, 0.50, 0.54, 0.51, 0.56, 0.73, 0.72, 0.98, 0.96, 0.88, 0.96, 1.16, 1.16, 1.09, 1.17, 1.25, 1.24, 1.38, 1.49, 1.52, 1.66, 1.71, 1.66, 1.63, 1.67, 1.66, 1.68, 1.68, 1.67, 1.65, 1.64, 1.63, 1.65, 1.66, 1.66, 1.65, 1.63, 0.67, 0.25, 0.23, 0.19, 0.18, 0.16, 0.14, 0.10, 0.11, 0.11, 0.06, 0.08, 0.11, 0.09, 0.10, 0.13, 0.17, 0.18, 0.13, 0.12, 0.12, 0.08, 0.30, 0.33, 0.57, 1.05, 1.37, 1.83, 2.44, 2.91, 3.42, 3.76, 3.99, 4.17, 4.33, 4.45, 4.39, 4.37, 4.48, 4.83, 4.93, 5.05, 5.04, 5.08, 5.00, 4.95, 4.95, 4.93, 4.91, 4.92, 4.87, 4.65, 4.51, 4.23, 4.04, 3.71, 3.48, 3.19, 3.06, 2.84, 2.66, 2.62, 2.62, 2.66, 2.66, 2.65, 2.49, 2.33, 2.19, 2.16, 2.19, 2.18, 2.23, 2.27, 2.29, 2.27, 2.26, 2.28, 2.33, 2.45},
     {0.04, -0.42, -0.68, -0.79, -0.69, -0.82, -0.77, -0.74, -0.78, -0.76, -0.84, -0.68, -0.74, -0.75, -0.89, -0.77, -0.75, -0.77, -0.72, -0.77, -0.75, -0.75, -0.75, -0.76, -0.80, -0.93, -0.80, -0.81, -0.79, -0.90, -0.78, -0.81, -0.81, -0.85, -0.93, -0.91, -0.86, -0.87, -0.87, -0.80, -0.80, -0.79, -0.79, -0.78, -0.78, -0.78, -0.83, -0.81, -0.78, -0.81, -0.77, -0.76, -0.75, -0.78, -0.78, -0.84, -0.81, -0.79, -0.76, -0.71, -0.74, -0.75, -0.72, -0.68, -0.62, -0.66, -0.67, -0.69, -0.71, -0.71, -0.70, -0.73, -0.74, -0.73, -0.73, -0.73, -0.73, -0.74, -0.74, -0.74, -0.74, -0.82, -0.73, -0.69, -0.72, -0.71, -0.68, -0.68, -0.67, -0.69, -0.51, -0.11, -0.02, 0.15, 0.53, 0.54, 0.74, 0.99, 1.00, 1.36, 1.45, 1.45, 1.59, 1.72, 1.77, 1.77, 1.77, 1.73, 1.65, 1.69, 1.70, 1.50, 1.50, 1.50, 1.43, 1.19, 1.07, 1.02, 0.89, 0.81, 0.60, 0.41, 0.37, 0.31, 0.16, 0.09, 0.04, -0.04, -0.06, -0.06, -0.06, -0.05, -0.05, -0.04, -0.04, -0.04, -0.04, -0.04, -0.05, -0.04, -0.04, -0.04, -0.04}
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
   m_stateFile    = StringFormat("AMS_ct_state3_%I64u.txt", magic);
   m_initAt       = TimeCurrent();
   m_n            = ArraySize(syms);
   ArrayResize(m_sym, m_n);
   for(int i = 0; i < m_n; i++)
     {
      m_sym[i] = syms[i];
      if(!SymbolSelect(m_sym[i], true))
         PrintFormat("[AMS] 金利差＋トレンド：%s を気配値表示に追加できません", m_sym[i]);
      PrintFormat("[AMS] 金利差＋トレンド：%s 金利の表の見積もり 買い %.2f%% / 売り %.2f%%、口座のスワップ（方式=%d）買い %.2f / 売り %.2f → 年率 買い %.2f%% / 売り %.2f%%",
                  m_sym[i], TesterCarryPct(m_sym[i], true), TesterCarryPct(m_sym[i], false), (int)SymbolInfoInteger(m_sym[i], SYMBOL_SWAP_MODE),
                  SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_LONG), SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_SHORT),
                  SwapAnnualPct(m_sym[i], true), SwapAnnualPct(m_sym[i], false));
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
   const double sw   = SymbolInfoDouble(sym, isLong ? SYMBOL_SWAP_LONG : SYMBOL_SWAP_SHORT);
   const int    mode = (int)SymbolInfoInteger(sym, SYMBOL_SWAP_MODE);
   if(mode == SYMBOL_SWAP_MODE_POINTS)
     {
      //--- ポイント単位：1日あたり「値 × 1ポイント」だけ値段が有利・不利になるのと同じ。年率は 値 × ポイント × 365 ÷ 価格。
      //    （2026年11月20日のデモ口座の値で検算：EURUSD 売り +3.34 → 年 +1.1%、USDCHF 買い +7.16 → 年 +3.1%。
      //      実際の金利差から上乗せを引いた値とよく合う。最初の版は、ティックの価値を経由して計算し、2〜3倍にずれていた）
      const double pt    = SymbolInfoDouble(sym, SYMBOL_POINT);
      const double price = SymbolInfoDouble(sym, SYMBOL_BID);
      if(price <= 0.0)
         return(0.0);
      return(sw * pt * 365.0 / price * 100.0);
     }
   if(mode == SYMBOL_SWAP_MODE_INTEREST_CURRENT || mode == SYMBOL_SWAP_MODE_INTEREST_OPEN)
      return(sw);
   const double contract = SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE);
   if(contract <= 0.0)
      return(0.0);
   if(mode == SYMBOL_SWAP_MODE_CURRENCY_SYMBOL || mode == SYMBOL_SWAP_MODE_CURRENCY_MARGIN)
      return(sw / contract * 365.0 * 100.0);
   if(mode == SYMBOL_SWAP_MODE_CURRENCY_DEPOSIT)
     {
      const double notional = NotionalPerLot(sym);
      if(notional <= 0.0)
         return(0.0);
      return(sw * 365.0 / notional * 100.0);
     }
   return(0.0);
  }

//+------------------------------------------------------------------+
//| 金利の表から：受け取れる金利差の見積もり（年率 %、業者の上乗せ 年1% を引く）          |
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
   //--- 表の 0 番目は 2014年12月。その月の判断には、前の月の値を使う（2015年1月 → 0 番目）
   const int mi = (int)MathMax(0, MathMin(CT_MONTHS - 1, (dt.year - 2015) * 12 + (dt.mon - 1)));
   const double diff = CT_RATE_M[ib][mi] - CT_RATE_M[iq][mi];
   return((isLong ? diff : -diff) - 1.0);
  }

//+------------------------------------------------------------------+
//| 判断に使う金利差：実運用は口座の実際のスワップ、テスターは月ごとの金利の表 |
//+------------------------------------------------------------------+
double CCarryTrend::CarryPct(const string sym, const bool isLong)
  {
   const double t = TesterCarryPct(sym, isLong);
   if(MQLInfoInteger(MQL_TESTER))
      return(t);
   //--- 実運用：口座の実際のスワップ（上乗せ込みで、実際に受け取れる・払う年率）を使う。
   //    買い・売りの両方が 0 のときは、まだ値を受け取っていない（2026年11月20日、起動直後に円のペアがすべて 0 だった）
   //    とみなして、金利の表の見積もりを使う。
   const double swL = SymbolInfoDouble(sym, SYMBOL_SWAP_LONG);
   const double swS = SymbolInfoDouble(sym, SYMBOL_SWAP_SHORT);
   if(swL == 0.0 && swS == 0.0)
      return(t);
   return(SwapAnnualPct(sym, isLong));
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
         held += StringFormat(" %s%s%.2f（金利差 %.1f%%）", m_sym[i], dir[i] > 0 ? "+" : "-", tl[i], CarryPct(m_sym[i], dir[i] > 0));
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

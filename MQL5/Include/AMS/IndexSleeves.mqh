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
//| 値段で売買する。建玉は、ルール1つ分の値動きが「口座の年 x %」になる        |
//| 大きさにする。ルールごとに別々の建玉は持たず、銘柄ごとの合計に合わせる。   |
//|                                                                  |
//| 損失を小さくするための仕組み（98章。利益の出どころのルールは変えない）：    |
//|  1 値動きの見積もり：翌日の分散 = 0.37×当日 + 0.56×5日の平均            |
//|    + 0.20×22日の平均（分散は日足の始値・高値・安値・終値から計算。         |
//|    HAR 型。係数は 2018年までの先物のデータで決めて固定）。                |
//|    急に荒れ始めた直後に、建玉が大きくなりすぎるのを防ぐ。                  |
//|  2 VIX の状態：戻りの利益は、VIX が高いときほど大きい（流動性を提供する     |
//|    ことへの対価）。VIX が過去の分布の下 1/3 なら 0.5 倍、上 1/3 なら       |
//|    1.5 倍にする。VIX は共通フォルダのファイルから読み、判定する日足より     |
//|    前の日の終値だけを使う。ファイルがない・古いときは 1.0 倍。              |
//|  3 逆指値：毎日、売買の時点の値段から「その日の値動きの見積もり × k」       |
//|    だけ下に置き直す（1日の損失の上限を決める。EA が止まっていても効く）。    |
//|                                                                  |
//| 持ち越しのコスト（スワップ）を減らす仕組み（99章。使うかどうかは入力で選ぶ）：|
//|  スワップは、日々の取引の区切り（サーバーの日付が変わる時）に持っている      |
//|  建玉にかかる。そこで、その夜のスワップが、持ち直すときのスプレッドより      |
//|  高いときだけ、区切りの数分前にいったん手じまい、次の日足の判定のあとに      |
//|  持ち直す。何を買うかの判断（ルール）は変えない。                          |
//|                                                                  |
//| 強制ロスカットを数式で避ける仕組み（99章）：                             |
//|  建玉の合計を、「すべての建玉が逆指値（その日の値動きの見積もり × k）に     |
//|  かかっても、証拠金維持率がロスカットの水準を下回らない」大きさに抑える：    |
//|    Σ 建玉の額 ×（k × 1日の値動きの見積もり + ロスカットの水準 × 証拠金率）    |
//|      ≤ 有効証拠金 × 余裕の係数                                        |
//| ルールがそろった数の重み（99章）：1つ・2つ・3つのときの建玉の単位を入力で   |
//|  決める（1,2,3 = ルールの数に比例。1,2,4 = 3つそろったときに厚くする）。    |
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
   double            m_slVolMul;       // 逆指値：その日の値動きの見積もりの何倍下に置くか（0 で置かない。毎日置き直す）
   int               m_volModel;       // 値動きの見積もり：0 = 直近60日、1 = HAR 型
   string            m_vixFile;        // VIX の日次の終値のファイル（共通フォルダ。空なら使わない）
   double            m_vixLow;         // VIX が過去の分布の下 1/3 のときの、戻りの建玉の倍率
   double            m_vixHigh;        // 上 1/3 のときの倍率
   datetime          m_vixDate[];      // VIX の日付（古い順）
   double            m_vixVal[];       // VIX の終値
   datetime          m_vixTried;       // VIX のファイルを最後に読み直した時刻
   datetime          m_vixWarnAt;
   int               m_flatMin;        // 日々の区切りの何分前に手じまうか（0 で使わない）
   double            m_flatEdgeBp;     // スワップがスプレッドをこれだけ（値段の1万分の1単位）上回るときだけ手じまう
   datetime          m_flatDone[];     // 区切りの前の判断を済ませた日足の時刻
   long              m_flatCount;      // 区切りの前に手じまった回数
   long              m_flatSkip;       // スワップのほうが安いので持ち越した回数
   double            m_ruleW[4];       // ルールが 0・1・2・3 つ出ているときの建玉の単位
   double            m_soGuard;        // 強制ロスカットを避ける上限の、余裕の係数（0 で使わない）
   double            m_dvol[];         // 銘柄ごとの、最後に計算した1日の値動きの見積もり
   double            m_tgtLots[];      // 銘柄ごとの、最後に決めた目標のロット（最小の取引単位に届かないときは 0）
   long              m_soCut;          // 上の上限で建玉を縮めた回数
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
   void              ApplyStops(const string sym, const double dailyVol);
   datetime          SessionEnd(const string sym, const datetime t0);
   double            SwapTonightPct(const string sym, const datetime t0);
   void              FlatBeforeRollover(const int i, const datetime now);
   int               LoadVix(void);
   double            VixMult(const datetime barDate, string &note);
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
                          const double slVolMul, const int delayMin, const double maxSpreadPct,
                          const int volModel, const string vixFile, const double vixLow, const double vixHigh,
                          const int flatMin, const double flatEdgeBp, const string ruleWeights, const double soGuard);
   void              OnTick(void);
   void              Summary(void);
  };

//+------------------------------------------------------------------+
bool CIndexSleeves::Init(CTrade *trade, const ulong magic, const string &revSyms[], const string &trendSyms[],
                         const bool useR2, const bool useD7, const bool useIBS, const double revUnit, const double trendUnit,
                         const int trendDays, const double maxLev, const double maxMarginPct, const double band,
                         const double slVolMul, const int delayMin, const double maxSpreadPct,
                         const int volModel, const string vixFile, const double vixLow, const double vixHigh,
                         const int flatMin, const double flatEdgeBp, const string ruleWeights, const double soGuard)
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
   m_volModel     = volModel;
   m_vixFile      = vixFile;
   m_vixLow       = vixLow;
   m_vixHigh      = vixHigh;
   m_vixTried     = 0;
   m_vixWarnAt    = 0;
   m_flatMin      = (int)MathMax(0, flatMin);
   m_flatEdgeBp   = flatEdgeBp;
   m_flatCount    = 0;
   m_flatSkip     = 0;
   m_soGuard      = MathMax(0.0, soGuard);
   m_soCut        = 0;
   //--- ルールがそろった数の重み（「1,2,4」の形。読めないときは 1,2,3 = ルールの数に比例）
   m_ruleW[0] = 0.0;
   m_ruleW[1] = 1.0;
   m_ruleW[2] = 2.0;
   m_ruleW[3] = 3.0;
   string wparts[];
   if(StringSplit(ruleWeights, ',', wparts) == 3)
     {
      const double w1 = StringToDouble(wparts[0]), w2 = StringToDouble(wparts[1]), w3 = StringToDouble(wparts[2]);
      if(w1 >= 0.0 && w2 >= 0.0 && w3 > 0.0)
        {
         m_ruleW[1] = w1;
         m_ruleW[2] = w2;
         m_ruleW[3] = w3;
        }
     }
   ArrayResize(m_vixDate, 0);
   ArrayResize(m_vixVal, 0);
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
   ArrayResize(m_flatDone, m_n);
   ArrayResize(m_dvol, m_n);
   ArrayResize(m_tgtLots, m_n);
   for(int i = 0; i < m_n; i++)
     {
      m_flatDone[i] = 0;
      m_dvol[i] = 0.0;
      m_tgtLots[i] = 0.0;
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
      double mg = 0.0;
      if(!OrderCalcMargin(ORDER_TYPE_BUY, m_sym[i], 1.0, SymbolInfoDouble(m_sym[i], SYMBOL_ASK), mg))
         mg = 0.0;
      PrintFormat("[AMS] 指数の層：%s（%s%s）最小 %.2f lot・刻み %.2f、1 lot の額 %.0f・必要証拠金 %.0f（口座のレバレッジ 1:%d）、スワップ（方式=%d）買い %.4f / 売り %.4f",
                  m_sym[i], m_rev[i] ? "戻り" : "", m_trd[i] ? (m_rev[i] ? "・順張り" : "順張り") : "",
                  SymbolInfoDouble(m_sym[i], SYMBOL_VOLUME_MIN), SymbolInfoDouble(m_sym[i], SYMBOL_VOLUME_STEP), NotionalPerLot(m_sym[i]), mg,
                  (int)AccountInfoInteger(ACCOUNT_LEVERAGE),
                  (int)SymbolInfoInteger(m_sym[i], SYMBOL_SWAP_MODE), SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_LONG),
                  SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_SHORT));
      //--- スワップの曜日ごとの倍率と、取引の区切りの時刻（区切りの前の手じまいの判断に使う値）
      const datetime b0 = iTime(m_sym[i], PERIOD_D1, 0);
      PrintFormat("[AMS] 指数の層：%s スワップの倍率（日〜土）%.0f/%.0f/%.0f/%.0f/%.0f/%.0f/%.0f（3日分の曜日の設定 %d）、今日の取引の終わり %s、今夜のスワップ 値段の %.4f%%",
                  m_sym[i], SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_SUNDAY), SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_MONDAY),
                  SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_TUESDAY), SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_WEDNESDAY),
                  SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_THURSDAY), SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_FRIDAY),
                  SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_SATURDAY), (int)SymbolInfoInteger(m_sym[i], SYMBOL_SWAP_ROLLOVER3DAYS),
                  b0 > 0 ? TimeToString(SessionEnd(m_sym[i], b0), TIME_MINUTES) : "?", b0 > 0 ? SwapTonightPct(m_sym[i], b0) : 0.0);
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
   const int vixRows = (m_vixFile != "") ? LoadVix() : 0;
   PrintFormat("[AMS] 指数の層：値動きの見積もり %s、逆指値 %s、VIX の倍率 %s",
               m_volModel == 1 ? "HAR 型（当日・5日・22日の値幅）" : "直近60日",
               m_slVolMul > 0.0 ? StringFormat("その日の値動きの見積もり × %.1f（毎日置き直す）", m_slVolMul) : "なし",
               m_vixFile == "" ? "使わない" :
               (vixRows >= 500 ? StringFormat("%s（%d 日分、最後の日付 %s）。下 1/3 で %.2f 倍・上 1/3 で %.2f 倍", m_vixFile, vixRows,
                                              TimeToString(m_vixDate[vixRows - 1], TIME_DATE), m_vixLow, m_vixHigh)
                : StringFormat("%s が読めない・足りない（%d 日分）ため、1.0 倍のまま", m_vixFile, vixRows)));
   if(m_flatMin > 0)
      PrintFormat("[AMS] 指数の層：その夜のスワップがスプレッドより値段の %.2f/10000 以上高いときは、取引の区切りの %d 分前に手じまい、次の日足の判定のあとに持ち直します",
                  m_flatEdgeBp, m_flatMin);
   PrintFormat("[AMS] 指数の層：ルールがそろった数の重み 1つ %.2f・2つ %.2f・3つ %.2f、強制ロスカットを避ける上限 %s（ロスカットの水準 %.0f%%）",
               m_ruleW[1], m_ruleW[2], m_ruleW[3], m_soGuard > 0.0 ? StringFormat("あり（余裕の係数 %.2f）", m_soGuard) : "なし",
               (AccountInfoInteger(ACCOUNT_MARGIN_SO_MODE) == ACCOUNT_STOPOUT_MODE_PERCENT) ? AccountInfoDouble(ACCOUNT_MARGIN_SO_SO) : 100.0);
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
      double sl = 0.0;
      if(m_slVolMul > 0.0 && dailyVol > 0.0)
         sl = NormalizeDouble(SymbolInfoDouble(sym, SYMBOL_BID) * (1.0 - m_slVolMul * dailyVol), dg);
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
//| 逆指値を、今の値段から「その日の値動きの見積もり × k」だけ下に置き直す     |
//+------------------------------------------------------------------+
void CIndexSleeves::ApplyStops(const string sym, const double dailyVol)
  {
   if(m_slVolMul <= 0.0 || dailyVol <= 0.0)
      return;
   const double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   const double pt  = SymbolInfoDouble(sym, SYMBOL_POINT);
   const int    dg  = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   if(bid <= 0.0 || pt <= 0.0)
      return;
   const double minDist = (double)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL) * pt;
   double sl = bid * (1.0 - m_slVolMul * dailyVol);
   if(bid - sl < minDist)
      sl = bid - minDist;
   sl = NormalizeDouble(sl, dg);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != m_magic)
         continue;
      if(PositionGetInteger(POSITION_TYPE) != POSITION_TYPE_BUY)
         continue;
      if(MathAbs(PositionGetDouble(POSITION_SL) - sl) < 0.5 * pt)
         continue;
      if(!m_trade.PositionModify(tk, sl, PositionGetDouble(POSITION_TP)))
         PrintFormat("[AMS] 指数の層：%s #%I64u の逆指値を置き直せません（%d %s）", sym, tk, m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
     }
  }

//+------------------------------------------------------------------+
//| VIX の日次の終値を、共通フォルダのファイルから読む                       |
//| 行の形：日付,終値（日付は 2026.11.25／2026-11-25／11/25/2026 のどれか）   |
//+------------------------------------------------------------------+
int CIndexSleeves::LoadVix(void)
  {
   m_vixTried = TimeCurrent();
   const int fh = FileOpen(m_vixFile, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(fh == INVALID_HANDLE)
      return(ArraySize(m_vixDate));
   datetime dts[];
   double   vals[];
   int n = 0, cap = 0;
   while(!FileIsEnding(fh))
     {
      string line = FileReadString(fh);
      string f[];
      if(StringSplit(line, ',', f) < 2)
         continue;
      string ds = f[0];
      StringTrimLeft(ds);
      StringTrimRight(ds);
      StringReplace(ds, "-", ".");
      string q[];
      if(StringSplit(ds, '/', q) == 3)                 // 月/日/年
         ds = q[2] + "." + q[0] + "." + q[1];
      const datetime dt = StringToTime(ds);
      const double   v  = StringToDouble(f[ArraySize(f) - 1]);
      if(dt < D'1980.01.01' || v <= 0.0)
         continue;
      if(n > 0 && dt <= dts[n - 1])
         continue;
      if(n >= cap)
        {
         cap += 2048;
         ArrayResize(dts, cap);
         ArrayResize(vals, cap);
        }
      dts[n]  = dt;
      vals[n] = v;
      n++;
     }
   FileClose(fh);
   if(n > ArraySize(m_vixDate))
     {
      ArrayResize(m_vixDate, n);
      ArrayResize(m_vixVal, n);
      for(int k = 0; k < n; k++)
        {
         m_vixDate[k] = dts[k];
         m_vixVal[k]  = vals[k];
        }
     }
   return(ArraySize(m_vixDate));
  }

//+------------------------------------------------------------------+
//| VIX の状態による、戻りの建玉の倍率                                    |
//| barDate（判定する日足の日付）より前の、最後の VIX の終値が、              |
//| それまでの VIX の分布のどこにあるか（0〜1）で決める                      |
//+------------------------------------------------------------------+
double CIndexSleeves::VixMult(const datetime barDate, string &note)
  {
   if(m_vixFile == "")
      return(1.0);
   int n = ArraySize(m_vixDate);
   //--- ファイルが古ければ、読み直す（実運用では、起動のたびに新しいファイルが置かれる）
   if((n == 0 || m_vixDate[n - 1] < barDate - 86400) && (long)TimeCurrent() - (long)m_vixTried >= 3600)
      n = LoadVix();
   int lo = 0, hi = n - 1, j = -1;
   while(lo <= hi)
     {
      const int mid = (lo + hi) / 2;
      if(m_vixDate[mid] < barDate)
        {
         j = mid;
         lo = mid + 1;
        }
      else
         hi = mid - 1;
     }
   string why = "";
   if(j < 499)
      why = "VIX の記録が足りない";
   else if((long)barDate - (long)m_vixDate[j] > 7 * 86400)
      why = StringFormat("VIX の記録が古い（最後の日付 %s）", TimeToString(m_vixDate[j], TIME_DATE));
   if(why != "")
     {
      if((long)TimeCurrent() - (long)m_vixWarnAt >= 6 * 3600)
        {
         m_vixWarnAt = TimeCurrent();
         PrintFormat("[AMS] 指数の層：%sため、VIX の倍率は 1.0 のままにします", why);
        }
      return(1.0);
     }
   int le = 0;
   for(int k = 0; k <= j; k++)
      if(m_vixVal[k] <= m_vixVal[j])
         le++;
   const double rank = (double)le / (double)(j + 1);
   const double mult = (rank < 1.0 / 3.0) ? m_vixLow : ((rank >= 2.0 / 3.0) ? m_vixHigh : 1.0);
   note = StringFormat("VIX %.2f（%s、過去の分布での位置 %.2f）→ %.2f 倍", m_vixVal[j], TimeToString(m_vixDate[j], TIME_DATE), rank, mult);
   return(mult);
  }

//+------------------------------------------------------------------+
//| 今日の取引の終わりの時刻（銘柄の取引時間の表から。なければ日付の変わり目）   |
//+------------------------------------------------------------------+
datetime CIndexSleeves::SessionEnd(const string sym, const datetime t0)
  {
   MqlDateTime dt;
   TimeToStruct(t0, dt);
   long best = -1;
   for(uint idx = 0; idx < 10; idx++)
     {
      datetime from = 0, to = 0;
      if(!SymbolInfoSessionTrade(sym, (ENUM_DAY_OF_WEEK)dt.day_of_week, idx, from, to))
         break;
      if((long)to > best)
         best = (long)to;
     }
   if(best <= 0 || best > 86400)
      best = 86400;
   return((datetime)((long)t0 + best));
  }

//+------------------------------------------------------------------+
//| 今夜、買いの建玉を持ち越すとかかるスワップ（値段に対する %。受け取りなら 0。  |
//| 計算できない方式なら −1）                                            |
//+------------------------------------------------------------------+
double CIndexSleeves::SwapTonightPct(const string sym, const datetime t0)
  {
   const double sl = SymbolInfoDouble(sym, SYMBOL_SWAP_LONG);
   if(sl >= 0.0)
      return(0.0);
   MqlDateTime dt;
   TimeToStruct(t0, dt);
   double mult = 0.0, sum = 0.0;
   const double w[7] = {SymbolInfoDouble(sym, SYMBOL_SWAP_SUNDAY), SymbolInfoDouble(sym, SYMBOL_SWAP_MONDAY), SymbolInfoDouble(sym, SYMBOL_SWAP_TUESDAY),
                        SymbolInfoDouble(sym, SYMBOL_SWAP_WEDNESDAY), SymbolInfoDouble(sym, SYMBOL_SWAP_THURSDAY),
                        SymbolInfoDouble(sym, SYMBOL_SWAP_FRIDAY), SymbolInfoDouble(sym, SYMBOL_SWAP_SATURDAY)};
   for(int k = 0; k < 7; k++)
      sum += w[k];
   if(sum > 0.0)
      mult = w[dt.day_of_week];
   else
      mult = (dt.day_of_week == (int)SymbolInfoInteger(sym, SYMBOL_SWAP_ROLLOVER3DAYS)) ? 3.0 : 1.0;
   const int    mode = (int)SymbolInfoInteger(sym, SYMBOL_SWAP_MODE);
   const double bid  = SymbolInfoDouble(sym, SYMBOL_BID);
   if(mode == SYMBOL_SWAP_MODE_INTEREST_CURRENT || mode == SYMBOL_SWAP_MODE_INTEREST_OPEN)
      return(-sl / 360.0 * mult);
   if(mode == SYMBOL_SWAP_MODE_POINTS && bid > 0.0)
      return(-sl * SymbolInfoDouble(sym, SYMBOL_POINT) / bid * 100.0 * mult);
   return(-1.0);
  }

//+------------------------------------------------------------------+
//| 取引の区切りの前：今夜のスワップが、持ち直すときのスプレッドより高ければ、   |
//| いったん手じまう（次の日足の判定で、ルールが続いていれば持ち直す）          |
//+------------------------------------------------------------------+
void CIndexSleeves::FlatBeforeRollover(const int i, const datetime now)
  {
   const string   sym = m_sym[i];
   const datetime t0  = iTime(sym, PERIOD_D1, 0);
   if(t0 <= 0 || m_flatDone[i] == t0)
      return;
   const datetime endT = SessionEnd(sym, t0);
   if((long)now < (long)endT - (long)m_flatMin * 60 || now >= endT)
      return;
   int dir = 0;
   if(CurrentLots(sym, dir) <= 0.0 || dir <= 0)
     {
      m_flatDone[i] = t0;
      return;
     }
   MqlTick tk;
   if(!SymbolInfoTick(sym, tk) || tk.bid <= 0.0 || tk.ask <= 0.0 || (long)now - (long)tk.time > 120)
      return;                                           // 値段が動いていない（市場が閉じている）あいだは、何もしない
   const double spreadPct = (tk.ask - tk.bid) / tk.bid * 100.0;
   const double swapPct   = SwapTonightPct(sym, t0);
   if(swapPct < 0.0 || swapPct <= spreadPct + m_flatEdgeBp / 100.0)
     {
      m_flatDone[i] = t0;
      m_flatSkip++;
      return;                                           // スワップのほうが安い（または計算できない）ので、そのまま持ち越す
     }
   CloseSymbol(sym, StringFormat("区切りの前の手じまい（今夜のスワップ %.4f%% > スプレッド %.4f%%）", swapPct, spreadPct));
   if(CurrentLots(sym, dir) <= 0.0)
     {
      m_flatDone[i] = t0;
      m_flatCount++;
     }
  }

//+------------------------------------------------------------------+
void CIndexSleeves::Summary(void)
  {
   if(m_flatMin > 0)
      PrintFormat("[AMS] 指数の層：区切りの前に手じまった回数 %I64d、スワップのほうが安くて持ち越した回数 %I64d", m_flatCount, m_flatSkip);
   if(m_soGuard > 0.0)
      PrintFormat("[AMS] 指数の層：強制ロスカットを避ける上限で建玉を縮めた回数 %I64d", m_soCut);
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
   //--- 翌日の値動きの大きさの見積もり（1日の標準偏差）
   double dailyVol = 0.0;
   if(m_volModel == 1)
     {
      //--- HAR 型：その日の分散 = 値幅から計算した分散（Garman–Klass）＋ 前の終値から始値までの動きの2乗
      double dv[22];
      for(int q = 0; q < 22; q++)
        {
         const int    k  = got - 22 + q;
         const double o  = rt[k].open, h = rt[k].high, l = rt[k].low, cl = rt[k].close, pc = rt[k - 1].close;
         if(h > l && l > 0.0 && o > 0.0 && pc > 0.0)
           {
            const double hl = MathLog(h / l), co = MathLog(cl / o), on = MathLog(o / pc);
            dv[q] = MathMax(0.5 * hl * hl - 0.3862943611198906 * co * co, 0.0) + on * on;
           }
         else
           {
            const double cc = (pc > 0.0 && cl > 0.0) ? MathLog(cl / pc) : 0.0;
            dv[q] = cc * cc;
           }
        }
      double m5 = 0.0, m22 = 0.0;
      for(int q = 17; q < 22; q++)
         m5 += dv[q];
      for(int q = 0; q < 22; q++)
         m22 += dv[q];
      const double var = 0.37 * dv[21] + 0.56 * m5 / 5.0 + 0.20 * m22 / 22.0;
      dailyVol = (var > 0.0) ? MathSqrt(var) : 0.0;
     }
   else
     {
      //--- 直近60日の値動きの大きさ
      double sum = 0.0, sum2 = 0.0;
      for(int k = got - 60; k < got; k++)
        {
         const double r = rt[k].close / rt[k - 1].close - 1.0;
         sum  += r;
         sum2 += r * r;
        }
      const double var = (sum2 - sum * sum / 60.0) / 59.0;
      dailyVol = (var > 0.0) ? MathSqrt(var) : 0.0;
     }
   const double annVol = MathMax(dailyVol * MathSqrt(252.0), 0.025);
   //--- 目標の建玉の額（戻りの分は、VIX の状態で倍率をかける）
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   const int nRev = m_state[i][IX_R2] + m_state[i][IX_D7] + m_state[i][IX_IBS];
   string vixNote = "";
   const double vmult = (nRev > 0) ? VixMult(rt[got - 1].time, vixNote) : 1.0;
   double tgt = equity * (m_ruleW[nRev] * m_revUnit * vmult + m_state[i][IX_TREND] * m_trendUnit) / 100.0 / annVol;
   m_dvol[i] = dailyVol;
   //--- ほかの銘柄の建玉の額（最小の取引単位に届かず持っていない銘柄は、数えない）
   double others = 0.0;
   for(int k = 0; k < m_n; k++)
      if(k != i)
         others += m_tgtLots[k] * NotionalPerLot(m_sym[k]);
   if(m_maxLev > 0.0 && others + tgt > m_maxLev * equity)
     {
      tgt = MathMax(0.0, m_maxLev * equity - others);
      note += " （建玉の合計の上限のため縮小）";
     }
   const double npl = NotionalPerLot(sym);
   if(npl <= 0.0)
     {
      Warn(i, "1 lot の額が計算できないため、まだ売買できません");
      return(false);
     }
   //--- 強制ロスカットを避ける上限：すべての建玉が逆指値（k × 1日の値動きの見積もり）にかかっても、証拠金維持率がロスカットの水準を下回らない大きさ
   if(m_soGuard > 0.0 && tgt > 0.0)
     {
      const double kk = (m_slVolMul > 0.0) ? m_slVolMul : 4.0;
      const double so = (AccountInfoInteger(ACCOUNT_MARGIN_SO_MODE) == ACCOUNT_STOPOUT_MODE_PERCENT) ? AccountInfoDouble(ACCOUNT_MARGIN_SO_SO) / 100.0 : 1.0;
      double used = 0.0;
      for(int k = 0; k < m_n; k++)
        {
         if(k == i || m_tgtLots[k] <= 0.0)
            continue;
         double mk = 0.0;
         const double nk = NotionalPerLot(m_sym[k]);
         if(nk <= 0.0 || !OrderCalcMargin(ORDER_TYPE_BUY, m_sym[k], 1.0, SymbolInfoDouble(m_sym[k], SYMBOL_ASK), mk))
            mk = 0.1 * nk;
         used += m_tgtLots[k] * nk * (kk * m_dvol[k] + so * ((nk > 0.0) ? mk / nk : 0.1));
        }
      double mi = 0.0;
      if(!OrderCalcMargin(ORDER_TYPE_BUY, sym, 1.0, SymbolInfoDouble(sym, SYMBOL_ASK), mi))
         mi = 0.1 * npl;
      const double per   = kk * dailyVol + so * mi / npl;
      const double allow = (per > 0.0) ? (m_soGuard * equity - used) / per : tgt;
      if(tgt > allow)
        {
         tgt = MathMax(0.0, allow);
         m_soCut++;
         note += " （強制ロスカットを避ける上限のため縮小）";
        }
     }
   m_target[i] = tgt;
   const double want = tgt / npl;
   double tl = NormalizeLots(sym, want);
   m_tgtLots[i] = tl;
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
   //--- 逆指値を、今の値段から置き直す（持っている建玉すべて）
   if(tl > 0.0)
      ApplyStops(sym, dailyVol);
   if(changed || note != "")
      PrintFormat("[AMS] 指数の層：%s%s → 持つルール：%s、目標 %.2f lot（額 %.0f、値動きの見積もり 年 %.1f%%%s）", sym, note, StateText(i), tl, tgt,
                  annVol * 100.0, vixNote == "" ? "" : "、" + vixNote);
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
      if(m_flatMin > 0)
         FlatBeforeRollover(i, now);
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

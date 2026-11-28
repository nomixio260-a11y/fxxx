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
//|                                                                  |
//| 100章の仕組み：                                                    |
//|  まとめて丸める：小さい口座では、最小の取引単位のせいで目標どおりに持てない。 |
//|   そこで、ルールが出ている銘柄をまとめて、「目標とのずれの分散」            |
//|   (N − N*)ᵀ Σ (N − N*) が最小になるロットの組み合わせを選ぶ               |
//|   （N = 建玉の額、N* = 目標の額、Σ = 値動きの分散・共分散）。              |
//|   全体の値動きは、目標の (1 + ε) 倍を超えない。                           |
//|  状態の復元：起動時に、日足の履歴からルールの状態を作り直す                 |
//|   （状態のファイルがなくても、止まっていても、同じ状態に戻る）。             |
//|  前提の監視：戻りの手法は「指数の日々の値動きは反転しやすい」ことが前提。    |
//|   「当日の値動き」と「直前4日の値動きの重みつきの合計（4×前日+3×2日前       |
//|   +2×3日前+4日前）」の、過去 W 日の順位の相関（スピアマン）が、              |
//|   標準誤差（1 ÷ √W）の k 倍を超えている = 値動きが続きやすい相場のあいだは、   |
//|   IBS（200日の平均の条件がないルール）を止める。                            |
//|   判定は1つの銘柄（US500）の日足で、全銘柄まとめて行う。                      |
//|  観察モード：注文を一切出さず、判定と目標の建玉だけをログに出す。            |
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
   //--- 100章
   bool              m_joint;          // 建玉を、銘柄をまとめて丸める
   double            m_jointEps;       // まとめて丸めるとき、全体の値動きが目標を超えてよい割合
   bool              m_dryRun;         // 観察モード（注文を出さない）
   bool              m_warm;           // 起動時に、日足の履歴からルールの状態を復元する
   int               m_regDays;        // 前提の監視：過去何日の MAC5 の平均を見るか（0 で使わない）
   double            m_regThr;         // 順位の相関がこの値を超えたら「続きやすい相場」とみなして IBS を止める（入力は標準誤差の倍数。ここは相関の値）
   string            m_regRef;         // 監視に使う銘柄（空なら、銘柄ごとに自分の日足で判定する）
   double            m_eqOffset;       // 建玉の計算に使わない額（口座通貨）。有効証拠金からこの額を引いた残りを「元金」とみなす
   int               m_regOn[];        // 銘柄ごと：1 = IBS を使ってよい、0 = 止める
   double            m_regVal[];       // 銘柄ごと：監視の値（計算できないときは EMPTY_VALUE）
   bool              m_evOk[];         // 判定の結果（銘柄ごと）
   bool              m_evChanged[];
   string            m_evNote[];
   string            m_evVix[];
   double            m_evAnnVol[];
   double            m_evFrac[];       // 目標の建玉の額 ÷ 有効証拠金
   datetime          m_evalBar[];      // 判定を済ませた、作りかけの日足の時刻（まとめて丸める形）
   datetime          m_evLast[];       // 判定に使った、最後に確定した日足の時刻
   datetime          m_firstEval;      // 最初の銘柄の判定が済んだ時刻
   long              m_jointUp;        // まとめて丸めて、切り捨てより建玉が増えた回数
   long              m_soCut;          // 上の上限で建玉を縮めた回数
   int               m_delaySec;       // 新しい日足が始まってから、売買するまで待つ秒数
   double            m_maxSpreadPct;   // スプレッドがこの割合（値段に対する %）を超えているあいだは待つ
   int               m_state[][IX_NR]; // ルールごとの状態（1 = 持つ）
   datetime          m_lastBar[];      // 最後に処理したときの、作りかけの日足の時刻
   bool              m_reconOk[];      // 状態の復元が済んだか（日足がまだ届いていなければ、あとでやり直す）
   datetime          m_stateBar[];     // ルールの状態に反映した、最後の確定した日足の時刻（状態の復元を使うとき）
   bool              m_obsDone;        // 観察モード：口座と銘柄の条件を、値段が届いたあとにもう一度ログに出したか
   bool              m_riskRestored;   // 起動時：いま持っている建玉と値動きの見積もりを、上限の計算に反映し終えたか
   string            m_expSyms[];      // 観察モード：日足の履歴を書き出す銘柄（研究用）
   int               m_expLast[];      // その銘柄の、前回に取れた日足の本数
   int               m_expTries[];     // 試した回数
   bool              m_expDone[];      // 書き出しが済んだか
   datetime          m_expAt;          // 最後に試した時刻
   bool              m_tradeFail;      // 直前の売買の手順の中で、注文・決済・逆指値の変更に失敗したか
   int               m_retryCount[];   // その日足で、売買をやり直した回数
   datetime          m_retryAt[];      // 次にやり直してよい時刻
   bool              m_retryChanged[]; // 失敗した回に「ルールの出入り」があったか（やり直しのときも、必ず建玉を直す）
   datetime          m_jointRetryAt;   // まとめて丸める形：次にやり直してよい時刻
   long              m_retryBars;      // 注文の失敗で、やり直しになった回数（銘柄 × 日）
   long              m_retryGiveUp;    // やり直しの上限に達して、その日はあきらめた回数
   int               m_testRestartSec; // 検証用：この秒数ごとに「EA の起動し直し」を再現する（0 で使わない）
   bool              m_testLoseState;  // 検証用：起動し直しのとき、状態のファイルも失われたものとする
   datetime          m_testRestartAt;  // 検証用：最後に再現した時刻
   long              m_testRestarts;   // 検証用：再現した回数
   bool              m_posSeen[];      // 起動時：その銘柄の、いまの建玉を確かめたか
   datetime          m_seenBar[];      // 新しい日足を見つけたときの、その日足の時刻
   datetime          m_seenAt[];       // 見つけた時刻
   datetime          m_trendCheck[];   // 順張りを最後に見直した日足の時刻
   double            m_target[];       // 銘柄ごとの目標の建玉の額（口座通貨）
   datetime          m_warnAt[];       // 同じ注意を何度も出さないための時刻
   string            m_stateFile;

   double            SizingEquity(void);
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
   bool              Evaluate(const int i, const datetime t0);
   void              UpdateStates(const int i, const MqlRates &rt[], const int got, const int jStart, const bool entryOnAll,
                                  bool &changed, string &note);
   void              Reconstruct(const int i, const bool upToProcessed = true);
   void              ObserveLog(void);
   void              ObserveHistory(const int i, const int days);
   void              RestoreRisk(void);
   void              ExportDaily(void);
   void              SimulateRestart(void);
   double            DailyVol(const MqlRates &rt[], const int got);
   double            RegimeValue(const string sym);
   void              ExecuteJoint(void);
   void              TradeTo(const int i, const double tl, const bool changed, const double equity, string &note);
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
                          const int flatMin, const double flatEdgeBp, const string ruleWeights, const double soGuard,
                          const bool jointRound, const double jointEps, const bool warmStart, const int regimeDays,
                          const double regimeThr, const string regimeRef, const bool dryRun, const double equityOffset,
                          const string exportSyms, const int testRestartMin, const bool testLoseState);
   void              OnTick(void);
   void              Summary(void);
  };

//+------------------------------------------------------------------+
bool CIndexSleeves::Init(CTrade *trade, const ulong magic, const string &revSyms[], const string &trendSyms[],
                         const bool useR2, const bool useD7, const bool useIBS, const double revUnit, const double trendUnit,
                         const int trendDays, const double maxLev, const double maxMarginPct, const double band,
                         const double slVolMul, const int delayMin, const double maxSpreadPct,
                         const int volModel, const string vixFile, const double vixLow, const double vixHigh,
                         const int flatMin, const double flatEdgeBp, const string ruleWeights, const double soGuard,
                         const bool jointRound, const double jointEps, const bool warmStart, const int regimeDays,
                         const double regimeThr, const string regimeRef, const bool dryRun, const double equityOffset,
                         const string exportSyms, const int testRestartMin, const bool testLoseState)
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
   m_joint        = jointRound;
   m_jointEps     = MathMax(0.0, jointEps);
   m_warm         = warmStart;
   m_regDays      = (int)MathMax(0, regimeDays);
   //--- しきい値は、標準誤差（1 ÷ √日数）の何倍かで指定する。相関の値に直して持っておく
   m_regThr       = (m_regDays > 0) ? regimeThr / MathSqrt((double)m_regDays) : 0.0;
   m_regRef       = regimeRef;
   m_eqOffset     = MathMax(0.0, equityOffset);
   m_tradeFail    = false;
   m_jointRetryAt = 0;
   m_retryBars    = 0;
   m_retryGiveUp  = 0;
   m_testRestartSec = (int)MathMax(0, testRestartMin) * 60;
   m_testLoseState  = testLoseState;
   m_testRestartAt  = 0;
   m_testRestarts   = 0;
   //--- 観察モードのときだけ：日足の履歴を書き出す銘柄（研究用。テスターでは使わない）
   m_expAt = 0;
   ArrayResize(m_expSyms, 0);
   if(dryRun && !MQLInfoInteger(MQL_TESTER) && exportSyms != "")
     {
      string parts[];
      const int np = StringSplit(exportSyms, ',', parts);
      for(int q = 0; q < np; q++)
        {
         StringTrimLeft(parts[q]);
         StringTrimRight(parts[q]);
         if(parts[q] == "")
            continue;
         const int n = ArraySize(m_expSyms);
         ArrayResize(m_expSyms, n + 1);
         ArrayResize(m_expLast, n + 1);
         ArrayResize(m_expTries, n + 1);
         ArrayResize(m_expDone, n + 1);
         m_expSyms[n] = parts[q];
         m_expLast[n] = -1;
         m_expTries[n] = 0;
         m_expDone[n] = false;
        }
     }
   m_dryRun       = dryRun;
   m_firstEval    = 0;
   m_jointUp      = 0;
   m_obsDone      = false;
   m_riskRestored = false;
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
   ArrayResize(m_reconOk, m_n);
   ArrayResize(m_posSeen, m_n);
   ArrayResize(m_retryCount, m_n);
   ArrayResize(m_retryAt, m_n);
   ArrayResize(m_retryChanged, m_n);
   ArrayResize(m_stateBar, m_n);
   ArrayResize(m_seenBar, m_n);
   ArrayResize(m_seenAt, m_n);
   ArrayResize(m_trendCheck, m_n);
   ArrayResize(m_target, m_n);
   ArrayResize(m_warnAt, m_n);
   ArrayResize(m_flatDone, m_n);
   ArrayResize(m_dvol, m_n);
   ArrayResize(m_tgtLots, m_n);
   ArrayResize(m_regOn, m_n);
   ArrayResize(m_regVal, m_n);
   ArrayResize(m_evOk, m_n);
   ArrayResize(m_evChanged, m_n);
   ArrayResize(m_evNote, m_n);
   ArrayResize(m_evVix, m_n);
   ArrayResize(m_evAnnVol, m_n);
   ArrayResize(m_evFrac, m_n);
   ArrayResize(m_evalBar, m_n);
   ArrayResize(m_evLast, m_n);
   for(int i = 0; i < m_n; i++)
     {
      m_flatDone[i] = 0;
      m_dvol[i] = 0.0;
      m_tgtLots[i] = 0.0;
      m_regOn[i] = 1;
      m_regVal[i] = EMPTY_VALUE;
      m_evOk[i] = false;
      m_evChanged[i] = false;
      m_evNote[i] = "";
      m_evVix[i] = "";
      m_evAnnVol[i] = 0.0;
      m_evFrac[i] = 0.0;
      m_evalBar[i] = 0;
      m_evLast[i] = 0;
      for(int r = 0; r < IX_NR; r++)
         m_state[i][r] = 0;
      m_lastBar[i] = 0;
      m_reconOk[i] = false;
      m_posSeen[i] = false;
      m_retryCount[i] = 0;
      m_retryAt[i] = 0;
      m_retryChanged[i] = false;
      m_stateBar[i] = 0;
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
   if(m_regDays > 0 && m_regRef != "" && !SymbolSelect(m_regRef, true))
     {
      PrintFormat("[AMS] 指数の層：前提の監視に使う銘柄 %s が口座にないため、銘柄ごとに判定します", m_regRef);
      m_regRef = "";
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
   PrintFormat("[AMS] 指数の層：建玉の丸め方 %s、状態の復元 %s、前提の監視 %s%s",
               m_joint ? StringFormat("まとめて丸める（全体の値動きは目標の %.2f 倍まで）", 1.0 + m_jointEps) : "銘柄ごとに切り捨て",
               m_warm ? "あり" : "なし",
               m_regDays > 0 ? StringFormat("あり（%s過去 %d 日の、当日と直前4日の値動きの順位の相関が %+.3f を超えたら IBS を止める）",
                                            m_regRef != "" ? m_regRef + " の日足で、すべての銘柄を判定。" : "", m_regDays, m_regThr) : "なし",
               m_dryRun ? "、**観察モード（注文は出しません）**" : "");
   if(m_eqOffset > 0.0)
      PrintFormat("[AMS] 指数の層：有効証拠金 %.0f のうち %.0f は建玉の計算に使いません（残りの %.0f を元金とみなして、建玉と上限を計算します）",
                  AccountInfoDouble(ACCOUNT_EQUITY), m_eqOffset, SizingEquity());
   if(m_dryRun)
      ObserveLog();
   //--- 起動時に、日足の履歴からルールの状態を復元する（状態のファイルがなくても、止まっていても、同じ状態に戻る）
   if(m_warm)
      for(int i = 0; i < m_n; i++)
         Reconstruct(i);
   return(m_n > 0);
  }

//+------------------------------------------------------------------+
//| 起動時：いま持っている建玉と、値動きの見積もりを、上限の計算に反映する。  |
//| 上限（建玉の合計・強制ロスカットを避ける上限）は、ほかの銘柄の建玉を       |
//| 数えて決める。再起動の直後は、その記録（目標のロット・値動きの見積もり）が  |
//| 空なので、次の日足の判定で、まだ判定していない銘柄の建玉が数に入らず、      |
//| 上限が甘くなる。テスターでは再起動がないので、実際の運用だけで起きる違い。   |
//| 値段と日足が届くまで、毎ティックやり直す。                              |
//+------------------------------------------------------------------+
void CIndexSleeves::RestoreRisk(void)
  {
   if(!MQLInfoInteger(MQL_TESTER) && !TerminalInfoInteger(TERMINAL_CONNECTED))
      return;
   bool all = true;
   string held = "";
   for(int i = 0; i < m_n; i++)
     {
      if(m_dvol[i] <= 0.0)
        {
         MqlRates rt[];
         ArraySetAsSeries(rt, false);
         const int got = CopyRates(m_sym[i], PERIOD_D1, 1, IX_BARS, rt);
         if(got >= 215)
            m_dvol[i] = DailyVol(rt, got);
         else
            all = false;
        }
      if(!m_posSeen[i])
        {
         int dir = 0;
         const double cur = CurrentLots(m_sym[i], dir);
         if(dir > 0 && cur > 0.0 && m_tgtLots[i] <= 0.0)
           {
            m_tgtLots[i] = cur;
            held += StringFormat(" %s %.2f lot", m_sym[i], cur);
           }
         m_posSeen[i] = true;
        }
     }
   if(held != "")
      PrintFormat("[AMS] 指数の層：起動時に持っていた建玉を、上限の計算に反映しました：%s", held);
   if(all)
      m_riskRestored = true;
  }

//+------------------------------------------------------------------+
//| 検証用：EA の起動し直しを再現する。                                    |
//| 実際の運用では、EA は数時間ごとに起動し直される（GitHub の回の入れ替え）。  |
//| テスターには起動し直しがないので、メモリの中の記録を、起動した直後と同じ    |
//| 状態に戻して、同じ結果になるかを確かめる。                              |
//|  残るもの：状態のファイルに書く値（最後に処理した日足・順張りの見直しの日）  |
//|  消えるもの：ルールの状態（日足から復元する）、目標のロット、値動きの見積もり |
//| m_testLoseState = true なら、状態のファイルも失われたものとする。          |
//+------------------------------------------------------------------+
void CIndexSleeves::SimulateRestart(void)
  {
   m_testRestarts++;
   for(int i = 0; i < m_n; i++)
     {
      if(m_warm)
         for(int r = 0; r < 3; r++)
            m_state[i][r] = 0;
      m_tgtLots[i]  = 0.0;
      m_dvol[i]     = 0.0;
      m_target[i]   = 0.0;
      m_regOn[i]    = 1;
      m_regVal[i]   = EMPTY_VALUE;
      m_evOk[i]     = false;
      m_evChanged[i] = false;
      m_evNote[i]   = "";
      m_evVix[i]    = "";
      m_evAnnVol[i] = 0.0;
      m_evFrac[i]   = 0.0;
      m_evalBar[i]  = 0;
      m_evLast[i]   = 0;
      m_seenBar[i]  = 0;
      m_seenAt[i]   = 0;
      m_warnAt[i]   = 0;
      m_reconOk[i]  = false;
      m_stateBar[i] = 0;
      m_posSeen[i]  = false;
      m_retryCount[i] = 0;
      m_retryAt[i]    = 0;
      m_retryChanged[i] = false;
      if(m_testLoseState)
        {
         m_lastBar[i]    = 0;
         m_trendCheck[i] = 0;
         if(!m_warm)
            for(int r = 0; r < IX_NR; r++)
               m_state[i][r] = 0;
        }
     }
   m_riskRestored = false;
   m_firstEval    = 0;
   if(m_warm)
      for(int i = 0; i < m_n; i++)
         Reconstruct(i);
  }

//+------------------------------------------------------------------+
//| 観察モード：指定した銘柄の日足の履歴と、銘柄の条件を、共通フォルダの       |
//| ファイルに書き出す（研究用。注文は出さない）。履歴は、端末がサーバーから    |
//| 取り寄せるのに時間がかかるので、本数が変わらなくなるまで10秒おきに試す。    |
//+------------------------------------------------------------------+
void CIndexSleeves::ExportDaily(void)
  {
   const int n = ArraySize(m_expSyms);
   if(n == 0)
      return;
   const datetime now = TimeLocal();
   if((long)now - (long)m_expAt < 10)
      return;
   m_expAt = now;
   for(int j = 0; j < n; j++)
     {
      if(m_expDone[j])
         continue;
      const string sym = m_expSyms[j];
      if(!SymbolSelect(sym, true))
        {
         PrintFormat("[AMS] 指数の層：（書き出し）%s は口座にありません", sym);
         m_expDone[j] = true;
         continue;
        }
      MqlRates rt[];
      ArraySetAsSeries(rt, false);
      const int got = CopyRates(sym, PERIOD_D1, 0, 6000, rt);
      m_expTries[j]++;
      const bool stable = (got > 0 && got == m_expLast[j] && m_expTries[j] >= 3);
      m_expLast[j] = got;
      if(!stable && m_expTries[j] < 45)
         continue;
      m_expDone[j] = true;
      if(got <= 0)
        {
         PrintFormat("[AMS] 指数の層：（書き出し）%s の日足が取れませんでした", sym);
         continue;
        }
      const int fh = FileOpen("AMS_d1_" + sym + ".csv", FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
      if(fh == INVALID_HANDLE)
         continue;
      FileWrite(fh, "date", "open", "high", "low", "close", "tick_volume", "spread");
      const int dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      for(int k = 0; k < got; k++)
         FileWrite(fh, TimeToString(rt[k].time, TIME_DATE), DoubleToString(rt[k].open, dg), DoubleToString(rt[k].high, dg), DoubleToString(rt[k].low, dg),
                   DoubleToString(rt[k].close, dg), IntegerToString(rt[k].tick_volume), IntegerToString(rt[k].spread));
      FileClose(fh);
      //--- 銘柄の条件（1行）
      const int fs = FileOpen("AMS_ix_symbols.csv", FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
      if(fs != INVALID_HANDLE)
        {
         if(FileSize(fs) == 0)
            FileWrite(fs, "symbol", "bars", "first", "last", "digits", "point", "contract", "vol_min", "vol_step", "swap_mode", "swap_long", "swap_short",
                      "swap_sun", "swap_mon", "swap_tue", "swap_wed", "swap_thu", "swap_fri", "swap_sat", "notional_1lot", "margin_1lot", "spread_points", "bid",
                      "currency_profit", "stops_level", "trade_mode", "calc_mode", "swap_3days", "path");
         FileSeek(fs, 0, SEEK_END);
         double mg = 0.0;
         if(!OrderCalcMargin(ORDER_TYPE_BUY, sym, 1.0, SymbolInfoDouble(sym, SYMBOL_ASK), mg))
            mg = 0.0;
         FileWrite(fs, sym, IntegerToString(got), TimeToString(rt[0].time, TIME_DATE), TimeToString(rt[got - 1].time, TIME_DATE), IntegerToString(dg),
                   DoubleToString(SymbolInfoDouble(sym, SYMBOL_POINT), 6), DoubleToString(SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE), 2),
                   DoubleToString(SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN), 2), DoubleToString(SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP), 2),
                   IntegerToString(SymbolInfoInteger(sym, SYMBOL_SWAP_MODE)), DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_LONG), 4),
                   DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_SHORT), 4),
                   DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_SUNDAY), 1), DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_MONDAY), 1),
                   DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_TUESDAY), 1), DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_WEDNESDAY), 1),
                   DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_THURSDAY), 1), DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_FRIDAY), 1),
                   DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_SATURDAY), 1),
                   DoubleToString(NotionalPerLot(sym), 0), DoubleToString(mg, 0),
                   DoubleToString((SymbolInfoDouble(sym, SYMBOL_ASK) - SymbolInfoDouble(sym, SYMBOL_BID)) / MathMax(SymbolInfoDouble(sym, SYMBOL_POINT), 1e-9), 1),
                   DoubleToString(SymbolInfoDouble(sym, SYMBOL_BID), dg), SymbolInfoString(sym, SYMBOL_CURRENCY_PROFIT),
                   IntegerToString(SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL)), IntegerToString(SymbolInfoInteger(sym, SYMBOL_TRADE_MODE)),
                   IntegerToString(SymbolInfoInteger(sym, SYMBOL_TRADE_CALC_MODE)), IntegerToString(SymbolInfoInteger(sym, SYMBOL_SWAP_ROLLOVER3DAYS)),
                   SymbolInfoString(sym, SYMBOL_PATH));
         FileClose(fs);
        }
      PrintFormat("[AMS] 指数の層：（書き出し）%s 日足 %d 本（%s〜%s）、スワップ 買い %.4f / 売り %.4f、最小 %.2f lot・刻み %.2f、1 lot の額 %.0f、スプレッド %.1f ポイント",
                  sym, got, TimeToString(rt[0].time, TIME_DATE), TimeToString(rt[got - 1].time, TIME_DATE), SymbolInfoDouble(sym, SYMBOL_SWAP_LONG),
                  SymbolInfoDouble(sym, SYMBOL_SWAP_SHORT), SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN), SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP), NotionalPerLot(sym),
                  (SymbolInfoDouble(sym, SYMBOL_ASK) - SymbolInfoDouble(sym, SYMBOL_BID)) / MathMax(SymbolInfoDouble(sym, SYMBOL_POINT), 1e-9));
     }
  }

//+------------------------------------------------------------------+
//| 観察モード：口座と銘柄の条件をログに出す（実際の環境とテスターを比べる）   |
//+------------------------------------------------------------------+
void CIndexSleeves::ObserveLog(void)
  {
   PrintFormat("[AMS] 指数の層：（観察モード）口座：レバレッジ 1:%d、証拠金の方式 %d、ロスカットの水準 %.0f（方式 %d）、有効証拠金 %.0f（建玉の計算に使う額 %.0f）、建玉 %d",
               (int)AccountInfoInteger(ACCOUNT_LEVERAGE), (int)AccountInfoInteger(ACCOUNT_MARGIN_MODE), AccountInfoDouble(ACCOUNT_MARGIN_SO_SO),
               (int)AccountInfoInteger(ACCOUNT_MARGIN_SO_MODE), AccountInfoDouble(ACCOUNT_EQUITY), SizingEquity(), PositionsTotal());
   for(int i = 0; i < m_n; i++)
     {
      MqlTick tk;
      const bool okTick = SymbolInfoTick(m_sym[i], tk);
      MqlRates rr[];
      const int bars = CopyRates(m_sym[i], PERIOD_D1, 1, 3000, rr);
      double mg = 0.0;
      if(!OrderCalcMargin(ORDER_TYPE_BUY, m_sym[i], 1.0, SymbolInfoDouble(m_sym[i], SYMBOL_ASK), mg))
         mg = 0.0;
      const datetime b0 = iTime(m_sym[i], PERIOD_D1, 0);
      PrintFormat("[AMS] 指数の層：（観察モード）%s 最小 %.2f lot・刻み %.2f・最大 %.1f、1 lot の額 %.0f・必要証拠金 %.0f（証拠金率 %.2f%%）、契約の大きさ %.2f、スワップ（方式=%d）買い %.4f / 売り %.4f、今夜のスワップ 値段の %.4f%%、作りかけの日足 %s、取引の終わり %s",
                  m_sym[i], SymbolInfoDouble(m_sym[i], SYMBOL_VOLUME_MIN), SymbolInfoDouble(m_sym[i], SYMBOL_VOLUME_STEP), SymbolInfoDouble(m_sym[i], SYMBOL_VOLUME_MAX),
                  NotionalPerLot(m_sym[i]), mg, NotionalPerLot(m_sym[i]) > 0.0 ? mg / NotionalPerLot(m_sym[i]) * 100.0 : 0.0,
                  SymbolInfoDouble(m_sym[i], SYMBOL_TRADE_CONTRACT_SIZE), (int)SymbolInfoInteger(m_sym[i], SYMBOL_SWAP_MODE),
                  SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_LONG), SymbolInfoDouble(m_sym[i], SYMBOL_SWAP_SHORT), b0 > 0 ? SwapTonightPct(m_sym[i], b0) : 0.0,
                  b0 > 0 ? TimeToString(b0, TIME_DATE | TIME_MINUTES) : "?", b0 > 0 ? TimeToString(SessionEnd(m_sym[i], b0), TIME_MINUTES) : "?");
      PrintFormat("[AMS] 指数の層：（観察モード）%s 逆指値の最小距離 %d ポイント、注文の方式 %d、今のスプレッド %.1f ポイント（値段の %.4f%%）、確定した日足 %d 本（最初 %s）、最後の日足 %s 始 %.1f 高 %.1f 安 %.1f 終 %.1f",
                  m_sym[i], (int)SymbolInfoInteger(m_sym[i], SYMBOL_TRADE_STOPS_LEVEL), (int)SymbolInfoInteger(m_sym[i], SYMBOL_FILLING_MODE),
                  okTick ? (tk.ask - tk.bid) / SymbolInfoDouble(m_sym[i], SYMBOL_POINT) : 0.0, (okTick && tk.bid > 0.0) ? (tk.ask - tk.bid) / tk.bid * 100.0 : 0.0,
                  bars, bars > 0 ? TimeToString(rr[0].time, TIME_DATE) : "?", bars > 0 ? TimeToString(rr[bars - 1].time, TIME_DATE) : "?",
                  bars > 0 ? rr[bars - 1].open : 0.0, bars > 0 ? rr[bars - 1].high : 0.0, bars > 0 ? rr[bars - 1].low : 0.0, bars > 0 ? rr[bars - 1].close : 0.0);
     }
  }

//+------------------------------------------------------------------+
//| 建玉の計算に使う額：有効証拠金 − 使わない額（入力）。                   |
//| デモ口座の残高が検証の元金より大きいときに、検証と同じ大きさで動かすため。 |
//| 損益はそのまま反映されるので、複利の効き方は元金が小さい口座と同じになる。 |
//+------------------------------------------------------------------+
double CIndexSleeves::SizingEquity(void)
  {
   return(MathMax(0.0, AccountInfoDouble(ACCOUNT_EQUITY) - m_eqOffset));
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
   if(m_dryRun)
     {
      PrintFormat("[AMS] 指数の層：（観察モード）%s を決済するところ（%s）", sym, why);
      return;
     }
   m_trade.SetTypeFillingBySymbol(sym);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != m_magic)
         continue;
      if(m_trade.PositionClose(tk))
         PrintFormat("[AMS] 指数の層：決済 %s #%I64u（%s）", sym, tk, why);
      else
        {
         m_tradeFail = true;
         PrintFormat("[AMS] 指数の層：%s の決済に失敗（%d %s）", sym, m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
        }
     }
  }

//+------------------------------------------------------------------+
//| 買いを lots 増やす（1回の注文の上限を超える分は分けて注文）              |
//+------------------------------------------------------------------+
void CIndexSleeves::OpenLots(const string sym, double lots, const double dailyVol)
  {
   if(m_dryRun)
     {
      const double b = SymbolInfoDouble(sym, SYMBOL_BID);
      PrintFormat("[AMS] 指数の層：（観察モード）%s を %.2f lot 買うところ（買値 %s、スプレッド %.4f%%、逆指値 %s）", sym, lots,
                  DoubleToString(SymbolInfoDouble(sym, SYMBOL_ASK), (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
                  b > 0.0 ? (SymbolInfoDouble(sym, SYMBOL_ASK) - b) / b * 100.0 : 0.0,
                  (m_slVolMul > 0.0 && dailyVol > 0.0) ? DoubleToString(b * (1.0 - m_slVolMul * dailyVol), (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)) : "なし");
      return;
     }
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
         m_tradeFail = true;
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
   if(m_dryRun)
     {
      PrintFormat("[AMS] 指数の層：（観察モード）%s を %.2f lot 減らすところ", sym, lots);
      return;
     }
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
         else
           {
            m_tradeFail = true;
            PrintFormat("[AMS] 指数の層：%s の決済に失敗（%d %s）", sym, m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
           }
        }
      else
        {
         const double v = NormalizeLots(sym, lots);
         if(v <= 0.0)
            break;
         if(m_trade.PositionClosePartial(tk, v))
            lots -= v;
         else
           {
            m_tradeFail = true;
            PrintFormat("[AMS] 指数の層：%s の一部の決済に失敗（%d %s）", sym, m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
            break;
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| 逆指値を、今の値段から「その日の値動きの見積もり × k」だけ下に置き直す     |
//+------------------------------------------------------------------+
void CIndexSleeves::ApplyStops(const string sym, const double dailyVol)
  {
   if(m_slVolMul <= 0.0 || dailyVol <= 0.0 || m_dryRun)
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
        {
         m_tradeFail = true;
         PrintFormat("[AMS] 指数の層：%s #%I64u の逆指値を置き直せません（%d %s）", sym, tk, m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription());
        }
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
   if(m_joint)
      PrintFormat("[AMS] 指数の層：まとめて丸めて、切り捨てより建玉が増えた回数 %I64d", m_jointUp);
   if(m_retryBars > 0 || m_retryGiveUp > 0)
      PrintFormat("[AMS] 指数の層：注文の失敗でやり直した回数（銘柄 × 日）%I64d、やり直してもできずにあきらめた回数 %I64d", m_retryBars, m_retryGiveUp);
   if(m_testRestartSec > 0)
      PrintFormat("[AMS] 指数の層：（検証用）EA の起動し直しを再現した回数 %I64d（%d 分ごと%s）", m_testRestarts, m_testRestartSec / 60,
                  m_testLoseState ? "。状態のファイルも失われたものとした" : "");
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
   if(MQLInfoInteger(MQL_TESTER) || m_dryRun)
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
//| 日足 jStart〜got-1 を古い順に見て、ルールの状態を更新する               |
//| entryOnAll = true なら、途中の日足でも「買い」の判定をする（状態の復元用）  |
//+------------------------------------------------------------------+
void CIndexSleeves::UpdateStates(const int i, const MqlRates &rt[], const int got, const int jStart, const bool entryOnAll,
                                 bool &changed, string &note)
  {
   for(int j = jStart; j < got; j++)
     {
      const bool last   = (j == got - 1);
      const bool newest = last || entryOnAll;
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
         if(m_ruleOn[IX_IBS] && last)
           {
            //--- 前提の監視：値動きが続きやすい相場と判定されているあいだは、IBS を持たない
            const int st = (ibs < 0.2 && m_regOn[i] > 0) ? 1 : 0;
            if(st != m_state[i][IX_IBS])
              {
               m_state[i][IX_IBS] = st;
               changed = true;
               note += StringFormat(" IBS %s（%.2f）", st > 0 ? "買い" : "手じまい", ibs);
              }
           }
        }
      if(m_trd[i] && last && (m_trendCheck[i] == 0 || (long)rt[j].time - (long)m_trendCheck[i] >= (long)m_trendDays * 86400))
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
  }

//+------------------------------------------------------------------+
//| 前提の監視の値：「当日の値動き」と「直前4日の値動きの重みつきの合計      |
//| （4×前日 + 3×2日前 + 2×3日前 + 4日前）」の、過去 m_regDays 日の         |
//| 順位の相関（スピアマン）。マイナス = 反転しやすい、プラス = 続きやすい。    |
//| 順位で測るので、飛び抜けて大きい1日（急落の日）に引っ張られない           |
//| （値動きの掛け算の平均で測ると、急落の当日だけ「続きやすい」と誤って判定    |
//|   する。100章）。日足が m_regDays + 6 本そろわなければ EMPTY_VALUE         |
//+------------------------------------------------------------------+
double CIndexSleeves::RegimeValue(const string sym)
  {
   if(m_regDays <= 0)
      return(EMPTY_VALUE);
   const int W    = m_regDays;
   const int need = W + 6;
   MqlRates rt[];
   ArraySetAsSeries(rt, false);
   const int got = CopyRates(sym, PERIOD_D1, 1, need, rt);
   if(got < need)
      return(EMPTY_VALUE);
   double r[];
   ArrayResize(r, got);
   r[0] = 0.0;
   for(int k = 1; k < got; k++)
      r[k] = (rt[k].close > 0.0 && rt[k - 1].close > 0.0) ? MathLog(rt[k].close / rt[k - 1].close) : 0.0;
   //--- 並べ替えて順位をつける（同じ値は、順位の平均）
   double a[][2], b[][2], ra[], rb[];
   ArrayResize(a, W);
   ArrayResize(b, W);
   ArrayResize(ra, W);
   ArrayResize(rb, W);
   for(int q = 0; q < W; q++)
     {
      const int k = got - W + q;
      a[q][0] = r[k];
      a[q][1] = q;
      b[q][0] = 4.0 * r[k - 1] + 3.0 * r[k - 2] + 2.0 * r[k - 3] + r[k - 4];
      b[q][1] = q;
     }
   ArraySort(a);
   ArraySort(b);
   for(int pass = 0; pass < 2; pass++)
     {
      int q = 0;
      while(q < W)
        {
         int e = q;
         while(e + 1 < W && ((pass == 0) ? (a[e + 1][0] == a[q][0]) : (b[e + 1][0] == b[q][0])))
            e++;
         const double rank = 0.5 * (q + e) + 1.0;
         for(int z = q; z <= e; z++)
           {
            if(pass == 0)
               ra[(int)a[z][1]] = rank;
            else
               rb[(int)b[z][1]] = rank;
           }
         q = e + 1;
        }
     }
   double ma = 0.0, mb = 0.0, saa = 0.0, sbb = 0.0, sab = 0.0;
   for(int q = 0; q < W; q++)
     {
      ma += ra[q];
      mb += rb[q];
     }
   ma /= W;
   mb /= W;
   for(int q = 0; q < W; q++)
     {
      const double da = ra[q] - ma, db = rb[q] - mb;
      saa += da * da;
      sbb += db * db;
      sab += da * db;
     }
   if(saa <= 0.0 || sbb <= 0.0)
      return(EMPTY_VALUE);
   return(sab / MathSqrt(saa * sbb));
  }

//+------------------------------------------------------------------+
//| 起動時：日足の履歴から、ルールの状態を作り直す                          |
//| （直近80本を、何も持っていない状態から順にたどる。R2・D7 は数日〜数十日で   |
//|   手じまうので、これで今の状態が決まる）                                |
//+------------------------------------------------------------------+
void CIndexSleeves::Reconstruct(const int i, const bool upToProcessed = true)
  {
   const string sym = m_sym[i];
   MqlRates rt[];
   ArraySetAsSeries(rt, false);
   const int got = CopyRates(sym, PERIOD_D1, 1, IX_BARS + 80, rt);
   if(got < 215)
     {
      PrintFormat("[AMS] 指数の層：%s 確定した日足が %d 本しかないため、状態を復元できません", sym, got);
      return;
     }
   //--- どの日足までを反映するか。
   //    起動時（upToProcessed = true）：前回の処理のあとに確定した日足（前回の処理のときに作りかけだった足）は、ここでは反映しない。
   //    次の判定で、ふつうどおり「新しく確定した1本」として反映する（そうしないと、起動し直した日だけ、ルールの出入りが
   //    「変化なし」に見えて、止まらずに動いていた場合と建玉の直し方が変わる）。
   int upto = got;
   if(upToProcessed && m_lastBar[i] > 0)
      while(upto > 216 && rt[upto - 1].time >= m_lastBar[i])
         upto--;
   const string before = StateText(i);
   for(int r = 0; r < 3; r++)
      m_state[i][r] = 0;
   if(m_regDays > 0)
     {
      m_regVal[i] = RegimeValue(m_regRef != "" ? m_regRef : sym);
      m_regOn[i]  = (m_regVal[i] != EMPTY_VALUE && m_regVal[i] > m_regThr) ? 0 : 1;
     }
   bool changed = false;
   string note = "";
   const datetime keepCheck = m_trendCheck[i];
   UpdateStates(i, rt, upto, (int)MathMax(205, upto - 80), true, changed, note);
   if(m_trd[i] && keepCheck == 0)
     {
      //--- 順張り：前回の見直しの記録がなければ、最後の日足で判定する
      double s200 = 0.0;
      for(int k = upto - 200; k < upto; k++)
         s200 += rt[k].close;
      m_state[i][IX_TREND] = (rt[upto - 1].close > s200 / 200.0) ? 1 : 0;
      m_trendCheck[i] = rt[upto - 1].time;
     }
   m_reconOk[i]  = true;
   m_stateBar[i] = rt[upto - 1].time;
   PrintFormat("[AMS] 指数の層：%s 状態の復元（最後の日足 %s）：%s%s%s", sym, TimeToString(rt[upto - 1].time, TIME_DATE), StateText(i),
               before != StateText(i) ? "（記録では " + before + "）" : "",
               m_regDays > 0 ? (m_regVal[i] == EMPTY_VALUE ? "、前提の監視：日足が足りず計算できない（IBS は使う）"
                                : StringFormat("、前提の監視 %+.3f（%s）", m_regVal[i], m_regOn[i] > 0 ? "反転しやすい相場" : "続きやすい相場：IBS を止める")) : "");
  }

//+------------------------------------------------------------------+
//| 翌日の値動きの大きさの見積もり（1日の標準偏差）。rt は古い順、         |
//| 最後の要素が、最後に確定した日足                                      |
//+------------------------------------------------------------------+
double CIndexSleeves::DailyVol(const MqlRates &rt[], const int got)
  {
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
   return(dailyVol);
  }

//+------------------------------------------------------------------+
//| 観察モード：過去 days 日分の判定を、口座の日足の履歴からやり直して      |
//| ログに出す（テスターの同じ日の判定と突き合わせる。状態は変えない）       |
//+------------------------------------------------------------------+
void CIndexSleeves::ObserveHistory(const int i, const int days)
  {
   const string sym = m_sym[i];
   int keep[IX_NR];
   for(int r = 0; r < IX_NR; r++)
      keep[r] = m_state[i][r];
   const datetime keepCheck = m_trendCheck[i];
   for(int sft = days; sft >= 1; sft--)
     {
      MqlRates rt[];
      ArraySetAsSeries(rt, false);
      const int got = CopyRates(sym, PERIOD_D1, 1 + sft, IX_BARS + 80, rt);
      if(got < 215)
         continue;
      for(int r = 0; r < 3; r++)
         m_state[i][r] = 0;
      bool changed = false;
      string note = "";
      UpdateStates(i, rt, got, (int)MathMax(205, got - 80), true, changed, note);
      const double dailyVol = DailyVol(rt, got);
      const double annVol   = MathMax(dailyVol * MathSqrt(252.0), 0.025);
      const int    nRev     = m_state[i][IX_R2] + m_state[i][IX_D7] + m_state[i][IX_IBS];
      string vixNote = "";
      const double vmult = (nRev > 0) ? VixMult(rt[got - 1].time, vixNote) : 1.0;
      PrintFormat("[AMS] 指数の層：（観察モード・過去の判定）%s %s までの日足で判定：持つルール：%s、目標の割合 %.4f、1日の値動きの見積もり %.4f%%、VIX の倍率 %.2f、その日足 始 %.1f 高 %.1f 安 %.1f 終 %.1f",
                  sym, TimeToString(rt[got - 1].time, TIME_DATE), StateText(i), m_ruleW[nRev] * m_revUnit * vmult / 100.0 / annVol, dailyVol * 100.0, vmult,
                  rt[got - 1].open, rt[got - 1].high, rt[got - 1].low, rt[got - 1].close);
     }
   for(int r = 0; r < IX_NR; r++)
      m_state[i][r] = keep[r];
   m_trendCheck[i] = keepCheck;
  }

//+------------------------------------------------------------------+
//| 判定：確定した日足でルールの状態を更新し、値動きの見積もりと、            |
//| 目標の建玉の額（有効証拠金に対する割合）を計算する。売買はしない。         |
//| 日足がそろわないときは false（あとでやり直す）                          |
//+------------------------------------------------------------------+
bool CIndexSleeves::Evaluate(const int i, const datetime t0)
  {
   const string sym = m_sym[i];
   m_evOk[i] = false;
   MqlRates rt[];
   ArraySetAsSeries(rt, false);
   const int got = CopyRates(sym, PERIOD_D1, 1, IX_BARS, rt);
   if(got < 215)
     {
      Warn(i, StringFormat("確定した日足が %d 本しかないため、まだ判定できません（215 本以上が必要）", got));
      return(false);
     }
   //--- 前提の監視（IBS を使ってよいか）
   if(m_regDays > 0)
     {
      m_regVal[i] = RegimeValue(m_regRef != "" ? m_regRef : sym);
      const int on = (m_regVal[i] != EMPTY_VALUE && m_regVal[i] > m_regThr) ? 0 : 1;
      if(on != m_regOn[i])
         PrintFormat("[AMS] 指数の層：%s 前提の監視 %+.3f → %s", sym, m_regVal[i], on > 0 ? "反転しやすい相場に戻った（IBS を使う）" : "続きやすい相場（IBS を止める）");
      m_regOn[i] = on;
     }
   bool changed = false;
   string note = "";
   if(m_warm)
     {
      //--- 状態の復元を使う形：ルールの状態は、いつも「止まらずに動いていた場合」と同じにする。
      //    まだ復元できていない（起動時に日足が届いていなかった）・2本以上の日足が抜けた（止まっていた）ときは、履歴から作り直す。
      //    ふつうは、新しく確定した1本だけを反映する。
      if(!m_reconOk[i] || (got >= 2 && rt[got - 2].time > m_stateBar[i]))
        {
         const string before = StateText(i);
         const bool   first  = !m_reconOk[i];
         m_reconOk[i] = false;
         //--- 初めての復元（起動時に日足が届いていなかった）は、前回の処理までを反映する。日足が抜けたときは、最後の日足まで作り直す
         Reconstruct(i, first);
         if(!m_reconOk[i])
           {
            Warn(i, "日足の履歴がまだそろわないため、状態を復元できません（そろうまで待ちます）");
            return(false);
           }
         if(first && got >= 2 && rt[got - 2].time > m_stateBar[i])
           {
            //--- 起動した時点で、すでに2本以上の日足が抜けていた：最後の日足まで作り直す
            const string mid = StateText(i);
            m_reconOk[i] = false;
            Reconstruct(i, false);
            if(!m_reconOk[i])
               return(false);
            if(mid != StateText(i))
              {
               changed = true;
               note += " （止まっていたあいだの日足から、状態を作り直した）";
              }
           }
         if(!first && before != StateText(i))
           {
            changed = true;
            note += " （止まっていたあいだの日足から、状態を作り直した）";
           }
        }
      if(rt[got - 1].time > m_stateBar[i])
        {
         UpdateStates(i, rt, got, got - 1, false, changed, note);
         m_stateBar[i] = rt[got - 1].time;
        }
     }
   else
     {
      //--- 前回の処理のあとに確定した日足（ふつうは1本）。止まっていたあいだの分は、手じまいの条件だけを古い順に確かめる
      int jStart = got - 1;
      if(m_lastBar[i] > 0)
         for(int j = got - 1; j >= 0 && j >= got - IX_REPLAY; j--)
            if(rt[j].time >= m_lastBar[i])
               jStart = j;
      if(jStart < 205)
         jStart = 205;
      UpdateStates(i, rt, got, jStart, false, changed, note);
     }
   //--- 翌日の値動きの大きさの見積もり（1日の標準偏差）
   const double dailyVol = DailyVol(rt, got);
   const double annVol = MathMax(dailyVol * MathSqrt(252.0), 0.025);
   //--- 目標の建玉の額（戻りの分は、VIX の状態で倍率をかける）。有効証拠金に対する割合で持っておく
   const int nRev = m_state[i][IX_R2] + m_state[i][IX_D7] + m_state[i][IX_IBS];
   string vixNote = "";
   const double vmult = (nRev > 0) ? VixMult(rt[got - 1].time, vixNote) : 1.0;
   m_evFrac[i]    = (m_ruleW[nRev] * m_revUnit * vmult + m_state[i][IX_TREND] * m_trendUnit) / 100.0 / annVol;
   m_evChanged[i] = changed;
   m_evNote[i]    = note;
   m_evVix[i]     = vixNote;
   m_evAnnVol[i]  = annVol;
   m_dvol[i]      = dailyVol;
   m_evLast[i]    = rt[got - 1].time;
   m_evOk[i]      = true;
   if(m_dryRun)
      PrintFormat("[AMS] 指数の層：（観察モード）%s 判定に使った最後の日足 %s 始 %.1f 高 %.1f 安 %.1f 終 %.1f、持つルール：%s、目標の割合 %.4f、1日の値動きの見積もり %.4f%%、VIX の倍率 %.2f",
                  sym, TimeToString(rt[got - 1].time, TIME_DATE), rt[got - 1].open, rt[got - 1].high, rt[got - 1].low, rt[got - 1].close,
                  StateText(i), m_evFrac[i], dailyVol * 100.0, vmult);
   return(true);
  }

//+------------------------------------------------------------------+
//| 新しい日足が始まった銘柄を処理する（銘柄ごとに切り捨てる形）：            |
//| 判定のあと、目標のロットに合わせる                                    |
//+------------------------------------------------------------------+
bool CIndexSleeves::Process(const int i, const datetime t0)
  {
   if(!Evaluate(i, t0))
      return(false);
   const string sym      = m_sym[i];
   const bool   changed  = m_evChanged[i] || m_retryChanged[i];
   string       note     = m_evNote[i];
   m_tradeFail = false;
   const string vixNote  = m_evVix[i];
   const double dailyVol = m_dvol[i];
   const double annVol   = m_evAnnVol[i];
   const double equity   = SizingEquity();
   double tgt = equity * m_evFrac[i];
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
   if(changed || note != "" || m_dryRun)
      PrintFormat("[AMS] 指数の層：%s%s → 持つルール：%s、目標 %.2f lot（額 %.0f、値動きの見積もり 年 %.1f%%%s）", sym, note, StateText(i), tl, tgt,
                  annVol * 100.0, vixNote == "" ? "" : "、" + vixNote);
   if(m_dryRun)
      PrintFormat("[AMS] 指数の層：（観察モード）%s %s までの日足で判定：有効証拠金 %.0f、目標の割合 %.4f、切り捨てる前の目標 %.4f lot、1 lot の額 %.0f、1日の値動きの見積もり %.4f%%、前提の監視 %s、今の建玉 %.2f lot",
                  sym, TimeToString(m_evLast[i], TIME_DATE), equity, m_evFrac[i], want, npl, dailyVol * 100.0,
                  (m_regDays > 0 && m_regVal[i] != EMPTY_VALUE) ? StringFormat("%+.4f", m_regVal[i]) : "なし", cur);
   //--- 注文・決済・逆指値の変更に失敗したときは、この日足を「処理済み」にせず、30秒後からやり直す（最大 120 回 = 約1時間）。
   //    取引時間の境目・接続の切れ目・業者の側の一時的な拒否で、その日の売買が抜けるのを防ぐ。
   if(m_tradeFail)
     {
      m_tradeFail = false;
      if(m_retryCount[i] == 0)
         m_retryBars++;
      m_retryCount[i]++;
      if(m_retryCount[i] <= 120)
        {
         m_retryChanged[i] = changed;
         m_retryAt[i] = TimeCurrent() + 30;
         return(false);
        }
      m_retryGiveUp++;
      PrintFormat("[AMS] 指数の層：%s 売買のやり直しが上限（120回）に達したため、この日足ではあきらめます", sym);
     }
   m_retryCount[i]   = 0;
   m_retryChanged[i] = false;
   return(true);
  }

//+------------------------------------------------------------------+
//| 目標のロット tl に合わせて売買する（まとめて丸める形で使う）              |
//+------------------------------------------------------------------+
void CIndexSleeves::TradeTo(const int i, const double tl, const bool changed, const double equity, string &note)
  {
   const string sym      = m_sym[i];
   const double dailyVol = m_dvol[i];
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
         if(!m_dryRun && m_maxMarginPct > 0.0 && OrderCalcMargin(ORDER_TYPE_BUY, sym, add, SymbolInfoDouble(sym, SYMBOL_ASK), need) && need > 0.0)
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
  }

//+------------------------------------------------------------------+
//| まとめて丸める形：判定の済んだ銘柄の目標を、まとめてロットに直して売買する  |
//|  1 上限（建玉の合計・強制ロスカットを避ける上限）は、同じ割合で縮める       |
//|  2 ルールが出ている戻りの銘柄を、「目標とのずれの分散」が最小になるように    |
//|    1刻みずつ動かして丸める（全体の値動きは、目標の (1 + ε) 倍まで）         |
//+------------------------------------------------------------------+
void CIndexSleeves::ExecuteJoint(void)
  {
   const double equity = SizingEquity();
   const double kk = (m_slVolMul > 0.0) ? m_slVolMul : 4.0;
   const double so = (AccountInfoInteger(ACCOUNT_MARGIN_SO_MODE) == ACCOUNT_STOPOUT_MODE_PERCENT) ? AccountInfoDouble(ACCOUNT_MARGIN_SO_SO) / 100.0 : 1.0;
   double npl[], mrate[], tgt[], xs[], tl[], need1[];
   bool   pend[];
   ArrayResize(npl, m_n);
   ArrayResize(mrate, m_n);
   ArrayResize(tgt, m_n);
   ArrayResize(xs, m_n);
   ArrayResize(tl, m_n);
   ArrayResize(need1, m_n);
   ArrayResize(pend, m_n);
   bool anyChanged = false;
   int  nPend = 0;
   for(int i = 0; i < m_n; i++)
     {
      npl[i] = NotionalPerLot(m_sym[i]);
      double mg = 0.0;
      mrate[i] = (npl[i] > 0.0 && OrderCalcMargin(ORDER_TYPE_BUY, m_sym[i], 1.0, SymbolInfoDouble(m_sym[i], SYMBOL_ASK), mg) && mg > 0.0) ? mg / npl[i] : 0.1;
      need1[i] = kk * m_dvol[i] + so * mrate[i];             // 建玉の額1あたりの、上限の計算での重さ
      const datetime t0 = iTime(m_sym[i], PERIOD_D1, 0);
      pend[i] = (m_evOk[i] && t0 > 0 && m_evalBar[i] == t0 && t0 != m_lastBar[i] && npl[i] > 0.0);
      if(pend[i])
        {
         tgt[i] = equity * m_evFrac[i];
         nPend++;
         if(m_evChanged[i])
            anyChanged = true;
        }
      else
         tgt[i] = m_tgtLots[i] * npl[i];                     // 今回は判定していない銘柄：そのまま
     }
   if(nPend == 0)
      return;
   //--- 上限：判定した銘柄を、同じ割合で縮める
   double fixedN = 0.0, pendN = 0.0, fixedNeed = 0.0, pendNeed = 0.0;
   for(int i = 0; i < m_n; i++)
     {
      if(pend[i])
        {
         pendN += tgt[i];
         pendNeed += tgt[i] * need1[i];
        }
      else
        {
         fixedN += tgt[i];
         fixedNeed += tgt[i] * need1[i];
        }
     }
   double scale = 1.0;
   string capNote = "";
   if(m_maxLev > 0.0 && pendN > 0.0 && fixedN + pendN > m_maxLev * equity)
     {
      scale = MathMin(scale, MathMax(0.0, (m_maxLev * equity - fixedN) / pendN));
      capNote += " （建玉の合計の上限のため縮小）";
     }
   if(m_soGuard > 0.0 && pendNeed > 0.0 && fixedNeed + pendNeed > m_soGuard * equity)
     {
      scale = MathMin(scale, MathMax(0.0, (m_soGuard * equity - fixedNeed) / pendNeed));
      capNote += " （強制ロスカットを避ける上限のため縮小）";
      m_soCut++;
     }
   int act[];
   int na = 0;
   for(int i = 0; i < m_n; i++)
     {
      if(pend[i])
        {
         tgt[i] *= scale;
         m_target[i] = tgt[i];
         xs[i] = tgt[i] / npl[i];
         tl[i] = NormalizeLots(m_sym[i], xs[i]);
         if(m_rev[i] && xs[i] > 0.0)
           {
            ArrayResize(act, na + 1);
            act[na++] = i;
           }
        }
      else
        {
         xs[i] = m_tgtLots[i];
         tl[i] = m_tgtLots[i];
        }
     }
   //--- まとめて丸める
   if(na >= 1)
     {
      //--- 値動きの相関（直近60日の日足。そろわなければ 0.9 とみなす）
      double rets[];
      ArrayResize(rets, na * 60);
      datetime tref[60];
      bool okc = true;
      for(int a = 0; a < na && okc; a++)
        {
         MqlRates rr[];
         ArraySetAsSeries(rr, false);
         if(CopyRates(m_sym[act[a]], PERIOD_D1, 1, 61, rr) != 61)
           {
            okc = false;
            break;
           }
         for(int q = 0; q < 60; q++)
           {
            rets[a * 60 + q] = (rr[q].close > 0.0) ? rr[q + 1].close / rr[q].close - 1.0 : 0.0;
            if(a == 0)
               tref[q] = rr[q + 1].time;
            else if(rr[q + 1].time != tref[q])
               okc = false;
           }
        }
      double S[];
      ArrayResize(S, na * na);
      for(int a = 0; a < na; a++)
        {
         for(int b = 0; b < na; b++)
           {
            double c = (a == b) ? 1.0 : 0.9;
            if(okc && a != b)
              {
               double ma = 0.0, mb = 0.0, saa = 0.0, sbb = 0.0, sab = 0.0;
               for(int q = 0; q < 60; q++)
                 {
                  ma += rets[a * 60 + q];
                  mb += rets[b * 60 + q];
                 }
               ma /= 60.0;
               mb /= 60.0;
               for(int q = 0; q < 60; q++)
                 {
                  const double da = rets[a * 60 + q] - ma, db = rets[b * 60 + q] - mb;
                  saa += da * da;
                  sbb += db * db;
                  sab += da * db;
                 }
               if(saa > 0.0 && sbb > 0.0)
                  c = sab / MathSqrt(saa * sbb);
              }
            S[a * na + b] = m_dvol[act[a]] * m_dvol[act[b]] * c;
           }
        }
      double x[], nt[], e[], nv[];
      ArrayResize(x, na);
      ArrayResize(nt, na);
      ArrayResize(e, na);
      ArrayResize(nv, na);
      double riskT = 0.0;
      for(int a = 0; a < na; a++)
        {
         x[a]  = tl[act[a]];
         nt[a] = xs[act[a]] * npl[act[a]];
        }
      for(int a = 0; a < na; a++)
         for(int b = 0; b < na; b++)
            riskT += nt[a] * nt[b] * S[a * na + b];
      riskT = MathSqrt(MathMax(riskT, 0.0));
      //--- 戻りの銘柄以外・判定していない銘柄の分（上限の確認に使う）
      double otherN = 0.0, otherNeed = 0.0;
      for(int i = 0; i < m_n; i++)
        {
         bool isAct = false;
         for(int a = 0; a < na; a++)
            if(act[a] == i)
               isAct = true;
         if(!isAct)
           {
            otherN += tl[i] * npl[i];
            otherNeed += tl[i] * npl[i] * need1[i];
           }
        }
      double best = 0.0;
      for(int a = 0; a < na; a++)
         e[a] = x[a] * npl[act[a]] - nt[a];
      for(int a = 0; a < na; a++)
         for(int b = 0; b < na; b++)
            best += e[a] * e[b] * S[a * na + b];
      bool up = false;
      for(int iter = 0; iter < 400; iter++)
        {
         int    bestA = -1;
         double bestX = 0.0, bestTE = best;
         for(int a = 0; a < na; a++)
           {
            const double mn = SymbolInfoDouble(m_sym[act[a]], SYMBOL_VOLUME_MIN);
            const double st = SymbolInfoDouble(m_sym[act[a]], SYMBOL_VOLUME_STEP);
            if(st <= 0.0)
               continue;
            for(int dirn = 1; dirn >= -1; dirn -= 2)
              {
               double y = x[a];
               if(dirn > 0)
                  y = (x[a] < mn - 1e-9) ? mn : x[a] + st;
               else
                 {
                  if(x[a] <= 0.0)
                     continue;
                  y = (x[a] - st < mn - 1e-9) ? 0.0 : x[a] - st;
                 }
               const double keep = x[a];
               x[a] = y;
               bool okMove = true;
               if(dirn > 0)
                 {
                  //--- 全体の値動きが、目標の (1 + ε) 倍を超えない／上限を超えない
                  double rk = 0.0, totN = otherN, totNeed = otherNeed;
                  for(int q = 0; q < na; q++)
                    {
                     nv[q] = x[q] * npl[act[q]];
                     totN += nv[q];
                     totNeed += nv[q] * need1[act[q]];
                    }
                  for(int q = 0; q < na; q++)
                     for(int w = 0; w < na; w++)
                        rk += nv[q] * nv[w] * S[q * na + w];
                  if(MathSqrt(MathMax(rk, 0.0)) > (1.0 + m_jointEps) * riskT + 1e-9)
                     okMove = false;
                  if(m_maxLev > 0.0 && totN > m_maxLev * equity)
                     okMove = false;
                  if(m_soGuard > 0.0 && totNeed > m_soGuard * equity)
                     okMove = false;
                 }
               if(okMove)
                 {
                  double te = 0.0;
                  for(int q = 0; q < na; q++)
                     e[q] = x[q] * npl[act[q]] - nt[q];
                  for(int q = 0; q < na; q++)
                     for(int w = 0; w < na; w++)
                        te += e[q] * e[w] * S[q * na + w];
                  if(te < bestTE - 1e-9)
                    {
                     bestTE = te;
                     bestA  = a;
                     bestX  = y;
                    }
                 }
               x[a] = keep;
              }
           }
         if(bestA < 0)
            break;
         x[bestA] = bestX;
         best = bestTE;
        }
      for(int a = 0; a < na; a++)
        {
         const double v = NormalizeLots(m_sym[act[a]], x[a]);
         if(v > tl[act[a]] + 1e-9)
            up = true;
         tl[act[a]] = v;
        }
      if(up)
         m_jointUp++;
     }
   //--- 売買
   for(int i = 0; i < m_n; i++)
     {
      if(!pend[i])
         continue;
      const string sym  = m_sym[i];
      const double base = NormalizeLots(sym, xs[i]);
      string note = m_evNote[i] + capNote;
      if(MathAbs(tl[i] - base) > 1e-9)
         note += StringFormat(" （まとめて丸め：目標 %.3f lot → %.2f lot。切り捨てなら %.2f lot）", xs[i], tl[i], base);
      else if(xs[i] > 0.0 && tl[i] <= 0.0)
         note += StringFormat(" （目標 %.3f lot が最小の取引単位 %.2f lot に届かないため、持たない）", xs[i], SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN));
      m_tgtLots[i] = tl[i];
      m_tradeFail = false;
      TradeTo(i, tl[i], anyChanged || m_retryChanged[i], equity, note);
      if(m_evChanged[i] || note != "" || m_dryRun)
         PrintFormat("[AMS] 指数の層：%s%s → 持つルール：%s、目標 %.2f lot（額 %.0f、値動きの見積もり 年 %.1f%%%s）", sym, note, StateText(i), tl[i], tgt[i],
                     m_evAnnVol[i] * 100.0, m_evVix[i] == "" ? "" : "、" + m_evVix[i]);
      if(m_dryRun)
         PrintFormat("[AMS] 指数の層：（観察モード）%s %s までの日足で判定：有効証拠金 %.0f、目標の割合 %.4f、切り捨てる前の目標 %.4f lot、1 lot の額 %.0f、1日の値動きの見積もり %.4f%%、前提の監視 %s",
                     sym, TimeToString(m_evLast[i], TIME_DATE), equity, m_evFrac[i], xs[i], npl[i], m_dvol[i] * 100.0,
                     (m_regDays > 0 && m_regVal[i] != EMPTY_VALUE) ? StringFormat("%+.4f", m_regVal[i]) : "なし");
      if(m_tradeFail && m_retryCount[i] < 120)
        {
         //--- 失敗：この銘柄は「処理済み」にせず、30秒後からやり直す
         if(m_retryCount[i] == 0)
            m_retryBars++;
         m_retryCount[i]++;
         m_retryChanged[i] = (anyChanged || m_retryChanged[i]);
         m_jointRetryAt = TimeCurrent() + 30;
         m_tradeFail = false;
         continue;
        }
      if(m_tradeFail)
         m_retryGiveUp++;
      m_tradeFail = false;
      m_retryCount[i]   = 0;
      m_retryChanged[i] = false;
      m_lastBar[i] = m_evalBar[i];
     }
  }

//+------------------------------------------------------------------+
//| 毎ティック：新しい日足が始まった銘柄を処理する                          |
//+------------------------------------------------------------------+
void CIndexSleeves::OnTick(void)
  {
   const datetime now = TimeCurrent();
   bool saved = false;
   int  waiting = 0, pending = 0;
   //--- 検証用：決めた間隔で、EA の起動し直しを再現する
   if(m_testRestartSec > 0 && (long)now - (long)m_testRestartAt >= m_testRestartSec)
     {
      if(m_testRestartAt > 0)
         SimulateRestart();
      m_testRestartAt = now;
     }
   if(!m_riskRestored)
      RestoreRisk();
   ExportDaily();
   for(int i = 0; i < m_n; i++)
     {
      if(m_flatMin > 0)
         FlatBeforeRollover(i, now);
      const datetime t0 = iTime(m_sym[i], PERIOD_D1, 0);
      if(t0 <= 0 || t0 == m_lastBar[i])
         continue;
      if(m_joint && m_evOk[i] && m_evalBar[i] == t0)
        {
         pending++;                                   // 判定は済んでいて、まとめての売買を待っている
         continue;
        }
      waiting++;
      if(m_seenBar[i] != t0)
        {
         m_seenBar[i] = t0;
         m_seenAt[i]  = now;
        }
      if((long)now - (long)m_seenAt[i] < m_delaySec)
         continue;
      if(now < m_retryAt[i])
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
      if(!m_joint)
        {
         if(!Process(i, t0))
            continue;
         m_lastBar[i] = t0;
         saved = true;
         waiting--;
        }
      else
        {
         if(!Evaluate(i, t0))
            continue;
         m_evalBar[i] = t0;
         waiting--;
         pending++;
         if(m_firstEval == 0)
            m_firstEval = now;
        }
     }
   //--- まとめて丸める形：すべての銘柄の判定がそろったら（そろわなくても、最初の判定から2分たったら）売買する
   if(m_joint && pending > 0 && now >= m_jointRetryAt && (waiting == 0 || (long)now - (long)m_firstEval >= 120))
     {
      ExecuteJoint();
      m_firstEval = 0;
      saved = true;
     }
   if(saved)
     {
      //--- 観察モード：値段と日足が届いたあとの条件を、もう一度だけログに出す（起動直後は届いていないことがある）
      if(m_dryRun && !m_obsDone)
        {
         m_obsDone = true;
         ObserveLog();
         if(!MQLInfoInteger(MQL_TESTER))
            for(int i = 0; i < m_n; i++)
               ObserveHistory(i, 30);
        }
      SaveState();
     }
  }

#endif // AMS_INDEXSLEEVES_MQH

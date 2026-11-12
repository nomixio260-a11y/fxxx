//+------------------------------------------------------------------+
//|                                          AMS_ImportHistData.mq5  |
//|  1分足CSV（YYYY.MM.DD,HH:MM,O,H,L,C,V）をカスタム銘柄に取り込む。     |
//|  ブローカーに接続できない環境でバックテストするためのもの。              |
//|  CSV は MQL5\Files に置く（tools/backtest_custom.sh が自動でコピー）。 |
//+------------------------------------------------------------------+
#property copyright "fxxx"
#property version   "1.00"
#property script_show_inputs false

input string InpFile        = "USDJPY_M1.csv";  // 取り込むCSV（MQL5\Files）
input string InpSymbol      = "USDJPY_HD";      // 作るカスタム銘柄名
input string InpOrigin      = "USDJPY";         // 仕様をコピーする元の銘柄（無ければ手動設定）
input int    InpSpreadPts   = 4;                // 固定スプレッド（point。USDJPYは 4 = 0.4pips）

//+------------------------------------------------------------------+
bool SetupSymbol(void)
  {
   if(SymbolInfoInteger(InpSymbol, SYMBOL_CUSTOM))
     {
      SymbolSelect(InpSymbol, false);
      CustomRatesDelete(InpSymbol, 0, LONG_MAX);
      CustomTicksDelete(InpSymbol, 0, LONG_MAX);
     }
   else
     {
      bool ok = false;
      if(SymbolInfoInteger(InpOrigin, SYMBOL_DIGITS) > 0)
         ok = CustomSymbolCreate(InpSymbol, "AMS", InpOrigin);
      if(!ok && !CustomSymbolCreate(InpSymbol, "AMS"))
        {
         PrintFormat("[AMS-Import] カスタム銘柄の作成に失敗 err=%d", GetLastError());
         return(false);
        }
     }

   //--- USDJPY の仕様（元銘柄が無い場合でも同じになるよう明示的に設定）
   CustomSymbolSetString(InpSymbol, SYMBOL_CURRENCY_BASE, "USD");
   CustomSymbolSetString(InpSymbol, SYMBOL_CURRENCY_PROFIT, "JPY");
   CustomSymbolSetString(InpSymbol, SYMBOL_CURRENCY_MARGIN, "USD");
   CustomSymbolSetString(InpSymbol, SYMBOL_DESCRIPTION, "USDJPY (histdata.com M1)");
   CustomSymbolSetInteger(InpSymbol, SYMBOL_DIGITS, 3);
   CustomSymbolSetDouble(InpSymbol, SYMBOL_POINT, 0.001);
   CustomSymbolSetDouble(InpSymbol, SYMBOL_TRADE_TICK_SIZE, 0.001);
   CustomSymbolSetDouble(InpSymbol, SYMBOL_TRADE_CONTRACT_SIZE, 100000.0);
   CustomSymbolSetInteger(InpSymbol, SYMBOL_TRADE_CALC_MODE, SYMBOL_CALC_MODE_FOREX);
   CustomSymbolSetInteger(InpSymbol, SYMBOL_TRADE_MODE, SYMBOL_TRADE_MODE_FULL);
   CustomSymbolSetInteger(InpSymbol, SYMBOL_TRADE_EXEMODE, SYMBOL_TRADE_EXECUTION_MARKET);
   CustomSymbolSetInteger(InpSymbol, SYMBOL_FILLING_MODE, SYMBOL_FILLING_FOK | SYMBOL_FILLING_IOC);
   CustomSymbolSetInteger(InpSymbol, SYMBOL_ORDER_MODE, 127);
   CustomSymbolSetDouble(InpSymbol, SYMBOL_VOLUME_MIN, 0.01);
   CustomSymbolSetDouble(InpSymbol, SYMBOL_VOLUME_MAX, 100.0);
   CustomSymbolSetDouble(InpSymbol, SYMBOL_VOLUME_STEP, 0.01);
   CustomSymbolSetInteger(InpSymbol, SYMBOL_SPREAD_FLOAT, false);
   CustomSymbolSetInteger(InpSymbol, SYMBOL_SPREAD, InpSpreadPts);
   CustomSymbolSetInteger(InpSymbol, SYMBOL_TRADE_STOPS_LEVEL, 0);
   CustomSymbolSetInteger(InpSymbol, SYMBOL_TRADE_FREEZE_LEVEL, 0);
   CustomSymbolSetInteger(InpSymbol, SYMBOL_SWAP_MODE, SYMBOL_SWAP_MODE_DISABLED);
   CustomSymbolSetDouble(InpSymbol, SYMBOL_MARGIN_INITIAL, 0.0);

   //--- 月〜金は終日取引可能
   for(int d = MONDAY; d <= FRIDAY; d++)
     {
      CustomSymbolSetSessionQuote(InpSymbol, (ENUM_DAY_OF_WEEK)d, 0, 0, 86400);
      CustomSymbolSetSessionTrade(InpSymbol, (ENUM_DAY_OF_WEEK)d, 0, 0, 86400);
     }
   return(true);
  }

//+------------------------------------------------------------------+
void OnStart(void)
  {
   if(!SetupSymbol())
      return;

   const int fh = FileOpen(InpFile, FILE_READ | FILE_CSV | FILE_ANSI, ',');
   if(fh == INVALID_HANDLE)
     {
      PrintFormat("[AMS-Import] %s を開けません err=%d", InpFile, GetLastError());
      return;
     }

   const int BATCH = 50000;
   MqlRates rates[];
   ArrayResize(rates, BATCH);
   int  n = 0;
   long total = 0;
   datetime first = 0, last = 0;

   while(!FileIsEnding(fh) && !IsStopped())
     {
      const string d = FileReadString(fh);
      const string t = FileReadString(fh);
      const double o = StringToDouble(FileReadString(fh));
      const double h = StringToDouble(FileReadString(fh));
      const double l = StringToDouble(FileReadString(fh));
      const double c = StringToDouble(FileReadString(fh));
      const long   v = StringToInteger(FileReadString(fh));
      if(d == "" || o <= 0.0)
         continue;

      MqlRates r;
      r.time        = StringToTime(d + " " + t);
      r.open        = o;
      r.high        = h;
      r.low         = l;
      r.close       = c;
      r.tick_volume = (v > 0) ? v : 1;
      r.spread      = InpSpreadPts;
      r.real_volume = 0;
      rates[n++] = r;
      if(first == 0)
         first = r.time;
      last = r.time;

      if(n == BATCH)
        {
         if(CustomRatesUpdate(InpSymbol, rates, n) < 0)
            PrintFormat("[AMS-Import] CustomRatesUpdate 失敗 err=%d", GetLastError());
         total += n;
         n = 0;
        }
     }
   FileClose(fh);
   if(n > 0)
     {
      ArrayResize(rates, n);
      if(CustomRatesUpdate(InpSymbol, rates, n) < 0)
         PrintFormat("[AMS-Import] CustomRatesUpdate 失敗 err=%d", GetLastError());
      total += n;
     }
   SymbolSelect(InpSymbol, true);
   PrintFormat("[AMS-Import] 完了: %s に %I64d 本（%s 〜 %s）", InpSymbol, total,
               TimeToString(first), TimeToString(last));
  }
//+------------------------------------------------------------------+

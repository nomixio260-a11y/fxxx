//+------------------------------------------------------------------+
//|                                                   AMS/Common.mqh |
//|  Adaptive Multi-Strategy EA - 共通の定義とユーティリティ               |
//+------------------------------------------------------------------+
#ifndef AMS_COMMON_MQH
#define AMS_COMMON_MQH

//--- 相場状況（レジーム）
enum ENUM_AMS_REGIME
  {
   REGIME_NEUTRAL = 0,   // 中立
   REGIME_TREND   = 1,   // 強いトレンド
   REGIME_RANGE   = 2,   // レンジ
   REGIME_HIGHVOL = 3    // 高ボラティリティ
  };

//--- 高ボラティリティ時の扱い
enum ENUM_AMS_HIGHVOL_MODE
  {
   HIGHVOL_BLOCK = 0,    // 新規エントリーを停止
   HIGHVOL_HALF  = 1     // ロット半分（中立の重みで判定）
  };

//--- 売買ロジック
#define AMS_STRATEGY_COUNT 4
enum ENUM_AMS_STRATEGY
  {
   STRAT_TREND    = 0,   // トレンドフォロー
   STRAT_BREAKOUT = 1,   // ブレイクアウト
   STRAT_MEANREV  = 2,   // 逆張り
   STRAT_MOMENTUM = 3    // モメンタム
  };

//+------------------------------------------------------------------+
string RegimeShortName(const ENUM_AMS_REGIME regime)
  {
   switch(regime)
     {
      case REGIME_TREND:   return("TREND");
      case REGIME_RANGE:   return("RANGE");
      case REGIME_HIGHVOL: return("HVOL");
      default:             return("NEUT");
     }
  }

//+------------------------------------------------------------------+
string StrategyShortName(const int strategy)
  {
   switch(strategy)
     {
      case STRAT_TREND:    return("TF");
      case STRAT_BREAKOUT: return("BO");
      case STRAT_MEANREV:  return("MR");
      case STRAT_MOMENTUM: return("MO");
      default:             return("--");
     }
  }

//+------------------------------------------------------------------+
//| 1pipの価格幅（3桁/5桁業者は point*10）                              |
//+------------------------------------------------------------------+
double PipSize(const string symbol)
  {
   const int    digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   const double point  = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(digits == 3 || digits == 5)
      return(point * 10.0);
   return(point);
  }

//+------------------------------------------------------------------+
//| 価格をティックサイズに丸める                                          |
//+------------------------------------------------------------------+
double NormalizePrice(const string symbol, const double price)
  {
   const double tick   = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   const int    digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(tick <= 0.0)
      return(NormalizeDouble(price, digits));
   return(NormalizeDouble(MathRound(price / tick) * tick, digits));
  }

//+------------------------------------------------------------------+
//| value 以下の要素の割合（0.0〜1.0）                                   |
//+------------------------------------------------------------------+
double PercentRank(const double &values[], const int count, const double value)
  {
   if(count <= 0)
      return(0.5);
   int below = 0;
   for(int i = 0; i < count; i++)
      if(values[i] <= value)
         below++;
   return((double)below / (double)count);
  }

#endif // AMS_COMMON_MQH
//+------------------------------------------------------------------+

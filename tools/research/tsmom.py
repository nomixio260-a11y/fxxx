#!/usr/bin/env python3
"""時系列モメンタム（Moskowitz, Ooi & Pedersen 2012）を日足で確かめる。過去 L か月の値動きの向きに1か月保有し、ボラティリティで大きさをそろえる。
使い方: python3 tools/research/tsmom.py"""
import sys, numpy as np, pandas as pd
sys.path.insert(0,'tools/research'); import data as D
# 時系列モメンタム（Moskowitz, Ooi & Pedersen 2012）：過去 L か月の値動きの向きに1か月保有。ボラティリティで大きさをそろえる。
res=[]
for L in (1,3,6,12):
  for per,(a,b) in (("設計",D.DESIGN),("検証",D.VALID)):
    rets=[]
    for p in D.PAIRS:
      d=D.bars(p,"1D") if False else None
      h=D.bars(p,"1h")
      c=h["c"].resample("1D").last().dropna()
      m=c.resample("ME").last()
      r=np.log(m).diff()
      vol=np.log(c).diff().rolling(60).std().resample("ME").last()*np.sqrt(21)
      sig=np.sign(np.log(m).diff(L)).shift(1)
      pnl=(sig*r/vol.shift(1)*0.1/np.sqrt(12)*np.sqrt(12)).loc[a:b].dropna()  # 月のボラ ~10%/年 目安に揃える
      rets.append(pnl.rename(p))
    P=pd.concat(rets,axis=1).mean(axis=1)
    sr=P.mean()/P.std()*np.sqrt(12)
    res.append((L,per,len(P),P.mean()*100,sr))
for x in res: print(f"L={x[0]:>2}か月 {x[1]} {x[2]}か月 月平均{x[3]:+.2f}% 年シャープ{x[4]:+.2f}")

#!/usr/bin/env python3
"""探索で見つかった候補を、+0.5 pips のコスト上乗せと年ごとの成績で確かめる。使い方: python3 tools/research/candidates_check.py"""
import sys, numpy as np, pandas as pd
sys.path.insert(0,'tools/research')
import data as D, seasonality as S
def trades(pair, clock, hh, mm, hold, d, dow=None):
    df=D.bars(pair,'5min'); pip=D.pip_size(pair); cost=S.COST[pair]
    t=df.index[(df[f'{clock}_h'].values==hh)&(df[f'{clock}_m'].values==mm)]
    if dow is not None:
        t=t[pd.DatetimeIndex(df.loc[t,f'{clock}_date']).dayofweek==dow]
    o=df['o']; e=o.reindex(t).values; x=o.reindex(t+pd.Timedelta(minutes=hold)).values
    r=pd.Series(d*(x-e)/pip-cost,index=t).dropna()
    return r
def rep(name,r):
    print('==',name,'n=',len(r))
    for lab,p in (('設計',D.DESIGN),('検証',D.VALID),('最終',D.FINAL)):
        x=r[D.period_mask(r.index,p)]
        for c in (0,0.5):
            y=x-c; gp=y[y>0].sum(); gl=-y[y<0].sum()
            print(f'  {lab} +{c}: n={len(y)} mean={y.mean():+.2f} PF={gp/gl:.2f} t={y.mean()/y.std()*np.sqrt(len(y)):.1f}')
    yr=r.groupby(r.index.year).agg(['count','mean'])
    print('  年別', ' '.join(f"{y}:{m:+.1f}" for y,m in zip(yr.index,yr['mean'])))
rep('A EURUSD LDN11:00 120 売り 毎日',trades('EURUSD','ldn',11,0,120,-1))
rep('A2 EURUSD LDN11:00 120 売り 月-金 個別 (水)',trades('EURUSD','ldn',11,0,120,-1,2))
rep('B AUDJPY NY13:30 120 買い 火',trades('AUDJPY','ny',13,30,120,1,1))
rep('B2 AUDJPY NY13:30 120 買い 全日',trades('AUDJPY','ny',13,30,120,1))
rep('B3 EURJPY NY13:30 120 買い 火',trades('EURJPY','ny',13,30,120,1,1))

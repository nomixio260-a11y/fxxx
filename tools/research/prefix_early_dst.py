#!/usr/bin/env python3
"""prefix_early.py の補足：夏時間・冬時間（日付の変わり目に入るかどうか）で分けて確かめる。"""
import sys; sys.path.insert(0,'tools/research')
import numpy as np, pandas as pd, data as D, seasonality as S
from prefix_early import PERIODS, st
for pair in ("USDJPY","EURJPY"):
    df=D.bars(pair,"5min"); pip,cost=D.pip_size(pair),S.COST[pair]; o=df["o"]
    fix=df.index[(df["tky_h"].values==9)&(df["tky_m"].values==55)]
    fix=fix[S.gotobi_mask(pd.DatetimeIndex(df.loc[fix,"tky_date"]))]
    for hh,mm in ((7,0),(7,30),(8,0)):
        back=pd.Timedelta(minutes=(9*60+55)-(hh*60+mm))
        ent=fix-back
        r=pd.Series((o.reindex(fix).values-o.reindex(ent).values)/pip-cost,index=fix).dropna()
        nyh=df["ny_h"].reindex(r.index-back).values
        for lab,m in (("冬(NY17時台に入る)" if (hh,mm)!=(8,0) else "冬",nyh<=17),("夏",nyh>=18)):
            m=np.asarray(m)
            print(pair,f"{hh}:{mm:02d}",lab," | ".join(st(r[m & D.period_mask(r.index,p)].values) for _,p in PERIODS))

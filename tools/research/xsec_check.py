#!/usr/bin/env python3
"""xsec.py の「日付の変わり目の戻り」が、売値だけのデータの見かけ（スプレッド拡大）かどうかを確かめる。"""
import sys; sys.path.insert(0,'tools/research')
import numpy as np, pandas as pd, data as D, xsec as X
p=X.log_prices(); idx=p.index; cols=list(p.columns)
grpA=np.array([X.LEGS[c][1]==1 for c in cols])   # EUR,GBP,AUD,NZD（XXXUSD）
ny=idx.tz_localize('UTC').tz_convert('America/New_York'); nyh=ny.hour
for (h,L,H) in ((18,2,1),(18,2,2),(17,1,2),(19,2,1)):
    past=p-p.shift(L); okp=(idx-idx.to_series().shift(L)).values==np.timedelta64(L,'h')
    fut=p.shift(-H)-p; okf=(idx.to_series().shift(-H)-idx).values==np.timedelta64(H,'h')
    lo=past.values.argmin(1); hi=past.values.argmax(1); f=fut.values
    r=f[np.arange(len(f)),lo]-f[np.arange(len(f)),hi]-X.COST
    v=okp&okf&~np.isnan(r)&(nyh==h)
    same=grpA[lo]==grpA[hi]
    art=(grpA[lo])&(~grpA[hi])   # 弱いのが XXXUSD、強いのが USDXXX（スプレッドの見かけと一致）
    print(f"NY{h} L{L} H{H}: 同じ組の割合 {same[v].mean():.2f}, 見かけと一致する割合 {art[v].mean():.2f}")
    for lab,m in (('全体',v),('同じ組だけ',v&same),('見かけと一致',v&art),('見かけと逆',v&grpA[hi]&~grpA[lo])):
        cells=[]
        for pn,pr in X.PERIODS:
            s=X.st(r[m&D.period_mask(idx,pr)]); cells.append('-' if s is None else f"{s['n']}回 {s['mean']:+.1f}bp t{s['t']:.1f}")
        print('   ',lab,' | '.join(cells))

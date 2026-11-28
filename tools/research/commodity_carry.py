#!/usr/bin/env python3
"""研究：急落と無関係な、新しい利益の出どころ ― 原油・天然ガスの「期近と期先の差（キャリー）」（107章）。日付・時刻は使わない。

- ねらい：指数の戻りの層の弱点（急落での負け）は、層の中の工夫では消せなかった（106・107章）。残る道は、急落と無関係に利益が出る層を足すこと。
- 文献（105章の調査）：先物の期近が期先より高い（逆ざや）商品を買い、安い（順ざや）商品を売る方法は、シャープ 0.4〜0.75（Koijen ほか 2018、
  Bhardwaj ほか 2015）。持ち続けるだけで、期先が期近の値段に近づく分（ロール）が損益になる。
- OANDA の商品CFDでは、この差がスワップとして毎日受け払いされる（105章：確認した日は、米国産原油の買いが年 +6.7%・売りが −11.7%。
  真ん中の +9.2% が期近と期先の差、±2.5% が業者の取り分）。EA は、その日のスワップを口座から直接読めるので、外のデータなしで判定できる。
- データ：米国エネルギー情報局（EIA）が公表している、先物の期近から4番目までの日々の終値（原油 WTI 1983年〜、天然ガス 1994年〜。2024年4月まで）。
  損益は「2番目の限月を持ち、期近が消える日に、次の2番目に乗り換える」計算（期近の最後の数日の異常な値動き＝2020年4月のマイナス価格などを避ける）。
- 形（結果を見る前に決めた。これ以外は試さない）：
   CC1 キャリーだけ：年率に直した差（12 × ln(期近 ÷ 2番目)）が +2.5% より大きければ買い、−2.5% より小さければ売り、あいだは持たない
        （2.5% は業者の取り分。スワップが受け取りになる向きだけ持つ、ということ）
   CC2 キャリーと流れがそろったときだけ：CC1 の買いは 終値が200日の平均より上のときだけ、売りは 下のときだけ
  どちらも7日ごとに見直し。建玉は、その商品の値動き（過去60日）が口座の年10%になる大きさ。
  コスト：業者の取り分 年2.5%（買い・売りとも）、スプレッド（原油 0.06%、天然ガス 0.2%。往復）。
- 判定（結果を見る前に決めた）。新しい層として採用の候補にするのは、同じ形が次をすべて満たすときだけ：
   (a) 原油・天然ガスを同じ値動きで合わせた層のシャープ（コスト後）が、全期間で 0.4 以上、前半・後半ともプラス
   (b) 原油だけ・天然ガスだけでも、全期間でプラス
   (c) 指数の戻りの層との、日々の損益の相関が ±0.2 以内（2000年10月〜）
   (d) 株の急落の局面（2000年〜の11局面）の損益の合計が、マイナスでない
- 追加（上の判定のあとで決めた。実装のための確かめで、成績を見て形を選び直すものではない）：
   OANDA の CFD の値段は、乗り換えの段差がなく、水準は期近に付いていく連続の値段と分かった（下の 7）。
   EA が見られるのはこの値段なので、流れ（200日の平均）を「期近の値段そのまま」で判定する形（CC2s）でも同じ結果になるかを確かめる。
   さらに、乗り換えの日の前後の損益を数えない・業者の取り分を倍にする、という厳しめの条件でも、指数の層と合わせた効果が残るかを見る。
- 追加2（OANDA の値段の作りを確かめたあとで決めた。cfd_construction.py。結果を見る前に決めた）：
   OANDA の CFD は、期近の先物を参照し、期限の数日前に次の先物へ乗り換える（原油は約1営業日前、天然ガスは約3営業日前）。
   公式の説明どおりなら、買いの損益（値段の変化 ＋ スワップ）は「参照している先物を持った損益 − 年2.5%」になる。
   上の CC2・CC2s は「2番目の限月を持つ」計算だったので、参照どおり（期近を持ち、期限の lead 営業日前に乗り換える）の損益で計算し直す（下の 8）。
   合図は2通り。どちらも、流れ（期近の値段と200日の平均）がそろったときだけ持つ：
    S1 いまの傾き：12 × ln(期近 ÷ 2番目)（CC2s と同じ）
    S2 乗り換えの時点で決まった傾き：直前の乗り換えの時点の 12 × ln(前の先物 ÷ 乗り換えた先の先物)。次の乗り換えまで変わらない。
       OANDA のスワップは、公式の説明どおりなら、この傾きで決まる（プラスなら買いが受け取り）。
   判定は上の (a)〜(d) と同じ。lead は 原油 1・天然ガス 3（cfd_construction.py の A2 による）で判定し、どちらも 1・3・5 にした場合を感度として並べる。
   期近の値段がゼロ以下になった日（2020年4月20日）と次の日は、2番目の値動きを使う（OANDA の値段はマイナスにならず、早めに次の限月へ移っていた）。
使い方: python3 -I tools/research/commodity_carry.py [商品の口座の書き出しのフォルダ]  → reports/research/commodity_carry.md
"""
import os
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fred_data as F  # noqa: E402
import target300 as T  # noqa: E402

ANN = 252
DIR = os.path.join(F.ROOT, "data", "eia")
SERIES = {"原油（WTI）": ("pet", "RCLC", 0.0006), "天然ガス": ("ng", "RNGC", 0.002)}
MARKUP = 2.5
WINDOW = int(os.environ.get("AMS_ROLL_WINDOW", "3"))        # 乗り換えの日を探す範囲（決まりから計算した日の前後の営業日）
EP = (("2000年9月〜02年10月", "2000-09-01", "2002-10-09"), ("2007年10月〜09年3月", "2007-10-09", "2009-03-09"), ("2010年4〜7月", "2010-04-23", "2010-07-02"),
      ("2011年7〜10月", "2011-07-22", "2011-10-03"), ("2015年8月", "2015-08-17", "2015-08-25"), ("2018年1〜2月", "2018-01-26", "2018-02-08"),
      ("2018年9〜12月", "2018-09-20", "2018-12-24"), ("2020年2〜3月", "2020-02-19", "2020-03-23"), ("2022年1〜10月", "2022-01-03", "2022-10-12"))


def fetch(group, code):
    """EIA の先物の日々の終値（期近から4番目まで）。なければ取得する（公開データ。リポジトリには入れない）。"""
    os.makedirs(DIR, exist_ok=True)
    out = {}
    for k in (1, 2, 3, 4):
        path = os.path.join(DIR, f"{code}{k}.xls")
        if not os.path.exists(path) or os.path.getsize(path) < 10000:
            subprocess.run(["curl", "-sS", "-L", "-m", "120", "-A", "Mozilla/5.0", "-o", path, f"https://www.eia.gov/dnav/{group}/hist_xls/{code}{k}d.xls"], check=True)
        x = pd.read_excel(path, sheet_name="Data 1", skiprows=2)
        x.columns = ["date", "v"]
        out[k] = pd.Series(x["v"].values, index=pd.to_datetime(x["date"]))
    return pd.DataFrame(out).dropna()


def roll_days(index, kind):
    """期近の先物が消えた次の取引日（＝2番目が期近に変わる日）。取引所の決まりから計算する（値動きからは判定しない：
    限月どうしの値段の差が小さいと、ふつうの日の大きな値動きを乗り換えと取り違えるため）。
    原油（WTI）：受け渡しの月の前の月の、25日の3営業日前（25日が休みなら、その前の営業日の3営業日前）が最後の取引日。
    天然ガス：受け渡しの月の1日の、3営業日前（＝前の月の、最後から3番目の営業日）が最後の取引日。"""
    days = pd.DatetimeIndex(index)
    out = []
    months = sorted(set((t.year, t.month) for t in days))
    for y, m in months:
        mdays = days[(days.year == y) & (days.month == m)]
        if kind == "pet":
            ref = mdays[mdays.day <= 25]
            if len(ref) == 0:
                continue
            last = ref[-1]
            pos = days.get_loc(last)
            pos -= 3 if last.day == 25 else 3                    # 25日が営業日ならその3営業日前、休みなら直前の営業日の3営業日前
            if last.day != 25:
                pos = days.get_loc(last) - 3
        else:
            if len(mdays) < 4:
                continue
            pos = days.get_loc(mdays[-3])
        if 0 <= pos < len(days) - 1:
            out.append(days[pos + 1])
    return pd.DatetimeIndex(out)


def held_returns(D, kind):
    """2番目の限月を持ち続けたときの日々の値動きと、乗り換えの日。
    乗り換えの日（期近が消えた次の日）は、きのうの2番目が、きょうの期近になっている。"""
    # 決まりから計算した日は、月によって1〜2日ずれる（休日の数え方・決まりの変更）。ずれたままだと、限月どうしの値段の差が損益に紛れ込む。
    # 正しい日は、次の性質で見分ける：乗り換えの日は「きのうの k+1 番目 → きょうの k 番目」と見ると、3つの限月がほぼ同じ率で動く（平行に動く）。
    # ふつうの日にそう見ると、限月どうしの差（月によって大きさが違う）が混ざって、3つの動きがばらばらになる。
    # 見るのは「3つの動きのばらつき」だけで、その日の値動きの向きや大きさには左右されない
    # （値動きの大きさで判定すると、逆ざやの下げの日・順ざやの上げの日を乗り換えと取り違えて、キャリーの方法に有利な誤りになる。最初の計算で実際に起きた）。
    lg = np.log(D.where(D > 0))
    as_roll = pd.concat([lg[k] - lg[k + 1].shift(1) for k in (1, 2, 3)], axis=1).std(axis=1)
    as_same = pd.concat([lg[k] - lg[k].shift(1) for k in (1, 2, 3)], axis=1).std(axis=1)
    score = as_same - as_roll                                 # 大きいほど「乗り換えの日らしい」
    days = D.index
    chosen = []
    for t in roll_days(days, kind):
        pos = days.get_loc(t)
        cand = days[max(pos - WINDOW, 1):min(pos + WINDOW + 1, len(days))]
        e = score.reindex(cand).dropna()
        chosen.append(e.idxmax() if len(e) and e.max() > 0 else t)
    is_roll = pd.Series(D.index.isin(pd.DatetimeIndex(chosen)), index=D.index)
    r = (D[2] / D[2].shift(1) - 1.0).where(~is_roll, D[1] / D[2].shift(1) - 1.0)
    return r, is_roll


def simulate(D, spread, form, kind, unit=0.10, check=7, drop=0, markup=MARKUP, rule_only=False):
    """form：CC1（キャリーだけ）・CC2（キャリーと流れ。流れは乗り換え込みの値段）・CC2s（流れは期近の値段そのまま＝CFD の値段に近い）・TREND（流れだけ。買いと売り）。
    drop：乗り換えの日の前後 drop−1 営業日の損益を数えない（1 なら乗り換えの日だけ）。rule_only：乗り換えの日を、決まりから計算した日のままにする。"""
    r, is_roll = held_returns(D, kind)
    if rule_only:
        is_roll = pd.Series(D.index.isin(roll_days(D.index, kind)), index=D.index)
        r = (D[2] / D[2].shift(1) - 1.0).where(~is_roll, D[1] / D[2].shift(1) - 1.0)
    if drop:
        skip = np.zeros(len(D), dtype=bool)
        for p in np.flatnonzero(is_roll.values):
            skip[max(p - (drop - 1), 0):p + drop] = True
        r = r.where(~skip, 0.0)
    carry = 12.0 * np.log((D[1] / D[2]).where((D[1] > 0) & (D[2] > 0))) * 100.0          # 年 %
    spot = D[1].where(D[1] > 0).ffill()
    c2 = spot if form in ("CC2s", "TREND") else (1 + r.fillna(0.0)).cumprod()           # 流れの判定に使う値段
    sma = c2.rolling(200).mean()
    raw = pd.Series(0.0, index=D.index)
    if form == "TREND":
        raw[c2 > sma] = 1.0
        raw[c2 < sma] = -1.0
    else:
        raw[carry > MARKUP] = 1.0
        raw[carry < -MARKUP] = -1.0
    if form in ("CC2", "CC2s"):
        raw = raw.where(~((raw > 0) & (c2 < sma)) & ~((raw < 0) & (c2 > sma)), 0.0)
    raw = raw.where(sma.notna() & carry.notna())
    st = np.full(len(D), np.nan)
    last, cur = None, np.nan
    for i, t in enumerate(D.index):
        if np.isnan(raw.iloc[i]):
            continue
        if last is None or (t - last).days >= check:
            cur, last = raw.iloc[i], t
        st[i] = cur
    st = pd.Series(st, index=D.index)
    sd = spot.pct_change().rolling(60).std() if form in ("CC2s", "TREND") else r.rolling(60).std()
    w = (st * unit / np.maximum(sd * np.sqrt(ANN), 0.05)).shift(1).fillna(0.0)          # 前の日に決めた建玉
    days = pd.Series(D.index, index=D.index).diff().dt.days.fillna(1.0)
    cost = (w - w.shift(1).fillna(0.0)).abs() * spread / 2.0 + w.abs() * markup / 100.0 / 360.0 * days
    return (w * r.fillna(0.0) - cost), st, carry


def active_returns(D, kind, lead):
    """OANDA の CFD が参照している先物を持ったときの日々の値動き：期近を持ち、期限の lead 営業日前の終値で2番目に乗り換える。
    戻り値：日々の値動き、乗り換えた先を持ちはじめる日（前の日の終値で乗り換え）。"""
    _, is_roll = held_returns(D, kind)
    r1 = D[1] / D[1].shift(1) - 1.0
    r2 = D[2] / D[2].shift(1) - 1.0
    use2 = np.zeros(len(D), dtype=bool)
    sw = np.zeros(len(D), dtype=bool)
    for p in np.flatnonzero(is_roll.values):
        s_ = max(p - lead, 1)
        use2[s_:p] = True
        sw[s_] = True
    bad = ((D[1] <= 0) | (D[1].shift(1) <= 0)).values           # 期近がゼロ以下の日と次の日
    r = r1.where(~(use2 | bad), r2)
    r = r.where(~is_roll.values, D[1] / D[2].shift(1) - 1.0)
    return r, pd.Series(sw, index=D.index)


def simulate_active(D, spread, kind, signal, lead, unit=0.10, check=7, markup=MARKUP):
    """OANDA の作りどおりの損益（参照している先物の値動き − 業者の取り分 − スプレッド）。signal：S1（いまの傾き）・S2（乗り換えの時点で決まった傾き）。"""
    r, sw = active_returns(D, kind, lead)
    ok = (D[1] > 0) & (D[2] > 0)
    cur = 12.0 * np.log((D[1] / D[2]).where(ok)) * 100.0
    if signal == "S1":
        carry = cur
    else:
        carry = cur.shift(1).where(sw.values).ffill()             # 乗り換えの直前の終値での傾きを、次の乗り換えまで使う
    spot = D[1].where(D[1] > 0).ffill()
    sma = spot.rolling(200).mean()
    raw = pd.Series(0.0, index=D.index)
    raw[(carry > MARKUP) & (spot > sma)] = 1.0
    raw[(carry < -MARKUP) & (spot < sma)] = -1.0
    raw = raw.where(sma.notna() & carry.notna())
    st = np.full(len(D), np.nan)
    last, c_ = None, np.nan
    for i, t in enumerate(D.index):
        if np.isnan(raw.iloc[i]):
            continue
        if last is None or (t - last).days >= check:
            c_, last = raw.iloc[i], t
        st[i] = c_
    st = pd.Series(st, index=D.index)
    sd = spot.pct_change().rolling(60).std()
    w = (st * unit / np.maximum(sd * np.sqrt(ANN), 0.05)).shift(1).fillna(0.0)
    days = pd.Series(D.index, index=D.index).diff().dt.days.fillna(1.0)
    cost = (w - w.shift(1).fillna(0.0)).abs() * spread / 2.0 + w.abs() * markup / 100.0 / 360.0 * days
    return (w * r.fillna(0.0) - cost), st, carry


def sh(x):
    return x.mean() / x.std() * np.sqrt(ANN) if len(x) > 200 and x.std() > 0 else np.nan


def mdd(x):
    e = (1 + x).cumprod()
    return (e / e.cummax() - 1).min()


def main():
    lines = ["# 研究：原油・天然ガスのキャリー（`tools/research/commodity_carry.py`）", "",
             "EIA が公表している先物の日々の終値（期近〜4番目）。建玉は、その商品の値動きが口座の年10%になる大きさ。コスト（業者の取り分 年2.5%・スプレッド）込み。", "",
             "## 1 商品ごと・形ごと", "",
             "| 商品（期間） | 形 | シャープ | 前半 | 後半 | 年率 | 最大の下落 | 買いの日・売りの日・持たない日 | 2009年〜 | 2017年〜 |", "|---|---|---|---|---|---|---|---|---|---|"]
    R = {}
    for name, (group, code, spread) in SERIES.items():
        D = fetch(group, code)
        for form in ("CC1", "CC2"):
            r, st, carry = simulate(D, spread, form, group)
            r = r.iloc[260:]
            st2 = st.iloc[260:]
            mid = r.index[len(r) // 2]
            R[(name, form)] = r
            lines.append(f"| {name}（{r.index[0].date()}〜{r.index[-1].date()}） | {form} | {sh(r):+.2f} | {sh(r[r.index <= mid]):+.2f} | {sh(r[r.index > mid]):+.2f} | {r.mean() * ANN * 100:+.1f}% | {mdd(r) * 100:.0f}% | "
                         f"{(st2 > 0).mean() * 100:.0f}%・{(st2 < 0).mean() * 100:.0f}%・{(st2 == 0).mean() * 100:.0f}% | {sh(r[r.index >= '2009-01-01']):+.2f} | {sh(r[r.index >= '2017-01-01']):+.2f} |")
            print(lines[-1], flush=True)
        buy = (D[2] / D[2].shift(1) - 1.0)
        lines.append(f"| {name} | （参考）買い持ち | {sh(held_returns(D, group)[0].iloc[260:].dropna()):+.2f} | | | | | キャリーの平均 年 {carry.mean():+.1f}%（プラスの日 {(carry > 0).mean() * 100:.0f}%） | | |")
        print(lines[-1], flush=True)
    # ---------- 2つを合わせた層と、指数の戻りの層との関係
    idx = T.cash_returns(5.0)
    lines += ["", "## 2 原油と天然ガスを合わせた層（同じ値動きで半分ずつ。1994年〜）と、指数の戻りの層との関係", "",
              "| 形 | シャープ | 前半 | 後半 | 最大の下落 | 指数の戻りの層との相関（日々・2000年10月〜） | 株の急落の局面の損益の合計 | 指数の層 ＋ この層（値動き 1：0.5）：シャープ（指数だけ） | 最大の下落（指数だけ） |", "|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for form in ("CC1", "CC2"):
        z = pd.concat([R[("原油（WTI）", form)], R[("天然ガス", form)]], axis=1, sort=True).dropna()
        c = z.mean(axis=1)
        mid = c.index[len(c) // 2]
        both = pd.concat([idx, c], axis=1, sort=True)
        both.columns = ["i", "c"]
        rho = both.dropna().corr().iloc[0, 1]
        both = both[(both.index >= max(idx.index[0], c.index[0])) & (both.index <= min(idx.index[-1], c.index[-1]))].fillna(0.0)   # どちらかのデータがない日も落とさない
        ep = sum(float(c[(c.index > a) & (c.index <= b)].sum()) for _, a, b in EP)
        k = 0.5 * both["i"].std() / both["c"].std()
        mix = both["i"] + k * both["c"]
        res[form] = dict(sh=sh(c), a=sh(c[c.index <= mid]), b=sh(c[c.index > mid]), rho=rho, ep=ep,
                         each=(sh(R[("原油（WTI）", form)]), sh(R[("天然ガス", form)])))
        lines.append(f"| {form} | {sh(c):+.2f} | {res[form]['a']:+.2f} | {res[form]['b']:+.2f} | {mdd(c) * 100:.0f}% | {rho:+.2f} | {ep * 100:+.1f}% | "
                     f"{sh(mix):+.2f}（{sh(both['i']):+.2f}） | {mdd(mix) * 100:.0f}%（{mdd(both['i']) * 100:.0f}%） |")
        print(lines[-1], flush=True)
    lines += ["", "## 3 株の急落の局面ごとの損益（合わせた層。値動き 年10% の大きさ。%）", "", "| 局面 | CC1 | CC2 | （参考）指数の戻りの層（ルール1つ分 5%） |", "|---|---|---|---|"]
    for lab, a, b in EP:
        cells = []
        for form in ("CC1", "CC2"):
            z = pd.concat([R[("原油（WTI）", form)], R[("天然ガス", form)]], axis=1, sort=True).dropna().mean(axis=1)
            cells.append(f"{float(z[(z.index > a) & (z.index <= b)].sum()) * 100:+.1f}")
        lines.append(f"| {lab} | {cells[0]} | {cells[1]} | {float(idx[(idx.index > a) & (idx.index <= b)].sum()) * 100:+.1f} |")
    lines += ["", "## 4 判定（事前に決めた基準）", "", "| 形 | (a) シャープ 0.4 以上・前半後半ともプラス | (b) 原油・天然ガスとも単独でプラス | (c) 相関 ±0.2 以内 | (d) 急落の局面の合計がマイナスでない | 判定 |", "|---|---|---|---|---|---|"]
    for form in ("CC1", "CC2"):
        x = res[form]
        a = x["sh"] >= 0.4 and x["a"] > 0 and x["b"] > 0
        b = x["each"][0] > 0 and x["each"][1] > 0
        c = abs(x["rho"]) <= 0.2
        d = x["ep"] >= 0
        lines.append(f"| {form} | {'○' if a else '×'}（{x['sh']:+.2f}、{x['a']:+.2f}／{x['b']:+.2f}） | {'○' if b else '×'}（{x['each'][0]:+.2f}・{x['each'][1]:+.2f}） | {'○' if c else '×'}（{x['rho']:+.2f}） | "
                     f"{'○' if d else '×'}（{x['ep'] * 100:+.1f}%） | {'**候補**' if (a and b and c and d) else '不合格'} |")
        print(lines[-1], flush=True)
    # ---------- 実装できる形（CC2s）と、厳しめの条件
    import index_trend_combo as ITC
    idx2 = idx.add(ITC.trend_returns("NASDAQ100", 10.0), fill_value=0.0)                 # 指数の口座（戻り 5% ＋ 順張り 10%）
    EP2 = tuple((lab, max(a, "2001-01-01"), b) for lab, a, b in EP)

    def pack(**kw):
        rs = []
        for name, (group, code, spread) in SERIES.items():
            rr, _, _ = simulate(fetch(group, code), spread, kw.pop("form", "CC2s") if False else kw.get("form", "CC2s"), group, **{k: v for k, v in kw.items() if k != "form"})
            rs.append(rr.iloc[260:])
        c = pd.concat(rs, axis=1, sort=True).dropna().mean(axis=1)
        return rs, c

    def joined(c):
        """指数の口座とエネルギーの層を、同じ日付に並べる。EIA のデータには抜けている日がある（2001〜11年に約390日）ので、
        どちらかがない日は損益 0 として残す（落とすと、指数の口座のその日の損益が消えて、年ごとの成績が変わってしまう）。"""
        z = pd.concat([idx2, c], axis=1, sort=True)
        z.columns = ["i", "c"]
        return z[(z.index >= "2001-01-01") & (z.index <= c.index[-1])].fillna(0.0)

    def st20(r):
        e = (1 + r).cumprod()
        y = (1 + r).groupby(r.index.year).prod() - 1
        return dict(cagr=e.iloc[-1] ** (365.25 / (r.index[-1] - r.index[0]).days) - 1, sh=sh(r), dd=(e / e.cummax() - 1).min(), wy=y.min(),
                    ep=[float(np.prod(1 + r[(r.index > a) & (r.index <= b)]) - 1) for _, a, b in EP2])
    lines += ["", "## 5 実装できる形（CC2s：流れを、CFD の値段に近い「期近の値段そのまま」で判定）と、厳しめの条件", "",
              "右の4列は、指数の口座（戻り 5% ＋ 順張り 10%。現物の写し、2001年〜2024年4月）と同じ資金に対して、この層を「原油・天然ガスそれぞれ 値動き 年10%」（EA の設定 InpCrUnitVol=10 に当たる。層の合計の値動きは年10%ほど）で足し、最大の下落が指数だけのときと同じになるように全体を縮めた場合。", "",
              "| 条件 | 原油 | 天然ガス | 合わせて | 前半／後半 | 急落の局面でプラス | 足しただけ（縮めない）：年率・最大の下落（指数だけ） | 同じ最大の下落に縮めた：年率（指数だけ） | 急落の9局面の損益の合計（指数だけ） | 最悪の年（指数だけ） | シャープ（指数だけ） |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    keep = {}
    for lab, kw in (("CC2（流れ：乗り換え込みの値段）", dict(form="CC2")), ("**CC2s（流れ：期近の値段そのまま）**", dict(form="CC2s")),
                    ("CC2s・乗り換えの日の損益を数えない", dict(form="CC2s", drop=1)), ("CC2s・その前後1日も数えない（月に3日）", dict(form="CC2s", drop=2)),
                    ("CC2s・その前後2日も数えない（月に5日）", dict(form="CC2s", drop=3)), ("CC2s・乗り換えの日＝決まりから計算した日のまま", dict(form="CC2s", rule_only=True)),
                    ("CC2s・業者の取り分 年5%・乗り換えの日を数えない", dict(form="CC2s", drop=1, markup=5.0)), ("（参考）流れだけ・買いと売り", dict(form="TREND")), ("（参考）キャリーだけ", dict(form="CC1"))):
        rs, c = pack(**kw)
        mid = c.index[len(c) // 2]
        z = joined(c)
        b0 = st20(z["i"])
        mix = z["i"] + 2.0 * z["c"]
        s1 = st20(mix)
        s2 = st20(mix * (b0["dd"] / s1["dd"]))
        epc = [float(c[(c.index > a) & (c.index <= b)].sum()) for _, a, b in EP2]
        keep[lab] = (z, b0, s2)
        lines.append(f"| {lab} | {sh(rs[0]):+.2f} | {sh(rs[1]):+.2f} | {sh(c):+.2f} | {sh(c[c.index <= mid]):+.2f}／{sh(c[c.index > mid]):+.2f} | {sum(x > 0 for x in epc)} / 9 | "
                     f"{s1['cagr'] * 100:+.1f}%・{s1['dd'] * 100:.1f}%（{b0['cagr'] * 100:+.1f}%・{b0['dd'] * 100:.1f}%） | "
                     f"{s2['cagr'] * 100:+.1f}%（{b0['cagr'] * 100:+.1f}%） | {sum(s2['ep']) * 100:+.0f}%（{sum(b0['ep']) * 100:+.0f}%） | {s2['wy'] * 100:+.1f}%（{b0['wy'] * 100:+.1f}%） | {sh(mix):+.2f}（{sh(z['i']):+.2f}） |")
        print(lines[-1], flush=True)
    z, b0, _ = keep["**CC2s（流れ：期近の値段そのまま）**"]
    lines += ["", "## 6 株の急落の局面ごと：指数の口座だけ → エネルギーの層（CC2s、原油・天然ガスそれぞれ 年10%）を足した場合（同じ資金に対する損益。縮めていない）", "",
              "| 局面 | 指数の口座だけ | エネルギーの層だけ | 合わせて |", "|---|---|---|---|"]
    for lab, a, b in EP2:
        f = lambda r: float(np.prod(1 + r[(r.index > a) & (r.index <= b)]) - 1) * 100       # noqa: E731
        lines.append(f"| {lab} | {f(z['i']):+.1f}% | {f(2.0 * z['c']):+.1f}% | {f(z['i'] + 2.0 * z['c']):+.1f}% |")
    y = (1 + z["c"]).groupby(z.index.year).prod() - 1
    yi = (1 + z["i"]).groupby(z.index.year).prod() - 1
    ym = (1 + z["i"] + 2.0 * z["c"]).groupby(z.index.year).prod() - 1
    lines += ["", "- エネルギーの層（CC2s、原油・天然ガスそれぞれ 年5% の大きさ＝上の半分）の年ごとの損益（%）：" + " ".join(f"{str(k)[2:]}年 {v * 100:+.0f}" for k, v in y.items()),
              "- 年ごと（%）：指数の口座だけ → エネルギーの層（各10%）を足した場合：" + " ".join(f"{str(k)[2:]}年 {yi[k] * 100:+.0f}→{ym[k] * 100:+.0f}" for k in yi.index),
              f"- 指数の口座との、日々の損益の相関：{z[(z['i'] != 0) & (z['c'] != 0)].corr().iloc[0, 1]:+.2f}（{z.index[0].date()}〜{z.index[-1].date()}）。"]
    # ---------- OANDA の CFD の値段の作り（書き出しのフォルダがあるとき）
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    if folder and os.path.isdir(folder):
        lines += ["", "## 7 OANDA の CFD の値段は、先物のどれに当たるか（2006年〜2024年4月の日足）", "",
                  "| 銘柄 | 日々の値動きの相関：期近をそのまま | 2番目をそのまま | 乗り換え込み（2番目を持って乗り換え） | 乗り換えの日の平均：OANDA | 期近をそのまま（段差を含む） | 乗り換え込み | 値段の水準：OANDA ÷ 期近（中央値） | 全期間の値動き（対数の合計）：OANDA | 期近をそのまま | 乗り換え込み |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for sym, key in (("USOIL", "原油（WTI）"), ("NATGAS", "天然ガス")):
            group, code, _ = SERIES[key]
            D = fetch(group, code)
            f = os.path.join(folder, f"AMS_d1_{sym}.csv")
            if not os.path.exists(f):
                continue
            o = pd.read_csv(f)
            o.index = pd.to_datetime(o["date"], format="%Y.%m.%d")
            o = o[o.index.dayofweek < 5]["close"].astype(float)
            r, is_roll = held_returns(D, group)
            zz = pd.concat([o.pct_change(), D[1].pct_change(), D[2].pct_change(), r, is_roll], axis=1, sort=True).dropna()
            zz.columns = ["o", "c1", "c2", "ro", "roll"]
            zz = zz[zz.index >= "2006-01-01"]
            rd = zz[zz["roll"] == True]                                              # noqa: E712
            lv = pd.concat([o, D[1]], axis=1, sort=True).dropna()
            lv = lv[lv.index >= "2006-01-01"]
            lines.append(f"| {sym} | {zz['o'].corr(zz['c1']):.2f} | {zz['o'].corr(zz['c2']):.2f} | {zz['o'].corr(zz['ro']):.2f} | {rd['o'].mean() * 100:+.2f}% | {rd['c1'].mean() * 100:+.2f}% | {rd['ro'].mean() * 100:+.2f}% | "
                         f"{np.median(lv.iloc[:, 0] / lv.iloc[:, 1]):.3f} | {np.log1p(zz['o']).sum():+.2f} | {np.log1p(zz['c1']).sum():+.2f} | {np.log1p(zz['ro']).sum():+.2f} |")
            print(lines[-1], flush=True)
        lines += ["", "- OANDA の値段は、乗り換えの日に段差がなく（乗り換え込みの値動きと同じ）、長い目の水準は期近に付いていく。",
                  "  作りの詳しい確かめは `cfd_construction.py`：期近の先物を参照し、期限の数日前に次の先物へ乗り換える。乗り換えで値段は飛ばさず、次の期限までに先物の値段へ近づけていく。",
                  "  公式の説明では、この「近づく値動き」をスワップで打ち消すので、買いの損益（値段の変化 ＋ スワップ）は、参照している先物を持った損益 − 業者の取り分 に当たる。"]
    # ---------- OANDA の作りどおりの損益（参照している先物＝期近を持つ）で計算し直す
    lines += ["", "## 8 OANDA の作りどおりの損益で計算し直す（期近を持ち、期限の lead 営業日前に乗り換える。業者の取り分 年2.5%・スプレッド込み）", "",
              "右の列は 5 と同じ：指数の口座（戻り 5% ＋ 順張り 10%）と同じ資金に、原油・天然ガスそれぞれ 年10% で足した場合。", "",
              "| 合図 | lead（原油・天然ガス） | 原油 | 天然ガス | 合わせて | 前半／後半 | 2009年〜 | 2017年〜 | 最大の下落（合わせた層・年10%） | 指数の戻りの層との相関 | 急落の局面の合計（合わせた層） | 急落の局面でプラス | "
              "足しただけ：年率・最大の下落（指数だけ） | 同じ最大の下落に縮めた：年率（指数だけ） | 急落の9局面の合計（指数だけ） | 最悪の年（指数だけ） | シャープ（指数だけ） |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    verdict = {}
    for signal in ("S1", "S2"):
        for la, lb in ((1, 3), (1, 1), (3, 3), (5, 5)):
            rs = []
            for (name, (group, code, spread)), lead in zip(SERIES.items(), (la, lb)):
                rr, _, _ = simulate_active(fetch(group, code), spread, group, signal, lead)
                rs.append(rr.iloc[260:])
            c = pd.concat(rs, axis=1, sort=True).dropna().mean(axis=1)
            mid = c.index[len(c) // 2]
            both = pd.concat([idx, c], axis=1, sort=True).dropna()
            rho = both.corr().iloc[0, 1]
            epc = [float(c[(c.index > a) & (c.index <= b)].sum()) for _, a, b in EP]
            z = joined(c)
            b0 = st20(z["i"])
            mix = z["i"] + 2.0 * z["c"]
            s1 = st20(mix)
            s2 = st20(mix * (b0["dd"] / s1["dd"]))
            if (la, lb) == (1, 3):
                verdict[signal] = dict(sh=sh(c), a=sh(c[c.index <= mid]), b=sh(c[c.index > mid]), each=(sh(rs[0]), sh(rs[1])), rho=rho, ep=sum(epc))
            lines.append(f"| {signal} | {la}・{lb}{'（判定に使う）' if (la, lb) == (1, 3) else ''} | {sh(rs[0]):+.2f} | {sh(rs[1]):+.2f} | {sh(c):+.2f} | {sh(c[c.index <= mid]):+.2f}／{sh(c[c.index > mid]):+.2f} | "
                         f"{sh(c[c.index >= '2009-01-01']):+.2f} | {sh(c[c.index >= '2017-01-01']):+.2f} | {mdd(c) * 100:.0f}% | {rho:+.2f} | {sum(epc) * 100:+.1f}% | {sum(x > 0 for x in epc)} / 9 | "
                         f"{s1['cagr'] * 100:+.1f}%・{s1['dd'] * 100:.1f}%（{b0['cagr'] * 100:+.1f}%・{b0['dd'] * 100:.1f}%） | {s2['cagr'] * 100:+.1f}%（{b0['cagr'] * 100:+.1f}%） | "
                         f"{sum(s2['ep']) * 100:+.0f}%（{sum(b0['ep']) * 100:+.0f}%） | {s2['wy'] * 100:+.1f}%（{b0['wy'] * 100:+.1f}%） | {sh(mix):+.2f}（{sh(z['i']):+.2f}） |")
            print(lines[-1], flush=True)
    lines += ["", "判定（1〜4 と同じ基準。lead は 原油 1・天然ガス 3）：", "",
              "| 合図 | (a) シャープ 0.4 以上・前半後半ともプラス | (b) 原油・天然ガスとも単独でプラス | (c) 相関 ±0.2 以内 | (d) 急落の局面の合計がマイナスでない | 判定 |", "|---|---|---|---|---|---|"]
    for signal, x in verdict.items():
        a = x["sh"] >= 0.4 and x["a"] > 0 and x["b"] > 0
        b = x["each"][0] > 0 and x["each"][1] > 0
        c_ok = abs(x["rho"]) <= 0.2
        d = x["ep"] >= 0
        lines.append(f"| {signal} | {'○' if a else '×'}（{x['sh']:+.2f}、{x['a']:+.2f}／{x['b']:+.2f}） | {'○' if b else '×'}（{x['each'][0]:+.2f}・{x['each'][1]:+.2f}） | {'○' if c_ok else '×'}（{x['rho']:+.2f}） | "
                     f"{'○' if d else '×'}（{x['ep'] * 100:+.1f}%） | {'**候補**' if (a and b and c_ok and d) else '不合格'} |")
        print(lines[-1], flush=True)
    out = os.path.join(F.ROOT, "reports", "research", "commodity_carry.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

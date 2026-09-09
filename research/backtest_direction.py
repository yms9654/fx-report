"""USD/KRW 워크포워드 백테스트. 랜덤워크를 이기는 모델이 있는지 실제로 잰다.

규칙: 셔플 금지, 미래 정보 금지, 표준화는 학습구간에서만 적합,
      재학습은 분기마다 확장 윈도우로.
"""
import json, math, pathlib, warnings
import numpy as np
warnings.filterwarnings("ignore")
from sklearn.linear_model import Ridge
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

rows = json.loads(pathlib.Path("long.json").read_text())
d = sorted(rows)
px = np.array([rows[k] for k in d], float)
lp = np.log(px)
r = np.diff(lp, prepend=lp[0])                      # 일간 로그수익률

def sma(a, n):
    c = np.cumsum(np.insert(a, 0, 0)); out = np.full(len(a), np.nan)
    out[n-1:] = (c[n:] - c[:-n]) / n; return out

def rsi(a, n=14):
    dd = np.diff(a, prepend=a[0]); g = np.where(dd > 0, dd, 0); l = np.where(dd < 0, -dd, 0)
    out = np.full(len(a), np.nan); ag = g[1:n+1].mean(); al = l[1:n+1].mean()
    for i in range(n+1, len(a)):
        ag = (ag*(n-1)+g[i])/n; al = (al*(n-1)+l[i])/n
        out[i] = 100.0 if al == 0 else 100-100/(1+ag/al)
    return out

def rvol(a, n):
    out = np.full(len(a), np.nan)
    for i in range(n, len(a)): out[i] = a[i-n+1:i+1].std()
    return out

ma5, ma20, ma60 = sma(px,5), sma(px,20), sma(px,60)
F = np.column_stack([
    r, np.roll(r,1), np.roll(r,2), np.roll(r,3), np.roll(r,4),          # 지연 수익률 5
    np.log(px/ma5), np.log(px/ma20), np.log(px/ma60),                    # 이평 이격
    np.log(ma5/ma20), np.log(ma20/ma60),                                 # 이평 배열
    (rsi(px)-50)/50,                                                     # 모멘텀
    rvol(r,5), rvol(r,20), rvol(r,60),                                   # 실현변동성
    sma(r,5), sma(r,20),                                                 # 평균 수익률
])
NAMES = ["r1","r2","r3","r4","r5","px/ma5","px/ma20","px/ma60","ma5/ma20",
         "ma20/ma60","rsi","vol5","vol20","vol60","mr5","mr20"]

def run(H):
    y = np.full(len(px), np.nan)
    y[:-H] = lp[H:] - lp[:-H]                                            # 향후 H일 로그수익률
    ok = ~np.isnan(F).any(1) & ~np.isnan(y)
    idx = np.where(ok)[0]
    split = int(len(idx)*0.6)
    models = {
        "Ridge":  lambda: Ridge(alpha=3.0),
        "GBM":    lambda: GradientBoostingRegressor(n_estimators=120, max_depth=3,
                                                    learning_rate=0.03, subsample=0.8, random_state=0),
        "MLP":    lambda: MLPRegressor(hidden_layer_sizes=(64,32), alpha=1e-2, max_iter=600,
                                       early_stopping=True, random_state=0),
    }
    preds = {k: [] for k in models}; acts = []
    fitted = {}; last_fit = -10**9
    for j in range(split, len(idx)):
        i = idx[j]
        if j - last_fit >= 63:                                           # 분기마다 재학습
            tr = idx[:j]
            sc = StandardScaler().fit(F[tr])
            for k, mk in models.items():
                m = mk(); m.fit(sc.transform(F[tr]), y[tr]); fitted[k] = (m, sc)
            last_fit = j
        for k, (m, sc) in fitted.items():
            preds[k].append(float(m.predict(sc.transform(F[i:i+1]))[0]))
        acts.append(y[i])
    a = np.array(acts)
    base = np.sqrt((a**2).mean())                                        # 랜덤워크 = 0 예측
    out = {"n": len(a), "base_rmse": base}
    for k in models:
        p = np.array(preds[k])
        rmse = np.sqrt(((p-a)**2).mean())
        dir_ok = ((np.sign(p) == np.sign(a)) & (a != 0)).sum() / max((a != 0).sum(), 1)
        se = 0.5/math.sqrt(max((a != 0).sum(),1))
        out[k] = {"rmse": rmse, "ratio": rmse/base, "dir": dir_ok,
                  "z": (dir_ok-0.5)/se, "pnl": float(np.sum(np.sign(p)*a))}
    return out

print(f"데이터 {len(px)}영업일  {d[0]} ~ {d[-1]}\n")
for H, lab in [(1,"1일"), (5,"1주"), (20,"4주")]:
    o = run(H)
    print(f"━━ {lab} 앞 예측  (테스트 {o['n']}개, 워크포워드) ━━")
    print(f"  {'모델':8}{'RMSE':>10}{'RW대비':>9}{'방향적중':>10}{'z':>7}   판정")
    print(f"  {'랜덤워크':8}{o['base_rmse']:>10.5f}{1.0:>9.3f}{'—':>10}{'—':>7}   기준")
    for k in ["Ridge","GBM","MLP"]:
        m = o[k]
        v = "이김" if m["ratio"] < 0.999 and m["z"] > 1.96 else \
            "차이없음" if abs(m["z"]) <= 1.96 else "졌음"
        print(f"  {k:8}{m['rmse']:>10.5f}{m['ratio']:>9.3f}{m['dir']*100:>9.1f}%{m['z']:>7.2f}   {v}")
    print()

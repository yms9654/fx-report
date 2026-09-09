import json,math,pathlib,warnings; import numpy as np; warnings.filterwarnings("ignore")
import torch, torch.nn as nn
torch.manual_seed(0); np.random.seed(0)
rows=json.loads(pathlib.Path("long.json").read_text()); d=sorted(rows)
px=np.array([rows[k] for k in d],float); lp=np.log(px); r=np.diff(lp,prepend=lp[0])
def sma(a,n):
    c=np.cumsum(np.insert(a,0,0)); o=np.full(len(a),np.nan); o[n-1:]=(c[n:]-c[:-n])/n; return o
def rvol(a,n):
    o=np.full(len(a),np.nan)
    for i in range(n,len(a)): o[i]=a[i-n+1:i+1].std()
    return o
SEQ=40
feat=np.column_stack([r, np.log(px/sma(px,5)), np.log(px/sma(px,20)),
                      np.log(px/sma(px,60)), rvol(r,5), rvol(r,20)])
class Net(nn.Module):
    def __init__(s,nf,h=48,cell=nn.LSTM):
        super().__init__(); s.rnn=cell(nf,h,batch_first=True); s.fc=nn.Linear(h,1)
    def forward(s,x): o,_=s.rnn(x); return s.fc(o[:,-1]).squeeze(-1)

def build(target,H):
    X,Y=[],[]
    for i in range(SEQ,len(px)-H):
        w=feat[i-SEQ:i]
        if np.isnan(w).any(): continue
        t=target(i,H)
        if t is None or np.isnan(t): continue
        X.append(w); Y.append(t)
    return np.array(X,np.float32), np.array(Y,np.float32)

def train_eval(target,H,label,baseline):
    X,Y=build(target,H)
    n=len(X); a,b=int(n*.6),int(n*.75)
    mu,sd=X[:a].reshape(-1,X.shape[2]).mean(0),X[:a].reshape(-1,X.shape[2]).std(0)+1e-9
    Xs=(X-mu)/sd
    ym,ys=Y[:a].mean(),Y[:a].std()+1e-9
    tr=(torch.tensor(Xs[:a]),torch.tensor((Y[:a]-ym)/ys))
    va=(torch.tensor(Xs[a:b]),torch.tensor((Y[a:b]-ym)/ys))
    te_x,te_y=torch.tensor(Xs[b:]),Y[b:]
    best=(1e9,None)
    m=Net(X.shape[2]); opt=torch.optim.Adam(m.parameters(),1e-3); lf=nn.MSELoss()
    for ep in range(60):
        m.train()
        perm=torch.randperm(len(tr[0]))
        for k in range(0,len(perm),128):
            j=perm[k:k+128]; opt.zero_grad(); l=lf(m(tr[0][j]),tr[1][j]); l.backward(); opt.step()
        m.eval()
        with torch.no_grad(): vl=lf(m(va[0]),va[1]).item()
        if vl<best[0]: best=(vl,{k:v.clone() for k,v in m.state_dict().items()})
    m.load_state_dict(best[1]); m.eval()
    with torch.no_grad(): p=m(te_x).numpy()*ys+ym
    bl=baseline(b,H,len(te_y))
    rm=lambda q: float(np.sqrt(((q-te_y)**2).mean()))
    print(f"  {label:22} 테스트 {len(te_y):4}개   LSTM RMSE {rm(p):.5f}   "
          f"기준선 {rm(bl):.5f}   비율 {rm(p)/rm(bl):.3f}  "
          f"{'이김' if rm(p)<rm(bl) else '못이김'}")
    return p,te_y,bl

print(f"데이터 {len(px)}영업일  {d[0]} ~ {d[-1]}   LSTM 48유닛 · 시퀀스 {SEQ}일\n")
print("━━ ① 방향/수익률 예측 (기준선: 랜덤워크 = 0) ━━")
for H in (1,5,20):
    p,y,_=train_eval(lambda i,H: lp[i+H]-lp[i], H, f"향후 {H}일 수익률",
                     lambda b,H,n: np.zeros(n,np.float32))
    dok=((np.sign(p)==np.sign(y))&(y!=0)).sum()/max((y!=0).sum(),1)
    nn_=(y!=0).sum(); z=(dok-0.5)/(0.5/math.sqrt(nn_))
    print(f"  {'':22} 방향적중 {dok*100:.1f}%  z={z:.2f}  "
          f"{'유의' if abs(z)>1.96 else '유의하지 않음'}")
print("\n━━ ② 변동성 예측 (기준선: 직전 20일 실현변동성 그대로) ━━")
idx_v=[]
def vol_t(i,H):
    v=r[i:i+H].std() if i+H<=len(r) else None
    return v
def vol_base(b,H,n):
    out=[]
    k=0
    for i in range(SEQ,len(px)-H):
        w=feat[i-SEQ:i]
        if np.isnan(w).any(): continue
        t=vol_t(i,H)
        if t is None or np.isnan(t): continue
        out.append(rvol(r,20)[i]); k+=1
    return np.array(out[-n:],np.float32)
train_eval(vol_t,20,"향후 20일 변동성",vol_base)

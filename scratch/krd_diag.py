"""Conditioning of the zero->par map, zero-sum vs par-PV01, and the seasoned-swap failure mode."""
import os, datetime, time
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import numpy as np, pandas as pd, rateslib as rl
from Caching.curve_store import CurveStore
pd.set_option("display.width", 240)

store = CurveStore.default()
DAY = datetime.date(2026, 6, 15)
raw = store.read_raw_nodes("USD-SOFR-1D-CITIVELOEXCELMIN", start=DAY, end=DAY)
row = raw.iloc[len(raw)//2].to_dict()
curve = CurveStore.reconstruct_curve(row)
REF = curve.nodes.initial
CALN = curve.meta.calendar
CAL = rl.get_calendar(CALN)
SPOT = CAL.lag_bus_days(REF, 2, True)
ND = list(curve.nodes.nodes)
NDF = np.array([float(curve.nodes.nodes[d]) for d in ND])
NDAYS = np.array([(pd.Timestamp(d)-pd.Timestamp(REF)).days for d in ND], float)
LN = np.log(NDF)
def dff(d): return np.exp(np.interp(d, NDAYS, LN))


def build(ladder):
    Kn = len(ladder)
    ins = [rl.IRS(effective=SPOT, termination=t, spec="usd_irs", curves=curve, notional=100e6) for t in ladder]
    par = np.array([float(i.rate(curves=curve).real) for i in ins])
    pv01 = np.array([float(i.leg1.analytic_delta(disc_curve=curve).real) for i in ins])
    GRID = np.array([(pd.Timestamp(i.leg1.schedule.termination)-pd.Timestamp(REF)).days for i in ins], float)
    def g(t):
        t = np.atleast_1d(np.asarray(t, float)); W = np.zeros((t.size, Kn))
        for a, tv in enumerate(t):
            if tv <= GRID[0]: W[a,0]=1.0
            elif tv >= GRID[-1]: W[a,-1]=1.0
            else:
                j=int(np.searchsorted(GRID,tv)-1); f=(tv-GRID[j])/(GRID[j+1]-GRID[j]); W[a,j],W[a,j+1]=1-f,f
        return W*(t/365.0)[:,None]
    def krd(term, notl, fr, eff=None):
        irs = rl.IRS(effective=eff or SPOT, termination=term, spec="usd_irs", curves=curve,
                     notional=1.0, fixed_rate=1.0)
        def pull(cf, typ):
            d=pd.DataFrame(cf); d=d[d["Type"]==typ]
            f=lambda c: np.array([(pd.Timestamp(x)-pd.Timestamp(REF)).days for x in d[c]],float)
            return f("Acc Start"),f("Acc End"),f("Payment"),np.array(d["DCF"],float)
        (s1,e1,p1,d1)=pull(irs.leg1.cashflows(rate_curve=curve,disc_curve=curve),"FixedPeriod")
        (s2,e2,p2,d2)=pull(irs.leg2.cashflows(rate_curve=curve,disc_curve=curve),"FloatPeriod")
        out=((-notl*d1*(fr/100.0)*dff(p1))[:,None]*(-g(p1))).sum(axis=0)
        dfs,dfe,dfp=dff(s2),dff(e2),dff(p2); r=dfs/dfe
        out=out+((notl*r*dfp)[:,None]*(g(e2)-g(s2))+(notl*(r-1)*dfp)[:,None]*(-g(p2))).sum(axis=0)
        return out*1e-4
    J=np.zeros((Kn,Kn))
    for i,t in enumerate(ladder): J[i,:]=krd(t,100e6,float(par[i]))/pv01[i]
    return ladder, par, pv01, J, krd


GRIDS = {
 "15 (coarse)": ["3M","6M","1Y","18M","2Y","3Y","4Y","5Y","7Y","10Y","12Y","15Y","20Y","25Y","30Y"],
 "21 (mid)":    ["3M","6M","9M","1Y","18M","2Y","3Y","4Y","5Y","6Y","7Y","8Y","9Y","10Y","11Y","12Y","15Y","20Y","25Y","30Y","40Y"],
 "30 (futures-aligned)": ["1M","2M","3M","6M","9M","1Y","15M","18M","21M","2Y","30M","3Y","4Y","5Y","6Y","7Y",
                          "8Y","9Y","10Y","11Y","12Y","15Y","20Y","25Y","30Y","40Y","50Y","2W","1W","4M"],
}
GRIDS["30 (futures-aligned)"] = ["1M","2M","3M","4M","6M","9M","1Y","15M","18M","21M","2Y","30M","3Y","4Y","5Y",
                                 "6Y","7Y","8Y","9Y","10Y","11Y","12Y","15Y","20Y","25Y","30Y","40Y","50Y"]

print("===== conditioning of the zero->par Jacobian =====")
built = {}
for tag, L in GRIDS.items():
    t0 = time.perf_counter()
    lad, par, pv01, J, krd = build(L)
    t = time.perf_counter()-t0
    built[tag] = (lad, par, pv01, J, krd)
    print(f"{tag:24s} K={len(L):2d}  cond(J)={np.linalg.cond(J):8.2f}  "
          f"diag range {np.diag(J).min():.3f}-{np.diag(J).max():.3f}  build {t*1000:.0f} ms")

print("\n===== sum(zero-KRD) vs rateslib par PV01 (annuity), spot par swaps =====")
lad, par, pv01, J, krd = built["21 (mid)"]
rows = []
for i, t in enumerate(lad):
    z = krd(t, 100e6, float(par[i])).sum()
    rows.append((t, pv01[i], z, z/pv01[i]))
print(pd.DataFrame(rows, columns=["tenor","par_PV01_usd_per_bp","sum_zero_KRD","ratio"]).round(4).to_string(index=False))

print("\n===== FAILURE MODE: seasoned / past-effective swap =====")
past = pd.Timestamp(REF) - pd.Timedelta(days=200)
past = rl.dt(past.year, past.month, past.day)
try:
    irs = rl.IRS(effective=past, termination="10Y", spec="usd_irs", curves=curve,
                 notional=100e6, fixed_rate=4.0)
    cf2 = pd.DataFrame(irs.leg2.cashflows(rate_curve=curve, disc_curve=curve))
    cf2 = cf2[cf2["Type"] == "FloatPeriod"]
    lhs = np.array(cf2["Cashflow"], float)
    dfs = np.array([float(curve[pd.Timestamp(x)]) if pd.Timestamp(x) >= pd.Timestamp(REF) else np.nan
                    for x in cf2["Acc Start"]])
    dfe = np.array([float(curve[pd.Timestamp(x)]) for x in cf2["Acc End"]])
    rhs = -np.array(cf2["Notional"], float) * (dfs/dfe - 1.0)
    with np.errstate(invalid="ignore"):
        rel = np.abs((lhs-rhs)/lhs)
    print(f"effective={past.date()} (200d before curve ref).  periods={len(lhs)}")
    print(f"  first (accruing) period: rateslib cf={lhs[0]:,.2f}  telescoping cf={rhs[0]:,.2f}  "
          f"(nan means Acc Start is in the past)")
    print(f"  later periods max rel err = {np.nanmax(rel[1:]):.3e}")
    print(f"  swap NPV = {float(irs.npv(curves=curve).real):,.2f}")
except Exception as exc:
    print("  RAISED:", type(exc).__name__, exc)

print("\n===== FAILURE MODE: 50Y trade against a 30Y-capped grid =====")
lad15, par15, pv0115, J15, krd15 = built["15 (coarse)"]
a50 = krd15("50Y", 100e6, 4.2)
print(pd.DataFrame({"bucket": lad15, "zero_krd": a50}).round(1).to_string(index=False))
ins50 = rl.IRS(effective=SPOT, termination="50Y", spec="usd_irs", curves=curve, notional=100e6, fixed_rate=4.2)
print(f"  sum = {a50.sum():,.1f}   rateslib par PV01 = {float(ins50.leg1.analytic_delta(disc_curve=curve).real):,.1f}")
lad28, par28, pv0128, J28, krd28 = built["30 (futures-aligned)"]
a50b = krd28("50Y", 100e6, 4.2)
print(f"  with 50Y in the grid: sum = {a50b.sum():,.1f}, top buckets "
      f"{[(lad28[i], round(a50b[i],1)) for i in np.argsort(-np.abs(a50b))[:4]]}")

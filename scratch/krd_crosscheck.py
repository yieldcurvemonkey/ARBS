"""Independent cross-check: my analytic KRD vs the repo's OWN tent bump-and-reprice
ladder (RVUtils/StrikelessVol/decomposition.tent_shifted_handle), which I did not write."""
import os, datetime
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import numpy as np, pandas as pd, rateslib as rl
from Caching.curve_store import CurveStore
from RVUtils.StrikelessVol.decomposition import tent_shifted_handle, _phi
from RVUtils.StrikelessVol.greeks import daily_dcf
pd.set_option("display.width", 240)

store = CurveStore.default()
DAY = datetime.date(2026, 6, 15)
raw = store.read_raw_nodes("USD-SOFR-1D-CITIVELOEXCELMIN", start=DAY, end=DAY)
curve = CurveStore.reconstruct_curve(raw.iloc[len(raw)//2].to_dict())
REF = curve.nodes.initial
CALN = curve.meta.calendar
SPOT = rl.get_calendar(CALN).lag_bus_days(REF, 2, True)
D = daily_dcf(curve)
print(f"curve convention={curve.meta.convention}  daily_dcf={D:.10f}  (1/{1/D:.2f})")

LADDER = ["3M","6M","1Y","18M","2Y","3Y","4Y","5Y","7Y","10Y","12Y","15Y","20Y","25Y","30Y"]
K = len(LADDER)
ins = [rl.IRS(effective=SPOT, termination=t, spec="usd_irs", curves=curve, notional=100e6) for t in LADDER]
PAR = np.array([float(i.rate(curves=curve).real) for i in ins])
PILLARS = [i.leg1.schedule.termination for i in ins]
PD = np.array([(pd.Timestamp(p)-pd.Timestamp(REF)).days for p in PILLARS], float)

NDAYS = np.array([(pd.Timestamp(d)-pd.Timestamp(REF)).days for d in curve.nodes.nodes], float)
LN = np.log(np.array([float(v) for v in curve.nodes.nodes.values()]))
def dff(x): return np.exp(np.interp(x, NDAYS, LN))


def g_repo(t_days):
    """g_j(t) matching decomposition._phi with the curve's own daily DCF."""
    t = np.atleast_1d(np.asarray(t_days, float))
    W = np.array([[_phi(tv, j, PD) for j in range(K)] for tv in t])
    return W * (t * D)[:, None]


def analytic(term, notl, fr, eff=None):
    irs = rl.IRS(effective=eff or SPOT, termination=term, spec="usd_irs", curves=curve,
                 notional=1.0, fixed_rate=1.0)
    def pull(cf, typ):
        d = pd.DataFrame(cf); d = d[d["Type"] == typ]
        f = lambda c: np.array([(pd.Timestamp(x)-pd.Timestamp(REF)).days for x in d[c]], float)
        return f("Acc Start"), f("Acc End"), f("Payment"), np.array(d["DCF"], float)
    (s1,e1,p1,d1) = pull(irs.leg1.cashflows(rate_curve=curve, disc_curve=curve), "FixedPeriod")
    (s2,e2,p2,d2) = pull(irs.leg2.cashflows(rate_curve=curve, disc_curve=curve), "FloatPeriod")
    out = ((-notl*d1*(fr/100.0)*dff(p1))[:, None] * (-g_repo(p1))).sum(axis=0)
    dfs, dfe, dfp = dff(s2), dff(e2), dff(p2); r = dfs/dfe
    out = out + ((notl*r*dfp)[:, None]*(g_repo(e2)-g_repo(s2))
                 + (notl*(r-1)*dfp)[:, None]*(-g_repo(p2))).sum(axis=0)
    return out*1e-4


fwd5 = rl.add_tenor(SPOT, "5Y", "MF", CALN)
CASES = [("spot 10Y payer par", "10Y", 100e6, float(PAR[LADDER.index("10Y")]), None),
         ("spot 30Y recv par", "30Y", -50e6, float(PAR[LADDER.index("30Y")]), None),
         ("spot 7Y payer OFFmkt", "7Y", 250e6, 2.50, None),
         ("5Yx5Y payer", "5Y", 300e6, 4.20, fwd5)]

print("\n===== analytic vs repo's tent_shifted_handle central difference =====")
for name, term, notl, fr, eff in CASES:
    swap = rl.IRS(effective=eff or SPOT, termination=term, spec="usd_irs", curves=curve,
                  notional=notl, fixed_rate=fr)
    for h in (1.0, 0.1):
        repo = np.array([
            (float(swap.npv(curves=tent_shifted_handle(curve, PILLARS, i, +h)).real)
             - float(swap.npv(curves=tent_shifted_handle(curve, PILLARS, i, -h)).real)) / (2*h)
            for i in range(K)])
        a = analytic(term, notl, fr, eff)
        tot = abs(repo.sum())
        print(f"{name:22s} h={h:4}bp  max|analytic-repo| = {np.abs(a-repo).max():9.5f} USD/bp "
              f"= {np.abs(a-repo).max()/tot*100:.7f}% of total DV01 ({repo.sum():,.1f}); "
              f"sum analytic {a.sum():,.4f} vs repo {repo.sum():,.4f}")

print("\n===== effect of the time-measure convention (1/360 vs 1/365) =====")
a360 = analytic("10Y", 100e6, float(PAR[LADDER.index("10Y")]))
print(f"sum with daily_dcf (act360, 1/{1/D:.2f}) = {a360.sum():,.2f}")
print(f"scaling by 360/365 would give            = {a360.sum()*360/365:,.2f}  "
      f"(a {(365/360-1)*100:.2f}% uniform scale on every bucket)")

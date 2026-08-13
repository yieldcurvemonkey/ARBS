"""(1) diagnose the 1Yx10Y outlier, (2) end-to-end throughput on a realistic day."""
import os, time, datetime, statistics
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import numpy as np
import pandas as pd
import rateslib as rl
from Caching.curve_store import CurveStore

pd.set_option("display.width", 240)
store = CurveStore.default()
DAY = datetime.date(2026, 6, 15)
raw = store.read_raw_nodes("USD-SOFR-1D-CITIVELOEXCELMIN", start=DAY, end=DAY)
row = raw.iloc[len(raw) // 2].to_dict()
curve = CurveStore.reconstruct_curve(row)
REF = curve.nodes.initial
CALN, CONV, MODF = curve.meta.calendar, curve.meta.convention, curve.meta.modifier
CAL = rl.get_calendar(CALN)
SPOT = CAL.lag_bus_days(REF, 2, True)
NODE_DATES = list(curve.nodes.nodes)
NODE_DF = np.array([float(curve.nodes.nodes[d]) for d in NODE_DATES])
NODE_DAYS = np.array([(pd.Timestamp(d) - pd.Timestamp(REF)).days for d in NODE_DATES], float)
LN_DF = np.log(NODE_DF)


def make(ladder):
    Kn = len(ladder)
    ins = [rl.IRS(effective=SPOT, termination=t, spec="usd_irs", curves=curve, notional=100e6)
           for t in ladder]
    par = np.array([float(i.rate(curves=curve).real) for i in ins])
    pv01 = np.array([float(i.leg1.analytic_delta(disc_curve=curve).real) for i in ins])
    mats = [i.leg1.schedule.termination for i in ins]
    GRID = np.array([(pd.Timestamp(m) - pd.Timestamp(REF)).days for m in mats], float)

    def tent(t_days):
        t = np.atleast_1d(np.asarray(t_days, float)); W = np.zeros((t.size, Kn))
        for a, tv in enumerate(t):
            if tv <= GRID[0]: W[a, 0] = 1.0
            elif tv >= GRID[-1]: W[a, -1] = 1.0
            else:
                j = int(np.searchsorted(GRID, tv) - 1)
                f = (tv - GRID[j]) / (GRID[j+1] - GRID[j]); W[a, j], W[a, j+1] = 1-f, f
        return W

    def g(t):
        t = np.atleast_1d(np.asarray(t, float)); return tent(t) * (t/365.0)[:, None]

    sched = {}

    def schedule(term, eff):
        key = (str(eff or SPOT), str(term))
        if key not in sched:
            irs = rl.IRS(effective=eff or SPOT, termination=term, spec="usd_irs",
                         curves=curve, notional=1.0, fixed_rate=1.0)
            def pull(cf, typ):
                d = pd.DataFrame(cf); d = d[d["Type"] == typ]
                f = lambda c: np.array([(pd.Timestamp(x)-pd.Timestamp(REF)).days for x in d[c]], float)
                return f("Acc Start"), f("Acc End"), f("Payment"), np.array(d["DCF"], float)
            sched[key] = (pull(irs.leg1.cashflows(rate_curve=curve, disc_curve=curve), "FixedPeriod"),
                          pull(irs.leg2.cashflows(rate_curve=curve, disc_curve=curve), "FloatPeriod"))
        return sched[key]

    def df(d): return np.exp(np.interp(d, NODE_DAYS, LN_DF))

    def krd(term, notl, fr, eff=None):
        (s1, e1, p1, dcf1), (s2, e2, p2, dcf2) = schedule(term, eff)
        out = ((-notl*dcf1*(fr/100.0)*df(p1))[:, None] * (-g(p1))).sum(axis=0)
        dfs, dfe, dfp = df(s2), df(e2), df(p2)
        r = dfs/dfe
        out = out + ((notl*r*dfp)[:, None]*(g(e2)-g(s2)) + (notl*(r-1)*dfp)[:, None]*(-g(p2))).sum(axis=0)
        return out*1e-4

    nodes = {REF: 1.0}
    for m in mats: nodes[m] = float(curve[m])
    rc = rl.Curve(nodes=dict(sorted(nodes.items())), convention=CONV, calendar=CALN,
                  modifier=MODF, interpolation="log_linear", id="RISK")
    slv = rl.Solver(curves=[rc], instruments=[rl.IRS(effective=SPOT, termination=t, spec="usd_irs",
                                                     curves=rc, notional=100e6) for t in ladder],
                    s=list(par), instrument_labels=ladder, id="RISK", func_tol=1e-8, conv_tol=1e-10)
    J = np.zeros((Kn, Kn))
    for i, t in enumerate(ladder):
        J[i, :] = krd(t, 100e6, float(par[i])) / pv01[i]
    return dict(ladder=ladder, krd=krd, rc=rc, slv=slv, JinvT=np.linalg.inv(J).T, par=par)


L15 = ["3M","6M","1Y","18M","2Y","3Y","4Y","5Y","7Y","10Y","12Y","15Y","20Y","25Y","30Y"]
L21 = ["3M","6M","9M","1Y","18M","2Y","3Y","4Y","5Y","6Y","7Y","8Y","9Y","10Y","11Y","12Y",
       "15Y","20Y","25Y","30Y","40Y"]

fwd1 = rl.add_tenor(SPOT, "1Y", "MF", CALN)
fwd5 = rl.add_tenor(SPOT, "5Y", "MF", CALN)
CASES = [
    ("spot 2Y payer par", "2Y", 200e6, None, None),
    ("spot 10Y payer par", "10Y", 100e6, None, None),
    ("spot 30Y recv par", "30Y", -50e6, None, None),
    ("spot 7Y payer OFFmkt", "7Y", 250e6, 2.50, None),
    ("spot 20Y recv OFFmkt", "20Y", -75e6, 6.00, None),
    ("5Yx5Y payer", "5Y", 300e6, 4.20, fwd5),
    ("1Yx10Y receiver", "10Y", -150e6, 4.10, fwd1),
    ("spot 11Y payer", "11Y", 100e6, 4.07, None),
    ("spot 25Y payer", "25Y", 37.5e6, 4.4444, None),
    ("spot 40Y payer", "40Y", 50e6, 4.20, None),
]

print("===== bucket-set sensitivity: converted-par vs rateslib solver delta =====")
out = []
for tag, M in (("15-bucket", make(L15)), ("21-bucket", make(L21))):
    for name, term, notl, fr, eff in CASES:
        if fr is None:
            fr = float(M["par"][M["ladder"].index(term)])
        a = M["krd"](term, notl, fr, eff)
        s = rl.Portfolio([rl.IRS(effective=eff or SPOT, termination=term, spec="usd_irs",
                                 curves=M["rc"], notional=notl, fixed_rate=fr)]
                         ).delta(solver=M["slv"]).iloc[:, 0].to_numpy(float)
        conv = M["JinvT"] @ a
        out.append(dict(ladder=tag, case=name, total_dv01=s.sum(),
                        raw_zero_pct=np.abs(a-s).max()/abs(s.sum())*100,
                        conv_par_pct=np.abs(conv-s).max()/abs(s.sum())*100,
                        conv_par_usd=np.abs(conv-s).max()))
df = pd.DataFrame(out)
print(df.pivot(index="case", columns="ladder", values="conv_par_pct").round(4).to_string())
print("\nmax abs USD/bp difference:")
print(df.pivot(index="case", columns="ladder", values="conv_par_usd").round(2).to_string())
print("\nRAW zero-KRD vs solver par delta (the 'no conversion' answer), % of total DV01:")
print(df.pivot(index="case", columns="ladder", values="raw_zero_pct").round(2).to_string())

# ================================================== throughput, realistic day
print("\n===== end-to-end throughput, one simulated tape day =====")
M = make(L15)
Kn = 15
GRIDMATS = [rl.IRS(effective=SPOT, termination=t, spec="usd_irs", curves=curve,
                   notional=1.0).leg1.schedule.termination for t in L15]
GRID = np.array([(pd.Timestamp(m)-pd.Timestamp(REF)).days for m in GRIDMATS], float)

rng = np.random.default_rng(11)
N_LEGS = 3815                      # 2,326,781 / 610
N_MIN = 897                        # 547,338 / 610
tenors = rng.choice(["1Y","2Y","3Y","5Y","7Y","10Y","12Y","15Y","20Y","30Y"], N_LEGS)
notls = rng.uniform(5e6, 500e6, N_LEGS)
frs = rng.uniform(3.0, 5.0, N_LEGS)
minute_idx = rng.integers(0, min(N_MIN, len(raw)), N_LEGS)

# warm schedule cache (158,249 distinct pairs over the whole tape -> ~260/day)
for t in set(tenors):
    M["krd"](t, 1.0, 4.0)

# pre-extract every minute's node arrays (this is ALL the curve state the analytic needs)
t0 = time.perf_counter()
node_state = []
for i in range(min(N_MIN, len(raw))):
    r = raw.iloc[i]
    nd = np.array([(pd.Timestamp(d)-pd.Timestamp(REF)).days for d in r["node_dates"]], float)
    node_state.append((nd, np.log(np.asarray(r["discount_factors"], float))))
t_nodes = time.perf_counter()-t0
print(f"[thru] extract node arrays for {len(node_state)} minutes (no rl.Curve at all): "
      f"{t_nodes*1000:.0f} ms -> {t_nodes/len(node_state)*1e6:.0f} us/minute")

t0 = time.perf_counter()
for i in range(min(N_MIN, len(raw))):
    CurveStore.reconstruct_curve(raw.iloc[i].to_dict())
t_recon = time.perf_counter()-t0
print(f"[thru] (alternative) reconstruct_curve x{min(N_MIN,len(raw))}: {t_recon*1000:.0f} ms "
      f"-> {t_recon/min(N_MIN,len(raw))*1000:.3f} ms/minute")

sched_abs = {}
for t in set(tenors):
    irs = rl.IRS(effective=SPOT, termination=t, spec="usd_irs", curves=curve, notional=1.0, fixed_rate=1.0)
    def pull(cf, typ):
        d = pd.DataFrame(cf); d = d[d["Type"] == typ]
        f = lambda c: np.array([(pd.Timestamp(x)-pd.Timestamp(REF)).days for x in d[c]], float)
        return f("Acc Start"), f("Acc End"), f("Payment"), np.array(d["DCF"], float)
    sched_abs[t] = (pull(irs.leg1.cashflows(rate_curve=curve, disc_curve=curve), "FixedPeriod"),
                    pull(irs.leg2.cashflows(rate_curve=curve, disc_curve=curve), "FloatPeriod"))


def tentw(t_days):
    t = np.atleast_1d(np.asarray(t_days, float)); W = np.zeros((t.size, Kn))
    for a, tv in enumerate(t):
        if tv <= GRID[0]: W[a, 0] = 1.0
        elif tv >= GRID[-1]: W[a, -1] = 1.0
        else:
            j = int(np.searchsorted(GRID, tv)-1)
            f = (tv-GRID[j])/(GRID[j+1]-GRID[j]); W[a, j], W[a, j+1] = 1-f, f
    return W


gcache = {}
def gof(key, t_days):
    if key not in gcache:
        t = np.asarray(t_days, float)
        gcache[key] = tentw(t) * (t/365.0)[:, None]
    return gcache[key]


t0 = time.perf_counter()
res = np.empty((N_LEGS, Kn))
for a in range(N_LEGS):
    nd, lndf = node_state[minute_idx[a]]
    (s1, e1, p1, d1), (s2, e2, p2, d2) = sched_abs[tenors[a]]
    dfp1 = np.exp(np.interp(p1, nd, lndf))
    v = ((-notls[a]*d1*(frs[a]/100.0)*dfp1)[:, None] * (-gof((tenors[a], 'p1'), p1))).sum(axis=0)
    dfs = np.exp(np.interp(s2, nd, lndf)); dfe = np.exp(np.interp(e2, nd, lndf))
    dfp2 = np.exp(np.interp(p2, nd, lndf)); r = dfs/dfe
    v += ((notls[a]*r*dfp2)[:, None]*(gof((tenors[a],'e2'), e2)-gof((tenors[a],'s2'), s2))
          + (notls[a]*(r-1)*dfp2)[:, None]*(-gof((tenors[a],'p2'), p2))).sum(axis=0)
    res[a] = v*1e-4
t_day = time.perf_counter()-t0
print(f"[thru] {N_LEGS} legs across {len(node_state)} distinct minutes: {t_day*1000:.0f} ms "
      f"-> {t_day/N_LEGS*1e6:.0f} us/leg")
total = t_nodes + t_day
print(f"[thru] one day total (nodes + krd) = {total:.3f} s")
print(f"[thru] PROJECTED 610 days = {total*610/60:.1f} min  (+ parquet reads)")

# rateslib route for the same day, extrapolated from measured unit costs
solver_ms, irs_ms, delta_ms = 42.2, 1.30, 0.80
rl_day = (N_MIN*solver_ms + N_LEGS*(irs_ms+delta_ms))/1000
print(f"[thru] rateslib solver route, same day (measured unit costs "
      f"{solver_ms}ms/solver, {irs_ms}+{delta_ms}ms/leg) = {rl_day:.1f} s "
      f"-> 610 days = {rl_day*610/3600:.2f} h")

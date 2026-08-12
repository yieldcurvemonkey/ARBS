"""Which tent? continuous phi*tau vs node-interpolated phi*tau, against the
repo's own repriceable shock (tent_shifted_handle)."""
import os, datetime
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import numpy as np, pandas as pd, rateslib as rl
from Caching.curve_store import CurveStore
from RVUtils.StrikelessVol.decomposition import tent_shifted_handle, _phi
from RVUtils.StrikelessVol.greeks import daily_dcf
pd.set_option("display.width", 240)

store = CurveStore.default()
curve = CurveStore.reconstruct_curve(
    store.read_raw_nodes("USD-SOFR-1D-CITIVELOEXCELMIN",
                         start=datetime.date(2026, 6, 15), end=datetime.date(2026, 6, 15)
                         ).iloc[660].to_dict())
REF = curve.nodes.initial
CALN = curve.meta.calendar
SPOT = rl.get_calendar(CALN).lag_bus_days(REF, 2, True)
D = daily_dcf(curve)
NDAYS = np.array([(pd.Timestamp(d)-pd.Timestamp(REF)).days for d in curve.nodes.nodes], float)
LN = np.log(np.array([float(v) for v in curve.nodes.nodes.values()]))
print("node spacing (years) near the long end:",
      [round(x/365, 1) for x in NDAYS[-10:]])
def dff(x): return np.exp(np.interp(x, NDAYS, LN))

LADDER = ["3M","6M","1Y","18M","2Y","3Y","4Y","5Y","7Y","10Y","12Y","15Y","20Y","25Y","30Y"]
K = len(LADDER)
ins = [rl.IRS(effective=SPOT, termination=t, spec="usd_irs", curves=curve, notional=100e6) for t in LADDER]
PAR = np.array([float(i.rate(curves=curve).real) for i in ins])
PV01 = np.array([float(i.leg1.analytic_delta(disc_curve=curve).real) for i in ins])
PILLARS = [i.leg1.schedule.termination for i in ins]
PD = np.array([(pd.Timestamp(p)-pd.Timestamp(REF)).days for p in PILLARS], float)
PHI_NODE = np.array([[_phi(n, j, PD) for j in range(K)] for n in NDAYS])
AMP_NODE = PHI_NODE * (NDAYS * D)[:, None]          # exactly what tent_shifted_handle applies


def g_cont(t):
    t = np.atleast_1d(np.asarray(t, float))
    return np.array([[_phi(tv, j, PD) for j in range(K)] for tv in t]) * (t * D)[:, None]


def g_node(t):
    t = np.atleast_1d(np.asarray(t, float))
    return np.column_stack([np.interp(t, NDAYS, AMP_NODE[:, j]) for j in range(K)])


def analytic(term, notl, fr, gfun, eff=None):
    irs = rl.IRS(effective=eff or SPOT, termination=term, spec="usd_irs", curves=curve,
                 notional=1.0, fixed_rate=1.0)
    def pull(cf, typ):
        d = pd.DataFrame(cf); d = d[d["Type"] == typ]
        f = lambda c: np.array([(pd.Timestamp(x)-pd.Timestamp(REF)).days for x in d[c]], float)
        return f("Acc Start"), f("Acc End"), f("Payment"), np.array(d["DCF"], float)
    (s1,e1,p1,d1) = pull(irs.leg1.cashflows(rate_curve=curve, disc_curve=curve), "FixedPeriod")
    (s2,e2,p2,d2) = pull(irs.leg2.cashflows(rate_curve=curve, disc_curve=curve), "FloatPeriod")
    out = ((-notl*d1*(fr/100.0)*dff(p1))[:, None] * (-gfun(p1))).sum(axis=0)
    dfs, dfe, dfp = dff(s2), dff(e2), dff(p2); r = dfs/dfe
    out = out + ((notl*r*dfp)[:, None]*(gfun(e2)-gfun(s2))
                 + (notl*(r-1)*dfp)[:, None]*(-gfun(p2))).sum(axis=0)
    return out*1e-4


fwd5 = rl.add_tenor(SPOT, "5Y", "MF", CALN)
CASES = [("spot 10Y payer par", "10Y", 100e6, float(PAR[LADDER.index("10Y")]), None),
         ("spot 20Y payer par", "20Y", 100e6, float(PAR[LADDER.index("20Y")]), None),
         ("spot 30Y recv par", "30Y", -50e6, float(PAR[LADDER.index("30Y")]), None),
         ("spot 7Y payer OFFmkt", "7Y", 250e6, 2.50, None),
         ("5Yx5Y payer", "5Y", 300e6, 4.20, fwd5)]

print("\n===== analytic vs repo tent_shifted_handle (h=0.1bp central difference) =====")
rows = []
for name, term, notl, fr, eff in CASES:
    swap = rl.IRS(effective=eff or SPOT, termination=term, spec="usd_irs", curves=curve,
                  notional=notl, fixed_rate=fr)
    h = 0.1
    repo = np.array([
        (float(swap.npv(curves=tent_shifted_handle(curve, PILLARS, i, +h)).real)
         - float(swap.npv(curves=tent_shifted_handle(curve, PILLARS, i, -h)).real)) / (2*h)
        for i in range(K)])
    ac, an = analytic(term, notl, fr, g_cont, eff), analytic(term, notl, fr, g_node, eff)
    tot = abs(repo.sum())
    rows.append(dict(case=name, total=repo.sum(),
                     cont_pct=np.abs(ac-repo).max()/tot*100,
                     node_pct=np.abs(an-repo).max()/tot*100,
                     node_usd=np.abs(an-repo).max()))
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:,.7f}"))

# 30Y ladder detail
name, term, notl, fr, eff = CASES[2]
swap = rl.IRS(effective=SPOT, termination=term, spec="usd_irs", curves=curve, notional=notl, fixed_rate=fr)
repo = np.array([(float(swap.npv(curves=tent_shifted_handle(curve, PILLARS, i, +0.1)).real)
                  - float(swap.npv(curves=tent_shifted_handle(curve, PILLARS, i, -0.1)).real))/0.2
                 for i in range(K)])
print(f"\n----- 30Y ladder detail -----")
print(pd.DataFrame({"bucket": LADDER, "repo_reprice": repo,
                    "analytic_cont": analytic(term, notl, fr, g_cont),
                    "analytic_node": analytic(term, notl, fr, g_node)}).round(2).to_string(index=False))

# does the node tent change the zero->par conversion agreement?
def jac(gfun):
    J = np.zeros((K, K))
    for i, t in enumerate(LADDER):
        J[i, :] = analytic(t, 100e6, float(PAR[i]), gfun) / PV01[i]
    return J

nodes = {REF: 1.0}
for m in PILLARS: nodes[m] = float(curve[m])
rc = rl.Curve(nodes=dict(sorted(nodes.items())), convention=curve.meta.convention,
              calendar=CALN, modifier=curve.meta.modifier, interpolation="log_linear", id="RISK")
slv = rl.Solver(curves=[rc], instruments=[rl.IRS(effective=SPOT, termination=t, spec="usd_irs",
                                                 curves=rc, notional=100e6) for t in LADDER],
                s=list(PAR), instrument_labels=LADDER, id="RISK", func_tol=1e-8, conv_tol=1e-10)
print("\n===== zero->par conversion vs rateslib solver delta, both tents =====")
out = []
for gname, gfun in (("continuous", g_cont), ("node-interp", g_node)):
    JT = np.linalg.inv(jac(gfun)).T
    for name, term, notl, fr, eff in CASES:
        a = analytic(term, notl, fr, gfun, eff)
        s = rl.Portfolio([rl.IRS(effective=eff or SPOT, termination=term, spec="usd_irs",
                                 curves=rc, notional=notl, fixed_rate=fr)]
                         ).delta(solver=slv).iloc[:, 0].to_numpy(float)
        out.append(dict(tent=gname, case=name, max_pct=np.abs(JT@a - s).max()/abs(s.sum())*100))
print(pd.DataFrame(out).pivot(index="case", columns="tent", values="max_pct").round(5).to_string())

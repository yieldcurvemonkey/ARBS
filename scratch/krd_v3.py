"""V1b exact-node shock control + V3 zero->par Jacobian conversion + batch timings."""
import os, time, datetime, statistics
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import numpy as np
import pandas as pd
import rateslib as rl
from Caching.curve_store import CurveStore

NAME = "USD-SOFR-1D-CITIVELOEXCELMIN"
DAY = datetime.date(2026, 6, 15)
LADDER = ["3M", "6M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y", "7Y",
          "10Y", "12Y", "15Y", "20Y", "25Y", "30Y"]
K = len(LADDER)

store = CurveStore.default()
raw = store.read_raw_nodes(NAME, start=DAY, end=DAY)
row = raw.iloc[len(raw) // 2].to_dict()
curve = CurveStore.reconstruct_curve(row)
REF = curve.nodes.initial
CAL = rl.get_calendar("nyc")
SPOT = CAL.lag_bus_days(REF, 2, True)

NODE_DATES = list(curve.nodes.nodes)
NODE_DF = np.array([float(curve.nodes.nodes[d]) for d in NODE_DATES])
NODE_DAYS = np.array([(pd.Timestamp(d) - pd.Timestamp(REF)).days for d in NODE_DATES], float)
DCF_DAILY = 1.0 / 365.0
NODE_YEARS = NODE_DAYS * DCF_DAILY
CONV, CALN, MODF = curve.meta.convention, curve.meta.calendar, curve.meta.modifier


def mk_irs(term, curves, notional=100e6, fixed_rate=None, effective=None):
    kw = dict(effective=effective or SPOT, termination=term, spec="usd_irs",
              curves=curves, notional=notional)
    if fixed_rate is not None:
        kw["fixed_rate"] = fixed_rate
    return rl.IRS(**kw)


ladder_dense = [mk_irs(t, curve) for t in LADDER]
PAR = np.array([float(i.rate(curves=curve).real) for i in ladder_dense])
PV01 = np.array([float(i.leg1.analytic_delta(disc_curve=curve).real) for i in ladder_dense])
MATS = [i.leg1.schedule.termination for i in ladder_dense]
GRID_DAYS = np.array([(pd.Timestamp(m) - pd.Timestamp(REF)).days for m in MATS], float)


def tent_weights(t_days):
    t = np.atleast_1d(np.asarray(t_days, float))
    W = np.zeros((t.size, K))
    idx = np.clip(np.searchsorted(GRID_DAYS, t) - 1, 0, K - 2)
    for a, tv in enumerate(t):
        if tv <= GRID_DAYS[0]:
            W[a, 0] = 1.0
        elif tv >= GRID_DAYS[-1]:
            W[a, -1] = 1.0
        else:
            j = idx[a]
            f = (tv - GRID_DAYS[j]) / (GRID_DAYS[j + 1] - GRID_DAYS[j])
            W[a, j] = 1.0 - f
            W[a, j + 1] = f
    return W


TENT_NODE_AMP = tent_weights(NODE_DAYS) * NODE_YEARS[:, None]


def g_node_interp(t_days):
    t = np.atleast_1d(np.asarray(t_days, float))
    return np.column_stack([np.interp(t, NODE_DAYS, TENT_NODE_AMP[:, j]) for j in range(K)])


def g_continuous(t_days):
    t = np.atleast_1d(np.asarray(t_days, float))
    return tent_weights(t) * (t * DCF_DAILY)[:, None]


_sched = {}


def schedule(term, effective=None):
    key = (str(effective or SPOT), term)
    if key not in _sched:
        irs = mk_irs(term, curve, notional=1.0, fixed_rate=1.0)

        def pull(cf, typ):
            d = pd.DataFrame(cf)
            d = d[d["Type"] == typ]
            f = lambda col: np.array([(pd.Timestamp(x) - pd.Timestamp(REF)).days for x in d[col]], float)
            return f("Acc Start"), f("Acc End"), f("Payment"), np.array(d["DCF"], float)

        _sched[key] = (pull(irs.leg1.cashflows(rate_curve=curve, disc_curve=curve), "FixedPeriod"),
                       pull(irs.leg2.cashflows(rate_curve=curve, disc_curve=curve), "FloatPeriod"))
    return _sched[key]


# vectorised log-linear DF lookup straight off the node array (exact for this curve)
LN_DF = np.log(NODE_DF)


def df_fast(day_offsets):
    return np.exp(np.interp(day_offsets, NODE_DAYS, LN_DF))


def df_curve(day_offsets):
    return np.array([float(curve[pd.Timestamp(REF) + pd.Timedelta(days=int(x))]) for x in day_offsets])


def analytic_krd(term, notional, fixed_rate, gfun, dffun=df_fast, effective=None):
    (s1, e1, p1, dcf1), (s2, e2, p2, dcf2) = schedule(term, effective)
    dfp1 = dffun(p1)
    cf1 = -notional * dcf1 * (fixed_rate / 100.0)
    krd = ((cf1 * dfp1)[:, None] * (-gfun(p1))).sum(axis=0)
    dfs, dfe, dfp2 = dffun(s2), dffun(e2), dffun(p2)
    gs, ge, gp = gfun(s2), gfun(e2), gfun(p2)
    ratio = dfs / dfe
    krd = krd + ((notional * ratio * dfp2)[:, None] * (ge - gs)
                 + (notional * (ratio - 1.0) * dfp2)[:, None] * (-gp)).sum(axis=0)
    return krd * 1e-4


# ---------------------------------------------------- V1b exact-node shock
def exact_shocked_curve(j, bump_bp):
    scale = bump_bp * 1e-4
    nodes = {d: float(NODE_DF[i] * np.exp(-scale * TENT_NODE_AMP[i, j]))
             for i, d in enumerate(NODE_DATES)}
    return rl.Curve(nodes=nodes, convention=CONV, calendar=CALN, modifier=MODF,
                    interpolation="log_linear", id=f"sh{j}")


TEST_TERM, TEST_N = "10Y", 100e6
TEST_K = float(PAR[LADDER.index("10Y")])
test_irs = mk_irs(TEST_TERM, curve, notional=TEST_N, fixed_rate=TEST_K)

for bump in (1.0, 0.1):
    ex = []
    for j in range(K):
        up = float(test_irs.npv(curves=exact_shocked_curve(j, +bump)).real)
        dn = float(test_irs.npv(curves=exact_shocked_curve(j, -bump)).real)
        ex.append((up - dn) / (2.0 * bump))
    ex = np.array(ex)
    an = analytic_krd(TEST_TERM, TEST_N, TEST_K, g_node_interp, dffun=df_curve)
    tot = ex.sum()
    print(f"[V1b bump={bump}bp exact-node reprice] max|analytic-reprice| = "
          f"{np.abs(an-ex).max():.5f} USD/bp = {np.abs(an-ex).max()/abs(tot)*100:.7f}% of total "
          f"DV01 ({tot:.2f}); sum analytic {an.sum():.4f}")

# fast (numpy) DF vs rateslib DF
an_fast = analytic_krd(TEST_TERM, TEST_N, TEST_K, g_node_interp, dffun=df_fast)
an_rl = analytic_krd(TEST_TERM, TEST_N, TEST_K, g_node_interp, dffun=df_curve)
print(f"[df] numpy log-linear vs rateslib curve[] : max|diff| = {np.abs(an_fast-an_rl).max():.3e} USD/bp")

# ------------------------------------------------------- V3 zero -> par map
t0 = time.perf_counter()
Jac = np.zeros((K, K))                       # J[i,j] = d par_i / d zero_j  (bp/bp)
for i, t in enumerate(LADDER):
    Jac[i, :] = analytic_krd(t, 100e6, float(PAR[i]), g_continuous) / (PV01[i] / 100e6 * 100e6)
t_jac = time.perf_counter() - t0
print(f"\n[V3] zero->par Jacobian ({K}x{K}) built analytically in {t_jac*1000:.2f} ms")
print("[V3] Jacobian diagonal (should be ~1):", np.round(np.diag(Jac), 4).tolist())
print("[V3] row sums (should be ~1):", np.round(Jac.sum(axis=1), 4).tolist())

Jinv_T = np.linalg.inv(Jac).T
zero_krd = analytic_krd(TEST_TERM, TEST_N, TEST_K, g_continuous)
par_from_analytic = Jinv_T @ zero_krd

solver_delta = np.load(os.path.join(os.path.dirname(__file__), "_solver_delta.npy"))
tot_par = solver_delta.sum()
cmp = pd.DataFrame({"bucket": LADDER, "zero_krd_analytic": zero_krd,
                    "par_from_analytic": par_from_analytic,
                    "rateslib_solver_delta": solver_delta})
cmp["diff_par"] = cmp["par_from_analytic"] - cmp["rateslib_solver_delta"]
cmp["diff_raw_zero_vs_solver"] = cmp["zero_krd_analytic"] - cmp["rateslib_solver_delta"]
pd.set_option("display.width", 220)
print(cmp.round(3).to_string(index=False))
print(f"\nsum zero_krd            = {zero_krd.sum():.2f}")
print(f"sum par_from_analytic   = {par_from_analytic.sum():.2f}")
print(f"sum rateslib solver     = {tot_par:.2f}")
print(f"[RAW zero vs solver par] max|diff| = {np.abs(cmp['diff_raw_zero_vs_solver']).max():.2f} USD/bp "
      f"= {np.abs(cmp['diff_raw_zero_vs_solver']).max()/abs(tot_par)*100:.3f}% of total DV01")
print(f"[CONVERTED par vs solver] max|diff| = {np.abs(cmp['diff_par']).max():.3f} USD/bp "
      f"= {np.abs(cmp['diff_par']).max()/abs(tot_par)*100:.4f}% of total DV01")

# ------------------------------------------------------------- batch timing
rng = np.random.default_rng(7)
terms = [f"{int(x)}Y" for x in rng.integers(1, 31, 2000)]
notionals = rng.uniform(10e6, 500e6, 2000)
rates = rng.uniform(3.0, 5.0, 2000)
for t in set(terms):
    schedule(t)                                   # warm the schedule cache
t0 = time.perf_counter()
out = np.empty((2000, K))
for a in range(2000):
    out[a] = analytic_krd(terms[a], notionals[a], rates[a], g_continuous)
t_batch = time.perf_counter() - t0
print(f"\n[timing] analytic_krd x2000 (warm schedule cache, numpy DF): {t_batch*1000:.1f} ms "
      f"-> {t_batch/2000*1e6:.1f} us/trade")

t0 = time.perf_counter()
par_out = out @ Jinv_T.T
print(f"[timing] par conversion 2000x{K} matvec: {(time.perf_counter()-t0)*1e6:.0f} us total")

# cold cache cost (a tenor never seen before)
_sched.clear()
ts = []
uniq = [f"{i}Y" for i in range(1, 21)]
for t in uniq:
    _sched.clear()
    t0 = time.perf_counter(); schedule(t); ts.append(time.perf_counter() - t0)
print(f"[timing] cold schedule build (rl.IRS + 2x cashflows): median {statistics.median(ts)*1000:.2f} ms/tenor")

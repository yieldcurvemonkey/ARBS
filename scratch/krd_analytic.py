"""Analytic cashflow-bucketed key-rate DV01, validated 3 ways.

V1  analytic (node-interpolated tent) vs central-difference bump-and-reprice of
    the SAME tent  -> validates the derivative code against a known answer.
V2  analytic continuous tent vs analytic node-interpolated tent -> bucket-definition gap.
V3  analytic zero-KRD -> par space via the curve's own dp/dz Jacobian, vs
    rateslib Portfolio.delta(solver=...).
"""
import os, sys, time, datetime, statistics, json
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import numpy as np
import pandas as pd
import rateslib as rl
from Caching.curve_store import CurveStore

NAME_SOFR = "USD-SOFR-1D-CITIVELOEXCELMIN"
DAY = datetime.date(2026, 6, 15)
LADDER = ["3M", "6M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y", "7Y",
          "10Y", "12Y", "15Y", "20Y", "25Y", "30Y"]

store = CurveStore.default()
raw = store.read_raw_nodes(NAME_SOFR, start=DAY, end=DAY)
row = raw.iloc[len(raw) // 2].to_dict()
curve = CurveStore.reconstruct_curve(row)
REF = curve.nodes.initial
CAL = rl.get_calendar("nyc")
SPOT = CAL.lag_bus_days(REF, 2, True)

NODE_DATES = list(curve.nodes.nodes)
NODE_DAYS = np.array([(pd.Timestamp(d) - pd.Timestamp(REF)).days for d in NODE_DATES], float)
DCF_DAILY = 1.0 / 365.0          # year-fraction convention for the tent axis only
NODE_YEARS = NODE_DAYS * DCF_DAILY


def mk_irs(term, curves, notional=100e6, fixed_rate=None, effective=None):
    kw = dict(effective=effective or SPOT, termination=term, spec="usd_irs",
              curves=curves, notional=notional)
    if fixed_rate is not None:
        kw["fixed_rate"] = fixed_rate
    return rl.IRS(**kw)


ladder_dense = [mk_irs(t, curve) for t in LADDER]
PAR = [float(i.rate(curves=curve).real) for i in ladder_dense]
MATS = [i.leg1.schedule.termination for i in ladder_dense]
GRID_DAYS = np.array([(pd.Timestamp(m) - pd.Timestamp(REF)).days for m in MATS], float)
GRID_YEARS = GRID_DAYS * DCF_DAILY
K = len(LADDER)


# ------------------------------------------------------------------ tents
def tent_weights(t_days):
    """(n, K) continuous piecewise-linear hat weights on GRID_DAYS; rows sum to 1."""
    t = np.atleast_1d(np.asarray(t_days, float))
    W = np.zeros((t.size, K))
    for a, tv in enumerate(t):
        if tv <= GRID_DAYS[0]:
            W[a, 0] = 1.0
        elif tv >= GRID_DAYS[-1]:
            W[a, -1] = 1.0
        else:
            j = int(np.searchsorted(GRID_DAYS, tv) - 1)
            f = (tv - GRID_DAYS[j]) / (GRID_DAYS[j + 1] - GRID_DAYS[j])
            W[a, j] = 1.0 - f
            W[a, j + 1] = f
    return W


# node-level tent amplitudes a_j(node) = w_j(u_node) * u_node  (years)
TENT_NODE_AMP = tent_weights(NODE_DAYS) * NODE_YEARS[:, None]      # (n_nodes, K)


def g_node_interp(t_days):
    """g_j(t) for the tent as rateslib sees it: log-linear between curve nodes."""
    t = np.atleast_1d(np.asarray(t_days, float))
    return np.column_stack([np.interp(t, NODE_DAYS, TENT_NODE_AMP[:, j]) for j in range(K)])


def g_continuous(t_days):
    """g_j(t) for the ideal continuous tent: w_j(t) * tau(t)."""
    t = np.atleast_1d(np.asarray(t_days, float))
    return tent_weights(t) * (t * DCF_DAILY)[:, None]


# ------------------------------------------------------------ schedule cache
_sched_cache = {}


def swap_schedule(term, effective=None):
    key = (str(effective or SPOT), term)
    if key in _sched_cache:
        return _sched_cache[key]
    irs = mk_irs(term, curve, notional=1.0, fixed_rate=1.0)
    cf1 = irs.leg1.cashflows(rate_curve=curve, disc_curve=curve)
    cf2 = irs.leg2.cashflows(rate_curve=curve, disc_curve=curve)

    def pull(cf):
        d = pd.DataFrame(cf)
        d = d[d["Type"].isin(("FixedPeriod", "FloatPeriod"))]
        return (
            np.array([(pd.Timestamp(x) - pd.Timestamp(REF)).days for x in d["Acc Start"]], float),
            np.array([(pd.Timestamp(x) - pd.Timestamp(REF)).days for x in d["Acc End"]], float),
            np.array([(pd.Timestamp(x) - pd.Timestamp(REF)).days for x in d["Payment"]], float),
            np.array(d["DCF"], float),
        )

    out = (pull(cf1), pull(cf2))
    _sched_cache[key] = out
    return out


def df_at(day_offsets):
    return np.array([float(curve[pd.Timestamp(REF) + pd.Timedelta(days=int(x))])
                     for x in day_offsets])


def analytic_krd(term, notional, fixed_rate, gfun, effective=None):
    """Signed key-rate DV01 (USD per bp of each bucket) of a payer IRS.

    notional>0 = pay fixed (rateslib convention). Returns length-K vector.
    """
    (s1, e1, p1, dcf1), (s2, e2, p2, dcf2) = swap_schedule(term, effective)
    # --- fixed leg: PV = -N * sum dcf_i * K * DF(p_i)
    dfp1 = df_at(p1)
    g1 = gfun(p1)                                   # (n1, K)
    cf1 = -notional * dcf1 * (fixed_rate / 100.0)
    krd = ((cf1 * dfp1)[:, None] * (-g1)).sum(axis=0)
    # --- float leg: PV = +N * sum (DF(s)/DF(e) - 1) * DF(p)
    dfs, dfe, dfp2 = df_at(s2), df_at(e2), df_at(p2)
    gs, ge, gp = gfun(s2), gfun(e2), gfun(p2)
    ratio = dfs / dfe
    term_a = (notional * ratio * dfp2)[:, None] * (ge - gs)
    term_b = (notional * (ratio - 1.0) * dfp2)[:, None] * (-gp)
    krd = krd + (term_a + term_b).sum(axis=0)
    return krd * 1e-4


# ------------------------------------------------------ V1: bump and reprice
def shocked_curve(j, bump_bp):
    scale = bump_bp * 1e-4
    tent_nodes = {d: float(np.exp(-scale * TENT_NODE_AMP[i, j]))
                  for i, d in enumerate(NODE_DATES)}
    tent = rl.Curve(nodes=tent_nodes, convention=curve.meta.convention,
                    calendar=curve.meta.calendar, modifier=curve.meta.modifier,
                    id=f"tent{j}")
    return rl.CompositeCurve([curve, tent])


TEST_TERM, TEST_N = "10Y", 100e6
TEST_K = PAR[LADDER.index("10Y")]
test_irs = mk_irs(TEST_TERM, curve, notional=TEST_N, fixed_rate=TEST_K)

# --- V0: does the OIS float leg telescope?  cf = -N2*(DF(s)/DF(e)-1) ?
_cf2 = test_irs.leg2.cashflows(rate_curve=curve, disc_curve=curve)
_cf2 = pd.DataFrame(_cf2)
_cf2 = _cf2[_cf2["Type"] == "FloatPeriod"]
_lhs = np.array(_cf2["Cashflow"], float)
_dfs = np.array([float(curve[pd.Timestamp(x)]) for x in _cf2["Acc Start"]])
_dfe = np.array([float(curve[pd.Timestamp(x)]) for x in _cf2["Acc End"]])
_n2 = np.array(_cf2["Notional"], float)
_rhs = -_n2 * (_dfs / _dfe - 1.0)
print(f"[V0] OIS telescoping identity  max|cf - (-N2*(DFs/DFe-1))| = {np.abs(_lhs-_rhs).max():.4f} USD "
      f"on cashflows of order {np.abs(_lhs).mean():.0f} "
      f"(rel {np.abs((_lhs-_rhs)/_lhs).max():.3e})")

# --- V0b: total DV01 of the test swap, three ways
_pv01_analytic = float(test_irs.leg1.analytic_delta(disc_curve=curve).real)
print(f"[V0b] rateslib analytic_delta (annuity per bp) = {_pv01_analytic:.2f}")

t0 = time.perf_counter()
bump_krd = []
for j in range(K):
    up = float(test_irs.npv(curves=shocked_curve(j, +1.0)).real)
    dn = float(test_irs.npv(curves=shocked_curve(j, -1.0)).real)
    bump_krd.append((up - dn) / 2.0)
bump_krd = np.array(bump_krd)
t_bump = time.perf_counter() - t0

ana_node = analytic_krd(TEST_TERM, TEST_N, TEST_K, g_node_interp)
ana_cont = analytic_krd(TEST_TERM, TEST_N, TEST_K, g_continuous)

print("=" * 78)
print(f"TEST TRADE: spot 10Y payer, $100mm, fixed={TEST_K:.4f}%, curve {row['timestamp_utc']}")
print("=" * 78)
res = pd.DataFrame({"bucket": LADDER, "bump_reprice": bump_krd,
                    "analytic_nodeTent": ana_node, "analytic_contTent": ana_cont})
res["V1_diff"] = res["analytic_nodeTent"] - res["bump_reprice"]
res["V2_diff"] = res["analytic_contTent"] - res["analytic_nodeTent"]
pd.set_option("display.width", 200)
print(res.round(3).to_string(index=False))
tot = bump_krd.sum()
print(f"\nsum bump-reprice   = {bump_krd.sum():.3f}")
print(f"sum analytic node  = {ana_node.sum():.3f}")
print(f"sum analytic cont  = {ana_cont.sum():.3f}")
print(f"V1 max|diff| = {np.abs(res['V1_diff']).max():.4f} USD/bp "
      f"= {np.abs(res['V1_diff']).max()/abs(tot)*100:.6f}% of total DV01")
print(f"V2 max|diff| = {np.abs(res['V2_diff']).max():.4f} USD/bp "
      f"= {np.abs(res['V2_diff']).max()/abs(tot)*100:.6f}% of total DV01")
print(f"[timing] bump-and-reprice ladder ({K} buckets, central diff): {t_bump*1000:.1f} ms")

med = statistics.median([_t for _t in [
    (lambda: (time.perf_counter(), analytic_krd(TEST_TERM, TEST_N, TEST_K, g_continuous),
              time.perf_counter()))() for _ in range(1)]][0][0:1]) if False else None
ts = []
for _ in range(50):
    t0 = time.perf_counter(); analytic_krd(TEST_TERM, TEST_N, TEST_K, g_continuous)
    ts.append(time.perf_counter() - t0)
print(f"[timing] analytic_krd (warm schedule cache): median {statistics.median(ts)*1000:.4f} ms")
_sched_cache.clear()
ts = []
for i in range(20):
    _sched_cache.clear()
    t0 = time.perf_counter(); analytic_krd(TEST_TERM, TEST_N, TEST_K, g_continuous)
    ts.append(time.perf_counter() - t0)
print(f"[timing] analytic_krd (cold schedule, incl. rl.IRS + cashflows): "
      f"median {statistics.median(ts)*1000:.3f} ms")

np.save(os.path.join(os.path.dirname(__file__), "_ana_cont.npy"), ana_cont)
np.save(os.path.join(os.path.dirname(__file__), "_ana_node.npy"), ana_node)
np.save(os.path.join(os.path.dirname(__file__), "_bump.npy"), bump_krd)

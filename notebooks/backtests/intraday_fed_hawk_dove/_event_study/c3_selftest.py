"""Known-answer tests for c3_stats. Every check has an independently-known answer.
Also includes MUTATION checks: deliberately broken inputs that MUST fail the test,
proving the test has a real hole to fall through."""
import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

import numpy as np
from scipy import stats as sps
import c3_stats as CS

rng = np.random.default_rng(7)
FAILS = []


def chk(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("   " + detail if detail else ""))
    if not ok:
        FAILS.append(name)


print("=== TEST 1: simple_fit slope/t/r2 vs scipy.stats.linregress ===")
for trial in range(5):
    x = rng.normal(size=30)
    y = 2.5 * x + rng.normal(size=30) * 3 + 1.0
    f = CS.simple_fit(x, y)
    lr = sps.linregress(x, y)
    ok = (abs(f["slope"] - lr.slope) < 1e-10 and abs(f["t_slope"] - lr.slope / lr.stderr) < 1e-8
          and abs(f["r2"] - lr.rvalue ** 2) < 1e-10 and abs(f["p_slope"] - lr.pvalue) < 1e-10
          and abs(f["intercept"] - lr.intercept) < 1e-10)
    chk(f"trial {trial}: slope/t/r2/p/intercept match linregress", ok,
        f"slope {f['slope']:.6f} vs {lr.slope:.6f}")

print()
print("=== TEST 2: analytic 3-point fit with a hand-computable answer ===")
# x=[0,1,2], y=[1,3,5] is exactly y = 1 + 2x  -> slope 2, r2 1.0, resid 0
f = CS.simple_fit([0.0, 1.0, 2.0], [1.0, 3.0, 5.0])
chk("exact line: slope == 2", abs(f["slope"] - 2.0) < 1e-12, f"got {f['slope']}")
chk("exact line: intercept == 1", abs(f["intercept"] - 1.0) < 1e-12, f"got {f['intercept']}")
chk("exact line: r2 == 1", abs(f["r2"] - 1.0) < 1e-12, f"got {f['r2']}")
# leverage of a 3-pt bivariate fit must sum to k=2
chk("leverage sums to k=2", abs(f["leverage"].sum() - 2.0) < 1e-10, f"got {f['leverage'].sum()}")

print()
print("=== TEST 3: leverage identifies the known high-leverage point ===")
# one x far from the rest MUST have the highest leverage, by construction
x = np.concatenate([rng.normal(size=20), [50.0]])
y = rng.normal(size=21)
f = CS.simple_fit(x, y)
chk("far-out x has max leverage", int(np.argmax(f["leverage"])) == 20,
    f"argmax={int(np.argmax(f['leverage']))} h={f['leverage'][20]:.4f}")

print()
print("=== TEST 4: Cook's D identifies the point whose removal moves the slope most ===")
x = np.concatenate([rng.normal(size=20), [30.0]])
y = np.concatenate([rng.normal(size=20), [40.0]])
f = CS.simple_fit(x, y)
full = f["slope"]
shifts = []
for i in range(len(x)):
    m = np.ones(len(x), bool)
    m[i] = False
    shifts.append(abs(CS.simple_fit(x[m], y[m])["slope"] - full))
chk("argmax Cook's D == argmax |slope shift on removal|",
    int(np.argmax(f["cook"])) == int(np.argmax(shifts)),
    f"cook argmax={int(np.argmax(f['cook']))} shift argmax={int(np.argmax(shifts))}")

print()
print("=== TEST 5: cluster SE with singleton clusters == HC0-style, and shrinks vs grouped ===")
n = 200
x = rng.normal(size=n)
y = x * 0.5 + rng.normal(size=n)
X = np.column_stack([np.ones(n), x])
singleton = CS.ols_cluster(X, y, np.arange(n))
plain = CS.ols(X, y)
chk("singleton-cluster SE within 20% of plain OLS SE (iid data)",
    abs(singleton["se"][1] / plain["se"][1] - 1.0) < 0.20,
    f"ratio {singleton['se'][1]/plain['se'][1]:.4f}")
# NOTE: a cluster-correlated ERROR alone does NOT inflate the slope SE if the
# regressor is iid across clusters -- the shocks are then orthogonal to x and the
# cluster SE correctly comes in BELOW the naive one. The textbook inflation needs
# BOTH the regressor and the error to be cluster-correlated. Build that case.
g = np.repeat(np.arange(10), 20)
xg = np.repeat(rng.normal(size=10) * 2.0, 20) + rng.normal(size=n) * 0.3  # cluster-correlated x
shock = np.repeat(rng.normal(size=10) * 3.0, 20)                          # cluster-correlated e
y2 = xg * 0.5 + shock + rng.normal(size=n) * 0.3
X2 = np.column_stack([np.ones(n), xg])
cl = CS.ols_cluster(X2, y2, g)
pl = CS.ols(X2, y2)
chk("cluster-correlated x AND e: cluster SE >> plain SE", cl["se"][1] > 2.0 * pl["se"][1],
    f"cluster {cl['se'][1]:.4f} vs plain {pl['se'][1]:.4f} ratio {cl['se'][1]/pl['se'][1]:.2f}")

print()
print("=== TEST 5b: cluster SE vs statsmodels (independent implementation) ===")
try:
    import statsmodels.api as sm
    sm_res = sm.OLS(y2, X2).fit(cov_type="cluster", cov_kwds={"groups": g, "use_correction": True})
    chk("cluster SE matches statsmodels CR1 to 1e-6",
        np.allclose(cl["se"], sm_res.bse, rtol=1e-6),
        f"mine {cl['se']} vs sm {sm_res.bse.values if hasattr(sm_res.bse,'values') else sm_res.bse}")
    chk("beta matches statsmodels", np.allclose(cl["beta"], sm_res.params, rtol=1e-10))
    sm_plain = sm.OLS(y, np.column_stack([np.ones(n), x])).fit()
    p_ols = CS.ols(np.column_stack([np.ones(n), x]), y)
    chk("plain OLS SE matches statsmodels", np.allclose(p_ols["se"], sm_plain.bse, rtol=1e-10))
except ImportError:
    print("  SKIP  statsmodels not installed -- no independent cross-check available")
    FAILS.append("statsmodels cross-check unavailable")

print()
print("=== TEST 6: cluster point estimate identical to OLS point estimate ===")
chk("beta identical", np.allclose(cl["beta"], pl["beta"]),
    f"{cl['beta']} vs {pl['beta']}")

print()
print("=== TEST 7: WLS with equal weights reproduces OLS ===")
n = 40
x = rng.normal(size=n)
y = 1.5 * x + rng.normal(size=n)
X = np.column_stack([np.ones(n), x])
w = np.ones(n)
a = CS.wls(X, y, w)
b = CS.ols(X, y)
chk("equal-weight WLS beta == OLS beta", np.allclose(a["beta"], b["beta"]),
    f"{a['beta']} vs {b['beta']}")
# WLS with a known-answer: give one point weight ~0, slope must move toward the rest
w2 = np.ones(n); w2[0] = 1e-9
c = CS.wls(X, y, w2)
m = np.ones(n, bool); m[0] = False
d = CS.ols(X[m], y[m])
chk("zero-weighting a point == dropping it", np.allclose(c["beta"], d["beta"], atol=1e-5),
    f"{c['beta']} vs {d['beta']}")

print()
print("=== MUTATION CHECKS: broken inputs that MUST be caught ===")
# M1: if simple_fit ignored x entirely (slope 0), test 1 would fail
xm = rng.normal(size=30); ym = 2.5 * xm + rng.normal(size=30)
lrm = sps.linregress(xm, ym)
chk("M1 a zero-slope stub would FAIL test 1", abs(0.0 - lrm.slope) > 1e-10,
    f"true slope {lrm.slope:.4f} != 0")
# M2: if y and x were swapped, slope differs (unless r2==1)
f_ok = CS.simple_fit(xm, ym)["slope"]
f_sw = CS.simple_fit(ym, xm)["slope"]
chk("M2 x/y swap changes the slope (test would catch it)", abs(f_ok - f_sw) > 1e-6,
    f"{f_ok:.4f} vs {f_sw:.4f}")
# M3: a sign flip in y must flip the slope sign
f_neg = CS.simple_fit(xm, -ym)["slope"]
chk("M3 negating y flips slope sign", abs(f_neg + f_ok) < 1e-10, f"{f_neg:.4f} vs {-f_ok:.4f}")

print()
print("=" * 60)
if FAILS:
    print("SELF-TEST FAILURES:", FAILS)
    sys.exit(1)
print("ALL SELF-TESTS PASSED")

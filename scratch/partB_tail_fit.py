"""Part B step 2: right-truncated tail fits per (tenor band x cap vintage).

The estimand is  E[notional | notional > C]  for each cap C, so that the
right-censored prints can be given an expected size instead of the cap value.

Two traps this code is built around:

1. The sub-cap sample is **right-truncated at C**, not a clean sample from the
   tail.  Fitting an ordinary Hill/Pareto MLE to [u, C) biases alpha UP (the
   tail looks thinner than it is) which biases E[X|X>C] DOWN.  Every fit here
   carries the (1 - (u/C)^alpha) truncation term.
2. A tail fit can return alpha <= 1, for which the Pareto mean does not exist.
   The code reports alpha and `mean_exists` per cell rather than silently
   emitting inf.

Two estimators are reported per family:
  * `trunc`    -- MLE on the sub-cap observations only, right-truncated at C.
  * `censored` -- MLE using the sub-cap observations AND the observed count of
                  capped prints as mass on [C, inf).  Strictly more
                  information; it is the one whose predicted capped count
                  cannot disagree with the observed one.

Run:
    python scratch/partB_tail_fit.py --selftest   # recover known parameters
    python scratch/partB_tail_fit.py              # fit the tape
"""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
from scipy import optimize, stats
from scipy.special import ndtr

OUT = os.path.dirname(os.path.abspath(__file__))
pd.set_option("display.width", 320)
pd.set_option("display.max_rows", 500)
pd.set_option("display.max_columns", 60)


# ===========================================================================
# Pareto, right-truncated at C, left-truncated (conditioned) at u
# ===========================================================================
def pareto_trunc_mle(x, w, u, C):
    """alpha maximising the [u, C)-truncated Pareto likelihood."""
    W = float(np.sum(w))
    rho = np.log(C / u)
    m = float(np.sum(w * np.log(x / u)) / W)          # mean log-excess

    def g(a):
        if abs(a) < 1e-9:
            return rho / 2.0 - m
        return 1.0 / a - rho / np.expm1(a * rho) - m

    lo, hi = -5.0, 200.0
    if g(lo) * g(hi) > 0:
        return float("nan")
    return float(optimize.brentq(g, lo, hi, xtol=1e-10))


def pareto_censored_mle(x, w, u, C, n_cap):
    """alpha from sub-cap observations PLUS the observed mass at/above C.

    Closed form: alpha = W / (W*m + n_cap*ln(C/u)).  This is the Hill
    estimator with the censored prints contributing their known log-excess.
    """
    W = float(np.sum(w))
    rho = np.log(C / u)
    m = float(np.sum(w * np.log(x / u)) / W)
    denom = W * m + n_cap * rho
    return float(W / denom) if denom > 0 else float("nan")


def pareto_loglik_trunc(a, x, w, u, C):
    W = float(np.sum(w))
    rho = np.log(C / u)
    if abs(a) < 1e-12:
        return -np.inf
    return (W * np.log(abs(a)) + W * a * np.log(u)
            - (a + 1.0) * float(np.sum(w * np.log(x)))
            - W * np.log(abs(-np.expm1(-a * rho))))


def pareto_cdf_trunc(q, a, u, C):
    """P(X <= q | u <= X < C) for the truncated Pareto."""
    q = np.asarray(q, dtype=float)
    return (1.0 - (u / q) ** a) / (1.0 - (u / C) ** a)


def pareto_tail_ratio(a, u, C):
    """S(C)/S(u) for the untruncated Pareto conditioned at u."""
    return (u / C) ** a


def pareto_mean_above(a, C):
    if not np.isfinite(a) or a <= 1.0:
        return float("inf")
    return a * C / (a - 1.0)


# ===========================================================================
# Lognormal, right-truncated at C, left-truncated at u
# ===========================================================================
_LOG2PI = float(np.log(2.0 * np.pi))


def _suffstats(lx, w):
    """(W, sum w*lx, sum w*lx^2, sum w*lx) -- makes the loglik O(1) per eval."""
    W = float(np.sum(w))
    S1 = float(np.sum(w * lx))
    S2 = float(np.sum(w * lx * lx))
    return W, S1, S2


LN_SIGMA_MAX = 6.0          # log-notional sd; 6 is already absurd for money
LN_MU_SLACK = 30.0          # how far below ln(u) mu may wander


def _ln_trunc_negll(p, S, lu, lC):
    W, S1, S2 = S
    mu, ls = p[0], p[1]
    if ls < -3.0 or ls > np.log(LN_SIGMA_MAX) or mu < lu - LN_MU_SLACK or mu > lC + 10.0:
        return 1e12
    s = np.exp(ls)
    mass = float(ndtr((lC - mu) / s) - ndtr((lu - mu) / s))
    if mass <= 1e-300:
        return 1e12
    quad = (S2 - 2.0 * mu * S1 + mu * mu * W) / (s * s)
    ll = -0.5 * quad - 0.5 * W * _LOG2PI - W * ls - S1 - W * np.log(mass)
    return -ll if np.isfinite(ll) else 1e12


def lognorm_trunc_mle(x, w, u, C):
    lx, lu, lC = np.log(x), np.log(u), np.log(C)
    S = _suffstats(lx, w)
    W, S1, S2 = S
    m0 = S1 / W
    s0 = float(np.sqrt(max(S2 / W - m0 * m0, 1e-6)))
    best = None
    for mu0 in (m0, m0 - 1.0, m0 - 3.0, lu):
        for sg0 in (s0, 2 * s0, 1.0, 2.5):
            r = optimize.minimize(_ln_trunc_negll, [mu0, np.log(sg0)],
                                  args=(S, lu, lC), method="Nelder-Mead",
                                  options={"maxiter": 4000, "xatol": 1e-9, "fatol": 1e-9})
            if best is None or r.fun < best.fun:
                best = r
    return float(best.x[0]), float(np.exp(best.x[1])), -float(best.fun)


def _ln_cens_negll(p, S, lu, lC, n_cap):
    W, S1, S2 = S
    mu, ls = p[0], p[1]
    if ls < -3.0 or ls > np.log(LN_SIGMA_MAX) or mu < lu - LN_MU_SLACK or mu > lC + 10.0:
        return 1e12
    s = np.exp(ls)
    Su = float(ndtr(-(lu - mu) / s))
    SC = float(ndtr(-(lC - mu) / s))
    if Su <= 1e-300 or SC <= 1e-300:
        return 1e12
    quad = (S2 - 2.0 * mu * S1 + mu * mu * W) / (s * s)
    ll = (-0.5 * quad - 0.5 * W * _LOG2PI - W * ls - S1 - W * np.log(Su)
          + n_cap * (np.log(SC) - np.log(Su)))
    return -ll if np.isfinite(ll) else 1e12


def lognorm_censored_mle(x, w, u, C, n_cap):
    lx, lu, lC = np.log(x), np.log(u), np.log(C)
    S = _suffstats(lx, w)
    W, S1, S2 = S
    m0 = S1 / W
    s0 = float(np.sqrt(max(S2 / W - m0 * m0, 1e-6)))
    best = None
    for mu0 in (m0, m0 - 1.0, m0 - 3.0, lu):
        for sg0 in (s0, 2 * s0, 1.0, 2.5):
            r = optimize.minimize(_ln_cens_negll, [mu0, np.log(sg0)],
                                  args=(S, lu, lC, n_cap), method="Nelder-Mead",
                                  options={"maxiter": 4000, "xatol": 1e-9, "fatol": 1e-9})
            if best is None or r.fun < best.fun:
                best = r
    return float(best.x[0]), float(np.exp(best.x[1])), -float(best.fun)


def lognorm_cdf_trunc(q, mu, s, u, C):
    q = np.asarray(q, dtype=float)
    F = ndtr((np.log(q) - mu) / s)
    Fu = ndtr((np.log(u) - mu) / s)
    FC = ndtr((np.log(C) - mu) / s)
    return (F - Fu) / (FC - Fu)


def lognorm_tail_ratio(mu, s, u, C):
    return stats.norm.sf((np.log(C) - mu) / s) / stats.norm.sf((np.log(u) - mu) / s)


def lognorm_mean_above(mu, s, C):
    z = (np.log(C) - mu) / s
    sf = stats.norm.sf(z)
    if sf <= 0:
        return float("nan")
    return np.exp(mu + 0.5 * s * s) * stats.norm.sf(z - s) / sf


# ===========================================================================
def weighted_ks(x, w, cdf):
    """Weighted two-sided KS statistic against a continuous cdf callable."""
    o = np.argsort(x)
    xs, ws = x[o], w[o]
    W = ws.sum()
    upper = np.cumsum(ws) / W
    lower = upper - ws / W
    F = cdf(xs)
    return float(max(np.max(np.abs(upper - F)), np.max(np.abs(F - lower))))


# ===========================================================================
def fit_cell(x, w, u, C, n_cap):
    """All four fits + diagnostics for one (band, vintage) cell."""
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    keep = (x >= u) & (x < C)
    x, w = x[keep], w[keep]
    W = float(w.sum())
    if W < 200 or len(x) < 5:
        return None

    a_t = pareto_trunc_mle(x, w, u, C)
    a_c = pareto_censored_mle(x, w, u, C, n_cap)
    ll_p = pareto_loglik_trunc(a_t, x, w, u, C)
    mu_t, s_t, ll_l = lognorm_trunc_mle(x, w, u, C)
    mu_c, s_c, _ = lognorm_censored_mle(x, w, u, C, n_cap)

    ks_p = weighted_ks(x, w, lambda q: pareto_cdf_trunc(q, a_t, u, C))
    ks_l = weighted_ks(x, w, lambda q: lognorm_cdf_trunc(q, mu_t, s_t, u, C))

    # predicted capped count from each fit:  n_sub * p/(1-p),  p = S(C)/S(u)
    def pred(p):
        return W * p / (1.0 - p) if 0 < p < 1 else float("nan")

    p_par_t = pareto_tail_ratio(a_t, u, C)
    p_par_c = pareto_tail_ratio(a_c, u, C)
    p_ln_t = lognorm_tail_ratio(mu_t, s_t, u, C)
    p_ln_c = lognorm_tail_ratio(mu_c, s_c, u, C)

    return {
        "u": u, "C": C, "n_sub": W, "n_cap": n_cap,
        "par_alpha_trunc": a_t, "par_alpha_cens": a_c,
        "ln_mu_trunc": mu_t, "ln_sigma_trunc": s_t,
        "ln_mu_cens": mu_c, "ln_sigma_cens": s_c,
        "loglik_pareto": ll_p, "loglik_lognorm": ll_l,
        "aic_pareto": 2 * 1 - 2 * ll_p, "aic_lognorm": 2 * 2 - 2 * ll_l,
        "ks_pareto": ks_p, "ks_lognorm": ks_l,
        "pred_ncap_par_trunc": pred(p_par_t), "pred_ncap_par_cens": pred(p_par_c),
        "pred_ncap_ln_trunc": pred(p_ln_t), "pred_ncap_ln_cens": pred(p_ln_c),
        "E_above_par_trunc": pareto_mean_above(a_t, C),
        "E_above_par_cens": pareto_mean_above(a_c, C),
        "E_above_ln_trunc": lognorm_mean_above(mu_t, s_t, C),
        "E_above_ln_cens": lognorm_mean_above(mu_c, s_c, C),
        "par_mean_exists_trunc": bool(np.isfinite(a_t) and a_t > 1.0),
        "par_mean_exists_cens": bool(np.isfinite(a_c) and a_c > 1.0),
        # sigma pinned at the box edge means the lognormal has collapsed onto a
        # power-law mimic: it fits inside [u,C) and extrapolates to nonsense.
        "ln_degenerate": bool(s_t > 0.98 * LN_SIGMA_MAX or s_c > 0.98 * LN_SIGMA_MAX),
    }


# ===========================================================================
def selftest() -> int:
    """Recover known parameters from simulated right-truncated samples."""
    rng = np.random.default_rng(20260811)
    fails = []
    print("=" * 78)
    print("SELFTEST 1: Pareto -- simulate alpha, truncate at C, recover alpha")
    print("=" * 78)
    print(f"{'true a':>7} {'u':>10} {'C':>12} {'n_sub':>7} {'n_cap':>6} "
          f"{'a_trunc':>8} {'a_cens':>8} {'a_naiveHill':>12}")
    for a_true in (0.8, 1.2, 1.8, 2.5):
        u, C, N = 5e7, 5e8, 120_000
        z = u * (rng.random(N) ** (-1.0 / a_true))          # Pareto(u, a_true)
        sub = z[z < C]
        n_cap = int((z >= C).sum())
        w = np.ones_like(sub)
        a_t = pareto_trunc_mle(sub, w, u, C)
        a_c = pareto_censored_mle(sub, w, u, C, n_cap)
        a_h = len(sub) / np.sum(np.log(sub / u))            # naive Hill, no truncation
        print(f"{a_true:>7.2f} {u:>10.3g} {C:>12.3g} {len(sub):>7} {n_cap:>6} "
              f"{a_t:>8.4f} {a_c:>8.4f} {a_h:>12.4f}")
        if abs(a_t - a_true) > 0.05 * a_true:
            fails.append(f"pareto trunc MLE off: true {a_true}, got {a_t:.4f}")
        if abs(a_c - a_true) > 0.05 * a_true:
            fails.append(f"pareto censored MLE off: true {a_true}, got {a_c:.4f}")
        if a_true <= 1.8 and abs(a_h - a_true) < 0.05 * a_true:
            fails.append(f"naive Hill was NOT biased at a={a_true} -- selftest is not "
                         "exercising the truncation correction")

    print()
    print("=" * 78)
    print("SELFTEST 2: lognormal -- simulate (mu,sigma), truncate, recover")
    print("=" * 78)
    print(f"{'true mu':>8} {'true s':>7} {'n_sub':>7} {'n_cap':>6} "
          f"{'mu_tr':>8} {'s_tr':>7} {'mu_cn':>8} {'s_cn':>7}")
    for mu_true, s_true in ((17.0, 1.2), (16.0, 1.8), (18.0, 0.9)):
        u, C, N = 5e7, 5e8, 120_000
        z = np.exp(rng.normal(mu_true, s_true, N))
        z = z[z >= u]
        sub = z[z < C]
        n_cap = int((z >= C).sum())
        if len(sub) < 500 or n_cap < 50:
            continue
        w = np.ones_like(sub)
        mt, st, _ = lognorm_trunc_mle(sub, w, u, C)
        mc, sc, _ = lognorm_censored_mle(sub, w, u, C, n_cap)
        print(f"{mu_true:>8.2f} {s_true:>7.2f} {len(sub):>7} {n_cap:>6} "
              f"{mt:>8.3f} {st:>7.3f} {mc:>8.3f} {sc:>7.3f}")
        if abs(mc - mu_true) > 0.15 or abs(sc - s_true) > 0.12:
            fails.append(f"lognorm censored off: true ({mu_true},{s_true}) "
                         f"got ({mc:.3f},{sc:.3f})")

    print()
    print("=" * 78)
    print("SELFTEST 3: E[X|X>C] and predicted capped count against simulation truth")
    print("=" * 78)
    print(f"{'true a':>7} {'sim E[X|X>C]':>14} {'fit trunc':>12} {'fit cens':>12} "
          f"{'obs ncap':>9} {'pred cens':>10}")
    for a_true in (1.2, 1.8, 2.5):
        u, C, N = 5e7, 5e8, 400_000
        z = u * (rng.random(N) ** (-1.0 / a_true))
        sub, above = z[z < C], z[z >= C]
        n_cap = len(above)
        w = np.ones_like(sub)
        a_t = pareto_trunc_mle(sub, w, u, C)
        a_c = pareto_censored_mle(sub, w, u, C, n_cap)
        p = pareto_tail_ratio(a_c, u, C)
        pred = len(sub) * p / (1 - p)
        print(f"{a_true:>7.2f} {above.mean():>14.4g} "
              f"{pareto_mean_above(a_t, C):>12.4g} {pareto_mean_above(a_c, C):>12.4g} "
              f"{n_cap:>9} {pred:>10.0f}")
        if abs(pred - n_cap) / n_cap > 0.05:
            fails.append(f"predicted ncap off at a={a_true}: {pred:.0f} vs {n_cap}")
        if a_true > 1 and abs(pareto_mean_above(a_c, C) - above.mean()) / above.mean() > 0.10:
            fails.append(f"E[X|X>C] off at a={a_true}")

    print()
    print("=" * 78)
    print("SELFTEST 4: model discrimination -- lognormal data must NOT prefer Pareto")
    print("=" * 78)
    u, C = 5e7, 5e8
    z = np.exp(rng.normal(17.2, 1.1, 200_000))
    z = z[(z >= u)]
    sub = z[z < C]
    n_cap = int((z >= C).sum())
    w = np.ones_like(sub)
    r = fit_cell(sub, w, u, C, n_cap)
    print(f"  lognormal-generated: aic_lognorm={r['aic_lognorm']:.1f}  "
          f"aic_pareto={r['aic_pareto']:.1f}  "
          f"ks_ln={r['ks_lognorm']:.4f}  ks_par={r['ks_pareto']:.4f}  "
          f"-> {'lognormal' if r['aic_lognorm'] < r['aic_pareto'] else 'PARETO (WRONG)'}")
    if r["ks_lognorm"] >= r["ks_pareto"]:
        fails.append("KS picked Pareto on lognormal-generated data")

    a_true = 1.6
    z = u * (rng.random(200_000) ** (-1.0 / a_true))
    sub = z[z < C]
    n_cap = int((z >= C).sum())
    w = np.ones_like(sub)
    r = fit_cell(sub, w, u, C, n_cap)
    print(f"  Pareto-generated   : aic_lognorm={r['aic_lognorm']:.1f}  "
          f"aic_pareto={r['aic_pareto']:.1f}  "
          f"ks_ln={r['ks_lognorm']:.4f}  ks_par={r['ks_pareto']:.4f}  "
          f"-> {'Pareto' if r['aic_pareto'] < r['aic_lognorm'] else 'LOGNORMAL (WRONG)'}")
    print(f"  NOTE: over one decade [u,C) the AIC gap is "
          f"{abs(r['aic_pareto']-r['aic_lognorm']):.1f} on a loglik of "
          f"{abs(r['loglik_pareto']):.3g} -- AIC barely discriminates; KS does.")
    if r["ks_pareto"] >= r["ks_lognorm"]:
        fails.append("KS picked lognormal on Pareto-generated data")

    print()
    print("=" * 78)
    print("SELFTEST 5: grouped-frequency path == raw path (this is how the tape is fed)")
    print("=" * 78)
    u, C = 5e7, 5e8
    z = u * (rng.random(200_000) ** (-1.0 / 1.7))
    sub = z[z < C]
    n_cap = int((z >= C).sum())
    # round to $1mm the way Part 43 Appendix A rounds, then collapse to counts
    g = np.round(sub / 1e6) * 1e6
    g = g[(g >= u) & (g < C)]
    vals, cnts = np.unique(g, return_counts=True)
    a_raw = pareto_censored_mle(g, np.ones_like(g), u, C, n_cap)
    a_grp = pareto_censored_mle(vals, cnts.astype(float), u, C, n_cap)
    m_raw = lognorm_censored_mle(g, np.ones_like(g), u, C, n_cap)
    m_grp = lognorm_censored_mle(vals, cnts.astype(float), u, C, n_cap)
    print(f"  raw n={len(g):,} distinct={len(vals):,}")
    print(f"  pareto alpha   raw {a_raw:.6f}  grouped {a_grp:.6f}  "
          f"diff {abs(a_raw-a_grp):.2e}")
    print(f"  lognorm mu     raw {m_raw[0]:.6f}  grouped {m_grp[0]:.6f}")
    print(f"  lognorm sigma  raw {m_raw[1]:.6f}  grouped {m_grp[1]:.6f}")
    e_raw = lognorm_mean_above(m_raw[0], m_raw[1], C)
    e_grp = lognorm_mean_above(m_grp[0], m_grp[1], C)
    print(f"  lognorm E[X|X>C] raw {e_raw:.6g}  grouped {e_grp:.6g}  "
          f"rel diff {abs(e_raw-e_grp)/e_raw:.2e}")
    if abs(a_raw - a_grp) > 1e-6 or abs(e_raw - e_grp) / e_raw > 1e-3:
        fails.append("grouped-frequency path disagrees with the raw path")

    print()
    if fails:
        print("SELFTEST FAILED")
        for f in fails:
            print("  -", f)
        return 1
    print("SELFTEST PASSED")
    return 0


# ===========================================================================
def run_tape(u_div: float = 10.0) -> int:
    import warnings

    import psycopg2

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    with open(os.path.join(OUT, "partB_cap_schedule.json")) as fh:
        sched = json.load(fh)
    switch = sched["switch_date"]
    bands = sched["bands"]
    print(f"schedule: {len(bands)} (band x vintage) cells, vintage switch {switch}")

    # one CASE that names the cell for every flow leg
    whens = []
    for i, b in enumerate(bands):
        vcond = ("as_of_date <  DATE '%s'" % switch) if b["vintage"] == "V1" \
            else ("as_of_date >= DATE '%s'" % switch)
        whens.append(
            f"WHEN {vcond} AND tenor_years >= {b['lo']} AND tenor_years < {b['hi']} "
            f"THEN '{b['vintage']}|{b['lo']}|{b['hi']}|{b['cap']:.0f}'")
    CELL = "CASE\n  " + "\n  ".join(whens) + "\n  ELSE NULL END"

    conn = psycopg2.connect(resolve_pg_url())

    def q(sql):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return pd.read_sql(sql, conn)

    FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"
    print("pulling the (cell x notional) frequency table ...")
    freq = q(f"""
        SELECT {CELL} AS cell, is_capped, notional,
               count(*) AS n,
               sum(tenor_years) AS sum_t,
               sum(notional * tenor_years * 1e-4) AS sum_dv01
        FROM {LEGS_TABLE}
        WHERE {FLOW} AND tenor_years > 0 AND notional > 0 AND notional < 1e11
        GROUP BY 1, 2, 3
    """)
    conn.close()
    print(f"  {len(freq):,} (cell, is_capped, notional) rows")
    unassigned = freq[freq["cell"].isna()]
    print(f"  rows not assigned to any band: n={int(unassigned['n'].sum()):,} "
          f"({unassigned['n'].sum()/freq['n'].sum():.3%} of flow legs) "
          f"-- tenors in the gaps between derived bands")

    freq = freq.dropna(subset=["cell"]).copy()
    meta = freq["cell"].str.split("|", expand=True)
    freq["vintage"] = meta[0]
    freq["lo"] = meta[1].astype(float)
    freq["hi"] = meta[2].astype(float)
    freq["cap"] = meta[3].astype(float)
    freq["notional"] = freq["notional"].astype(float)
    freq["n"] = freq["n"].astype(float)
    freq["sum_dv01"] = freq["sum_dv01"].astype(float)
    freq["mean_t"] = freq["sum_t"].astype(float) / freq["n"]

    results, summary = [], []
    for cell, g in freq.groupby("cell", sort=True):
        C = g["cap"].iloc[0]
        vin, lo, hi = g["vintage"].iloc[0], g["lo"].iloc[0], g["hi"].iloc[0]
        cap_rows = g[g["is_capped"]]
        sub_rows = g[~g["is_capped"]]
        n_cap = float(cap_rows["n"].sum())
        # capped prints not sitting exactly on C are bucket-edge noise: drop
        n_cap_at_C = float(cap_rows.loc[cap_rows["notional"] == C, "n"].sum())
        u = C / u_div

        tail = sub_rows[(sub_rows["notional"] >= u) & (sub_rows["notional"] < C)]
        fit = fit_cell(tail["notional"].to_numpy(), tail["n"].to_numpy(),
                       u, C, n_cap_at_C) if len(tail) else None

        tot_n = float(g["n"].sum())
        tot_notional = float((g["notional"] * g["n"]).sum())
        tot_dv01 = float(g["sum_dv01"].sum())
        cap_mean_t = float((cap_rows["sum_t"].astype(float)).sum() / n_cap) if n_cap else np.nan

        rec = {"vintage": vin, "lo": lo, "hi": hi, "cap": C,
               "n_all": tot_n, "n_cap": n_cap, "n_cap_at_C": n_cap_at_C,
               "cap_share": n_cap / tot_n,
               "tot_notional": tot_notional, "tot_dv01": tot_dv01,
               "cap_mean_tenor": cap_mean_t,
               "notional_at_cap_face": n_cap_at_C * C}
        if fit:
            rec.update(fit)
        summary.append(rec)
        if fit:
            results.append({"cell": cell, **fit})

    S = pd.DataFrame(summary).sort_values(["vintage", "lo"]).reset_index(drop=True)
    S.to_csv(os.path.join(OUT, "partB_tail_fits.csv"), index=False)

    pd.set_option("display.float_format", lambda v: f"{v:,.4g}")
    print("\n===== T1. cell sizes and cap share =====")
    print(S[["vintage", "lo", "hi", "cap", "n_all", "n_cap", "n_cap_at_C",
             "cap_share", "n_sub"]].to_string(index=False))

    print("\n===== T2. fits: parameters =====")
    print(S[["vintage", "lo", "hi", "cap", "n_sub", "par_alpha_trunc",
             "par_alpha_cens", "ln_mu_trunc", "ln_sigma_trunc", "ln_mu_cens",
             "ln_sigma_cens"]].to_string(index=False))

    print("\n===== T3. model comparison (lower AIC / KS is better) =====")
    cmp = S[["vintage", "lo", "hi", "cap", "n_sub", "loglik_pareto",
             "loglik_lognorm", "aic_pareto", "aic_lognorm", "ks_pareto",
             "ks_lognorm"]].copy()
    cmp["better_aic"] = np.where(cmp["aic_lognorm"] < cmp["aic_pareto"],
                                 "lognormal", "pareto")
    cmp["better_ks"] = np.where(cmp["ks_lognorm"] < cmp["ks_pareto"],
                                "lognormal", "pareto")
    print(cmp.to_string(index=False))

    print("\n===== T4. predicted vs observed capped count (the fit's own test) =====")
    chk = S[["vintage", "lo", "hi", "cap", "n_cap_at_C", "pred_ncap_par_trunc",
             "pred_ncap_par_cens", "pred_ncap_ln_trunc", "pred_ncap_ln_cens"]].copy()
    for c in ("pred_ncap_par_trunc", "pred_ncap_ln_trunc", "pred_ncap_ln_cens"):
        chk[c.replace("pred_ncap", "err")] = chk[c] / chk["n_cap_at_C"] - 1.0
    print(chk.to_string(index=False))

    print("\n===== T5. E[notional | notional > cap], and does the mean exist? =====")
    em = S[["vintage", "lo", "hi", "cap", "par_alpha_cens", "par_mean_exists_cens",
            "E_above_par_cens", "E_above_par_trunc", "E_above_ln_cens",
            "E_above_ln_trunc"]].copy()
    em["par_mult"] = em["E_above_par_cens"] / em["cap"]
    em["ln_mult"] = em["E_above_ln_cens"] / em["cap"]
    print(em.to_string(index=False))

    # ---------------- imputed fractions ------------------------------------
    print("\n===== T6. imputed share of notional and of the DV01 proxy =====")
    for model, col in (("lognormal (censored)", "E_above_ln_cens"),
                       ("pareto (censored)", "E_above_par_cens")):
        T = S.copy()
        T["E"] = T[col]
        T["excess_notional"] = T["n_cap_at_C"] * np.maximum(T["E"] - T["cap"], 0.0)
        T["excess_dv01"] = (T["excess_notional"] * T["cap_mean_tenor"] * 1e-4)
        T["tot_notional_imp"] = T["tot_notional"] + T["excess_notional"]
        T["tot_dv01_imp"] = T["tot_dv01"] + T["excess_dv01"]
        T["imp_share_notional"] = T["excess_notional"] / T["tot_notional_imp"]
        T["imp_share_dv01"] = T["excess_dv01"] / T["tot_dv01_imp"]
        print(f"\n--- {model} ---")
        print(T[["vintage", "lo", "hi", "cap", "cap_share", "tot_notional",
                 "excess_notional", "imp_share_notional", "tot_dv01",
                 "excess_dv01", "imp_share_dv01"]].to_string(index=False))
        tot = T[["tot_notional", "excess_notional", "tot_dv01", "excess_dv01"]].sum()
        print(f"  OVERALL  notional observed {tot['tot_notional']:,.4g}  "
              f"imputed excess {tot['excess_notional']:,.4g}  "
              f"=> imputed share {tot['excess_notional']/(tot['tot_notional']+tot['excess_notional']):.3%}")
        print(f"  OVERALL  dv01     observed {tot['tot_dv01']:,.4g}  "
              f"imputed excess {tot['excess_dv01']:,.4g}  "
              f"=> imputed share {tot['excess_dv01']/(tot['tot_dv01']+tot['excess_dv01']):.3%}")
        T.to_csv(os.path.join(OUT, f"partB_imputed_{col}.csv"), index=False)

    print(f"\nwrote {os.path.join(OUT, 'partB_tail_fits.csv')}")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    div = 10.0
    for a in sys.argv[1:]:
        if a.startswith("--udiv="):
            div = float(a.split("=", 1)[1])
    raise SystemExit(run_tape(div))

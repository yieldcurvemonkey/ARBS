"""Settle the upfront rule's sign, its cap exposure and its termination behaviour.

Reads the priced samples written by ``uf02_price.py`` and answers, in order:

  A. the sign, empirically -- on the 275,540-leg population where the rate rule
     and the upfront rule both apply, how often do they agree, and what does the
     disagreement stratum look like;
  B. tau_upfront -- fit the symmetric mixture on ``z = (|f| - U)/DV01`` per
     population, and check ``h_upfront`` against the rate rule's own ``h``;
  C. the capped-print inversion -- ``|NPV|/U`` capped vs uncapped, which is
     scale-free in notional and therefore needs no size matching;
  D. terminations -- does ``U/|f|`` cluster near 1, i.e. does the mechanism
     work at all before anyone asks about its confidence.

``--selftest`` runs the whole analysis machinery over synthetic rows whose
answers are known by hand, plus a mixture-recovery check against the closed-form
moment estimator in DESIGN 1.2. Run it before believing anything below.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from scipy import optimize

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import upfront as up

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

SCRATCH = "C:/Users/chris/clee/ARBS-dd/scratch"
# F-17 band edges, in years.
BANDS = [0.12, 0.30, 0.54, 1.04, 2.25, 5.25, 10.5, 31.0]
CAP_VINTAGE_SWITCH = pd.Timestamp("2024-10-07").date()


def load(name: str) -> pd.DataFrame:
    df = pd.read_csv(f"{SCRATCH}/uf02_{name}.csv")
    df = df[df["error"].isna()].copy()
    df["as_of_date"] = pd.to_datetime(df["as_of_date"]).dt.date
    df["pv01"] = df["pv01"].abs()
    df["abs_npv"] = df["npv_pay"].abs()
    df["u"] = df["other_payment_ufro"].fillna(0.0)
    df["band"] = np.digitize(df["tenor_years"].fillna(0.0), BANDS)
    df["vintage"] = np.where(
        pd.to_datetime(df["as_of_date"]) < pd.Timestamp(CAP_VINTAGE_SWITCH), "V1", "V2")
    return df


# --------------------------------------------------------------------------
# the two rules, both taken from the shipped module rather than re-derived
# --------------------------------------------------------------------------

def rule_signs(df: pd.DataFrame, *, is_lifecycle=False) -> pd.DataFrame:
    out = df.copy()
    out["rate_sign"] = [conv.dealer_side(d) for d in out["dev_bps"]]
    calls = [up.classify(npv_pay=n, upfront=u, structure_dv01=p,
                         is_lifecycle=is_lifecycle, exclude_capped=False)
             for n, u, p in zip(out["npv_pay"], out["u"], out["pv01"])]
    out["upfront_sign"] = [c.dealer_sign for c in calls]
    out["edge_bps"] = [c.edge_bps for c in calls]
    out["z_bps"] = [c.residual_bps for c in calls]
    out["u_bps"] = [c.upfront_bps for c in calls]
    out["ratio"] = out["u_bps"] / out["dev_bps"].abs()
    return out


def agreement_table(df: pd.DataFrame, by) -> pd.DataFrame:
    d = df[(df["rate_sign"] != 0) & (df["upfront_sign"] != 0)]
    g = d.groupby(by)
    return pd.DataFrame({
        "n": g.size(),
        "agree": g.apply(lambda x: (x["rate_sign"] == x["upfront_sign"]).mean()),
        "med_|dev|": g["dev_bps"].apply(lambda s: s.abs().median()),
        "med_u_bps": g["u_bps"].median(),
        "med_ratio": g["ratio"].median(),
    })


# --------------------------------------------------------------------------
# the mixture fitter used ONLY here, injected into the module's fit_tau_upfront
# --------------------------------------------------------------------------

def _phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def mixture_mle(x):
    """Symmetric two-component MLE: ``0.5 N(b0+h, s^2) + 0.5 N(b0-h, s^2)``.

    Equal weights are imposed, not fitted (DESIGN 1.2): a free weight is not
    identifiable from ``b0`` at realistic separations and would absorb a curve
    bias as a flow imbalance. Lives in the measurement harness, not in
    ``upfront.py`` -- the shipped module takes the fitter as a dependency so
    there is exactly one estimator in the package once ``probability.py`` lands.
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    lo, hi = np.percentile(x, [2.5, 97.5])
    x = x[(x >= lo) & (x <= hi)]                    # trimmed, as specified

    def nll(theta):
        # TRUNCATED likelihood. Trimming without the ``log(mass)`` term is not
        # a robustified MLE, it is a biased one: the selftest recovered
        # s = 0.417 for a true 0.50 and h = 0.572 for a true 0.60, both low,
        # because the discarded tails are exactly the mass that sets the scale.
        b0, log_h, log_s = theta
        h, s = math.exp(log_h), math.exp(log_s)
        za, zb = (x - b0 - h) / s, (x - b0 + h) / s
        m = np.maximum(-0.5 * za ** 2, -0.5 * zb ** 2)
        dens = np.exp(-0.5 * za ** 2 - m) + np.exp(-0.5 * zb ** 2 - m)
        mass = 0.5 * (_phi((hi - b0 - h) / s) - _phi((lo - b0 - h) / s)
                      + _phi((hi - b0 + h) / s) - _phi((lo - b0 + h) / s))
        return (-np.sum(m + np.log(dens + 1e-300))
                + len(x) * (log_s + math.log(2 * math.sqrt(2 * math.pi)))
                + len(x) * math.log(max(mass, 1e-12)))

    sd = x.std(ddof=1)
    best = None
    for h0 in (0.25 * sd, 0.6 * sd, 0.9 * sd):
        r = optimize.minimize(
            nll, [np.median(x), math.log(max(h0, 1e-6)), math.log(max(sd / 2, 1e-6))],
            method="Nelder-Mead",
            options={"maxiter": 4000, "xatol": 1e-8, "fatol": 1e-8})
        if best is None or r.fun < best.fun:
            best = r
    b0, log_h, log_s = best.x
    return {"b0": float(b0), "h": float(math.exp(log_h)), "s": float(math.exp(log_s))}


def moment_check(x):
    """DESIGN 1.2's closed form. Real only when the sample is platykurtic."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    lo, hi = np.percentile(x, [2.5, 97.5])
    x = x[(x >= lo) & (x <= hi)]
    m2 = np.mean((x - x.mean()) ** 2)
    m4 = np.mean((x - x.mean()) ** 4)
    disc = m2 ** 2 - (m4 - m2 ** 2) / 2.0
    if disc < 0:
        return None, None, (m4 / m2 ** 2 - 3.0)
    s2 = m2 - math.sqrt(disc)
    return math.sqrt(max(s2, 0.0)), math.sqrt(max(m2 - s2, 0.0)), (m4 / m2 ** 2 - 3.0)


def robust_scale(x) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def fit_report(label: str, z, population: str) -> None:
    z = np.asarray(z, float)
    z = z[np.isfinite(z)]
    if len(z) < 50:
        print(f"{label:28s} n={len(z)} -- too few")
        return
    s_m, h_m, exk = moment_check(z)
    mm = (f"moment s={s_m:.3f} h={h_m:.3f}" if s_m is not None
          else "moment: LEPTOKURTIC, no real solution")
    tail = (f"  [{mm}, exkurt {exk:+.2f}, MAD-sigma {robust_scale(z):.3f}, "
            f"med|z| {np.median(np.abs(z)):.3f}]")
    try:
        tau = up.fit_tau_upfront(z, population=population, bucket=label,
                                 mixture_fit=mixture_mle)
    except ValueError as exc:
        print(f"{label:28s} n={len(z):5d}  MIXTURE REFUSED: {str(exc)[:60]}...{tail}")
        return
    print(f"{label:28s} n={tau.n:5d}  b0={tau.bias_bps:+.3f}  h={tau.half_spread_bps:.3f}"
          f"  s={tau.sigma_bps:.3f}  tau={tau.tau_bps:.3f} bp{tail}")


# --------------------------------------------------------------------------

def selftest() -> None:
    print("=== SELFTEST: known answers before any tape number is believed ===")
    # 1. the agreement calculator, by hand.
    #    dev=+2bp, u=1bp  -> u<|dev| -> rules AGREE, both RECEIVED
    #    dev=+2bp, u=3bp  -> u>|dev| -> DISAGREE (upfront says PAID)
    #    dev=-2bp, u=1bp  -> AGREE, both PAID
    #    dev=-2bp, u=3bp  -> DISAGREE (upfront says RECEIVED)
    pv01 = 10_000.0
    rows = [(+2.0, 1.0, +1, +1), (+2.0, 3.0, +1, -1),
            (-2.0, 1.0, -1, -1), (-2.0, 3.0, -1, +1)]
    df = pd.DataFrame([{
        "dev_bps": d, "npv_pay": -d * pv01, "u": u * pv01, "pv01": pv01,
        "tenor_years": 5.0, "as_of_date": pd.Timestamp("2025-01-02").date(),
        "abs_npv": abs(d) * pv01, "other_payment_ufro": u * pv01,
        "error": None, "band": 5, "vintage": "V2",
    } for d, u, _, _ in rows])
    got = rule_signs(df)
    assert list(got["rate_sign"]) == [r[2] for r in rows], got["rate_sign"].tolist()
    assert list(got["upfront_sign"]) == [r[3] for r in rows], got["upfront_sign"].tolist()
    assert agreement_table(got, "band")["agree"].iloc[0] == 0.5
    print("  agreement calculator: 4/4 hand-computed cases OK, agree=0.50")

    # 2. mixture recovery on a synthetic sample with a known (b0, h, s).
    rng = np.random.default_rng(7)
    for b0, h, s in [(0.0, 1.0, 0.4), (0.2, 0.6, 0.5), (-0.1, 2.0, 0.8)]:
        n = 20_000
        z = b0 + h * rng.choice([-1.0, 1.0], n) + s * rng.standard_normal(n)
        fit = mixture_mle(z)
        assert abs(fit["b0"] - b0) < 0.05, fit
        assert abs(fit["h"] - h) / h < 0.06, fit
        assert abs(fit["s"] - s) / s < 0.12, fit
        print(f"  mixture recovery b0={b0:+.2f} h={h:.2f} s={s:.2f} -> "
              f"{fit['b0']:+.3f} {fit['h']:.3f} {fit['s']:.3f}")

    # 3. a pure-noise sample must NOT report a confident half-spread.
    z = 0.3 * rng.standard_normal(20_000)
    fit = mixture_mle(z)
    print(f"  pure noise (h=0) -> h={fit['h']:.3f} s={fit['s']:.3f} "
          f"(tau={fit['s']**2/(2*fit['h']):.2f}: a large tau is the honest answer)")
    print("  SELFTEST PASSED\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return

    # -----------------------------------------------------------------
    print("=== 0. the harness reproduces F-15 on the on-market control ===")
    ctl = load("onmkt_control")
    print(f"n={len(ctl)}  median dev {ctl['dev_bps'].median():+.4f} bp  "
          f"IQR [{ctl['dev_bps'].quantile(.25):+.4f}, {ctl['dev_bps'].quantile(.75):+.4f}]  "
          f"within +-0.1bp {(ctl['dev_bps'].abs()<=0.1).mean():.3f}   "
          f"(F-15: +0.021, [-0.096,+0.170], 0.405)")
    ctl_fit = mixture_mle(ctl["dev_bps"].values)
    s_mid = (ctl["dev_bps"].quantile(.75) - ctl["dev_bps"].quantile(.25)) / 1.349
    print(f"rate-rule mixture on the control: b0={ctl_fit['b0']:+.4f} "
          f"h={ctl_fit['h']:.4f} s={ctl_fit['s']:.4f}  "
          f"(h -> 0 means the two components are not separable here); "
          f"robust s from the IQR = {s_mid:.4f} bp")

    # -----------------------------------------------------------------
    print("\n=== A. THE SIGN: rate rule vs upfront rule, where both apply ===")
    flow = rule_signs(load("flow_fee"))
    dec = flow[(flow["rate_sign"] != 0) & (flow["upfront_sign"] != 0)]
    agree = (dec["rate_sign"] == dec["upfront_sign"]).mean()
    print(f"n decisive = {len(dec)} of {len(flow)}")
    print(f"AGREEMENT (derived sign)  = {agree:.4f}")
    print(f"AGREEMENT (inverted sign) = {1-agree:.4f}")
    print(f"  rate rule   RECEIVED {(dec['rate_sign']>0).mean():.3f}")
    print(f"  upfront rule RECEIVED {(dec['upfront_sign']>0).mean():.3f}")

    dec = dec.copy()
    dec["ratio_bin"] = pd.cut(dec["ratio"], [0, 0.25, 0.5, 0.9, 1.1, 2.0, 5.0, np.inf])
    print("\nby u/|dev| (agreement is FORCED below 1 and impossible above it -- "
          "the number is the geometry, the strata are the content):")
    print(agreement_table(dec, "ratio_bin").to_string())
    dec["dev_bin"] = pd.cut(dec["dev_bps"].abs(), [0, 0.1, 0.3, 1.0, 3.0, 10.0, np.inf])
    print("\nby |dev| (bp):")
    print(agreement_table(dec, "dev_bin").to_string())
    dec["fee_bin"] = pd.cut(dec["u"], [0, 500, 5_000, 50_000, 500_000, np.inf])
    print("\nby fee size ($; 500 is stir_flow's PTP_USD_FLOOR):")
    print(agreement_table(dec, "fee_bin").to_string())
    print("\nby tenor band:")
    print(agreement_table(dec, "band").to_string())

    print("\ndoes the fee TRACK the rate deviation on the disagreement stratum?")
    for name, sub in (("agree (u<|dev|)", dec[dec["ratio"] < 1]),
                      ("disagree (u>|dev|)", dec[dec["ratio"] >= 1])):
        if not len(sub):
            continue
        print(f"  {name:20s} n={len(sub):5d}  median u/|dev| {sub['ratio'].median():.3f}"
              f"  spearman(u,|dev|) {sub['u_bps'].corr(sub['dev_bps'].abs(), method='spearman'):+.3f}"
              f"  median |z| {sub['z_bps'].abs().median():.3f} bp")

    print("\nfragility: how many calls have their SIGN inside the mid's own error?")
    for k in (1.0, 2.0):
        frag = (dec["dev_bps"].abs() <= k * s_mid) & (dec["u_bps"] > dec["dev_bps"].abs())
        print(f"  |dev| <= {k:.0f}*s ({k*s_mid:.3f} bp) and u > |dev|: "
              f"{frag.mean():.4f} of decisive rows")

    # -----------------------------------------------------------------
    print("\n=== B. tau_upfront, fitted on z = (|f| - U)/DV01 ===")
    off = rule_signs(load("offmkt_fee"))
    fit_report("flow_fee ALL", flow["z_bps"], up.POPULATION_FLOW)
    for b, sub in flow.groupby("band"):
        fit_report(f"flow_fee band {b}", sub["z_bps"], up.POPULATION_FLOW)
    fit_report("offmkt_fee ALL", off["z_bps"], up.POPULATION_FLOW)
    term = rule_signs(load("term_fee"), is_lifecycle=True)
    fit_report("term_fee ALL", term["z_bps"], up.POPULATION_LIFECYCLE)

    # -----------------------------------------------------------------
    print("\n=== C. capped prints: |NPV|/U, which is scale-free in notional ===")
    cap = load("capped_fee")
    big = load("uncapped_big_fee")
    for label, d in (("capped", cap), ("uncapped>=250mm", big)):
        r = (d["abs_npv"] / d["u"]).replace([np.inf, -np.inf], np.nan).dropna()
        print(f"  {label:16s} n={len(r):5d}  median |NPV|/U {r.median():.3f}  "
              f"IQR [{r.quantile(.25):.3f}, {r.quantile(.75):.3f}]  "
              f"frac>1 {(r>1).mean():.3f}")
    print("\n  paired by (tenor band, cap vintage) -- the cap is a function of both:")
    rows = []
    for key, c in cap.groupby(["band", "vintage"]):
        b = big[(big["band"] == key[0]) & (big["vintage"] == key[1])]
        if len(c) < 15 or len(b) < 15:
            continue
        rc = (c["abs_npv"] / c["u"]).replace([np.inf, -np.inf], np.nan).dropna()
        rb = (b["abs_npv"] / b["u"]).replace([np.inf, -np.inf], np.nan).dropna()
        rows.append({"band": key[0], "vintage": key[1], "n_cap": len(rc),
                     "n_unc": len(rb), "med_cap": rc.median(), "med_unc": rb.median(),
                     "ratio": rc.median() / rb.median(),
                     "frac>1_cap": (rc > 1).mean(), "frac>1_unc": (rb > 1).mean()})
    print(pd.DataFrame(rows).to_string(index=False) if rows else "  no comparable cells")

    # -----------------------------------------------------------------
    print("\n=== D. terminations: does U/|f| cluster near 1? ===")
    for label, name in (("all fee-bearing", "term_fee"),
                        ("seasoned (>30d past effective)", "term_seasoned")):
        t = rule_signs(load(name), is_lifecycle=True)
        r = (t["u"] / t["abs_npv"]).replace([np.inf, -np.inf], np.nan).dropna()
        print(f"  {label:32s} n={len(r):5d}  median U/|f| {r.median():.3f}  "
              f"IQR [{r.quantile(.25):.3f}, {r.quantile(.75):.3f}]  "
              f"within 10% of 1: {((r-1).abs()<0.1).mean():.3f}")
        print(f"     dealer RECEIVED (side held on the dying swap) "
              f"{(t['upfront_sign']>0).mean():.3f}; "
              f"the FLOW rule would say {(t['upfront_sign']<0).mean():.3f}")
        print(f"     median |edge| {t['edge_bps'].abs().median():.2f} bp "
              f"(a bid-offer is a fraction of a bp)")


if __name__ == "__main__":
    main()

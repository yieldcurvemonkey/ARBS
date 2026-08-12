"""Quadrature error of classify(..., mid_sigma_bps=...) on the REAL sample.

Reference = the same integral on a 40k-point grid over +-12 sigma. Validated
against the u = 0 case (smooth integrand), where GH and the grid agree to 1e-6.
"""
import math
import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import upfront as up

S = 0.2543          # measured mid sigma, bp (uf03 section 0)
TAUB = 3.816        # measured tau_upfront, flow ALL


def ref(dev, u, tau=TAUB, s=S, b=0.0):
    x = np.linspace(dev - 12 * s, dev + 12 * s, 40001)
    w = np.exp(-0.5 * ((x - dev) / s) ** 2)
    w /= w.sum()
    e = np.where(x >= 0, x - (u + b), x + (u + b))
    return float(np.dot(w, 1.0 / (1.0 + np.exp(-np.clip(e / tau, -500, 500)))))


d = pd.read_csv("scratch/uf02_flow_fee.csv")
d = d[d["error"].isna()].copy()
d["pv01"] = d["pv01"].abs()
d["u"] = d["other_payment_ufro"].fillna(0.0)
tau = up.TauUpfront(tau_bps=TAUB, bias_bps=0.0, half_spread_bps=0.0128,
                    sigma_bps=0.3816, n=2025, population=up.POPULATION_FLOW,
                    bucket="ALL")

rows = []
for n, u, p in zip(d["npv_pay"], d["u"], d["pv01"]):
    c = up.classify(npv_pay=n, upfront=u, structure_dv01=p, tau=tau,
                    mid_sigma_bps=S)
    rows.append((c.dev_bps, c.upfront_bps, c.p, ref(c.dev_bps, c.upfront_bps)))
r = pd.DataFrame(rows, columns=["dev", "u_bps", "p_gh", "p_ref"])
r["err"] = r["p_gh"] - r["p_ref"]
r["sw_gh"] = 2 * r["p_gh"] - 1
r["sw_ref"] = 2 * r["p_ref"] - 1

print(f"n = {len(r)}   mid sigma {S} bp, tau {TAUB} bp")
print("  max |p error|          %.4f" % r["err"].abs().max())
print("  mean |p error|         %.5f" % r["err"].abs().mean())
print("  rows |p error| > 0.005 %.3f  (n=%d)"
      % ((r["err"].abs() > 0.005).mean(), int((r["err"].abs() > 0.005).sum())))
print("  rows |p error| > 0.02  %.3f  (n=%d)"
      % ((r["err"].abs() > 0.02).mean(), int((r["err"].abs() > 0.02).sum())))
bad = r[np.sign(r["sw_gh"]) != np.sign(r["sw_ref"])]
print("  rows where signed_weight has the WRONG SIGN  %.3f  (n=%d)"
      % (len(bad) / len(r), len(bad)))
if len(bad):
    print(bad[["dev", "u_bps", "p_gh", "p_ref"]].head(12).to_string(index=False))
print("\n  sum of signed_weight over the sample: GH %+.3f  reference %+.3f"
      % (r["sw_gh"].sum(), r["sw_ref"].sum()))
print("  (an unweighted ladder direction is this sum; the quadrature error "
      "does not cancel)")
print("\n  by |dev| bucket:")
r["bin"] = pd.cut(r["dev"].abs(), [0, 0.05, 0.1, 0.2, 0.5, 1.0, np.inf])
print(r.groupby("bin", observed=True).agg(
    n=("err", "size"), mean_err=("err", "mean"),
    max_abs_err=("err", lambda x: x.abs().max())).to_string())

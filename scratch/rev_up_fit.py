"""Two checks the builder's own script does not make.

1. Do the docstring's "fitted s 0.358 / 0.382 bp" and "tau capped at 2.9-11.0 bp
   by tenor band" reproduce under probability.fit_mixture (the estimator
   fit_tau_upfront actually calls)?
2. Does FLAG_SIGN_FRAGILE cover the population whose SIGN is actually a coin
   flip -- i.e. the rows where z = |dev| - u is inside the mid's error?
"""
import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import probability as prob
from SDRUtils.dealer_direction import upfront as up

BANDS = [0.12, 0.30, 0.54, 1.04, 2.25, 5.25, 10.5, 31.0]


def load(name):
    d = pd.read_csv(f"scratch/uf02_{name}.csv")
    d = d[d["error"].isna()].copy()
    d["pv01"] = d["pv01"].abs()
    d["u"] = d["other_payment_ufro"].fillna(0.0)
    d["band"] = np.digitize(d["tenor_years"].fillna(0.0), BANDS)
    return d


flow = load("flow_fee")
ctrl = load("onmkt_control")
calls = [up.classify(npv_pay=n, upfront=u, structure_dv01=p)
         for n, u, p in zip(flow["npv_pay"], flow["u"], flow["pv01"])]
flow["z"] = [c.residual_bps for c in calls]
flow["dev"] = [c.dev_bps for c in calls]
flow["ub"] = [c.upfront_bps for c in calls]

print("[1] probability.fit_mixture, the estimator fit_tau_upfront calls")
f_ctrl = prob.fit_mixture(ctrl["dev_bps"].values, bucket="CONTROL")
print(f"  control dev   n={f_ctrl.n:5d} b0={f_ctrl.b0:+.4f} h={f_ctrl.h:.4f} "
      f"s={f_ctrl.s:.4f} tau={f_ctrl.tau:.3f}  flags={f_ctrl.flags}   "
      f"docstring s=0.358")
f_all = prob.fit_mixture(flow["z"].values, bucket="FLOW_ALL")
print(f"  flow z ALL    n={f_all.n:5d} b0={f_all.b0:+.4f} h={f_all.h:.4f} "
      f"s={f_all.s:.4f} tau={f_all.tau:.3f}  flags={f_all.flags}   "
      f"docstring s=0.382, tau=3.8")
taus = []
for b, sub in flow.groupby("band"):
    if len(sub) < 30:
        continue
    f = prob.fit_mixture(sub["z"].values, bucket=f"BAND{b}")
    taus.append(f.tau)
    print(f"  band {b}        n={f.n:5d} s={f.s:.4f} h={f.h:.4f} "
          f"tau={f.tau:8.3f}  flags={f.flags}")
print(f"  --> band tau range {min(taus):.2f}-{max(taus):.2f} bp    "
      f"docstring 2.9-11.0 bp")

print()
print("[2] what FLAG_SIGN_FRAGILE covers, at the measured mid sigma 0.254 bp")
S = 0.2543
frag = [up.FLAG_SIGN_FRAGILE in
        up.classify(npv_pay=n, upfront=u, structure_dv01=p,
                    mid_sigma_bps=S).flags
        for n, u, p in zip(flow["npv_pay"], flow["u"], flow["pv01"])]
flow["fragile"] = frag
print(f"  rows flagged SIGN_FRAGILE                     {np.mean(frag):.3f}")
print(f"  rows whose |z| < 1 mid-sigma ({S} bp)      "
      f"{float((flow['z'].abs() < S).mean()):.3f}")
print(f"  rows whose |z| < 2 mid-sigma                  "
      f"{float((flow['z'].abs() < 2 * S).mean()):.3f}")
un = flow[(flow["z"].abs() < S) & (~flow["fragile"])]
print(f"  |z| inside the mid error but NOT flagged      "
      f"{len(un) / len(flow):.3f}  (n={len(un)})")
print("  those rows: median |dev| %.2f bp, median u %.2f bp, median |z| %.3f bp"
      % (un["dev"].abs().median(), un["ub"].median(), un["z"].abs().median()))
print("  their dealer_sign is decided by |z| against a %.3f bp mid error." % S)

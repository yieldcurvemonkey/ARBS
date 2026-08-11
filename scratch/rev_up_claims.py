"""Re-derive the numeric claims in upfront.py's docstrings from the builder's
own measurement CSVs, independently of the builder's analysis script.
"""
import numpy as np
import pandas as pd


def load(name):
    d = pd.read_csv("scratch/" + name)
    return d[d["error"].isna() & d["npv_pay"].notna() & d["pv01"].notna()].copy()


def fee(d):
    u = d["other_payment_ufro"].fillna(0.0)
    p = d["pkg_ptp"].abs().fillna(0.0)
    d["U"] = np.where(p > 1000.0, p, u)          # PTP_USD_FLOOR precedence
    return d[d["U"] > 0].copy()


def mad_sigma(x):
    x = np.asarray(x, float)
    return 1.4826 * float(np.median(np.abs(x - np.median(x))))


flow = fee(load("uf02_flow_fee.csv"))
flow = flow[~flow["is_capped"].astype(bool)]
flow["u_bps_"] = flow["U"] / flow["pv01"]
flow["z"] = flow["npv_pay"].abs() / flow["pv01"] - flow["u_bps_"]
ratio = flow["U"] / flow["npv_pay"].abs()
print("FLOW fee-bearing outrights")
print("  n                     =", len(flow), "   claim 2,025")
print("  days                  =", flow['as_of_date'].nunique(), "   claim 609")
print("  median U/|dev|        = %.4f   claim 0.9996" % ratio.median())
print("  frac within 10%%       = %.3f    claim 0.52" %
      float(((ratio - 1).abs() <= 0.10).mean()))
print("  median |z| bp         = %.3f    claim 0.178" % flow["z"].abs().median())
print("  MAD-sigma of z        = %.3f    claim 0.261" % mad_sigma(flow["z"]))

ctrl = load("uf02_onmkt_control.csv")
ctrl["dev"] = -ctrl["npv_pay"] / ctrl["pv01"]
print("ON-MARKET control")
print("  n                     =", len(ctrl), "   claim 507")
print("  robust sigma of dev   = %.3f    claim 0.254" % mad_sigma(ctrl["dev"]))

cap = fee(load("uf02_capped_fee.csv"))
unc = fee(load("uf02_uncapped_big_fee.csv"))
for nm, d in (("capped", cap), ("uncapped", unc)):
    r = d["npv_pay"].abs() / d["U"]
    print(f"{nm:9s} n={len(d):5d}  median |NPV|/U = {r.median():.4f}"
          f"   frac(|NPV|>U) = {float((r > 1).mean()):.3f}"
          f"   IQR = {float(r.quantile(.75) - r.quantile(.25)):.3f}")
print("  claims: n 952/979, median 1.004/1.000, frac 0.563/0.490")

cap["cell"] = cap["tenor_label"].astype(str)
unc["cell"] = unc["tenor_label"].astype(str)
g = []
for cell in sorted(set(cap["cell"]) & set(unc["cell"])):
    a = cap[cap["cell"] == cell]
    b = unc[unc["cell"] == cell]
    if len(a) >= 20 and len(b) >= 20:
        ra = (a["npv_pay"].abs() / a["U"]).median()
        rb = (b["npv_pay"].abs() / b["U"]).median()
        g.append((cell, len(a), len(b), ra / rb))
print("paired by tenor label (n>=20 both sides): claim 0.984-1.017 over 7 cells")
for row in g:
    print("   %-6s cap n=%4d unc n=%4d  ratio of medians = %.4f" % row)

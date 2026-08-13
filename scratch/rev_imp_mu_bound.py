"""Is the shipped ln_mu a maximum-likelihood point, or the box constraint?"""
import numpy as np
from SDRUtils.dealer_direction import imputation as imp

print(f"{'cell':22s} {'ln_mu':>14s} {'log_u-SLACK':>14s} {'gap':>10s} "
      f"{'sigma':>8s} {'mult':>7s}  pinned")
pinned = []
for b in imp.CAP_BANDS:
    u = b.cap / imp.THRESHOLD_DIVISOR
    bound = np.log(u) - imp.LN_MU_SLACK
    gap = b.ln_mu - bound
    is_pin = gap < 1e-3
    if is_pin:
        pinned.append(b)
    print(f"{b.vintage+' '+b.label:22s} {b.ln_mu:14.9f} {bound:14.9f} "
          f"{gap:10.2e} {b.ln_sigma:8.4f} {b.multiplier:7.4f}  {is_pin}")

print(f"\npinned at the mu bound: {len(pinned)}/18")
print("ln_degenerate would flag (sigma > 0.98*LN_SIGMA_MAX = "
      f"{0.98*imp.LN_SIGMA_MAX}):",
      [b.label for b in pinned if b.ln_sigma > 0.98 * imp.LN_SIGMA_MAX])

# What does the implied unconditional tail probability look like in those cells?
print("\nimplied P(X > cap) in pinned cells (a lognormal with mu 30 below ln u):")
from scipy.special import ndtr
for b in pinned:
    z = (np.log(b.cap) - b.ln_mu) / b.ln_sigma
    print(f"  {b.vintage} {b.label:10s} P(X>C) = {float(ndtr(-z)):.3e}   "
          f"tail_ratio S(C)/S(u) = "
          f"{imp.lognormal_tail_ratio(b.ln_mu, b.ln_sigma, b.cap/4, b.cap):.4f}")

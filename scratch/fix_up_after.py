"""Post-fix measurement on the real 2,025-print fee-bearing flow sample,
driven through `upfront.classify` itself rather than a re-implementation."""
import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import upfront as up

S = 0.2543
TAUB = 3.816

d = pd.read_csv("scratch/uf02_flow_fee.csv")
d = d[d["error"].isna()].copy()
d["pv01"] = d["pv01"].abs()
u = d["other_payment_ufro"].fillna(0.0).to_numpy()
p = d["pkg_ptp"].abs().fillna(0.0).to_numpy()
U = np.where(p > 1000.0, p, u)
keep = U > 0
d, U = d[keep].copy(), U[keep]

tau = up.TauUpfront(tau_bps=TAUB, bias_bps=0.0, half_spread_bps=0.0128,
                    sigma_bps=0.3816, n=2025, population=up.POPULATION_FLOW,
                    bucket="ALL")

rows = []
for npv, fee, pv01 in zip(d["npv_pay"], U, d["pv01"]):
    c = up.classify(npv_pay=npv, upfront=fee, structure_dv01=pv01, tau=tau,
                    mid_sigma_bps=S)
    rows.append((c.dev_bps, c.residual_bps, c.dealer_sign, c.p,
                 c.signed_weight, up.FLAG_SIGN_FRAGILE in c.flags))
r = pd.DataFrame(rows, columns=["dev", "z", "sign", "p", "sw", "fragile"])

print(f"n = {len(r)}   sigma {S} bp   tau {TAUB} bp")
print(f"  FLAG_SIGN_FRAGILE rate            {r['fragile'].mean():.3f} "
      f"(n={int(r['fragile'].sum())})")
print(f"  of the flagged, |dev| <= 2s only  "
      f"{float((r['fragile'] & (r['dev'].abs() <= 2 * S) & (r['z'].abs() > 2 * S)).sum())/max(1,r['fragile'].sum()):.3f}")
print(f"  of the flagged, |z|   <= 2s only  "
      f"{float((r['fragile'] & (r['z'].abs() <= 2 * S) & (r['dev'].abs() > 2 * S)).sum())/max(1,r['fragile'].sum()):.3f}")
print(f"  UNflagged with |z| <= 1s          "
      f"{float(((~r['fragile']) & (r['z'].abs() <= S)).sum())}  (was 931)")
print(f"  UNflagged with |dev| <= 1s        "
      f"{float(((~r['fragile']) & (r['dev'].abs() <= S)).sum())}")

bad = r[(r["sign"] != 0) & (np.sign(r["sw"]) != 0)
        & (np.sign(r["sw"]) != r["sign"])]
print(f"  rows where signed_weight and dealer_sign DISAGREE  {len(bad)}")
print(f"  median |p - 0.5|                  {(r['p'] - 0.5).abs().median():.4f}")
print(f"  sum of signed_weight              {r['sw'].sum():+.3f}")

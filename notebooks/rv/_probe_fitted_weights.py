"""Does the fitted fly weighting survive being mapped back to whole contracts?

Three questions, in order of how much they matter:

1. Is the measured tilt (wings ~0.43/0.58 rather than 0.5/0.5) real, or is it the
   fitted vector quietly buying outright direction? An unconstrained regression
   of the belly on its wings has no reason to make the loadings sum to 1, and any
   excess is net rate exposure -- which is exactly what the belly shadow already
   showed makes money. So: refit with the sum CONSTRAINED to 1 and see what
   survives.
2. Once constrained, what integer contract package expresses it? Each SR3
   contract is $25/bp, so a package's cost in bp of its own spread is just
   (contracts x 0.5bp) and the practical menu is 1/-2/1 (4c), 2/-5/3 (10c) and
   3/-7/4 (14c).
3. For each package: is the spread more stationary, does it revert faster, and
   how many equilibrium sigmas does a round trip cost?

Universe is capped at strip slot 12 to match USD-SOFR-1D-Q12STIRT.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd
import statsmodels.api as sm

from RVUtils.MeanRev.contracts import (
    integer_weight_frontier, package_contracts, package_cost_bp, spread_from_weights,
)
from RVUtils.mean_reversion import adf_pvalue, calibrate_ou, half_life

DATA = REPO / "notebooks" / "data" / "sfr_fly_meanrev"
MAX_SLOT = 12
START = "2022-01-03"
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_rows", 200)

st = pd.read_parquet(DATA / "structures_3m.parquet")
st["as_of"] = pd.to_datetime(st["as_of"])
st = st[(st["as_of"] >= START) & (st["back_slot"] <= MAX_SLOT)]
print(f"3m flies, slots <= {MAX_SLOT}, from {START}: {st['key'].nunique()} keys, "
      f"{st['as_of'].nunique()} sessions")

CANDIDATES = {
    "1/-2/1  (4c)": (-1.0, 2.0, -1.0),
    "2/-5/3  (10c)": (-2.0, 5.0, -3.0),
    "3/-7/4  (14c)": (-3.0, 7.0, -4.0),
}

rows = []
for key, g in st.groupby("key"):
    g = g.sort_values("as_of")
    if len(g) < 400:
        continue
    idx = pd.DatetimeIndex(g["as_of"])
    legs = pd.DataFrame({"f": g["leg0_value"].to_numpy(float),
                         "b": g["leg1_value"].to_numpy(float),
                         "k": g["leg2_value"].to_numpy(float)}, index=idx)

    # --- (1) unconstrained vs level-neutral-constrained fit -----------------
    X = sm.add_constant(legs[["f", "k"]].to_numpy())
    fit_u = sm.OLS(legs["b"].to_numpy(), X).fit()
    bf_u, bk_u = float(fit_u.params[1]), float(fit_u.params[2])
    resid_u = pd.Series(legs["b"].to_numpy() - X @ fit_u.params, index=idx) * 100

    # constrained so the loadings sum to 1: (b - k) = a + bf*(f - k)
    y_c = (legs["b"] - legs["k"]).to_numpy()
    x_c = sm.add_constant((legs["f"] - legs["k"]).to_numpy())
    fit_c = sm.OLS(y_c, x_c).fit()
    bf_c = float(fit_c.params[1])
    bk_c = 1.0 - bf_c
    resid_c = pd.Series(y_c - x_c @ fit_c.params, index=idx) * 100

    rec = {
        "key": key, "slot": int(g["cm_slot"].median()), "n": len(g),
        "bf_uncon": bf_u, "bk_uncon": bk_u, "sum_uncon": bf_u + bk_u,
        "bf_con": bf_c, "bk_con": bk_c,
        "sd_resid_uncon": resid_u.std(), "sd_resid_con": resid_c.std(),
        "adf_uncon": adf_pvalue(resid_u), "adf_con": adf_pvalue(resid_c),
        "hl_uncon": half_life(resid_u), "hl_con": half_life(resid_c),
    }

    # --- (2)+(3) the three integer packages --------------------------------
    for name, w in CANDIDATES.items():
        s = spread_from_weights(legs, w)
        p = calibrate_ou(s)
        kap = p.get("kappa", np.nan)
        sig_eq = (p["sigma"] / np.sqrt(2 * kap)
                  if np.isfinite(kap) and kap > 0 else np.nan)
        cost = package_cost_bp(w)
        tag = name.split()[0]
        rec[f"sd_{tag}"] = s.std()
        rec[f"hl_{tag}"] = p["half_life"]
        rec[f"adf_{tag}"] = adf_pvalue(s)
        rec[f"sigeq_{tag}"] = sig_eq
        rec[f"cost_{tag}"] = cost
        # how many equilibrium sigmas a round trip costs -- scale-invariant
        rec[f"costsig_{tag}"] = cost / sig_eq if np.isfinite(sig_eq) and sig_eq > 0 else np.nan
        # per-unit-belly volatility, to see the tilt's vol reduction
        rec[f"sdper2_{tag}"] = s.std() / (abs(w[1]) / 2.0)
    rows.append(rec)

d = pd.DataFrame(rows).sort_values("slot")

print("\n" + "=" * 110)
print("1. IS THE TILT REAL, OR IS IT BUYING DIRECTION?")
print("=" * 110)
print(d[["key", "slot", "bf_uncon", "bk_uncon", "sum_uncon", "bf_con", "bk_con",
         "adf_uncon", "adf_con", "hl_uncon", "hl_con"]].round(4).to_string(index=False))
print(f"\nunconstrained loading sum: mean {d['sum_uncon'].mean():.4f}, "
      f"range [{d['sum_uncon'].min():.4f}, {d['sum_uncon'].max():.4f}]")
print(f"  net rate exposure per unit belly: mean "
      f"{(d['sum_uncon'] - 1).mean():+.4f} -- i.e. the unconstrained fit is "
      f"{'LONG' if (d['sum_uncon']-1).mean() > 0 else 'SHORT'} outright rates")
print(f"\nfront wing share: unconstrained mean {d['bf_uncon'].mean():.4f}, "
      f"CONSTRAINED mean {d['bf_con'].mean():.4f}  (a plain fly is 0.5000)")
print(f"back  wing share: unconstrained mean {d['bk_uncon'].mean():.4f}, "
      f"CONSTRAINED mean {d['bk_con'].mean():.4f}")
print(f"\nADF p < 0.10:  unconstrained {int((d['adf_uncon'] < 0.10).sum())}/{len(d)}"
      f"   constrained {int((d['adf_con'] < 0.10).sum())}/{len(d)}")
print(f"median half-life: unconstrained {d['hl_uncon'].median():.1f}d   "
      f"constrained {d['hl_con'].median():.1f}d")

print("\n" + "=" * 110)
print("2. THE TILT BY SLOT (does it drift along the strip?)")
print("=" * 110)
print(d.groupby("slot").agg(n_keys=("key", "size"),
                            bf_con=("bf_con", "mean"),
                            bk_con=("bk_con", "mean"),
                            sum_uncon=("sum_uncon", "mean")).round(4).to_string())

print("\n" + "=" * 110)
print("3. THE THREE INTEGER PACKAGES")
print("=" * 110)
for tag in ("1/-2/1", "2/-5/3", "3/-7/4"):
    w = CANDIDATES[[k for k in CANDIDATES if k.startswith(tag)][0]]
    print(f"\n--- {tag}: {package_contracts(w):.0f} contracts, "
          f"round trip {package_cost_bp(w):.1f}bp of its own spread ---")
    sub = d[["key", "slot", f"sd_{tag}", f"sdper2_{tag}", f"hl_{tag}",
             f"adf_{tag}", f"sigeq_{tag}", f"costsig_{tag}"]]
    print(sub.round(3).to_string(index=False))

print("\n" + "=" * 110)
print("4. HEAD TO HEAD (medians across keys)")
print("=" * 110)
cmp = pd.DataFrame({
    tag: {
        "contracts": package_contracts(CANDIDATES[[k for k in CANDIDATES
                                                   if k.startswith(tag)][0]]),
        "cost_bp_of_spread": d[f"cost_{tag}"].iloc[0],
        "median_sd_bp": d[f"sd_{tag}"].median(),
        "median_sd_per_belly2": d[f"sdper2_{tag}"].median(),
        "median_half_life_d": d[f"hl_{tag}"].median(),
        "n_adf_stationary_10pct": int((d[f"adf_{tag}"] < 0.10).sum()),
        "median_sigma_eq_bp": d[f"sigeq_{tag}"].median(),
        "median_cost_in_sigma_eq": d[f"costsig_{tag}"].median(),
    } for tag in ("1/-2/1", "2/-5/3", "3/-7/4")
}).T
cmp["n_keys"] = len(d)
print(cmp.round(4).to_string())
print("\n  'cost_in_sigma_eq' is the scale-invariant number: how many equilibrium")
print("  standard deviations of its own spread a round trip costs. Lower is better,")
print("  and it is invariant to how big you trade the package.")

print("\n" + "=" * 110)
print("5. THE INTEGER FRONTIER FOR THE MEASURED TILT")
print("=" * 110)
fr = integer_weight_frontier(d["bf_con"].mean(), d["bk_con"].mean(), max_belly=120)
print(fr[fr["is_frontier"]][["belly", "n_front", "n_back", "front_share",
                             "wing_error", "contracts",
                             "cost_bp_of_spread"]].round(5).to_string(index=False))

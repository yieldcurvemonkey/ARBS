"""Follow-up independent checks: NW-t on TLH-2023 cell, disjoint size bins with NW-t,
multiple-testing formula check, and a hand-checked single-observation arithmetic spot
check inside the TLH 912810SY5 sub-cell.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from RVUtils.ETFRebalance import _audit_concentration as A

pd.set_option("display.width", 240)

h = 63


def expected_max_abs_t(n_trials: int) -> float:
    n = max(2, 2 * n_trials)
    ln_n = np.log(n)
    ln_ln_n = np.log(max(ln_n, 1e-9))
    base = np.sqrt(2 * ln_n)
    corr = (ln_ln_n + np.log(4 * np.pi)) / (2 * base)
    return float(base - corr)


print("expected_max_abs_t(229) =", expected_max_abs_t(229))
print("expected_max_abs_t(148) =", expected_max_abs_t(148))

for fund in ("TLT", "TLH"):
    print(f"\n{'='*90}\n{fund}\n{'='*90}")
    d = A.build(fund)
    sub_all = d.dropna(subset=["z_active_w", f"fwd_{h}_orth"])

    print("disjoint size bins (63d), NW-corrected t:")
    edges = [0.0, 1.0, 1.5, 2.0, 2.5, 3.0, np.inf]
    for lo, hi in zip(edges[:-1], edges[1:]):
        sub = sub_all[(sub_all["z_active_w"].abs() >= lo) & (sub_all["z_active_w"].abs() < hi)]
        per_date = sub.groupby("date")[f"edge_{h}"].mean().dropna()
        if len(per_date) < 10:
            continue
        m = per_date.mean()
        sd = per_date.std(ddof=1)
        naive_t = m / (sd / np.sqrt(len(per_date))) if sd > 0 else np.nan
        nw_t = A.newey_west_t(per_date.to_numpy(), lags=h - 1)
        print(f"  [{lo},{hi}): n_dates={len(per_date)} mean_bp={m:.4f} naive_t={naive_t:.2f} NW_t={nw_t:.2f}")

    if fund == "TLH":
        sub25 = sub_all[sub_all["z_active_w"].abs() >= 2.5]
        g23 = sub25[sub25["year"] == 2023]
        per_date = g23.groupby("date")[f"edge_{h}"].mean().dropna()
        m = per_date.mean(); sd = per_date.std(ddof=1)
        naive_t = m / (sd / np.sqrt(len(per_date)))
        nw_t = A.newey_west_t(per_date.to_numpy(), lags=h - 1)
        print(f"\nTLH 2023-only |z|>=2.5 cell: n_dates={len(per_date)} mean_bp={m:.4f} naive_t={naive_t:.2f} NW_t={nw_t:.2f}")

        # hand spot-check: pick one 912810SY5 obs, recompute fwd_63 and fwd_63_orth from raw resid_bp
        g = d[d["cusip"] == "912810SY5"].sort_values("date").reset_index(drop=True)
        g25 = g[(g["z_active_w"].abs() >= 2.5) & (g["year"] == 2023)]
        print(f"\n912810SY5: {len(g)} total rows, {len(g25)} rows with |z|>=2.5 in 2023")
        if len(g25):
            row = g25.iloc[len(g25) // 2]
            dt0 = row["date"]
            print(f"spot check date={dt0.date()}  resid_bp(t)={row['resid_bp']:.4f}  "
                  f"z_active_w(used, lagged)={row['z_active_w']:.3f}  direction={row['direction']:.0f}")
            # find the row h business observations later for this cusip (by ROW index, not calendar,
            # matching my_fwd_resid's groupby('cusip').shift(-h) convention)
            idx = g.index[g["date"] == dt0][0]
            if idx + h < len(g):
                row_fwd = g.iloc[idx + h]
                resid_t = row["resid_bp"]
                resid_t_h = row_fwd["resid_bp"]
                fwd_hand = -(resid_t_h - resid_t)
                print(f"  row+{h}: date={row_fwd['date'].date()} resid_bp={resid_t_h:.4f}")
                print(f"  hand fwd_{h} = -(resid[t+h]-resid[t]) = -({resid_t_h:.4f}-{resid_t:.4f}) = {fwd_hand:.4f}bp")
                print(f"  script fwd_{h} (unorth) on this row = {row[f'fwd_{h}']:.4f}bp")
                print(f"  script fwd_{h}_orth (after resid control) = {row[f'fwd_{h}_orth']:.4f}bp")
                print(f"  script edge_{h} (direction * orth) = {row[f'edge_{h}']:.4f}bp")
                print(f"  hand direction*fwd_hand(unorth) = {row['direction'] * fwd_hand:.4f}bp  "
                      f"(orth differs because it nets out the cross-sectional z_resid slope that date)")

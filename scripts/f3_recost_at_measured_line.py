"""F3 / H16 re-cost at the CM-2 MEASURED linear line (L-0042a reopener).

L-0042(a): "a genuinely better execution line (listed-instrument analogue, maker
fills) reopens F3 and H16; note the LINEAR leg dominates every boat and that
line is the Citi 2019 schedule, not CM-1 smear." CM-2 measures that line. This
applies it to F3's committed episodes and reports what changes.

F3's instrument is a direction-neutral package of k-year-forward 1Y swaps
(``kF1Y``, k = 2..19). The graded gate charged a FLAT 1.0 bp package round trip.
The measured line is per-leg, so the package round trip is rebuilt explicitly:

    RT_package = sum|w| x 2 x half_spread(tenor=1Y, fwd=k)

for a 1-2-1 fly (sum|w| = 4). Both the graded flat benchmark and the rebuilt
measured one are reported side by side — the point is the comparison, and the
rebuilt one is NOT automatically the friendlier number.

Run after cost_swap_sdr.py has written swap_cost_cells.parquet.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
CCYS = ["USD", "EUR", "GBP", "JPY"]
GRADED_RT_BP = 1.0          # what the F3 gate charged
FLY_WEIGHT_SUM = 4.0        # 1-2-1


def measured_half_spread() -> dict:
    """1Y half-spread by forward-start bucket, from CM-2. Two readings kept."""
    cells = pd.read_parquet(DATA / "swap_cost_cells.parquet")
    one = cells[cells["tenor"] == 1]
    if one.empty:
        raise SystemExit("CM-2 has no 1Y cells — cannot re-cost F3's instrument")
    out = {}
    for _, r in one.iterrows():
        out[str(r["fwd_bucket"])] = {
            "n_prints": int(r["n_prints"]),
            "upper_bound_bp": float(r["median_abs_dev_bp"]),
            "at_stamp_bp": float(r["stamp_hour_median_abs_bp"]),
            "assumed_bp": float(r["assumed_half_spread_bp"]),
        }
    return out


def main() -> None:
    hs = measured_half_spread()
    print("CM-2 measured 1Y half-spread by forward-start bucket (annual rate bp):")
    print(json.dumps(hs, indent=1))

    # F3's k runs 2..19 years forward; the measured buckets that cover it are
    # 1-3Y, 3-6Y and 6-10Y. Beyond 10Y there is no measurement, so those k are
    # priced at the widest measured bucket and the extrapolation is FLAGGED.
    fwd_buckets = [b for b in ("1-3Y", "3-6Y", "6-10Y") if b in hs]
    if not fwd_buckets:
        raise SystemExit("CM-2 measured no forward-starting 1Y cells")
    for reading in ("upper_bound_bp", "at_stamp_bp"):
        vals = [hs[b][reading] for b in fwd_buckets if np.isfinite(hs[b][reading])]
        if not vals:
            continue
        lo, hi = float(np.min(vals)), float(np.max(vals))
        print(f"\n=== package RT rebuilt from the '{reading}' reading ===")
        print(f"per-leg half-spread across F3's forward range: {lo:.3f}..{hi:.3f} bp")
        rt_lo, rt_hi = FLY_WEIGHT_SUM * 2 * lo, FLY_WEIGHT_SUM * 2 * hi
        print(f"1-2-1 package round trip: {rt_lo:.2f}..{rt_hi:.2f} bp "
              f"(graded gate charged {GRADED_RT_BP:.2f})")

        rows = []
        for ccy in CCYS:
            fp = DATA / f"f3_episodes_{ccy}.parquet"
            if not fp.exists():
                continue
            e = pd.read_parquet(fp)
            e = e[e["complete"] & ~e["in_restriction"]]
            r63 = e["reversion_63bd"].dropna()
            if len(r63) < 20:
                continue
            med = float(r63.median())
            rows.append({
                "ccy": ccy, "n_episodes": int(len(r63)),
                "median_reversion_63bd_bp": med,
                "over_graded_rt": med / GRADED_RT_BP,
                "over_measured_rt_lo": med / rt_lo,
                "over_measured_rt_hi": med / rt_hi,
            })
        t = pd.DataFrame(rows)
        pd.set_option("display.width", 200)
        print(t.round(3).to_string(index=False))
        print("NOTE these are ORACLE medians (perfect direction). The program's own "
              "regularity is that realised harvest is 10-30% of oracle, so a ratio "
              "under ~3-10x is not a live pond.")

    (DATA / "f3_recost.json").write_text(json.dumps(
        {"measured_1y_half_spread": hs, "graded_rt_bp": GRADED_RT_BP,
         "fly_weight_sum": FLY_WEIGHT_SUM}, indent=1))


if __name__ == "__main__":
    main()

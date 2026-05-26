"""Compare Breeden-Litzenberger vs BKM implied distribution for SFRZ26.

Runs both extraction methods on the same smile and reports the differences
in moments, highlighting the noise characteristics of each approach.
"""

import datetime
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from RVUtils.ImpliedDistribution import SFRImpliedDistribution


def main():
    print("=" * 72)
    print("SFRZ26 Implied Distribution: BL vs BKM Comparison")
    print(f"as_of = 2026-05-22")
    print("=" * 72)

    stirfo_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")

    smile = stirfo_mdp.fetch_sabr_smile({
        "symbol": "SFRZ26",
        "as_of": datetime.date(2026, 5, 22),
        "strike_offsets_bps": "listed",
        "show_tqdm": True,
    })

    print(f"\nSmile: {smile.symbol}")
    print(f"  Forward price: {smile.params.forward_price:.4f}")
    print(f"  Forward rate:  {smile.params.forward_rate:.4f}%")
    print(f"  Time to expiry: {smile.params.time_to_expiry:.4f}y")
    print(f"  N points: {len(smile.points)}")
    print(f"  SABR params: α={smile.params.alpha:.6f}, ρ={smile.params.rho:.4f}, ν={smile.params.nu:.4f}")

    # --- Method 1: BL (default JPM methodology) ---
    # Use SABR vols at listed strikes to ensure enough data points
    dist = SFRImpliedDistribution(
        use_sabr_vols=True,
        sabr_extrapolation=False,
    )
    snapshot_bl = dist.extract(smile, run_bl=True, run_gm=False, run_bkm=False)
    bl = snapshot_bl.bl_result

    # --- Method 2: BL with SABR extrapolation (dense grid extending tails) ---
    dist_ext = SFRImpliedDistribution(
        use_sabr_vols=True,
        sabr_extrapolation=True,
        sabr_n_strikes=300,
    )
    snapshot_bl_ext = dist_ext.extract(smile, run_bl=True, run_gm=False, run_bkm=False)
    bl_ext = snapshot_bl_ext.bl_result

    # --- Method 3: BKM on listed strikes (SABR vols) ---
    snapshot_bkm = dist.extract(smile, run_bl=False, run_gm=False, run_bkm=True)
    bkm = snapshot_bkm.bkm_result

    # --- Method 4: BKM on extrapolated grid (dense, full tails) ---
    snapshot_bkm_ext = dist_ext.extract(smile, run_bl=False, run_gm=False, run_bkm=True)
    bkm_ext = snapshot_bkm_ext.bkm_result

    # --- Report ---
    print("\n" + "-" * 72)
    print("MOMENT COMPARISON")
    print("-" * 72)

    header = f"{'Moment':<20} {'BL listed':<14} {'BL extrap':<14} {'BKM listed':<14} {'BKM extrap':<14}"
    print(header)
    print("-" * len(header))

    # Mean
    print(f"{'Mean (rate %)':<20} {bl.mean_rate:<14.6f} {bl_ext.mean_rate:<14.6f} {bkm.mean_rate:<14.6f} {bkm_ext.mean_rate:<14.6f}")

    # Std
    print(f"{'Std (rate %)':<20} {bl.std_rate:<14.6f} {bl_ext.std_rate:<14.6f} {bkm.std_rate:<14.6f} {bkm_ext.std_rate:<14.6f}")

    # Std in bps
    print(f"{'Std (bps)':<20} {bl.std_rate*100:<14.2f} {bl_ext.std_rate*100:<14.2f} {bkm.std_rate*100:<14.2f} {bkm_ext.std_rate*100:<14.2f}")

    # Skewness
    print(f"{'Skewness':<20} {bl.skewness:<14.4f} {bl_ext.skewness:<14.4f} {bkm.skewness_rate:<14.4f} {bkm_ext.skewness_rate:<14.4f}")

    # Kurtosis
    print(f"{'Kurtosis':<20} {bl.kurtosis:<14.4f} {bl_ext.kurtosis:<14.4f} {bkm.kurtosis_rate:<14.4f} {bkm_ext.kurtosis_rate:<14.4f}")

    # Excess kurtosis
    print(f"{'Excess Kurt':<20} {bl.kurtosis - 3:<14.4f} {bl_ext.kurtosis - 3:<14.4f} {bkm.excess_kurtosis_rate:<14.4f} {bkm_ext.excess_kurtosis_rate:<14.4f}")

    print("\n" + "-" * 72)
    print("DIFFERENCES: BKM vs BL (same strike grid)")
    print("-" * 72)

    print(f"\n  Listed strikes ({len(smile.points)} points):")
    std_diff = (bkm.std_rate - bl.std_rate) * 100
    print(f"    Std diff:      {std_diff:+.2f} bps  ({std_diff / (bl.std_rate * 100) * 100:+.2f}%)")
    print(f"    Skew diff:     {bkm.skewness_rate - bl.skewness:+.4f}")
    print(f"    Kurt diff:     {bkm.kurtosis_rate - bl.kurtosis:+.4f}")

    print(f"\n  Extrapolated grid (300 points):")
    std_diff_ext = (bkm_ext.std_rate - bl_ext.std_rate) * 100
    print(f"    Std diff:      {std_diff_ext:+.2f} bps  ({std_diff_ext / (bl_ext.std_rate * 100) * 100:+.2f}%)")
    print(f"    Skew diff:     {bkm_ext.skewness_rate - bl_ext.skewness:+.4f}")
    print(f"    Kurt diff:     {bkm_ext.kurtosis_rate - bl_ext.kurtosis:+.4f}")

    print("\n" + "-" * 72)
    print("BKM TAIL DIAGNOSTICS")
    print("-" * 72)
    print(f"\n  Listed strikes:")
    print(f"    OTM calls: {bkm.n_otm_calls},  OTM puts: {bkm.n_otm_puts}")
    print(f"    Left tail (puts) contribution to variance:  {bkm.left_tail_variance_frac:.1%}")
    print(f"    Right tail (calls) contribution to variance: {bkm.right_tail_variance_frac:.1%}")

    print(f"\n  Extrapolated grid:")
    print(f"    OTM calls: {bkm_ext.n_otm_calls},  OTM puts: {bkm_ext.n_otm_puts}")
    print(f"    Left tail (puts) contribution to variance:  {bkm_ext.left_tail_variance_frac:.1%}")
    print(f"    Right tail (calls) contribution to variance: {bkm_ext.right_tail_variance_frac:.1%}")

    if bkm.warnings:
        print(f"\n  BKM warnings (listed): {bkm.warnings}")
    if bkm_ext.warnings:
        print(f"  BKM warnings (extrap): {bkm_ext.warnings}")

    print("\n" + "-" * 72)
    print("BL DISTRIBUTION DETAILS")
    print("-" * 72)
    print(f"\n  Forward rate: {bl.input.forward_rate:.4f}%")
    print(f"  5th percentile:  {bl.percentile(5):.4f}%")
    print(f"  25th percentile: {bl.percentile(25):.4f}%")
    print(f"  50th percentile: {bl.percentile(50):.4f}%")
    print(f"  75th percentile: {bl.percentile(75):.4f}%")
    print(f"  95th percentile: {bl.percentile(95):.4f}%")
    print(f"  Spline residual: {bl.spline_residual:.6f}")
    if bl.warnings:
        print(f"  Warnings: {bl.warnings}")

    print("\n" + "-" * 72)
    print("INTERPRETATION")
    print("-" * 72)
    print(f"""
  The BKM approach computes moments via INTEGRATION of option prices,
  while BL computes them via DIFFERENTIATION (2nd derivative of spline).

  Key observations:
  - Mean: BL gives {bl.mean_rate:.4f}%, forward rate is {bl.input.forward_rate:.4f}%.
    BKM uses the forward directly (it IS the risk-neutral mean).
    BL mean error: {(bl.mean_rate - bl.input.forward_rate)*100:+.2f} bps
  - Std: BKM={bkm.std_rate*100:.2f}bps vs BL={bl.std_rate*100:.2f}bps (diff={std_diff:+.2f}bps)
    Integration smooths → BKM is more numerically stable.
  - Skew: BKM={bkm.skewness_rate:.4f} vs BL={bl.skewness:.4f}
    Positive skew in rate space = right tail fatter (higher-rate scenarios).
  - Kurtosis: BKM={bkm.kurtosis_rate:.4f} vs BL={bl.kurtosis:.4f}
    >3 means fat tails relative to Normal.

  For butterfly RV:
  - Use BKM std for the variance term structure (robust, no spline artifacts)
  - Use BL density for the full distribution shape and scenario binning
  - Use the forward rate for the mean (exact, not estimated)
""")


if __name__ == "__main__":
    main()

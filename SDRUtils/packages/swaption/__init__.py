"""
Swaption package detection module.

This subpackage contains modular, composable detection logic for various
swaption package types. The architecture follows a pipeline pattern that
makes it easy to add new structure types (e.g., Iron Condors, Iron Butterflies)
by simply adding a new detection module.

Package structure:
- utils.py: Shared helper functions (vega estimation, bucketing, etc.)
- straddle.py: Straddle detection (Payer + Receiver with same strike/expiry/tenor)
- risk_reversal.py: Risk reversal detection (4-leg structures)
- spreads.py: Vertical spread detection (1x1, 1x2, etc.)
- conditional_curve.py: Conditional curve trades (same expiry, different tails)
- vega_curve.py: Vega curve trades (vega-matched straddles across tenors)
- vega_buckets.py: Vega-bucketed package detection
- linking.py: Second-pass package linking

Each detection module exports a standard function signature:
    detect_X(df, *, <explicit_kwargs>) -> pd.DataFrame

The main orchestrator (swaption_packages.py) runs detectors in a pipeline,
maintaining a pool of unmatched trades that gets consumed by each detector.
"""

from SDRUtils.packages.swaption.utils import (
    vega_bucket,
    time_bucket,
    safe_float,
    compute_package_id,
    build_package_reason,
    estimate_swaption_vega,
    extract_effective_premium,
    ensure_package_columns,
    is_payer,
    is_receiver,
)
from SDRUtils.packages.swaption.straddle import detect_straddles_packages
from SDRUtils.packages.swaption.risk_reversal import detect_risk_reversals_packages 
from SDRUtils.packages.swaption.spreads import detect_vertical_spreads_packages
from SDRUtils.packages.swaption.conditional_curve import detect_conditional_curve_packages
from SDRUtils.packages.swaption.vega_curve import detect_vega_curve_packages
from SDRUtils.packages.swaption.vega_buckets import detect_vega_bucketed_packages
from SDRUtils.packages.swaption.linking import link_packages

__all__ = [
    # Utils
    "vega_bucket",
    "time_bucket",
    "safe_float",
    "compute_package_id",
    "build_package_reason",
    "estimate_swaption_vega",
    "extract_effective_premium",
    "ensure_package_columns",
    "is_payer",
    "is_receiver",
    # Detectors
    "detect_straddles_packages",
    "detect_risk_reversals_packages",
    "detect_vertical_spreads_packages",
    "detect_conditional_curve_packages",
    "detect_vega_curve_packages",
    "detect_vega_bucketed_packages",
    "link_packages",
]

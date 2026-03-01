"""
Swaption package detection submodules.

This package contains granular detection modules for different
swaption package types. Each module is responsible for detecting
a specific structure pattern.

Modules:
    straddle: Payer + Receiver with same strike/expiry/tenor
    risk_reversal: 4-leg structures with wings + delta hedge (IDB)
    customer_rr_strangle: 2-leg payer+receiver with benchmark widths
    spreads: Vertical spreads (1x1, 1x2, etc.)
    ladder: Christmas tree structures (3+ legs)
    conditional_curve: Same expiry, different tail maturities
    vega_curve: Vega-matched straddles across tenors
    vega_buckets: Vega-similar trades within time proximity
    delta_hedge: Swaption + USD swap hedge linkage
    outright: Unexplained single-leg trades with ATMF enrichment
    linking: Second-pass linking of packages by time/vega overlap
    utils: Shared utilities for all detection modules

The main orchestrator is in the parent module:
    SDRUtils.packages.swaption_packages
"""

# Detection functions
from SDRUtils.packages.swaption.straddle import detect_straddles_packages
from SDRUtils.packages.swaption.risk_reversal import detect_risk_reversals_packages
from SDRUtils.packages.swaption.customer_rr_strangle import (
    detect_customer_rr_strangles_packages,
)
from SDRUtils.packages.swaption.spreads import detect_vertical_spreads_packages
from SDRUtils.packages.swaption.ladder import detect_ladder_packages
from SDRUtils.packages.swaption.conditional_curve import (
    detect_conditional_curve_packages,
)
from SDRUtils.packages.swaption.vega_curve import detect_vega_curve_packages
from SDRUtils.packages.swaption.vega_buckets import detect_vega_bucketed_packages
from SDRUtils.packages.swaption.delta_hedge import detect_delta_hedge_packages
from SDRUtils.packages.swaption.outright import detect_outright_swaptions
from SDRUtils.packages.swaption.linking import link_packages

# Utilities
from SDRUtils.packages.swaption.utils import (
    vega_bucket,
    time_bucket,
    safe_float,
    compute_package_id,
    build_package_reason,
    estimate_swaption_vega,
    extract_effective_premium,
    is_payer,
    is_receiver,
    ensure_package_columns,
    check_economic_filters,
)

__all__ = [
    # Detection functions
    "detect_straddles_packages",
    "detect_risk_reversals_packages",
    "detect_customer_rr_strangles_packages",
    "detect_vertical_spreads_packages",
    "detect_ladder_packages",
    "detect_conditional_curve_packages",
    "detect_vega_curve_packages",
    "detect_vega_bucketed_packages",
    "detect_delta_hedge_packages",
    "detect_outright_swaptions",
    "link_packages",
    # Utilities
    "vega_bucket",
    "time_bucket",
    "safe_float",
    "compute_package_id",
    "build_package_reason",
    "estimate_swaption_vega",
    "extract_effective_premium",
    "is_payer",
    "is_receiver",
    "ensure_package_columns",
    "check_economic_filters",
]

"""Curve-fly screener — spot and forward butterflies on risk-adjusted carry-roll.

See ``docs/curvefly/DESIGN.md``.
"""
from RVUtils.CurveFlyScreener.universe import (
    FWD_STARTS,
    FWD_TENORS,
    MAX_FWD_END,
    SPOT_TENORS,
    forward_curves_same_start,
    forward_curves_same_tenor,
    forward_flies_uni,
    full_universe,
    leg_label,
    leg_universe,
    spot_curves,
    spot_flies_uni,
)
from RVUtils.CurveFlyScreener.screener import (
    Leg,
    add_risk_adjustment,
    breakeven_daily_bp,
    compose_levels,
    Structure,
    age,
    carry_roll_bp,
    curve_pairs,
    dv01_bp,
    forward_flies,
    neutral_weights,
    par_rate_bp,
    screen,
    spot_flies,
    structure_rate_bp,
)

__all__ = [
    "Leg", "Structure", "age", "carry_roll_bp", "curve_pairs", "dv01_bp",
    "forward_flies", "neutral_weights", "par_rate_bp", "screen", "spot_flies",
    "structure_rate_bp", "compose_levels", "add_risk_adjustment",
    "breakeven_daily_bp",
    "SPOT_TENORS", "FWD_STARTS", "FWD_TENORS", "MAX_FWD_END",
    "leg_label", "leg_universe", "spot_curves", "forward_curves_same_start",
    "forward_curves_same_tenor", "spot_flies_uni", "forward_flies_uni",
    "full_universe",
]

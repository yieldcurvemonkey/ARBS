"""Outcome-map RV: the FOMC count-cell map of an SR3 quarterly, priced twice.

Exchangeability collapses a quarterly's resolved-meeting outcome space to the
distribution of the TOTAL move count, so the identified object is a vector of
**cells** — one per distinct atom on the 25bp lattice — each carrying an
option-implied and a lattice-implied probability. This package builds that map
from listed premiums, decomposes its richness into the standing (even)
dispersion premium and the (odd) tilt that a linear market also prices, and
provides the packages, hedge ratios and trade loop that trade the odd part.

Modules
-------
``cells``       map construction, the even/odd decomposition, signal selectors
``structures``  butterfly legs, telescoping, contract counts
``hedge``       package hedge ratios vs per-meeting jumps; ZQ / swap leg costs
``engine``      the trade loop (lag-1 entries, one package per symbol)
``calendar``    the adjacent-expiry (vol-vs-vol) leg: pairing, mirroring, ratios
"""
from RVUtils.OutcomeMap.cells import (
    Cell, CellMap, build_cell_map, decompose, distinct_atoms, snap_center,
    map_full_weights, pair_odd_dev_signal, pair_odd_signal,
    pair_raw_signal,
)
from RVUtils.OutcomeMap.structures import (
    FLY_WING, fly_legs, package_contracts, telescope,
)
from RVUtils.OutcomeMap.hedge import (
    linear_leg_cost_bp, option_leg_cost_bp, package_hedge_ratios,
    package_tree_value, zq_basket_contracts,
)
from RVUtils.OutcomeMap.calendar import (
    LAMBDA_CAP, MIN_SHARED_MEETINGS, adjacent, align_exposure,
    empirical_ratio, mirror_package, residual_exposure, tree_ratio,
)
from RVUtils.OutcomeMap.engine import (
    HedgeContext, OutcomeTrade, run_outcome_backtest)

__all__ = [
    "Cell", "CellMap", "build_cell_map", "decompose", "distinct_atoms",
    "snap_center", "map_full_weights", "pair_odd_dev_signal",
    "pair_odd_signal", "pair_raw_signal",
    "FLY_WING", "fly_legs", "package_contracts", "telescope",
    "linear_leg_cost_bp", "option_leg_cost_bp", "package_hedge_ratios",
    "package_tree_value", "zq_basket_contracts",
    "HedgeContext", "OutcomeTrade", "run_outcome_backtest",
    "LAMBDA_CAP", "MIN_SHARED_MEETINGS", "adjacent", "align_exposure",
    "empirical_ratio", "mirror_package", "residual_exposure", "tree_ratio",
]

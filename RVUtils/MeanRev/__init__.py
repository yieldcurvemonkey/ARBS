"""Mean-reversion lab: a panel backtest engine and the signal families it runs.

Data-agnostic. Everything takes pandas objects -- a wide ``levels`` frame
(``date x key``, values in the traded unit, bp for a butterfly) and a matching
``signal`` frame -- and knows nothing about futures, curves or providers.

The honesty rules are structural, not configurable, and are the same ones
:mod:`RVUtils.SFRRVLab.engine` enforces for option structures:

* a signal observed on bar ``i`` is filled on bar ``i + lag``;
* a **deterministic** exit date (fixed horizon, max hold, end of sample) is
  known at entry and is filled on the bar itself -- lagging it a second time
  was a real bug in the prior lab;
* costs are charged once per completed trade, on the exit bar, in the daily
  series as well as the trade row;
* gates apply at entry only, because force-closing on a gate that fails later
  is a look-ahead exit.

Grading is deliberately shared with the options lab: :mod:`RVUtils.SFRRVLab.stats`
consumes :class:`MRResult` directly, so both labs are scored by identical code.
"""
from RVUtils.MeanRev.engine import (
    COST_SCENARIOS,
    MRConfig,
    MRResult,
    grid_search,
    leg_round_trip_bp,
    run_backtest,
    run_continuous,
)
from RVUtils.MeanRev.panel import (
    add_strip_slots,
    cm_label,
    enumerate_structures,
    pivot_levels,
    regime_tag,
    structure_liquidity,
)
from RVUtils.MeanRev.shadow import shadow_levels, shadow_table
from RVUtils.MeanRev.signals import (
    bollinger_signal,
    coint_spread_signal,
    curvefit_residual_signal,
    kalman_level_signal,
    ou_sscore_signal,
    pca_residual_signal,
    xsection_signal,
    zscore_signal,
)

__all__ = [
    "COST_SCENARIOS", "MRConfig", "MRResult", "grid_search", "leg_round_trip_bp",
    "run_backtest", "run_continuous",
    "add_strip_slots", "cm_label", "enumerate_structures", "pivot_levels",
    "regime_tag", "structure_liquidity",
    "shadow_levels", "shadow_table",
    "bollinger_signal", "coint_spread_signal", "curvefit_residual_signal",
    "kalman_level_signal", "ou_sscore_signal", "pca_residual_signal",
    "xsection_signal", "zscore_signal",
]

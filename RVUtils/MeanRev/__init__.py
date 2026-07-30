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
from RVUtils.MeanRev.contracts import (
    FLY_WEIGHTS_CONTRACTS,
    SR3_DV01_USD,
    SR3_HALF_SPREAD_BP,
    PackageWeights,
    best_integer_weights,
    integer_weight_frontier,
    package_contracts,
    package_cost_bp,
    package_cost_usd,
    package_dv01_usd,
    spread_from_weights,
)
from RVUtils.MeanRev.diagnostics import (
    forward_move,
    move_profile,
    oracle_table,
    selectivity_table,
    signal_entry_mask,
    variance_decomposition,
)
from RVUtils.MeanRev.ff import (
    ZQ_DV01_USD,
    ZQ_HALF_TICK_BP,
    ZQ_POINT_USD,
    ZQ_TICK_BP,
    applicable_source_day,
    compounding_bias_bp,
    day_regime_index,
    effr_publication_days,
    expected_settle_rate,
    half_tick_onset,
    round_settle_rate,
    tick_bp,
    zq_exposure_matrix,
    zq_exposure_vector,
    zq_regime_weights,
)
from RVUtils.MeanRev.ff import delivery_window as zq_delivery_window
from RVUtils.MeanRev.ff import month_code as zq_month_code
from RVUtils.MeanRev.ff import round_trip_bp as zq_round_trip_bp
from RVUtils.MeanRev.engine import (
    COST_SCENARIOS,
    MRConfig,
    MRResult,
    grid_search,
    leg_round_trip_bp,
    run_backtest,
    run_continuous,
)
from RVUtils.MeanRev.meetings import (
    FOMC_DECISIONS,
    LAST_ACTUAL_YEAR,
    LAST_PUBLISHED_YEAR,
    calendar_fly_loading,
    calendar_fly_panel,
    calendar_tilted_fly,
    contract_weight_table,
    effective_meeting_count,
    fomc_decisions,
    fomc_schedule,
    meeting_count_gaps,
    meeting_residual_panel,
    meeting_weight_matrix,
    solve_smooth_path,
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
    calendar_adjusted_signal,
    curvefit_residual_signal,
    kalman_level_signal,
    meeting_residual_signal,
    ou_sscore_signal,
    pca_residual_signal,
    structure_signal_from_slots,
    xsection_signal,
    zscore_signal,
)

__all__ = [
    "COST_SCENARIOS", "MRConfig", "MRResult", "grid_search", "leg_round_trip_bp",
    "run_backtest", "run_continuous",
    "FLY_WEIGHTS_CONTRACTS", "SR3_DV01_USD", "SR3_HALF_SPREAD_BP",
    "PackageWeights", "best_integer_weights", "integer_weight_frontier",
    "package_contracts", "package_cost_bp", "package_cost_usd",
    "package_dv01_usd", "spread_from_weights",
    "add_strip_slots", "cm_label", "enumerate_structures", "pivot_levels",
    "regime_tag", "structure_liquidity",
    "shadow_levels", "shadow_table",
    "bollinger_signal", "coint_spread_signal", "curvefit_residual_signal",
    "kalman_level_signal", "ou_sscore_signal", "pca_residual_signal",
    "xsection_signal", "zscore_signal",
    "meeting_residual_signal", "calendar_adjusted_signal",
    "structure_signal_from_slots",
    "FOMC_DECISIONS", "LAST_ACTUAL_YEAR", "LAST_PUBLISHED_YEAR",
    "calendar_fly_loading", "calendar_fly_panel", "calendar_tilted_fly",
    "contract_weight_table",
    "effective_meeting_count", "fomc_decisions", "fomc_schedule",
    "meeting_count_gaps", "meeting_residual_panel", "meeting_weight_matrix",
    "solve_smooth_path",
    "forward_move", "move_profile", "oracle_table", "selectivity_table",
    "signal_entry_mask", "variance_decomposition",
    "ZQ_DV01_USD", "ZQ_POINT_USD", "ZQ_TICK_BP", "ZQ_HALF_TICK_BP",
    "applicable_source_day", "compounding_bias_bp", "day_regime_index",
    "effr_publication_days", "expected_settle_rate", "half_tick_onset",
    "round_settle_rate", "tick_bp", "zq_delivery_window", "zq_exposure_matrix",
    "zq_exposure_vector", "zq_month_code", "zq_regime_weights",
    "zq_round_trip_bp",
]

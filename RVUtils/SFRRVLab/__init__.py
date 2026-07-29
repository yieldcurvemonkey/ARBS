"""SR3 futures-vs-options relative-value lab.

A premium-native backtest stack for listed 3M SOFR futures against their listed
options. See ``docs/superpowers/specs/2026-07-29-sfr-rv-lab-design.md``.

The design constraint that shapes the whole package: put-call parity and the
conversion arb pin each surface's risk-neutral mean to its own futures settle,
so there is **no mean-level RV** between the two markets. Relative value lives
only in within-contract shape, cross-contract coupling, implied-vs-realized, and
event-speed differences — and every framework here is marked on listed settle
premiums at strikes fixed on the execution bar, with lag-1 fills.

Modules
-------
``structures``  Leg / Structure / MarkBook and how a package is marked in bp.
``panels``      panel IO, parity hygiene, strike selection, digitals, FOMC dates.
``signals``     premium-native signal panels (skew, digital calendars, vol, wings).
``engine``      the single backtest loop (fade AND momentum) + grid search.
``stats``       grid distribution, deflated Sharpe, neighbourhood stability.
"""
from RVUtils.SFRRVLab.engine import (
    COST_SCENARIOS,
    LabConfig,
    LabResult,
    grid_search,
    run_backtest,
)
from RVUtils.SFRRVLab.panels import (
    FOMC_DATES,
    add_event_distance,
    atm_premium_panel,
    attach_parity_flag,
    constant_maturity_slots,
    digital_panel,
    load_panels,
    parity_residuals,
    pick_listed_strike,
    realized_vol_bp,
    vertical_digital,
)
from RVUtils.SFRRVLab.signals import (
    adjacent_pairs,
    contract_pairs,
    delta_hedged_pnl,
    digital_calendar_panel,
    digital_legs,
    pair_rr_basis,
    quarterly_sort_key,
    risk_reversal_panel,
    vol_smile_panel,
    wing_panel,
    zscore_by_key,
)
from RVUtils.SFRRVLab.stats import (
    cost_curve,
    deflated_for_grid,
    grid_distribution,
    neighbourhood_stability,
    nonoverlapping_sharpe,
    nw_tstat,
    verdict,
)
from RVUtils.SFRRVLab.structures import (
    DOLLARS_PER_BP,
    Leg,
    MarkBook,
    Structure,
    hedge_each_contract,
    hedged_path,
    mark_structure,
    package_contracts,
    round_trip_cost_bp,
    structure_delta,
)

__all__ = [
    "COST_SCENARIOS", "DOLLARS_PER_BP", "FOMC_DATES",
    "LabConfig", "LabResult", "Leg", "MarkBook", "Structure",
    "add_event_distance", "adjacent_pairs", "atm_premium_panel",
    "attach_parity_flag", "constant_maturity_slots", "contract_pairs",
    "cost_curve", "deflated_for_grid", "delta_hedged_pnl",
    "digital_calendar_panel", "digital_legs",
    "digital_panel", "grid_distribution", "grid_search", "load_panels",
    "mark_structure", "neighbourhood_stability", "nonoverlapping_sharpe",
    "nw_tstat", "pair_rr_basis", "parity_residuals", "pick_listed_strike",
    "quarterly_sort_key", "realized_vol_bp", "risk_reversal_panel",
    "round_trip_cost_bp", "run_backtest", "structure_delta", "verdict",
    "vertical_digital", "vol_smile_panel", "wing_panel", "zscore_by_key",
]

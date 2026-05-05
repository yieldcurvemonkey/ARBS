"""STIR Options Asymmetric Screener.

Daily screener that ranks asymmetric STIR options trades driven by
policy-rate-path mispricing. Each candidate is classified into one of
eight structural archetypes from the design spec
``docs/plans/2026-05-04-stir-asymmetric-screener-design.md`` (§1):
wing, wide vertical, risk reversal, ratio, ladder, conditional curve,
tree (broken fly), and condor.

**Public entry point**::

    from RVUtils.STIRAsymmetricScreener import build_snapshot, ScreenerConfig
    snap = build_snapshot(ScreenerConfig(), as_of=datetime.date(2026, 5, 4))
    df = snap.to_dataframe()  # spec §7 columns

The orchestrator runs:

1. ``_universe.resolve_universe`` (§0) — quarterly/serial/midcurve grid
   inside the configured DTE band.
2. ``_market_data.load_market_data`` (§3 of plan) — SABR smiles, OIS
   curve, FOMC schedule, per-leg quotes/OI/bid-ask, historical IV/RR.
3. ``_rnd.extract_per_expiry_rnd`` (§12) — Breeden-Litzenberger density
   with smoothing-spline stability checks, bimodality detection, and a
   side-by-side SABR-implied density for §2.9b divergence flagging.
4. ``_path.extract_fomc_path`` (§5) — cumulative cuts/hikes by horizon
   and per-meeting marginal change.
5. ``_catalysts.load_catalyst_calendar`` (§6) — FOMC + ECB meetings.
6. ``_enumerate.*`` (§1.1–§1.8) — eight archetype-specific enumerators.
7. ``_payoff.max_payoff_loss`` + ``_greeks.compute_greeks`` (§7) — entry
   + aged Greeks, payoff bounds, breakeven roots.
8. ``_carry.compute_carry`` (§2.7) — static-curve aged premium at
   1w/1m/3m/to-expiry.
9. ``_signals.compute_all_signals`` (§2) — eleven signals matching spec
   §2.1–§2.10.
10. ``_gates.GATE_BY_ARCHETYPE`` (§3) — per-archetype gate tables.
11. ``_scoring.composite_asymmetry_score`` (§4) — composite ranking
    score with sub-component breakdown.
12. ``_output.write_snapshot`` — parquet + JSON sidecar persistence.

**Implementation plan**: ``docs/plans/2026-05-04-stir-asymmetric-screener.md``.

**To extend with a new archetype**:

1. Add the ``ArchetypeType`` member.
2. Add an enumerator under ``_enumerate/<archetype>.py`` returning
   ``List[CandidateDef]``; register it in ``_enumerate/__init__.py``.
3. Add a gate function in ``_gates.py``; register it in
   ``GATE_BY_ARCHETYPE``.
4. Update ``ScreenerConfig.min_payoff_multiple_per_archetype`` default.
5. Add a test fixture under ``tests/test_stir_asym_screener_enumerate.py``.
"""

from RVUtils.STIRAsymmetricScreener._types import (
    ArchetypeType,
    CandidateDef,
    CandidateResult,
    OptionLeg,
    ScreenerConfig,
    ScreenerSnapshot,
)
from RVUtils.STIRAsymmetricScreener._universe import (
    ContractEntry,
    UniverseEntry,
    attach_strike_grid,
    enumerate_contracts,
    resolve_universe,
)
from RVUtils.STIRAsymmetricScreener._market_data import (
    LegMarket,
    STIRMarketData,
    load_market_data,
)
from RVUtils.STIRAsymmetricScreener._rnd import (
    RNDRecord,
    extract_per_expiry_rnd,
    payoff_zone_probability,
    sabr_rnd_payoff_zone_diff,
)
from RVUtils.STIRAsymmetricScreener._catalysts import (
    Catalyst,
    catalysts_inside_window,
    load_catalyst_calendar,
)
from RVUtils.STIRAsymmetricScreener._path import (
    FOMCPath,
    PathScenario,
    cumulative_path_mispricing_bp,
    enumerate_path_scenarios,
    extract_fomc_path,
    path_scenario_probability_rnd,
)
from RVUtils.STIRAsymmetricScreener._output import (
    snapshot_to_dataframe,
    write_snapshot,
)
from RVUtils.STIRAsymmetricScreener.screener import build_snapshot

__all__ = [
    "ArchetypeType",
    "CandidateDef",
    "CandidateResult",
    "Catalyst",
    "ContractEntry",
    "FOMCPath",
    "LegMarket",
    "OptionLeg",
    "PathScenario",
    "RNDRecord",
    "STIRMarketData",
    "ScreenerConfig",
    "ScreenerSnapshot",
    "UniverseEntry",
    "attach_strike_grid",
    "build_snapshot",
    "catalysts_inside_window",
    "cumulative_path_mispricing_bp",
    "enumerate_contracts",
    "enumerate_path_scenarios",
    "extract_fomc_path",
    "extract_per_expiry_rnd",
    "load_catalyst_calendar",
    "load_market_data",
    "path_scenario_probability_rnd",
    "payoff_zone_probability",
    "resolve_universe",
    "sabr_rnd_payoff_zone_diff",
    "snapshot_to_dataframe",
    "write_snapshot",
]

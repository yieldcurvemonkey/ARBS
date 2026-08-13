"""GSS cash-bond butterfly book — a UST re-target of the GSS curve-fitting RV process.

Ported from ``jpm_pfin/RelativeValue/ag_processes/CURVE_FITTING/python/GSS``. Self-contained:
nothing here imports from :mod:`BT.xccy_rv`.

The chain is: fitted-curve residual per bond → blended time-series / cross-sectional richness
score → butterfly construction (wing selection, maturity weights, sign by the fly's own z) →
vol-scaled entry with turning-point timing → exit on decay below the repo hurdle → QDB.

Quick start
-----------
>>> from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
>>> from BT.gss_fly import GSSConfig, build_curve_panel, run_gss_backtest
>>> mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
>>> panel = build_curve_panel(business_days, mdp)          # doctest: +SKIP
>>> res = run_gss_backtest(panel, mdp, cfg=GSSConfig())    # doctest: +SKIP
>>> res.summary()                                          # doctest: +SKIP
"""

from BT.gss_fly.config import (
    REPO_BASIS,
    BacktestConfig,
    BondSignalConfig,
    CostConfig,
    FlyConfig,
    GSSConfig,
    UniverseConfig,
)
from BT.gss_fly.costs import (
    FINANCED,
    REPO_COLLATERAL,
    REPO_TENORS,
    UNFINANCED,
    RepoCurve,
    basis_note,
    fly_tcost_bp,
    load_repo_from_workbook,
    repo_carry_bp,
    repo_tag,
    repo_tag_grid,
    resolve_repo_curve,
)
from BT.gss_fly.data import (
    BOND_SNAPSHOT_VALUES,
    CurvePanel,
    apply_universe_filter,
    build_curve_panel,
    fetch_curveset_snapshot,
    warm_bond_snapshots,
)
from BT.gss_fly.flies import (
    FlyState,
    build_fly_state,
    build_weights,
    scan_flies,
    select_wings,
    wing_window,
)
from BT.gss_fly.signals import (
    build_bond_signals,
    cross_sectional_zscore,
    ewm_zscore,
    ts_scoring,
)

__all__ = [
    "GSSConfig",
    "BondSignalConfig",
    "UniverseConfig",
    "FlyConfig",
    "CostConfig",
    "BacktestConfig",
    "REPO_BASIS",
    "CurvePanel",
    "build_curve_panel",
    "apply_universe_filter",
    "fetch_curveset_snapshot",
    "warm_bond_snapshots",
    "BOND_SNAPSHOT_VALUES",
    "ewm_zscore",
    "ts_scoring",
    "cross_sectional_zscore",
    "build_bond_signals",
    "wing_window",
    "select_wings",
    "build_weights",
    "FlyState",
    "build_fly_state",
    "scan_flies",
    "fly_tcost_bp",
    "repo_carry_bp",
    "RepoCurve",
    "load_repo_from_workbook",
    "resolve_repo_curve",
    "basis_note",
    "FINANCED",
    "UNFINANCED",
    "repo_tag",
    "repo_tag_grid",
    "REPO_TENORS",
    "REPO_COLLATERAL",
]


def __getattr__(name):  # pragma: no cover - lazy, keeps import cheap for pure-logic users
    if name in {"run_gss_backtest", "GSSResult", "summarize"}:
        from BT.gss_fly import backtest as _bt

        return getattr(_bt, name)
    if name in {"GSSSignalEngine", "GSSEntryAction", "GSSExitAction", "build_gss_trigger", "OpenFly"}:
        from BT.gss_fly import strategy as _st

        return getattr(_st, name)
    raise AttributeError(name)

"""Fly-vs-vol RV framework: SOFR butterflies vs option-implied distributions.

See ``docs/superpowers/specs/2026-07-28-fly-vs-vol-rv-framework-design.md``.
"""
from RVUtils.FlyVsVol._types import (
    FLY_WEIGHTS,
    ContractMarginal,
    FlyDefinition,
    FlySnapshot,
    FlyVsVolConfig,
    PathDistribution,
)
from RVUtils.FlyVsVol.convergence import (
    ConvergencePackage,
    SkewAttribution,
    WingLeg,
    WingQuote,
    convergence_package,
    skew_attribution,
)
from RVUtils.FlyVsVol.coupling import (
    comonotone_grid,
    gaussian_copula_sample,
    historical_corr,
)
from RVUtils.FlyVsVol.metrics import build_fly_snapshot, path_metrics
from RVUtils.FlyVsVol.screener import (
    adjacent_triples,
    history_zscores,
    run_fly_screener,
    screener_table,
)

__all__ = [
    "FLY_WEIGHTS",
    "ContractMarginal",
    "FlyDefinition",
    "FlySnapshot",
    "FlyVsVolConfig",
    "PathDistribution",
    "ConvergencePackage",
    "SkewAttribution",
    "WingLeg",
    "WingQuote",
    "convergence_package",
    "skew_attribution",
    "comonotone_grid",
    "gaussian_copula_sample",
    "historical_corr",
    "build_fly_snapshot",
    "path_metrics",
    "adjacent_triples",
    "history_zscores",
    "run_fly_screener",
    "screener_table",
]

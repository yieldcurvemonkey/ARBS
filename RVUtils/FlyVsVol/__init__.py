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

__all__ = [
    "FLY_WEIGHTS",
    "ContractMarginal",
    "FlyDefinition",
    "FlySnapshot",
    "FlyVsVolConfig",
    "PathDistribution",
]

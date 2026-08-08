"""Units, sign conventions and the labelled vol type.

Load-bearing conventions for the whole package:

* ``ASW = UST yield - matched swap rate`` (tool convention; the desk convention
  is its negative).
* ``curve = longer forward - shorter forward``; **negative means inverted**.
* A flattener receives the longer forward and pays the shorter. It is the
  long-convexity side and carries ``sign = FLATTENER = +1``.
* Rates are decimals, spreads are basis points, vols are **bp/day** internally.
  Annual normals appear only at display boundaries.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

TRADING_DAYS: float = 252.0

FLATTENER: int = 1
STEEPENER: int = -1

__all__ = [
    "TRADING_DAYS",
    "FLATTENER",
    "STEEPENER",
    "VolQuote",
    "annual_normals_to_bp_day",
    "bp_day_to_annual_normals",
    "slope_bp",
]


def annual_normals_to_bp_day(annual_normals: Any) -> Any:
    """Annualised normal vol (bp/yr) -> daily bp vol.

    Works on scalars and on array-likes (e.g. a pandas Series of daily
    implied-vol prints) alike: uses ``np.asarray`` rather than ``float()``,
    which raises on a multi-element Series -- same pattern as ``slope_bp``.
    """
    return np.asarray(annual_normals) / math.sqrt(TRADING_DAYS)


def bp_day_to_annual_normals(bp_day: Any) -> Any:
    """Daily bp vol -> annualised normal vol (bp/yr).

    Works on scalars and on array-likes alike -- see ``annual_normals_to_bp_day``.
    """
    return np.asarray(bp_day) * math.sqrt(TRADING_DAYS)


def slope_bp(*, short_rate: Any, long_rate: Any) -> Any:
    """Forward slope in bp: (longer forward - shorter forward), both decimals.

    Works on scalars and on array-likes (e.g. a pandas Series of decimal par
    rates) alike: uses ``np.asarray`` rather than ``float()``, which raises on
    a multi-element Series. One formula serves both a single scalar slope and
    a vectorised panel column -- callers that need pandas metadata (index,
    name) back re-attach it themselves; this function only computes the
    number(s).

    Negative = inverted = the normal state of the ultra-long forward curve.
    """
    return (np.asarray(long_rate) - np.asarray(short_rate)) * 10_000.0


@dataclass(frozen=True)
class VolQuote:
    """A vol that states what it is computed on.

    Unlabelled floats do not cross module boundaries in this package: a vol is
    only interpretable alongside its measure, underlying and window.
    """

    value_bp_day: float
    measure: str  # "realized" | "implied" | "breakeven"
    underlying: str  # e.g. "USD 20y10y forward par rate"
    window: str  # e.g. "63d" | "atm 2y10y" | "h=25bp"

    @property
    def annual_normals(self) -> float:
        return bp_day_to_annual_normals(self.value_bp_day)

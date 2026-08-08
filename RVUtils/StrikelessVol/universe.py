"""The tradeable universe, bounded by measured provider coverage.

Coverage was read from the GS instrument sheet
``MDP/IRSwaps/GSQUANT/COVERAGE/IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx``
(33,111 rows, local, no network):

===========  ==================  ==============
market       longest observed    history starts
===========  ==================  ==============
USD (OIS)    30y                 2010-01-04
USD (SOFR)   30y                 2018-04-27
EUR (ESTR)   50y                 ~2019
JPY (TONA)   30y                 2010-01-04
GBP (OIS)    50y                 2010-01-04
===========  ==================  ==============

USD ``10y10y/25y10y`` needs a 35y point that no GS tenor publishes, so it is
absent here by construction rather than filtered later. Nothing in this package
prices a leg whose end point is beyond its market's observed coverage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

_TENOR_RE = re.compile(r"^(\d+)([DWMY])$", re.IGNORECASE)

_UNIT_YEARS = {"D": 1.0 / 365.0, "W": 7.0 / 365.0, "M": 1.0 / 12.0, "Y": 1.0}

MARKET_MAX_POINT_YEARS: Dict[str, float] = {
    "USD": 30.0,
    "EUR": 50.0,
    "JPY": 30.0,
    "GBP": 50.0,
}

MARKET_CURVES: Dict[str, str] = {
    "USD": "USD-OIS",
    "EUR": "EUR-ESTR",
    "JPY": "JPY-TONAR",
    # GBP-SONIA already exists in Query/IRSwaps/backends/rateslib/
    # rl_curve_definitions_map.py; only the GSQUANT build definition is missing.
    "GBP": "GBP-SONIA",
}


def tenor_years(label: str) -> float:
    """'10Y' -> 10.0, '6M' -> 0.5. Raises on anything else."""
    m = _TENOR_RE.match(str(label).strip())
    if not m:
        raise ValueError(f"Unsupported tenor label: {label!r}")
    return float(m.group(1)) * _UNIT_YEARS[m.group(2).upper()]


@dataclass(frozen=True)
class ForwardLeg:
    """A forward-starting par swap: ``fwd`` forward into a ``tail`` swap."""

    fwd: str
    tail: str

    @property
    def label(self) -> str:
        return f"{self.fwd}{self.tail}".upper()

    @property
    def fwd_years(self) -> float:
        return tenor_years(self.fwd)

    @property
    def tail_years(self) -> float:
        return tenor_years(self.tail)

    @property
    def end_years(self) -> float:
        return self.fwd_years + self.tail_years


@dataclass(frozen=True)
class ForwardPair:
    """A slope: receive ``long``, pay ``short``, DV01-neutral (the flattener)."""

    market: str
    curve_name: str
    short: ForwardLeg
    long: ForwardLeg

    @property
    def name(self) -> str:
        return f"{self.market} {self.short.label}/{self.long.label}"

    @property
    def required_point_years(self) -> float:
        return max(self.short.end_years, self.long.end_years)


def _pair(market: str, s_fwd: str, s_tail: str, l_fwd: str, l_tail: str) -> ForwardPair:
    return ForwardPair(
        market=market,
        curve_name=MARKET_CURVES[market],
        short=ForwardLeg(s_fwd, s_tail),
        long=ForwardLeg(l_fwd, l_tail),
    )


USD_PAIRS = (
    _pair("USD", "10Y", "10Y", "20Y", "10Y"),
    _pair("USD", "15Y", "5Y", "20Y", "10Y"),
    _pair("USD", "5Y", "10Y", "15Y", "10Y"),
)

EUR_PAIRS = (
    _pair("EUR", "10Y", "10Y", "20Y", "10Y"),
    _pair("EUR", "15Y", "5Y", "20Y", "10Y"),
    _pair("EUR", "10Y", "10Y", "25Y", "10Y"),
)

JPY_PAIRS = (
    _pair("JPY", "10Y", "10Y", "20Y", "10Y"),
    _pair("JPY", "15Y", "5Y", "20Y", "10Y"),
)

GBP_PAIRS = (
    _pair("GBP", "15Y", "10Y", "25Y", "10Y"),
    _pair("GBP", "10Y", "10Y", "20Y", "10Y"),
)

ALL_PAIRS = USD_PAIRS + EUR_PAIRS + JPY_PAIRS + GBP_PAIRS

# Short-dated slopes where the convexity story should NOT hold. The identical
# rulebook is run on these; a "signal" that survives here is a calendar or
# curve-shape artifact, not convexity.
PLACEBO_PAIRS = (
    _pair("USD", "1Y", "5Y", "2Y", "5Y"),
    _pair("USD", "2Y", "2Y", "3Y", "2Y"),
)


def supported_pairs(
    pairs: Iterable[ForwardPair],
    max_point_years: Dict[str, float] | None = None,
) -> List[ForwardPair]:
    """Drop any pair whose longest point is not an observed instrument."""
    caps = MARKET_MAX_POINT_YEARS if max_point_years is None else max_point_years
    return [p for p in pairs if p.required_point_years <= caps[p.market]]

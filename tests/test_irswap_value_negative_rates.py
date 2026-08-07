r"""``IRSwapValue.RATE`` must carry a negative rate's sign.

``calc_spread_rate`` used to wrap each leg's fair rate in ``abs()``. That is
invisible while every rate in the book is positive - which every curve this repo
priced before 2026-08-07 was - and wrong the moment one is not.

Found by tying the new Citi Velocity source out against Citi's own quotes: CHF
SARON's front is **-0.055314%** and an outright came back as **+0.055314%**, an
11.06 bp error, exactly twice the rate. A curve trade whose legs straddle zero was
wrong by a similar amount in the other direction.

``abs()`` cannot have been sign normalisation. ``fair_rate`` is a par rate and
carries no direction; the direction lives in the risk weights, which
``_swap_structure_sign_mapper`` applies on the line above.
"""

from __future__ import annotations

import datetime as dt

import pytest

from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue


class _Swap:
    def __init__(self, tenor: str, notional: float, fixed_rate: float):
        self.tenor = tenor
        self.notional = notional
        self.fixed_rate = fixed_rate

    @property
    def tenor_years(self) -> float:
        return float(self.tenor.rstrip("Yy"))


class _NegativeRateCurve:
    """A curve whose front is negative and whose long end is positive - CHF's shape."""

    RATES = {"1Y": -0.00055314, "2Y": -0.00021, "10Y": 0.0063500}

    def id(self):
        return "CHF-SARON-1D"

    def reference_date(self):
        return dt.date(2026, 8, 6)

    def calendar_advance(self, ref_date, tenor):
        _ = tenor
        return ref_date

    def build_irswap(
        self, fwd=None, tenor=None, effective_date=None, maturity_date=None,
        fixed_rate=-0.0, notional=None, bpv=None,
    ):
        _ = fwd, effective_date, maturity_date, fixed_rate
        return _Swap(tenor or "1Y", float(notional or bpv or 1_000_000.0), self.RATES[tenor or "1Y"])

    def fair_rate(self, instrument):
        return self.RATES[instrument.tenor]

    def pv01(self, instrument):
        return abs(instrument.notional) * instrument.tenor_years * 1e-4

    def dv01(self, instrument):
        return self.pv01(instrument)

    def npv(self, instrument):
        return 0.0

    def meta(self):
        return {}


def _rate(structure, **kwargs):
    query = IRSwapQuery(structure=structure, value=IRSwapValue.RATE, **kwargs)
    curve = _NegativeRateCurve()
    package, weights = query.resolve_package(pricer_or_curve=curve)
    value_map = query.build_value_map(pricer_or_curve=curve, package=package, risk_weights=weights)
    return float(value_map.apply(IRSwapValue.RATE))


def test_an_outright_at_a_negative_rate_keeps_its_sign():
    """The measured CHF case: -0.055314% must not come back as +0.055314%."""
    got = _rate(
        IRSwapStructure.OUTRIGHT,
        tenor="1Y",
        curve="CHF-SARON-1D",
        structure_kwargs={"notional": 1_000_000},
    )
    assert got == pytest.approx(-0.055314, abs=1e-9)


def test_an_outright_at_a_positive_rate_is_unchanged():
    """The fix must be a no-op for every curve that was already correct."""
    got = _rate(
        IRSwapStructure.OUTRIGHT,
        tenor="10Y",
        curve="CHF-SARON-1D",
        structure_kwargs={"notional": 1_000_000},
    )
    assert got == pytest.approx(0.635, abs=1e-9)


def test_a_curve_trade_whose_legs_straddle_zero():
    """1s10s across zero. With ``abs()`` the front leg contributed the wrong sign,
    understating the slope by twice the front rate: 58.0 bp instead of 69.0 bp."""
    got = _rate(
        IRSwapStructure.CURVE,
        curve="CHF-SARON-1D",
        structure_kwargs={"front_tenor": "1Y", "back_tenor": "10Y", "bpv": 10_000},
    )
    assert got == pytest.approx((0.0063500 - -0.00055314) * 10_000, abs=1e-6)
    assert got > 69.0, "the slope must include the front leg's negative sign"

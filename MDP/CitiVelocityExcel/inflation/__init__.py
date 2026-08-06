r"""Inflation curves, breakevens and linkers built from Citi Velocity quotes.

Citi serves four inflation families, all 100% shape-valid in the harvest:

``RATES.INFLATION.SWAP.<index>.<tenor>``
    Zero-coupon inflation swap rates - breakevens - in percent, across 17 index
    tokens on a 16-point tenor axis plus ``SPOT``. This is the curve input.
``RATES.INFLATION.INDEX.<token>``
    Published index levels for five series (``US_CPIZU``, ``UK_RPI``,
    ``EURO_HICPXT``, ``FRANCE_CPI``, ``SWEDEN_CPI``). This is where the
    ``index_base`` and the historic fixings come from - and getting that number
    from the wrong month is the single most expensive mistake in the package.
``RATES.INFLATION.INF_CARRY.<curve>.<index>.<measure>``
    ``IOTA``, ``CARRYADJIOTA``, ``NETBEICARRY``, ``NOMINALYIELDCARRY``,
    ``REALYIELDCARRY`` for six curves.
``RATES.INFLATION.SWAPTION.<index>.ATM.{NORMAL,FWDPREMIUM}``
    Three indices only. The level below ``NORMAL`` is a 19-point axis that the
    Function Builder walk did not expand, so whether it is expiry-only or
    expiry x tail is **unverified**; nothing here consumes it.

Two backends, deliberately
--------------------------
:mod:`rl_inflation` builds in rateslib 2.1.1 (no ``IndexCurve`` class in this
version - an index curve is a :class:`rateslib.Curve` carrying ``index_base`` and
``index_lag``). :mod:`ql_inflation` builds in QuantLib 1.41
(:class:`ql.PiecewiseZeroInflation` off :class:`ql.ZeroCouponInflationSwapHelper`).

Measured in ``_smoke.py`` on a synthetic 12-point curve for USD_CPURNSA,
GBP_UKRPI and EUR_CPTFEMU: each backend reprices its own calibration set to
**2.2e-06 bp** or better, and the two agree at the pillars to **2e-06 bp** - but
that pillar agreement is mostly the round trip restated, because calibration pins
it. The informative numbers are **off-pillar**, where the two interpolate
different quantities and diverge by up to **0.64 bp** (worst at 4Y, between the 3Y
and 5Y pillars), and the **implied index level**, which the two fixed-leg year
counts pull apart by up to **1.53 bp of level** at the one pillar whose maturity
is business-day adjusted off its anniversary. QuantLib alone handles quarterly
indices and seasonality.

What none of that proves: **a self-consistent observation-lag error is invisible
to every test here.** Rebuild at a 6-month lag with a 6-month-lagged base and the
breakevens do not move at all. Only the index level does. The conventions in
:mod:`indices` carry their provenance for exactly that reason.

Run ``python -m MDP.CitiVelocityExcel.inflation._smoke`` for the round trip.
"""

from __future__ import annotations

from MDP.CitiVelocityExcel.inflation.indices import (
    CARRY_CURVE_FOR_INDEX,
    CITI_INFLATION_INDICES,
    CITI_LINKER_CONVENTIONS,
    CITI_ZC_TENORS,
    DEFAULT_CALIBRATION_TENORS,
    INDEX_LEVEL_TOKEN_FOR_SWAP_INDEX,
    SWAPTION_INDICES,
    InflationIndexConvention,
    LinkerConvention,
    conventions_for,
    describe,
    index_base_month,
    linker_conventions_for,
    reference_month,
    required_fixing_months,
    supported_indices,
    tenor_to_years,
)
from MDP.CitiVelocityExcel.inflation.ql_inflation import (
    QLInflationCurve,
    build_ql_zero_inflation_curve,
    clear_ql_index_fixings,
    ql_breakeven,
    ql_forward_breakeven,
    ql_multiplicative_seasonality,
    ql_zc_inflation_swap,
    ql_zc_inflation_swap_npv,
)
from MDP.CitiVelocityExcel.inflation.rl_inflation import (
    IndexBondDescriptor,
    RLIndexCurve,
    build_rl_index_curve,
    build_rl_zcis,
    rl_breakeven,
    rl_forward_breakeven,
    rl_index_bond,
    rl_index_fixings_series,
)

__all__ = [
    "CARRY_CURVE_FOR_INDEX",
    "CITI_INFLATION_INDICES",
    "CITI_LINKER_CONVENTIONS",
    "CITI_ZC_TENORS",
    "DEFAULT_CALIBRATION_TENORS",
    "INDEX_LEVEL_TOKEN_FOR_SWAP_INDEX",
    "IndexBondDescriptor",
    "InflationIndexConvention",
    "LinkerConvention",
    "QLInflationCurve",
    "RLIndexCurve",
    "SWAPTION_INDICES",
    "build_ql_zero_inflation_curve",
    "build_rl_index_curve",
    "build_rl_zcis",
    "clear_ql_index_fixings",
    "conventions_for",
    "describe",
    "index_base_month",
    "linker_conventions_for",
    "ql_breakeven",
    "ql_forward_breakeven",
    "ql_multiplicative_seasonality",
    "ql_zc_inflation_swap",
    "ql_zc_inflation_swap_npv",
    "reference_month",
    "required_fixing_months",
    "rl_breakeven",
    "rl_forward_breakeven",
    "rl_index_bond",
    "rl_index_fixings_series",
    "supported_indices",
    "tenor_to_years",
]

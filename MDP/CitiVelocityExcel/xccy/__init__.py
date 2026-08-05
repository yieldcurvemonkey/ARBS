r"""Cross-currency basis from Citi Velocity, priced in rateslib and QuantLib.

``RATES.XCCY_OIS_SWAP.<ccy1>.<ccy2>.<fwd>.<tenor>.{BASE_LEG,SPREAD_LEG}.BASIS_SPREAD``
is the only Velocity family that validated 1,097/1,097 - every recorded tag is
shape-correct end to end - across 16 base and 12 quote currency tokens.

Layers
------
``basis_data``  :class:`XccyBasisCurve` plus the fetch/offline constructors
``rl_xccy``     :class:`rateslib.XCS` assembly and the collateral-curve solve
``ql_xccy``     explicit-cashflow swap and a hand-rolled discount bootstrap

Read before trusting a number
-----------------------------
* Which currency Velocity's ``SPREAD_LEG`` denotes is **not** recorded in the
  harvest. The default follows market convention (spread on the non-USD leg) and
  is an assumption; ``spread_ccy=`` overrides it.
* The sign and units of ``BASIS_SPREAD`` are documented as basis points but
  unverified against a live quote; ``sign=`` and ``scale=`` override them.
* The QuantLib side is **constant-notional**; the rateslib side defaults to the
  market-standard MTM leg. They therefore do not produce the same fair spread,
  by design. ``MDP/CitiVelocityExcel/xccy/_smoke.py`` measures the gap.
* ``AUD_BBSW`` and ``NZD_BKBM`` are IBOR-indexed legs. Both backends refuse them
  rather than price a term-fixing leg as compounded OIS.
"""

from __future__ import annotations

from MDP.CitiVelocityExcel.xccy.basis_data import (
    PRIMARY_OIS_INDEX,
    XCCY_BASE_CURRENCIES,
    XCCY_QUOTE_CURRENCIES,
    XCCY_TENORS,
    XccyBasisCurve,
    basis_from_quotes,
    conventions_for_currency,
    default_collateral_ccy,
    default_spread_ccy,
    fetch_xccy_basis,
    iso_currency,
    ois_index_for_currency,
)
from MDP.CitiVelocityExcel.xccy.ql_xccy import (
    QLCrossCurrencySwap,
    bootstrap_ql_xccy_discount_curve,
    build_ql_xccy_swap,
    ql_curve_from_rl,
    ql_fair_basis_spread,
    ql_xccy_reprice_errors_bp,
)
from MDP.CitiVelocityExcel.xccy.rl_xccy import (
    RL_XCS_SPECS,
    RLXccyCurves,
    build_rl_xcs,
    rl_xccy_reprice_errors_bp,
    rl_xcs_kwargs,
    solve_rl_collateral_curve,
)

__all__ = [
    "PRIMARY_OIS_INDEX",
    "QLCrossCurrencySwap",
    "RLXccyCurves",
    "RL_XCS_SPECS",
    "XCCY_BASE_CURRENCIES",
    "XCCY_QUOTE_CURRENCIES",
    "XCCY_TENORS",
    "XccyBasisCurve",
    "basis_from_quotes",
    "bootstrap_ql_xccy_discount_curve",
    "build_ql_xccy_swap",
    "build_rl_xcs",
    "conventions_for_currency",
    "default_collateral_ccy",
    "default_spread_ccy",
    "fetch_xccy_basis",
    "iso_currency",
    "ois_index_for_currency",
    "ql_curve_from_rl",
    "ql_fair_basis_spread",
    "ql_xccy_reprice_errors_bp",
    "rl_xccy_reprice_errors_bp",
    "rl_xcs_kwargs",
    "solve_rl_collateral_curve",
]

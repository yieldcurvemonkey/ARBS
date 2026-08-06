"""Single-look CMS spread options and midcurve swaptions, from Citi Velocity quotes.

Two families, both quoted by the desk and both **unverified below the measure
level** - the Function Builder walk was depth-capped above their expiry levels,
so the tag shapes here come from the desk's documentation and have never been
confirmed against ``CVTSHIST``. Every builder in this sub-package says so, and
:func:`~MDP.CitiVelocityExcel.options.spread_options.fetch_spread_options` and
:func:`~MDP.CitiVelocityExcel.options.midcurves.fetch_midcurves` raise rather
than return an empty list when the shape turns out to be wrong.

``spread_options``
    ``RATES.SPREAD_OPTIONS.<ccy>.{OPT_CAP,OPT_FLR,OPT_STR}.{PRICE,VOL}.<expiry>.<pair>``.
    One European option on ``CMS_long - CMS_short`` at one expiry - **not** a
    strip, which is what a CMS spread cap is. Priced in closed form on the
    spread's normal vol, with Hagan's standard CMS convexity adjustment on each
    leg. QuantLib's CMS-spread machinery is coupon-based and prices the strip;
    :func:`~MDP.CitiVelocityExcel.options.spread_options.build_ql_cms_spread`
    builds it and labels it as such.
``midcurves``
    ``RATES.MIDCURVES.<ccy>.{OPT_PAY,OPT_REC,OPT_STR}.{PRICE,VOL}.<expiry>.<underlying>``.
    An option expiring at ``T`` on a swap that starts after ``T``. The formula is
    Bachelier; everything midcurve-specific is in which forward, which annuity
    and which vol you feed it.

Both are built from repo primitives (``Query.Base.bachelier``, the catalog's
tenor grammar) plus QuantLib. rateslib 2.1.1 has no IR volatility object of any
kind - no swaption, no cube, no ``rateslib.volatility`` module; its only vol
classes are FX - so its role here is the discount curve and nothing else.

**Units: everything here is in DECIMALS.** ``0.0425`` for 4.25%, ``0.01`` for a
100 bp normal vol. The sibling
:class:`MDP.CitiVelocityExcel.vol.cube_data.SwaptionCubeData` stores vols in
basis points and Citi's ``PAR`` tags serve percent, so
:func:`~MDP.CitiVelocityExcel.options.midcurves.midcurve_from_vol_cube` converts
using the cube's own ``vol_unit`` and every pricer calls
:func:`~MDP.CitiVelocityExcel.options.spread_options.assert_decimal_rate`, which
raises on anything above 1.0. A 1e4 slip cannot reach a price.

Verified against QuantLib at the numbers ``_smoke.py`` prints, each with its
control: the closed-form CMS convexity adjustment matches ``ql.LinearTsrPricer``
to 0.006 bp on a FLAT curve (where its own flat-yield assumption holds, so that
is the algebra) and to 0.20 bp on a sloped one (which is the approximation's real
cost); the Bachelier single look matches ``ql.LognormalCmsSpreadPricer`` to
9e-15 bp with a normal surface - a wiring check, since both then reduce to the
same formula - and differs by ~0.5 bp against a lognormal one, which is the
honest model error bar.
"""

from __future__ import annotations

from MDP.CitiVelocityExcel.options.midcurves import (
    MIDCURVE_CURRENCIES,
    MIDCURVE_KINDS,
    MIDCURVE_START_IS_RELATIVE_TO_EXPIRY,
    MidcurveQuote,
    add_tenors,
    fetch_midcurves,
    midcurve_forward,
    midcurve_from_vol_cube,
    midcurve_implied_vol,
    midcurve_price,
    midcurve_vol_from_decomposition,
    parse_underlying,
    underlying_token,
)
from MDP.CitiVelocityExcel.options.spread_options import (
    QUANTLIB_SINGLE_LOOK_NOTE,
    SPREAD_IS_LONG_MINUS_SHORT,
    SPREAD_OPTION_CURRENCIES,
    SPREAD_OPTION_KINDS,
    QlCmsSpreadBuild,
    SpreadOptionQuote,
    assert_decimal_rate,
    build_ql_cms_spread,
    cms_rate,
    correlation_from_spread_vol,
    fetch_spread_options,
    forward_swap_rate,
    hagan_convexity_adjustment,
    hagan_g_ratio,
    implied_correlation,
    normalise_right,
    pair_token,
    parse_pair,
    single_look_spread_option_price,
    split_concatenated_tenors,
    spread_normal_vol,
)

__all__ = [
    "MIDCURVE_CURRENCIES",
    "MIDCURVE_KINDS",
    "MIDCURVE_START_IS_RELATIVE_TO_EXPIRY",
    "MidcurveQuote",
    "QUANTLIB_SINGLE_LOOK_NOTE",
    "QlCmsSpreadBuild",
    "SPREAD_IS_LONG_MINUS_SHORT",
    "SPREAD_OPTION_CURRENCIES",
    "SPREAD_OPTION_KINDS",
    "SpreadOptionQuote",
    "add_tenors",
    "assert_decimal_rate",
    "build_ql_cms_spread",
    "cms_rate",
    "correlation_from_spread_vol",
    "fetch_midcurves",
    "fetch_spread_options",
    "forward_swap_rate",
    "hagan_convexity_adjustment",
    "hagan_g_ratio",
    "implied_correlation",
    "midcurve_forward",
    "midcurve_from_vol_cube",
    "midcurve_implied_vol",
    "midcurve_price",
    "midcurve_vol_from_decomposition",
    "normalise_right",
    "pair_token",
    "parse_pair",
    "parse_underlying",
    "single_look_spread_option_price",
    "split_concatenated_tenors",
    "spread_normal_vol",
    "underlying_token",
]

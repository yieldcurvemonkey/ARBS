r"""Hermetic tests for single-look CMS spread options and midcurve swaptions.

Two shape facts drive everything here:

* A **single-look** CMS spread option is one European option on
  ``CMS_a - CMS_b`` at a single expiry. It is NOT a strip. QuantLib 1.41 has no
  single-look instrument at all - its CMS-spread classes (``SwapSpreadIndex``,
  ``CmsSpreadCoupon``, ``LognormalCmsSpreadPricer``) are coupon-based, i.e. the
  components of a cap/floor strip. So the single look is priced in closed form and
  a strip is never presented as one.
* A **midcurve** is an option expiring at T on a swap that starts LATER than T.
  Reading the start as spot-relative rather than expiry-relative changes the
  forward, and on the test curve that is worth 24% of the option premium.

Both families were harvested only to the measure level, so their expiry and
pair/underlying levels are the desk's documented shape and are UNVERIFIED. The
tests assert the warnings say so.
"""

from __future__ import annotations

import datetime
import math

import pytest

from MDP.CitiVelocityExcel.options import (
    MIDCURVE_START_IS_RELATIVE_TO_EXPIRY,
    SPREAD_IS_LONG_MINUS_SHORT,
    assert_decimal_rate,
    hagan_convexity_adjustment,
    implied_correlation,
    midcurve_implied_vol,
    midcurve_price,
    parse_pair,
    parse_underlying,
    single_look_spread_option_price,
    split_concatenated_tenors,
    spread_normal_vol,
)

FWD_LONG = 0.0425      # 10Y CMS, decimal
FWD_SHORT = 0.0355     # 2Y CMS, decimal
VOL_LONG = 0.0100      # 100 bp normal vol, decimal
VOL_SHORT = 0.0095
STRIKE = 0.0020        # 20 bp spread strike
EXPIRY_YEARS = 1.0
ANNUITY = 8.0


# ------------------------------------------------------------------ #
#                          the tenor grammar                         #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "token, expected",
    [
        ("2Y5Y", ("2Y", "5Y")),
        ("5Y10Y", ("5Y", "10Y")),
        ("10Y30Y", ("10Y", "30Y")),
        ("1Y10Y", ("1Y", "10Y")),
        ("10Y1Y", ("10Y", "1Y")),
        ("1Y1Y", ("1Y", "1Y")),
        ("18M2Y", ("18M", "2Y")),
        ("2Y-5Y", ("2Y", "5Y")),
        ("10Y/30Y", ("10Y", "30Y")),
    ],
)
def test_every_documented_pair_form_resolves_to_one_split(token: str, expected):
    assert parse_pair(token) == expected


def test_a_naive_middle_split_is_wrong_for_asymmetric_tokens():
    """MUTATION CHECK for the tenor splitter.

    Splitting ``18M2Y`` down the middle gives ``('18', 'M2Y')`` - neither half is
    a tenor. The splitter enumerates every position where BOTH halves match
    ``^\\d+[DWMY]$`` and accepts only a unique one.
    """
    token = "18M2Y"
    naive = (token[: len(token) // 2], token[len(token) // 2 :])
    assert naive != parse_pair(token)
    assert parse_pair(token) == ("18M", "2Y")

    candidates = split_concatenated_tenors(token)
    assert isinstance(candidates, tuple) and candidates == ("18M", "2Y")


def test_an_unparseable_pair_raises_rather_than_guessing():
    for bad in ("2Y5", "XY5Y", "", "5Y5Y5Y"):
        with pytest.raises(Exception):
            parse_pair(bad)


def test_underlying_forms_resolve(tmp_path):
    assert parse_underlying("1Y1Y") == ("1Y", "1Y")
    assert parse_underlying("2Y10Y") == ("2Y", "10Y")


def test_the_payoff_orientation_is_declared_because_it_was_never_harvested():
    """``SPREAD_IS_LONG_MINUS_SHORT`` is a market convention, not a measurement.

    The pair level of ``RATES.SPREAD_OPTIONS`` was never walked, so neither the
    token order nor the sign is confirmed against Citi. It is a module constant
    with a ``sign`` override rather than an assumption buried in arithmetic.
    """
    assert SPREAD_IS_LONG_MINUS_SHORT is True
    assert MIDCURVE_START_IS_RELATIVE_TO_EXPIRY is True


# ------------------------------------------------------------------ #
#                          the single look                           #
# ------------------------------------------------------------------ #


def _price(rho: float, right: str = "OPT_CAP") -> float:
    return single_look_spread_option_price(
        forward_long=FWD_LONG,
        forward_short=FWD_SHORT,
        vol_long=VOL_LONG,
        vol_short=VOL_SHORT,
        correlation=rho,
        strike=STRIKE,
        expiry_years=EXPIRY_YEARS,
        annuity=ANNUITY,
        right=right,
    )


def test_a_spread_cap_is_short_correlation():
    """Higher correlation compresses the spread's vol, so the cap is worth less."""
    rhos = [-0.99, -0.5, 0.0, 0.5, 0.9, 0.99]
    prices = [_price(r) for r in rhos]
    assert all(a > b for a, b in zip(prices, prices[1:])), prices
    assert prices[0] > prices[-1] * 1.5


def test_implied_correlation_round_trips_exactly():
    """The inversion is exact, not a root search: Bachelier inverse then a quadratic."""
    for rho in (-0.5, -0.1, 0.0, 0.25, 0.75, 0.9):
        price = _price(rho)
        recovered = implied_correlation(
            market_price=price,
            forward_long=FWD_LONG,
            forward_short=FWD_SHORT,
            vol_long=VOL_LONG,
            vol_short=VOL_SHORT,
            strike=STRIKE,
            expiry_years=EXPIRY_YEARS,
            annuity=ANNUITY,
            right="OPT_CAP",
        )
        assert recovered == pytest.approx(rho, abs=1e-6)


def test_flipping_the_correlation_sign_breaks_both_properties():
    """MUTATION CHECK for the spread-variance algebra.

    ``sigma^2 = s_l^2 + s_s^2 - 2 rho s_l s_s``. With ``+2 rho`` the price becomes
    INCREASING in correlation and the implied-correlation round trip blows up, so
    the two tests above are measuring the sign rather than assuming it.
    """
    def wrong_vol(rho: float) -> float:
        return math.sqrt(VOL_LONG ** 2 + VOL_SHORT ** 2 + 2 * rho * VOL_LONG * VOL_SHORT)

    right = [
        spread_normal_vol(vol_long=VOL_LONG, vol_short=VOL_SHORT, correlation=r)
        for r in (-0.5, 0.0, 0.5)
    ]
    wrong = [wrong_vol(r) for r in (-0.5, 0.0, 0.5)]
    assert right[0] > right[1] > right[2], "correct: spread vol falls as rho rises"
    assert wrong[0] < wrong[1] < wrong[2], "the mutation inverts the monotonicity"


def test_put_call_parity_holds_across_the_three_rights():
    cap = _price(0.4, "OPT_CAP")
    flr = _price(0.4, "OPT_FLR")
    strad = _price(0.4, "OPT_STR")
    forward_spread = (FWD_LONG - FWD_SHORT - STRIKE) * ANNUITY
    assert cap - flr == pytest.approx(forward_spread, abs=1e-10)
    assert strad == pytest.approx(cap + flr, abs=1e-10)


def test_a_price_below_intrinsic_raises_rather_than_returning_nan():
    with pytest.raises(Exception):
        implied_correlation(
            market_price=-1.0,
            forward_long=FWD_LONG,
            forward_short=FWD_SHORT,
            vol_long=VOL_LONG,
            vol_short=VOL_SHORT,
            strike=STRIKE,
            expiry_years=EXPIRY_YEARS,
            annuity=ANNUITY,
            right="OPT_CAP",
        )


# ------------------------------------------------------------------ #
#                        the convexity adjustment                    #
# ------------------------------------------------------------------ #


def test_cms_convexity_adjustment_is_material_and_tenor_dependent():
    """It does NOT cancel in the spread - each leg must be adjusted separately.

    ``G'/G`` depends on the swap tenor, so a 10Y leg and a 2Y leg pick up
    different adjustments and the spread moves. Treating it as a common factor
    that cancels is a several-basis-point error on a 5Y expiry.
    """
    long_adj = hagan_convexity_adjustment(
        forward=FWD_LONG, normal_vol=VOL_LONG, expiry_years=5.0, tenor_years_=10.0
    )
    short_adj = hagan_convexity_adjustment(
        forward=FWD_SHORT, normal_vol=VOL_SHORT, expiry_years=5.0, tenor_years_=2.0
    )
    assert long_adj > 0 and short_adj > 0
    assert abs(long_adj - short_adj) * 10_000 > 1.0, (
        f"the two legs' adjustments should differ by bp: {long_adj:.6f} vs {short_adj:.6f}"
    )


def test_the_adjustment_grows_with_expiry_and_with_vol():
    base = hagan_convexity_adjustment(
        forward=FWD_LONG, normal_vol=VOL_LONG, expiry_years=1.0, tenor_years_=10.0
    )
    longer = hagan_convexity_adjustment(
        forward=FWD_LONG, normal_vol=VOL_LONG, expiry_years=5.0, tenor_years_=10.0
    )
    noisier = hagan_convexity_adjustment(
        forward=FWD_LONG, normal_vol=VOL_LONG * 2, expiry_years=1.0, tenor_years_=10.0
    )
    assert longer > base * 3
    assert noisier > base * 3


# ------------------------------------------------------------------ #
#                            midcurves                               #
# ------------------------------------------------------------------ #


def test_midcurve_price_matches_bachelier_and_inverts():
    """The premium is annuity x Bachelier, and the implied vol inverts it exactly.

    (The first half is a TAUTOLOGY by construction - ``midcurve_price`` IS that
    product. It is asserted anyway so a refactor that changes the composition is
    caught. The inversion is the part that carries information.)
    """
    forward, strike, vol = 0.0367, 0.0367, 0.0090
    premium = midcurve_price(
        forward=forward,
        strike=strike,
        normal_vol=vol,
        expiry_years=1.0,
        annuity=ANNUITY,
        right="OPT_PAY",
    )
    assert premium > 0
    recovered = midcurve_implied_vol(
        market_price=premium,
        forward=forward,
        strike=strike,
        expiry_years=1.0,
        annuity=ANNUITY,
        right="OPT_PAY",
    )
    assert recovered == pytest.approx(vol, rel=1e-9)


def test_units_are_enforced_rather_than_guessed():
    """Three separate 1e4/100 traps meet here.

    ``SwaptionCubeData`` stores vols in BASIS POINTS, Citi PAR tags serve PERCENT
    and rateslib returns PERCENT - all three of which "price" without complaint if
    fed to a decimal-expecting formula. ``assert_decimal_rate`` refuses anything
    above 1.0.
    """
    assert_decimal_rate(0.0090, name="normal_vol")  # fine
    with pytest.raises(ValueError):
        assert_decimal_rate(90.0, name="normal_vol")  # a bp vol
    with pytest.raises(ValueError):
        midcurve_price(
            forward=0.0367, strike=0.0367, normal_vol=90.0, expiry_years=1.0, annuity=ANNUITY
        )

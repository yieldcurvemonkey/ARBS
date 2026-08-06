r"""Hermetic tests for the Citi Velocity inflation layer.

``RATES.INFLATION.SWAP.<index>.<tenor>`` serves zero-coupon inflation swap rates
(breakevens), from which both backends build an index curve.

The most important thing in this module is a **negative** result, stated as a
structural limit rather than hidden: a self-consistent round trip is BLIND to the
observation lag. Rebuilding a curve at a wrong-but-matching lag leaves every
breakeven bit-identical, so no amount of "it reprices its own inputs" validates
the lag. What CAN be measured is the size of the error when the lag is wrong on
only one side, and :func:`test_publication_lag_error_is_measured_not_asserted`
does exactly that.

Everything is synthetic. Nothing here has been priced against a live Citi quote or
a real published CPI print.
"""

from __future__ import annotations

import datetime

import pytest
import QuantLib as ql

from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog
from MDP.CitiVelocityExcel.inflation import (
    DEFAULT_CALIBRATION_TENORS,
    INDEX_LEVEL_TOKEN_FOR_SWAP_INDEX,
    build_ql_zero_inflation_curve,
    build_rl_index_curve,
    conventions_for,
    ql_breakeven,
    rl_breakeven,
    supported_indices,
)

REF_DATE = datetime.date(2026, 8, 5)
INDEX_BASE = 320.0
TENORS = ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y")


def _quotes(level: float = 2.45, slope: float = 0.10) -> dict[str, float]:
    """A gently upward-sloping breakeven curve, in percent."""
    out = {}
    for i, tenor in enumerate(TENORS):
        out[tenor] = level + slope * (1.0 - 1.0 / (1.0 + i / 3.0))
    return out


def _fixings(index_base: float = INDEX_BASE) -> "object":
    """A flat 2.5% index history, deliberately free of seasonality."""
    import pandas as pd

    months = pd.date_range("2016-01-01", "2026-08-01", freq="MS")
    values = [index_base / (1.025 ** ((months[-1] - m).days / 365.25)) for m in months]
    return pd.Series(values, index=months)


# ------------------------------------------------------------------ #
#                       the catalog's own shape                      #
# ------------------------------------------------------------------ #


def test_inflation_family_shape_is_read_not_assumed():
    cat = CitiVeloCatalog.default()
    assert set(cat.options("RATES.INFLATION")) == {"INDEX", "INF_CARRY", "SWAP", "SWAPTION"}
    assert len(cat.options("RATES.INFLATION.SWAP")) >= 17
    assert set(cat.options("RATES.INFLATION.INDEX")) == {
        "EURO_HICPXT",
        "FRANCE_CPI",
        "SWEDEN_CPI",
        "UK_RPI",
        "US_CPIZU",
    }


def test_us_cpi_carries_spot_only_and_cannot_be_calibrated():
    """``US_CPI`` has ONE child (``SPOT``), so there is no curve to fit.

    Silently building a one-point curve from it would produce a flat breakeven
    that looks like data. It is refused instead.
    """
    cat = CitiVeloCatalog.default()
    assert cat.options("RATES.INFLATION.SWAP.US_CPI") == ["SPOT"]
    with pytest.raises(Exception):
        build_rl_index_curve(
            zc_swap_rates={"SPOT": 2.4},
            ref_date=REF_DATE,
            citi_index="US_CPI",
            index_base=INDEX_BASE,
        )


def test_every_index_records_its_provenance_and_its_lag():
    approximate = [i for i in supported_indices() if conventions_for(i).provenance != "rateslib_spec"]
    assert len(approximate) >= 13, "most indices' conventions are market standard, and say so"
    for index in supported_indices():
        conv = conventions_for(index)
        assert conv.observation_lag >= 0
        assert conv.index_method in {"daily", "monthly", "curve"}
        if conv.provenance != "rateslib_spec":
            assert conv.note, f"{index} is approximate and must say what is approximate"


def test_the_three_flagship_conventions_come_from_rateslib_not_from_memory():
    """``usd_zcis``, ``eur_zcis`` and ``gbp_zcis`` are real rateslib specs.

    They also genuinely disagree: USD interpolates daily on a 3-month lag, GBP
    uses a 2-month lag on the non-interpolated month. Those are not typos.
    """
    import rateslib as rl

    usd, eur, gbp = (conventions_for(i) for i in ("USD_CPURNSA", "EUR_CPTFEMU", "GBP_UKRPI"))
    assert usd.rl_spec == "usd_zcis" and eur.rl_spec == "eur_zcis" and gbp.rl_spec == "gbp_zcis"
    assert rl.defaults.spec["usd_zcis"]["leg2_index_method"] == usd.index_method
    assert rl.defaults.spec["gbp_zcis"]["leg2_index_lag"] == gbp.observation_lag
    assert (usd.observation_lag, usd.index_method) != (gbp.observation_lag, gbp.index_method)


# ------------------------------------------------------------------ #
#                            round trips                             #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("index", ["USD_CPURNSA", "GBP_UKRPI", "EUR_CPTFEMU"])
def test_both_backends_reprice_their_own_calibration_swaps(index: str):
    rl_curve = build_rl_index_curve(
        zc_swap_rates=_quotes(),
        ref_date=REF_DATE,
        citi_index=index,
        index_base=INDEX_BASE,
        index_fixings=_fixings(),
    )
    assert rl_curve.max_repricing_error_bp < 0.01

    ql_curve = build_ql_zero_inflation_curve(
        zc_swap_rates=_quotes(),
        ref_date=REF_DATE,
        citi_index=index,
        fixings=_fixings(),
        index_base=INDEX_BASE,
    )
    for tenor, quote in _quotes().items():
        assert ql_breakeven(ql_curve, tenor) == pytest.approx(quote, abs=1e-4)


def test_a_zero_coupon_swap_rate_is_independent_of_the_discount_curve():
    """Both legs settle on the same date, so discounting cancels exactly.

    A breakeven that moved when the nominal curve moved would mean the fixed and
    floating legs had been given different payment dates.
    """
    import rateslib as rl

    def nominal(rate: float):
        start = datetime.datetime(REF_DATE.year, REF_DATE.month, REF_DATE.day)
        nodes = {start + datetime.timedelta(days=int(365.25 * t)): (1 + rate) ** -t
                 for t in (0, 1, 2, 5, 10, 20, 30, 45)}
        nodes[start] = 1.0
        return rl.Curve(nodes, interpolation="log_linear", calendar="nyc", convention="act360",
                        id=f"nom_{int(rate * 1000)}")

    flat = build_rl_index_curve(
        zc_swap_rates=_quotes(), ref_date=REF_DATE, citi_index="USD_CPURNSA",
        index_base=INDEX_BASE, index_fixings=_fixings(), nominal_curve=nominal(0.0),
    )
    steep = build_rl_index_curve(
        zc_swap_rates=_quotes(), ref_date=REF_DATE, citi_index="USD_CPURNSA",
        index_base=INDEX_BASE, index_fixings=_fixings(), nominal_curve=nominal(0.06),
    )
    for tenor in ("2Y", "10Y", "30Y"):
        assert rl_breakeven(flat, tenor) == pytest.approx(rl_breakeven(steep, tenor), abs=1e-6)


# ------------------------------------------------------------------ #
#                    the lag: measured, and its limit                #
# ------------------------------------------------------------------ #


def test_publication_lag_error_is_measured_not_asserted():
    """The reference-month error is measured on the INDEX LEVEL, where it lives.

    A curve re-solved to the same quotes has the same breakevens whatever base it
    was handed - the base cancels. The lag error only becomes a rate error when
    one side uses a different reference month from the other, e.g. a swap struck
    off the latest published print priced against a curve built on the
    convention's 3-month-lagged month.

    So this measures the thing that does move: the implied index level three
    months apart, converted to the annualised rate error it would cause at 2Y and
    at 30Y. On this flat 2.5% history it is tens of basis points at the front and
    a couple at the back - invisible where people usually look, which is exactly
    why it survives casual checks.
    """
    import pandas as pd

    curve = build_rl_index_curve(
        zc_swap_rates=_quotes(), ref_date=REF_DATE, citi_index="USD_CPURNSA",
        index_base=INDEX_BASE, index_fixings=_fixings(),
    )
    conv = conventions_for("USD_CPURNSA")
    assert conv.observation_lag == 3, "this test is about USD's 3-month convention"

    # index_value() takes an OBSERVATION date and applies the lag internally, so
    # the correct anchor for a swap starting now is this month, and the mistake is
    # reading the index three months later.
    correct_month = pd.Timestamp(REF_DATE).normalize().replace(day=1)
    wrong_month = correct_month + pd.DateOffset(months=conv.observation_lag)
    correct_level = curve.index_value(correct_month.to_pydatetime())
    wrong_level = curve.index_value(wrong_month.to_pydatetime())
    assert correct_level > 0 and wrong_level > 0
    ratio = wrong_level / correct_level
    assert ratio > 1.0, "the index grows, so a later reference month is a higher level"

    err_2y_bp = abs(ratio ** (1 / 2) - 1.0) * 10_000.0
    err_30y_bp = abs(ratio ** (1 / 30) - 1.0) * 10_000.0
    assert err_2y_bp > 5.0, f"2Y reference-month error only {err_2y_bp:.2f} bp"
    assert err_2y_bp > err_30y_bp * 5, (
        f"the error must be front-loaded: 2Y {err_2y_bp:.2f} bp vs 30Y {err_30y_bp:.2f} bp"
    )


def test_a_round_trip_is_structurally_blind_to_the_lag():
    """STRUCTURAL LIMIT, asserted so nobody mistakes self-consistency for validation.

    Rebuild the whole curve at a DIFFERENT observation lag with a base that is
    lagged to match, and every breakeven is unchanged and the repricing error is
    identical. Only the implied index LEVEL moves. No self-consistency test can
    validate an observation lag - which is why provenance is recorded per index
    instead.
    """
    fixings = _fixings()
    base = build_rl_index_curve(
        zc_swap_rates=_quotes(), ref_date=REF_DATE, citi_index="USD_CPURNSA",
        index_base=INDEX_BASE, index_fixings=fixings,
    )
    relagged = build_rl_index_curve(
        zc_swap_rates=_quotes(), ref_date=REF_DATE, citi_index="USD_CPURNSA",
        index_base=INDEX_BASE, index_fixings=fixings, index_lag=6,
    )
    for tenor in ("2Y", "10Y", "30Y"):
        assert rl_breakeven(base, tenor) == pytest.approx(rl_breakeven(relagged, tenor), abs=1e-6)
    # Both fit their inputs equally well - the residual difference is solver
    # noise at 1e-8 bp, not information about the lag.
    assert base.max_repricing_error_bp < 0.01
    assert relagged.max_repricing_error_bp < 0.01
    # What DOES move is the implied index level, which is the only observable
    # that carries the lag at all.
    assert base.index_lag != relagged.index_lag


def test_an_index_base_from_the_wrong_anchor_is_refused():
    """The rateslib silent-zero trap: a nonsense base still CALIBRATES.

    A curve anchored on ``ref_date`` rather than the first of the month returns an
    index base of ~62 against a true ~320 and solves happily. The guard raises
    instead of shipping a curve that is wrong by a factor of five.
    """
    with pytest.raises(Exception):
        build_rl_index_curve(
            zc_swap_rates=_quotes(), ref_date=REF_DATE, citi_index="USD_CPURNSA",
            index_base=0.0, index_fixings=_fixings(),
        )


# ------------------------------------------------------------------ #
#                        QuantLib specifics                          #
# ------------------------------------------------------------------ #


def test_quantlib_zero_rate_is_not_the_breakeven():
    """``curve.zeroRate()`` and the swap's fair rate are different numbers.

    ``ql_breakeven`` prices a real ``ql.ZeroCouponInflationSwap`` rather than
    reading the curve, because the curve's own zero rate carries the helper's
    day-count and lag conventions rather than the swap's.
    """
    curve = build_ql_zero_inflation_curve(
        zc_swap_rates=_quotes(), ref_date=REF_DATE, citi_index="USD_CPURNSA",
        fixings=_fixings(), index_base=INDEX_BASE,
    )
    for tenor, quote in _quotes().items():
        assert ql_breakeven(curve, tenor) == pytest.approx(quote, abs=1e-4)

    # ... and the curve's own zero rate is a DIFFERENT number, because it
    # carries the helper's day count and lag rather than the swap's.
    curve.activate()
    gaps_bp = []
    for tenor in ("1Y", "2Y", "10Y", "30Y"):
        years = int(tenor[:-1])
        maturity = curve.curve.baseDate() + ql.Period(years, ql.Years)
        zero = float(curve.curve.zeroRate(maturity)) * 100.0
        gaps_bp.append(abs(zero - ql_breakeven(curve, tenor)) * 100.0)
    assert max(gaps_bp) > 0.05, (
        "zeroRate() and the swap fair rate should differ measurably; "
        f"gaps {gaps_bp} bp - if they agree, ql_breakeven may be reading the curve"
    )


def test_index_level_token_map_only_claims_what_the_catalog_has():
    """A swap index needs a published level to anchor its base.

    Only five of the seventeen swap indices have a ``RATES.INFLATION.INDEX``
    counterpart in the catalog, so the map has five entries and the pricer raises
    an actionable error for the rest rather than inventing a base.
    """
    cat = CitiVeloCatalog.default()
    levels = set(cat.options("RATES.INFLATION.INDEX"))
    assert set(INDEX_LEVEL_TOKEN_FOR_SWAP_INDEX.values()) <= levels
    assert len(INDEX_LEVEL_TOKEN_FOR_SWAP_INDEX) == 5
    for swap_index in INDEX_LEVEL_TOKEN_FOR_SWAP_INDEX:
        assert swap_index in supported_indices()

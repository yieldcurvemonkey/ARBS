r"""The guard that refuses a Citi bond quote which cannot be what it claims.

Every number in here is a real one off the tape, not an invention. Citi served
``PRICE = -0.562509`` and ``YIELD = 1460.54`` for the on-the-run 2-year on
2026-07-14, and ``PRICE = 7.66648`` for ``US912810UV88`` on the same day - and the
second of those is the dangerous one, because a solver converges on it.

The two halves matter equally and are tested as such:

* it fires on the corruption that happened, and
* it does NOT fire on the widest legitimate values ten years of tape contains.

A guard tested only on bad input is a guard whose false-positive rate is unknown,
and an unknown false-positive rate is how guards get switched off.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

from MDP.CitiVelocityExcel.bonds import sanity as S
from MDP.CitiVelocityExcel.bonds import values as V
from MDP.CitiVelocityExcel.bonds.fetcher import CitiVeloBondFetcher, build_pricer_args
from MDP.CitiVelocityExcel.bonds.resolution import resolve_bond
from MDP.CitiVelocityExcel.bonds.universe import BondUniverse

# --------------------------------------------------------------------- #
#      the corruption, verbatim from the DAILY/CLOSE tag cache           #
# --------------------------------------------------------------------- #

#: 2026-07-13 .. 07-16 for US91282CQY02 (T 4 1/8 Jun-28). The middle two days are
#: the defect; the outer two are what the same bond quoted either side of it.
CQY02 = {
    datetime.date(2026, 7, 13): {"PRICE": 99.744100, "YIELD": 4.26150},
    datetime.date(2026, 7, 14): {"PRICE": -0.562509, "YIELD": 1460.54000},
    datetime.date(2026, 7, 15): {"PRICE": -0.553099, "YIELD": 1463.78000},
    datetime.date(2026, 7, 16): {"PRICE": 99.941400, "YIELD": 4.15558},
}

#: The one that would have priced. 7.66648 against a 5% coupon is absurd, and it
#: is also a number ``ift_1dim`` converges on without complaint.
UV88_BAD_PRICE = 7.66648

#: The widest legitimate values in the measured population, which must all pass.
WIDEST_GOOD = {
    "PRICE": (43.60860, 174.31300),
    "YIELD": (-2.39725, 17.89830),
}

#: A Brazilian NTN-F quotes per 1,000 face. This is a correct price, and the
#: first version of the scan called 1,027 of them impossible.
BRL_ISIN, BRL_PRICE = "BRSTNCNTF212", 2024.99


@pytest.fixture(scope="module")
def ust_isin():
    """A real US Treasury ISIN out of the committed catalog."""
    uni = BondUniverse.from_catalog(country="USA", asset_type="GOVT")
    isins = sorted(d.isin for d in uni if d.isin.startswith("US912"))
    assert isins, "no US912 ISIN in the catalog, so nothing here is exercising a UST"
    return isins[0]


# --------------------------------------------------------------------- #
#                          the band, on its own                          #
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("date", [datetime.date(2026, 7, 14), datetime.date(2026, 7, 15)])
def test_the_corrupt_days_are_refused(date, ust_isin):
    out = S.screen_quotes(CQY02[date], isin=ust_isin)
    assert set(out.rejected) == {"PRICE", "YIELD"}, out.rejected
    assert out.kept == {}
    assert out.screened is True


@pytest.mark.parametrize("date", [datetime.date(2026, 7, 13), datetime.date(2026, 7, 16)])
def test_the_good_days_either_side_are_untouched(date, ust_isin):
    out = S.screen_quotes(CQY02[date], isin=ust_isin)
    assert out.rejected == {}
    assert out.kept == CQY02[date]


def test_the_price_a_solver_would_have_accepted_is_refused(ust_isin):
    """7.66648 is the whole reason the guard is bounded at 15 and not at 1.

    A floor of zero-or-above would have let this through, the yield solver would
    have converged, and a plausible number would have been written with no trace.
    """
    out = S.screen_quotes({"PRICE": UV88_BAD_PRICE}, isin=ust_isin)
    assert "PRICE" in out.rejected
    assert "outside 15..200" in out.rejected["PRICE"].reason


@pytest.mark.parametrize("value,bounds", sorted(WIDEST_GOOD.items()))
def test_the_widest_legitimate_values_pass(value, bounds, ust_isin):
    """The false-positive half. These are the extremes of ~800,000 real cells."""
    for observed in bounds:
        out = S.screen_quotes({value: observed}, isin=ust_isin)
        assert out.rejected == {}, (
            f"{value}={observed} is the widest value Citi actually served in ten "
            f"years and the guard refused it"
        )


def test_a_market_that_was_never_characterised_is_not_screened():
    """A correct BRL price must survive, and the result must SAY it was not checked.

    An empty ``rejected`` from an unscreened market is not a clean bill of health,
    and ``screened`` is what stops it being read as one.
    """
    out = S.screen_quotes({"PRICE": BRL_PRICE}, isin=BRL_ISIN, country="BRA", currency="BRL")
    assert out.rejected == {}
    assert out.kept == {"PRICE": BRL_PRICE}
    assert out.screened is False
    assert out.values_screened == ()


def test_values_with_no_band_pass_through_untouched(ust_isin):
    """SPREAD_TSY reaches -1548.22 legitimately, so it must not be banded."""
    book = {"SPREAD_TSY": -1548.22, "DV01": 3338.22, "DURATION": 24.9134}
    out = S.screen_quotes(book, isin=ust_isin)
    assert out.kept == book
    assert out.rejected == {}
    assert out.values_screened == ("PRICE", "YIELD")


def test_a_non_numeric_quote_is_not_silently_dropped(ust_isin):
    """Screening is a filter on impossibility, not a type check. Something that
    cannot be compared is passed on for whoever owns that problem, because
    dropping it here would hide it behind the wrong error."""
    out = S.screen_quotes({"PRICE": None}, isin=ust_isin)
    assert out.kept == {"PRICE": None}
    assert out.rejected == {}


# --------------------------------------------------------------------- #
#                     end to end, through the fetcher                    #
# --------------------------------------------------------------------- #


class _Reader:
    """Serves one frame offline; never reaches a client."""

    offline = True

    def __init__(self, frame):
        self._frame = frame

    def frame(self, tags, freq="DAILY", **kwargs):
        return self._frame[[t for t in tags if t in self._frame.columns]]

    def client(self):  # pragma: no cover - reaching this is the bug
        raise AssertionError("offline path must not ask for a live client")

    def close(self):
        pass


def _fetch(isin, book, *, date=datetime.date(2026, 7, 14)):
    """One EOD fetch of ``book`` for ``isin``, with a clean day before it.

    The good day matters: it gives every value a stamp the guard must not keep,
    and it is what makes "the refused value's stamp is gone" a real assertion
    rather than a vacuous one.
    """
    idx = pd.DatetimeIndex([pd.Timestamp(date) - pd.Timedelta(days=1), pd.Timestamp(date)])
    frame = pd.DataFrame(
        {
            f"RATES.BOND.{isin}.{v}": [CQY02[datetime.date(2026, 7, 13)].get(v, 1.0), bad]
            for v, bad in book.items()
        },
        index=idx,
    )
    resolution = resolve_bond(isin)
    fetcher = CitiVeloBondFetcher(quotes=_Reader(frame), offline=True)
    return fetcher.fetch([resolution], date, values=list(book))[isin]


def test_a_refused_price_leaves_the_quote_and_takes_its_stamp_with_it(ust_isin):
    quote = _fetch(ust_isin, {"PRICE": -0.562509, "DURATION": 1.86039})

    assert quote.get("PRICE") is None, "a refused price must not be readable"
    assert "PRICE" not in quote.stamps, (
        "the stamp outlived the value it belongs to; as_of and the pricer's "
        "reference date are both derived from stamps"
    )
    assert "PRICE" in quote.rejected
    assert quote.rejected["PRICE"].value == pytest.approx(-0.562509)


def test_the_good_values_on_a_corrupt_day_survive(ust_isin):
    """The failure this replaces dropped the whole date. DURATION, DV01 and
    SPREAD_TSY printed perfectly well on 2026-07-14 and there is no reason to
    lose them because PRICE did not."""
    quote = _fetch(ust_isin, {"PRICE": -0.562509, "DURATION": 1.86039, "DV01": 186.115})

    assert quote.get("DURATION") == pytest.approx(1.86039)
    assert quote.get("DV01") == pytest.approx(186.115)
    assert quote.served is True


def test_a_refusal_is_visible_in_the_coverage_book(ust_isin):
    """It has to be readable off the result, not inferred from a log line."""
    quote = _fetch(ust_isin, {"PRICE": -0.562509, "DURATION": 1.86039})
    book = quote.coverage_book()

    assert "PRICE" in book["rejected"]
    assert "-0.562509" in book["rejected"]["PRICE"]
    assert "REFUSED" in quote.describe()


def test_the_pricer_says_the_price_was_refused_not_that_it_was_missing(ust_isin):
    """Distinguishable messages, because they send the reader different places.

    "no PRICE row in the window" means widen the window. This means the vendor
    published a bad number and no window will help.
    """
    quote = _fetch(ust_isin, {"PRICE": -0.562509, "DURATION": 1.86039})
    with pytest.raises(V.NoQuotedPriceError) as exc:
        build_pricer_args(quote, backend="RL", ref_meta={})

    assert "SERVED a PRICE and it was refused" in str(exc.value)
    assert "no PRICE row" not in str(exc.value)


def test_a_clean_day_prices_normally(ust_isin):
    """The control. Same path, same bond, a price that is a price."""
    quote = _fetch(ust_isin, {"PRICE": 99.941400, "DURATION": 1.85542})

    assert quote.rejected == {}
    assert quote.get("PRICE") == pytest.approx(99.941400)
    assert quote.coverage_book()["rejected"] == {}

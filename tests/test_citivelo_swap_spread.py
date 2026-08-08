r"""Citi Velocity's published ``SWAP_SPREAD`` as an ``IRSwapValue``.

Hermetic: no Excel, no network, no cache, no database - and now literally so. The
tie-out tests used to open with ``module._memory_gate(3800.0)``, which spawned a
real PowerShell probe against the live ``EXCEL.EXE`` from a file making this
claim; every probe and every gate call below is stubbed, and ``subprocess.run``
is replaced in the two tests that exercise the probe's own parsing.

Every quote in here comes from a frame built in the test, which is the only way
this could be written at all - as of 2026-08-08 **zero** ``SWAP_SPREAD`` tags are
cached and the one ``EXCEL.EXE`` on this machine (pid 51420, started 2026-08-07
17:24:33) read 13,865 MB on the tie-out's own probe - 3.6x the 3,800 MB ceiling
and 2.6x the 5,249 MB that wedged it. So there was no live number to fetch and
none is invented.

What the numbers below are and are not: ``-27.35`` is an ARBITRARY sentinel chosen
so that a units bug shows up as ``-0.2735`` or ``-2735``. It is not a measured USD
10Y swap spread. The one thing these tests do pin about units is that **nothing
scales the served number**, which is exactly the property
``scripts/citivelo_swap_spread_tieout.py`` needs in order to settle bp-vs-decimal
on the first run after a human restarts Excel.
"""

from __future__ import annotations

import datetime
import warnings

import pandas as pd
import pytest

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

from MDP.CitiVelocityExcel.errors import UnknownTagError
from MDP.IRSwaps.CITIVELO_EXCEL import fetcher as fetcher_mod
from MDP.IRSwaps.CITIVELO_EXCEL import swap_spreads as ss_mod
from MDP.IRSwaps.CITIVELO_EXCEL.fetcher import StaleCurveError
from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import wire_timezone
from MDP.IRSwaps.CITIVELO_EXCEL.swap_spreads import (
    FREQ_BY_MODE,
    LOOKBACK_BY_MODE,
    SOURCE_TOKEN,
    UNIT,
    SwapSpreadUnavailableError,
    fetch_swap_spread,
    fetch_swap_spreads,
    indices_with_swap_spread,
    swap_spread_for_curve,
    swap_spread_history,
    swap_spread_tag,
    swap_spread_tenors,
    tenor_for_swap,
)
from Query.IRSwaps.IRSwapValue import (
    _CITIVELO_SWAP_SPREAD_KWARGS,
    IRSwapValue,
    IRSwapValueFunctionMap,
)

NY = ZoneInfo("America/New_York")

#: Citi's USD_SOFR ``SWAP_SPREAD`` axis, written out rather than generated. A
#: generated expectation passes even when the generator changes, and these
#: eleven strings are what every downstream call will be spelled with. Note what
#: is IN it (money-market 1M/3M/6M) and what is NOT (4Y, 15Y, 25Y) - it is not
#: the 44-tenor PAR grid and it is not a swap grid anyone would guess.
USD_SOFR_AXIS = ("1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y")

#: The sentinel value. See the module docstring.
SENTINEL = -27.35


# ------------------------------------------------------------------ #
#                             test doubles                           #
# ------------------------------------------------------------------ #


class _StubQuotes:
    """Serves a frame built in the test. Records what was asked for.

    ``metadata`` raises on purpose. ``CVMETADATA`` reports ZERO valid tenors for
    this family while ``CVTSHIST`` serves the USD_SOFR axis, and
    ``RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y`` hard-fails an entire ``CVMETADATA``
    batch to ``#VALUE!`` even when probed alone. Any code path that reaches for
    metadata here is wrong, so it must not be able to pass quietly.

    ``honour_bounds=False`` makes ``frame`` ignore the ``start``/``end`` it was
    handed and serve the whole block. That is not a fantasy transport: it is the
    state the module's own as-of clamp exists for, and with the default
    (``True``) the clamp is unreachable in a test because the stub has already
    done the clamp's job. One of the two look-ahead protections has to be
    disabled for the other to be measurable at all.
    """

    def __init__(self, frame: pd.DataFrame, *, honour_bounds: bool = True):
        self._frame = frame
        self._honour_bounds = bool(honour_bounds)
        self.calls: list = []

    def frame(self, tags, freq="DAILY", **kwargs):
        self.calls.append((tuple(tags), freq, kwargs))
        cols = [t for t in tags if t in self._frame.columns]
        out = self._frame[cols]
        if not self._honour_bounds:
            return out
        start, end = kwargs.get("start"), kwargs.get("end")
        if start is not None:
            out = out[out.index >= pd.Timestamp(start)]
        if end is not None:
            out = out[out.index <= pd.Timestamp(end)]
        return out

    def metadata(self, tags):  # pragma: no cover - reaching this IS the failure
        raise AssertionError(
            "CVMETADATA must never be called for RATES.OIS.*.SWAP_SPREAD: it reports zero "
            "valid tenors and poisons its own batch to #VALUE!."
        )

    def close(self):
        pass


def _series(tenors=USD_SOFR_AXIS, index=None, value=SENTINEL, citi_index="USD_SOFR"):
    if index is None:
        index = pd.date_range("2026-07-01", "2026-08-06", freq="B")
    return pd.DataFrame(
        {f"RATES.OIS.{citi_index}.SWAP_SPREAD.{t}": [value] * len(index) for t in tenors},
        index=index,
    )


class _FakeSwap:
    def __init__(self, effective: datetime.date, maturity: datetime.date):
        self.effective = effective
        self.maturity = maturity


class _FakeCitiCurve:
    """The minimum of ``_IRSwapGenericCurve`` this value actually touches."""

    def __init__(self, meta):
        self._meta = meta

    def meta(self):
        return self._meta

    def effective_date(self, swap):
        return swap.effective

    def maturity_date(self, swap):
        return swap.maturity


def _eod_curve(reference_date=datetime.date(2026, 8, 6), citi_index="USD_SOFR", **over):
    meta = {
        "source": SOURCE_TOKEN,
        "mode": "eod",
        "citi_index": citi_index,
        "reference_date": reference_date.isoformat(),
        "timestamp": datetime.datetime(2026, 8, 6, 17, 0, tzinfo=NY),
        "backend": "rl",
    }
    meta.update(over)
    return _FakeCitiCurve(meta)


# ------------------------------------------------------------------ #
#                           the tenor axis                           #
# ------------------------------------------------------------------ #


def test_usd_sofr_axis_is_exactly_the_eleven_the_catalog_records():
    assert swap_spread_tenors("USD_SOFR") == USD_SOFR_AXIS


def test_every_usd_tenor_builds_the_documented_tag():
    for tenor in USD_SOFR_AXIS:
        assert swap_spread_tag("USD_SOFR", tenor) == f"RATES.OIS.USD_SOFR.SWAP_SPREAD.{tenor}"


def test_the_axis_is_read_from_the_catalog_not_from_the_usd_only_tuple():
    """``tags.SWAP_SPREAD_LIQUID_TENORS`` is the USD axis under a generic name.

    Using it for GBP would ask for four tenors that do not exist (1M 3M 6M 1Y)
    and miss three that do (15Y 40Y 50Y). The axes must therefore differ here.
    """
    from MDP.CitiVelocityExcel.tags import SWAP_SPREAD_LIQUID_TENORS

    gbp = swap_spread_tenors("GBP_SONIA")
    assert gbp != USD_SOFR_AXIS
    assert set(SWAP_SPREAD_LIQUID_TENORS) == set(USD_SOFR_AXIS)
    assert {"15Y", "40Y", "50Y"} <= set(gbp)
    assert not ({"1M", "3M", "6M", "1Y"} & set(gbp))


@pytest.mark.parametrize("tenor", ["4Y", "15Y", "25Y"])
def test_a_tenor_off_the_axis_raises_and_names_the_whole_accepted_list(tenor):
    """4Y/15Y/25Y are the PAR grid's tenors, not this family's. A caller asking for
    them is assuming the 44-tenor axis, so the message has to show the real one.

    The last assertion looks like testing wording, and is not: ``tags._pick``
    would also reject these with a generic "Unknown segment", so the ONLY thing
    the check in ``swap_spread_tag`` adds is naming the assumption the caller
    actually made. Drop that check and this test must fail, or the check is
    decoration.
    """
    with pytest.raises(UnknownTagError) as excinfo:
        swap_spread_tag("USD_SOFR", tenor)
    message = str(excinfo.value)
    assert tenor in message
    for accepted in USD_SOFR_AXIS:
        assert accepted in message
    assert "PAR grid" in message


def test_an_index_without_the_sub_type_raises():
    """EUR_EUROSTR carries BFLY/CURVES/FWD/PAR/ROLL_CARRY and no SWAP_SPREAD."""
    with pytest.raises(UnknownTagError, match="SWAP_SPREAD"):
        swap_spread_tenors("EUR_EUROSTR")


class _StubCatalog:
    """A catalog whose ``SWAP_SPREAD`` node exists with NO recorded children.

    No shipped index is in that state today, which is exactly why it needs a
    stub: ``tags.ois()`` validates trailing segments with
    ``allow_unrecorded=True``, so a node with an empty option list would accept
    ANY tenor string and turn a typo into a tag that fails at the add-in instead
    of here. The guard is unreachable through real data and would rot unnoticed.
    """

    _OPTIONS = {
        "RATES.OIS": ["FAKE_IDX", "USD_SOFR"],
        "RATES.OIS.FAKE_IDX": ["PAR", "SWAP_SPREAD"],
        "RATES.OIS.FAKE_IDX.SWAP_SPREAD": [],
        "RATES.OIS.USD_SOFR": ["PAR", "SWAP_SPREAD"],
        "RATES.OIS.USD_SOFR.SWAP_SPREAD": ["2Y", "10Y"],
    }

    def options(self, node):
        return list(self._OPTIONS.get(node, []))


def test_an_axis_recorded_as_empty_is_refused_rather_than_trusted():
    cat = _StubCatalog()
    with pytest.raises(UnknownTagError) as excinfo:
        swap_spread_tenors("FAKE_IDX", catalog=cat)
    message = str(excinfo.value)
    assert "no recorded tenors" in message
    assert "USD_SOFR" in message, "the message must name the indices whose axis IS recorded"
    # and the guard must not fire for an index whose axis IS recorded
    assert swap_spread_tenors("USD_SOFR", catalog=cat) == ("2Y", "10Y")


def test_the_indices_that_serve_it_come_from_the_catalog():
    """Pinned in full, because ``swap_spreads.py``'s module docstring prints this
    table with per-index tenor counts and a table nobody checks goes stale."""
    from MDP.CitiVelocityExcel.tags import OIS_INDICES

    indices = indices_with_swap_spread()
    assert set(indices) == {
        "AUD_AONIA", "CAD_CORRA", "CHF_SARON", "DKK_TNDKK", "GBP_SONIA",
        "JPY_TONAR", "JPY_TONAR_JSCC", "JPY_TONAR_LCH", "NOK_NOWA", "NZD_NZIONA",
        "SEK_STINA", "USD_FEDFUND", "USD_SOFR",
    }
    assert set(indices) <= set(OIS_INDICES)
    assert set(OIS_INDICES) - set(indices) == {
        "EUR_EONIA", "EUR_EUROSTR", "ILS_SHIR", "MXN_T_FONDEO",
        "SGD_SORA", "THB_THOR", "ZAR_ZARONIA",
    }


def test_the_per_index_tenor_counts_in_the_docstring_are_the_catalogs():
    """The counts the module docstring quotes, so the doc cannot drift silently."""
    expected = {
        "USD_SOFR": 11, "USD_FEDFUND": 11, "JPY_TONAR": 12, "JPY_TONAR_JSCC": 12,
        "JPY_TONAR_LCH": 12, "GBP_SONIA": 10, "AUD_AONIA": 7, "NZD_NZIONA": 5,
        "CAD_CORRA": 4, "CHF_SARON": 4, "DKK_TNDKK": 4, "SEK_STINA": 4, "NOK_NOWA": 3,
    }
    assert {i: len(swap_spread_tenors(i)) for i in indices_with_swap_spread()} == expected
    # Membership too, not just counts - three of the four-tenor curves happen to
    # share an axis and one does not, which a count alone cannot tell apart.
    assert swap_spread_tenors("CHF_SARON") == ("2Y", "5Y", "10Y", "30Y")
    assert swap_spread_tenors("NOK_NOWA") == ("2Y", "5Y", "10Y")
    assert swap_spread_tenors("NZD_NZIONA") == ("2Y", "5Y", "7Y", "10Y", "20Y")
    assert swap_spread_tenors("JPY_TONAR") == (
        "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y", "40Y"
    )
    assert swap_spread_tenors("JPY_TONAR_LCH") == swap_spread_tenors("JPY_TONAR")
    assert swap_spread_tenors("GBP_SONIA") == (
        "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y", "40Y", "50Y"
    )


def test_the_index_spelling_is_normalised_through_the_shared_builder():
    assert swap_spread_tag("usd_sofr", "10y") == "RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y"


def test_the_swap_spread_node_does_not_share_pars_axis():
    """``tags.ois_swap_spread``'s docstring used to say the catalog carries the full
    44-tenor axis "because it is shared with PAR". Measured against the committed
    catalog it is not shared and it is not 44 - USD_SOFR's SWAP_SPREAD node has
    eleven children and PAR has forty-four. The distinction is load-bearing: a
    reader who believes the axes are shared concludes the membership check in
    ``swap_spread_tag`` is redundant and deletes it.
    """
    from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog

    cat = CitiVeloCatalog.default()
    par = cat.options("RATES.OIS.USD_SOFR.PAR")
    swap_spread = swap_spread_tenors("USD_SOFR")
    assert len(par) == 44
    assert len(swap_spread) == 11
    assert set(swap_spread) < set(par), "a proper subset, not the same axis"
    assert {"4Y", "15Y", "25Y"} <= set(par) - set(swap_spread)


# ------------------------------------------------------------------ #
#                          the three modes                           #
# ------------------------------------------------------------------ #


def test_freq_and_lookback_are_the_curve_fetchers_own_tables():
    """Not a second copy. Two copies of "MI01 looks back 5 days" is how one of them
    ends up past the 6-day downsampling cliff without anyone noticing."""
    assert FREQ_BY_MODE is fetcher_mod._FREQ
    assert LOOKBACK_BY_MODE is fetcher_mod._LOOKBACK
    assert LOOKBACK_BY_MODE["intraday"] <= datetime.timedelta(days=6)
    assert LOOKBACK_BY_MODE["live"] <= datetime.timedelta(days=6)


@pytest.mark.parametrize("mode", ["intraday", "live"])
def test_the_mi01_window_actually_asked_for_stays_under_the_downsampling_cliff(mode):
    """The constant being right is not the same as the constant being USED.

    Pinning ``LOOKBACK_BY_MODE`` by identity (above) says nothing about the
    ``start`` that reaches ``CVTSHIST``: a hardcoded 45-day span next to it would
    leave that assertion green while asking for 7.5x the measured 7-day cliff,
    past which the add-in silently returns ten-minute rows in a block that looks
    identical to one-minute rows. So this reads the width off the recorded call.
    """
    if mode == "live":
        anchor = datetime.datetime.now(wire_timezone()).replace(tzinfo=None)
        when: object = "live"
    else:
        anchor = datetime.datetime(2026, 8, 6, 10, 30)
        when = datetime.datetime(2026, 8, 6, 10, 30, tzinfo=NY)
    index = pd.date_range(anchor - pd.Timedelta(hours=2), anchor, freq="min")
    stub = _StubQuotes(_series(index=index))
    fetch_swap_spread("USD_SOFR", "10Y", when, quotes=stub)

    asked = stub.calls[-1][2]
    assert stub.calls[-1][1] == "MI01"
    width = asked["end"] - asked["start"]
    assert width == LOOKBACK_BY_MODE[mode], "the window width must be the shared lookback"
    assert width <= datetime.timedelta(days=6), (
        f"{mode} asked CVTSHIST for {width}, past the measured 6-day MI01 cliff"
    )


def test_a_bare_date_is_eod_and_reads_the_daily_series():
    stub = _StubQuotes(_series())
    quote = fetch_swap_spread("USD_SOFR", "10Y", datetime.date(2026, 8, 6), quotes=stub)
    assert quote.mode == "eod"
    assert quote.freq == "DAILY"
    assert stub.calls[-1][1] == "DAILY"


def test_a_midnight_timestamp_is_eod_not_intraday():
    """The trap. ``pandas.Timestamp`` subclasses ``datetime`` subclasses ``date``,
    so an isinstance ladder gets this wrong in both directions, and
    ``Timestamp("2026-08-06")`` is the common accidental spelling of "that day"."""
    stub = _StubQuotes(_series())
    quote = fetch_swap_spread("USD_SOFR", "10Y", pd.Timestamp("2026-08-06"), quotes=stub)
    assert quote.mode == "eod"
    assert stub.calls[-1][1] == "DAILY"


def test_a_datetime_with_a_time_is_intraday_and_reads_mi01():
    index = pd.date_range("2026-08-06 09:00", "2026-08-06 11:00", freq="min")
    stub = _StubQuotes(_series(index=index))
    quote = fetch_swap_spread(
        "USD_SOFR", "10Y", datetime.datetime(2026, 8, 6, 10, 30, tzinfo=NY), quotes=stub
    )
    assert quote.mode == "intraday"
    assert quote.freq == "MI01"
    assert stub.calls[-1][1] == "MI01"
    assert quote.requested_at == datetime.datetime(2026, 8, 6, 10, 30, tzinfo=NY)


def test_live_reads_mi01_and_is_bounded_above_by_now():
    """The bound is only testable against rows that would violate it.

    A fixture whose newest row is in the past cannot tell a bounded ``end`` from
    an unbounded one - the previous version of this test ended the index at
    now-3min and its ``2 <= lag <= 6`` assertion was measuring the fixture's own
    gap. So the frame here carries rows stamped THIRTY MINUTES INTO THE FUTURE,
    which is what an add-in clock skew looks like, and the assertions are that
    they are not served and that the lag never goes negative.
    """
    now = datetime.datetime.now(wire_timezone()).replace(tzinfo=None).replace(microsecond=0)
    index = pd.date_range(now - pd.Timedelta(minutes=30), now + pd.Timedelta(minutes=30), freq="min")
    # A ramp rather than a constant: which row was served has to be visible in
    # the value, not only in the stamp.
    frame = pd.DataFrame(
        {"RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y": [SENTINEL + i for i in range(len(index))]},
        index=index,
    )
    stub = _StubQuotes(frame)

    quote = fetch_swap_spread("USD_SOFR", "10Y", "live", quotes=stub)

    assert quote.mode == "live"
    assert quote.freq == "MI01"
    assert quote.requested_at is None
    assert stub.calls[-1][2]["end"] <= datetime.datetime.now(wire_timezone()).replace(tzinfo=None)
    assert quote.quoted_at <= datetime.datetime.now(wire_timezone()), (
        "a live quote stamped in the future is a clock skew being served as a market move"
    )
    assert quote.lag >= datetime.timedelta(0), f"negative lag {quote.lag}: a future row was served"
    assert quote.lag <= datetime.timedelta(minutes=2)
    assert quote.value == pytest.approx(SENTINEL + 30, abs=1e-9), (
        "the served row must be the one stamped at or before now, not the newest in the block"
    )


def test_a_print_after_the_requested_instant_is_not_served():
    """The as-of clamp, with the transport's own bound removed.

    ``series[series.index <= target]`` is the second of two mutually redundant
    look-ahead protections; the first is ``end=`` on the ``CVTSHIST`` call. With a
    stub that honours ``end`` the clamp can never remove a row, so disabling it
    changes nothing and the guard is decoration. ``honour_bounds=False`` serves
    the whole block and makes the clamp the only thing standing between a 10:30
    request and the 11:00 print.
    """
    index = pd.date_range("2026-08-06 09:00", "2026-08-06 11:00", freq="min")
    tag = "RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y"
    frame = pd.DataFrame({tag: [SENTINEL + i for i in range(len(index))]}, index=index)
    stub = _StubQuotes(frame, honour_bounds=False)

    quote = fetch_swap_spread(
        "USD_SOFR", "10Y", datetime.datetime(2026, 8, 6, 10, 30, tzinfo=NY), quotes=stub
    )

    assert quote.quoted_at == datetime.datetime(2026, 8, 6, 10, 30, tzinfo=NY)
    assert quote.value == pytest.approx(SENTINEL + 90, abs=1e-9), (
        "10:30 is the 91st row; serving the 11:00 row is reading the future"
    )
    assert quote.lag == datetime.timedelta(0)


def test_an_aware_timestamp_is_converted_into_citis_zone_before_being_asked_for():
    """14:30 UTC is 10:30 ET in August. Asking the add-in for 14:30 would read a
    row four hours late and it would look like a real market move."""
    index = pd.date_range("2026-08-06 09:00", "2026-08-06 11:00", freq="min")
    stub = _StubQuotes(_series(index=index))
    fetch_swap_spread(
        "USD_SOFR",
        "10Y",
        datetime.datetime(2026, 8, 6, 14, 30, tzinfo=datetime.timezone.utc),
        quotes=stub,
    )
    assert stub.calls[-1][2]["end"] == datetime.datetime(2026, 8, 6, 10, 30)


def test_every_requested_tenor_goes_out_in_one_call():
    stub = _StubQuotes(_series())
    quotes = fetch_swap_spreads("USD_SOFR", None, datetime.date(2026, 8, 6), quotes=stub)
    assert set(quotes) == set(USD_SOFR_AXIS)
    assert len(stub.calls) == 1, "eleven tenors must be one CVTSHIST call, not eleven"
    assert len(stub.calls[0][0]) == 11


# ------------------------------------------------------------------ #
#                               guards                               #
# ------------------------------------------------------------------ #


def test_a_stale_intraday_quote_raises_rather_than_looking_current():
    """An as-of search is backward and unbounded; this repo has a recorded case of
    a request 365 days past the data resolving silently to the last row."""
    index = pd.date_range("2026-08-04 09:00", "2026-08-04 10:00", freq="min")
    stub = _StubQuotes(_series(index=index))
    with pytest.raises(StaleCurveError, match="stale"):
        fetch_swap_spread(
            "USD_SOFR", "10Y", datetime.datetime(2026, 8, 6, 10, 30, tzinfo=NY), quotes=stub
        )


def test_a_stale_eod_quote_raises_in_days_not_hours():
    """An EOD row is stamped at midnight and is a day "old" by construction, so the
    12-hour intraday limit would reject every one of them. The limit is 7 days.

    The window has to sit between the 7-day limit and the 21-day lookback for the
    guard to be REACHABLE at all - beyond 21 days the fetch returns nothing and
    the unavailable path fires instead. That relationship is pinned below.
    """
    assert LOOKBACK_BY_MODE["eod"] > fetcher_mod.DEFAULT_MAX_EOD_GAP
    index = pd.date_range("2026-07-14", "2026-07-20", freq="D")  # 17 days before the request
    stub = _StubQuotes(_series(index=index))
    with pytest.raises(StaleCurveError, match=r"\d+\.\d d stale"):
        fetch_swap_spread("USD_SOFR", "10Y", datetime.date(2026, 8, 6), quotes=stub)


def test_an_eod_quote_inside_the_seven_day_gap_still_serves():
    """A long weekend plus a holiday must not raise."""
    index = pd.date_range("2026-07-28", "2026-08-03", freq="D")
    stub = _StubQuotes(_series(index=index))
    quote = fetch_swap_spread("USD_SOFR", "10Y", datetime.date(2026, 8, 6), quotes=stub)
    assert quote.value == pytest.approx(SENTINEL)


def test_a_tenor_that_served_nothing_raises_and_says_not_to_use_cvmetadata():
    stub = _StubQuotes(_series(tenors=("2Y",)))
    with pytest.raises(SwapSpreadUnavailableError, match="CVMETADATA"):
        fetch_swap_spread("USD_SOFR", "10Y", datetime.date(2026, 8, 6), quotes=stub)


def test_history_refuses_an_intraday_frequency_and_names_the_windowed_fetcher():
    with pytest.raises(ValueError, match="fetch_windowed"):
        swap_spread_history(
            "USD_SOFR",
            ["10Y"],
            start=datetime.date(2026, 1, 1),
            end=datetime.date(2026, 8, 6),
            freq="MI01",
        )


def test_history_returns_tenor_named_columns():
    stub = _StubQuotes(_series(tenors=("2Y", "10Y")))
    frame = swap_spread_history(
        "USD_SOFR",
        ["10Y", "2Y"],
        start=datetime.date(2026, 7, 1),
        end=datetime.date(2026, 8, 6),
        quotes=stub,
    )
    assert list(frame.columns) == ["10Y", "2Y"]
    assert frame["10Y"].iloc[-1] == pytest.approx(SENTINEL)


def test_an_entirely_empty_history_reports_absence_as_a_missing_column():
    """``fetch_swap_spreads``' docstring sends callers here *because* absence shows
    up as a missing column. Returning every requested tenor as a zero-row column
    on an empty window contradicts that at exactly the moment it matters, and
    ``scripts/daily_cache_warmer.py:462`` logs ``len(frame.columns)`` as "served
    N/M tenors" - which would have read "served 11/11" for a window that served
    nothing at all.
    """
    empty = pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))
    frame = swap_spread_history(
        "USD_SOFR",
        ["10Y", "2Y"],
        start=datetime.date(2026, 7, 1),
        end=datetime.date(2026, 8, 6),
        quotes=_StubQuotes(empty),
    )
    assert frame.empty
    assert list(frame.columns) == [], "a tenor that served nothing must not appear as a column"


def test_an_eod_request_for_today_warns_that_it_is_the_running_session():
    """Citi's DAILY series carries a row for the CURRENT, incomplete session -
    measured 2026-08-07, a row stamped 2026-08-07 00:00 existed at 10:47 ET. The
    sibling curve fetcher warns about this (fetcher.py:355-366); a published
    spread read the same way is the same running level, and calling it ``eod``
    without saying so is stale-data-served-as-final in its other direction.
    """
    today = datetime.datetime.now(wire_timezone()).date()
    index = pd.date_range(today - datetime.timedelta(days=5), today, freq="D")
    stub = _StubQuotes(_series(index=index))
    with pytest.warns(UserWarning, match="incomplete session"):
        quote = fetch_swap_spread("USD_SOFR", "10Y", today, quotes=stub)
    assert quote.mode == "eod"


def test_an_eod_request_for_a_settled_day_does_not_warn():
    """The other half: a warning on every EOD call is a warning nobody reads."""
    stub = _StubQuotes(_series())
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        quote = fetch_swap_spread("USD_SOFR", "10Y", datetime.date(2026, 8, 6), quotes=stub)
    assert quote.mode == "eod"


def test_a_history_ending_today_warns_that_its_last_row_is_incomplete():
    """``scripts/citivelo_swap_spread_tieout.py`` defaults ``end`` to today, so its
    last differenced row would be a mid-session level against a settled repo-side
    SPREADOVER - a spurious final-day residual with nothing flagging it."""
    today = datetime.datetime.now(wire_timezone()).date()
    index = pd.date_range(today - datetime.timedelta(days=5), today, freq="D")
    stub = _StubQuotes(_series(index=index))
    with pytest.warns(UserWarning, match="incomplete session"):
        swap_spread_history(
            "USD_SOFR", ["10Y"], start=today - datetime.timedelta(days=5), end=today, quotes=stub
        )


def test_a_history_ending_on_a_settled_day_does_not_warn():
    stub = _StubQuotes(_series())
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        swap_spread_history(
            "USD_SOFR",
            ["10Y"],
            start=datetime.date(2026, 7, 1),
            end=datetime.date(2026, 8, 6),
            quotes=stub,
        )


class _CloseFailsQuotes(_StubQuotes):
    """A teardown that fails the way a wedged add-in fails."""

    def close(self):
        raise RuntimeError("(-2147417848) The object invoked has disconnected from its clients")


def test_a_close_failure_on_a_lazily_built_quotes_is_logged_not_discarded(monkeypatch, caplog):
    """``except Exception: pass`` around ``quotes.close()`` is right - a teardown
    failure must not mask the quote - but discarding it leaves no trace anywhere,
    and the next call reconnects into an Excel that has already broken once.
    """
    stub = _CloseFailsQuotes(_series())
    monkeypatch.setattr(ss_mod, "_default_quotes", lambda **kw: stub)

    with caplog.at_level("WARNING", logger=ss_mod.__name__):
        quote = fetch_swap_spread("USD_SOFR", "10Y", datetime.date(2026, 8, 6))

    assert quote.value == pytest.approx(SENTINEL), "the close failure must not mask the quote"
    records = [r for r in caplog.records if r.name == ss_mod.__name__ and r.levelname == "WARNING"]
    assert records, "a failed teardown must leave a record"
    assert "closing the quotes" in records[0].getMessage()
    assert records[0].exc_info is not None, (
        "without exc_info the record says a close failed and not why, which is not actionable"
    )
    assert "disconnected from its clients" in str(records[0].exc_info[1])


def test_client_kwargs_reach_the_lazily_built_quotes(monkeypatch):
    """A batch caller that cannot inject ``quotes`` must still be able to tune the
    connect. ``client_kwargs`` was reachable on ``fetch_swap_spreads`` but not on
    ``swap_spread_for_curve``, which is the only door the value map opens."""
    seen: dict = {}

    def _record(**kw):
        seen.update(kw)
        return _StubQuotes(_series())

    monkeypatch.setattr(ss_mod, "_default_quotes", _record)
    curve = _eod_curve()
    swap = _FakeSwap(datetime.date(2026, 8, 10), datetime.date(2036, 8, 10))
    out = swap_spread_for_curve(
        curve=curve, package=[swap], tenor="10Y", client_kwargs={"visible": False}, offline=True
    )
    assert out == pytest.approx(SENTINEL)
    assert seen == {"offline": True, "client_kwargs": {"visible": False}}
    assert "client_kwargs" in _CITIVELO_SWAP_SPREAD_KWARGS, (
        "and the value map has to be able to forward it"
    )


# ------------------------------------------------------------------ #
#                                units                               #
# ------------------------------------------------------------------ #


def test_the_served_number_is_returned_unscaled():
    """The whole units position rests on this. Nothing multiplies or divides, so
    the tie-out script can read Citi's raw magnitude and settle bp-vs-decimal."""
    stub = _StubQuotes(_series(value=SENTINEL))
    quote = fetch_swap_spread("USD_SOFR", "10Y", datetime.date(2026, 8, 6), quotes=stub)
    assert quote.value == pytest.approx(SENTINEL, abs=0.0)
    assert quote.unit == "as_published"


def test_the_unit_is_declared_unmeasured_until_the_tieout_runs():
    """A constant that says "as_published" cannot be mistaken for a measurement.
    When ``scripts/citivelo_swap_spread_tieout.py`` has run, this becomes "bp" and
    this test's expectation moves with it - deliberately, so the change is a
    decision somebody made rather than a default that drifted."""
    assert UNIT == "as_published"


# ------------------------------------------------------------------ #
#                      the tenor derived from a swap                 #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "months,expected",
    [(1, "1M"), (3, "3M"), (6, "6M"), (12, "1Y"), (24, "2Y"), (36, "3Y"),
     (60, "5Y"), (84, "7Y"), (120, "10Y"), (240, "20Y"), (360, "30Y")],
)
def test_a_swaps_own_dates_round_trip_to_its_tenor(months, expected):
    effective = datetime.date(2026, 8, 10)
    year, month = divmod(effective.month - 1 + months, 12)
    maturity = datetime.date(effective.year + year, month + 1, effective.day)
    curve = _eod_curve()
    assert tenor_for_swap(curve, _FakeSwap(effective, maturity)) == expected


def test_a_swap_off_the_axis_raises_rather_than_reading_the_nearest_tenor():
    """A 4Y swap must not quietly return the 5Y published spread."""
    curve = _eod_curve()
    swap = _FakeSwap(datetime.date(2026, 8, 10), datetime.date(2030, 8, 10))
    assert tenor_for_swap(curve, swap) == "4Y"
    with pytest.raises(UnknownTagError, match="4Y"):
        swap_spread_for_curve(curve=curve, package=[swap], quotes=_StubQuotes(_series()))


# ------------------------------------------------------------------ #
#              the spot start Citi's axis assumes and does not say    #
# ------------------------------------------------------------------ #


def test_a_forward_starting_swap_is_refused_rather_than_served_the_spot_number():
    """The one that returns a real number for a different trade.

    ``RATES.OIS.<index>.SWAP_SPREAD.<tenor>`` indexes a MATURITY, not a
    ``(forward, tenor)`` pair the way Citi's ``FWD`` sub-type does, so a 5Yx5Y
    forward derives tenor ``5Y`` from ``maturity - effective`` and reads the SPOT
    5Y quote - byte-identical to the spot answer, no warning, no raise. The
    residual against the swap's own forward rate would be the entire forward/spot
    spread and nothing in the stack would say so.
    """
    curve = _eod_curve(reference_date=datetime.date(2026, 8, 6))
    forward = _FakeSwap(datetime.date(2031, 8, 10), datetime.date(2036, 8, 10))
    assert tenor_for_swap(curve, forward) == "5Y", "the derivation itself is duration-only"

    with pytest.raises(ss_mod.SpotStartRequiredError) as excinfo:
        swap_spread_for_curve(curve=curve, package=[forward], quotes=_StubQuotes(_series()))
    message = str(excinfo.value)
    assert "2031-08-10" in message, "the message must name the effective date that failed"
    assert "2026-08-06" in message, "and the as-of it was measured against"
    assert "spot" in message.lower()


def test_the_forward_start_guard_fires_even_when_the_tenor_is_stated():
    """Passing ``tenor="5Y"`` bypasses the derivation but not the trade's dates, and
    an explicitly-tenored forward is the same wrong number."""
    curve = _eod_curve(reference_date=datetime.date(2026, 8, 6))
    forward = _FakeSwap(datetime.date(2031, 8, 10), datetime.date(2036, 8, 10))
    with pytest.raises(ss_mod.SpotStartRequiredError):
        swap_spread_for_curve(
            curve=curve, package=[forward], tenor="5Y", quotes=_StubQuotes(_series())
        )


def test_the_forward_start_guard_reaches_the_value_map():
    """The value map is the blast radius: an RV book asks for
    ``IRS_CITIVELO_SWAP_SPREAD``, not for ``swap_spread_for_curve``."""
    curve = _eod_curve(reference_date=datetime.date(2026, 8, 6))
    forward = _FakeSwap(datetime.date(2031, 8, 10), datetime.date(2036, 8, 10))
    with pytest.raises(ss_mod.SpotStartRequiredError):
        _value_map(curve, [forward]).apply(
            value=IRSwapValue.CITIVELO_SWAP_SPREAD, quotes=_StubQuotes(_series()), tenor="5Y"
        )


def test_a_swap_already_running_is_refused_too():
    """A seasoned swap is not spot either, and it is wrong in the other direction:
    ``tenor_for_swap`` reports its ORIGINAL span, not its remaining life, so a
    10Y struck two years ago reads the published 10Y rather than the 8Y."""
    curve = _eod_curve(reference_date=datetime.date(2026, 8, 6))
    seasoned = _FakeSwap(datetime.date(2024, 8, 10), datetime.date(2034, 8, 10))
    assert tenor_for_swap(curve, seasoned) == "10Y"
    with pytest.raises(ss_mod.SpotStartRequiredError, match="before"):
        swap_spread_for_curve(
            curve=curve, package=[seasoned], tenor="10Y", quotes=_StubQuotes(_series())
        )


@pytest.mark.parametrize("lag_days", [0, 2, 4, 6, 10])
def test_a_spot_start_is_admitted_across_the_worst_settlement_calendar(lag_days):
    """T+2 business days is 4 calendar days over an ordinary weekend and 6 with a
    Friday and Monday both closed. The tolerance has to admit all of those and
    still refuse the shortest forward anybody trades (1M = 28-31 days)."""
    as_of = datetime.date(2026, 8, 6)
    effective = as_of + datetime.timedelta(days=lag_days)
    curve = _eod_curve(reference_date=as_of)
    swap = _FakeSwap(effective, datetime.date(effective.year + 10, effective.month, effective.day))
    out = swap_spread_for_curve(
        curve=curve, package=[swap], tenor="10Y", quotes=_StubQuotes(_series())
    )
    assert out == pytest.approx(SENTINEL)


def test_the_tolerance_refuses_a_one_month_forward():
    """The boundary in the direction that matters. A 1M forward start is the
    shortest structure anybody would put on this value; if the tolerance admitted
    it, the guard would be documentation."""
    as_of = datetime.date(2026, 8, 6)
    curve = _eod_curve(reference_date=as_of)
    swap = _FakeSwap(datetime.date(2026, 9, 8), datetime.date(2036, 9, 8))
    assert ss_mod.MAX_SPOT_START_LAG < datetime.timedelta(days=28)
    with pytest.raises(ss_mod.SpotStartRequiredError):
        swap_spread_for_curve(
            curve=curve, package=[swap], tenor="10Y", quotes=_StubQuotes(_series())
        )


# ------------------------------------------------------------------ #
#                     served through the value map                   #
# ------------------------------------------------------------------ #


def _value_map(curve, package):
    return IRSwapValueFunctionMap(curve=curve, package=package, risk_weights=[1.0])


def test_the_value_map_serves_the_published_number_for_an_eod_citi_curve():
    curve = _eod_curve()
    swap = _FakeSwap(datetime.date(2026, 8, 10), datetime.date(2036, 8, 10))
    stub = _StubQuotes(_series())
    out = _value_map(curve, [swap]).apply(
        value=IRSwapValue.CITIVELO_SWAP_SPREAD, quotes=stub, tenor="10Y"
    )
    assert out == pytest.approx(SENTINEL, abs=0.0)
    assert stub.calls[-1][0] == ("RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y",)
    assert stub.calls[-1][1] == "DAILY"


def test_the_value_map_derives_the_tenor_when_it_is_not_given():
    curve = _eod_curve()
    swap = _FakeSwap(datetime.date(2026, 8, 10), datetime.date(2036, 8, 10))
    stub = _StubQuotes(_series())
    out = _value_map(curve, [swap]).apply(value=IRSwapValue.CITIVELO_SWAP_SPREAD, quotes=stub)
    assert out == pytest.approx(SENTINEL, abs=0.0)
    assert stub.calls[-1][0] == ("RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y",)


def test_a_live_curve_reads_the_spread_at_the_curves_own_instant_not_at_now():
    """A live curve's stamp is already in the past. Re-asking for "live" would pair
    the curve with a spread from a different minute - two markets stitched
    together, neither number wrong on its own."""
    instant = pd.Timestamp.now(tz=NY).floor("min") - pd.Timedelta(minutes=4)
    curve = _FakeCitiCurve(
        {
            "source": SOURCE_TOKEN,
            "mode": "live",
            "citi_index": "USD_SOFR",
            "timestamp": instant.to_pydatetime(),
            "reference_date": instant.date().isoformat(),
        }
    )
    index = pd.date_range(instant - pd.Timedelta(minutes=30), instant, freq="min").tz_localize(None)
    stub = _StubQuotes(_series(index=index))
    # The effective date is derived from the curve's own instant rather than
    # hardcoded: the spot-start guard measures against the curve's as-of, and a
    # fixed 2026-08-10 would silently turn this into a forward-start case as soon
    # as the wall clock moved past it.
    effective = instant.date() + datetime.timedelta(days=2)
    swap = _FakeSwap(
        effective,
        datetime.date(effective.year + 10, effective.month, min(effective.day, 28)),
    )

    quote = swap_spread_for_curve(
        curve=curve, package=[swap], tenor="10Y", quotes=stub, return_quote=True
    )
    assert quote.mode == "intraday", "a live curve pins the spread to its own instant"
    assert stub.calls[-1][1] == "MI01"
    assert stub.calls[-1][2]["end"] == instant.tz_localize(None).to_pydatetime()


def test_an_eod_curve_reads_the_spread_from_its_own_reference_date():
    curve = _eod_curve(reference_date=datetime.date(2026, 8, 5))
    swap = _FakeSwap(datetime.date(2026, 8, 10), datetime.date(2036, 8, 10))
    stub = _StubQuotes(_series())
    quote = swap_spread_for_curve(
        curve=curve, package=[swap], tenor="10Y", quotes=stub, return_quote=True
    )
    assert quote.mode == "eod"
    assert stub.calls[-1][2]["end"] == datetime.datetime(2026, 8, 5, 23, 59, 59)


def test_a_curve_from_another_source_is_refused_by_name():
    """Every other value on the map would have answered, so a silent wrong answer
    here would be invisible. The message has to name the source that was found."""
    curve = _FakeCitiCurve(
        {"source": "cme_ny_eod_live", "mode": "eod", "citi_index": "USD_SOFR",
         "reference_date": "2026-08-06"}
    )
    swap = _FakeSwap(datetime.date(2026, 8, 10), datetime.date(2036, 8, 10))
    with pytest.raises(ValueError, match="cme_ny_eod_live"):
        swap_spread_for_curve(curve=curve, package=[swap], tenor="10Y", quotes=_StubQuotes(_series()))


@pytest.mark.parametrize("n_legs", [2, 3])
def test_a_multi_leg_package_is_refused(n_legs):
    """Citi publishes CURVES and BFLY as their own sub-types; risk-weighting two
    published spreads would manufacture a quote that never existed."""
    curve = _eod_curve()
    swap = _FakeSwap(datetime.date(2026, 8, 10), datetime.date(2036, 8, 10))
    with pytest.raises(NotImplementedError, match="outright"):
        swap_spread_for_curve(curve=curve, package=[swap] * n_legs, tenor="10Y")


def test_it_reaches_the_value_through_an_irswapquery_the_way_a_caller_would():
    """The plumbing, not just the function. ``build_value_map`` goes through the
    registered IRS adapter, and ``value_kwargs`` is the mechanism that already
    carries ``horizon`` for the carry/roll values - so ``tenor`` and ``quotes``
    ride the same rail rather than needing a new one."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery

    curve = _eod_curve()
    swap = _FakeSwap(datetime.date(2026, 8, 10), datetime.date(2036, 8, 10))
    stub = _StubQuotes(_series())
    query = IRSwapQuery(
        curve="USD-SOFR-1D",
        tenor="10Y",
        value=IRSwapValue.CITIVELO_SWAP_SPREAD,
        value_kwargs={"tenor": "10Y", "quotes": stub},
    )
    value_map = query.build_value_map(pricer_or_curve=curve, package=[swap], risk_weights=[1.0])
    out = value_map.apply(value=query.value, **(query.value_kwargs or {}))
    assert out == pytest.approx(SENTINEL, abs=0.0)


def test_the_value_map_does_not_forward_risk_weights_into_the_fetcher():
    """``apply`` merges the map's own kwargs with the caller's, so a blind
    ``**kwargs`` would hand ``risk_weights`` to a function that has no such
    parameter. The allow-list is what stops that, and this is the test for it."""
    curve = _eod_curve()
    swap = _FakeSwap(datetime.date(2026, 8, 10), datetime.date(2036, 8, 10))
    out = _value_map(curve, [swap]).apply(
        value=IRSwapValue.CITIVELO_SWAP_SPREAD, quotes=_StubQuotes(_series()), tenor="10Y"
    )
    assert out == pytest.approx(SENTINEL, abs=0.0)


# ------------------------------------------------------------------ #
#                    the tie-out script's memory gate                #
# ------------------------------------------------------------------ #


def _tieout_module():
    """Import ``scripts/citivelo_swap_spread_tieout.py`` without running it."""
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "citivelo_swap_spread_tieout.py"
    spec = importlib.util.spec_from_file_location("_tieout_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sentinel_on_the_hazard(monkeypatch):
    """Put the tripwire on the LIVE CONNECTION, not on the last line of ``fetch``.

    The previous version of this guarded ``module._out_path``, which ``fetch``
    reaches at tieout:226 - 43 lines AFTER ``swap_spread_history`` at :183, which
    is what builds a ``CitiVeloQuotes(offline=False)`` and opens COM. So the one
    mutation that proves the gate (``_memory_gate -> return True``) could not be
    run without connecting to a 13.2 GB Excel, and therefore never was.

    ``fetch`` imports ``swap_spread_history`` INSIDE the function, so the name has
    to be replaced on the SOURCE module - patching the tieout module object would
    silently not take, and the test would pass for the wrong reason.
    """
    tripped: list = []

    def _must_not_run(*a, **k):  # pragma: no cover - reaching this IS the failure
        tripped.append((a, k))
        raise AssertionError(
            "fetch proceeded past the memory gate and reached the live-Excel path"
        )

    monkeypatch.setattr(ss_mod, "swap_spread_history", _must_not_run)
    monkeypatch.setattr(ss_mod, "_default_quotes", _must_not_run)
    return tripped


def test_the_tieout_script_aborts_above_the_memory_ceiling_without_touching_excel(
    monkeypatch, tmp_path
):
    """The guard that matters most, because the failure it prevents is unrecoverable
    without a human: the add-in's cache only ever grows and a wedged Excel at
    5,249 MB has already happened once (2026-08-07). The level measured on
    2026-08-08 was 13,221 MB - 2.5x the wedge - which is why nothing in this
    session fetched anything.
    """
    module = _tieout_module()
    assert module.DEFAULT_MEMORY_ABORT_MB == 3800.0
    monkeypatch.setattr(module, "excel_memory_mb", lambda: 13221.0)
    tripped = _sentinel_on_the_hazard(monkeypatch)

    rc = module.fetch(
        citi_index="USD_SOFR",
        start=datetime.date(2026, 1, 1),
        end=datetime.date(2026, 8, 6),
        tenors=None,
        out_dir=tmp_path,
        memory_abort_mb=module.DEFAULT_MEMORY_ABORT_MB,
        force_refresh=False,
    )
    assert rc == 2
    assert tripped == [], "the fetch must not have reached the live-Excel path"
    assert not list(tmp_path.iterdir()), "an aborted fetch must write nothing"


def test_the_tieout_script_aborts_when_the_probe_cannot_be_read(monkeypatch, tmp_path):
    """FAIL CLOSED. A running-but-unreadable Excel and no Excel at all used to be
    the same observation (``None``), and the gate proceeded on it - so a
    PowerShell timeout, PowerShell off PATH or a locked-down execution policy
    would have connected COM into whatever was actually running, which on this
    machine is 13.2 GB and only a human restart clears.
    """
    module = _tieout_module()
    monkeypatch.setattr(module, "excel_memory_mb", lambda: None)
    tripped = _sentinel_on_the_hazard(monkeypatch)

    rc = module.fetch(
        citi_index="USD_SOFR",
        start=datetime.date(2026, 1, 1),
        end=datetime.date(2026, 8, 6),
        tenors=None,
        out_dir=tmp_path,
        memory_abort_mb=module.DEFAULT_MEMORY_ABORT_MB,
        force_refresh=False,
    )
    assert rc == 2
    assert tripped == []
    assert not list(tmp_path.iterdir())


def test_the_tieout_script_proceeds_below_the_ceiling(monkeypatch):
    """The gate must have an OPEN state too, or the abort tests would pass against a
    function that always refuses. Every call here is stubbed: the previous version
    of this test opened with ``_memory_gate(3800.0)``, which ran the REAL
    PowerShell probe against the live EXCEL.EXE from a file whose docstring says
    "no Excel, no network", and then asserted ``is not None`` - which every
    possible return satisfies.
    """
    module = _tieout_module()
    monkeypatch.setattr(module, "excel_memory_mb", lambda: 674.0)
    assert module._memory_gate(3800.0) is True
    monkeypatch.setattr(module, "excel_memory_mb", lambda: 0.0)
    assert module._memory_gate(3800.0) is True, "no Excel running at all is the safest state"
    monkeypatch.setattr(module, "excel_memory_mb", lambda: 3800.0)
    assert module._memory_gate(3800.0) is False, "the ceiling is inclusive"
    monkeypatch.setattr(module, "excel_memory_mb", lambda: 13221.0)
    assert module._memory_gate(3800.0) is False
    monkeypatch.setattr(module, "excel_memory_mb", lambda: None)
    assert module._memory_gate(3800.0) is False, "an unreadable probe must not proceed"


class _FakeCompleted:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


@pytest.mark.parametrize(
    "outcome,expected",
    [
        (_FakeCompleted("NONE\n"), 0.0),
        (_FakeCompleted("13221000000\n"), 13221.0),
        (_FakeCompleted("", returncode=1), None),
        (_FakeCompleted("not a number\n"), None),
        (_FakeCompleted("\n"), None),
    ],
)
def test_the_probe_separates_no_excel_from_an_unreadable_probe(monkeypatch, outcome, expected):
    """The two states the old probe collapsed into ``None``, and whose correct
    actions are opposite. ``Measure-Object -Sum`` over zero processes sums to
    ``$null``, so the query emits an explicit ``NONE`` rather than an empty line
    that could equally mean the command never ran.

    Hermetic: ``subprocess.run`` is replaced, so no PowerShell is spawned and no
    EXCEL.EXE is inspected.
    """
    module = _tieout_module()
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: outcome)
    got = module.excel_memory_mb()
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_the_probe_reports_unreadable_when_powershell_cannot_be_run(monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError("powershell")

    module = _tieout_module()
    monkeypatch.setattr(module.subprocess, "run", _boom)
    assert module.excel_memory_mb() is None


# ------------------------------------------------------------------ #
#              coexistence with the two computed spreads             #
# ------------------------------------------------------------------ #


def test_the_new_member_does_not_shadow_mmss_or_spreadover():
    from MDP.IRSwapSpreads.IRSwapSpreadsMDP import (
        _BENCHMARK_SPREAD_VALUES,
        _MMSS_VALUES,
        _SPREADOVER_VALUES,
    )

    new = IRSwapValue.CITIVELO_SWAP_SPREAD
    assert IRSwapValue.MMSS in _MMSS_VALUES and IRSwapValue.SPREADOVER in _SPREADOVER_VALUES
    assert new not in _MMSS_VALUES
    assert new not in _SPREADOVER_VALUES
    assert new not in _BENCHMARK_SPREAD_VALUES


def test_the_timeseries_builder_still_routes_mmss_and_spreadover_to_the_bond_path():
    """And routes the new one down the ordinary IRS value path instead, because it
    needs no bond pricer at all."""
    from TB.TimeseriesBuilder import _IRSWAP_ADJUSTED_SPREAD_VALUES

    routed = {IRSwapValue.MMSS, IRSwapValue.SPREADOVER} | _IRSWAP_ADJUSTED_SPREAD_VALUES
    assert IRSwapValue.CITIVELO_SWAP_SPREAD not in routed


def test_only_the_new_member_is_on_the_value_function_map():
    """MMSS/SPREADOVER are served by IRSwapSpreadsMDP, not by this map. If a future
    edit put them here they would start answering from a curve with no bond leg."""
    value_map = _value_map(_eod_curve(), [_FakeSwap(datetime.date(2026, 8, 10),
                                                   datetime.date(2036, 8, 10))])
    assert IRSwapValue.CITIVELO_SWAP_SPREAD in value_map._map
    assert IRSwapValue.MMSS not in value_map._map
    assert IRSwapValue.SPREADOVER not in value_map._map


def test_the_name_cannot_be_caught_by_the_existing_column_filters():
    """``BT/signals/tfp_swap_spread.py`` selects columns with ``"MMSS" in c``. A
    name like CITIVELO_MMSS would have been silently swept into that backtest's
    MMSS panel; this one cannot be."""
    name = IRSwapValue.CITIVELO_SWAP_SPREAD.name
    assert "MMSS" not in name
    assert "SPREADOVER" not in name
    assert name.startswith("CITIVELO"), "the publisher is the distinction: this one is a QUOTE"


def test_the_unified_value_exists_and_is_distinct():
    from Query.Unified.registry import UnifiedValue

    assert UnifiedValue.IRS_CITIVELO_SWAP_SPREAD.name == "IRS_CITIVELO_SWAP_SPREAD"
    assert len({UnifiedValue.IRS_CITIVELO_SWAP_SPREAD,
                UnifiedValue.IRS_MMSS,
                UnifiedValue.IRS_SPREADOVER}) == 3


def test_appending_the_member_did_not_renumber_the_existing_ones():
    """``auto()`` renumbers everything after an insertion point. Pinning two of the
    older members is what turns a mid-list insert from silent into a failure."""
    assert IRSwapValue.SPREADOVER.value == 10
    assert IRSwapValue.MMSS.value == 11
    assert IRSwapValue.CITIVELO_SWAP_SPREAD.value == max(v.value for v in IRSwapValue)

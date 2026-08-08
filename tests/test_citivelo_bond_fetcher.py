r"""The Velocity BOND fetcher: mode dispatch, coverage honesty, and the cliff.

Hermetic. No Excel process is opened and no network is touched: every test drives
either the packaged COM fake (:mod:`MDP.CitiVelocityExcel.testing`) or a stub
quotes object. That is not a convenience - at the time these were written
``EXCEL.EXE`` was at 7,639 MB against a 3,800 MB ceiling and there were **zero**
cached ``RATES.BOND`` tags, so a test that reached the live path would have had
nothing to reach and would have risked wedging a process only a human can restart.

The bond ISINs are real ones out of the committed 2,162-ISIN harvest, and their
per-bond coverage is the harvest's own. That matters for the central test here:
``US91282CCS89`` genuinely does not serve ``ASW_4_USD`` while ``US91282CNJ61``
does, so "only ask for what this bond serves" is checked against real unevenness
rather than against a fixture invented to make it true.

What each group is defending against
------------------------------------
**Mode dispatch.** ``pd.Timestamp`` ⊂ ``datetime`` ⊂ ``date``, so an isinstance
ladder is wrong in both directions. A midnight Timestamp is the common spelling
of "that day" and must resolve to EOD; a 14:30 Timestamp must NOT, even though
``isinstance(x, datetime.date)`` is True for it.

**Unavailable vs empty.** Merging them turns "widen your window" into "this bond
has no OAS", which is false for 1,401 of 2,162 ISINs - OAS was measured empty
over one week and full over five years.

**Never request what is not served.** An unserved tag that falls through to a
live ``CVTSHIST`` call, once per bond, is a warm that spends the Excel budget
rediscovering something already committed to JSON. The assertion is on the
formulas the fake actually received, not on the fetcher's own bookkeeping - a
fetch that requested a tag and then discarded it would pass the weaker check.

**The span cliff.** ``CVTSHIST`` downsamples by requested span, silently; the
``MI01`` cliff is exactly 7 days. The fake reproduces that (``downsample_cliff``),
so the test that a 20-day intraday lookback still comes back at 1-minute spacing
is a real check on the chunker rather than a restatement of it.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

from MDP.CitiVelocityExcel.bonds import fetcher as fetcher_module
from MDP.CitiVelocityExcel.bonds import values as V
from MDP.CitiVelocityExcel.bonds.conventions import UNIVERSE_COUNTRIES
from MDP.CitiVelocityExcel.bonds.fetcher import (
    BOND_MARKET_TIMEZONES,
    CITI_QUOTE_PREFIX,
    COMPUTED_FRB_VALUES,
    DEFAULT_BOND_VALUES,
    DEFAULT_MAX_PRICE_LAG,
    BondQuoteTransportError,
    CitiVeloBondFetcher,
    build_pricer_args,
    market_timezone,
)
from MDP.CitiVelocityExcel.bonds.resolution import resolve_bond
from MDP.CitiVelocityExcel.bonds.universe import BondUniverse
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData
from MDP.CitiVelocityExcel.windowed import MAX_SPAN

#: Two real US Treasuries out of the harvest, chosen because their coverage
#: DIFFERS: 91282CNJ6 serves ASW_4_USD and 91282CCS8 does not. Both serve
#: ASW_4_AUD (348 of the 349 US Treasuries do). Neither serves CAS, and no US
#: TREASURY does - exactly one US ISIN in the whole universe carries CAS,
#: US3133EPSW68, an FFCB agency, so "no bond in the US universe" would be wrong.
ISIN_WITH_ASW_USD = "US91282CNJ61"
ISIN_WITHOUT_ASW_USD = "US91282CCS89"
#: A JGB, for the intraday day-bucketing test: Citi stamps it in New York, but its
#: session is Tokyo's, so a 22:30 ET print belongs to the NEXT Tokyo date.
ISIN_JGB = "JP1300561H93"
#: An MBONO, for the EOD half of the same asymmetry. Mexico City is the only zone
#: in ``BOND_MARKET_TIMEZONES`` WEST of New York, and it is the only one that moves
#: an EOD label: midnight ET on 2026-08-06 is 22:00 on 2026-08-05 in Mexico City
#: (Mexico has run CST year-round since 2022, so there is no DST caveat), against
#: no move at all for Tokyo or Sao Paulo. A JGB therefore cannot fail that test.
ISIN_MEX = "MX0MGO0001N5"

NY = ZoneInfo("America/New_York")
TOKYO = ZoneInfo("Asia/Tokyo")
MEXICO_CITY = ZoneInfo("America/Mexico_City")


@pytest.fixture(scope="module")
def universe():
    return BondUniverse.from_catalog()


@pytest.fixture(scope="module")
def resolutions(universe):
    return [
        resolve_bond(ISIN_WITH_ASW_USD, universe=universe),
        resolve_bond(ISIN_WITHOUT_ASW_USD, universe=universe),
    ]


# ------------------------------------------------------------------ #
#                          fake data plumbing                        #
# ------------------------------------------------------------------ #

#: Every value gets a distinct number so a mix-up between them is visible rather
#: than plausible.
_VALUE_OFFSET = {
    "PRICE": 0.0,
    "YIELD": -95.0,
    "DURATION": -92.0,
    "SPREAD_TSY": -87.0,
    "DV01": -98.95,
    "ASW_4_USD": -120.0,
    "ASW_4_AUD": -125.0,
    "ASW_4_JPY": -130.0,
}

#: The default set plus the two values the coverage tests need and the defaults
#: deliberately leave out: ``OAS`` (both bonds serve it, and it returns nothing in
#: a short window - the ``empty`` case) and ``ASW_4_JPY`` (neither bond serves it -
#: the ``unavailable`` case). Passed explicitly rather than relied on as defaults,
#: because a coverage test that depends on the default list silently changes
#: meaning whenever the list does.
_COVERAGE_VALUES = tuple(DEFAULT_BOND_VALUES) + ("OAS", "ASW_4_JPY")
#: The base each bond's numbers are built from, so an assertion can name the
#: value it expects instead of restating an arithmetic coincidence.
_BASE = {
    ISIN_WITH_ASW_USD: 99.0,
    ISIN_WITHOUT_ASW_USD: 88.0,
    ISIN_JGB: 101.0,
    ISIN_MEX: 97.0,
}


def _daily_series(isin: str, base: float, *, values, start="2026-07-01", end="2026-08-06"):
    idx = pd.date_range(start, end, freq="D")
    return {
        f"RATES.BOND.{isin}.{v}": pd.Series(base + _VALUE_OFFSET[v], index=idx)
        for v in values
    }


def _minute_series(isin: str, base: float, *, values, start, end):
    idx = pd.date_range(start, end, freq="1min", inclusive="left")
    return {
        f"RATES.BOND.{isin}.{v}": pd.Series(base + _VALUE_OFFSET[v], index=idx)
        for v in values
    }


def _quotes_over(series, *, pending_reads=0):
    """A real ``CitiVeloQuotes`` on the packaged COM fake.

    ``cache=False`` on purpose: the cache is not under test here and a default
    ``CitiVeloQuotes()`` would write into the user's real cache directory and,
    on any miss, try to connect to a live Excel.
    """
    data = FakeVelocityData(series=dict(series))
    app = FakeExcelApp(data=data, pending_reads=pending_reads)
    workbook = app.Workbooks.Add()
    client = CitiVelocityExcelClient(app=app, workbook=workbook, drain_seconds=0.0)
    client._ws = workbook.Worksheets(1)
    return CitiVeloQuotes(client=client, cache=False), app


def _tags_asked(app) -> set:
    """Every tag the fake was actually asked for, across all ``CVTSHIST`` calls."""
    out = set()
    for formula in app.formulas_for("CVTSHIST"):
        taglist = formula.split('"')[1]
        out.update(t.strip() for t in taglist.split(",") if t.strip())
    return out


class _RecordingQuotes:
    """A quotes stub that serves a frame and records the bounds it was asked for.

    Deliberately does NOT expose an ``offline`` attribute: the fetcher reconciles
    its own ``offline`` flag against an injected reader's, and a stub that stayed
    silent about its state is the case where there is nothing to reconcile.
    :class:`_OfflineQuotes` is the one that declares itself.
    """

    def __init__(self, frame: pd.DataFrame):
        if frame.empty and not isinstance(frame.index, pd.DatetimeIndex):
            # What the real reader returns for a request that served nothing.
            frame = pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))
        self._frame = frame
        self.calls = []

    def frame(self, tags, freq="DAILY", **kwargs):
        self.calls.append({"tags": tuple(tags), "freq": freq, **kwargs})
        cols = [t for t in tags if t in self._frame.columns]
        out = self._frame[cols]
        if kwargs.get("start") is not None:
            out = out[out.index >= pd.Timestamp(kwargs["start"])]
        if kwargs.get("end") is not None:
            out = out[out.index <= pd.Timestamp(kwargs["end"])]
        return out

    def client(self):  # pragma: no cover - reaching this is the bug
        raise AssertionError("offline path must not ask for a live client")

    def close(self):
        pass


class _OfflineQuotes(_RecordingQuotes):
    """A reader that declares itself offline, the way ``CitiVeloQuotes`` does.

    ``CitiVeloQuotes(offline=True)`` cannot be used here: with ``cache=False`` its
    ``series()`` calls ``client()`` unconditionally and raises, and with the real
    cache the test would read the user's cache directory.
    """

    offline = True


class _DisconnectedClient:
    """A client that goes away mid-run, the way Excel does.

    ``-2147417848`` is the COM ``RPC_E_DISCONNECTED`` the add-in raises when the
    Excel process behind it dies. ``fetch_windowed`` catches it per window and
    records it on :class:`~MDP.CitiVelocityExcel.windowed.WindowResult.error`, so
    the fetcher sees a failure rather than an exception - which is exactly how a
    transport failure used to be laundered into "the market was empty".
    """

    MESSAGE = "(-2147417848) The object invoked has disconnected from its clients"

    def __init__(self):
        self.windows_pushed = 0

    def push_window_sheet(self, name):
        self.windows_pushed += 1
        return name

    def drop_window_sheet(self):
        pass

    def fetch_timeseries(self, tags, freq=None, **kwargs):
        raise RuntimeError(self.MESSAGE)

    def last_failures(self):
        return {}


class _DisconnectedQuotes:
    """Serves :class:`_DisconnectedClient` on the online path."""

    offline = False

    def __init__(self):
        self._client = _DisconnectedClient()

    def client(self):
        return self._client

    def close(self):
        pass


# ------------------------------------------------------------------ #
#                            mode dispatch                           #
# ------------------------------------------------------------------ #


def _eod_fetcher(resolutions):
    served = {}
    for isin, base in ((ISIN_WITH_ASW_USD, 99.0), (ISIN_WITHOUT_ASW_USD, 88.0)):
        vals = ["PRICE", "YIELD", "DURATION", "SPREAD_TSY", "DV01"]
        if isin == ISIN_WITH_ASW_USD:
            vals.append("ASW_4_USD")
        served.update(_daily_series(isin, base, values=vals))
    quotes, app = _quotes_over(served)
    return CitiVeloBondFetcher(quotes=quotes), app


def test_a_bare_date_is_end_of_day(resolutions):
    fetcher, _ = _eod_fetcher(resolutions)
    out = fetcher.fetch(resolutions, datetime.date(2026, 8, 6))
    quote = out[ISIN_WITH_ASW_USD]
    assert quote.mode == "eod"
    assert quote.freq == "DAILY"
    assert quote.market_date == datetime.date(2026, 8, 6)


def test_a_midnight_timestamp_is_end_of_day_not_intraday(resolutions):
    """``pd.Timestamp('2026-08-06')`` is the common accidental spelling of "that
    day", and it is also what the add-in stamps its own DAILY rows with, so the
    reading that round-trips is EOD."""
    fetcher, _ = _eod_fetcher(resolutions)
    out = fetcher.fetch(resolutions, pd.Timestamp("2026-08-06"))
    assert out[ISIN_WITH_ASW_USD].mode == "eod"
    assert out[ISIN_WITH_ASW_USD].freq == "DAILY"


def test_a_pandas_timestamp_with_a_time_is_intraday_not_a_date():
    """The isinstance trap, stated directly.

    ``isinstance(pd.Timestamp('2026-08-06 14:30'), datetime.date)`` is **True**,
    because Timestamp subclasses datetime subclasses date. A dispatch written as
    an isinstance ladder would answer a 14:30 request with a daily close.
    """
    ts = pd.Timestamp("2026-08-06 14:30")
    assert isinstance(ts, datetime.date), "premise of the trap changed"

    end = datetime.datetime(2026, 8, 6, 14, 30)
    served = _minute_series(
        ISIN_WITH_ASW_USD, 99.0, values=["PRICE"], start=end - datetime.timedelta(days=1), end=end
    )
    quotes, _ = _quotes_over(served)
    resolution = resolve_bond(ISIN_WITH_ASW_USD)
    out = CitiVeloBondFetcher(quotes=quotes).fetch([resolution], ts, values=["PRICE"])
    quote = out[ISIN_WITH_ASW_USD]
    assert quote.mode == "intraday"
    assert quote.freq == "MI01"


def test_live_resolves_to_the_minute_series_and_needs_no_timestamp():
    now = pd.Timestamp.now().floor("min").to_pydatetime()
    served = _minute_series(
        ISIN_WITH_ASW_USD, 99.0, values=["PRICE"], start=now - datetime.timedelta(hours=2), end=now
    )
    quotes, _ = _quotes_over(served)
    resolution = resolve_bond(ISIN_WITH_ASW_USD)
    out = CitiVeloBondFetcher(quotes=quotes).fetch([resolution], "live", values=["PRICE"])
    quote = out[ISIN_WITH_ASW_USD]
    assert quote.mode == "live"
    assert quote.freq == "MI01"
    assert quote.served


# ------------------------------------------------------------------ #
#                 only ask for what the bond serves                  #
# ------------------------------------------------------------------ #


def test_a_value_citi_does_not_serve_for_a_bond_is_never_requested(resolutions):
    """The assertion is on what the add-in RECEIVED.

    Checking ``quote.unavailable`` alone would pass for a fetcher that requested
    the tag and then threw the answer away - which is precisely the failure being
    guarded against, because the cost is the Excel round trip, not the column.
    """
    fetcher, app = _eod_fetcher(resolutions)
    fetcher.fetch(resolutions, datetime.date(2026, 8, 6), values=_COVERAGE_VALUES + ("CAS",))

    asked = _tags_asked(app)
    assert f"RATES.BOND.{ISIN_WITHOUT_ASW_USD}.ASW_4_USD" not in asked
    assert f"RATES.BOND.{ISIN_WITH_ASW_USD}.ASW_4_USD" in asked, "the served leg must still be asked for"
    assert not [t for t in asked if t.endswith(".CAS")], "no US Treasury serves CAS"
    assert not [t for t in asked if t.endswith(".ASW_4_JPY")], "neither bond serves the JPY leg"
    assert [t for t in asked if t.endswith(".ASW_4_AUD")], "both bonds serve the AUD leg"


def test_the_whole_basket_goes_out_in_one_call(resolutions):
    """One batched ``CVTSHIST``, not one per bond. A 300-name warm issued per bond
    is 300 round trips into an add-in whose memory only a human restart reclaims."""
    fetcher, app = _eod_fetcher(resolutions)
    fetcher.fetch(resolutions, datetime.date(2026, 8, 6))
    assert len(app.formulas_for("CVTSHIST")) == 1


def test_plan_reports_unavailable_without_asking_anything(resolutions):
    fetcher, app = _eod_fetcher(resolutions)
    plan = fetcher.plan(resolutions, values=_COVERAGE_VALUES)
    assert app.formulas_for("CVTSHIST") == [], "plan() must not fetch"
    assert "ASW_4_USD" in plan[ISIN_WITHOUT_ASW_USD]["unavailable"]
    assert "ASW_4_USD" in plan[ISIN_WITH_ASW_USD]["requested"]
    # Against the tag strings themselves, not against the sibling field: ``tags``
    # and ``requested`` are built in adjacent lines from the same list, so
    # comparing them to each other is a tautology of the implementation and
    # survives any refactor that keeps them built together.
    entry = plan[ISIN_WITH_ASW_USD]
    assert entry["tags"] == {
        v: f"RATES.BOND.{ISIN_WITH_ASW_USD}.{v}"
        for v in ("PRICE", "YIELD", "DURATION", "SPREAD_TSY", "DV01", "ASW_4_USD", "ASW_4_AUD", "OAS")
    }
    assert entry["unavailable"] == ("ASW_4_JPY",)


def test_an_unknown_value_token_is_rejected_rather_than_dropped(resolutions):
    """A typo silently dropped comes back as "Citi does not serve it for this
    bond", which sends the reader to look at coverage instead of at their own
    string."""
    fetcher, _ = _eod_fetcher(resolutions)
    with pytest.raises(KeyError, match="Unknown Citi bond value"):
        fetcher.plan(resolutions, values=["SPREAD_TREASURY"])


# ------------------------------------------------------------------ #
#                     unavailable is not empty                       #
# ------------------------------------------------------------------ #


def test_unavailable_and_empty_are_reported_separately(resolutions):
    """OAS is in this bond's served vocabulary and returns nothing in this window;
    ASW_4_JPY is not served at all. They are different answers with different
    fixes and must not be merged."""
    fetcher, _ = _eod_fetcher(resolutions)
    quote = fetcher.fetch(
        resolutions, datetime.date(2026, 8, 6), values=_COVERAGE_VALUES
    )[ISIN_WITH_ASW_USD]

    assert "OAS" in quote.empty
    assert "OAS" not in quote.unavailable
    assert "OAS" in quote.requested, "an empty value WAS asked for"

    assert "ASW_4_JPY" in quote.unavailable
    assert "ASW_4_JPY" not in quote.empty
    assert "ASW_4_JPY" not in quote.requested, "an unavailable value was NOT asked for"


def test_an_empty_value_is_a_normal_outcome_not_an_error(resolutions):
    """Measured: OAS returns nothing over a one-week window and a full history
    over five years. So an empty OAS must not sink the bond."""
    fetcher, _ = _eod_fetcher(resolutions)
    quote = fetcher.fetch(
        resolutions, datetime.date(2026, 8, 6), values=_COVERAGE_VALUES
    )[ISIN_WITH_ASW_USD]
    assert quote.served
    assert quote.get("PRICE") == pytest.approx(99.0)


def test_a_bond_that_served_nothing_is_reported_not_dropped(resolutions):
    """An all-empty bond stays in the result with an explanation. Dropping it
    would make "Citi has no data today" indistinguishable from "you asked for a
    bond that does not exist"."""
    served = _daily_series(ISIN_WITH_ASW_USD, 99.0, values=["PRICE"])
    quotes, _ = _quotes_over(served)
    out = CitiVeloBondFetcher(quotes=quotes).fetch(resolutions, datetime.date(2026, 8, 6))

    starved = out[ISIN_WITHOUT_ASW_USD]
    assert not starved.served
    assert starved.quoted == {}
    assert "PRICE" in starved.empty
    assert starved.as_of.tzinfo is not None, "as_of must stay tz-aware even with nothing served"


def test_no_price_raises_rather_than_inventing_one(resolutions):
    served = _daily_series(ISIN_WITH_ASW_USD, 99.0, values=["PRICE"])
    quotes, _ = _quotes_over(served)
    out = CitiVeloBondFetcher(quotes=quotes).fetch(resolutions, datetime.date(2026, 8, 6))
    with pytest.raises(ValueError, match="No Citi PRICE"):
        build_pricer_args(out[ISIN_WITHOUT_ASW_USD], backend="QL", ref_meta={})


# ------------------------------------------------------------------ #
#                             provenance                             #
# ------------------------------------------------------------------ #


def _args_for(resolutions, backend="QL"):
    fetcher, _ = _eod_fetcher(resolutions)
    quote = fetcher.fetch(
        resolutions, datetime.date(2026, 8, 6), values=_COVERAGE_VALUES
    )[ISIN_WITH_ASW_USD]
    return build_pricer_args(
        quote,
        backend=backend,
        ref_meta={"cusip": "91282CNJ6", "issue_date": "2025-06-30", "maturity_date": "2032-06-30", "cpn": 4.0},
    )


def test_a_quoted_value_records_the_tag_it_came_from(resolutions):
    meta = _args_for(resolutions)["meta_data"]
    prov = V.provenance_of(meta, "SPREAD_TSY")
    assert prov is not None
    assert prov.origin == "quoted"
    assert prov.detail == f"RATES.BOND.{ISIN_WITH_ASW_USD}.SPREAD_TSY"
    assert prov.unit == "basis_points"


def test_a_computed_value_records_the_backend_and_the_quote_it_used(resolutions):
    """"computed" alone is not a claim you can check; "computed by
    RLFixedRateBondPricer.ytm from RATES.BOND.<ISIN>.PRICE" is."""
    for backend, expect in (("QL", "QLFixedRateBondPricer.ytm"), ("RL", "RLFixedRateBondPricer.ytm")):
        meta = _args_for(resolutions, backend=backend)["meta_data"]
        prov = V.provenance_of(meta, "YTM")
        assert prov.origin == "computed"
        assert expect in prov.detail
        assert prov.detail.endswith(f"<-RATES.BOND.{ISIN_WITH_ASW_USD}.PRICE")


def test_clean_price_carries_the_unverified_reading_forward(resolutions):
    """Citi's PRICE is READ as clean and that has not been measured. The source
    must propagate the standing, not quietly assert it - if the number is dirty
    every downstream yield is wrong by up to 3.18 price points."""
    meta = _args_for(resolutions)["meta_data"]
    prov = V.provenance_of(meta, "CLEAN_PRICE")
    assert prov.origin == "quoted"
    assert prov.verified is False
    assert "UNVERIFIED" in prov.note
    assert "PRICE" in V.unverified_values()


def test_every_computed_frb_value_has_a_provenance_entry(resolutions):
    meta = _args_for(resolutions)["meta_data"]
    for frb_value in COMPUTED_FRB_VALUES:
        prov = V.provenance_of(meta, frb_value)
        assert prov is not None, frb_value
        assert prov.origin == "computed", frb_value


def test_the_dv01_name_collision_is_resolved_explicitly_not_silently(resolutions):
    """``DV01`` is both a Citi value token and an FRB member, and they are
    DIFFERENT numbers here: Citi publishes its own, while FRB_DV01 is the
    backend's PV01 off the locally re-solved yield. The flat book records what
    FRB_DV01 returns, and Citi's own keeps its provenance beside it rather than
    being overwritten."""
    meta = _args_for(resolutions)["meta_data"]
    assert V.provenance_of(meta, "DV01").origin == "computed"

    displaced = V.provenance_of(meta, f"{CITI_QUOTE_PREFIX}DV01")
    assert displaced is not None, "the quoted DV01 provenance was silently dropped"
    assert displaced.origin == "quoted"
    assert displaced.detail == f"RATES.BOND.{ISIN_WITH_ASW_USD}.DV01"
    # And Citi's own number is still there to calibrate against.
    assert V.quoted_value_of(meta, "DV01") == pytest.approx(
        _BASE[ISIN_WITH_ASW_USD] + _VALUE_OFFSET["DV01"]
    )


def test_citis_own_numbers_are_all_kept_even_the_unused_ones(resolutions):
    """YIELD and DURATION are not what FRB_YTM and FRB_MOD_DURATION return, but
    keeping them is what makes the calibration possible without a second fetch."""
    meta = _args_for(resolutions)["meta_data"]
    for value in ("PRICE", "YIELD", "DURATION", "DV01", "SPREAD_TSY", "ASW_4_USD"):
        assert V.quoted_value_of(meta, value) is not None, value
    assert V.quoted_value_of(meta, "OAS") is None


def test_the_backend_selects_the_pricer_key_not_a_backend_field(resolutions):
    """``_build_pricer_from_args`` dispatches on key PRESENCE, so the -QL/-RL
    suffix has to change which key exists."""
    assert "ql_frb_id" in _args_for(resolutions, backend="QL")
    assert "rl_frb_id" not in _args_for(resolutions, backend="QL")
    assert "rl_frb_id" in _args_for(resolutions, backend="RL")
    assert "ql_frb_id" not in _args_for(resolutions, backend="RL")


def test_coverage_book_round_trips_the_three_lists(resolutions):
    meta = _args_for(resolutions)["meta_data"]
    coverage = V.coverage_of(meta)
    assert "OAS" in coverage["empty"]
    assert "ASW_4_JPY" in coverage["unavailable"]
    assert "PRICE" in coverage["requested"]
    assert V.is_velocity_meta(meta)
    assert not V.is_velocity_meta({"cusip": "91282CNJ6"})


# ------------------------------------------------------------------ #
#                       the market-timezone table                    #
# ------------------------------------------------------------------ #


def test_the_market_timezone_table_covers_every_universe_country():
    """A country missing from the table falls back to New York, which is a
    one-business-day misdate for anything east of it and completely silent."""
    missing = [c for c in UNIVERSE_COUNTRIES if c not in BOND_MARKET_TIMEZONES]
    assert not missing, f"no market timezone for {missing}"


def test_every_market_timezone_is_a_real_zone():
    """Two separate checks, and only the first used to have teeth.

    ``market_timezone(country) == BOND_MARKET_TIMEZONES[country]`` inside a loop
    over that same dict re-reads the table under test through a function that only
    reads that table: it survives replacing every entry with one wrong zone. So
    the mapping is pinned against literals here, for the entries whose wrongness
    would move a date rather than merely rename a zone.
    """
    for country, name in BOND_MARKET_TIMEZONES.items():
        ZoneInfo(name)  # raises for a typo

    assert BOND_MARKET_TIMEZONES["USA"] == "America/New_York"
    assert BOND_MARKET_TIMEZONES["JPN"] == "Asia/Tokyo"
    assert BOND_MARKET_TIMEZONES["MEX"] == "America/Mexico_City"
    assert BOND_MARKET_TIMEZONES["NZL"] == "Pacific/Auckland"
    assert market_timezone("jpn") == "Asia/Tokyo", "the lookup upper-cases and strips"


def test_an_unknown_country_falls_back_to_the_wire_zone_rather_than_guessing():
    assert market_timezone("ZZZ") == "America/New_York"
    assert market_timezone(None) == "America/New_York"


def test_intraday_day_bucketing_uses_the_bonds_own_market_zone(universe):
    """A JGB print at 22:30 New York on a Tuesday is 11:30 Wednesday in Tokyo and
    belongs to Wednesday's session. Bucketing it by the ET calendar date puts a
    whole morning session one business day early - the sibling curve source has
    that failure recorded on JPY_TONAR."""
    end = datetime.datetime(2026, 8, 4, 22, 30)  # Tuesday, ET
    served = _minute_series(
        ISIN_JGB, 101.0, values=["PRICE"], start=end - datetime.timedelta(hours=2), end=end
    )
    quotes, _ = _quotes_over(served)
    resolution = resolve_bond(ISIN_JGB, universe=universe)
    quote = CitiVeloBondFetcher(quotes=quotes).fetch(
        [resolution], end.replace(tzinfo=NY), values=["PRICE"]
    )[ISIN_JGB]

    assert quote.market_timezone == "Asia/Tokyo"
    assert quote.as_of.astimezone(NY).date() == datetime.date(2026, 8, 4)
    assert quote.market_date == datetime.date(2026, 8, 5), "the Tokyo session date, not the ET one"


def test_eod_keeps_citis_own_date_label_rather_than_re_deriving_it(universe):
    """The opposite rule, and it is not an inconsistency. An EOD row is stamped
    with the label Citi assigned it, at midnight ET; re-deriving that through a
    local zone moves it for every market west of New York.

    The fixture is an MBONO and that is the whole point. This test previously used
    a JGB, which made it INERT: midnight ET converted to Asia/Tokyo is the same
    calendar date, so deleting the asymmetry (replacing the two branches of
    ``_market_date`` with an unconditional ``astimezone(...).date()``) left all 59
    tests in this file passing. Measured over the eighteen zones in
    ``BOND_MARKET_TIMEZONES``, ``2026-08-06 00:00-04:00`` moves the date for
    exactly one of them - America/Mexico_City, to 2026-08-05. Tokyo and
    Sao_Paulo do not move. So the fixture has to be the Mexican bond.
    """
    served = _daily_series(ISIN_MEX, _BASE[ISIN_MEX], values=["PRICE"])
    quotes, _ = _quotes_over(served)
    resolution = resolve_bond(ISIN_MEX, universe=universe)
    quote = CitiVeloBondFetcher(quotes=quotes).fetch(
        [resolution], datetime.date(2026, 8, 6), values=["PRICE"]
    )[ISIN_MEX]

    assert quote.market_timezone == "America/Mexico_City"
    # The premise, stated so a zone-database change cannot make the test vacuous.
    assert quote.as_of.astimezone(MEXICO_CITY).date() == datetime.date(2026, 8, 5)
    assert quote.market_date == datetime.date(2026, 8, 6), "Citi's own EOD label, not a re-derivation"


def test_intraday_bucketing_moves_a_western_market_backwards_too(universe):
    """The other half of the asymmetry, on the same bond.

    The JGB test above shows an eastern session moving FORWARD. This one shows a
    western session moving BACKWARD: 00:30 ET on 2026-08-06 is 22:30 on the 5th in
    Mexico City and belongs to the 5th's session. One bond exercising both
    branches is what makes the pair of rules assertable rather than a matter of
    which fixture happened to be picked.
    """
    end = datetime.datetime(2026, 8, 6, 0, 30)  # ET
    served = _minute_series(
        ISIN_MEX, _BASE[ISIN_MEX], values=["PRICE"],
        start=end - datetime.timedelta(hours=2), end=end,
    )
    quotes, _ = _quotes_over(served)
    resolution = resolve_bond(ISIN_MEX, universe=universe)
    quote = CitiVeloBondFetcher(quotes=quotes).fetch(
        [resolution], end.replace(tzinfo=NY), values=["PRICE"]
    )[ISIN_MEX]

    assert quote.as_of.astimezone(NY).date() == datetime.date(2026, 8, 6)
    assert quote.market_date == datetime.date(2026, 8, 5), "the Mexico City session date, not the ET one"


def test_an_eod_asof_dates_the_quote_by_the_row_that_answered(resolutions):
    """A request over a day with no row resolves backwards. Dating that quote by
    the day that was ASKED for would price Friday's close as of Sunday."""
    served = _daily_series(ISIN_WITH_ASW_USD, 99.0, values=["PRICE"], end="2026-08-07")
    quotes, _ = _quotes_over(served)
    resolution = resolve_bond(ISIN_WITH_ASW_USD)
    quote = CitiVeloBondFetcher(quotes=quotes).fetch(
        [resolution], datetime.date(2026, 8, 9), values=["PRICE"]
    )[ISIN_WITH_ASW_USD]
    assert quote.market_date == datetime.date(2026, 8, 7)


# ------------------------------------------------------------------ #
#                            the span cliff                          #
# ------------------------------------------------------------------ #


def test_a_wide_intraday_lookback_is_chunked_and_stays_at_full_resolution():
    """The chunker, checked by its OUTPUT rather than by its call count.

    The fake reproduces the measured cliff: an MI01 request spanning more than 6
    days comes back at 10-minute spacing, silently, looking exactly like a
    successful minute request. A 20-day lookback issued as one call would
    therefore return a quarter of the rows and no error at all - so asserting
    1-minute spacing here is what proves the request was chunked.
    """
    end = datetime.datetime(2026, 8, 6, 14, 30)
    start = end - datetime.timedelta(days=21)
    served = _minute_series(ISIN_WITH_ASW_USD, 99.0, values=["PRICE"], start=start, end=end)
    quotes, app = _quotes_over(served)

    fetcher = CitiVeloBondFetcher(
        quotes=quotes, intraday_lookback=datetime.timedelta(days=20)
    )
    resolution = resolve_bond(ISIN_WITH_ASW_USD)
    quote = fetcher.fetch([resolution], end, values=["PRICE"])[ISIN_WITH_ASW_USD]

    assert quote.served
    assert len(app.formulas_for("CVTSHIST")) >= 4, "a 20-day MI01 span must be chunked"
    # Each window got its own sheet, and each was dropped once read: a backfill
    # that leaves them behind fills Excel with live add-in cells.
    workbook = app.workbooks_created[0]
    assert len(workbook.sheets_deleted) == len(app.formulas_for("CVTSHIST"))


def test_the_offline_intraday_path_clamps_the_window_under_the_cliff():
    """Offline cannot push the per-window sheets ``fetch_windowed`` needs, so it
    holds the request under the cliff instead. Unclamped, a 20-day cached read
    would be a 20-day request the moment the cache was cold."""
    end = datetime.datetime(2026, 8, 6, 14, 30)
    idx = pd.date_range(end - datetime.timedelta(days=21), end, freq="1min", inclusive="left")
    frame = pd.DataFrame({f"RATES.BOND.{ISIN_WITH_ASW_USD}.PRICE": 99.0}, index=idx)
    quotes = _RecordingQuotes(frame)

    fetcher = CitiVeloBondFetcher(
        quotes=quotes, offline=True, intraday_lookback=datetime.timedelta(days=20)
    )
    resolution = resolve_bond(ISIN_WITH_ASW_USD)
    fetcher.fetch([resolution], end, values=["PRICE"])

    assert len(quotes.calls) == 1
    call = quotes.calls[0]
    assert call["freq"] == "MI01"
    span = pd.Timestamp(call["end"]) - pd.Timestamp(call["start"])
    assert span <= MAX_SPAN["MI01"], f"offline intraday asked for {span}, past the cliff"


def test_eod_is_not_clamped_because_daily_has_no_cliff():
    """DAILY is not on the granularity ladder, so the EOD lookback must survive
    intact - clamping it would silently shorten every as-of search."""
    served = _daily_series(ISIN_WITH_ASW_USD, 99.0, values=["PRICE"], start="2026-01-01")
    idx = pd.date_range("2026-01-01", "2026-08-06", freq="D")
    frame = pd.DataFrame({f"RATES.BOND.{ISIN_WITH_ASW_USD}.PRICE": 99.0}, index=idx)
    quotes = _RecordingQuotes(frame)
    fetcher = CitiVeloBondFetcher(quotes=quotes, offline=True)
    resolution = resolve_bond(ISIN_WITH_ASW_USD)
    fetcher.fetch([resolution], datetime.date(2026, 8, 6), values=["PRICE"])

    call = quotes.calls[0]
    assert call["freq"] == "DAILY"
    assert pd.Timestamp(call["end"]) - pd.Timestamp(call["start"]) >= datetime.timedelta(days=20)


# ------------------------------------------------------------------ #
#                              defaults                              #
# ------------------------------------------------------------------ #


def test_the_default_value_set_is_the_seven_a_default_window_can_actually_serve():
    """Pinned, because widening it silently multiplies the tag count of every
    warm and narrowing it silently drops a column downstream.

    Two of the eight originally in this tuple were wrong, both re-derived from the
    committed 16,288-tag harvest (2,147 of the 2,162 ISINs carry at least one
    validated tag):

    ``OAS`` is out. It is served for 1,401 of 2,162 ISINs (304 of the 349 US
    Treasuries) but is window-dependent - measured empty over one week and full
    over five years - and the default EOD lookback is 21 days. Keeping it in the
    defaults spends a column per bond on something the default window cannot
    return, which is precisely the cost this module exists to avoid. It stays
    addressable: pass ``citivelo_values=[..., "OAS"]`` with a wide ``eod_lookback``.

    ``ASW_4_JPY`` is out and ``ASW_4_AUD`` is in. The docstring claimed the set was
    "in descending coverage order", and JPY was in fact the LEAST covered value of
    all thirteen: 324 of 2,162 against AUD 1,120, GBP 1,110, USD 1,081, CHF 689,
    EUR 418, CAS 381. On the US universe the gap is starker still - 348 of the 349
    US Treasuries serve ASW_4_AUD against 253 for ASW_4_USD and 56 for ASW_4_JPY.
    """
    assert DEFAULT_BOND_VALUES == (
        "PRICE", "YIELD", "DURATION", "SPREAD_TSY", "DV01", "ASW_4_USD", "ASW_4_AUD",
    )
    for value in DEFAULT_BOND_VALUES:
        assert value in V.CITI_BOND_VALUES
    assert "OAS" not in DEFAULT_BOND_VALUES
    assert "OAS" in V.CITI_BOND_VALUES, "still addressable, just not by default"


def test_an_empty_basket_costs_nothing():
    quotes = _RecordingQuotes(pd.DataFrame())
    assert CitiVeloBondFetcher(quotes=quotes, offline=True).fetch([], datetime.date(2026, 8, 6)) == {}
    assert quotes.calls == []


def test_the_offline_clamp_uses_the_cliff_of_the_frequency_it_asked_for(monkeypatch):
    """The clamp reads ``MAX_SPAN[freq]``, not ``MAX_SPAN['MI01']``.

    Correct today only because ``_FREQ`` maps every mode to DAILY or MI01. Add a
    coarse-intraday mode - MI10, whose measured cliff is 60 days against MI01's 6 -
    and a hardcoded MI01 clamp truncates 90% of the lookback silently, which is the
    failure this module exists to prevent, inverted.
    """
    monkeypatch.setitem(fetcher_module._FREQ, "intraday", "MI10")

    end = datetime.datetime(2026, 8, 6, 14, 30)
    idx = pd.date_range(end - datetime.timedelta(days=21), end, freq="10min", inclusive="left")
    frame = pd.DataFrame({f"RATES.BOND.{ISIN_WITH_ASW_USD}.PRICE": 99.0}, index=idx)
    quotes = _RecordingQuotes(frame)

    fetcher = CitiVeloBondFetcher(
        quotes=quotes, offline=True, intraday_lookback=datetime.timedelta(days=20)
    )
    fetcher.fetch([resolve_bond(ISIN_WITH_ASW_USD)], end, values=["PRICE"])

    call = quotes.calls[0]
    assert call["freq"] == "MI10"
    span = pd.Timestamp(call["end"]) - pd.Timestamp(call["start"])
    assert span <= MAX_SPAN["MI10"]
    assert span == datetime.timedelta(days=20), f"a 20-day MI10 lookback was clamped to {span}"


# ------------------------------------------------------------------ #
#        the pricer is dated by the quote it is PRICED FROM          #
# ------------------------------------------------------------------ #

_REF_META = {
    "cusip": "91282CNJ6",
    "issue_date": "2025-06-30",
    "maturity_date": "2032-06-30",
    "cpn": 4.0,
}


def _lagging_price_quote(*, price_end="2026-08-04", rest_end="2026-08-06"):
    """A response where PRICE stopped printing before the other values did.

    The real shape of an illiquid bond: Citi keeps publishing a yield, a duration,
    a spread and a DV01 off its own curve while the last actual PRICE print is days
    old. Every fixture in the first version of this file gave all values one shared
    index, which is exactly why the misdating was invisible to the suite.
    """
    values = ["YIELD", "DURATION", "SPREAD_TSY", "DV01"]
    served = _daily_series(ISIN_WITH_ASW_USD, 99.0, values=["PRICE"], end=price_end)
    served.update(_daily_series(ISIN_WITH_ASW_USD, 99.0, values=values, end=rest_end))
    quotes, _ = _quotes_over(served)
    return CitiVeloBondFetcher(quotes=quotes).fetch(
        [resolve_bond(ISIN_WITH_ASW_USD)],
        datetime.date(2026, 8, 6),
        values=["PRICE"] + values,
    )[ISIN_WITH_ASW_USD]


def test_the_reference_date_is_prices_own_stamp_not_the_newest_constituent():
    """The pricer is dated by the quote it is PRICED FROM.

    ``as_of`` is the newest stamp across every served value, which is the right
    label for the RESPONSE. It is the wrong date for the pricer: the clean price is
    ``stamps['PRICE']``'s number, and handing QuantLib or rateslib a two-day-newer
    reference date makes both apply two extra days of accrual to it. FRB_YTM,
    FRB_MOD_DURATION, FRB_DV01, FRB_NPV and every spline residual built on that
    pricer are then wrong, with a provenance book that says the number is fine.
    """
    quote = _lagging_price_quote()

    assert quote.stamps["PRICE"].date() == datetime.date(2026, 8, 4)
    assert quote.stamps["YIELD"].date() == datetime.date(2026, 8, 6)
    assert quote.market_date == datetime.date(2026, 8, 6), "the response's own newest label"
    assert quote.price_lag == datetime.timedelta(days=2)
    assert quote.market_date_of("PRICE") == datetime.date(2026, 8, 4)

    args = build_pricer_args(
        quote, backend="QL", ref_meta=_REF_META, max_price_lag=datetime.timedelta(days=3)
    )
    assert args["clean_price"] == pytest.approx(99.0)
    assert args["reference_date"] == "2026-08-04", "priced off the 08-04 print, so dated 08-04"


def test_a_price_staler_than_the_rest_of_the_response_is_refused_by_default():
    """A several-day-stale price is worse than no number, so the default refuses.

    The threshold is a deliberate choice with a cost: see
    ``DEFAULT_MAX_PRICE_LAG``. It is calendar-based, so a Friday PRICE beside a
    Monday YIELD (3 calendar days, 1 business day) also refuses. Raising
    ``max_price_lag`` accepts the quote and the number is still dated by PRICE.
    """
    quote = _lagging_price_quote()
    with pytest.raises(V.StalePriceError, match="2 days"):
        build_pricer_args(quote, backend="QL", ref_meta=_REF_META)

    # And it is a NoQuotedPriceError, so the MDP branch drops the one bond rather
    # than losing the basket - the same treatment as a bond with no PRICE at all.
    assert issubclass(V.StalePriceError, V.NoQuotedPriceError)


def test_the_constituent_disagreement_is_recorded_even_when_it_is_accepted():
    """Recorded unconditionally, not only when it trips the threshold. A consumer
    that wants a tighter rule than this module's needs the number, not a boolean."""
    quote = _lagging_price_quote()
    meta = build_pricer_args(
        quote, backend="QL", ref_meta=_REF_META, max_price_lag=datetime.timedelta(days=3)
    )["meta_data"]

    assert meta["citivelo_price_lag_seconds"] == pytest.approx(2 * 86_400.0)
    assert meta["citivelo_constituent_spread_seconds"] == pytest.approx(2 * 86_400.0)
    assert meta["citivelo_market_date"] == "2026-08-04", "the date the pricer is on"
    assert meta["citivelo_basket_market_date"] == "2026-08-06", "the response's own label"


def test_a_response_whose_values_agree_is_dated_by_the_day_they_agree_on():
    """The regression guard: the common case must be unchanged."""
    quote = _lagging_price_quote(price_end="2026-08-06")
    assert quote.price_lag == datetime.timedelta(0)
    args = build_pricer_args(quote, backend="QL", ref_meta=_REF_META)
    assert args["reference_date"] == "2026-08-06"
    assert args["meta_data"]["citivelo_price_lag_seconds"] == pytest.approx(0.0)


def test_the_meta_timestamp_is_naive_so_carry_roll_reads_an_eod_pricer_as_eod():
    """``meta['timestamp']`` is the field ``carry_roll._infer_pricing_timestamp``
    reads, and it branches on ``tzinfo is not None`` BEFORE its midnight-means-date
    rule. Every other FixedRateBondsMDP branch writes a naive stamp; an
    offset-bearing one out of this branch alone makes an EOD pricer classify as
    intraday. The wire offset is kept, one key over, where no classifier reads it.
    """
    quote = _lagging_price_quote(price_end="2026-08-06")
    meta = build_pricer_args(quote, backend="QL", ref_meta=_REF_META)["meta_data"]

    assert meta["timestamp"] == "2026-08-06T00:00:00"
    assert pd.Timestamp(meta["timestamp"]).tzinfo is None
    assert meta["citivelo_price_timestamp"].endswith("-04:00"), "the offset is kept, just not there"
    assert meta["citivelo_as_of"].endswith("-04:00")


# ------------------------------------------------------------------ #
#            a transport failure is not an empty market              #
# ------------------------------------------------------------------ #


def test_a_dead_transport_raises_rather_than_reporting_an_empty_market():
    """Excel going away mid-run must not be reported as "Citi returned no rows".

    ``fetch_windowed`` catches a COM error per window so one bad window cannot end
    a backfill, which means a wholly dead transport reaches this module as a list
    of failed windows and an empty frame. Classifying that as ``empty`` tells the
    caller to widen the window - advice that cannot work - and, through the MDP
    branch's per-bond ``continue``, turns a 300-name warm during an Excel hiccup
    into a silently partial dict with no exception anywhere.
    """
    quotes = _DisconnectedQuotes()
    fetcher = CitiVeloBondFetcher(quotes=quotes)
    with pytest.raises(BondQuoteTransportError, match="disconnected from its clients"):
        fetcher.fetch(
            [resolve_bond(ISIN_WITH_ASW_USD)],
            datetime.datetime(2026, 8, 6, 14, 30),
            values=["PRICE"],
        )
    assert quotes._client.windows_pushed >= 1, "the failure has to come from a real attempt"


def test_an_add_in_that_is_not_signed_in_is_not_reported_as_an_empty_market(resolutions):
    """The EOD half of the same rule, through the real client.

    ``udf_registered=False`` is a running Excel that is not signed in to Velocity:
    every ``CV*`` formula resolves to ``#NAME?``. ``CitiVeloQuotes.series``
    documents that a failed tag is ABSENT and the reason is on
    ``client.last_failures()``; this module used to never read it, so an
    unentitled or rejected tag became "empty window" too.
    """
    data = FakeVelocityData(series={}, udf_registered=False)
    app = FakeExcelApp(data=data, pending_reads=0)
    workbook = app.Workbooks.Add()
    client = CitiVelocityExcelClient(app=app, workbook=workbook, drain_seconds=0.0)
    client._ws = workbook.Worksheets(1)
    quotes = CitiVeloQuotes(client=client, cache=False)

    with pytest.raises(BondQuoteTransportError, match=r"#NAME\?"):
        CitiVeloBondFetcher(quotes=quotes).fetch(
            resolutions, datetime.date(2026, 8, 6), values=["PRICE"]
        )


def test_one_rejected_tag_is_reported_as_failed_and_the_rest_still_serve(resolutions):
    """``CVTSHIST`` degrades per column, so one bad tag must cost its own value and
    nothing else - and that value must not be called ``empty``, whose documented
    fix is "widen the window"."""
    served = {}
    for isin, base in ((ISIN_WITH_ASW_USD, 99.0), (ISIN_WITHOUT_ASW_USD, 88.0)):
        served.update(_daily_series(isin, base, values=["PRICE", "SPREAD_TSY"]))
    bad = f"RATES.BOND.{ISIN_WITH_ASW_USD}.SPREAD_TSY"
    data = FakeVelocityData(series=served, bad_tags={bad})
    app = FakeExcelApp(data=data, pending_reads=0)
    workbook = app.Workbooks.Add()
    client = CitiVelocityExcelClient(app=app, workbook=workbook, drain_seconds=0.0)
    client._ws = workbook.Worksheets(1)
    quotes = CitiVeloQuotes(client=client, cache=False)

    quote = CitiVeloBondFetcher(quotes=quotes).fetch(
        resolutions, datetime.date(2026, 8, 6), values=["PRICE", "SPREAD_TSY"]
    )[ISIN_WITH_ASW_USD]

    assert quote.get("PRICE") == pytest.approx(99.0), "one bad column must not cost the others"
    assert "SPREAD_TSY" in quote.failed
    assert "SPREAD_TSY" not in quote.empty, "a rejected tag is not an empty window"
    assert "bad tag" in quote.failed["SPREAD_TSY"]
    assert quote.coverage_book()["failed"] == ["SPREAD_TSY"]


def test_an_empty_window_is_still_empty_and_not_a_transport_failure(resolutions):
    """The regression guard on the other side. ``empty`` is a real, normal, measured
    outcome (OAS over a short window) and it must survive the new classification -
    otherwise every widen-the-window case turns into a false transport alarm."""
    fetcher, _ = _eod_fetcher(resolutions)
    quote = fetcher.fetch(
        resolutions, datetime.date(2026, 8, 6), values=_COVERAGE_VALUES
    )[ISIN_WITH_ASW_USD]
    assert "OAS" in quote.empty
    assert quote.failed == {}


# ------------------------------------------------------------------ #
#          an unswept bond is not a bond Citi does not serve         #
# ------------------------------------------------------------------ #

#: One of the fifteen universe ISINs with ZERO validated tags. Re-derived from the
#: harvest: thirteen Canadians (CND...) and two Italians (IT0005680753,
#: IT0005707689) - the validation sweep covered 2,147 of the 2,162 ISINs, and these
#: are the fifteen it missed.
ISIN_NEVER_SWEPT = "CND0000002K8"


def test_a_bond_the_sweep_never_covered_is_asked_rather_than_declared_unserved(universe):
    """``available_values`` returning ``[]`` is not evidence of anything.

    Its own docstring says so: "An empty list is NOT proof the bond has no data:
    the sweep covered 2,147 of the 2,162 ISINs." Treating it as proof turned an
    incomplete sweep into a positive coverage claim - zero tags built, every value
    reported ``unavailable``, and a message asserting "Citi does not serve X for
    this bond" about a bond nobody ever asked the wire about.
    """
    resolution = resolve_bond(ISIN_NEVER_SWEPT, universe=universe)
    assert resolution.available_values == (), "the premise: this bond has no validated tags"

    quotes = _RecordingQuotes(pd.DataFrame())
    fetcher = CitiVeloBondFetcher(quotes=quotes, offline=True)
    entry = fetcher.plan([resolution], values=["PRICE", "SPREAD_TSY"])[ISIN_NEVER_SWEPT]

    assert entry["validated"] is False
    assert entry["unavailable"] == (), "nothing is KNOWN to be unserved for this bond"
    assert set(entry["tags"]) == {"PRICE", "SPREAD_TSY"}, "so it is asked, not assumed away"


def test_an_unswept_bonds_quote_says_its_coverage_was_never_validated(universe):
    resolution = resolve_bond(ISIN_NEVER_SWEPT, universe=universe)
    quotes = _RecordingQuotes(pd.DataFrame())
    quote = CitiVeloBondFetcher(quotes=quotes, offline=True).fetch(
        [resolution], datetime.date(2026, 8, 6), values=["PRICE"]
    )[ISIN_NEVER_SWEPT]

    assert quote.coverage_validated is False
    assert quote.coverage_book()["validated"] is False
    assert not V.coverage_is_validated({V.COVERAGE_KEY: quote.coverage_book()})
    # And a bond that WAS swept still says so, or the flag means nothing.
    swept = CitiVeloBondFetcher(quotes=_RecordingQuotes(pd.DataFrame()), offline=True).fetch(
        [resolve_bond(ISIN_WITH_ASW_USD, universe=universe)],
        datetime.date(2026, 8, 6), values=["PRICE"],
    )[ISIN_WITH_ASW_USD]
    assert swept.coverage_validated is True


# ------------------------------------------------------------------ #
#                    lifecycle: whose reader is it                   #
# ------------------------------------------------------------------ #


def test_close_does_not_swap_an_injected_reader_for_a_live_one():
    """``close()`` used to null ``_quotes`` unconditionally, including when the
    caller injected it. The next ``quotes()`` then built a brand-new
    ``CitiVeloQuotes(offline=False)`` whose first cache miss calls
    ``CitiVelocityExcelClient.connect()`` - so a hermetic fetcher silently became
    one that opens a live Excel, and ``_owns_quotes`` being False meant nothing
    ever closed it either (this package has a recorded 62-workbook leak).
    """
    injected = _RecordingQuotes(pd.DataFrame())
    with CitiVeloBondFetcher(quotes=injected, offline=True) as fetcher:
        pass
    assert fetcher.quotes() is injected


def test_an_injected_reader_that_declares_itself_offline_is_believed():
    """``offline`` selects the intraday TRANSPORT, and an injected reader has its
    own flag. Unreconciled, ``CitiVeloBondFetcher(quotes=CitiVeloQuotes(offline=True))``
    - the natural spelling, with the kwarg omitted - takes the ONLINE path and
    ``client()`` raises inside what the caller believes is an offline fetch.
    """
    end = datetime.datetime(2026, 8, 6, 14, 30)
    idx = pd.date_range(end - datetime.timedelta(days=8), end, freq="1min", inclusive="left")
    frame = pd.DataFrame({f"RATES.BOND.{ISIN_WITH_ASW_USD}.PRICE": 99.0}, index=idx)
    quotes = _OfflineQuotes(frame)

    fetcher = CitiVeloBondFetcher(quotes=quotes)  # offline NOT passed
    assert fetcher.offline is True

    fetcher.fetch([resolve_bond(ISIN_WITH_ASW_USD)], end, values=["PRICE"])
    assert len(quotes.calls) == 1, "the offline transport, not fetch_windowed"
    span = pd.Timestamp(quotes.calls[0]["end"]) - pd.Timestamp(quotes.calls[0]["start"])
    assert span <= MAX_SPAN["MI01"]


def test_an_offline_flag_that_contradicts_the_injected_reader_is_refused():
    """The other direction: ``offline=True`` over a live-capable reader still reaches
    Excel on any cache miss, which defeats the flag's stated purpose. Neither
    mismatch is silently resolved."""
    with pytest.raises(ValueError, match="offline"):
        CitiVeloBondFetcher(quotes=_OfflineQuotes(pd.DataFrame()), offline=False)


def test_the_quotes_reader_publishes_its_own_offline_state():
    """The reconciliation reads a documented property, not a private attribute."""
    assert CitiVeloQuotes(client=None, cache=False, offline=True).offline is True
    assert CitiVeloQuotes(client=None, cache=False).offline is False

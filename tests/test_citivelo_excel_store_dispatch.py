"""Which CurveStore loader a citivelo_excel request is routed to.

The trap being pinned: ``pandas.Timestamp`` subclasses ``datetime.datetime``,
which subclasses ``datetime.date``. A dispatch that tests ``isinstance(ts, date)``
first therefore swallows EVERY intraday request into the end-of-day branch, and
the symptom is not an error - it is a curve for the wrong time of day, which
prices plausibly and is wrong.

There are three routes and they must stay distinguishable:

* an aware ``datetime``          -> the minute store (``-CITIVELOEXCELMIN``)
* a bare ``date``                -> the EOD store  (``-CITIVELOEXCEL``)
* a midnight ``pd.Timestamp``    -> the EOD store, because midnight-means-EOD is
  how ``resolve_request`` reads the common spelling of "that day"

and a miss in either store must fall through to building from live quotes rather
than raising.
"""

from __future__ import annotations

import datetime
import zoneinfo

import pandas as pd
import pytest

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

ET = zoneinfo.ZoneInfo("America/New_York")
CURVE = "USD-SOFR-1D"


@pytest.fixture()
def routed(monkeypatch):
    """Record which loader ran, and stop before any Excel or store I/O."""
    calls = []

    monkeypatch.setattr(
        IRSwapsMDP,
        "_load_citivelo_excel_minute_store_point",
        lambda self, *, curve_name, timestamp, **kw: calls.append("minute") or "MINUTE",
    )
    monkeypatch.setattr(
        IRSwapsMDP,
        "_load_citivelo_excel_curve_store_point",
        lambda self, *, curve_name, trading_date, **kw: calls.append("eod") or "EOD",
    )
    return calls


@pytest.fixture()
def mdp():
    return IRSwapsMDP(source="citivelo_excel_rl")


def _build(mdp, timestamp):
    return mdp._build_citivelo_excel_curve(curve_name=CURVE, timestamp=timestamp, kwargs={})


def test_an_aware_datetime_goes_to_the_minute_store(mdp, routed):
    got = _build(mdp, datetime.datetime(2026, 8, 5, 10, 30, tzinfo=ET))
    assert routed == ["minute"]
    assert got == "MINUTE"


def test_a_bare_date_goes_to_the_eod_store(mdp, routed):
    got = _build(mdp, datetime.date(2026, 8, 5))
    assert routed == ["eod"]
    assert got == "EOD"


def test_a_midnight_timestamp_goes_to_the_eod_store(mdp, routed):
    """``pd.Timestamp("2026-08-05")`` is how people spell "that day"."""
    got = _build(mdp, pd.Timestamp("2026-08-05"))
    assert routed == ["eod"], "midnight must read as EOD, not as 00:00 intraday"
    assert got == "EOD"


def test_a_naive_intraday_timestamp_still_goes_to_the_minute_store(mdp, routed):
    got = _build(mdp, pd.Timestamp("2026-08-05 10:30"))
    assert routed == ["minute"]
    assert got == "MINUTE"


def test_the_two_routes_are_actually_different_loaders(mdp, routed):
    """Guards against both branches collapsing onto one loader."""
    _build(mdp, datetime.datetime(2026, 8, 5, 10, 30, tzinfo=ET))
    _build(mdp, datetime.date(2026, 8, 5))
    assert routed == ["minute", "eod"]


@pytest.mark.parametrize("flag", ["force_refresh", "ignore_cache", "no_curve_store"])
def test_the_store_is_bypassed_when_the_caller_asks_for_fresh_data(mdp, monkeypatch, flag):
    """A caller who asked to skip the cache must not be served from it."""
    calls = []
    monkeypatch.setattr(
        IRSwapsMDP,
        "_load_citivelo_excel_minute_store_point",
        lambda self, **kw: calls.append("minute") or "MINUTE",
    )
    monkeypatch.setattr(
        IRSwapsMDP,
        "_load_citivelo_excel_curve_store_point",
        lambda self, **kw: calls.append("eod") or "EOD",
    )
    # Stop before Excel: the fetcher is what the bypass falls through TO.
    monkeypatch.setattr(
        IRSwapsMDP,
        "_get_citivelo_excel_fetcher",
        lambda self, **kw: (_ for _ in ()).throw(RuntimeError("reached the live path")),
    )
    with pytest.raises(RuntimeError, match="reached the live path"):
        mdp._build_citivelo_excel_curve(
            curve_name=CURVE,
            timestamp=datetime.datetime(2026, 8, 5, 10, 30, tzinfo=ET),
            kwargs={flag: True},
        )
    assert calls == [], f"{flag} did not bypass the CurveStore"


def test_a_store_miss_falls_through_to_the_live_build(mdp, monkeypatch):
    """``None`` from the loader means cold, not broken."""
    monkeypatch.setattr(
        IRSwapsMDP, "_load_citivelo_excel_minute_store_point", lambda self, **kw: None
    )
    monkeypatch.setattr(
        IRSwapsMDP,
        "_get_citivelo_excel_fetcher",
        lambda self, **kw: (_ for _ in ()).throw(RuntimeError("reached the live path")),
    )
    with pytest.raises(RuntimeError, match="reached the live path"):
        _build(mdp, datetime.datetime(2026, 8, 5, 10, 30, tzinfo=ET))


# -- curve definitions must be registered on the STORE path too ---------


def test_non_usd_curve_names_are_registered_without_building_a_fetcher(monkeypatch):
    """The store fast paths bypass the fetcher - and that is where register() was.

    Nineteen of the twenty curve names exist nowhere else in this repo. A curve
    reconstructed from the CurveStore carries its name as ``reference_key``, so
    pricing it needs the definition even though no fetcher was built. Before the
    fix, USD-SOFR-1D worked (the repo already defines it) and EUR/GBP/CAD/JPY
    raised KeyError on the curve name after silently falling back to
    act360/nyc/mf.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL import curve_definitions as CD
    from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import (
        RATESLIB_CURVE_DEFINITIONS as DEFS,
    )

    names = ("EUR-ESTR-1D", "GBP-SONIA-1D", "CAD-CORRA-1D", "JPY-TONAR-1D-LCH")
    for name in names:
        DEFS.pop(name, None)
    # register() is idempotent via a cached report, so a fresh process is what
    # this must model - otherwise the guard short-circuits and nothing re-adds
    # the names the test just removed.
    CD._REPORT = None

    # The FETCHER also registers, so it has to be unreachable or this test cannot
    # tell the two apart - which it could not, until a mutation run showed it
    # passing with the registration removed.
    monkeypatch.setattr(
        IRSwapsMDP,
        "_get_citivelo_excel_fetcher",
        lambda self, **kw: (_ for _ in ()).throw(RuntimeError("fetcher must not be built")),
    )
    monkeypatch.setattr(
        IRSwapsMDP, "_load_citivelo_excel_curve_store_point", lambda self, **kw: None
    )

    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    with pytest.raises(RuntimeError, match="fetcher must not be built"):
        mdp._build_citivelo_excel_curve(
            curve_name="EUR-ESTR-1D",
            timestamp=datetime.date(2026, 8, 5),
            kwargs={},
        )

    for name in names:
        assert name in DEFS, f"{name} was never registered, so it cannot be priced"

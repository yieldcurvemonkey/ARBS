r"""The INTRADAY Velocity FRB read path warms the range once, then reads offline.

The defect these pin
--------------------
``FixedRateBondsMDP._citivelo_prefetch_range`` used to warm ``DAILY`` and nothing
else, so an INTRADAY range prefetched nothing. Every per-minute point then took
``CitiVeloBondFetcher._fetch_frame``'s ONLINE branch -
``windowed.fetch_windowed`` - which takes the COM client directly and therefore
neither reads nor writes the tag cache. One live Excel round trip per minute bar,
with a worksheet pushed and dropped for each: measured at **593 s for 60 points,
500 s of it in ``time.sleep``** waiting for cells to settle, across 61 fetches
for a range that is one warm.

Measured again through this file's counting vendor, 60 one-minute points:
**60 vendor round trips and 60 worksheets before, 1 and 0 after**, with every
served value identical.

What is asserted, and why each one is separately necessary
-----------------------------------------------------------
``once``
    The warm happens once for a whole range. Counted at the vendor seam, which
    is the only place the saving is real - counting calls to ``prefetch`` would
    pass while every point still opened a workbook.
``under the cliff``
    Every request is at most SIX days wide. ``CVTSHIST`` silently downsamples by
    requested span and the ``MI01`` threshold is measured at exactly 6 days: a
    7-day request returns 10-minute rows in a block that looks identical. The
    bound is written here as ``timedelta(days=6)`` rather than as
    ``MAX_SPAN["MI01"]`` on purpose - asserting against the constant the code
    reads would pass no matter what that constant said.
``does not reach the client``
    After the warm, a point is served from the cache. This is the assertion the
    speed-up actually is.
``the values are the ones the vendor served``
    Offline-and-empty is fast, plausible and wrong: an offline read of a cache
    that was never warmed does not raise, it returns an absent column, which
    downstream reads as "Citi served nothing in this window". Every test that
    asserts a count also asserts the numbers.
``an empty warm does NOT switch the reads offline``
    The flag that turns the per-point reads offline is data-bearing, not
    exception-free, for exactly that reason.
``both transports resolve the same instant``
    ``fetch_windowed`` fetches ``[start, end)`` - it steps each window's upper
    bound back a minute so adjacent windows do not both return the shared
    instant - so an as-of read for 10:00 asked Citi for ``..09:59`` and could
    never see the 10:00 print, while the cached branch could. Measured on
    US912810EX29 at 2026-08-07 10:00 (09:58's print against 10:00's) and on 27 of
    60 minute bars in one hour. Now that whether a point reads online or offline
    depends on whether the warm succeeded, the two MUST agree.

Hermetic: no Excel, no network, no real cache directory.
"""

from __future__ import annotations

import datetime
import threading
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
import pytest

from MDP.CitiVelocityExcel.bonds.fetcher import (
    INTRADAY_BOND_VALUES,
    CitiVeloBondFetcher,
    default_values_for_mode,
)
from MDP.CitiVelocityExcel.bonds.resolution import resolve_bond
from MDP.CitiVelocityExcel.bonds.universe import BondUniverse
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
from MDP.CitiVelocityExcel.windowed import warm_windows
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

#: The measured ``MI01`` downsampling cliff, written out rather than imported.
#: See the module docstring: importing ``MAX_SPAN`` would make every bound
#: assertion in this file a tautology.
MI01_CLIFF = datetime.timedelta(days=6)

CUSIP = "91282CNJ6"
ISIN = "US91282CNJ61"

#: A weekday well inside the window the fake vendor serves.
DAY = datetime.date(2026, 8, 6)
#: What the vendor actually publishes for this bond. Two of the seven values an
#: intraday request asks for; the other five come back absent, which is the
#: ``empty`` classification and not a failure.
SERVED_VALUES = ("PRICE", "YIELD")


# ------------------------------------------------------------------ #
#                          the counting vendor                       #
# ------------------------------------------------------------------ #


class CountingVendor:
    """A ``CitiVelocityExcelClient`` stand-in that counts what it is asked.

    Serves a distinct value per MINUTE, so a point that resolves the wrong
    instant is a wrong number rather than a coincidence. Reproduces the add-in's
    silent span-driven downsampling, so a request that crosses the cliff comes
    back coarse instead of raising - which is the failure mode the bound exists
    to prevent, and it must be reproducible for the bound to be testable.
    """

    #: Prints run from here, one a minute, for three days.
    ORIGIN = datetime.datetime(2026, 8, 4, 0, 0)
    N_MINUTES = 3 * 24 * 60

    def __init__(self, *, serve: Sequence[str] = SERVED_VALUES, empty: bool = False):
        self._serve = tuple(serve)
        self._empty = bool(empty)
        self._lock = threading.RLock()
        self.calls: List[Dict[str, Any]] = []
        self.sheets_pushed = 0

    # -- the series it publishes ----------------------------------------

    def _series(self, tag: str) -> Optional[pd.Series]:
        value = tag.rsplit(".", 1)[-1]
        if value not in self._serve:
            return None
        idx = pd.date_range(self.ORIGIN, periods=self.N_MINUTES, freq="1min")
        base = 100.0 if value == "PRICE" else 4.0
        # A distinct number per minute: the minute index in ten-thousandths.
        return pd.Series(base + pd.RangeIndex(len(idx)) * 1e-4, index=idx, name=tag)

    @classmethod
    def price_at(cls, when: datetime.datetime) -> float:
        """What ``PRICE`` is at ``when``, computed the same way the vendor does."""
        minutes = int((when - cls.ORIGIN).total_seconds() // 60)
        return 100.0 + minutes * 1e-4

    # -- the client surface ---------------------------------------------

    def fetch_timeseries(
        self,
        tags: Sequence[str],
        freq: str = "DAILY",
        *,
        period: Optional[str] = None,
        start: Any = None,
        end: Any = None,
        price_point: str = "CLOSE",
        strict: bool = False,
        timeout: Optional[float] = None,
    ) -> Dict[str, pd.Series]:
        lo = None if start is None else pd.Timestamp(start)
        hi = None if end is None else pd.Timestamp(end)
        with self._lock:
            self.calls.append({"freq": str(freq), "start": lo, "end": hi,
                               "span": None if (lo is None or hi is None) else hi - lo})
        if self._empty:
            return {}

        out: Dict[str, pd.Series] = {}
        for tag in dict.fromkeys(str(t).strip() for t in tags):
            s = self._series(tag)
            if s is None:
                continue
            if lo is not None:
                s = s[s.index >= lo]
            if hi is not None:
                s = s[s.index <= hi]
            if s.empty:
                continue
            if lo is not None and hi is not None and (hi - lo) > MI01_CLIFF:
                # The add-in's measured behaviour: coarser rows, no warning.
                s = s.resample("10min").last().dropna()
            out[tag] = s
        return out

    def last_failures(self) -> Dict[str, str]:
        return {}

    def push_window_sheet(self, name: str) -> str:
        with self._lock:
            self.sheets_pushed += 1
        return name

    def drop_window_sheet(self) -> bool:
        return True

    def close(self) -> None:
        pass

    # -- reporting -------------------------------------------------------

    @property
    def round_trips(self) -> int:
        return len(self.calls)

    def spans(self) -> List[datetime.timedelta]:
        return [c["span"].to_pytimedelta() for c in self.calls if c["span"] is not None]


class RecordingQuotes:
    """Records the ``frame`` requests ``warm_windows`` issues, and serves nothing.

    Used for the pure bounds test, where what came back does not matter and the
    request bounds are the whole point.
    """

    offline = False

    def __init__(self):
        self.requests: List[Dict[str, Any]] = []

    def frame(self, tags, freq="DAILY", **kwargs) -> pd.DataFrame:
        self.requests.append({"tags": list(tags), "freq": freq, **kwargs})
        return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))


# ------------------------------------------------------------------ #
#                               fixtures                             #
# ------------------------------------------------------------------ #


@pytest.fixture()
def cache_dir(monkeypatch, tmp_path):
    """Point the Velocity tag cache at a temp directory.

    Not a nicety: without it every one of these tests writes minute parquets into
    the developer's real warm cache, and a later real read is answered with
    synthetic numbers.
    """
    root = tmp_path / "citivelo_excel"
    monkeypatch.setattr("MDP.CitiVelocityExcel.cache.default_cache_dir", lambda: root)
    return root


@pytest.fixture()
def vendor(monkeypatch, cache_dir):
    """One counting vendor behind every ``client()`` in the process."""
    from MDP.CitiVelocityExcel import com_client as _cc

    client = CountingVendor()
    monkeypatch.setattr(
        _cc.CitiVelocityExcelClient, "connect", staticmethod(lambda *a, **k: client)
    )
    return client


@pytest.fixture()
def resolution():
    return resolve_bond(CUSIP, universe=BondUniverse.from_catalog(country="USA", asset_type="GOVT"))


@pytest.fixture()
def wired_mdp(monkeypatch, tmp_path, cache_dir):
    """A ``FixedRateBondsMDP`` on the Velocity source with everything but the
    Velocity read path stubbed out.

    ``update_reference_data`` really downloads fiscaldata, and ``force_refresh``
    makes it do so ONCE PER TIMESTAMP; the pricer cache is a DiskCache in the
    user's home directory. Neither is under test here.
    """
    from Caching.DiskCacheMixin import DiskCacheMixin

    ref = pd.DataFrame(
        [{
            "cusip": CUSIP, "oi": "7-Year",
            "issue_date": datetime.date(2025, 6, 30),
            "maturity_date": datetime.date(2032, 6, 30), "cpn": 4.0,
        }]
    )
    monkeypatch.setattr(
        "MDP.FixedRateBonds.reference_data_cache.ust_reference_data.update_reference_data",
        lambda source, source_kwargs=None, force_refresh=False: ref.copy(),
    )
    monkeypatch.setattr(DiskCacheMixin, "CACHE_ROOT", str(tmp_path / "diskcache"))
    return FixedRateBondsMDP(source="USTS_CITIVELO-QL")


def _minutes(hour: int, minute: int, n: int) -> List[datetime.datetime]:
    first = datetime.datetime(DAY.year, DAY.month, DAY.day, hour, minute)
    return [first + datetime.timedelta(minutes=i) for i in range(n)]


# ------------------------------------------------------------------ #
#                    the shared window-bounded warm                  #
# ------------------------------------------------------------------ #


def test_warm_windows_holds_every_request_under_the_measured_cliff():
    """A month of minutes is many requests, none of them over six days.

    This is the assertion that catches a widened bound: ``CVTSHIST`` answers a
    7-day ``MI01`` request with 10-minute rows and no error, so nothing else in
    the stack would notice.
    """
    quotes = RecordingQuotes()
    start = datetime.datetime(2026, 7, 1, 0, 0)
    end = datetime.datetime(2026, 7, 31, 0, 0)

    windows = warm_windows(quotes, ["RATES.BOND.X.PRICE"], "MI01", start, end)

    assert len(windows) == len(quotes.requests)
    assert len(windows) >= 5, "a 30-day range cannot be one sub-cliff request"
    for window in windows:
        assert window.span <= MI01_CLIFF, f"{window} crosses the measured MI01 cliff"
    for request in quotes.requests:
        assert request["end"] - request["start"] <= MI01_CLIFF


def test_warm_windows_covers_the_whole_range_without_a_hole():
    quotes = RecordingQuotes()
    start = datetime.datetime(2026, 7, 1, 0, 0)
    end = datetime.datetime(2026, 7, 31, 0, 0)

    windows = sorted(warm_windows(quotes, ["T"], "MI01", start, end), key=lambda w: w.start)

    assert windows[0].start == start
    assert windows[-1].end == end
    for earlier, later in zip(windows, windows[1:]):
        assert later.start <= earlier.end, "a gap between windows loses data silently"


def test_warm_windows_does_not_chunk_a_frequency_with_no_measured_cliff():
    """``DAILY`` has no span threshold, so chunking it would only cost round
    trips against a limit that does not exist."""
    quotes = RecordingQuotes()
    windows = warm_windows(
        quotes, ["T"], "DAILY", datetime.date(2020, 1, 1), datetime.date(2026, 1, 1)
    )
    assert len(windows) == 1
    assert len(quotes.requests) == 1


# ------------------------------------------------------------------ #
#                    the warm asks for what the read asks for        #
# ------------------------------------------------------------------ #


def test_the_warm_requests_every_tag_the_per_point_read_will_ask_for(vendor, resolution):
    """Prefetch and fetch must agree on the value set.

    They cannot be checked by the "no client call" test: on the offline path a
    value the warm never fetched is not an error, it is an absent column. So the
    two sets are compared directly, and both come from
    ``default_values_for_mode``.
    """
    when = datetime.datetime(DAY.year, DAY.month, DAY.day, 10, 0)

    fetcher = CitiVeloBondFetcher()
    result = fetcher.prefetch([resolution], when, when, mode="intraday")

    read_plan = fetcher.plan([resolution], values=default_values_for_mode("intraday"))
    read_tags = {t for entry in read_plan.values() for t in entry["tags"].values()}

    assert set(result.tags) >= read_tags
    assert set(default_values_for_mode("intraday")) == set(INTRADAY_BOND_VALUES)
    assert result.ok


def test_a_warm_that_served_nothing_is_not_reported_as_ok(monkeypatch, cache_dir, resolution):
    """``ok`` is data-bearing. A warm that raised nothing and cached nothing must
    not let its caller switch the reads offline."""
    from MDP.CitiVelocityExcel import com_client as _cc

    empty = CountingVendor(empty=True)
    monkeypatch.setattr(
        _cc.CitiVelocityExcelClient, "connect", staticmethod(lambda *a, **k: empty)
    )
    when = datetime.datetime(DAY.year, DAY.month, DAY.day, 10, 0)

    result = CitiVeloBondFetcher().prefetch([resolution], when, when, mode="intraday")

    assert result.tags, "the plan itself should still have produced tags"
    assert not result.served
    assert not result.ok


# ------------------------------------------------------------------ #
#                   the read path, end to end on the MDP             #
# ------------------------------------------------------------------ #


def test_an_intraday_range_warms_once_and_then_reads_from_cache(wired_mdp, vendor):
    """The whole point: 30 minute bars, ONE vendor round trip, no worksheets."""
    points = _minutes(10, 0, 30)

    out = wired_mdp.bulk_get_data(timestamps=points, cusips=[CUSIP], max_workers=1)

    assert vendor.round_trips == 1, (
        f"{vendor.round_trips} vendor calls for {len(points)} points - the range "
        f"was not warmed, so every point fetched for itself"
    )
    assert vendor.sheets_pushed == 0, (
        "a pushed worksheet means windowed.fetch_windowed ran, which bypasses the "
        "tag cache in both directions"
    )
    assert set(out) == set(points)
    for point in points:
        pricer = out[point][CUSIP]
        assert pricer.clean_price() == pytest.approx(CountingVendor.price_at(point)), (
            "an offline read of an unwarmed cache is empty, not an error - so the "
            "numbers have to be checked, not just the call count"
        )


def test_every_vendor_request_in_a_range_read_stays_under_the_cliff(wired_mdp, vendor):
    points = _minutes(10, 0, 30)

    wired_mdp.bulk_get_data(timestamps=points, cusips=[CUSIP], max_workers=1)

    assert vendor.spans(), "no bounded request was issued at all"
    for span in vendor.spans():
        assert span <= MI01_CLIFF, (
            f"a {span} request at MI01 is over the measured 6-day cliff: the add-in "
            f"would serve 10-minute rows in a block that looks identical"
        )


def test_a_failed_warm_leaves_the_old_per_point_behaviour_in_place(
    monkeypatch, wired_mdp, cache_dir
):
    """A warm that cached nothing must NOT leave every point offline-and-empty.

    The regression this guards is the attractive one: switching the reads offline
    on "the prefetch did not raise" makes a broken warm produce a fast, complete,
    entirely empty timeseries.
    """
    from MDP.CitiVelocityExcel import com_client as _cc

    empty = CountingVendor(empty=True)
    monkeypatch.setattr(
        _cc.CitiVelocityExcelClient, "connect", staticmethod(lambda *a, **k: empty)
    )
    points = _minutes(10, 0, 4)

    wired_mdp.bulk_get_data(timestamps=points, cusips=[CUSIP], max_workers=1)

    assert empty.round_trips > len(points), (
        "the points went offline behind a warm that served nothing"
    )
    assert empty.sheets_pushed >= len(points)


# ------------------------------------------------------------------ #
#              the two transports resolve the same instant           #
# ------------------------------------------------------------------ #


def test_online_and_offline_resolve_the_same_print_at_the_requested_instant(
    vendor, resolution
):
    """Whether a point reads online or offline now depends on whether the warm
    succeeded, so the two must not disagree about the endpoint."""
    when = datetime.datetime(DAY.year, DAY.month, DAY.day, 10, 0)

    online = CitiVeloBondFetcher(values=["PRICE"]).fetch([resolution], when)[ISIN]
    CitiVeloBondFetcher(values=["PRICE"]).prefetch(
        [resolution], when, when, mode="intraday", values=["PRICE"]
    )
    offline = CitiVeloBondFetcher(values=["PRICE"], offline=True).fetch([resolution], when)[ISIN]

    assert online.stamps["PRICE"].replace(tzinfo=None) == when
    assert offline.stamps["PRICE"].replace(tzinfo=None) == when
    assert online.get("PRICE") == pytest.approx(CountingVendor.price_at(when))
    assert offline.get("PRICE") == pytest.approx(online.get("PRICE"))


# ------------------------------------------------------------------ #
#                    EOD is a different branch, unchanged            #
# ------------------------------------------------------------------ #


def test_an_eod_range_still_warms_daily_and_stays_online(monkeypatch, wired_mdp, cache_dir):
    """EOD has no equivalent gap and is deliberately not switched offline.

    ``_fetch_frame`` takes its CACHED branch whenever the frequency is ``DAILY``,
    whatever the offline flag says, so an EOD range is already served from disk
    after the warm. The flag would only stop it topping up the 21-day lookback
    head it legitimately needs, so this pins that it is not applied.

    Measured with every value served: five dates cost THREE vendor calls - the
    warm, one head top-up for the 21-day lookback, one tail top-up for the last
    day - and that is constant in the number of dates. No worksheet is ever
    pushed, which is the property that matters: a pushed sheet means
    ``fetch_windowed`` ran, and that is the transport that scales with N.
    """
    from MDP.CitiVelocityExcel import com_client as _cc

    daily = CountingVendor(serve=SERVED_VALUES)

    def _daily_series(self, tag):  # noqa: ANN001
        value = tag.rsplit(".", 1)[-1]
        if value not in SERVED_VALUES:
            return None
        idx = pd.date_range("2026-07-01", "2026-08-07", freq="D")
        base = 100.0 if value == "PRICE" else 4.0
        return pd.Series(base + pd.RangeIndex(len(idx)) * 1e-3, index=idx, name=tag)

    monkeypatch.setattr(CountingVendor, "_series", _daily_series)
    monkeypatch.setattr(
        _cc.CitiVelocityExcelClient, "connect", staticmethod(lambda *a, **k: daily)
    )

    dates = [datetime.date(2026, 8, 4), datetime.date(2026, 8, 5), datetime.date(2026, 8, 6)]
    out = wired_mdp.bulk_get_data(timestamps=dates, cusips=[CUSIP], max_workers=1)

    assert {c["freq"] for c in daily.calls} == {"DAILY"}
    assert daily.sheets_pushed == 0, (
        "EOD must never take the windowed transport - that is the one that costs "
        "a worksheet and a live round trip per point"
    )
    assert set(out) == set(dates)
    for date in dates:
        assert out[date][CUSIP].reference_date() == date

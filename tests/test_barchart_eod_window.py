"""The BarChart EOD (``queryeod``) window filter.

``queryeod`` bars are **date**-stamped -- no time of day, no timezone. Every caller in this repo
hands the fetcher a *timestamped* window instead, and two of them hand it a **timezone-aware** one
(``USTFuturesMDP._fetch_barchart_timeseries`` localizes 00:01 and 23:59 to America/Chicago). Comparing
those boundaries against the naive bar stamps produced two distinct failures, both measured:

1. a tz-aware boundary raises ``Invalid comparison between dtype=datetime64[ns] and datetime``.
   The raise happens *inside* the retry loop, so it was swallowed, re-fetched five times, and the
   call returned an **empty frame** rather than an error -- silent, and five wasted round trips.
2. a ``00:01`` start against a bar stamped ``00:00`` silently drops that whole day. So a naive fix
   that only makes the comparison legal turns "raises" into "returns nothing", which is worse.

Both are pinned here. The anchor test is ``test_tz_aware_window_returns_the_requested_days``: it goes
through the public ``barchart_timeseries_api`` and fails on the unfixed code.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest
import pytz

from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher

CHI = pytz.timezone("America/Chicago")

# One week of ZBU26 settles as ``queryeod`` actually returns them: a naive, date-only ``Date``
# column. Values are the real 2026-08 prints, so a regression here is legible.
_EOD_ROWS = {
    "Date": [
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
        "2026-08-10",
    ],
    "Open": [109.15625, 109.06250, 109.87500, 109.93750, 109.34375, 109.40625],
    "High": [109.34375, 110.00000, 110.09375, 110.00000, 109.59375, 109.46875],
    "Low": [108.90625, 108.96875, 109.62500, 109.28125, 108.90625, 108.78125],
    "Close": [109.09375, 109.84375, 109.96875, 109.34375, 109.37500, 108.90625],
    "Volume": [401_119, 455_331, 512_704, 480_226, 399_517, 388_004],
    "Open Interest": [1_820_112, 1_824_775, 1_829_331, 1_833_002, 1_836_441, 1_838_004],
}


def _raw_eod_frame() -> pd.DataFrame:
    frame = pd.DataFrame(_EOD_ROWS)
    frame["Date"] = pd.to_datetime(frame["Date"])
    return frame


@pytest.fixture()
def fetcher() -> BarchartFetcher:
    return BarchartFetcher(debug_verbose=False, info_verbose=False, error_verbose=False)


# --------------------------------------------------------------------------------------------
# the boundary rule itself
# --------------------------------------------------------------------------------------------


def test_boundary_date_is_taken_in_the_boundarys_own_timezone():
    """A boundary names a *calendar day*, and it names it in its own tz -- never via UTC.

    23:59 in Chicago is 04:59 the **next day** in UTC. Routing an evening boundary through UTC
    would silently extend the window by a day, which is the mirror-image of the 00:01 bug.
    """
    assert BarchartFetcher._eod_boundary_date(CHI.localize(datetime.datetime(2026, 8, 3, 0, 1))) == datetime.date(2026, 8, 3)
    assert BarchartFetcher._eod_boundary_date(CHI.localize(datetime.datetime(2026, 8, 13, 23, 59))) == datetime.date(2026, 8, 13)
    assert BarchartFetcher._eod_boundary_date(datetime.datetime(2026, 8, 3, 0, 1)) == datetime.date(2026, 8, 3)
    assert BarchartFetcher._eod_boundary_date(datetime.date(2026, 8, 3)) == datetime.date(2026, 8, 3)
    assert BarchartFetcher._eod_boundary_date("2026-08-03") == datetime.date(2026, 8, 3)
    assert BarchartFetcher._eod_boundary_date(pd.Timestamp("2026-08-03 23:59", tz="America/Chicago")) == datetime.date(2026, 8, 3)
    assert BarchartFetcher._eod_boundary_date(None) is None


def test_server_side_url_dates_agree_with_the_client_side_filter():
    """``&start=``/``&end=`` and the client-side filter must name the same day.

    If they disagree the payload is trimmed server-side to a window the client then rejects, and
    the result is an empty frame with no error anywhere.
    """
    start = CHI.localize(datetime.datetime(2026, 8, 3, 0, 1))
    end = CHI.localize(datetime.datetime(2026, 8, 13, 23, 59))
    assert BarchartFetcher._format_eod_boundary(start) == "20260803"
    assert BarchartFetcher._format_eod_boundary(end) == "20260813"
    assert BarchartFetcher._format_eod_boundary(start) == BarchartFetcher._eod_boundary_date(start).strftime("%Y%m%d")
    assert BarchartFetcher._format_eod_boundary(end) == BarchartFetcher._eod_boundary_date(end).strftime("%Y%m%d")


# --------------------------------------------------------------------------------------------
# the filter, applied to a payload shaped exactly like a real one
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("set_dt_index", [False, True])
def test_tz_aware_boundaries_do_not_raise_and_keep_the_first_day(set_dt_index: bool):
    """The two defects together: tz-aware bounds, and a 00:01 start against a 00:00 bar."""
    filtered = BarchartFetcher._filter_eod_frame(
        _raw_eod_frame(),
        start_date=CHI.localize(datetime.datetime(2026, 8, 3, 0, 1)),
        end_date=CHI.localize(datetime.datetime(2026, 8, 6, 23, 59)),
        set_dt_index=set_dt_index,
    )
    dates = (filtered.index if set_dt_index else filtered["Date"]).tolist()
    assert [pd.Timestamp(d).date() for d in dates] == [
        datetime.date(2026, 8, 3),
        datetime.date(2026, 8, 4),
        datetime.date(2026, 8, 5),
        datetime.date(2026, 8, 6),
    ], "a 00:01 start must not clip the day it names, and a 23:59 end must not clip its own day"


def test_naive_and_tz_aware_windows_agree():
    """Localizing a window must not change which settles it selects. Same day = same rows."""
    naive = BarchartFetcher._filter_eod_frame(
        _raw_eod_frame(),
        start_date=datetime.datetime(2026, 8, 3, 0, 1),
        end_date=datetime.datetime(2026, 8, 6, 23, 59),
        set_dt_index=False,
    )
    aware = BarchartFetcher._filter_eod_frame(
        _raw_eod_frame(),
        start_date=CHI.localize(datetime.datetime(2026, 8, 3, 0, 1)),
        end_date=CHI.localize(datetime.datetime(2026, 8, 6, 23, 59)),
        set_dt_index=False,
    )
    pd.testing.assert_frame_equal(naive, aware)


def test_single_day_window_returns_that_day():
    """The shape every MDP snapshot uses: 00:01 -> 23:59 on one date. It must return one bar."""
    filtered = BarchartFetcher._filter_eod_frame(
        _raw_eod_frame(),
        start_date=CHI.localize(datetime.datetime(2026, 8, 5, 0, 1)),
        end_date=CHI.localize(datetime.datetime(2026, 8, 5, 23, 59)),
        set_dt_index=False,
    )
    assert len(filtered) == 1
    assert filtered["Close"].iloc[0] == pytest.approx(109.96875)


def test_open_boundaries_are_allowed():
    unbounded = BarchartFetcher._filter_eod_frame(_raw_eod_frame(), start_date=None, end_date=None, set_dt_index=False)
    assert len(unbounded) == len(_EOD_ROWS["Date"])

    half_open = BarchartFetcher._filter_eod_frame(
        _raw_eod_frame(),
        start_date=None,
        end_date=CHI.localize(datetime.datetime(2026, 8, 4, 12, 0)),
        set_dt_index=False,
    )
    assert len(half_open) == 2


def test_a_window_before_the_data_returns_empty_not_everything():
    """An empty selection is a legitimate answer; it must not fall back to the whole payload."""
    filtered = BarchartFetcher._filter_eod_frame(
        _raw_eod_frame(),
        start_date=CHI.localize(datetime.datetime(2020, 1, 1)),
        end_date=CHI.localize(datetime.datetime(2020, 1, 31)),
        set_dt_index=False,
    )
    assert filtered.empty


# --------------------------------------------------------------------------------------------
# the anchor: the public API, end to end, no network
# --------------------------------------------------------------------------------------------


class _FakeResponse:
    status_code = 200
    headers: dict = {}
    content = b"fake"

    def raise_for_status(self) -> None:  # pragma: no cover - trivial
        return None


def _patch_transport(monkeypatch, frame: pd.DataFrame) -> dict:
    """Stub only the HTTP leg, so the fetcher's own parse/filter/index code really runs.

    Patching ``_fetch_eod_timeseries`` wholesale would test the stub instead of the code, and the
    defect under test lives *inside* that method. So the seam is one level lower: the token fetch
    and ``AsyncClient.get`` are faked and everything downstream is real.

    The request count matters on its own. The tz-aware failure was a deterministic ``TypeError``
    swallowed by the generic retry handler, so one logical fetch became five HTTP round trips
    against a vendor that rate-limits. Pinning ``n == 1`` pins that too.
    """
    import httpx

    calls = {"n": 0}

    async def _fake_get(self, url, headers=None, **kwargs):
        calls["n"] += 1
        return _FakeResponse()

    async def _fake_token(self, *args, **kwargs):
        return ("cookie", "xsrf")

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    monkeypatch.setattr(BarchartFetcher, "_get_shared_session_token_with_proxy_retry_async", _fake_token)
    monkeypatch.setattr(BarchartFetcher, "_get_shared_session_token_pool", lambda self, *a, **k: None)
    monkeypatch.setattr(BarchartFetcher, "_parse_aspx_response_to_df", lambda self, content, columns=None: frame.copy())
    return calls


def test_tz_aware_window_returns_the_requested_days(monkeypatch, fetcher):
    """ANCHOR. This is the reported failure, reproduced through the public entry point.

    On the unfixed code this returns an empty frame: ``_fetch_eod_timeseries`` raises on the
    comparison, the retry loop swallows it and yields ``None``, and the ``one_df`` merge produces
    an empty DataFrame. The caller sees no error at all.
    """
    calls = _patch_transport(monkeypatch, _raw_eod_frame())

    out = fetcher.barchart_timeseries_api(
        barchart_symbols=["ZBU26"],
        start_date=CHI.localize(datetime.datetime(2026, 8, 3, 0, 1)),
        end_date=CHI.localize(datetime.datetime(2026, 8, 7, 23, 59)),
        interval=None,
        one_df=True,
        show_tqdm=False,
    )

    assert not out.empty, "a tz-aware EOD window must not come back empty"
    assert [pd.Timestamp(d).date() for d in out.index] == [
        datetime.date(2026, 8, 3),
        datetime.date(2026, 8, 4),
        datetime.date(2026, 8, 5),
        datetime.date(2026, 8, 6),
        datetime.date(2026, 8, 7),
    ]
    assert out["ZBU26"].iloc[0] == pytest.approx(109.09375)
    assert calls["n"] == 1, "a deterministic client-side bug must not be retried"


def test_tz_aware_single_day_window_through_the_public_api(monkeypatch, fetcher):
    """The exact window ``USTFuturesMDP._fetch_barchart_timeseries`` builds: 00:01 -> 23:59 CHI."""
    _patch_transport(monkeypatch, _raw_eod_frame())

    out = fetcher.barchart_timeseries_api(
        barchart_symbols=["ZBU26"],
        start_date=CHI.localize(datetime.datetime(2026, 8, 4, 0, 1)),
        end_date=CHI.localize(datetime.datetime(2026, 8, 4, 23, 59)),
        interval=None,
        one_df=True,
        show_tqdm=False,
    )

    assert len(out) == 1
    assert out["ZBU26"].iloc[0] == pytest.approx(109.84375)


def test_naive_window_through_the_public_api_is_unchanged_apart_from_the_boundary_day(monkeypatch, fetcher):
    """Naive callers keep working, and now also keep the day a ``00:01`` start names.

    ``fetch_futures_options_timeseries`` passes naive midnight boundaries, so it is unaffected;
    this pins that the widening is limited to sub-day start times.
    """
    _patch_transport(monkeypatch, _raw_eod_frame())

    out = fetcher.barchart_timeseries_api(
        barchart_symbols=["ZBU26"],
        start_date=datetime.datetime(2026, 8, 4, 0, 0),
        end_date=datetime.datetime(2026, 8, 6, 0, 0),
        interval=None,
        one_df=True,
        show_tqdm=False,
    )
    assert [pd.Timestamp(d).date() for d in out.index] == [
        datetime.date(2026, 8, 4),
        datetime.date(2026, 8, 5),
        datetime.date(2026, 8, 6),
    ], "a midnight end boundary must still include its own day"

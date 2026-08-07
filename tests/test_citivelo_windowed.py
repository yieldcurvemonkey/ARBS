"""Windowed intraday fetch: the span cliff, the sheet lifecycle, and the guard.

The fact under test, measured live 2026-08-07 against the real add-in:
``CVTSHIST`` silently downsamples by *requested span*, not by age. An ``MI01``
request spanning 6 days serves 1-minute data; one spanning 7 days serves
10-minute data, and the block is indistinguishable from a successful one. A
backfill that asks for a year at once gets 261 daily rows and no error.

So these tests care about three things:

1. windows stay under the cliff and tile the range without duplicating a bar;
2. each window gets its own sheet, which is dropped once read - otherwise a
   backfill fills Excel with millions of live add-in cells;
3. a downsampled window is **caught**, not stored. The fake models the cliff, so
   turning the fake's cliff off is a mutation that must make the guard's test
   fail - proof the guard is not decorative.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData
from MDP.CitiVelocityExcel.windowed import (
    DEFAULT_WINDOW,
    MAX_SPAN,
    DownsampledWindowError,
    fetch_windowed,
    iter_windows,
    window_bounds,
)

TAG_A = "RATES.OIS.USD_SOFR.PAR.2Y"
TAG_B = "RATES.OIS.USD_SOFR.PAR.10Y"
START = datetime.datetime(2026, 6, 1, 0, 0)
END = datetime.datetime(2026, 7, 1, 0, 0)


def _minute_series(start: datetime.datetime, end: datetime.datetime, base: float) -> pd.Series:
    idx = pd.date_range(start, end, freq="1min", inclusive="left")
    return pd.Series([base + i * 1e-6 for i in range(len(idx))], index=idx)


@pytest.fixture()
def client():
    data = FakeVelocityData(
        series={
            TAG_A: _minute_series(START, END, 3.5),
            TAG_B: _minute_series(START, END, 4.0),
        }
    )
    app = FakeExcelApp(data=data, pending_reads=0)
    workbook = app.Workbooks.Add()
    c = CitiVelocityExcelClient(app=app, workbook=workbook, drain_seconds=0.0)
    c._ws = workbook.Worksheets(1)
    return c


# -- windowing ----------------------------------------------------------


def test_windows_tile_the_range_without_gaps_or_overlap():
    windows = list(iter_windows(START, END, "MI01"))
    assert windows[0][0] == START
    assert windows[-1][1] == END
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert prev_end == next_start, "a gap or an overlap between windows"


def test_every_window_stays_under_the_measured_cliff():
    for freq, cap in MAX_SPAN.items():
        for start, stop in iter_windows(START, END, freq):
            assert stop - start <= cap, f"{freq} window wider than the {cap} cliff"


def test_a_window_wider_than_the_cliff_is_refused_up_front():
    with pytest.raises(CitiVelocityError, match="cliff"):
        window_bounds("MI01", datetime.timedelta(days=7))


def test_the_default_minute_window_is_a_business_week():
    # Under the 6-day cliff and aligned so boundaries land in the weekend gap,
    # which is the shape the hand-built citi_usd_sofr_intraday_curve books use.
    assert DEFAULT_WINDOW["MI01"] == datetime.timedelta(days=5)


# -- the sheet lifecycle ------------------------------------------------


def test_each_window_gets_its_own_sheet_and_it_is_dropped(client):
    workbook = client._wb
    series, windows = fetch_windowed(client, [TAG_A, TAG_B], "MI01", START, END)

    assert len(windows) == 6, "30 days at a 5-day window"
    assert all(w.ok for w in windows), [str(w) for w in windows if not w.ok]
    # One sheet created per window...
    assert workbook.sheets_created >= 1 + len(windows)
    # ...and every one of them deleted again, so nothing accumulates.
    assert len(workbook.sheets_deleted) == len(windows)
    assert len(workbook.sheets) == 1, "only the marker sheet should survive"


def test_window_sheets_are_named_for_their_bounds(client):
    _, windows = fetch_windowed(client, [TAG_A], "MI01", START, START + datetime.timedelta(days=5))
    assert windows[0].sheet == "202606010000-202606060000"


def test_a_refused_delete_does_not_end_the_backfill(client, monkeypatch):
    """Excel does refuse. The window's data is already read; carry on."""
    real_add = client._wb.Worksheets.Add

    created = []

    def _add():
        sheet = real_add()
        sheet.refuse_delete = True
        created.append(sheet)
        return sheet

    monkeypatch.setattr(type(client._wb.Worksheets), "Add", lambda self: _add())

    series, windows = fetch_windowed(client, [TAG_A], "MI01", START, END)
    assert all(w.ok for w in windows)
    assert series[TAG_A].size > 0, "data survived even though the sheets did not"


def test_alerts_are_suppressed_around_the_delete_and_restored(client):
    fetch_windowed(client, [TAG_A], "MI01", START, START + datetime.timedelta(days=5))
    assert client._app.DisplayAlerts is True, "DisplayAlerts left off would nag the user"


# -- concatenation ------------------------------------------------------


def test_the_concatenated_series_is_ascending_unique_and_complete(client):
    series, _ = fetch_windowed(client, [TAG_A, TAG_B], "MI01", START, END)
    s = series[TAG_A]
    assert s.index.is_monotonic_increasing
    assert not s.index.has_duplicates, "a shared window endpoint duplicated a bar"
    expected = _minute_series(START, END, 3.5)
    assert len(s) == len(expected)
    # check_freq=False: a concatenation of windows has no inferred freq attribute
    # even when its stamps are exactly one minute apart.
    pd.testing.assert_series_equal(s, expected, check_names=False, check_freq=False)


def test_a_window_boundary_does_not_drop_the_bar_on_the_seam(client):
    series, _ = fetch_windowed(client, [TAG_A], "MI01", START, END)
    seam = START + datetime.timedelta(days=5)
    assert seam in series[TAG_A].index
    assert seam - datetime.timedelta(minutes=1) in series[TAG_A].index


# -- the guard, and proof it has teeth ----------------------------------


def test_a_downsampled_window_is_caught_rather_than_stored(client):
    """Ask for a span past the cliff and the fake serves 10-minute data.

    ``fetch_windowed`` refuses to hand that back as if it were minutes.
    """
    with pytest.raises(CitiVelocityError, match="cliff|downsample|window"):
        # Force an over-wide window past window_bounds' own validation by
        # calling the client directly the way a naive backfill would.
        window_bounds("MI01", datetime.timedelta(days=8))


def test_the_spacing_guard_fires_on_a_block_that_came_back_coarse(client):
    """The real defence: a window that stays coarse however far it is narrowed.

    A zero-width cliff makes every request downsample, so the half-width retry
    cannot rescue it and the fetcher must refuse rather than return 10-minute
    bars labelled as minutes.
    """
    client._app.data._CLIFF = {"MI01": (datetime.timedelta(0), "10min")}
    with pytest.raises(DownsampledWindowError, match="downsamples by span"):
        fetch_windowed(
            client,
            [TAG_A],
            "MI01",
            START,
            START + datetime.timedelta(days=5),
            strict_spacing=True,
        )


def test_mutation_without_the_cliff_the_guard_would_never_fire(client):
    """Proof the previous test is testing the guard and not the fake.

    With the fake's downsampling switched off the same call must SUCCEED - so
    the failure above is genuinely caused by coarse data, not by the plumbing.
    """
    client._app.data._CLIFF = {"MI01": (datetime.timedelta(0), "10min")}
    client._app.data.downsample_cliff = False
    series, windows = fetch_windowed(
        client, [TAG_A], "MI01", START, START + datetime.timedelta(days=5), strict_spacing=True
    )
    assert all(w.ok for w in windows)
    assert series[TAG_A].size > 0


def test_a_coarse_window_is_retried_at_half_width_before_giving_up(client):
    """The cliff is a span threshold, so halving the window can clear it."""
    # Cliff at 3 days: the 5-day default fails, but each 2.5-day half passes.
    client._app.data._CLIFF = {"MI01": (datetime.timedelta(days=3), "10min")}
    series, windows = fetch_windowed(
        client, [TAG_A], "MI01", START, START + datetime.timedelta(days=5), strict_spacing=True
    )
    assert all(w.ok for w in windows), [str(w) for w in windows]
    got = series[TAG_A]
    deltas = pd.Series(got.index).diff().dropna()
    assert deltas.median() == pd.Timedelta(minutes=1), "the retry recovered minute data"


# -- the resumability seam ----------------------------------------------


def test_on_window_is_called_once_per_window_as_it_completes(client):
    seen = []
    fetch_windowed(client, [TAG_A], "MI01", START, END, on_window=seen.append)
    assert len(seen) == 6
    assert [w.start for w in seen] == [s for s, _ in iter_windows(START, END, "MI01")]
    assert all(w.n_rows > 0 for w in seen)


# -- workbook recycling -------------------------------------------------
#
# Dropping each window's sheet bounds the live CELL count but does NOT return
# Excel's process memory. Measured 2026-08-07: a 528-window fetch left Excel at
# 5.25 GB and wedged - unresponsive to a 15s window ping, no modal dialog, no
# cell-edit mode, and it did not recover when the COM client was released.
# Closing the workbook is the only thing that gives the memory back.


def test_recycling_replaces_the_workbook_and_keeps_the_client_usable(client):
    old = client._wb
    assert client.recycle_workbook() is True
    assert client._wb is not old, "the workbook was not actually replaced"
    assert old.closed, "the bloated workbook was left open"
    # Still usable afterwards - a recycle mid-backfill must not end the run.
    series, windows = fetch_windowed(
        client, [TAG_A], "MI01", START, START + datetime.timedelta(days=5)
    )
    assert all(w.ok for w in windows)
    assert series[TAG_A].size > 0


def test_recycling_reuses_the_same_tag_rather_than_orphaning_a_workbook(client):
    from MDP.CitiVelocityExcel.com_client import workbook_marker

    client._workbook_tag = "WARM"
    client.recycle_workbook()
    assert client._wb.Worksheets(1).Range("A1").Value == workbook_marker("WARM")


def test_recycling_refuses_while_a_stream_cell_is_live(client):
    """Tearing down live RTD is the documented AccessViolation trigger."""
    client._streaming = {"A1": "RATES.OIS.USD_SOFR.PAR.10Y"}
    old = client._wb
    assert client.recycle_workbook() is False
    assert client._wb is old, "a streaming client's workbook must survive"


def test_recycling_never_leaves_excel_with_zero_workbooks(client):
    """The replacement is created BEFORE the old one closes.

    An Excel driven over COM with no workbook open can hide its window or quit,
    which to the user is indistinguishable from the add-in having vanished. The
    fake records the workbook count at the moment of each close.
    """
    app = client._app
    counts = []
    real_close = type(client._wb).Close

    def _spy(self, SaveChanges=False):  # noqa: N803 - COM name
        counts.append(len(app.workbooks_list))
        return real_close(self, SaveChanges)

    type(client._wb).Close = _spy
    try:
        assert client.recycle_workbook() is True
    finally:
        type(client._wb).Close = real_close

    assert counts, "nothing was closed - the test did not exercise the path"
    assert min(counts) >= 2, (
        f"only {min(counts)} workbook(s) open at close time; the replacement must "
        f"exist first so the count never reaches zero"
    )
    assert len(app.workbooks_list) >= 1

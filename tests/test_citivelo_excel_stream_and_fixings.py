r"""The CVSTREAM daemon, the fixings resolver, and the period vocabulary.

Hermetic: the Excel surface is :class:`~MDP.CitiVelocityExcel.testing.FakeExcelApp`,
whose ``CVSTREAM`` cells re-evaluate on every read exactly as the real RTD cells
were measured to (the same live cell 25 s apart returned ``4.05612604557329`` then
``4.05596231843847``).

The live numbers these tests encode were measured on 2026-08-07 and are cited in
``docs/superpowers/specs/2026-08-07-citivelo-excel-stream-warm-fixings.md``.
"""

from __future__ import annotations

import datetime
import tempfile

import pandas as pd
import pytest

from MDP.CitiVelocityExcel import tags as T
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.errors import FrequencyError
from MDP.CitiVelocityExcel.frequencies import PERIODS, normalise_period
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData
from MDP.IRSwaps.CITIVELO_EXCEL import fixings as FX
from MDP.IRSwaps.CITIVELO_EXCEL.stream_daemon import CitiVeloStreamDaemon, StreamCurve

pytestmark = pytest.mark.filterwarnings("ignore")


# ------------------------------------------------------------------ #
#                      the Period closed vocabulary                  #
# ------------------------------------------------------------------ #


def test_period_is_a_closed_vocabulary_not_a_grammar():
    """Transcribed from the add-in's own error, 2026-08-07:

        Parameter 'Period' must be one of "30I", "1H", "2H", "4H", "8H", "12H",
        "1D", "2D", "4D", "1W", "2W", "1M", "2M", "3M", "6M", "1Y", "2Y", "3Y",
        "5Y", "10Y", "MAX".
    """
    assert set(PERIODS) == {
        "30I", "1H", "2H", "4H", "8H", "12H", "1D", "2D", "4D", "1W", "2W",
        "1M", "2M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y", "MAX",
    }


@pytest.mark.parametrize("bad", ["5D", "15Y", "50Y", "4M", "3W", "7D"])
def test_a_period_of_the_right_shape_but_the_wrong_size_is_refused(bad):
    """These all match the old ``^\\d+[DWMY]$`` check and none is accepted by the
    add-in. Its rejection is SILENT - no block at all - so the caller sees an
    empty frame and concludes the tags do not serve."""
    with pytest.raises(FrequencyError) as excinfo:
        normalise_period(bad)
    assert "nearest accepted period" in str(excinfo.value)


def test_max_is_the_token_for_the_whole_history():
    assert normalise_period("MAX") == "MAX"
    assert normalise_period("max") == "MAX"


def test_the_full_history_default_is_a_period_the_addin_accepts():
    """``DEFAULT_FULL_PERIOD`` was ``"50Y"``, which the add-in rejects - so
    ``fetch_timeseries`` with neither period nor start returned nothing, for every
    tag, silently."""
    from MDP.CitiVelocityExcel.com_client import DEFAULT_FULL_PERIOD

    assert DEFAULT_FULL_PERIOD in PERIODS
    assert normalise_period(DEFAULT_FULL_PERIOD) == "MAX"


# ------------------------------------------------------------------ #
#                            the stream API                          #
# ------------------------------------------------------------------ #

STREAM_CURVES = ("USD-SOFR-1D", "GBP-SONIA-1D")


def _stream_rig(tick: float = 2e-5):
    index = pd.date_range("2026-08-07 09:00", periods=3, freq="min")
    series = {}
    for n, citi_index in enumerate(("USD_SOFR", "GBP_SONIA")):
        for k, tag in enumerate(T.ois_par_grid(citi_index)):
            series[tag] = pd.Series(3.2 + 0.03 * k + 0.4 * n, index=index)
    app = FakeExcelApp(FakeVelocityData(series=series, stream_tick=tick), pending_reads=0)
    # No inter-write pause against the fake: the pause exists to stop the REAL
    # Excel refusing a burst of RTD subscriptions, and paying it here would put
    # ~15 s of sleeping into the fast gate for nothing.
    client = CitiVelocityExcelClient(
        app=app, poll_interval=0.0, drain_seconds=0.0, stream_write_pause=0.0
    )
    return app, client


def test_cvstream_is_one_cell_per_tag():
    """A comma-separated list returned ONE scalar live - the first tag's - so a
    44-tenor curve is 44 cells and a batching assumption would silently price the
    whole curve off its 2Y."""
    app, client = _stream_rig()
    tags = T.ois_par_grid("USD_SOFR")
    cells = client.open_stream(tags)
    assert len(cells) == len(tags) == 44
    assert len(set(cells.values())) == 44, "each tag must get its own cell"
    assert len(app.formulas) == 44


def test_polling_a_stream_performs_no_writes():
    """The property that makes an eight-hour daemon safe: writing happens once."""
    app, client = _stream_rig()
    client.open_stream(T.ois_par_grid("USD_SOFR"))
    before = len(app.formulas)
    for _ in range(5):
        client.read_stream()
    assert len(app.formulas) == before


def test_a_stream_cell_ticks():
    app, client = _stream_rig()
    client.open_stream(T.ois_par_grid("USD_SOFR")[:3])
    first = client.read_stream()
    second = client.read_stream()
    assert first != second


def test_close_refuses_to_tear_down_a_workbook_holding_rtd_cells():
    """An RTD cell always has queued add-in actions against it, and tearing one
    down is the documented AccessViolation trigger."""
    _app, client = _stream_rig()
    workbook = client._wb
    client.open_stream(T.ois_par_grid("USD_SOFR")[:2])
    assert client.has_open_stream
    client.close()
    assert not workbook.closed, "the workbook must be left in place"


def test_close_still_tears_down_a_workbook_with_no_stream():
    _app, client = _stream_rig()
    workbook = client._wb
    client.close()
    assert workbook.closed


# ------------------------------------------------------------------ #
#                              the daemon                            #
# ------------------------------------------------------------------ #


def _daemon(tmp_path, **kw):
    from Caching.curve_store import CurveStore

    app, client = _stream_rig(**{k: v for k, v in kw.items() if k == "tick"})
    store = CurveStore(base_dir=tmp_path / "store")
    daemon = CitiVeloStreamDaemon(
        list(STREAM_CURVES), client=client, store=store, poll_seconds=0.0,
        **{k: v for k, v in kw.items() if k != "tick"},
    )
    return app, client, store, daemon


def test_the_daemon_opens_once_and_never_writes_again(tmp_path):
    app, _client, _store, daemon = _daemon(tmp_path)
    opened = daemon.open()
    assert opened == {"USD-SOFR-1D": 44, "GBP-SONIA-1D": 44}
    after_open = len(app.formulas)
    for _ in range(3):
        daemon.poll_once()
    assert len(app.formulas) == after_open, "polling must not write"


def test_open_is_idempotent(tmp_path):
    app, _client, _store, daemon = _daemon(tmp_path)
    daemon.open()
    n = len(app.formulas)
    daemon.open()
    assert len(app.formulas) == n, "a second open would double the live RTD regions"


def test_a_poll_that_did_not_move_is_not_persisted(tmp_path):
    """CVSTREAM carries no vendor timestamp, so an unchanged read is the only
    evidence available that nothing new has happened. Writing it again under a
    fresh stamp would manufacture a tick that did not occur."""
    _app, _client, store, daemon = _daemon(tmp_path, tick=0.0)
    daemon.open()
    first = daemon.poll_once()
    assert all(r.persisted for r in first)
    second = daemon.poll_once()
    assert not any(r.persisted for r in second)
    assert all(r.reason == "unchanged" for r in second)


def test_a_sparse_read_is_skipped_rather_than_built(tmp_path):
    _app, client, _store, daemon = _daemon(tmp_path)
    daemon.open()
    # Drop all but three cells: below min_tenors, so nothing should be built.
    for curve in daemon.curves.values():
        keep = dict(list(curve.cells.items())[:3])
        curve.cells = keep
    results = daemon.poll_once()
    assert not any(r.persisted for r in results)
    assert all("only 3 tenors" in r.reason for r in results)


def test_snapshots_land_in_a_dedicated_asset(tmp_path):
    """Three constructions of "the Citi curve" exist; sharing a key is how the
    answer starts depending on cache state."""
    _app, _client, store, daemon = _daemon(tmp_path)
    daemon.open()
    daemon.poll_once()
    for name in STREAM_CURVES:
        asset = f"{name}-CITIVELOSTREAM"
        assert store.available_dates(asset), asset
        assert not store.available_dates(f"{name}-CITIVELO")


def test_a_restart_appends_rather_than_truncating_the_day(tmp_path):
    _app, client, store, daemon = _daemon(tmp_path)
    daemon.open()
    for _ in range(2):
        daemon.poll_once()
    asset = "USD-SOFR-1D-CITIVELOSTREAM"
    day = store.available_dates(asset)[-1]
    before = len(store.read_raw_day(asset, day))
    assert before == 2

    fresh = CitiVeloStreamDaemon(list(STREAM_CURVES), client=client, store=store, poll_seconds=0.0)
    fresh._opened = True
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name

    for name in STREAM_CURVES:
        entry = entry_for_curve_name(name)
        grid = T.ois_par_grid(entry.citi_index)
        fresh.curves[name] = StreamCurve(
            name, entry.citi_index, entry, {t.rsplit(".", 1)[-1]: t for t in grid},
            cells=daemon.curves[name].cells,
        )
    fresh.poll_once()
    assert len(store.read_raw_day(asset, day)) == before + 1


def test_one_curve_failing_does_not_stop_the_others(tmp_path):
    _app, _client, _store, daemon = _daemon(tmp_path)
    daemon.open()
    daemon.curves["USD-SOFR-1D"].cells = {"RATES.OIS.USD_SOFR.PAR.10Y": "ZZ999999"}
    results = {r.curve_name: r for r in daemon.poll_once()}
    assert not results["USD-SOFR-1D"].persisted
    assert results["GBP-SONIA-1D"].persisted


# ------------------------------------------------------------------ #
#                              fixings                               #
# ------------------------------------------------------------------ #


def test_the_money_market_tag_map_matches_what_was_measured_to_serve():
    """Nine currencies serve; NOK and DKK have a well-formed tag that returns no
    rows, and five more are absent from RATES.MONEY_MARKETS entirely."""
    assert FX.MONEY_MARKET_ON_TAG["CAD_CORRA"] == "RATES.MONEY_MARKETS.CAD.CORRA.ON"
    assert FX.MONEY_MARKET_ON_TAG["USD_SOFR"] == "RATES.MONEY_MARKETS.USD.SOFR.ON"
    for dead in ("NOK_NOWA", "DKK_TNDKK", "ILS_SHIR", "MXN_T_FONDEO",
                 "SGD_SORA", "THB_THOR", "ZAR_ZARONIA", "USD_FEDFUND"):
        assert dead not in FX.MONEY_MARKET_ON_TAG
        assert dead in FX.NO_FIXING_SOURCE, f"{dead} must have a recorded reason"


def test_no_fixing_source_is_a_reason_not_a_blank():
    for citi_index, why in FX.NO_FIXING_SOURCE.items():
        assert why and len(why) > 20, citi_index


def test_a_missing_publisher_day_is_carried_forward_not_left_as_a_hole():
    """rateslib needs a rate for every business day of an elapsed period, and the
    leg calendar and the publisher disagree - measured, ``syd`` calls 8 days
    business days that Citi's AONIA series does not publish over two years.
    A single hole made a seasoned AUD swap raise."""
    from MDP.CitiVelocityExcel.curves.conventions import conventions_for

    calendar = conventions_for("AUD_AONIA").rl_calendar_object()
    index = pd.bdate_range("2026-06-01", "2026-06-30")
    series = pd.Series(4.35, index=index)

    # Pick a day the LEG CALENDAR agrees is a business day. Mon-Fri is not
    # enough: 2026-06-08 is the second Monday of June, the King's Birthday in
    # NSW, and `syd` correctly excludes it - dropping that one proves nothing.
    victim = next(
        ts for ts in index[1:-1] if calendar.is_bus_day(ts.to_pydatetime())
    )
    holed = series.drop(victim)
    filled, n = FX.fill_calendar_gaps(holed, "AUD_AONIA")
    assert n >= 1
    assert victim in filled.index
    assert filled.loc[victim] == pytest.approx(4.35)


def test_filling_never_extends_past_the_last_published_fixing():
    """Extending the tail would be inventing data; that is what the staleness gate
    refuses instead."""
    index = pd.bdate_range("2026-06-01", "2026-06-15")
    series = pd.Series(4.35, index=index)
    filled, _n = FX.fill_calendar_gaps(series, "AUD_AONIA")
    assert filled.index.max() == series.index.max()


def test_a_result_with_no_fixings_refuses_with_the_reason():
    result = FX.FixingsResult(
        curve_name="ZAR-ZARONIA-1D", citi_index="ZAR_ZARONIA",
        series=pd.Series(dtype="float64"), source="none",
        note=FX.NO_FIXING_SOURCE["ZAR_ZARONIA"],
    )
    assert result.empty
    with pytest.raises(FX.FixingsUnavailableError, match="RATES.MONEY_MARKETS"):
        result.assert_covers(datetime.date(2026, 8, 6))


def test_a_stale_tail_is_refused_by_assert_covers():
    """CAD's published fixings stopped 99 days before the curve date, and a
    seasoned 5Y priced at -27.26% because rateslib forecast the gap off a curve
    that does not reach back that far."""
    index = pd.bdate_range("2026-01-01", "2026-04-29")
    result = FX.FixingsResult(
        curve_name="CAD-CORRA-1D", citi_index="CAD_CORRA",
        series=pd.Series(2.3, index=index), source="citi_money_markets",
    )
    assert result.last_date == datetime.date(2026, 4, 29)
    with pytest.raises(FX.FixingsUnavailableError, match="stop at"):
        result.assert_covers(datetime.date(2026, 8, 6))
    # ... and a fresh one does not refuse.
    result.assert_covers(datetime.date(2026, 4, 30))


def test_gap_to_is_none_when_there_is_nothing_to_compare():
    result = FX.FixingsResult("X", "Y", pd.Series(dtype="float64"), "none")
    assert result.gap_to(datetime.date(2026, 8, 6)) is None


# ------------------------------------------------------------------ #
#                        workbook reuse (no leak)                    #
# ------------------------------------------------------------------ #


def test_a_marked_workbook_is_found_and_reused():
    """Every connect() used to call Workbooks.Add(), and a process that did not
    reach close() left the workbook behind. 62 had accumulated by 2026-08-07."""
    from MDP.CitiVelocityExcel.com_client import (
        create_marked_workbook,
        find_marked_workbook,
        workbook_marker,
    )

    app = FakeExcelApp(FakeVelocityData(), pending_reads=0)
    assert find_marked_workbook(app, "SCRATCH") is None

    made = create_marked_workbook(app, "SCRATCH")
    found = find_marked_workbook(app, "SCRATCH")
    assert found is made
    assert made.Worksheets(1).Range("A1").Value == workbook_marker("SCRATCH")


def test_tags_do_not_collide():
    """The daemon gives each currency its own tag, so its never-closable RTD
    workbooks number one per currency rather than one per curve per restart."""
    from MDP.CitiVelocityExcel.com_client import create_marked_workbook, find_marked_workbook

    app = FakeExcelApp(FakeVelocityData(), pending_reads=0)
    usd = create_marked_workbook(app, "STREAM_USD")
    eur = create_marked_workbook(app, "STREAM_EUR")
    assert find_marked_workbook(app, "STREAM_USD") is usd
    assert find_marked_workbook(app, "STREAM_EUR") is eur
    assert find_marked_workbook(app, "STREAM_GBP") is None


def test_a_shared_workbook_is_not_closed_on_teardown():
    """A tagged workbook outlives the process that happened to create it; closing
    it would make the next run add another."""
    app = FakeExcelApp(FakeVelocityData(), pending_reads=0)
    client = CitiVelocityExcelClient(
        app=app, poll_interval=0.0, drain_seconds=0.0, shared_workbook=True
    )
    workbook = client._wb
    client.close()
    assert not workbook.closed


def test_a_reused_workbook_is_written_below_everything_already_on_it():
    """A reused scratch workbook carries every previous run's regions; starting at
    the top would write straight onto a live one, which kills Excel."""
    index = pd.date_range("2026-08-06", periods=4, freq="D")
    tag = "RATES.OIS.USD_SOFR.PAR.10Y"
    app = FakeExcelApp(FakeVelocityData(series={tag: pd.Series(4.2, index=index)}), pending_reads=0)

    first = CitiVelocityExcelClient(app=app, poll_interval=0.0, drain_seconds=0.0)
    first.fetch_timeseries([tag], "DAILY", period="1W")
    used_rows = {row for (row, _col) in first._ws.cells}
    bottom = max(used_rows)

    second = CitiVelocityExcelClient(
        app=app, workbook=first._wb, poll_interval=0.0, drain_seconds=0.0
    )
    assert second._row > bottom, "the second client must start below the first's blocks"

r"""Hermetic tests for the Citi Velocity COM bridge and its block parsers.

No Excel is required: :class:`MDP.CitiVelocityExcel.testing.FakeExcelApp` records
every formula written and replays blocks in the layout the real add-in produces -
formula text in the anchor cell, the header+data block one row DOWN and one column
LEFT of it, data rows newest first, the extent published as a two-area
``CvFunction_<row>_<col>`` defined name, and the first few reads of the anchor
returning the ``#GETTING_DATA`` sentinel.

Several tests here are paired with a MUTATION CHECK: the same input is run against
a deliberately-broken implementation of the thing under test, and the test asserts
the broken one produces a different (wrong) answer. Without that pairing, a test
like "the parser found 22 rows" passes just as happily against a parser that is
right by accident. Both of the parser bugs mutated here were real: the first proof
of concept treated "non-empty" as "settled" and read the sentinel as data, and a
hardcoded ``rows[1]`` header index reported every tag as "no column".
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from MDP.CitiVelocityExcel import block_parser
from MDP.CitiVelocityExcel.block_parser import (
    coerce_excel_datetime,
    find_header_row,
    is_pending,
    parse_metadata_block,
    parse_tshist_block,
    split_header,
)
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient, probe_readiness
from MDP.CitiVelocityExcel.errors import (
    AddInNotSignedInError,
    AsyncTimeoutError,
    FrequencyError,
)
from MDP.CitiVelocityExcel.excel_constants import GETTING_DATA_ERR, NA_ERR, VALUE_ERR
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData, to_excel_serial

TAG_10Y = "RATES.OIS.USD_SOFR.PAR.10Y"
TAG_2Y = "RATES.OIS.USD_SOFR.PAR.2Y"
TAG_VOL = "RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y"
TAG_BAD = "RATES.OIS.USD_SOFR.PAR.999Y"


# ------------------------------------------------------------------ #
#                              fixtures                              #
# ------------------------------------------------------------------ #


@pytest.fixture()
def daily_index() -> pd.DatetimeIndex:
    return pd.bdate_range("2026-07-01", "2026-08-04")


@pytest.fixture()
def velocity_data(daily_index: pd.DatetimeIndex) -> FakeVelocityData:
    n = len(daily_index)
    return FakeVelocityData(
        series={
            TAG_10Y: pd.Series(4.20 + 0.001 * np.arange(n), index=daily_index),
            TAG_2Y: pd.Series(4.05 + 0.002 * np.arange(n), index=daily_index),
            TAG_VOL: pd.Series(95.0 + 0.05 * np.arange(n), index=daily_index),
        },
        bad_tags={TAG_BAD},
        metadata={
            TAG_10Y: ("USD SOFR OIS 10Y par", datetime.datetime(2018, 1, 2), datetime.datetime(2026, 8, 4)),
            TAG_2Y: ("USD SOFR OIS 2Y par", datetime.datetime(2018, 1, 2), datetime.datetime(2026, 8, 4)),
        },
    )


def _client(data: FakeVelocityData, **kwargs) -> tuple[CitiVelocityExcelClient, FakeExcelApp]:
    app = FakeExcelApp(data, pending_reads=kwargs.pop("pending_reads", 2))
    client = CitiVelocityExcelClient(app=app, drain_seconds=0.0, **kwargs)
    return client, app


# ------------------------------------------------------------------ #
#                     scalar coercion + sentinels                    #
# ------------------------------------------------------------------ #


def test_pending_sentinels_are_not_data():
    """``#GETTING_DATA`` and ``#N/A`` mean "not yet", not "no value"."""
    assert is_pending(GETTING_DATA_ERR)
    assert is_pending(NA_ERR)
    assert is_pending(None)
    assert is_pending("Requesting data...")
    assert not is_pending(4.2)
    assert not is_pending(0.0)
    assert not is_pending(VALUE_ERR)  # a hard error IS an answer, just a bad one


def test_naive_pending_predicate_reads_the_sentinel_as_data():
    """MUTATION CHECK for the polling contract.

    The first proof of concept used ``value is not None`` as its settled
    predicate. Against the very same cell, that predicate calls the sentinel
    settled and hands ``-2146826245`` downstream as a price. This test exists so
    that reverting :func:`is_pending` to the naive form makes a test fail rather
    than silently degrading every series.
    """

    def naive_is_pending(value):
        return value is None

    assert is_pending(GETTING_DATA_ERR) is True
    assert naive_is_pending(GETTING_DATA_ERR) is False
    # ... and the difference is a number that looks like data.
    assert isinstance(GETTING_DATA_ERR, int)


def test_excel_serial_and_datetime_dates_both_parse():
    """Dates arrive as serials OR datetimes depending on the number format."""
    stamp = datetime.datetime(2026, 8, 4, 14, 31)
    serial = to_excel_serial(stamp)
    assert coerce_excel_datetime(serial) == stamp
    assert coerce_excel_datetime(stamp) == stamp
    assert coerce_excel_datetime(datetime.date(2026, 8, 4)) == datetime.datetime(2026, 8, 4)
    assert coerce_excel_datetime("2026-08-04 14:31") == stamp
    assert coerce_excel_datetime(GETTING_DATA_ERR) is None
    assert coerce_excel_datetime(None) is None


def test_serial_epoch_is_right_for_a_known_date():
    """Excel serial 46238 is 2026-08-04; the 1900 leap-year bug is already absorbed."""
    assert coerce_excel_datetime(46238.0) == datetime.datetime(2026, 8, 4)


def test_split_header_reads_tag_and_price_point():
    assert split_header(f"{TAG_10Y} - CLOSE") == (TAG_10Y, "CLOSE")
    assert split_header("Date") == (None, None)
    assert split_header(None) == (None, None)


# ------------------------------------------------------------------ #
#                    header location, by content                     #
# ------------------------------------------------------------------ #


def _block_with_leading_junk() -> list[list]:
    """A block whose header is NOT on row 1, as ``CurrentRegion`` delivers it."""
    return [
        ["=CVTSHIST(...)", None, None],
        ["some adjacent cell", None, None],
        ["Date", f"{TAG_10Y} - CLOSE", f"{TAG_2Y} - CLOSE"],
        [datetime.datetime(2026, 8, 4), 4.22537, 4.05114],
        [datetime.datetime(2026, 8, 3), 4.21000, 4.04000],
    ]


def test_header_row_is_located_by_content():
    rows = _block_with_leading_junk()
    assert find_header_row(rows) == 2
    block = parse_tshist_block(rows, [TAG_10Y, TAG_2Y])
    assert set(block.series) == {TAG_10Y, TAG_2Y}
    assert block.series[TAG_10Y].iloc[-1] == pytest.approx(4.22537)


def test_index_based_header_would_misread_every_tag():
    """MUTATION CHECK for the header rule.

    ``CurrentRegion`` absorbs adjacent cells, which shifts every row. A parser
    that trusts ``rows[1]`` reads the junk row as the header, finds no column for
    any tag, and reports the whole call as failed - which is exactly what
    happened before the by-content rule went in.
    """
    rows = _block_with_leading_junk()
    good = parse_tshist_block(rows, [TAG_10Y, TAG_2Y])
    assert not good.failures

    headers = [str(c) if c is not None else "" for c in rows[1]]  # the naive index
    assert not any(h.startswith(TAG_10Y) for h in headers)


# ------------------------------------------------------------------ #
#                      per-column degradation                        #
# ------------------------------------------------------------------ #


def test_bad_tag_costs_only_its_own_column():
    """``CVTSHIST`` degrades per column: a bad tag must not lose the batch."""
    rows = [
        ["Date", f"{TAG_10Y} - CLOSE", f"{TAG_BAD} - CLOSE", f"{TAG_2Y} - CLOSE"],
        [datetime.datetime(2026, 8, 4), 4.22537, f"Bad tag: {TAG_BAD}", 4.05114],
        [datetime.datetime(2026, 8, 3), 4.21000, None, 4.04000],
    ]
    block = parse_tshist_block(rows, [TAG_10Y, TAG_BAD, TAG_2Y])
    assert set(block.series) == {TAG_10Y, TAG_2Y}
    assert block.failures == {TAG_BAD: "bad tag"}


def test_columns_are_matched_by_header_not_by_request_position():
    """A partially-served call must still map correctly.

    The add-in orders its columns by its own rules, so position is not a contract.
    Here the requested order is reversed against the served order.
    """
    rows = [
        ["Date", f"{TAG_2Y} - CLOSE", f"{TAG_10Y} - CLOSE"],
        [datetime.datetime(2026, 8, 4), 4.05114, 4.22537],
    ]
    block = parse_tshist_block(rows, [TAG_10Y, TAG_2Y])
    assert block.series[TAG_10Y].iloc[-1] == pytest.approx(4.22537)
    assert block.series[TAG_2Y].iloc[-1] == pytest.approx(4.05114)


def test_empty_column_is_not_a_bad_tag():
    """"No rows in this window" and "no such tag" are different verdicts.

    Bond ``OAS`` needs a window longer than 1W to show data; a short probe that
    conflated the two would wrongly discard the whole measure - which a design
    probe did before this distinction went in.
    """
    rows = [
        ["Date", f"{TAG_10Y} - CLOSE", f"{TAG_2Y} - CLOSE"],
        [datetime.datetime(2026, 8, 4), 4.22537, None],
    ]
    block = parse_tshist_block(rows, [TAG_10Y, TAG_2Y])
    assert block.failures == {TAG_2Y: "empty"}


def test_newest_first_block_comes_back_ascending():
    rows = [
        ["Date", f"{TAG_10Y} - CLOSE"],
        [datetime.datetime(2026, 8, 4), 4.3],
        [datetime.datetime(2026, 8, 3), 4.2],
        [datetime.datetime(2026, 8, 2), 4.1],
    ]
    series = parse_tshist_block(rows, [TAG_10Y]).series[TAG_10Y]
    assert series.index.is_monotonic_increasing
    assert series.iloc[0] == pytest.approx(4.1)
    assert series.iloc[-1] == pytest.approx(4.3)


# ------------------------------------------------------------------ #
#                         the client, end to end                     #
# ------------------------------------------------------------------ #


def test_fetch_timeseries_batches_every_tag_into_one_call(velocity_data):
    client, app = _client(velocity_data)
    try:
        out = client.fetch_timeseries([TAG_10Y, TAG_2Y, TAG_VOL], "DAILY", period="1M")
    finally:
        client.close()
    assert set(out) == {TAG_10Y, TAG_2Y, TAG_VOL}
    assert len(app.formulas_for("CVTSHIST")) == 1


def test_fetch_timeseries_polls_past_the_sentinel(velocity_data):
    """The client must read the anchor repeatedly until it stops being pending."""
    client, app = _client(velocity_data, pending_reads=5)
    try:
        out = client.fetch_timeseries([TAG_10Y], "DAILY", period="1M")
    finally:
        client.close()
    assert TAG_10Y in out
    assert app.calculate_calls >= 5


def test_async_timeout_raises_with_the_tag_list(velocity_data):
    client, app = _client(velocity_data, pending_reads=-1)  # never settles
    client._poll_timeout = 0.2
    client._poll_interval = 0.01
    with pytest.raises(AsyncTimeoutError) as excinfo:
        client.fetch_timeseries([TAG_10Y], "DAILY", period="1M")
    assert TAG_10Y in str(excinfo.value)
    client.close()


def test_serial_dates_survive_the_whole_client_path(daily_index):
    data = FakeVelocityData(
        series={TAG_10Y: pd.Series(np.full(len(daily_index), 4.2), index=daily_index)},
        date_as_serial=True,
    )
    client, _ = _client(data)
    try:
        series = client.fetch_timeseries([TAG_10Y], "DAILY", period="1M")[TAG_10Y]
    finally:
        client.close()
    assert isinstance(series.index, pd.DatetimeIndex)
    assert series.index.max() == daily_index.max()


def test_bad_tag_is_surfaced_not_swallowed(velocity_data):
    client, _ = _client(velocity_data)
    try:
        out = client.fetch_timeseries([TAG_10Y, TAG_BAD], "DAILY", period="1M")
        failures = client.last_failures()
    finally:
        client.close()
    assert TAG_10Y in out
    assert TAG_BAD not in out
    assert failures[TAG_BAD] == "bad tag"


def test_readiness_probe_reports_ready(velocity_data):
    app = FakeExcelApp(velocity_data, pending_reads=1)
    status, workbook = probe_readiness(app, timeout=5.0, poll=0.0)
    assert status == "ready"
    assert workbook is not None


def test_readiness_probe_distinguishes_not_signed_in(velocity_data):
    """``#NAME?`` means the add-in is loaded but has not registered its UDFs.

    This must be its OWN verdict: "no Excel" is fixed by opening Excel, "not
    signed in" by signing in, and the two need different messages. It must also
    not be retried in a tight loop - the login runs through
    ``ExcelAsyncUtil.QueueAsMacro`` and needs Excel idle.
    """
    velocity_data.udf_registered = False
    app = FakeExcelApp(velocity_data, pending_reads=1)
    status, _ = probe_readiness(app, timeout=5.0, poll=0.0)
    assert status == "not_signed_in"


def test_readiness_probe_rejects_a_rot_zombie(velocity_data):
    """A zombie exposes an Application object whose ``Workbooks`` raises.

    ``GetActiveObject`` returns whatever registered in the Running Object Table
    first, and that can be an embedded instance with no Workbooks collection, so
    every candidate is probed rather than the first one trusted.
    """
    app = FakeExcelApp(velocity_data, dead=True)
    status, _ = probe_readiness(app, timeout=1.0, poll=0.0)
    assert status == "unusable"


def test_readiness_probe_reports_pending_rather_than_dead(velocity_data):
    """A slow login is 'pending', not 'dead'.

    After an Excel restart the Velocity login takes ~13 minutes and logs nothing
    in between; four launch paths were wrongly written off as failed before it
    landed. The probe must therefore report "still waiting" as its own state.
    """
    app = FakeExcelApp(velocity_data, pending_reads=-1)  # never settles
    status, _ = probe_readiness(app, timeout=0.05, poll=0.0)
    assert status == "pending"


def test_unsupported_frequency_names_the_accepted_set_and_calls_out_se10():
    client, _ = _client(FakeVelocityData())
    try:
        with pytest.raises(FrequencyError) as excinfo:
            client.fetch_timeseries([TAG_10Y], "SE10")
    finally:
        client.close()
    message = str(excinfo.value)
    assert "MI01" in message and "MONTHLY" in message
    assert "STREAMING" in message.upper()


# ------------------------------------------------------------------ #
#                          write discipline                          #
# ------------------------------------------------------------------ #


def test_blocks_never_overlap_a_live_region(velocity_data):
    """The crash trigger, turned into an assertion.

    In the real add-in, writing a block that overlaps a live ``CvFunction_*``
    region raises ``System.AccessViolationException`` from
    ``ExcelRegistration..ctor`` and takes the whole Excel process down, including
    the user's open workbook. The fake raises instead, so a regression in the
    anchoring discipline fails here rather than in the user's session.
    """
    client, app = _client(velocity_data)
    try:
        for _ in range(12):
            client.fetch_timeseries([TAG_10Y, TAG_2Y], "DAILY", period="1M")
    finally:
        client.close()
    assert len(app.formulas_for("CVTSHIST")) == 12
    anchors = app.anchors()
    assert len(set(anchors)) == len(anchors), "an anchor was reused"


def test_cursor_advances_past_the_measured_extent(velocity_data):
    """Blocks come back taller than predicted, so the cursor must measure, not guess."""
    client, app = _client(velocity_data)
    try:
        client.fetch_timeseries([TAG_10Y], "DAILY", period="1M")
        first_rows = app.blocks[0][3]
        client.fetch_timeseries([TAG_2Y], "DAILY", period="1M")
    finally:
        client.close()
    top_first, top_second = app.blocks[0][1], app.blocks[1][1]
    assert top_second > top_first + first_rows, "the second block started inside the first"


def test_teardown_never_clears_or_deletes(velocity_data):
    """Deleting a region with queued add-in actions outstanding is crash trigger #2.

    The client must close the workbook once, after a drain pause, and never clear
    or delete anything - the naive fix for the overlap crash IS the second crash.
    """
    client, app = _client(velocity_data)
    client.fetch_timeseries([TAG_10Y], "DAILY", period="1M")
    populated_before = len(app.workbooks_created[0].sheets[0].cells)
    client.close()
    assert app.workbooks_created[0].closed
    assert app.workbooks_created[0].saved is False
    assert len(app.workbooks_created[0].sheets[0].cells) == populated_before


def test_the_users_workbooks_are_never_touched(velocity_data):
    """The client works only in a scratch workbook it created."""
    app = FakeExcelApp(velocity_data, pending_reads=1)
    users_book = app.Workbooks.Add()
    users_book.sheets[0].cells[(1, 1)] = "the user's unsaved work"
    client = CitiVelocityExcelClient(app=app, drain_seconds=0.0)
    try:
        client.fetch_timeseries([TAG_10Y], "DAILY", period="1M")
    finally:
        client.close()
    assert users_book.sheets[0].cells[(1, 1)] == "the user's unsaved work"
    assert users_book.closed is False


# ------------------------------------------------------------------ #
#                        CVMETADATA and bisect                       #
# ------------------------------------------------------------------ #


def test_metadata_parses_description_and_history_bounds(velocity_data):
    client, _ = _client(velocity_data)
    try:
        rows = client.metadata([TAG_10Y, TAG_2Y])
    finally:
        client.close()
    assert rows[TAG_10Y].ok
    assert rows[TAG_10Y].history_start == datetime.datetime(2018, 1, 2)


def test_value_error_batch_is_bisected_to_the_poison_tag(velocity_data):
    """``#VALUE!`` poisons the WHOLE ``CVMETADATA`` batch, so it must be bisected.

    ``RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y`` does this in reality even when probed
    alone. Discarding the batch would lose every good tag in it.
    """
    poison = "RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y"
    velocity_data.poison_metadata_tags = {poison}
    client, app = _client(velocity_data)
    client._metadata_chunk_size = 4
    try:
        rows = client.metadata([TAG_10Y, TAG_2Y, poison])
    finally:
        client.close()
    assert rows[TAG_10Y].ok, "a good tag was lost to the poison tag"
    assert rows[poison].ok is False
    assert len(app.formulas_for("CVMETADATA")) > 1, "the batch was not bisected"


def test_metadata_all_failed_batch_has_no_header():
    """With no valid tag the add-in emits no header row at all."""
    rows = [
        ["Error: Invalid Tag / No data available. Tag = X", None, None],
        ["Error: Invalid Tag / No data available. Tag = Y", None, None],
    ]
    parsed = parse_metadata_block(rows, ["X", "Y"])
    assert all(not r.ok for r in parsed.values())


# ------------------------------------------------------------------ #
#                            validation                              #
# ------------------------------------------------------------------ #


def test_validate_classifies_valid_empty_and_bad(velocity_data, daily_index):
    velocity_data.series["RATES.OIS.USD_SOFR.PAR.7Y"] = pd.Series(dtype="float64")
    client, _ = _client(velocity_data)
    try:
        verdicts = client.validate([TAG_10Y, TAG_BAD, "RATES.OIS.USD_SOFR.PAR.7Y"])
    finally:
        client.close()
    assert verdicts[TAG_10Y] == "valid"
    assert verdicts[TAG_BAD] == "bad tag"
    assert verdicts["RATES.OIS.USD_SOFR.PAR.7Y"] in {"empty", "no column"}


def test_validate_refuses_to_report_when_the_controls_fail(velocity_data):
    """A validator that is itself broken reports failure everywhere.

    Two validators in the design session produced confident wrong numbers
    (0/1673 valid, and "13% fetchable"); controls are what caught them.
    """
    client, _ = _client(velocity_data)
    try:
        with pytest.raises(Exception) as excinfo:
            client.validate_with_controls([TAG_10Y], controls=["RATES.NOT.A.REAL.TAG"])
    finally:
        client.close()
    assert "control" in str(excinfo.value).lower()

r"""Regression tests for the merged-region tag-cache poison.

The defect
----------
``CitiVeloTagCache`` served swaption normal volatility under the OIS par-rate
tags: ``RATES.OIS.USD_SOFR.PAR.2Y`` returned ~102 on a day the 2y SOFR OIS was
4.24%. 36 of 44 USD_SOFR PAR parquets carried it, plus CAD_CORRA and
JPY_TONAR_LCH, back to 2015-10-08 - the USD swaption tags' own first day.

The mechanism, measured
-----------------------
1. ``_write_and_read`` reserves ``rows_needed + gap`` = 8 + 30 = 38 rows per
   anchor and then CORRECTS the cursor from the block's real extent via
   ``_advance_past(_extent(anchor))``. Both early-return paths - a poll timeout
   and an Excel error int - return BEFORE that correction, so the cursor stays 38
   rows below a formula that spills 2,700-5,500 rows.
2. The next ``CVTSHIST`` is therefore planted inside the previous block's
   footprint, and ``_extent`` (``CurrentRegion``, which its own docstring says
   "absorbs adjacent cells") hands back ONE region holding TWO blocks.
3. ``parse_tshist_block`` locates the FIRST ``Date`` header - the par block's -
   and then reads EVERY body row below it, including the second block's rows,
   mapping them by COLUMN POSITION.
4. ``DEFAULT_CHUNK_SIZE == 44 == len(ois_par_grid(...))``, so column j of the vol
   block is column j of the par block, one for one. A vol column that served
   nothing (Citi quotes no 4Y or 12Y swaption tenor) yields ``coerce_float(None)
   -> None`` and is skipped, which is why exactly 8 par tenors stayed clean at
   their exact positions instead of the rest shifting.
5. ``s[~s.index.duplicated(keep="first")]`` keeps the UPPER block's value where
   the dates coincide, so a short nightly tail request keeps its own few days and
   takes ~2,700 historical days from the vol block. ``cache.get`` then writes the
   whole returned series unclipped, banking an 11-year vol history from a 7-day
   request.

Every test here is paired with a MUTATION CHECK in the sense the sibling client
tests use: the guard is exercised against input that is wrong in exactly the way
the wire was wrong, and the assertion names the value that must NOT appear.
"""

from __future__ import annotations

import datetime
import pathlib

import pandas as pd
import pytest

from MDP.CitiVelocityExcel.block_parser import parse_tshist_block
from MDP.CitiVelocityExcel.excel_constants import GETTING_DATA_ERR, VALUE_ERR
from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.sanity import (
    TagSanityError,
    band_for_tag,
    implausible_rows,
)

PAR_10Y = "RATES.OIS.USD_SOFR.PAR.10Y"
PAR_2Y = "RATES.OIS.USD_SOFR.PAR.2Y"
PAR_1Y = "RATES.OIS.USD_SOFR.PAR.1Y"
VOL_A = "RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1M.1Y"
VOL_B = "RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1M.2Y"


# ------------------------------------------------------------------ #
#              1. the parser must not read a second block            #
# ------------------------------------------------------------------ #


def _merged_region(*, second_header: bool = True, formula_row: bool = True) -> list[list]:
    """One region holding a SHORT par block and, below it, a deep vol block.

    This is the shape ``CurrentRegion`` returns once the cursor has been left
    inside a previous block's footprint. The par block is a nightly tail request;
    the vol block carries history the par tags never had.
    """
    rows: list[list] = [
        ["=CVTSHIST(par)", None, None],
        ["Date", f"{PAR_10Y} - CLOSE", f"{PAR_2Y} - CLOSE"],
        [datetime.datetime(2026, 8, 4), 4.22537, 4.05114],
        [datetime.datetime(2026, 8, 3), 4.21000, 4.04000],
        [None, None, None],
    ]
    if formula_row:
        rows.append(["=CVTSHIST(vol)", None, None])
    if second_header:
        rows.append(["Date", f"{VOL_A} - CLOSE", f"{VOL_B} - CLOSE"])
    rows += [
        [datetime.datetime(2026, 8, 4), 76.5078, 80.1234],
        [datetime.datetime(2020, 1, 2), 55.0000, 60.0000],
        [datetime.datetime(2015, 10, 8), 39.9784, 54.7386],
    ]
    return rows


def test_a_second_block_in_the_region_never_reaches_the_series():
    """THE REGRESSION. Vol rows below a par block must not become par rates."""
    block = parse_tshist_block(_merged_region(), [PAR_10Y, PAR_2Y])

    s = block.series[PAR_10Y]
    assert list(s.index) == [pd.Timestamp("2026-08-03"), pd.Timestamp("2026-08-04")]
    assert s.loc[pd.Timestamp("2026-08-04")] == pytest.approx(4.22537)

    # The three values the poison put on disk, named so a regression is legible.
    assert 39.9784 not in set(s.to_numpy())
    assert 55.0 not in set(s.to_numpy())
    assert pd.Timestamp("2015-10-08") not in s.index


def test_the_foreign_rows_are_reported_not_silently_dropped():
    """A merged region is a defect upstream; truncating it quietly would hide it."""
    block = parse_tshist_block(_merged_region(), [PAR_10Y, PAR_2Y])
    assert block.foreign_rows > 0


def test_the_seam_is_found_without_a_header_or_a_formula_row():
    """Content alone must settle it: a CVTSHIST body is newest-first.

    If the region is cut so the second block's header and formula row fall
    outside it, the only remaining evidence is that the dates STOP descending.
    That has to be enough, or the guard depends on rows the region may not carry.
    """
    rows = _merged_region(second_header=False, formula_row=False)
    block = parse_tshist_block(rows, [PAR_10Y, PAR_2Y])
    s = block.series[PAR_10Y]
    assert pd.Timestamp("2015-10-08") not in s.index
    assert s.max() == pytest.approx(4.22537)


def test_a_repeated_stamp_across_a_chunk_seam_is_still_accepted():
    """The parser's own contract: "the block can repeat a stamp across chunk
    seams". Equality is not an ascending step and must not truncate."""
    rows = [
        ["Date", f"{PAR_10Y} - CLOSE"],
        [datetime.datetime(2026, 8, 4), 4.3],
        [datetime.datetime(2026, 8, 4), 4.3],
        [datetime.datetime(2026, 8, 3), 4.2],
        [datetime.datetime(2026, 8, 2), 4.1],
    ]
    s = parse_tshist_block(rows, [PAR_10Y]).series[PAR_10Y]
    assert len(s) == 3
    assert s.iloc[0] == pytest.approx(4.1)


def test_an_ordinary_single_block_is_untouched():
    rows = [
        ["=CVTSHIST(par)", None],
        ["Date", f"{PAR_10Y} - CLOSE"],
        [datetime.datetime(2026, 8, 4), 4.3],
        [datetime.datetime(2026, 8, 3), 4.2],
        [datetime.datetime(2026, 8, 2), 4.1],
    ]
    block = parse_tshist_block(rows, [PAR_10Y])
    assert block.foreign_rows == 0
    assert len(block.series[PAR_10Y]) == 3


def _planted_inside_a_spill() -> list[list]:
    """The layout the three structural markers CANNOT see.

    A short nightly-tail par request is planted 38 rows into a taller vol spill,
    so what follows the par block is that spill's CONTINUATION rows: no second
    header, no formula row, and - because the vol rows at that sheet depth carry
    dates months older than the par block's oldest - the sequence never stops
    descending. Only the requested WINDOW distinguishes them.
    """
    rows: list[list] = [
        ["=CVTSHIST(par)", None],
        ["Date", f"{PAR_10Y} - CLOSE"],
        [datetime.datetime(2026, 8, 21), 4.30],
        [datetime.datetime(2026, 8, 20), 4.29],
        [datetime.datetime(2026, 8, 19), 4.28],
    ]
    d = datetime.datetime(2026, 6, 15)
    for i in range(40):
        rows.append([d - datetime.timedelta(days=i), 76.5 + i * 0.1])
    return rows


def test_the_window_rejects_a_continuation_that_never_stops_descending():
    """THE SECOND REGRESSION, found by asking what the markers could not see.

    Without the window this returns 43 rows reaching back to May, 40 of them
    normal vol wearing a par rate's name - and reports zero failures.
    """
    rows = _planted_inside_a_spill()
    block = parse_tshist_block(
        rows, [PAR_10Y],
        window=(datetime.date(2026, 8, 14), datetime.date(2026, 8, 21)),
    )
    s = block.series[PAR_10Y]
    assert len(s) == 3
    assert s.max() == pytest.approx(4.30)
    assert not ((s < -1.0) | (s > 15.0)).any()
    assert block.foreign_rows == 40


def test_without_a_window_the_markers_alone_do_not_see_that_layout():
    """Names the residual honestly: this is why the window guard exists, and why
    a relative ``period=`` request is defended by the band rather than here."""
    block = parse_tshist_block(_planted_inside_a_spill(), [PAR_10Y])
    s = block.series[PAR_10Y]
    assert ((s < -1.0) | (s > 15.0)).any()


def test_a_bound_landing_on_a_holiday_does_not_lose_real_rows():
    """The pad is not decoration. The add-in resolves a bound against the tag's
    own calendar, so a request can legitimately answer a day or two outside it."""
    rows = [
        ["Date", f"{PAR_10Y} - CLOSE"],
        [datetime.datetime(2026, 8, 21), 4.30],
        [datetime.datetime(2026, 8, 20), 4.29],
        [datetime.datetime(2026, 8, 19), 4.28],
    ]
    block = parse_tshist_block(
        rows, [PAR_10Y],
        window=(datetime.date(2026, 8, 20), datetime.date(2026, 8, 20)),
    )
    assert len(block.series[PAR_10Y]) == 3
    assert block.foreign_rows == 0


def test_no_window_means_no_filtering():
    """A relative ``period=`` request has no window; guessing one would drop
    real rows, so the guard must not fire at all."""
    rows = [
        ["Date", f"{PAR_10Y} - CLOSE"],
        [datetime.datetime(2005, 1, 3), 4.10],
        [datetime.datetime(2026, 8, 21), 4.30],
    ]
    block = parse_tshist_block(rows, [PAR_10Y], window=None)
    assert block.foreign_rows == 0
    assert len(block.series[PAR_10Y]) == 2


def test_an_open_end_bounds_only_the_near_side():
    rows = [
        ["Date", f"{PAR_10Y} - CLOSE"],
        [datetime.datetime(2026, 8, 21), 4.30],
        [datetime.datetime(2015, 10, 8), 39.97],
    ]
    block = parse_tshist_block(
        rows, [PAR_10Y], window=(datetime.date(2026, 8, 14), None)
    )
    assert len(block.series[PAR_10Y]) == 1
    assert block.foreign_rows == 1


# ------------------------------------------------------------------ #
#            1b. the whole chain, not just the parse                  #
# ------------------------------------------------------------------ #


def test_a_merged_region_banks_nothing_foreign_end_to_end(tmp_path: pathlib.Path):
    """THE INTEGRATION. Every layer here is the production one.

    A 5-day nightly-tail PAR request whose region also holds 2,700 rows of the
    first 44-tag vol chunk. Before the fix this banked an 11-year vol history
    into 36 of the 44 par parquets. It must now bank 44 x 5 rows, none of them
    older than the requested start, and nothing under a tag nobody asked for.
    """
    from MDP.CitiVelocityExcel.tags import ois_par_grid
    from MDP.CitiVelocityExcel.vol.cube_data import cube_tags

    par = ois_par_grid("USD_SOFR")
    chunk = [t for t, m in cube_tags(currency="USD").items() if m[0] == "ATM"][:44]
    unserved = {"4Y", "12Y"}  # Citi quotes no swaption at these tenors

    par_days = pd.bdate_range("2026-08-17", "2026-08-21")
    vol_days = pd.bdate_range("2015-10-08", "2026-08-21")[::-1][:600]

    rows: list[list] = [["=CVTSHIST(par)"] + [None] * 44,
                        ["Date"] + [f"{t} - CLOSE" for t in par]]
    for d in par_days[::-1]:
        rows.append([d.to_pydatetime()] + [4.0 + i * 0.001 for i in range(44)])
    rows.append([None] * 45)
    rows.append(["=CVTSHIST(vol)"] + [None] * 44)
    rows.append(["Date"] + [f"{t} - CLOSE" for t in chunk])
    for d in vol_days:
        rows.append([d.to_pydatetime()] +
                    [None if t.rsplit(".", 1)[-1] in unserved else 60.0 + j * 0.5
                     for j, t in enumerate(chunk)])

    def fetcher(span_tags, span_freq, span_start, span_end, span_point):
        block = parse_tshist_block(
            rows, list(span_tags), price_point=span_point,
            window=(span_start, span_end),
        )
        assert block.foreign_rows > 0, "the guard did not notice the second block"
        return dict(block.series)

    cache = CitiVeloTagCache(base_dir=tmp_path)
    cache.get(par, "DAILY", start=datetime.date(2026, 8, 17),
              end=datetime.date(2026, 8, 21), fetcher=fetcher)

    written = sorted(p.name for p in (tmp_path / "DAILY" / "CLOSE").glob("*.parquet"))
    assert written, "nothing was banked at all"
    assert all(n.startswith("RATES.OIS.USD_SOFR.PAR.") for n in written), (
        f"a tag nobody asked for reached the disk: "
        f"{[n for n in written if not n.startswith('RATES.OIS.USD_SOFR.PAR.')][:3]}"
    )

    total = 0
    for tag in par:
        s = cache.read(tag, "DAILY")
        if s is None:
            continue
        total += len(s)
        assert s.index.min() >= pd.Timestamp("2026-08-17"), (
            f"{tag} was extended back to {s.index.min()} - the vol block's history"
        )
        assert not ((s < -1.0) | (s > 15.0)).any(), f"{tag} holds a non-rate"
    assert total == len(par) * len(par_days), (
        f"banked {total} rows, expected {len(par) * len(par_days)}"
    )


# ------------------------------------------------------------------ #
#          2. the cache must not write a tag it was not asked for     #
# ------------------------------------------------------------------ #


def test_get_refuses_a_fetcher_key_it_did_not_request(tmp_path: pathlib.Path):
    """A writer that can address a tag it does not own IS the defect.

    ``get`` wrote ``for tag, series in fetched.items()`` with no check against
    the tags it asked for, so any fetcher could bank anything under any name.
    """
    cache = CitiVeloTagCache(base_dir=tmp_path)
    idx = pd.DatetimeIndex(["2026-08-03", "2026-08-04"])

    def fetcher(tags, freq, start, end, price_point):
        return {
            PAR_10Y: pd.Series([4.2, 4.3], index=idx),
            VOL_A: pd.Series([76.5, 77.0], index=idx),   # never requested
        }

    out = cache.get([PAR_10Y], "DAILY", fetcher=fetcher)

    assert PAR_10Y in out
    assert cache.path(PAR_10Y, "DAILY").is_file()
    assert not cache.path(VOL_A, "DAILY").is_file(), (
        "a fetcher key that was not requested reached the disk"
    )


def test_get_still_serves_the_requested_tags_when_a_stray_key_is_present(
    tmp_path: pathlib.Path,
):
    cache = CitiVeloTagCache(base_dir=tmp_path)
    idx = pd.DatetimeIndex(["2026-08-03", "2026-08-04"])

    def fetcher(tags, freq, start, end, price_point):
        return {PAR_10Y: pd.Series([4.2, 4.3], index=idx), VOL_A: pd.Series([76.5, 77.0], index=idx)}

    out = cache.get([PAR_10Y], "DAILY", fetcher=fetcher)
    assert out[PAR_10Y].tolist() == [4.2, 4.3]


# ------------------------------------------------------------------ #
#           3. a value that cannot be a par rate cannot land          #
# ------------------------------------------------------------------ #


def test_band_for_tag_knows_the_par_family():
    lo, hi = band_for_tag(PAR_2Y)
    assert lo <= 0.0 and hi >= 10.0
    assert not (lo <= 102.0 <= hi)


def test_a_vol_series_is_refused_under_a_par_tag(tmp_path: pathlib.Path):
    """The blunt check that would have caught this on day one, at the WRITE
    boundary rather than at every read site."""
    cache = CitiVeloTagCache(base_dir=tmp_path)
    poisoned = pd.Series(
        [102.0, 4.24], index=pd.DatetimeIndex(["2023-06-01", "2026-08-04"])
    )
    with pytest.raises(TagSanityError) as exc:
        cache.write(PAR_2Y, "DAILY", poisoned)
    assert "102" in str(exc.value)
    assert not cache.path(PAR_2Y, "DAILY").is_file()


def test_a_real_par_series_writes_normally(tmp_path: pathlib.Path):
    cache = CitiVeloTagCache(base_dir=tmp_path)
    good = pd.Series([4.24, 4.03], index=pd.DatetimeIndex(["2023-06-01", "2026-08-04"]))
    merged = cache.write(PAR_2Y, "DAILY", good)
    assert len(merged) == 2
    assert cache.path(PAR_2Y, "DAILY").is_file()


def test_a_vol_tag_may_hold_a_vol_number(tmp_path: pathlib.Path):
    """The band is per FAMILY. 76.5 is impossible for a par rate and ordinary
    for a normal vol in bp; a single global band would break the vol warm."""
    cache = CitiVeloTagCache(base_dir=tmp_path)
    vol = pd.Series([76.5078], index=pd.DatetimeIndex(["2026-08-04"]))
    cache.write(VOL_A, "DAILY", vol)
    assert cache.path(VOL_A, "DAILY").is_file()


def test_an_unknown_family_is_not_gated(tmp_path: pathlib.Path):
    """No band means no opinion. A guard that guessed would block real data."""
    cache = CitiVeloTagCache(base_dir=tmp_path)
    assert band_for_tag("SOMETHING.WE.DO.NOT.KNOW") is None
    cache.write("SOMETHING.WE.DO.NOT.KNOW", "DAILY",
                pd.Series([1e9], index=pd.DatetimeIndex(["2026-08-04"])))


def test_implausible_rows_names_the_dates(tmp_path: pathlib.Path):
    s = pd.Series([102.0, 4.24, 164.6],
                  index=pd.DatetimeIndex(["2023-06-01", "2026-08-04", "2023-06-02"]))
    bad = implausible_rows(PAR_2Y, s)
    assert set(bad.index) == {pd.Timestamp("2023-06-01"), pd.Timestamp("2023-06-02")}


# ------------------------------------------------------------------ #
#        4. the cursor must never be left inside a live spill         #
# ------------------------------------------------------------------ #


class _FakeRegion:
    """A spill 2,700 rows tall, starting at the anchor - a DAILY par grid."""

    def __init__(self, row: int, n_rows: int):
        self.Row = row
        self.Rows = type("R", (), {"Count": n_rows})()
        self.Value = [["Date"], [None]]


def _client_over_a_spill(settled_value, *, spill_rows: int, extent_raises: bool = False):
    """A client whose formula settles to ``settled_value`` over a spill."""
    from MDP.CitiVelocityExcel import com_client as cc

    client = cc.CitiVelocityExcelClient.__new__(cc.CitiVelocityExcelClient)
    client._row = 1
    client._gap = 30
    client._logger = cc._logger
    client.calls = 0
    client._app = type("App", (), {"CalculateUntilAsyncQueriesDone": lambda self: None})()
    client._ws = type("WS", (), {"Range": lambda self, a: type("R", (), {"Formula": None})()})()
    client._check_alive = lambda: None
    client._anchor = lambda rows_needed: "B1"
    client._settle = lambda cell, timeout=None: (settled_value, 0.0)

    def _extent(anchor):
        if extent_raises:
            raise RuntimeError("Excel is wedged; the extent cannot be measured")
        return _FakeRegion(row=1, n_rows=spill_rows)

    client._extent = _extent
    return client


@pytest.mark.parametrize("settled, what", [
    (GETTING_DATA_ERR, "a poll timeout"),
    (VALUE_ERR, "an Excel error int"),
])
def test_the_cursor_advances_past_a_spill_on_the_early_return_paths(settled, what):
    """THE CAUSE, tested where it lives.

    ``_write_and_read`` reserves 8 + 30 = 38 rows provisionally and corrects the
    cursor from the real extent. Both early returns used to fire BEFORE that
    correction, so ``self._row`` stayed 39 while the block went on to fill 2,700
    rows - and the next formula was planted inside it.
    """
    client = _client_over_a_spill(settled, spill_rows=2700)
    rows, _value, _elapsed = client._write_and_read("=CVTSHIST(...)", rows_needed=8)
    assert rows == []
    assert client._row > 2700, (
        f"after {what} the cursor stayed at row {client._row}, inside a 2,700-row "
        "spill; the next anchor lands in a live block and the two regions merge"
    )


def test_a_spill_taller_than_the_worst_case_is_still_cleared():
    """Isolates ``_advance_past``. An MI01 block runs well past
    ``_WORST_CASE_SPILL_ROWS``, so the constant alone is not enough and the
    MEASURED extent has to be honoured too."""
    client = _client_over_a_spill(GETTING_DATA_ERR, spill_rows=12_000)
    client._write_and_read("=CVTSHIST(...)", rows_needed=8)
    assert client._row > 12_000, (
        f"cursor at {client._row}: the measured extent was ignored and the "
        "constant floor is short of this block"
    )


def test_the_cursor_still_clears_the_block_when_the_extent_cannot_be_measured():
    """Isolates the worst-case skip, in the case it exists for.

    ``_extent`` is COM and can fail on exactly the wedged Excel that produced the
    timeout. With no measurement at all the cursor must still clear a full DAILY
    history rather than staying at the 38-row provisional reservation.
    """
    from MDP.CitiVelocityExcel.com_client import _WORST_CASE_SPILL_ROWS

    client = _client_over_a_spill(GETTING_DATA_ERR, spill_rows=0, extent_raises=True)
    client._write_and_read("=CVTSHIST(...)", rows_needed=8)
    assert client._row >= 1 + _WORST_CASE_SPILL_ROWS, (
        f"cursor at {client._row} with no usable extent; the next anchor lands "
        "inside whatever this formula goes on to spill"
    )

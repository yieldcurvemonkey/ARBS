"""The unwind-lineage sidecar.

Every test here pins a failure that is *silent* in production: a row that is
never written, a chain that stops one hop early, a publication time read in the
wrong timezone, a flip applied twice. None of them raise on their own.

Offline by design -- the DTCC transport and the tape lookup are both injected,
so the whole file runs with no network and no database.
"""
from __future__ import annotations

import argparse
import datetime
import io
import zipfile

import pandas as pd
import pytest

from SDRUtils.dealer_direction import lineage as lin

DI = lin.DI
ODI = lin.ODI

FILE_DATE = datetime.date(2026, 6, 16)

# The two-row zip every fetch test is built from: one ordinary NEWT executed on
# the file date, and one termination whose #96 is frozen two years earlier --
# which is the row `fetch_historical_reports` masks away.
_CSV_HEADER = (
    "Dissemination Identifier,Original Dissemination Identifier,Action type,"
    "Event type,Event timestamp,Execution Timestamp,Notional currency-Leg 1,"
    "UPI FISN,Other payment amount,Fixed rate-Leg 1\n"
)
_ROW_NEWT = (
    "900000000001,,NEWT,TRAD,2026-06-16T14:15:36Z,2026-06-16T14:15:36Z,USD,"
    "NA/Swap OIS USD,,3.5\n"
)
_ROW_TERM_STALE = (
    "900000000002,700000000000,TERM,ETRM,2026-06-16T15:00:00Z,2024-04-01T14:15:36Z,USD,"
    "NA/Swap OIS USD,1020000,\n"
)


def _zip_of(csv_text: str, *, member="CFTC_CUMULATIVE_RATES_2026_06_16.csv",
            mtime=(2026, 6, 16, 10, 0, 0)) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo(member, date_time=mtime), csv_text)
    buf.seek(0)
    return buf


def _source(csv_text: str):
    def _src(date_string: str):
        return _zip_of(csv_text)
    return _src


# --------------------------------------------------------------------------
# The defect this whole sidecar exists to route around.
# --------------------------------------------------------------------------

def test_a_lifecycle_row_older_than_the_file_survives_the_fetch(tmp_path):
    """Measured 2026-08-06: `fetch_historical_reports(start=end=D)` drops 257 of
    624 terminations (41.2%) because it masks on `Execution Timestamp.dt.date`
    before persisting, and a TERM carries the *original's* execution date --
    median 89 days before the file date, max 10 years. The whole sidecar exists
    because that row must survive; if a future cleanup reintroduces any date
    mask here, this is what fails.
    """
    df = lin.fetch_raw_day(FILE_DATE, root=tmp_path,
                           zip_source=_source(_CSV_HEADER + _ROW_NEWT + _ROW_TERM_STALE))
    assert len(df) == 2
    term = df[df["Action type"] == "TERM"].iloc[0]
    assert term["Execution Timestamp"].date() == datetime.date(2024, 4, 1)
    assert term["file_date"] == FILE_DATE
    # and it is on disk, not just in the returned frame
    again = pd.read_parquet(lin.raw_day_path(FILE_DATE, root=tmp_path))
    assert len(again) == 2


def test_the_raw_cache_is_not_the_sdr_cache(tmp_path):
    """Two DTCC readers with different filtering now exist. They must not be able
    to write into each other's tree -- a lineage consumer reading a masked frame
    would silently lose 41% of its population and report a clean 100% coverage
    of what remained.
    """
    lin.fetch_raw_day(FILE_DATE, root=tmp_path, zip_source=_source(_CSV_HEADER + _ROW_NEWT))
    written = [p for p in tmp_path.rglob("*.parquet")]
    assert written, "nothing cached"
    for p in written:
        assert "sdr_cache" not in str(p).replace("\\", "/")
        assert lin.RAW_SUBDIR in str(p).replace("\\", "/")


def test_a_cached_day_is_served_without_refetching(tmp_path):
    lin.fetch_raw_day(FILE_DATE, root=tmp_path, zip_source=_source(_CSV_HEADER + _ROW_TERM_STALE))

    def _explode(date_string):
        raise AssertionError("refetched a day that is already cached")

    df = lin.fetch_raw_day(FILE_DATE, root=tmp_path, zip_source=_explode)
    assert len(df) == 1


def test_an_empty_day_raises_and_writes_nothing(tmp_path):
    """A backfill in this repo once recorded days as `ok` on exit code 0 while
    the upstream returned an empty frame, destroying six days of data. An empty
    upstream must be an exception, never a zero-row parquet that later reads as
    a legitimately quiet day.
    """
    with pytest.raises(lin.EmptyDTCCDay):
        lin.fetch_raw_day(FILE_DATE, root=tmp_path, zip_source=lambda ds: None)
    assert not lin.raw_day_path(FILE_DATE, root=tmp_path).exists()

    with pytest.raises(lin.EmptyDTCCDay):
        lin.fetch_raw_day(FILE_DATE, root=tmp_path, zip_source=_source(_CSV_HEADER))
    assert not lin.raw_day_path(FILE_DATE, root=tmp_path).exists()


# --------------------------------------------------------------------------
# Multi-hop resolution.
#
# Re-measured on the unfiltered union of 2026-06-15..18 (100,079 raw rows,
# 17,305 pointer rows): 197 TERM->TERM pointers, of which 193 point at
# THEMSELVES and 4 are genuine -- and all 4 land on a self-pointer, so they
# terminate one hop later. `multi_hop` was 0 and `max_hops` 1 over the whole
# union. The transitive walk is kept because a partial-termination chain is
# representable and the walk is free, NOT because that week required it; the
# earlier "43 TERM->TERM pointers, therefore chains" reading counted
# self-pointers as chain links.
# --------------------------------------------------------------------------

def _raw(rows) -> pd.DataFrame:
    cols = [DI, ODI, "Action type", "Event type", "Event timestamp", "Execution Timestamp"]
    df = pd.DataFrame(rows, columns=cols)
    for c in ("Event timestamp", "Execution Timestamp"):
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    df["file_date"] = FILE_DATE
    return df


def test_chained_partial_terminations_walk_all_the_way_to_the_newt():
    """Appendix F Example 1 draws a star -- D2 pointing at the original. A chain
    of partial terminations is not representable in a star, and single-hop
    resolution stops at the middle termination and calls the original
    unresolved. Measured frequency of a genuine chain in 2026-06-15..18: zero
    (see the section header), so this pins the walk against a shape the data
    permits rather than one it exhibited that week.
    """
    raw = _raw([
        ("300", None, "NEWT", "TRAD", "2026-06-01T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("301", "300", "TERM", "ETRM", "2026-06-10T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("302", "301", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z"),
    ])
    out = lin.resolve_lineage(raw).set_index("dissemination_id")
    assert out.loc["302", "resolved_original_id"] == "300"
    assert out.loc["302", "hops"] == 2
    assert out.loc["301", "hops"] == 1
    assert out.loc["302", "terminal_action"] == "NEWT"


def test_a_star_of_partials_still_resolves_at_one_hop():
    raw = _raw([
        ("300", None, "NEWT", "TRAD", "2026-06-01T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("301", "300", "TERM", "ETRM", "2026-06-10T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("302", "300", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z"),
    ])
    out = lin.resolve_lineage(raw).set_index("dissemination_id")
    assert list(out.loc[["301", "302"], "hops"]) == [1, 1]
    assert set(out["resolved_original_id"]) == {"300"}


def test_a_row_that_points_at_itself_is_not_its_own_original():
    """361 rows in the 2026-06-15..18 week carry `ODI == own DI` -- 111 of them
    TERM/ETRM. Walking that to a terminal of "itself" would book the unwind as
    resolved and hand a consumer the termination row in place of the original
    trade, which the direction-agreement check would then compare against
    itself. It carries no lineage, and it must not look like it does.

    It is also how the recorded "43 TERM->TERM pointers, therefore chains" was
    manufactured: a self-pointer trivially satisfies "the target is a TERM in
    this week's frame". Re-measured on the same week: 193 of 197.
    """
    raw = _raw([("301", "301", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z")])
    out = lin.resolve_lineage(raw).iloc[0]
    assert out["status"] == lin.ST_SELF_POINTER
    assert out["hops"] == 0
    assert pd.isna(out["reach_back_days"])


def test_a_walk_that_dies_on_a_self_pointer_is_not_resolved_lineage():
    """The self-pointer guard covers the row that points at itself. The row that
    points AT a self-pointer walks one hop, finds no further parent, finds the
    id in the window and -- before this was fixed -- was booked
    ``RESOLVED_RAW_ONLY`` with a MODI/TERM/CORR handed over as "the original".

    Measured on the unfiltered union of 2026-06-15..18: every one of the 30
    resolved rows whose terminal is not a NEWT died on a self-pointer (17 MODI,
    11 TERM, 2 CORR). Downstream that makes ``direction_agreement`` compare a
    termination against a termination.

    The tape lookup must not rescue it either: a MODI is a print the tape holds,
    so a status decided on "is the terminal in the tape" relabels exactly the
    joinable rows ``RESOLVED_TAPE`` and the defect survives where it does the
    most damage.
    """
    raw = _raw([
        ("300", "300", "MODI", "TRAD", "2026-06-15T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("301", "300", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z"),
    ])
    out = lin.resolve_lineage(
        raw,
        exec_ts_lookup=lambda ids: {"300": pd.Timestamp("2026-06-01 10:00:00", tz="UTC")},
    ).set_index("dissemination_id")

    assert out.loc["300", "status"] == lin.ST_SELF_POINTER
    assert out.loc["301", "status"] == lin.ST_TERMINAL_SELF_POINTER
    # the id is still reported -- it names something, it just is not an original
    assert out.loc["301", "resolved_original_id"] == "300"
    assert pd.isna(out.loc["301", "original_execution_timestamp"])
    assert pd.isna(out.loc["301", "reach_back_days"])
    # and it does not count towards coverage
    assert lin.coverage_summary(out.reset_index())["resolved"] == 0


def test_a_chain_that_finishes_on_the_last_allowed_hop_is_resolved_not_capped():
    """``max_hops`` is a guard against an unbounded walk, not a truncation. A
    chain that terminates in exactly ``max_hops`` hops was being labelled
    ``MAX_HOPS`` -- with the correct terminal id but its
    ``original_execution_timestamp`` discarded, so the reach-back of a fully
    resolved chain was silently lost and the row was booked as a pathology.
    """
    raw = _raw([
        ("500", None, "NEWT", "TRAD", "2026-06-01T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("501", "500", "MODI", "TRAD", "2026-06-02T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("502", "501", "MODI", "TRAD", "2026-06-03T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("503", "502", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z"),
    ])
    out = lin.resolve_lineage(raw, max_hops=3).set_index("dissemination_id")
    assert out.loc["503", "hops"] == 3
    assert out.loc["503", "status"] == lin.ST_RESOLVED_RAW_ONLY
    assert out.loc["503", "original_execution_timestamp"] == pd.Timestamp("2026-06-01 10:00", tz="UTC")
    assert out.loc["503", "reach_back_days"] == pytest.approx(15.0)

    # a chain that genuinely outruns the cap is still named as such
    capped = lin.resolve_lineage(raw, max_hops=2).set_index("dissemination_id")
    assert capped.loc["503", "status"] == lin.ST_MAX_HOPS


def test_resolution_survives_a_frame_whose_index_is_not_unique():
    """`pd.concat([a, b])` without `ignore_index=True` is the ordinary way to
    build the union, and it used to raise "The truth value of a Series is
    ambiguous" from inside the walk -- a public entry point that is a trap for
    every caller that does not happen to use `load_raw_days`.
    """
    raw = pd.concat([
        _raw([("300", None, "NEWT", "TRAD", "2026-06-01T10:00:00Z", "2026-06-01T10:00:00Z")]),
        _raw([("301", "300", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z")]),
    ])
    assert not raw.index.is_unique
    out = lin.resolve_lineage(raw)
    assert list(out["dissemination_id"]) == ["301"]
    assert out.iloc[0]["resolved_original_id"] == "300"


def test_a_pointer_cycle_is_named_not_looped():
    raw = _raw([
        ("401", "402", "MODI", "TRAD", "2026-06-16T10:00:00Z", "2026-06-16T10:00:00Z"),
        ("402", "401", "MODI", "TRAD", "2026-06-16T10:01:00Z", "2026-06-16T10:01:00Z"),
    ])
    out = lin.resolve_lineage(raw).set_index("dissemination_id")
    assert set(out["status"]) == {lin.ST_CYCLE}


def test_rows_without_a_pointer_are_not_keys_in_the_store():
    """NEWT carries a pointer on 0.00% of rows. Writing one row per NEWT would
    triple the store for ids that by measurement can never be looked up.
    """
    raw = _raw([
        ("300", None, "NEWT", "TRAD", "2026-06-16T10:00:00Z", "2026-06-16T10:00:00Z"),
        ("301", "300", "TERM", "ETRM", "2026-06-16T11:00:00Z", "2026-06-01T10:00:00Z"),
    ])
    out = lin.resolve_lineage(raw)
    assert list(out["dissemination_id"]) == ["301"]


# --------------------------------------------------------------------------
# Status vocabulary and reach-back.
# --------------------------------------------------------------------------

def test_a_pointer_out_of_the_window_resolves_through_the_tape_lookup():
    raw = _raw([
        ("301", "200", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-03-18T10:00:00Z"),
    ])
    out = lin.resolve_lineage(
        raw,
        exec_ts_lookup=lambda ids: {"200": pd.Timestamp("2026-03-18 10:00:00", tz="UTC")},
    ).iloc[0]
    assert out["status"] == lin.ST_RESOLVED_TAPE
    assert out["resolved_original_id"] == "200"
    assert out["hops"] == 1
    # reach-back is (unwind event timestamp - the ORIGINAL's execution), the
    # definition the 75.5 / 90.7 / 95.6 percentiles were measured under.
    assert out["reach_back_days"] == pytest.approx(90.0, abs=1e-6)


def test_an_in_window_original_that_the_tape_also_holds_is_flagged_as_tape_resolved():
    """RESOLVED_TAPE is the flippable population, so it must not depend on
    whether the original happened to print inside the fetched window. Stopping
    the lookup at "I already have a row for that id" files same-week
    terminations -- 75.5% of them, by the reach-back -- as RAW_ONLY and hides
    them from the only join a consumer cares about.
    """
    raw = _raw([
        ("300", None, "NEWT", "TRAD", "2026-06-16T10:00:00Z", "2026-06-16T10:00:00Z"),
        ("301", "300", "TERM", "ETRM", "2026-06-16T11:00:00Z", "2026-06-01T10:00:00Z"),
    ])
    out = lin.resolve_lineage(
        raw, exec_ts_lookup=lambda ids: {"300": pd.Timestamp("2026-06-16 10:00:00", tz="UTC")},
    ).iloc[0]
    assert out["status"] == lin.ST_RESOLVED_TAPE


def test_a_pointer_older_than_the_tape_is_labelled_pre_tape_not_missing():
    """5.6% of TERMs reference a print older than the tape and resolved 0/206.
    Calling those `missing` would book a data defect against a print that
    correctly does not exist.
    """
    raw = _raw([
        ("301", "5", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2001-03-18T10:00:00Z"),
        ("302", "9" * 18, "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("303", "555", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z"),
    ])
    out = lin.resolve_lineage(raw, exec_ts_lookup=lambda ids: {},
                              tape_id_range=(100, 1000)).set_index("dissemination_id")
    assert out.loc["301", "status"] == lin.ST_PRE_TAPE
    assert out.loc["302", "status"] == lin.ST_ABOVE_RANGE
    assert out.loc["303", "status"] == lin.ST_MISSING_IN_RANGE


def test_an_unparseable_pointer_is_unresolved_not_missing_from_the_tape():
    """`MISSING_IN_RANGE` means "inside the tape's id range and genuinely
    absent" -- a print the tape never ingested. A pointer that is not a number
    at all is neither inside nor outside that range, and filing it as MISSING
    books a tape ingestion defect against a malformed field.
    """
    raw = _raw([("301", "not-an-id", "TERM", "ETRM", "2026-06-16T10:00:00Z",
                 "2026-06-01T10:00:00Z")])
    out = lin.resolve_lineage(raw, exec_ts_lookup=lambda ids: {},
                              tape_id_range=(100, 1000)).iloc[0]
    assert out["status"] == lin.ST_UNRESOLVED


def test_the_terminal_is_reported_even_when_it_does_not_resolve():
    """An unresolved pointer still names something. Dropping the id would make
    the 43 chained TERM->TERM pointers indistinguishable from unpointed rows.
    """
    raw = _raw([("301", "555", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z")])
    out = lin.resolve_lineage(raw, exec_ts_lookup=lambda ids: {}).iloc[0]
    assert out["resolved_original_id"] == "555"
    assert pd.isna(out["reach_back_days"])


def test_identifiers_that_round_tripped_through_a_float_still_join():
    """`123.0` and `123` are the same dissemination id. A float round trip
    through pandas is what silently makes a pointer unresolvable.
    """
    raw = _raw([
        ("300.0", None, "NEWT", "TRAD", "2026-06-16T10:00:00Z", "2026-06-16T10:00:00Z"),
        ("301", " 300 ", "TERM", "ETRM", "2026-06-16T11:00:00Z", "2026-06-01T10:00:00Z"),
    ])
    out = lin.resolve_lineage(raw).iloc[0]
    assert out["resolved_original_id"] == "300"
    assert out["hops"] == 1
    # the status is the point: without the strip the join MISSES and the row is
    # booked UNRESOLVED, i.e. as a tape ingestion gap. Asserting only the id and
    # the hop count leaves that invisible, because the pointer side normalises
    # through `.strip()` either way.
    assert out["status"] == lin.ST_RESOLVED_RAW_ONLY


# --------------------------------------------------------------------------
# What the coverage numbers count.
# --------------------------------------------------------------------------

def test_coverage_summary_counts_only_walks_that_reached_an_original():
    """The numbers the backfill prints and the report quotes. A status that is
    not a resolution -- SELF_POINTER, TERMINAL_SELF_POINTER, UNRESOLVED -- must
    not be inside `resolved`, or the sidecar reports coverage of a population it
    did not resolve.
    """
    raw = _raw([
        ("300", None, "NEWT", "TRAD", "2026-06-01T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("301", "300", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("302", "302", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("303", "302", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("304", "999", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z"),
    ])
    got = lin.coverage_summary(lin.resolve_lineage(raw))
    assert got["n"] == 4
    assert got["resolved"] == 1
    assert got["resolved_pct"] == 25.0
    assert got["by_status"][lin.ST_SELF_POINTER] == 1
    assert got["by_status"][lin.ST_TERMINAL_SELF_POINTER] == 1
    assert got["multi_hop"] == 0
    assert got["max_hops"] == 1
    assert got["reach_back_cum_pct"]["<=7d"] == 0.0
    assert got["reach_back_cum_pct"]["<=63d"] == 100.0


def test_a_negative_reach_back_is_counted_where_a_reader_can_see_it():
    """An "original" executed AFTER the unwind that tears it up is impossible;
    6 such rows are in the measured week. They land in the `<=0d` bucket and
    inflate every cumulative percentile below them, so the count has to be
    reported next to the percentiles rather than left to be inferred.
    """
    raw = _raw([
        ("300", None, "NEWT", "TRAD", "2026-06-20T10:00:00Z", "2026-06-20T10:00:00Z"),
        ("301", "300", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z"),
    ])
    out = lin.resolve_lineage(raw)
    assert out.iloc[0]["reach_back_days"] == pytest.approx(-4.0)
    assert lin.coverage_summary(out)["reach_back_negative"] == 1


# --------------------------------------------------------------------------
# Why `core/graph_resolver.build_synthetic_uti_mapping` is not used.
# --------------------------------------------------------------------------

def test_graph_resolver_anchors_on_the_termination_when_the_original_is_out_of_frame():
    """The existing resolver is undirected connected components plus an anchor
    rule of "earliest NEWT, else earliest timestamp". Whenever the original is
    outside the loaded window the component holds no NEWT, so the anchor falls
    on the *termination itself* and the pointer target is discarded. That is the
    opposite of lineage, at any frequency: measured on the 4-day union of
    2026-06-15..18, 28.1% of pointer rows name an id that is not in the window
    at all (`UNRESOLVED`, 4,864 of 17,305). It is a shape defect, not a rate.
    """
    from SDRUtils.core.graph_resolver import build_synthetic_uti_mapping

    raw = _raw([("301", "200", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-03-18T10:00:00Z")])
    mapping, _ = build_synthetic_uti_mapping(raw)
    assert mapping["301"] == "301"          # anchors on the unwind, not the original
    assert mapping["200"] == "301"

    ours = lin.resolve_lineage(raw).iloc[0]
    assert ours["resolved_original_id"] == "200"


# --------------------------------------------------------------------------
# The publication clock.
# --------------------------------------------------------------------------

def test_the_zip_member_mtime_is_eastern_and_comes_back_as_utc():
    """Validated against the listing's `dissemDTM` on 10 live slices: zip mtime
    read as ET and converted sits 2-4 s early, median |delta| 3.0 s, 10/10. Read
    as UTC instead it would be four hours wrong and still perfectly plausible.
    """
    buf = _zip_of(_CSV_HEADER + _ROW_NEWT, member="CFTC_SLICE_RATES_2026_06_16_100.csv",
                  mtime=(2026, 6, 16, 10, 0, 0))
    assert lin.slice_publication_time(buf) == pd.Timestamp("2026-06-16 14:00:00", tz="UTC")


def test_a_member_stamped_in_the_dst_fall_back_hour_takes_the_later_reading():
    """01:30 on 2026-11-01 happens twice in New York, so the wall clock alone
    cannot say which. The default `tz_localize` behaviour is to RAISE, and
    `fetch_slice_publications` swallows every per-slice exception -- so one hour
    a year of publication times would vanish with nothing in the output to show
    it. Of the two readings, EST (06:30Z) is the later; EDT (05:30Z) would claim
    a print was public an hour before it was, which is the one direction this
    clock must never err in.
    """
    buf = _zip_of(_CSV_HEADER + _ROW_NEWT, member="CFTC_SLICE_RATES_2026_11_01_100.csv",
                  mtime=(2026, 11, 1, 1, 30, 0))
    assert lin.slice_publication_time(buf) == pd.Timestamp("2026-11-01 06:30:00", tz="UTC")


def test_slice_enumeration_names_the_files_dtcc_actually_serves():
    names = lin.slice_date_strings(datetime.date(2026, 6, 16), [1, 100, 1333])
    assert names[:2] == ["2026_06_16_1", "2026_06_16_100"]
    assert len(names) == 3


def test_the_slice_scan_reads_the_publication_time_out_of_every_member():
    """The measured clock's only producer, and it had no test at all."""
    def _src(ds):
        return _zip_of(_CSV_HEADER + _ROW_NEWT,
                       member=f"CFTC_SLICE_RATES_{ds}.csv", mtime=(2026, 6, 16, 10, 0, 0))

    got = lin.fetch_slice_publications(FILE_DATE, [1, 2], slice_source=_src, workers=2)
    assert list(got[DI]) == ["900000000001"]          # first publication wins
    clock = lin.PublicationClock.from_frame(got)
    assert len(clock) == 1
    assert clock.published_at("900000000001") == pd.Timestamp("2026-06-16 14:00:00", tz="UTC")


def test_a_slice_scan_that_reads_nothing_at_all_is_an_error_not_an_empty_clock():
    """Every per-slice failure is swallowed on purpose -- one corrupt member must
    cost one slice, not the day. But when EVERY slice of a non-empty request
    fails, the function used to return a 0-row frame; `PublicationClock` then has
    length 0 and every row silently falls back to the Appendix C 60-minute
    indeterminate delay in place of a 5.23-minute measured median, with nothing
    but `visibility_source` to show for it. Zero rows is the failure this repo
    has already paid for once.
    """
    with pytest.raises(lin.EmptyDTCCDay):
        lin.fetch_slice_publications(FILE_DATE, [1, 2, 3],
                                     slice_source=lambda ds: None, workers=2)
    # an empty request is not a failure -- there was nothing to read
    assert lin.fetch_slice_publications(FILE_DATE, [], slice_source=lambda ds: None).empty


def test_the_availability_clock_prefers_the_measured_time_and_says_which_it_used():
    """`Clocks.visibility_source` exists so a consumer can gate on it. A measured
    publication time and an Appendix C legal estimate are not interchangeable --
    the measured NEWT/OIS/USD lag is 5.23 min median against a 60 min
    indeterminate legal delay.
    """
    clock = lin.PublicationClock({"900000000001": pd.Timestamp("2026-06-16 14:20:00", tz="UTC")})
    execution = pd.Timestamp("2026-06-16 14:15:00", tz="UTC")

    ts, source = clock.visibility("900000000001", execution)
    assert source == lin.VISIBILITY_SLICE_MTIME
    assert ts == pd.Timestamp("2026-06-16 14:20:00", tz="UTC")

    ts2, source2 = clock.visibility("not_measured", execution)
    assert source2 == lin.VISIBILITY_APPENDIX_C
    assert ts2 > execution


def test_the_appendix_c_fallback_is_the_frozen_estimate_not_a_reimplementation():
    from SDRUtils.stir_flow.ladder_conventions import visibility_timestamp

    execution = pd.Timestamp("2026-06-16 14:15:00", tz="UTC")
    clock = lin.PublicationClock({})
    ts, _ = clock.visibility("x", execution, is_block=True)
    assert ts == visibility_timestamp(execution, is_block=True)


def test_a_measured_time_before_the_execution_is_refused():
    """A publication time earlier than the execution it publishes is not a tight
    availability bound, it is a broken one -- and it would let an aggregation
    see a print before it existed, which is the one error the visibility clock
    is there to prevent.
    """
    clock = lin.PublicationClock({"1": pd.Timestamp("2026-06-16 14:00:00", tz="UTC")})
    ts, source = clock.visibility("1", pd.Timestamp("2026-06-16 14:15:00", tz="UTC"))
    assert source == lin.VISIBILITY_APPENDIX_C
    assert ts > pd.Timestamp("2026-06-16 14:15:00", tz="UTC")


def test_the_availability_bound_is_the_event_not_the_frozen_execution():
    """On every row that does not mint a new UTI, #96 is frozen at the ORIGINAL
    trade's execution and can be years stale (`types.Clocks.pricing`). Bounding
    a 2026 termination's publication time against a 2024 execution admits any
    2026 timestamp, so the guard that exists to stop an aggregation seeing a
    print before it existed is vacuous for exactly the rows this module is
    about -- and, worse, the Appendix C fallback anchored on that stale #96
    marks the 2026 unwind as visible in 2024.

    The bound that cannot be violated is the dissemination event, #30.
    """
    from SDRUtils.stir_flow.ladder_conventions import visibility_timestamp

    execution = pd.Timestamp("2024-04-01 14:15:00", tz="UTC")     # #96, frozen
    event = pd.Timestamp("2026-06-16 15:00:00", tz="UTC")         # #30, the unwind

    # a "measured" time two years after the execution but BEFORE the event
    early = lin.PublicationClock({"2": pd.Timestamp("2026-06-16 14:00:00", tz="UTC")})
    ts, source = early.visibility("2", execution, event_ts=event)
    assert source == lin.VISIBILITY_APPENDIX_C
    assert ts == visibility_timestamp(event)          # fallback anchors on the EVENT
    assert ts > event

    # and a measured time after the event is still preferred
    late = lin.PublicationClock({"2": pd.Timestamp("2026-06-16 15:05:00", tz="UTC")})
    ts2, source2 = late.visibility("2", execution, event_ts=event)
    assert source2 == lin.VISIBILITY_SLICE_MTIME
    assert ts2 == pd.Timestamp("2026-06-16 15:05:00", tz="UTC")


# --------------------------------------------------------------------------
# The TERM<->NEWT direction agreement check.
# --------------------------------------------------------------------------

def test_the_encoded_unwind_direction_is_pinned_so_it_cannot_flip_silently():
    """Pins the direction the module ENCODES. It does not establish it.

    The encoded reading: on entry the party taking the in-the-money side pays
    for it, so `U < |f|` means the dealer holds it (`stir_flow/classifier.py:77`);
    on an unwind the ITM party is paid out, so the same inequality means the ITM
    party was underpaid -- i.e. the customer. Same algebra, opposite conclusion.

    THE ARGUMENT IS VERBAL AND THE DATA DOES NOT SETTLE IT. On the only subset
    that respects the rule's premise -- U/|f| in [0.8, 1.2], the 58 pairs of
    `MEASURED_PAIRS` below -- the encoded direction agrees with the original
    print 34/58 = 58.6% (z = +1.31) and the inverse gets 24/58 = 41.4%. Neither
    is distinguishable from a coin flip at n = 58. What this test buys is that
    the choice cannot be inverted without a test going red, because the two
    readings differ by a global sign flip and a flipped ladder is complete and
    plausible.
    """
    npv_pay = -1_000_000.0          # receive-fixed is ITM
    assert lin.unwind_implied_original_sign(npv_pay, upfront=1_020_000.0) == lin.DEALER_RECEIVED
    assert lin.unwind_implied_original_sign(npv_pay, upfront=980_000.0) == lin.DEALER_PAID
    # the entry rule, for contrast: U < |f| would say the dealer holds the ITM
    # (receive-fixed) side, i.e. DEALER_RECEIVED -- the opposite call.


def test_the_unwind_sign_is_pinned_in_all_four_quadrants():
    """`npv_pay < 0` alone does not exercise the rule: `customer_paid_fixed`
    is a function of BOTH `u vs |f|` and `sign(f)`, and dropping the `sign(f)`
    term (`customer_paid_fixed = u > abs(f)`) reproduces the `f < 0` column
    exactly while inverting the whole `f > 0` column. That mutant passed the
    suite. Every termination where the fixed payer is in the money would get a
    complete, plausible, exactly inverted dealer side, and the
    direction-agreement rate would barely move because both quadrants flip
    together.
    """
    R, P = lin.DEALER_RECEIVED, lin.DEALER_PAID
    #                      f            u          expected
    quadrants = [(-1_000_000.0, 1_020_000.0, R),   # dealer ITM, dealer receives fixed
                 (-1_000_000.0,   980_000.0, P),   # customer ITM (receive-fixed) -> dealer paid
                 (+1_000_000.0, 1_020_000.0, P),   # dealer ITM, ITM side is pay-fixed
                 (+1_000_000.0,   980_000.0, R)]   # customer ITM and pay-fixed
    for f, u, expected in quadrants:
        assert lin.unwind_implied_original_sign(f, u) == expected, (f, u)
        assert lin.unwind_dealer_sign(f, u) == -expected, (f, u)
    # the fee is unsigned: its sign carries no information about the side
    assert lin.unwind_implied_original_sign(+1_000_000.0, -1_020_000.0) == P


def test_a_zero_fee_is_not_a_call():
    """`types.Unit.upfront` is the SUM of the legs' other-payment amounts and
    ~86% of terminations carry no fee, so every `.sum()` / `.fillna(0)` path
    delivers `0.0` rather than `None`. `u = 0` satisfies `u < |f|` for every
    non-zero `f`, so an unreported fee would produce a confident side decided
    entirely by `sign(f)` -- for 86% of the population. A reported zero and an
    absent fee are indistinguishable here, so neither is a call.
    """
    assert lin.unwind_implied_original_sign(-1_000_000.0, 0.0) == 0
    assert lin.unwind_implied_original_sign(+1_000_000.0, 0.0) == 0
    assert lin.unwind_dealer_sign(-1_000_000.0, 0.0) == 0
    assert lin.unwind_implied_original_sign(-1_000_000.0, None) == 0
    assert lin.unwind_implied_original_sign(None, 1_020_000.0) == 0
    assert lin.unwind_implied_original_sign(float("nan"), 1_020_000.0) == 0


def test_the_hand_worked_pair_agrees():
    """The example the batch measurement is calibrated against.

    A 5Y SOFR swap prints at 3.50% against a 3.48% mid, so the payer overpaid,
    the payer is the customer, and the dealer RECEIVED fixed (+1). Rates then
    fall: at the unwind the mid is 3.20%, so `f = (m - R) * A < 0` and the
    receive-fixed side -- the dealer's -- is in the money. The dealer is giving
    up something worth $1.00mm, so it is paid more than that: `U = 1.02mm`.
    That inequality identifies the customer as the OTM (pay-fixed) party, hence
    the dealer as the receiver, which agrees with the original print.
    """
    original = lin.DEALER_RECEIVED
    implied = lin.unwind_implied_original_sign(-1_000_000.0, 1_020_000.0)
    assert implied == original
    # stated in the flip framing the task asks for: the side the dealer takes ON
    # the unwind is the opposite of the side it held, and that is what matches.
    assert lin.unwind_dealer_sign(-1_000_000.0, 1_020_000.0) == -original


def test_direction_agreement_counts_only_pairs_where_both_sides_made_a_call():
    pairs = pd.DataFrame({
        "original_dealer_sign": [1, 1, -1, 0, 1, 1],
        "unwind_dealer_sign": [-1, 1, 1, -1, 0, -1],
    })
    got = lin.direction_agreement(pairs)
    assert got["n_pairs"] == 6
    assert got["n_called"] == 4        # the two zero-sign rows are not calls
    assert got["n_agree"] == 3         # rows 0, 2 and 5 flip correctly, row 1 does not
    assert got["agreement"] == pytest.approx(3 / 4)
    # The 2x2 the report quotes: the quadrant labels have to name the quadrant
    # they count, or a disagreement is read off as its own opposite. The two
    # off-diagonal counts differ on purpose -- with 1 and 1 the assertion is
    # invariant under transposing the table and pins nothing.
    assert got["table"] == {"orig+_unwind-": 2, "orig+_unwind+": 1,
                            "orig-_unwind+": 1, "orig-_unwind-": 0}


def test_direction_agreement_is_symmetric_under_relabelling():
    """Flipping BOTH inferences must leave the agreement rate unchanged. If it
    does not, the function is reading an absolute side somewhere instead of the
    relation between the two -- which is how a sign convention leaks in.
    """
    pairs = pd.DataFrame({"original_dealer_sign": [1, 1, -1], "unwind_dealer_sign": [-1, 1, 1]})
    flipped = pairs * -1
    assert lin.direction_agreement(pairs)["agreement"] == \
        lin.direction_agreement(flipped)["agreement"]


# --------------------------------------------------------------------------
# The partial-termination hole in the unwind rule.
#
# INHERITED MEASUREMENT. Every number below comes from the tracked artifact
# `scratch/out_direction_agreement.csv` (written 2026-08-11 12:02). The lineage
# store it was built from -- `scratch/dd_lineage_store/`, gitignored -- has been
# DELETED, so it cannot be re-derived end to end; re-running the pipeline
# against a rebuilt store would be a DIFFERENT measurement, not this one. The
# rows here ARE the artifact, frozen: the 154 pairs whose original repriced
# within 25 bp of mid, as `(npv_pay, upfront, original_dealer_sign)`, sorted by
# U/|f|, with `npv_pay` at full float precision (the two smallest are ~1e-5, and
# rounding them to cents would turn them into a division by zero).
#
# Agreement with the original print, by U/|f| -- this is what the gate is for:
#
#       U/|f|      n   agree    rate    z vs coin flip
#       < 0.5     36       9   0.250    -3.00
#       0.5-0.8   36       6   0.167    -4.00
#       0.8-1.2   58      34   0.586    +1.31
#       1.2-2      8       3   0.375    -0.71
#       > 2       16      11   0.688    +1.50
#       all      154      63   0.409    -2.26
#
# (A review of this same CSV quoted 14/9 in the `> 2` bucket. The two rows it
# dropped have ratios 8.2e10 and 8.6e11 and both agree, so 14/9 and 16/11
# reconcile exactly; a finite top bin edge is the likely cause. Every other
# bucket matches to the row.)
#
# The zone below 0.8 is 46.8% of the population and is where a partial
# termination lands: the fee pays for the fraction x that was torn up, while
# `npv_pay` is repriced on the ORIGINAL notional, so U ~ x|f| and `u < abs(f)`
# is structurally forced. It measured 15/72 = 0.208, i.e. significantly WORSE
# than a coin flip -- an anti-prediction, not a gap.
# --------------------------------------------------------------------------

MEASURED_PAIRS = (
    (6714.19489990361, 1.0, +1),
    (102902.51310971938, 2300.0, -1),
    (738637.7307156892, 48311.4912, -1),
    (-6947.526766673662, 500.0, -1),
    (49180.50512112398, 6300.0, +1),
    (358907.18180255964, 67654.04231, +1),
    (103577.10041865056, 20700.0, +1),
    (1235939.6497339308, 249383.86089, -1),
    (1358466.401020117, 282628.0464, -1),
    (35213.61497982533, 7900.0, -1),
    (3265378.0833800808, 742653.86, -1),
    (334915.3299778546, 78666.588, -1),
    (614693.6379498187, 147214.9228, -1),
    (3825542.773289845, 948688.0, -1),
    (4090180.4292619377, 1017120.0, -1),
    (1376863.2410094189, 368547.6007, -1),
    (-100836.1946082759, 27000.0, +1),
    (310775.37156315846, 84584.56584, -1),
    (780571.7918057591, 214000.0, +1),
    (396635.3874623305, 126812.5463, -1),
    (994501.1180880108, 321604.33386, -1),
    (1078833.4341718704, 375166.182, -1),
    (1066900.147042686, 380460.135, -1),
    (667625.6302103852, 243606.33185, -1),
    (5591189.424881771, 2042314.89, +1),
    (519388.49910673406, 192576.95019, -1),
    (244828.7801105473, 94931.865, -1),
    (23397.7428536003, 9200.0, -1),
    (1850456.071652856, 798978.6, +1),
    (1850306.7460963016, 799193.0, +1),
    (5534591.474954478, 2429747.574, -1),
    (1119262.6580995098, 512800.0, -1),
    (8122672.916748352, 3800000.0, -1),
    (545293.9301459892, 261929.27655, -1),
    (545293.9301459892, 261929.27655, -1),
    (2423688.622742757, 1175000.0, -1),
    (36479.82090997882, 19000.0, -1),
    (26800.608540557325, 14173.2, -1),
    (-211123.85735386657, 121689.945, +1),
    (284209.2935859524, 164100.0, -1),
    (962379.6530043188, 556000.0, -1),
    (82208.6740677841, 50580.74, +1),
    (327857.3342591687, 209100.0, -1),
    (74453.39020738285, 47585.62, -1),
    (7290194.678977869, 4688000.0, +1),
    (69533.67581307213, 44720.0, +1),
    (170030.44426311716, 114200.0, -1),
    (6955730.226330712, 4672222.944, -1),
    (203575.14853700344, 137937.858, -1),
    (204471.9756207117, 139594.23, +1),
    (204471.9756207117, 139594.23, -1),
    (-22888.03749830089, 16000.0, +1),
    (2108535.5532096457, 1485121.696, -1),
    (1661929.667221047, 1193000.0, +1),
    (107776.32923395188, 78043.75745, -1),
    (348804.7958292477, 255500.0, -1),
    (1073454.708083028, 793253.646, -1),
    (198460.71941609588, 147964.7984, -1),
    (198460.71941609588, 147964.7984, -1),
    (198460.71941609588, 147964.7984, -1),
    (198460.71941609588, 147964.7984, -1),
    (51749.86843984085, 39000.0, -1),
    (56470.61448012863, 42857.2, -1),
    (5346695.850286104, 4107800.0, -1),
    (126456.70764907727, 97222.0, -1),
    (247114.04018425383, 190600.0, -1),
    (134098.1966194166, 104255.55, -1),
    (67224.22837184463, 53000.0, +1),
    (304029.1574766119, 240000.0, -1),
    (3671185.305478193, 2900000.0, -1),
    (355441.9575151638, 282543.3072, -1),
    (-6283.449100400554, 4999.0, +1),
    (2241053.8654948547, 1820000.0, -1),
    (193612.9479690697, 157681.6, -1),
    (280175.0004106886, 230000.0, -1),
    (-30081.714142743265, 25000.0, -1),
    (9146.34040243202, 7651.44, -1),
    (6667658.098554641, 5668248.0, +1),
    (100765.0961219616, 85820.4608, -1),
    (16025.991778710972, 14123.395, +1),
    (-224854.69520948548, 200000.0, +1),
    (256700.0281704506, 229000.0, +1),
    (56035.27106831095, 51147.72, +1),
    (6651388.269024812, 6085521.21, +1),
    (141217.13474483928, 130000.0, -1),
    (54805.37004067085, 51300.0, +1),
    (38897.20966577856, 36458.45, +1),
    (149219.32712884434, 141000.0, +1),
    (78278.32051525265, 74567.575, +1),
    (1776802.513143804, 1705607.4, -1),
    (7315127.91494669, 7052908.044, +1),
    (1496567.4420623966, 1444232.0, +1),
    (1219235.020094729, 1181000.0, +1),
    (208518.89181111704, 202000.0, -1),
    (2390909.2469462883, 2318912.4, +1),
    (124656.067993104, 120996.225, +1),
    (76169.70815624762, 74000.0, +1),
    (6904646.720704675, 6718782.0232, +1),
    (262585.8770541735, 256000.0, +1),
    (2166444.557746406, 2113000.0, +1),
    (2338325.073470643, 2285440.0, +1),
    (2910710.1360516325, 2846884.0, +1),
    (723757.2021664176, 712363.0, +1),
    (853342.7368555777, 844000.0, -1),
    (13740475.95878867, 13595218.45, +1),
    (208211.91226140969, 206500.0, +1),
    (3598079.0628851056, 3570000.0, -1),
    (85050.06766553805, 84449.388, +1),
    (1070813.3100170456, 1066828.56, +1),
    (1150100.741022028, 1146119.46, +1),
    (6870410.978665821, 6847353.0, -1),
    (135309.43110632803, 135000.0, +1),
    (116633.86414983356, 117528.0, +1),
    (1036798.274980437, 1046586.0, +1),
    (21278.409421242308, 21506.38314, -1),
    (339050.14797958964, 343691.0, +1),
    (104093.004878246, 105800.0, +1),
    (266152.4829648836, 271774.0, +1),
    (959187.3617600054, 985000.0, -1),
    (318852.69073543884, 330000.0, -1),
    (524813.3707686807, 546753.48, -1),
    (233089.81765386555, 243380.0052, +1),
    (171779.9351851642, 180000.0, -1),
    (45218.37984431046, 47599.864, +1),
    (2051570.282555446, 2161752.888, +1),
    (-7288.433942150907, 7756.53156, -1),
    (71629.8619350791, 76643.154, -1),
    (509019.64568244666, 561000.0, +1),
    (-793.1305221328657, 883.7312, -1),
    (176778.2458808273, 207510.66, +1),
    (26498.802498918027, 33000.0, -1),
    (116635.55484005064, 148900.0, +1),
    (3935111.4260634175, 5408853.84, -1),
    (143302.07080938667, 198000.0, +1),
    (-47815.68256586557, 78947.25, -1),
    (420243.17190625984, 695720.871, -1),
    (-93587.26928285325, 168944.3, -1),
    (-81395.38810169883, 151072.5, -1),
    (877691.6995932721, 1884700.0, +1),
    (16728.27838333696, 48744.63, +1),
    (46087.85760845686, 136273.224, -1),
    (42138.97185208998, 129509.223, -1),
    (1639322.2857652716, 5443700.0, +1),
    (65464.38086931268, 226374.0, -1),
    (40625.39674425474, 158390.75836, -1),
    (33109.45808913035, 165952.215, -1),
    (3603428.252331618, 18743000.0, +1),
    (552332.7572493227, 4681000.0, +1),
    (53751.83016017079, 1231767.97678, -1),
    (-8384.623068030924, 690923.7, +1),
    (9.722429611720145, 1141.43, -1),
    (794.9562012776732, 2529335.9, -1),
    (2.847927473990236e-05, 2343750.0, -1),
    (2.1659940185523446e-05, 18554687.5, -1),
)


def _split_by_ratio(band=None):
    """The measured pairs, split into (below band, in band, above band)."""
    lo, hi = band if band is not None else lin.UNWIND_RATIO_BAND
    below, inside, above = [], [], []
    for f, u, o in MEASURED_PAIRS:
        ratio = abs(u) / abs(f)
        (below if ratio < lo else inside if ratio <= hi else above).append((f, u, o))
    return below, inside, above


def test_the_frozen_measurement_is_the_population_the_gate_was_cut_from():
    """A guard tuned to a fixture that does not match the artifact guards
    nothing. Pins the three counts and the headline agreements the band edges
    were chosen from, so a later edit to `MEASURED_PAIRS` cannot quietly move
    the population under the gate.
    """
    below, inside, above = _split_by_ratio(band=(0.8, 1.2))
    assert (len(below), len(inside), len(above)) == (72, 58, 24)
    assert len(MEASURED_PAIRS) == 154
    # the encoded rule, ungated, against the original print
    def agree(rows):
        return sum(1 for f, u, o in rows
                   if lin.unwind_dealer_sign(f, u, ratio_band=None) == -o)
    assert agree(MEASURED_PAIRS) == 63          # 40.9% aggregate, z = -2.26
    assert agree(below) == 15                   # 20.8%, the anti-predictive zone
    assert agree(inside) == 34                  # 58.6%, z = +1.31, not significant
    assert agree(above) == 14


def test_a_partial_termination_is_a_no_call_not_a_confident_side():
    """The hole. A partial unwind of fraction x pays a fee of about x|f| while
    `npv_pay` is repriced on the ORIGINAL notional, so `u < abs(f)` is
    structurally forced and `customer_is_itm` is True for reasons that have
    nothing to do with who was in the money. The side then falls out of
    `sign(f)` alone -- exactly what the `u == 0.0` branch exists to prevent,
    reintroduced through a non-zero fee.
    """
    for f in (-1_000_000.0, +1_000_000.0):
        for x in (0.02, 0.1, 0.25, 0.5, 0.75, 0.79):
            u = abs(f) * x
            assert lin.unwind_implied_original_sign(f, u) == 0, (f, x)
            assert lin.unwind_dealer_sign(f, u) == 0, (f, x)
    # the fee that dwarfs the residual is the same premise failure from the
    # other side (the artifact's worst row: a 2-cent residual against an
    # 18.5mm fee, U/|f| = 8.6e11)
    assert lin.unwind_implied_original_sign(2.1659940185523446e-05, 18_554_687.5) == 0
    assert lin.unwind_dealer_sign(-1_000_000.0, 3_000_000.0) == 0


def test_the_gate_silences_the_zone_that_measured_worse_than_a_coin_flip():
    """15/72 = 20.8% agreement below 0.8, and it is not noise: `customer_is_itm`
    fires on 72/72 of those rows and the call is `-sign(npv_pay)` on 72/72. A
    rule that is significantly anti-predictive on 46.8% of its population is
    not making weak calls there, it is making wrong ones.
    """
    below, _, above = _split_by_ratio()
    assert below and above
    for f, u, _o in below + above:
        assert lin.unwind_implied_original_sign(f, u) == 0, (f, u)
        assert lin.unwind_dealer_sign(f, u) == 0, (f, u)
    # ungated, every single one of them was a call, and the call was sign(f)
    for f, u, _o in below:
        ungated = lin.unwind_implied_original_sign(f, u, ratio_band=None)
        assert ungated != 0
        assert ungated == (lin.DEALER_RECEIVED if f > 0 else lin.DEALER_PAID)


def test_the_gate_leaves_the_premise_respecting_subset_intact():
    """A guard that silences everything is not a guard. The 58 in-band pairs
    must still be called, and called the same way they were before -- the gate
    changes WHICH rows get an answer, never the answer.
    """
    _below, inside, _above = _split_by_ratio()
    assert len(inside) == 58
    n_agree = 0
    for f, u, o in inside:
        gated = lin.unwind_implied_original_sign(f, u)
        assert gated != 0, (f, u)
        assert gated == lin.unwind_implied_original_sign(f, u, ratio_band=None)
        n_agree += (lin.unwind_dealer_sign(f, u) == -o)
    assert n_agree == 34            # 58.6%; the inverse direction would get 24


def test_the_band_edges_are_inclusive_and_a_hair_outside_is_a_no_call():
    """Where the boundary sits is a stated choice, not a measured one, so it is
    pinned rather than argued: 0.8 is the measured edge of the anti-predictive
    zone; 1.2 mirrors it on the overcharge side, where the data is too thin to
    say anything (n = 8 at 0.375, n = 16 at 0.688, neither significant) and the
    exclusion rests on the premise, not on evidence.
    """
    assert lin.UNWIND_RATIO_BAND == (0.8, 1.2)
    f = -1_000_000.0
    assert lin.unwind_implied_original_sign(f, 800_000.0) == lin.DEALER_PAID       # 0.80
    assert lin.unwind_implied_original_sign(f, 1_200_000.0) == lin.DEALER_RECEIVED  # 1.20
    assert lin.unwind_implied_original_sign(f, 799_999.0) == 0
    assert lin.unwind_implied_original_sign(f, 1_200_001.0) == 0
    # a caller may widen or narrow it, and that has to actually take effect
    assert lin.unwind_implied_original_sign(f, 500_000.0, ratio_band=(0.4, 2.5)) != 0
    assert lin.unwind_implied_original_sign(f, 900_000.0, ratio_band=(0.95, 1.05)) == 0


def test_a_band_that_does_not_straddle_one_is_refused():
    """A one-sided band is a one-sided ladder. `(1.0, 1.2)` admits only
    `u > |f|`, so every call it makes is the DEALER-ITM branch and the flow it
    produces is a complete, plausible, systematically one-signed book -- with
    no error anywhere for a test to catch. Refused at the door.
    """
    for bad in ((1.0, 1.2), (0.8, 1.0), (0.8, 0.99), (1.2, 0.8), (-0.5, 1.2), (0.0, 1.2)):
        with pytest.raises(ValueError):
            lin.unwind_implied_original_sign(-1_000_000.0, 900_000.0, ratio_band=bad)
        with pytest.raises(ValueError):
            lin.unwind_dealer_sign(-1_000_000.0, 900_000.0, ratio_band=bad)
    # and it must raise on EVERY row, not only the ones that carry a fee and a
    # value: a band checked after the input guards is a band that a population
    # of no-calls hides completely
    with pytest.raises(ValueError):
        lin.unwind_implied_original_sign(None, None, ratio_band=(1.0, 1.2))
    with pytest.raises(ValueError):
        lin.unwind_implied_original_sign(-1_000_000.0, 0.0, ratio_band=(1.0, 1.2))


def test_an_exact_tie_between_the_fee_and_the_value_is_not_a_call():
    """`u == abs(f)` is the one point where the inequality carries no
    information at all: the fee is exactly the residual value, so neither party
    was paid for anything. It sits in the MIDDLE of the band, so the ratio gate
    does not cover it -- delete this branch and the tie silently becomes
    "not less than, therefore dealer ITM", a side invented out of an equality.
    """
    for f in (+1_000_000.0, -1_000_000.0):
        assert lin.unwind_implied_original_sign(f, 1_000_000.0) == 0
        assert lin.unwind_implied_original_sign(f, -1_000_000.0) == 0   # fee is unsigned
        assert lin.unwind_dealer_sign(f, 1_000_000.0) == 0
        assert lin.unwind_implied_original_sign(f, 1_000_000.0, ratio_band=None) == 0
    # one cent either side of the tie IS a call, and the two calls are opposite
    assert lin.unwind_implied_original_sign(-1e6, 1_000_000.01) == lin.DEALER_RECEIVED
    assert lin.unwind_implied_original_sign(-1e6, 999_999.99) == lin.DEALER_PAID


def test_an_explicitly_flagged_partial_termination_is_never_a_call():
    """The flag the tape does not populate. `lc_was_partially_terminated`,
    `lc_has_partial_unwind`, `xd_was_partially_terminated`,
    `lc_inception_notional` and `lc_current_notional` are ALL-NULL on
    `arbs_usd_swap_tape_legs_v3` -- 0 of 187,782 legs over the last 60 days, and
    0 of the 154 originals behind `MEASURED_PAIRS`. `xd_has_partial_unwind` is
    populated on 17.5% of legs but is TRUE on 1 of those 154, and that one row
    is in-band: it flags NONE of the 72 low-ratio rows. So the parameter exists
    for a caller that has a real indicator, and the ratio gate is what actually
    does the work today.
    """
    f, u = -1_000_000.0, 1_020_000.0                  # in band, otherwise a call
    assert lin.unwind_implied_original_sign(f, u) == lin.DEALER_RECEIVED
    assert lin.unwind_implied_original_sign(f, u, partially_terminated=True) == 0
    assert lin.unwind_dealer_sign(f, u, partially_terminated=True) == 0
    assert lin.unwind_implied_original_sign(f, u, partially_terminated=True,
                                            ratio_band=None) == 0
    # False and "not recorded" are different from True and must not silence it
    for absent in (False, None, float("nan"), pd.NA):
        assert lin.unwind_implied_original_sign(f, u, partially_terminated=absent) \
            == lin.DEALER_RECEIVED, absent


def test_the_ungated_escape_hatch_reaches_both_spellings():
    """`unwind_dealer_sign` is a negation of the other spelling, so it has to
    forward the guards too. Drop the forwarding and it silently reverts to the
    defaults -- which no test built out of the defaults can see.
    """
    f, u = -1_000_000.0, 300_000.0
    assert lin.unwind_dealer_sign(f, u) == 0
    assert lin.unwind_dealer_sign(f, u, ratio_band=None) == -lin.DEALER_PAID
    assert lin.unwind_implied_original_sign(f, u, ratio_band=None) == lin.DEALER_PAID
    assert lin.unwind_dealer_sign(f, u, ratio_band=(0.2, 1.8)) == -lin.DEALER_PAID


# --------------------------------------------------------------------------
# The store.
# --------------------------------------------------------------------------

def test_store_round_trips_and_reports_what_it_actually_holds(tmp_path):
    store = lin.LineageStore(root=tmp_path)
    raw = _raw([
        ("300", None, "NEWT", "TRAD", "2026-06-16T10:00:00Z", "2026-06-16T10:00:00Z"),
        ("301", "300", "TERM", "ETRM", "2026-06-16T11:00:00Z", "2026-06-01T10:00:00Z"),
    ])
    n = store.write_day(FILE_DATE, lin.resolve_lineage(raw))
    assert n == 1
    assert store.covered_days() == [FILE_DATE]
    back = store.read_day(FILE_DATE)
    assert list(back["dissemination_id"]) == ["301"]


def test_the_store_refuses_to_record_a_day_it_wrote_no_rows_for(tmp_path):
    store = lin.LineageStore(root=tmp_path)
    with pytest.raises(lin.EmptyLineageDay):
        store.write_day(FILE_DATE, lin.resolve_lineage(_raw([])))
    assert store.covered_days() == []


def _runner():
    """The CLI, loaded by path -- `scripts/` is not an importable package."""
    import importlib.util
    import pathlib

    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "build_dd_lineage_store.py"
    spec = importlib.util.spec_from_file_location("build_dd_lineage_store", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_runner_aborts_on_a_day_the_upstream_serves_nothing(tmp_path):
    """Exit code 0 is not success. The runner must refuse a day rather than
    count it, which is the failure that cost six days of data here before.
    """
    run = _runner()
    with pytest.raises(lin.EmptyDTCCDay):
        run.fetch_days([FILE_DATE], root=tmp_path, zip_source=lambda ds: None)
    assert not lin.raw_day_path(FILE_DATE, root=tmp_path).exists()


def test_the_runner_reports_rows_per_day_and_writes_only_target_days(tmp_path):
    run = _runner()
    counts = run.fetch_days([FILE_DATE], root=tmp_path,
                            zip_source=_source(_CSV_HEADER + _ROW_NEWT + _ROW_TERM_STALE))
    assert counts == {FILE_DATE: 2}
    store = lin.LineageStore(root=tmp_path)
    written = run.resolve_and_write([FILE_DATE], root=tmp_path, store=store, use_tape=False)
    assert written == {FILE_DATE: 1}                  # the TERM only; the NEWT has no pointer
    assert store.days_needing_work([FILE_DATE]) == []


def test_the_runner_unions_the_explicit_range_with_the_trailing_window():
    run = _runner()
    args = argparse.Namespace(start="2026-06-01", end="2026-06-05", trailing_days=90,
                              as_of="2026-08-10")
    days = run.target_days(args)
    assert datetime.date(2026, 6, 1) in days          # from the explicit range
    assert datetime.date(2026, 8, 10) in days         # from the trailing window
    assert days == sorted(set(days))
    # The federal holidays this window actually contains. 2026-07-04 is a
    # SATURDAY, so asserting on it pins nothing -- dropping the holiday calendar
    # for a plain `freq="B"` passed that assertion. These three are weekdays on
    # which DTCC publishes no file, so a backfill that targets them aborts on an
    # empty day.
    for holiday in (datetime.date(2026, 5, 25),       # Memorial Day, a Monday
                    datetime.date(2026, 6, 19),       # Juneteenth, a Friday
                    datetime.date(2026, 7, 3)):       # July 4 observed, a Friday
        assert holiday.weekday() < 5, holiday         # the assertion is not vacuous
        assert holiday not in days, holiday


def test_a_limited_pass_that_did_its_work_exits_zero(tmp_path):
    """`--limit N` is the documented chunking mode ("days per pass; resume
    handles the rest"), and exit 2 is documented as "a day failed". The
    post-write target-set check re-checked the FULL day list rather than the
    days this pass claimed, so every successful chunked pass exited 2 and any
    unattended driver reads its own chunking as a hard failure.
    """
    run = _runner()
    d1, d2 = datetime.date(2026, 6, 16), datetime.date(2026, 6, 17)
    for i, d in enumerate((d1, d2)):
        row = (f"90000000000{i},70000000000{i},TERM,ETRM,2026-06-16T15:00:00Z,"
               "2024-04-01T14:15:36Z,USD,NA/Swap OIS USD,1020000,\n")
        lin.fetch_raw_day(d, root=tmp_path, zip_source=_source(_CSV_HEADER + row))

    def _args():
        return argparse.Namespace(root=str(tmp_path), start=d1.isoformat(), end=d2.isoformat(),
                                  trailing_days=0, as_of=None, force=False, limit=1,
                                  no_tape=True)

    assert run.cmd_build(_args()) == 0                 # pass 1 wrote day 1 and only day 1
    store = lin.LineageStore(root=tmp_path)
    assert store.days_needing_work([d1, d2]) == [d2]
    assert run.cmd_build(_args()) == 0                 # pass 2 resumes
    assert store.days_needing_work([d1, d2]) == []


def test_the_slice_sequence_default_covers_a_whole_day():
    """Bisected on three days: a day runs to 1,896 / 1,930 / 1,969 slices. The
    listing API's ~1,333 is a rolling 24 h window, and stopping there scans
    73.7% of a day while looking complete, so the default upper bound must sit
    above the largest measured day.
    """
    run = _runner()
    seen = {}

    def _capture(args):
        seen.update(vars(args))
        return 0

    run.cmd_slices = _capture
    assert run.main(["slices", "--day", "2026-06-16"]) == 0
    assert seen["total"] >= 1969


def test_report_on_an_empty_store_says_so_instead_of_raising(tmp_path):
    run = _runner()
    args = argparse.Namespace(root=str(tmp_path), start=None, end=None,
                              trailing_days=0, as_of=None)
    assert run.cmd_report(args) == 2


def test_resume_is_keyed_to_the_target_set_not_the_ledger(tmp_path):
    """A backfill here once recorded completion in its ledger while days were
    silently absent from the target range. The ledger is a record; the parquet
    with rows in it is the authority.
    """
    store = lin.LineageStore(root=tmp_path)
    raw = _raw([("301", "300", "TERM", "ETRM", "2026-06-16T11:00:00Z", "2026-06-01T10:00:00Z")])
    store.write_day(FILE_DATE, lin.resolve_lineage(raw))
    store.record(FILE_DATE, rows=1)
    # a day the ledger claims but which has no parquet is still outstanding
    store.record(datetime.date(2026, 6, 17), rows=99)
    todo = store.days_needing_work([FILE_DATE, datetime.date(2026, 6, 17)])
    assert todo == [datetime.date(2026, 6, 17)]

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
# Multi-hop resolution. 43 TERM->TERM pointers in a single week, so a star
# topology is not what the data does.
# --------------------------------------------------------------------------

def _raw(rows) -> pd.DataFrame:
    cols = [DI, ODI, "Action type", "Event type", "Event timestamp", "Execution Timestamp"]
    df = pd.DataFrame(rows, columns=cols)
    for c in ("Event timestamp", "Execution Timestamp"):
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    df["file_date"] = FILE_DATE
    return df


def test_chained_partial_terminations_walk_all_the_way_to_the_newt():
    """Appendix F Example 1 draws a star -- D2 pointing at the original. The
    data disagrees: 43 TERM->TERM pointers in one week, which a star makes
    impossible. Single-hop resolution stops at the middle termination and calls
    the original unresolved.
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
    this week's frame". 42 of those 43 point at themselves.
    """
    raw = _raw([("301", "301", "TERM", "ETRM", "2026-06-16T10:00:00Z", "2026-06-01T10:00:00Z")])
    out = lin.resolve_lineage(raw).iloc[0]
    assert out["status"] == lin.ST_SELF_POINTER
    assert out["hops"] == 0
    assert pd.isna(out["reach_back_days"])


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


# --------------------------------------------------------------------------
# Why `core/graph_resolver.build_synthetic_uti_mapping` is not used.
# --------------------------------------------------------------------------

def test_graph_resolver_anchors_on_the_termination_when_the_original_is_out_of_frame():
    """The existing resolver is undirected connected components plus an anchor
    rule of "earliest NEWT, else earliest timestamp". With the original outside
    the loaded window -- 24.5% of terminations by the measured reach-back -- the
    component holds no NEWT, so the anchor falls on the *termination itself* and
    the pointer target is discarded. That is the opposite of lineage.
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


def test_slice_enumeration_names_the_files_dtcc_actually_serves():
    names = lin.slice_date_strings(datetime.date(2026, 6, 16), [1, 100, 1333])
    assert names[:2] == ["2026_06_16_1", "2026_06_16_100"]
    assert len(names) == 3


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


# --------------------------------------------------------------------------
# The TERM<->NEWT direction agreement check.
# --------------------------------------------------------------------------

def test_the_unwind_fee_rule_is_the_reverse_of_the_entry_fee_rule():
    """On entry the dealer *pays* for the in-the-money side, so `U < |f|` means
    the dealer holds it (`stir_flow/classifier.py:77`). On an unwind the ITM
    party is *paid out*, so the same inequality means the ITM party was
    underpaid -- i.e. the ITM party is the customer. Same algebra, opposite
    conclusion; carrying the entry rule over to terminations inverts every call
    and produces a complete, plausible, exactly wrong ladder.
    """
    npv_pay = -1_000_000.0          # receive-fixed is ITM
    assert lin.unwind_implied_original_sign(npv_pay, upfront=1_020_000.0) == lin.DEALER_RECEIVED
    assert lin.unwind_implied_original_sign(npv_pay, upfront=980_000.0) == lin.DEALER_PAID
    # the entry rule, for contrast: U < |f| would say the dealer holds the ITM
    # (receive-fixed) side, i.e. DEALER_RECEIVED -- the opposite call.


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
        "original_dealer_sign": [1, 1, -1, 0, 1],
        "unwind_dealer_sign": [-1, 1, 1, -1, 0],
    })
    got = lin.direction_agreement(pairs)
    assert got["n_pairs"] == 5
    assert got["n_called"] == 3        # the two zero-sign rows are not calls
    assert got["n_agree"] == 2         # rows 0 and 2 flip correctly, row 1 does not
    assert got["agreement"] == pytest.approx(2 / 3)


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
    assert datetime.date(2026, 7, 4) not in days      # Independence Day, not a business day
    assert days == sorted(set(days))


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

"""The intraday mid grid's seam: schema, tenor grid, join arithmetic, adapter.

Everything here is offline. What the curve store and the tape decide is
measured by the runner's own ``validate`` stage -- the known-answer check
against ``arbs_dd_unit_v1.deviation_bps`` -- which is a measurement, not a
test. What is pinned here is the part that would fail *silently*: a column the
writer writes and the DDL does not declare, a tenor quietly added or dropped,
a join key off by one minute, and a session bound re-derived instead of
delegated.
"""
from __future__ import annotations

import datetime
import os
import re

import numpy as np
import pandas as pd
import pytest
import pytz

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")

from SDRUtils._swappulse_scripts import _dealer_direction_schema_v1 as S  # noqa: E402
from SDRUtils._swappulse_scripts import backfill_curve_mids as B  # noqa: E402
from SDRUtils.dealer_direction import midprice, snapshot  # noqa: E402

NY = pytz.timezone("America/New_York")


def _ddl_block(table: str) -> str:
    """The one CREATE TABLE statement for this table, not the whole DDL.

    Checking a column against the concatenated DDL passes when the column is
    declared on some *other* table -- which is exactly the mistake a two-table
    addition invites, since both tables here carry `grid_date`, `rate_index`
    and `curve_name`.
    """
    head = f"CREATE TABLE IF NOT EXISTS {table} ("
    hits = [s for s in S.DDL_STATEMENTS if head in s]
    assert len(hits) == 1, f"{table}: expected one CREATE TABLE, got {len(hits)}"
    return hits[0]


def _declared(block: str) -> set[str]:
    """Column names declared in a CREATE TABLE block."""
    body = block.split("(", 1)[1]
    out = set()
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("--") or line.startswith("PRIMARY KEY"):
            continue
        m = re.match(r"^([a-z_][a-z0-9_]*)\s+[A-Z]", line)
        if m:
            out.add(m.group(1))
    return out


# ==========================================================================
# the DDL declares every column the writer writes
# ==========================================================================

def test_the_grid_ddl_declares_every_column_the_writer_writes():
    declared = _declared(_ddl_block(S.CURVE_MID_TABLE))
    missing = [c for c in B.GRID_COLS if c not in declared]
    assert not missing, (
        f"{missing} are written by the runner and not declared on "
        f"{S.CURVE_MID_TABLE}; the INSERT would fail on the first day of a "
        "backfill, hours after the schema stage said it was fine"
    )


def test_the_day_ledger_ddl_declares_every_column_the_writer_writes():
    declared = _declared(_ddl_block(S.CURVE_MID_DAY_TABLE))
    missing = [c for c in B.DAY_COLS if c not in declared]
    assert not missing, f"{missing} missing from {S.CURVE_MID_DAY_TABLE}"


def test_the_writer_writes_every_NOT_NULL_column_that_has_no_default():
    """A NOT NULL column nobody writes is a backfill that cannot start."""
    for table, cols in ((S.CURVE_MID_TABLE, B.GRID_COLS),
                        (S.CURVE_MID_DAY_TABLE, B.DAY_COLS)):
        block = _ddl_block(table)
        for line in block.splitlines():
            line = line.strip()
            m = re.match(r"^([a-z_][a-z0-9_]*)\s+[A-Z].*NOT NULL", line)
            if not m or "DEFAULT" in line:
                continue
            assert m.group(1) in cols, (
                f"{table}.{m.group(1)} is NOT NULL with no default and the "
                "writer never sets it")


def test_the_primary_key_matches_the_read_and_the_index_matches_the_day_read():
    block = _ddl_block(S.CURVE_MID_TABLE)
    # One index, one tenor, a time range -- equality columns first, then the
    # range column.
    assert "PRIMARY KEY (rate_index, tenor_label, ts)" in block
    idx = [s for s in S.DDL_STATEMENTS
           if "CREATE INDEX" in s and S.CURVE_MID_TABLE in s]
    assert any("(grid_date, rate_index, tenor_label, ts)" in s for s in idx), (
        "there is no index for 'one day, one curve, one tenor, ordered by "
        "time', which is the read the chart makes")
    assert "PRIMARY KEY (grid_date, rate_index)" in _ddl_block(
        S.CURVE_MID_DAY_TABLE)


def test_the_grid_is_keyed_on_the_ET_date_and_NOT_on_as_of_date():
    """`as_of_date` is a UTC date and the grid is partitioned on New York.

    ~4% of a tape day's prints (ET hours 20-23) were executed the previous ET
    evening, so a grid keyed on `as_of_date` puts those prints a whole day from
    their own minutes. Every "no grid point within 30 minutes" case in the
    sizing probe was this artifact.
    """
    declared = _declared(_ddl_block(S.CURVE_MID_TABLE))
    assert "grid_date" in declared
    assert "as_of_date" not in declared
    assert "grid_date" in B.GRID_COLS
    assert "as_of_date" not in B.GRID_COLS


def test_a_stale_row_says_so_on_its_own_row():
    """The provenance of the served snapshot, per row, not per day.

    A chart that silently draws a 90-minute-old mid as if it were live is the
    failure these columns exist to prevent, so all four travel together: the
    instant asked for, the instant served, the realised lag, and which policy
    branch allowed it.
    """
    declared = _declared(_ddl_block(S.CURVE_MID_TABLE))
    for c in ("ts", "served_ts", "snapshot_lag_seconds", "snapshot_policy"):
        assert c in declared and c in B.GRID_COLS, c
    # And the policy vocabulary is the pricer's own, not a local spelling.
    assert midprice.POLICY_STRICT == "STRICT_1MIN_IN_SESSION"
    assert midprice.POLICY_HOLE == "ASOF_2H_OUT_OF_SESSION"


def test_a_mid_is_never_null_because_a_hole_would_read_as_a_quiet_market():
    block = _ddl_block(S.CURVE_MID_TABLE)
    assert re.search(r"mid_pct\s+DOUBLE PRECISION NOT NULL", block)
    # ...and the dates that say WHICH instrument the rate belongs to are not
    # optional either. `tenor_label` is a bucket: '10Y' spans 3,468-3,830 days.
    assert re.search(r"effective_date\s+DATE NOT NULL", block)
    assert re.search(r"maturity_date\s+DATE NOT NULL", block)


def test_the_names_derive_from_the_generation_helper():
    assert S.CURVE_MID_TABLE == "arbs_dd_curve_mid_v1"
    assert S.CURVE_MID_DAY_TABLE == "arbs_dd_curve_mid_day_v1"
    assert S.CURVE_MID_TABLE == S._t("curve_mid")
    assert S.CURVE_MID_DAY_TABLE == S._t("curve_mid_day")


def test_the_dashboard_pins_the_same_two_table_names():
    import pathlib
    ts = (pathlib.Path(__file__).resolve().parents[1] / "SDRUtils" / "dashboard"
          / "src" / "lib" / "dealer-direction-tables.ts").read_text(
              encoding="utf-8")
    assert "DD_CURVE_MID = d('curve_mid')" in ts
    assert "DD_CURVE_MID_DAY = d('curve_mid_day')" in ts


# ==========================================================================
# the tenor grid is what was decided, and it was decided by measurement
# ==========================================================================

def test_the_sofr_grid_is_the_21_tenors_that_were_measured():
    # 95.3% of all SOFR flow prints and 93.7% of |risk| (96.5% / 97.1% on
    # spot-start STANDARD prints). Pinned as a literal list rather than as a
    # count: a count survives a substitution, and a substituted tenor is a
    # column of the chart that quietly stops matching the tape.
    assert B.TENORS["SOFR"] == (
        "1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "4Y",
        "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "12Y", "15Y", "20Y", "25Y", "30Y")
    assert len(B.TENORS["SOFR"]) == 21


def test_the_fed_funds_grid_is_the_12_tenors_that_were_measured():
    # 88.7% of FF flow prints, 90.4% of |risk|. Widening to 19 buys 93.5% for
    # +10 s/day and +9,086 rows/day -- measured, and not worth it.
    assert B.TENORS["FED_FUNDS"] == (
        "1M", "2M", "3M", "4M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "5Y",
        "10Y")
    assert len(B.TENORS["FED_FUNDS"]) == 12


def test_40Y_is_absent_on_purpose():
    # 9.7 ms of a 67.5 ms SOFR grid minute -- 17% of the cost -- for 2.4
    # prints a day.
    assert "40Y" not in B.TENORS["SOFR"]
    assert "40Y" not in B.TENORS["FED_FUNDS"]


@pytest.mark.parametrize("index", ["SOFR", "FED_FUNDS"])
def test_every_tenor_label_is_a_label_rateslib_can_advance(index):
    for tn in B.TENORS[index]:
        assert re.fullmatch(r"\d+[DWMY]", tn), tn
    assert len(set(B.TENORS[index])) == len(B.TENORS[index]), "duplicate tenor"


def test_the_grid_covers_exactly_the_two_indices_the_universe_admits():
    assert B.INDICES == ("SOFR", "FED_FUNDS")
    assert set(B.TENORS) == set(B.INDICES)
    assert set(snapshot.CURVE_FOR) == set(B.INDICES)


# ==========================================================================
# the pricer is the direction pipeline's own
# ==========================================================================

def test_the_source_token_is_the_RL_spelling():
    """A "-QL" spelling never consults the minute store.

    ``IRSwapsMDP._build_citivelo_excel_curve`` gates ``_store_eligible`` on
    ``backend == "rl"``, so a QL token makes every strict request miss -- which
    is indistinguishable from a cold store, and was.
    """
    assert snapshot.CURVE_SOURCE == "CITIVELO_EXCEL"
    assert not snapshot.CURVE_SOURCE.upper().endswith("-QL")


def test_the_runner_reaches_the_curve_through_the_direction_pipelines_pricer():
    src = (__import__("pathlib").Path(B.__file__)).read_text(encoding="utf-8")
    # The engines are built from UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    # and the grid uses that repricer's own SessionBranchPricer. A second,
    # independent discount-factor path is the failure this whole design exists
    # to prevent, so it is pinned in the source rather than left to review.
    assert "UnitRepricer.for_source(snapshot.CURVE_SOURCE)" in src
    assert "rep.pricer" in src
    assert "day_scope()" in src


def test_the_minute_asset_is_spelled_the_way_the_MDP_spells_it():
    # `IRSwapsMDP.py:3207`: asset = f"{curve_name}-CITIVELOEXCELMIN". If the
    # asset the grid instants come from is not the asset the pricer serves
    # from, every minute misses.
    assert B.minute_asset("USD-SOFR-1D") == "USD-SOFR-1D-CITIVELOEXCELMIN"
    assert B.minute_asset("USD-FEDFUNDS-1D") == (
        "USD-FEDFUNDS-1D-CITIVELOEXCELMIN")


def test_the_spot_rule_is_two_business_days_off_the_curves_reference_date():
    # `RLIRSwapCurve.build_irswap(fwd="0D")`'s own rule, reproducing the tape's
    # modal effective date on 99.3% of prints.
    assert B.SPOT_TENOR == "2b"


# ==========================================================================
# the join arithmetic: this IS the join rule
# ==========================================================================

def test_snap_instant_floors_to_the_minute_and_steps_back_one():
    """The grid is looked up at this instant, by equality.

    `arbs_dd_unit_v1.curve_timestamp` already holds it (973,305/973,305 rows
    carry second = 0), which is why a 1-minute grid reproduces the annotation's
    own mid to 2.7e-13 bp. Looking the grid up at the print's own execution
    minute returns the minute AFTER the one the annotation priced at.
    """
    trade = NY.localize(datetime.datetime(2026, 4, 1, 12, 5, 30))
    got = pd.Timestamp(snapshot.snap_instant(trade)).tz_convert(NY)
    assert (got.hour, got.minute, got.second) == (12, 4, 0)


def test_the_snap_is_a_whole_minute_for_every_second_of_a_minute():
    base = datetime.datetime(2026, 4, 1, 12, 5)
    seen = set()
    for sec in range(0, 60):
        t = NY.localize(base.replace(second=sec, microsecond=500))
        got = pd.Timestamp(snapshot.snap_instant(t)).tz_convert(NY)
        assert got.second == 0 and got.microsecond == 0
        seen.add((got.hour, got.minute))
    assert seen == {(12, 4)}, (
        "every second of 12:05 must snap to the same grid minute, or the join "
        "key is not a function of the minute")


def test_the_snap_at_the_top_of_the_minute_steps_back_a_full_minute():
    t = NY.localize(datetime.datetime(2026, 4, 1, 12, 5, 0))
    got = pd.Timestamp(snapshot.snap_instant(t)).tz_convert(NY)
    assert (got.hour, got.minute) == (12, 4)


def test_the_grid_minutes_are_the_stores_own_stamps_floored_and_deduplicated():
    """`_day_minutes` is the whole "grid instants come from the store" rule.

    A generated date_range would waste strict misses on truncated sessions and
    get DST days wrong; the store's stamps carry both for free.
    """
    class _Store:
        def read_raw_day(self, asset, day):
            return pd.DataFrame({"timestamp_utc": pd.to_datetime([
                "2026-04-01 13:00:00", "2026-04-01 13:00:31",   # same minute
                "2026-04-01 13:02:00",
                "2026-04-01 13:01:00",                          # out of order
            ], utc=True)})

    got = B._day_minutes(_Store(), "X", datetime.date(2026, 4, 1), NY)
    assert [t.strftime("%H:%M:%S") for t in got] == ["09:00:00", "09:01:00",
                                                     "09:02:00"]
    assert all(t.second == 0 for t in got)
    assert got == sorted(got)
    assert all(str(t.tz) == "America/New_York" for t in got)


def test_an_empty_partition_yields_no_minutes_rather_than_a_fabricated_range():
    class _Empty:
        def read_raw_day(self, asset, day):
            return pd.DataFrame()

    assert B._day_minutes(_Empty(), "X", datetime.date(2026, 4, 1), NY) == []


# ==========================================================================
# the session window is delegated, not re-derived
# ==========================================================================

def test_the_session_bounds_come_from_the_module_that_measured_them():
    from MDP.IRSwaps.CITIVELO_EXCEL.citi_session import CITI_USD_SESSION as C
    assert C.day_open_minute_et == 60            # 01:00 ET, inclusive
    assert C.day_close_minute_et == 22 * 60 + 59  # 22:59 ET, inclusive


@pytest.mark.parametrize("hh,mm,expected", [
    (0, 30, False),   # the nightly hole: Citi publishes nothing 23:00-00:59 ET
    (0, 59, False),
    (1, 0, True),     # inclusive at both edges
    (12, 0, True),
    (22, 59, True),
    (23, 0, False),
])
def test_the_nightly_hole_is_23_00_to_00_59_ET(hh, mm, expected):
    from MDP.IRSwaps.CITIVELO_EXCEL import citi_session
    t = NY.localize(datetime.datetime(2026, 4, 1, hh, mm))  # a Wednesday
    assert citi_session.publishes("USD-SOFR-1D", t) is expected


def test_a_full_weekday_session_is_1320_minutes_but_the_floor_is_not():
    from MDP.IRSwaps.CITIVELO_EXCEL import citi_session
    n = citi_session.expected_minutes("USD-SOFR-1D", datetime.date(2026, 4, 1))
    assert n == 1320, "01:00..22:59 ET inclusive"
    # ...and the completion check must NOT be against it. Truncated sessions
    # are real -- 2026-04-02 ends 19:59 ET, the minimum observed is 911 of
    # 1,320 -- so the hard check is an equality against what was served and
    # this is only the soft, reportable comparison.
    assert B.DEFAULT_DENSITY_WARN < 911 / 1320 < 1.0
    assert B.DEFAULT_SERVED_FLOOR >= 0.99


def test_saturday_has_no_session_at_all_and_that_is_not_an_error():
    from MDP.IRSwaps.CITIVELO_EXCEL import citi_session
    sat = datetime.date(2026, 4, 4)
    assert sat.weekday() == 5
    assert citi_session.expected_minutes("USD-SOFR-1D", sat) == 0
    assert B.STATUS_NO_SESSION == "NO_SESSION"


# ==========================================================================
# the per-day accounting, which is what "done" means
# ==========================================================================

def test_the_accounting_row_cannot_be_built_positionally():
    """Six of its thirteen fields are integer counts that mean different things.

    Positionally, transposing `served` and `missed` -- or `n_rows` and
    `n_tenors` -- inserts cleanly and makes the completion check assert the
    wrong equality. The arity error that caught this on the runner's first real
    invocation was the lucky version of that mistake, so the signature is
    keyword-only and this pins it.
    """
    with pytest.raises(TypeError):
        B._day_row("2026-04-01", "SOFR", "USD-SOFR-1D", 1299, 1320, 1299, 0,
                   1299 * 21, 21, 1, B.STATUS_OK, None, "v")


def test_the_completion_check_is_an_equality_over_served_minutes():
    row = B._day_row(day="2026-04-01", index="SOFR", curve="USD-SOFR-1D",
                     partition_minutes=1299, expected=1320, served=1299,
                     missed=0, n_rows=1299 * 21, n_tenors=21, n_refs=1,
                     status=B.STATUS_OK, error=None, vintage="deadbeef")
    assert row["n_rows"] == row["n_tenors"] * row["minutes_served"]
    # 21 x 1,299 + 12 x 1,298 = 42,855 rows was the measured pilot day.
    assert row["n_rows"] == 27279
    assert row["partition_minutes"] <= row["session_expected_minutes"]


def test_the_ledger_carries_the_denominator_the_database_cannot_see():
    for c in ("partition_minutes", "session_expected_minutes", "minutes_served",
              "minutes_missed", "n_rows", "n_tenors"):
        assert c in B.DAY_COLS, c


# ==========================================================================
# build_one_day itself, against a fake pricer
#
# Everything above this point pins constants, DDL and arithmetic. These drive
# the real `build_one_day` -- the skip path, the row-count equality, the
# circularity guard and the non-finite refusal -- through a substituted pricer,
# because those are behaviours no assertion about a constant can reach. The
# seam substituted is the one `midprice.UnitRepricer` documents as five members
# wide; the guard object itself is the real `UnitRepricer`, so the rule under
# test is the frozen package's own and not a copy of it.
# ==========================================================================

DAY = datetime.date(2026, 4, 1)          # a Wednesday, 1,320 published minutes


def _minutes(n: int, *, day: datetime.date = DAY, start_hour: int = 13):
    """`n` consecutive whole minutes of one ET date, as the store stamps them."""
    base = pd.Timestamp(datetime.datetime.combine(
        day, datetime.time(start_hour, 0)), tz=NY)
    return [base + pd.Timedelta(minutes=i) for i in range(n)]


class _FakeStore:
    """`read_raw_day` -> the stamps this partition holds, in UTC, unsorted."""

    def __init__(self, stamps):
        self._stamps = list(stamps)

    def read_raw_day(self, asset, day):
        return pd.DataFrame({"timestamp_utc": pd.to_datetime(
            [pd.Timestamp(t).tz_convert("UTC") for t in self._stamps],
            utc=True)})


class _FakeHandle:
    """Enough of a curve handle to define the instrument, and nothing more."""

    def __init__(self, ref: datetime.date):
        self._ref = ref

    def reference_date(self):
        return self._ref

    def calendar_advance(self, d, tenor):
        d = pd.Timestamp(d)
        if tenor == "2b":
            return (d + pd.Timedelta(days=2)).date()
        n, unit = int(tenor[:-1]), tenor[-1]
        step = {"D": pd.DateOffset(days=n), "W": pd.DateOffset(weeks=n),
                "M": pd.DateOffset(months=n), "Y": pd.DateOffset(years=n)}[unit]
        return (d + step).date()


class _FakeLegPricing:
    def __init__(self, mid, pv01):
        self.mid_pct = mid
        self.pv01 = pv01


class _FakePricer:
    """The five-member seam. Refuses named minutes; marks are configurable."""

    def __init__(self, *, refuse=(), lag=0.0, from_future=False,
                 mid=3.9251, ref=datetime.date(2026, 4, 1)):
        self.refuse = {pd.Timestamp(t) for t in refuse}
        self.lag, self.from_future, self.mid = lag, from_future, mid
        self.handle = _FakeHandle(ref)
        self.priced = []

    snapshot_governed = True

    def curve_for(self, rate_index):
        return snapshot.CURVE_FOR[rate_index]

    def day_scope(self):
        import contextlib
        return contextlib.nullcontext(self)

    def mark_curve(self, curve_name, instant):
        from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss
        if pd.Timestamp(instant) in self.refuse:
            raise SnapshotMiss(f"no snapshot for {instant}")
        return midprice.CurveMark(
            policy=midprice.POLICY_STRICT, curve_name=curve_name,
            requested=pd.Timestamp(instant), lag_seconds=self.lag,
            served_from_future=self.from_future,
            served_utc=(None if self.lag is None else
                        pd.Timestamp(instant).tz_convert("UTC")
                        - pd.Timedelta(seconds=self.lag)),
            handle=self.handle)

    def price_leg(self, curve_name, instant, eff, mat, notional,
                  fixed_rate=None):
        self.priced.append((curve_name, pd.Timestamp(instant), eff, mat))
        return _FakeLegPricing(self.mid, 950.0)


def _install(monkeypatch, pricer, stamps):
    """`_ENGINES` is the worker's lazily-built (repricer, pricer, store)."""
    rep = midprice.UnitRepricer(pricer)      # the REAL guard, a fake seam
    monkeypatch.setattr(B, "_ENGINES", (rep, pricer, _FakeStore(stamps)))


def _run(tmp_path, monkeypatch, pricer, stamps):
    _install(monkeypatch, pricer, stamps)
    paths = B.Paths(tmp_path)
    paths.mkdirs()
    return B.build_one_day(DAY.isoformat(), paths, dry_run=True, reprice=True)


def test_a_refused_minute_produces_no_row_and_is_counted_instead(tmp_path,
                                                                 monkeypatch):
    """The whole "skipped and counted, never fabricated" rule, on real code.

    A carried-forward or interpolated value for a minute the store could not
    answer is indistinguishable from a real mark once it is on the chart, so
    the refused minutes must be absent from the frame AND present in the
    accounting.
    """
    stamps = _minutes(6)
    refused = {stamps[2], stamps[4]}
    res = _run(tmp_path, monkeypatch, _FakePricer(refuse=refused), stamps)

    n_sofr, n_ff = len(B.TENORS["SOFR"]), len(B.TENORS["FED_FUNDS"])
    assert res["missed"] == 2 * len(B.INDICES)
    assert res["rows"] == 4 * n_sofr + 4 * n_ff
    df = pd.read_parquet(B.Paths(tmp_path).parquet(DAY.isoformat()))
    got = {pd.Timestamp(t) for t in pd.to_datetime(df["ts"], utc=True)}
    for t in refused:
        assert pd.Timestamp(t).tz_convert("UTC") not in got, (
            "a minute the store refused has a row anyway -- something "
            "fabricated it")
    assert len(got) == 4


def test_the_row_count_is_the_equality_the_completion_check_asserts(tmp_path,
                                                                    monkeypatch):
    stamps = _minutes(5)
    res = _run(tmp_path, monkeypatch, _FakePricer(), stamps)
    assert res["rows"] == 5 * (len(B.TENORS["SOFR"]) + len(B.TENORS["FED_FUNDS"]))
    import json
    rows = json.loads(B.Paths(tmp_path).stats(DAY.isoformat()).read_text())
    for r in rows:
        assert r["n_rows"] == r["n_tenors"] * r["minutes_served"]
        assert r["minutes_served"] + r["minutes_missed"] == r["partition_minutes"]
        assert r["session_expected_minutes"] == 1320


def test_a_snapshot_served_from_after_its_own_timestamp_fails_the_day(
        tmp_path, monkeypatch):
    """A negative lag is a curve that can contain the prints drawn on it.

    Structurally impossible under both policies here -- `strict()` and the
    out-of-session `asof` both set `allow_future=False` -- which is exactly why
    it is checked. `verify`'s `max(abs(lag))` is blind to it by construction.
    """
    with pytest.raises(midprice.CircularCurve):
        _run(tmp_path, monkeypatch, _FakePricer(lag=-30.0), _minutes(3))


def test_the_served_from_future_flag_alone_also_fails_the_day(tmp_path,
                                                              monkeypatch):
    # The flag and the sign of the lag are one fact written twice, and the
    # guard reads both: a guard that tested only the lag sign would pass this.
    with pytest.raises(midprice.CircularCurve):
        _run(tmp_path, monkeypatch,
             _FakePricer(lag=30.0, from_future=True), _minutes(3))


def test_a_mark_with_no_lag_telemetry_at_all_fails_the_day(tmp_path,
                                                           monkeypatch):
    """A whole run of `lag=None` is indistinguishable from a correct one.

    `RLIRSwapCurve` exposes `.meta()`, not `.meta_data`; that exact run
    happened once and every price on it looked fine.
    """
    with pytest.raises(midprice.LagTelemetryMissing):
        _run(tmp_path, monkeypatch, _FakePricer(lag=None), _minutes(3))


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_mid_fails_the_day_rather_than_writing_a_hole(
        bad, tmp_path, monkeypatch):
    # The curve WAS served, so this is a pricing defect, not a store hole. A
    # skipped row here would read as a market that was not publishing.
    with pytest.raises(RuntimeError, match="non-finite mid"):
        _run(tmp_path, monkeypatch, _FakePricer(mid=bad), _minutes(2))


def test_every_grid_row_is_priced_at_its_own_stamped_instant(tmp_path,
                                                             monkeypatch):
    """`ts` is the instant the row was priced at, not a nearby one.

    The front end joins by equality on this column, so a row stamped with a
    minute it was not priced at is a silent one-minute lookahead or lookbehind
    on every point of the chart.
    """
    stamps = _minutes(4)
    pricer = _FakePricer()
    _run(tmp_path, monkeypatch, pricer, stamps)
    df = pd.read_parquet(B.Paths(tmp_path).parquet(DAY.isoformat()))
    priced_at = sorted({t for _, t, _, _ in pricer.priced})
    assert priced_at == sorted(pd.Timestamp(t) for t in stamps)
    assert {pd.Timestamp(t) for t in pd.to_datetime(df["ts"], utc=True)} == {
        pd.Timestamp(t).tz_convert("UTC") for t in stamps}


def test_a_stamp_from_a_neighbouring_ET_date_is_not_drawn_into_this_day():
    """`grid_date` must stay a true function of `ts`.

    The primary key is (rate_index, tenor_label, ts) and the delete is by
    `grid_date`, so a stamp that strayed across the date boundary would let two
    days claim one row and the later publish would rewrite the earlier day's
    `grid_date` out from under it.
    """
    stamps = _minutes(2) + [pd.Timestamp(datetime.datetime(2026, 4, 2, 0, 30),
                                         tz=NY)]
    got = B._day_minutes(_FakeStore(stamps), "X", DAY, NY)
    assert len(got) == 2
    assert {t.date() for t in got} == {DAY}


def test_a_stale_staged_parquet_is_a_cache_MISS_not_a_frame_to_be_padded(
        tmp_path):
    """`reindex` would manufacture an absent column as all-NaN.

    The NOT NULL columns fail the insert loudly, but `served_ts`, `pv01` and
    `snapshot_lag_seconds` are nullable -- so a stage written by an older
    version of this runner would publish NULL provenance for a whole day and
    read as a curve that reported nothing.
    """
    import json
    paths = B.Paths(tmp_path)
    paths.mkdirs()
    day = DAY.isoformat()
    full = pd.DataFrame([{c: 1 for c in B.GRID_COLS}])
    paths.stats(day).write_text(json.dumps([{"rate_index": "SOFR"}]),
                                encoding="utf-8")
    full.to_parquet(paths.parquet(day), index=False)
    assert B._load_cached(paths, day) is not None

    full.drop(columns=["served_ts"]).to_parquet(paths.parquet(day), index=False)
    assert B._load_cached(paths, day) is None


# ==========================================================================
# the validate gate can fail, and has been run in both directions
# ==========================================================================

def _gate_frame(errs, dts=None):
    dts = [0.0] * len(errs) if dts is None else dts
    return pd.DataFrame({"err_bp": errs, "dt_s": dts})


def test_the_validate_gate_passes_at_the_measured_noise_floor():
    rc, msg = B.validate_gate(_gate_frame([7.1e-13, -4.4e-14, 0.0]))
    assert rc == 0 and "PASS" in msg


def test_the_validate_gate_fails_on_a_divergence_a_trader_could_see():
    # Half a basis point: the exact failure this stage exists to catch, and the
    # size a convention fault (day count, roll, spot lag) actually produces.
    rc, msg = B.validate_gate(_gate_frame([1e-13, 0.5]))
    assert rc == 1 and "FAIL" in msg


def test_the_validate_gate_fails_on_an_empty_sample():
    """An empty check is not a pass -- and this is the realistic way to get one.

    A window whose grid was never backfilled matches no prints at all; without
    this the stage would print "n=0" and exit 0.
    """
    assert B.validate_gate(_gate_frame([]))[0] == 1
    assert B.validate_gate(None)[0] == 1
    # ...including when prints exist but none of them land ON a grid point,
    # which is what a coarser grid would look like.
    assert B.validate_gate(_gate_frame([1e-13, 1e-13], dts=[45.0, 900.0]))[0] == 1


def test_the_gate_is_machine_precision_and_not_a_tolerance():
    # Seven orders above the measured 7.1e-13 bp maximum and six below
    # anything a trader could see. Nothing real lands in between, so widening
    # this is the precise way to hide a convention fault.
    assert B.VALIDATE_MAX_ABS_BP == 1e-6
    assert 7.1e-13 < B.VALIDATE_MAX_ABS_BP < 0.01


def test_the_gate_is_scoped_to_the_join_the_front_end_actually_makes():
    """dt = 0 only. Off the grid point the comparison is not an identity.

    In the 23:00-00:59 ET hole no grid row exists, so an hour-00 print matches
    forward to the next session's 01:00 point where the grid's spot is a
    business day behind the print's own -- <= 0.42 bp, measured, and the
    instrument differing rather than the mid. Gating on those would fail the
    pipeline for the calendar.
    """
    rc, _ = B.validate_gate(_gate_frame([1e-13, 0.42], dts=[0.0, 3600.0]))
    assert rc == 0


# ==========================================================================
# psycopg2 adapts neither numpy scalars nor NaN -- and there is ONE adapter
# ==========================================================================

def test_the_runner_uses_the_dealer_direction_adapter_rather_than_its_own():
    from SDRUtils._swappulse_scripts import backfill_dealer_direction as D
    assert B._sanitize is D._sanitize
    assert B._atomic_parquet is D._atomic_parquet


@pytest.mark.parametrize("raw,expected", [
    (np.float64(3.9251), 3.9251),
    (np.int64(1299), 1299),
    (np.bool_(True), True),
    (float("nan"), None),
    (float("inf"), None),
    (pd.NaT, None),
    (None, None),
    ("STRICT_1MIN_IN_SESSION", "STRICT_1MIN_IN_SESSION"),
])
def test_the_adapter_unwraps_numpy_and_nulls_the_non_finite(raw, expected):
    got = B._sanitize(raw)
    assert got == expected or (got is None and expected is None)
    assert not isinstance(got, np.generic)


def test_the_adapter_returns_a_real_datetime_not_a_timestamp():
    got = B._sanitize(pd.Timestamp("2026-04-01 13:04:00+00:00"))
    assert isinstance(got, datetime.datetime)
    assert not isinstance(got, pd.Timestamp)


def test_a_non_finite_mid_is_nulled_by_the_adapter_which_is_why_it_is_refused():
    """The guard in the runner, and the reason it cannot be relaxed.

    `_sanitize` turns a NaN into None, and `mid_pct` is NOT NULL, so a
    non-finite mark would abort the insert for the whole day with a constraint
    error rather than a diagnosis. The runner refuses it at the point of
    pricing, naming the index, tenor and instant.
    """
    assert B._sanitize(float("nan")) is None
    assert B._f(float("nan")) is None
    assert B._f(float("inf")) is None
    assert B._f(3.9251) == 3.9251


# ==========================================================================
# the served instant is recorded, not inferred at read time
# ==========================================================================

class _Mark:
    def __init__(self, served_utc, lag):
        self.served_utc = served_utc
        self.lag_seconds = lag


def test_the_served_instant_is_read_from_the_handles_own_metadata():
    req = pd.Timestamp("2026-04-01 13:04:00", tz="UTC")
    got = B._served_ts(_Mark(pd.Timestamp("2026-04-01 13:03:00"), 60.0), req)
    assert got == pd.Timestamp("2026-04-01 13:03:00", tz="UTC")


def test_the_served_instant_falls_back_to_the_signed_lag():
    """The lag and the served stamp are one fact written twice.

    ``IRSwapsMDP.py:3336`` publishes ``signed = (wanted - actual)`` and the
    served instant from the same line, so reconstructing one from the other
    cannot disagree with it.
    """
    req = pd.Timestamp("2026-04-01 13:04:00", tz="UTC")
    assert B._served_ts(_Mark(None, 120.0), req) == pd.Timestamp(
        "2026-04-01 13:02:00", tz="UTC")
    assert B._served_ts(_Mark(None, None), req) is None


# ==========================================================================
# the validate stage measures the identity it claims to
# ==========================================================================

def test_the_validation_identity_is_the_one_the_direction_pipeline_writes():
    """implied_mid_pct = fixed_rate*100 - deviation_bps/100.

    `backfill_dealer_direction.py:524-530` writes
    ``deviation_bps = structure_price(traded) - structure_price(mid)`` and for
    an OUTRIGHT ``quote_weights = (1,)``, so ``structure_price(x_pct) =
    x_pct * 100``. The identity is exact, not approximate -- reproduced here on
    the arithmetic rather than trusted to a comment.
    """
    from SDRUtils.dealer_direction import conventions as conv
    traded_pct, mid_pct = 3.925100, 3.919800
    dev = conv.structure_price([traded_pct], conv.OUTRIGHT, 1, conv.RULE_RATE) \
        - conv.structure_price([mid_pct], conv.OUTRIGHT, 1, conv.RULE_RATE)
    implied = traded_pct - dev / 100.0
    assert abs(implied - mid_pct) < 1e-12
    assert abs(dev - (traded_pct - mid_pct) * 100.0) < 1e-12


def test_the_validate_query_selects_only_the_population_the_identity_holds_on():
    sql = B.VALIDATE_SQL
    for clause in ("kind = 'OUTRIGHT'", "n_legs = 1", "rule = 'RATE_VS_MID'",
                   "exclusion_reason IS NULL",
                   "special_tenor_type = 'STANDARD'"):
        assert clause in sql, clause
    # A forward-start or past-start print is not the same instrument as a spot
    # grid point, so it cannot score the grid.
    assert "forward_start_years" in sql
    # And the tenor filter is per (index, tenor) PAIR, not the union of the two
    # tenor sets: on 2025-10-15 the union left 11 prints of 647 "unmatched",
    # every one a SOFR 4M or a FED_FUNDS 4Y/7Y -- a tenor in the OTHER index's
    # grid, absent from its own by construction.
    assert "(u.rate_index, l.tenor_label) IN %(pairs)s" in sql
    assert "l.tenor_label = ANY" not in sql


def test_the_validate_lookup_is_bounded_and_reports_its_own_distance():
    # The nearest grid point, within a bounded window, with the distance kept:
    # the by-distance split is the only thing that says whether the spacing is
    # too coarse, and an equality join would throw it away.
    assert "interval '2 hours'" in B.NEAREST_SQL
    assert "ORDER BY abs(extract(epoch FROM (m.ts - p.curve_timestamp)))" in (
        B.NEAREST_SQL)
    assert "LIMIT 1" in B.NEAREST_SQL


# ==========================================================================
# the stages exist and the defaults respect the box
# ==========================================================================

def test_the_stages_are_the_four_named_plus_the_validation():
    # Read off the parser, not off a list beside it: a stage that is dropped
    # from the parser fails as a stage nobody runs, which is silent.
    stage = [a for a in B.build_parser()._actions if a.dest == "stage"][0]
    assert set(stage.choices) == {"schema", "backfill", "verify", "validate",
                                  "status"}
    assert set(B.STAGES) == set(stage.choices)


def test_the_backfill_stage_can_be_asked_to_write_nothing():
    args = B.build_parser().parse_args(["backfill", "--dry-run", "--workers", "1"])
    assert args.dry_run is True and args.workers == 1 and args.stage == "backfill"


def test_the_default_worker_count_respects_a_loaded_box():
    src = (__import__("pathlib").Path(B.__file__)).read_text(encoding="utf-8")
    m = re.search(r'"--workers", type=int, default=(\d+)', src)
    assert m and int(m.group(1)) <= 2, (
        "the default must not saturate a box that is already carrying other "
        "long jobs; the caller widens it deliberately")


def test_the_grid_floor_is_the_tape_floor_and_the_store_covers_it():
    # Measured: both minute stores hold 610 of 610 tape days from here, so no
    # store-floor truncation is needed.
    assert B.GRID_FLOOR == "2024-03-01"

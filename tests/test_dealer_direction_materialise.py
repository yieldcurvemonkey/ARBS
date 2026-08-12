"""The materialisation seam: schema, sign mapping, and the numpy adapter.

Everything here is offline. The pieces that need the tape or the curve store
are exercised by the runner's own pilot, which is a measurement rather than a
test; what is pinned here is the part that would fail silently.
"""
from __future__ import annotations

import datetime
import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

from SDRUtils._swappulse_scripts import _dealer_direction_schema_v1 as S  # noqa: E402
from SDRUtils.dealer_direction import indicator as ind  # noqa: E402
from SDRUtils.dealer_direction import ladder as ladder_mod  # noqa: E402
from SDRUtils.dealer_direction import provenance as prov  # noqa: E402
from SDRUtils.dealer_direction import types as T  # noqa: E402


# ==========================================================================
# the sign convention, at the seam where it becomes a word
# ==========================================================================

def _label(sign, exclusion=None):
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import direction_label
    return direction_label(sign, exclusion)


def test_a_positive_dealer_sign_is_RECEIVED_and_that_is_not_reversible():
    # customer pays fixed -> dealer RECEIVED fixed -> long duration
    #                     -> delta_dv01 > 0
    assert _label(1) == "RECEIVED"
    assert _label(-1) == "PAID"
    # Named explicitly rather than "the two differ": a comparative assertion
    # survives a global flip, which is exactly how an inverted z-score got
    # through a 59-test green suite on the backend work.
    assert _label(1) != "PAID"
    assert _label(-1) != "RECEIVED"


def test_no_call_is_ABSTAINED_not_a_side():
    assert _label(0) == "ABSTAINED"
    assert _label(None) == "ABSTAINED"


def test_an_exclusion_wins_over_any_sign():
    # A unit can carry a sign from a rule that then refused it. The reason is
    # what the reader must see, not a side we did not stand behind.
    assert _label(1, "UNORIENTABLE_PKG") == "ABSTAINED"
    assert _label(-1, "PKG_SIGNS_AMBIGUOUS") == "ABSTAINED"


def test_the_three_labels_are_the_only_ones():
    from SDRUtils._swappulse_scripts import backfill_dealer_direction as B
    assert {B.DIR_RECEIVED, B.DIR_PAID, B.DIR_ABSTAINED} == {
        "RECEIVED", "PAID", "ABSTAINED"}


# ==========================================================================
# the ladder table mirrors indicator.CELL_COLUMNS, verbatim
# ==========================================================================

def test_the_ladder_table_columns_are_the_indicator_cells_plus_the_coverage_pair():
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import (
        LADDER_DB_COLUMNS,
    )
    expected = list(ind.CELL_COLUMNS) + ["coverage_dv01_kept", "coverage_dv01_total"]
    # Set equality, because the DDL orders the keys first for readability.
    assert set(LADDER_DB_COLUMNS) == set(expected), (
        "the ladder table must carry indicator's published columns and nothing "
        "renamed; renaming at this seam is where a translation bug lives"
    )
    assert len(LADDER_DB_COLUMNS) == len(expected)


def test_no_published_ladder_column_accumulates():
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import (
        LADDER_DB_COLUMNS,
    )
    # Compression and allocation are never publicly reported, so a running sum
    # carries an unbounded monotone error. `indicator` refuses cumulate();
    # the table must not smuggle one in under another name.
    for c in LADDER_DB_COLUMNS:
        assert "cum" not in c.lower()
        assert "inventory" not in c.lower()
        assert "position" not in c.lower()
        assert "decay" not in c.lower()


def test_the_ladder_ddl_declares_every_published_column():
    ddl = "\n".join(S.DDL_STATEMENTS)
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import (
        LADDER_DB_COLUMNS,
    )
    for c in LADDER_DB_COLUMNS:
        assert f"    {c} " in ddl or f"    {c}\n" in ddl, f"{c} missing from the DDL"


# ==========================================================================
# both keys are stored, and the join key is package_id
# ==========================================================================

def test_the_unit_table_carries_BOTH_keys():
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import (
        UNIT_DB_COLUMNS,
    )
    # package_id is the display view's grain and what the front end joins.
    # unit_key is the backend's identity and every dealer_direction frame is
    # keyed on it. Measured over five days spanning the whole tape, unit_key
    # matches the view on 21.7-29.3% of rows and package_id on 100.0000%.
    assert "package_id" in UNIT_DB_COLUMNS
    assert "unit_key" in UNIT_DB_COLUMNS


def test_package_id_is_the_primary_key_of_the_unit_table():
    ddl = "\n".join(S.DDL_STATEMENTS)
    assert "package_id              TEXT PRIMARY KEY" in ddl


def test_the_unit_bucket_table_is_keyed_on_package_id_and_bucket():
    ddl = "\n".join(S.DDL_STATEMENTS)
    assert "PRIMARY KEY (package_id, bucket_key)" in ddl


# ==========================================================================
# the coverage table is a partition, and it stores kept AND total
# ==========================================================================

def test_coverage_stores_a_reason_per_row_so_kept_and_total_both_roll_up():
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import (
        COVERAGE_DB_COLUMNS,
    )
    assert "reason" in COVERAGE_DB_COLUMNS
    assert "dv01" in COVERAGE_DB_COLUMNS
    # A ratio alone cannot be re-aggregated and the denominator is the only
    # thing that knows about the units that were excluded, so the table stores
    # neither a ratio nor a bare kept figure.
    assert "coverage_frac" not in COVERAGE_DB_COLUMNS
    assert "dv01_kept" not in COVERAGE_DB_COLUMNS


def test_IN_LADDER_agrees_with_provenance():
    assert S.IN_LADDER == prov.IN_LADDER


# ==========================================================================
# the vocabulary the front end renders
# ==========================================================================

def test_every_exclusion_constant_has_a_phrase_on_the_front_end():
    """The TS phrase map must cover every code the backend can emit."""
    import pathlib
    import re

    ts = (pathlib.Path(__file__).resolve().parents[1] / "SDRUtils" / "dashboard"
          / "src" / "features" / "usd-swaps-tape-v2" / "utils"
          / "dealerDirection.ts").read_text(encoding="utf-8")
    phrases = set(re.findall(r"^\s{2}([A-Z][A-Z0-9_]+):", ts, re.M))

    from SDRUtils.dealer_direction import package_price as pp
    from SDRUtils.dealer_direction import upfront as U
    codes = {v for k, v in vars(T).items()
             if k.startswith("EXCL_") and isinstance(v, str)}
    codes |= {v for k, v in vars(pp).items()
              if k.startswith("EXCL_") and isinstance(v, str)}
    codes |= {v for k, v in vars(U).items()
              if k.startswith("EXCL_") and isinstance(v, str)}
    codes |= {"NO_CALIBRATION"}   # minted by the runner itself

    missing = sorted(codes - phrases)
    assert not missing, (
        f"{missing} can reach a rendered row with no phrase. An abstention "
        "that cannot say why reads as an absence of flow."
    )


def test_the_venue_classes_are_the_three_the_backend_uses():
    assert (T.VENUE_D2C, T.VENUE_D2D, T.VENUE_UNKNOWN) == (
        "D2C", "D2D", "VENUE_UNKNOWN")
    # Not "UNKNOWN": accepting that spelling would serve an empty third series
    # that looks like no flow rather than like a wrong parameter.
    assert T.VENUE_UNKNOWN != "UNKNOWN"


def test_the_series_names_are_the_ladder_constants():
    assert (ladder_mod.SERIES_FLOW, ladder_mod.SERIES_LIFECYCLE) == (
        "FLOW", "LIFECYCLE")


# ==========================================================================
# psycopg2 adapts neither numpy scalars nor NaN
# ==========================================================================

@pytest.mark.parametrize("raw,expected", [
    (np.float64(1.5), 1.5),
    (np.int64(3), 3),
    (np.bool_(True), True),
    (float("nan"), None),
    (float("inf"), None),
    (np.nan, None),
    (pd.NaT, None),
    (None, None),
    ("x", "x"),
    (True, True),
])
def test_the_adapter_unwraps_numpy_and_nulls_the_non_finite(raw, expected):
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import _sanitize
    got = _sanitize(raw)
    assert got == expected or (got is None and expected is None)
    assert not isinstance(got, np.generic)


def test_a_string_field_that_came_back_as_nan_reads_as_absent():
    """`if r["pkg_exclusion"]:` was true on every package unit, for a day.

    A column in ``UNIT_COLS`` that no row assigns that day is created by
    ``reindex`` as an all-NaN **float64** column, parquet round-trips it as
    float64, and ``bool(nan)`` is ``True`` -- so a presence test on a string
    field fires on every row and hands the reason ``nan`` downstream. Neither
    a reason nor a null.
    """
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import _s

    assert _s(float("nan")) is None
    assert bool(float("nan")) is True, (
        "the premise of this test: NaN is truthy, which is why a bare "
        "presence test on a string field is unsafe"
    )
    assert _s(np.nan) is None
    assert _s(None) is None
    assert _s(pd.NaT) is None
    assert _s("") is None
    assert _s("UNORIENTABLE_PKG") == "UNORIENTABLE_PKG"
    assert _s(np.str_("PKG_TIEOUT_FAIL")) == "PKG_TIEOUT_FAIL"
    # A float where a string belongs is absent, not str(1.0).
    assert _s(1.0) is None


def test_an_all_none_string_column_round_trips_through_parquet_as_float(tmp_path):
    """The mechanism, reproduced rather than asserted from memory."""
    df = pd.DataFrame({"a": ["x", None]}).reindex(columns=["a", "never_set"])
    p = tmp_path / "t.parquet"
    df.to_parquet(p, index=False)
    back = pd.read_parquet(p)
    assert back["never_set"].dtype == np.float64
    rec = back.to_dict("records")[0]
    assert isinstance(rec["never_set"], float)
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import _s
    assert _s(rec["never_set"]) is None


def test_the_adapter_returns_a_real_datetime_not_a_timestamp():
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import _sanitize
    got = _sanitize(pd.Timestamp("2026-04-01 13:13:51+00:00"))
    assert isinstance(got, datetime.datetime)
    assert not isinstance(got, pd.Timestamp)


# ==========================================================================
# the shim carries exactly what the ladder reads
# ==========================================================================

def test_the_unit_shim_satisfies_ladder_unit_meta():
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import _shim
    row = {
        "unit_key": "U1", "package_id": "P1", "venue_class": "D2C",
        "is_lifecycle": False,
        "pricing_ts": pd.Timestamp("2026-04-01 13:13:00+00:00"),
        "execution_ts": pd.Timestamp("2026-04-01 13:13:51+00:00"),
        "event_ts": pd.Timestamp("2026-04-01 13:13:51+00:00"),
        "visibility_ts": pd.Timestamp("2026-04-01 14:13:51+00:00"),
        "visibility_source": "APPENDIX_C", "as_of_date": "2026-04-01",
        "rate_index": "SOFR", "kind": "OUTRIGHT", "n_legs": 1,
        "is_block": False, "is_capped": False,
    }
    meta = ladder_mod._unit_meta(_shim(row))
    assert meta["unit_key"] == "U1"
    assert meta["series"] == ladder_mod.SERIES_FLOW
    assert meta["venue_class"] == "D2C"
    assert meta["n_legs"] == 1
    assert meta["visibility_date"] == datetime.date(2026, 4, 1)


def test_a_lifecycle_unit_lands_in_the_lifecycle_series():
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import _shim
    row = {
        "unit_key": "U2", "venue_class": "D2C", "is_lifecycle": True,
        "pricing_ts": pd.Timestamp("2026-04-01 13:00:00+00:00"),
        "execution_ts": pd.Timestamp("2026-04-01 13:00:00+00:00"),
        "event_ts": pd.Timestamp("2026-04-01 13:00:00+00:00"),
        "visibility_ts": pd.Timestamp("2026-04-01 14:00:00+00:00"),
        "visibility_source": "APPENDIX_C", "as_of_date": "2026-04-01",
        "rate_index": "SOFR", "kind": "OUTRIGHT", "n_legs": 1,
        "is_block": False, "is_capped": False,
    }
    assert ladder_mod._unit_meta(_shim(row))["series"] == (
        ladder_mod.SERIES_LIFECYCLE)


# ==========================================================================
# the calibration must never see the day it calibrates
# ==========================================================================

class _FakeCal:
    def __init__(self, tag):
        self.tag = tag


def test_the_tau_set_takes_the_most_recent_window_that_ENDS_before_the_day():
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import TauSet
    d = datetime.date
    cals = {
        d(2026, 3, 1): (d(2026, 1, 1), d(2026, 2, 28), _FakeCal("A")),
        d(2026, 3, 6): (d(2026, 1, 6), d(2026, 3, 5), _FakeCal("B")),
        # a window that ENDS ON the day: must not be selected
        d(2026, 3, 11): (d(2026, 1, 11), d(2026, 3, 10), _FakeCal("C")),
    }
    ts = TauSet(cals)
    assert ts.for_day(d(2026, 3, 7)).tag == "B"
    assert ts.for_day(d(2026, 3, 10)).tag == "B", (
        "a window ending on the classification day puts that day's own "
        "deviations into its own b0"
    )
    assert ts.for_day(d(2026, 3, 11)).tag == "C"
    assert ts.for_day(d(2026, 1, 1)) is None


def test_a_day_with_no_prior_calibration_gets_none_rather_than_the_nearest():
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import TauSet
    d = datetime.date
    ts = TauSet({d(2026, 3, 1): (d(2026, 1, 1), d(2026, 2, 28), _FakeCal("A"))})
    assert ts.for_day(d(2025, 12, 1)) is None


# ==========================================================================
# the publish floor
# ==========================================================================

def test_the_publish_floor_is_the_indicator_sample_floor():
    assert ind.SAMPLE_FLOOR == datetime.date(2024, 7, 1)


def test_pricing_starts_before_the_publish_floor_so_day_one_is_calibrated():
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import (
        CALIB_WINDOW_DAYS, PRICE_FLOOR,
    )
    gap = (ind.SAMPLE_FLOOR - datetime.date.fromisoformat(PRICE_FLOOR)).days
    assert gap > CALIB_WINDOW_DAYS, (
        f"only {gap} calendar days of priced history sit in front of the "
        f"publish floor, against a {CALIB_WINDOW_DAYS}-day trailing window"
    )


# ==========================================================================
# the generation constants agree across the language boundary
# ==========================================================================

def test_the_dashboard_pins_the_same_generation():
    import pathlib
    import re
    ts = (pathlib.Path(__file__).resolve().parents[1] / "SDRUtils" / "dashboard"
          / "src" / "lib" / "dealer-direction-tables.ts").read_text(encoding="utf-8")
    m = re.search(r"DD_GENERATION\s*=\s*'([^']+)'", ts)
    assert m and m.group(1) == S.DD_GENERATION
    for name in (S.UNIT_TABLE, S.UNIT_BUCKET_TABLE, S.COVERAGE_TABLE,
                 S.LADDER_TABLE, S.RUNS_TABLE):
        assert name.startswith("arbs_dd_")


def test_the_tape_generation_travels_on_every_unit_row():
    from SDRUtils._swappulse_scripts.backfill_dealer_direction import (
        UNIT_DB_COLUMNS,
    )
    # code_vintage hashes the tape generation in, but a reader should not have
    # to decode a hash to learn which tape the row was built from.
    assert "tape_generation" in UNIT_DB_COLUMNS
    assert "code_vintage" in UNIT_DB_COLUMNS
    assert S.SOURCE_TAPE_GENERATION == "v3"

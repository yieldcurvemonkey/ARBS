"""Phase 1 primitives: sentinels, notation, timestamps, schedules, day count.

Covers findings B3 (timestamp), B4 (notation), B5 (sentinels), H3 (day count),
H8 (naive datetime), M12 (semicolon schedule).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import QuantLib as ql

from SDRUtils.core.conventions import DAY_COUNT_TABLE, resolve_day_counter
from SDRUtils.core.parsing import (
    PACKAGE_PRICE_SENTINEL,
    PRICE_SENTINEL,
    SPREAD_BPS_SENTINEL,
    SPREAD_DECIMAL_SENTINEL,
    mask_sentinels,
    parse_notation_scalar,
    parse_schedule,
    parse_sdr_timestamp,
)


class TestMaskSentinels:
    def test_price_sentinel_masked(self):
        s = pd.Series([1.0, PRICE_SENTINEL, 2.5])
        out = mask_sentinels(s, "price")
        assert pd.isna(out.iloc[1])
        assert out.iloc[0] == 1.0 and out.iloc[2] == 2.5

    def test_spread_decimal_sentinel_masked(self):
        s = pd.Series([0.0257, SPREAD_DECIMAL_SENTINEL, 0.01])
        out = mask_sentinels(s, "spread_decimal")
        assert pd.isna(out.iloc[1])
        assert out.iloc[0] == pytest.approx(0.0257)

    def test_spread_bps_sentinel_masked(self):
        s = pd.Series([257.0, SPREAD_BPS_SENTINEL, 15.0])
        out = mask_sentinels(s, "spread_bps")
        assert pd.isna(out.iloc[1])

    def test_package_price_sentinel_masked(self):
        s = pd.Series([100.125, PACKAGE_PRICE_SENTINEL])
        out = mask_sentinels(s, "package_price")
        assert pd.isna(out.iloc[1])


class TestParseNotationScalar:
    def test_bps_notation_divides_by_10000(self):
        assert parse_notation_scalar(257, 4) == pytest.approx(0.0257)

    def test_decimal_notation_passthrough(self):
        assert parse_notation_scalar(0.0257, 3) == pytest.approx(0.0257)

    def test_monetary_notation_passthrough(self):
        assert parse_notation_scalar(1000.0, 1) == pytest.approx(1000.0)

    def test_sentinel_spread_decimal_nan(self):
        assert np.isnan(parse_notation_scalar(SPREAD_DECIMAL_SENTINEL, 3))

    def test_sentinel_spread_bps_nan(self):
        assert np.isnan(parse_notation_scalar(SPREAD_BPS_SENTINEL, 4))

    def test_missing_value_nan(self):
        assert np.isnan(parse_notation_scalar(None, 3))
        assert np.isnan(parse_notation_scalar("", 4))

    def test_missing_notation_defaults_decimal(self):
        assert parse_notation_scalar(0.05, None) == pytest.approx(0.05)

    def test_string_notation_coerced(self):
        assert parse_notation_scalar("257", "4") == pytest.approx(0.0257)


class TestParseSdrTimestamp:
    def test_iso_with_offset(self):
        ts = parse_sdr_timestamp("2026-03-09 04:00:05+00:00")
        assert ts.tzinfo is not None
        assert ts.year == 2026 and ts.month == 3 and ts.day == 9

    def test_naive_assumed_utc(self):
        ts = parse_sdr_timestamp("2026-03-09 04:00:05")
        assert ts.tzinfo is not None
        assert str(ts.tzinfo) in {"UTC", "tzutc()"}

    def test_z_suffix(self):
        ts = parse_sdr_timestamp("2026-03-09T04:00:05Z")
        assert ts.tzinfo is not None

    def test_nan_returns_nat(self):
        assert pd.isna(parse_sdr_timestamp(None))
        assert pd.isna(parse_sdr_timestamp(float("nan")))

    def test_unparseable_returns_nat(self):
        assert pd.isna(parse_sdr_timestamp("garbage"))


class TestParseSchedule:
    def test_semicolon_numeric_list(self):
        out = parse_schedule("31000000;30000000;29000000")
        assert out == [31000000.0, 30000000.0, 29000000.0]

    def test_semicolon_date_strings_preserved(self):
        out = parse_schedule("2026-06-30;2026-12-31;2027-06-30")
        assert len(out) == 3
        assert isinstance(out[0], str)

    def test_empty_cell_returns_empty_list(self):
        assert parse_schedule("") == []
        assert parse_schedule(None) == []
        assert parse_schedule(float("nan")) == []

    def test_single_value(self):
        assert parse_schedule("1000000") == [1000000.0]

    def test_commas_stripped_from_numeric(self):
        assert parse_schedule("1,000,000;2,000,000") == [1_000_000.0, 2_000_000.0]

    def test_ten_element_schedule_from_fixture(self):
        # Mirrors row 1 of notebooks/sdr/sdr_example.csv.
        cell = "31000000;31000000;30000000;29000000;29000000;28000000;27000000;26000000;26000000;25000000"
        out = parse_schedule(cell)
        assert len(out) == 10
        assert all(isinstance(v, float) for v in out)


class TestDayCountTable:
    def test_a004_is_actual_360(self):
        dc = DAY_COUNT_TABLE["A004"]
        assert dc.name() == ql.Actual360().name()

    def test_a005_is_actual_365_fixed(self):
        dc = DAY_COUNT_TABLE["A005"]
        assert dc.name() == ql.Actual365Fixed().name()

    def test_a001_bond_basis(self):
        dc = DAY_COUNT_TABLE["A001"]
        assert "30" in dc.name()

    def test_a006_actual_actual_isma(self):
        dc = DAY_COUNT_TABLE["A006"]
        assert "ISMA" in dc.name()

    def test_narr_none(self):
        assert DAY_COUNT_TABLE["NARR"] is None

    def test_resolve_falls_back_for_narr(self):
        fallback = ql.Actual360()
        resolved = resolve_day_counter("NARR", fallback)
        assert resolved.name() == fallback.name()

    def test_resolve_falls_back_for_none(self):
        fallback = ql.Actual360()
        assert resolve_day_counter(None, fallback).name() == fallback.name()

    def test_resolve_returns_matched_counter(self):
        fallback = ql.Actual360()
        resolved = resolve_day_counter("A005", fallback)
        assert resolved.name() == ql.Actual365Fixed().name()

    def test_round_trip_year_fraction_a004_vs_a005(self):
        # One year of daily-count: A004 uses /360, A005 uses /365 → different.
        dc_a004 = DAY_COUNT_TABLE["A004"]
        dc_a005 = DAY_COUNT_TABLE["A005"]
        d1 = ql.Date(9, 3, 2026)
        d2 = ql.Date(9, 3, 2027)
        yf_a004 = dc_a004.yearFraction(d1, d2)
        yf_a005 = dc_a005.yearFraction(d1, d2)
        assert yf_a004 > yf_a005
        assert yf_a004 == pytest.approx(365 / 360, rel=1e-6)
        assert yf_a005 == pytest.approx(1.0, rel=1e-6)


class TestBuilderTsColDefault:
    """H6: default ts_col must be Execution Timestamp so curve builders use
    the event-study anchor, not the lagged Event timestamp."""

    def test_fetch_historical_default_execution(self):
        import inspect

        from SDRUtils.data.builder import DTCCFetcher

        sig = inspect.signature(DTCCFetcher.fetch_historical_reports)
        assert sig.parameters["ts_col"].default == "Execution Timestamp"

    def test_fetch_intraday_default_execution(self):
        import inspect

        from SDRUtils.data.builder import DTCCFetcher

        sig = inspect.signature(DTCCFetcher.fetch_intraday_reports)
        assert sig.parameters["ts_col"].default == "Execution Timestamp"

    def test_grab_sdr_trades_default_execution(self):
        import inspect

        from SDRUtils.data.builder import SDRDataBuilder

        sig = inspect.signature(SDRDataBuilder.grab_sdr_trades)
        assert sig.parameters["ts_col"].default == "Execution Timestamp"

    def test_mdp_sdr_data_builder_fetch_historical_default_execution(self):
        import inspect

        from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.SDRDataBuilder import (
            DTCCFetcher as SDRDBFetcher,
        )

        sig = inspect.signature(SDRDBFetcher.fetch_historical_reports)
        assert sig.parameters["ts_col"].default == "Execution Timestamp"


class TestPackageSpreadNotation:
    """B4: spread notation must be applied before the gate compares to the
    100 bps ceiling. 257 at notation=4 → 0.0257; 0.0257 at notation=3 → 0.0257."""

    def test_bps_notation_normalizes_to_decimal(self):
        assert parse_notation_scalar(257, 4) == pytest.approx(0.0257)

    def test_decimal_notation_passthrough(self):
        assert parse_notation_scalar(0.0257, 3) == pytest.approx(0.0257)

    def test_sentinel_at_notation_3_masks(self):
        assert np.isnan(parse_notation_scalar(9.9999999999, 3))

"""Tests for the vectorized EOD rate computation engine."""
import datetime

import numpy as np
import pytest

import pandas as pd

from Caching.eod_vectorized_engine import (
    parse_tenor,
    build_payment_schedule,
    PaymentSchedule,
    interpolate_discount_factors,
    compute_par_swap_rate,
    compute_eod_rate_panel,
    compute_and_persist_eod_panel,
)


class TestParseTenor:
    """Test tenor string parsing into (fwd_period, swap_period) tuples."""

    def test_spot_outright_months(self):
        fwd, swap = parse_tenor("6M")
        assert fwd is None
        assert swap == "6M"

    def test_spot_outright_years(self):
        fwd, swap = parse_tenor("10Y")
        assert fwd is None
        assert swap == "10Y"

    def test_forward_starting(self):
        fwd, swap = parse_tenor("2Y3Y")
        assert fwd == "2Y"
        assert swap == "3Y"

    def test_forward_starting_months(self):
        fwd, swap = parse_tenor("6M1Y")
        assert fwd == "6M"
        assert swap == "1Y"

    def test_forward_starting_mixed(self):
        fwd, swap = parse_tenor("18M5Y")
        assert fwd == "18M"
        assert swap == "5Y"

    def test_granular_month_tenor(self):
        fwd, swap = parse_tenor("42M")
        assert fwd is None
        assert swap == "42M"


class TestBuildPaymentSchedule:
    """Test payment schedule generation."""

    def test_spot_2y_schedule(self):
        # 2Y annual swap from 2024-01-02 (T+2 from 2023-12-29)
        sched = build_payment_schedule(
            trading_date=datetime.date(2023, 12, 29),
            tenor="2Y",
            settlement_days=2,
        )
        assert isinstance(sched, PaymentSchedule)
        assert len(sched.payment_dates) == 2  # annual payments
        assert len(sched.accrual_fractions) == 2
        assert sched.effective_date < sched.maturity_date
        # ACT/360 accrual fractions should be close to 1.0139 (365/360)
        for tau in sched.accrual_fractions:
            assert 0.99 < tau < 1.03

    def test_forward_starting_schedule(self):
        sched = build_payment_schedule(
            trading_date=datetime.date(2024, 3, 15),
            tenor="1Y2Y",
            settlement_days=2,
        )
        # Forward 1Y then 2Y swap = 2 annual payments
        assert len(sched.payment_dates) == 2
        # Effective should be ~1Y after spot
        spot = datetime.date(2024, 3, 19)  # T+2
        assert (sched.effective_date - spot).days > 350

    def test_maturity_equals_last_payment(self):
        sched = build_payment_schedule(
            trading_date=datetime.date(2024, 6, 3),
            tenor="5Y",
            settlement_days=2,
        )
        assert sched.maturity_date == sched.payment_dates[-1]


class TestInterpolateDiscountFactors:
    """Test log-linear discount factor interpolation."""

    def test_on_node_returns_exact(self):
        base_date = datetime.date(2024, 1, 2)
        node_dates = [datetime.date(2024, 1, 2), datetime.date(2025, 1, 2), datetime.date(2026, 1, 2)]
        node_dfs = np.array([1.0, 0.96, 0.92])
        target_dates = [datetime.date(2025, 1, 2)]
        result = interpolate_discount_factors(base_date, node_dates, node_dfs, target_dates)
        np.testing.assert_allclose(result, [0.96], atol=1e-12)

    def test_midpoint_log_linear(self):
        base_date = datetime.date(2024, 1, 2)
        node_dates = [datetime.date(2024, 1, 2), datetime.date(2026, 1, 2)]
        node_dfs = np.array([1.0, 0.92])
        # Midpoint: log-linear interpolation at 1Y
        target_dates = [datetime.date(2025, 1, 2)]
        result = interpolate_discount_factors(base_date, node_dates, node_dfs, target_dates)
        # 2024 is leap year: 366 days to midpoint, 731 days to end
        frac = 366.0 / 731.0
        expected = np.exp(frac * np.log(0.92))
        np.testing.assert_allclose(result, [expected], atol=1e-10)

    def test_multiple_targets(self):
        base_date = datetime.date(2024, 1, 2)
        node_dates = [datetime.date(2024, 1, 2), datetime.date(2025, 1, 2), datetime.date(2029, 1, 2)]
        node_dfs = np.array([1.0, 0.95, 0.80])
        targets = [datetime.date(2025, 1, 2), datetime.date(2027, 1, 2)]
        result = interpolate_discount_factors(base_date, node_dates, node_dfs, targets)
        assert len(result) == 2
        np.testing.assert_allclose(result[0], 0.95, atol=1e-12)

    def test_beyond_last_node_returns_nan(self):
        base_date = datetime.date(2024, 1, 2)
        node_dates = [datetime.date(2024, 1, 2), datetime.date(2026, 1, 2)]
        node_dfs = np.array([1.0, 0.92])
        target_dates = [datetime.date(2030, 1, 2)]
        result = interpolate_discount_factors(base_date, node_dates, node_dfs, target_dates)
        assert np.isnan(result[0])


class TestComputeParSwapRate:
    """Test par swap rate formula."""

    def test_known_rate(self):
        # Construct a simple case: 2 annual payments, known DFs
        # DF_eff = 1.0, DF_1 = 0.96, DF_2 = 0.92 (maturity)
        # tau = 365/360 for each period (approx)
        # rate = (1.0 - 0.92) / (0.96 * 365/360 + 0.92 * 365/360)
        tau = 365.0 / 360.0
        df_eff = 1.0
        df_mat = 0.92
        df_payments = np.array([0.96, 0.92])
        accruals = np.array([tau, tau])
        expected = (df_eff - df_mat) / np.dot(df_payments, accruals)
        result = compute_par_swap_rate(
            df_effective=df_eff,
            df_maturity=df_mat,
            df_at_payments=df_payments,
            accrual_fractions=accruals,
        )
        np.testing.assert_allclose(result, expected, atol=1e-12)

    def test_forward_starting(self):
        # Forward effective DF != 1.0
        df_eff = 0.96
        df_mat = 0.88
        df_payments = np.array([0.93, 0.90, 0.88])
        accruals = np.array([1.0139, 1.0139, 1.0139])
        expected = (df_eff - df_mat) / np.dot(df_payments, accruals)
        result = compute_par_swap_rate(
            df_effective=df_eff,
            df_maturity=df_mat,
            df_at_payments=df_payments,
            accrual_fractions=accruals,
        )
        np.testing.assert_allclose(result, expected, atol=1e-12)

    def test_nan_df_returns_nan(self):
        result = compute_par_swap_rate(
            df_effective=1.0,
            df_maturity=np.nan,
            df_at_payments=np.array([0.96]),
            accrual_fractions=np.array([1.0]),
        )
        assert np.isnan(result)


class TestComputeEodRatePanel:
    """Test full vectorized panel computation from raw node data."""

    def test_panel_from_raw_nodes(self):
        # Simulate raw node data for 3 trading dates
        # Each date has a simple flat curve at ~4% (DF ~ exp(-0.04 * t))
        trading_dates = [
            datetime.date(2024, 1, 2),
            datetime.date(2024, 1, 3),
            datetime.date(2024, 1, 4),
        ]
        # Node dates: 0, 1Y, 2Y, 5Y, 10Y, 30Y from each trading date
        def _make_nodes(td):
            offsets_years = [0, 1, 2, 5, 10, 30]
            dates = [td + datetime.timedelta(days=int(y * 365.25)) for y in offsets_years]
            dfs = [np.exp(-0.04 * y) for y in offsets_years]
            return dates, dfs

        rows = []
        for td in trading_dates:
            nd, df = _make_nodes(td)
            rows.append({
                "trading_date": td,
                "node_dates": nd,
                "discount_factors": df,
            })
        raw_df = pd.DataFrame(rows)

        tenors = ["2Y", "5Y", "10Y"]
        panel = compute_eod_rate_panel(
            raw_nodes_df=raw_df,
            tenors=tenors,
            settlement_days=2,
        )
        assert isinstance(panel, pd.DataFrame)
        assert len(panel) == 3  # 3 trading dates
        assert set(panel.columns) >= {"2Y", "5Y", "10Y"}
        # Rates should be close to 4% for a flat curve
        for col in tenors:
            assert panel[col].notna().all(), f"NaN found in {col}"
            for rate in panel[col]:
                assert 0.035 < rate < 0.045, f"Rate {rate} not near 4% for {col}"


import QuantLib as ql
from Caching.eod_vectorized_engine import _period_to_ql, _ql_date


class TestNumericalValidation:
    """Validate vectorized rates against QuantLib discount curve lookups.

    We validate that our log-linear interpolation and par rate formula
    match QuantLib's DiscountCurve (which also uses log-linear interp)
    when both use the same schedule. This isolates the math from
    schedule convention differences (e.g. SOFR OIS stub handling).
    """

    @pytest.mark.parametrize("tenor", ["2Y", "5Y", "10Y", "30Y", "1Y1Y", "2Y5Y", "5Y10Y"])
    def test_matches_quantlib(self, tenor):
        """Vectorized rate must match QuantLib DiscountCurve to within 0.01bp."""
        trading_date = datetime.date(2024, 6, 3)
        base = trading_date
        offsets_days = [0, 30, 91, 182]
        offsets_years = list(range(1, 31)) + [40, 50]
        node_dates = (
            [base + datetime.timedelta(days=d) for d in offsets_days]
            + [base + datetime.timedelta(days=int(y * 365.25)) for y in offsets_years]
        )
        rate_at_node = lambda y: 0.04 + 0.005 * (1 - np.exp(-0.3 * y))
        node_dfs = [
            np.exp(-rate_at_node((d - base).days / 365.25) * (d - base).days / 365.25)
            for d in node_dates
        ]

        # Build QuantLib discount curve
        ql_trade = _ql_date(trading_date)
        ql.Settings.instance().evaluationDate = ql_trade
        ql_dates = [_ql_date(d) for d in node_dates]
        ql_curve = ql.DiscountCurve(ql_dates, node_dfs, ql.Actual360())
        ql_curve.enableExtrapolation()

        # Build our schedule
        sched = build_payment_schedule(trading_date, tenor, settlement_days=2)

        # Compute QuantLib reference rate using same schedule + curve DFs
        ql_dc = ql.Actual360()
        ql_eff = _ql_date(sched.effective_date)
        ql_sched_dates = [ql_eff] + [_ql_date(d) for d in sched.payment_dates]
        df_eff_ql = ql_curve.discount(ql_eff)
        df_payments_ql = np.array([ql_curve.discount(d) for d in ql_sched_dates[1:]])
        accruals_ql = np.array([
            ql_dc.yearFraction(ql_sched_dates[i], ql_sched_dates[i + 1])
            for i in range(len(ql_sched_dates) - 1)
        ])
        ql_rate = (df_eff_ql - df_payments_ql[-1]) / np.dot(df_payments_ql, accruals_ql)

        # Vectorized rate
        all_targets = [sched.effective_date] + sched.payment_dates
        interp_dfs = interpolate_discount_factors(
            base_date=node_dates[0],
            node_dates=node_dates,
            node_dfs=np.array(node_dfs),
            target_dates=all_targets,
        )
        vec_rate = compute_par_swap_rate(
            df_effective=interp_dfs[0],
            df_maturity=interp_dfs[-1],
            df_at_payments=interp_dfs[1:],
            accrual_fractions=np.array(sched.accrual_fractions),
        )

        # 0.01bp tolerance = 1e-6
        assert abs(vec_rate - ql_rate) < 1e-6, (
            f"tenor={tenor}: vectorized={vec_rate:.8f} vs ql={ql_rate:.8f}, "
            f"diff={abs(vec_rate - ql_rate):.2e}"
        )


class TestComputeAndPersist:
    """Test that computed rates are persisted to all stores."""

    def test_writes_to_duckdb_and_parquet(self, tmp_path):
        from Caching.computed_timeseries_store import ComputedTimeseriesStore

        # Build synthetic raw node data
        trading_dates = [datetime.date(2024, 6, 3), datetime.date(2024, 6, 4)]
        offsets_years = [0, 1, 2, 5, 10, 30, 50]

        def _nodes(td):
            dates = [td + datetime.timedelta(days=int(y * 365.25)) for y in offsets_years]
            dfs = [np.exp(-0.04 * y) for y in offsets_years]
            return dates, dfs

        raw_rows = []
        for td in trading_dates:
            nd, df = _nodes(td)
            raw_rows.append({"trading_date": td, "node_dates": nd, "discount_factors": df})
        raw_df = pd.DataFrame(raw_rows)

        ts_store = ComputedTimeseriesStore(
            base_dir=str(tmp_path / "ts"),
            use_duckdb=True,
            duckdb_path=str(tmp_path / "test.duckdb"),
        )

        result = compute_and_persist_eod_panel(
            raw_nodes_df=raw_df,
            tenors=["2Y", "5Y", "10Y"],
            curve_name="USD-SOFR-1D",
            source="ERIS_EOD_LIVE-RL_BASIC",
            computed_ts_store=ts_store,
            curve_store=None,  # skip analytics panel write in test
        )

        assert result["status"] == "ok"
        assert result["rates_computed"] > 0

        # Verify DuckDB has data
        duckdb_cache = ts_store._duckdb_cache
        assert duckdb_cache is not None
        for td in trading_dates:
            rows = duckdb_cache.read_rows(
                result["symbols"][0],  # first symbol
                start=td,
                end=td,
            )
            assert len(rows) > 0, f"No DuckDB rows for {td}"


import time


class TestPerformance:
    """Benchmark vectorized engine throughput."""

    def test_252_dates_200_tenors_under_5s(self):
        """Full year x full desk tenors must complete in under 5 seconds."""
        # Generate 252 synthetic trading dates
        base = datetime.date(2024, 1, 2)
        trading_dates = []
        d = base
        while len(trading_dates) < 252:
            if d.weekday() < 5:  # skip weekends
                trading_dates.append(d)
            d += datetime.timedelta(days=1)

        offsets_years = [0, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 50]

        def _nodes(td):
            dates = [td + datetime.timedelta(days=int(y * 365.25)) for y in offsets_years]
            dfs = [np.exp(-0.04 * y) for y in offsets_years]
            return dates, dfs

        raw_rows = []
        for td in trading_dates:
            nd, df = _nodes(td)
            raw_rows.append({"trading_date": td, "node_dates": nd, "discount_factors": df})
        raw_df = pd.DataFrame(raw_rows)

        # 200 tenors: spot 1M-50Y + forward-starting
        tenors = (
            [f"{m}M" for m in range(1, 24)]
            + [f"{y}Y" for y in range(2, 51)]
            + ["1Y1Y", "1Y2Y", "1Y3Y", "1Y5Y", "1Y10Y",
               "2Y1Y", "2Y2Y", "2Y3Y", "2Y5Y", "2Y10Y",
               "3Y1Y", "3Y2Y", "3Y3Y", "3Y5Y", "3Y10Y",
               "5Y1Y", "5Y2Y", "5Y3Y", "5Y5Y", "5Y10Y",
               "7Y1Y", "7Y2Y", "7Y3Y", "7Y5Y",
               "10Y1Y", "10Y2Y", "10Y5Y", "10Y10Y",
               "15Y5Y", "15Y10Y", "15Y15Y",
               "20Y5Y", "20Y10Y", "20Y30Y",
               "30Y5Y", "30Y10Y", "30Y20Y"]
        )

        start = time.perf_counter()
        panel = compute_eod_rate_panel(raw_df, tenors)
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, f"Took {elapsed:.2f}s (budget: 5s)"
        assert len(panel) == 252
        assert len(panel.columns) >= 100  # at least 100 tenors produced
        # Most rates should be non-NaN
        fill_rate = panel.notna().sum().sum() / (len(panel) * len(panel.columns))
        assert fill_rate > 0.8, f"Fill rate {fill_rate:.2%} too low"

        print(f"\nBenchmark: {len(panel)} dates x {len(panel.columns)} tenors = "
              f"{panel.notna().sum().sum():.0f} rates in {elapsed:.2f}s "
              f"({panel.notna().sum().sum() / elapsed:.0f} rates/sec)")

"""
Integration tests for TimeseriesBuilder — full pipeline end-to-end.

These tests exercise the complete flow:
  MDP → TB → DiskCacheMixin → DuckDB/Parquet → DataFrame

Each test uses a single query to keep execution time manageable
while still validating the entire pipeline from market data fetch
through to final output.

Requirements:
  - Network access (MDPs fetch from external APIs)
  - Installed dependencies: diskcache, duckdb, rateslib/QuantLib, etc.

Note:
  IRS (interest rate swap) queries currently fail due to a pre-existing
  rateslib API change (leg2_fixings → leg2_fx_fixings). These tests are
  marked xfail until the upstream fix lands.
"""

import datetime

import pandas as pd
import pytest

pytestmark = pytest.mark.slow

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

from TB.IRSwapsTB import IRSwapsTB
from TB.FixedRateBondsTB import FixedRateBondsTB
from TB.STIRFuturesTB import STIRFuturesTB
from TB.USTFuturesTB import USTFuturesTB
from TB.STIRFutureOptionsTB import STIRFutureOptionsTB
from TB.TimeseriesBuilder import TimeseriesBuilder

from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureValue import STIRFutureValue
from Query.USTFutures.USTFutureQuery import USTFutureQuery
from Query.USTFutures.USTFutureValue import USTFutureValue
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue

# ---------------------------------------------------------------------------
# Shared date range — a narrow window to keep tests fast
# ---------------------------------------------------------------------------

START = datetime.date(2026, 2, 23)
END = datetime.date(2026, 2, 27)

# rateslib broke IRS pricing (leg2_fixings → leg2_fx_fixings)
_IRS_XFAIL = pytest.mark.xfail(
    reason="Pre-existing rateslib API change: leg2_fixings → leg2_fx_fixings",
    strict=False,
)


# ---------------------------------------------------------------------------
# Fixtures — one MDP per product, one TB router
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def irs_mdp():
    return IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")


@pytest.fixture(scope="module")
def frb_mdp():
    return FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")


@pytest.fixture(scope="module")
def stirf_mdp():
    return STIRFutureMDP(source="BARCHART_TOS_LIVE_STIRF-RL")


@pytest.fixture(scope="module")
def ustf_mdp():
    return USTFuturesMDP(source="BARCHART_USTF-RL")


@pytest.fixture(scope="module")
def stirfo_mdp():
    return STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")


@pytest.fixture(scope="module")
def tb(irs_mdp, frb_mdp, stirf_mdp, ustf_mdp, stirfo_mdp):
    return TimeseriesBuilder(
        irswaps_tb=IRSwapsTB(irs_mdp, show_tqdm=False),
        fixedratebonds_tb=FixedRateBondsTB(frb_mdp, show_tqdm=False),
        stirfutures_tb=STIRFuturesTB(stirf_mdp, show_tqdm=False),
        ustfutures_tb=USTFuturesTB(ustf_mdp, show_tqdm=False),
        stirfutureoptions_tb=STIRFutureOptionsTB(stirfo_mdp, show_tqdm=False),
    )


def _assert_timeseries_basics(df, expected_cols=1):
    """Common assertions for any timeseries result."""
    assert isinstance(df, pd.DataFrame), "Result must be a DataFrame"
    assert not df.empty, "Result must not be empty"
    assert len(df.columns) >= expected_cols, f"Expected >= {expected_cols} columns, got {len(df.columns)}"
    assert df.index.is_monotonic_increasing, "Index must be sorted ascending"
    assert df.notna().any().any(), "Must have at least some non-NaN values"


# ---------------------------------------------------------------------------
# IRS — Interest Rate Swaps
# ---------------------------------------------------------------------------

class TestIRSwaps:
    @_IRS_XFAIL
    def test_rate(self, tb):
        """IRS outright par rate for 5Y SOFR."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        _assert_timeseries_basics(df)
        vals = df.iloc[:, 0].dropna()
        assert all(0.001 < v < 0.10 for v in vals), f"Rates outside expected range: {vals.tolist()}"

    @_IRS_XFAIL
    def test_pv01(self, tb):
        """IRS PV01 for 10Y SOFR."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.PV01)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        _assert_timeseries_basics(df)
        vals = df.iloc[:, 0].dropna()
        assert all(abs(v) > 0 for v in vals), "PV01 must be non-zero"


# ---------------------------------------------------------------------------
# FRB — Fixed Rate Bonds (US Treasuries)
# ---------------------------------------------------------------------------

class TestFixedRateBonds:
    def test_ytm(self, tb):
        """On-the-run 10Y UST yield-to-maturity."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        _assert_timeseries_basics(df)
        # YTM may be returned in percent (e.g. 4.02) or decimal (0.0402)
        vals = df.iloc[:, 0].dropna()
        assert all(0.005 < v < 10.0 for v in vals), f"YTM outside expected range: {vals.tolist()}"

    def test_clean_price(self, tb):
        """On-the-run 2Y UST clean price."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[FixedRateBondQuery(cusip="CT2", value=FixedRateBondValue.CLEAN_PRICE)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        _assert_timeseries_basics(df)
        vals = df.iloc[:, 0].dropna()
        assert all(70 < v < 130 for v in vals), f"Clean price outside expected range: {vals.tolist()}"


# ---------------------------------------------------------------------------
# STIRF — STIR Futures (SOFR futures)
# ---------------------------------------------------------------------------

class TestSTIRFutures:
    def test_price(self, tb):
        """SOFR future price."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[STIRFutureQuery(symbol="SR3U26", curve="USD-SOFR-1D", value=STIRFutureValue.PRICE)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        _assert_timeseries_basics(df)
        vals = df.iloc[:, 0].dropna()
        assert all(90 < v < 101 for v in vals), f"STIR price outside expected range: {vals.tolist()}"

    @_IRS_XFAIL
    def test_rate(self, tb):
        """SOFR future implied rate (requires IRS curve building)."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[STIRFutureQuery(symbol="SR3U26", curve="USD-SOFR-1D", value=STIRFutureValue.RATE)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        _assert_timeseries_basics(df)
        vals = df.iloc[:, 0].dropna()
        assert all(0.001 < abs(v) < 0.10 for v in vals), f"STIR rate outside expected range: {vals.tolist()}"


# ---------------------------------------------------------------------------
# USTF — US Treasury Futures
# ---------------------------------------------------------------------------

class TestUSTFutures:
    @pytest.mark.xfail(reason="Barchart USTF fetcher requires SOCKS proxy (socksio)", strict=False)
    def test_price(self, tb):
        """10Y UST future (TY) price."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[USTFutureQuery(symbol="TYH26", value=USTFutureValue.PRICE)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        _assert_timeseries_basics(df)
        vals = df.iloc[:, 0].dropna()
        assert all(80 < v < 150 for v in vals), f"UST future price outside expected range: {vals.tolist()}"


# ---------------------------------------------------------------------------
# STIRFO — STIR Future Options
# ---------------------------------------------------------------------------

class TestSTIRFutureOptions:
    def test_price(self, tb):
        """STIR future option (at-the-money straddle) price."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[STIRFutureOptionQuery(symbol="SR3Z26|ATMS", value=STIRFutureOptionValue.PRICE)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        _assert_timeseries_basics(df)

    def test_iv_normal_bps(self, tb):
        """STIR future option normal implied vol in bps."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[STIRFutureOptionQuery(symbol="SR3Z26|ATMS", value=STIRFutureOptionValue.IV_NORMAL_BPS)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        _assert_timeseries_basics(df)
        vals = df.iloc[:, 0].dropna()
        assert all(v > 0 for v in vals), f"IV normal bps must be positive: {vals.tolist()}"


# ---------------------------------------------------------------------------
# Cross-product: MMSS (swap spread = swap rate - treasury yield)
# ---------------------------------------------------------------------------

class TestSwapSpread:
    @_IRS_XFAIL
    def test_mmss(self, tb):
        """Mid-market swap spread: IRS rate minus UST yield for CT10."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[IRSwapQuery(curve="USD-SOFR-1D", tenor="CT10", value=IRSwapValue.MMSS)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        _assert_timeseries_basics(df)


# ---------------------------------------------------------------------------
# Output shape and index
# ---------------------------------------------------------------------------

class TestOutputFormat:
    def test_index_name(self, tb):
        """Output DataFrame index should be named 'Date'."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[FixedRateBondQuery(cusip="CT2", value=FixedRateBondValue.YTM)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        assert df.index.name == "Date"

    def test_business_days_only(self, tb):
        """Default output should only contain business days."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[FixedRateBondQuery(cusip="CT2", value=FixedRateBondValue.YTM)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        for d in df.index:
            if isinstance(d, datetime.date):
                assert d.weekday() < 5, f"Found weekend date in output: {d}"

    def test_multilevel_columns(self, tb):
        """When drop_multilevel_cols=False, columns should be MultiIndex."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[FixedRateBondQuery(cusip="CT2", value=FixedRateBondValue.YTM)],
            drop_multilevel_cols=False,
            ignore_cache=True,
        )
        assert isinstance(df.columns, pd.MultiIndex), "Expected MultiIndex columns"

    def test_date_range_respected(self, tb):
        """Output dates must fall within [start, end]."""
        df = tb.get_timeseries(
            start=START,
            end=END,
            queries=[FixedRateBondQuery(cusip="CT2", value=FixedRateBondValue.YTM)],
            drop_multilevel_cols=True,
            ignore_cache=True,
        )
        for d in df.index:
            assert START <= d <= END, f"Date {d} outside [{START}, {END}]"


# ---------------------------------------------------------------------------
# Cache behavior (ignore_cache flag)
# ---------------------------------------------------------------------------

class TestCacheBehavior:
    def test_cached_vs_fresh(self, tb):
        """Running with ignore_cache=False twice should return same shape."""
        q = [FixedRateBondQuery(cusip="CT5", value=FixedRateBondValue.CLEAN_PRICE)]
        df1 = tb.get_timeseries(start=START, end=END, queries=q, drop_multilevel_cols=True, ignore_cache=True)
        df2 = tb.get_timeseries(start=START, end=END, queries=q, drop_multilevel_cols=True, ignore_cache=False)
        assert df1.shape == df2.shape, f"Shape mismatch: {df1.shape} vs {df2.shape}"

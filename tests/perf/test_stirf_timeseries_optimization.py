"""Cold-cache performance test for STIRF intraday timeseries optimization.

Run with: conda run -n stir python -m pytest tests/perf/test_stirf_timeseries_optimization.py -v -s
"""
import datetime
import time

import pytz
import pytest

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.Unified.UnifiedQuery import UnifiedQuery
from Query.Unified.registry import UnifiedValue
from TB.TimeseriesBuilder import TimeseriesBuilder

NYC = pytz.timezone("America/New_York")


def _build_ts():
    curve_mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    ts_builder = TimeseriesBuilder()
    start = NYC.localize(datetime.datetime(2026, 3, 12, 7, 0))
    end = NYC.localize(datetime.datetime(2026, 3, 13, 17, 0))
    q1 = UnifiedQuery(
        curve="USD-SOFR-1D-Q12STIRT",
        tenor="fomc_dec26",
        value=UnifiedValue.IRS_RATE,
    )
    return ts_builder, start, end, q1, curve_mdp


class TestSTIRFTimeseriesPerformance:
    @pytest.mark.slow
    def test_cold_cache_timeseries(self):
        """Cold-cache full-day minutely timeseries. Target: <180s, ideal ~120s."""
        ts_builder, start, end, q1, curve_mdp = _build_ts()

        t0 = time.perf_counter()
        df = ts_builder.get_timeseries(
            start=start,
            end=end,
            queries=[q1],
            n_jobs=12,
            freq="1min",
            mdps={"IRS": curve_mdp},
        )
        elapsed = time.perf_counter() - t0

        assert not df.empty, "DataFrame should not be empty"
        assert len(df) > 100, f"Expected >100 rows, got {len(df)}"
        print(f"\n[PERF] Cold-cache timeseries: {elapsed:.1f}s ({len(df)} rows)")
        assert elapsed < 180, f"Cold-cache took {elapsed:.1f}s, target is <180s"

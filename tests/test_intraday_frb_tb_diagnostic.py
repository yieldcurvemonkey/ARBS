"""Diagnostic test: reproduce & fix the intraday FRB timeseries L2 cache storm.

Run with:  conda activate stir && cd /c/Users/chris/clee/ARBS && python -m pytest tests/test_intraday_frb_tb_diagnostic.py -v -s
"""
import datetime
import logging
import os
import time

import pytz
import pytest

# Suppress Supabase L2 writes during diagnostic (avoids the storm entirely)
os.environ.setdefault("ARBS_SUPABASE_WRITE_QUEUE_SIZE", "8192")  # 2x default
os.environ.setdefault("ARBS_SUPABASE_WRITE_WORKERS", "2")        # fewer workers = less contention

NY_tz = pytz.timezone("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s %(name)s:%(filename)s:%(funcName)s()- %(message)s",
)
logger = logging.getLogger(__name__)


def _short_intraday_range(date: datetime.date, start_hour=9, start_min=30, end_hour=10, end_min=0, freq="5min"):
    """Build a small intraday range for fast testing."""
    import QuantLib as ql
    # Use a helper if available, else fall back to pandas
    try:
        from BT.misc import ql_cal_date_range
        start = NY_tz.localize(datetime.datetime(date.year, date.month, date.day, start_hour, start_min))
        end = NY_tz.localize(datetime.datetime(date.year, date.month, date.day, end_hour, end_min))
        return ql_cal_date_range(
            ql.UnitedStates(ql.UnitedStates.GovernmentBond),
            start=start,
            end=end,
            freq=freq,
        )
    except ImportError:
        import pandas as pd
        start = NY_tz.localize(datetime.datetime(date.year, date.month, date.day, start_hour, start_min))
        end = NY_tz.localize(datetime.datetime(date.year, date.month, date.day, end_hour, end_min))
        return pd.date_range(start=start, end=end, freq=freq).to_pydatetime().tolist()


@pytest.mark.skipif(
    os.environ.get("RUN_INTRADAY_DIAG") != "1",
    reason="Set RUN_INTRADAY_DIAG=1 to run (hits live Webull API)",
)
class TestIntradayFRBDiagnostic:
    """Diagnostic tests for the intraday FRB timeseries cache storm."""

    def test_small_intraday_window_njobs1(self):
        """Baseline: small window, single-threaded — should work without L2 storm."""
        from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
        from TB.FixedRateBondsTB import FixedRateBondsTB
        from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery

        usts_mdp = FixedRateBondsMDP(source="USTS_WEBULL_WSJ_LIVE-RL")
        usts_tb = FixedRateBondsTB(usts_mdp)

        # Only 7 timestamps (5min freq, 30min window) — manageable
        ts_range = _short_intraday_range(datetime.date(2026, 2, 19))
        logger.info("Testing with %d timestamps (n_jobs=1)", len(ts_range))

        t0 = time.time()
        df = usts_tb.get_timeseries(
            start=None,
            end=None,
            timestamps=ts_range,
            queries=[FixedRateBondQuery(cusip="912810UA4")],
            n_jobs=1,
        )
        elapsed = time.time() - t0
        logger.info("Result shape: %s, elapsed: %.1fs", df.shape, elapsed)
        logger.info("Head:\n%s", df.head())
        assert not df.empty, "Expected non-empty DataFrame"

    def test_small_intraday_window_njobs4(self):
        """4 workers on small window — should show if threading causes L2 storm."""
        from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
        from TB.FixedRateBondsTB import FixedRateBondsTB
        from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery

        usts_mdp = FixedRateBondsMDP(source="USTS_WEBULL_WSJ_LIVE-RL")
        usts_tb = FixedRateBondsTB(usts_mdp)

        ts_range = _short_intraday_range(datetime.date(2026, 2, 19))
        logger.info("Testing with %d timestamps (n_jobs=4)", len(ts_range))

        t0 = time.time()
        df = usts_tb.get_timeseries(
            start=None,
            end=None,
            timestamps=ts_range,
            queries=[FixedRateBondQuery(cusip="912810UA4")],
            n_jobs=4,
        )
        elapsed = time.time() - t0
        logger.info("Result shape: %s, elapsed: %.1fs", df.shape, elapsed)
        assert not df.empty

    def test_l2_queue_stats_after_run(self):
        """Check L2 queue stats to quantify the write storm."""
        from Caching.layered_cache_mixin import LayeredDictProxy

        logger.info(
            "L2 stats: queued=%d dropped=%d queue_depth=%d",
            LayeredDictProxy._L2_WRITES_OK,
            LayeredDictProxy._L2_WRITES_DROPPED,
            LayeredDictProxy._L2_WRITE_QUEUE.qsize() if LayeredDictProxy._L2_WRITE_QUEUE else 0,
        )
        # If dropped > 0, that confirms the L2 storm
        if LayeredDictProxy._L2_WRITES_DROPPED > 0:
            logger.warning(
                "L2 WRITE STORM CONFIRMED: %d writes dropped out of %d attempted",
                LayeredDictProxy._L2_WRITES_DROPPED,
                LayeredDictProxy._L2_WRITES_OK + LayeredDictProxy._L2_WRITES_DROPPED,
            )


@pytest.mark.skipif(
    os.environ.get("RUN_INTRADAY_DIAG") != "1",
    reason="Set RUN_INTRADAY_DIAG=1 to run",
)
class TestIntradayFRBWithL2Disabled:
    """Same tests but with L2 writes disabled — should be fast and clean."""

    def test_intraday_no_l2_writes(self):
        """Disable L2 writes to confirm the bottleneck is Supabase."""
        # Temporarily disable L2 writes
        from Caching.layered_cache_mixin import LayeredCacheMixin
        original = LayeredCacheMixin.L2_WRITE
        try:
            LayeredCacheMixin.L2_WRITE = False

            from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
            from TB.FixedRateBondsTB import FixedRateBondsTB
            from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery

            usts_mdp = FixedRateBondsMDP(source="USTS_WEBULL_WSJ_LIVE-RL")
            usts_tb = FixedRateBondsTB(usts_mdp)

            ts_range = _short_intraday_range(
                datetime.date(2026, 2, 19),
                start_hour=9, start_min=30,
                end_hour=10, end_min=30,
                freq="1min",
            )
            logger.info("Testing with %d timestamps, L2_WRITE=False, n_jobs=8", len(ts_range))

            t0 = time.time()
            df = usts_tb.get_timeseries(
                start=None,
                end=None,
                timestamps=ts_range,
                queries=[FixedRateBondQuery(cusip="912810UA4")],
                n_jobs=8,
            )
            elapsed = time.time() - t0
            logger.info("Result shape: %s, elapsed: %.1fs (L2 disabled)", df.shape, elapsed)
            assert not df.empty
        finally:
            LayeredCacheMixin.L2_WRITE = original

"""Smoke / unit tests for the run_backtest top-level orchestrator."""
from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

pytestmark = pytest.mark.slow

from RVUtils.SFRConvexScreener import (
    Leg,
    SFRConvexScreenerConfig,
    SFRConvexScreenerSnapshot,
    StructureDef,
    StructureResult,
    StructureType,
)
from RVUtils.SFRConvexScreener._metrics import PayoffMetrics
from RVUtils.SFRConvexScreener.backtest import (
    SFRScreenerBacktestConfig,
    _config_summary_for_cache,
    run_backtest,
)


def _trivial_snapshot(d: datetime.date) -> SFRConvexScreenerSnapshot:
    sd = StructureDef(
        structure_id="A_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25.0),),
    )
    metrics = PayoffMetrics(
        mean_bp=1.0, std_bp=5.0, skew=0.5, excess_kurtosis=1.0,
        p_profit=0.55, ev_given_profit_bp=4.0, ev_given_loss_bp=-3.0,
        asymmetry_ratio=2.0,
        percentiles_bp={"p5": -8, "p25": -2, "p50": 1, "p75": 5, "p95": 11},
        tail_ratio=1.4,
    )
    r = StructureResult(
        structure_def=sd, metrics_by_method={"marginal": metrics},
        primary_method="marginal", carry_3m_bp=0.0, rolldown_bp=0.0,
        iv_rv_diagnostics=(), historical=None, warnings=(),
        composite_score=0.7, rank=1,
    )
    return SFRConvexScreenerSnapshot(
        as_of=d, results=(r,), config_summary={"universe_size": 4},
    )


def test_config_summary_for_cache_stable():
    cfg = SFRConvexScreenerConfig(universe_size=12, jpm_method=True)
    s = _config_summary_for_cache(cfg)
    assert s["universe_size"] == 12
    assert s["jpm_method"] is True
    assert "calendar_gaps" in s
    assert "fly_gaps" in s


def test_run_backtest_with_synthetic_snapshots(tmp_path: Path):
    """Cache is pre-populated -> run_backtest does not call build_snapshot."""
    cfg = SFRConvexScreenerConfig(universe_size=4)
    cache_summary = _config_summary_for_cache(cfg)
    from RVUtils.SFRConvexScreener._backtest_cache import SnapshotCache
    cache = SnapshotCache(root=tmp_path)
    d = datetime.date(2026, 4, 28)
    cache.put(_trivial_snapshot(d), cache_summary)

    bt_dt = datetime.datetime(2026, 4, 28, 17, 0)
    bt_cfg = SFRScreenerBacktestConfig(max_concurrent=1, rebalance_dow=None)

    with patch("RVUtils.SFRConvexScreener.backtest.IRSwapsMDP") as mock_mdp_cls, \
         patch("RVUtils.SFRConvexScreener.backtest.QueryDrivenBacktest") as mock_bt_cls, \
         patch("RVUtils.SFRConvexScreener.backtest.build_snapshot") as mock_build:
        mock_mdp_cls.return_value = MagicMock()
        mock_bt_inst = MagicMock()
        mock_bt_cls.return_value = mock_bt_inst
        mock_build.side_effect = AssertionError("should not be called - cache hit")

        bt = run_backtest(
            bt_datetimes=[bt_dt],
            screener_config=cfg,
            backtest_config=bt_cfg,
            cache_root=tmp_path,
            show_progress=False,
        )

    assert bt is mock_bt_inst
    mock_bt_inst.run.assert_called_once()


@pytest.mark.integration
def test_run_backtest_smoke(tmp_path: Path):
    import pytz

    NYC = pytz.timezone("America/New_York")
    bt_dates = pd.bdate_range(
        NYC.localize(datetime.datetime(2026, 4, 21, 17, 0)),
        NYC.localize(datetime.datetime(2026, 4, 28, 17, 0)),
        tz=NYC,
    )
    screener_cfg = SFRConvexScreenerConfig(
        universe_size=4, calendar_gaps=(1,), fly_gaps=(1,),
        correlation_window=10, n_simulations=10_000,
    )
    bt_cfg = SFRScreenerBacktestConfig(max_concurrent=2, rebalance_dow=None)
    bt = run_backtest(
        bt_datetimes=[d.to_pydatetime() for d in bt_dates],
        screener_config=screener_cfg,
        backtest_config=bt_cfg,
        cache_root=tmp_path,
        show_progress=False,
    )
    assert bt is not None
    assert hasattr(bt, "portfolio")

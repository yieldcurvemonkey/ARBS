"""Top-level entry point for the SFR Convex Screener backtest.

Wires the on-disk snapshot cache, the BacktestSignal table, and the
entry/exit triggers into a ``QueryDrivenBacktest`` runnable on a
TimeGrid of business datetimes.

Usage
-----

    from RVUtils.SFRConvexScreener import SFRConvexScreenerConfig
    from RVUtils.SFRConvexScreener.backtest import (
        SFRScreenerBacktestConfig, run_backtest,
    )

    bt = run_backtest(
        bt_datetimes=tz_aware_business_datetimes,
        screener_config=SFRConvexScreenerConfig(universe_size=12, jpm_method=True),
        backtest_config=SFRScreenerBacktestConfig(max_concurrent=5),
    )
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Iterable, Optional, Sequence, Union

from BT.data_handler import TimeGrid
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

from RVUtils.SFRConvexScreener._backtest_cache import (
    SnapshotCache,
    load_or_build_many,
)
from RVUtils.SFRConvexScreener._backtest_signals import (
    build_signal_table_from_snapshots,
)
from RVUtils.SFRConvexScreener._backtest_triggers import (
    SFRScreenerBacktestConfig,
    build_entry_trigger,
    build_exit_trigger,
)
from RVUtils.SFRConvexScreener._types import SFRConvexScreenerConfig
from RVUtils.SFRConvexScreener.screener import build_snapshot

logger = logging.getLogger(__name__)


def _config_summary_for_cache(cfg: SFRConvexScreenerConfig) -> dict:
    """Stable summary of the screener config used as the cache hash payload."""
    return {
        "universe_size": cfg.universe_size,
        "include_outrights": cfg.include_outrights,
        "jpm_method": cfg.jpm_method,
        "calendar_gaps": list(cfg.calendar_gaps),
        "fly_gaps": list(cfg.fly_gaps),
        "correlation_window": cfg.correlation_window,
        "n_simulations": cfg.n_simulations,
        "ghost_extension_bps": cfg.ghost_extension_bps,
        "primary_joint_method": getattr(cfg.primary_joint_method, "value", str(cfg.primary_joint_method)),
    }


def run_backtest(
    *,
    bt_datetimes: Sequence[datetime.datetime],
    screener_config: SFRConvexScreenerConfig,
    backtest_config: SFRScreenerBacktestConfig,
    cache_root: Optional[Union[str, Path]] = None,
    snapshot_dates: Optional[Iterable[datetime.date]] = None,
    show_progress: bool = True,
) -> QueryDrivenBacktest:
    """Run the SFR Convex Screener backtest.

    Parameters
    ----------
    bt_datetimes
        TZ-aware datetimes that form the simulation TimeGrid.
    screener_config
        Passed to ``build_snapshot`` per as_of date.
    backtest_config
        Filter thresholds, sizing, and exit conditions.
    cache_root
        Directory for the on-disk snapshot cache. Defaults to
        ``data/screener_results/sfr_convex_screener_backtest_cache``.
    snapshot_dates
        Defaults to the unique dates in ``bt_datetimes``.
    show_progress
        Forwarded to both the cache loader and the backtest engine.
    """
    if cache_root is None:
        cache_root = Path("data/screener_results/sfr_convex_screener_backtest_cache")
    cache = SnapshotCache(root=cache_root)

    if snapshot_dates is None:
        snapshot_dates = sorted({d.date() for d in bt_datetimes})

    config_summary = _config_summary_for_cache(screener_config)

    def _build_one(d: datetime.date):
        return build_snapshot(screener_config, as_of=d)

    snapshots = load_or_build_many(
        dates=snapshot_dates,
        cache=cache,
        build_fn=_build_one,
        config_summary=config_summary,
        show_progress=show_progress,
    )
    signal_table = build_signal_table_from_snapshots(snapshots.values())

    entry = build_entry_trigger(signal_table, backtest_config)
    exit_ = build_exit_trigger(signal_table, backtest_config)

    curve_mdp = IRSwapsMDP(source=screener_config.curve_source)
    strategy = QueryStrategy(
        name="sfr_convex_screener",
        triggers=[entry, exit_],
        default_mdp=curve_mdp,
    )
    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(list(bt_datetimes)),
        strategy=strategy,
        mdp=curve_mdp,
        show_progress=show_progress,
    )
    bt.run()
    return bt

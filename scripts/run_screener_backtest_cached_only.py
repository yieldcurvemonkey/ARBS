"""Drive the screener backtest grid over a long TimeGrid using only the
snapshot dates currently in the on-disk cache.

Lets us produce multi-week MTM curves for configs that already populated
positions, without paying the Barchart cache-priming cost on uncached
dates inside the window.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import pickle
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backtest_cached")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from RVUtils.SFRConvexScreener import (  # noqa: E402
    JointMethod,
    SFRConvexScreenerConfig,
    SFRScreenerBacktestConfig,
)
from RVUtils.SFRConvexScreener.backtest import (  # noqa: E402
    _config_summary_for_cache,
    run_backtest,
)
from RVUtils.SFRConvexScreener._backtest_cache import (  # noqa: E402
    SnapshotCache,
    snapshot_cache_key,
)

NYC = pytz.timezone("America/New_York")
GRID_ROOT = REPO_ROOT / "data" / "screener_results" / "sfr_convex_screener_backtest_grid"


def _make_screener_cfg() -> SFRConvexScreenerConfig:
    return SFRConvexScreenerConfig(
        universe_size=12,
        include_outrights=True,
        jpm_method=True,
        primary_joint_method=JointMethod.HISTORICAL_GAUSSIAN_COPULA,
        correlation_window=60,
        n_simulations=50_000,
    )


def _bt_datetimes(start: datetime.date, end: datetime.date) -> List[datetime.datetime]:
    # pd.bdate_range normalises to midnight regardless of input time, so
    # produce business dates first then attach 17:00 NYC EOD timestamps.
    bdates = pd.bdate_range(start, end)
    return [
        NYC.localize(datetime.datetime.combine(d.date(), datetime.time(17, 0)))
        for d in bdates
    ]


def _grid_configs() -> Dict[str, SFRScreenerBacktestConfig]:
    return {
        "a_outright_conservative": SFRScreenerBacktestConfig(
            structure_types=("outright",),
            entry_min_asymmetry=2.0, max_concurrent=3,
            exit_max_holding_days=22, exit_take_profit_bp=10.0,
            exit_stop_loss_bp=-15.0, rebalance_dow=4,
        ),
        "b_calendar_only": SFRScreenerBacktestConfig(
            structure_types=("calendar",),
            entry_min_asymmetry=3.0, max_concurrent=5,
            exit_asymmetry_threshold=1.5,
            exit_max_holding_days=22, rebalance_dow=4,
        ),
        "c_butterfly_only": SFRScreenerBacktestConfig(
            structure_types=("butterfly",),
            entry_min_asymmetry=3.0, max_concurrent=5,
            exit_asymmetry_threshold=1.5,
            exit_max_holding_days=44, rebalance_dow=4,
        ),
        "d_all_structures_default": SFRScreenerBacktestConfig(
            structure_types=("outright", "calendar", "butterfly"),
            entry_min_asymmetry=1.5, max_concurrent=5,
            exit_asymmetry_threshold=1.10,
            exit_take_profit_bp=10.0, exit_stop_loss_bp=-15.0,
            exit_max_holding_days=22, rebalance_dow=4,
        ),
        "e_aggressive_concurrency": SFRScreenerBacktestConfig(
            structure_types=("outright", "calendar", "butterfly"),
            entry_min_asymmetry=1.2, max_concurrent=10,
            exit_asymmetry_threshold=1.10,
            exit_take_profit_bp=10.0, exit_stop_loss_bp=-15.0,
            exit_max_holding_days=22, rebalance_dow=4,
        ),
        "f_daily_rebalance": SFRScreenerBacktestConfig(
            structure_types=("outright", "calendar", "butterfly"),
            entry_min_asymmetry=1.5, max_concurrent=5,
            exit_asymmetry_threshold=1.10,
            exit_take_profit_bp=10.0, exit_stop_loss_bp=-15.0,
            exit_max_holding_days=22, rebalance_dow=None,
        ),
    }


def _list_cached_dates(cache_root: Path, config_summary: Dict[str, Any]) -> List[datetime.date]:
    """Walk cache_root and return only the dates whose hash matches our config."""
    cached: List[datetime.date] = []
    for p in sorted(cache_root.glob("*.pkl")):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})_([0-9a-f]+)\.pkl$", p.name)
        if not m:
            continue
        d_str, h = m.groups()
        d = datetime.date.fromisoformat(d_str)
        # check the hash matches
        if snapshot_cache_key(d, config_summary).endswith(f"_{h}"):
            cached.append(d)
    return sorted(cached)


def _summarize(bt: Any, *, name: str, elapsed_s: float) -> Dict[str, Any]:
    closed = list(getattr(bt.portfolio, "closed_positions_log", []) or [])
    rows = []
    for entry in closed:
        pmeta = dict(entry.get("position_meta", {}) or {})
        xmeta = dict(entry.get("exit_meta", {}) or {})
        rows.append({
            "opened": entry.get("opened_at"),
            "closed": entry.get("closed_at"),
            "days": float(entry.get("holding_period_days", 0.0) or 0.0),
            "realized_pnl": float(entry.get("realized_pnl", 0.0) or 0.0),
            "gross": float(entry.get("gross_realized_pnl", 0.0) or 0.0),
            "fee": float(entry.get("fee_allocated", 0.0) or 0.0),
            "structure_id": pmeta.get("structure_id"),
            "structure_type": pmeta.get("structure_type"),
            "direction": pmeta.get("direction"),
            "entry_asymmetry": pmeta.get("entry_asymmetry"),
            "entry_composite": pmeta.get("entry_composite"),
            "entry_npv": pmeta.get("entry_npv"),
            "exit_reason": xmeta.get("reason"),
        })
    trades = pd.DataFrame(rows)

    mtm = pd.Series({pd.Timestamp(k): float(v) for k, v in (bt.mtm_history or {}).items()}).sort_index()
    if not mtm.empty and mtm.index.tz is not None:
        mtm.index = mtm.index.tz_localize(None)

    daily = mtm.diff().dropna() if not mtm.empty else pd.Series([], dtype=float)
    sharpe = float(np.sqrt(252) * daily.mean() / daily.std()) if daily.std() > 0 else float("nan")
    if not mtm.empty:
        running_max = mtm.cummax()
        max_dd = float((mtm - running_max).min())
        final_mtm = float(mtm.iloc[-1])
    else:
        max_dd = float("nan")
        final_mtm = 0.0
    n_trades = len(trades)
    n_open = len(getattr(bt.portfolio, "positions", []) or [])
    win_rate = float((trades["realized_pnl"] > 0).mean()) if n_trades else float("nan")
    avg_hold = float(trades["days"].mean()) if n_trades else float("nan")

    if n_trades:
        winners = trades.nlargest(3, "realized_pnl")[["structure_id", "direction", "realized_pnl", "days", "exit_reason"]]
        losers = trades.nsmallest(3, "realized_pnl")[["structure_id", "direction", "realized_pnl", "days", "exit_reason"]]
    else:
        winners = pd.DataFrame()
        losers = pd.DataFrame()

    return {
        "name": name,
        "elapsed_s": elapsed_s,
        "n_trades": int(n_trades),
        "n_unrealized_open": int(n_open),
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "final_mtm": final_mtm,
        "win_rate": win_rate,
        "avg_holding_days": avg_hold,
        "exit_reason_counts": trades["exit_reason"].value_counts().to_dict() if n_trades else {},
        "trades_df": trades,
        "mtm_series": mtm,
        "top_winners": winners,
        "top_losers": losers,
    }


def _persist(out_dir: Path, summary: Dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary["trades_df"].to_csv(out_dir / "trades.csv", index=False)
    summary["mtm_series"].to_frame("mtm_usd").to_csv(out_dir / "mtm_history.csv")
    payload = {k: v for k, v in summary.items() if k not in ("trades_df", "mtm_series", "top_winners", "top_losers")}
    payload["top_winners"] = summary["top_winners"].to_dict("records") if not summary["top_winners"].empty else []
    payload["top_losers"] = summary["top_losers"].to_dict("records") if not summary["top_losers"].empty else []
    with (out_dir / "summary.json").open("w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    try:
        with (out_dir / "backtest.pkl").open("wb") as fh:
            pickle.dump(
                {
                    "trades_df": summary["trades_df"],
                    "mtm_series": summary["mtm_series"],
                    "summary": {k: v for k, v in summary.items() if k not in ("trades_df", "mtm_series", "top_winners", "top_losers")},
                },
                fh,
            )
    except Exception:
        logger.exception("could not pickle backtest result for %s", summary["name"])


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--cache-root", default="data/screener_results/sfr_convex_screener_backtest_cache")
    p.add_argument("--only", nargs="*", help="If set, only run these config names")
    args = p.parse_args()

    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end)
    bt_dts = _bt_datetimes(start, end)

    cfg = _make_screener_cfg()
    cache_summary = _config_summary_for_cache(cfg)

    cache_root = Path(args.cache_root)
    cached = _list_cached_dates(cache_root, cache_summary)
    cached_in_range = [d for d in cached if start <= d <= end]
    logger.info(
        "TimeGrid: %d business datetimes [%s -> %s] | cached snapshots in range: %d (%s)",
        len(bt_dts), start, end, len(cached_in_range),
        ", ".join(d.isoformat() for d in cached_in_range[:6]) + (" ..." if len(cached_in_range) > 6 else ""),
    )

    configs = _grid_configs()
    if args.only:
        configs = {k: v for k, v in configs.items() if k in args.only}

    summaries: List[Dict[str, Any]] = []
    for name, bt_cfg in configs.items():
        out_dir = GRID_ROOT / name
        logger.info("=== running %s -> %s ===", name, out_dir)
        logger.info("  bt_cfg: %r", bt_cfg)
        t0 = time.monotonic()
        bt = run_backtest(
            bt_datetimes=bt_dts,
            screener_config=cfg,
            backtest_config=bt_cfg,
            cache_root=cache_root,
            snapshot_dates=cached_in_range,  # ONLY cached dates
            show_progress=False,
        )
        elapsed = time.monotonic() - t0
        summary = _summarize(bt, name=name, elapsed_s=elapsed)
        _persist(out_dir, summary)
        summaries.append(summary)
        logger.info(
            "=== %s done | %d trades | sharpe=%.2f | maxDD=%.0f | final=%.0f | %d open | %.1fs ===",
            name, summary["n_trades"], summary["sharpe"], summary["max_drawdown"],
            summary["final_mtm"], summary["n_unrealized_open"], elapsed,
        )

    print("\n## comparison\n")
    print("| name | trades | unrealized | sharpe | maxDD | finalMTM | winRate | avgHoldDays | wallSec |")
    print("|---|---|---|---|---|---|---|---|---|")
    for s in summaries:
        print(
            f"| {s['name']} | {s['n_trades']} | {s['n_unrealized_open']} | "
            f"{s['sharpe']:.2f} | {s['max_drawdown']:,.0f} | {s['final_mtm']:,.0f} | "
            f"{s['win_rate']:.2%} | {s['avg_holding_days']:.1f} | {s['elapsed_s']:.1f} |"
        )

    grid = {
        s["name"]: {k: v for k, v in s.items() if k not in ("trades_df", "mtm_series", "top_winners", "top_losers")}
        for s in summaries
    }
    GRID_ROOT.mkdir(parents=True, exist_ok=True)
    with (GRID_ROOT / "grid_summary.json").open("w") as fh:
        json.dump(grid, fh, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Drive the SFR Convex Screener backtest across a configuration grid.

Runs each config sequentially, persists raw artifacts (per-trade log, MTM
history, summary stats) under
``data/screener_results/sfr_convex_screener_backtest_grid/<config_name>/``,
and prints a Markdown comparison table at the end. Configs share the same
screener cache (``universe_size=12``, ``jpm_method=True``); the first run
primes it and every subsequent run reuses it.

Run via::

    conda run -n stir python scripts/run_screener_backtest_grid.py

Honours an optional ``--max-config-minutes`` knob (default 60) that aborts
any config exceeding the wall-time cap so the grid keeps moving even when
Barchart throttles cache priming.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import pickle
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backtest_grid")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from RVUtils.SFRConvexScreener import (  # noqa: E402
    JointMethod,
    SFRConvexScreenerConfig,
    SFRScreenerBacktestConfig,
)
from RVUtils.SFRConvexScreener.backtest import run_backtest  # noqa: E402

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
            entry_min_asymmetry=2.0,
            max_concurrent=3,
            exit_max_holding_days=22,
            exit_take_profit_bp=10.0,
            exit_stop_loss_bp=-15.0,
            rebalance_dow=4,
        ),
        "b_calendar_only": SFRScreenerBacktestConfig(
            structure_types=("calendar",),
            entry_min_asymmetry=3.0,
            max_concurrent=5,
            exit_asymmetry_threshold=1.5,
            exit_max_holding_days=22,
            rebalance_dow=4,
        ),
        "c_butterfly_only": SFRScreenerBacktestConfig(
            structure_types=("butterfly",),
            entry_min_asymmetry=3.0,
            max_concurrent=5,
            exit_asymmetry_threshold=1.5,
            exit_max_holding_days=44,
            rebalance_dow=4,
        ),
        "d_all_structures_default": SFRScreenerBacktestConfig(
            structure_types=("outright", "calendar", "butterfly"),
            entry_min_asymmetry=1.5,
            max_concurrent=5,
            exit_asymmetry_threshold=1.10,
            exit_take_profit_bp=10.0,
            exit_stop_loss_bp=-15.0,
            exit_max_holding_days=22,
            rebalance_dow=4,
        ),
        "e_aggressive_concurrency": SFRScreenerBacktestConfig(
            structure_types=("outright", "calendar", "butterfly"),
            entry_min_asymmetry=1.2,
            max_concurrent=10,
            exit_asymmetry_threshold=1.10,
            exit_take_profit_bp=10.0,
            exit_stop_loss_bp=-15.0,
            exit_max_holding_days=22,
            rebalance_dow=4,
        ),
        "f_daily_rebalance": SFRScreenerBacktestConfig(
            structure_types=("outright", "calendar", "butterfly"),
            entry_min_asymmetry=1.5,
            max_concurrent=5,
            exit_asymmetry_threshold=1.10,
            exit_take_profit_bp=10.0,
            exit_stop_loss_bp=-15.0,
            exit_max_holding_days=22,
            rebalance_dow=None,
        ),
    }


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
            "exit_reason": xmeta.get("reason"),
        })
    trades = pd.DataFrame(rows)

    mtm = pd.Series({pd.Timestamp(k): float(v) for k, v in (bt.mtm_history or {}).items()}).sort_index()
    if not mtm.empty:
        mtm.index = pd.DatetimeIndex(mtm.index).tz_localize(None) if mtm.index.tz is not None else mtm.index

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
    n_open_unrealized = len(getattr(bt.portfolio, "positions", []) or [])
    win_rate = float((trades["realized_pnl"] > 0).mean()) if n_trades else float("nan")
    avg_hold = float(trades["days"].mean()) if n_trades else float("nan")
    avg_daily = float(daily.mean()) if not daily.empty else float("nan")
    std_daily = float(daily.std()) if not daily.empty else float("nan")
    exit_breakdown = trades["exit_reason"].value_counts().to_dict() if n_trades else {}

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
        "n_unrealized_open": int(n_open_unrealized),
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "final_mtm": final_mtm,
        "win_rate": win_rate,
        "avg_holding_days": avg_hold,
        "avg_daily_pnl": avg_daily,
        "std_daily_pnl": std_daily,
        "exit_reason_counts": exit_breakdown,
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


class _Timeout(Exception):
    pass


def _alarm_handler(signum, frame):
    raise _Timeout()


def _run_with_timeout(callable_, seconds: int):
    if seconds <= 0:
        return callable_()
    if hasattr(signal, "SIGALRM"):  # POSIX only
        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(seconds)
        try:
            return callable_()
        finally:
            signal.alarm(0)
    return callable_()  # Windows: no SIGALRM, run uncapped — caller must monitor


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2025-10-28")
    p.add_argument("--end", default="2026-04-28")
    p.add_argument("--max-config-minutes", type=int, default=60)
    p.add_argument("--only", nargs="*", help="If set, only run these config names")
    args = p.parse_args()

    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end)
    bt_dts = _bt_datetimes(start, end)
    logger.info("grid timegrid: %d business datetimes [%s -> %s]",
                len(bt_dts), bt_dts[0].date(), bt_dts[-1].date())

    configs = _grid_configs()
    if args.only:
        configs = {k: v for k, v in configs.items() if k in args.only}
    if not configs:
        logger.warning("no configs selected")
        return 0

    screener_cfg = _make_screener_cfg()
    summaries: List[Dict[str, Any]] = []

    for name, bt_cfg in configs.items():
        out_dir = GRID_ROOT / name
        logger.info("=== running %s -> %s ===", name, out_dir)
        t0 = time.monotonic()
        try:
            bt = _run_with_timeout(
                lambda: run_backtest(
                    bt_datetimes=bt_dts,
                    screener_config=screener_cfg,
                    backtest_config=bt_cfg,
                    show_progress=True,
                ),
                seconds=args.max_config_minutes * 60,
            )
        except _Timeout:
            elapsed = time.monotonic() - t0
            logger.error("config %s exceeded %d-minute cap (%.0fs) — skipping",
                         name, args.max_config_minutes, elapsed)
            summaries.append({
                "name": name, "elapsed_s": elapsed, "timeout": True,
                "n_trades": 0, "sharpe": float("nan"), "max_drawdown": float("nan"),
                "final_mtm": float("nan"), "win_rate": float("nan"),
                "avg_holding_days": float("nan"),
                "avg_daily_pnl": float("nan"), "std_daily_pnl": float("nan"),
                "exit_reason_counts": {},
                "trades_df": pd.DataFrame(), "mtm_series": pd.Series([], dtype=float),
                "top_winners": pd.DataFrame(), "top_losers": pd.DataFrame(),
            })
            (out_dir).mkdir(parents=True, exist_ok=True)
            with (out_dir / "TIMEOUT.txt").open("w") as fh:
                fh.write(f"{elapsed:.0f}s exceeded {args.max_config_minutes}-minute cap\n")
            continue
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - t0
            logger.exception("config %s failed after %.0fs: %s", name, elapsed, exc)
            summaries.append({
                "name": name, "elapsed_s": elapsed, "error": repr(exc),
                "n_trades": 0, "sharpe": float("nan"), "max_drawdown": float("nan"),
                "final_mtm": float("nan"), "win_rate": float("nan"),
                "avg_holding_days": float("nan"),
                "avg_daily_pnl": float("nan"), "std_daily_pnl": float("nan"),
                "exit_reason_counts": {},
                "trades_df": pd.DataFrame(), "mtm_series": pd.Series([], dtype=float),
                "top_winners": pd.DataFrame(), "top_losers": pd.DataFrame(),
            })
            out_dir.mkdir(parents=True, exist_ok=True)
            with (out_dir / "ERROR.txt").open("w") as fh:
                fh.write(f"{elapsed:.0f}s failed:\n{exc!r}\n")
            continue

        elapsed = time.monotonic() - t0
        summary = _summarize(bt, name=name, elapsed_s=elapsed)
        _persist(out_dir, summary)
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
            logger.exception("could not pickle backtest result for %s", name)
        summaries.append(summary)
        logger.info("=== %s done | %d trades | sharpe=%.2f | maxDD=%.0f | final=%.0f | %.0fs ===",
                    name, summary["n_trades"], summary["sharpe"],
                    summary["max_drawdown"], summary["final_mtm"], elapsed)

    print("\n## comparison\n")
    print(f"| name | trades | sharpe | maxDD | winRate | avgHoldDays | finalMTM | wallSec |")
    print(f"|---|---|---|---|---|---|---|---|")
    for s in summaries:
        if s.get("timeout"):
            print(f"| {s['name']} | _TIMEOUT_ | - | - | - | - | - | {s['elapsed_s']:.0f} |")
        elif s.get("error"):
            print(f"| {s['name']} | _ERROR_ | - | - | - | - | - | {s['elapsed_s']:.0f} |")
        else:
            print(
                f"| {s['name']} | {s['n_trades']} | {s['sharpe']:.2f} | {s['max_drawdown']:,.0f} | "
                f"{s['win_rate']:.2%} | {s['avg_holding_days']:.1f} | {s['final_mtm']:,.0f} | "
                f"{s['elapsed_s']:.0f} |"
            )

    grid_summary = {
        s["name"]: {k: v for k, v in s.items() if k not in ("trades_df", "mtm_series", "top_winners", "top_losers")}
        for s in summaries
    }
    GRID_ROOT.mkdir(parents=True, exist_ok=True)
    with (GRID_ROOT / "grid_summary.json").open("w") as fh:
        json.dump(grid_summary, fh, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())

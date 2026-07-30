#!/usr/bin/env python
"""Benchmark thread vs process calibration executor for STIRF curve backfill.

Runs a small date range (default: 2 business days) with both executors and
reports wall-clock time, curves/sec, and effective speedup.

Usage:
    conda run --no-capture-output -n stir python -u scripts/benchmark_calibration_executor.py \
        --curve "USD-OIS-Q12xM12STIRT-SERFFX-MIX23" \
        --date 2026-07-10 \
        --n-jobs 6
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _run_single_day(
    *,
    curve_name: str,
    trade_date: dt.date,
    executor: str,
    n_jobs: int,
    cme_session: bool,
) -> dict:
    from zoneinfo import ZoneInfo
    import QuantLib as ql

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from scripts.stirf_curve_service import (
        _build_cme_trade_date_bucket,
        _select_missing_curve_store_timestamps,
        _resolve_curve_store_name,
        build_bulk_request,
    )

    tz = ZoneInfo("America/Chicago")
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

    timestamps = _build_cme_trade_date_bucket(
        trade_date=trade_date, freq="1min", timezone=tz, calendar=cal,
    ) if cme_session else []

    if not timestamps:
        return {"executor": executor, "date": str(trade_date), "status": "no_timestamps"}

    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    store = mdp._get_curve_store()
    store_curve = _resolve_curve_store_name(mdp, curve_name)
    missing = _select_missing_curve_store_timestamps(
        store, curve_name=store_curve, timestamps=timestamps,
    )

    if not missing:
        return {
            "executor": executor,
            "date": str(trade_date),
            "status": "all_cached",
            "total_timestamps": len(timestamps),
        }

    request = build_bulk_request(
        curve_name=curve_name,
        timestamps=missing,
        n_jobs=n_jobs,
        show_tqdm=True,
        ignore_cache=False,
        calibration_executor=executor,
        auto_prime_bulk=True,
        calibration_max_workers=n_jobs,
        max_tasks_per_child=50 if executor == "process" else None,
    )

    t0 = time.perf_counter()
    curves = mdp.bulk_get_data(request)
    elapsed = time.perf_counter() - t0

    return {
        "executor": executor,
        "date": str(trade_date),
        "status": "ok",
        "total_timestamps": len(timestamps),
        "missing_timestamps": len(missing),
        "calibrated": len(curves),
        "elapsed_seconds": round(elapsed, 2),
        "curves_per_second": round(len(curves) / elapsed, 2) if elapsed > 0 else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark thread vs process calibration")
    parser.add_argument("--curve", default="USD-OIS-Q12xM12STIRT-SERFFX-MIX23")
    parser.add_argument("--date", type=lambda s: dt.date.fromisoformat(s), required=True,
                        help="Single trade date to benchmark (YYYY-MM-DD)")
    parser.add_argument("--n-jobs", type=int, default=6)
    parser.add_argument("--cme-session", action="store_true", default=True)
    parser.add_argument("--executor", choices=("thread", "process", "both"), default="both",
                        help="Which executor(s) to benchmark")
    args = parser.parse_args()

    executors = ["thread", "process"] if args.executor == "both" else [args.executor]
    results = []

    for executor in executors:
        print(f"\n{'='*60}")
        print(f"Benchmarking executor={executor} n_jobs={args.n_jobs} date={args.date}")
        print(f"{'='*60}")
        result = _run_single_day(
            curve_name=args.curve,
            trade_date=args.date,
            executor=executor,
            n_jobs=args.n_jobs,
            cme_session=args.cme_session,
        )
        results.append(result)
        print(f"Result: {result}")

    if len(results) == 2 and all(r.get("elapsed_seconds") for r in results):
        thread_time = results[0]["elapsed_seconds"]
        process_time = results[1]["elapsed_seconds"]
        speedup = thread_time / process_time if process_time > 0 else float("inf")
        print(f"\n{'='*60}")
        print(f"COMPARISON: thread={thread_time}s  process={process_time}s  speedup={speedup:.2f}x")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()

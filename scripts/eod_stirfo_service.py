#!/usr/bin/env python
"""EOD STIR futures option cache warmer.

Warms the STIRFutureOptionPricer_Cache with option_snapshot and sabr_smile
entries for the first N SFR quarterly contracts (default 12) across a range
of business dates.

Two modes:
1. ``backfill``: iterate [start_date, end_date] business days, warm all.
2. ``live-service``: warm today (or an explicit date).

Usage:
  python scripts/eod_stirfo_service.py backfill --start-date 2026-06-01 --end-date 2026-06-19
  python scripts/eod_stirfo_service.py live-service
  python scripts/eod_stirfo_service.py live-service --date 2026-06-17
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import QuantLib as ql

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eod-stirfo")

DEFAULT_N_CONTRACTS = 12
DEFAULT_SOURCE = "BARCHART_STIRFO-QL"
DEFAULT_DELTAS = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]

_DELTA_SUFFIXES = [f"{d}DC" for d in DEFAULT_DELTAS] + [f"{d}DP" for d in DEFAULT_DELTAS]


def _is_business_day(value: dt.date, calendar: ql.Calendar) -> bool:
    ql_date = ql.Date(value.day, value.month, value.year)
    return bool(calendar.isBusinessDay(ql_date))


def iter_eod_business_dates(
    *,
    start_date: dt.date,
    end_date: dt.date,
    calendar: ql.Calendar | None = None,
) -> Iterator[dt.date]:
    cal = calendar or ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    current = start_date
    while current <= end_date:
        if _is_business_day(current, cal):
            yield current
        current += dt.timedelta(days=1)


def front_contracts(as_of: dt.date, count: int = DEFAULT_N_CONTRACTS) -> List[str]:
    from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _imm_cutoff, _next_contracts
    return _next_contracts(
        start_date=as_of,
        prefix="SFR",
        count=count,
        valid_months=[3, 6, 9, 12],
        cutoff_fn=_imm_cutoff,
    )


def _snapshot_symbols_for_contract(contract: str) -> List[str]:
    return [f"{contract}|{suffix}" for suffix in _DELTA_SUFFIXES]


def warm_stirfo_eod_date(
    mdp: Any,
    as_of: dt.date,
    contracts: List[str],
    *,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Warm option_snapshot + sabr_smile for all contracts on one date.

    Returns summary dict with counts.
    """
    stats: Dict[str, Any] = {
        "date": as_of.isoformat(),
        "contracts": list(contracts),
        "snapshot_ok": 0,
        "snapshot_fail": 0,
        "smile_ok": 0,
        "smile_fail": 0,
    }

    # --- Phase 1: option_snapshot (delta-addressed) per contract ---
    for contract in contracts:
        symbols = _snapshot_symbols_for_contract(contract)
        try:
            mdp.get_data({
                "endpoint": "option_snapshot",
                "symbols": symbols,
                "timestamp": as_of,
                "force_refresh": force_refresh,
            })
            stats["snapshot_ok"] += 1
        except Exception as exc:
            stats["snapshot_fail"] += 1
            log.warning("  snapshot FAIL %s @ %s: %s", contract, as_of, exc)

    # --- Phase 2: sabr_smile via bulk fetch ---
    try:
        mdp.fetch_bulk_sabr_smile({
            "symbols": list(contracts),
            "timestamps": [as_of],
            "force_refresh": force_refresh,
        })
        stats["smile_ok"] = len(contracts)
    except Exception as exc:
        log.warning("  bulk smile FAIL @ %s: %s — falling back to per-contract", as_of, exc)
        for contract in contracts:
            try:
                mdp.get_data({
                    "endpoint": "sabr_smile",
                    "symbol": contract,
                    "as_of": as_of,
                    "force_refresh": force_refresh,
                })
                stats["smile_ok"] += 1
            except Exception as exc2:
                stats["smile_fail"] += 1
                log.warning("  smile FAIL %s @ %s: %s", contract, as_of, exc2)

    return stats


def run_backfill(
    start_date: dt.date,
    end_date: dt.date,
    n_contracts: int = DEFAULT_N_CONTRACTS,
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    mdp = STIRFutureOptionMDP(source=DEFAULT_SOURCE)
    dates = list(iter_eod_business_dates(start_date=start_date, end_date=end_date))
    log.info("Backfill: %d business days (%s → %s), %d contracts/day",
             len(dates), start_date, end_date, n_contracts)

    all_stats: List[Dict[str, Any]] = []
    total = len(dates)

    with mdp:
        for i, as_of in enumerate(dates, 1):
            contracts = front_contracts(as_of, count=n_contracts)
            log.info("[%d/%d] %s  contracts: %s … %s",
                     i, total, as_of, contracts[0], contracts[-1])
            t0 = time.perf_counter()
            stats = warm_stirfo_eod_date(mdp, as_of, contracts, force_refresh=force_refresh)
            elapsed = time.perf_counter() - t0
            stats["elapsed_s"] = round(elapsed, 1)
            all_stats.append(stats)
            log.info("  done in %.1fs  snap=%d/%d  smile=%d/%d",
                     elapsed,
                     stats["snapshot_ok"], stats["snapshot_ok"] + stats["snapshot_fail"],
                     stats["smile_ok"], stats["smile_ok"] + stats["smile_fail"])

    return all_stats


def run_live_service(
    date: dt.date | None = None,
    n_contracts: int = DEFAULT_N_CONTRACTS,
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    target = date or dt.date.today()
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    if not _is_business_day(target, cal):
        log.info("Skipping non-business day %s", target)
        return []

    mdp = STIRFutureOptionMDP(source=DEFAULT_SOURCE)
    contracts = front_contracts(target, count=n_contracts)
    log.info("Live service: %s  contracts: %s … %s", target, contracts[0], contracts[-1])

    with mdp:
        t0 = time.perf_counter()
        stats = warm_stirfo_eod_date(mdp, target, contracts, force_refresh=force_refresh)
        elapsed = time.perf_counter() - t0
        stats["elapsed_s"] = round(elapsed, 1)
        log.info("done in %.1fs  snap=%d/%d  smile=%d/%d",
                 elapsed,
                 stats["snapshot_ok"], stats["snapshot_ok"] + stats["snapshot_fail"],
                 stats["smile_ok"], stats["smile_ok"] + stats["smile_fail"])

    return [stats]


def main():
    parser = argparse.ArgumentParser(description="EOD STIR futures option cache warmer")
    sub = parser.add_subparsers(dest="mode")

    bf = sub.add_parser("backfill", help="Backfill a date range")
    bf.add_argument("--start-date", required=True, type=str)
    bf.add_argument("--end-date", required=True, type=str)
    bf.add_argument("--n-contracts", type=int, default=DEFAULT_N_CONTRACTS)
    bf.add_argument("--force-refresh", action="store_true")

    ls = sub.add_parser("live-service", help="Warm today or a specific date")
    ls.add_argument("--date", type=str, default=None)
    ls.add_argument("--n-contracts", type=int, default=DEFAULT_N_CONTRACTS)
    ls.add_argument("--force-refresh", action="store_true")

    args = parser.parse_args()

    if args.mode == "backfill":
        start = dt.date.fromisoformat(args.start_date)
        end = dt.date.fromisoformat(args.end_date)
        all_stats = run_backfill(start, end, args.n_contracts, args.force_refresh)
    elif args.mode == "live-service":
        target = dt.date.fromisoformat(args.date) if args.date else None
        all_stats = run_live_service(target, args.n_contracts, args.force_refresh)
    else:
        parser.print_help()
        return

    # Summary
    total_snap_ok = sum(s["snapshot_ok"] for s in all_stats)
    total_snap_fail = sum(s["snapshot_fail"] for s in all_stats)
    total_smile_ok = sum(s["smile_ok"] for s in all_stats)
    total_smile_fail = sum(s["smile_fail"] for s in all_stats)
    total_elapsed = sum(s.get("elapsed_s", 0) for s in all_stats)
    log.info("=" * 60)
    log.info("SUMMARY: %d days  snapshots=%d/%d  smiles=%d/%d  total=%.1fs",
             len(all_stats),
             total_snap_ok, total_snap_ok + total_snap_fail,
             total_smile_ok, total_smile_ok + total_smile_fail,
             total_elapsed)


if __name__ == "__main__":
    main()

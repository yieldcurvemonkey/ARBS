"""Daily cache warmer for all notebook timeseries sources.

Prices EOD data for all curves/products used in notebooks/timeseries/,
writing results to the computed TS cache (DuckDB + Parquet + Supabase).

Usage:
  python scripts/daily_cache_warmer.py                     # today only
  python scripts/daily_cache_warmer.py --backfill 7        # past 7 days
  python scripts/daily_cache_warmer.py --date 2026-03-28   # specific date
  python scripts/daily_cache_warmer.py --jobs 1,2,3        # run specific jobs only
  python scripts/daily_cache_warmer.py --list               # list available jobs

Runs on the desktop workstation; laptop pulls from Supabase on first query.
"""

import argparse
import datetime
import logging
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cache-warmer")

N_JOBS = 12

# ─────────────────────────────────────────────────────────────────────
# Tenor sets
# ─────────────────────────────────────────────────────────────────────

# Outrights: standard benchmark tenors
_EOD_OUTRIGHT_TENORS = (
    "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y",
    "11Y", "12Y", "15Y", "20Y", "25Y", "30Y", "40Y", "50Y",
)

# Forward starts: short-end + belly + long-end
_EOD_FORWARD_TENORS = (
    # Short fwd x short tail
    "3m3m", "3m6m", "3m1y", "3m2y",
    "6m3m", "6m6m", "6m1y", "6m2y",
    # 1Y fwd
    "1y1y", "1y2y", "1y3y", "1y5y", "1y10y",
    # 2Y fwd
    "2y1y", "2y2y", "2y3y", "2y5y", "2y10y",
    # 3Y fwd
    "3y2y", "3y5y", "3y7y",
    # 5Y fwd
    "5y5y", "5y10y", "5y20y", "5y25y",
    # 10Y fwd
    "10y10y", "10y20y",
)

# Curve spreads (swap spreads over USTs)
_EOD_CURVE_SPREAD_TENORS = (
    "CT2", "CT5", "CT7", "CT10", "CT20", "CT30",
    "CT2/CT10", "CT2/CT30", "CT5/CT30", "CT7/CT20", "CT7/CT30", "CT10/CT30",
)

# UST aliases: on-the-runs, olds, double-olds, triple-olds
# CT{N} = on-the-run (rank 0), O{N} = old (rank 1),
# OO{N} = double-old (rank 2), OOO{N} = triple-old (rank 3)
_FRB_TENORS = (2, 3, 5, 7, 10, 20, 30)
_FRB_CUSIPS = (
    # On-the-runs
    *[f"CT{t}" for t in _FRB_TENORS],
    # Olds
    *[f"O{t}" for t in _FRB_TENORS],
    # Double-olds
    *[f"OO{t}" for t in _FRB_TENORS],
    # Triple-olds
    *[f"OOO{t}" for t in _FRB_TENORS],
)

# USD-OIS uses the same outrights + a subset of forwards (max 30Y)
_OIS_OUTRIGHT_TENORS = tuple(t for t in _EOD_OUTRIGHT_TENORS if int(t.rstrip("Y")) <= 30)
_OIS_FORWARD_TENORS = (
    "1y1y", "1y2y", "1y5y", "1y10y",
    "2y2y", "2y5y", "2y10y",
    "5y5y", "5y10y", "5y25y",
    "10y10y", "10y20y",
)


# ─────────────────────────────────────────────────────────────────────
# Job definitions
# ─────────────────────────────────────────────────────────────────────

def warm_gsquant_ois_eod(start, end):
    """Job 1: GSQUANT-RL USD-OIS EOD — outrights + forwards."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue

    mdp = IRSwapsMDP(source="GSQUANT-RL")
    tb = TimeseriesBuilder()

    queries = [
        UnifiedQuery(curve="USD-OIS", tenor=t, value=UnifiedValue.IRS_RATE)
        for t in (*_OIS_OUTRIGHT_TENORS, *_OIS_FORWARD_TENORS)
    ]
    log.info("  %d queries (%d outrights + %d forwards)",
             len(queries), len(_OIS_OUTRIGHT_TENORS), len(_OIS_FORWARD_TENORS))

    df = tb.get_timeseries(
        start=start,
        end=end,
        queries=queries,
        n_jobs=N_JOBS,
        routers={"IRS": IRSwapsTB(mdp, show_tqdm=True)},
        ignore_cache_miss=True,
    )
    return df


def warm_eris_eod(start, end):
    """Job 2: ERIS EOD USD-SOFR-1D — outrights + forwards + swap spreads."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from TB.IRSwapsTB import IRSwapsTB
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue

    curve_mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
    usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")
    tb = TimeseriesBuilder()

    queries = []

    # Outright rates
    for t in _EOD_OUTRIGHT_TENORS:
        queries.append(UnifiedQuery(curve="USD-SOFR-1D", tenor=t, value=UnifiedValue.IRS_RATE))

    # Forward start rates
    for t in _EOD_FORWARD_TENORS:
        queries.append(UnifiedQuery(curve="USD-SOFR-1D", tenor=t, value=UnifiedValue.IRS_RATE))

    # Swap spreads (MMSS + SPREADOVER) for single tenors
    for cusip in ("CT2", "CT5", "CT7", "CT10", "CT20", "CT30"):
        queries.append(UnifiedQuery(curve="USD-SOFR-1D", tenor=cusip, value=UnifiedValue.IRS_MMSS))
        queries.append(UnifiedQuery(curve="USD-SOFR-1D", tenor=cusip, value=UnifiedValue.IRS_SPREADOVER))

    # Curve spreads (MMSS + SPREADOVER)
    for pair in ("CT2/CT10", "CT2/CT30", "CT5/CT30", "CT7/CT20", "CT7/CT30", "CT10/CT30"):
        queries.append(UnifiedQuery(curve="USD-SOFR-1D", tenor=pair, value=UnifiedValue.IRS_MMSS))
        queries.append(UnifiedQuery(curve="USD-SOFR-1D", tenor=pair, value=UnifiedValue.IRS_SPREADOVER))

    log.info("  %d queries (outrights + forwards + swap spreads)", len(queries))

    df = tb.get_timeseries(
        start=start,
        end=end,
        queries=queries,
        n_jobs=N_JOBS,
        routers={
            "IRS": IRSwapsTB(curve_mdp, show_tqdm=True),
            "FRB": FixedRateBondsTB(usts_mdp, show_tqdm=True),
        },
        ignore_cache_miss=True,
    )
    return df


def warm_frb_fedinvest_eod(start, end):
    """Job 3: FedInvest UST YTMs for on-the-run CUSIPs."""
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue

    usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")
    tb = TimeseriesBuilder()
    queries = [
        UnifiedQuery(cusip=c, value=UnifiedValue.FRB_YTM)
        for c in _FRB_CUSIPS
    ]
    log.info("  %d CUSIPs: %s", len(_FRB_CUSIPS), ", ".join(_FRB_CUSIPS))

    df = tb.get_timeseries(
        start=start,
        end=end,
        queries=queries,
        n_jobs=N_JOBS,
        routers={"FRB": FixedRateBondsTB(usts_mdp, show_tqdm=True)},
    )
    return df


def warm_stirf_cme_session(start, end):
    """Job 4: STIRF intraday CME session curves via stirf_curve_service.py.

    Delegates to the existing backfill script which calibrates raw curves
    at 1-minute resolution for the full CME Globex session (17:00 CT prior
    day through 16:00 CT trade date). The default tenors for STIRT curves
    are the 12 IMM relative pairs (IMM_1xIMM_2 through IMM_12xIMM_13).
    """
    import pandas as pd
    import QuantLib as ql

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    bdates = pd.bdate_range(start, end).date.tolist()
    bdates = [
        d for d in bdates
        if cal.isBusinessDay(ql.Date(d.day, d.month, d.year))
    ]

    if not bdates:
        log.info("No business days in range for STIRF backfill")
        return None

    curves = [
        "USD-SOFR-1D-Q12STIRT",
        "USD-SOFR-1D-Q16STIRT",
        # "CAD-CORRA-Q8STIRT",
        "USD-OIS-Q12xM12STIRT-SERFFX-MIX23",
        # "USD-SOFR-1D-Q12xM12STIRT",
    ]
    python_exe = sys.executable
    script = os.path.join(REPO_ROOT, "scripts", "stirf_curve_service.py")

    for curve in curves:
        cmd = [
            python_exe, script, "backfill",
            "--curve", curve,
            "--start-date", bdates[0].isoformat(),
            "--end-date", bdates[-1].isoformat(),
            "--cme-session",
        ]
        log.info("Running: %s", " ".join(cmd))
        result = subprocess.run(cmd, cwd=REPO_ROOT, timeout=3600)
        if result.returncode != 0:
            log.warning("stirf_curve_service exited %d for %s", result.returncode, curve)

    return f"STIRF backfill: {len(bdates)} days x {len(curves)} curves"


def warm_stirfo_eod(start, end):
    """Job 6: SFR options EOD — option snapshots + SABR smiles.

    Warms option_snapshot (delta-addressed, 20 symbols/contract) and
    sabr_smile (SABR beta=0.5 calibration) for the first 12 SFR quarterly
    contracts on each business day in the range.
    """
    from scripts.eod_stirfo_service import run_backfill

    all_stats = run_backfill(start, end, n_contracts=12)
    total_snap = sum(s["snapshot_ok"] for s in all_stats)
    total_smile = sum(s["smile_ok"] for s in all_stats)
    return f"STIRFO EOD: {len(all_stats)} days, {total_snap} snapshots, {total_smile} smiles"


def warm_ustf_invoice_caches(start, end):
    """Job 5: UST futures delivery basket + pricer caches.

    Populates USTFutureDeliveryBasket_Cache and USTFuturePricer_Cache for the
    front-month contracts of TU/FV/TY/UXY/US/WN. Without this, the SDR
    invoice-swap enrichment path (``_build_invoice_swap_lookup``) pays a
    Barchart + FedInvest round-trip per root on first use — ~90s before the
    Apr-2026 perf fix, still ~22s with only basket warmed.

    Delegates to scripts/warm_ustf_cache.py which owns the warming logic.
    The basket cache is keyed by ``as_of`` date, so we warm every business
    day in the requested range.
    """
    import pandas as pd
    import QuantLib as ql

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    bdates = pd.bdate_range(start, end).date.tolist()
    bdates = [
        d for d in bdates
        if cal.isBusinessDay(ql.Date(d.day, d.month, d.year))
    ]

    if not bdates:
        log.info("No business days in range for UST futures warm")
        return None

    python_exe = sys.executable
    script = os.path.join(REPO_ROOT, "scripts", "warm_ustf_cache.py")

    for as_of in bdates:
        cmd = [
            python_exe, script,
            "--basket-days", "1",
            "--skip-prices",
        ]
        # When warming a historical date, --basket-days alone targets today;
        # use --backfill-days spanning today->as_of when backfilling.
        days_back = (datetime.date.today() - as_of).days
        if days_back > 0:
            cmd = [python_exe, script, "--backfill-days", str(days_back + 1), "--skip-prices"]

        log.info("Running: %s", " ".join(cmd))
        result = subprocess.run(cmd, cwd=REPO_ROOT, timeout=600)
        if result.returncode != 0:
            log.warning("warm_ustf_cache exited %d for as_of=%s", result.returncode, as_of)

        # Historical backfill call above covers all days up to today — no
        # need to iterate further.
        if days_back > 0:
            break

    return f"UST futures warm: {len(bdates)} day(s)"


# ─────────────────────────────────────────────────────────────────────
# Job registry
# ─────────────────────────────────────────────────────────────────────

JOBS = [
    ("GSQUANT USD-OIS EOD", warm_gsquant_ois_eod),
    ("ERIS USD-SOFR-1D EOD", warm_eris_eod),
    ("FRB FedInvest EOD", warm_frb_fedinvest_eod),
    ("STIRF CME Session", warm_stirf_cme_session),
    ("UST Futures Invoice Caches", warm_ustf_invoice_caches),
    ("STIRFO SFR Options EOD", warm_stirfo_eod),
]


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Daily cache warmer for notebook sources")
    parser.add_argument("--date", type=str, help="Specific date (YYYY-MM-DD)")
    parser.add_argument("--backfill", type=int, metavar="N", help="Backfill past N days")
    parser.add_argument("--jobs", type=str, help="Comma-separated job indices (1-based), e.g. '1,3'")
    parser.add_argument("--list", action="store_true", help="List available jobs and exit")
    args = parser.parse_args()

    if args.list:
        print("Available jobs:")
        for i, (name, _) in enumerate(JOBS, 1):
            print(f"  {i}. {name}")
        return

    # Determine date range
    if args.date:
        target = datetime.date.fromisoformat(args.date)
        start = end = target
    elif args.backfill:
        end = datetime.date.today()
        start = end - datetime.timedelta(days=args.backfill)
    else:
        start = end = datetime.date.today()

    log.info("Cache warming: %s to %s", start, end)

    # Select jobs
    if args.jobs:
        indices = [int(x.strip()) - 1 for x in args.jobs.split(",")]
        selected = [(i, JOBS[i]) for i in indices if 0 <= i < len(JOBS)]
    else:
        selected = list(enumerate(JOBS))

    # Run jobs
    results = []
    for idx, (name, fn) in selected:
        log.info("─" * 60)
        log.info("Job %d: %s", idx + 1, name)
        t0 = time.perf_counter()
        try:
            result = fn(start, end)
            elapsed = time.perf_counter() - t0
            shape = getattr(result, "shape", None)
            status = f"OK ({elapsed:.1f}s"
            if shape:
                status += f", {shape[0]} rows x {shape[1]} cols"
            status += ")"
            results.append((name, status))
            log.info("  %s", status)
        except Exception as e:
            elapsed = time.perf_counter() - t0
            results.append((name, f"FAILED ({elapsed:.1f}s): {e}"))
            log.exception("  FAILED: %s", e)

    # Summary
    log.info("=" * 60)
    log.info("SUMMARY")
    log.info("=" * 60)
    for name, status in results:
        log.info("  %-30s %s", name, status)


if __name__ == "__main__":
    main()

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

from utils.warm_jobs import STORE, WarmJob, check, describe  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cache-warmer")

#: Where the run's own record goes. ``/logs`` is gitignored.
#:
#: This exists because there was no record at all. The scheduled task's action
#: carries no redirection, so the SUMMARY table went to a console nobody reads,
#: and Windows' own ``TaskScheduler/Operational`` log is disabled on this
#: machine - so "did last night's warm work?" had no answer anywhere except by
#: inspecting the CurveStore and inferring. Dated per run rather than rotated on
#: a clock, because two tasks (weekday 18:15 and Saturday 10:00) write here and a
#: rotating handler shared between processes truncates whichever one loses.
LOG_DIR = os.path.join(REPO_ROOT, "logs", "cache_warmer")
LOG_RETENTION = 60

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

# ── Citi Velocity ────────────────────────────────────────────────────
#
# The five majors that are warmed in the CurveStore. The other fifteen Citi
# curves still work through the live path; they are simply not warmed, so
# pricing them here would drive Excel on a schedule.
_CITIVELO_CURVES = (
    "USD-SOFR-1D",
    "EUR-ESTR-1D",
    "GBP-SONIA-1D",
    "CAD-CORRA-1D",
    "JPY-TONAR-1D-LCH",
)

# EOD tenors, same shape as the ERIS job. Capped at 30Y: Citi serves out to 50Y
# but the long end is thin in the non-USD currencies.
_CITIVELO_EOD_OUTRIGHTS = (
    "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y",
)
_CITIVELO_EOD_FORWARDS = (
    "1y1y", "1y5y", "2y5y", "5y5y", "5y10y", "10y10y",
)
_CITIVELO_EOD_SPREADS = (
    "2y/5y", "2y/10y", "5y/10y", "10y/30y", "2y/5y/10y", "5y/10y/30y",
)

# Intraday is deliberately a SUBSET. The minute store holds ~1,100 points per
# curve per day, so pricing the full EOD grid on a 15-minute stride would be
# 5 curves x 33 tenors x 33 points a day, every day, for numbers nobody has
# asked for. These are the ones that get looked at intraday.
_CITIVELO_INTRADAY_TENORS = ("2Y", "5Y", "10Y", "30Y", "2y/10y", "5y/10y/30y")
_CITIVELO_INTRADAY_FREQ = "15min"

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

def _business_days(start, end):
    import pandas as pd

    return [d.date() for d in pd.bdate_range(start, end)]


#: Every non-zero subprocess exit seen this run, as ``(label, returncode)``.
#:
#: A job that shells out is deliberately allowed to continue past a failed step -
#: an intraday fetch that dies still leaves work for the build and EOD phases to
#: do. What was NOT deliberate is that the failure then vanished: every caller of
#: :func:`_run` discards the return code, ``main`` caught nothing, and the process
#: exited 0. Recorded here so the run can end honestly even though the step it
#: lost was survivable.
_SUBPROCESS_FAILURES: list[tuple[str, int]] = []


def _run(cmd, label):
    """Run a warm script as a subprocess and report, without killing the run."""
    log.info("  %s: %s", label, " ".join(cmd[2:]))
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if result.returncode != 0:
        log.warning("  %s exited %d", label, result.returncode)
        _SUBPROCESS_FAILURES.append((label, result.returncode))
    return result.returncode


def warm_citivelo_curve_stores(start, end):
    """Job 7: Citi Velocity CurveStore - intraday minutes then EOD.

    ORDER MATTERS and so does the split. ``fetch`` is the only phase that drives
    Excel; ``build`` is pure CPU. Keeping them separate is what makes the job
    resumable, because a day already on disk is skipped on the next run.

    The fetch is given a memory ceiling on purpose. The add-in's own series cache
    only ever grows and only a HUMAN restart clears it - a 528-window run wedged
    Excel at 5,249 MB on 2026-08-07. Above ``--memory-abort-mb`` the fetch stops
    cleanly and reports what it banked rather than pushing further; the next
    scheduled run picks up where it left off.
    """
    py = sys.executable
    days = _business_days(start, end)
    if not days:
        log.info("  no business days in range")
        return None

    curves = ",".join(_CITIVELO_CURVES)
    # end is exclusive in the fetcher's window arithmetic
    fetch_end = (max(days) + datetime.timedelta(days=1)).isoformat()

    _run([py, "-u", "scripts/citivelo_excel_intraday_warm.py", "fetch",
          "--curves", curves, "--start", min(days).isoformat(), "--end", fetch_end,
          "--recycle-every", "20", "--memory-ceiling-mb", "2500",
          "--memory-abort-mb", "3800"], "intraday fetch")

    _run([py, "-u", "scripts/citivelo_excel_intraday_warm.py", "build",
          "--curves", curves], "intraday build")

    # EOD runs entirely offline against the banked tag cache.
    _run([py, "-u", "scripts/citivelo_excel_warm.py", "warm",
          "--curves", curves, "--start", min(days).isoformat(),
          "--end", max(days).isoformat()], "EOD warm")

    _run([py, "-u", "scripts/citivelo_excel_intraday_warm.py", "status"], "status")
    return None


def warm_citivelo_swaption_cube(start, end):
    """Job 8: Citi Velocity swaption cube - vol tags, then the cube store.

    ``fetch`` is the Excel phase and carries the same memory ceiling; ``build``
    assembles one cube per observation date from the cached quotes with no Excel
    and no network.
    """
    py = sys.executable
    _run([py, "-u", "scripts/citivelo_swaption_vol_warm.py", "fetch",
          "--currency", "USD", "--memory-abort-mb", "3800"], "vol fetch")
    _run([py, "-u", "scripts/citivelo_swaption_vol_warm.py", "build",
          "--currency", "USD"], "cube build")
    _run([py, "-u", "scripts/citivelo_swaption_vol_warm.py", "status",
          "--currency", "USD"], "status")
    return None


def warm_citivelo_timeseries_eod(start, end):
    """Job 9: Citi Velocity EOD timeseries values, five currencies.

    Reads the warmed CurveStore - no Excel. Run this AFTER job 7 so the day it
    needs is already in the store; a date outside the warm silently falls through
    to the live path and would drive Excel from a scheduled task.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    tb = TimeseriesBuilder()

    queries = [
        UnifiedQuery(curve=curve, tenor=tenor, value=UnifiedValue.IRS_RATE)
        for curve in _CITIVELO_CURVES
        for tenor in (*_CITIVELO_EOD_OUTRIGHTS, *_CITIVELO_EOD_FORWARDS, *_CITIVELO_EOD_SPREADS)
    ]
    log.info("  %d queries (%d curves x %d tenors)", len(queries), len(_CITIVELO_CURVES),
             len(_CITIVELO_EOD_OUTRIGHTS) + len(_CITIVELO_EOD_FORWARDS) + len(_CITIVELO_EOD_SPREADS))

    return tb.get_timeseries(
        start=start,
        end=end,
        queries=queries,
        n_jobs=N_JOBS,
        routers={"IRS": IRSwapsTB(mdp, show_tqdm=True)},
        ignore_cache_miss=True,
    )


def warm_citivelo_timeseries_intraday(start, end):
    """Job 10: Citi Velocity intraday timeseries values, five currencies.

    A 15-minute stride over each day's session, from the minute store. The
    session runs 08:00-19:59 in the curve's OWN zone, so the window below is
    deliberately wide enough to cover all five and is trimmed by what the store
    actually holds.
    """
    import pytz

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    nyc = pytz.timezone("America/New_York")
    days = _business_days(start, end)
    if not days:
        log.info("  no business days in range")
        return None

    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    tb = TimeseriesBuilder()
    queries = [
        UnifiedQuery(curve=curve, tenor=tenor, value=UnifiedValue.IRS_RATE)
        for curve in _CITIVELO_CURVES
        for tenor in _CITIVELO_INTRADAY_TENORS
    ]
    log.info("  %d queries x %d day(s) at %s", len(queries), len(days), _CITIVELO_INTRADAY_FREQ)

    frames = []
    for day in days:
        try:
            frame = tb.get_timeseries(
                start=nyc.localize(datetime.datetime.combine(day, datetime.time(2, 0))),
                end=nyc.localize(datetime.datetime.combine(day, datetime.time(17, 0))),
                queries=queries,
                freq=_CITIVELO_INTRADAY_FREQ,
                n_jobs=N_JOBS,
                routers={"IRS": IRSwapsTB(mdp, show_tqdm=True)},
                ignore_cache_miss=True,
            )
            if frame is not None and len(frame):
                frames.append(frame)
        except Exception as exc:  # one bad day must not end the job
            log.warning("  %s failed: %s: %s", day, type(exc).__name__, exc)

    if not frames:
        return None
    import pandas as pd

    return pd.concat(frames).sort_index()


# ─────────────────────────────────────────────────────────────────────
# Citi Velocity jobs
#
# These four are the only jobs in the registry with an ordering constraint
# between them, and it is a real one rather than a tidiness preference. The
# Velocity sources read their numbers from the tag cache and fall through to
# LIVE EXCEL on a miss. A value job scheduled before its tag warm therefore
# does not fail - it opens a workbook, on a scheduled task, at whatever hour
# this runs, against an add-in whose memory only ever grows and that only a
# human restart clears. It wedged at 5,249 MB on 2026-08-07.
#
# So the dependency is declared (`provides`/`requires` on each WarmJob) and
# checked at import by utils.warm_jobs.check. Reordering two lines in the
# registry now raises instead of quietly arranging that failure.
# ─────────────────────────────────────────────────────────────────────

#: Asset keys the tag warms provide and the value jobs require. Distinct per
#: producer: two jobs writing one key is caught by assert_unique_providers.
_CV_BOND_TAGS = "CITIVELO-TAGS-RATES.BOND"
_CV_BOND_TAGS_MI01 = "CITIVELO-TAGS-RATES.BOND-MI01"
_CV_SWAP_SPREAD_TAGS = "CITIVELO-TAGS-RATES.OIS.SWAP_SPREAD"

#: Stop below this. See utils/warm_jobs.py and the 2026-08-07 wedge.
_CV_MEMORY_CEILING_MB = 3800.0

#: The bonds warmed daily. On-the-run and first three off-the-runs across the
#: curve, expressed as ISINs at run time via the alias table, plus whatever the
#: caller adds. Kept small deliberately: the universe is 2,162 bonds and a full
#: warm is an Excel-memory problem, not a time problem.
_CV_BOND_TENORS = (2, 3, 5, 7, 10, 20, 30)
_CV_BOND_ALIASES = tuple(f"CT{t}" for t in _CV_BOND_TENORS) + tuple(f"O{t}" for t in _CV_BOND_TENORS)

#: The index whose swap-spread axis is warmed. The TENORS are deliberately NOT
#: listed here: the axis is ragged and per index, so a hardcoded tuple is wrong
#: for anything but USD. USD_SOFR/USD_FEDFUND carry eleven (money-market tenors
#: in, no 4Y/15Y/25Y); GBP_SONIA carries a different ten (no 1M-1Y, but 15Y/40Y/
#: 50Y); EUR_EUROSTR has no SWAP_SPREAD sub-type at all. Only 13 of the 20
#: indices carry the family. `swap_spread_tenors` reads the real axis from the
#: catalog and raises rather than inventing one.
_CV_SWAP_SPREAD_INDEX = "USD_SOFR"


def _citivelo_excel_guard():
    """Refuse to start a Velocity warm against an Excel that is already too big.

    The size is read BEFORE anything connects. An earlier version of this called
    ``quotes.client()`` and then asked the connected client for its memory, which
    is a guard that runs after the act it exists to prevent — opening a workbook
    against a wedged add-in is exactly what the ceiling is for, and by then it has
    happened. ``memory_guard`` asks Windows over ``Get-Process`` instead, with no
    COM involved, and fails closed when the probe cannot be read at all.

    Returns ``(quotes, client)`` so the caller can sample again on the way out.
    """
    from MDP.CitiVelocityExcel.memory_guard import assert_safe_to_connect
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    mb = assert_safe_to_connect(_CV_MEMORY_CEILING_MB, what="a Citi Velocity warm")
    log.info("  Excel at %.0f MB before connecting (ceiling %.0f)", mb, _CV_MEMORY_CEILING_MB)
    quotes = CitiVeloQuotes()
    return quotes, quotes.client()


def _citivelo_bond_resolutions(as_of):
    """The warm's bond set, as BondResolutions, via the repo's own alias table.

    Uses ``FixedRateBondsMDP._resolve_aliases_bulk`` rather than a private alias
    list so the warm covers exactly the bonds the queries will ask for. An alias
    that resolves to a bond Citi does not quote is dropped with a log line
    instead of failing the job - Citi carries a liquid subset, and a warm that
    dies because one off-the-run is missing is worse than one that says so.
    """
    from MDP.CitiVelocityExcel.bonds.resolution import resolve_bonds
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP, _filter_and_rank_ref_df
    from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

    mdp = FixedRateBondsMDP(source="USTS_CITIVELO-RL")
    ref_df = _filter_and_rank_ref_df(update_reference_data(source="fiscaldata"), as_of)
    alias_to_cusip, _ = mdp._resolve_aliases_bulk(list(_CV_BOND_ALIASES), as_of, ref_df=ref_df)
    resolved, failures = resolve_bonds(list(alias_to_cusip.values()), strict=False)
    if failures:
        log.info("  %d alias(es) not quoted by Citi, skipped: %s",
                 len(failures), ", ".join(sorted(failures)))
    return list(resolved.values())


def warm_citivelo_ust_universe_eod(start, end):
    """Job 7 [STORE]: the WHOLE Citi UST universe at DAILY, into the tag cache.

    Citi is the truth source for these bonds, so the cache holds all 349 rather
    than the fourteen on-the-run aliases the value jobs happen to ask for. A
    warmed tag is what stops a later value request falling through to live Excel,
    and this runs unattended.

    Measured 2026-08-08: 349 bonds, 2,302 tags, five years of history, 137 s,
    Excel +287 MB for the one-off deep warm. EOD is cheap - 52 tags over five
    years cost +1 MB - so the whole universe costs about what one liquid basket
    used to. The nightly window is 30 days; see the comment on the call.

    Resumable: ``citivelo_ust_universe_warm`` records progress per batch, so a
    run that stops at the memory ceiling resumes tomorrow rather than restarting.
    """
    from scripts.citivelo_ust_universe_warm import warm

    # A ROLLING window, not the full history, and the reason is the resume key:
    # it includes the end date, so `end = today` changes every night and the whole
    # universe would look un-warmed every single run. Five years nightly is 137 s
    # of Excel for data that has not moved. Thirty days keeps the cache current
    # and costs seconds.
    #
    # The deep backfill is a separate, deliberate act:
    #     python scripts/citivelo_ust_universe_warm.py eod --years 5
    # Run once (it has been), or after a gap. Override here with
    # CITIVELO_UST_EOD_DAYS when a longer nightly window is actually wanted.
    days = int(os.environ.get("CITIVELO_UST_EOD_DAYS", "30"))
    out = warm("eod", start=end - datetime.timedelta(days=days), end=end,
               ceiling_mb=_CV_MEMORY_CEILING_MB)
    if out.get("stopped"):
        raise RuntimeError(
            f"UST universe EOD warm stopped after {out['done']}/{out['of']} bonds: "
            f"{out['reason']}. Progress is in the manifest; re-run to continue."
        )
    return None


def warm_citivelo_ust_universe_intraday(start, end):
    """Job 8 [STORE]: the WHOLE Citi UST universe at MI01, into the tag cache.

    ``PRICE`` and ``YIELD`` only, and that is a measured budget rather than a
    preference: intraday costs ~1.7 MB of Excel per tag, so these two across 349
    bonds are 698 tags and about 170 MB, while the full seven-value set would be
    2,302 tags and ~3.9 GB - over the ceiling, in a process only a human restart
    can shrink. Widen with ``--values`` when someone is watching.

    Measured 2026-08-08: 349 bonds, 698 tags, 48 s, Excel +170 MB.

    Note this deliberately drives ``CitiVeloQuotes.frame`` in sub-cliff windows
    rather than ``CitiVeloBondFetcher.fetch``. The fetcher is the right way to
    READ an intraday quote, but it reaches ``quotes.client()`` directly, so
    nothing it fetches is cached - the first version of this warm "succeeded" on
    349 bonds and left zero MI01 files on disk. See ``_warm_intraday``.
    """
    from scripts.citivelo_ust_universe_warm import warm

    days = int(os.environ.get("CITIVELO_UST_INTRADAY_DAYS", "2"))
    out = warm("intraday", start=end - datetime.timedelta(days=days), end=end,
               ceiling_mb=_CV_MEMORY_CEILING_MB)
    if out.get("stopped"):
        raise RuntimeError(
            f"UST universe intraday warm stopped after {out['done']}/{out['of']} bonds: "
            f"{out['reason']}. Progress is in the manifest; re-run to continue."
        )
    return None


def warm_citivelo_swap_spread_tags(start, end):
    """Job 8 [STORE]: pull RATES.OIS.<index>.SWAP_SPREAD.<tenor> into the tag cache.

    The tenor axis comes from the catalog, not from a literal here — it is ragged
    and per index, and the USD tuple would ask GBP for four tenors that do not
    exist while missing three that do.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.swap_spreads import swap_spread_history, swap_spread_tenors

    quotes, client = _citivelo_excel_guard()
    try:
        tenors = swap_spread_tenors(_CV_SWAP_SPREAD_INDEX)
        log.info("  %s: %d tenors (%s), %s..%s",
                 _CV_SWAP_SPREAD_INDEX, len(tenors), ", ".join(tenors), start, end)
        frame = swap_spread_history(
            _CV_SWAP_SPREAD_INDEX, tenors, start=start, end=end, quotes=quotes,
        )
        log.info("  served %d/%d tenors; Excel at %.0f MB after",
                 len(frame.columns), len(tenors), client.excel_memory_mb())
        return frame
    finally:
        quotes.close()


def warm_citivelo_frb_values(start, end):
    """Job 9 [VALUE]: FRB values on the citivelo source, into the computed TS cache.

    Requires the bond tag warm. Reads only what Citi serves per bond, so the
    quote-only values (SPREAD_TSY, OAS, ASW) are asked for alongside the ones
    rebuilt locally from PRICE.
    """
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    mdp = FixedRateBondsMDP(source="USTS_CITIVELO-RL")
    tb = TimeseriesBuilder()
    wanted = [UnifiedValue.FRB_YTM, UnifiedValue.FRB_CLEAN_PRICE, UnifiedValue.FRB_SPREAD_TSY]
    queries = [
        UnifiedQuery(cusip=c, value=v) for c in _CV_BOND_ALIASES for v in wanted
    ]
    log.info("  %d queries (%d aliases x %d values)", len(queries), len(_CV_BOND_ALIASES), len(wanted))
    return tb.get_timeseries(
        start=start, end=end, queries=queries, n_jobs=N_JOBS,
        routers={"FRB": FixedRateBondsTB(mdp, show_tqdm=True)},
        ignore_cache_miss=True,
    )


def warm_citivelo_swap_spread_values(start, end):
    """Job 10 [VALUE]: Citi's published swap spreads, into the computed TS cache.

    Requires the swap-spread tag warm. This is Citi's OWN published number, not
    the repo's computed IRS_MMSS / IRS_SPREADOVER — see the value's docstring for
    what each one is a spread between.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.swap_spreads import swap_spread_tenors
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    tenors = swap_spread_tenors(_CV_SWAP_SPREAD_INDEX)
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL-RL")
    tb = TimeseriesBuilder()
    queries = [
        UnifiedQuery(curve="USD-SOFR-1D", tenor=t,
                     value=UnifiedValue.IRS_CITIVELO_SWAP_SPREAD)
        for t in tenors
    ]
    log.info("  %d tenors: %s", len(tenors), ", ".join(tenors))
    return tb.get_timeseries(
        start=start, end=end, queries=queries, n_jobs=N_JOBS,
        routers={"IRS": IRSwapsTB(mdp, show_tqdm=True)},
        ignore_cache_miss=True,
    )


# ─────────────────────────────────────────────────────────────────────
# Job registry
#
# ORDER IS LOAD-BEARING and is now ENFORCED rather than trusted. The comment
# this replaced already said it - "the two store warms come FIRST and in this
# order: the value jobs read the stores, and a date that is not warmed falls
# through to the live Excel path" - which was exactly right and enforced by
# nothing. utils.warm_jobs.check runs at import and raises if a value job
# precedes a store warm it reads, or if two jobs write the same store asset
# (write_day replaces a whole day partition, so a shared key means one silently
# deletes the other's rows and both report success).
#
# Two independent Citi Velocity families live here and do not interact: CURVES
# and the swaption cube, and BONDS and swap spreads. Each declares its own
# assets.
# ─────────────────────────────────────────────────────────────────────

#: Store assets the Velocity CURVE jobs write and read.
_CV_CURVE_STORE = "CITIVELO-CURVESTORE"
_CV_SWAPTION_CUBE = "CITIVELO-SWAPTION-CUBE"

WARM_JOBS = [
    WarmJob("GSQUANT USD-OIS EOD", warm_gsquant_ois_eod),
    WarmJob("ERIS USD-SOFR-1D EOD", warm_eris_eod),
    WarmJob("FRB FedInvest EOD", warm_frb_fedinvest_eod),
    WarmJob("STIRF CME Session", warm_stirf_cme_session),
    WarmJob("UST Futures Invoice Caches", warm_ustf_invoice_caches),
    WarmJob("STIRFO SFR Options EOD", warm_stirfo_eod),

    # -- Citi Velocity STORE warms, all before any value job that reads them --
    WarmJob("CitiVelo CurveStore (intraday + EOD)", warm_citivelo_curve_stores,
            kind=STORE, provides=(_CV_CURVE_STORE,)),
    WarmJob("CitiVelo swaption cube", warm_citivelo_swaption_cube,
            kind=STORE, provides=(_CV_SWAPTION_CUBE,)),
    WarmJob("CITIVELO UST universe tags EOD (store)", warm_citivelo_ust_universe_eod,
            kind=STORE, provides=(_CV_BOND_TAGS,)),
    WarmJob("CITIVELO UST universe tags INTRADAY (store)", warm_citivelo_ust_universe_intraday,
            kind=STORE, provides=(_CV_BOND_TAGS_MI01,)),
    WarmJob("CITIVELO swap-spread tags (store)", warm_citivelo_swap_spread_tags,
            kind=STORE, provides=(_CV_SWAP_SPREAD_TAGS,)),

    # -- then the value jobs that read them --
    WarmJob("CitiVelo EOD timeseries", warm_citivelo_timeseries_eod,
            requires=(_CV_CURVE_STORE,)),
    WarmJob("CitiVelo intraday timeseries", warm_citivelo_timeseries_intraday,
            requires=(_CV_CURVE_STORE,)),
    WarmJob("CITIVELO FRB values EOD", warm_citivelo_frb_values,
            requires=(_CV_BOND_TAGS,)),
    WarmJob("CITIVELO swap spreads EOD", warm_citivelo_swap_spread_values,
            requires=(_CV_SWAP_SPREAD_TAGS,)),
]

check(WARM_JOBS)

#: The ``(name, fn)`` shape the runner below has always consumed. Derived rather
#: than maintained separately, so the two cannot drift.
JOBS = [j.as_tuple() for j in WARM_JOBS]


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def _start_run_log(stamp=None):
    """Attach a per-run file handler and prune old ones. Returns the path.

    Never fatal: a warm that cannot open its log should still warm.
    """
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        stamp = stamp or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(LOG_DIR, f"cache_warmer_{stamp}.log")
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
        )
        # Attached to THIS logger, not to root. ``basicConfig`` is a no-op once
        # root has a handler, so root's level is whatever the first importer left
        # it at - and under pytest the logging plugin owns root outright. Neither
        # is a dependency worth having for the only durable record of the run.
        log.addHandler(handler)
        log.setLevel(logging.INFO)

        existing = sorted(
            f for f in os.listdir(LOG_DIR)
            if f.startswith("cache_warmer_") and f.endswith(".log")
        )
        for stale in existing[:-LOG_RETENTION]:
            try:
                os.remove(os.path.join(LOG_DIR, stale))
            except OSError:
                pass
        return path
    except Exception as exc:  # noqa: BLE001 - logging must not break the warm
        log.warning("could not open a run log under %s (%s)", LOG_DIR, exc)
        return None


def main():
    parser = argparse.ArgumentParser(description="Daily cache warmer for notebook sources")
    parser.add_argument("--date", type=str, help="Specific date (YYYY-MM-DD)")
    parser.add_argument("--backfill", type=int, metavar="N", help="Backfill past N days")
    parser.add_argument("--jobs", type=str, help="Comma-separated job indices (1-based), e.g. '1,3'")
    parser.add_argument("--list", action="store_true", help="List available jobs and exit")
    args = parser.parse_args()

    if args.list:
        print("Available jobs (store warms must precede the value jobs that read them):")
        print(describe(WARM_JOBS))
        return 0

    log_path = _start_run_log()
    if log_path:
        log.info("run log: %s", log_path)

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
        # The import-time check only proves the FULL list is ordered. A subset
        # can still put a value job on the wrong side of its store warm, which
        # is the same failure by a different route -- a live Excel fall-through
        # on an unattended run. Re-check what was actually selected.
        chosen = [WARM_JOBS[i] for i, _ in selected]
        chosen_names = {j.name for j in chosen}
        for job in chosen:
            for asset in job.requires:
                provider = next((p for p in WARM_JOBS if asset in p.provides), None)
                if provider is not None and provider.name not in chosen_names:
                    log.warning(
                        "Job %r requires %r, warmed by %r, which is NOT in --jobs %s. "
                        "It will read an unwarmed cache and fall through to LIVE Excel.",
                        job.name, asset, provider.name, args.jobs,
                    )
        check(chosen)
    else:
        selected = list(enumerate(JOBS))

    # Run jobs
    results = []
    failed = 0
    for idx, (name, fn) in selected:
        log.info("─" * 60)
        log.info("Job %d: %s", idx + 1, name)
        t0 = time.perf_counter()
        before = len(_SUBPROCESS_FAILURES)
        try:
            result = fn(start, end)
            elapsed = time.perf_counter() - t0
            # A job that shells out can return normally having lost a step: every
            # caller of _run discards the code on purpose, so the only evidence
            # is what _run recorded while this job was running.
            lost = _SUBPROCESS_FAILURES[before:]
            if lost:
                detail = ", ".join(f"{label} exited {code}" for label, code in lost)
                status = f"FAILED ({elapsed:.1f}s): {len(lost)} step(s) failed - {detail}"
                failed += 1
                log.error("  %s", status)
            else:
                shape = getattr(result, "shape", None)
                status = f"OK ({elapsed:.1f}s"
                if shape:
                    status += f", {shape[0]} rows x {shape[1]} cols"
                status += ")"
                log.info("  %s", status)
            results.append((name, status))
        except Exception as e:
            elapsed = time.perf_counter() - t0
            results.append((name, f"FAILED ({elapsed:.1f}s): {e}"))
            failed += 1
            log.exception("  FAILED: %s", e)

    # Summary
    log.info("=" * 60)
    log.info("SUMMARY")
    log.info("=" * 60)
    for name, status in results:
        log.info("  %-30s %s", name, status)

    # The exit code is the only thing the Windows scheduler records, so it has to
    # mean something. It used to be 0 unconditionally - every job could fail and
    # the task still read rc=0x00000000, which is how a warm can look healthy for
    # weeks while producing nothing.
    if failed:
        log.error("%d of %d job(s) FAILED", failed, len(results))
        return 1
    log.info("all %d job(s) OK", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())

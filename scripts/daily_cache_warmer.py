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

Exit codes, and why there are three of them
-------------------------------------------
The exit code is the only thing the Windows scheduler records, so it has to
carry a decision:

==  ===========================================================================
0   Everything selected was warmed.
1   At least one job FAILED. A real defect - read the run log, and the child
    output sidecar beside it.
2   Nothing failed, but at least one job - or one STEP inside a job - was
    SKIPPED. Excel was shut, bloated, or signed out; a job's provider did not
    deliver; or a step exited on one of its own declared skip codes because it
    needs a human to act first. Someone opens Excel or runs what the message
    names; there is no bug to find.
==  ===========================================================================

The step-level half of 2 is newer than the job-level half and was added for one
measured case: the EOD CurveStore warm is OFFLINE by construction and can only
build curves as far as the banked DAILY par grid reaches. Nothing on this
schedule advanced that grid, so it reported "EOD warm exited 1" on six of ten
retained nights for an input it does not own. ``scripts/citivelo_daily_par_refresh.py``
now advances it, and when that cannot run the warm says SKIPPED and names the
command instead of failing opaquely.

Two codes were not enough, and the reason is operational rather than tidy. Five
Velocity jobs depend on a human-authenticated Excel whose memory only ever grows
and which only a human restart clears. Over the ten retained runs in
``logs/cache_warmer`` that produced a FAILED line on most nights for a reason
nobody can act on at 18:15 - 2026-08-14, five jobs FAILED in 187.8 s all saying
"Excel is at 6526 MB"; 2026-08-15, no Excel at all, five jobs, 383.2 s. An exit
code that is always 1 is an exit code nobody reads, and that is not a cosmetic
problem: it is how a tag-cache write that persisted nothing and a subprocess
error with no visible cause both survived ten runs unnoticed.

A run with both a failure and a skip exits 1. The failure is the actionable half
and must not be softened by the skips it caused.

What a provider's outcome does to its consumers
-----------------------------------------------
FAILED and SKIPPED do different things to the jobs downstream, and the split is
measured rather than tidy. A provider that FAILED may have written half a store
partition, so its consumers read something that is neither yesterday's day nor
today's - they are skipped. A provider that was SKIPPED because Excel was
unavailable wrote NOTHING: the guard refuses before connecting, and the consumers
read the tag cache, which is CUMULATIVE. On both Excel-down nights those three
consumers ran and succeeded - 2026-08-14: 23.3 s, 790.8 s, 16.0 s; 2026-08-15:
116.5 s, 701.8 s, 653.8 s - about 2,300 s of work that blanket propagation
stopped attempting. So they run, and each records on its own SUMMARY line which
provider was missing while it ran, because the real risk (job 16 builds offline,
so an unbanked tag becomes a hole that looks like a day Citi served nothing) is a
hole nobody can attribute rather than a hole.
"""

import argparse
import datetime
import logging
import os
import re
import subprocess
import sys
import time
from typing import NamedTuple

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
# The old grid could synthesize common packages only when every primitive leg
# happened to be present. In particular it omitted 1Y30Y, so the research fly
# 1Y5Y/1Y10Y/1Y30Y priced from scratch on every day. Keep the non-USD grid
# bounded, but make the USD-SOFR 1Y-forward strip package-complete through 30Y.
_CITIVELO_USD_SOFR_EOD_FORWARDS = tuple(dict.fromkeys((
    *_CITIVELO_EOD_FORWARDS,
    "1y2y", "1y3y", "1y7y", "1y10y", "1y15y", "1y20y", "1y30y",
)))
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


def _citivelo_eod_tenors(curve: str):
    """Canonical EOD primitive/package grid for one warmed Citi curve."""
    forwards = (
        _CITIVELO_USD_SOFR_EOD_FORWARDS
        if str(curve).upper() == "USD-SOFR-1D"
        else _CITIVELO_EOD_FORWARDS
    )
    return (*_CITIVELO_EOD_OUTRIGHTS, *forwards, *_CITIVELO_EOD_SPREADS)


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

    # A per-curve timeout with no run-level budget bounds one child and not the
    # job: three curves at the 3,600 s cap is three hours, inside a warm whose
    # whole nightly span is 2 h 45 m. Measured over the retained runs, this job
    # takes 1,275-1,648 s on a normal single-day night, and the third curve
    # (``...SERFFX-MIX23``) is most of it. The one timeout on record was a
    # FIVE-day catch-up on 2026-08-15, where that curve hit 3,600 s and took the
    # job to 3,842 s.
    #
    # So: keep the per-curve cap where the measurement put it, and add a shared
    # deadline at 5,400 s - 3.3x the worst normal night, enough for a multi-day
    # backfill's first curves, and half the three-hour worst case.
    deadline = time.monotonic() + _STIRF_TOTAL_BUDGET_S
    for curve in curves:
        label = f"stirf_curve_service {curve}"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            # Recorded, not skipped silently: the curve did not warm, and the
            # job must not report OK for the ones it never attempted.
            log.error("  %s: STIRF budget of %.0fs is spent; not started", label,
                      _STIRF_TOTAL_BUDGET_S)
            _SUBPROCESS_FAILURES.append(_StepFailure(
                label, "NOT RUN",
                f"the {_STIRF_TOTAL_BUDGET_S:.0f}s STIRF budget was spent by earlier curves",
            ))
            continue

        cmd = [
            python_exe, script, "backfill",
            "--curve", curve,
            "--start-date", bdates[0].isoformat(),
            "--end-date", bdates[-1].isoformat(),
            "--cme-session",
        ]
        cap = min(_STIRF_CURVE_TIMEOUT_S, remaining)
        try:
            _run(cmd, label, timeout=cap, record=False)
        except subprocess.TimeoutExpired:
            # Caught rather than propagated, so ONE slow curve stops costing the
            # other two. On 2026-08-15 the third curve timed out and the job died
            # with it; the first two had already succeeded, and a fourth would
            # never have been tried. Recorded so the job still reports FAILED -
            # a timeout genuinely lost work, and ``record=False`` above covers a
            # non-zero exit, which has always been treated as a warning here.
            log.error("  %s timed out after %.0fs; continuing with the next curve",
                      label, cap)
            _SUBPROCESS_FAILURES.append(_StepFailure(
                label, "TIMEOUT", f"timed out after {cap:.0f}s (child output in the sidecar)",
            ))

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

        _run(cmd, f"warm_ustf_cache as_of={as_of}", timeout=600, record=False)

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


class _StepFailure(NamedTuple):
    """One non-zero subprocess exit, with the child's own last word attached.

    ``detail`` is the single most informative line the child printed. It is what
    turns ``EOD warm exited 1`` - a message that named no cause and cost this
    warm six undiagnosed nights - into ``EOD warm exited 1: nothing written and
    nothing already present: EUR-ESTR-1D: no banked DAILY rows in ...``.

    ``returncode`` is the child's exit code, or one of the strings ``"TIMEOUT"``
    and ``"NOT RUN"`` for the two ways a step can fail without ever producing
    one. :func:`_describe_step_failure` is what renders it, so the SUMMARY says
    "timed out after 3600s" rather than "exited TIMEOUT".
    """

    label: str
    returncode: object
    detail: str = ""


#: Every non-zero subprocess exit seen this run.
#:
#: A job that shells out is deliberately allowed to continue past a failed step -
#: an intraday fetch that dies still leaves work for the build and EOD phases to
#: do. What was NOT deliberate is that the failure then vanished: every caller of
#: :func:`_run` discards the return code, ``main`` caught nothing, and the process
#: exited 0. Recorded here so the run can end honestly even though the step it
#: lost was survivable.
_SUBPROCESS_FAILURES: list[_StepFailure] = []

#: Every step that exited with one of its own declared SKIP codes this run.
#:
#: Separate from :data:`_SUBPROCESS_FAILURES` because the two need opposite
#: reactions and merging them is what trained the exit code to be ignored. A skip
#: here means "this step did nothing and a HUMAN has to act before it can" - the
#: EOD warm finding the banked DAILY par grid ending before its window is the
#: case this was built for, and it happened on six of ten retained nights while
#: being reported as FAILED. Nobody can fix a stale grid by reading code at
#: 18:15; they can run the refresh.
#:
#: It is still recorded rather than swallowed. A step that quietly does nothing
#: is the "green while stale" shape this warm has now been bitten by twice, so
#: the skip is named in SUMMARY and moves the run's exit code to 2.
_SUBPROCESS_SKIPS: list[_StepFailure] = []

#: How many trailing child lines go into the RUN log on a failure. The full
#: output always goes to the sidecar, so this only has to be big enough to carry
#: the cause - a Python traceback's last frame plus its exception line fits.
CHILD_TAIL_LINES = 15

#: Cap on the one-line ``detail``. Long enough for the Excel memory-guard
#: sentence, short enough to keep the SUMMARY table readable.
_DETAIL_MAX = 300

#: Longest ONE STIRF curve may run. Left where the original measurement put it.
_STIRF_CURVE_TIMEOUT_S = 3600

#: Longest the STIRF job may run across ALL its curves. See
#: :func:`warm_stirf_cme_session` for the measurements behind the number.
_STIRF_TOTAL_BUDGET_S = 5400

#: Where this run's full child output goes. Set by :func:`_start_run_log`.
_CHILD_LOG_PATH: str | None = None

#: A line that looks like the last line of a Python traceback, e.g.
#: ``MDP.CitiVelocityExcel.memory_guard.ExcelTooLargeError: Refusing to start``.
_EXCEPTION_LINE = re.compile(
    r"^[A-Za-z_][\w.]*(?:Error|Exception|Interrupt|SystemExit|Warning)\b"
)


def _describe_step_failure(f):
    """One SUMMARY-ready phrase for a lost step, whatever kind of loss it was.

    ``exited 1`` reads correctly and ``exited TIMEOUT`` does not, and the SUMMARY
    table is the line a human actually reads at 08:00.
    """
    if f.returncode == "TIMEOUT":
        head = f"{f.label} timed out"
    elif f.returncode == "NOT RUN":
        head = f"{f.label} was not run"
    else:
        head = f"{f.label} exited {f.returncode}"
    return head + (f": {f.detail}" if f.detail else "")


def _as_text(raw):
    """Child output as ``str``. ``TimeoutExpired`` hands back bytes on Windows."""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw)


def _tail(text, n=CHILD_TAIL_LINES):
    """The last ``n`` non-blank lines of ``text``."""
    return [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()][-n:]


def _child_raised(err):
    """Whether the child's stderr carries an actual traceback.

    This distinction is not pedantry, and it is the difference between a useful
    log and a second undiagnosable one: every child in this warm imports
    rateslib, whose licence notice and curve-definition banner go to stderr on a
    perfectly HEALTHY run. A "prefer stderr" rule reports ``citivelo_excel curve
    definitions: rateslib +19 (kept 1)...`` as the cause of every failure. The
    real signal on the two commonest failures - ``EOD warm`` and ``vol fetch``
    reporting that they wrote nothing - is on stdout.
    """
    lines = _tail(err, 200)
    return "Traceback (most recent call last)" in (err or "") or (
        bool(lines) and bool(_EXCEPTION_LINE.match(lines[-1]))
    )


def _clip(line):
    return line if len(line) <= _DETAIL_MAX else line[: _DETAIL_MAX - 1].rstrip() + "…"


def _last_meaningful_line(out, err):
    """The one line that best explains why a child failed."""
    err_lines = _tail(err, 200)
    out_lines = _tail(out, 200)
    if _child_raised(err):
        return _clip(err_lines[-1])
    if out_lines:
        return _clip(out_lines[-1])
    return _clip(err_lines[-1]) if err_lines else ""


def _archive_child_output(label, cmd, returncode, out, err):
    """Append one child's FULL output to this run's sidecar file.

    Kept out of the run log on purpose. The run log is the thing a human reads to
    answer "did last night work?", and a warm shells out seven times; pasting
    every child's output into it would bury the summary that makes it useful.
    The sidecar means no failure ever needs a re-run to diagnose.
    """
    if not _CHILD_LOG_PATH:
        return
    try:
        with open(_CHILD_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"\n{'=' * 70}\n{label}  exit={returncode}\n")
            fh.write(f"  {' '.join(cmd)}\n{'=' * 70}\n")
            fh.write("--- stdout ---\n")
            fh.write(out or "(empty)\n")
            fh.write("\n--- stderr ---\n")
            fh.write(err or "(empty)\n")
    except Exception as exc:  # noqa: BLE001 - bookkeeping must not break the warm
        log.warning("  could not archive %s output (%s)", label, exc)


def _run(cmd, label, timeout=None, record=True, skip_codes=()):
    """Run a warm script as a subprocess and report, without killing the run.

    Captures the child's streams rather than letting them inherit the scheduled
    task's console. The task's action carries no redirection, so an inherited
    stream goes nowhere at all - which is why the most frequent failure in this
    warm ("EOD warm exited 1", seven of the ten retained runs) named no cause.

    ``record=False`` archives and reports the child exactly the same way but
    keeps the exit out of :data:`_SUBPROCESS_FAILURES`. Two call sites (the STIRF
    backfill and the UST futures warm) have always treated a non-zero child as a
    warning rather than a job failure; capturing their output is a diagnostic
    change, and changing what counts as a failed job is not one to smuggle in
    alongside it.

    ``skip_codes`` are exit codes THAT CHILD defines as "I did nothing and a
    human has to act first". They go to :data:`_SUBPROCESS_SKIPS` instead of
    :data:`_SUBPROCESS_FAILURES`, so the step is named in SUMMARY and moves the
    run to exit 2 rather than exit 1.

    Per call site, never global. The same integer means different things to
    different children - 3 is "stale par grid, run the refresh" to
    ``citivelo_excel_warm.py`` and "stopped at the Excel memory ceiling" to
    ``citivelo_excel_intraday_warm.py``, and the second of those IS worth a
    red line. A blanket "3 means skip" would silently reclassify it.
    """
    log.info("  %s: %s", label, " ".join(cmd[2:]))
    env = dict(os.environ)
    # The children print em-dashes and box-drawing characters. A captured pipe on
    # Windows defaults to cp1252, so without this the child dies on its own
    # progress message - a failure the capture itself would have created.
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        result = subprocess.run(
            cmd, cwd=REPO_ROOT, env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        # The timeout carries whatever the child managed to say first. Without
        # this it is discarded and the run log records only "timed out after
        # 3600 seconds" - true, and useless.
        t_out = _as_text(exc.stdout)
        t_err = _as_text(exc.stderr)
        _archive_child_output(f"{label} (TIMEOUT)", cmd, "timeout", t_out, t_err)
        for line in _tail(t_out) or _tail(t_err):
            log.warning("    [%s last output] %s", label, line)
        raise
    out = _as_text(getattr(result, "stdout", ""))
    err = _as_text(getattr(result, "stderr", ""))
    _archive_child_output(label, cmd, result.returncode, out, err)
    if result.returncode in tuple(skip_codes) and result.returncode != 0:
        # The child's own last line is the actionable half - it names what a
        # human has to run. Carried into SUMMARY verbatim rather than replaced
        # with a generic "skipped", because "EOD warm exited 1" naming no cause
        # is the failure this whole path exists to stop repeating.
        detail = _last_meaningful_line(out, err)
        log.warning("  %s SKIPPED (not a failure): %s", label, detail)
        _SUBPROCESS_SKIPS.append(_StepFailure(label, result.returncode, detail))
        return result.returncode
    if result.returncode != 0:
        log.warning("  %s exited %d", label, result.returncode)
        for line in _tail(out):
            log.warning("    [stdout] %s", line)
        # stderr only when it carries a traceback (or stdout said nothing at
        # all). Otherwise it is fifteen lines of rateslib licence banner pushing
        # the actual cause off the top of the log.
        if _child_raised(err) or not out.strip():
            for line in _tail(err):
                log.warning("    [stderr] %s", line)
        if _CHILD_LOG_PATH:
            log.warning("    full output: %s", _CHILD_LOG_PATH)
        if record:
            _SUBPROCESS_FAILURES.append(
                _StepFailure(label, result.returncode, _last_meaningful_line(out, err))
            )
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

    # Only THIS step drives Excel. The three below read the banked tag cache and
    # touch nothing live, so an absent or bloated Excel must cost the fetch and
    # nothing else - skipping the whole job on a bad pre-flight would throw away
    # the build and the EOD warm, which are the phases that actually advance the
    # CurveStore. ``citivelo_excel_intraday_warm`` tests the ceiling only inside
    # its fetch loop, at every 20th window, so a short fetch never tests it at
    # all: on 2026-08-11 this step exited 0 having connected to an Excel measured
    # at 3,886 MB one minute later. This is the pre-connect check it lacked.
    blocked = _excel_preflight()
    if blocked:
        log.warning("  intraday fetch SKIPPED (not a failure): %s", blocked)
    else:
        _run([py, "-u", "scripts/citivelo_excel_intraday_warm.py", "fetch",
              "--curves", curves, "--start", min(days).isoformat(), "--end", fetch_end,
              "--recycle-every", "20", "--memory-ceiling-mb", "2500",
              "--memory-abort-mb", "3800"], "intraday fetch")

        # THE DAILY PAR GRID, which nothing on this schedule used to advance.
        #
        # This is the half of the job that was missing, not a tuning change.
        # ``intraday fetch`` above writes MINUTE par rates into
        # ``_intraday_par_cache``; the ``EOD warm`` below reads the DAILY par
        # tags in the ``CitiVeloTagCache``. Two different stores, and only a
        # human running the harvest ever wrote the second one - so the minute
        # store was current to 2026-08-18 on all five curves while the EOD store
        # sat on 2026-08-07, and "EOD warm exited 1" on six of ten nights was
        # simply the warm being asked to build curves from data nobody fetched.
        #
        # Second in the Excel block and inside the same pre-flight, because it is
        # one ``CVTSHIST`` per curve - measured 44/44 tags in 1.4 s against
        # explicit bounds - so it costs seconds next to the intraday fetch's
        # minutes, and it must not run at all when Excel is unusable.
        _run([py, "-u", "scripts/citivelo_daily_par_refresh.py", "refresh",
              "--curves", curves, "--end", max(days).isoformat(),
              "--ceiling-mb", "3000"], "DAILY par refresh", skip_codes=(3,))

    _run([py, "-u", "scripts/citivelo_excel_intraday_warm.py", "build",
          "--curves", curves], "intraday build")

    # EOD runs entirely offline against the banked tag cache - so a stale grid is
    # an INPUT it does not own, and exit 3 says exactly that. It stays a skip
    # rather than a failure whether the refresh above ran and could not reach a
    # curve, or was itself skipped because Excel was shut.
    _run([py, "-u", "scripts/citivelo_excel_warm.py", "warm",
          "--curves", curves, "--start", min(days).isoformat(),
          "--end", max(days).isoformat()], "EOD warm", skip_codes=(3,))

    _run([py, "-u", "scripts/citivelo_excel_intraday_warm.py", "status"], "status")
    return None


def warm_citivelo_swaption_cube(start, end):
    """Job 8: Citi Velocity swaption cube - vol tags, then the cube store.

    ``fetch`` is the Excel phase and carries the same memory ceiling; ``build``
    assembles one cube per observation date from the cached quotes with no Excel
    and no network.
    """
    py = sys.executable
    # As in job 7: ``fetch`` is the only Excel phase, and ``citivelo_swaption_vol_warm``
    # carries no ``assert_safe_to_connect`` of its own. Its bare ``return 0 if done
    # else 1`` is what produced "vol fetch exited 1" on the three nights when a
    # sibling job was simultaneously reporting Excel at 3,886 and 6,526 MB.
    blocked = _excel_preflight()
    if blocked:
        log.warning("  vol fetch SKIPPED (not a failure): %s", blocked)
    else:
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
        for tenor in _citivelo_eod_tenors(curve)
    ]
    log.info("  %d queries (%d curves; USD-SOFR includes the 1Y forward strip through 30Y)",
             len(queries), len(_CITIVELO_CURVES))

    return tb.get_timeseries(
        start=start,
        end=end,
        queries=queries,
        n_jobs=N_JOBS,
        routers={"IRS": IRSwapsTB(mdp, show_tqdm=True)},
        ignore_cache_miss=True,
    )


def warm_citivelo_swaption_timeseries_eod(start, end):
    """Warm durable USD-SOFR swaption values from persisted Citi inputs only.

    The raw cube warm is intentionally separate from this job: a cube is a
    market-data input, while notebooks consume scalar package values. The helper
    intersects CurveStore and CubeStore coverage, enables its COM tripwire, and
    raises if anything tries to fall back to live Excel.
    """
    from scripts.citivelo_swaption_eod_warm import warm_eod_values

    start_date = start.date() if isinstance(start, datetime.datetime) else start
    end_date = end.date() if isinstance(end, datetime.datetime) else end
    return warm_eod_values(start=start_date, end=end_date, n_jobs=N_JOBS)


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


def _excel_unavailable_errors():
    """The exception types that mean "Excel was not usable", not "the warm is broken".

    All three need the same thing from a human - open Excel, sign in to
    Velocity, or restart it - and none of them is a defect in this repo. The
    runner uses this tuple to report SKIPPED rather than FAILED; see
    :func:`_excel_preflight` for why that distinction is worth the code.

    Imported lazily. This module is imported by ``--list`` and by every test
    that touches the runner, and dragging the Velocity bridge in at import time
    to build an ``except`` clause is a cost paid by everything to benefit one
    branch.
    """
    try:
        from MDP.CitiVelocityExcel.errors import AddInNotSignedInError, ExcelNotRunningError
        from MDP.CitiVelocityExcel.memory_guard import ExcelTooLargeError
    except Exception as exc:  # noqa: BLE001 - the non-Velocity jobs must still run
        # An empty tuple is a valid ``except`` clause that matches nothing, so a
        # Velocity bridge that will not import costs the reclassification and
        # nothing else: the eleven jobs that never touch Excel still warm, and
        # the Velocity ones report FAILED, which is exactly right when the
        # bridge itself is broken.
        log.warning("could not load the Velocity error types (%s); an Excel outage "
                    "will be reported as FAILED rather than SKIPPED this run", exc)
        return ()

    return (ExcelTooLargeError, ExcelNotRunningError, AddInNotSignedInError)


def _excel_preflight():
    """Ask ONCE whether the Excel jobs can run. ``None`` means go.

    Every Velocity job used to rediscover the same machine-wide fact
    independently, and the rediscovery is not free. Measured on the retained
    runs: 2026-08-14, Excel at 6,526 MB - five jobs, 187.8 s, and the one
    actionable sentence printed three times verbatim. 2026-08-15, no Excel at
    all - five jobs, 383.2 s. The probe itself is a single ``Get-Process`` and
    the three jobs that fail on it fastest take 0.2-0.3 s end to end, so asking
    once up front costs under a third of a second against a 2 h 45 m run.

    This is additive and **replaces no guard**. Every per-job
    ``assert_safe_to_connect`` stays exactly where it is, for a reason the logs
    settle: on 2026-08-11 jobs 1-6 completed normally and Excel was over the
    ceiling by the time jobs 9-11 ran. The environment degrades mid-run, so a
    pre-flight alone would be a gate that passes and then stops being true.
    What this adds is that the jobs which cannot possibly work are not started,
    and that the answer is written down once instead of five times.

    Returns
    -------
    None
        Excel is present and under the ceiling; the jobs may run.
    str
        Why they may not, phrased as something a human can act on.
    """
    try:
        # INSIDE the try, and that is the whole of finding A. This import sat
        # outside it while :func:`_excel_unavailable_errors` guarded the same
        # bridge and documented the intent - "the eleven jobs that never touch
        # Excel still warm" - so a Velocity bridge that would not import took
        # the WHOLE run down instead of just the Velocity half. Measured:
        # ``main(--jobs 1)`` selects GSQUANT, which never touches Excel, and
        # raised ModuleNotFoundError before job 1 started.
        #
        # It returns a BLOCKING string rather than ``None``. A probe that cannot
        # be loaded says nothing about what is running, and what might be
        # running is the 13,884 MB add-in measured on 2026-08-08 - so the Excel
        # jobs are refused and the other eleven proceed. Failing open here would
        # be the same mistake as treating an unreadable reading as "no Excel".
        from MDP.CitiVelocityExcel.memory_guard import excel_memory_mb
    except Exception as exc:  # noqa: BLE001 - the non-Velocity jobs must still run
        return (
            f"the Velocity memory probe will not import ({exc}); no Velocity job "
            "can be allowed to connect until that is fixed. Jobs that never touch "
            "Excel are unaffected"
        )

    try:
        mb = excel_memory_mb()
    except Exception as exc:  # noqa: BLE001 - a broken probe must not end the run
        return f"could not probe Excel's memory ({exc}); fix the probe"

    # Three outcomes, three different human actions - and collapsing any two of
    # them is what made the old log unreadable. ``None`` is NOT "no Excel": see
    # memory_guard's docstring, it means the probe could not be read at all, and
    # what might be running is a 13 GB add-in.
    if mb is None:
        return (
            "could not read Excel's memory (the probe timed out, PowerShell was "
            "unavailable, or its output was unparseable) - fix the probe; until "
            "then no Velocity job can be allowed to connect"
        )
    if mb <= 0.0:
        return (
            "no Excel is running, so no Velocity job can work. The bridge attaches "
            "to a human-authenticated Excel and never spawns one, because a spawned "
            "instance never registers the CV* UDFs"
        )
    if mb >= _CV_MEMORY_CEILING_MB:
        return (
            f"Excel is at {mb:.0f} MB, at or above the {_CV_MEMORY_CEILING_MB:.0f} MB "
            "ceiling. Only a human restart shrinks it - the add-in's memory only ever "
            "grows, and it wedged at 5,249 MB on 2026-08-07"
        )
    log.info("Excel pre-flight: %.0f MB, under the %.0f MB ceiling - Velocity jobs may run",
             mb, _CV_MEMORY_CEILING_MB)
    return None


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
    _raise_on_coverage_regression(out, "EOD")
    return None


#: A coverage regression has to reach the SCHEDULER, not just the CLI.
#:
#: ``citivelo_ust_universe_warm.main`` exits 1 on ``regressed``, but the nightly
#: does not go through ``main`` - it calls ``warm()`` and, until this existed,
#: read only ``stopped``. So a bond that fell silent since the last run returned
#: ``None`` here, printed OK, and the run exited 0. That is defect 2's own shape
#: one layer up: a warm that cannot fail on coverage grounds cannot be trusted to
#: report coverage.
#:
#: Only the CHANGE escalates, never the LEVEL - deliberately, and for the reason
#: the CLI already documents: ten value families have been dead since 2025-10-03
#: and 2025-11-28, so escalating the level would exit non-zero every night for a
#: condition nobody can act on, which is precisely the always-failing exit code
#: this warmer's docstring says trains an operator to stop reading exit codes.
#: The level goes to the log and to ``status``.
def _raise_on_coverage_regression(out, label):
    regressed = out.get("regressed") or {}
    if not regressed:
        return
    shown = ", ".join(
        f"{isin}: {', '.join(vals)}" for isin, vals in sorted(regressed.items())[:5]
    )
    more = f" and {len(regressed) - 5} more" if len(regressed) > 5 else ""
    raise RuntimeError(
        f"UST universe {label} warm: {len(regressed)} bond(s) newly stopped updating "
        f"since the last run ({shown}{more}). The warm itself completed - this is a "
        f"coverage regression, not a partial run, so re-running will not clear it."
    )


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
    _raise_on_coverage_regression(out, "intraday")
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


def warm_citivelo_ust_timeseries(start, end):
    """Job 11 [VALUE]: the UST constant-maturity grid + every listed issue, EOD.

    The daily SLICE of ``scripts/citivelo_ust_timeseries_warm.py``. The ten-year
    backfill is a separate, deliberate one-off:

        python scripts/citivelo_ust_timeseries_warm.py fetch --years 10
        python scripts/citivelo_ust_timeseries_warm.py build --years 10

    Only the BUILD phase runs here, and that is the point of the split. Build
    drives no Excel at all - the MDP is constructed ``offline=True``, so a tag
    the cache does not hold produces an empty column instead of a workbook. The
    tags themselves come from job "CITIVELO UST universe tags EOD", which is why
    this declares ``requires``: run the other way round and an unattended job
    reaches for a live add-in whose memory only a human restart clears.

    Measured 2026-08-08 on this machine, offline, against the warmed tag cache:
    **377 symbols (28 aliases + 349 issues) x 2 values over 6 business days =
    4,488 computed cells in 372 s**, so the default five-day window is about five
    minutes. Widen with ``CITIVELO_UST_TS_DAYS``; drop the specific issues with
    ``CITIVELO_UST_TS_CUSIPS=none`` if that is ever too much.

    That cost does NOT scale with the catalog, and the reason is worth knowing.
    The catalog has since grown to 877 USA.USD.GOVT ISINs by absorbing the
    matured bonds, but a symbol is only priced over its own life clipped to the
    window - so a five-day window produces 380 (symbol, year) slices out of 905
    candidates, the other 525 being bonds that redeemed years ago. A nightly job
    that priced every catalogued name over the requested window regardless would
    have doubled overnight without anyone touching this file.

    A rolling window rather than the full history, for the same reason as the tag
    warm: the resume key includes the window, so a nightly run whose start moves
    every night would look entirely un-warm and re-price a decade. The manifest
    lives beside the tag cache, NOT in the repo - this runs from the primary
    checkout and must not leave a tracked file dirty every morning.

    Overlaps job "CITIVELO FRB values EOD" on 14 aliases x 2 values. That is
    waste, not damage: both jobs compute the same numbers from the same tag cache
    into the same ``(symbol, date)`` keys, and ``append_many_rows`` upserts rather
    than replacing a partition. Folding the older job into this one is the
    obvious follow-up; it is left alone here so this change adds coverage without
    altering what already runs.
    """
    from scripts.citivelo_ust_timeseries_warm import (
        DEFAULT_BUILD_VALUES,
        DEFAULT_VALUES,
        WarmPlan,
        _parse_cusips,
        build,
        default_aliases,
    )

    days = int(os.environ.get("CITIVELO_UST_TS_DAYS", "5"))
    cusips_env = os.environ.get("CITIVELO_UST_TS_CUSIPS")
    values_env = os.environ.get("CITIVELO_UST_TS_BUILD_VALUES")
    plan = WarmPlan(
        start=end - datetime.timedelta(days=days),
        end=end,
        aliases=default_aliases(),
        cusips=_parse_cusips([cusips_env] if cusips_env else None),
        values=DEFAULT_VALUES,
        # TEN values, matching what the ten-year backfill wrote. Derived from the
        # fetch set this built two of them, and the other eight would have gone
        # stale from the day the backfill finished - invisibly, because a series
        # that stops updating looks exactly like one with nothing new to say.
        build_values=(
            tuple(v.strip() for v in values_env.split(",") if v.strip())
            if values_env else DEFAULT_BUILD_VALUES
        ),
    )
    log.info("  %s", plan.describe().replace("\n", "\n  "))
    out = build(plan, n_jobs=N_JOBS)
    if out.get("stopped"):
        raise RuntimeError(
            f"UST timeseries build stopped after {out['done']}/{out['of']} slices: "
            f"{out['reason']}. Progress is in the manifest; re-run to continue."
        )
    return None


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
    # needs_excel on these three and not on the two above: jobs 7 and 8 drive
    # Excel in one step out of four and do real offline work in the rest, so they
    # probe around their own fetch step. These three are Excel end to end - with
    # no Excel they take 50-102 s each to arrive at a foregone conclusion, and
    # with Excel over the ceiling they take 0.2 s to print the same sentence a
    # third time.
    WarmJob("CITIVELO UST universe tags EOD (store)", warm_citivelo_ust_universe_eod,
            kind=STORE, provides=(_CV_BOND_TAGS,), needs_excel=True),
    WarmJob("CITIVELO UST universe tags INTRADAY (store)", warm_citivelo_ust_universe_intraday,
            kind=STORE, provides=(_CV_BOND_TAGS_MI01,), needs_excel=True),
    WarmJob("CITIVELO swap-spread tags (store)", warm_citivelo_swap_spread_tags,
            kind=STORE, provides=(_CV_SWAP_SPREAD_TAGS,), needs_excel=True),

    # -- then the value jobs that read them --
    WarmJob("CitiVelo EOD timeseries", warm_citivelo_timeseries_eod,
            requires=(_CV_CURVE_STORE,)),
    WarmJob("CitiVelo swaption values EOD", warm_citivelo_swaption_timeseries_eod,
            requires=(_CV_CURVE_STORE, _CV_SWAPTION_CUBE)),
    WarmJob("CitiVelo intraday timeseries", warm_citivelo_timeseries_intraday,
            requires=(_CV_CURVE_STORE,)),
    WarmJob("CITIVELO FRB values EOD", warm_citivelo_frb_values,
            requires=(_CV_BOND_TAGS,)),
    # Same requirement, and it is the load-bearing one: this job builds OFFLINE,
    # so a tag the EOD universe warm has not banked comes back as an empty column
    # rather than as a live Excel call. Silent, and it would populate the computed
    # store with holes that look like days Citi served nothing.
    WarmJob("CITIVELO UST timeseries values EOD", warm_citivelo_ust_timeseries,
            requires=(_CV_BOND_TAGS,)),
    WarmJob("CITIVELO swap spreads EOD", warm_citivelo_swap_spread_values,
            requires=(_CV_SWAP_SPREAD_TAGS,)),
]

check(WARM_JOBS)

# There is deliberately no ``JOBS = [(name, fn), ...]`` projection any more. The
# runner needs each job's ``requires``/``provides``/``needs_excel`` to decide
# SKIPPED from FAILED, which a ``(name, fn)`` pair cannot carry - and a module
# that exports both invites a caller (a test, most dangerously) to substitute the
# one the runner no longer reads. Removing it turns that mistake into an
# immediate ``AttributeError`` instead of a run against the seventeen REAL jobs,
# five of which drive the user's Excel.


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def _start_run_log(stamp=None):
    """Attach a per-run file handler and prune old ones. Returns the path.

    Never fatal: a warm that cannot open its log should still warm.
    """
    global _CHILD_LOG_PATH
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        stamp = stamp or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(LOG_DIR, f"cache_warmer_{stamp}.log")
        # Deliberately NOT ``*.log``: the prune below globs that, and a sidecar
        # counted as a run would halve the retention and split the pairs.
        _CHILD_LOG_PATH = os.path.join(LOG_DIR, f"cache_warmer_{stamp}.children.txt")
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
            for victim in (stale, stale[:-len(".log")] + ".children.txt"):
                try:
                    os.remove(os.path.join(LOG_DIR, victim))
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
        selected = [(i, WARM_JOBS[i]) for i in indices if 0 <= i < len(WARM_JOBS)]
        # The import-time check only proves the FULL list is ordered. A subset
        # can still put a value job on the wrong side of its store warm, which
        # is the same failure by a different route -- a live Excel fall-through
        # on an unattended run. Re-check what was actually selected.
        chosen = [job for _, job in selected]
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
        selected = list(enumerate(WARM_JOBS))

    # One probe, before anything runs, for the fact five jobs used to rediscover
    # independently. ``None`` means the Velocity jobs may run.
    #
    # Not asked at all when nothing selected needs Excel. The probe shells out to
    # PowerShell against the live EXCEL.EXE, and ``--jobs 1`` (GSQUANT, offline)
    # has no business paying for that - nor for anything the Velocity bridge does
    # on the way. Jobs 7 and 8 call this themselves around their own fetch step,
    # so a selection containing them still gets the probe, once, where it matters.
    needs_probe = any(job.needs_excel for _, job in selected)
    excel_blocked = _excel_preflight() if needs_probe else None
    excel_errors = _excel_unavailable_errors()

    # Run jobs
    results = []
    failed = skipped = 0
    #: asset key -> ``(blocking, why)``. Populated when a STORE job fails OR is
    #: skipped, and read by every job that declares it in ``requires``. This is
    #: the runtime half of the dependency contract: ``assert_ordered`` proves the
    #: LIST is ordered, which it did correctly and uselessly while the swaption
    #: value job ran anyway against a CurveStore whose warm had exited 1 four
    #: minutes earlier and reported "No common CurveStore/CubeStore EOD dates" as
    #: though it were its own bug.
    #:
    #: ``blocking`` is the distinction this pair exists for, and it is measured
    #: rather than tidy. A provider that FAILED may have written half a store, so
    #: its consumers are reading something that is neither the old day nor the
    #: new one - they must not run. A provider that was SKIPPED because Excel was
    #: unavailable wrote NOTHING, and its consumers read the tag cache, which is
    #: CUMULATIVE: they run against tags banked on earlier nights. That is not a
    #: theory. On both Excel-down nights the three consumers ran and succeeded:
    #:
    #:   2026-08-14 (Excel at 6,526 MB)  FRB values 23.3 s, UST timeseries
    #:                                   790.8 s, swap spreads 16.0 s
    #:   2026-08-15 (no Excel at all)    116.5 s, 701.8 s, 653.8 s
    #:
    #: ~2,300 s of demonstrably successful work, which blanket propagation stopped
    #: attempting. Job "CITIVELO UST timeseries values EOD" carries the real
    #: counter-argument - it builds OFFLINE, so a tag its provider did not bank
    #: comes back as an empty column and writes a HOLE that looks like a day Citi
    #: served nothing. That is honoured by recording the provenance on the
    #: consumer's own result, not by refusing to run it: a hole nobody can
    #: attribute is the problem, and the run still exits 2 because the provider's
    #: own skip is still counted.
    unmet = {}

    def _skip(job, status, *, blocking=True):
        """Record a job that was not run, and disown whatever it provides.

        ``blocking=False`` is for a skip that means "this warm did not happen",
        as opposed to "this warm happened and went wrong": nothing was written,
        so a consumer reading the banked cache is in a defined state. See the
        note on ``unmet``.
        """
        nonlocal skipped
        skipped += 1
        for asset in job.provides:
            unmet.setdefault(asset, (blocking, f"{job.name!r} was skipped"))
        log.warning("  %s", status)
        results.append((job.name, status))

    for idx, job in selected:
        log.info("─" * 60)
        log.info("Job %d: %s", idx + 1, job.name)

        blocked_on = next((a for a in job.requires if unmet.get(a, (False,))[0]), None)
        if blocked_on is not None:
            _skip(job, f"SKIPPED: needs {blocked_on!r}, but {unmet[blocked_on][1]}")
            continue

        if job.needs_excel and excel_blocked:
            # NOT blocking. An Excel that is shut, bloated or signed out stopped
            # this warm from happening; it did not corrupt anything, and the
            # consumers read a cumulative cache.
            _skip(job, f"SKIPPED: {excel_blocked}", blocking=False)
            continue

        # Provenance, carried onto this job's own result line. A consumer that
        # ran without its provider produced attributable output or it produced
        # an unattributable hole, and the difference is one string in SUMMARY.
        degraded = [a for a in job.requires if a in unmet]
        provenance = ""
        if degraded:
            provenance = " [ran without " + ", ".join(
                f"{a} ({unmet[a][1]})" for a in degraded
            ) + "]"
            log.warning(
                "  running against %s, which was NOT warmed this run (%s). The "
                "banked tags are cumulative, so this is expected to work - but "
                "anything they do not cover becomes a hole in the computed store.",
                " and ".join(repr(a) for a in degraded),
                "; ".join(unmet[a][1] for a in degraded),
            )

        t0 = time.perf_counter()
        before = len(_SUBPROCESS_FAILURES)
        before_skips = len(_SUBPROCESS_SKIPS)
        try:
            result = job.fn(start, end)
            elapsed = time.perf_counter() - t0
            # A job that shells out can return normally having lost a step: every
            # caller of _run discards the code on purpose, so the only evidence
            # is what _run recorded while this job was running.
            lost = _SUBPROCESS_FAILURES[before:]
            # Steps that exited on one of their own declared skip codes. Counted
            # and named separately: a failure means "read the log, something is
            # broken", a skip means "run the thing the message names".
            waived = _SUBPROCESS_SKIPS[before_skips:]
            if lost:
                detail = ", ".join(_describe_step_failure(f) for f in lost)
                status = f"FAILED ({elapsed:.1f}s): {len(lost)} step(s) failed - {detail}"
                failed += 1
                for asset in job.provides:
                    unmet.setdefault(asset, (True, f"{job.name!r} failed"))
                log.error("  %s", status)
            else:
                shape = getattr(result, "shape", None)
                status = f"OK ({elapsed:.1f}s"
                if shape:
                    status += f", {shape[0]} rows x {shape[1]} cols"
                status += ")"
                log.info("  %s", status)
            if waived:
                # Appended to whatever the job's own status is, so a job that did
                # four things and skipped the fifth reads as exactly that. The
                # run-level ``skipped`` counter moves too, which is what makes
                # the process exit 2 instead of 0 - the documented meaning of 2
                # is "nothing failed, but something did not happen", and a stale
                # par grid awaiting a human is precisely that.
                detail = "; ".join(f"{s.label}: {s.detail}" for s in waived)
                status += f" [{len(waived)} step(s) SKIPPED - {detail}]"
                skipped += 1
                log.warning("  %d step(s) SKIPPED in %s - %s", len(waived), job.name, detail)
            results.append((job.name, status + provenance))
        except excel_errors as e:
            # Not a failure of this warm. Excel was absent, unreadable, over the
            # ceiling, or signed out - four states with one property in common:
            # nobody can act on them at 18:15, and none of them is a defect here.
            # Reporting them as FAILED every night is what trained the exit code
            # to be ignored, which is how the two REAL bugs (a cache write that
            # persisted nothing, a subprocess error nobody could see) survived
            # ten runs unnoticed. The GUARD still refuses to connect; only the
            # word for the outcome has changed.
            #
            # Non-blocking for the same reason as the pre-flight skip above: the
            # guard refused BEFORE connecting, so nothing was written.
            elapsed = time.perf_counter() - t0
            _skip(job, f"SKIPPED ({elapsed:.1f}s): {e}{provenance}", blocking=False)
        except Exception as e:
            elapsed = time.perf_counter() - t0
            results.append((job.name, f"FAILED ({elapsed:.1f}s): {e}{provenance}"))
            failed += 1
            for asset in job.provides:
                unmet.setdefault(asset, (True, f"{job.name!r} failed"))
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
    #
    # Three codes rather than two, because "something is broken" and "the machine
    # was not in a state to warm" need different people to do different things,
    # and a code that means both means neither:
    #
    #   0  everything asked for was warmed.
    #   1  at least one job FAILED - a real defect, worth reading the log for.
    #   2  nothing failed, but something was SKIPPED - Excel was shut, bloated or
    #      signed out. Someone opens Excel; there is no bug to find.
    #
    # A dependency skip only ever follows a failure, so a night with both is a 1:
    # the failure is the actionable half and must not be softened by the skips it
    # caused.
    if failed:
        log.error("%d of %d job(s) FAILED, %d SKIPPED", failed, len(results), skipped)
        return 1
    if skipped:
        log.warning(
            "%d of %d job(s) SKIPPED, none failed - the warm did not run everything, "
            "but nothing here is broken", skipped, len(results),
        )
        return 2
    log.info("all %d job(s) OK", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())

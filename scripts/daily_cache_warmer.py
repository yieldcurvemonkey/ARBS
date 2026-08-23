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
import faulthandler
import logging
import os
import re
import subprocess
import sys
import threading
import time
from typing import NamedTuple

# THE SUPABASE L2 SWITCH, AND IT HAS TO BE HERE - above every other import in
# this file and before anything under ``Caching`` is reachable.
#
# ``Caching.supabase_engine`` reads the flag ONCE, at import, into a module
# global (``SUPABASE_ENABLED = _env_enabled("ARBS_SUPABASE_ENABLED", True)``),
# so a setting applied after the first import of that package is inert. Every
# Citi script in this repo already opens with this exact line for that reason.
#
# The default is ENABLED, and the credentials are not an env var anybody forgot
# to set - they are hard-coded module constants pointing at the production
# pooler (``supabase_engine.DEFAULT_DB_HOST/USER/PASSWORD``). Neither scheduled
# task sets the flag. So the unattended nightly has been opening connections to
# prod and pushing a whole-day Parquet blob per computed symbol, on background
# threads nobody waits for or reads the result of, all night, every night.
#
# ``setdefault`` rather than an assignment: a human who exports
# ``ARBS_SUPABASE_ENABLED=1`` deliberately - to refresh what the laptop pulls -
# still gets it.
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

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

#: Whether the FedInvest warm covers the whole off-the-run curve or only the 28
#: constant-maturity ranks. Set to 0 to go back to the old behaviour.
_FRB_FULL_UNIVERSE = os.environ.get("ARBS_WARM_FRB_UNIVERSE", "full").strip().lower() != "ranks"

#: How much of the requested symbol set must actually price before the day is
#: believed. See :func:`warm_frb_fedinvest_eod` for the measurement.
_FRB_MIN_COVERAGE = float(os.environ.get("ARBS_WARM_FRB_MIN_COVERAGE", "0.60"))


def _frb_universe_symbols(as_of):
    """Every nominal UST alive on ``as_of``, addressed by its MATURITY alias.

    The 28 constant-maturity ranks come along unchanged; what this adds is the
    rest of the curve - 349 bonds on 2026-08-21 against the 28 the warm used to
    price, and the other 321 are the off-the-runs a relative-value book actually
    trades.

    WHY MMYY-oi RATHER THAN THE CUSIP, and why not the bare MMYY
    ------------------------------------------------------------
    The computed-timeseries symbol is a sha1 of the cusip token AS TYPED
    (``TB/FixedRateBondsTB.py::_ts_symbol_for_query``), not of the CUSIP it
    resolves to. So the token chosen here IS the series key, permanently:

    * ``CT10`` is one series whose underlying bond changes every quarter. That
      is right for a constant-maturity study and wrong for everything else.
    * ``912810SP4`` names one bond forever but is unreadable and is not what
      anybody types.
    * ``0850`` - the alias grammar this repo already speaks, and already emits
      from the SDR trade tape (``tape_label_ust_alias``) and accepts in the
      IRSwaps adapter - names the bond maturing August 2050. One bond, one
      series, in the tokens the notebooks use.

    The ``-oi`` suffix is not decoration and the bare form is not a synonym. A
    bare ``MMYY`` means "the bond maturing that month" and stays unambiguous
    only until Treasury issues a second one. Measured on this machine's own
    reference data: ``0245`` resolved to the 30y ``912810RK6`` as-of 2020, 2022
    AND 2024, then became ambiguous in 2026 once the 20y ``912810UJ5`` maturing
    02/2045 existed. ``0245-30`` is ``912810RK6`` throughout and ``0245-20`` is
    the 20y. So the DURABLE key is always ``MMYY-oi``, and every bond gets one.

    The bare form is emitted TOO, but only where it is currently unambiguous
    (76 of the 170 distinct MMYY keys on 2026-08-21). That is not redundancy for
    its own sake: a human types ``0850``, and a query token that was not warmed
    under that exact spelling misses the cache and reprices. It costs one extra
    row per bond per day. If such a key later becomes ambiguous it simply stops
    being emitted - the oi-qualified series carries on, and the bare one has a
    visible end rather than a silent change of meaning.

    COVERAGE, measured on the cached reference frame
    ------------------------------------------------
    349 live rows on 2026-08-21 -> 170 distinct MMYY keys, 76 unambiguous,
    94 ambiguous splitting into 273 oi-buckets, and ZERO buckets still holding
    more than one CUSIP. 76 + 273 = 349, i.e. ``MMYY-oi`` addresses the entire
    live universe uniquely. The frame is nominal coupon Notes and Bonds only -
    fiscaldata excludes TIPS, bills and FRNs server-side - so nothing here has
    to filter them out.

    WHAT IT COSTS: essentially nothing, and that is the point.
    FedInvest is a WHOLE-FILE DAILY download - the POST carries only the price
    date, no CUSIP list - and the fetch cache is keyed by DATE ALONE. Widening
    the symbol set therefore adds ZERO fetches; 4,182 days are already banked
    locally (2006-01-31..2026-08-21) and the day's table already holds 352
    nominal coupon rows, covering all 349. The marginal cost is CPU: 1.39 ms per
    pricer construct + ytm, i.e. about +0.45 s per date for 28 -> 349 symbols.
    """
    from MDP.FixedRateBonds.FixedRateBondsMDP import _filter_and_rank_ref_df
    from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import (
        update_reference_data,
    )

    ref = _filter_and_rank_ref_df(update_reference_data(source="fiscaldata"), as_of)

    import pandas as pd

    mats = pd.to_datetime(ref["maturity_date"], errors="coerce")
    keys = mats.dt.strftime("%m%y")

    def _oi_num(value):
        m = re.search(r"(\d+)", str(value))
        return m.group(1) if m else str(value).strip()

    ois = ref["oi"].map(_oi_num)

    symbols = list(_FRB_CUSIPS)
    seen = set(symbols)
    per_key = {}
    for key, oi in zip(keys, ois):
        if not isinstance(key, str) or not key:
            continue
        per_key.setdefault(key, set()).add(oi)

    for key, buckets in sorted(per_key.items()):
        for oi in sorted(buckets):
            token = f"{key}-{oi}"
            if token not in seen:
                seen.add(token)
                symbols.append(token)
        # The bare spelling only while it still names one bond. See above.
        if len(buckets) == 1 and key not in seen:
            seen.add(key)
            symbols.append(key)

    return tuple(symbols)

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

# ── The Citi Velocity swap grid ──────────────────────────────────────
#
# SPELLING IS PART OF THE GRID and is deliberately left ALONE.
#
# The computed-timeseries symbol is a sha1 of the tenor string AS TYPED
# (``TB/IRSwapsTB._query_fingerprint``). '5y5y', '5yx5y' and '5Y5Y' price
# identically and hash to three DIFFERENT series. So the spelling a warm uses is
# that series' permanent identity, and changing it does not migrate the history -
# it orphans it and starts a new series beside it. Every tenor added below
# therefore follows the convention already in the file (UPPERCASE spot
# outrights, lowercase concatenated forwards, lowercase packages) rather than
# imposing a tidier one.
#
# Worth knowing while reading this, because it looks like it should matter and
# does not: ``IRSwapsTB`` carries a cache-synthesis shortcut that builds a
# cached 'a/b/c' out of cached outright legs, and it looks legs up by the
# VERBATIM substring of the package tenor - so a package spelled '2y/10y' asks
# for legs '2y' and '10y' while this grid banks '2Y' and '10Y'. That mismatch
# costs nothing, because the branch is UNREACHABLE anyway: its guard skips any
# query carrying ``structure_kwargs['notional']`` and ``IRSwapQuery`` populates
# that with 1,000,000 on every query ever constructed. Verified rather than
# taken from the comment that says so - both a direct ``IRSwapQuery`` and one
# built through ``UnifiedQuery`` come back with ``notional=1000000``. Packages
# price off the curve, which is cheap; see the measurement on the intraday block.
#
# Capped at 30Y: Citi serves out to 50Y but the long end is thin in the non-USD
# currencies, and the EOD warm already accepts days with as few as 20 of 44
# tenors.

#: Spot outrights. UPPERCASE, as they have always been banked.
_CITIVELO_EOD_OUTRIGHTS = (
    "1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y", "12Y", "15Y", "20Y", "25Y", "30Y",
)

#: Forward-start outrights for the four non-USD curves. Bounded deliberately -
#: these curves are thinner and nobody reads a 20y10y ESTR intraday.
_CITIVELO_EOD_FORWARDS = (
    "1y1y", "1y5y", "1y10y", "2y5y", "5y5y", "5y10y", "10y10y",
)

#: USD-SOFR gets the full forward surface an RV book works in: the 1y strip
#: through 30y, the 2y/3y/5y strips, and the long forwards. Every one of these
#: is a leg of at least one package below, and the closure check enforces the
#: converse.
_CITIVELO_USD_SOFR_EOD_FORWARDS = tuple(dict.fromkeys((
    *_CITIVELO_EOD_FORWARDS,
    # front strip -- what a front-end RV book reads off the meeting grid
    "3m3m", "3m6m", "6m3m", "6m6m", "9m3m", "1y3m", "1y6m",
    # 1y-forward strip, package-complete through 30y
    "1y2y", "1y3y", "1y4y", "1y7y", "1y15y", "1y20y", "1y30y",
    # 2y and 3y forward strips
    "2y1y", "2y2y", "2y3y", "2y7y", "2y10y", "2y20y",
    "3y2y", "3y5y", "3y7y",
    # long forwards
    "5y15y", "5y20y", "5y25y", "10y20y", "15y15y", "20y10y", "30y10y",
)))

#: SPOT curves and flies. Legs must appear in ``_CITIVELO_EOD_OUTRIGHTS``.
_CITIVELO_EOD_SPREADS = (
    # curves
    "2y/5y", "2y/10y", "2y/30y", "3y/7y", "5y/10y", "5y/30y", "7y/10y",
    "10y/20y", "10y/30y", "20y/30y",
    # flies
    "1y/2y/3y", "2y/3y/5y", "2y/5y/10y", "3y/5y/7y", "5y/7y/10y",
    "5y/10y/30y", "2y/10y/30y", "10y/20y/30y", "5y/10y/20y",
)

#: FORWARD curves and flies - the ones this repo's own research code types, plus
#: the standard rolldown structures. Legs must appear in the USD forward tuple.
#:
#: These are USD-SOFR only. A forward fly on a curve whose 20y is a single thin
#: quote is a number with no market behind it, and the non-USD EOD warm already
#: tolerates days serving less than half its tenors.
_CITIVELO_USD_SOFR_EOD_FWD_PACKAGES = (
    # forward curves
    "1y1y/2y1y", "2y1y/3y2y", "1y2y/1y5y", "1y5y/1y10y", "1y10y/1y30y",
    "2y2y/5y5y", "5y5y/10y10y", "10y10y/20y10y", "5y5y/5y25y",
    "3m3m/6m3m", "6m3m/9m3m", "1y1y/1y5y",
    # forward flies
    "1y2y/1y5y/1y10y", "1y5y/1y10y/1y30y", "1y1y/2y1y/3y2y",
    "2y2y/5y5y/10y10y", "5y5y/10y10y/20y10y", "3m3m/6m3m/9m3m",
    "1y1y/1y5y/1y10y", "2y5y/5y5y/10y10y",
)


def _assert_packages_are_closed():
    """Refuse a package whose legs are not themselves warmed series.

    NOT for the synthesis shortcut - that branch is unreachable, see the grid
    header. This is a COVERAGE property, and it is the one a reader of these
    numbers actually needs: a fly is only interpretable next to its legs. A grid
    warming ``1y5y/1y10y/1y30y`` but not ``1y30y`` hands a PM a spread they
    cannot decompose, and nothing about the missing leg is visible from the
    frame - it is simply a column nobody asked for.

    Same discipline as
    ``scripts/citivelo_intraday_ts_warm._assert_universe_is_closed``, and run at
    import for the same reason: a grid edit is a one-line change that otherwise
    fails silently.
    """
    problems = []
    for label, legs_pool, packages in (
        ("non-USD", set(_CITIVELO_EOD_OUTRIGHTS) | set(_CITIVELO_EOD_FORWARDS),
         _CITIVELO_EOD_SPREADS),
        ("USD-SOFR", set(_CITIVELO_EOD_OUTRIGHTS) | set(_CITIVELO_USD_SOFR_EOD_FORWARDS),
         _CITIVELO_EOD_SPREADS + _CITIVELO_USD_SOFR_EOD_FWD_PACKAGES),
        ("intraday", set(_CITIVELO_INTRADAY_OUTRIGHTS), _CITIVELO_INTRADAY_PACKAGES),
    ):
        # Case-insensitive ON PURPOSE. Spot outrights are banked UPPERCASE and
        # package legs are written lowercase; both spellings are history that
        # must not be renamed, and the two name the same swap.
        pool = {leg.upper() for leg in legs_pool}
        for package in packages:
            missing = [leg for leg in package.split("/") if leg.upper() not in pool]
            if missing:
                problems.append(f"  {label}: {package!r} needs unwarmed leg(s) {missing}")
    if problems:
        raise AssertionError(
            "Citi warm grid is not package-closed - these packages name a leg the "
            "warm does not price as a series of its own:\n" + "\n".join(problems)
        )


# Intraday is deliberately a SUBSET of EOD. The minute store holds ~1,100 points
# per curve per day and the nightly prices a 15-minute stride, so every tenor
# here is 61 pricings per curve per day rather than one.
#
# It is no longer six. Measured on 2026-08-21 against the warmed minute store,
# one tenor over five stamps costs 0.02-0.57 s and triggers ZERO curve builds -
# curve acquisition is amortised across every tenor at the same instant
# (``IRSwapsTB`` calls ``bulk_get_data`` once per curve for all missing points,
# then re-uses the object), so tenors are close to free and timestamps are not.
# That is the opposite of the assumption the old six-tenor comment encoded.
_CITIVELO_INTRADAY_OUTRIGHTS = (
    "2Y", "5Y", "10Y", "30Y", "1y1y", "2y1y", "1y5y", "5y5y", "10y10y",
)
_CITIVELO_INTRADAY_PACKAGES = (
    "2y/10y", "5y/10y", "5y/10y/30y", "2y/5y/10y",
    "1y1y/2y1y", "5y5y/10y10y",
)
_CITIVELO_INTRADAY_TENORS = (*_CITIVELO_INTRADAY_OUTRIGHTS, *_CITIVELO_INTRADAY_PACKAGES)
_CITIVELO_INTRADAY_FREQ = "15min"

_assert_packages_are_closed()

# USD-OIS uses the same outrights + a subset of forwards (max 30Y)
#: The USD curves warmed from GS Quant: SOFR and Fed Funds OIS, at BOTH clearing
#: houses, at BOTH the long end and the front end. A clean 2x2x2.
#:
#:                      LCH cleared              CME cleared
#:   SOFR   30y   USD-SOFR-1D              USD-SOFR-1D-CME
#:   OIS    30y   USD-OIS                  USD-OIS-CME
#:   SOFR    3y   USD-SOFR-1D-STIR-LCH     USD-SOFR-1D-STIR-CME
#:   OIS     3y   USD-OIS-STIR-LCH         USD-OIS-STIR-CME
#:
#: The LCH/CME basis is the reason for warming both sides, and it is only readable if
#: the two are priced on the same tenor grid on the same dates -- which is why the grid
#: is keyed off the curve rather than applied uniformly.
#:
#: EACH CURVE GETS THE GRID IT CAN ANSWER, and that is the difference between a rate and
#: a fabrication. The 30y curves carry 7,300 days of extrapolation and answer the whole
#: ladder. The STIR curves reach 3y and carry NO extrapolation, deliberately, so a
#: request past their support fails loudly instead of interpolating something plausible.
#: Every tenor in the STIR grid ENDS inside 3y -- the longest are 1y2y and 2y1y.
#:
#: Verified against IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx before wiring: every leg of
#: all eight curves resolves. Two asymmetries are coverage facts rather than gaps, and
#: both are worth knowing before reading a basis off these:
#:
#:   * The OIS STIR curves carry 28 legs against SOFR's 33. GS publishes no sub-1y
#:     SPOT-STARTING OIS swaps, so the five ``0b to 1m/2m/3m/6m/9m`` legs are absent for
#:     OIS at both houses. Every FOMC (frb) and IMM leg is present.
#:   * The BUILDABLE start of a curve is the LATEST history start among its legs, not
#:     the earliest -- a curve needs all of them. Measured after the backfill:
#:       USD-OIS          2005-10-24     USD-OIS-CME           2010-01-04
#:       USD-SOFR-1D      2018-08-01     USD-SOFR-1D-CME       2018-08-02
#:       ...-STIR-LCH     2018-08-01     ...-STIR-CME          2018-08-02
#:       USD-OIS-STIR-LCH 2018-08-01     USD-OIS-STIR-CME      2019-04-09
#:     So only the Fed Funds 30y pair spans the whole sample; everything else starts in
#:     2018 or later. Quoting the earliest leg start (2018-04-27 for CME SOFR) overstates
#:     it by three months and I did exactly that before measuring.

#: The STIR grid. Ends at 3y, inside every STIR curve's support, and no further because
#: none of them extrapolates.
_GS_STIR_TENORS = (
    "1Y", "2Y", "3Y",
    "3m3m", "3m6m", "3m1y", "6m3m", "6m6m", "6m1y", "1y1y", "1y2y", "2y1y",
)

#: curve -> its grid. ``None`` means the full outright + forward ladder below.
_GSQUANT_CURVES = {
    "USD-SOFR-1D":          None,              # SOFR,        LCH, 30y
    "USD-SOFR-1D-CME":      None,              # SOFR,        CME, 30y
    "USD-OIS":              None,              # Fed Funds,   LCH, 30y
    "USD-OIS-CME":          None,              # Fed Funds,   CME, 30y
    "USD-SOFR-1D-STIR-LCH": _GS_STIR_TENORS,   # SOFR STIR,   LCH,  3y
    "USD-SOFR-1D-STIR-CME": _GS_STIR_TENORS,   # SOFR STIR,   CME,  3y
    "USD-OIS-STIR-LCH":     _GS_STIR_TENORS,   # FF OIS STIR, LCH,  3y
    "USD-OIS-STIR-CME":     _GS_STIR_TENORS,   # FF OIS STIR, CME,  3y
}

_OIS_OUTRIGHT_TENORS = tuple(t for t in _EOD_OUTRIGHT_TENORS if int(t.rstrip("Y")) <= 30)
_OIS_FORWARD_TENORS = (
    "1y1y", "1y2y", "1y5y", "1y10y",
    "2y2y", "2y5y", "2y10y",
    "5y5y", "5y10y", "5y25y",
    "10y10y", "10y20y",
)


def _citivelo_eod_tenors(curve: str):
    """Canonical EOD primitive/package grid for one warmed Citi curve.

    USD-SOFR gets the forward surface and the forward packages; the four
    non-USD curves get the bounded forward set and spot packages only. See the
    grid block above for why the spelling is uniform.
    """
    if str(curve).upper() == "USD-SOFR-1D":
        return (
            *_CITIVELO_EOD_OUTRIGHTS,
            *_CITIVELO_USD_SOFR_EOD_FORWARDS,
            *_CITIVELO_EOD_SPREADS,
            *_CITIVELO_USD_SOFR_EOD_FWD_PACKAGES,
        )
    return (*_CITIVELO_EOD_OUTRIGHTS, *_CITIVELO_EOD_FORWARDS, *_CITIVELO_EOD_SPREADS)


# ─────────────────────────────────────────────────────────────────────
# Job definitions
# ─────────────────────────────────────────────────────────────────────

def warm_gsquant_ois_eod(start, end):
    """Job 1: GSQUANT-RL USD EOD -- SOFR and Fed Funds OIS, LCH and CME, 30y and STIR."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue

    from scripts.warm_gsquant_curve_store import warm as warm_gsquant_curves

    # THE STORE WARM COMES FIRST, and without it the rest of this job is decoration.
    #
    # IRSwapsMDP opts GSQUANT-RL into the CurveStore raw-curve and analytics fast paths,
    # and _build_irs_curve_store_curve_map READS that store and returns {} on a miss --
    # it never builds. Nothing in the nightly banked those curves
    # (import_gsquant_curve_panel.py is a one-off CSV importer), so USD-OIS coasted on a
    # historical import that ended 2026-08-03 and this job reported
    # "OK (68.6s, 0 rows x 0 cols)" every night against an empty read.
    #
    # Measured for 2026-08-20: with the store warm the frame goes from 0 columns to 160.
    # Idempotent -- a day already holding both partitions is skipped, so this is a no-op
    # on a warm store and costs ~18s for eight cold curve-days.
    warm_gsquant_curves(start=start, end=end, curves=tuple(_GSQUANT_CURVES))

    mdp = IRSwapsMDP(source="GSQUANT-RL")
    tb = TimeseriesBuilder()

    full = (*_OIS_OUTRIGHT_TENORS, *_OIS_FORWARD_TENORS)
    queries = []
    for curve, own in _GSQUANT_CURVES.items():
        tenors = full if own is None else own
        queries += [UnifiedQuery(curve=curve, tenor=t, value=UnifiedValue.IRS_RATE)
                    for t in tenors]
        log.info("  %-22s %2d tenors%s", curve, len(tenors),
                 "" if own is None else "  (3y STIR grid; this curve does not extrapolate)")
    log.info("  %d queries over %d curves", len(queries), len(_GSQUANT_CURVES))

    df = tb.get_timeseries(
        start=start,
        end=end,
        queries=queries,
        n_jobs=N_JOBS,
        routers={"IRS": IRSwapsTB(mdp, show_tqdm=True)},
        ignore_cache_miss=True,
    )

    # AN EMPTY FRAME IS NOT A SUCCESS, and treating it as one is what hid the outage.
    #
    # The runner reports whatever shape it is handed -- "OK (68.6s, 0 rows x 0 cols)" is
    # a real line from four consecutive nights. A value job that priced nothing has not
    # warmed anything, and it should read FAILED so somebody looks, rather than green so
    # nobody does. This is not the Excel case: no provider was unavailable here, the job
    # simply produced no numbers, which means something is broken.
    if df is None or df.empty or not len(df.columns):
        raise RuntimeError(
            f"GS Quant EOD priced NOTHING for {start}..{end} across "
            f"{len(_GSQUANT_CURVES)} curve(s). The curve store warm ran first, so an "
            "empty frame here means the pricing path found no curves it could read -- "
            "check the CurveStore partitions for these curve names before re-running."
        )
    log.info("  %d series priced across %d curve(s)", len(df.columns), len(_GSQUANT_CURVES))
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
    """Job 3: FedInvest UST YTMs across the whole nominal coupon curve.

    Used to be the 28 constant-maturity ranks. It is now every bond alive on the
    day, each under its own maturity alias, because FedInvest is a whole-file
    daily download whose cache is keyed by DATE ALONE - so the off-the-runs cost
    no extra fetches at all, only ~0.45 s of pricing per date. See
    :func:`_frb_universe_symbols` for the token grammar and why it is
    ``MMYY-oi``.

    Two guards, and each one is here because of a measured incident rather than
    to be thorough:

    An EMPTY FRAME IS NOT A SUCCESS. The runner reports the shape it is handed,
    so a job that priced nothing reads ``OK (0 rows x 0 cols)`` - a real line
    from four consecutive nights of the GS Quant job, which is how that outage
    survived a month. Copied from there deliberately.

    A DAY WHERE MOST BONDS VANISH IS NOT A DAY. On nine days in 2026-07/08
    (07-09, 07-10, 07-13, 07-17, 07-20, 07-24, 07-27, 08-07, 08-10) FedInvest
    served ``eod_price = 0.00`` for ALL 463 bonds while bid and offer stayed
    good. Zero is a sentinel, so ``notna()`` and every required-column
    assertion pass; the pricer solved yields of 605%-5,408% from it and a
    butterfly book marked on those days reached $178 trillion. The MDP's own
    ``50.0 <= clean_price <= 250.0`` band does catch a zero and drops the bond -
    which turns a corrupt tape into a nearly EMPTY FRAME rather than a wrong
    one. That is the shape this looks for. Widening the warm from 28 symbols to
    349 makes the check worth having: at 28 symbols a corrupt day is an
    annoyance, at 349 it is a poisoned store.

    The floor is 60% of the requested symbols and is deliberately loose, because
    the union is taken over the whole window and historical coverage is real:
    349/349 present on 2026-08-21, 309/309 on 2020-08-20, 256/261 on
    2012-08-20. A day that loses 40% of the curve is not a quiet auction week.
    """
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue

    if _FRB_FULL_UNIVERSE:
        symbols = _frb_universe_symbols(end)
        log.info(
            "  %d symbols: %d constant-maturity ranks + %d maturity aliases",
            len(symbols), len(_FRB_CUSIPS), len(symbols) - len(_FRB_CUSIPS),
        )
    else:
        symbols = _FRB_CUSIPS
        log.info("  %d CUSIPs (ranks only): %s", len(symbols), ", ".join(symbols))

    usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")
    tb = TimeseriesBuilder()
    queries = [
        UnifiedQuery(cusip=c, value=UnifiedValue.FRB_YTM)
        for c in symbols
    ]

    df = tb.get_timeseries(
        start=start,
        end=end,
        queries=queries,
        n_jobs=N_JOBS,
        routers={"FRB": FixedRateBondsTB(usts_mdp, show_tqdm=True)},
    )

    if df is None or df.empty or not len(df.columns):
        raise RuntimeError(
            f"FedInvest priced NOTHING for {start}..{end} across {len(symbols)} "
            "symbol(s). FedInvest serves a whole-day table and the fetch is cached "
            "by date, so an empty frame here is the tape, not the request - check "
            "whether the day's eod_price column is all zeros before re-running."
        )

    covered = len(df.columns) / float(len(symbols))
    if covered < _FRB_MIN_COVERAGE:
        raise RuntimeError(
            f"FedInvest priced only {len(df.columns)} of {len(symbols)} symbol(s) "
            f"({covered:.0%}) for {start}..{end}, under the {_FRB_MIN_COVERAGE:.0%} "
            "floor. The MDP drops any bond outside a 50..250 clean price, so a tape "
            "serving eod_price=0.00 arrives here as missing columns rather than as "
            "absurd yields - which is what nine days in 2026-07/08 did."
        )
    log.info("  %d of %d symbol(s) priced (%.0f%%)", len(df.columns), len(symbols), covered * 100)
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


def warm_sr3_settles_eod(start, end):
    """Job: SR3 **EOD settles** at pack depth 20.

    Distinct from "STIRF CME Session", which warms *curves* through the intraday
    path (fetcher wired to ``BARCHART_TOS_LIVE_STIRF-RL``), and from "STIRFO SFR
    Options EOD", which warms options at depth 12. Neither writes the 17:00 EOD
    settle cache the convexity-adjustment panel reads, so nothing did.

    Depth 20 because Golds (rank 17) spans contracts 17..20. Idempotent: dates
    already at depth are skipped, so the daily run is a no-op on a warm cache.
    """
    from scripts.warm_sr3_settles import warm_sr3_eod_settles

    return warm_sr3_eod_settles(start, end)


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


def _last_settled_session(on_or_before=None):
    """The most recent US government-bond session that is over and banked.

    "Over" is the whole point: a job whose writer refuses rows stamped today
    (see ``WarmJob.banks_today``) must be pointed at a day whose rows it will
    actually keep, and that is the previous session, not today's - however far
    past the close the warm happens to run.

    ``pd.bdate_range`` alone is not enough, and the mistake it makes is the one
    this repo has recorded twice: it counts market holidays as business days, so
    a Tuesday after a Monday holiday would be told to warm the Monday, find
    nothing, and report an outage. Filtered on the same
    ``ql.UnitedStates.GovernmentBond`` calendar the other jobs use, plus Good
    Friday, which that calendar treats as a business day while the bond market
    closes and every vendor here serves nothing - measured independently from GS
    (no curve) and from twelve scraped iShares ETFs (no holdings) on 2026-04-03
    and 2023-04-07.
    """
    import QuantLib as ql

    today = datetime.date.today()
    day = min(on_or_before or today, today) - datetime.timedelta(days=1)
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    for _ in range(30):
        qd = ql.Date(day.day, day.month, day.year)
        if cal.isBusinessDay(qd) and not _is_good_friday(day):
            return day
        day -= datetime.timedelta(days=1)
    # Thirty calendar days without a session is not a holiday, it is a broken
    # calendar. Say so rather than silently warming a month ago.
    raise RuntimeError(
        f"no US government-bond session found in the 30 days before "
        f"{on_or_before or today}; the QuantLib calendar is not answering"
    )


def _is_good_friday(day):
    """Good Friday, which the GovernmentBond calendar calls a business day."""
    if day.weekday() != 4:  # Friday
        return False
    return day == _easter_sunday(day.year) - datetime.timedelta(days=2)


def _easter_sunday(year):
    """Anonymous Gregorian computus. Pure arithmetic, no calendar dependency."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lam = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lam) // 451
    month, dayn = divmod(h + lam - 7 * m + 114, 31)
    return datetime.date(year, month, dayn + 1)


def _window_for(job, start, end):
    """The date window this job is actually run over.

    A job that banks today gets exactly what the caller asked for. A job whose
    writer drops today's rows gets a window ending at the last settled session,
    because otherwise it computes numbers nothing keeps - which is what the
    weekday warm did every night, measured on partition mtimes rather than
    argued. See :attr:`utils.warm_jobs.WarmJob.banks_today`.

    ``start`` is clamped rather than shifted with ``end``: a ``--backfill 7``
    should still cover the whole week, just stopping at the last settled day.
    """
    if job.banks_today or end < datetime.date.today():
        return start, end
    settled = _last_settled_session(end)
    return min(start, settled), settled


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

#: Longest any ONE job may run before the process gives up on the whole night.
#:
#: The subprocess jobs have always had deadlines; the IN-PROCESS ones had none
#: at all, and on 2026-08-22 that cost a full run and then some. The Saturday
#: backfill deadlocked inside job 2 and was still alive 24 hours later: two
#: ``frb-mdp`` worker threads each wedged in ``asyncio.run`` ->
#: ``ProactorEventLoop._poll`` under ``FedInvestFetcher.runner``, 306 threads,
#: CPU flat at 159.1 s across a 40-minute gap between two ``py-spy`` dumps with
#: byte-identical stacks. Sixteen of eighteen jobs never started, and the
#: process went on holding the Excel it had launched at 10:00 that morning.
#:
#: Only the multi-date runs reach it: ``_process_one`` is dispatched per
#: timestamp into a thread pool and each worker calls ``asyncio.run`` on its own
#: event loop, so ``--backfill 7`` opens eight of them concurrently and the
#: weekday single-day run opens one. That is why this is a Saturday failure.
#:
#: Two hours because the longest measured job is the UST universe tag warm at
#: 3,466 s (2026-08-21) and the STIRF job carries its own 5,400 s budget - so
#: this has to sit ABOVE the honest worst case or it becomes the thing that
#: breaks the night. 7,200 s is 2.1x the worst real job, and the STIRF job is
#: given its own longer budget below rather than being killed by this.
_JOB_DEADLINE_S = float(os.environ.get("ARBS_WARM_JOB_DEADLINE_S", "7200"))

def _arm_job_watchdog(job_name, results, budget_s):
    """Kill the process if one job runs past its budget, saying which and why.

    A Python thread cannot be interrupted from outside, so there is no way to
    abandon a wedged in-process job and carry on with the next one. The choice
    is between ending the night with a diagnosis and holding the machine
    indefinitely without one, and 2026-08-22 settled which of those is worse.

    Before exiting it dumps every thread's stack through :mod:`faulthandler`,
    which is the same picture ``py-spy dump`` gave for that incident and the
    only thing that made it diagnosable. Then it writes what the run had
    achieved so far, so the log is not truncated mid-job the way that one was.

    Returns a canceller. Nothing here runs on the happy path.
    """
    if budget_s <= 0:
        return lambda: None

    def _fire():
        log.error("=" * 60)
        log.error(
            "DEADLINE: job %r has run for %.0fs without returning. Every thread's "
            "stack follows; the last one that is NOT idle in the run loop is the "
            "job. Ending the run so the machine is not held overnight.",
            job_name, budget_s,
        )
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:  # noqa: BLE001 - we are already dying
                pass
        try:
            stream = open(_CHILD_LOG_PATH, "a", encoding="utf-8") if _CHILD_LOG_PATH else sys.stderr
            stream.write(f"\n{'=' * 70}\nDEADLINE in {job_name!r} after {budget_s:.0f}s\n{'=' * 70}\n")
            faulthandler.dump_traceback(file=stream, all_threads=True)
            stream.flush()
        except Exception:  # noqa: BLE001
            pass
        log.error("=" * 60)
        log.error("SUMMARY (run ended by the job deadline)")
        log.error("=" * 60)
        for name, status in results:
            log.error("  %-30s %s", name, status)
        log.error("  %-30s %s", job_name, f"DEADLINE ({budget_s:.0f}s)")
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:  # noqa: BLE001
                pass
        # os._exit, not sys.exit: the run loop is on another thread and a
        # SystemExit raised here would be swallowed by this timer thread. The
        # deadlocked threads are daemon-less pool workers that would keep the
        # interpreter alive through a normal shutdown - which is exactly the
        # 24-hour state this exists to end.
        os._exit(1)

    timer = threading.Timer(budget_s, _fire)
    timer.daemon = True
    timer.start()
    return timer.cancel

#: Longest the STIRF job may run across ALL its curves. See
#: :func:`warm_stirf_cme_session` for the measurements behind the number.
_STIRF_TOTAL_BUDGET_S = 5400

#: Per-job deadline overrides. The STIRF job carries its own 5,400 s budget and
#: may legitimately approach it, so the run-level watchdog has to sit above that
#: rather than becoming the thing that kills a job doing its job.
_JOB_DEADLINE_OVERRIDES = {
    "STIRF CME Session": _STIRF_TOTAL_BUDGET_S + 1800.0,
}

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

    _warn_unguarded_fallthrough("CitiVelo EOD timeseries")
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

    _warn_unguarded_fallthrough("CitiVelo intraday timeseries")
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
#: The MI01 twin of the swap-spread asset. A SEPARATE key, not a flag on the
#: same one, because the two are separate directories in the tag cache and
#: because ``assert_unique_providers`` would otherwise see two jobs writing one
#: asset - which is the hazard it exists to catch, since ``write_day`` replaces a
#: whole partition rather than merging into it.
_CV_SWAP_SPREAD_TAGS_MI01 = "CITIVELO-TAGS-RATES.OIS.SWAP_SPREAD-MI01"

#: Stop below this. See utils/warm_jobs.py and the 2026-08-07 wedge.
#:
#: This is the HARD ceiling - the one above which nothing may connect at all.
#: The UST universe warms are handed ``citivelo_ust_universe_warm``'s own
#: ``WORKING_CEILING_MB`` (3,500) instead, which is what that script's between-
#: batch check is sized for: its comment reads "leave headroom below the hard
#: 3,800 MB ceiling so a batch in flight cannot cross it. One intraday batch is
#: ~14 MB, so 300 MB is ~20 batches of slack." Passing the hard number spent
#: that headroom, which is the point at which a batch in flight is what crosses
#: the line rather than the check that stops before it.
_CV_MEMORY_CEILING_MB = 3800.0

#: Whether the nightly may START Excel and wait for the add-in to sign itself in.
#:
#: The pre-flight used to treat "no Excel" and "Excel over the ceiling" as human
#: problems, and on a machine nobody is sitting at they are terminal ones. Measured
#: 2026-08-20: six of seventeen jobs failed with ``ExcelNotRunningError`` because the
#: last process that had been using Excel closed it. Three consecutive nights, three
#: different causes -- a batch-0 abort, a 12,501 MB ceiling refusal, then no Excel at
#: all -- and only the middle one had anything to do with this repo's code.
#:
#: ``supervisor`` already knows how to fix both, and its launch path is measured
#: rather than assumed: ``launch_excel`` uses ShellExecute, i.e. exactly what
#: double-clicking the anchor workbook does, and on 2026-08-09 with everything else
#: held equal the ShellExecute instance signed in while a ``Popen`` one accepted the
#: click and did nothing. That is the distinction the old pre-flight message got
#: wrong: a COM-spawned Excel never registers the ``CV*`` UDFs, but a
#: ShellExecute'd one is an ordinary user session and does. Measured again
#: 2026-08-20 across three fresh launches during a multi-hour backfill: signed in
#: every time, 2.8 min, one Login press.
#:
#: Set to 0 to restore the old refuse-and-wait-for-a-human behaviour.
_CV_EXCEL_AUTOSTART = os.environ.get("ARBS_WARM_EXCEL_AUTOSTART", "1").strip().lower() not in {
    "0", "false", "f", "no", "n", "off",
}

#: How long to wait for the add-in to authenticate. Saved credentials resume in
#: about half a minute once the login pane is open, but the pane's handler is inert
#: until roughly four minutes after launch, so the wait has to outlast that. Measured
#: sign-ins have taken 2.8 min; the connect path's own docstring records ~13 for a
#: cold one. 15 minutes sits above both and well inside a nightly envelope that runs
#: 1 h 26 m to 2 h 52 m. It is a WALL CLOCK, not a retry count: the failure mode this
#: has to avoid is the one that wedged 2026-08-20's run for two hours, a COM retry
#: loop with no deadline at all.
_CV_SIGNIN_TIMEOUT_S = float(os.environ.get("ARBS_WARM_EXCEL_SIGNIN_TIMEOUT", "900"))

#: One repair per process, ever. A leaking add-in must not be able to turn this into
#: a restart loop that spends the whole night rescuing and relaunching an Excel that
#: grows past the ceiling again each time. If one attempt does not produce a usable
#: session, the run says so and the Velocity jobs are SKIPPED exactly as before.
_EXCEL_REPAIR_ATTEMPTED = False

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


#: This run's pre-flight verdict, so a job can ask without re-probing.
#:
#: THE GUARD WAS A FENCE WITH A GATE NEXT TO IT, and this is that gate. Measured
#: on 2026-08-19: Excel was at 12,501 MB, all three ``needs_excel`` jobs refused
#: to connect - and then jobs 12, 14 and 15 connected to the SAME Excel and
#: fetched live. 382 tag-cache parquets were written between 19:24:00 and
#: 20:07:00, one of them
#: ``MI01/CLOSE/RATES.OIS.USD_SOFR.PAR.10Y.meta.json`` carrying
#: ``"fetched_at": "2026-08-19T20:06:22"`` over data stamped 20:05 that evening.
#: A ceiling three jobs honour and four walk past is decorative.
#:
#: The seam is documented a hundred lines above and was enforced only by job
#: ORDER: "the Velocity sources read their numbers from the tag cache and fall
#: through to LIVE EXCEL on a miss". Ordering survives a provider that FAILS; it
#: does not survive one that is SKIPPED, because the consumer still runs and the
#: cache still misses.
_EXCEL_BLOCKED = None


def _excel_is_blocked():
    """Why no Velocity job may connect this run, or ``None``."""
    return _EXCEL_BLOCKED


def _warn_unguarded_fallthrough(what):
    """Say out loud that this job can still reach live Excel on a cache miss.

    NOT a guard, and deliberately named so nobody reads it as one. Three of the
    four fall-through jobs go through ``IRSwapsMDP``, whose ``offline`` flag is a
    per-REQUEST kwarg consumed by the Velocity fetcher rather than a constructor
    setting a ``TimeseriesBuilder`` run could reach - so the one-line fix applied
    to the FRB values job has no equivalent here, and inventing one against an
    unverified kwarg would be a guard that silently is not one.

    Until that is closed properly, the seam is at least ATTRIBUTABLE: if these
    jobs write tag parquets on a night the ceiling refused the store warms, this
    line is in the log above it.
    """
    blocked = _excel_is_blocked()
    if blocked:
        log.warning(
            "  %s reads the tag cache and falls through to LIVE EXCEL on a miss, "
            "and Excel is not usable this run (%s). This job is NOT guarded - "
            "measured 2026-08-19, four jobs like it wrote 382 tag parquets while "
            "every guarded job had refused. Watch for tag-cache writes after this "
            "line.", what, blocked,
        )


def _repair_excel(reason: str, *, over_ceiling: bool, signed_out: bool = False):
    """Try ONCE to give this run a signed-in Excel. ``None`` on success, else why not.

    Two situations, two different repairs, and the difference matters because one of
    them can destroy the user's work:

    * **Nothing running.** Launch and wait. Nothing to lose, so nothing to rescue.
    * **Over the ceiling.** ``restart_excel`` RESCUES FIRST -- a dirty workbook with a
      path is saved in place, one without is saved into the recovery directory and the
      path logged -- and if a rescue fails it aborts the restart and leaves Excel alone.
      ``force=True`` overrides that and is never passed here. ``EXCEL.EXE`` is the
      user's application, and a warm that discards someone's unsaved ``Book5`` to save
      itself twenty minutes has made a bad trade on their behalf.

    Never raises. The caller's contract is a reason string or ``None``, and a repair
    that throws would convert a SKIPPED Velocity block into a FAILED run -- the exact
    misreporting the SKIPPED/FAILED split exists to prevent.
    """
    global _EXCEL_REPAIR_ATTEMPTED

    if not _CV_EXCEL_AUTOSTART:
        return f"{reason} (autostart is off: ARBS_WARM_EXCEL_AUTOSTART=0)"
    if _EXCEL_REPAIR_ATTEMPTED:
        return f"{reason}; a repair was already attempted this run and did not stick"
    _EXCEL_REPAIR_ATTEMPTED = True

    try:
        from MDP.CitiVelocityExcel import supervisor
        from MDP.CitiVelocityExcel.memory_guard import excel_memory_mb
    except Exception as exc:  # noqa: BLE001 - the eleven non-Velocity jobs must still run
        return f"{reason}; the supervisor will not import ({exc})"

    t0 = time.perf_counter()
    try:
        if signed_out:
            # ESCALATING, cheap remedy first. A signed-out add-in usually just needs the
            # Login pane pressed, which keeps the session and its warm series cache and
            # costs seconds. But "pressed Login and it did not take" is a real outcome --
            # the pane's handler is inert for minutes after a launch, and an Excel can be
            # signed out AND wedged at the same time -- so when the cheap remedy fails
            # the run is not out of options: kill it and do the full auth path.
            #
            # Bounded by construction: two remedies inside ONE latched repair, never a
            # loop. If the restart does not produce a usable session either, the
            # Velocity block is SKIPPED exactly as before.
            log.warning("Excel pre-flight: %s -- pressing Login and waiting", reason)
            try:
                client = supervisor.wait_for_addin(
                    timeout=_CV_SIGNIN_TIMEOUT_S, press_login=True, logger=log
                )
            except Exception as exc:  # noqa: BLE001 - escalate rather than give up
                log.warning("Excel pre-flight: the Login press did not take (%s: %s) -- "
                            "escalating to a full restart and re-auth",
                            type(exc).__name__, exc)
                client = supervisor.restart_excel(
                    ready_timeout=_CV_SIGNIN_TIMEOUT_S, logger=log
                )
        elif over_ceiling:
            log.warning("Excel pre-flight: %s -- restarting it (rescuing first, force=False)",
                        reason)
            client = supervisor.restart_excel(ready_timeout=_CV_SIGNIN_TIMEOUT_S, logger=log)
        else:
            log.warning("Excel pre-flight: %s -- starting it and waiting for sign-in", reason)
            supervisor.launch_excel(logger=log)
            client = supervisor.wait_for_addin(
                timeout=_CV_SIGNIN_TIMEOUT_S, press_login=True, logger=log
            )
    except Exception as exc:  # noqa: BLE001 - a failed repair is a SKIP, not a crash
        return (f"{reason}; tried to fix it and could not after "
                f"{time.perf_counter() - t0:.0f}s ({type(exc).__name__}: {exc})")

    if client is None:
        return f"{reason}; the repair returned no client after {time.perf_counter() - t0:.0f}s"

    # Re-probe rather than trust the repair. ``wait_for_addin`` proves the add-in
    # ANSWERS; it says nothing about how big the process is, and a restart that
    # relands above the ceiling must still block -- otherwise this has replaced a
    # refusal with a connection to exactly the state the ceiling exists to refuse.
    try:
        mb = excel_memory_mb()
    except Exception as exc:  # noqa: BLE001
        return f"repaired Excel but could not re-probe its memory ({exc})"
    if mb is None or mb <= 0.0:
        return "repaired Excel but the memory probe still cannot see a running instance"
    if mb >= _CV_MEMORY_CEILING_MB:
        return (f"repaired Excel but it came back at {mb:.0f} MB, still at or above the "
                f"{_CV_MEMORY_CEILING_MB:.0f} MB ceiling")

    log.info("Excel pre-flight: repaired in %.1f min, now at %.0f MB and signed in",
             (time.perf_counter() - t0) / 60.0, mb)
    return None


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
        # NOT "a human must open Excel" any more. The bridge still never spawns an
        # instance over COM -- one of those does not register the CV* UDFs -- but
        # ``supervisor.launch_excel`` does not spawn over COM. It ShellExecutes the
        # anchor workbook, which is an ordinary user session, and that instance signs
        # itself in from saved credentials.
        return _repair_excel(
            "no Excel is running, so no Velocity job can work",
            over_ceiling=False,
        )
    if mb >= _CV_MEMORY_CEILING_MB:
        # "Only a human restart shrinks it" was true of the memory and false of the
        # human: ``supervisor.restart_excel`` performs exactly that restart, rescuing
        # unsaved work before it quits and refusing to proceed if a rescue fails.
        return _repair_excel(
            f"Excel is at {mb:.0f} MB, at or above the {_CV_MEMORY_CEILING_MB:.0f} MB "
            "ceiling (the add-in's memory only ever grows, and it wedged at 5,249 MB "
            "on 2026-08-07)",
            over_ceiling=True,
        )
    log.info("Excel pre-flight: %.0f MB, under the %.0f MB ceiling", mb, _CV_MEMORY_CEILING_MB)

    # MEMORY IS NOT LIVENESS, and the gap between them cost three nights of cubes.
    #
    # Every branch above reads a number from Get-Process. None of them asks the only
    # question that matters: does the add-in ANSWER? An Excel sitting at 500 MB with the
    # Velocity add-in signed out passes all three and then fails every Velocity job with
    # AddInNotSignedInError, one job at a time, for the whole run.
    #
    # Measured on the swaption cube (job 8), which stopped writing after 2026-08-17:
    #   2026-08-19  vol fetch exited 1 after 2 s     -> Excel at 12,501 MB, guard refused
    #   2026-08-20  vol fetch exited 1 after 164 s   -> ExcelNotRunningError, no Excel
    # Both of those the memory branches now repair. A signed-out session is the third
    # way in and was still unhandled, so this asks directly.
    #
    # One attach, bounded. It is the same call every Velocity job is about to make, so
    # it adds no new hazard -- it moves the failure thirty seconds earlier, to the one
    # place in the run that can still do something about it.
    return _repair_addin_if_silent()


def _repair_addin_if_silent():
    """``None`` when the add-in answers. Otherwise repair once, or say why not.

    Kept separate from the memory branches because the remedy differs: a signed-out
    add-in does not need Excel restarted, it needs the Login pane pressed, and
    ``wait_for_addin`` does exactly that. Restarting instead would throw away a healthy
    session and cost ~2.8 min of sign-in to reach the same place.
    """
    try:
        from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
        from MDP.CitiVelocityExcel.errors import AddInNotSignedInError, ExcelNotRunningError
    except Exception as exc:  # noqa: BLE001 - the offline jobs must still run
        log.warning("could not import the Velocity bridge for the liveness probe (%s); "
                    "proceeding on the memory reading alone", exc)
        return None

    try:
        CitiVelocityExcelClient.connect(attempts=1, readiness_timeout=60.0)
        log.info("Excel pre-flight: the add-in answers - Velocity jobs may run")
        return None
    except AddInNotSignedInError:
        return _repair_excel("Excel is running and under the ceiling but the Velocity "
                             "add-in is SIGNED OUT", over_ceiling=False, signed_out=True)
    except ExcelNotRunningError:
        # The memory probe saw a process and the bridge cannot bind to it -- an Excel
        # outside the Running Object Table, which a restart fixes and a Login press
        # does not.
        return _repair_excel("Excel is running but the bridge cannot bind to it (not in "
                             "the Running Object Table)", over_ceiling=True)
    except Exception as exc:  # noqa: BLE001 - an unreadable probe must not end the run
        log.warning("Excel pre-flight: the liveness probe failed (%s: %s); proceeding on "
                    "the memory reading alone", type(exc).__name__, exc)
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
    from scripts.citivelo_ust_universe_warm import WORKING_CEILING_MB, warm

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
               ceiling_mb=WORKING_CEILING_MB)
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

    Four values - ``PRICE``, ``YIELD``, ``CAS_RFR`` and ``YYS_RFR`` - and the
    number is a measured budget rather than a preference. The set lives in
    ``citivelo_ust_universe_warm.INTRADAY_VALUES``; widen it with ``--values``
    when someone is watching.

    THE COST MODEL THIS DOCSTRING USED TO QUOTE WAS THE WRONG TRANSPORT'S.
    "~1.7 MB of Excel per tag" is ``fetch_windowed``, a sheet-per-window path
    this warm deliberately does not use (see the note on ``_warm_intraday``).
    What it does use, ``CitiVeloQuotes.frame`` through ``windowed.warm_windows``,
    measured **0.24 MB per tag** - and the very next clause here, "698 tags and
    about 170 MB", is that 0.24 number rather than the 1.7 it had just claimed.
    Sized off the wrong one, two extra values project to +1.2 GB against a
    3,800 MB ceiling and look impossible; sized off the measured one they are
    +58 MB.

    They are also fewer tags than they look. ``CitiVeloBondFetcher.plan`` drops
    any value a bond is not validated for, and only 120 of the 877 catalogued
    ISINs carry CAS_RFR/YYS_RFR - so the marginal cost is 240 tags, taking the
    warm from 1,754 to 1,994.

    Measured 2026-08-08 at two values: 349 bonds, 698 tags, 48 s, Excel +170 MB.
    The universe is 877 bonds now, not 349; both numbers appear in older
    comments and only the first was ever measured.

    Note this deliberately drives ``CitiVeloQuotes.frame`` in sub-cliff windows
    rather than ``CitiVeloBondFetcher.fetch``. The fetcher is the right way to
    READ an intraday quote, but it reaches ``quotes.client()`` directly, so
    nothing it fetches is cached - the first version of this warm "succeeded" on
    349 bonds and left zero MI01 files on disk. See ``_warm_intraday``.
    """
    from scripts.citivelo_ust_universe_warm import (
        DEPTH_BUDGET_S, DEPTH_TARGET_DAYS, WORKING_CEILING_MB, backfill_depth, warm,
    )

    days = int(os.environ.get("CITIVELO_UST_INTRADAY_DAYS", "2"))
    out = warm("intraday", start=end - datetime.timedelta(days=days), end=end,
               ceiling_mb=WORKING_CEILING_MB)
    if out.get("stopped"):
        raise RuntimeError(
            f"UST universe intraday warm stopped after {out['done']}/{out['of']} bonds: "
            f"{out['reason']}. Progress is in the manifest; re-run to continue."
        )

    # DEPTH, after the current window and never instead of it.
    #
    # The rolling window above walks forward and only forward, so on its own this
    # job can never hold more than `days` of history no matter how many nights it
    # runs - measured on the real cache, one window banked 2026-08-04..08-07 and
    # never extended in the twelve days since. The backwards pass is what turns
    # "MI01 for the entire UST universe" from a nightly snapshot into an
    # accumulating series. It is deliberately second: a night that spends its
    # whole budget going backwards and never warmed today would be a regression.
    #
    # A spent budget is the EXPECTED end of this pass and is logged, not raised.
    # The forward warm above raises on `stopped` because a partial forward warm
    # means today is missing; a partial backwards pass means only that the target
    # is one night further away, which is the design.
    depth_days = int(os.environ.get("CITIVELO_UST_DEPTH_DAYS", DEPTH_TARGET_DAYS))
    if depth_days <= 0:
        log.info("  depth backfill disabled (CITIVELO_UST_DEPTH_DAYS=%d)", depth_days)
    else:
        budget = float(os.environ.get("CITIVELO_UST_DEPTH_BUDGET_S", DEPTH_BUDGET_S))
        # NOTHING the backwards pass does may escape this block, and the reason
        # is the line after it rather than tidiness.
        #
        # ``backfill_depth`` opens with its own ``assert_safe_to_connect``, which
        # can raise ``ExcelTooLargeError`` in the seconds between the forward
        # warm's last between-batch check and this call - Excel grows without
        # anyone here touching it (1,918 -> 12,501 MB overnight on 08-18/19 with
        # no cron job connected). Left to propagate, the runner's
        # ``except excel_errors`` would label the WHOLE job SKIPPED, disowning a
        # forward warm that had already succeeded, and
        # ``_raise_on_coverage_regression`` below would never run - silencing the
        # alarm that exists precisely to notice a bond that stopped updating.
        #
        # Depth is the optional half of this job. It may cost the run an exit
        # code; it may not cost it the forward warm's result or its alarm.
        try:
            deep = backfill_depth(end=end, depth_days=depth_days, budget_s=budget,
                                  ceiling_mb=WORKING_CEILING_MB)
            log.info(
                "  depth: %d bond-week(s) over %d pass(es), deepest %s, target %s%s",
                deep["weeks"], deep["passes"], deep.get("deepest"), deep.get("target"),
                f", stopped: {deep['reason']}" if deep.get("stopped") else "",
            )
            if deep.get("stopped") and "budget" not in (deep.get("reason") or ""):
                # The ceiling, an unreadable probe or a dead wire. Not a failure
                # of this job - the forward warm above already succeeded - but it
                # must not be silent either, so it is recorded as a SKIPPED step,
                # which is what makes the run exit 2 rather than 0.
                _SUBPROCESS_SKIPS.append(
                    _StepFailure("UST universe depth backfill", "NOT RUN", deep["reason"])
                )
        except _excel_unavailable_errors() as exc:
            # Excel went away, filled up or signed out between the forward warm
            # and here. Nobody can act on that at 18:15 and nothing was written.
            log.warning("  depth backfill SKIPPED (not a failure): %s", exc)
            _SUBPROCESS_SKIPS.append(
                _StepFailure("UST universe depth backfill", "NOT RUN", str(exc))
            )
        except Exception as exc:  # noqa: BLE001 - a defect here must not eat the alarm
            # A real defect in the backwards pass. Recorded as a FAILED step so
            # the run exits 1, and still not allowed to take the forward warm's
            # coverage check down with it.
            log.exception("  depth backfill FAILED: %s", exc)
            _SUBPROCESS_FAILURES.append(
                _StepFailure("UST universe depth backfill", "NOT RUN",
                             f"{type(exc).__name__}: {exc}")
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


#: The intraday swap-spread window, in the curve's own zone.
#:
#: 08:00-17:00 keeps every reference point INSIDE Citi's USD publishing session,
#: and that is a cost control rather than tidiness. Citi publishes SWAP_SPREAD
#: only during its session while the minute CurveStore holds the Sunday-evening
#: open and the small hours, so a Monday 01:44 curve exists whose newest spread
#: print is the previous Friday 17:59 - 55.8 h against a 12 h limit.
#: ``_resolve_one`` then raises ``StaleCurveError`` per (tenor, minute) and
#: ``IRSwapsTB`` logs a full traceback for each: measured at roughly 4,000
#: tracebacks on a Monday, costing more than the pricing they replace.
_CV_SWAP_SPREAD_INTRADAY_OPEN = datetime.time(8, 0)
_CV_SWAP_SPREAD_INTRADAY_CLOSE = datetime.time(17, 0)
_CV_SWAP_SPREAD_INTRADAY_FREQ = "15min"


def warm_citivelo_swap_spread_tags_intraday(start, end):
    """Job [STORE]: USD_SOFR ``SWAP_SPREAD`` at MI01, into the tag cache.

    USD-SOFR only, and that is the whole scope. Of the twenty Citi indices only
    thirteen carry a ``SWAP_SPREAD`` sub-type at all, the axis is ragged per
    index, and USD is the one anybody reads at minute resolution.

    Distinct from the DAILY sibling by the cache key, not by the tag: the tag
    path ``RATES.OIS.USD_SOFR.SWAP_SPREAD.<tenor>`` carries no frequency
    segment, and ``CitiVeloTagCache`` stores MI01 and DAILY under separate
    directories. So the same eleven tags serve both and neither can overwrite
    the other - which is why this declares its own asset key.

    It is cheap on a warm cache and that is by construction:
    ``_intraday_history_frame`` chunks the request under the measured six-day
    MI01 downsampling cliff and passes ``force_refresh=not cached`` per chunk,
    so a window the cache already covers costs no Excel round trip at all. The
    trailing window is small for the same reason the DAILY one is.

    Measured on this machine's own cache: all eleven USD_SOFR tenors already
    hold MI01 from 2022-08-24 to 2026-08-21, ~1.27M rows and 13-17 MB each,
    ~161 MB in total - four years, already banked. This job keeps the head of
    that current rather than building it.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.swap_spreads import (
        swap_spread_history, swap_spread_tenors,
    )

    # A TRAILING window, not [today, today], and the reason is that the tag
    # cache's coverage model is a single [first, last] interval. It cannot see a
    # hole INSIDE that interval, and a hole does not raise - the as-of search
    # serves the previous print and a whole session silently inherits the day
    # before. One missed night with a [today, today] window would therefore
    # leave a permanent, invisible gap. Overlapping every run is what closes it.
    days = int(os.environ.get("CITIVELO_SWAP_SPREAD_MI01_DAYS", "4"))
    window_start = end - datetime.timedelta(days=days)

    quotes, client = _citivelo_excel_guard()
    try:
        tenors = swap_spread_tenors(_CV_SWAP_SPREAD_INDEX)
        log.info("  %s MI01: %d tenors, %s..%s",
                 _CV_SWAP_SPREAD_INDEX, len(tenors), window_start, end)
        frame = swap_spread_history(
            _CV_SWAP_SPREAD_INDEX, tenors,
            start=window_start, end=end, freq="MI01", quotes=quotes,
        )
        log.info("  served %d/%d tenors, %d minute row(s); Excel at %.0f MB after",
                 len(frame.columns), len(tenors), len(frame), client.excel_memory_mb())
        if not len(frame.columns):
            raise RuntimeError(
                f"{_CV_SWAP_SPREAD_INDEX} MI01 swap spreads returned NO tenors for "
                f"{window_start}..{end}. All eleven have four years of banked MI01, "
                "so an empty axis here is the wire or the window, not the market."
            )
        return frame
    finally:
        quotes.close()


def warm_citivelo_swap_spread_values_intraday(start, end):
    """Job [VALUE]: Citi's published swap spread at a 15-minute stride.

    The same value as the EOD job - ``IRS_CITIVELO_SWAP_SPREAD``, Citi's OWN
    published number rather than the repo's computed MMSS/SPREADOVER - read at
    intraday instants instead of at a close.

    Nothing routes it here explicitly: mode dispatch is
    ``timestamps.resolve_request``, and a datetime carrying a time IS the
    intraday mode, which reads MI01. A bare date, or a midnight timestamp, is
    EOD. So the only difference between this job and its EOD sibling is the
    reference points.

    OFFLINE is forced through the module seam rather than through the query, and
    that distinction is load-bearing. ``quotes=`` and ``offline=`` ARE accepted
    in ``value_kwargs``, but ``value_kwargs`` is hashed into the
    computed-timeseries symbol - so a warm that passed them there would bank
    every value under a symbol no plain user query will ever read. It would look
    like a working warm and serve nobody. ``set_force_offline`` is the
    process-wide seam that exists for exactly this, and it is restored
    afterwards so the setting cannot leak into a later job.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL import swap_spreads
    from MDP.IRSwaps.CITIVELO_EXCEL.swap_spreads import swap_spread_tenors
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    import pytz

    nyc = pytz.timezone("America/New_York")
    days = _business_days(start, end)
    if not days:
        log.info("  no business days in range")
        return None

    tenors = swap_spread_tenors(_CV_SWAP_SPREAD_INDEX)
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL-RL")
    tb = TimeseriesBuilder()
    queries = [
        UnifiedQuery(curve="USD-SOFR-1D", tenor=t,
                     value=UnifiedValue.IRS_CITIVELO_SWAP_SPREAD)
        for t in tenors
    ]
    log.info("  %d tenors x %d day(s) at %s, in-session only (%s-%s ET)",
             len(tenors), len(days), _CV_SWAP_SPREAD_INTRADAY_FREQ,
             _CV_SWAP_SPREAD_INTRADAY_OPEN, _CV_SWAP_SPREAD_INTRADAY_CLOSE)

    frames = []
    swap_spreads.set_force_offline(True)
    try:
        for day in days:
            try:
                frame = tb.get_timeseries(
                    start=nyc.localize(datetime.datetime.combine(
                        day, _CV_SWAP_SPREAD_INTRADAY_OPEN)),
                    end=nyc.localize(datetime.datetime.combine(
                        day, _CV_SWAP_SPREAD_INTRADAY_CLOSE)),
                    queries=queries,
                    freq=_CV_SWAP_SPREAD_INTRADAY_FREQ,
                    n_jobs=N_JOBS,
                    routers={"IRS": IRSwapsTB(mdp, show_tqdm=True)},
                    ignore_cache_miss=True,
                )
                if frame is not None and len(frame):
                    frames.append(frame)
            except Exception as exc:  # one bad day must not end the job
                log.warning("  %s failed: %s: %s", day, type(exc).__name__, exc)
    finally:
        swap_spreads.set_force_offline(None)

    if not frames:
        return None

    import pandas as pd

    out = pd.concat(frames).sort_index()
    log.info("  %d rows x %d cols", len(out), len(out.columns))
    return out


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

    # OFFLINE when the pre-flight said no Velocity job may connect, and this is
    # the only one of the four fall-through jobs where that can be said cleanly:
    # ``FixedRateBondsMDP`` reads ``offline`` off its constructor config
    # (``_citivelo_option``), which is the sole route a ``TimeseriesBuilder`` run
    # has - ``TB.FixedRateBondsTB`` calls ``bulk_get_data`` with a fixed kwarg set
    # and forwards nothing. ``IRSwapsMDP`` takes ``offline`` as a per-REQUEST
    # kwarg into its Velocity fetcher instead, so the same one-liner does not
    # exist there and is not guessed at here.
    #
    # The cost is stated rather than hidden: offline turns a live fallback into
    # an empty column, which becomes a HOLE in the computed store that looks like
    # a day Citi served nothing. That is the better of the two, because the
    # alternative measured itself on 2026-08-19 - an unattended scheduled task
    # opening workbooks against a 12.5 GB add-in - and because the hole is
    # attributable: the run says so here and carries the provenance in SUMMARY.
    blocked = _excel_is_blocked()
    if blocked:
        log.warning(
            "  building OFFLINE: %s. A tag the cache does not hold becomes an "
            "empty column rather than a live workbook; anything it does not "
            "cover is a hole in the computed store, not a day Citi missed.",
            blocked,
        )
    mdp = FixedRateBondsMDP(source="USTS_CITIVELO-RL", offline=bool(blocked))
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


#: The intraday stride for UST bond values, and it is a HARD CONSTRAINT rather
#: than a taste.
#:
#: ``FixedRateBondsTB`` disables the computed-timeseries cache entirely - read
#: AND write - for any intraday request over 50 reference points
#: (``_skip_ts_cache = is_intraday and len(ref_points) > 50``). Past that line
#: the job would price a full session and persist NONE of it, reporting a frame
#: and writing nothing, which is the same shape as the today-guard defect one
#: layer up. 08:00-17:00 ET at 15 minutes is 37 points, comfortably inside it;
#: 10 minutes would be 55 and silently outside.
_CV_BOND_INTRADAY_FREQ = "15min"
_CV_BOND_INTRADAY_OPEN = datetime.time(8, 0)
_CV_BOND_INTRADAY_CLOSE = datetime.time(17, 0)


def warm_citivelo_ust_intraday_values(start, end):
    """Job [VALUE]: UST bond values at MI01, off the banked minute tags.

    THE MI01 BOND STORE HAD NO READER. "CITIVELO UST universe tags INTRADAY"
    has been banking minute quotes nightly - 806 tags over 403 bonds, 993 MB,
    some series back to 2021-01-24 - and ``CITIVELO-TAGS-RATES.BOND-MI01`` was
    declared in ``provides`` by that job and in ``requires`` by nobody. Both UST
    value jobs read the DAILY asset. So the whole intraday half of that warm was
    write-only: a store that costs Excel memory every night and answers no
    question anybody asks through the Query/MDP path.

    This is the reader. It is deliberately narrow where the tag warm is broad:

    * **14 aliases, not 403 bonds.** CT and O across 2/3/5/7/10/20/30 - the
      benchmarks somebody actually watches move during a session. 403 bonds at
      37 stamps would be ~30,000 cells a night for numbers nobody reads.
    * **Two values.** ``FRB_YTM`` and ``FRB_CLEAN_PRICE``, both of which SOLVE
      from the banked ``PRICE``/``YIELD``. The quote-only values (SPREAD_TSY,
      CITI_DURATION, CITI_DV01) are not in ``INTRADAY_VALUES`` and would come
      back as empty columns - a hole that looks like a day Citi served nothing.
    * **A 15-minute stride**, for the 50-point reason above.
    * **``offline=True``**, so a tag the cache does not hold is an empty column
      rather than a live workbook opened from a scheduled task. That is the same
      trade "CITIVELO FRB values EOD" makes and for the same reason, and it is
      only sound BECAUSE the tag warm runs first - which is what ``requires``
      declares.

    One day per call, and the frames concatenated, so one bad day costs a day.
    """
    import pytz

    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    nyc = pytz.timezone("America/New_York")
    days = _business_days(start, end)
    if not days:
        log.info("  no business days in range")
        return None

    mdp = FixedRateBondsMDP(source="USTS_CITIVELO-RL", offline=True)
    tb = TimeseriesBuilder()
    wanted = (UnifiedValue.FRB_YTM, UnifiedValue.FRB_CLEAN_PRICE)
    queries = [
        UnifiedQuery(cusip=alias, value=value)
        for alias in _CV_BOND_ALIASES
        for value in wanted
    ]
    log.info(
        "  %d queries (%d aliases x %d values) x %d day(s) at %s, offline",
        len(queries), len(_CV_BOND_ALIASES), len(wanted), len(days),
        _CV_BOND_INTRADAY_FREQ,
    )

    frames = []
    for day in days:
        try:
            frame = tb.get_timeseries(
                start=nyc.localize(datetime.datetime.combine(day, _CV_BOND_INTRADAY_OPEN)),
                end=nyc.localize(datetime.datetime.combine(day, _CV_BOND_INTRADAY_CLOSE)),
                queries=queries,
                freq=_CV_BOND_INTRADAY_FREQ,
                n_jobs=N_JOBS,
                routers={"FRB": FixedRateBondsTB(mdp, show_tqdm=True)},
            )
            if frame is not None and len(frame):
                frames.append(frame)
        except Exception as exc:  # one bad day must not end the job
            log.warning("  %s failed: %s: %s", day, type(exc).__name__, exc)

    if not frames:
        # Not a silent None. This job exists because the store it reads had no
        # reader; a run that reads nothing from it is the same state wearing a
        # different face, and it should be visible in SUMMARY.
        raise RuntimeError(
            f"UST intraday values priced NOTHING for {start}..{end} across "
            f"{len(_CV_BOND_ALIASES)} alias(es). The MDP is offline, so this means "
            "the MI01 tag cache holds nothing for these bonds in this window - "
            "check 'CITIVELO UST universe tags INTRADAY' ran."
        )

    import pandas as pd

    out = pd.concat(frames).sort_index()
    log.info("  %d rows x %d cols", len(out), len(out.columns))
    return out


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

    _warn_unguarded_fallthrough("CitiVelo swap spread values")
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
    WarmJob("GSQUANT USD SOFR+OIS EOD (LCH+CME, 30y+STIR)", warm_gsquant_ois_eod,
            banks_today=False),
    WarmJob("ERIS USD-SOFR-1D EOD", warm_eris_eod, banks_today=False),
    WarmJob("FRB FedInvest EOD", warm_frb_fedinvest_eod, banks_today=False),
    WarmJob("SR3 EOD settles (depth 20)", warm_sr3_settles_eod),
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
    # The MI01 twin. Same eleven tags, a different cache directory, its own
    # asset key. Cheap on a warm cache - four years are already banked and the
    # chunked reader only connects for a window the cache does not cover.
    WarmJob("CITIVELO swap-spread tags MI01 (store)", warm_citivelo_swap_spread_tags_intraday,
            kind=STORE, provides=(_CV_SWAP_SPREAD_TAGS_MI01,), needs_excel=True),

    # -- then the value jobs that read them --
    WarmJob("CitiVelo EOD timeseries", warm_citivelo_timeseries_eod,
            requires=(_CV_CURVE_STORE,), banks_today=False),
    WarmJob("CitiVelo swaption values EOD", warm_citivelo_swaption_timeseries_eod,
            requires=(_CV_CURVE_STORE, _CV_SWAPTION_CUBE), banks_today=False),
    WarmJob("CitiVelo intraday timeseries", warm_citivelo_timeseries_intraday,
            requires=(_CV_CURVE_STORE,), banks_today=False),
    WarmJob("CITIVELO FRB values EOD", warm_citivelo_frb_values,
            requires=(_CV_BOND_TAGS,), banks_today=False),
    # Same requirement, and it is the load-bearing one: this job builds OFFLINE,
    # so a tag the EOD universe warm has not banked comes back as an empty column
    # rather than as a live Excel call. Silent, and it would populate the computed
    # store with holes that look like days Citi served nothing.
    WarmJob("CITIVELO UST timeseries values EOD", warm_citivelo_ust_timeseries,
            requires=(_CV_BOND_TAGS,), banks_today=False),
    WarmJob("CITIVELO swap spreads EOD", warm_citivelo_swap_spread_values,
            requires=(_CV_SWAP_SPREAD_TAGS,), banks_today=False),
    WarmJob("CITIVELO swap spreads INTRADAY", warm_citivelo_swap_spread_values_intraday,
            requires=(_CV_SWAP_SPREAD_TAGS_MI01,), banks_today=False),
    # The first reader the MI01 bond store has ever had. It was declared in
    # `provides` by the tag warm and in `requires` by nobody, so the intraday
    # half of that job was write-only: 993 MB of minute quotes costing Excel
    # memory every night and answering nothing through the Query/MDP path.
    WarmJob("CITIVELO UST timeseries values INTRADAY", warm_citivelo_ust_intraday_values,
            requires=(_CV_BOND_TAGS_MI01,), banks_today=False),
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
    #
    # ``needs_excel`` alone is the WRONG selector for whether to probe, and that
    # is the 2026-08-19 seam: the four jobs that connected to a 12,501 MB Excel
    # that night all carry ``needs_excel=False``, because none of them needs
    # Excel - they need the TAG CACHE, and reach for Excel only on a miss. So the
    # probe runs for anything that touches a Velocity asset in either direction,
    # and the verdict is published where a job can read it.
    needs_probe = any(
        job.needs_excel
        or any(str(a).startswith("CITIVELO") for a in (job.requires + job.provides))
        for _, job in selected
    )
    global _EXCEL_BLOCKED
    excel_blocked = _excel_preflight() if needs_probe else None
    _EXCEL_BLOCKED = excel_blocked
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

        # The window this job actually gets. A job whose writer refuses today's
        # rows is pointed at the last settled session instead, so the nightly
        # keeps what it computes; see WarmJob.banks_today for the mtime evidence
        # that it previously did not.
        job_start, job_end = _window_for(job, start, end)
        if (job_start, job_end) != (start, end):
            log.info("  window %s..%s (this job does not bank today)", job_start, job_end)

        t0 = time.perf_counter()
        before = len(_SUBPROCESS_FAILURES)
        before_skips = len(_SUBPROCESS_SKIPS)
        cancel_watchdog = _arm_job_watchdog(
            job.name, results, _JOB_DEADLINE_OVERRIDES.get(job.name, _JOB_DEADLINE_S)
        )
        try:
            result = job.fn(job_start, job_end)
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
        finally:
            cancel_watchdog()

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

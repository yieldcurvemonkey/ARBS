r"""Recurring warm for SR3 **EOD settles** at full pack depth.

Why this job exists
===================
The convexity-adjustment panel is built from 17:00 EOD SR3 settles
(``BARCHART_STIRF-RL``). Nothing in the daily warmer fed that cache. The one
STIR entry, ``warm_stirf_cme_session``, warms *curves* (``Q12STIRT``,
``Q16STIRT``, ``…MIX23``) through the intraday CME-session path, whose fetcher is
wired to ``BARCHART_TOS_LIVE_STIRF-RL`` -- a different cache, 1-minute bars, and
one that reaches depth 20 on **zero** dates.

The consequence was measured: settle depth decays toward the front as you move
forward in time, because the only thing that ever wrote deep settles was ad-hoc
historical analysis. Dates holding a contiguous strip of depth >= 20 by year:
253 (2020), 187 (2021), 52 (2022), 51 (2023), **19 (2024), 1 (2025), 0 (2026)**.
Blues (rank 13) needs depth 16 and Golds (rank 17) needs depth 20, so the deep
packs simply stopped being computable. A one-time backfill would move that cliff
rather than remove it, which is why this is a recurring job and not a script.

What it does
============
For each business day in the range, fetch the front ``depth`` quarterly SR3
contracts from the EOD settle source in a single ``fetch_pricers_flat`` call, so
a date costs about one round trip rather than one per contract.

Idempotent by construction: :func:`RVUtils.ConvexityRV.strat2_q20.strip_depth_by_date`
is consulted first and any date already at the target depth is skipped, so the
daily run is a no-op on a warm cache and the weekend backfill only fills holes.

Acceptance is measured, not assumed
===================================
Keys written is **not** the success criterion. The panel matches settles against
a ``{iso_timestamp}-{TICKER}-{SOURCE}`` key stamped 17:00 New York; a fetch that
writes a differently shaped key would report thousands of successful writes and
recover exactly nothing. So depth is re-measured after the warm and the job
reports **before -> after contiguous depth**. If depth does not move, the job
says so and exits non-zero rather than reporting success.

Network
=======
This job is *meant* to reach the network -- it is the warm. It is nonetheless
confined to ``STIRFutureMDP(source="BARCHART_STIRF-RL")``. It must never touch
``IRSwapsMDP(source="BARCHART_STIRF-RL").get_pricer({"curve_name":
"USD-SOFR-1D-Q20STIRT", ...})``, which was measured at 52-57 outbound requests
*per date* and ignores ``offline=True``.

Usage
=====
    python scripts/warm_sr3_settles.py --backfill 7
    python scripts/warm_sr3_settles.py --start 2024-01-01 --end 2024-12-31
    python scripts/warm_sr3_settles.py --date 2026-08-18 --depth 20
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

#: SR3 settles on a New York clock; the scheduler's local time is not it.
_NY_TZ = ZoneInfo("America/New_York")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

log = logging.getLogger(__name__)

#: Golds (rank 17) spans contracts 17..20, so 20 is the depth that makes every
#: colour Citi prints computable. The options warmer's 12 is not enough.
DEFAULT_DEPTH = 20

#: Pause between dates. The warm is small and idempotent; there is no reason to
#: lean on the vendor.
DEFAULT_SLEEP_S = 0.35

#: Hard ceiling on dates touched in one invocation, so an unattended scheduled
#: run cannot turn into an unbounded crawl if the date range is wrong.
DEFAULT_MAX_DATES = 400


def _business_days(start: dt.date, end: dt.date) -> List[dt.date]:
    import pandas as pd
    import QuantLib as ql

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    days = pd.bdate_range(start, end).date.tolist()
    return [d for d in days if cal.isBusinessDay(ql.Date(d.day, d.month, d.year))]


def _strip_symbols(as_of: dt.date, depth: int) -> List[str]:
    """The front ``depth`` quarterly SR3 symbols as of *as_of*."""
    from RVUtils.ConvexityRV.packs import quarterly_imm_sequence
    from RVUtils.ConvexityRV.strat2_sofr_convexity import futures_symbol

    return [futures_symbol(y, m) for (y, m) in quarterly_imm_sequence(as_of, depth)]


def _depth_by_date(depth: int, start: dt.date, end: dt.date) -> Dict[dt.date, int]:
    """Contiguous front-strip depth per date, straight off the local shards.

    Both floors have to be lowered, and for a while only one of them was.

    ``min_instruments`` is the **curve-solve** floor. Forcing it to 1 was correct
    when it was also the universe floor: a 20-node curve fitted to six contracts
    is not a curve, but that is the wrong lens for a warm, whose whole job is to
    find the shallow dates.

    ``9df2875a`` then split the two, moving universe admission to
    ``min_strip_depth`` (default 4) and leaving ``min_instruments`` to the solve.
    This function was not updated, so from that commit it silently stopped seeing
    every date below depth 4 -- measured on a synthetic shard, a date at depth 2
    was omitted entirely while depth 6 came through. The acceptance test then
    reads ``before[d] = 0`` for such a date, so a genuine 2 -> 3 gain scores as no
    gain. The manual deferred warm's ledger recorded **213 dates at depth 0-3**
    before it ran, so this is the common case for a cold date, not an edge case.

    ``strip_depth_by_date``'s own ``min_depth`` overrides the universe floor,
    which is what ``warm_sr3_deferred.plan`` passes and what this needs.
    """
    from RVUtils.ConvexityRV.strat2_q20 import Q20Config, strip_depth_by_date

    return strip_depth_by_date(
        Q20Config(max_instruments=depth, min_instruments=1, start=start, end=end),
        min_depth=1,
    )


#: Hour (America/New_York) after which the current session's SR3 settle is
#: assumed published. SR3 settles at ~15:00 ET; the scheduled slot is 18:15 ET.
SETTLE_HOUR_ET = 16


def _session_has_settled(d: dt.date, *, now_et: Optional[dt.datetime] = None) -> bool:
    """Is *d*'s SR3 settlement published yet?

    ``warm_sr3_deferred`` refuses any date ``>= today`` outright, because
    ``get_data`` stamps a 17:00 settlement alias from whatever the vendor serves
    at request time -- so warming a live session files an intraday print under a
    settlement key, the exact confusion ``assert_settle_source`` exists to catch,
    arriving through the back door. This job had no such guard and its default is
    ``start = end = today``, so the two disagreed.

    A flat ``d >= today`` refusal is the wrong reconciliation: it would make the
    nightly, whose entire purpose is the session that just closed, a no-op every
    night. The hazard is not the calendar date, it is fetching **before the settle
    exists**. So the test is on the clock.
    """
    now = now_et or dt.datetime.now(_NY_TZ).replace(tzinfo=None)
    if d < now.date():
        return True
    if d > now.date():
        return False
    return now.hour >= SETTLE_HOUR_ET


def warm_one_date(mdp, as_of: dt.date, depth: int) -> Tuple[int, Optional[str]]:
    """Fetch the front *depth* settles for one date.

    Returns ``(n_pricers, error)``. A failure is returned rather than raised so
    one bad date cannot abort an unattended run.
    """
    symbols = _strip_symbols(as_of, depth)
    try:
        pricers = mdp.fetch_pricers_flat(symbols, timestamp=as_of)
        return len(pricers), None
    except Exception as exc:  # noqa: BLE001 - recorded as data, see docstring
        return 0, f"{type(exc).__name__}: {exc}"


def run_warm(
    start: dt.date,
    end: dt.date,
    *,
    depth: int = DEFAULT_DEPTH,
    sleep_s: float = DEFAULT_SLEEP_S,
    max_dates: int = DEFAULT_MAX_DATES,
    force: bool = False,
) -> Dict[str, object]:
    """Warm EOD settles to *depth* across the range. Returns a summary dict."""
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    dates = _business_days(start, end)
    if not dates:
        log.info("No business days in %s..%s", start, end)
        return {"dates_considered": 0, "warmed": 0, "skipped": 0, "failed": 0}

    # Never reach for a session whose settle does not exist yet: `get_data`
    # stamps a 17:00 settlement alias from whatever the vendor serves at request
    # time, so an unsettled date files an intraday print under a settlement key.
    unsettled = [d for d in dates if not _session_has_settled(d)]
    if unsettled:
        log.info("skipping %d date(s) whose session has not settled: %s",
                 len(unsettled), ", ".join(str(d) for d in unsettled[:5]))
        dates = [d for d in dates if _session_has_settled(d)]
        if not dates:
            log.info("nothing settled in %s..%s yet", start, end)
            return {"dates_considered": 0, "warmed": 0, "skipped": 0,
                    "failed": 0, "skipped_unsettled": len(unsettled)}

    before = _depth_by_date(depth, start, end)
    todo = dates if force else [d for d in dates if before.get(d, 0) < depth]
    skipped = len(dates) - len(todo)

    capped = False
    if len(todo) > max_dates:
        log.warning("capping at %d dates (%d needed) -- rerun to continue",
                    max_dates, len(todo))
        todo, capped = todo[:max_dates], True

    log.info("SR3 settle warm: depth %d, %d business days, %d already deep, %d to fetch",
             depth, len(dates), skipped, len(todo))

    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    warmed, failures = 0, []
    for i, d in enumerate(todo, 1):
        n, err = warm_one_date(mdp, d, depth)
        if err is None:
            warmed += 1
            log.info("[%d/%d] %s  %d pricers", i, len(todo), d, n)
        else:
            failures.append({"date": d.isoformat(), "error": err})
            log.warning("[%d/%d] %s  FAIL %s", i, len(todo), d, err)
        if sleep_s:
            time.sleep(sleep_s)

    # --- acceptance: did measured depth actually move? -----------------------
    after = _depth_by_date(depth, start, end)
    gained = sum(1 for d in todo if after.get(d, 0) > before.get(d, 0))
    reached = sum(1 for d in todo if after.get(d, 0) >= depth)

    summary = {
        "dates_considered": len(dates),
        "already_deep": skipped,
        "attempted": len(todo),
        "warmed": warmed,
        "failed": len(failures),
        "depth_gained": gained,
        "reached_target": reached,
        "capped": capped,
        "failures": failures[:20],
    }
    log.info("SR3 settle warm done: %d fetched, %d gained depth, %d now at >=%d, %d failed",
             warmed, gained, reached, depth, len(failures))
    if warmed and gained == 0:
        log.error("WROTE %d dates BUT MEASURED DEPTH DID NOT MOVE -- the cache key "
                  "shape the panel reads and the one being written may disagree.", warmed)
    return summary


def warm_sr3_eod_settles(start, end):
    """``daily_cache_warmer`` entry point. Signature is ``fn(start, end)``."""
    s = run_warm(start, end)
    if s["dates_considered"] == 0:
        return None
    if s["warmed"] and s["depth_gained"] == 0:
        raise RuntimeError(
            f"SR3 settle warm fetched {s['warmed']} dates but measured contiguous "
            "depth did not increase on any of them")
    return (f"SR3 EOD settles: {s['warmed']} warmed, {s['already_deep']} already deep, "
            f"{s['reached_target']} at >= {DEFAULT_DEPTH}, {s['failed']} failed")


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--start", type=dt.date.fromisoformat)
    p.add_argument("--end", type=dt.date.fromisoformat)
    p.add_argument("--date", type=dt.date.fromisoformat, help="single date")
    p.add_argument("--backfill", type=int, metavar="N", help="past N calendar days")
    p.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    p.add_argument("--max-dates", type=int, default=DEFAULT_MAX_DATES)
    p.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_S)
    p.add_argument("--force", action="store_true", help="refetch even if already deep")
    p.add_argument("--dry-run", action="store_true", help="report the gap, fetch nothing")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    today = dt.date.today()
    if a.date:
        start = end = a.date
    elif a.backfill:
        start, end = today - dt.timedelta(days=a.backfill), today
    else:
        start = a.start or today
        end = a.end or today

    if a.dry_run:
        depth_map = _depth_by_date(a.depth, start, end)
        days = _business_days(start, end)
        short = [(d, depth_map.get(d, 0)) for d in days if depth_map.get(d, 0) < a.depth]
        print(f"{len(days)} business days, {len(short)} below depth {a.depth}")
        for d, n in short[:25]:
            print(f"   {d}  depth {n}")
        if len(short) > 25:
            print(f"   ... and {len(short) - 25} more")
        return 0

    s = run_warm(start, end, depth=a.depth, sleep_s=a.sleep,
                 max_dates=a.max_dates, force=a.force)
    print(s)
    return 1 if (s["warmed"] and s["depth_gained"] == 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())

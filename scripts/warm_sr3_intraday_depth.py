r"""Warm the SR3 **minute tape** to full pack depth, so Golds prices intraday.

Why this job exists
===================
``sfr_cvx_adj_intraday`` refuses ``GOLDS`` (rank 17, needs a contiguous strip of
20) at every instant, and for a while the notebook explained that as a property
of the tape. It is not. It is a property of what we have ever asked for.

The measurement that settles it, over 1,667 dates of local shards, is the
distribution of the **deepest rank ever written** on a date::

    rank 12 -> 457 dates      rank 14 -> 2
    rank 13 -> 289 dates      rank 15 -> 2
    rank 17 -> 106 dates      rank 16 -> 1

12, 13 and 17 are exactly the instrument counts of the three curves the nightly
intraday job builds -- ``…MIX23`` ``SFRCM1..12``, ``Q12STIRT`` ``..13``,
``Q16STIRT`` ``..17``. A liquidity ceiling would be ragged and would drift with
volume. Three spikes sitting on three config lengths is a **request** ceiling.

And asked directly, the vendor serves deeper. At 2026-08-19 14:00 CT, ranks
12..20 each returned a price at the requested minute, monotone 95.940 down to
95.755; 18-20 came back freshly stamped in UTC because nothing had ever cached
them.

So this is the intraday analogue of ``warm_sr3_settles.py``: the settle warm
lifted the *daily* panel from 0 usable Golds dates in 2026 to 159, and this is
the same shape of fix one clock down.

What it does, and what it deliberately does NOT do
==================================================
It warms **only the ranks that are missing**, at **only the instants that
already exist**. Both restrictions matter:

*Only the missing ranks.* Ranks 1..17 are already written by the nightly curve
builds. Re-fetching them would multiply the vendor cost by six for nothing.

*Only the existing instants.* A minute at which nothing else is cached is a
minute at which the strip cannot be completed anyway -- the *other* legs are not
there either -- so fetching rank 18 at it buys nothing. Enumerating the instants
already present for a front contract turns "warm a session" from ~480 blind
requests into ~300 targeted ones, and every one of them completes a strip that
was otherwise one contract short.

The consequence is that this job **cannot create an intraday series where none
exists**. On a date whose tape holds five stamps, it warms five instants and the
date remains unusable as a series. That is correct: the missing thing there is
the nightly job's coverage, not this job's depth.

Alternatives rejected
=====================
*Deepening the nightly curve configs* (``Q16STIRT`` from 17 instruments to 20).
That is the tempting one-line fix and it is wrong: those configs are read by
everything that builds an intraday SOFR curve, so lengthening them changes curve
solves for consumers who never asked for deep packs, and it does so silently.
Depth for the CA panel is a caching concern, not a curve-shape concern.

*A blind minute-by-minute crawl.* ~480 instants x 20 symbols x 181 dates is a
six-figure request count against a vendor this repo has already provoked into a
429 storm once. Bounded, targeted, resumable, or not at all.

Acceptance is measured, not assumed
===================================
Keys written is not the criterion, for the same reason it is not in the settle
warm: a fetch that writes a differently-shaped key reports thousands of
successful writes and recovers nothing. This job re-measures **contiguous depth
at the warmed instants**, before and after, and reports the movement. If depth
does not move it says so and exits non-zero.

Network
=======
This job is *meant* to reach the network. It is confined to
``STIRFutureMDP(source="BARCHART_TOS_LIVE_STIRF-RL")``. It must never touch
``IRSwapsMDP(...).get_pricer({"curve_name": "USD-SOFR-1D-Q20STIRT"})``, measured
at 52-57 outbound requests per date.

It also refuses any instant inside ``LIVE_QUOTE_GUARD_MINUTES`` of now: within
that window ``STIRFutureMDP`` switches to live quotes and bypasses the cache, so
a "warm" there writes nothing and costs a request.

Usage
=====
    # measure only -- no network at all
    python scripts/warm_sr3_intraday_depth.py --date 2026-08-19 --dry-run

    # one session, bounded
    python scripts/warm_sr3_intraday_depth.py --date 2026-08-19 --budget-s 600

    # a range, resumable: already-deep instants are skipped
    python scripts/warm_sr3_intraday_depth.py --start 2026-01-02 --end 2026-08-20 \
        --budget-s 3600
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

log = logging.getLogger(__name__)

#: Golds (rank 17) spans contracts 17..20, so 20 is the depth that makes every
#: colour Citi prints computable intraday.
DEFAULT_DEPTH = 20

#: The nightly intraday job's deepest curve calibrates to SFRCM1..17, so 1..17
#: are already cached on any date it ran. Warming from 18 is the whole saving.
DEFAULT_FROM_RANK = 18

#: Pause between instants. Deliberately unhurried: this repo has provoked a 429
#: storm out of this vendor before, from an unthrottled 429-blind fetcher.
DEFAULT_SLEEP_S = 0.35

#: Wall-clock ceiling for one invocation. There is no natural stopping point in
#: a backfill, so the job takes one from the caller and reports where it stopped.
DEFAULT_BUDGET_S = 900.0

#: Never touch more instants than this in one run, budget or no budget.
DEFAULT_MAX_INSTANTS = 5000


def _tape_tz() -> ZoneInfo:
    from RVUtils.ConvexityRV import ca_intraday as CI
    return ZoneInfo(CI.TAPE_TZ_NAME)


def _business_days(start: dt.date, end: dt.date) -> List[dt.date]:
    import pandas as pd
    import QuantLib as ql

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    days = pd.bdate_range(start, end).date.tolist()
    return [d for d in days if cal.isBusinessDay(ql.Date(d.day, d.month, d.year))]


def _strip_symbols(as_of: dt.date, depth: int) -> List[str]:
    from RVUtils.ConvexityRV.packs import quarterly_imm_sequence
    from RVUtils.ConvexityRV.strat2_sofr_convexity import futures_symbol

    return [futures_symbol(y, m) for (y, m) in quarterly_imm_sequence(as_of, depth)]


def instants_present(
    probe,
    day: dt.date,
    anchor_symbol: str,
    *,
    open_ct: dt.time = dt.time(7, 0),
    close_ct: dt.time = dt.time(16, 0),
    step_minutes: int = 1,
) -> List[dt.datetime]:
    """The minutes on *day* at which the tape already holds *anchor_symbol*.

    This is the targeting step, and it is what keeps the job bounded. The
    anchor is a front contract, which the nightly job writes whenever it runs at
    all, so its stamps are a faithful index of "minutes this session actually
    has". Probing is local and free; fetching is not.

    Both key spellings are probed, because the local slice carries a UTC-stamped
    tape and a Chicago-stamped tape written by different jobs, and 741 of 1,667
    dates carry more than one family.
    """
    from RVUtils.ConvexityRV import ca_intraday as CI

    tz = _tape_tz()
    start = dt.datetime.combine(day, open_ct, tzinfo=tz)
    end = dt.datetime.combine(day, close_ct, tzinfo=tz)
    out: List[dt.datetime] = []
    cur = start
    step = dt.timedelta(minutes=step_minutes)
    while cur <= end:
        if any(probe(k) for k in CI.tape_keys(cur, anchor_symbol)):
            out.append(cur)
        cur += step
    return out


def _instant_is_warmable(ts: dt.datetime) -> Tuple[bool, str]:
    """Refuse instants the MDP would answer from the live quote path.

    Inside the guard window ``STIRFutureMDP`` stops reading the cache entirely,
    so a fetch there writes nothing under the key this job is trying to fill and
    still costs a request. Skipping is not a limitation; it is the only way the
    acceptance measurement below stays honest.
    """
    from RVUtils.ConvexityRV import ca_intraday as CI

    now = dt.datetime.now(dt.timezone.utc)
    age_min = (now - ts.astimezone(dt.timezone.utc)).total_seconds() / 60.0
    if age_min < CI.LIVE_QUOTE_GUARD_MINUTES:
        return False, f"within {CI.LIVE_QUOTE_GUARD_MINUTES}min live-quote window"
    return True, ""


def warm_one_instant(
    mdp,
    ts: dt.datetime,
    symbols: Sequence[str],
) -> Tuple[int, Optional[str]]:
    """Fetch *symbols* at one instant. Returns ``(n_pricers, error)``.

    A failure is returned rather than raised so one bad minute cannot abort an
    unattended run -- and so the reasons end up in the summary, where a reader
    can tell "the vendor has nothing here" from "our request was malformed".
    """
    try:
        pricers = mdp.fetch_pricers_flat(list(symbols), timestamp=ts)
        return len(pricers), None
    except Exception as exc:                            # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def plan_day(probe, day: dt.date, depth: int, from_rank: int,
             **kw) -> Dict[str, object]:
    """What one date needs, measured locally with no network at all."""
    from RVUtils.ConvexityRV import ca_intraday as CI

    ladder = _strip_symbols(day, depth)
    anchor = ladder[0]
    stamps = instants_present(probe, day, anchor, **kw)
    before = {ts: CI.tape_depth(probe, ts, ladder) for ts in stamps}
    todo = [ts for ts, d in before.items() if d < depth]
    return {
        "date": day,
        "ladder": ladder,
        "missing_symbols": ladder[from_rank - 1:depth],
        "stamps": stamps,
        "before": before,
        "todo": todo,
        "already_deep": len(stamps) - len(todo),
    }


def run_warm(
    start: dt.date,
    end: dt.date,
    *,
    depth: int = DEFAULT_DEPTH,
    from_rank: int = DEFAULT_FROM_RANK,
    sleep_s: float = DEFAULT_SLEEP_S,
    budget_s: float = DEFAULT_BUDGET_S,
    max_instants: int = DEFAULT_MAX_INSTANTS,
    dry_run: bool = False,
    step_minutes: int = 1,
) -> Dict[str, object]:
    """Warm the minute tape to *depth* across the range. Returns a summary."""
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
    from RVUtils.ConvexityRV import ca_intraday as CI

    mdp = STIRFutureMDP(source=CI.INTRADAY_FUTURES_SOURCE)
    probe = CI.mdp_key_probe(mdp)

    days = _business_days(start, end)
    t0 = time.monotonic()
    summary: Dict[str, object] = {
        "start": str(start), "end": str(end), "depth": depth,
        "from_rank": from_rank, "dry_run": dry_run,
        "dates_considered": len(days), "dates_touched": 0,
        "instants_seen": 0, "instants_already_deep": 0,
        "instants_warmed": 0, "instants_skipped_live": 0,
        "instants_failed": 0, "depth_before": {}, "depth_after": {},
        "gained": 0, "unchanged": 0, "stopped_early": None, "failures": {},
    }

    for day in days:
        if time.monotonic() - t0 > budget_s:
            summary["stopped_early"] = f"budget {budget_s:.0f}s reached at {day}"
            break
        if summary["instants_warmed"] >= max_instants:
            summary["stopped_early"] = f"max_instants {max_instants} reached at {day}"
            break

        p = plan_day(probe, day, depth, from_rank, step_minutes=step_minutes)
        stamps, todo = p["stamps"], p["todo"]
        summary["instants_seen"] += len(stamps)
        summary["instants_already_deep"] += int(p["already_deep"])
        if not todo:
            continue
        summary["dates_touched"] += 1
        log.info("%s: %d stamps, %d already at depth %d, %d to warm",
                 day, len(stamps), p["already_deep"], depth, len(todo))

        deepest_before = max(p["before"].values()) if p["before"] else 0
        summary["depth_before"][str(day)] = deepest_before

        for ts in todo:
            if time.monotonic() - t0 > budget_s:
                summary["stopped_early"] = f"budget {budget_s:.0f}s reached in {day}"
                break
            if summary["instants_warmed"] >= max_instants:
                summary["stopped_early"] = f"max_instants reached in {day}"
                break
            ok, why = _instant_is_warmable(ts)
            if not ok:
                summary["instants_skipped_live"] += 1
                continue
            if dry_run:
                summary["instants_warmed"] += 1
                continue
            n, err = warm_one_instant(mdp, ts, p["missing_symbols"])
            if err:
                summary["instants_failed"] += 1
                summary["failures"].setdefault(str(day), {})[ts.isoformat()] = err
            else:
                summary["instants_warmed"] += 1
            time.sleep(sleep_s)

        # Acceptance, re-measured on the SAME instants. Keys written is not the
        # criterion: a differently-shaped key reports success and recovers
        # nothing, which is precisely the failure this re-measure exists to catch.
        if not dry_run:
            after = {ts: CI.tape_depth(probe, ts, p["ladder"]) for ts in stamps}
            deepest_after = max(after.values()) if after else 0
            summary["depth_after"][str(day)] = deepest_after
            if deepest_after > deepest_before:
                summary["gained"] += 1
            else:
                summary["unchanged"] += 1

    summary["elapsed_s"] = round(time.monotonic() - t0, 1)
    return summary


def _report(s: Dict[str, object]) -> int:
    print(json.dumps({k: v for k, v in s.items()
                      if k not in ("depth_before", "depth_after", "failures")},
                     indent=2, default=str))
    before, after = s["depth_before"], s["depth_after"]
    if before:
        print("\ndeepest contiguous depth, before -> after:")
        for d in sorted(before):
            b = before[d]
            a = after.get(d, b)
            flag = "  GAINED" if a > b else ""
            print(f"  {d}  {b:2d} -> {a:2d}{flag}")
    if s["failures"]:
        print("\nfailures (first 5 dates):")
        for d in list(s["failures"])[:5]:
            for ts, err in list(s["failures"][d].items())[:2]:
                print(f"  {d} {ts}: {err}")

    if s["dry_run"]:
        print(f"\nDRY RUN: {s['instants_warmed']} instants would be fetched "
              f"across {s['dates_touched']} dates.")
        return 0
    if not s["dates_touched"]:
        print("\nNothing to do: every measured instant was already at depth.")
        return 0
    if not s["gained"]:
        # Deliberately non-zero. A warm that wrote keys and moved no depth is
        # the exact silent failure this job's acceptance check exists for.
        print("\nFAILED: instants were fetched and NO date gained depth. Either "
              "the vendor has nothing at these minutes, or the keys written do "
              "not match the keys the panel reads. Do not report success.")
        return 1
    print(f"\nOK: {s['gained']} of {s['gained'] + s['unchanged']} dates gained "
          f"depth.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", type=dt.date.fromisoformat)
    ap.add_argument("--start", type=dt.date.fromisoformat)
    ap.add_argument("--end", type=dt.date.fromisoformat)
    ap.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    ap.add_argument("--from-rank", type=int, default=DEFAULT_FROM_RANK,
                    help="first rank to fetch; 1..17 are written by the nightly "
                         "curve builds, so the default of 18 is the saving")
    ap.add_argument("--step-minutes", type=int, default=1)
    ap.add_argument("--sleep-s", type=float, default=DEFAULT_SLEEP_S)
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    ap.add_argument("--max-instants", type=int, default=DEFAULT_MAX_INSTANTS)
    ap.add_argument("--dry-run", action="store_true",
                    help="measure and plan with NO network at all")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if a.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s")
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

    if a.date:
        start = end = a.date
    elif a.start and a.end:
        start, end = a.start, a.end
    else:
        ap.error("give --date, or --start and --end")

    return _report(run_warm(
        start, end, depth=a.depth, from_rank=a.from_rank, sleep_s=a.sleep_s,
        budget_s=a.budget_s, max_instants=a.max_instants, dry_run=a.dry_run,
        step_minutes=a.step_minutes))


if __name__ == "__main__":
    raise SystemExit(main())

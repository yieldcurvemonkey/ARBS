r"""Warm the DEFERRED end of the SR3 settle strip, so the deep packs exist again.

    C:/Users/chris/anaconda3/envs/stir/python.exe scripts/warm_sr3_deferred.py --dry-run
    C:/Users/chris/anaconda3/envs/stir/python.exe scripts/warm_sr3_deferred.py --max-calls 400

WHAT THIS IS FOR, AND WHAT IT IS NOT FOR
========================================
The convexity-adjustment panel went sparse after 2023 for two independent
reasons. One was a code defect -- a universe gate that dropped a whole date for
want of contracts its front packs never read -- and that is fixed in
``strat2_q20`` / ``strat2_sofr_convexity`` and costs no network at all. It
recovers rank 1 and rank 5.

The other is real absence. Nothing has written a **deferred** SR3 settle to this
machine since the ad-hoc analysis that needed one. Contiguous strip depth by
year, measured off the shards:

======  ====  ====  ====  ====  ====  ====  ====
depth   2020  2021  2022  2023  2024  2025  2026
======  ====  ====  ====  ====  ====  ====  ====
>= 12    253   252   252   231    19     3     5
>= 16    253   252   195    51    19     2     3
>= 20    253   187    52    51    19     2     2
======  ====  ====  ====  ====  ====  ====  ====

Blues is rank 13 and needs depth 16; Golds is rank 17 and needs depth 20. No
amount of code recovers those. This job is the fetch that does.

THE UNIT COST, MEASURED RATHER THAN ASSUMED
===========================================
The brief this was written against assumed "one fetch back-fills a contract's
whole history, so a warm costs one call per contract". **It does not.**
``STIRFutureMDP.get_data`` with a ``datetime.date`` sets ``want_eod``
(``STIRFutureMDP.py:1023``), which forces ``interval = None`` (``:1137``), which
bounds the request to **one day** (``:799-801``). Two timed probes on
2025-07-11/14:

* 1 contract x 1 date -> **3.55 s**, 1 new key, 1 date touched.
* 16 contracts x 1 date -> **6.08 s**, 31 new keys, 1 date each.

Fit ``t(n) = 3.38 + 0.169 n`` seconds for n contracts on one date. So the warm is
per **(date, contract) cell** in what it writes but per **date** in what it
costs, because symbols batch into one call. That is why the budget here is
counted in ``get_data`` calls -- one per date -- and not in contracts.

FOUR PROPERTIES THAT MATTER MORE THAN SPEED
===========================================
1. **It never refetches a cell that is already present.** The symbol list for a
   date is the front strip MINUS what the local scan already resolves. A present
   settle therefore cannot be overwritten by a later vendor revision, which is
   what makes "no previously-published CA value moved" a fact about the data
   rather than a hope.
2. **It skips dates already deep enough to be published.** Deepening a date from 12
   instruments to 20 recalibrates its Q20 curve and *would* move that date's
   published ``ca_bp_q20``. Those dates are left exactly as they are and reported
   as remaining work.
3. **Acceptance is measured, not counted.** Keys written is not the criterion:
   the panel reads a ``{iso}-{TICKER}-{SOURCE}`` alias stamped in **New York
   local time**, and the store already contains 1,061 17:00 keys stamped
   ``+00:00`` that match the naive regex and resolve to nothing. So depth is
   re-measured after the run with the same reader the panel uses, and a date that
   gained keys without gaining depth is reported as a FAILURE.
4. **Resumable, write-through, failures as data.** The ledger is written after
   every date, so a kill costs one date; a rerun skips what the ledger already
   records as done, and records what it could not get rather than dropping it.

SUPERSEDED IN PART (2026-08-27)
===============================
``scripts/warm_sr3_settles.py`` now warms by CONTRACT rather than by date, via
``STIRFutureMDP.warm_settles``, which is ~one vendor request per contract instead
of one per date -- so for a plain depth backfill prefer that. This runner is kept
for its ledger, its resume and its per-date accounting. Both write into the same
settle namespace.

NETWORK
=======
This job is *meant* to reach the network. It is nonetheless confined to
``STIRFutureMDP(source="BARCHART_STIRF_SETTLE-RL")``, one batched call per date. It must
never touch ``IRSwapsMDP(...).get_pricer({"curve_name": "USD-SOFR-1D-Q20STIRT"})``
-- measured at 52-57 outbound requests **per date**, with ``offline=True``
accepted and then ignored -- and it never builds a curve at all. The pre-scan
that decides what to fetch reads the sqlite shards read-only and opens no socket.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DATA = REPO / "notebooks" / "data" / "convexity_rv"
LEDGER = DATA / "warm_sr3_deferred_ledger.json"
PANEL = DATA / "strat2_q20_panel.parquet"

#: Golds (rank 17) spans contracts 17..20, so 20 makes every colour Citi prints
#: computable. Fetching to 20 rather than 16 costs 4 x 0.169s = 0.7s per date.
DEFAULT_DEPTH = 20

#: Budget, in ``get_data`` calls == dates. The task brief caps the warm at 400
#: "contract-fetches"; the measured unit of a fetch is one per-date call, so this
#: is that cap read in the unit the API actually bills in. The full 2024-2026
#: warm is ~650 calls, i.e. over budget -- see ``--start`` to finish the rest.
DEFAULT_MAX_CALLS = 400

#: Be a good citizen. 0.4s is the pause the proven UST harvester uses.
DEFAULT_PAUSE = 0.4


# ---------------------------------------------------------------------------
# Planning -- entirely offline
# ---------------------------------------------------------------------------
def _business_days(start: dt.date, end: dt.date) -> List[dt.date]:
    """US government-bond business days in ``[start, end]``.

    Falls back to plain weekdays if QuantLib is unavailable -- a holiday costs
    one wasted call and is recorded as a zero-resolution date, not a crash.
    """
    import pandas as pd

    days = [d.date() for d in pd.bdate_range(start, end)]
    try:
        import QuantLib as ql                                  # noqa: PLC0415

        cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
        return [d for d in days
                if cal.isBusinessDay(ql.Date(d.day, d.month, d.year))]
    except Exception:                                          # noqa: BLE001
        return days


def plan(
    start: dt.date,
    end: dt.date,
    *,
    depth: int = DEFAULT_DEPTH,
    protect_min_depth: int = 12,
) -> Tuple[List[Tuple[dt.date, int, List[str]]], Dict[str, object]]:
    """``[(date, current_depth, symbols_to_fetch)]`` plus a summary. No network.

    A date is a candidate when it already carries an EOD session (so it is a real
    trading day the vendor has data for) and its contiguous strip falls short of
    *depth*. The symbols requested are exactly the ones missing -- never the whole
    strip -- so a present settle is never overwritten.

    ``protect_min_depth`` is the subtle one. Deepening a date does not overwrite
    any settle, but it DOES change that date's Q20 curve: the curve is calibrated
    to ``SFRCM1..depth``, so going from 12 instruments to 20 re-solves it and
    moves the date's published ``ca_bp_q20`` by a fraction of a basis point. For
    a coverage repair that must not move a single previously-published number,
    any date already deep enough to have contributed deep-pack rows is therefore
    left exactly as it is, and reported as remaining work. 12 is the depth at
    which rank 9 (Greens) becomes quotable, which is where the shipped panel's
    deep content begins.
    """
    import RVUtils.ConvexityRV.strat2_q20 as Q
    from RVUtils.ConvexityRV.packs import quarterly_imm_sequence
    from RVUtils.ConvexityRV.strat2_sofr_convexity import (
        _cached_symbols_by_date, Strat2Config, futures_symbol)

    # `min_depth=1` is the warm's lens: a config floored at 4 cannot see the
    # one- and two-contract dates this job exists to fill.
    cfg = Q.Q20Config(max_instruments=depth, start=start, end=end)
    have = _cached_symbols_by_date(
        Strat2Config(n_contracts=depth, start=start, end=end))
    depths = Q.strip_depth_by_date(cfg, min_depth=1)

    # Candidates are US government-bond business days UNION the dates that
    # already hold an EOD key. The union matters: ~40 trading days in this window
    # hold NO SR3 EOD key at all, so a scan-only planner is blind to exactly the
    # coldest dates -- and those are holes in the middle of the series, which is
    # what the complaint is about. The calendar keeps the run off weekends and
    # holidays, where a call costs the same and returns nothing.
    candidates = set(depths) | set(_business_days(start, end))

    # TODAY IS NOT A SETTLE. The 17:00 alias is written from whatever the vendor
    # serves at request time, so warming the current session stamps an intraday
    # print with a settlement key -- the exact confusion `assert_settle_source`
    # exists to prevent, arriving through the back door. A recurring warm must
    # run after settlement and must never reach for the running session.
    today = dt.date.today()

    out: List[Tuple[dt.date, int, List[str]]] = []
    n_protected = 0
    n_unsettled = 0
    for d in sorted(candidates):
        cur = int(depths.get(d, 0))
        if not (start <= d <= end) or cur >= depth:
            continue
        if d >= today:
            n_unsettled += 1
            continue
        if cur >= protect_min_depth:
            n_protected += 1
            continue
        present = have.get(d.isoformat(), set())
        syms = [futures_symbol(y, m) for y, m in quarterly_imm_sequence(d, depth)]
        todo = [s for s in syms if s not in present]
        if todo:
            out.append((d, cur, todo))

    cells = sum(len(t) for _, _, t in out)
    summary = {
        "window": [str(start), str(end)],
        "target_depth": depth,
        "dates_with_eod": len(depths),
        "dates_short": len(out),
        "dates_protected_already_deep": n_protected,
        "dates_skipped_unsettled": n_unsettled,
        "cells_to_fetch": cells,
        "est_seconds": round(sum(3.38 + 0.169 * len(t) + DEFAULT_PAUSE
                                 for _, _, t in out)),
    }
    return out, summary


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def warm_one(mdp, as_of: dt.date, symbols: Sequence[str]) -> Tuple[int, str]:
    """One batched EOD call. Returns ``(n_resolved, error)``; never raises.

    ``timestamp`` is a ``datetime.date`` and NOT a ``datetime`` -- that is what
    sets ``want_eod`` and writes the ``17:00:00`` request alias the universe scan
    reads. Passing a ``datetime`` writes bar-timestamp keys instead and recovers
    nothing while costing exactly the same.
    """
    try:
        snap = mdp.get_data({"symbols": list(symbols), "timestamp": as_of})
        return sum(1 for s in symbols if snap.get(s)), ""
    except Exception as exc:                                   # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"[:200]


def run(
    start: dt.date,
    end: dt.date,
    *,
    depth: int = DEFAULT_DEPTH,
    max_calls: int = DEFAULT_MAX_CALLS,
    pause: float = DEFAULT_PAUSE,
    protect_min_depth: int = 12,
    newest_first: bool = True,
    resume: bool = True,
) -> Dict[str, object]:
    """Fetch, then re-measure. Returns the summary that is also written to disk."""
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    import RVUtils.ConvexityRV.strat2_q20 as Q

    todo, summary = plan(start, end, depth=depth, protect_min_depth=protect_min_depth)
    done: Dict[str, Dict] = {}
    if resume and LEDGER.exists():
        try:
            done = json.loads(LEDGER.read_text(encoding="utf-8")).get("dates", {})
        except Exception:                                      # noqa: BLE001
            done = {}
    todo = [t for t in todo if t[0].isoformat() not in done]

    # Newest first: the visible end of every chart is the most recent date, and a
    # run that is cut short should leave a contiguous block ending at the present
    # rather than a block ending 18 months ago.
    todo.sort(key=lambda t: t[0], reverse=newest_first)
    capped = len(todo) > max_calls
    attempt = todo[:max_calls]

    print(json.dumps(summary, indent=1), flush=True)
    print(f"ledger holds {len(done)} dates; {len(todo)} still to do; "
          f"attempting {len(attempt)}{' (CAPPED)' if capped else ''}", flush=True)

    from MDP.STIRFutures.STIRFutureMDP import SETTLE_SOURCE

    mdp = STIRFutureMDP(source=SETTLE_SOURCE)
    t0 = time.time()
    calls = 0
    for i, (d, cur, syms) in enumerate(attempt, 1):
        t1 = time.time()
        n, err = warm_one(mdp, d, syms)
        calls += 1
        done[d.isoformat()] = {
            "depth_before": int(cur), "requested": len(syms), "resolved": int(n),
            "error": err, "seconds": round(time.time() - t1, 2),
            "at": dt.datetime.now().isoformat(timespec="seconds"),
        }
        # Write through after every date: a kill costs one date, not the run.
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps({"summary": summary, "dates": done}, indent=1),
                          encoding="utf-8")
        print(f"[{i}/{len(attempt)}] {d} depth {cur}->? "
              f"{n}/{len(syms)} resolved {'' if not err else 'ERR ' + err} "
              f"({time.time() - t1:.1f}s, {time.time() - t0:.0f}s total)", flush=True)
        if pause:
            time.sleep(pause)

    # ---- acceptance: re-measure with the SAME reader the panel uses ----------
    after = Q.strip_depth_by_date(
        Q.Q20Config(max_instruments=depth, start=start, end=end), min_depth=1)
    gained = sum(1 for d, cur, _ in attempt if after.get(d, 0) > cur)
    reached = sum(1 for d, _, _ in attempt if after.get(d, 0) >= depth)
    for d, cur, _ in attempt:
        done[d.isoformat()]["depth_after"] = int(after.get(d, 0))

    summary.update({
        "calls_made": calls,
        "wall_clock_s": round(time.time() - t0, 1),
        "dates_gained_depth": gained,
        "dates_at_target": reached,
        "dates_failed": sum(1 for d, _, _ in attempt if after.get(d, 0) <= 0),
        "capped": capped,
        "remaining_dates": max(0, len(todo) - len(attempt)),
    })
    LEDGER.write_text(json.dumps({"summary": summary, "dates": done}, indent=1),
                      encoding="utf-8")
    print("\n" + json.dumps(summary, indent=1), flush=True)
    if calls and gained == 0:
        print("FAILED: fetched dates but MEASURED DEPTH DID NOT MOVE -- the key "
              "shape written and the one the panel reads disagree.", flush=True)
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2025, 1, 1))
    p.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2026, 8, 19))
    p.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    p.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                   help="budget in get_data calls == dates")
    p.add_argument("--pause", type=float, default=DEFAULT_PAUSE)
    p.add_argument("--oldest-first", action="store_true")
    p.add_argument("--protect-min-depth", type=int, default=12,
                   help="leave alone any date already at this depth -- deepening "
                        "it would re-solve its Q20 curve and move its published "
                        "ca_bp_q20. Set 21 to deepen everything.")
    p.add_argument("--no-resume", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)

    import logging

    logging.disable(logging.WARNING)

    if a.dry_run:
        todo, summary = plan(a.start, a.end, depth=a.depth,
                             protect_min_depth=a.protect_min_depth)
        print(json.dumps(summary, indent=1))
        for d, cur, syms in todo[:10]:
            print(f"  {d}  depth {cur:>2} -> fetch {len(syms):>2}: {' '.join(syms[:6])}...")
        print(f"  ... {max(0, len(todo)-10)} more")
        return 0

    s = run(a.start, a.end, depth=a.depth, max_calls=a.max_calls, pause=a.pause,
            protect_min_depth=a.protect_min_depth, newest_first=not a.oldest_first,
            resume=not a.no_resume)
    return 1 if (s["calls_made"] and s["dates_gained_depth"] == 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())

r"""Advance the banked DAILY par grid the EOD CurveStore warm reads.

    conda run -n stir python scripts/citivelo_daily_par_refresh.py refresh
    conda run -n stir python scripts/citivelo_daily_par_refresh.py status

This is the step the nightly warm never had. It is the ONLY scheduled thing that
writes ``DAILY``/``CLOSE`` par tags into the ``CitiVeloTagCache``; everything
downstream of it runs offline.

The hole this fills
-------------------
``citivelo_excel_warm.py warm`` builds one EOD curve per business day out of the
banked daily par grid, offline, through a ``CitiVeloQuotes(offline=True)`` that
CANNOT fetch. So the store advances only as far as the grid does. Nothing on the
nightly schedule advanced the grid: ``citivelo_excel_intraday_warm.py`` hard
limits ``--freq`` to ``MI01``/``MI10``/``HOURLY`` and writes minute par rates
into its OWN ``_intraday_par_cache``, never into the tag cache. Two different
stores, and the nightly only ever touched the one the EOD warm does not read.

Measured on 2026-08-19, the defect in one table - the minute store current on all
five curves, the EOD store frozen on the date a human last ran the harvest:

====================================  ======  ============
CurveStore asset                       days   last
====================================  ======  ============
``USD-SOFR-1D-CITIVELOEXCEL``           5511   2026-08-14
``EUR-ESTR-1D-CITIVELOEXCEL``           5565   2026-08-07
``GBP-SONIA-1D-CITIVELOEXCEL``          4067   2026-08-07
``CAD-CORRA-1D-CITIVELOEXCEL``          2820   2026-08-07
``JPY-TONAR-1D-LCH-CITIVELOEXCEL``      1108   2026-08-07
all five ``-CITIVELOEXCELMIN``             -   2026-08-18
====================================  ======  ============

The visible symptom was "EOD warm exited 1" on six of ten retained nights -
``cmd_warm`` returning "wrote 0 curve-days" because every day it was asked for was
already past the end of the grid. The job was not crashing. It was being asked to
build curves out of data nothing had fetched.

Why this is a new script and not ``--freq DAILY`` on the intraday warm
----------------------------------------------------------------------
That exclusion is deliberate and widening it fails on three independent counts,
each re-verified here rather than taken on trust:

1. **It is structural.** ``fetch_curve`` line 222 is ``window =
   DEFAULT_WINDOW[freq]`` - a bare dict index. ``DEFAULT_WINDOW`` holds only
   ``HOURLY``/``MI01``/``MI10``, so ``--freq DAILY`` raises ``KeyError: 'DAILY'``
   into ``cmd_fetch``'s per-curve ``except Exception`` and returns 0: five
   "FAILED" lines and a green exit. ``window_bounds('DAILY')`` refuses outright -
   *"DAILY is not an intraday frequency"*.
2. **Wrong destination.** Even patched, that path writes per-day parquet into
   ``_intraday_par_cache``. ``windowed.warm_windows``' own docstring records the
   measurement: ``fetch_windowed`` *"writes nothing to the tag cache"* - 349
   bonds / 698 tags "succeeded" in 134 s and left zero parquets.
3. **The chunking is dead weight.** ``MAX_SPAN`` and ``TARGET_SPACING`` have no
   DAILY entry because there is no measured cliff. ``warm_windows`` states the
   rule: *"A frequency with no measured cliff (DAILY and coarser) is fetched in
   ONE request. Chunking it would spend round trips against a threshold that does
   not exist."*

So DAILY is one ``CVTSHIST`` per curve, unchunked, through the same
``fetch_timeseries`` + ``cache.write`` shape the human harvester's
``fetch_and_bank`` uses. That is what this script does.

Argument FORM is the measured failure axis, not span
----------------------------------------------------
``windowed.py`` warns that the ladder "is **not** monotone in the argument form",
and the harvest evidence log settles it. Both rows are the same 44 tags, the same
frequency, the same session - only the arguments differ:

===================================  ==============  ==========================
``fetch_timeseries`` kwargs           served          depth
===================================  ==============  ==========================
``period='15Y'``                      **0/44**, 0.02s  nothing at all
``start=2005-01-01, end=today``       **44/44**, 1.4s  2005-01-03 .. 2026-08-06
===================================  ==============  ==========================

``period='1Y'`` serves 44/44 too, so ``period`` is not broken in general - the
long relative window specifically returns no block. **Explicit ``yyyyMMdd``
bounds, never ``period=``** is therefore the rule here, and the full 21-year
depth in 1.4 s is also the evidence that there is no downsampling to defend
against: one request returned every row the tag has.

Why a TAIL top-up, and why a missing sidecar is a SKIP rather than a deep fetch
------------------------------------------------------------------------------
``start`` is computed from what the cache already holds - the minimum sidecar
``last`` across the curve's own grid, minus :data:`OVERLAP` - rather than from a
constant. The two constants both misbehave, measured:

* ``start=None`` re-requests the entire head every night. No sidecar carries
  ``history_start`` (the ``.meta.json`` files hold ``tag/freq/price_point/
  intraday/fetched_at/n_rows/first/last`` and nothing else), so ``Coverage.
  complete_back`` is False for ever.
* ``start=2005-01-01`` asks for history that cannot exist: ``cov.first`` is
  2010-11-26 for ``GBP_SONIA.PAR.2Y`` and 2015-10-08 for ``JPY_TONAR_LCH``, so a
  head span is emitted, unfillable, once per span-group, every night, for ever.

A tag with NO sidecar is a different question and deliberately not answered here.
It means this curve has never been banked at DAILY, which is a deep-history fetch
(21 years, the harvester's stage W) and not a nightly tail. Guessing a start for
it would bank a truncated grid that looks complete, and a truncated grid is worse
than an absent one because the EOD warm would then happily build curves from it.
So the curve is SKIPPED and the harvest is named. **The deep head remains a
manual harvest; only the tail is automated.**

``OVERLAP`` re-requests a few days that are already banked. ``CitiVeloTagCache.
write`` merges rather than replaces, so the cost is a few rows on the wire and
the benefit is that a day which was partially published when it was first fetched
gets corrected rather than frozen.

Exit codes
----------
``0``  every curve is current, or was advanced.
``1``  the transport did not answer - see :data:`BENIGN_FAILURE_REASONS`. A real
       defect; the tag cache is unchanged for the curves that failed.
``3``  nothing was fetched because a human has to act first: Excel is not usable,
       or a curve has never been banked at DAILY. Not a failure - the caller
       reports it as SKIPPED, which is why it is a distinct code and not 1.

3 covers the Excel outage as well as the unbanked curve, and that is not tidiness:
the nightly's pre-flight only proves Excel was usable when the JOB started, and
Excel is measured crossing the ceiling mid-run (2026-08-11, jobs 1-6 fine, jobs
9-11 refused at 3,886 MB). An uncaught raise here would exit 1 and be recorded as
a FAILED step - the opaque nightly failure this file exists to remove, re-created
one layer down. Nothing is banked in either case, because the guard refuses
before connecting.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import pathlib
import sys
from typing import Dict, List, Optional, Sequence, Tuple

# Read before anything imports ``Caching``: this script never pushes L2, and the
# env var is read once at import time. Same discipline as the sibling warms.
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

LOGGER = logging.getLogger(__name__)

#: The five curves the EOD CurveStore warm builds.
#:
#: Character-for-character ``_CITIVELO_CURVES`` in ``scripts/daily_cache_warmer.py``,
#: which passes ``--curves`` explicitly - so this default matters only for a
#: human running the script by hand. It is kept in step anyway because the
#: divergence that matters is silent: ``JPY-TONAR-1D`` and ``JPY-TONAR-1D-LCH``
#: are DIFFERENT Citi indices (``JPY_TONAR`` vs ``JPY_TONAR_LCH``) with their own
#: banked grids, so a hand-run refresh against the wrong one would advance a grid
#: the nightly never reads and leave the real one exactly as stale.
DEFAULT_CURVES = "USD-SOFR-1D,EUR-ESTR-1D,GBP-SONIA-1D,CAD-CORRA-1D,JPY-TONAR-1D-LCH"

#: How far back before the last banked row to start the request.
#:
#: Not a guess about calendars: a request from exactly ``last`` would re-fetch
#: one row and trust that every row before it was complete when it was written.
#: Seven calendar days covers a weekend plus a holiday either side, costs a
#: handful of rows on a wire that served 21 years in 1.4 s, and lets a day that
#: was partially published at first fetch be corrected by the merge in
#: ``CitiVeloTagCache.write``.
OVERLAP = datetime.timedelta(days=7)

#: Per-tag failure reasons that mean "the wire answered, this tag had nothing",
#: as opposed to "there was no readable block at all".
#:
#: Identical in meaning and membership to the set in
#: ``scripts/citivelo_ust_universe_warm.py``, and deliberately duplicated rather
#: than imported: that module pulls in the bond universe and a COM fetcher on
#: import, and this script must be able to say "the grid is stale" without any of
#: it. If one moves, move both - the docstring there carries the measurement.
#:
#: Unknown reasons fall in the FAULT set on purpose. A reason nobody has seen is
#: not evidence that the wire is healthy.
BENIGN_FAILURE_REASONS = frozenset({"empty", "bad tag", "no column"})

#: Excel measured above this refuses to be connected to. Matches the ceiling the
#: nightly warmer passes its other Velocity fetch steps; the add-in's series cache
#: only ever grows and only a human restart clears it, and a 528-window run wedged
#: Excel at 5,249 MB on 2026-08-07.
DEFAULT_CEILING_MB = 3000.0


def _curves(arg: str) -> List[str]:
    return [c.strip().upper() for c in str(arg).split(",") if c.strip()]


def _transport_faults(reported) -> Dict[str, str]:
    """The subset of ``{tag: reason}`` that means the transport did not answer."""
    if not reported:
        return {}
    return {
        str(tag): str(why)
        for tag, why in reported.items()
        if str(why).strip().lower() not in BENIGN_FAILURE_REASONS
    }


def _sidecar_last(cache, tag: str) -> Optional[datetime.date]:
    """The newest DAILY row the sidecar claims for ``tag``, or ``None``.

    The sidecar is authoritative and that is measured rather than assumed:
    ``CitiVeloTagCache.write`` writes ``first``/``last``/``n_rows`` from the
    MERGED series on every write, and on a hand-checked sample the sidecar
    ``last`` equalled the parquet's own maximum timestamp every time. Reading it
    costs a small JSON read instead of parsing a 5,500-row parquet, which is what
    makes asking all 44 tags of all five curves free.
    """
    path = cache.meta_path(str(tag), "DAILY")
    if not path.is_file():
        return None
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable sidecar is a miss, not a crash
        return None
    raw = meta.get("last")
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def grid_coverage(citi_index: str, *, cache=None) -> Tuple[List[str], Dict[str, Optional[datetime.date]]]:
    """``(tags, {tag: last banked DAILY row})`` for one curve's whole par grid.

    ``None`` for a tag means no sidecar at all - never banked at DAILY. That is
    the state this script refuses to guess a start for; see the module docstring.
    """
    from MDP.CitiVelocityExcel import tags as T

    if cache is None:
        from MDP.CitiVelocityExcel.cache import CitiVeloTagCache, default_cache_dir

        cache = CitiVeloTagCache(base_dir=default_cache_dir())
    grid = list(T.ois_par_grid(citi_index))
    return grid, {tag: _sidecar_last(cache, tag) for tag in grid}


def plan_window(
    coverage: Dict[str, Optional[datetime.date]],
    *,
    end: datetime.date,
    overlap: datetime.timedelta = OVERLAP,
) -> Tuple[Optional[datetime.date], str]:
    """``(start, reason)`` for one curve's refresh request.

    ``start is None`` means do not fetch, and ``reason`` says which of the two
    non-fetching outcomes it is:

    ``"never banked"``
        At least one tag has no sidecar. A deep harvest, not a nightly tail.
    ``"current"``
        Every tag already holds a row on or after ``end``. Nothing to ask for.

    Otherwise ``start`` is the OLDEST tag's last row minus ``overlap``. The
    minimum rather than the maximum on purpose: the tags of one grid do not all
    stop on the same day (the long end of a curve prints less often than the
    belly), and starting from the newest would leave the laggards permanently
    behind by exactly the amount they lag.
    """
    if not coverage:
        return None, "never banked"
    if any(last is None for last in coverage.values()):
        return None, "never banked"
    oldest = min(last for last in coverage.values() if last is not None)
    if oldest >= end:
        return None, "current"
    return oldest - overlap, "refresh"


def refresh_curve(
    curve_name: str,
    *,
    client,
    cache,
    end: datetime.date,
    overlap: datetime.timedelta = OVERLAP,
    logger: logging.Logger = LOGGER,
) -> Dict[str, object]:
    """One ``CVTSHIST`` for one curve's par grid, banked before returning.

    Returns a record rather than raising, so one curve that has never been banked
    does not deny the other four their tail. The caller aggregates.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name

    entry = entry_for_curve_name(curve_name)
    grid, coverage = grid_coverage(entry.citi_index, cache=cache)
    start, why = plan_window(coverage, end=end, overlap=overlap)
    banked = min((d for d in coverage.values() if d is not None), default=None)
    record: Dict[str, object] = {
        "curve": entry.curve_name, "citi_index": entry.citi_index,
        "tags": len(grid), "banked_to": banked, "outcome": why,
        "written": 0, "faults": {},
    }
    if start is None:
        return record

    # EXPLICIT BOUNDS, never ``period=``. See the module docstring: the same 44
    # tags served 0/44 in 0.02 s with ``period='15Y'`` and 44/44 in 1.4 s with
    # explicit dates. This is the one call that matters and the form is the
    # measured difference between it working and it silently doing nothing.
    logger.info("%s (%s): banked to %s, asking %s .. %s for %d tag(s)",
                entry.curve_name, entry.citi_index, banked, start, end, len(grid))
    series = client.fetch_timeseries(
        grid, "DAILY", price_point="CLOSE", start=start, end=end
    )
    faults = _transport_faults(client.last_failures())
    record["faults"] = faults
    if faults:
        # Nothing is banked from a request whose block did not come back. A
        # partial write here would move the sidecar ``last`` forward on the tags
        # that happened to answer, which is exactly the "green while stale" shape
        # this whole change exists to remove.
        record["outcome"] = "fault"
        return record

    written = 0
    for tag, s in series.items():
        if s is not None and len(s):
            cache.write(tag, "DAILY", s, price_point="CLOSE")
            written += 1
    record["written"] = written
    record["outcome"] = "refreshed" if written else "served nothing"
    return record


def refresh(
    curve_names: Sequence[str],
    *,
    end: Optional[datetime.date] = None,
    overlap: datetime.timedelta = OVERLAP,
    ceiling_mb: float = DEFAULT_CEILING_MB,
    client=None,
    cache=None,
    logger: logging.Logger = LOGGER,
) -> List[Dict[str, object]]:
    """:func:`refresh_curve` over several curves, sharing one Excel connection.

    The connection is opened LAZILY - only once a curve is known to need one - so
    a night on which every grid is already current touches no Excel at all.
    """
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache, default_cache_dir

    end = end or datetime.date.today()
    if cache is None:
        cache = CitiVeloTagCache(base_dir=default_cache_dir())

    owned = None
    out: List[Dict[str, object]] = []
    try:
        for name in curve_names:
            if client is None and owned is None:
                # Does THIS curve need a wire at all? Asked before connecting,
                # because "every grid is current" must cost zero Excel.
                from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name

                _, cov = grid_coverage(entry_for_curve_name(name).citi_index, cache=cache)
                if plan_window(cov, end=end, overlap=overlap)[0] is None:
                    out.append(refresh_curve(name, client=None, cache=cache, end=end,
                                             overlap=overlap, logger=logger))
                    continue
                # PRE-CONNECT, not post. A guard placed after the connection has
                # already done the thing it was meant to prevent - and the add-in
                # gives memory back only to a human restart, so connecting to a
                # bloated Excel wedges it for whoever sits down next.
                from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
                from MDP.CitiVelocityExcel.memory_guard import assert_safe_to_connect

                mb = assert_safe_to_connect(ceiling_mb, what="the DAILY par refresh")
                logger.info("Excel at %.0f MB, under the %.0f MB ceiling; connecting",
                            mb, ceiling_mb)
                owned = CitiVelocityExcelClient.connect(workbook_tag="WARM")
            out.append(refresh_curve(name, client=client or owned, cache=cache, end=end,
                                     overlap=overlap, logger=logger))
    finally:
        if owned is not None:
            try:
                owned.close()
            except Exception:  # noqa: BLE001 - a close that fails must not lose the bank
                logger.warning("could not close the Excel client cleanly", exc_info=True)
    return out


def _report(records: Sequence[Dict[str, object]], logger: logging.Logger) -> int:
    """Print the per-curve outcome and turn it into the process exit code."""
    for r in records:
        logger.info("  %-22s %-14s banked_to=%s written=%s%s",
                    r["curve"], r["outcome"], r["banked_to"], r["written"],
                    f" faults={len(r['faults'])}" if r["faults"] else "")

    faulted = [r for r in records if r["outcome"] == "fault"]
    if faulted:
        lead = faulted[0]
        shown = ", ".join(f"{t} ({why})" for t, why in sorted(lead["faults"].items())[:4])
        # Printed LAST so a caller that keeps only the child's final line keeps
        # the cause. The nightly warmer's ``_last_meaningful_line`` does exactly
        # that, and "EOD warm exited 1" naming no cause is the failure mode that
        # made this whole change necessary.
        print(f"TRANSPORT FAULT on {len(faulted)} curve(s): {lead['curve']}: {shown}. "
              f"Nothing was banked for them; the next run retries.", flush=True)
        return 1

    # ANY never-banked curve returns 3, even when the other four advanced. That
    # curve's grid cannot move without a human, so a run that quietly exits 0
    # because its siblings worked is the same "green while stale" shape as the
    # bug this file exists to remove. The per-curve lines above still show what
    # did advance.
    never = [r for r in records if r["outcome"] == "never banked"]
    if never:
        names = ", ".join(str(r["curve"]) for r in never)
        print(f"SKIPPED: {names} has never been banked at DAILY, which is a "
              f"21-year deep fetch and not a nightly tail. Run the harvest: "
              f"python MDP/CitiVelocityExcel/harvest/harvest_curve_modes.py --stages W",
              flush=True)
        return 3
    return 0


def _excel_unavailable_errors():
    """The exception types that mean "Excel was not usable", not "this is broken".

    Imported lazily and defensively, exactly as the nightly warmer does it: an
    empty tuple is a valid ``except`` clause that matches nothing, so a Velocity
    bridge that will not import costs the reclassification and nothing else.
    """
    try:
        from MDP.CitiVelocityExcel.errors import AddInNotSignedInError, ExcelNotRunningError
        from MDP.CitiVelocityExcel.memory_guard import ExcelTooLargeError
    except Exception:  # noqa: BLE001
        return ()
    return (ExcelNotRunningError, AddInNotSignedInError, ExcelTooLargeError)


def cmd_refresh(args) -> int:
    end = datetime.date.fromisoformat(args.end) if args.end else datetime.date.today()
    try:
        records = refresh(_curves(args.curves), end=end,
                          overlap=datetime.timedelta(days=int(args.overlap_days)),
                          ceiling_mb=args.ceiling_mb)
    except _excel_unavailable_errors() as exc:
        # AN EXCEL OUTAGE IS A SKIP, AND WITHOUT THIS IT WOULD BE A FAILURE.
        #
        # The nightly's pre-flight only proves Excel was usable when job 7
        # STARTED. The environment degrades mid-run and that is measured: on
        # 2026-08-11 jobs 1-6 completed normally and jobs 9-11 then refused at
        # 3,886 MB. So this step can be reached with Excel over the ceiling, shut,
        # or signed out, and an uncaught raise here exits 1 - which the parent
        # records as a FAILED step, which is precisely the opaque nightly failure
        # this whole change removes, re-created one layer down.
        #
        # Nothing was banked: ``assert_safe_to_connect`` refuses BEFORE the
        # connection, so the tag cache is untouched and the next run retries.
        print(f"SKIPPED: Excel is not usable ({type(exc).__name__}: {exc}). Nothing "
              f"was banked and nothing was changed - open or restart Excel, sign in "
              f"to Velocity, and the next nightly run advances the grid.", flush=True)
        return 3
    return _report(records, LOGGER)


def cmd_status(args) -> int:
    """What the grid holds, offline. Never connects, so it is safe any time."""
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache, default_cache_dir
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name

    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    end = datetime.date.fromisoformat(args.end) if args.end else datetime.date.today()
    print(f"{'curve':<22}{'index':<16}{'tags':>6}{'banked_to':>13}{'missing':>9}  outcome")
    for name in _curves(args.curves):
        entry = entry_for_curve_name(name)
        grid, cov = grid_coverage(entry.citi_index, cache=cache)
        missing = sum(1 for v in cov.values() if v is None)
        _, why = plan_window(cov, end=end)
        banked = min((d for d in cov.values() if d is not None), default=None)
        print(f"{entry.curve_name:<22}{entry.citi_index:<16}{len(grid):>6}"
              f"{str(banked):>13}{missing:>9}  {why}")
    # Always 0. ``status`` is a report, and the nightly runs it through ``_run``,
    # which records ANY non-zero child as a failed step - so a status that
    # editorialised with an exit code would re-create the opaque nightly failure
    # this change removes. The outcome column is the answer.
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__ or "")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("refresh", help="advance the banked DAILY par grid")
    r.add_argument("--curves", default=DEFAULT_CURVES)
    r.add_argument("--end", default="")
    r.add_argument("--overlap-days", type=int, default=OVERLAP.days)
    r.add_argument("--ceiling-mb", type=float, default=DEFAULT_CEILING_MB)
    r.set_defaults(func=cmd_refresh)

    s = sub.add_parser("status", help="what the grid holds, offline")
    s.add_argument("--curves", default=DEFAULT_CURVES)
    s.add_argument("--end", default="")
    s.set_defaults(func=cmd_status)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

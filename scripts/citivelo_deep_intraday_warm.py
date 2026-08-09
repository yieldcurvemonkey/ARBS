r"""Warm the minute CurveStore back to Citi's ACTUAL intraday floor, unattended.

``scripts/citivelo_excel_intraday_warm.py`` already fetches minute par grids and
solves them into ``<curve>-CITIVELOEXCELMIN``. What it has never been given is
(a) how far back each curve can actually go, and (b) permission to keep going
when Excel fills up. This driver supplies both, and it walks **newest-first** so
an interrupted run has left the recent history behind rather than a hole in the
middle.

Where the floors come from
--------------------------
``scripts/citivelo_snap_depth_probe.py``, run live on 2026-08-09, bisected each
curve's floor to +/-21 days and separated two things that had been conflated:

===============  =============  ============  ===================================
curve            1-minute from  intraday from note
===============  =============  ============  ===================================
USD_SOFR         2021-09-15     2021-09-15
USD_FEDFUND      2018-09-05     2017-12-06    sparse era ~8-10 min, 15-18 tenors
EUR_EUROSTR      2021-09-15     2021-09-15
EUR_EURIBOR      2016-07-06     2016-07-06    not an OIS index - see below
JPY_TONAR        2017-12-06     2017-12-06    sparse era ~600 prints/day
JPY_TONAR_LCH    2024-01-17     2024-01-17    the CCP-split twin is much shorter
EUR_EONIA        <= 2018-01-10  <= 2018-01-10 the pre-ESTR euro discount curve
===============  =============  ============  ===================================

Two corrections to earlier belief are baked in here.

**``CVTSHIST`` was never capped at two years.** The two-year figure was the
*span* cliff - the add-in silently downsamples a request wider than six days -
and :mod:`MDP.CitiVelocityExcel.windowed` has handled that since 2026-08-07.
Retention is four to ten years depending on the curve.

**``CVSNAP`` cannot extend any of this.** It was measured against ``CVTSHIST`` on
all six curves: identical to the digit where both serve (0.0 bp), and empty at
every instant below the floor - 0 of 3 snaps at 30, 120 and 365 days under it,
on every curve. The one apparent exception (``USD_FEDFUND`` answering 168 days
under its floor) was our own measurement's fault: the floor test asked "is the
median spacing one minute?", and below its dense era that curve still serves
~330 rows over four days at ~8-minute spacing. ``CVTSHIST`` serves those same
instants. The stores are the same store.

**The sparse era is synchronous, not ragged.** Measured on 2018-03-14: every one
of the 224 published stamps carries all 15 available tenors, so the ordinary
build path solves them without changes. That is what removes the last thing a
snap grid could have been for - manufacturing a simultaneous cross-section.

Running it
----------
::

    python scripts/citivelo_deep_intraday_warm.py plan
    python scripts/citivelo_deep_intraday_warm.py fetch --auto-restart
    python scripts/citivelo_deep_intraday_warm.py build --workers 8
    python scripts/citivelo_deep_intraday_warm.py verify --per-era 5
    python scripts/citivelo_deep_intraday_warm.py status

**Start ``fetch`` DETACHED**, not as a child of a shell you might stop::

    Start-Process -FilePath <env>\python.exe -WindowStyle Hidden `
        -ArgumentList '-u','scripts\citivelo_deep_intraday_warm.py','fetch','--auto-restart' `
        -RedirectStandardError logs\deep_intraday_fetch.err

Excel is started as a child of whatever runs this, so killing the backfill takes
its Excel with it and the next run pays a fresh 13-25 minute sign-in. The driver
recovers - it launches Excel when there is none - but the twenty minutes are
real. Progress is in the log and in ``_deep_warm_ledger.json`` beside the day
files; ``plan`` re-run shows the remaining chunk count shrinking.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from citivelo_excel_intraday_warm import (  # noqa: E402
    MemoryCeilingReached,
    _default_work_dir,
    asset_name,
    fetch_curve,
)

LOGGER = logging.getLogger("citivelo_deep_intraday_warm")


@dataclass(frozen=True)
class Horizon:
    """One curve's measured intraday reach.

    ``dense_from`` is where true one-minute data starts. ``intraday_from`` is
    where ANY intraday data starts - for two curves that is materially earlier,
    and those days are worth having: they are fewer curves per day, not worse
    ones.
    """

    curve_name: str
    dense_from: datetime.date
    intraday_from: datetime.date
    note: str = ""
    #: An upper bound on what is worth fetching. Set only where the series is
    #: RETIRED or where this warm needs it for a bounded purpose - EONIA is
    #: fetched to discount the pre-ESTR EURIBOR era and nothing else, so paying
    #: for its 2021-2025 tail would be four wasted Excel sessions.
    until: Optional[datetime.date] = None

    @property
    def start(self) -> datetime.date:
        return self.intraday_from


def _d(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text)


#: MEASURED 2026-08-09 by ``scripts/citivelo_snap_depth_probe.py``; the raw
#: bisection trail is in ``analysis_outputs/snap_probe_floor2.json``. Each floor
#: is the newer end of a +/-21 day bracket, so it is the CONSERVATIVE date - the
#: true floor is at or before it and the fetch simply returns nothing for the
#: windows in between.
HORIZONS: Dict[str, Horizon] = {
    h.curve_name: h
    for h in (
        Horizon("USD-SOFR-1D", _d("2021-09-15"), _d("2021-09-15")),
        Horizon("USD-FEDFUNDS-1D", _d("2018-09-05"), _d("2017-12-06"),
                "sparse below 2018-09: ~8-10 min spacing, 15-18 of 44 tenors"),
        Horizon("EUR-ESTR-1D", _d("2021-09-15"), _d("2021-09-15")),
        Horizon("JPY-TONAR-1D", _d("2017-12-06"), _d("2017-12-06"),
                "the uncleared/legacy TONAR reaches 6 years deeper than JPY-TONAR-1D-LCH"),
        Horizon("EUR-EURIBOR-6M", _d("2016-07-06"), _d("2016-07-06"),
                "RATES.SWAP_LIBOR.EUR - the deepest intraday series Citi serves, and "
                "the only one that predates the 2017-12-06 archive epoch"),
        Horizon("EUR-EONIA-1D", _d("2017-12-06"), _d("2017-12-06"),
                "retired 2025-08-15; it exists here to DISCOUNT the pre-ESTR EURIBOR era, "
                "so it is fetched only up to where EUR-ESTR-1D takes over",
                until=_d("2021-10-01")),
        Horizon("GBP-SONIA-1D", _d("2021-09-15"), _d("2021-09-15"),
                "not probed; assumed to follow the other RFR curves - verify before trusting"),
        Horizon("CAD-CORRA-1D", _d("2021-09-15"), _d("2021-09-15"),
                "not probed; assumed to follow the other RFR curves - verify before trusting"),
        Horizon("JPY-TONAR-1D-LCH", _d("2024-01-17"), _d("2024-01-17")),
    )
}

#: What the ten-year request actually resolves to. The ORDER of this tuple is not
#: the order the fetch runs in - :func:`_work_queue` interleaves these
#: round-robin so an interrupted run has covered every curve rather than the
#: first two. ``EUR-EONIA-1D`` is not itself a requested curve: it is the
#: discount curve the pre-2021 EURIBOR era needs, and fetching it is what keeps
#: that era from being self-discounted.
DEFAULT_CURVES: Tuple[str, ...] = (
    "USD-SOFR-1D",
    "EUR-ESTR-1D",
    "USD-FEDFUNDS-1D",
    "JPY-TONAR-1D",
    "EUR-EURIBOR-6M",
    "EUR-EONIA-1D",
)


def tags_and_zone_for(curve_name: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """The par grid and session zone for a curve the OIS lookup cannot resolve.

    ``(None, None)`` means "use the ordinary OIS path", which is every RFR curve.
    Only ``RATES.SWAP_LIBOR`` needs this: it is not an OIS index, has no
    ``curve_names`` entry, and its tenor axis is its own (36 tenors, no 1D/2W/3W
    and no 35Y/45Y).
    """
    from MDP.CitiVelocityExcel.curves.ibor_builder import IBOR_CURVES, par_grid_tags

    spec = IBOR_CURVES.get(str(curve_name).strip().upper())
    if spec is None:
        return None, None
    return list(par_grid_tags(spec)), spec.local_timezone


@dataclass
class CurvePlan:
    curve_name: str
    start: datetime.date
    end: datetime.date
    business_days: int = 0
    on_disk: int = 0
    in_store: int = 0
    chunks: List[Tuple[datetime.date, datetime.date]] = field(default_factory=list)

    @property
    def missing(self) -> int:
        return max(0, self.business_days - self.on_disk)


def _business_days(start: datetime.date, end: datetime.date) -> int:
    import pandas as pd

    if end <= start:
        return 0
    return int(len(pd.bdate_range(start, end - datetime.timedelta(days=1))))


#: A stored day with at least this many curve snapshots is treated as already
#: dense enough and is not refetched. Below it, the day is refetched at MI01 -
#: which is how the 2022-08..2023-12 stretch of ``USD-SOFR-1D-CITIVELOEXCELMIN``
#: gets UPGRADED rather than skipped: it holds ~130 curves per day (ten-minute
#: data acquired before the span cliff was understood) against ~1,250 for a real
#: minute day, and it currently reads as "covered".
DEFAULT_MIN_STORE_CURVES = 600


def _stored_curve_count(store: Any, asset: str, day: datetime.date) -> int:
    """How many curve snapshots the store holds for one day, from PARQUET METADATA.

    One row is one curve (nodes are list columns), so ``num_rows`` is the count
    without reading a single value. Cheap enough to run over thousands of days
    while planning.
    """
    import pyarrow.parquet as pq

    try:
        partition = store.raw_partition_dir(asset, day)
    except Exception:  # noqa: BLE001
        return 0
    if not partition.exists():
        return 0
    total = 0
    for path in partition.glob("*.parquet"):
        try:
            total += int(pq.ParquetFile(path).metadata.num_rows)
        except Exception:  # noqa: BLE001 - a corrupt file is "not enough", not a crash
            continue
    return total


def plan_curve(
    curve_name: str,
    *,
    work_dir: Path,
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
    chunk_days: int = 60,
    min_store_curves: int = DEFAULT_MIN_STORE_CURVES,
) -> CurvePlan:
    """What is left to fetch for one curve, chunked NEWEST-FIRST.

    Chunking exists for one reason: ``fetch_curve`` walks forward from its
    ``start``, so a single call over five years would spend its first hour in
    2017 and lose everything if Excel died. Sixty-day chunks issued newest-first
    make the run's progress monotone in usefulness.

    A business day is considered done when its parquet is already in the work
    directory **or** the store already holds a dense day for it. Both halves
    matter: the first makes a re-run cheap, the second stops a fresh worktree
    (the work directory is repo-relative and therefore per-worktree) from
    refetching four years that are already solved.
    """
    from Caching.curve_store import CurveStore

    import pandas as pd

    horizon = HORIZONS.get(curve_name)
    lo = start or (horizon.start if horizon else _d("2021-09-15"))
    hi = end or (horizon.until if horizon and horizon.until else datetime.date.today())
    curve_dir = work_dir / curve_name
    on_disk = {
        datetime.date.fromisoformat(p.stem)
        for p in curve_dir.glob("*.parquet")
    } if curve_dir.exists() else set()

    store = CurveStore.default()
    asset = asset_name(curve_name)
    # The density threshold only applies where dense data EXISTS. Below a curve's
    # dense_from, Citi publishes a few hundred prints a day at best, so a flat
    # "600 curves or refetch" rule would mark every sparse-era day thin forever
    # and re-run those Excel windows on every invocation.
    dense_from = horizon.dense_from if horizon else lo
    stored_dense = set()
    for d in store.available_dates(asset):
        if not (lo <= d < hi):
            continue
        threshold = min_store_curves if d >= dense_from else 1
        if _stored_curve_count(store, asset, d) >= threshold:
            stored_dense.add(d)

    plan = CurvePlan(curve_name=curve_name, start=lo, end=hi)
    plan.business_days = _business_days(lo, hi)
    plan.on_disk = sum(1 for d in on_disk if lo <= d < hi)
    plan.in_store = len(stored_dense)

    done = on_disk | stored_dense
    cursor = hi
    while cursor > lo:
        chunk_start = max(lo, cursor - datetime.timedelta(days=chunk_days))
        wanted = [
            d.date() for d in pd.bdate_range(chunk_start, cursor - datetime.timedelta(days=1))
        ]
        if any(d not in done for d in wanted):
            plan.chunks.append((chunk_start, cursor))
        cursor = chunk_start
    return plan


def cmd_plan(args, logger: logging.Logger) -> int:
    work_dir = Path(args.work_dir) if args.work_dir else _default_work_dir()
    print(f"{'curve':<20}{'from':<13}{'to':<13}{'bdays':>7}{'on disk':>9}"
          f"{'in store':>10}{'chunks':>8}  note")
    total_chunks = 0
    for curve in _curves(args):
        plan = plan_curve(curve, work_dir=work_dir, start=_opt_date(args.start),
                          end=_opt_date(args.end), chunk_days=args.chunk_days,
                          min_store_curves=args.min_store_curves)
        total_chunks += len(plan.chunks)
        note = (HORIZONS.get(curve).note if HORIZONS.get(curve) else "") or ""
        print(f"{curve:<20}{str(plan.start):<13}{str(plan.end):<13}{plan.business_days:>7}"
              f"{plan.on_disk:>9}{plan.in_store:>10}{len(plan.chunks):>8}  {note}")
    print(f"\n{total_chunks} chunk(s) of up to {args.chunk_days} days to fetch, newest first.")
    print("A chunk is skipped only when EVERY business day in it is already on disk.")
    return 0


def _opt_date(text: Optional[str]) -> Optional[datetime.date]:
    return datetime.date.fromisoformat(text) if text else None


def _curves(args) -> List[str]:
    raw = getattr(args, "curves", "") or ""
    if not raw.strip():
        return list(DEFAULT_CURVES)
    return [c.strip() for c in raw.split(",") if c.strip()]


def cmd_fetch(args, logger: logging.Logger) -> int:
    """Drive Excel until the plan is empty or the restart budget runs out.

    The restart is the whole point of this command existing. ``fetch_curve``
    raises :class:`MemoryCeilingReached` when recycling the scratch workbook can
    no longer hold the add-in below its ceiling; the only cure is a process
    restart, which takes 13-25 minutes of silent re-authentication. Doing that
    by hand once per ~600 business days is what has kept this backfill at two
    years.

    .. warning::
       **The ceiling is enforced HERE, between chunks, not only inside
       ``fetch_curve``.** That function counts the windows *it* has run and
       checks Excel every ``recycle_every`` of them. A driver that calls it once
       per 60-day chunk resets that counter every 12 windows, so a
       ``recycle_every`` of 25 never fires at all. Measured on the first real
       run: Excel went 1,811 -> 4,573 MB across 84 windows with the guard
       silently inert, ~700 MB short of the 5,249 MB that wedged it in August.
       The between-chunks check below does not depend on the inner counter, and
       ``--recycle-every`` now defaults below the windows-per-chunk count so the
       inner one fires as well.
    """
    from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient

    work_dir = Path(args.work_dir) if args.work_dir else _default_work_dir()
    ledger = work_dir / "_deep_warm_ledger.json"
    state: Dict[str, Any] = {"started": datetime.datetime.now().isoformat(timespec="seconds"),
                             "restarts": 0, "chunks_done": 0, "days_written": 0, "errors": []}

    client = _connect_or_restart(args, logger)

    plans: Dict[str, CurvePlan] = {}
    for curve in _curves(args):
        plan = plan_curve(curve, work_dir=work_dir, start=_opt_date(args.start),
                          end=_opt_date(args.end), chunk_days=args.chunk_days,
                          min_store_curves=args.min_store_curves)
        plans[curve] = plan
        logger.info("=== %s: %d chunk(s), %s -> %s (%d bdays, %d on disk, %d dense in store) ===",
                    curve, len(plan.chunks), plan.start, plan.end,
                    plan.business_days, plan.on_disk, plan.in_store)

    queue = _work_queue(plans, interleave=not args.no_interleave)
    logger.info("%d chunk(s) queued %s",
                len(queue), "round-robin across curves" if not args.no_interleave
                else "curve by curve")

    tag_cache = {c: tags_and_zone_for(c) for c in plans}
    restarts = 0
    index = 0
    try:
        while index < len(queue):
            curve, chunk_start, chunk_end = queue[index]
            tags, zone = tag_cache[curve]
            t0 = time.time()
            try:
                days, windows = fetch_curve(
                    curve, chunk_start, chunk_end,
                    work_dir=work_dir, client=client, force=args.force,
                    freq=args.freq, recycle_every=args.recycle_every,
                    memory_ceiling_mb=args.memory_ceiling_mb,
                    memory_abort_mb=args.memory_abort_mb,
                    tags=tags, timezone=zone, logger=logger,
                )
            except MemoryCeilingReached as exc:
                if not args.auto_restart or restarts >= args.max_restarts:
                    logger.warning(
                        "%s stopped at %s..%s: %s. %s",
                        curve, chunk_start, chunk_end, exc,
                        "Re-run to resume - everything fetched is on disk."
                        if not args.auto_restart
                        else f"restart budget exhausted ({restarts}/{args.max_restarts}).",
                    )
                    state["errors"].append(f"{curve} {chunk_start}: {exc}")
                    _write_ledger(ledger, state)
                    return 3
                restarts += 1
                state["restarts"] = restarts
                logger.warning("Excel is full (%s). Restart %d/%d.",
                               exc, restarts, args.max_restarts)
                client = _restart(client, args, logger)
                continue  # SAME chunk, on a fresh Excel
            except Exception as exc:  # noqa: BLE001 - one chunk must not end the run
                logger.error("%s %s..%s FAILED: %s: %s",
                             curve, chunk_start, chunk_end, type(exc).__name__, exc)
                state["errors"].append(f"{curve} {chunk_start}: {type(exc).__name__}: {exc}")
                index += 1
                continue

            used = client.excel_memory_mb()
            state["chunks_done"] += 1
            state["days_written"] += days
            state["excel_mb"] = used
            state["last"] = f"{curve} {chunk_start}..{chunk_end}"
            logger.info(
                "[%d/%d] %s %s..%s: %d day(s) from %d window(s) in %.0fs  [Excel %.0f MB]",
                index + 1, len(queue), curve, chunk_start, chunk_end, days, windows,
                time.time() - t0, used,
            )
            _write_ledger(ledger, state)
            index += 1

            # The guard that does not depend on the inner window counter.
            if used >= args.memory_ceiling_mb:
                if not args.auto_restart or restarts >= args.max_restarts:
                    logger.warning(
                        "Excel is at %.0f MB, at or over the %.0f MB ceiling, and "
                        "%s. Stopping - %d day file(s) are on disk and a re-run resumes.",
                        used, args.memory_ceiling_mb,
                        "auto-restart is off" if not args.auto_restart
                        else f"the restart budget is spent ({restarts}/{args.max_restarts})",
                        state["days_written"],
                    )
                    _write_ledger(ledger, state)
                    return 3
                restarts += 1
                state["restarts"] = restarts
                logger.warning(
                    "Excel at %.0f MB >= %.0f MB ceiling after %d chunk(s). Restart %d/%d.",
                    used, args.memory_ceiling_mb, state["chunks_done"],
                    restarts, args.max_restarts,
                )
                _write_ledger(ledger, state)
                client = _restart(client, args, logger)
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
    state["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    _write_ledger(ledger, state)
    logger.info("deep fetch complete: %d chunk(s), %d day file(s), %d restart(s), %d error(s)",
                state["chunks_done"], state["days_written"], state["restarts"],
                len(state["errors"]))
    return 1 if state["errors"] else 0


def _work_queue(
    plans: Dict[str, CurvePlan], *, interleave: bool = True
) -> List[Tuple[str, datetime.date, datetime.date]]:
    """Every chunk to fetch, ordered so that stopping early costs the least.

    Two orderings, and the difference only shows up when the run does not finish
    - which, at ~20 hours and a 13-25 minute Excel restart every five or six
    chunks, is the case worth designing for.

    **Curve by curve** finishes ``USD-SOFR-1D`` completely and may never reach
    ``JPY-TONAR-1D`` at all.

    **Round-robin** (the default) takes one chunk from each curve in turn, so a
    run cut off at any point has walked all five curves back to roughly the same
    date. Every curve is already fetched newest-first, so that date is the recent
    past - the part a reader asks for first. Five curves at three years each is a
    more useful cache than two curves at ten and three at nothing, and the ask
    named all five.

    It costs nothing: each chunk is an independent ``fetch_curve`` call with its
    own tag list, and the add-in has no per-curve state to warm.
    """
    ordered = [(c, p) for c, p in plans.items() if p.chunks]
    if not interleave:
        return [(c, s, e) for c, p in ordered for s, e in p.chunks]
    out: List[Tuple[str, datetime.date, datetime.date]] = []
    depth = 0
    while True:
        added = False
        for curve, plan in ordered:
            if depth < len(plan.chunks):
                out.append((curve, plan.chunks[depth][0], plan.chunks[depth][1]))
                added = True
        if not added:
            return out
        depth += 1


def _connect_or_restart(args, logger: logging.Logger) -> Any:
    """Attach to Excel, restarting it first if it is already too full to be useful.

    ``memory_guard.assert_safe_to_connect`` refuses above the ceiling, which is
    the right behaviour for a probe and the wrong one for an unattended backfill:
    a previous run leaves Excel at 4 GB, and refusing means the next 20 hours of
    work never start. With ``--auto-restart`` the answer to a full Excel is to
    empty it.
    """
    from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
    from MDP.CitiVelocityExcel.memory_guard import assert_safe_to_connect, excel_memory_mb

    used = excel_memory_mb()
    if used is not None and used >= args.memory_ceiling_mb and args.auto_restart:
        logger.warning(
            "Excel is already at %.0f MB (ceiling %.0f) before this run starts. "
            "Restarting it first rather than beginning with no headroom.",
            used, args.memory_ceiling_mb,
        )
        return _restart(None, args, logger)
    assert_safe_to_connect(args.memory_abort_mb, what="the deep intraday warm")
    try:
        client = CitiVelocityExcelClient.connect(workbook_tag=args.workbook_tag)
    except Exception as exc:  # noqa: BLE001
        # Two different states land here and they need different answers.
        #
        # Excel is UP but still re-authenticating: AddInNotSignedInError for
        # ~13 minutes with nothing printed in between. Wait it out - refusing
        # would kill a run relaunched during exactly the window the PREVIOUS run
        # created by restarting Excel.
        #
        # Excel is GONE: waiting is pointless, because nothing is coming. This
        # happens for a reason worth writing down - `restart_excel` LAUNCHES
        # Excel as a child of this process, so killing the run takes Excel with
        # it, and the next run finds an empty machine. Unattended means the
        # driver has to start it.
        from MDP.CitiVelocityExcel.supervisor import excel_pids, launch_excel, wait_for_addin

        if not excel_pids():
            logger.warning(
                "connect failed (%s) and no EXCEL.EXE is running - launching one. "
                "Note that restart_excel starts Excel as a CHILD of this process, "
                "so killing a previous run takes its Excel down too.", exc,
            )
            launch_excel(logger=logger)
        else:
            logger.warning("connect failed (%s); waiting for the add-in to sign in.", exc)
        client = wait_for_addin(
            timeout=getattr(args, "ready_timeout", 1800.0),
            workbook_tag=args.workbook_tag,
            logger=logger,
        )
    logger.info("connected to Excel (%s sheets, %.0f MB)",
                client.sheet_count(), client.excel_memory_mb())
    return client


def _restart(client: Any, args, logger: logging.Logger) -> Any:
    from MDP.CitiVelocityExcel.supervisor import restart_excel

    if client is not None:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
    return restart_excel(
        workbook_tag=args.workbook_tag,
        ready_timeout=args.ready_timeout,
        logger=logger,
    )


def _write_ledger(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def cmd_build(args, logger: logging.Logger) -> int:
    """Solve the fetched days into the CurveStore.

    OIS curves go to the existing builder unchanged: the sparse era is
    synchronous (measured), so the signature-grouping build already handles a
    15-tenor day exactly as it handles a 44-tenor one. IBOR curves take the
    dual-curve path in :mod:`MDP.CitiVelocityExcel.curves.ibor_builder`, because
    a EURIBOR swap forecasts one curve and discounts another.
    """
    import citivelo_excel_intraday_warm as base

    rc = 0
    for curve in _curves(args):
        logger.info("=== build %s ===", curve)
        if curve.strip().upper() in _ibor_curve_names():
            rc |= build_ibor_curve_days(curve, args, logger)
            continue
        rc |= build_ois_curve_days(curve, args, logger)
    return rc


def build_ois_curve_days(curve_name: str, args, logger: logging.Logger) -> int:
    """The existing per-day solver, with a DENSITY-aware skip.

    ``citivelo_excel_intraday_warm.cmd_build`` skips a day the store already
    holds, which is right when the only question is "has this day been built".
    It is wrong here, and silently so: the whole point of refetching
    ``USD-SOFR-1D``'s 2022-08..2023-12 stretch is that the store's version of
    those days is TEN-MINUTE data - ~130 curves against ~1,250 - acquired before
    the span cliff was understood. ``has_day`` says yes to every one of them, so
    the newly fetched minute parquets would sit on disk and never be solved, and
    the run would report success having changed nothing.

    The fetch planner already makes this distinction. This makes the build agree
    with it.
    """
    from Caching.curve_store import CurveStore

    import citivelo_excel_intraday_warm as base

    work_dir = Path(args.work_dir) if args.work_dir else _default_work_dir()
    store = CurveStore(base_dir=Path(args.base_dir)) if args.base_dir else CurveStore.default()
    curve_dir = work_dir / curve_name
    if not curve_dir.exists():
        logger.warning("%s: nothing fetched yet (%s)", curve_name, curve_dir)
        return 0

    params = base.curve_params(curve_name)
    asset = asset_name(curve_name)
    tasks: List[tuple] = []
    upgrades = 0
    for path in sorted(curve_dir.glob("*.parquet")):
        try:
            day = datetime.date.fromisoformat(path.stem)
        except ValueError:
            continue
        if args.start and day < datetime.date.fromisoformat(args.start):
            continue
        if args.end and day > datetime.date.fromisoformat(args.end):
            continue
        if not args.force and store.has_day(asset, day):
            if _already_dense(store, asset, day, curve_name, args.min_store_curves):
                continue
            upgrades += 1
        tasks.append((day, str(path), params))

    if not tasks:
        logger.info("%s: nothing to build - every fetched day is already dense in the store",
                    curve_name)
        return 0
    logger.info("%s: building %d day(s) on %d worker(s) (%d of them UPGRADES of a "
                "thin stored day)", curve_name, len(tasks), args.workers, upgrades)

    from concurrent.futures import ProcessPoolExecutor, as_completed

    progress = base.Progress(total_days=len(tasks))
    with ProcessPoolExecutor(
        max_workers=args.workers, initializer=base._init_worker, initargs=(args.base_dir,)
    ) as pool:
        futures = {pool.submit(base._warm_one_day, t): t[0] for t in tasks}
        for future in as_completed(futures):
            stat = future.result()
            progress.record(stat)
            if stat.error:
                logger.error("%s %s: %s", curve_name, stat.date, stat.error)
            if progress.days_done % 25 == 0 or progress.days_done == len(tasks):
                logger.info("%s: %s", curve_name, progress.heartbeat())
    logger.info("%s build complete: %s", curve_name, progress.heartbeat())
    return 1 if progress.errors else 0


def _already_dense(
    store: Any, asset: str, day: datetime.date, curve_name: str, min_store_curves: int
) -> bool:
    """Is the stored day already at the resolution this run would produce?

    ``has_day`` alone is the wrong question and fails silently in the one place
    it matters: ``USD-SOFR-1D``'s 2022-08..2023-12 days ARE in the store, as
    TEN-MINUTE data (~130 curves against ~1,250), and re-solving them at one
    minute is the entire point of refetching them. A ``has_day`` skip would leave
    the new parquets unsolved on disk and report success.

    Below a curve's measured ``dense_from`` the threshold drops to 1, because a
    sparse-era day cannot reach the dense count and would otherwise rebuild on
    every run forever.
    """
    if not store.has_day(asset, day):
        return False
    horizon = HORIZONS.get(curve_name)
    dense_from = horizon.dense_from if horizon else datetime.date(1900, 1, 1)
    threshold = min_store_curves if day >= dense_from else 1
    return _stored_curve_count(store, asset, day) >= threshold


def _ibor_curve_names() -> set:
    from MDP.CitiVelocityExcel.curves.ibor_builder import IBOR_CURVES

    return set(IBOR_CURVES)


def discount_source_for(
    curve_name: str, day: datetime.date, work_dir: Path
) -> Tuple[Optional[str], str]:
    """Which euro OIS curve discounts ``curve_name`` on ``day``, and from where.

    Returns ``(curve name, "parquet"|"store")``, or ``(None, "self")`` when no
    euro OIS curve has intraday data that far back.

    **Both sources have to be checked, and missing the second one is silent.**
    The fetch planner skips a day the CurveStore already holds densely, so
    ``EUR-ESTR-1D`` has no work-directory parquet for the 500-odd days it is
    already warmed for - 2024-08 onward, the two most liquid years in the whole
    range. A parquet-only lookup falls through ESTR (no file), then through EONIA
    (its plan stops at 2021-10), and lands on self-discounting for exactly the
    era where the right discount curve is sitting in the store. The result is
    labelled, so it would not have been *wrong* so much as quietly worse, for
    years, in the place it matters most.
    """
    from Caching.curve_store import CurveStore

    from MDP.CitiVelocityExcel.curves.ibor_builder import ibor_spec_for

    spec = ibor_spec_for(curve_name)
    store = CurveStore.default()
    for available_from, name in spec.discount_plan:
        if day < available_from:
            continue
        if (work_dir / name / f"{day.isoformat()}.parquet").exists():
            return name, "parquet"
        if store.has_day(asset_name(name), day):
            return name, "store"
    return None, "self"


def build_ibor_curve_days(curve_name: str, args, logger: logging.Logger) -> int:
    """One process pool over the fetched IBOR days."""
    from Caching.curve_store import CurveStore

    import citivelo_excel_intraday_warm as base

    work_dir = Path(args.work_dir) if args.work_dir else _default_work_dir()
    store = CurveStore(base_dir=Path(args.base_dir)) if args.base_dir else CurveStore.default()
    curve_dir = work_dir / curve_name
    if not curve_dir.exists():
        logger.warning("%s: nothing fetched yet (%s)", curve_name, curve_dir)
        return 0

    tasks: List[tuple] = []
    for path in sorted(curve_dir.glob("*.parquet")):
        try:
            day = datetime.date.fromisoformat(path.stem)
        except ValueError:
            continue
        if args.start and day < datetime.date.fromisoformat(args.start):
            continue
        if args.end and day > datetime.date.fromisoformat(args.end):
            continue
        if not args.force and _already_dense(
            store, asset_name(curve_name), day, curve_name, args.min_store_curves
        ):
            continue
        disc_name, disc_from = discount_source_for(curve_name, day, work_dir)
        disc_path = (
            str(work_dir / disc_name / f"{day.isoformat()}.parquet")
            if disc_name and disc_from == "parquet" else ""
        )
        tasks.append((curve_name, day, str(path), disc_name or "", disc_path, disc_from,
                      bool(args.include_short_tenors)))

    if not tasks:
        logger.info("%s: nothing to build", curve_name)
        return 0

    by_source: Dict[str, int] = {}
    for task in tasks:
        by_source[task[5]] = by_source.get(task[5], 0) + 1
    logger.info(
        "%s: %d day(s); discount source %s",
        curve_name, len(tasks),
        ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())),
    )

    from concurrent.futures import ProcessPoolExecutor, as_completed

    errors = 0
    done = 0
    with ProcessPoolExecutor(
        max_workers=args.workers, initializer=base._init_worker, initargs=(args.base_dir,)
    ) as pool:
        futures = {pool.submit(_build_ibor_day, t): t[1] for t in tasks}
        for future in as_completed(futures):
            stat = future.result()
            done += 1
            if stat.get("error"):
                errors += 1
                logger.error("%s %s: %s", curve_name, stat["date"], stat["error"])
            elif done % 25 == 0 or done == len(tasks):
                logger.info(
                    "%s: %d/%d days, last %s -> %d curves (%s, worst reprice %.4g bp)",
                    curve_name, done, len(tasks), stat["date"], stat["n_curves"],
                    stat["discounting"], stat["max_reprice_bp"],
                )
    logger.info("%s build complete: %d day(s), %d error(s)", curve_name, len(tasks), errors)
    return 1 if errors else 0


def _build_ibor_day(task: tuple) -> Dict[str, Any]:
    """Solve every minute of one IBOR day and write the partition. Runs in a worker.

    The discount curve comes from whichever source has it, in that order:

    * **the OIS par cache**, when this run fetched that day - re-solved per
      minute, so the discount curve is from the SAME MINUTE and the build has no
      ordering dependency on the OIS warm having finished;
    * **the CurveStore**, when the day was already warmed and therefore skipped
      by the fetch planner - already solved, so it is read back and memoised
      rather than rebuilt, backward-only to the nearest snapshot;
    * **nothing**, below every euro OIS floor, where the build self-discounts and
      records that in ``source_variant``.

    The middle case is not an optimisation. Without it, every EURIBOR day from
    2024-08 on - the two most liquid years in the range - would self-discount,
    because those are exactly the days the planner skips.
    """
    import datetime as _dt
    import zoneinfo

    import pandas as pd

    from Caching.curve_store import CurveSnapshot

    import citivelo_excel_intraday_warm as base
    from MDP.CitiVelocityExcel.curves.ibor_builder import build_rl_ibor_curve, ibor_spec_for

    curve_name, day, par_path, disc_name, disc_path, disc_from, include_short = task
    out: Dict[str, Any] = {
        "date": str(day), "n_curves": 0, "n_skipped": 0,
        "discounting": disc_name or "self", "max_reprice_bp": 0.0, "error": None,
    }
    try:
        spec = ibor_spec_for(curve_name)
        store = base._WORKER["store"]
        frame = pd.read_parquet(par_path).set_index("timestamp").sort_index()
        if not include_short:
            # EUR swaps are annual 30E/360 against SIX-MONTH EURIBOR only from 1Y
            # out. Citi's PAR grid also carries 1W..11M, and what those quote is
            # NOT that instrument - short EUR is conventionally deposits or
            # 3M-indexed - so pricing them with eur_irs6 builds a contract that
            # does not exist. It would solve, and the reprice guard would pass,
            # because the guard checks the curve against the same wrong swap.
            # Excluded until an external anchor says otherwise; see
            # docs/citivelo_intraday_depth_and_cvsnap.md.
            frame = frame[[c for c in frame.columns if _tenor_years_of(c) >= 1.0]]
        disc_frame = (
            pd.read_parquet(disc_path).set_index("timestamp").sort_index()
            if disc_path else None
        )
        disc_store_frame = None
        if disc_frame is None and disc_name and disc_from == "store":
            disc_store_frame = _store_curves_for_day(store, asset_name(disc_name), day)

        local_tz = zoneinfo.ZoneInfo(spec.local_timezone)
        utc = _dt.timezone.utc
        snapshots: List[Any] = []
        disc_memo: Dict[int, Any] = {}
        worst = 0.0

        for stamp, row in frame.iterrows():
            par = {c: float(v) for c, v in row.items() if pd.notna(v)}
            if len(par) < base.MIN_TENORS:
                out["n_skipped"] += 1
                continue

            disc_curve = None
            disc_label = None
            if disc_frame is not None:
                prior = disc_frame.index[disc_frame.index <= stamp]
                if len(prior):
                    disc_row = disc_frame.loc[prior.max()]
                    disc_par = {c: float(v) for c, v in disc_row.items() if pd.notna(v)}
                    if len(disc_par) >= base.MIN_TENORS:
                        from MDP.CitiVelocityExcel.curves.rl_builder import build_rl_ois_curve

                        citi_index = _CITI_INDEX_BY_CURVE.get(disc_name, "EUR_EUROSTR")
                        disc_curve = build_rl_ois_curve(
                            par_rates=disc_par, ref_date=day, citi_index=citi_index,
                            curve_id="disc",
                        ).rl_pricing_curve
                        disc_label = disc_name
            elif disc_store_frame is not None:
                # The OIS curve is already solved and in the store; rebuilding it
                # from par rates we do not have on disk would be the wrong kind of
                # thorough. Nearest snapshot at or before the minute.
                curve_at = _nearest_stored_curve(disc_store_frame, stamp, disc_memo)
                if curve_at is not None:
                    disc_curve, disc_label = curve_at, disc_name

            try:
                result = build_rl_ibor_curve(
                    par_rates=par, ref_date=day, curve_name=curve_name,
                    discount_curve=disc_curve, discount_curve_name=disc_label,
                )
            except Exception:  # noqa: BLE001 - one bad minute must not lose the day
                out["n_skipped"] += 1
                continue

            worst = max(worst, result.max_reprice_error_bp)
            raw = (
                result.curve.nodes._nodes
                if hasattr(result.curve.nodes, "_nodes")
                else dict(result.curve.nodes)
            )
            ordered_nodes = sorted(raw.keys())
            naive = stamp.to_pydatetime() if hasattr(stamp, "to_pydatetime") else stamp
            ts_utc = naive.replace(tzinfo=local_tz).astimezone(utc).replace(microsecond=0)
            snapshots.append(
                CurveSnapshot(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_utc.astimezone(local_tz),
                    trading_date=day,
                    session_minute=int(naive.hour * 60 + naive.minute),
                    curve_name=asset_name(curve_name),
                    cfg_hash="",
                    reference_key=curve_name,
                    interpolation="log_linear",
                    # The discounting is part of the artefact's identity: a
                    # self-discounted EURIBOR curve and an ESTR-discounted one
                    # are different objects with the same par quotes, and a
                    # reader that cannot tell them apart will splice them.
                    source_variant=(
                        f"{base.SOURCE_VARIANT}/{disc_label}" if disc_label
                        else f"{base.SOURCE_VARIANT}/self_discounted"
                    ),
                    node_dates=[d.date() if hasattr(d, "date") else d for d in ordered_nodes],
                    discount_factors=[float(raw[d]) for d in ordered_nodes],
                )
            )

        if snapshots:
            snapshots.sort(key=lambda s: s.timestamp_utc)
            store.write_day(asset_name(curve_name), day, snapshots, overwrite=True)
        out["n_curves"] = len(snapshots)
        out["max_reprice_bp"] = worst
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


#: Only the euro OIS curves an IBOR build can discount on. Kept here rather than
#: imported so a worker does not pay for ``curve_names`` on every day.
_CITI_INDEX_BY_CURVE: Dict[str, str] = {
    "EUR-ESTR-1D": "EUR_EUROSTR",
    "EUR-EONIA-1D": "EUR_EONIA",
}

_UNIT_YEARS = {"D": 1.0 / 365.25, "W": 7.0 / 365.25, "M": 1.0 / 12.0, "Y": 1.0}


def _tenor_years_of(tenor: str) -> float:
    text = str(tenor).strip().upper()
    try:
        return float(text[:-1]) * _UNIT_YEARS[text[-1]]
    except (ValueError, KeyError, IndexError):
        return 0.0


def _register_curve_definitions() -> None:
    """Teach ``reconstruct_curve`` about the Citi Velocity curve names. Idempotent.

    Without this, ``CurveStore.reconstruct_curve`` does not find the stored
    ``reference_key`` in ``RATESLIB_CURVE_DEFINITIONS`` and falls back to
    **act360 / nyc / mf**. It warns, and for the USD curves the fallback happens
    to be correct - which is exactly why it is dangerous. A euro curve rebuilt on
    the New York calendar instead of TARGET is a different curve, and the only
    signal is a log line.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_definitions import register

    register(quantlib=False)


def _store_curves_for_day(store: Any, asset: str, day: datetime.date):
    """Every stored curve snapshot for one day, indexed by local timestamp.

    Returns ``None`` when the day is absent, so a caller can tell "no discount
    curve" from "an empty one".
    """
    import pandas as pd

    _register_curve_definitions()

    frame = store.read_raw_day(asset, day)
    if frame is None or frame.empty:
        return None
    stamp = "timestamp_local" if "timestamp_local" in frame.columns else "timestamp_utc"
    frame = frame.copy()
    frame["_stamp"] = pd.to_datetime(frame[stamp])
    return frame.sort_values("_stamp").reset_index(drop=True)


def _nearest_stored_curve(frame, stamp, memo: Optional[Dict[int, Any]] = None):
    """The stored curve at or before ``stamp``, rebuilt. ``None`` if there is none.

    Backward-only on purpose. ``nearest`` would happily discount an 08:05 EURIBOR
    quote on an 08:40 ESTR curve, which is the same look-ahead the sibling
    ``citivelo`` source was measured making by up to 55 minutes.

    ``searchsorted`` rather than a boolean mask, and a memo keyed on the row
    position: two curves published a minute apart resolve to the same discount
    snapshot most of the time, and rebuilding it is ~1.6 ms that would otherwise
    be paid ~1,200 times a day for nothing.
    """
    import numpy as np
    import pandas as pd

    from Caching.curve_store import CurveStore

    target = np.datetime64(pd.Timestamp(stamp))
    pos = int(np.searchsorted(frame["_stamp"].values, target, side="right")) - 1
    if pos < 0:
        return None
    if memo is not None and pos in memo:
        return memo[pos]
    try:
        curve = CurveStore.reconstruct_curve(frame.iloc[pos].to_dict())
    except Exception:  # noqa: BLE001 - a bad stored row degrades to self-discounting
        curve = None
    if memo is not None:
        memo[pos] = curve
    return curve


def cmd_verify(args, logger: logging.Logger) -> int:
    """Tie stored curves back to Citi at a handful of minutes, using ``CVSNAP``.

    This is the one job ``CVSNAP`` measured *well* at, and the reason it is worth
    keeping in the toolkit at all after the depth question came back negative: it
    reads **one instant** for ~0.5 s and ~4 MB of Excel, where the same question
    asked through ``CVTSHIST`` costs a 5,800-row window and ~46 MB. For an
    independent check on a few dozen minutes that ratio is the whole argument.

    Sampling is **per era**, not uniform, because the eras fail differently: the
    dense era is the one everybody reads, the sparse era has a different tenor
    set, and the pre-EONIA EURIBOR era is self-discounted. A uniform sample over
    ten years puts almost nothing in the two that are least proven.

    What it compares is the curve's own ``fair_rate`` for a tenor against Citi's
    published par quote at the same minute - not the stored par input, which
    would be a tautology.
    """
    import pandas as pd

    from Caching.curve_store import CurveStore
    from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
    from MDP.CitiVelocityExcel.memory_guard import assert_safe_to_connect

    store = CurveStore(base_dir=Path(args.base_dir)) if args.base_dir else CurveStore.default()
    assert_safe_to_connect(args.ceiling_mb, what="the deep intraday warm verifier")

    rows: List[Dict[str, Any]] = []
    with CitiVelocityExcelClient.connect(workbook_tag=args.workbook_tag) as client:
        for curve in _curves(args):
            asset = asset_name(curve)
            available = [d for d in store.available_dates(asset)]
            if not available:
                logger.warning("%s: nothing in the store yet", curve)
                continue
            horizon = HORIZONS.get(curve)
            eras = _sample_eras(available, horizon, args.per_era)
            tags, zone = tags_and_zone_for(curve)
            if zone is None:
                from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name

                zone = entry_for_curve_name(curve).local_timezone
            for era, days in eras.items():
                for day in days:
                    frame = store.read_raw_day(asset, day)
                    if frame is None or frame.empty:
                        continue
                    row = frame.iloc[len(frame) // 2].to_dict()
                    local = pd.Timestamp(row.get("timestamp_local") or row["timestamp_utc"])
                    wire = _local_to_wire_instant(local.to_pydatetime(), zone)
                    tag = _quote_tag_for(curve, args.tenor)
                    try:
                        got = client.snapshot([tag], wire)
                        quote, _ = got.get(tag, (None, None))
                    except Exception as exc:  # noqa: BLE001
                        rows.append({"curve": curve, "era": era, "date": str(day),
                                     "error": f"{type(exc).__name__}: {exc}"})
                        continue
                    fair = _fair_rate_of(row, args.tenor, store)
                    rows.append({
                        "curve": curve, "era": era, "date": str(day),
                        "minute": str(local), "wire": str(wire),
                        "citi": quote, "curve_rate": fair,
                        "diff_bp": (None if (quote is None or fair is None)
                                    else round((fair - quote) * 100.0, 4)),
                        "source_variant": row.get("source_variant", ""),
                    })
                    logger.info("  %-16s %-8s %s %s  citi=%s curve=%s diff=%s bp",
                                curve, era, day, local.time(), quote,
                                None if fair is None else round(fair, 5),
                                rows[-1]["diff_bp"])

    print(f"\n{'curve':<18}{'era':<10}{'n':>4}{'worst |diff| bp':>17}{'median bp':>12}  variants")
    ok = True
    for curve in sorted({r["curve"] for r in rows}):
        for era in sorted({r["era"] for r in rows if r["curve"] == curve}):
            block = [r for r in rows
                     if r["curve"] == curve and r["era"] == era and r.get("diff_bp") is not None]
            if not block:
                print(f"{curve:<18}{era:<10}{0:>4}{'no comparison':>17}")
                continue
            diffs = sorted(abs(r["diff_bp"]) for r in block)
            worst = diffs[-1]
            median = diffs[len(diffs) // 2]
            variants = ",".join(sorted({r["source_variant"] for r in block}))
            flag = "" if worst <= args.tolerance_bp else "   <-- OVER TOLERANCE"
            ok = ok and worst <= args.tolerance_bp
            print(f"{curve:<18}{era:<10}{len(block):>4}{worst:>17.4f}{median:>12.4f}"
                  f"  {variants}{flag}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
        logger.info("wrote %s", args.out)
    return 0 if ok else 1


def _sample_eras(
    available: Sequence[datetime.date], horizon: Optional[Horizon], per_era: int
) -> Dict[str, List[datetime.date]]:
    """Split stored days into dense / sparse eras and take a spread of each.

    Spread rather than random: evenly-spaced picks cover the range on the first
    run and are reproducible, which matters more here than independence - the
    failure this looks for is a whole era being wrong, not one bad day.
    """
    days = sorted(available)
    dense_from = horizon.dense_from if horizon else (days[0] if days else None)
    eras: Dict[str, List[datetime.date]] = {
        "dense": [d for d in days if dense_from is None or d >= dense_from],
        "sparse": [d for d in days if dense_from is not None and d < dense_from],
    }
    out: Dict[str, List[datetime.date]] = {}
    for era, members in eras.items():
        if not members:
            continue
        if len(members) <= per_era:
            out[era] = members
            continue
        step = len(members) / float(per_era)
        out[era] = [members[min(len(members) - 1, int(i * step))] for i in range(per_era)]
    return out


def _local_to_wire_instant(local: datetime.datetime, tz: str) -> datetime.datetime:
    """Curve-local wall clock -> the naive New York instant the add-in expects."""
    import zoneinfo

    aware = local.replace(tzinfo=zoneinfo.ZoneInfo(tz))
    return aware.astimezone(zoneinfo.ZoneInfo("America/New_York")).replace(tzinfo=None)


def _quote_tag_for(curve_name: str, tenor: str) -> str:
    from MDP.CitiVelocityExcel.curves.ibor_builder import IBOR_CURVES

    spec = IBOR_CURVES.get(curve_name.strip().upper())
    if spec is not None:
        return f"RATES.SWAP_LIBOR.{spec.citi_currency}.PAR.{tenor.upper()}"
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import citi_index_for_curve_name

    return f"RATES.OIS.{citi_index_for_curve_name(curve_name)}.PAR.{tenor.upper()}"


def _discount_curve_of(row: Dict[str, Any], store: Any) -> Tuple[Optional[Any], str]:
    """The curve a stored IBOR snapshot was DISCOUNTED on, rebuilt from the store.

    Without this, verifying a EURIBOR curve reprices it self-discounted while it
    was built dual-curve, and the residual is the discounting difference rather
    than anything wrong - a systematic false alarm on the one curve that most
    needs the check. ``source_variant`` is where the build recorded which curve
    it used, which is what makes this recoverable at all.
    """
    variant = str(row.get("source_variant") or "")
    name = variant.rsplit("/", 1)[-1] if "/" in variant else ""
    if not name or name.endswith("self_discounted"):
        return None, "self"
    if store is None:
        return None, "unavailable"
    import pandas as pd

    day = row.get("trading_date")
    day = pd.Timestamp(day).date() if day is not None else None
    if day is None:
        return None, "unavailable"
    frame = _store_curves_for_day(store, asset_name(name), day)
    if frame is None:
        return None, "unavailable"
    stamp = row.get("timestamp_local") or row.get("timestamp_utc")
    return _nearest_stored_curve(frame, stamp), name


def _fair_rate_of(
    row: Dict[str, Any], tenor: str, store: Any = None
) -> Optional[float]:
    """The stored curve's own par rate for ``tenor``, in PERCENT.

    The unit is MEASURED, not assumed: on a stored ``USD-FEDFUNDS-1D`` minute of
    2026-07-08 this returns ``4.10733979`` against Citi's published
    ``4.10734`` - agreement to **-0.0000 bp**. ``rl.IRS.rate()`` is percent;
    ``RLCurveBase``-style ``fair_rate()`` helpers are DECIMAL, and confusing the
    two turns a 4.42% swap into 442 bp of error that reads exactly like a broken
    curve. The minute-warm tie-out walked into that once already.
    """
    import rateslib as rl

    from Caching.curve_store import CurveStore

    _register_curve_definitions()
    try:
        curve = CurveStore.reconstruct_curve(row)
    except Exception:  # noqa: BLE001
        return None
    reference = str(row.get("reference_key") or "")
    # The spec, calendar and settlement lag come from the SAME definitions the
    # warm solved with, not from a lookup table written here. A 2-day spot on the
    # wrong calendar moves the effective date and the comparison silently becomes
    # a different swap - see the QuantLib MakeOIS effective-date case, which cost
    # 6.5 bp of forward error with nothing raising.
    from MDP.CitiVelocityExcel.curves.ibor_builder import IBOR_CURVES

    ibor = IBOR_CURVES.get(reference.upper())
    discount = None
    if ibor is not None:
        spec, calendar, spot_lag = ibor.rl_spec, ibor.calendar, ibor.spot_lag
        discount, _how = _discount_curve_of(row, store)
    else:
        try:
            import citivelo_excel_intraday_warm as base

            params = base.curve_params(reference)
        except Exception:  # noqa: BLE001 - an unknown curve is not verifiable here
            return None
        spec, calendar, spot_lag = params["spec"], params["calendar"], params["spot_lag"]

    nodes = sorted(curve.nodes._nodes if hasattr(curve.nodes, "_nodes") else dict(curve.nodes))
    if not nodes:
        return None
    ref = nodes[0]
    try:
        cal = rl.get_calendar(calendar)
        spot = cal.add_bus_days(ref, int(spot_lag), True)
        # [leg1 forecast, leg1 discount, leg2 forecast, leg2 discount]. A stored
        # dual-curve IBOR snapshot repriced self-discounted comes back off by the
        # discounting difference, not by anything wrong.
        curves = [curve, discount, curve, discount] if discount is not None else curve
        swap = rl.IRS(effective=spot, termination=tenor, spec=spec, curves=curves)
        return float(swap.rate(curves=curves))
    except Exception:  # noqa: BLE001
        return None


def cmd_status(args, logger: logging.Logger) -> int:
    from Caching.curve_store import CurveStore

    work_dir = Path(args.work_dir) if args.work_dir else _default_work_dir()
    store = CurveStore(base_dir=Path(args.base_dir)) if args.base_dir else CurveStore.default()
    print(f"{'curve':<20}{'target from':<13}{'fetched':>9}{'stored':>8}"
          f"{'first':>13}{'last':>13}{'% of target':>13}")
    for curve in _curves(args):
        horizon = HORIZONS.get(curve)
        target = horizon.start if horizon else None
        curve_dir = work_dir / curve
        days = sorted(datetime.date.fromisoformat(p.stem) for p in curve_dir.glob("*.parquet")) \
            if curve_dir.exists() else []
        asset = asset_name(curve)
        stored = sum(1 for d in days if store.has_day(asset, d))
        want = _business_days(target, datetime.date.today()) if target else 0
        pct = f"{100.0 * len(days) / want:.1f}%" if want else "-"
        print(f"{curve:<20}{str(target or '-'):<13}{len(days):>9}{stored:>8}"
              f"{str(days[0]) if days else '-':>13}{str(days[-1]) if days else '-':>13}{pct:>13}")
    ledger = work_dir / "_deep_warm_ledger.json"
    if ledger.exists():
        print("\nlast run: " + ledger.read_text(encoding="utf-8").replace("\n", " ")[:400])
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--work-dir", default=None)
    p.add_argument("--base-dir", default=None, help="CurveStore base dir")
    p.add_argument("--curves", default="", help="comma-separated; default the four requested")
    p.add_argument("--start", default=None, help="override the measured floor")
    p.add_argument("--end", default=None)
    p.add_argument("--chunk-days", type=int, default=60)
    p.add_argument(
        "--min-store-curves", type=int, default=DEFAULT_MIN_STORE_CURVES,
        help="a stored day with fewer curves than this is refetched at MI01 rather "
             "than skipped - this is what upgrades the ten-minute 2022-2023 era",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("plan", help="what would run, and how much is already done")
    pl.set_defaults(func=cmd_plan)

    f = sub.add_parser("fetch", help="drive Excel to the measured floor, restarting as needed")
    f.add_argument("--workbook-tag", default="DEEPWARM")
    f.add_argument("--freq", default="MI01", choices=("MI01", "MI10", "HOURLY"))
    f.add_argument("--force", action="store_true")
    f.add_argument(
        "--recycle-every", type=int, default=6,
        help="check Excel every N windows INSIDE one chunk. Must be below the "
             "windows-per-chunk count (a 60-day chunk at MI01 is 12 windows) or "
             "it never fires: fetch_curve counts windows per CALL, and this "
             "driver calls it once per chunk.",
    )
    f.add_argument("--memory-ceiling-mb", type=float, default=3000.0)
    f.add_argument("--memory-abort-mb", type=float, default=3800.0)
    f.add_argument(
        "--no-interleave", action="store_true",
        help="finish one curve before starting the next. The default walks all "
             "curves back together, so a run that stops early has covered every "
             "curve rather than the first two.",
    )
    f.add_argument("--auto-restart", action="store_true",
                   help="restart Excel at the ceiling. Rescues unsaved workbooks first.")
    f.add_argument("--max-restarts", type=int, default=20)
    f.add_argument("--ready-timeout", type=float, default=1800.0,
                   help="how long to wait for the add-in to sign back in (it logs nothing)")
    f.set_defaults(func=cmd_fetch)

    b = sub.add_parser("build", help="solve the fetched days into the CurveStore")
    b.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    b.add_argument("--force", action="store_true")
    b.add_argument(
        "--include-short-tenors", action="store_true",
        help="calibrate IBOR curves on the sub-1Y PAR quotes too. OFF by default: "
             "EUR swaps are annual vs 6M EURIBOR only from 1Y out, and pricing a "
             "1M quote with eur_irs6 builds an instrument that does not exist. It "
             "would still solve, and the reprice guard would still pass, because "
             "the guard checks the curve against the same wrong swap. Turn this on "
             "once an external anchor (RATES.BASIS_SWAPS.EUROSTR_EURIBOR_BASIS, or "
             "a with/without comparison of the 1Y+ forwards) says the short quotes "
             "belong on this curve.",
    )
    b.set_defaults(func=cmd_build)

    v = sub.add_parser(
        "verify",
        help="CVSNAP a stored minute per era and compare against the curve's own par rate",
    )
    v.add_argument("--workbook-tag", default="VERIFY")
    v.add_argument("--per-era", type=int, default=5)
    v.add_argument("--tenor", default="10Y")
    v.add_argument("--tolerance-bp", type=float, default=0.05)
    v.add_argument("--ceiling-mb", type=float, default=3500.0)
    v.add_argument("--out", default=None)
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    return args.func(args, LOGGER)


if __name__ == "__main__":
    sys.exit(main())

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
    python scripts/citivelo_deep_intraday_warm.py status
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

#: What the ten-year request actually resolves to, in run order. Deepest history
#: last: the shallow curves finish quickly and bank their days before the long
#: ones start consuming Excel sessions. ``EUR-EONIA-1D`` is not itself a
#: requested curve - it is the discount curve the pre-2021 EURIBOR era needs, and
#: fetching it is what keeps that era from being self-discounted.
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
    stored_dense = {
        d for d in store.available_dates(asset)
        if lo <= d < hi and _stored_curve_count(store, asset, d) >= min_store_curves
    }

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

    restarts = 0
    try:
        for curve in _curves(args):
            plan = plan_curve(curve, work_dir=work_dir, start=_opt_date(args.start),
                              end=_opt_date(args.end), chunk_days=args.chunk_days,
                              min_store_curves=args.min_store_curves)
            logger.info("=== %s: %d chunk(s), %s -> %s (%d bdays, %d on disk) ===",
                        curve, len(plan.chunks), plan.start, plan.end,
                        plan.business_days, plan.on_disk)
            tags, zone = tags_and_zone_for(curve)
            index = 0
            while index < len(plan.chunks):
                chunk_start, chunk_end = plan.chunks[index]
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
                logger.info(
                    "%s %s..%s: %d day(s) from %d window(s) in %.0fs  [Excel %.0f MB]",
                    curve, chunk_start, chunk_end, days, windows, time.time() - t0, used,
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
    client = CitiVelocityExcelClient.connect(workbook_tag=args.workbook_tag)
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
        sub = argparse.Namespace(
            curves=curve, start=args.start, end=args.end, workers=args.workers,
            force=args.force, work_dir=args.work_dir, base_dir=args.base_dir,
        )
        rc |= base.cmd_build(sub, logger)
    return rc


def _ibor_curve_names() -> set:
    from MDP.CitiVelocityExcel.curves.ibor_builder import IBOR_CURVES

    return set(IBOR_CURVES)


def discount_source_for(curve_name: str, day: datetime.date, work_dir: Path) -> Optional[str]:
    """Which OIS par cache to discount ``curve_name`` with on ``day``.

    Returns the OIS curve's name, or ``None`` when no euro OIS curve has intraday
    data that far back and the build must self-discount. The plan is on the
    :class:`IborCurveSpec`; this only adds the "is it actually on disk?" half,
    because a discount curve that was planned and never fetched has to degrade to
    self-discounting rather than fail the day.
    """
    from MDP.CitiVelocityExcel.curves.ibor_builder import ibor_spec_for

    spec = ibor_spec_for(curve_name)
    for available_from, name in spec.discount_plan:
        if day >= available_from and (work_dir / name / f"{day.isoformat()}.parquet").exists():
            return name
    return None


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
        if not args.force and store.has_day(asset_name(curve_name), day):
            continue
        disc_name = discount_source_for(curve_name, day, work_dir)
        disc_path = str(work_dir / disc_name / f"{day.isoformat()}.parquet") if disc_name else ""
        tasks.append((curve_name, day, str(path), disc_name or "", disc_path))

    if not tasks:
        logger.info("%s: nothing to build", curve_name)
        return 0

    self_discounted = sum(1 for t in tasks if not t[3])
    logger.info(
        "%s: %d day(s), %d dual-curve, %d self-discounted",
        curve_name, len(tasks), len(tasks) - self_discounted, self_discounted,
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

    The discount curve is rebuilt here from the OIS par cache rather than read
    back out of the CurveStore. That costs a second solve per minute and buys
    two things worth more than the CPU: the build has no ordering dependency on
    the OIS warm having already run, and the discount curve is the one from the
    SAME MINUTE rather than the nearest stored snapshot.
    """
    import datetime as _dt
    import zoneinfo

    import pandas as pd

    from Caching.curve_store import CurveSnapshot

    import citivelo_excel_intraday_warm as base
    from MDP.CitiVelocityExcel.curves.ibor_builder import build_rl_ibor_curve, ibor_spec_for

    curve_name, day, par_path, disc_name, disc_path = task
    out: Dict[str, Any] = {
        "date": str(day), "n_curves": 0, "n_skipped": 0,
        "discounting": disc_name or "self", "max_reprice_bp": 0.0, "error": None,
    }
    try:
        spec = ibor_spec_for(curve_name)
        store = base._WORKER["store"]
        frame = pd.read_parquet(par_path).set_index("timestamp").sort_index()
        disc_frame = (
            pd.read_parquet(disc_path).set_index("timestamp").sort_index()
            if disc_path else None
        )

        local_tz = zoneinfo.ZoneInfo(spec.local_timezone)
        utc = _dt.timezone.utc
        snapshots: List[Any] = []
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
    f.add_argument("--auto-restart", action="store_true",
                   help="restart Excel at the ceiling. Rescues unsaved workbooks first.")
    f.add_argument("--max-restarts", type=int, default=20)
    f.add_argument("--ready-timeout", type=float, default=1800.0,
                   help="how long to wait for the add-in to sign back in (it logs nothing)")
    f.set_defaults(func=cmd_fetch)

    b = sub.add_parser("build", help="solve the fetched days into the CurveStore")
    b.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    b.add_argument("--force", action="store_true")
    b.set_defaults(func=cmd_build)

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

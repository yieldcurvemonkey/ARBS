r"""Warm the CurveStore with minute-resolution Citi Velocity curves, any currency.

This is the intraday sibling of ``scripts/citivelo_excel_warm.py`` (which warms
one EOD curve per day). It follows the two-phase shape proven by
``scripts/citivelo_curve_service.py`` - which built ~1.087M USD curves - but
takes its par rates from **live Excel** rather than a hand-built 365 MB workbook,
and is parameterised by currency instead of hardcoded to USD.

The acquisition problem this solves
-----------------------------------
``CVTSHIST`` silently downsamples by *requested span*: ask for a year of ``MI01``
and you get 261 daily rows, with no error and a block that looks perfectly
healthy. Measured 2026-08-07, the minute cliff is at **7 days** - a 6-day request
serves 1-minute data, a 7-day request serves 10-minute - and it is a span effect,
not a retention one: a 4-day window returned true minute data at every age out to
a year back. So the history is all there; it just has to be asked for in pieces.
``MDP.CitiVelocityExcel.windowed`` does the chunking and verifies the spacing of
every window it returns.

Two phases, because Excel is a single shared resource
-----------------------------------------------------
**Phase 1 (fetch)** is single-threaded through the one Excel session, writing one
``{date}.parquet`` of ``(timestamp, tenor...)`` per calendar day. Each window
gets its own worksheet, dropped once read, so Excel never holds more than one
window's cells.

**Phase 2 (build)** is pure CPU and runs in a process pool: one rateslib solver
per NaN-tenor signature per day, re-solved per minute.

Splitting them is what makes the run **resumable**. A day file on disk is a
completed unit of Excel work; if Excel logs out or the machine reboots, the rerun
skips every day already fetched. Losing Excel costs time, never data.

Usage::

    conda run -n stir python scripts/citivelo_excel_intraday_warm.py fetch \
        --curves USD-SOFR-1D,EUR-ESTR-1D --start 2026-06-30 --end 2026-08-07
    conda run -n stir python scripts/citivelo_excel_intraday_warm.py build \
        --curves USD-SOFR-1D
    conda run -n stir python scripts/citivelo_excel_intraday_warm.py status
"""

from __future__ import annotations

# MUST precede any Caching import, and re-runs in spawned workers: writes are
# local-only, otherwise write_day background-pushes ~1M rows to prod Supabase.
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import argparse
import contextlib
import datetime
import gc
import io
import logging
import math
import sys
import time
import zoneinfo
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

#: Minute curves get their own asset. Deliberately NOT the EOD warm's
#: ``-CITIVELOEXCEL``: ``write_day`` replaces a whole day partition, so sharing
#: one asset would mean an EOD re-warm silently deleting that day's 1,100 minute
#: curves. Distinct assets make the two independent.
ASSET_SUFFIX = "CITIVELOEXCELMIN"

SOURCE_VARIANT = "CITIVELOEXCELMIN"
DEFAULT_INTERPOLATION = "log_linear"
MIN_TENORS = 4

#: The add-in stamps EVERY curve in New York wall-clock regardless of currency.
#: Established by watching EUR_EUROSTR's fixed CET session move from 02:00-13:59
#: to 03:00-14:59 across the 2026-03-08 *US* spring-forward - a shift no fixed
#: offset and no London clock can produce.
WIRE_TZ = "America/New_York"

LOGGER = logging.getLogger("citivelo_excel_intraday_warm")


class MemoryCeilingReached(RuntimeError):
    """Excel's memory reached the point where continuing risks wedging it.

    Not a failure: everything fetched is already on disk. The run stops so the
    next one can resume after an Excel restart.
    """


def asset_name(curve_name: str) -> str:
    return f"{curve_name}-{ASSET_SUFFIX}"


def _default_work_dir() -> Path:
    return _REPO_ROOT / "MDP" / "IRSwaps" / "CITIVELO_EXCEL" / "_intraday_par_cache"


def curve_params(curve_name: str) -> Dict[str, Any]:
    """Everything Phase 2 needs about a curve, resolved once in the parent."""
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_definitions import (
        rateslib_definition,
        rateslib_spec_for,
        register,
    )
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name

    register()
    entry = entry_for_curve_name(curve_name)
    definition = rateslib_definition(entry)
    return {
        "curve_name": curve_name,
        "citi_index": entry.citi_index,
        "spec": rateslib_spec_for(entry.citi_index),
        "convention": definition["DayCounter"],
        "calendar": definition["Calendar"],
        "modifier": definition["BusinessConvention"],
        "spot_lag": int(definition["SettlementDays"]),
        "timezone": entry.local_timezone,
        "interpolation": DEFAULT_INTERPOLATION,
    }


# ---------------------------------------------------------------------------
# Phase 1 - fetch par rates out of Excel, one parquet per calendar day
# ---------------------------------------------------------------------------


def _write_day_parquet(out: Path, frame: pd.DataFrame) -> int:
    """Atomically write one day's ``(timestamp, tenor...)`` table."""
    out.parent.mkdir(parents=True, exist_ok=True)
    arrays = [pa.array(frame.index.values.astype("datetime64[us]"))]
    names = ["timestamp"]
    for column in frame.columns:
        arrays.append(pa.array(frame[column].to_numpy(dtype="float64"), type=pa.float64()))
        names.append(str(column))
    table = pa.Table.from_arrays(arrays, names=names)
    tmp = out.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, out)
    return len(frame)


def fetch_curve(
    curve_name: str,
    start: datetime.date,
    end: datetime.date,
    *,
    work_dir: Path,
    client: Any,
    force: bool = False,
    recycle_every: int = 25,
    memory_ceiling_mb: float = 3000.0,
    memory_abort_mb: float = 3800.0,
    logger: logging.Logger = LOGGER,
) -> Tuple[int, int]:
    """Fetch ``[start, end)`` of minute par rates for one curve.

    Returns ``(days_written, windows_run)``. Days already on disk are skipped
    unless ``force`` - that skip is what makes a lost Excel session cost only the
    window that was in flight.
    """
    import datetime as _dt

    from MDP.CitiVelocityExcel.windowed import DEFAULT_WINDOW, fetch_windowed
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import entry_for_curve_name
    from MDP.IRSwaps.CITIVELO_EXCEL.fetcher import CitiVeloExcelCurveFetcher

    entry = entry_for_curve_name(curve_name)
    tags = CitiVeloExcelCurveFetcher.par_grid_tags(entry.citi_index)
    curve_dir = work_dir / curve_name
    curve_dir.mkdir(parents=True, exist_ok=True)

    tenor_of = {tag: tag.rsplit(".", 1)[-1] for tag in tags}
    window = DEFAULT_WINDOW["MI01"]
    days_written = 0
    windows_run = 0

    cursor = _dt.datetime.combine(start, _dt.time.min)
    stop = _dt.datetime.combine(end, _dt.time.min)
    while cursor < stop:
        w_end = min(cursor + window, stop)
        # Skip a window only when EVERY weekday in it is already on disk.
        needed = [
            d for d in pd.date_range(cursor, w_end, freq="D", inclusive="left").date
            if d.weekday() < 5 and (force or not (curve_dir / f"{d.isoformat()}.parquet").exists())
        ]
        if not needed:
            logger.info("  %s..%s  already on disk, skipped", cursor.date(), w_end.date())
            cursor = w_end
            continue

        series, windows = fetch_windowed(
            client, tags, "MI01", cursor, w_end, window=window, strict_spacing=True
        )
        windows_run += len(windows)
        for w in windows:
            if not w.ok:
                logger.warning("  window %s failed: %s", w.sheet or w.start, w.error)

        if series:
            frame = pd.DataFrame(
                {tenor_of[tag]: s for tag, s in series.items()}
            ).sort_index()
            # The add-in stamps every curve in NEW YORK wall-clock, whatever the
            # currency: EUR_EUROSTR's session reads 02:00-13:59 here, which is
            # 08:00-19:59 in Berlin. Two things therefore have to happen before
            # the frame can be bucketed by day.
            #
            #   1. Convert to the curve's own zone. Otherwise JPY's 19:00 ET bars
            #      - already 08:00 the NEXT morning in Tokyo - would be filed
            #      under the previous Tokyo business date, and Phase 2 would
            #      solve them off the wrong reference and spot date.
            #   2. Bucket by the LOCAL date, so a day partition is a trading day
            #      in the market that produced it.
            frame.index = (
                frame.index.tz_localize(
                    WIRE_TZ, ambiguous=True, nonexistent="shift_forward"
                )
                .tz_convert(entry.local_timezone)
                .tz_localize(None)
            )
            for day, sub in frame.groupby(frame.index.date):
                out = curve_dir / f"{day.isoformat()}.parquet"
                if out.exists() and not force:
                    continue
                n = _write_day_parquet(out, sub)
                days_written += 1
                logger.info("  wrote %s  %d minutes x %d tenors", out.name, n, sub.shape[1])
        cursor = w_end

        # Dropping each window's sheet bounds the number of live cells but does
        # NOT return Excel's process memory. Measured 2026-08-07 the hard way: a
        # 528-window fetch left Excel at 5.25 GB and WEDGED - unresponsive to a
        # 15s window ping, no modal dialog, no cell-edit mode, and it did not
        # recover when the COM client was released. Closing the workbook is the
        # only thing that actually gives the memory back.
        if recycle_every and windows_run and windows_run % recycle_every == 0:
            used = client.excel_memory_mb()
            if 0 <= used < memory_ceiling_mb:
                logger.info("  %d window(s) in, Excel at %.0f MB", windows_run, used)
            else:
                logger.info(
                    "  recycling the scratch workbook after %d window(s) (Excel %.0f MB)",
                    windows_run, used,
                )
                recycled = client.recycle_workbook()
                after = client.excel_memory_mb() if recycled else used
                if not recycled:
                    logger.warning(
                        "  recycle refused - stopping rather than driving Excel further "
                        "up. Everything fetched is on disk; re-run to resume."
                    )
                    raise MemoryCeilingReached(f"recycle refused at {used:.0f} MB")
                # Recycling recovers far less than it costs. MEASURED 2026-08-07:
                # a recycle took Excel 2,621 -> 2,409 MB (~200 MB back) while the
                # 20 windows before it had ADDED ~340 MB. The memory is in the
                # add-in's own cache, not in the workbook, so closing the workbook
                # cannot reclaim it and the trend stays upward. Stop cleanly well
                # under the 5,249 MB that wedged Excel: the fetch banks its work
                # per day and resumes, so an early stop costs only time.
                if after >= memory_abort_mb:
                    raise MemoryCeilingReached(
                        f"Excel is at {after:.0f} MB, at or above the {memory_abort_mb:.0f} MB "
                        f"abort ceiling, and recycling no longer recovers enough. Stopping "
                        f"before it wedges (it did at 5,249 MB on 2026-08-07). Everything "
                        f"fetched is on disk - restart Excel and re-run to resume."
                    )

    return days_written, windows_run


# ---------------------------------------------------------------------------
# Phase 2 - solve curves per day, in a process pool
# ---------------------------------------------------------------------------


@dataclass
class DayStat:
    date: datetime.date
    curve_name: str = ""
    n_curves: int = 0
    n_fallback: int = 0
    n_skipped_rows: int = 0
    max_reprice_bp: float = 0.0
    elapsed: float = 0.0
    error: Optional[str] = None


_WORKER: Dict[str, Any] = {"store": None}


def _init_worker(base_dir: Optional[str]) -> None:
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    from Caching.curve_store import CurveStore

    _WORKER["store"] = CurveStore(base_dir=Path(base_dir)) if base_dir else CurveStore.default()


def _tenor_sort_key(tenor: str) -> tuple:
    unit = tenor[-1].upper()
    try:
        n = float(tenor[:-1])
    except ValueError:
        return (9, 0.0)
    return ({"D": 0, "W": 1, "M": 2, "Y": 3}.get(unit, 9), n * {"D": 1, "W": 7, "M": 30, "Y": 365}.get(unit, 1))


def _build_day_snapshots(
    date: datetime.date, par_path: str, params: dict
) -> Tuple[list, DayStat]:
    """Every CurveSnapshot for one calendar day. No store I/O here."""
    import rateslib as rl

    from Caching.curve_store import CurveSnapshot

    convention = params["convention"]
    calendar = params["calendar"]
    modifier = params["modifier"]
    spot_lag = params["spot_lag"]
    interpolation = params["interpolation"]
    spec = params["spec"]
    curve_name = params["curve_name"]
    local_tz = zoneinfo.ZoneInfo(params["timezone"])
    utc = datetime.timezone.utc

    df = pd.read_parquet(par_path).set_index("timestamp").sort_index()
    stat = DayStat(date=date, curve_name=curve_name)

    cal = rl.get_calendar(calendar)
    ref = rl.dt(date.year, date.month, date.day)
    while not cal.is_bus_day(ref):
        ref = ref - datetime.timedelta(days=1)
    spot = cal.add_bus_days(ref, spot_lag, True)

    snapshots: list = []
    notna = df.notna()
    signature = notna.apply(lambda r: tuple(df.columns[r.values]), axis=1)

    for sig, idx in signature.groupby(signature).groups.items():
        tenors = sorted(sig, key=_tenor_sort_key)
        if len(tenors) < MIN_TENORS:
            stat.n_skipped_rows += len(idx)
            continue
        protos = [
            (t, rl.IRS(effective=spot, termination=t, spec=spec, curves="c", fixed_rate=2.0))
            for t in tenors
        ]
        protos.sort(key=lambda p: p[1].leg1.schedule.termination)
        ordered = [p[0] for p in protos]
        node_dates = [p[1].leg1.schedule.termination for p in protos]

        group = df.loc[idx, ordered].sort_index()
        rows = group.to_numpy(dtype="float64")
        stamps = group.index.to_pydatetime()

        instruments = [
            rl.IRS(effective=spot, termination=t, spec=spec, curves="c", fixed_rate=float(rows[0][j]))
            for j, t in enumerate(ordered)
        ]

        def _fresh(rates: List[float]):
            # Seed each node with the discount factor its own par rate implies.
            # A flat 1.0 seed diverges outright on steep, high-rate curves
            # (measured on MXN and ZAR: max_iter with f_val nan).
            nodes = {ref: 1.0}
            for date_j, rate_j in zip(node_dates, rates):
                years = max((date_j - ref).days / 365.0, 1e-6)
                nodes[date_j] = math.exp(-float(rate_j) / 100.0 * years)
            curve = rl.Curve(
                nodes=nodes, id="c", convention=convention, calendar=calendar,
                modifier=modifier, interpolation=interpolation,
            )
            solver = rl.Solver(
                curves=[curve], instruments=instruments, s=list(rates), id="c",
                func_tol=1e-9, conv_tol=1e-10,
            )
            return curve, solver

        curve, solver = _fresh(list(rows[0]))

        for k in range(len(rows)):
            rates = list(rows[k])
            if k:
                solver.s = rates
                solver.iterate()
            ok = solver.result.get("status") == "SUCCESS"
            if not ok:
                curve, solver = _fresh(rates)
                stat.n_fallback += 1
                ok = solver.result.get("status") == "SUCCESS"
                if not ok:
                    stat.n_skipped_rows += 1
                    continue

            # status == SUCCESS stopped being proof of a good solve in rateslib
            # 2.7, so spot-check that the curve actually reprices its own inputs.
            # Every 250th minute: enough to catch a drifting solver, cheap enough
            # not to dominate a million-curve run.
            if k % 250 == 0:
                # rateslib 2.7 made rate() keyword-only (verified by
                # inspect.signature, not by probing with try/except).
                err = max(
                    abs(float(inst.rate(curves=curve)) - r) * 100.0
                    for inst, r in zip(instruments, rates)
                )
                stat.max_reprice_bp = max(stat.max_reprice_bp, err)
                if err > 0.1:
                    curve, solver = _fresh(rates)
                    stat.n_fallback += 1
                    if solver.result.get("status") != "SUCCESS":
                        stat.n_skipped_rows += 1
                        continue

            raw = curve.nodes._nodes if hasattr(curve.nodes, "_nodes") else dict(curve.nodes)
            ordered_nodes = sorted(raw.keys())
            naive = stamps[k]
            ts_utc = naive.replace(tzinfo=local_tz).astimezone(utc).replace(microsecond=0)
            snapshots.append(
                CurveSnapshot(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_utc.astimezone(local_tz),
                    trading_date=date,
                    session_minute=int(naive.hour * 60 + naive.minute),
                    curve_name=asset_name(curve_name),
                    cfg_hash="",
                    reference_key=curve_name,
                    interpolation=interpolation,
                    source_variant=SOURCE_VARIANT,
                    node_dates=[d.date() if hasattr(d, "date") else d for d in ordered_nodes],
                    discount_factors=[float(raw[d]) for d in ordered_nodes],
                )
            )

    stat.n_curves = len(snapshots)
    return snapshots, stat


def _warm_one_day(task: tuple) -> DayStat:
    date, par_path, params = task
    t0 = time.time()
    try:
        # rateslib prints a SUCCESS line per solve; across ~1M solves that both
        # bloats the log and serialises workers on the shared stdout.
        with contextlib.redirect_stdout(io.StringIO()):
            snapshots, stat = _build_day_snapshots(date, par_path, params)
        if snapshots:
            snapshots.sort(key=lambda s: s.timestamp_utc)
            _WORKER["store"].write_day(
                asset_name(params["curve_name"]), date, snapshots, overwrite=True
            )
        stat.elapsed = time.time() - t0
        return stat
    except Exception as exc:  # noqa: BLE001 - isolate one bad day
        return DayStat(
            date=date, curve_name=params["curve_name"], elapsed=time.time() - t0,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        gc.collect()


def _rss_mb() -> float:
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1e6
    except Exception:  # noqa: BLE001
        return 0.0


@dataclass
class Progress:
    total_days: int
    started: float = field(default_factory=time.time)
    days_done: int = 0
    curves: int = 0
    fallbacks: int = 0
    errors: int = 0
    max_reprice_bp: float = 0.0

    def record(self, stat: DayStat) -> None:
        self.days_done += 1
        self.curves += stat.n_curves
        self.fallbacks += stat.n_fallback
        self.max_reprice_bp = max(self.max_reprice_bp, stat.max_reprice_bp)
        if stat.error:
            self.errors += 1

    def heartbeat(self) -> str:
        elapsed = max(time.time() - self.started, 1e-9)
        pct = 100.0 * self.days_done / self.total_days if self.total_days else 100.0
        rate = self.days_done / (elapsed / 60.0)
        eta = ((self.total_days - self.days_done) / rate * 60.0) if rate > 0 else 0.0
        return (
            f"day {self.days_done}/{self.total_days} ({pct:.1f}%) curves={self.curves:,} "
            f"({self.curves / elapsed:.0f}/s) fallbacks={self.fallbacks} errors={self.errors} "
            f"reprice<={self.max_reprice_bp:.4f}bp elapsed={elapsed / 60:.1f}m "
            f"eta={eta / 60:.1f}m mem={_rss_mb():.0f}MB"
        )


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def _curve_list(raw: str) -> List[str]:
    return [c.strip() for c in str(raw).split(",") if c.strip()]


def cmd_fetch(args, logger: logging.Logger) -> int:
    from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient

    work_dir = Path(args.work_dir) if args.work_dir else _default_work_dir()
    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end)
    curves = _curve_list(args.curves)

    client = CitiVelocityExcelClient.connect(workbook_tag=args.workbook_tag)
    logger.info("connected to Excel (%s sheets)", client.sheet_count())
    total_days = 0
    for curve in curves:
        t0 = time.time()
        logger.info("=== %s  %s -> %s ===", curve, start, end)
        try:
            days, windows = fetch_curve(
                curve, start, end, work_dir=work_dir, client=client,
                force=args.force, recycle_every=args.recycle_every,
                memory_ceiling_mb=args.memory_ceiling_mb,
                memory_abort_mb=args.memory_abort_mb, logger=logger,
            )
        except MemoryCeilingReached as exc:
            # Deliberately ends the WHOLE run, not just this curve: the ceiling
            # is a property of the shared Excel, so the next curve would hit it
            # immediately and the one after that would wedge.
            logger.warning("%s stopped: %s", curve, exc)
            logger.info(
                "fetch stopped early at %d day file(s) under %s. Restart Excel and "
                "re-run the same command to resume.", total_days, work_dir,
            )
            return 3
        except Exception as exc:  # noqa: BLE001 - one curve must not end the run
            logger.error("%s FAILED: %s: %s", curve, type(exc).__name__, exc)
            continue
        total_days += days
        logger.info(
            "%s: %d day file(s) from %d window(s) in %.1fs",
            curve, days, windows, time.time() - t0,
        )
    logger.info("fetch complete: %d day file(s) written under %s", total_days, work_dir)
    return 0


def cmd_build(args, logger: logging.Logger) -> int:
    from Caching.curve_store import CurveStore

    work_dir = Path(args.work_dir) if args.work_dir else _default_work_dir()
    store = CurveStore(base_dir=Path(args.base_dir)) if args.base_dir else CurveStore.default()

    tasks: List[tuple] = []
    for curve in _curve_list(args.curves):
        params = curve_params(curve)
        curve_dir = work_dir / curve
        if not curve_dir.exists():
            logger.warning("%s: nothing fetched yet (%s)", curve, curve_dir)
            continue
        for path in sorted(curve_dir.glob("*.parquet")):
            day = datetime.date.fromisoformat(path.stem)
            if args.start and day < datetime.date.fromisoformat(args.start):
                continue
            if args.end and day > datetime.date.fromisoformat(args.end):
                continue
            if not args.force and store.has_day(asset_name(curve), day):
                continue
            tasks.append((day, str(path), params))

    if not tasks:
        logger.info("nothing to build - every fetched day is already in the store")
        return 0

    progress = Progress(total_days=len(tasks))
    logger.info("building %d day(s) across %d worker(s)", len(tasks), args.workers)
    with ProcessPoolExecutor(
        max_workers=args.workers, initializer=_init_worker, initargs=(args.base_dir,)
    ) as pool:
        futures = {pool.submit(_warm_one_day, t): t[0] for t in tasks}
        for future in as_completed(futures):
            stat = future.result()
            progress.record(stat)
            if stat.error:
                logger.error("%s %s: %s", stat.curve_name, stat.date, stat.error)
            if progress.days_done % 10 == 0 or progress.days_done == len(tasks):
                logger.info(progress.heartbeat())
    logger.info("build complete: %s", progress.heartbeat())
    return 1 if progress.errors else 0


def cmd_status(args, logger: logging.Logger) -> int:
    from Caching.curve_store import CurveStore

    work_dir = Path(args.work_dir) if args.work_dir else _default_work_dir()
    store = CurveStore(base_dir=Path(args.base_dir)) if args.base_dir else CurveStore.default()
    print(f"{'curve':<22}{'fetched':>9}{'in store':>10}{'first':>13}{'last':>13}")
    for curve_dir in sorted(p for p in work_dir.glob("*") if p.is_dir()):
        curve = curve_dir.name
        days = sorted(datetime.date.fromisoformat(p.stem) for p in curve_dir.glob("*.parquet"))
        in_store = sum(1 for d in days if store.has_day(asset_name(curve), d))
        first = days[0].isoformat() if days else "-"
        last = days[-1].isoformat() if days else "-"
        print(f"{curve:<22}{len(days):>9}{in_store:>10}{first:>13}{last:>13}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--base-dir", default=None, help="CurveStore base dir")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="pull minute par rates out of Excel")
    f.add_argument("--curves", required=True)
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    f.add_argument("--workbook-tag", default="WARM")
    f.add_argument("--force", action="store_true")
    f.add_argument(
        "--recycle-every", type=int, default=25,
        help="check Excel's memory every N windows and recycle the workbook "
             "if it is over the ceiling (0 disables)",
    )
    f.add_argument(
        "--memory-ceiling-mb", type=float, default=3000.0,
        help="recycle above this. Excel wedged at 5,250 MB on 2026-08-07.",
    )
    f.add_argument(
        "--memory-abort-mb", type=float, default=3800.0,
        help="stop the run when recycling can no longer hold Excel below this. "
             "The fetch resumes from disk, so stopping early costs only time.",
    )
    f.set_defaults(func=cmd_fetch)

    b = sub.add_parser("build", help="solve curves and write the CurveStore")
    b.add_argument("--curves", required=True)
    b.add_argument("--start", default=None)
    b.add_argument("--end", default=None)
    b.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    b.add_argument("--force", action="store_true")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    return args.func(args, LOGGER)


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import argparse
import datetime as dt
import json
import multiprocessing as mp
import os
import threading
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

import QuantLib as ql

from BT.misc import ql_cal_date_range


DEFAULT_SOURCE = "USTFO_DUAL-QL"
DEFAULT_ROOTS = ("TU", "FV", "TY", "TN", "US", "UL")
DEFAULT_CMTS = ("30", "60", "90")


@dataclass(frozen=True, order=True)
class DateRange:
    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"Invalid date range: {self.start.isoformat()} > {self.end.isoformat()}")

    @property
    def label(self) -> str:
        return f"{self.start.isoformat()}:{self.end.isoformat()}"


@dataclass
class RangeWarmResult:
    range_label: str
    start: str
    end: str
    date_count: int
    snapshot_requests: int
    smile_requests: int
    failure_count: int
    failures: list[dict[str, str]]
    duration_seconds: float


@dataclass
class WorkerProgress:
    range_label: str
    pid: int
    total_dates: int
    total_pairs: int
    completed_dates: int = 0
    completed_pairs: int = 0
    snapshot_requests: int = 0
    smile_requests: int = 0
    failure_count: int = 0
    current_date: str | None = None
    current_cmt: str | None = None
    started_monotonic: float = 0.0
    last_update_monotonic: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def _parse_iso_date(text: str) -> dt.date:
    return dt.date.fromisoformat(text.strip())


def parse_range_token(token: str) -> DateRange:
    parts = token.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Expected START:END, got {token!r}")
    return DateRange(start=_parse_iso_date(parts[0]), end=_parse_iso_date(parts[1]))


def split_contiguous_date_ranges(dates: Sequence[dt.date], chunks: int) -> list[DateRange]:
    if chunks < 1:
        raise ValueError("chunks must be >= 1")
    if not dates:
        return []

    chunk_count = min(int(chunks), len(dates))
    base, remainder = divmod(len(dates), chunk_count)
    out: list[DateRange] = []
    offset = 0
    for idx in range(chunk_count):
        width = base + (1 if idx < remainder else 0)
        chunk = dates[offset : offset + width]
        out.append(DateRange(start=chunk[0], end=chunk[-1]))
        offset += width
    return out


def ensure_non_overlapping(ranges: Sequence[DateRange]) -> list[DateRange]:
    ordered = sorted(ranges)
    for prev, curr in zip(ordered, ordered[1:]):
        if curr.start <= prev.end:
            raise ValueError(f"Date ranges overlap: {prev.label} and {curr.label}")
    return ordered


def build_business_date_ranges(start: dt.date, end: dt.date, chunks: int) -> list[DateRange]:
    business_dates = ql_cal_date_range(
        ql_cal=ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        start=start,
        end=end,
        to_date=True,
    )
    return split_contiguous_date_ranges(business_dates, chunks)


def _snapshot_symbols(roots: Sequence[str], cmt: str) -> list[str]:
    return [f"{root}_{cmt}|ATMS" for root in roots]


def _smile_symbols(roots: Sequence[str], cmt: str) -> list[str]:
    return [f"{root}_{cmt}" for root in roots]


def _bulk_warm_timestamps(dates: Sequence[dt.date]) -> list[dt.date]:
    ordered = list(dates)
    if len(ordered) != 1:
        return ordered
    end = ordered[0]
    window = ql_cal_date_range(
        ql_cal=ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        start=end - dt.timedelta(days=7),
        end=end,
        to_date=True,
    )
    if len(window) >= 2:
        return list(window[-2:])
    return ordered


def _is_retryable_warm_error(exc: Exception) -> bool:
    message = str(exc or "").strip().lower()
    retry_tokens = (
        "socks5 authentication failed",
        "failed to establish a new connection",
        "max retries exceeded",
        "connection aborted",
        "connection reset",
        "connection refused",
        "proxyerror",
        "connectionerror",
        "read timed out",
        "connect timeout",
    )
    return any(token in message for token in retry_tokens)


def _snapshot_worker_progress(progress: WorkerProgress, *, now_monotonic: float | None = None) -> dict[str, object]:
    now = time.perf_counter() if now_monotonic is None else float(now_monotonic)
    with progress.lock:
        return {
            "range_label": progress.range_label,
            "pid": progress.pid,
            "completed_dates": progress.completed_dates,
            "total_dates": progress.total_dates,
            "completed_pairs": progress.completed_pairs,
            "total_pairs": progress.total_pairs,
            "snapshot_requests": progress.snapshot_requests,
            "smile_requests": progress.smile_requests,
            "failure_count": progress.failure_count,
            "current_date": progress.current_date,
            "current_cmt": progress.current_cmt,
            "elapsed_seconds": round(now - progress.started_monotonic, 1),
            "idle_seconds": round(now - progress.last_update_monotonic, 1),
        }


def _format_worker_heartbeat(snapshot: dict[str, object], *, tag: str = "[heartbeat]") -> str:
    current_date = snapshot.get("current_date") or "-"
    current_cmt = snapshot.get("current_cmt") or "-"
    return (
        f"{tag}"
        f" pid={snapshot['pid']}"
        f" range={snapshot['range_label']}"
        f" dates={snapshot['completed_dates']}/{snapshot['total_dates']}"
        f" pairs={snapshot['completed_pairs']}/{snapshot['total_pairs']}"
        f" current_date={current_date}"
        f" current_cmt={current_cmt}"
        f" snapshot_calls={snapshot['snapshot_requests']}"
        f" smile_calls={snapshot['smile_requests']}"
        f" failures={snapshot['failure_count']}"
        f" elapsed_s={snapshot['elapsed_seconds']:.1f}"
        f" idle_s={snapshot['idle_seconds']:.1f}"
    )


def _heartbeat_loop(progress: WorkerProgress, stop_event: threading.Event, heartbeat_seconds: float) -> None:
    while not stop_event.wait(heartbeat_seconds):
        snapshot = _snapshot_worker_progress(progress)
        total_pairs = int(snapshot["total_pairs"])
        completed_pairs = int(snapshot["completed_pairs"])
        if total_pairs > 0 and completed_pairs >= total_pairs:
            return
        print(_format_worker_heartbeat(snapshot), flush=True)


def _warm_range(
    range_spec: DateRange,
    *,
    source: str,
    roots: tuple[str, ...],
    cmts: tuple[str, ...],
    warm_snapshot: bool,
    warm_smile: bool,
    use_ql_calculator: bool,
    startup_delay_seconds: float,
    heartbeat_seconds: float,
) -> RangeWarmResult:
    if startup_delay_seconds > 0:
        time.sleep(startup_delay_seconds)

    from MDP.USTFutures.USTFutureOptionMDP import USTFutureOptionMDP

    started_at = time.perf_counter()
    mdp = USTFutureOptionMDP(source=source)
    dates = ql_cal_date_range(
        ql_cal=ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        start=range_spec.start,
        end=range_spec.end,
        to_date=True,
    )
    total_pairs = len(dates) * len(cmts)
    now = time.perf_counter()
    progress = WorkerProgress(
        range_label=range_spec.label,
        pid=os.getpid(),
        total_dates=len(dates),
        total_pairs=total_pairs,
        started_monotonic=now,
        last_update_monotonic=now,
    )
    stop_event = threading.Event()
    heartbeat_thread: threading.Thread | None = None
    if heartbeat_seconds > 0:
        print(_format_worker_heartbeat(_snapshot_worker_progress(progress), tag="[worker-start]"), flush=True)
        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(progress, stop_event, float(heartbeat_seconds)),
            name=f"ustfo-heartbeat-{progress.pid}",
            daemon=True,
        )
        heartbeat_thread.start()

    failures: list[dict[str, str]] = []
    snapshot_requests = 0
    smile_requests = 0

    def _record_failure(*, date_label: str, cmt: str, exc: Exception) -> None:
        failures.append(
            {
                "date": date_label,
                "cmt": str(cmt),
                "error": str(exc),
                "traceback": traceback.format_exc(limit=8),
            }
        )

    def _run_single_date(trade_date: dt.date, cmt: str) -> None:
        nonlocal snapshot_requests, smile_requests
        if warm_snapshot:
            mdp.get_pricer(
                {
                    "endpoint": "option_snapshot",
                    "symbols": _snapshot_symbols(roots, cmt),
                    "timestamp": trade_date,
                    "show_tqdm": False,
                    "use_ql_calculator": use_ql_calculator,
                }
            )
            snapshot_requests += 1

        if warm_smile:
            mdp.fetch_bulk_sabr_smile(
                {
                    "globex_symbols": _smile_symbols(roots, cmt),
                    "timestamps": [trade_date],
                    "show_tqdm": False,
                }
            )
            smile_requests += 1

    try:
        source_upper = str(source).upper()
        for cmt in cmts:
            if source_upper == "USTFO_DUAL-QL":
                with progress.lock:
                    progress.current_date = range_spec.label
                    progress.current_cmt = str(cmt)
                    progress.last_update_monotonic = time.perf_counter()

                bulk_request = {
                    "globex_symbols": _smile_symbols(roots, cmt),
                    "timestamps": _bulk_warm_timestamps(dates),
                    "show_tqdm": False,
                    "use_ql_calculator": use_ql_calculator,
                }
                bulk_seeded = False
                for attempt in range(2):
                    try:
                        # Bulk SABR warming also seeds the dual-source ATM snapshot aliases.
                        mdp.fetch_bulk_sabr_smile(bulk_request)
                        if warm_snapshot:
                            snapshot_requests += len(dates)
                        if warm_smile:
                            smile_requests += len(dates)
                        bulk_seeded = True
                        break
                    except Exception as exc:
                        if attempt >= 1 or not _is_retryable_warm_error(exc):
                            break
                        time.sleep(float(attempt + 1))

                if bulk_seeded:
                    with progress.lock:
                        progress.completed_pairs += len(dates)
                        progress.completed_dates = min(len(dates), progress.completed_pairs // max(len(cmts), 1))
                        progress.snapshot_requests = snapshot_requests
                        progress.smile_requests = smile_requests
                        progress.failure_count = len(failures)
                        progress.last_update_monotonic = time.perf_counter()
                    continue

            for trade_date in dates:
                with progress.lock:
                    progress.current_date = trade_date.isoformat()
                    progress.current_cmt = str(cmt)
                    progress.last_update_monotonic = time.perf_counter()

                try:
                    _run_single_date(trade_date, cmt)
                except Exception as exc:
                    _record_failure(date_label=trade_date.isoformat(), cmt=str(cmt), exc=exc)
                finally:
                    with progress.lock:
                        progress.completed_pairs += 1
                        progress.completed_dates = min(len(dates), progress.completed_pairs // max(len(cmts), 1))
                        progress.snapshot_requests = snapshot_requests
                        progress.smile_requests = smile_requests
                        progress.failure_count = len(failures)
                        progress.last_update_monotonic = time.perf_counter()
    finally:
        stop_event.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=max(1.0, float(heartbeat_seconds) + 1.0))

    return RangeWarmResult(
        range_label=range_spec.label,
        start=range_spec.start.isoformat(),
        end=range_spec.end.isoformat(),
        date_count=len(dates),
        snapshot_requests=snapshot_requests,
        smile_requests=smile_requests,
        failure_count=len(failures),
        failures=failures,
        duration_seconds=round(time.perf_counter() - started_at, 3),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python MDP/USTFutures/warm_ustfo_cache_parallel.py",
        description="Warm the UST future options persistent cache in parallel over contiguous date ranges.",
    )
    parser.add_argument("--start", type=_parse_iso_date, help="Overall start date in YYYY-MM-DD format.")
    parser.add_argument("--end", type=_parse_iso_date, help="Overall end date in YYYY-MM-DD format.")
    parser.add_argument(
        "--range",
        dest="ranges",
        action="append",
        default=[],
        help="Explicit date range in START:END format. Repeat up to five times or more if needed.",
    )
    parser.add_argument("--chunks", type=int, default=5, help="Number of contiguous business-date ranges to create.")
    parser.add_argument("--workers", type=int, default=5, help="Maximum worker processes to run at once.")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help=f"USTFutureOptionMDP source. Default: {DEFAULT_SOURCE}.")
    parser.add_argument("--roots", nargs="+", default=list(DEFAULT_ROOTS), help="Future roots to warm.")
    parser.add_argument("--cmts", nargs="+", default=list(DEFAULT_CMTS), help="CMT buckets to warm.")
    parser.add_argument(
        "--startup-stagger-seconds",
        type=float,
        default=0.5,
        help="Delay each worker startup by index * this amount to reduce simultaneous pressure.",
    )
    parser.add_argument(
        "--warm-snapshot",
        dest="warm_snapshot",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Populate option snapshot cache entries.",
    )
    parser.add_argument(
        "--warm-smile",
        dest="warm_smile",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Populate SABR smile cache entries.",
    )
    parser.add_argument(
        "--use-ql-calculator",
        dest="use_ql_calculator",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pass use_ql_calculator through to option snapshot requests.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional output path for a JSON run summary.",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=60.0,
        help="Per-worker heartbeat interval in seconds. Set to 0 to disable worker heartbeats.",
    )
    return parser


def _resolve_ranges(args: argparse.Namespace) -> list[DateRange]:
    if args.ranges:
        return ensure_non_overlapping([parse_range_token(token) for token in args.ranges])

    if args.start is None or args.end is None:
        raise ValueError("Provide either --range START:END ... or both --start and --end.")

    if args.end < args.start:
        raise ValueError(f"Invalid overall range: {args.start.isoformat()} > {args.end.isoformat()}")

    ranges = build_business_date_ranges(args.start, args.end, args.chunks)
    if not ranges:
        raise ValueError("No business dates found in the requested span.")
    return ranges


def _run_parallel(args: argparse.Namespace, ranges: Sequence[DateRange]) -> list[RangeWarmResult]:
    max_workers = min(len(ranges), max(1, int(args.workers)))
    results: list[RangeWarmResult] = []
    ctx = mp.get_context("spawn")

    with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as executor:
        future_map = {}
        for idx, range_spec in enumerate(ranges):
            future = executor.submit(
                _warm_range,
                range_spec,
                source=str(args.source),
                roots=tuple(str(root).upper() for root in args.roots),
                cmts=tuple(str(cmt) for cmt in args.cmts),
                warm_snapshot=bool(args.warm_snapshot),
                warm_smile=bool(args.warm_smile),
                use_ql_calculator=bool(args.use_ql_calculator),
                startup_delay_seconds=float(args.startup_stagger_seconds) * idx,
                heartbeat_seconds=max(0.0, float(args.heartbeat_seconds)),
            )
            future_map[future] = range_spec

        for future in as_completed(future_map):
            result = future.result()
            results.append(result)
            print(
                "[done]"
                f" range={result.range_label}"
                f" dates={result.date_count}"
                f" snapshot_calls={result.snapshot_requests}"
                f" smile_calls={result.smile_requests}"
                f" failures={result.failure_count}"
                f" duration_s={result.duration_seconds:.3f}"
            )

    return sorted(results, key=lambda item: item.start)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    started_at = time.perf_counter()

    if not args.warm_snapshot and not args.warm_smile:
        parser.error("At least one of --warm-snapshot or --warm-smile must be enabled.")

    ranges = _resolve_ranges(args)
    print(f"[start] ranges={len(ranges)} workers={min(len(ranges), max(1, int(args.workers)))} source={args.source}")
    for range_spec in ranges:
        print(f"[range] {range_spec.label}")

    results = _run_parallel(args, ranges)
    failure_count = sum(result.failure_count for result in results)
    payload = {
        "source": str(args.source),
        "roots": [str(root).upper() for root in args.roots],
        "cmts": [str(cmt) for cmt in args.cmts],
        "warm_snapshot": bool(args.warm_snapshot),
        "warm_smile": bool(args.warm_smile),
        "workers": min(len(ranges), max(1, int(args.workers))),
        "ranges": [asdict(result) for result in results],
        "summary": {
            "range_count": len(results),
            "date_count": sum(result.date_count for result in results),
            "snapshot_requests": sum(result.snapshot_requests for result in results),
            "smile_requests": sum(result.smile_requests for result in results),
            "failure_count": failure_count,
            "sum_worker_duration_seconds": round(sum(result.duration_seconds for result in results), 3),
            "wall_clock_seconds": round(time.perf_counter() - started_at, 3),
        },
    }

    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(payload, indent=2, sort_keys=True))
        print(f"[report] wrote {args.report_json}")

    print(
        "[summary]"
        f" ranges={payload['summary']['range_count']}"
        f" dates={payload['summary']['date_count']}"
        f" snapshot_calls={payload['summary']['snapshot_requests']}"
        f" smile_calls={payload['summary']['smile_requests']}"
        f" failures={payload['summary']['failure_count']}"
    )
    return 0 if failure_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

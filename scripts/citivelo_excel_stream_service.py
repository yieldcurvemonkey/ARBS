r"""Live Citi Velocity curve daemon: ``CVSTREAM`` cells -> a CurveStore snapshot per tick.

    conda run -n stir python scripts/citivelo_excel_stream_service.py run
    conda run -n stir python scripts/citivelo_excel_stream_service.py run --once
    conda run -n stir python scripts/citivelo_excel_stream_service.py run \
        --curves USD-SOFR-1D,EUR-ESTR-1D --poll-seconds 30 --stop-at 17:00
    conda run -n stir python scripts/citivelo_excel_stream_service.py status

Reads back through the CurveStore asset ``<curve_name>-CITIVELOSTREAM``.

Operational notes that are not optional
---------------------------------------
* It drives the **user's own signed-in Excel**. Writing happens once, at startup
  (one RTD cell per tenor per curve); every poll after that only reads.
* Its workbook is **never closed** - an RTD cell always has queued add-in actions
  against it and tearing one down crashes Excel. Stopping the daemon leaves an
  orphaned scratch workbook, which is the cheap side of that trade.
* **Never ``Stop-Process`` it.** Ctrl-C is handled and exits cleanly. Killing it
  mid-COM-call wedges Excel's OLE server.
* One instance at a time: two processes writing into one Excel is how regions
  overlap. A file lock enforces it.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import logging
import os
import pathlib
import sys
import tempfile
from logging.handlers import RotatingFileHandler

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_CURVES = "USD-SOFR-1D,EUR-ESTR-1D,GBP-SONIA-1D,JPY-TONAR-1D,CAD-CORRA-1D"
_LOCK_NAME = "citivelo_excel_stream"

logger = logging.getLogger("citivelo_excel_stream_service")


class SingleInstanceLock:
    """One daemon per machine. Two writers into one Excel is crash trigger 1."""

    def __init__(self, name: str):
        d = pathlib.Path(tempfile.gettempdir()) / "arbs_citivelo_excel_stream"
        d.mkdir(parents=True, exist_ok=True)
        self._path = d / f"{name}.lock"
        self._fd = None

    @staticmethod
    def _alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            import psutil

            return psutil.pid_exists(pid)
        except Exception:  # noqa: BLE001
            return True

    def acquire(self) -> bool:
        try:
            self._fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(self._path.read_text().strip() or "-1")
            except (OSError, ValueError):
                pid = -1
            if pid > 0 and self._alive(pid):
                return False
            with contextlib.suppress(OSError):
                self._path.unlink()
            try:
                self._fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return False
        os.write(self._fd, str(os.getpid()).encode())
        return True

    def release(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None
        with contextlib.suppress(FileNotFoundError):
            self._path.unlink()


def _setup_logging(log_dir: pathlib.Path, verbose: bool) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "stream_service.log", maxBytes=8_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(handler)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root.addHandler(console)


def run(args: argparse.Namespace) -> int:
    from MDP.IRSwaps.CITIVELO_EXCEL.stream_daemon import CitiVeloStreamDaemon

    curves = [c.strip().upper() for c in args.curves.split(",") if c.strip()]
    stop_at = None
    if args.stop_at:
        hh, mm = args.stop_at.split(":")
        stop_at = datetime.time(int(hh), int(mm))

    lock = SingleInstanceLock(_LOCK_NAME)
    if not lock.acquire():
        logger.error(
            "another citivelo_excel stream daemon holds the lock (%s). Two processes writing "
            "into one Excel is how CvFunction regions overlap, which kills the process.",
            lock._path,
        )
        return 2

    daemon = CitiVeloStreamDaemon(
        curves,
        poll_seconds=args.poll_seconds,
        push_l2=args.push_l2,
        persist=not args.no_persist,
        min_tenors=args.min_tenors,
    )
    try:
        opened = daemon.open()
        logger.info("opened live cells: %s", opened)
        summary = daemon.run(once=args.once, max_polls=args.max_polls, stop_at=stop_at)
        logger.info("summary: %s", json.dumps(summary, indent=1))
        print(json.dumps(summary, indent=1))
        return 0
    except Exception:  # noqa: BLE001
        logger.exception("citivelo_excel stream daemon failed")
        return 3
    finally:
        daemon.close()
        lock.release()


def status(args: argparse.Namespace) -> int:
    from Caching.curve_store import CurveStore
    from MDP.IRSwaps.CITIVELO_EXCEL.stream_daemon import DEFAULT_ASSET_SUFFIX

    store = CurveStore.default()
    curves = [c.strip().upper() for c in args.curves.split(",") if c.strip()]
    print(f"{'asset':<34}{'days':>6}{'first':>13}{'last':>13}{'rows(last)':>12}")
    for name in curves:
        asset = f"{name}-{DEFAULT_ASSET_SUFFIX}"
        try:
            days = store.available_dates(asset)
        except Exception as exc:  # noqa: BLE001
            print(f"{asset:<34}  {type(exc).__name__}: {exc}")
            continue
        if not days:
            print(f"{asset:<34}{0:>6}")
            continue
        frame = store.read_raw_day(asset, days[-1])
        n = 0 if frame is None else len(frame)
        print(
            f"{asset:<34}{len(days):>6}{days[0].isoformat():>13}{days[-1].isoformat():>13}{n:>12}"
        )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    sub = parser.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="poll live CVSTREAM cells and persist curves")
    r.add_argument("--curves", default=DEFAULT_CURVES)
    r.add_argument("--poll-seconds", type=float, default=60.0)
    r.add_argument("--stop-at", default="", help="local HH:MM to stop at, e.g. 17:00")
    r.add_argument("--once", action="store_true")
    r.add_argument("--max-polls", type=int, default=None)
    r.add_argument("--min-tenors", type=int, default=8)
    r.add_argument("--push-l2", action="store_true", help="also push each day to Supabase")
    r.add_argument("--no-persist", action="store_true", help="build but do not write")
    r.add_argument("--verbose", action="store_true")
    r.set_defaults(func=run)

    s = sub.add_parser("status", help="what is in the store")
    s.add_argument("--curves", default=DEFAULT_CURVES)
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(func=status)

    args = parser.parse_args(argv)
    _setup_logging(_REPO_ROOT / "logs" / "citivelo_excel_stream", args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

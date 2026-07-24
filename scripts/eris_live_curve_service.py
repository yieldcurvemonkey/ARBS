"""Poll the live ERIS SOFR curve every minute and persist each fresh curve
handle as one indexed row in arbs_curve_snapshots_v1 (asset USD-SOFR-1D-ERISLIVE).

Per-session daemon: starts in the morning, loops with a drift-free 60s cadence
during the US session, exits after --stop-at. Read back via
IRSwapsMDP(source="eris_live_intraday").

Usage:
    conda run -n stir python scripts/eris_live_curve_service.py run
    conda run -n stir python scripts/eris_live_curve_service.py run --once
"""
from __future__ import annotations

# ── MUST precede any Caching / fetcher import ──
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "1")  # engine ON for our writes

import argparse
import contextlib
import datetime
import gc
import logging
import sys
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Tuple

import pytz
import QuantLib as ql

from Caching.curve_store import CurveSnapshot

logger = logging.getLogger("eris_live_curve_service")

ASSET_NAME = "USD-SOFR-1D-ERISLIVE"
REFERENCE_KEY = "USD-SOFR-1D"
SOURCE_VARIANT = "ERIS_RL_BASIC_NOJUMPS"
SOURCE_STRING = "ERIS_EOD_LIVE-RL_BASIC-NOJUMPS"
CURVE_NAME = "USD-SOFR-1D"
SESSION_START_MIN = 8 * 60   # 08:00 ET
SESSION_END_MIN = 17 * 60    # 17:00 ET

_ET = pytz.timezone("America/New_York")
_UTC = pytz.UTC
_CHI = pytz.timezone("America/Chicago")
_QL_CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)


def is_business_day(d: datetime.date) -> bool:
    return _QL_CAL.isBusinessDay(ql.Date(d.day, d.month, d.year))


def in_session(now_et: datetime.datetime, *, start_min: int, end_min: int) -> bool:
    m = now_et.hour * 60 + now_et.minute
    return start_min <= m < end_min


def should_persist(
    vendor_ts, now_et, ref_date, last_ts, *, max_lag_seconds: int = 90
) -> Tuple[bool, str]:
    """Gate a poll result before writing. Returns (persist?, reason)."""
    if vendor_ts is None or getattr(vendor_ts, "tzinfo", None) is None:
        return False, "tz: vendor timestamp missing or naive"
    if last_ts is not None and vendor_ts == last_ts:
        return False, "unchanged: vendor timestamp same as last poll"
    lag = (now_et - vendor_ts.astimezone(now_et.tzinfo)).total_seconds()
    if lag > max_lag_seconds:
        return False, f"stale: vendor timestamp {lag:.0f}s old (> {max_lag_seconds}s)"
    # The ERIS EOD-live curve legitimately rolls its reference (first-node) date to
    # the NEXT business day during the evening/overnight session, so an exact
    # "== today" check would reject the entire overnight session. The vendor_ts
    # recency check above is the real staleness signal; here we only reject a
    # reference date that is wildly off (e.g. a stale/wrong 200-OK file).
    if ref_date is None:
        return False, "reference_date missing"
    if abs((ref_date - now_et.date()).days) > 7:
        return False, f"reference_date {ref_date} far from today {now_et.date()} (stale/wrong file?)"
    return True, "ok"


def build_snapshot(curve, vendor_ts) -> CurveSnapshot:
    """Build a CurveSnapshot from a live RLIRSwapCurve + its vendor stamp."""
    from Caching.curve_store import _to_date

    handle = curve.handle()
    raw_nodes = handle.nodes._nodes if hasattr(handle.nodes, "_nodes") else dict(handle.nodes)
    nd_sorted = sorted(raw_nodes.keys())
    node_dates = [_to_date(d) for d in nd_sorted]
    discount_factors = [float(raw_nodes[d]) for d in nd_sorted]

    ts = vendor_ts
    if ts.tzinfo is None:
        ts = _ET.localize(ts)
    ts_utc = ts.astimezone(_UTC).replace(microsecond=0)
    ts_et = ts_utc.astimezone(_ET)
    return CurveSnapshot(
        timestamp_utc=ts_utc,
        timestamp_local=ts_utc.astimezone(_CHI),
        trading_date=ts_et.date(),
        session_minute=int(ts_et.hour * 60 + ts_et.minute),
        curve_name=ASSET_NAME,
        cfg_hash="",
        reference_key=REFERENCE_KEY,
        interpolation="log_linear",
        source_variant=SOURCE_VARIANT,
        node_dates=node_dates,
        discount_factors=discount_factors,
    )


class SingleInstanceLock:
    """O_CREAT|O_EXCL single-instance lock with stale-PID reclamation."""

    def __init__(self, name: str):
        lock_dir = Path(tempfile.gettempdir()) / "arbs_eris_live_curve"
        lock_dir.mkdir(parents=True, exist_ok=True)
        self._path = lock_dir / f"{name}.lock"
        self._fd = None

    def _pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            import psutil
            return psutil.pid_exists(pid)
        except Exception:
            pass
        if sys.platform == "win32":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k32 = ctypes.windll.kernel32
            handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                # ERROR_INVALID_PARAMETER(87)=no such pid -> dead; anything else -> assume alive
                return k32.GetLastError() != 87
            try:
                code = ctypes.c_ulong()
                if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return True  # ambiguous -> assume alive
                return code.value == STILL_ACTIVE
            finally:
                k32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    def acquire(self) -> bool:
        try:
            self._fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # stale-PID reclaim
            try:
                pid = int(self._path.read_text().strip() or "-1")
            except (OSError, ValueError):
                pid = -1
            if pid > 0 and self._pid_alive(pid):
                return False
            with contextlib.suppress(OSError):
                self._path.unlink()
            try:
                self._fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return False
        os.write(self._fd, str(os.getpid()).encode("utf-8"))
        return True

    def release(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None
        with contextlib.suppress(FileNotFoundError):
            self._path.unlink()


def _build_mdp():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    # error_verbose left off: this fetcher's BaseFetcher._setup_logger bakes a
    # "%Y-%m-%d %H:%M:%S" into the message format (should be datefmt), so every
    # fetch-error record spams a "--- Logging error ---" traceback to stderr
    # (logging catches it, so it doesn't crash — just noise, amplified by the
    # fetcher's retry loop). The daemon's own per-cycle logging (below) captures
    # each poll outcome; total-fetch-failure still surfaces as a caught ValueError.
    return IRSwapsMDP(source=SOURCE_STRING)


def poll_once(mdp):
    """One live poll. Returns the RLIRSwapCurve; raises on failure."""
    return mdp.get_pricer({"curve_name": CURVE_NAME, "timestamp": "live"})  # fresh dict each call


def _write_snapshot(sync, curve, vendor_ts) -> None:
    snap = build_snapshot(curve, vendor_ts)
    ok = sync.upsert_snapshot_row(snap, ASSET_NAME)
    if not ok:
        raise RuntimeError("upsert_snapshot_row returned False (engine unavailable or schema-ensure failed)")


def _default_writer(curve, vendor_ts):
    from Caching.supabase_curve_sync import SupabaseCurveSync
    _write_snapshot(SupabaseCurveSync.from_defaults(), curve, vendor_ts)


def run_service(
    *,
    poll_fn,
    now_fn,
    writer_fn,
    sleep_fn=time.sleep,
    stop_fn,
    poll_seconds: int = 60,
    start_min: int = SESSION_START_MIN,
    end_min: int = SESSION_END_MIN,
    last_ts=None,
) -> dict:
    counters = {"wrote": 0, "skipped": 0, "errors": 0, "polls": 0}
    cycle = 0
    while True:
        now_et = now_fn()
        if stop_fn(now_et):
            break
        t0 = time.monotonic()  # capture before gc/poll so the sleep stays drift-free
        cycle += 1
        if cycle % 120 == 0:  # light hygiene for a long-lived (24/5) process
            gc.collect()
        if is_business_day(now_et.date()) and in_session(now_et, start_min=start_min, end_min=end_min):
            counters["polls"] += 1
            try:
                curve = poll_fn()
                vendor_ts = curve.meta().get("timestamp")
                rd = curve.reference_date()
                ref_date = rd.date() if rd is not None else now_et.date()
                ok, reason = should_persist(vendor_ts, now_et, ref_date, last_ts)
                if ok:
                    writer_fn(curve, vendor_ts)
                    last_ts = vendor_ts
                    counters["wrote"] += 1
                    logger.info("wrote snapshot ts=%s nodes<-curve", vendor_ts)
                else:
                    counters["skipped"] += 1
                    logger.info("skip: %s", reason)
            except ValueError as exc:  # non-business-day guard OR empty-fetch unpack
                counters["skipped"] += 1
                logger.warning("skip poll (ValueError): %s", exc)
            except Exception:  # network/fixings/parse — isolate the cycle
                counters["errors"] += 1
                logger.exception("poll failed; continuing")
        sleep_fn(max(0.0, poll_seconds - (time.monotonic() - t0)))
    return counters


def _configure_logging(log_dir: str) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("eris_live_curve_service")
    if not logger.handlers:
        handler = RotatingFileHandler(Path(log_dir) / "eris_live_curve_service.log",
                                      maxBytes=10 * 1024 * 1024, backupCount=7)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.addHandler(logging.StreamHandler())
        logger.setLevel(logging.INFO)


def _parse_hm(s: str) -> int:
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="ERIS live intraday curve snapshot service")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--once", action="store_true", help="single poll then exit")
    run.add_argument("--poll-seconds", type=int, default=60)
    run.add_argument("--session-start", default="08:00")
    run.add_argument("--session-end", default="17:00")
    run.add_argument("--stop-at", default="17:15")
    run.add_argument(
        "--continuous",
        action="store_true",
        help="run around the clock on business days (ERIS publishes ~23/5 CME hours); "
             "ignores --session-start/--session-end/--stop-at",
    )
    run.add_argument(
        "--max-runtime-hours",
        type=float,
        default=0.0,
        help="continuous mode only: 0 = run until stopped; >0 = self-exit after N hours",
    )
    run.add_argument("--log-dir", default=str(Path("logs") / "eris_live_curve_service"))
    args = parser.parse_args(argv)

    _configure_logging(args.log_dir)

    # Suppress the ERIS fetcher's dead per-poll L2 KV write. Done here (not at
    # import) so importing this module for its helpers/CLI does not mutate the
    # shared LayeredCacheMixin.L2_WRITE class attribute for the whole process.
    from Caching.layered_cache_mixin import LayeredCacheMixin
    LayeredCacheMixin.L2_WRITE = False

    lock = SingleInstanceLock("eris-live-curve")
    if not lock.acquire():
        logger.error("another instance holds the lock; exiting")
        return 3
    try:
        from Caching.supabase_curve_sync import SupabaseCurveSync
        sync = SupabaseCurveSync.from_defaults()

        mdp = _build_mdp()
        if args.once:
            now_et = datetime.datetime.now(_ET)
            if not (is_business_day(now_et.date()) and in_session(
                now_et, start_min=_parse_hm(args.session_start), end_min=_parse_hm(args.session_end))):
                logger.warning("--once outside session/holiday; polling anyway for smoke")
            curve = poll_once(mdp)
            vendor_ts = curve.meta().get("timestamp")
            _write_snapshot(sync, curve, vendor_ts)
            logger.info("--once wrote snapshot ts=%s", vendor_ts)
            return 0

        if args.continuous:
            # Full-day window (is_business_day still gates weekends/holidays);
            # ERIS publishes ~around the clock on trading days.
            start_min, end_min = 0, 24 * 60
            run_start = time.monotonic()
            max_runtime_s = max(0.0, args.max_runtime_hours) * 3600.0

            def stop_fn(now_et):
                return max_runtime_s > 0 and (time.monotonic() - run_start) >= max_runtime_s

            logger.info(
                "continuous mode: business-day-gated, poll=%ss, max_runtime=%s",
                args.poll_seconds,
                f"{args.max_runtime_hours}h" if max_runtime_s > 0 else "unbounded",
            )
        else:
            start_min, end_min = _parse_hm(args.session_start), _parse_hm(args.session_end)
            stop_min = _parse_hm(args.stop_at)

            def stop_fn(now_et):
                return (now_et.hour * 60 + now_et.minute) >= stop_min

        initial_last_ts = sync.latest_snapshot_ts(ASSET_NAME, datetime.datetime.now(_ET).date())

        counters = run_service(
            poll_fn=lambda: poll_once(mdp),
            now_fn=lambda: datetime.datetime.now(_ET),
            writer_fn=lambda curve, ts: _write_snapshot(sync, curve, ts),
            stop_fn=stop_fn,
            poll_seconds=args.poll_seconds,
            start_min=start_min,
            end_min=end_min,
            last_ts=initial_last_ts,
        )
        logger.info("service done: %s", counters)
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())

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

from Caching.layered_cache_mixin import LayeredCacheMixin

LayeredCacheMixin.L2_WRITE = False  # kill the fetcher's dead ~820KB/poll KV write

import argparse
import contextlib
import datetime
import logging
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
    if ref_date != now_et.date():
        return False, f"reference_date {ref_date} != today {now_et.date()}"
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

from __future__ import annotations

import datetime
import hashlib
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from Caching.timeseries_cache import _atomic_write_bytes, _sanitize_symbol, _write_parquet_bytes

logger = logging.getLogger(__name__)

DEFAULT_COMPRESSION = "zstd"


def _get_ustf_sync(base_dir: Optional[Union[str, Path]] = None):
    from Caching.supabase_engine import SUPABASE_ENABLED

    if not SUPABASE_ENABLED:
        return None

    from Caching.supabase_engine import get_engine
    from Caching.supabase_ustf_sync import SupabaseUSTFutureSync

    if base_dir is None:
        return SupabaseUSTFutureSync.from_defaults()
    return SupabaseUSTFutureSync(base_dir=Path(base_dir), engine=get_engine())


class USTFutureStore:
    _default_instance: Optional["USTFutureStore"] = None
    _default_lock = threading.Lock()

    @classmethod
    def default(cls) -> "USTFutureStore":
        if cls._default_instance is None:
            with cls._default_lock:
                if cls._default_instance is None:
                    cls._default_instance = cls()
        return cls._default_instance

    def __init__(
        self,
        base_dir: Optional[Union[str, Path]] = None,
        compression: str = DEFAULT_COMPRESSION,
        bg_push_workers: Optional[int] = None,
    ) -> None:
        self._base_dir = Path(base_dir) if base_dir is not None else self._default_base_dir()
        self._compression = compression
        self._snapshots_dir = self._base_dir / "snapshots"
        self._basis_reports_dir = self._base_dir / "basis_reports"
        self._bg_push_threads: list[threading.Thread] = []
        self._bg_push_lock = threading.Lock()
        self._bg_push_condition = threading.Condition(self._bg_push_lock)
        self._bg_push_queue: queue.Queue[tuple[Any, str, str, datetime.date]] = queue.Queue()
        self._bg_push_pending = 0
        self._bg_push_worker_count = self._resolve_bg_push_workers(bg_push_workers)

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @staticmethod
    def _default_base_dir() -> Path:
        arbs_cache = os.getenv("ARBS_CACHE_DIR")
        if arbs_cache:
            return Path(arbs_cache) / "ust_future_store"
        try:
            from platformdirs import user_cache_dir

            return Path(user_cache_dir(appname="ARBS", appauthor=False)) / "ust_future_store"
        except Exception:
            if os.name == "nt":
                return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ARBS" / "Cache" / "ust_future_store"
            return Path.home() / ".cache" / "arbs" / "ust_future_store"

    @staticmethod
    def _resolve_bg_push_workers(bg_push_workers: Optional[int]) -> int:
        if bg_push_workers is None:
            raw_value = os.getenv("ARBS_USTF_STORE_BG_PUSH_WORKERS")
            if raw_value is None or raw_value == "":
                return 2
            try:
                bg_push_workers = int(raw_value)
            except ValueError:
                logger.warning("Invalid ARBS_USTF_STORE_BG_PUSH_WORKERS=%r; defaulting to 2", raw_value)
                return 2
        return max(1, int(bg_push_workers))

    def _ensure_bg_push_workers(self) -> None:
        threads_to_start: list[threading.Thread] = []
        with self._bg_push_lock:
            self._bg_push_threads = [thread for thread in self._bg_push_threads if thread.is_alive()]
            while len(self._bg_push_threads) < self._bg_push_worker_count:
                worker_idx = len(self._bg_push_threads) + 1
                thread = threading.Thread(
                    target=self._bg_push_worker,
                    name=f"ust-future-store-bg-push-{worker_idx}",
                    daemon=True,
                )
                self._bg_push_threads.append(thread)
                threads_to_start.append(thread)
        for thread in threads_to_start:
            thread.start()

    def _bg_push_worker(self) -> None:
        while True:
            sync, kind, symbol, trading_date = self._bg_push_queue.get()
            try:
                if kind == "snapshot":
                    sync.push_snapshot_day(symbol, trading_date)
                else:
                    sync.push_basis_report_day(symbol, trading_date)
            except Exception:
                logger.warning("UST future CORE push failed for %s/%s (%s)", symbol, trading_date, kind, exc_info=True)
            finally:
                with self._bg_push_condition:
                    self._bg_push_pending = max(0, self._bg_push_pending - 1)
                    if self._bg_push_pending == 0:
                        self._bg_push_condition.notify_all()
                self._bg_push_queue.task_done()

    def _enqueue_bg_push(
        self,
        sync: Any,
        *,
        kind: str,
        symbol: str,
        trading_date: datetime.date,
    ) -> None:
        self._ensure_bg_push_workers()
        with self._bg_push_condition:
            self._bg_push_pending += 1
        self._bg_push_queue.put((sync, kind, symbol, trading_date))

    def wait_for_background_pushes(self, timeout: Optional[float] = None) -> int:
        deadline = None if timeout is None else (time.monotonic() + float(timeout))
        with self._bg_push_condition:
            waited = self._bg_push_pending
            while self._bg_push_pending > 0:
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                if remaining is not None and remaining <= 0.0:
                    return waited
                self._bg_push_condition.wait(timeout=remaining)
                if deadline is not None and time.monotonic() >= deadline and self._bg_push_pending > 0:
                    return waited
            return waited

    def _partition_dir(self, symbol: str, trading_date: datetime.date, *, kind: str) -> Path:
        root = self._snapshots_dir if kind == "snapshot" else self._basis_reports_dir
        return root / f"asset={_sanitize_symbol(symbol)}" / f"date={trading_date.isoformat()}"

    def _write_partition(
        self,
        *,
        symbol: str,
        trading_date: datetime.date,
        df: pd.DataFrame,
        kind: str,
        overwrite: bool = False,
    ) -> Optional[dict]:
        if df is None or df.empty:
            return None
        table = pa.Table.from_pandas(df, preserve_index=False)
        payload = _write_parquet_bytes(table, compression=self._compression)
        sha = hashlib.sha256(payload).hexdigest()
        part_dir = self._partition_dir(symbol, trading_date, kind=kind)
        final_path = part_dir / f"{sha}.parquet"

        if final_path.exists() and not overwrite:
            return None

        if overwrite:
            for old_path in part_dir.glob("*.parquet"):
                try:
                    old_path.unlink()
                except OSError:
                    pass

        _atomic_write_bytes(final_path, payload)

        sync = _get_ustf_sync(self._base_dir)
        if sync is not None:
            self._enqueue_bg_push(sync, kind=kind, symbol=symbol, trading_date=trading_date)

        return {"path": str(final_path), "size": len(payload), "sha256": sha}

    def _read_partition(self, *, symbol: str, trading_date: datetime.date, kind: str) -> pd.DataFrame:
        part_dir = self._partition_dir(symbol, trading_date, kind=kind)
        pq_files = sorted(part_dir.glob("*.parquet"))
        if not pq_files:
            sync = _get_ustf_sync(self._base_dir)
            pulled = False
            if sync is not None:
                if kind == "snapshot":
                    pulled = bool(sync.pull_snapshot_day(symbol, trading_date))
                else:
                    pulled = bool(sync.pull_basis_report_day(symbol, trading_date))
            if not pulled:
                return pd.DataFrame()
            pq_files = sorted(part_dir.glob("*.parquet"))
            if not pq_files:
                return pd.DataFrame()

        tables = [pq.read_table(path) for path in pq_files]
        table = tables[0] if len(tables) == 1 else pa.concat_tables(tables, promote_options="default")
        df = table.to_pandas()
        if "timestamp_utc" in df.columns:
            df = df.sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True)
        return df

    def write_snapshot_day(
        self,
        symbol: str,
        trading_date: datetime.date,
        df: pd.DataFrame,
        *,
        overwrite: bool = False,
    ) -> Optional[dict]:
        return self._write_partition(symbol=symbol, trading_date=trading_date, df=df, kind="snapshot", overwrite=overwrite)

    def read_snapshot_day(self, symbol: str, trading_date: datetime.date) -> pd.DataFrame:
        return self._read_partition(symbol=symbol, trading_date=trading_date, kind="snapshot")

    def has_snapshot_day(self, symbol: str, trading_date: datetime.date) -> bool:
        part_dir = self._partition_dir(symbol, trading_date, kind="snapshot")
        return part_dir.exists() and any(part_dir.glob("*.parquet"))

    def write_basis_report_day(
        self,
        symbol: str,
        trading_date: datetime.date,
        df: pd.DataFrame,
        *,
        overwrite: bool = False,
    ) -> Optional[dict]:
        return self._write_partition(symbol=symbol, trading_date=trading_date, df=df, kind="basis_report", overwrite=overwrite)

    def read_basis_report_day(self, symbol: str, trading_date: datetime.date) -> pd.DataFrame:
        return self._read_partition(symbol=symbol, trading_date=trading_date, kind="basis_report")

    def has_basis_report_day(self, symbol: str, trading_date: datetime.date) -> bool:
        part_dir = self._partition_dir(symbol, trading_date, kind="basis_report")
        return part_dir.exists() and any(part_dir.glob("*.parquet"))

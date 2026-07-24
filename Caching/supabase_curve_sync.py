"""Bidirectional sync between local CurveStore Parquet and Supabase Postgres.

Usage:
    sync = SupabaseCurveSync.from_defaults()
    sync.push_day("USD-SOFR-1D", date(2025, 1, 15))   # local -> Supabase
    sync.pull_day("USD-SOFR-1D", date(2025, 1, 15))   # Supabase -> local
    sync.prefetch_range("USD-SOFR-1D", start, end)     # bulk download missing days
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional, Sequence

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

_SLUG_RX = re.compile(r"[^\w.\-]")
CURVE_SNAPSHOTS_TABLE = "arbs_curve_snapshots_v1"
CURVE_INTRADAY_BLOCKS_TABLE = "arbs_curve_intraday_blocks_v1"
CURVE_ANALYTICS_BLOCKS_TABLE = "arbs_curve_analytics_blocks_v1"


def _sanitize(name: str) -> str:
    return _SLUG_RX.sub("_", name)


def _to_python_date(value: object) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value))


def _snapshot_insert_params(snap, curve_name: str) -> dict:
    """Bound-param dict for a single untagged arbs_curve_snapshots_v1 upsert."""
    return {
        "curve_name": curve_name,
        "timestamp_utc": snap.timestamp_utc,
        "trading_date": snap.trading_date,
        "session_minute": int(snap.session_minute),
        "tags": [],  # untagged; TEXT[] NOT NULL DEFAULT '{}' accepts an empty list
        "cfg_hash": str(snap.cfg_hash),
        "reference_key": str(snap.reference_key),
        "interpolation": str(snap.interpolation),
        "source_variant": str(snap.source_variant),
        "node_dates": [_to_python_date(d) for d in snap.node_dates],
        "discount_factors": [float(v) for v in snap.discount_factors],
    }


def _pick_nearest(target_utc, rows: list) -> Optional[dict]:
    """Row with minimum absolute time distance to target_utc (None if empty)."""
    best = None
    best_delta = None
    for r in rows:
        delta = abs((r["timestamp_utc"] - target_utc).total_seconds())
        if best_delta is None or delta < best_delta:
            best, best_delta = r, delta
    return best


class SupabaseCurveSync:
    """Sync CurveStore Parquet files with Supabase curve tables."""

    def __init__(self, base_dir: Path, engine: Optional[Engine]):
        self._base_dir = Path(base_dir)
        self._engine = engine

    @classmethod
    def from_defaults(cls) -> "SupabaseCurveSync":
        from Caching.curve_store import CurveStore
        from Caching.supabase_engine import get_engine

        store = CurveStore.default()
        return cls(base_dir=store.base_dir, engine=get_engine())

    def _partition_dir(
        self,
        curve_name: str,
        trading_date: datetime.date,
        *,
        kind: str = "raw",
    ) -> Path:
        return (
            self._base_dir
            / kind
            / f"asset={_sanitize(curve_name)}"
            / f"date={trading_date.isoformat()}"
        )

    def _local_parquet_bytes(
        self,
        curve_name: str,
        trading_date: datetime.date,
        *,
        kind: str = "raw",
    ) -> Optional[bytes]:
        part_dir = self._partition_dir(curve_name, trading_date, kind=kind)
        if not part_dir.exists():
            return None
        pq_files = list(part_dir.glob("*.parquet"))
        if not pq_files:
            return None
        # Read the first (should be only) Parquet file
        return pq_files[0].read_bytes()

    def push_day(
        self,
        curve_name: str,
        trading_date: datetime.date,
        *,
        event_calendar: dict | None = None,
    ) -> bool:
        """Push a day's Parquet blob from local to Supabase.

        Returns True if upserted, False if skipped (no engine or no local data).
        """
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False
        payload = self._local_parquet_bytes(curve_name, trading_date, kind="raw")
        if payload is None:
            return False

        sha = hashlib.sha256(payload).hexdigest()
        # Count rows by reading Parquet metadata
        import pyarrow.parquet as pq
        import io

        table = pq.read_table(io.BytesIO(payload))
        row_count = table.num_rows

        with self._engine.begin() as conn:
            conn.execute(
                text(f"""
                    INSERT INTO {CURVE_INTRADAY_BLOCKS_TABLE}
                        (trading_date, curve_name, data_format, row_count, payload, sha256)
                    VALUES
                        (:trading_date, :curve_name, :data_format, :row_count, :payload, :sha256)
                    ON CONFLICT (trading_date, curve_name) DO UPDATE SET
                        data_format = EXCLUDED.data_format,
                        row_count = EXCLUDED.row_count,
                        payload = EXCLUDED.payload,
                        sha256 = EXCLUDED.sha256,
                        created_at = NOW()
                """),
                {
                    "trading_date": trading_date,
                    "curve_name": curve_name,
                    "data_format": "parquet_zstd",
                    "row_count": row_count,
                    "payload": payload,
                    "sha256": sha,
                },
            )

            # Extract and push priority snapshots
            if event_calendar is None:
                event_calendar = {}
            self._push_tagged_snapshots(conn, table, curve_name, trading_date, event_calendar)

        logger.info(
            "Pushed %s/%s to Supabase (%d rows, %d bytes)",
            curve_name, trading_date, row_count, len(payload),
        )
        return True

    def push_analytics_day(
        self,
        curve_name: str,
        trading_date: datetime.date,
    ) -> bool:
        """Push a day's analytics Parquet blob from local storage to Supabase."""
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False
        payload = self._local_parquet_bytes(curve_name, trading_date, kind="analytics")
        if payload is None:
            return False

        sha = hashlib.sha256(payload).hexdigest()
        import io
        import pyarrow.parquet as pq

        table = pq.read_table(io.BytesIO(payload))
        row_count = table.num_rows

        with self._engine.begin() as conn:
            conn.execute(
                text(f"""
                    INSERT INTO {CURVE_ANALYTICS_BLOCKS_TABLE}
                        (trading_date, curve_name, data_format, row_count, payload, sha256)
                    VALUES
                        (:trading_date, :curve_name, :data_format, :row_count, :payload, :sha256)
                    ON CONFLICT (trading_date, curve_name) DO UPDATE SET
                        data_format = EXCLUDED.data_format,
                        row_count = EXCLUDED.row_count,
                        payload = EXCLUDED.payload,
                        sha256 = EXCLUDED.sha256,
                        created_at = NOW()
                """),
                {
                    "trading_date": trading_date,
                    "curve_name": curve_name,
                    "data_format": "parquet_zstd",
                    "row_count": row_count,
                    "payload": payload,
                    "sha256": sha,
                },
            )

        logger.info(
            "Pushed analytics %s/%s to Supabase (%d rows, %d bytes)",
            curve_name, trading_date, row_count, len(payload),
        )
        return True

    def _push_tagged_snapshots(self, conn, table, curve_name, trading_date, event_calendar):
        """Extract tagged snapshots from Arrow table and UPSERT into curve_snapshots."""
        from Caching.curve_tag_config import get_tags

        df = table.to_pandas()
        max_minute = df["session_minute"].max()

        for _, row in df.iterrows():
            is_last = row["session_minute"] == max_minute
            tags = get_tags(
                session_minute=int(row["session_minute"]),
                trading_date=trading_date,
                is_last_of_day=is_last,
                event_calendar=event_calendar,
            )
            if not tags:
                continue

            node_dates = [_to_python_date(d) for d in row["node_dates"]]
            discount_factors = [float(v) for v in row["discount_factors"]]
            conn.execute(
                text(f"""
                    INSERT INTO {CURVE_SNAPSHOTS_TABLE}
                        (curve_name, timestamp_utc, trading_date, session_minute,
                         tags, cfg_hash, reference_key, interpolation, source_variant,
                         node_dates, discount_factors)
                    VALUES
                        (:curve_name, :timestamp_utc, :trading_date, :session_minute,
                         :tags, :cfg_hash, :reference_key, :interpolation, :source_variant,
                         :node_dates, :discount_factors)
                    ON CONFLICT (curve_name, timestamp_utc) DO UPDATE SET
                        tags = EXCLUDED.tags,
                        node_dates = EXCLUDED.node_dates,
                        discount_factors = EXCLUDED.discount_factors
                """),
                {
                    "curve_name": curve_name,
                    "timestamp_utc": row["timestamp_utc"],
                    "trading_date": trading_date,
                    "session_minute": int(row["session_minute"]),
                    "tags": tags,
                    "cfg_hash": str(row.get("cfg_hash", "")),
                    "reference_key": str(row.get("reference_key", "")),
                    "interpolation": str(row.get("interpolation", "")),
                    "source_variant": str(row.get("source_variant", "")),
                    "node_dates": node_dates,
                    "discount_factors": discount_factors,
                },
            )

    def upsert_snapshot_row(self, snap, curve_name: str) -> bool:
        """UPSERT one untagged curve snapshot into arbs_curve_snapshots_v1.

        Unlike push_day (whole-day BYTEA blob), this writes a single indexed
        row keyed (curve_name, timestamp_utc). Idempotent. Returns False when
        no engine is configured.
        """
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False

        with self._engine.begin() as conn:
            conn.execute(
                text(f"""
                    INSERT INTO {CURVE_SNAPSHOTS_TABLE}
                        (curve_name, timestamp_utc, trading_date, session_minute,
                         tags, cfg_hash, reference_key, interpolation, source_variant,
                         node_dates, discount_factors)
                    VALUES
                        (:curve_name, :timestamp_utc, :trading_date, :session_minute,
                         :tags, :cfg_hash, :reference_key, :interpolation, :source_variant,
                         :node_dates, :discount_factors)
                    ON CONFLICT (curve_name, timestamp_utc) DO UPDATE SET
                        trading_date = EXCLUDED.trading_date,
                        session_minute = EXCLUDED.session_minute,
                        reference_key = EXCLUDED.reference_key,
                        interpolation = EXCLUDED.interpolation,
                        source_variant = EXCLUDED.source_variant,
                        node_dates = EXCLUDED.node_dates,
                        discount_factors = EXCLUDED.discount_factors
                """),
                _snapshot_insert_params(snap, curve_name),
            )
        return True

    _SNAPSHOT_COLS = (
        "curve_name, timestamp_utc, trading_date, session_minute, "
        "reference_key, interpolation, source_variant, node_dates, discount_factors"
    )

    def _snapshot_row_to_dict(self, row) -> dict:
        return {
            "curve_name": row.curve_name,
            "timestamp_utc": row.timestamp_utc,
            "trading_date": row.trading_date,
            "session_minute": row.session_minute,
            "reference_key": row.reference_key,
            "interpolation": row.interpolation,
            "source_variant": row.source_variant,
            "node_dates": list(row.node_dates),
            "discount_factors": [float(v) for v in row.discount_factors],
        }

    def pull_latest_snapshot(self, curve_name: str) -> Optional[dict]:
        """Most recent stored snapshot for curve_name (for timestamp='live')."""
        if self._engine is None:
            return None
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return None
        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"""
                    SELECT {self._SNAPSHOT_COLS} FROM {CURVE_SNAPSHOTS_TABLE}
                    WHERE curve_name = :cn
                    ORDER BY timestamp_utc DESC LIMIT 1
                """),
                {"cn": curve_name},
            ).fetchone()
        return self._snapshot_row_to_dict(row) if row is not None else None

    def pull_snapshot_asof(
        self, curve_name: str, ts_utc: datetime.datetime, method: str = "asof"
    ) -> Optional[dict]:
        """As-of / nearest / exact lookup keyed on (curve_name, timestamp_utc)."""
        if method not in ("asof", "nearest", "exact"):
            raise ValueError(f"unknown method {method!r}; expected asof|nearest|exact")
        if self._engine is None:
            return None
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return None
        with self._engine.begin() as conn:
            if method == "exact":
                row = conn.execute(
                    text(f"""
                        SELECT {self._SNAPSHOT_COLS} FROM {CURVE_SNAPSHOTS_TABLE}
                        WHERE curve_name = :cn AND timestamp_utc = :ts LIMIT 1
                    """),
                    {"cn": curve_name, "ts": ts_utc},
                ).fetchone()
                return self._snapshot_row_to_dict(row) if row is not None else None

            before = conn.execute(
                text(f"""
                    SELECT {self._SNAPSHOT_COLS} FROM {CURVE_SNAPSHOTS_TABLE}
                    WHERE curve_name = :cn AND timestamp_utc <= :ts
                    ORDER BY timestamp_utc DESC LIMIT 1
                """),
                {"cn": curve_name, "ts": ts_utc},
            ).fetchone()
            if method == "asof":
                return self._snapshot_row_to_dict(before) if before is not None else None

            # nearest: also consider the first row strictly after ts
            after = conn.execute(
                text(f"""
                    SELECT {self._SNAPSHOT_COLS} FROM {CURVE_SNAPSHOTS_TABLE}
                    WHERE curve_name = :cn AND timestamp_utc > :ts
                    ORDER BY timestamp_utc ASC LIMIT 1
                """),
                {"cn": curve_name, "ts": ts_utc},
            ).fetchone()

        candidates = [self._snapshot_row_to_dict(r) for r in (before, after) if r is not None]
        return _pick_nearest(ts_utc, candidates)

    def pull_snapshots_range(self, curve_name: str, start_utc, end_utc):
        """Batch read: every snapshot for curve_name with timestamp_utc in
        [start_utc, end_utc] (inclusive), ascending, as a pandas DataFrame.

        One PK-index range scan (PRIMARY KEY (curve_name, timestamp_utc)). The
        returned columns are exactly what CurveStore.reconstruct_curves_batch
        consumes (node_dates, discount_factors, reference_key, interpolation,
        timestamp_utc, curve_name). Empty DataFrame when no engine / no schema /
        no rows. start_utc/end_utc must be tz-aware UTC datetimes.
        """
        import pandas as pd

        if self._engine is None:
            return pd.DataFrame()
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return pd.DataFrame()
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT {self._SNAPSHOT_COLS} FROM {CURVE_SNAPSHOTS_TABLE}
                    WHERE curve_name = :cn
                      AND timestamp_utc BETWEEN :lo AND :hi
                    ORDER BY timestamp_utc ASC
                """),
                {"cn": curve_name, "lo": start_utc, "hi": end_utc},
            ).fetchall()
        return pd.DataFrame([self._snapshot_row_to_dict(r) for r in rows])

    def latest_snapshot_ts(
        self, curve_name: str, trading_date: datetime.date
    ) -> Optional[datetime.datetime]:
        """High-water-mark timestamp_utc for (curve_name, trading_date); None if none."""
        if self._engine is None:
            return None
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return None
        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"""
                    SELECT max(timestamp_utc) AS ts FROM {CURVE_SNAPSHOTS_TABLE}
                    WHERE curve_name = :cn AND trading_date = :td
                """),
                {"cn": curve_name, "td": trading_date},
            ).fetchone()
        return row.ts if row is not None else None

    def pull_day(
        self, curve_name: str, trading_date: datetime.date
    ) -> bool:
        """Pull a day's Parquet blob from Supabase to local.

        Returns True if downloaded and written, False if not found or no engine.
        """
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False

        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"""
                    SELECT payload, sha256, data_format
                    FROM {CURVE_INTRADAY_BLOCKS_TABLE}
                    WHERE trading_date = :trading_date AND curve_name = :curve_name
                """),
                {"trading_date": trading_date, "curve_name": curve_name},
            ).fetchone()

        if row is None:
            return False

        part_dir = self._partition_dir(curve_name, trading_date, kind="raw")
        part_dir.mkdir(parents=True, exist_ok=True)
        dest = part_dir / f"{row.sha256}.parquet"
        dest.write_bytes(row.payload)
        for old_path in part_dir.glob("*.parquet"):
            if old_path == dest:
                continue
            try:
                old_path.unlink()
            except OSError:
                pass
        logger.info("Pulled %s/%s from Supabase -> %s", curve_name, trading_date, dest)
        return True

    def pull_analytics_day(
        self,
        curve_name: str,
        trading_date: datetime.date,
    ) -> bool:
        """Pull a day's analytics Parquet blob from Supabase to local storage."""
        if self._engine is None:
            return False
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return False

        with self._engine.begin() as conn:
            row = conn.execute(
                text(f"""
                    SELECT payload, sha256, data_format
                    FROM {CURVE_ANALYTICS_BLOCKS_TABLE}
                    WHERE trading_date = :trading_date AND curve_name = :curve_name
                """),
                {"trading_date": trading_date, "curve_name": curve_name},
            ).fetchone()

        if row is None:
            return False

        part_dir = self._partition_dir(curve_name, trading_date, kind="analytics")
        part_dir.mkdir(parents=True, exist_ok=True)
        dest = part_dir / f"{row.sha256}.parquet"
        dest.write_bytes(row.payload)
        for old_path in part_dir.glob("*.parquet"):
            if old_path == dest:
                continue
            try:
                old_path.unlink()
            except OSError:
                pass
        logger.info("Pulled analytics %s/%s from Supabase -> %s", curve_name, trading_date, dest)
        return True

    def prefetch_range(
        self,
        curve_name: str,
        start: datetime.date,
        end: datetime.date,
    ) -> list[datetime.date]:
        """Download all missing days from Supabase to local.

        Returns list of dates that were fetched (excludes already-cached days).
        """
        if self._engine is None:
            return []
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return []

        # Find locally available dates
        local_dates = set()
        asset_dir = self._base_dir / "raw" / f"asset={_sanitize(curve_name)}"
        if asset_dir.exists():
            for d in asset_dir.iterdir():
                if d.name.startswith("date=") and any(d.glob("*.parquet")):
                    try:
                        dt = datetime.date.fromisoformat(d.name[5:])
                        if start <= dt <= end:
                            local_dates.add(dt)
                    except ValueError:
                        pass

        # Fetch missing days from Supabase
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT trading_date, payload, sha256
                    FROM {CURVE_INTRADAY_BLOCKS_TABLE}
                    WHERE curve_name = :curve_name
                      AND trading_date BETWEEN :start AND :end
                    ORDER BY trading_date
                """),
                {"curve_name": curve_name, "start": start, "end": end},
            ).fetchall()

        fetched = []
        for row in rows:
            if row.trading_date in local_dates:
                continue
            part_dir = self._partition_dir(curve_name, row.trading_date, kind="raw")
            part_dir.mkdir(parents=True, exist_ok=True)
            dest = part_dir / f"{row.sha256}.parquet"
            dest.write_bytes(row.payload)
            for old_path in part_dir.glob("*.parquet"):
                if old_path == dest:
                    continue
                try:
                    old_path.unlink()
                except OSError:
                    pass
            fetched.append(row.trading_date)

        logger.info(
            "Prefetched %s: %d/%d days downloaded (%d already local)",
            curve_name, len(fetched), len(rows), len(local_dates),
        )
        return fetched

    def prefetch_analytics_range(
        self,
        curve_name: str,
        start: datetime.date,
        end: datetime.date,
    ) -> list[datetime.date]:
        """Download all missing analytics days from Supabase to local storage."""
        if self._engine is None:
            return []
        from Caching.supabase_schema import ensure_schema

        if not ensure_schema(self._engine):
            return []

        local_dates = set()
        asset_dir = self._base_dir / "analytics" / f"asset={_sanitize(curve_name)}"
        if asset_dir.exists():
            for d in asset_dir.iterdir():
                if d.name.startswith("date=") and any(d.glob("*.parquet")):
                    try:
                        dt = datetime.date.fromisoformat(d.name[5:])
                        if start <= dt <= end:
                            local_dates.add(dt)
                    except ValueError:
                        pass

        with self._engine.begin() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT trading_date, payload, sha256
                    FROM {CURVE_ANALYTICS_BLOCKS_TABLE}
                    WHERE curve_name = :curve_name
                      AND trading_date BETWEEN :start AND :end
                    ORDER BY trading_date
                """),
                {"curve_name": curve_name, "start": start, "end": end},
            ).fetchall()

        fetched = []
        for row in rows:
            if row.trading_date in local_dates:
                continue
            part_dir = self._partition_dir(curve_name, row.trading_date, kind="analytics")
            part_dir.mkdir(parents=True, exist_ok=True)
            dest = part_dir / f"{row.sha256}.parquet"
            dest.write_bytes(row.payload)
            for old_path in part_dir.glob("*.parquet"):
                if old_path == dest:
                    continue
                try:
                    old_path.unlink()
                except OSError:
                    pass
            fetched.append(row.trading_date)

        logger.info(
            "Prefetched analytics %s: %d/%d days downloaded (%d already local)",
            curve_name, len(fetched), len(rows), len(local_dates),
        )
        return fetched

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


def _sanitize(name: str) -> str:
    return _SLUG_RX.sub("_", name)


def _to_python_date(value: object) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value))


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

    def _partition_dir(self, curve_name: str, trading_date: datetime.date) -> Path:
        return (
            self._base_dir
            / "raw"
            / f"asset={_sanitize(curve_name)}"
            / f"date={trading_date.isoformat()}"
        )

    def _local_parquet_bytes(
        self, curve_name: str, trading_date: datetime.date
    ) -> Optional[bytes]:
        part_dir = self._partition_dir(curve_name, trading_date)
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
        payload = self._local_parquet_bytes(curve_name, trading_date)
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

        part_dir = self._partition_dir(curve_name, trading_date)
        part_dir.mkdir(parents=True, exist_ok=True)
        dest = part_dir / f"{row.sha256}.parquet"
        dest.write_bytes(row.payload)
        logger.info("Pulled %s/%s from Supabase -> %s", curve_name, trading_date, dest)
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
            part_dir = self._partition_dir(curve_name, row.trading_date)
            part_dir.mkdir(parents=True, exist_ok=True)
            dest = part_dir / f"{row.sha256}.parquet"
            dest.write_bytes(row.payload)
            fetched.append(row.trading_date)

        logger.info(
            "Prefetched %s: %d/%d days downloaded (%d already local)",
            curve_name, len(fetched), len(rows), len(local_dates),
        )
        return fetched

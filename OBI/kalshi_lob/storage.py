"""
Date-partitioned Parquet storage for Kalshi LOB data.

Stores three raw stream types (deltas, snapshots, trades) and the
reconstructed LOB output, all Hive-partitioned by date.

Output schema (matches paper Section 5.3):
    lob:    market_ticker, ts, side, price, qty
    trades: market_ticker, ts, yes_price, no_price, count, taker_side
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

DEFAULT_LOB_DIR = Path.home() / ".cache" / "arbs" / "kalshi_lob"

DELTA_SCHEMA = pa.schema([
    ("market_ticker", pa.string()),
    ("ts", pa.timestamp("us", tz="UTC")),
    ("side", pa.string()),
    ("price", pa.float64()),
    ("delta", pa.float64()),
    ("seq", pa.int64()),
])

SNAPSHOT_SCHEMA = pa.schema([
    ("market_ticker", pa.string()),
    ("ts", pa.timestamp("us", tz="UTC")),
    ("side", pa.string()),
    ("price", pa.float64()),
    ("qty", pa.float64()),
])

TRADE_SCHEMA = pa.schema([
    ("market_ticker", pa.string()),
    ("ts", pa.timestamp("us", tz="UTC")),
    ("yes_price", pa.float64()),
    ("no_price", pa.float64()),
    ("count", pa.int64()),
    ("taker_side", pa.string()),
    ("trade_id", pa.string()),
])

LOB_SCHEMA = pa.schema([
    ("market_ticker", pa.string()),
    ("ts", pa.timestamp("us", tz="UTC")),
    ("side", pa.string()),
    ("price", pa.float64()),
    ("qty", pa.float64()),
])


class LOBStorage:
    """Manages date-partitioned Parquet files for LOB data."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or DEFAULT_LOB_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._buffers: Dict[str, List[dict]] = {
            "deltas": [],
            "snapshots": [],
            "trades": [],
        }

    def _date_dir(self, stream: str, date: datetime.date) -> Path:
        d = self.base_dir / stream / f"date={date.isoformat()}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --- buffer + flush for raw streams ---

    def buffer_delta(self, record: dict):
        self._buffers["deltas"].append(record)

    def buffer_snapshot(self, records: List[dict]):
        self._buffers["snapshots"].extend(records)

    def buffer_trade(self, record: dict):
        self._buffers["trades"].append(record)

    def flush(self, date: Optional[datetime.date] = None):
        """Write all buffered data to Parquet and clear buffers."""
        date = date or datetime.datetime.now(datetime.timezone.utc).date()
        for stream, schema in [
            ("deltas", DELTA_SCHEMA),
            ("snapshots", SNAPSHOT_SCHEMA),
            ("trades", TRADE_SCHEMA),
        ]:
            rows = self._buffers[stream]
            if not rows:
                continue
            self._write_parquet(stream, date, rows, schema)
            logger.info(f"Flushed {len(rows)} {stream} rows for {date}")
            self._buffers[stream] = []

    def flush_lob(self, rows: List[dict], date: datetime.date):
        """Write reconstructed LOB rows to Parquet."""
        if not rows:
            return
        self._write_parquet("lob", date, rows, LOB_SCHEMA)
        logger.info(f"Flushed {len(rows)} LOB rows for {date}")

    def _write_parquet(
        self,
        stream: str,
        date: datetime.date,
        rows: List[dict],
        schema: pa.Schema,
    ):
        out_dir = self._date_dir(stream, date)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%H%M%S")
        path = out_dir / f"{stream}_{ts}.parquet"

        df = pd.DataFrame(rows)
        for field in schema:
            col = field.name
            if col not in df.columns:
                if pa.types.is_string(field.type):
                    df[col] = ""
                elif pa.types.is_int64(field.type):
                    df[col] = 0
                else:
                    df[col] = 0.0

        table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
        pq.write_table(table, path, compression="zstd")

    # --- reading ---

    def read_deltas(self, date: datetime.date) -> pd.DataFrame:
        return self._read_stream("deltas", date)

    def read_snapshots(self, date: datetime.date) -> pd.DataFrame:
        return self._read_stream("snapshots", date)

    def read_trades(self, date: datetime.date) -> pd.DataFrame:
        return self._read_stream("trades", date)

    def read_lob(
        self,
        date: datetime.date,
        market_ticker: Optional[str] = None,
    ) -> pd.DataFrame:
        df = self._read_stream("lob", date)
        if market_ticker and not df.empty:
            df = df[df["market_ticker"] == market_ticker]
        return df

    def _read_stream(self, stream: str, date: datetime.date) -> pd.DataFrame:
        d = self.base_dir / stream / f"date={date.isoformat()}"
        if not d.exists():
            return pd.DataFrame()
        frames = []
        for p in sorted(d.glob("*.parquet")):
            frames.append(pd.read_parquet(p))
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True).sort_values("ts").reset_index(drop=True)

    def list_dates(self, stream: str = "deltas") -> List[datetime.date]:
        d = self.base_dir / stream
        if not d.exists():
            return []
        dates = []
        for sub in sorted(d.iterdir()):
            if sub.name.startswith("date="):
                try:
                    dates.append(datetime.date.fromisoformat(sub.name[5:]))
                except ValueError:
                    pass
        return dates

    def buffer_counts(self) -> Dict[str, int]:
        return {k: len(v) for k, v in self._buffers.items()}

"""
Real-time order book snapshot collector.

Polls order book data from Polymarket/Kalshi at regular intervals
and stores snapshots to DuckDB/Parquet for future backtesting with
real (non-simulated) order book data.
"""
from __future__ import annotations

import datetime
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "arbs" / "obi_orderbook_snapshots"


class OrderBookCollector:
    """Collects and stores order book snapshots for backtesting."""

    def __init__(
        self,
        venue: str = "polymarket",
        cache_dir: Optional[Path] = None,
        poll_interval_seconds: float = 5.0,
    ):
        self.venue = venue
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.poll_interval = poll_interval_seconds
        self._snapshots: List[Dict[str, Any]] = []

    def collect_snapshot(self, contract_id: str) -> Optional[Dict[str, Any]]:
        """Fetch and store a single order book snapshot."""
        now = datetime.datetime.now(datetime.timezone.utc)

        try:
            if self.venue == "polymarket":
                from MDP.EventContracts.polymarket_orderbook import fetch_orderbook, fetch_midpoint
                book = fetch_orderbook(contract_id)
                mid = fetch_midpoint(contract_id)
            elif self.venue == "kalshi":
                from MDP.EventContracts.kalshi_fetcher import fetch_orderbook as k_fetch
                book = k_fetch(contract_id, depth=20)
                bids = book.get("yes", pd.DataFrame())
                asks = book.get("no", pd.DataFrame())
                book = {"bids": bids, "asks": asks}
                mid = (bids.iloc[0]["price"] + asks.iloc[0]["price"]) / 2 if not bids.empty and not asks.empty else 0.5
            else:
                return None
        except Exception as e:
            logger.warning(f"Snapshot fetch failed for {contract_id}: {e}")
            return None

        bids = book.get("bids", pd.DataFrame())
        asks = book.get("asks", pd.DataFrame())

        snapshot = {
            "timestamp": now.isoformat(),
            "venue": self.venue,
            "contract_id": contract_id,
            "mid_price": mid,
            "best_bid": bids.iloc[0]["price"] if not bids.empty else None,
            "best_ask": asks.iloc[0]["price"] if not asks.empty else None,
            "spread": (asks.iloc[0]["price"] - bids.iloc[0]["price"]) if not bids.empty and not asks.empty else None,
            "bid_depth_total": bids["quantity"].sum() if not bids.empty else 0,
            "ask_depth_total": asks["quantity"].sum() if not asks.empty else 0,
            "n_bid_levels": len(bids),
            "n_ask_levels": len(asks),
            "bids": bids.to_dict("records") if not bids.empty else [],
            "asks": asks.to_dict("records") if not asks.empty else [],
        }

        self._snapshots.append(snapshot)
        return snapshot

    def flush_to_parquet(self, contract_id: str = "unknown"):
        """Write buffered snapshots to Parquet file."""
        if not self._snapshots:
            return

        flat_rows = []
        for snap in self._snapshots:
            base = {k: v for k, v in snap.items() if k not in ("bids", "asks")}
            flat_rows.append(base)

        df = pd.DataFrame(flat_rows)
        date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        out_dir = self.cache_dir / self.venue / contract_id / date_str
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"snapshots_{date_str}.parquet"

        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df], ignore_index=True)

        df.to_parquet(path, index=False)
        n = len(self._snapshots)
        self._snapshots.clear()
        logger.info(f"Flushed {n} snapshots to {path}")

    def run_collection(
        self,
        contract_ids: List[str],
        duration_seconds: float = 300,
        flush_interval_seconds: float = 60,
    ):
        """Run continuous collection loop for a set of contracts."""
        start = time.time()
        last_flush = start
        logger.info(f"Starting collection for {len(contract_ids)} contracts, duration={duration_seconds}s")

        while time.time() - start < duration_seconds:
            for cid in contract_ids:
                self.collect_snapshot(cid)

            if time.time() - last_flush > flush_interval_seconds:
                for cid in contract_ids:
                    self.flush_to_parquet(cid)
                last_flush = time.time()

            time.sleep(self.poll_interval)

        for cid in contract_ids:
            self.flush_to_parquet(cid)
        logger.info("Collection complete")

    def load_snapshots(
        self,
        contract_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Load cached snapshots from Parquet files."""
        base = self.cache_dir / self.venue / contract_id
        if not base.exists():
            return pd.DataFrame()

        frames = []
        for parquet in sorted(base.rglob("*.parquet")):
            date_part = parquet.parent.name
            if start_date and date_part < start_date:
                continue
            if end_date and date_part > end_date:
                continue
            frames.append(pd.read_parquet(parquet))

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

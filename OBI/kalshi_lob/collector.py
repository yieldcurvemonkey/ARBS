"""
Kalshi LOB data collector.

Connects to Kalshi's WebSocket streaming API for real-time orderbook
deltas and trades, and periodically polls REST API for full book
snapshots.  Implements the collection system described in Section 3
of Marriott (2026).

Three streams captured:
    orderbook.delta  — net depth change at (market, side, price)
    orderbook.snapshot — full book via REST (configurable interval)
    trade            — executed trades

All data is buffered in memory and flushed to date-partitioned
Parquet via LOBStorage.
"""
from __future__ import annotations

import datetime
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd
import requests
import websockets
import asyncio

from MDP.EventContracts.kalshi_fetcher import build_kalshi_auth_headers
from OBI.kalshi_lob.storage import LOBStorage

logger = logging.getLogger(__name__)

KALSHI_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
KALSHI_REST_URL = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiLOBCollector:
    """Collects orderbook deltas, snapshots, and trades from Kalshi."""

    def __init__(
        self,
        api_key_id: str = "",
        private_key_pem: Optional[str] = None,
        storage: Optional[LOBStorage] = None,
        snapshot_interval_seconds: float = 900,  # 15 min per paper
        flush_interval_seconds: float = 60,
        market_tickers: Optional[List[str]] = None,
        auto_discover: bool = True,
        max_markets: int = 500,
    ):
        self.api_key_id = api_key_id
        self.private_key_pem = private_key_pem or self._load_default_key()
        self.storage = storage or LOBStorage()
        self.snapshot_interval = snapshot_interval_seconds
        self.flush_interval = flush_interval_seconds
        self.market_tickers: Set[str] = set(market_tickers or [])
        self.auto_discover = auto_discover
        self.max_markets = max_markets

        self._running = False
        self._seq_counter: Dict[str, int] = {}
        self._delta_count = 0
        self._trade_count = 0
        self._snapshot_count = 0

    def _load_default_key(self) -> Optional[str]:
        p = Path(__file__).resolve().parents[2] / "MDP" / "EventContracts" / "arbs_mdp.txt"
        if p.exists():
            return p.read_text()
        return None

    def _auth_headers(self, method: str, path: str) -> Dict[str, str]:
        return build_kalshi_auth_headers(method, path, self.api_key_id, self.private_key_pem)

    # -----------------------------------------------------------------
    # Market discovery
    # -----------------------------------------------------------------

    def discover_active_markets(self) -> List[str]:
        """Fetch all active (open) market tickers from Kalshi REST API."""
        tickers = []
        cursor = None
        path = "/trade-api/v2/markets"

        while len(tickers) < self.max_markets:
            params: Dict[str, Any] = {"limit": 200, "status": "open"}
            if cursor:
                params["cursor"] = cursor

            try:
                headers = self._auth_headers("GET", path)
                resp = requests.get(
                    f"{KALSHI_REST_URL}/markets",
                    params=params,
                    headers=headers,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"Market discovery failed: {e}")
                break

            markets = data.get("markets", [])
            if not markets:
                break

            for m in markets:
                ticker = m.get("ticker", "")
                if ticker:
                    tickers.append(ticker)

            cursor = data.get("cursor")
            if not cursor:
                break

        logger.info(f"Discovered {len(tickers)} active markets")
        return tickers

    # -----------------------------------------------------------------
    # REST snapshot polling
    # -----------------------------------------------------------------

    def fetch_snapshot(self, ticker: str) -> List[dict]:
        """Fetch full orderbook snapshot for one market via REST."""
        path = f"/trade-api/v2/markets/{ticker}/orderbook"
        try:
            headers = self._auth_headers("GET", path)
            resp = requests.get(
                f"{KALSHI_REST_URL}/markets/{ticker}/orderbook",
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.debug(f"Snapshot failed for {ticker}: {e}")
            return []

        now = datetime.datetime.now(datetime.timezone.utc)
        raw = resp.json()
        book = raw.get("orderbook_fp") or raw.get("orderbook", {})
        rows = []

        for side_key, side_label in [
            ("yes_dollars", "yes"), ("no_dollars", "no"),
            ("yes", "yes"), ("no", "no"),
        ]:
            levels = book.get(side_key, [])
            for lvl in levels:
                price = lvl[0] if isinstance(lvl, list) else lvl.get("price", 0)
                qty = lvl[1] if isinstance(lvl, list) else lvl.get("quantity", 0)
                rows.append({
                    "market_ticker": ticker,
                    "ts": now,
                    "side": side_label,
                    "price": float(price),
                    "qty": float(qty),
                })

        return rows

    def poll_snapshots(self):
        """Poll snapshots for all tracked markets."""
        tickers = list(self.market_tickers)
        total = 0
        for ticker in tickers:
            rows = self.fetch_snapshot(ticker)
            if rows:
                self.storage.buffer_snapshot(rows)
                total += len(rows)
        self._snapshot_count += total
        logger.info(f"Polled {total} snapshot levels across {len(tickers)} markets")

    # -----------------------------------------------------------------
    # WebSocket delta + trade collection
    # -----------------------------------------------------------------

    async def _ws_connect(self):
        """Connect to Kalshi WebSocket and stream deltas + trades."""
        path = "/trade-api/ws/v2"
        headers = self._auth_headers("GET", path)
        ws_headers = {
            "KALSHI-ACCESS-KEY": headers["KALSHI-ACCESS-KEY"],
            "KALSHI-ACCESS-TIMESTAMP": headers["KALSHI-ACCESS-TIMESTAMP"],
            "KALSHI-ACCESS-SIGNATURE": headers["KALSHI-ACCESS-SIGNATURE"],
        }

        logger.info(f"Connecting to Kalshi WebSocket...")

        async with websockets.connect(
            KALSHI_WS_URL,
            additional_headers=ws_headers,
            ping_interval=30,
            ping_timeout=10,
            max_size=10 * 1024 * 1024,
        ) as ws:
            logger.info("WebSocket connected")

            tickers = list(self.market_tickers)

            # orderbook_delta requires market_tickers; subscribe in batches
            batch_size = 20
            for i in range(0, len(tickers), batch_size):
                batch = tickers[i : i + batch_size]
                await ws.send(json.dumps({
                    "id": i // batch_size + 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_tickers": batch,
                    },
                }))

            # trade + ticker channels work globally (no market_tickers needed)
            await ws.send(json.dumps({
                "id": 9999,
                "cmd": "subscribe",
                "params": {"channels": ["trade", "ticker"]},
            }))

            logger.info(f"Subscribed: orderbook_delta for {len(tickers)} markets + global trade/ticker")

            async for raw_msg in ws:
                if not self._running:
                    break
                try:
                    msg = json.loads(raw_msg)
                    self._handle_ws_message(msg)
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.warning(f"WS message handling error: {e}")

    def _handle_ws_message(self, msg: dict):
        """Route incoming WebSocket message to appropriate handler."""
        msg_type = msg.get("type", "")
        data = msg.get("msg", {})

        if msg_type == "orderbook_delta":
            self._handle_delta(data)
        elif msg_type == "trade":
            self._handle_trade(data)
        elif msg_type == "ticker":
            self._handle_ticker(data)
        elif msg_type == "error":
            logger.warning(f"WS error: {data}")

    def _handle_delta(self, data: dict):
        """Process an orderbook delta message.

        Delta semantics (from paper Section 3):
        'add this signed quantity to the existing depth at this price level'
        Positive delta adds contracts; negative removes them.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        ticker = data.get("market_ticker", "")
        if not ticker:
            return

        price = data.get("price", data.get("price_dollars", 0))
        delta_val = data.get("delta", data.get("delta_fp", 0))
        side = data.get("side", "").lower()
        seq = data.get("seq", 0)

        if not side:
            return

        self.storage.buffer_delta({
            "market_ticker": ticker,
            "ts": now,
            "side": side,
            "price": float(price),
            "delta": float(delta_val),
            "seq": seq,
        })
        self._delta_count += 1

    def _handle_trade(self, data: dict):
        """Process a trade message.  Kalshi WS uses *_dollars / *_fp suffixed fields."""
        ticker = data.get("market_ticker", "")
        if not ticker:
            return

        ts_ms = data.get("ts_ms", 0)
        if ts_ms:
            ts = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=datetime.timezone.utc)
        else:
            ts_s = data.get("ts", 0)
            ts = datetime.datetime.fromtimestamp(ts_s, tz=datetime.timezone.utc) if ts_s else datetime.datetime.now(datetime.timezone.utc)

        yes_price = data.get("yes_price_dollars", data.get("yes_price", "0"))
        no_price = data.get("no_price_dollars", data.get("no_price", "0"))
        count = data.get("count_fp", data.get("count", "0"))

        self.storage.buffer_trade({
            "market_ticker": ticker,
            "ts": ts,
            "yes_price": float(yes_price),
            "no_price": float(no_price),
            "count": int(float(count)),
            "taker_side": data.get("taker_side", ""),
            "trade_id": str(data.get("trade_id", "")),
        })
        self._trade_count += 1

    def _handle_ticker(self, data: dict):
        """Process a ticker message — use as a lightweight snapshot of BBO."""
        pass  # ticker data is useful for monitoring but not stored as LOB

    # -----------------------------------------------------------------
    # Main run loop
    # -----------------------------------------------------------------

    def run(self, duration_seconds: Optional[float] = None):
        """Start collection.  Blocks until duration expires or stop() called."""
        self._running = True

        if self.auto_discover and not self.market_tickers:
            discovered = self.discover_active_markets()
            self.market_tickers.update(discovered)

        if not self.market_tickers:
            logger.error("No markets to collect.  Pass market_tickers or enable auto_discover.")
            return

        logger.info(
            f"Starting LOB collection | {len(self.market_tickers)} markets | "
            f"snapshot_interval={self.snapshot_interval}s"
        )

        snapshot_thread = threading.Thread(target=self._snapshot_loop, daemon=True)
        flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        snapshot_thread.start()
        flush_thread.start()

        start = time.time()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            while self._running:
                elapsed = time.time() - start
                if duration_seconds and elapsed >= duration_seconds:
                    logger.info("Collection duration reached")
                    break

                remaining = (duration_seconds - elapsed) if duration_seconds else None
                try:
                    if remaining:
                        loop.run_until_complete(
                            asyncio.wait_for(self._ws_connect(), timeout=remaining)
                        )
                    else:
                        loop.run_until_complete(self._ws_connect())
                    break
                except asyncio.TimeoutError:
                    logger.info("Collection duration reached")
                    break
                except KeyboardInterrupt:
                    logger.info("Collection interrupted")
                    break
                except Exception as e:
                    logger.error(f"WebSocket error: {e}")
                    logger.info("Reconnecting in 5s...")
                    time.sleep(5)
        finally:
            self._running = False
            self.storage.flush()
            elapsed = time.time() - start
            logger.info(
                f"Collection stopped | {elapsed:.0f}s | "
                f"deltas={self._delta_count} trades={self._trade_count} "
                f"snapshots={self._snapshot_count}"
            )

    def run_rest_only(self, duration_seconds: float = 300, poll_interval: float = 5):
        """REST-only collection mode (no WebSocket).

        Polls orderbook snapshots and trades at regular intervals.
        Useful when WebSocket connection is not available.
        """
        self._running = True

        if self.auto_discover and not self.market_tickers:
            discovered = self.discover_active_markets()
            self.market_tickers.update(discovered)

        if not self.market_tickers:
            logger.error("No markets to collect.")
            return

        logger.info(f"Starting REST-only collection | {len(self.market_tickers)} markets")
        start = time.time()
        last_flush = start

        try:
            while self._running and (time.time() - start) < duration_seconds:
                self.poll_snapshots()
                self._poll_trades()

                if time.time() - last_flush > self.flush_interval:
                    self.storage.flush()
                    last_flush = time.time()

                time.sleep(poll_interval)
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            self.storage.flush()
            logger.info(
                f"REST collection done | {time.time()-start:.0f}s | "
                f"snapshots={self._snapshot_count} trades={self._trade_count}"
            )

    def _poll_trades(self):
        """Poll recent trades for tracked markets."""
        path = "/trade-api/v2/markets/trades"
        now = datetime.datetime.now(datetime.timezone.utc)
        since = now - datetime.timedelta(seconds=max(10, self.flush_interval))

        for ticker in list(self.market_tickers):
            try:
                headers = self._auth_headers("GET", path)
                resp = requests.get(
                    f"{KALSHI_REST_URL}/markets/trades",
                    params={"ticker": ticker, "limit": 50, "min_ts": int(since.timestamp())},
                    headers=headers,
                    timeout=10,
                )
                resp.raise_for_status()
                trades = resp.json().get("trades", [])
                for t in trades:
                    self.storage.buffer_trade({
                        "market_ticker": ticker,
                        "ts": pd.Timestamp(t.get("created_time", now.isoformat())).to_pydatetime(),
                        "yes_price": float(t.get("yes_price", 0)) / 100,
                        "no_price": float(t.get("no_price", 0)) / 100,
                        "count": int(t.get("count", 0)),
                        "taker_side": t.get("taker_side", ""),
                        "trade_id": t.get("trade_id", ""),
                    })
                    self._trade_count += 1
            except Exception:
                pass

    def _snapshot_loop(self):
        """Background thread: poll snapshots at configured interval."""
        while self._running:
            try:
                self.poll_snapshots()
            except Exception as e:
                logger.warning(f"Snapshot loop error: {e}")
            time.sleep(self.snapshot_interval)

    def _flush_loop(self):
        """Background thread: flush buffers to Parquet at configured interval."""
        while self._running:
            time.sleep(self.flush_interval)
            try:
                self.storage.flush()
                counts = self.storage.buffer_counts()
                logger.debug(f"Flush complete | buffers: {counts}")
            except Exception as e:
                logger.warning(f"Flush error: {e}")

    def stop(self):
        self._running = False

    def stats(self) -> Dict[str, Any]:
        return {
            "markets": len(self.market_tickers),
            "deltas": self._delta_count,
            "trades": self._trade_count,
            "snapshots": self._snapshot_count,
            "buffers": self.storage.buffer_counts(),
        }

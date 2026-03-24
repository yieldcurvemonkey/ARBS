from __future__ import annotations
import datetime
from typing import Any, Dict, Optional
import pandas as pd
from pathlib import Path

from MDP.MarketDataProvider import MarketDataProvider

_VALID_SOURCES = ("KALSHI", "POLYMARKET")


class EventContractPricer:
    def __init__(self, data: pd.DataFrame, meta_data: Dict[str, Any], auth: Optional[Dict[str, str]] = None):
        self._data = data
        self._meta_data = meta_data
        self._auth = auth or {}

    @property
    def data(self) -> pd.DataFrame:
        return self._data

    @property
    def meta_data(self) -> Dict[str, Any]:
        return self._meta_data

    def latest_price(self) -> Optional[float]:
        if self._data.empty:
            return None
        col = "close" if "close" in self._data.columns else "price"
        return float(self._data[col].iloc[-1])

    def latest_volume(self) -> Optional[float]:
        if self._data.empty or "volume" not in self._data.columns:
            return None
        return float(self._data["volume"].iloc[-1])

    def latest_open_interest(self) -> Optional[float]:
        if self._data.empty or "open_interest" not in self._data.columns:
            return None
        return float(self._data["open_interest"].iloc[-1])

    def get_orderbook(self, request: Optional[Dict[str, Any]] = None) -> Dict[str, pd.DataFrame]:
        if self._meta_data.get("source") != "KALSHI":
            raise NotImplementedError("Orderbook is only supported for KALSHI")
        from MDP.EventContracts.kalshi_fetcher import fetch_orderbook

        request = request or {}
        depth = request.get("depth", 0)
        return fetch_orderbook(
            ticker=self._meta_data["ticker"],
            depth=depth,
            api_key_id=self._auth.get("api_key_id", ""),
            private_key_pem=self._auth.get("private_key_pem", ""),
        )

    def market_impact(self, quantity: int, side: str = "yes") -> Dict[str, Any]:
        """Walk the orderbook to estimate execution cost for *buying* contracts.

        In Kalshi's orderbook, ``yes`` and ``no`` contain resting **bids** for
        each side.  To **buy YES** you must match against **NO bids** (a NO bid
        at price P is equivalent to a YES offer at 1 − P), and vice-versa.

        Returns a dict with:
            avg_price       – volume-weighted average execution price
            best_price      – top-of-book (best available) price
            slippage        – avg_price − best_price (positive = worse)
            total_cost      – avg_price × filled_quantity
            filled_quantity – contracts actually filled (<= quantity)
        """
        book = self.get_orderbook()

        # To buy YES we lift NO bids (and flip prices); to buy NO we lift YES bids.
        opposite = "no" if side == "yes" else "yes"
        contra = book.get(opposite, pd.DataFrame())
        if contra.empty:
            return {"avg_price": None, "best_price": None, "slippage": None, "total_cost": None, "filled_quantity": 0}

        # Convert contra-side bids into offers on *side*: price → (1 − price).
        # Sort ascending so cheapest offer is first.
        levels = contra.copy()
        levels["price"] = 1.0 - levels["price"]
        levels = levels.sort_values("price", ascending=True).reset_index(drop=True)

        best_price = float(levels["price"].iloc[0])
        remaining = quantity
        total_cost = 0.0
        filled = 0

        for _, row in levels.iterrows():
            px = float(row["price"])
            qty_available = int(row["quantity"])
            fill = min(remaining, qty_available)
            total_cost += px * fill
            filled += fill
            remaining -= fill
            if remaining <= 0:
                break

        avg_price = total_cost / filled if filled > 0 else None
        slippage = (avg_price - best_price) if avg_price is not None else None

        return {
            "avg_price": avg_price,
            "best_price": best_price,
            "slippage": slippage,
            "total_cost": total_cost,
            "filled_quantity": filled,
        }


class EventContractsMDP(MarketDataProvider):
    """
    Event contracts MDP for Kalshi and Polymarket.
    Source: "KALSHI" or "POLYMARKET"
    """

    def __init__(self, source: str, **kwargs: Any):
        if source not in _VALID_SOURCES:
            raise ValueError(f"source must be one of {_VALID_SOURCES}, got '{source}'")
        super().__init__(source=source, **kwargs)

    def get_pricer(self, request: Any) -> EventContractPricer:
        if self.source == "KALSHI":
            return self._fetch_kalshi(request)
        else:
            return self._fetch_polymarket(request)

    @staticmethod
    def _resolve_datetime(request: Dict[str, Any], key: str, ts_key: str) -> Optional[datetime.datetime]:
        """Resolve a datetime from either a datetime value or a unix timestamp."""
        val = request.get(key)
        if val is not None:
            return val
        ts = request.get(ts_key)
        if ts is not None:
            return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        return None

    @staticmethod
    def _kalshi_ticker_type(ticker: str) -> str:
        """Heuristic Kalshi ticker classification.

        This is only a fallback. Some live Kalshi market tickers have two
        segments (for example ``FEDHIKE-26DEC31``), so callers should prefer
        explicit metadata resolution when available.
        """
        parts = ticker.split("-")
        return "market" if len(parts) >= 3 else "event"

    def _resolve_kalshi_contract(self, request: Dict[str, Any], ticker: str) -> tuple[str, str]:
        from MDP.EventContracts.kalshi_fetcher import fetch_event_metadata, fetch_market_metadata

        explicit_type = request.get("ticker_type")
        explicit_series = request.get("series_ticker")
        if explicit_type in {"market", "event"} and explicit_series:
            return explicit_type, explicit_series

        # First try the public market metadata endpoint. Some Kalshi market
        # tickers have only two segments, so structural heuristics are not
        # reliable.
        if explicit_type != "event":
            market_meta = fetch_market_metadata(ticker)
            if market_meta is not None:
                series_ticker = explicit_series
                if not series_ticker:
                    event_ticker = market_meta.get("event_ticker")
                    event_meta = fetch_event_metadata(event_ticker) if event_ticker else None
                    series_ticker = (event_meta or {}).get("series_ticker")
                return "market", series_ticker or ticker.rsplit("-", 1)[0]

        if explicit_type != "market":
            event_meta = fetch_event_metadata(ticker)
            if event_meta is not None:
                return "event", explicit_series or event_meta["series_ticker"]

        return explicit_type or self._kalshi_ticker_type(ticker), explicit_series or ticker.rsplit("-", 1)[0]

    def _fetch_kalshi(self, request: Dict[str, Any]) -> EventContractPricer:
        from MDP.EventContracts.kalshi_fetcher import (
            fetch_event_candlesticks,
            fetch_historical_candlesticks,
            fetch_live_candlesticks,
        )

        ticker = request["ticker"]
        start = self._resolve_datetime(request, "start", "start_ts")
        end = self._resolve_datetime(request, "end", "end_ts")
        if end is None:
            end = datetime.datetime.now(datetime.timezone.utc)
        if start is None:
            start = end - datetime.timedelta(days=90)
        period = request.get("period_interval", 1440)
        api_key = request.get("api_key_id", "dcd3316c-192d-4d1e-9049-832d46fd9564")
        private_key = request.get("private_key_pem", Path(r"C:\Users\chris\clee\ARBS\MDP\EventContracts\arbs_mdp.txt").read_text(encoding="utf-8"))
        ticker_type, series_ticker = self._resolve_kalshi_contract(request, ticker)

        if ticker_type == "event":
            if not (api_key and private_key):
                raise ValueError(
                    f"Event ticker '{ticker}' requires authentication "
                    "(api_key_id + private_key_pem). Use a market ticker "
                    "for unauthenticated historical access."
                )
            data = fetch_event_candlesticks(
                series_ticker=series_ticker,
                event_ticker=ticker,
                start=start,
                end=end,
                period_interval=period,
                api_key_id=api_key,
                private_key_pem=private_key,
            )
        elif api_key and private_key:
            data = fetch_live_candlesticks(
                series_ticker=series_ticker,
                ticker=ticker,
                start=start,
                end=end,
                period_interval=period,
                api_key_id=api_key,
                private_key_pem=private_key,
            )
        else:
            data = fetch_historical_candlesticks(
                ticker=ticker,
                start=start,
                end=end,
                period_interval=period,
            )
        auth = {"api_key_id": api_key, "private_key_pem": private_key}
        return EventContractPricer(data=data, meta_data={"source": "KALSHI", "ticker": ticker}, auth=auth)

    def _fetch_polymarket(self, request: Dict[str, Any]) -> EventContractPricer:
        from MDP.EventContracts.polymarket_fetcher import fetch_price_history

        market_id = request.get("market_id") or request.get("token_id")
        if market_id is None:
            raise KeyError("Polymarket request must include 'market_id' or 'token_id'")
        start = self._resolve_datetime(request, "start", "start_ts")
        end = self._resolve_datetime(request, "end", "end_ts")
        interval = request.get("interval", "1d")
        fidelity = request.get("fidelity", 1)
        data = fetch_price_history(market_id=market_id, start=start, end=end, interval=interval, fidelity=fidelity)
        return EventContractPricer(data=data, meta_data={"source": "POLYMARKET", "market_id": market_id})

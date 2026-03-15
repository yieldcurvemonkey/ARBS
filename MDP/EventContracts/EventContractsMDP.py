from __future__ import annotations
import datetime
from typing import Any, Dict, Optional
import pandas as pd
from pathlib import Path

from MDP.MarketDataProvider import MarketDataProvider

_VALID_SOURCES = ("KALSHI", "POLYMARKET")


class EventContractPricer:
    def __init__(self, data: pd.DataFrame, meta_data: Dict[str, Any]):
        self._data = data
        self._meta_data = meta_data

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
        """Infer Kalshi ticker type from its structure.

        Market tickers have 3+ dash-separated segments (e.g. KXFEDDECISION-26MAR-T4.625).
        Event tickers have 2 segments (e.g. KXFEDDECISION-26MAR).
        """
        parts = ticker.split("-")
        return "market" if len(parts) >= 3 else "event"

    def _fetch_kalshi(self, request: Dict[str, Any]) -> EventContractPricer:
        from MDP.EventContracts.kalshi_fetcher import (
            fetch_event_candlesticks,
            fetch_historical_candlesticks,
            fetch_live_candlesticks,
        )

        ticker = request["ticker"]
        start = self._resolve_datetime(request, "start", "start_ts")
        end = self._resolve_datetime(request, "end", "end_ts")
        period = request.get("period_interval", 1440)
        api_key = request.get("api_key_id", "dcd3316c-192d-4d1e-9049-832d46fd9564")
        private_key = request.get("private_key_pem", Path(r"C:\Users\chris\clee\ARBS\MDP\EventContracts\arbs_mdp.txt").read_text(encoding="utf-8"))
        series_ticker = request.get("series_ticker", ticker.rsplit("-", 1)[0])
        ticker_type = request.get("ticker_type", self._kalshi_ticker_type(ticker))

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
        return EventContractPricer(data=data, meta_data={"source": "KALSHI", "ticker": ticker})

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

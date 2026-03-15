from __future__ import annotations
from typing import Any, Dict, Optional
import pandas as pd
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

    def _fetch_kalshi(self, request: Dict[str, Any]) -> EventContractPricer:
        from MDP.EventContracts.kalshi_fetcher import fetch_historical_candlesticks, fetch_live_candlesticks
        ticker = request["ticker"]
        start = request.get("start")
        end = request.get("end")
        period = request.get("period_interval", 1440)
        api_key = request.get("api_key_id")
        private_key = request.get("private_key_pem")
        if api_key and private_key:
            series_ticker = request.get("series_ticker", ticker.rsplit("-", 1)[0])
            data = fetch_live_candlesticks(series_ticker=series_ticker, ticker=ticker, start=start, end=end, period_interval=period, api_key_id=api_key, private_key_pem=private_key)
        else:
            data = fetch_historical_candlesticks(ticker=ticker, start=start, end=end, period_interval=period)
        return EventContractPricer(data=data, meta_data={"source": "KALSHI", "ticker": ticker})

    def _fetch_polymarket(self, request: Dict[str, Any]) -> EventContractPricer:
        from MDP.EventContracts.polymarket_fetcher import fetch_price_history
        market_id = request["market_id"]
        start = request.get("start")
        end = request.get("end")
        interval = request.get("interval", "1d")
        fidelity = request.get("fidelity", 1)
        data = fetch_price_history(market_id=market_id, start=start, end=end, interval=interval, fidelity=fidelity)
        return EventContractPricer(data=data, meta_data={"source": "POLYMARKET", "market_id": market_id})

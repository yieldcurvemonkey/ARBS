"""Kalshi REST API client for historical and live event contract data."""
from __future__ import annotations
import base64
import datetime
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode
import pandas as pd
import requests

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


def build_kalshi_auth_headers(method: str, path: str, api_key_id: str, private_key_pem: Optional[str]) -> Dict[str, str]:
    if private_key_pem is None:
        raise ValueError("Kalshi private key PEM is required for authenticated endpoints")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    timestamp_ms = str(int(time.time() * 1000))
    message = (timestamp_ms + method.upper() + path).encode("utf-8")
    private_key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    signature = private_key.sign(message, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
    return {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
    }


def build_historical_candlestick_url(ticker: str, start_ts: int, end_ts: int, period_interval: int = 1440) -> str:
    params = urlencode({"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_interval})
    return f"{KALSHI_BASE_URL}/historical/markets/{ticker}/candlesticks?{params}"


def parse_candlestick_response(raw: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for candle in raw.get("candlesticks", []):
        ts = candle.get("end_period_ts", 0)
        price = candle.get("price") or {}
        previous = _parse_fp(price.get("previous_dollars"))
        volume = _parse_fp(candle.get("volume_fp"))
        open_px = _parse_fp(price.get("open_dollars"))
        high_px = _parse_fp(price.get("high_dollars"))
        low_px = _parse_fp(price.get("low_dollars"))
        close_px = _parse_fp(price.get("close_dollars"))
        mean_px = _parse_fp(price.get("mean_dollars"))

        # Market candles often return only previous_dollars during no-trade
        # intervals. Expose a flat carry-forward price so the resulting
        # timeseries is usable without requiring downstream custom parsing.
        if previous is not None and close_px is None:
            close_px = previous
        if previous is not None and volume == 0:
            if open_px is None:
                open_px = previous
            if high_px is None:
                high_px = previous
            if low_px is None:
                low_px = previous
            if mean_px is None:
                mean_px = previous

        rows.append({
            "timestamp": datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc),
            "open": open_px,
            "high": high_px,
            "low": low_px,
            "close": close_px,
            "mean": mean_px,
            "previous": previous,
            "volume": volume,
            "open_interest": _parse_fp(candle.get("open_interest_fp")),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.set_index("timestamp")
    return df


def _parse_fp(val: Optional[str]) -> Optional[float]:
    if val is None:
        return None
    return float(val)


def fetch_historical_candlesticks(ticker: str, start: datetime.datetime, end: datetime.datetime, period_interval: int = 1440) -> pd.DataFrame:
    url = build_historical_candlestick_url(ticker=ticker, start_ts=int(start.timestamp()), end_ts=int(end.timestamp()), period_interval=period_interval)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return parse_candlestick_response(resp.json())


def fetch_live_candlesticks(series_ticker: str, ticker: str, start: datetime.datetime, end: datetime.datetime, period_interval: int = 1440, api_key_id: str = "", private_key_pem: str = "") -> pd.DataFrame:
    path = f"/trade-api/v2/series/{series_ticker}/markets/{ticker}/candlesticks"
    params = urlencode({"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()), "period_interval": period_interval})
    url = f"{KALSHI_BASE_URL}/series/{series_ticker}/markets/{ticker}/candlesticks?{params}"
    headers = build_kalshi_auth_headers("GET", path, api_key_id, private_key_pem)
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return parse_candlestick_response(resp.json())


def fetch_event_markets(event_ticker: str, **_: Any) -> list:
    url = f"{KALSHI_BASE_URL}/events/{event_ticker}?with_nested_markets=true"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json().get("markets", [])


def fetch_market_metadata(ticker: str) -> Optional[Dict[str, Any]]:
    url = f"{KALSHI_BASE_URL}/markets/{ticker}"
    resp = requests.get(url, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("market")


def fetch_event_metadata(event_ticker: str) -> Optional[Dict[str, Any]]:
    url = f"{KALSHI_BASE_URL}/events/{event_ticker}"
    resp = requests.get(url, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("event")


def fetch_orderbook(ticker: str, depth: int = 0, api_key_id: str = "", private_key_pem: str = "") -> Dict[str, pd.DataFrame]:
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    qs = f"?depth={depth}" if depth > 0 else ""
    url = f"{KALSHI_BASE_URL}/markets/{ticker}/orderbook{qs}"
    headers = build_kalshi_auth_headers("GET", path, api_key_id, private_key_pem)
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    book = resp.json().get("orderbook_fp", {})
    return {
        "yes": _parse_book_side(book.get("yes_dollars", [])),
        "no": _parse_book_side(book.get("no_dollars", [])),
    }


def _parse_book_side(levels: list) -> pd.DataFrame:
    rows = [{"price": float(lvl[0]), "quantity": float(lvl[1])} for lvl in levels]
    return pd.DataFrame(rows, columns=["price", "quantity"])


def fetch_event_candlesticks(series_ticker: str, event_ticker: str, start: datetime.datetime, end: datetime.datetime, period_interval: int = 1440, api_key_id: str = "", private_key_pem: str = "") -> pd.DataFrame:
    path = f"/trade-api/v2/series/{series_ticker}/events/{event_ticker}/candlesticks"
    params = urlencode({"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()), "period_interval": period_interval})
    url = f"{KALSHI_BASE_URL}/series/{series_ticker}/events/{event_ticker}/candlesticks?{params}"
    headers = build_kalshi_auth_headers("GET", path, api_key_id, private_key_pem)
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return parse_candlestick_response(resp.json())

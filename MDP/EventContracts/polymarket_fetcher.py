"""Polymarket CLOB API client for price history data."""
from __future__ import annotations
import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlencode
import pandas as pd
import requests

POLYMARKET_CLOB_URL = "https://clob.polymarket.com"


def build_price_history_url(market_id: str, start_ts: Optional[int] = None, end_ts: Optional[int] = None, interval: str = "1d", fidelity: int = 1) -> str:
    params: Dict[str, Any] = {"market": market_id}
    if start_ts is not None:
        params["startTs"] = start_ts
    if end_ts is not None:
        params["endTs"] = end_ts
    params["interval"] = interval
    params["fidelity"] = fidelity
    return f"{POLYMARKET_CLOB_URL}/prices-history?{urlencode(params)}"


def parse_price_history(raw: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for point in raw.get("history", []):
        rows.append({
            "timestamp": datetime.datetime.fromtimestamp(point["t"], tz=datetime.timezone.utc),
            "price": float(point["p"]),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.set_index("timestamp")
    return df


def fetch_price_history(market_id: str, start: Optional[datetime.datetime] = None, end: Optional[datetime.datetime] = None, interval: str = "1d", fidelity: int = 1) -> pd.DataFrame:
    url = build_price_history_url(market_id=market_id, start_ts=int(start.timestamp()) if start else None, end_ts=int(end.timestamp()) if end else None, interval=interval, fidelity=fidelity)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return parse_price_history(resp.json())

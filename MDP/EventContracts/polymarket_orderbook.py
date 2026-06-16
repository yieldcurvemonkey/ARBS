"""Polymarket CLOB order book fetcher.

Retrieves live order book depth from the Polymarket CLOB REST API.
Public endpoint — no authentication required.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import requests

POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"


def fetch_orderbook(
    token_id: str,
    timeout: int = 15,
) -> Dict[str, pd.DataFrame]:
    """Fetch order book for a Polymarket condition token.

    Returns dict with 'bids' and 'asks' DataFrames, each having
    columns ['price', 'quantity'] sorted best→worst.
    """
    url = f"{POLYMARKET_CLOB_URL}/book"
    params = {"token_id": token_id}
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return {
        "bids": _parse_book_side(data.get("bids", []), ascending=False),
        "asks": _parse_book_side(data.get("asks", []), ascending=True),
    }


def fetch_midpoint(token_id: str, timeout: int = 10) -> float:
    """Fetch current midpoint price for a token."""
    url = f"{POLYMARKET_CLOB_URL}/midpoint"
    params = {"token_id": token_id}
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return float(resp.json().get("mid", 0.5))


def fetch_spread(token_id: str, timeout: int = 10) -> Dict[str, float]:
    """Fetch current spread for a token."""
    url = f"{POLYMARKET_CLOB_URL}/spread"
    params = {"token_id": token_id}
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return {
        "spread": float(data.get("spread", 0)),
        "bid": float(data.get("bid", 0)),
        "ask": float(data.get("ask", 0)),
    }


def fetch_market_info(condition_id: str, timeout: int = 15) -> Dict[str, Any]:
    """Fetch market metadata from Gamma API.

    Returns market details including tokens, outcomes, volume, etc.
    """
    url = f"{GAMMA_API_URL}/markets/{condition_id}"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def search_markets(
    query: str = "btc",
    active: bool = True,
    limit: int = 20,
    timeout: int = 15,
) -> List[Dict[str, Any]]:
    """Search Polymarket markets via Gamma API."""
    url = f"{GAMMA_API_URL}/markets"
    params: Dict[str, Any] = {"limit": limit}
    if query:
        params["_q"] = query
    if active:
        params["active"] = "true"
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def compute_market_impact(
    book: Dict[str, pd.DataFrame],
    quantity: float,
    side: str = "buy_yes",
) -> Dict[str, float]:
    """Walk the order book to estimate execution cost.

    side: 'buy_yes' (lift asks), 'buy_no' (hit bids on yes = lift asks on no),
          'sell_yes' (hit bids), 'sell_no' (lift asks on no)
    """
    if side in ("buy_yes", "sell_no"):
        levels = book["asks"]
    else:
        levels = book["bids"]

    if levels.empty:
        return {
            "avg_price": 0.0,
            "best_price": 0.0,
            "worst_price": 0.0,
            "slippage": 0.0,
            "total_cost": 0.0,
            "filled_qty": 0.0,
        }

    remaining = quantity
    total_cost = 0.0
    best_price = levels.iloc[0]["price"]
    worst_price = best_price
    filled = 0.0

    for _, row in levels.iterrows():
        px, qty = row["price"], row["quantity"]
        fill = min(remaining, qty)
        total_cost += fill * px
        filled += fill
        worst_price = px
        remaining -= fill
        if remaining <= 0:
            break

    avg_price = total_cost / filled if filled > 0 else 0.0
    return {
        "avg_price": avg_price,
        "best_price": best_price,
        "worst_price": worst_price,
        "slippage": avg_price - best_price if filled > 0 else 0.0,
        "total_cost": total_cost,
        "filled_qty": filled,
    }


def _parse_book_side(levels: List[Dict], ascending: bool = True) -> pd.DataFrame:
    """Parse CLOB book levels into DataFrame."""
    rows = []
    for level in levels:
        rows.append({
            "price": float(level.get("price", 0)),
            "quantity": float(level.get("size", 0)),
        })
    df = pd.DataFrame(rows, columns=["price", "quantity"])
    if not df.empty:
        df = df.sort_values("price", ascending=ascending).reset_index(drop=True)
    return df

"""
Order Book Imbalance signal computation.

Computes OBI from order book snapshots (live or simulated) and produces
trading signals for binary event contracts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


def raw_obi(bid_qty: float, ask_qty: float) -> float:
    """Standard OBI: (bid - ask) / (bid + ask).  Returns 0 if both zero."""
    total = bid_qty + ask_qty
    if total == 0:
        return 0.0
    return (bid_qty - ask_qty) / total


def multi_level_obi(
    bids: pd.DataFrame,
    asks: pd.DataFrame,
    levels: int = 5,
) -> float:
    """OBI aggregated across top-N price levels.

    bids/asks: DataFrame with columns ['price', 'quantity'] sorted best→worst.
    """
    b = bids.head(levels)["quantity"].sum()
    a = asks.head(levels)["quantity"].sum()
    return raw_obi(b, a)


def weighted_obi(
    bids: pd.DataFrame,
    asks: pd.DataFrame,
    mid_price: float,
    depth_pct: float = 0.025,
) -> float:
    """Distance-weighted OBI: levels closer to mid contribute more."""
    if mid_price <= 0:
        return 0.0
    depth_range = mid_price * depth_pct

    def _weighted_sum(book: pd.DataFrame, is_bid: bool) -> float:
        total = 0.0
        for _, row in book.iterrows():
            dist = abs(row["price"] - mid_price)
            if dist > depth_range:
                continue
            weight = 1.0 - (dist / depth_range) if depth_range > 0 else 1.0
            total += row["quantity"] * weight
        return total

    wb = _weighted_sum(bids, True)
    wa = _weighted_sum(asks, False)
    return raw_obi(wb, wa)


def compute_obi(
    bids: pd.DataFrame,
    asks: pd.DataFrame,
    mid_price: float,
    variant: str = "normalized",
    depth_levels: int = 5,
    depth_pct: float = 0.025,
) -> float:
    """Dispatch to the requested OBI variant."""
    if variant == "raw":
        b = bids.iloc[0]["quantity"] if len(bids) > 0 else 0
        a = asks.iloc[0]["quantity"] if len(asks) > 0 else 0
        return raw_obi(b, a)
    elif variant == "normalized" or variant == "multi_level":
        return multi_level_obi(bids, asks, levels=depth_levels)
    elif variant == "weighted":
        return weighted_obi(bids, asks, mid_price, depth_pct)
    else:
        return multi_level_obi(bids, asks, levels=depth_levels)


# ---------------------------------------------------------------------------
# Vectorized signal generation for backtesting
# ---------------------------------------------------------------------------

def standardize_obi_series(
    obi_raw: pd.Series,
    lookback: int = 60,
    ema_span: int = 0,
) -> pd.Series:
    """Z-score standardize a raw OBI series with optional EMA smoothing."""
    if ema_span > 0:
        obi_raw = obi_raw.ewm(span=ema_span, min_periods=1).mean()

    roll_mean = obi_raw.rolling(lookback, min_periods=1).mean()
    roll_std = obi_raw.rolling(lookback, min_periods=1).std().clip(lower=1e-8)
    return (obi_raw - roll_mean) / roll_std


def generate_signals(
    obi_series: pd.Series,
    threshold: float = 0.15,
    mode: str = "follow",
) -> pd.Series:
    """Convert OBI values to trade signals: +1 (buy YES), -1 (buy NO), 0 (no trade).

    follow: positive OBI → buy YES (BTC up pressure → bet on up)
    fade:   positive OBI → buy NO  (contrarian)
    """
    sig = pd.Series(0, index=obi_series.index, dtype=np.int8)
    sig[obi_series > threshold] = 1
    sig[obi_series < -threshold] = -1
    if mode == "fade":
        sig = -sig
    return sig


# ---------------------------------------------------------------------------
# Simulated order book for backtesting
# ---------------------------------------------------------------------------

def simulate_contract_book(
    true_prob: float,
    depth_contracts: int = 500,
    spread: float = 0.03,
    noise: float = 0.3,
    predictive_power: float = 0.15,
    n_levels: int = 10,
    rng: Optional[np.random.Generator] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, float]:
    """Simulate an order book for a binary contract.

    true_prob: actual probability the YES outcome occurs (0-1)
    predictive_power: how much the order book 'leaks' the true outcome
    noise: randomness in the book

    Returns (bids_df, asks_df, mid_price)
    """
    if rng is None:
        rng = np.random.default_rng()

    mid = np.clip(true_prob + rng.normal(0, noise * 0.1), 0.05, 0.95)
    half_spread = spread / 2

    best_bid = mid - half_spread
    best_ask = mid + half_spread

    bid_skew = predictive_power * (true_prob - 0.5) * 2
    bid_base = depth_contracts * (0.5 + bid_skew + rng.normal(0, noise * 0.3))
    ask_base = depth_contracts * (0.5 - bid_skew + rng.normal(0, noise * 0.3))

    bid_prices = np.array([best_bid - i * 0.01 for i in range(n_levels)])
    ask_prices = np.array([best_ask + i * 0.01 for i in range(n_levels)])

    bid_qtys = np.maximum(
        1,
        bid_base * np.exp(-0.3 * np.arange(n_levels))
        + rng.normal(0, noise * depth_contracts * 0.1, n_levels),
    )
    ask_qtys = np.maximum(
        1,
        ask_base * np.exp(-0.3 * np.arange(n_levels))
        + rng.normal(0, noise * depth_contracts * 0.1, n_levels),
    )

    bids = pd.DataFrame({"price": bid_prices, "quantity": bid_qtys})
    asks = pd.DataFrame({"price": ask_prices, "quantity": ask_qtys})
    return bids, asks, mid


def simulate_obi_timeseries(
    n_contracts: int,
    true_probs: np.ndarray,
    outcomes: np.ndarray,
    snapshots_per_contract: int = 10,
    depth_contracts: int = 500,
    spread: float = 0.03,
    noise: float = 0.3,
    predictive_power: float = 0.15,
    obi_variant: str = "normalized",
    depth_levels: int = 5,
    depth_pct: float = 0.025,
    seed: int = 42,
) -> pd.DataFrame:
    """Simulate OBI readings across many contracts for backtesting.

    Returns DataFrame with columns:
        contract_idx, snapshot_idx, obi, mid_price, spread, true_prob, outcome
    """
    rng = np.random.default_rng(seed)
    rows = []

    for i in range(n_contracts):
        tp = true_probs[i]
        outcome = outcomes[i]

        for s in range(snapshots_per_contract):
            pct_elapsed = (s + 1) / snapshots_per_contract
            evolving_prob = tp + (outcome - tp) * pct_elapsed * 0.5

            bids, asks, mid = simulate_contract_book(
                true_prob=evolving_prob,
                depth_contracts=depth_contracts,
                spread=spread * (1 + rng.normal(0, 0.2)),
                noise=noise,
                predictive_power=predictive_power,
                rng=rng,
            )

            obi_val = compute_obi(
                bids, asks, mid,
                variant=obi_variant,
                depth_levels=depth_levels,
                depth_pct=depth_pct,
            )

            actual_spread = asks.iloc[0]["price"] - bids.iloc[0]["price"] if len(asks) > 0 and len(bids) > 0 else spread
            rows.append({
                "contract_idx": i,
                "snapshot_idx": s,
                "pct_elapsed": pct_elapsed,
                "obi": obi_val,
                "mid_price": mid,
                "spread": actual_spread,
                "true_prob": tp,
                "outcome": outcome,
            })

    return pd.DataFrame(rows)

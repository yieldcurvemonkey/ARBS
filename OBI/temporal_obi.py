"""
Temporal OBI & Market-Maker strategies using intra-contract tick dynamics.

Strategy 1 — OBI Velocity:
    Instead of cumulative OBI (already priced in), measure the RATE OF
    CHANGE of order flow in the first 30-60s of a contract.  Early flow
    acceleration may predict outcomes before the market fully reprices.

Strategy 2 — OBI Market-Making:
    Post resting limit orders on both sides.  Earn the spread when filled.
    Use OBI to skew inventory: shift quotes toward the informed side to
    reduce adverse selection.  P&L = spread earned - inventory losses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# =====================================================================
# Strategy 1: Temporal OBI — early velocity signal
# =====================================================================

@dataclass
class TemporalFeatures:
    token_id: str
    outcome: float
    n_ticks: int
    # early OBI (first N seconds)
    obi_10s: float = 0.0
    obi_30s: float = 0.0
    obi_60s: float = 0.0
    # OBI velocity (Δ OBI / Δ time)
    obi_vel_10_30: float = 0.0      # change from 10s to 30s
    obi_vel_30_60: float = 0.0      # change from 30s to 60s
    obi_accel: float = 0.0          # acceleration (vel change)
    # mid-price dynamics
    mid_10s: float = 0.5
    mid_30s: float = 0.5
    mid_60s: float = 0.5
    mid_drift: float = 0.0          # mid at 60s - mid at 10s
    # flow pressure
    buy_rate_0_30: float = 0.0      # buys per second in first 30s
    sell_rate_0_30: float = 0.0
    flow_accel: float = 0.0         # buy_rate change: 30-60s vs 0-30s
    # spread dynamics
    spread_10s: float = 0.0
    spread_30s: float = 0.0
    # market price at entry point
    best_bid_30s: float = 0.0
    best_ask_30s: float = 0.0


def extract_temporal_features(
    ticks: pd.DataFrame,
    token_id: str,
    outcome: float,
    period_open: pd.Timestamp,
) -> Optional[TemporalFeatures]:
    """Extract time-bucketed OBI features from a contract's tick stream."""
    if len(ticks) < 10:
        return None

    ticks = ticks.sort_values("timestamp").copy()
    ticks["elapsed_s"] = (ticks["timestamp"] - period_open).dt.total_seconds()
    ticks = ticks[ticks["elapsed_s"] >= 0]

    if ticks.empty:
        return None

    valid = ticks.dropna(subset=["best_bid", "best_ask"])
    valid = valid[(valid["best_bid"] > 0) & (valid["best_ask"] > 0)]

    def bucket_stats(df, t_start, t_end):
        b = df[(df["elapsed_s"] >= t_start) & (df["elapsed_s"] < t_end)]
        if b.empty:
            return None
        buys = b[b["side"] == "BUY"]["size"].sum() if "side" in b.columns else 0
        sells = b[b["side"] == "SELL"]["size"].sum() if "side" in b.columns else 0
        total = buys + sells
        obi = (buys - sells) / total if total > 0 else 0.0
        v = b.dropna(subset=["best_bid", "best_ask"])
        v = v[(v["best_bid"] > 0) & (v["best_ask"] > 0)]
        mid = ((v["best_bid"] + v["best_ask"]) / 2).iloc[-1] if not v.empty else 0.5
        spread = (v["best_ask"] - v["best_bid"]).median() if not v.empty else 0.0
        bb = v["best_bid"].iloc[-1] if not v.empty else 0.0
        ba = v["best_ask"].iloc[-1] if not v.empty else 1.0
        return {
            "obi": obi, "buys": buys, "sells": sells,
            "mid": mid, "spread": spread, "n": len(b),
            "best_bid": bb, "best_ask": ba,
            "duration": t_end - t_start,
        }

    s10 = bucket_stats(ticks, 0, 10)
    s30 = bucket_stats(ticks, 0, 30)
    s60 = bucket_stats(ticks, 0, 60)
    s30_60 = bucket_stats(ticks, 30, 60)

    if s30 is None:
        return None

    feat = TemporalFeatures(
        token_id=token_id,
        outcome=outcome,
        n_ticks=len(ticks),
    )

    if s10:
        feat.obi_10s = s10["obi"]
        feat.mid_10s = s10["mid"]
        feat.spread_10s = s10["spread"]

    feat.obi_30s = s30["obi"]
    feat.mid_30s = s30["mid"]
    feat.spread_30s = s30["spread"]
    feat.best_bid_30s = s30["best_bid"]
    feat.best_ask_30s = s30["best_ask"]
    feat.buy_rate_0_30 = s30["buys"] / 30.0
    feat.sell_rate_0_30 = s30["sells"] / 30.0

    if s60:
        feat.obi_60s = s60["obi"]
        feat.mid_60s = s60["mid"]
        feat.mid_drift = s60["mid"] - (s10["mid"] if s10 else 0.5)

    if s10:
        feat.obi_vel_10_30 = (s30["obi"] - s10["obi"]) / 20.0

    if s60 and s30:
        feat.obi_vel_30_60 = (s60["obi"] - s30["obi"]) / 30.0

    if s10 and s60:
        vel1 = feat.obi_vel_10_30
        vel2 = feat.obi_vel_30_60
        feat.obi_accel = vel2 - vel1

    if s30_60:
        buy_rate_30_60 = s30_60["buys"] / 30.0
        feat.flow_accel = buy_rate_30_60 - feat.buy_rate_0_30

    return feat


def backtest_temporal_obi(
    features: List[TemporalFeatures],
    signal_col: str = "obi_vel_10_30",
    threshold: float = 0.001,
    signal_mode: str = "follow",
    max_spread: float = 0.10,
    fixed_size: float = 10.0,
    entry_fee_pct: float = 0.02,
    capital: float = 10_000.0,
) -> Dict:
    """Backtest using temporal OBI signals."""
    current_capital = capital
    trades = []

    for f in features:
        sig = getattr(f, signal_col, 0.0)
        if f.spread_30s > max_spread:
            continue
        if abs(sig) < threshold:
            continue

        direction = 1 if sig > 0 else -1
        if signal_mode == "fade":
            direction = -direction

        side = "YES" if direction > 0 else "NO"
        entry_price = f.best_ask_30s if side == "YES" else (1 - f.best_bid_30s)
        entry_price = np.clip(entry_price, 0.01, 0.99)

        qty = min(fixed_size, current_capital * 0.95 / max(entry_price, 0.01))
        qty = max(1, int(qty))

        won = (side == "YES" and f.outcome == 1) or (side == "NO" and f.outcome == 0)
        pnl = qty * ((1.0 if won else 0.0) - entry_price)
        fee = qty * entry_price * entry_fee_pct
        net = pnl - fee
        current_capital += net

        trades.append({"net_pnl": net, "won": won, "side": side,
                        "spread": f.spread_30s, "signal": sig, "entry": entry_price})

    return _compute_metrics(trades, capital)


# =====================================================================
# Strategy 2: OBI Market-Making
# =====================================================================

@dataclass
class MMState:
    inventory: float = 0.0
    cash: float = 0.0
    n_fills_bid: int = 0
    n_fills_ask: int = 0
    total_spread_earned: float = 0.0


def backtest_market_maker(
    features: List[TemporalFeatures],
    half_spread: float = 0.01,
    obi_skew_factor: float = 0.5,
    max_inventory: float = 50.0,
    inventory_decay: float = 0.1,
    entry_fee_pct: float = 0.02,
    capital: float = 10_000.0,
    contracts_per_quote: float = 5.0,
) -> Dict:
    """Market-making backtest with OBI inventory management.

    For each contract:
    1. Post bid at mid - half_spread, ask at mid + half_spread
    2. Skew quotes using OBI: if OBI > 0 (buying pressure), shift up
       to reduce long exposure
    3. Simulate fills: if market trades through our level, we get filled
    4. Mark inventory to resolution price (1 or 0)

    The OBI skew helps avoid adverse selection: when informed flow
    is buying YES, we raise our ask (harder to buy from us) and
    lower our bid (easier to sell to us), reducing net long exposure.
    """
    current_capital = capital
    trades = []

    for f in features:
        mid = f.mid_30s
        spread = f.spread_30s
        obi = f.obi_30s

        if mid <= 0.02 or mid >= 0.98:
            continue
        if spread <= 0:
            continue

        # Skew based on OBI: positive OBI = buying pressure = shift up
        skew = obi * obi_skew_factor * half_spread
        our_bid = mid - half_spread + skew
        our_ask = mid + half_spread + skew

        our_bid = np.clip(our_bid, 0.01, 0.98)
        our_ask = np.clip(our_ask, 0.02, 0.99)
        if our_ask <= our_bid:
            continue

        actual_spread = our_ask - our_bid

        # Fill simulation: we get filled on BOTH sides if market is active
        # In reality, one side gets filled more. Use OBI to estimate:
        # - High OBI (buying) → our ask gets lifted more (we sell YES)
        # - Low OBI (selling) → our bid gets hit more (we buy YES)
        bid_fill_prob = 0.5 + 0.3 * (-obi)  # more fills when selling pressure
        ask_fill_prob = 0.5 + 0.3 * obi      # more fills when buying pressure
        bid_fill_prob = np.clip(bid_fill_prob, 0.1, 0.9)
        ask_fill_prob = np.clip(ask_fill_prob, 0.1, 0.9)

        rng = np.random.default_rng(hash(f.token_id) % 2**32)
        bid_filled = rng.random() < bid_fill_prob
        ask_filled = rng.random() < ask_fill_prob

        inventory = 0.0
        cash = 0.0
        spread_earned = 0.0

        qty = contracts_per_quote

        if bid_filled:
            inventory += qty
            cash -= qty * our_bid
            fee = qty * our_bid * entry_fee_pct
            cash -= fee

        if ask_filled:
            inventory -= qty
            cash += qty * our_ask
            fee = qty * our_ask * entry_fee_pct
            cash -= fee

        if bid_filled and ask_filled:
            spread_earned = qty * actual_spread

        # Mark inventory to resolution
        resolution_price = 1.0 if f.outcome == 1 else 0.0
        mtm = inventory * resolution_price
        net_pnl = cash + mtm

        if bid_filled or ask_filled:
            trades.append({
                "net_pnl": net_pnl,
                "spread_earned": spread_earned,
                "inventory": inventory,
                "won": net_pnl > 0,
                "bid_filled": bid_filled,
                "ask_filled": ask_filled,
                "both_filled": bid_filled and ask_filled,
                "obi": obi,
                "our_bid": our_bid,
                "our_ask": our_ask,
                "side": "FLAT" if inventory == 0 else ("LONG" if inventory > 0 else "SHORT"),
                "spread": actual_spread,
                "entry": our_bid if inventory > 0 else our_ask,
            })
            current_capital += net_pnl

    return _compute_mm_metrics(trades, capital)


def _compute_metrics(trades, capital):
    if not trades:
        return {"n_trades": 0, "win_rate": 0, "total_pnl": 0, "sharpe": 0,
                "max_drawdown_pct": 0, "profit_factor": 0}

    tdf = pd.DataFrame(trades)
    pnls = tdf["net_pnl"].values
    n = len(pnls)
    wins = int(tdf["won"].sum())

    eq = capital + np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / np.clip(peak, 1, None)

    mu = pnls.mean()
    sigma = pnls.std() if n > 1 else 1e-8
    sharpe = mu / max(sigma, 1e-8) * np.sqrt(252 * 288)

    w_pnl = pnls[pnls > 0].sum()
    l_pnl = abs(pnls[pnls <= 0].sum())

    return {
        "n_trades": n,
        "n_wins": wins,
        "win_rate": round(wins / n, 4),
        "total_pnl": round(pnls.sum(), 2),
        "roi_pct": round(pnls.sum() / capital * 100, 2),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(abs(dd.min()) * 100, 2),
        "profit_factor": round(w_pnl / max(l_pnl, 1e-8), 4),
        "avg_pnl": round(mu, 4),
        "avg_spread": round(tdf["spread"].mean(), 4),
        "pct_yes": round((tdf["side"] == "YES").mean(), 4) if "YES" in tdf["side"].values else 0,
        "final_capital": round(capital + pnls.sum(), 2),
    }


def _compute_mm_metrics(trades, capital):
    if not trades:
        return {"n_trades": 0, "win_rate": 0, "total_pnl": 0, "sharpe": 0,
                "max_drawdown_pct": 0, "spread_pnl": 0, "inventory_pnl": 0}

    tdf = pd.DataFrame(trades)
    pnls = tdf["net_pnl"].values
    n = len(pnls)
    wins = int(tdf["won"].sum())

    eq = capital + np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / np.clip(peak, 1, None)

    mu = pnls.mean()
    sigma = pnls.std() if n > 1 else 1e-8
    sharpe = mu / max(sigma, 1e-8) * np.sqrt(252 * 288)

    both = tdf[tdf["both_filled"]]
    one_side = tdf[~tdf["both_filled"]]

    return {
        "n_trades": n,
        "n_wins": wins,
        "win_rate": round(wins / n, 4),
        "total_pnl": round(pnls.sum(), 2),
        "roi_pct": round(pnls.sum() / capital * 100, 2),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(abs(dd.min()) * 100, 2),
        "avg_pnl": round(mu, 4),
        "n_both_filled": len(both),
        "n_one_side": len(one_side),
        "total_spread_earned": round(tdf["spread_earned"].sum(), 2),
        "pct_long": round((tdf["side"] == "LONG").mean(), 4),
        "pct_short": round((tdf["side"] == "SHORT").mean(), 4),
        "pct_flat": round((tdf["side"] == "FLAT").mean(), 4),
        "both_fill_wr": round(both["won"].mean(), 4) if len(both) > 0 else 0,
        "one_side_wr": round(one_side["won"].mean(), 4) if len(one_side) > 0 else 0,
        "final_capital": round(capital + pnls.sum(), 2),
    }

"""
Kelly criterion for OBI event contract trading.

For a binary contract at price c, if we estimate the true probability
of YES winning at p:
    - Payout on win: 1 - c  (buy at c, receive 1)
    - Loss on lose: c       (buy at c, receive 0)
    - Odds: b = (1 - c) / c
    - Kelly fraction: f* = (p * b - q) / b = (p - c) / (1 - c)

The edge is entirely in the gap between our estimated p and the market
price c.  When OBI is priced in (p ≈ c), Kelly correctly sizes to ~0.
When OBI reveals mispricing (p >> c or p << c), Kelly sizes up.

We calibrate p from OBI using the empirical OBI→outcome relationship
from historical data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.interpolate import interp1d


# ---------------------------------------------------------------------------
# Kelly math
# ---------------------------------------------------------------------------

def kelly_fraction(p: float, c: float) -> float:
    """Full Kelly fraction for a binary contract.

    p: estimated probability of YES winning
    c: market price (cost) of YES contract
    Returns: fraction of bankroll to wager (can be negative = bet NO)
    """
    if c <= 0 or c >= 1:
        return 0.0
    f = (p - c) / (1 - c)
    return f


def kelly_bet(
    p: float,
    c: float,
    bankroll: float,
    fraction: float = 0.25,
    max_bet_pct: float = 0.05,
) -> Tuple[str, float, float]:
    """Compute Kelly-optimal bet.

    Returns (side, quantity, edge) where:
        side: "YES" or "NO"
        quantity: dollar amount to bet (0 if no edge)
        edge: estimated edge (p - c for YES, (1-p) - (1-c) for NO)
    """
    f_yes = kelly_fraction(p, c)

    if f_yes > 0:
        side = "YES"
        edge = p - c
        bet_frac = f_yes * fraction
    elif f_yes < 0:
        side = "NO"
        edge = (1 - p) - (1 - c)
        no_price = 1 - c
        f_no = kelly_fraction(1 - p, no_price)
        bet_frac = f_no * fraction
    else:
        return "NONE", 0.0, 0.0

    bet_frac = min(bet_frac, max_bet_pct)
    bet_frac = max(bet_frac, 0.0)
    qty = bankroll * bet_frac

    return side, qty, edge


# ---------------------------------------------------------------------------
# OBI → probability calibration
# ---------------------------------------------------------------------------

def calibrate_obi_to_prob(
    features: pd.DataFrame,
    n_bins: int = 20,
) -> interp1d:
    """Build an empirical mapping from OBI → P(YES wins).

    Bins OBI values and computes the empirical win rate in each bin.
    Returns an interpolation function: obi_value → estimated probability.
    """
    df = features.dropna(subset=["obi", "outcome"]).copy()
    df["obi_bin"] = pd.qcut(df["obi"], n_bins, duplicates="drop")
    cal = df.groupby("obi_bin", observed=True)["outcome"].agg(["mean", "count"])
    cal = cal[cal["count"] >= 5]

    bin_centers = [interval.mid for interval in cal.index]
    probs = cal["mean"].values

    if len(bin_centers) < 3:
        return lambda x: 0.5

    func = interp1d(
        bin_centers, probs,
        kind="linear",
        bounds_error=False,
        fill_value=(probs[0], probs[-1]),
    )
    return func


def calibrate_obi_logistic(
    features: pd.DataFrame,
) -> Tuple[float, float]:
    """Fit logistic regression: P(YES) = sigmoid(a * OBI + b).

    Returns (a, b) coefficients. More robust than binned calibration
    for sparse data.
    """
    df = features.dropna(subset=["obi", "outcome"]).copy()
    from scipy.optimize import minimize

    def neg_log_likelihood(params):
        a, b = params
        z = a * df["obi"].values + b
        p = 1 / (1 + np.exp(-np.clip(z, -20, 20)))
        p = np.clip(p, 1e-8, 1 - 1e-8)
        y = df["outcome"].values
        return -np.sum(y * np.log(p) + (1 - y) * np.log(1 - p))

    result = minimize(neg_log_likelihood, [1.0, 0.0], method="Nelder-Mead")
    return result.x[0], result.x[1]


def logistic_prob(obi: float, a: float, b: float) -> float:
    z = a * obi + b
    return 1 / (1 + np.exp(-np.clip(z, -20, 20)))


# ---------------------------------------------------------------------------
# Kelly backtest
# ---------------------------------------------------------------------------

@dataclass
class KellyTrade:
    token_id: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    dollar_bet: float
    pnl: float
    fee: float
    net_pnl: float
    won: bool
    obi: float
    estimated_p: float
    market_price: float
    edge: float
    kelly_f: float
    spread: float


def backtest_kelly(
    features: pd.DataFrame,
    kelly_frac: float = 0.25,
    max_bet_pct: float = 0.05,
    min_edge: float = 0.01,
    max_spread: float = 0.10,
    min_ticks: int = 10,
    entry_fee_pct: float = 0.02,
    capital: float = 10_000.0,
    calibration: str = "logistic",
    n_cal_bins: int = 20,
    train_frac: float = 0.6,
) -> Dict:
    """Run Kelly-criterion OBI backtest on real contract features.

    Splits data into train (calibration) and test (backtest) sets.
    Train set: fit OBI→P(YES) mapping.
    Test set: apply Kelly betting with the calibrated probabilities.
    """
    df = features.dropna(subset=["obi", "outcome"]).copy()
    df = df[df["n_ticks"] >= min_ticks].copy()
    df = df[df["median_spread"] <= max_spread].copy()
    df = df.sort_index().reset_index(drop=True)

    if len(df) < 20:
        return {"error": "Too few contracts", "n_trades": 0}

    # Train/test split (temporal via index order)
    split = int(len(df) * train_frac)
    train = df.iloc[:split]
    test = df.iloc[split:]

    # Calibrate on train set
    if calibration == "logistic":
        a, b = calibrate_obi_logistic(train)
        prob_func = lambda obi: logistic_prob(obi, a, b)
        cal_info = {"calibration": "logistic", "a": round(a, 4), "b": round(b, 4)}
    else:
        interp = calibrate_obi_to_prob(train, n_bins=n_cal_bins)
        prob_func = interp
        cal_info = {"calibration": "binned", "n_bins": n_cal_bins}

    # Backtest on test set
    trades: List[KellyTrade] = []
    current_capital = capital

    for _, row in test.iterrows():
        obi = row["obi"]
        outcome = row["outcome"]
        market_bid = row["last_bid"]
        market_ask = row["last_ask"]
        spread = row["median_spread"]

        p_yes = float(prob_func(obi))
        p_yes = np.clip(p_yes, 0.01, 0.99)

        market_mid = (market_bid + market_ask) / 2

        side, dollar_bet, edge = kelly_bet(
            p_yes, market_mid, current_capital,
            fraction=kelly_frac,
            max_bet_pct=max_bet_pct,
        )

        if side == "NONE" or dollar_bet < 0.01 or abs(edge) < min_edge:
            continue

        if side == "YES":
            entry_price = market_ask
        else:
            entry_price = 1 - market_bid

        entry_price = np.clip(entry_price, 0.01, 0.99)
        qty = dollar_bet / entry_price
        qty = max(1, int(qty))
        actual_dollar = qty * entry_price

        won = (side == "YES" and outcome == 1) or (side == "NO" and outcome == 0)
        exit_price = 1.0 if won else 0.0
        pnl = qty * (exit_price - entry_price)
        fee = actual_dollar * entry_fee_pct
        net = pnl - fee
        current_capital += net

        f_full = kelly_fraction(p_yes, market_mid)

        trades.append(KellyTrade(
            token_id=row["token_id"],
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=qty,
            dollar_bet=actual_dollar,
            pnl=pnl,
            fee=fee,
            net_pnl=net,
            won=won,
            obi=obi,
            estimated_p=p_yes,
            market_price=market_mid,
            edge=edge,
            kelly_f=f_full,
            spread=spread,
        ))

    if not trades:
        return {
            "n_trades": 0, "n_train": len(train), "n_test": len(test),
            **cal_info, "note": "No trades — Kelly found no edge above min_edge",
        }

    # Metrics
    pnls = np.array([t.net_pnl for t in trades])
    n = len(trades)
    wins = sum(1 for t in trades if t.won)
    edges = np.array([t.edge for t in trades])
    kelly_fs = np.array([t.kelly_f for t in trades])

    equity = capital + np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.clip(peak, 1, None)
    max_dd = abs(dd.min()) * 100

    mu = pnls.mean()
    sigma = pnls.std() if n > 1 else 1e-8
    sharpe = mu / max(sigma, 1e-8) * np.sqrt(252 * 288)

    wins_pnl = pnls[pnls > 0].sum()
    loss_pnl = abs(pnls[pnls <= 0].sum())
    pf = wins_pnl / max(loss_pnl, 1e-8)

    yes_trades = sum(1 for t in trades if t.side == "YES")
    no_trades = n - yes_trades

    return {
        "n_train": len(train),
        "n_test": len(test),
        "n_trades": n,
        "n_yes": yes_trades,
        "n_no": no_trades,
        "n_wins": wins,
        "win_rate": round(wins / n, 4),
        "total_pnl": round(pnls.sum(), 2),
        "roi_pct": round(pnls.sum() / capital * 100, 2),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd, 2),
        "profit_factor": round(pf, 4),
        "avg_pnl": round(mu, 4),
        "avg_edge": round(edges.mean(), 4),
        "avg_kelly_f": round(kelly_fs.mean(), 4),
        "avg_dollar_bet": round(np.mean([t.dollar_bet for t in trades]), 2),
        "avg_spread": round(np.mean([t.spread for t in trades]), 4),
        "final_capital": round(current_capital, 2),
        **cal_info,
    }

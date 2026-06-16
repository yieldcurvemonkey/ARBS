"""
Vectorized backtest engine for order book imbalance on binary event contracts.

Uses historical crypto price data to determine contract outcomes (up/down),
simulates order book microstructure, computes OBI signals, and runs a
full P&L simulation.  Supports BTC, ETH, SOL, and any ccxt-listed pair.
"""
from __future__ import annotations

import datetime
import itertools
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from OBI.config import BacktestConfig
from OBI.signals import (
    compute_obi,
    generate_signals,
    simulate_contract_book,
    standardize_obi_series,
)

warnings.filterwarnings("ignore", category=FutureWarning)


# ---------------------------------------------------------------------------
# Crypto price data fetching (multi-asset)
# ---------------------------------------------------------------------------

def fetch_crypto_prices(
    symbol: str = "BTC/USDT",
    start: str = "2025-01-01",
    end: str = "2025-06-01",
    source: str = "ccxt",
    exchange: str = "binance",
    timeframe: str = "1m",
    yf_ticker: Optional[str] = None,
) -> pd.DataFrame:
    """Fetch minute-level candles for any crypto pair.

    Returns DataFrame with columns: open, high, low, close, volume
    indexed by UTC timestamp.
    """
    start_dt = pd.Timestamp(start, tz="UTC")
    end_dt = pd.Timestamp(end, tz="UTC")

    if source == "ccxt":
        return _fetch_ccxt(exchange, timeframe, start_dt, end_dt, symbol=symbol)
    elif source == "yfinance":
        ticker = yf_ticker or symbol.replace("/", "-").replace("USDT", "USD")
        return _fetch_yfinance(start_dt, end_dt, ticker=ticker)
    else:
        raise ValueError(f"Unknown data source: {source}")


def fetch_btc_prices(
    start: str,
    end: str,
    source: str = "ccxt",
    exchange: str = "binance",
    timeframe: str = "1m",
) -> pd.DataFrame:
    """Backward-compatible wrapper: fetch BTC/USDT candles."""
    return fetch_crypto_prices(
        symbol="BTC/USDT",
        start=start,
        end=end,
        source=source,
        exchange=exchange,
        timeframe=timeframe,
        yf_ticker="BTC-USD",
    )


def _fetch_ccxt(
    exchange_id: str,
    timeframe: str,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    symbol: str = "BTC/USDT",
) -> pd.DataFrame:
    import ccxt

    exchange_cls = getattr(ccxt, exchange_id)
    ex = exchange_cls({"enableRateLimit": True})

    all_candles = []
    since_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    limit = 1000

    while since_ms < end_ms:
        candles = ex.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=limit)
        if not candles:
            break
        all_candles.extend(candles)
        since_ms = candles[-1][0] + 1
        if len(candles) < limit:
            break

    df = pd.DataFrame(
        all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    df = df[df.index <= end_dt]
    return df


def _fetch_yfinance(
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    ticker: str = "BTC-USD",
) -> pd.DataFrame:
    import yfinance as yf

    data = yf.download(
        ticker,
        start=start_dt.strftime("%Y-%m-%d"),
        end=end_dt.strftime("%Y-%m-%d"),
        interval="1m",
        progress=False,
    )
    data.index = data.index.tz_convert("UTC")
    data.columns = [c.lower() for c in data.columns]
    return data[["open", "high", "low", "close", "volume"]]


# ---------------------------------------------------------------------------
# Contract outcome generation
# ---------------------------------------------------------------------------

def generate_contract_windows(
    btc_prices: pd.DataFrame,
    duration_minutes: int = 5,
) -> pd.DataFrame:
    """Slice BTC prices into non-overlapping contract windows.

    Each window represents one binary contract:
    'Did BTC go up in this window?'

    Returns DataFrame with one row per contract:
        start_time, end_time, open_price, close_price, outcome (1=up, 0=down),
        return_pct, volatility
    """
    close = btc_prices["close"]
    n_bars = duration_minutes
    n_contracts = len(close) // n_bars

    records = []
    for i in range(n_contracts):
        start_idx = i * n_bars
        end_idx = start_idx + n_bars - 1
        if end_idx >= len(close):
            break

        window = close.iloc[start_idx : end_idx + 1]
        open_px = window.iloc[0]
        close_px = window.iloc[-1]
        ret = (close_px - open_px) / open_px
        vol = window.pct_change().dropna().std() if len(window) > 1 else 0.0
        outcome = 1 if close_px >= open_px else 0

        records.append({
            "contract_idx": i,
            "start_time": window.index[0],
            "end_time": window.index[-1],
            "open_price": open_px,
            "close_price": close_px,
            "return_pct": ret,
            "volatility": vol,
            "outcome": outcome,
        })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Simulated fair probability
# ---------------------------------------------------------------------------

def estimate_fair_probs(
    contracts: pd.DataFrame,
    base_prob: float = 0.50,
    vol_adj: float = 0.1,
) -> np.ndarray:
    """Estimate fair probability for each contract.

    In practice, BTC is roughly 50/50 up/down in any short window.
    We add slight vol-based adjustment to make it realistic.
    """
    n = len(contracts)
    vols = contracts["volatility"].values
    probs = np.full(n, base_prob)
    probs += np.clip(vols * vol_adj * 100, -0.1, 0.1)
    return np.clip(probs, 0.1, 0.9)


# ---------------------------------------------------------------------------
# Core backtest
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    contract_idx: int
    entry_time: Any
    exit_time: Any
    side: str             # "YES" or "NO"
    entry_price: float
    exit_price: float     # 1.0 if won, 0.0 if lost (binary)
    quantity: float
    pnl: float
    fees: float
    net_pnl: float
    obi_at_entry: float
    signal_strength: float
    outcome: int
    won: bool


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: List[TradeRecord]
    equity_curve: pd.Series
    contracts_df: pd.DataFrame
    metrics: Dict[str, float] = field(default_factory=dict)

    def summary(self) -> Dict[str, Any]:
        return {**self.config.to_dict(), **self.metrics}


def run_backtest(
    config: BacktestConfig,
    btc_prices: Optional[pd.DataFrame] = None,
    prices: Optional[pd.DataFrame] = None,
) -> BacktestResult:
    """Run a full OBI backtest on simulated event contracts.

    1. Fetch/use asset prices (BTC, ETH, SOL, …)
    2. Generate contract windows
    3. Simulate order book & OBI for each contract
    4. Apply signal logic
    5. Execute trades and compute P&L

    *prices* takes precedence over the legacy *btc_prices* parameter.
    """
    asset_prices = prices if prices is not None else btc_prices
    if asset_prices is None:
        asset_prices = fetch_crypto_prices(
            symbol=config.asset_symbol,
            start=config.start_date,
            end=config.end_date,
            source=config.btc_data_source,
            exchange=config.btc_exchange,
            timeframe=config.btc_timeframe,
            yf_ticker=config.asset_yf_ticker,
        )

    contracts = generate_contract_windows(asset_prices, config.contract_duration_minutes)
    if contracts.empty:
        return BacktestResult(
            config=config, trades=[], equity_curve=pd.Series(dtype=float),
            contracts_df=contracts, metrics=_empty_metrics(),
        )

    fair_probs = estimate_fair_probs(contracts)
    outcomes = contracts["outcome"].values
    n = len(contracts)

    rng = np.random.default_rng(42)

    trades: List[TradeRecord] = []
    equity = [config.capital]
    current_capital = config.capital
    daily_pnl = 0.0
    consecutive_losses = 0
    daily_trades = 0
    last_date = None

    snapshots_per_contract = max(1, config.contract_duration_minutes * 60 // max(config.obi_lookback_seconds, 1))
    entry_snapshot = max(
        0,
        min(
            snapshots_per_contract - 1,
            int(config.entry_delay_seconds / max(config.obi_lookback_seconds, 1)),
        ),
    )

    obi_history = []

    for i in range(n):
        trade_date = contracts.iloc[i]["start_time"]
        if hasattr(trade_date, "date"):
            td = trade_date.date()
        else:
            td = trade_date

        if last_date != td:
            daily_pnl = 0.0
            daily_trades = 0
            last_date = td

        if daily_trades >= config.max_daily_trades:
            equity.append(current_capital)
            continue
        if daily_pnl <= -config.max_daily_loss:
            equity.append(current_capital)
            continue
        if consecutive_losses >= config.max_consecutive_losses:
            equity.append(current_capital)
            continue

        tp = fair_probs[i]
        outcome = outcomes[i]

        bids, asks, mid = simulate_contract_book(
            true_prob=tp + (outcome - tp) * config.sim_obi_predictive_power,
            depth_contracts=config.sim_book_depth_contracts,
            spread=config.sim_spread_mean,
            noise=config.sim_obi_noise,
            predictive_power=config.sim_obi_predictive_power,
            rng=rng,
        )

        obi_val = compute_obi(
            bids, asks, mid,
            variant=config.obi_variant,
            depth_levels=config.obi_depth_levels,
            depth_pct=config.obi_depth_pct,
        )
        obi_history.append(obi_val)

        if len(obi_history) >= config.obi_lookback_seconds:
            obi_series = pd.Series(obi_history[-config.obi_lookback_seconds :])
            if config.obi_ema_span > 0:
                obi_series = obi_series.ewm(span=config.obi_ema_span, min_periods=1).mean()
            std = obi_series.std()
            if std > 1e-8:
                z_obi = (obi_val - obi_series.mean()) / std
            else:
                z_obi = 0.0
        else:
            z_obi = obi_val

        spread = asks.iloc[0]["price"] - bids.iloc[0]["price"] if len(asks) > 0 and len(bids) > 0 else config.sim_spread_mean
        if spread > config.max_spread or spread < config.min_spread:
            equity.append(current_capital)
            continue

        signal = 0
        signal_strength = abs(z_obi)
        if z_obi > config.entry_threshold:
            signal = 1
        elif z_obi < -config.entry_threshold:
            signal = -1

        if config.signal_mode == "fade":
            signal = -signal

        if signal == 0:
            equity.append(current_capital)
            continue

        if config.sizing_mode == "fixed":
            qty = config.fixed_size
        elif config.sizing_mode == "scaled":
            qty = config.fixed_size * min(2.0, signal_strength / config.entry_threshold)
        elif config.sizing_mode == "kelly":
            win_rate = 0.52 if len(trades) < 10 else sum(1 for t in trades[-50:] if t.won) / min(50, len(trades))
            edge = win_rate - (1 - win_rate)
            kelly_size = max(0, edge / 1.0) * config.kelly_fraction
            qty = config.fixed_size * kelly_size * 10
        else:
            qty = config.fixed_size

        qty = min(qty, config.max_position)
        qty = max(1, qty)

        side = "YES" if signal > 0 else "NO"
        entry_price = mid + (spread / 2 if side == "YES" else -spread / 2)
        entry_price = np.clip(entry_price, 0.01, 0.99)

        entry_cost = qty * entry_price
        entry_fee = entry_cost * config.entry_fee_pct
        total_cost = entry_cost + entry_fee

        if total_cost > current_capital * 0.95:
            qty = max(1, int((current_capital * 0.95 - entry_fee) / entry_price))
            entry_cost = qty * entry_price
            entry_fee = entry_cost * config.entry_fee_pct
            total_cost = entry_cost + entry_fee

        won = (side == "YES" and outcome == 1) or (side == "NO" and outcome == 0)
        exit_price = 1.0 if won else 0.0

        pnl = qty * (exit_price - entry_price)
        exit_fee = qty * exit_price * config.exit_fee_pct
        net_pnl = pnl - entry_fee - exit_fee

        trades.append(TradeRecord(
            contract_idx=i,
            entry_time=contracts.iloc[i]["start_time"],
            exit_time=contracts.iloc[i]["end_time"],
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=qty,
            pnl=pnl,
            fees=entry_fee + exit_fee,
            net_pnl=net_pnl,
            obi_at_entry=obi_val,
            signal_strength=signal_strength,
            outcome=outcome,
            won=won,
        ))

        current_capital += net_pnl
        daily_pnl += net_pnl
        daily_trades += 1

        if won:
            consecutive_losses = 0
        else:
            consecutive_losses += 1

        equity.append(current_capital)

    equity_series = pd.Series(equity)
    metrics = compute_metrics(trades, equity_series, config)

    return BacktestResult(
        config=config,
        trades=trades,
        equity_curve=equity_series,
        contracts_df=contracts,
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def compute_metrics(
    trades: List[TradeRecord],
    equity: pd.Series,
    config: BacktestConfig,
) -> Dict[str, float]:
    if not trades:
        return _empty_metrics()

    pnls = np.array([t.net_pnl for t in trades])
    n_trades = len(trades)
    n_wins = sum(1 for t in trades if t.won)
    n_losses = n_trades - n_wins

    total_pnl = pnls.sum()
    win_rate = n_wins / n_trades if n_trades > 0 else 0.0
    avg_win = np.mean([p for p in pnls if p > 0]) if n_wins > 0 else 0.0
    avg_loss = np.mean([p for p in pnls if p <= 0]) if n_losses > 0 else 0.0
    profit_factor = abs(avg_win * n_wins / (avg_loss * n_losses)) if n_losses > 0 and avg_loss != 0 else float("inf")

    returns = equity.pct_change().dropna()
    ann_factor = np.sqrt(252 * (24 * 60 / config.contract_duration_minutes))

    sharpe = (returns.mean() / returns.std() * ann_factor) if returns.std() > 0 else 0.0

    downside = returns[returns < 0]
    sortino = (returns.mean() / downside.std() * ann_factor) if len(downside) > 0 and downside.std() > 0 else 0.0

    cummax = equity.cummax()
    drawdown = (equity - cummax) / cummax.clip(lower=1e-8)
    max_drawdown = drawdown.min()
    max_drawdown_pct = abs(max_drawdown) * 100

    calmar = (total_pnl / config.capital) / abs(max_drawdown) if abs(max_drawdown) > 1e-8 else 0.0

    win_streak = _max_streak(trades, True)
    loss_streak = _max_streak(trades, False)

    roi = total_pnl / config.capital * 100

    avg_entry = np.mean([t.entry_price for t in trades])
    total_fees = sum(t.fees for t in trades)

    return {
        "n_trades": n_trades,
        "n_wins": n_wins,
        "n_losses": n_losses,
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "roi_pct": round(roi, 2),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "calmar": round(calmar, 4),
        "profit_factor": round(profit_factor, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "avg_entry_price": round(avg_entry, 4),
        "total_fees": round(total_fees, 2),
        "win_streak": win_streak,
        "loss_streak": loss_streak,
        "avg_pnl_per_trade": round(total_pnl / n_trades, 4),
        "expectancy": round(win_rate * avg_win + (1 - win_rate) * avg_loss, 4),
    }


def _max_streak(trades: List[TradeRecord], winning: bool) -> int:
    streak = 0
    max_s = 0
    for t in trades:
        if t.won == winning:
            streak += 1
            max_s = max(max_s, streak)
        else:
            streak = 0
    return max_s


def _empty_metrics() -> Dict[str, float]:
    return {
        "n_trades": 0, "n_wins": 0, "n_losses": 0, "win_rate": 0.0,
        "total_pnl": 0.0, "roi_pct": 0.0, "sharpe": 0.0, "sortino": 0.0,
        "max_drawdown_pct": 0.0, "calmar": 0.0, "profit_factor": 0.0,
        "avg_win": 0.0, "avg_loss": 0.0, "avg_entry_price": 0.0,
        "total_fees": 0.0, "win_streak": 0, "loss_streak": 0,
        "avg_pnl_per_trade": 0.0, "expectancy": 0.0,
    }


# ---------------------------------------------------------------------------
# Grid search runner
# ---------------------------------------------------------------------------

def run_grid_search(
    base_config: BacktestConfig,
    grid: Dict[str, List[Any]],
    btc_prices: Optional[pd.DataFrame] = None,
    prices: Optional[pd.DataFrame] = None,
    progress: bool = True,
) -> pd.DataFrame:
    """Run backtest across all parameter combinations.

    Returns DataFrame of (param1, param2, ..., metric1, metric2, ...).
    *prices* takes precedence over legacy *btc_prices*.
    """
    asset_prices = prices if prices is not None else btc_prices
    if asset_prices is None:
        asset_prices = fetch_crypto_prices(
            symbol=base_config.asset_symbol,
            start=base_config.start_date,
            end=base_config.end_date,
            source=base_config.btc_data_source,
            exchange=base_config.btc_exchange,
            timeframe=base_config.btc_timeframe,
            yf_ticker=base_config.asset_yf_ticker,
        )

    param_names = list(grid.keys())
    param_values = list(grid.values())
    combos = list(itertools.product(*param_values))
    n_combos = len(combos)

    if progress:
        from tqdm import tqdm
        iterator = tqdm(combos, desc=f"Grid search ({base_config.asset})", total=n_combos)
    else:
        iterator = combos

    results = []
    for combo in iterator:
        overrides = dict(zip(param_names, combo))
        cfg_dict = base_config.to_dict()
        cfg_dict.update(overrides)
        cfg = BacktestConfig.from_dict(cfg_dict)

        try:
            result = run_backtest(cfg, prices=asset_prices)
            row = {**overrides, **result.metrics}
        except Exception as e:
            row = {**overrides, "error": str(e)}

        results.append(row)

    df = pd.DataFrame(results)
    return df


def select_best_configs(
    grid_df: pd.DataFrame,
    objectives: Optional[Dict[str, str]] = None,
) -> Dict[str, pd.Series]:
    """Select best configs for multiple objectives.

    Default objectives:
        best_sharpe: highest Sharpe ratio
        best_winrate: highest win rate
        balanced: best product of sharpe * win_rate
        min_drawdown: lowest max drawdown (with positive PnL)
        best_expectancy: highest per-trade expectancy
    """
    if objectives is None:
        objectives = {
            "best_sharpe": "sharpe",
            "best_winrate": "win_rate",
            "balanced": "balanced_score",
            "min_drawdown": "max_drawdown_pct",
            "best_expectancy": "expectancy",
        }

    valid = grid_df.dropna(subset=["sharpe"]).copy()
    if "error" in valid.columns:
        valid = valid[valid["error"].isna()].copy()

    if valid.empty:
        return {}

    valid["balanced_score"] = valid["sharpe"] * valid["win_rate"]

    results = {}
    for name, col in objectives.items():
        if col not in valid.columns:
            continue
        if name == "min_drawdown":
            profitable = valid[valid["total_pnl"] > 0]
            if not profitable.empty:
                idx = profitable[col].idxmin()
                results[name] = profitable.loc[idx]
        else:
            idx = valid[col].idxmax()
            results[name] = valid.loc[idx]

    return results

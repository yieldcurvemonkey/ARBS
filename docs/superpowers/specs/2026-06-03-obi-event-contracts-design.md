# OBI Event Contracts Strategy — Design Spec

## Overview

Order Book Imbalance (OBI) trading strategy for binary prediction market contracts
on Polymarket and Kalshi, with focus on BTC up/down contracts (5-min Polymarket,
15-min Kalshi).

## Architecture

```
OBI/
├── config.py              # BacktestConfig, ExecutionConfig, presets, grids
├── signals.py             # OBI computation (raw, normalized, weighted, multi-level)
├── backtest.py            # Vectorized backtest engine + grid search runner
├── tearsheet.py           # Performance analytics and visualization
├── data_collector.py      # Real-time order book snapshot collection
└── execution/
    ├── base.py            # Abstract execution engine + risk management
    ├── paper.py           # Paper trading (simulated fills, real signals)
    ├── live.py            # Polymarket + Kalshi live execution
    └── runner.py          # Polling loop that drives execution

MDP/EventContracts/
└── polymarket_orderbook.py  # New: CLOB order book, midpoint, spread, market impact
```

## Signal Logic

**Core Formula**: `OBI = (Σ Bid Qty - Σ Ask Qty) / (Σ Bid Qty + Σ Ask Qty)`

**Variants**:
- `raw`: Top-of-book only
- `normalized`: Aggregate top-N levels (default N=5)
- `weighted`: Distance-from-mid exponential decay
- `multi_level`: Same as normalized

**Standardization**: Rolling z-score over lookback window + optional EMA smoothing

**Signal Modes**:
- `follow`: Positive OBI → buy YES (momentum — bet with the crowd)
- `fade`: Positive OBI → buy NO (contrarian — bet against the crowd)

## Backtest Methodology

Since historical order book data for prediction market contracts is unavailable,
the backtest uses a simulation approach:

1. **BTC prices** fetched from Binance (ccxt) at 1-minute granularity
2. **Contract windows** sliced from price data (5-min or 15-min non-overlapping)
3. **Outcome** determined by whether BTC went up or down in each window
4. **Order book simulated** with configurable `predictive_power` parameter:
   - Higher power = book skews toward true outcome (informed traders)
   - Lower power = more noise (uninformed market)
5. **OBI computed** from simulated book, z-scored, thresholded → trade signal
6. **P&L** computed as binary: win = payout − entry; loss = −entry

**Key insight**: The `sim_obi_predictive_power` parameter controls how much
edge exists in the order book. The grid search finds optimal thresholds
conditional on the level of OBI informativeness.

## Grid Search

**Polymarket 5m**: 4,800 combinations
**Kalshi 15m**: 4,800 combinations

**Parameters swept**:
- `entry_threshold`: [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
- `signal_mode`: [follow, fade]
- `entry_delay_seconds`: [10, 20, 30, 45, 60] / [30, 60, 90, 120, 180]
- `obi_depth_levels`: [3, 5, 8, 10]
- `obi_variant`: [raw, normalized, weighted]
- `sim_obi_predictive_power`: [0.05, 0.10, 0.15, 0.20, 0.25]
- `sizing_mode`: [fixed, scaled]

**Objectives**:
- Best Sharpe ratio
- Best win rate
- Balanced (Sharpe × win rate)
- Min drawdown (among profitable configs)
- Best expectancy (per-trade edge)

## Execution Engine

**Paper mode**: Real order book data for signals, simulated fills
**Live mode**: Full venue API integration

**Risk controls**:
- Max daily loss
- Max daily trades
- Max consecutive losses
- Position limits
- Spread filters

**Supported venues**:
- Polymarket CLOB (public order book, EIP-712 signed orders)
- Kalshi REST API (RSA auth, limit/market orders)

## Data Collection

`OrderBookCollector` polls order book snapshots at configurable intervals
and stores to Hive-partitioned Parquet for future backtesting with real data.

## Limitations

1. Backtest uses simulated order books — real market microstructure may differ
2. The `predictive_power` parameter is a hypothesis about OBI informativeness
3. Short-duration contracts have thin order books → high slippage risk
4. No websocket support yet (polling only)
5. Polymarket live execution requires py-clob-client for EIP-712 signing

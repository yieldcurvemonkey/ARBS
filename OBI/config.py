"""
Order Book Imbalance strategy configuration for event contract trading.

All backtest and execution parameters are controlled via dicts that conform
to the schemas below.  Presets are provided for common setups.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Per-asset metadata used by price fetching, market discovery, and simulation
# ---------------------------------------------------------------------------

ASSET_CONFIGS: Dict[str, Dict[str, Any]] = {
    "BTC": {
        "symbol": "BTC/USDT",
        "yf_ticker": "BTC-USD",
        "search_query": "bitcoin",
        "keywords": ["btc", "bitcoin"],
        "kalshi_series": "KXBTC",
        "base_price": 105_000,
    },
    "ETH": {
        "symbol": "ETH/USDT",
        "yf_ticker": "ETH-USD",
        "search_query": "ethereum",
        "keywords": ["eth", "ethereum"],
        "kalshi_series": "KXETH",
        "base_price": 3_800,
    },
    "SOL": {
        "symbol": "SOL/USDT",
        "yf_ticker": "SOL-USD",
        "search_query": "solana",
        "keywords": ["sol", "solana"],
        "kalshi_series": "KXSOL",
        "base_price": 180,
    },
}


class Venue(str, Enum):
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"


class OBIVariant(str, Enum):
    RAW = "raw"
    NORMALIZED = "normalized"
    WEIGHTED = "weighted"
    MULTI_LEVEL = "multi_level"


class SignalMode(str, Enum):
    FOLLOW = "follow"       # trade in direction of imbalance (momentum)
    FADE = "fade"           # trade against imbalance (mean-reversion)


class SizingMode(str, Enum):
    FIXED = "fixed"
    SCALED = "scaled"       # size proportional to signal strength
    KELLY = "kelly"         # kelly criterion sizing


class ExecMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


# ---------------------------------------------------------------------------
# Backtest configuration
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    # --- venue & contract ---
    venue: str = "polymarket"
    contract_duration_minutes: int = 5        # 5 for polymarket, 15 for kalshi
    contract_type: str = "btc_up_down"

    # --- asset identification ---
    asset: str = "BTC"                        # key into ASSET_CONFIGS
    asset_symbol: str = "BTC/USDT"            # ccxt trading pair
    asset_yf_ticker: str = "BTC-USD"          # yfinance ticker

    # --- OBI signal ---
    obi_variant: str = "normalized"
    obi_depth_levels: int = 5                 # order book levels for OBI calc
    obi_depth_pct: float = 0.025             # depth as % of mid (weighted variant)
    obi_lookback_seconds: int = 60           # rolling window for standardization
    obi_ema_span: int = 10                   # EMA smoothing span (0 = no smoothing)

    # --- entry ---
    signal_mode: str = "follow"
    entry_threshold: float = 0.15            # min |OBI| to trigger entry
    entry_delay_seconds: int = 30            # seconds after contract open to enter
    max_entry_pct: float = 0.80              # don't enter after this % of contract life
    min_spread: float = 0.0                  # min bid-ask spread to accept
    max_spread: float = 0.10                 # max spread filter

    # --- exit ---
    hold_to_expiry: bool = True              # hold binary contract to resolution
    early_exit_threshold: float = 0.0        # exit if signal reverses beyond this
    stop_loss_pct: float = 0.0               # 0 = disabled
    take_profit_pct: float = 0.0             # 0 = disabled

    # --- position sizing ---
    sizing_mode: str = "fixed"
    fixed_size: float = 10.0                 # contracts per trade (fixed mode)
    max_position: float = 100.0              # max outstanding contracts
    kelly_fraction: float = 0.25             # fractional kelly
    capital: float = 10_000.0                # total capital

    # --- risk ---
    max_daily_loss: float = 500.0            # daily loss limit
    max_daily_trades: int = 200              # max trades per day
    max_consecutive_losses: int = 10         # stop after N consecutive losses

    # --- fees ---
    entry_fee_pct: float = 0.02             # % of notional
    exit_fee_pct: float = 0.0               # many venues: 0 on resolution
    spread_cost: float = 0.01               # estimated half-spread cost

    # --- simulation (backtest-only) ---
    btc_data_source: str = "ccxt"           # ccxt or yfinance (legacy name kept)
    btc_exchange: str = "binance"           # for ccxt (legacy name kept)
    btc_timeframe: str = "1m"              # candle granularity (legacy name kept)
    sim_obi_noise: float = 0.3              # noise in simulated OBI
    sim_obi_predictive_power: float = 0.15  # correlation of OBI with outcome
    sim_book_depth_contracts: int = 500     # simulated book depth
    sim_spread_mean: float = 0.03           # simulated mean spread

    # --- backtest period ---
    start_date: str = "2025-01-01"
    end_date: str = "2025-06-01"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BacktestConfig":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid})


# ---------------------------------------------------------------------------
# Execution configuration (live / paper)
# ---------------------------------------------------------------------------

@dataclass
class ExecutionConfig:
    mode: str = "paper"
    venue: str = "polymarket"

    # --- connection ---
    poll_interval_ms: int = 500              # order book poll interval
    ws_enabled: bool = False                 # use websocket if available

    # --- polymarket ---
    poly_api_key: str = ""
    poly_api_secret: str = ""
    poly_api_passphrase: str = ""
    poly_funder: str = ""                    # funder address
    poly_chain_id: int = 137                 # polygon mainnet

    # --- kalshi ---
    kalshi_api_key_id: str = ""
    kalshi_private_key_path: str = ""

    # --- strategy (mirrors backtest) ---
    obi_variant: str = "normalized"
    obi_depth_levels: int = 5
    entry_threshold: float = 0.15
    signal_mode: str = "follow"
    sizing_mode: str = "fixed"
    fixed_size: float = 10.0
    max_position: float = 100.0
    capital: float = 10_000.0

    # --- risk ---
    max_daily_loss: float = 500.0
    max_daily_trades: int = 200
    max_consecutive_losses: int = 10

    # --- contract targeting ---
    contract_duration_minutes: int = 5
    contract_type: str = "btc_up_down"
    asset: str = "BTC"
    asset_keywords: List[str] = field(default_factory=lambda: ["btc", "bitcoin"])
    asset_search_query: str = "bitcoin"
    asset_series_ticker: str = "KXBTC"
    target_tickers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExecutionConfig":
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid})


# ---------------------------------------------------------------------------
# Grid search parameter space
# ---------------------------------------------------------------------------

DEFAULT_GRID = {
    "obi_variant": ["raw", "normalized", "weighted"],
    "entry_threshold": [0.05, 0.10, 0.15, 0.20, 0.30, 0.40],
    "signal_mode": ["follow", "fade"],
    "entry_delay_seconds": [10, 30, 60],
    "obi_depth_levels": [3, 5, 10],
    "obi_lookback_seconds": [30, 60, 120],
    "sizing_mode": ["fixed", "scaled"],
    "sim_obi_predictive_power": [0.05, 0.10, 0.15, 0.20, 0.30],
}

FOCUSED_GRID = {
    "entry_threshold": [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40],
    "signal_mode": ["follow", "fade"],
    "entry_delay_seconds": [10, 20, 30, 45, 60],
    "obi_depth_levels": [3, 5, 8, 10],
    "sim_obi_predictive_power": [0.05, 0.10, 0.15, 0.20, 0.25],
}

QUICK_GRID = {
    "entry_threshold": [0.10, 0.20, 0.30],
    "signal_mode": ["follow", "fade"],
    "entry_delay_seconds": [15, 30, 60],
}


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

POLYMARKET_5M_BTC = BacktestConfig(
    venue="polymarket",
    contract_duration_minutes=5,
    contract_type="btc_up_down",
    asset="BTC",
    asset_symbol="BTC/USDT",
    asset_yf_ticker="BTC-USD",
    entry_delay_seconds=30,
    entry_threshold=0.15,
    signal_mode="follow",
    obi_variant="normalized",
    obi_depth_levels=5,
    entry_fee_pct=0.02,
    exit_fee_pct=0.0,
    spread_cost=0.02,
    start_date="2025-01-01",
    end_date="2025-06-01",
)

KALSHI_15M_BTC = BacktestConfig(
    venue="kalshi",
    contract_duration_minutes=15,
    contract_type="btc_up_down",
    asset="BTC",
    asset_symbol="BTC/USDT",
    asset_yf_ticker="BTC-USD",
    entry_delay_seconds=60,
    entry_threshold=0.15,
    signal_mode="follow",
    obi_variant="normalized",
    obi_depth_levels=5,
    entry_fee_pct=0.07,
    exit_fee_pct=0.0,
    spread_cost=0.03,
    start_date="2025-01-01",
    end_date="2025-06-01",
)

POLYMARKET_5M_ETH = BacktestConfig(
    venue="polymarket",
    contract_duration_minutes=5,
    contract_type="eth_up_down",
    asset="ETH",
    asset_symbol="ETH/USDT",
    asset_yf_ticker="ETH-USD",
    entry_delay_seconds=30,
    entry_threshold=0.15,
    signal_mode="follow",
    obi_variant="normalized",
    obi_depth_levels=5,
    entry_fee_pct=0.02,
    exit_fee_pct=0.0,
    spread_cost=0.02,
    start_date="2025-01-01",
    end_date="2025-06-01",
)

POLYMARKET_5M_SOL = BacktestConfig(
    venue="polymarket",
    contract_duration_minutes=5,
    contract_type="sol_up_down",
    asset="SOL",
    asset_symbol="SOL/USDT",
    asset_yf_ticker="SOL-USD",
    entry_delay_seconds=30,
    entry_threshold=0.15,
    signal_mode="follow",
    obi_variant="normalized",
    obi_depth_levels=5,
    entry_fee_pct=0.02,
    exit_fee_pct=0.0,
    spread_cost=0.02,
    start_date="2025-01-01",
    end_date="2025-06-01",
)


def build_config(base: BacktestConfig, overrides: Dict[str, Any]) -> BacktestConfig:
    d = base.to_dict()
    d.update(overrides)
    return BacktestConfig.from_dict(d)


def build_asset_execution_config(
    asset: str,
    base: Optional[ExecutionConfig] = None,
    **overrides: Any,
) -> ExecutionConfig:
    """Build an ExecutionConfig for a given asset key (BTC, ETH, SOL)."""
    acfg = ASSET_CONFIGS[asset]
    defaults = {
        "asset": asset,
        "contract_type": f"{asset.lower()}_up_down",
        "asset_keywords": acfg["keywords"],
        "asset_search_query": acfg["search_query"],
        "asset_series_ticker": acfg["kalshi_series"],
    }
    if base is not None:
        d = base.to_dict()
    else:
        d = ExecutionConfig().to_dict()
    d.update(defaults)
    d.update(overrides)
    return ExecutionConfig.from_dict(d)

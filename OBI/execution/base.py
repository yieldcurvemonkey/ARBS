"""
Base execution engine for OBI strategy on event contracts.

Handles order book polling, signal computation, position management,
and risk controls. Subclasses implement venue-specific order submission.
"""
from __future__ import annotations

import datetime
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from OBI.config import ExecutionConfig
from OBI.signals import compute_obi

logger = logging.getLogger(__name__)


@dataclass
class Position:
    contract_id: str
    side: str               # "YES" or "NO"
    quantity: float
    entry_price: float
    entry_time: datetime.datetime
    expiry_time: Optional[datetime.datetime] = None
    exit_price: Optional[float] = None
    exit_time: Optional[datetime.datetime] = None
    pnl: Optional[float] = None
    status: str = "open"    # open, closed, expired


@dataclass
class OrderRequest:
    contract_id: str
    side: str               # "YES" or "NO"
    quantity: float
    price: float
    order_type: str = "limit"   # limit, market


@dataclass
class Fill:
    order_id: str
    contract_id: str
    side: str
    quantity: float
    price: float
    timestamp: datetime.datetime
    fees: float = 0.0


@dataclass
class ExecutionState:
    capital: float
    positions: Dict[str, Position] = field(default_factory=dict)
    closed_positions: List[Position] = field(default_factory=list)
    fills: List[Fill] = field(default_factory=list)
    daily_pnl: float = 0.0
    daily_trades: int = 0
    consecutive_losses: int = 0
    last_trade_date: Optional[datetime.date] = None
    obi_history: List[float] = field(default_factory=list)
    is_running: bool = False


class BaseExecutionEngine(ABC):
    """Abstract execution engine with signal generation and risk management."""

    def __init__(self, config: ExecutionConfig):
        self.config = config
        self.state = ExecutionState(capital=config.capital)
        self._setup_logging()

    def _setup_logging(self):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [OBI-%(levelname)s] %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    # --- abstract methods for venue-specific implementation ---

    @abstractmethod
    def fetch_orderbook(self, contract_id: str) -> Dict[str, pd.DataFrame]:
        """Fetch current order book. Returns {'bids': df, 'asks': df}."""

    @abstractmethod
    def submit_order(self, order: OrderRequest) -> Optional[Fill]:
        """Submit order to venue. Returns Fill on success, None on failure."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""

    @abstractmethod
    def get_active_contracts(self) -> List[Dict[str, Any]]:
        """Get list of currently active contracts matching our criteria."""

    @abstractmethod
    def get_contract_expiry(self, contract_id: str) -> Optional[datetime.datetime]:
        """Get expiry time for a contract."""

    # --- core logic ---

    def process_contract(self, contract_id: str) -> Optional[str]:
        """Process one contract: fetch book, compute signal, maybe trade.

        Returns action taken: 'buy_yes', 'buy_no', 'skip', or None on error.
        """
        try:
            book = self.fetch_orderbook(contract_id)
        except Exception as e:
            logger.warning(f"Failed to fetch orderbook for {contract_id}: {e}")
            return None

        bids = book.get("bids", pd.DataFrame())
        asks = book.get("asks", pd.DataFrame())

        if bids.empty or asks.empty:
            return "skip"

        mid = (bids.iloc[0]["price"] + asks.iloc[0]["price"]) / 2
        spread = asks.iloc[0]["price"] - bids.iloc[0]["price"]

        if spread > 0.10:
            return "skip"

        obi = compute_obi(
            bids, asks, mid,
            variant=self.config.obi_variant,
            depth_levels=self.config.obi_depth_levels,
        )

        self.state.obi_history.append(obi)

        lookback = min(len(self.state.obi_history), 60)
        if lookback > 5:
            recent = np.array(self.state.obi_history[-lookback:])
            std = recent.std()
            if std > 1e-8:
                z_obi = (obi - recent.mean()) / std
            else:
                z_obi = 0.0
        else:
            z_obi = obi

        if not self._check_risk_limits():
            return "skip"

        signal = 0
        if z_obi > self.config.entry_threshold:
            signal = 1
        elif z_obi < -self.config.entry_threshold:
            signal = -1

        if self.config.signal_mode == "fade":
            signal = -signal

        if signal == 0:
            return "skip"

        if contract_id in self.state.positions:
            return "skip"

        side = "YES" if signal > 0 else "NO"
        entry_price = asks.iloc[0]["price"] if side == "YES" else bids.iloc[0]["price"]
        qty = self._compute_size(z_obi, entry_price)

        if qty <= 0:
            return "skip"

        order = OrderRequest(
            contract_id=contract_id,
            side=side,
            quantity=qty,
            price=entry_price,
        )

        fill = self.submit_order(order)
        if fill is None:
            return "skip"

        pos = Position(
            contract_id=contract_id,
            side=side,
            quantity=fill.quantity,
            entry_price=fill.price,
            entry_time=fill.timestamp,
            expiry_time=self.get_contract_expiry(contract_id),
        )

        self.state.positions[contract_id] = pos
        self.state.fills.append(fill)
        self.state.capital -= fill.quantity * fill.price + fill.fees
        self.state.daily_trades += 1

        logger.info(
            f"TRADE: {side} {qty:.0f}x {contract_id} @ {fill.price:.3f} | "
            f"OBI={obi:.3f} z={z_obi:.3f} | capital={self.state.capital:.2f}"
        )

        return f"buy_{side.lower()}"

    def resolve_position(self, contract_id: str, outcome: int):
        """Resolve a binary contract position. outcome: 1=YES won, 0=NO won."""
        if contract_id not in self.state.positions:
            return

        pos = self.state.positions.pop(contract_id)
        won = (pos.side == "YES" and outcome == 1) or (pos.side == "NO" and outcome == 0)
        exit_price = 1.0 if won else 0.0
        pnl = pos.quantity * (exit_price - pos.entry_price)

        pos.exit_price = exit_price
        pos.exit_time = datetime.datetime.now(datetime.timezone.utc)
        pos.pnl = pnl
        pos.status = "closed"

        self.state.closed_positions.append(pos)
        self.state.capital += pos.quantity * exit_price
        self.state.daily_pnl += pnl

        if won:
            self.state.consecutive_losses = 0
        else:
            self.state.consecutive_losses += 1

        status = "WIN" if won else "LOSS"
        logger.info(
            f"RESOLVED: {status} {pos.side} {contract_id} | "
            f"entry={pos.entry_price:.3f} pnl={pnl:+.2f} | "
            f"capital={self.state.capital:.2f}"
        )

    def _compute_size(self, z_obi: float, entry_price: float) -> float:
        if self.config.sizing_mode == "fixed":
            qty = self.config.fixed_size
        elif self.config.sizing_mode == "scaled":
            scale = min(2.0, abs(z_obi) / max(self.config.entry_threshold, 0.01))
            qty = self.config.fixed_size * scale
        else:
            qty = self.config.fixed_size

        qty = min(qty, self.config.max_position)
        max_affordable = (self.state.capital * 0.95) / max(entry_price, 0.01)
        qty = min(qty, max_affordable)
        return max(0, int(qty))

    def _check_risk_limits(self) -> bool:
        today = datetime.date.today()
        if self.state.last_trade_date != today:
            self.state.daily_pnl = 0.0
            self.state.daily_trades = 0
            self.state.last_trade_date = today

        if self.state.daily_trades >= self.config.max_daily_trades:
            return False
        if self.state.daily_pnl <= -self.config.max_daily_loss:
            return False
        if self.state.consecutive_losses >= self.config.max_consecutive_losses:
            return False
        return True

    def get_performance_summary(self) -> Dict[str, Any]:
        closed = self.state.closed_positions
        if not closed:
            return {"n_trades": 0, "total_pnl": 0.0, "win_rate": 0.0, "capital": self.state.capital}

        pnls = [p.pnl for p in closed if p.pnl is not None]
        wins = sum(1 for p in closed if p.pnl is not None and p.pnl > 0)
        return {
            "n_trades": len(closed),
            "n_wins": wins,
            "win_rate": wins / len(closed),
            "total_pnl": sum(pnls),
            "avg_pnl": np.mean(pnls),
            "capital": self.state.capital,
            "open_positions": len(self.state.positions),
        }

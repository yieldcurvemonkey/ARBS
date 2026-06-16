"""
Paper trading execution engine.

Simulates order fills using real order book data without submitting
actual orders to any venue. Useful for forward testing.
"""
from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional

import pandas as pd

from OBI.config import ExecutionConfig
from OBI.execution.base import BaseExecutionEngine, Fill, OrderRequest

logger = logging.getLogger(__name__)


class PaperExecutionEngine(BaseExecutionEngine):
    """Paper trading engine using live order book data for signal generation
    but simulating fills locally."""

    def __init__(self, config: ExecutionConfig, venue_fetcher=None):
        super().__init__(config)
        self._venue_fetcher = venue_fetcher
        self._active_contracts: List[Dict[str, Any]] = []
        self._order_log: List[Dict[str, Any]] = []

    def set_venue_fetcher(self, fetcher):
        self._venue_fetcher = fetcher

    def fetch_orderbook(self, contract_id: str) -> Dict[str, pd.DataFrame]:
        if self._venue_fetcher is None:
            raise RuntimeError("No venue fetcher configured")
        return self._venue_fetcher.fetch_orderbook(contract_id)

    def submit_order(self, order: OrderRequest) -> Optional[Fill]:
        fill_id = str(uuid.uuid4())[:8]
        now = datetime.datetime.now(datetime.timezone.utc)

        slippage = 0.005 if order.order_type == "market" else 0.002
        fill_price = order.price + slippage if order.side == "YES" else order.price - slippage
        fill_price = max(0.01, min(0.99, fill_price))

        fee_rate = 0.02
        fees = order.quantity * fill_price * fee_rate

        fill = Fill(
            order_id=fill_id,
            contract_id=order.contract_id,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            timestamp=now,
            fees=fees,
        )

        self._order_log.append({
            "order_id": fill_id,
            "contract_id": order.contract_id,
            "side": order.side,
            "requested_price": order.price,
            "fill_price": fill_price,
            "quantity": order.quantity,
            "fees": fees,
            "timestamp": now,
            "mode": "paper",
        })

        logger.info(f"PAPER FILL: {order.side} {order.quantity}x @ {fill_price:.3f} (req {order.price:.3f})")
        return fill

    def cancel_order(self, order_id: str) -> bool:
        logger.info(f"PAPER CANCEL: {order_id}")
        return True

    def get_active_contracts(self) -> List[Dict[str, Any]]:
        return self._active_contracts

    def set_active_contracts(self, contracts: List[Dict[str, Any]]):
        self._active_contracts = contracts

    def get_contract_expiry(self, contract_id: str) -> Optional[datetime.datetime]:
        for c in self._active_contracts:
            if c.get("id") == contract_id or c.get("ticker") == contract_id:
                exp = c.get("expiry") or c.get("close_time")
                if isinstance(exp, str):
                    return pd.Timestamp(exp).to_pydatetime()
                return exp
        return None

    def get_order_log(self) -> pd.DataFrame:
        return pd.DataFrame(self._order_log)

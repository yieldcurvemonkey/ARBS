# ABOUTME: Execution engine for processing backtest orders
# ABOUTME: Naive immediate-fill implementation (no slippage, pricing, or venue logic)
from __future__ import annotations
from typing import List
from BT.order import Order

class ExecutionEngine:
    """Naive immediate-fill execution."""
    def execute(self, orders: List[Order]) -> List[Order]:
        # In real life: pricing, slippage, partial fills, venue logic
        return orders

"""SERFF fair-value model: ZQ (30-day fed funds) vs SR3 (3m SOFR) futures.

Three-layer decomposition of the SOFR-FF spread (mechanical policy path,
reserve-demand level model, month-end turn hurdle model) emitting a dated,
source-tagged residual ledger per decision date, plus a walk-forward,
publication-lag-aligned backtest with P&L attribution by source.

Design spec: docs/superpowers/specs/2026-07-02-serff-fair-value-model.md
"""

from BT.serff.config import (
    SerffBacktestConfig,
    SerffDataConfig,
    SerffModelConfig,
    SerffTradeConfig,
)

__all__ = [
    "SerffBacktestConfig",
    "SerffDataConfig",
    "SerffModelConfig",
    "SerffTradeConfig",
]

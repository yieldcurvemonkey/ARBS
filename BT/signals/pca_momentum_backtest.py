"""Backtest adapters for the intraday PCA momentum strategy."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

import numpy as np
import pandas as pd

from BT.data_handler import TimeGrid
from BT.event import TriggerInfo
from BT.query_engine import QueryDrivenBacktest
from BT.query_order import QueryOrder, UnwindOrder
from BT.query_strategy import QueryStrategy
from BT.signals.pca_momentum import (
    PCAMomentumConfig,
    PCAMomentumWalkForwardResult,
    build_rank_tenor_map,
)
from BT.triggers import Trigger, TriggerRequirements

logger = logging.getLogger(__name__)


@dataclass
class PCAMomentumVectorizedBacktestResult:
    """Fast vectorized backtest result."""

    config: PCAMomentumConfig
    signal_panel: pd.DataFrame
    position_panel: pd.DataFrame
    per_contract_pnl: pd.DataFrame
    aggregate_pnl: pd.Series
    cumulative_pnl: pd.Series
    trade_sides: pd.Series
    metrics: dict[str, float]


@dataclass
class PCAMomentumQueryBacktestResult:
    """Query-driven backtest result."""

    config: PCAMomentumConfig
    signal_panel: pd.DataFrame
    backtest: QueryDrivenBacktest
    mtm_history: pd.Series
    pnl_history: pd.Series
    order_frame: pd.DataFrame
    metrics: dict[str, float]


def build_signal_table(signal_panel: pd.DataFrame) -> dict[pd.Timestamp, dict[str, int]]:
    """Convert a panel of signals into timestamp-indexed desired positions."""
    table: dict[pd.Timestamp, dict[str, int]] = {}
    for timestamp, row in signal_panel.iterrows():
        desired = {
            str(contract): _coerce_signal(value)
            for contract, value in row.items()
            if not pd.isna(value)
        }
        table[pd.Timestamp(timestamp)] = desired
    return table


def run_pca_momentum_vectorized_backtest(
    rate_panel: pd.DataFrame,
    signal_panel: pd.DataFrame,
    config: Optional[PCAMomentumConfig] = None,
) -> PCAMomentumVectorizedBacktestResult:
    """Approximate PnL with frozen per-rank receiver-long semantics."""
    cfg = config or PCAMomentumConfig()
    rates = rate_panel.sort_index().copy()
    signals = signal_panel.reindex(rates.index).copy()
    signals = signals.fillna(0.0).astype(float).clip(-1.0, 1.0)

    position_panel = signals.shift(1).fillna(0.0)
    delta_rates = rates.diff().fillna(0.0)
    gross_pnl = -position_panel * delta_rates * float(cfg.trade_bpv) * 100.0

    trade_sides_panel = signals.diff().abs()
    trade_sides_panel.iloc[0] = signals.iloc[0].abs()
    costs = trade_sides_panel * float(cfg.transaction_cost_bps_per_side) * float(cfg.trade_bpv)
    per_contract_pnl = gross_pnl - costs

    aggregate_pnl = per_contract_pnl.sum(axis=1)
    cumulative_pnl = aggregate_pnl.cumsum()
    trade_sides = trade_sides_panel.sum(axis=0)

    annualization = _annualization_factor(rates.index)
    metrics = _compute_backtest_metrics(
        pnl_series=aggregate_pnl,
        cumulative_pnl=cumulative_pnl,
        trade_sides=float(trade_sides.sum()),
        annualization_factor=annualization,
    )

    return PCAMomentumVectorizedBacktestResult(
        config=cfg,
        signal_panel=signals,
        position_panel=position_panel,
        per_contract_pnl=per_contract_pnl,
        aggregate_pnl=aggregate_pnl,
        cumulative_pnl=cumulative_pnl,
        trade_sides=trade_sides,
        metrics=metrics,
    )


def run_pca_momentum_query_backtest(
    signal_source: PCAMomentumWalkForwardResult | pd.DataFrame,
    *,
    config: Optional[PCAMomentumConfig] = None,
    mdp=None,
    contract_to_tenor: Optional[Mapping[str, str]] = None,
    show_progress: bool = False,
) -> PCAMomentumQueryBacktestResult:
    """Run the momentum strategy through QueryStrategy / QueryDrivenBacktest."""
    cfg = config or (signal_source.config if isinstance(signal_source, PCAMomentumWalkForwardResult) else PCAMomentumConfig())
    if mdp is None:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        mdp = IRSwapsMDP(source=cfg.source)
    if isinstance(signal_source, PCAMomentumWalkForwardResult):
        signal_panel = signal_source.signal_panel.copy()
        tenor_map = dict(signal_source.contract_to_tenor)
    else:
        signal_panel = signal_source.copy()
        tenor_map = dict(contract_to_tenor or build_rank_tenor_map(cfg.contract_ranks))

    signal_panel = signal_panel.sort_index()
    action = _PCAMomentumSignalAction(
        signal_table=build_signal_table(signal_panel),
        contract_to_tenor=tenor_map,
        config=cfg,
    )
    strategy = QueryStrategy(
        name="pca_momentum_q12stirt",
        triggers=[Trigger(trigger_requirements=_AlwaysOnMomentumRequirements(), actions=[action])],
    )
    backtest = QueryDrivenBacktest(
        time_grid=TimeGrid(list(signal_panel.index.to_pydatetime())),
        strategy=strategy,
        mdp=mdp,
        show_progress=show_progress,
        progress_desc="PCA MOMENTUM QUERY BT",
    )
    backtest.run()

    mtm_history = pd.Series(backtest.mtm_history).sort_index()
    pnl_history = mtm_history.diff().fillna(mtm_history)
    order_frame = pd.DataFrame(
        [
            {
                "timestamp": order.timestamp,
                "contract": (order.meta or {}).get("contract"),
                "position_id": (order.meta or {}).get("position_id"),
                "signal_direction": (order.meta or {}).get("signal_direction"),
                "order_type": type(order).__name__,
            }
            for order in backtest.portfolio.orders_log
        ]
    )
    annualization = _annualization_factor(mtm_history.index)
    metrics = _compute_backtest_metrics(
        pnl_series=pnl_history,
        cumulative_pnl=mtm_history,
        trade_sides=float(len(order_frame)),
        annualization_factor=annualization,
    )

    return PCAMomentumQueryBacktestResult(
        config=cfg,
        signal_panel=signal_panel,
        backtest=backtest,
        mtm_history=mtm_history,
        pnl_history=pnl_history,
        order_frame=order_frame,
        metrics=metrics,
    )


class _AlwaysOnMomentumRequirements(TriggerRequirements):
    calc_type = "pca_momentum"

    def has_triggered(self, state, backtest=None):
        return TriggerInfo(True, info={})


@dataclass
class _PCAMomentumSignalAction:
    signal_table: dict[pd.Timestamp, dict[str, int]]
    contract_to_tenor: Mapping[str, str]
    config: PCAMomentumConfig
    _trade_seq: int = field(default=0, init=False)

    def __call__(self, *, now, backtest, info) -> list[Any]:
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapValue import IRSwapValue

        _ = info
        desired_row = _lookup_signal_row(self.signal_table, now)
        if desired_row is None:
            return []

        open_positions = {
            str(position.meta.get("contract")): position
            for position in backtest.portfolio.iter_positions()
            if (position.meta or {}).get("contract") is not None
        }
        orders: list[Any] = []

        for contract, desired_signal in desired_row.items():
            tenor = self.contract_to_tenor.get(contract)
            if tenor is None:
                continue

            existing = open_positions.get(contract)
            current_signal = 0 if existing is None else int(existing.meta.get("signal_direction", 0))
            if current_signal == desired_signal:
                continue

            if existing is not None:
                existing_position_id = str(existing.meta.get("position_id"))
                orders.append(
                    UnwindOrder(
                        timestamp=now,
                        selector=lambda position, position_id=existing_position_id: str(position.meta.get("position_id")) == position_id,
                        meta={"strategy": "pca_momentum", "contract": contract, "position_id": existing_position_id},
                    )
                )

            if desired_signal == 0:
                continue

            self._trade_seq += 1
            position_id = f"{contract}|{pd.Timestamp(now).isoformat()}|{self._trade_seq}"
            orders.append(
                QueryOrder(
                    timestamp=now,
                    query=IRSwapQuery(
                        curve=self.config.curve,
                        tenor=tenor,
                        value=IRSwapValue.NPV,
                        structure_kwargs={"bpv": float(self.config.trade_bpv) * float(desired_signal)},
                        tags=(f"pca_momentum_{contract}",),
                    ),
                    meta={
                        "strategy": "pca_momentum",
                        "contract": contract,
                        "tenor": tenor,
                        "position_id": position_id,
                        "signal_direction": int(desired_signal),
                        "tags": [f"pca_momentum_{contract}"],
                    },
                )
            )

        return orders


def _lookup_signal_row(
    signal_table: Mapping[pd.Timestamp, dict[str, int]],
    timestamp: Any,
) -> Optional[dict[str, int]]:
    ts = pd.Timestamp(timestamp)
    direct = signal_table.get(ts)
    if direct is not None:
        return direct

    if ts.tzinfo is not None:
        naive = ts.tz_localize(None)
        direct = signal_table.get(naive)
        if direct is not None:
            return direct

    for key, value in signal_table.items():
        key_ts = pd.Timestamp(key)
        if key_ts == ts:
            return value
        if key_ts.tzinfo is not None and ts.tzinfo is None and key_ts.tz_localize(None) == ts:
            return value
        if key_ts.tzinfo is None and ts.tzinfo is not None and key_ts == ts.tz_localize(None):
            return value

    return None


def _coerce_signal(value: Any) -> int:
    if pd.isna(value):
        return 0
    numeric = int(np.sign(float(value)))
    if numeric > 0:
        return 1
    if numeric < 0:
        return -1
    return 0


def _annualization_factor(index: pd.Index) -> float:
    if len(index) == 0:
        return 252.0

    session_labels = pd.Series([_session_date(ts) for ts in index], index=index)
    counts = session_labels.groupby(session_labels).size()
    bars_per_session = float(counts.median()) if not counts.empty else 1.0
    return max(1.0, bars_per_session) * 252.0


def _compute_backtest_metrics(
    *,
    pnl_series: pd.Series,
    cumulative_pnl: pd.Series,
    trade_sides: float,
    annualization_factor: float,
) -> dict[str, float]:
    pnl = pnl_series.fillna(0.0)
    cumulative = cumulative_pnl.ffill().fillna(0.0)
    std = float(pnl.std())
    sharpe = float(pnl.mean() / std * np.sqrt(annualization_factor)) if std > 0.0 else 0.0
    drawdown = cumulative - cumulative.cummax()
    return {
        "total_pnl": float(cumulative.iloc[-1]) if len(cumulative) else 0.0,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
        "trade_sides": float(trade_sides),
    }


def _session_date(timestamp: Any) -> dt.date:
    stamp = pd.Timestamp(timestamp)
    if stamp.tzinfo is None:
        return stamp.date()
    chi_stamp = stamp.tz_convert("America/Chicago")
    if chi_stamp.hour >= 17:
        return (chi_stamp + pd.Timedelta(days=1)).date()
    return chi_stamp.date()

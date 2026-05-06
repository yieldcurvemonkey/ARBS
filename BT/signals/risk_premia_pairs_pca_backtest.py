"""Risk-premia-by-pairs PCA RV backtest adapter.

This module implements the Part IX bridge from cross-asset pair selection to
rates RV:

* PCA dislocation alpha on a panel of swap spreads, butterflies, or related
  rates instruments.
* Phase-1 idea selection with realized Sharpe gates.
* Phase-2 shrinkage-covariance sizing with L2 regularization back to the
  Phase-1 weights.
* A separate volatility overlay.
* Normal QueryDrivenBacktest order flow, so open positions are marked daily by
  the product handlers.

The module intentionally consumes a pre-built signal panel. For swap-spread
research, build that panel with IRSwapSpreadsMDP/TimeseriesBuilder and supply a
query_factory that maps idea ids to executable IRS/FRB packages.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from BT.event import TriggerInfo
from BT.query_actions import BuiltQuery
from BT.query_order import QueryOrder, UnwindOrder
from BT.triggers import Trigger, TriggerRequirements
from Query.Base.BaseQuery import BaseQuery

logger = logging.getLogger(__name__)

QueryFactory = Callable[["RiskPremiaPCASignal"], Union[BaseQuery, BuiltQuery, Iterable[Union[BaseQuery, BuiltQuery]]]]


@dataclass
class RiskPremiaPairsPCAConfig:
    """Configuration for the Part IX PCA/pairs query backtest."""

    curve: str = "USD-SOFR-1D"

    # PCA dislocation layer.
    pca_window_days: int = 260
    pca_components: int = 3
    residual_z_entry: float = 1.5
    residual_z_exit: float = 0.25
    residual_z_stop: float = 3.0

    # Phase-1 selection.
    phase1_lookback_days: int = 63
    phase1_min_realized_sharpe: float = 0.0
    require_momentum_confirmation: bool = False
    require_positioning_confirmation: bool = False

    # Phase-2 construction.
    covariance_lookback_days: int = 63
    risk_aversion: float = 1.0
    l2_to_phase1: float = 10.0
    max_abs_weight: float = 0.35
    min_abs_target_weight: float = 0.02
    gross_leverage: float = 1.0

    # Risk overlay.
    target_annual_vol: Optional[float] = None
    min_overlay_scale_to_trade: float = 0.05

    # Trade lifecycle and sizing.
    trade_bpv: float = 100_000.0
    max_concurrent_positions: int = 10
    max_holding_days: int = 22
    no_duplicate_ideas: bool = True
    exit_when_signal_missing: bool = False
    round_trip_cost_bp: float = 0.0


@dataclass(frozen=True)
class RiskPremiaPCASignal:
    """One executable PCA dislocation signal for a date."""

    idea_id: str
    timestamp: pd.Timestamp
    residual: float
    zscore: float
    direction: int
    phase1_sharpe: float
    phase1_weight: float
    target_weight: float
    overlay_scale: float
    expected_edge_bp: float
    covariance_vol: float
    rank_score: float
    diagnostics: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskPremiaPCASnapshot:
    """Signal table entry for one rebalance date."""

    timestamp: pd.Timestamp
    signals: Tuple[RiskPremiaPCASignal, ...]
    overlay_scale: float
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def by_idea(self) -> Dict[str, RiskPremiaPCASignal]:
        return {s.idea_id: s for s in self.signals}


@dataclass
class RiskPremiaPairsPCABacktestResult:
    """Output from the query-driven Part IX backtest."""

    query_backtest: Any
    signal_table: Dict[pd.Timestamp, RiskPremiaPCASnapshot]
    daily_pnl: pd.Series
    daily_pnl_ccy: pd.Series
    cumulative_pnl: pd.Series
    cumulative_pnl_ccy: pd.Series
    drawdown: pd.Series
    trades: pd.DataFrame
    metrics: Dict[str, float]


def _as_timestamp_index(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    return out.apply(pd.to_numeric, errors="coerce")


def _safe_std(values: pd.Series) -> float:
    std = float(values.std(ddof=1)) if len(values.dropna()) > 1 else np.nan
    return std if np.isfinite(std) and std > 0.0 else np.nan


def _realized_sharpe(returns: pd.Series, direction: int) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if len(clean) < 2:
        return np.nan
    directed = float(direction) * clean
    std = _safe_std(directed)
    if not np.isfinite(std):
        return np.nan
    return float(directed.mean() / std * np.sqrt(252.0))


def _pca_residual_snapshot(window: pd.DataFrame, n_components: int) -> Tuple[pd.Series, pd.Series, Dict[str, Any]]:
    clean = window.dropna(axis=1, how="any")
    if clean.shape[0] < 5 or clean.shape[1] < 2:
        return pd.Series(dtype=float), pd.Series(dtype=float), {"reason": "insufficient_pca_window"}

    k = max(1, min(int(n_components), clean.shape[1] - 1, clean.shape[0] - 1))
    x = clean.to_numpy(dtype=float)
    mean = x.mean(axis=0)
    xc = x - mean

    cov = np.cov(xc, rowvar=False)
    evals, evecs = np.linalg.eigh(cov)
    order = np.argsort(evals)[::-1]
    evals = evals[order]
    evecs = evecs[:, order]
    loadings = evecs[:, :k]
    recon = mean + (xc @ loadings) @ loadings.T
    residuals = x - recon

    stats_resid = residuals[:-1] if residuals.shape[0] > 5 else residuals
    resid_mean = stats_resid.mean(axis=0)
    resid_std = stats_resid.std(axis=0, ddof=1)
    resid_std = np.where(resid_std > 0.0, resid_std, np.nan)

    current = residuals[-1]
    zscores = (current - resid_mean) / resid_std
    diagnostics = {
        "n_components": k,
        "explained_variance_ratio": (evals[:k] / evals.sum()).tolist() if float(evals.sum()) > 0.0 else [],
        "pca_columns": list(clean.columns),
    }
    return (
        pd.Series(current, index=clean.columns, dtype=float),
        pd.Series(zscores, index=clean.columns, dtype=float),
        diagnostics,
    )


def _ledoit_wolf_cov(returns: pd.DataFrame) -> pd.DataFrame:
    clean = returns.dropna(axis=1, how="any")
    if clean.shape[1] == 0:
        return pd.DataFrame()
    if clean.shape[0] < 3 or clean.shape[1] == 1:
        cov = clean.cov()
        return cov.fillna(0.0)

    try:
        from sklearn.covariance import LedoitWolf

        lw = LedoitWolf().fit(clean.to_numpy(dtype=float))
        return pd.DataFrame(lw.covariance_, index=clean.columns, columns=clean.columns)
    except Exception:
        logger.debug("LedoitWolf covariance failed; falling back to diagonal shrinkage", exc_info=True)
        sample = clean.cov().fillna(0.0)
        avg_var = float(np.trace(sample.to_numpy(dtype=float)) / max(sample.shape[0], 1))
        target = pd.DataFrame(np.eye(sample.shape[0]) * avg_var, index=sample.index, columns=sample.columns)
        return 0.5 * sample + 0.5 * target


def _normalize_clip_weights(weights: pd.Series, config: RiskPremiaPairsPCAConfig) -> pd.Series:
    w = weights.replace([np.inf, -np.inf], np.nan).dropna().astype(float)
    if w.empty:
        return w
    gross = float(w.abs().sum())
    if gross <= 0.0:
        return w * 0.0
    w = w / gross * float(config.gross_leverage)
    if config.max_abs_weight is not None and float(config.max_abs_weight) > 0.0:
        w = w.clip(lower=-float(config.max_abs_weight), upper=float(config.max_abs_weight))
    return w


def _phase2_weights(
    *,
    candidates: pd.DataFrame,
    returns_window: pd.DataFrame,
    config: RiskPremiaPairsPCAConfig,
) -> Tuple[pd.Series, float, float]:
    if candidates.empty:
        return pd.Series(dtype=float), 1.0, 0.0

    ids = list(candidates.index)
    prior = candidates["phase1_weight"].astype(float)
    prior = _normalize_clip_weights(prior, config)
    if prior.empty:
        return pd.Series(dtype=float), 1.0, 0.0

    ids = [i for i in ids if i in prior.index]
    cov = _ledoit_wolf_cov(returns_window.reindex(columns=ids))
    ids = [i for i in ids if i in cov.index and i in prior.index]
    if not ids:
        return pd.Series(dtype=float), 1.0, 0.0

    cov_m = cov.loc[ids, ids].to_numpy(dtype=float)
    alpha = candidates.loc[ids, "alpha"].to_numpy(dtype=float)
    prior_v = prior.loc[ids].to_numpy(dtype=float)

    ridge = float(config.l2_to_phase1)
    lhs = float(config.risk_aversion) * cov_m + ridge * np.eye(len(ids))
    rhs = alpha + ridge * prior_v
    try:
        raw = np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        raw = np.linalg.pinv(lhs) @ rhs

    # Keep optimizer from flipping the Phase-1 trade thesis.
    signs = np.sign(prior_v)
    raw = signs * np.maximum(signs * raw, 0.0)
    weights = _normalize_clip_weights(pd.Series(raw, index=ids, dtype=float), config)

    annual_vol = 0.0
    if not weights.empty:
        wv = weights.reindex(ids).fillna(0.0).to_numpy(dtype=float)
        daily_var = float(wv @ cov_m @ wv)
        annual_vol = float(np.sqrt(max(daily_var, 0.0)) * np.sqrt(252.0))

    overlay_scale = 1.0
    if config.target_annual_vol is not None and annual_vol > 0.0:
        overlay_scale = min(1.0, float(config.target_annual_vol) / annual_vol)
    weights = weights * overlay_scale
    return weights, float(overlay_scale), annual_vol


def build_risk_premia_pca_signal_table(
    panel: pd.DataFrame,
    config: RiskPremiaPairsPCAConfig,
    *,
    returns_panel: Optional[pd.DataFrame] = None,
    momentum_panel: Optional[pd.DataFrame] = None,
    positioning_panel: Optional[pd.DataFrame] = None,
) -> Dict[pd.Timestamp, RiskPremiaPCASnapshot]:
    """Build daily PCA-dislocation signals for the query backtest.

    Parameters
    ----------
    panel
        Date x idea-id levels. For swap-spread RV this is usually a panel of
        MMSS/SPREADOVER/ASW bps from IRSwapSpreadsMDP.
    returns_panel
        Date x idea-id daily returns/PnL proxies used for Sharpe and covariance.
        Defaults to ``panel.diff()``.
    momentum_panel / positioning_panel
        Optional confirmation panels. When the corresponding config flag is
        enabled, ``direction * value`` must be positive.
    """
    levels = _as_timestamp_index(panel)
    returns = _as_timestamp_index(returns_panel) if returns_panel is not None else levels.diff()
    momentum = _as_timestamp_index(momentum_panel) if momentum_panel is not None else None
    positioning = _as_timestamp_index(positioning_panel) if positioning_panel is not None else None

    table: Dict[pd.Timestamp, RiskPremiaPCASnapshot] = {}
    min_history = max(5, min(int(config.pca_window_days), len(levels)))

    for loc in range(min_history - 1, len(levels)):
        ts = pd.Timestamp(levels.index[loc])
        pca_window = levels.iloc[max(0, loc - int(config.pca_window_days) + 1) : loc + 1]
        residuals, zscores, pca_diag = _pca_residual_snapshot(pca_window, config.pca_components)
        if residuals.empty:
            table[ts] = RiskPremiaPCASnapshot(ts, tuple(), 1.0, pca_diag)
            continue

        ret_window = returns.iloc[max(0, loc - int(config.phase1_lookback_days) + 1) : loc + 1]
        cov_window = returns.iloc[max(0, loc - int(config.covariance_lookback_days) + 1) : loc + 1]

        rows: List[Dict[str, Any]] = []
        for idea_id, z in zscores.dropna().items():
            z = float(z)
            if not np.isfinite(z) or abs(z) < float(config.residual_z_entry):
                continue

            direction = -1 if z > 0.0 else 1
            if config.require_momentum_confirmation and momentum is not None:
                mom_val = momentum.get(idea_id, pd.Series(dtype=float)).get(ts, np.nan)
                if pd.isna(mom_val) or direction * float(mom_val) <= 0.0:
                    continue
            if config.require_positioning_confirmation and positioning is not None:
                pos_val = positioning.get(idea_id, pd.Series(dtype=float)).get(ts, np.nan)
                if pd.isna(pos_val) or direction * float(pos_val) <= 0.0:
                    continue

            sharpe = _realized_sharpe(ret_window.get(idea_id, pd.Series(dtype=float)), direction)
            if pd.isna(sharpe) or float(sharpe) < float(config.phase1_min_realized_sharpe):
                continue

            score = max(abs(z) - float(config.residual_z_entry), 0.0) + 1e-12
            score *= max(float(sharpe), 0.0) + 1.0
            rows.append(
                {
                    "idea_id": idea_id,
                    "residual": float(residuals.get(idea_id, np.nan)),
                    "zscore": z,
                    "direction": direction,
                    "phase1_sharpe": float(sharpe),
                    "rank_score": float(score),
                    "alpha": direction * float(score),
                }
            )

        if not rows:
            table[ts] = RiskPremiaPCASnapshot(ts, tuple(), 1.0, pca_diag)
            continue

        candidates = pd.DataFrame(rows).set_index("idea_id")
        phase1 = candidates["direction"] * candidates["rank_score"]
        candidates["phase1_weight"] = _normalize_clip_weights(phase1, config)
        target_weights, overlay_scale, annual_vol = _phase2_weights(
            candidates=candidates,
            returns_window=cov_window,
            config=config,
        )

        signals: List[RiskPremiaPCASignal] = []
        for idea_id, weight in target_weights.items():
            if abs(float(weight)) < float(config.min_abs_target_weight):
                continue
            row = candidates.loc[idea_id]
            signals.append(
                RiskPremiaPCASignal(
                    idea_id=str(idea_id),
                    timestamp=ts,
                    residual=float(row["residual"]),
                    zscore=float(row["zscore"]),
                    direction=int(row["direction"]),
                    phase1_sharpe=float(row["phase1_sharpe"]),
                    phase1_weight=float(row["phase1_weight"]),
                    target_weight=float(weight),
                    overlay_scale=float(overlay_scale),
                    expected_edge_bp=abs(float(row["residual"])),
                    covariance_vol=float(annual_vol),
                    rank_score=float(row["rank_score"]),
                    diagnostics=dict(pca_diag),
                )
            )

        signals.sort(key=lambda s: abs(s.target_weight), reverse=True)
        table[ts] = RiskPremiaPCASnapshot(
            timestamp=ts,
            signals=tuple(signals),
            overlay_scale=float(overlay_scale),
            diagnostics={**pca_diag, "annual_vol": annual_vol},
        )

    return table


def _match_snapshot(
    signal_table: Mapping[pd.Timestamp, RiskPremiaPCASnapshot],
    state_dt: Any,
) -> Optional[RiskPremiaPCASnapshot]:
    ts = pd.Timestamp(state_dt)
    direct = signal_table.get(ts)
    if direct is not None:
        return direct
    ts_norm = ts.normalize()
    direct = signal_table.get(ts_norm)
    if direct is not None:
        return direct
    target_date = ts.date()
    for key, snapshot in signal_table.items():
        if pd.Timestamp(key).date() == target_date:
            return snapshot
    return None


def _normalize_query_payload(payload: Any) -> List[BuiltQuery]:
    if payload is None:
        return []
    if isinstance(payload, BuiltQuery):
        return [payload]
    if isinstance(payload, BaseQuery):
        return [BuiltQuery(query=payload)]
    if isinstance(payload, Iterable) and not isinstance(payload, (str, bytes, dict)):
        out: List[BuiltQuery] = []
        for item in payload:
            out.extend(_normalize_query_payload(item))
        return out
    raise TypeError(f"Unsupported query_factory output type: {type(payload)!r}")


def make_irs_query_factory(
    *,
    curve: str = "USD-SOFR-1D",
    default_bpv: float = 100_000.0,
) -> QueryFactory:
    """Create a query factory for idea ids like ``2Y``, ``2Y/10Y``, or ``2Y/5Y/10Y``."""

    def _factory(signal: RiskPremiaPCASignal) -> BaseQuery:
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapStructure import IRSwapStructure
        from Query.IRSwaps.IRSwapValue import IRSwapValue

        parts = [p.strip() for p in str(signal.idea_id).split("/") if p.strip()]
        signed_bpv = float(default_bpv) * float(signal.target_weight)
        if len(parts) == 1:
            return IRSwapQuery(
                structure=IRSwapStructure.OUTRIGHT,
                value=IRSwapValue.NPV,
                curve=curve,
                tenor=parts[0],
                structure_kwargs={"bpv": signed_bpv},
                tags=("risk_premia_pairs_pca", signal.idea_id),
            )
        if len(parts) == 2:
            return IRSwapQuery(
                structure=IRSwapStructure.CURVE,
                value=IRSwapValue.NPV,
                curve=curve,
                structure_kwargs={
                    "front_tenor": parts[0],
                    "back_tenor": parts[1],
                    "bpv": signed_bpv,
                },
                tags=("risk_premia_pairs_pca", signal.idea_id),
            )
        if len(parts) == 3:
            return IRSwapQuery(
                structure=IRSwapStructure.FLY,
                value=IRSwapValue.NPV,
                curve=curve,
                structure_kwargs={
                    "front_tenor": parts[0],
                    "belly_tenor": parts[1],
                    "back_tenor": parts[2],
                    "bpv": signed_bpv,
                },
                tags=("risk_premia_pairs_pca", signal.idea_id),
            )
        raise ValueError(f"Cannot parse IRS idea id {signal.idea_id!r}; expected 1, 2, or 3 slash-separated tenors.")

    return _factory


class _RiskPremiaPCAAlwaysReqs(TriggerRequirements):
    calc_type = "risk_premia_pairs_pca"

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        return TriggerInfo(True, {})


@dataclass
class RiskPremiaPCASignalAction:
    """Combined entry/exit action for QueryDrivenBacktest."""

    signal_table: Mapping[pd.Timestamp, RiskPremiaPCASnapshot]
    query_factory: QueryFactory
    config: RiskPremiaPairsPCAConfig
    risk: Optional[str] = None
    _trade_seq: int = field(default=0, init=False)

    @staticmethod
    def _selector(position_id: str):
        return lambda p, position_id=position_id: p.meta.get("rpp_position_id") == position_id

    @staticmethod
    def _business_days(opened: Any, now: Any) -> int:
        try:
            return max(0, len(pd.bdate_range(pd.Timestamp(opened).date(), pd.Timestamp(now).date())) - 1)
        except Exception:
            return max(0, (pd.Timestamp(now) - pd.Timestamp(opened)).days)

    def _round_trip_fee_from_position(self, pos: Any) -> float:
        meta = pos.meta or {}
        target_weight = float(meta.get("target_weight", 0.0) or 0.0)
        return abs(target_weight) * float(self.config.trade_bpv) * float(self.config.round_trip_cost_bp)

    def _exit_reason(self, pos: Any, now: Any, snapshot: Optional[RiskPremiaPCASnapshot]) -> Optional[str]:
        meta = pos.meta or {}
        idea_id = meta.get("rpp_idea_id")
        if not idea_id:
            return None

        if self._business_days(pos.opened, now) >= int(self.config.max_holding_days):
            return "max_hold"

        if snapshot is None:
            return None
        if snapshot.overlay_scale <= float(self.config.min_overlay_scale_to_trade):
            return "risk_overlay"

        signal = snapshot.by_idea().get(idea_id)
        if signal is None:
            return "signal_missing" if self.config.exit_when_signal_missing else None

        entry_z = float(meta.get("entry_zscore", np.nan))
        current_z = float(signal.zscore)
        if abs(current_z) <= float(self.config.residual_z_exit):
            return "mean_reversion"
        if np.isfinite(entry_z) and np.sign(current_z) != np.sign(entry_z):
            return "mean_reversion"
        if (
            np.isfinite(entry_z)
            and np.sign(current_z) == np.sign(entry_z)
            and abs(current_z) >= float(self.config.residual_z_stop)
            and abs(current_z) > abs(entry_z)
        ):
            return "stop_loss"
        return None

    def __call__(self, *, now, backtest, info) -> List[Union[QueryOrder, UnwindOrder]]:
        snapshot = _match_snapshot(self.signal_table, now)
        orders: List[Union[QueryOrder, UnwindOrder]] = []

        current_positions = [
            p for p in backtest.portfolio.iter_positions()
            if (p.meta or {}).get("rpp_position_id") is not None
        ]
        exiting_position_ids: set[str] = set()
        for pos in current_positions:
            position_id = (pos.meta or {}).get("rpp_position_id")
            if position_id in exiting_position_ids:
                continue
            reason = self._exit_reason(pos, now, snapshot)
            if reason is None:
                continue
            exiting_position_ids.add(position_id)
            orders.append(
                UnwindOrder(
                    timestamp=now,
                    selector=self._selector(position_id),
                    meta={
                        "action": "risk_premia_pairs_pca_exit",
                        "reason": reason,
                        "fee": self._round_trip_fee_from_position(pos),
                    },
                )
            )

        if snapshot is None or snapshot.overlay_scale <= float(self.config.min_overlay_scale_to_trade):
            return orders

        open_after_exit = [
            p for p in current_positions
            if (p.meta or {}).get("rpp_position_id") not in exiting_position_ids
        ]
        open_ideas = {(p.meta or {}).get("rpp_idea_id") for p in open_after_exit}
        available = max(0, int(self.config.max_concurrent_positions) - len({(p.meta or {}).get("rpp_position_id") for p in open_after_exit}))
        if available <= 0:
            return orders

        signals = [
            s for s in snapshot.signals
            if abs(float(s.zscore)) >= float(self.config.residual_z_entry)
            and abs(float(s.target_weight)) >= float(self.config.min_abs_target_weight)
        ]
        if self.config.no_duplicate_ideas:
            signals = [s for s in signals if s.idea_id not in open_ideas]
        signals.sort(key=lambda s: abs(s.target_weight), reverse=True)
        signals = signals[:available]

        for signal in signals:
            built_queries = _normalize_query_payload(self.query_factory(signal))
            if not built_queries:
                continue

            self._trade_seq += 1
            position_id = f"{signal.idea_id}|{pd.Timestamp(now).date().isoformat()}|{self._trade_seq}"
            base_meta = {
                "strategy": "risk_premia_pairs_pca",
                "rpp_position_id": position_id,
                "rpp_idea_id": signal.idea_id,
                "entry_signal_date": pd.Timestamp(now).normalize(),
                "entry_residual": signal.residual,
                "entry_zscore": signal.zscore,
                "entry_phase1_sharpe": signal.phase1_sharpe,
                "phase1_weight": signal.phase1_weight,
                "target_weight": signal.target_weight,
                "overlay_scale": signal.overlay_scale,
                "direction": signal.direction,
            }
            for idx, built in enumerate(built_queries):
                leg_meta = dict(base_meta)
                leg_meta["rpp_leg_index"] = idx
                leg_meta.update(dict(built.meta or {}))
                orders.append(QueryOrder(timestamp=now, query=built.query, meta=leg_meta))

        return orders


class RiskPremiaPCATrigger(Trigger):
    """Always-on trigger whose action handles Part IX entry/exit decisions."""

    def __init__(
        self,
        signal_table: Mapping[pd.Timestamp, RiskPremiaPCASnapshot],
        query_factory: QueryFactory,
        config: RiskPremiaPairsPCAConfig,
    ):
        super().__init__(
            trigger_requirements=_RiskPremiaPCAAlwaysReqs(),
            actions=[RiskPremiaPCASignalAction(signal_table, query_factory, config)],
        )


def _compute_metrics(trades: pd.DataFrame, daily_pnl: pd.Series) -> Dict[str, float]:
    clean = daily_pnl.dropna()
    total = float(clean.sum()) if len(clean) else 0.0
    std = float(clean.std(ddof=1)) if len(clean) > 1 else 0.0
    sharpe = float(clean.mean() / std * np.sqrt(252.0)) if std > 0.0 else 0.0
    n_trades = int(len(trades))
    hit_rate = float((trades["realized_pnl"] > 0.0).mean()) if n_trades else 0.0
    drawdown = clean.cumsum() - clean.cumsum().cummax()
    return {
        "total_pnl": total,
        "n_trades": n_trades,
        "hit_rate": hit_rate,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
        "avg_holding_days": float(trades["holding_days"].mean()) if n_trades and "holding_days" in trades else 0.0,
    }


def _finalize_trades(backtest: Any, last_dt: pd.Timestamp) -> pd.DataFrame:
    grouped: Dict[str, Dict[str, Any]] = {}

    def _add_record(record: Dict[str, Any]) -> None:
        key = str(record.get("rpp_position_id") or "")
        if not key:
            return
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = dict(record)
            return
        existing["realized_pnl"] = float(existing.get("realized_pnl", 0.0) or 0.0) + float(record.get("realized_pnl", 0.0) or 0.0)
        existing["holding_days"] = max(float(existing.get("holding_days", 0.0) or 0.0), float(record.get("holding_days", 0.0) or 0.0))
        if pd.Timestamp(record.get("exit_date")) > pd.Timestamp(existing.get("exit_date")):
            existing["exit_date"] = record.get("exit_date")

    for rec in getattr(backtest.portfolio, "closed_positions_log", []):
        pos = rec.get("position")
        meta = getattr(pos, "meta", {}) or rec.get("position_meta", {}) or {}
        if meta.get("rpp_position_id") is None:
            continue
        _add_record(
            {
                "rpp_position_id": meta.get("rpp_position_id"),
                "idea_id": meta.get("rpp_idea_id"),
                "entry_date": rec.get("opened_at"),
                "exit_date": rec.get("closed_at"),
                "exit_reason": (rec.get("exit_meta") or {}).get("reason", "unwind"),
                "realized_pnl": rec.get("realized_pnl", 0.0),
                "entry_zscore": meta.get("entry_zscore"),
                "target_weight": meta.get("target_weight"),
                "holding_days": rec.get("holding_period_days"),
            }
        )

    for pos in backtest.portfolio.iter_positions():
        meta = pos.meta or {}
        if meta.get("rpp_position_id") is None:
            continue
        try:
            current_value = float(backtest._position_value(pos, last_dt.to_pydatetime()))
        except Exception:
            current_value = np.nan
        _add_record(
            {
                "rpp_position_id": meta.get("rpp_position_id"),
                "idea_id": meta.get("rpp_idea_id"),
                "entry_date": pos.opened,
                "exit_date": last_dt,
                "exit_reason": "end_of_backtest",
                "realized_pnl": current_value,
                "entry_zscore": meta.get("entry_zscore"),
                "target_weight": meta.get("target_weight"),
                "holding_days": RiskPremiaPCASignalAction._business_days(pos.opened, last_dt),
            }
        )

    records = list(grouped.values())
    if not records:
        return pd.DataFrame(
            columns=["rpp_position_id", "idea_id", "entry_date", "exit_date", "exit_reason", "realized_pnl", "holding_days"]
        )
    return pd.DataFrame(records).sort_values(["entry_date", "idea_id"]).reset_index(drop=True)


def run_risk_premia_pairs_pca_backtest(
    *,
    signal_table: Mapping[pd.Timestamp, RiskPremiaPCASnapshot],
    mdp: Any = None,
    mdps: Optional[Mapping[str, Any]] = None,
    query_factory: Optional[QueryFactory] = None,
    config: Optional[RiskPremiaPairsPCAConfig] = None,
    show_progress: bool = False,
) -> RiskPremiaPairsPCABacktestResult:
    """Run the Part IX query-driven backtest with daily MTM."""
    from BT.data_handler import TimeGrid
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy

    cfg = config or RiskPremiaPairsPCAConfig()
    if not signal_table:
        empty = pd.Series(dtype=float)
        empty_df = pd.DataFrame(
            columns=["rpp_position_id", "idea_id", "entry_date", "exit_date", "exit_reason", "realized_pnl", "holding_days"]
        )
        return RiskPremiaPairsPCABacktestResult(
            query_backtest=None,
            signal_table={},
            daily_pnl=empty,
            daily_pnl_ccy=empty,
            cumulative_pnl=empty,
            cumulative_pnl_ccy=empty,
            drawdown=empty,
            trades=empty_df,
            metrics=_compute_metrics(empty_df, empty),
        )

    q_factory = query_factory or make_irs_query_factory(curve=cfg.curve, default_bpv=cfg.trade_bpv)
    dates = sorted(pd.Timestamp(k).to_pydatetime() for k in signal_table.keys())

    trigger = RiskPremiaPCATrigger(signal_table, q_factory, cfg)
    strategy = QueryStrategy(
        name="risk_premia_pairs_pca",
        triggers=[trigger],
        mdps=mdps,
        default_mdp=mdp,
    )
    backtest = QueryDrivenBacktest(
        time_grid=TimeGrid(dates),
        strategy=strategy,
        mdp=mdp,
        show_progress=show_progress,
        progress_desc="RISK PREMIA PCA QUERY BACKTEST",
    )
    backtest.run()

    mtm_ccy = pd.Series(backtest.mtm_history).sort_index()
    daily_ccy = mtm_ccy.diff().fillna(mtm_ccy)
    normalizer = float(cfg.trade_bpv) if float(cfg.trade_bpv) else 1.0
    daily = daily_ccy / normalizer
    cumulative = daily.cumsum()
    drawdown = cumulative - cumulative.cummax()
    last_dt = pd.Timestamp(mtm_ccy.index[-1]).normalize() if len(mtm_ccy) else pd.Timestamp(dates[-1]).normalize()
    trades = _finalize_trades(backtest, last_dt)
    metrics = _compute_metrics(trades, daily)
    metrics["total_pnl_ccy"] = float(daily_ccy.sum()) if len(daily_ccy) else 0.0

    return RiskPremiaPairsPCABacktestResult(
        query_backtest=backtest,
        signal_table=dict(signal_table),
        daily_pnl=daily,
        daily_pnl_ccy=daily_ccy,
        cumulative_pnl=cumulative,
        cumulative_pnl_ccy=mtm_ccy,
        drawdown=drawdown,
        trades=trades,
        metrics=metrics,
    )


def build_irswap_spread_signal_panel(
    *,
    start: Union[dt.date, dt.datetime, str],
    end: Union[dt.date, dt.datetime, str],
    tenors: Sequence[str],
    curve: str = "USD-SOFR-1D",
    value: Any = None,
    spread_mdp: Any = None,
    mdps: Optional[Mapping[str, Any]] = None,
) -> pd.DataFrame:
    """Build a swap-spread level panel suitable for PCA dislocation signals."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from TB.TimeseriesBuilder import TimeseriesBuilder

    spread_value = value or IRSwapValue.MMSS
    queries = [IRSwapQuery(curve=curve, tenor=str(tenor), value=spread_value, name=str(tenor)) for tenor in tenors]
    routed_mdps = dict(mdps or {})
    if spread_mdp is not None:
        routed_mdps["IRSWAPSPREADS"] = spread_mdp

    df = TimeseriesBuilder().get_timeseries(
        start=start,
        end=end,
        queries=queries,
        mdps=routed_mdps or None,
    )
    out = pd.DataFrame(df)
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [str(c[-1]) for c in out.columns]
    rename = {}
    for tenor, col in zip(tenors, out.columns):
        rename[col] = str(tenor)
    return out.rename(columns=rename)

"""Comprehensive analytics and tearsheet rendering for QueryDrivenBacktest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

import numpy as np
import pandas as pd

from BT.query_engine import QueryDrivenBacktest
from BT.query_portfolio import ResolvedQueryPosition

_SIZE_PRIORITY: list[tuple[str, str]] = [
    ("bpv", "BPV"),
    ("trade_bpv", "Trade BPV"),
    ("belly_bpv", "Belly BPV"),
    ("notional", "Notional"),
    ("pv01", "PV01"),
    ("dv01", "DV01"),
    ("vega", "Vega"),
    ("delta", "Delta"),
    ("quantity", "Quantity"),
    ("size", "Size"),
    ("signal_direction", "Signal Units"),
]
_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class QueryBacktestAnalytics:
    backtest: QueryDrivenBacktest
    name: str
    capital_base: Optional[float]
    size_metric: Optional[str]
    step_equity: pd.Series
    step_pnl: pd.Series
    step_realized: pd.Series
    step_open_pnl: pd.Series
    step_returns: pd.Series
    session_equity: pd.Series
    session_pnl: pd.Series
    session_realized: pd.Series
    session_open_pnl: pd.Series
    session_returns: pd.Series
    session_drawdown: pd.Series
    rolling_sharpe: pd.Series
    rolling_vol: pd.Series
    position_counts: pd.DataFrame
    product_open_counts: pd.DataFrame
    size_exposure: pd.DataFrame
    trade_flow: pd.DataFrame
    snapshot_frame: pd.DataFrame
    closed_trades: pd.DataFrame
    open_positions: pd.DataFrame
    monthly_pnl: pd.DataFrame
    summary: dict[str, Any]
    summary_frame: pd.DataFrame
    product_summary: pd.DataFrame
    tag_summary: pd.DataFrame
    drawdown_episodes: pd.DataFrame
    top_trades: pd.DataFrame
    worst_trades: pd.DataFrame


@dataclass
class QueryBacktestTearSheet:
    analytics: QueryBacktestAnalytics

    @classmethod
    def from_backtest(
        cls,
        backtest: Any,
        *,
        capital_base: Optional[float] = None,
        rolling_window_sessions: int = 63,
        top_groups: int = 6,
        name: Optional[str] = None,
    ) -> "QueryBacktestTearSheet":
        return cls(
            build_query_backtest_analytics(
                backtest,
                capital_base=capital_base,
                rolling_window_sessions=rolling_window_sessions,
                top_groups=top_groups,
                name=name,
            )
        )

    def plot(self, *, backend: str = "matplotlib", **kwargs: Any) -> Any:
        backend_name = str(backend).lower().strip()
        if backend_name in {"matplotlib", "mpl", "plt"}:
            return self.plot_matplotlib(**kwargs)
        if backend_name in {"plotly", "interactive"}:
            return self.plot_plotly(**kwargs)
        raise ValueError("backend must be one of {'matplotlib', 'plotly'}.")

    def plot_matplotlib(self, *, figsize: tuple[float, float] = (22.0, 28.0)) -> Any:
        import matplotlib.pyplot as plt

        analytics = self.analytics
        fig = plt.figure(figsize=figsize, constrained_layout=True)
        gs = fig.add_gridspec(6, 2, height_ratios=[1.15, 1.0, 0.95, 1.0, 0.9, 0.9])

        summary_ax = fig.add_subplot(gs[0, :])
        _plot_summary_table_matplotlib(summary_ax, analytics)

        equity_ax = fig.add_subplot(gs[1, 0])
        _plot_equity_matplotlib(equity_ax, analytics)

        dd_ax = fig.add_subplot(gs[1, 1])
        _plot_drawdown_matplotlib(dd_ax, analytics)

        pnl_ax = fig.add_subplot(gs[2, 0])
        _plot_session_pnl_matplotlib(pnl_ax, analytics)

        rolling_ax = fig.add_subplot(gs[2, 1])
        _plot_rolling_metrics_matplotlib(rolling_ax, analytics)

        heatmap_ax = fig.add_subplot(gs[3, 0])
        _plot_monthly_heatmap_matplotlib(heatmap_ax, analytics)

        dist_ax = fig.add_subplot(gs[3, 1])
        _plot_distribution_matplotlib(dist_ax, analytics)

        position_ax = fig.add_subplot(gs[4, 0])
        _plot_position_and_flow_matplotlib(position_ax, analytics)

        exposure_ax = fig.add_subplot(gs[4, 1])
        _plot_exposure_or_product_counts_matplotlib(exposure_ax, analytics)

        product_ax = fig.add_subplot(gs[5, 0])
        _plot_group_bar_matplotlib(product_ax, analytics.product_summary, title="Product PnL Mix")

        trades_ax = fig.add_subplot(gs[5, 1])
        _plot_trade_scatter_or_tag_bar_matplotlib(trades_ax, analytics)

        fig.suptitle(f"{analytics.name} TearSheet", fontsize=18, fontweight="bold")
        return fig

    def plot_plotly(self, *, height: int = 2400, width: int = 1600) -> Any:
        from plotly.subplots import make_subplots

        analytics = self.analytics
        fig = make_subplots(
            rows=6,
            cols=2,
            vertical_spacing=0.055,
            horizontal_spacing=0.08,
            specs=[
                [{"type": "table", "colspan": 2}, None],
                [{"type": "xy"}, {"type": "xy"}],
                [{"type": "xy"}, {"type": "xy", "secondary_y": True}],
                [{"type": "heatmap"}, {"type": "xy"}],
                [{"type": "xy", "secondary_y": True}, {"type": "xy"}],
                [{"type": "xy"}, {"type": "xy"}],
            ],
            subplot_titles=[
                "",
                "Equity / Realized / Open",
                "Underwater",
                "Session PnL",
                "Rolling Sharpe / Vol",
                "Monthly Heatmap",
                "Session PnL Distribution",
                "Open Positions / Trade Sides",
                "Exposure / Product Counts",
                "Product PnL Mix",
                "Trade Scatter / Tag Mix",
            ],
        )

        _plot_summary_table_plotly(fig, analytics, row=1, col=1)
        _plot_equity_plotly(fig, analytics, row=2, col=1)
        _plot_drawdown_plotly(fig, analytics, row=2, col=2)
        _plot_session_pnl_plotly(fig, analytics, row=3, col=1)
        _plot_rolling_metrics_plotly(fig, analytics, row=3, col=2)
        _plot_monthly_heatmap_plotly(fig, analytics, row=4, col=1)
        _plot_distribution_plotly(fig, analytics, row=4, col=2)
        _plot_position_and_flow_plotly(fig, analytics, row=5, col=1)
        _plot_exposure_or_product_counts_plotly(fig, analytics, row=5, col=2)
        _plot_group_bar_plotly(fig, analytics.product_summary, title="Product PnL Mix", row=6, col=1)
        _plot_trade_scatter_or_tag_bar_plotly(fig, analytics, row=6, col=2)

        fig.update_layout(
            template="plotly_white",
            height=height,
            width=width,
            title=f"{analytics.name} TearSheet",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0),
            margin=dict(l=60, r=40, t=80, b=50),
        )
        return fig

    @property
    def summary_frame(self) -> pd.DataFrame:
        return self.analytics.summary_frame


def create_query_backtest_tearsheet(backtest: Any, **kwargs: Any) -> QueryBacktestTearSheet:
    return QueryBacktestTearSheet.from_backtest(backtest, **kwargs)


def plot_query_backtest_tearsheet(backtest: Any, *, backend: str = "matplotlib", **kwargs: Any) -> Any:
    return QueryBacktestTearSheet.from_backtest(backtest, **kwargs).plot(backend=backend)


def build_query_backtest_analytics(
    backtest: Any,
    *,
    capital_base: Optional[float] = None,
    rolling_window_sessions: int = 63,
    top_groups: int = 6,
    name: Optional[str] = None,
) -> QueryBacktestAnalytics:
    bt = _unwrap_backtest(backtest)
    if not getattr(bt, "mtm_history", None):
        raise ValueError("Backtest has no mtm_history. Run QueryDrivenBacktest.run() before building a tearsheet.")

    strategy_name = str(name or getattr(getattr(bt, "strategy", None), "name", None) or "query_backtest")
    step_equity = pd.Series(bt.mtm_history, dtype=float).sort_index()
    step_equity.index = pd.DatetimeIndex(step_equity.index)
    step_pnl = step_equity.diff().fillna(step_equity)

    realized_history = pd.Series(getattr(bt, "realized_pnl_history", {}), dtype=float).sort_index()
    if len(realized_history):
        realized_history.index = pd.DatetimeIndex(realized_history.index)
        step_realized = realized_history.reindex(step_equity.index).ffill().fillna(0.0)
    else:
        step_realized = pd.Series(0.0, index=step_equity.index, dtype=float)
    step_open_pnl = step_equity - step_realized
    step_returns = (
        pd.Series(step_pnl / float(capital_base), index=step_pnl.index, dtype=float)
        if capital_base not in (None, 0.0)
        else pd.Series(dtype=float)
    )

    session_labels = pd.Index([_session_timestamp(ts) for ts in step_equity.index], name="session")
    session_equity = step_equity.groupby(session_labels).last()
    session_realized = step_realized.groupby(session_labels).last()
    session_open_pnl = step_open_pnl.groupby(session_labels).last()
    session_equity.index = pd.DatetimeIndex(session_equity.index)
    session_realized.index = pd.DatetimeIndex(session_realized.index)
    session_open_pnl.index = pd.DatetimeIndex(session_open_pnl.index)
    session_pnl = session_equity.diff().fillna(session_equity)
    session_returns = (
        pd.Series(session_pnl / float(capital_base), index=session_pnl.index, dtype=float)
        if capital_base not in (None, 0.0)
        else pd.Series(dtype=float)
    )

    rolling_window = _resolve_rolling_window(len(session_pnl), rolling_window_sessions)
    rolling_sharpe = _rolling_sharpe(session_pnl, rolling_window)
    rolling_vol = session_pnl.rolling(rolling_window).std().mul(np.sqrt(252.0))
    session_drawdown = session_equity - session_equity.cummax()

    size_metric = _infer_preferred_size_metric(bt)
    closed_trades = _build_closed_trade_frame(bt, size_metric=size_metric)
    open_positions = _build_open_positions_frame(bt, size_metric=size_metric, last_timestamp=step_equity.index[-1])
    snapshot_frame = _build_snapshot_frame(bt, size_metric=size_metric)
    position_counts = _build_position_counts(snapshot_frame, step_equity.index)
    product_open_counts = _build_snapshot_group_counts(snapshot_frame, full_index=step_equity.index, group_col="product", top_n=top_groups)
    size_exposure = _build_size_exposure(snapshot_frame, full_index=step_equity.index)
    trade_flow = _build_trade_flow(bt, session_index=session_equity.index, closed_trades=closed_trades)
    monthly_pnl = _build_monthly_heatmap(session_pnl)
    product_summary = _build_group_summary(closed_trades, open_positions, group_col="product")
    tag_summary = _build_tag_summary(closed_trades, open_positions)
    drawdown_episodes = _drawdown_episodes(session_equity)
    summary = _build_summary(
        name=strategy_name,
        capital_base=capital_base,
        step_equity=step_equity,
        session_pnl=session_pnl,
        session_equity=session_equity,
        session_drawdown=session_drawdown,
        step_realized=step_realized,
        step_open_pnl=step_open_pnl,
        position_counts=position_counts,
        trade_flow=trade_flow,
        closed_trades=closed_trades,
        open_positions=open_positions,
    )
    summary_frame = _summary_frame(summary)

    top_trades = (
        closed_trades.sort_values("realized_pnl", ascending=False).head(10).reset_index(drop=True)
        if not closed_trades.empty
        else pd.DataFrame()
    )
    worst_trades = (
        closed_trades.sort_values("realized_pnl", ascending=True).head(10).reset_index(drop=True)
        if not closed_trades.empty
        else pd.DataFrame()
    )

    return QueryBacktestAnalytics(
        backtest=bt,
        name=strategy_name,
        capital_base=float(capital_base) if capital_base not in (None, 0.0) else None,
        size_metric=size_metric,
        step_equity=step_equity,
        step_pnl=step_pnl,
        step_realized=step_realized,
        step_open_pnl=step_open_pnl,
        step_returns=step_returns,
        session_equity=session_equity,
        session_pnl=session_pnl,
        session_realized=session_realized,
        session_open_pnl=session_open_pnl,
        session_returns=session_returns,
        session_drawdown=session_drawdown,
        rolling_sharpe=rolling_sharpe,
        rolling_vol=rolling_vol,
        position_counts=position_counts,
        product_open_counts=product_open_counts,
        size_exposure=size_exposure,
        trade_flow=trade_flow,
        snapshot_frame=snapshot_frame,
        closed_trades=closed_trades,
        open_positions=open_positions,
        monthly_pnl=monthly_pnl,
        summary=summary,
        summary_frame=summary_frame,
        product_summary=product_summary,
        tag_summary=tag_summary,
        drawdown_episodes=drawdown_episodes,
        top_trades=top_trades,
        worst_trades=worst_trades,
    )


def _unwrap_backtest(value: Any) -> QueryDrivenBacktest:
    if isinstance(value, QueryDrivenBacktest):
        return value
    for attr in ("backtest", "query_backtest", "_base"):
        candidate = getattr(value, attr, None)
        if isinstance(candidate, QueryDrivenBacktest):
            return candidate
    if hasattr(value, "mtm_history") and hasattr(value, "portfolio"):
        return value
    raise TypeError("Expected a QueryDrivenBacktest or an object that exposes one via .backtest / .query_backtest.")


def _resolve_rolling_window(length: int, requested: int) -> int:
    if length <= 1:
        return 1
    requested = max(2, int(requested))
    return min(requested, length)


def _rolling_sharpe(pnl: pd.Series, window: int) -> pd.Series:
    if window <= 1:
        return pd.Series(np.nan, index=pnl.index, dtype=float)
    rolling_mean = pnl.rolling(window).mean()
    rolling_std = pnl.rolling(window).std()
    ratio = rolling_mean.div(rolling_std.replace(0.0, np.nan))
    return ratio.mul(np.sqrt(252.0))


def _session_timestamp(timestamp: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(timestamp)
    if stamp.tzinfo is None:
        return pd.Timestamp(stamp.date())
    chicago = stamp.tz_convert("America/Chicago")
    if chicago.hour >= 17:
        chicago = chicago + pd.Timedelta(days=1)
    return pd.Timestamp(chicago.date())


def _is_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return np.isfinite(numeric)


def _preferred_size_value(query: Any, meta: Mapping[str, Any], preferred: Optional[str]) -> tuple[Optional[str], float]:
    structure_kwargs = dict(getattr(query, "structure_kwargs", {}) or {})
    meta_dict = dict(meta or {})

    def _lookup(key: str) -> Optional[float]:
        if key in structure_kwargs and _is_number(structure_kwargs[key]):
            return float(structure_kwargs[key])
        if key in meta_dict and _is_number(meta_dict[key]):
            return float(meta_dict[key])
        return None

    if preferred:
        preferred_value = _lookup(preferred)
        if preferred_value is not None:
            return preferred, preferred_value

    for key, _ in _SIZE_PRIORITY:
        value = _lookup(key)
        if value is not None:
            return key, value
    return None, float("nan")


def _infer_preferred_size_metric(backtest: Any) -> Optional[str]:
    positions: list[ResolvedQueryPosition] = []
    positions.extend(list(getattr(getattr(backtest, "portfolio", None), "iter_positions", lambda: ())()))
    for record in getattr(getattr(backtest, "portfolio", None), "closed_positions_log", []) or []:
        snapshot = record.get("position")
        if isinstance(snapshot, ResolvedQueryPosition):
            positions.append(snapshot)
    for snapshots in (getattr(backtest, "position_history", {}) or {}).values():
        positions.extend(list(snapshots))

    for key, _ in _SIZE_PRIORITY:
        for position in positions:
            query = getattr(position, "source_query", None)
            metric, _ = _preferred_size_value(query, getattr(position, "meta", {}), key)
            if metric == key:
                return key
    return None


def _query_label(query: Any) -> str:
    if query is None:
        return "unknown"
    if getattr(query, "name", None):
        return str(query.name)
    pieces: list[str] = []
    product = getattr(query, "product", None)
    if product:
        pieces.append(str(product))
    for attr in ("curve", "tenor", "contract", "ticker", "underlying", "expiry"):
        value = getattr(query, attr, None)
        if value not in (None, "", (), []):
            pieces.append(str(value))
    structure_id = getattr(query, "structure_id", None)
    if structure_id not in (None, "", (), []):
        pieces.append(str(structure_id))
    compact = " ".join(dict.fromkeys(pieces))
    if compact:
        return compact[:96]
    try:
        return str(query.signature())
    except Exception:
        return repr(query)


def _query_signature(query: Any) -> str:
    if query is None:
        return "unknown"
    try:
        return str(query.signature())
    except Exception:
        return _query_label(query)


def _collect_tags(query: Any, meta: Mapping[str, Any]) -> list[str]:
    tags: list[str] = []
    for source in (getattr(query, "tags", ()) or (), dict(meta or {}).get("tags", []) or []):
        values = [source] if isinstance(source, (str, bytes)) else list(source)
        for value in values:
            text = str(value)
            if text and text not in tags:
                tags.append(text)
    return tags


def _direction_hint(position: ResolvedQueryPosition, size_value: float) -> int:
    meta = dict(position.meta or {})
    if _is_number(meta.get("signal_direction")):
        direction = int(np.sign(float(meta["signal_direction"])))
        if direction != 0:
            return direction
    if np.isfinite(size_value) and size_value != 0.0:
        return int(np.sign(size_value))
    net_weight = float(np.sum(position.weights)) if getattr(position, "weights", None) else 0.0
    return int(np.sign(net_weight))


def _base_position_row(
    position: ResolvedQueryPosition,
    *,
    size_metric: Optional[str],
    timestamp: pd.Timestamp,
    position_index: int = 0,
) -> dict[str, Any]:
    query = position.source_query
    metric, size_value = _preferred_size_value(query, position.meta, size_metric)
    tags = _collect_tags(query, position.meta)
    return {
        "timestamp": pd.Timestamp(timestamp),
        "position_id": str(
            position.meta.get("position_id")
            or position.meta.get("rv_position_id")
            or f"{_query_signature(query)}|{pd.Timestamp(position.opened).isoformat()}|{position_index}"
        ),
        "opened_at": pd.Timestamp(position.opened),
        "product": str(getattr(query, "product", "unknown")),
        "query_label": _query_label(query),
        "query_signature": _query_signature(query),
        "curve": getattr(query, "curve", None),
        "tenor": getattr(query, "tenor", None),
        "tags": tags,
        "tag_text": ", ".join(tags),
        "gross_weight": float(np.sum(np.abs(position.weights))) if getattr(position, "weights", None) else 0.0,
        "net_weight": float(np.sum(position.weights)) if getattr(position, "weights", None) else 0.0,
        "package_size": len(position.package),
        "size_metric": metric,
        "size_value": size_value,
        "size_abs": abs(size_value) if np.isfinite(size_value) else np.nan,
        "direction": _direction_hint(position, size_value),
        "handler_name": str(position.meta.get("handler", "generic")),
        "meta": dict(position.meta or {}),
        "source_query": query,
    }


def _build_closed_trade_frame(backtest: QueryDrivenBacktest, *, size_metric: Optional[str]) -> pd.DataFrame:
    records = getattr(getattr(backtest, "portfolio", None), "closed_positions_log", []) or []
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        position = record.get("position")
        if not isinstance(position, ResolvedQueryPosition):
            continue
        row = _base_position_row(position, size_metric=size_metric, timestamp=pd.Timestamp(record["closed_at"]), position_index=index)
        exit_meta = dict(record.get("exit_meta", {}) or {})
        row.update(
            {
                "closed_at": pd.Timestamp(record["closed_at"]),
                "holding_period_steps": int(record.get("holding_period_steps", 0)),
                "holding_period_days": float(record.get("holding_period_days", 0.0)),
                "realized_pnl": float(record.get("realized_pnl", 0.0)),
                "gross_realized_pnl": float(record.get("gross_realized_pnl", 0.0)),
                "fee_allocated": float(record.get("fee_allocated", 0.0)),
                "exit_reason": exit_meta.get("reason") or exit_meta.get("action"),
                "is_winner": float(record.get("realized_pnl", 0.0)) > 0.0,
                "exit_meta": exit_meta,
                "position_meta": dict(record.get("position_meta", {}) or {}),
            }
        )
        rows.append(row)

    if not rows:
        return pd.DataFrame(
            columns=[
                "position_id",
                "opened_at",
                "closed_at",
                "product",
                "query_label",
                "query_signature",
                "tag_text",
                "realized_pnl",
                "holding_period_days",
                "holding_period_steps",
                "exit_reason",
            ]
        )
    frame = pd.DataFrame(rows).sort_values(["closed_at", "opened_at", "query_label"]).reset_index(drop=True)
    return frame


def _build_open_positions_frame(
    backtest: QueryDrivenBacktest,
    *,
    size_metric: Optional[str],
    last_timestamp: pd.Timestamp,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    positions = list(getattr(backtest.portfolio, "iter_positions", lambda: ())())
    for index, position in enumerate(positions):
        row = _base_position_row(position, size_metric=size_metric, timestamp=last_timestamp, position_index=index)
        try:
            current_mtm = float(backtest._position_value(position, last_timestamp))
        except Exception:
            current_mtm = float("nan")
        age_steps = (
            int(backtest._holding_period_steps(position.opened, last_timestamp))
            if hasattr(backtest, "_holding_period_steps")
            else 0
        )
        row.update(
            {
                "current_mtm": current_mtm,
                "age_steps": age_steps,
                "age_days": max(0.0, (pd.Timestamp(last_timestamp) - pd.Timestamp(position.opened)).total_seconds() / 86400.0),
            }
        )
        rows.append(row)

    if not rows:
        return pd.DataFrame(
            columns=[
                "position_id",
                "opened_at",
                "product",
                "query_label",
                "tag_text",
                "current_mtm",
                "age_days",
                "age_steps",
            ]
        )
    return pd.DataFrame(rows).sort_values(["opened_at", "product", "query_label"]).reset_index(drop=True)


def _build_snapshot_frame(backtest: QueryDrivenBacktest, *, size_metric: Optional[str]) -> pd.DataFrame:
    snapshot_map = dict(getattr(backtest, "position_history", {}) or {})
    if not snapshot_map and getattr(backtest, "mtm_history", None):
        last_timestamp = pd.DatetimeIndex(pd.Series(backtest.mtm_history).sort_index().index)[-1]
        snapshot_map[last_timestamp] = list(getattr(backtest.portfolio, "iter_positions", lambda: ())())

    rows: list[dict[str, Any]] = []
    for timestamp in sorted(snapshot_map):
        positions = snapshot_map[timestamp]
        for index, position in enumerate(positions):
            row = _base_position_row(position, size_metric=size_metric, timestamp=pd.Timestamp(timestamp), position_index=index)
            row["age_days"] = max(0.0, (pd.Timestamp(timestamp) - pd.Timestamp(position.opened)).total_seconds() / 86400.0)
            rows.append(row)

    if not rows:
        return pd.DataFrame(columns=["timestamp", "position_id", "product", "query_label", "size_value", "size_abs"])
    return pd.DataFrame(rows).sort_values(["timestamp", "opened_at", "product", "query_label"]).reset_index(drop=True)


def _build_position_counts(snapshot_frame: pd.DataFrame, full_index: pd.DatetimeIndex) -> pd.DataFrame:
    if snapshot_frame.empty:
        return pd.DataFrame({"open_positions": 0.0, "avg_age_days": 0.0}, index=full_index)
    grouped = snapshot_frame.groupby("timestamp").agg(open_positions=("position_id", "count"), avg_age_days=("age_days", "mean"))
    return grouped.reindex(full_index).fillna(0.0)


def _build_snapshot_group_counts(
    snapshot_frame: pd.DataFrame,
    *,
    full_index: pd.DatetimeIndex,
    group_col: str,
    top_n: int,
) -> pd.DataFrame:
    if snapshot_frame.empty:
        return pd.DataFrame(index=full_index)
    wide = snapshot_frame.pivot_table(index="timestamp", columns=group_col, values="position_id", aggfunc="count", fill_value=0.0)
    if wide.shape[1] > top_n:
        keep = wide.max().sort_values(ascending=False).head(top_n).index
        wide = wide.loc[:, keep]
    return wide.reindex(full_index).fillna(0.0)


def _build_size_exposure(snapshot_frame: pd.DataFrame, *, full_index: pd.DatetimeIndex) -> pd.DataFrame:
    if snapshot_frame.empty or "size_value" not in snapshot_frame or snapshot_frame["size_value"].dropna().empty:
        return pd.DataFrame(index=full_index)
    grouped = snapshot_frame.groupby("timestamp").agg(
        gross_size=("size_abs", "sum"),
        net_size=("size_value", "sum"),
    )
    return grouped.reindex(full_index).fillna(0.0)


def _count_sessions(values: Iterable[Any]) -> pd.Series:
    rows: list[pd.Timestamp] = []
    for value in values:
        rows.append(_session_timestamp(value))
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series(1.0, index=pd.DatetimeIndex(rows)).groupby(level=0).sum().sort_index()


def _build_trade_flow(
    backtest: QueryDrivenBacktest,
    *,
    session_index: pd.DatetimeIndex,
    closed_trades: pd.DataFrame,
) -> pd.DataFrame:
    entry_series = _count_sessions([order.timestamp for order in getattr(backtest.portfolio, "trades_log", []) or []])
    if not closed_trades.empty:
        exit_series = _count_sessions(closed_trades["closed_at"])
    else:
        exit_series = _count_sessions([order.timestamp for order in getattr(backtest.portfolio, "unwind_log", []) or []])
    flow = pd.DataFrame(index=session_index)
    flow["entries"] = entry_series.reindex(session_index).fillna(0.0)
    flow["exits"] = exit_series.reindex(session_index).fillna(0.0)
    flow["trade_sides"] = flow["entries"] + flow["exits"]
    flow["rolling_21_session_sides"] = flow["trade_sides"].rolling(min(21, max(1, len(flow)))).sum()
    return flow


def _build_monthly_heatmap(session_pnl: pd.Series) -> pd.DataFrame:
    if session_pnl.empty:
        return pd.DataFrame(columns=_MONTH_NAMES)
    clean = pd.Series(session_pnl, index=pd.DatetimeIndex(session_pnl.index), dtype=float).sort_index()
    monthly = clean.groupby([clean.index.year, clean.index.month]).sum().unstack()
    monthly = monthly.reindex(columns=list(range(1, 13)))
    monthly.columns = _MONTH_NAMES
    monthly.index.name = "Year"
    return monthly


def _explode_tags(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "tags" not in frame.columns:
        return pd.DataFrame(columns=list(frame.columns) + ["tag"])
    exploded = frame.copy()
    exploded["tag"] = exploded["tags"].apply(lambda values: values if values else ["untagged"])
    return exploded.explode("tag")


def _build_group_summary(closed_trades: pd.DataFrame, open_positions: pd.DataFrame, *, group_col: str) -> pd.DataFrame:
    closed_summary = pd.DataFrame()
    if not closed_trades.empty and group_col in closed_trades:
        closed_summary = closed_trades.groupby(group_col).agg(
            closed_trades=("position_id", "count"),
            realized_pnl=("realized_pnl", "sum"),
            avg_trade_pnl=("realized_pnl", "mean"),
            win_rate=("is_winner", "mean"),
            avg_holding_days=("holding_period_days", "mean"),
        )
    open_summary = pd.DataFrame()
    if not open_positions.empty and group_col in open_positions:
        open_summary = open_positions.groupby(group_col).agg(
            open_positions=("position_id", "count"),
            open_mtm=("current_mtm", "sum"),
            gross_size=("size_abs", "sum"),
        )
    if closed_summary.empty and open_summary.empty:
        return pd.DataFrame(columns=["closed_trades", "open_positions", "realized_pnl", "open_mtm", "total_pnl"])
    summary = closed_summary.join(open_summary, how="outer").fillna(0.0)
    summary["total_pnl"] = summary.get("realized_pnl", 0.0) + summary.get("open_mtm", 0.0)
    return summary.sort_values("total_pnl", ascending=False)


def _build_tag_summary(closed_trades: pd.DataFrame, open_positions: pd.DataFrame) -> pd.DataFrame:
    closed_tags = _explode_tags(closed_trades)
    open_tags = _explode_tags(open_positions)
    closed_summary = pd.DataFrame()
    if not closed_tags.empty:
        closed_summary = closed_tags.groupby("tag").agg(
            closed_trades=("position_id", "count"),
            realized_pnl=("realized_pnl", "sum"),
            avg_trade_pnl=("realized_pnl", "mean"),
        )
    open_summary = pd.DataFrame()
    if not open_tags.empty:
        open_summary = open_tags.groupby("tag").agg(
            open_positions=("position_id", "count"),
            open_mtm=("current_mtm", "sum"),
        )
    if closed_summary.empty and open_summary.empty:
        return pd.DataFrame(columns=["closed_trades", "open_positions", "realized_pnl", "open_mtm", "total_pnl"])
    summary = closed_summary.join(open_summary, how="outer").fillna(0.0)
    summary["total_pnl"] = summary.get("realized_pnl", 0.0) + summary.get("open_mtm", 0.0)
    return summary.sort_values("total_pnl", ascending=False)


def _drawdown_episodes(equity: pd.Series) -> pd.DataFrame:
    if equity.empty:
        return pd.DataFrame(columns=["peak_date", "trough_date", "recovery_date", "drawdown", "drawdown_pct", "duration_sessions"])

    series = equity.astype(float)
    current_peak = float(series.iloc[0])
    peak_date = pd.Timestamp(series.index[0])
    peak_idx = 0
    in_drawdown = False
    trough_date = peak_date
    trough_value = 0.0
    trough_idx = 0
    rows: list[dict[str, Any]] = []

    for idx, (timestamp, value) in enumerate(series.items()):
        ts = pd.Timestamp(timestamp)
        numeric_value = float(value)
        if numeric_value >= current_peak:
            if in_drawdown:
                rows.append(
                    {
                        "peak_date": peak_date,
                        "trough_date": trough_date,
                        "recovery_date": ts,
                        "drawdown": trough_value,
                        "drawdown_pct": (trough_value / current_peak) if current_peak != 0.0 else np.nan,
                        "duration_sessions": idx - peak_idx,
                        "recovery_sessions": idx - trough_idx,
                    }
                )
                in_drawdown = False
            current_peak = numeric_value
            peak_date = ts
            peak_idx = idx
            trough_date = ts
            trough_value = 0.0
            trough_idx = idx
            continue

        current_dd = numeric_value - current_peak
        if not in_drawdown:
            in_drawdown = True
            trough_date = ts
            trough_value = current_dd
            trough_idx = idx
        elif current_dd < trough_value:
            trough_date = ts
            trough_value = current_dd
            trough_idx = idx

    if in_drawdown:
        rows.append(
            {
                "peak_date": peak_date,
                "trough_date": trough_date,
                "recovery_date": pd.NaT,
                "drawdown": trough_value,
                "drawdown_pct": (trough_value / current_peak) if current_peak != 0.0 else np.nan,
                "duration_sessions": len(series) - 1 - peak_idx,
                "recovery_sessions": np.nan,
            }
        )

    if not rows:
        return pd.DataFrame(columns=["peak_date", "trough_date", "recovery_date", "drawdown", "drawdown_pct", "duration_sessions"])
    return pd.DataFrame(rows).sort_values("drawdown").reset_index(drop=True)


def _build_summary(
    *,
    name: str,
    capital_base: Optional[float],
    step_equity: pd.Series,
    session_pnl: pd.Series,
    session_equity: pd.Series,
    session_drawdown: pd.Series,
    step_realized: pd.Series,
    step_open_pnl: pd.Series,
    position_counts: pd.DataFrame,
    trade_flow: pd.DataFrame,
    closed_trades: pd.DataFrame,
    open_positions: pd.DataFrame,
) -> dict[str, Any]:
    pnl_std = float(session_pnl.std()) if len(session_pnl) > 1 else 0.0
    downside_std = float(session_pnl[session_pnl < 0.0].std()) if (session_pnl < 0.0).any() else 0.0
    sharpe = float(session_pnl.mean() / pnl_std * np.sqrt(252.0)) if pnl_std > 0.0 else 0.0
    sortino = float(session_pnl.mean() / downside_std * np.sqrt(252.0)) if downside_std > 0.0 else 0.0
    var_95 = float(session_pnl.quantile(0.05)) if len(session_pnl) else 0.0
    cvar_95 = float(session_pnl[session_pnl <= var_95].mean()) if len(session_pnl) and (session_pnl <= var_95).any() else var_95

    gross_profit = float(closed_trades.loc[closed_trades["realized_pnl"] > 0.0, "realized_pnl"].sum()) if not closed_trades.empty else 0.0
    gross_loss = float(-closed_trades.loc[closed_trades["realized_pnl"] < 0.0, "realized_pnl"].sum()) if not closed_trades.empty else 0.0
    avg_win = float(closed_trades.loc[closed_trades["realized_pnl"] > 0.0, "realized_pnl"].mean()) if not closed_trades.empty and (closed_trades["realized_pnl"] > 0.0).any() else 0.0
    avg_loss = float(closed_trades.loc[closed_trades["realized_pnl"] < 0.0, "realized_pnl"].mean()) if not closed_trades.empty and (closed_trades["realized_pnl"] < 0.0).any() else 0.0
    hit_rate = float((closed_trades["realized_pnl"] > 0.0).mean()) if not closed_trades.empty else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0.0 else (np.inf if gross_profit > 0.0 else 0.0)
    payoff_ratio = (avg_win / abs(avg_loss)) if avg_loss < 0.0 else (np.inf if avg_win > 0.0 else 0.0)

    total_pnl = float(step_equity.iloc[-1]) if len(step_equity) else 0.0
    realized_pnl = float(step_realized.iloc[-1]) if len(step_realized) else 0.0
    open_pnl = float(step_open_pnl.iloc[-1]) if len(step_open_pnl) else 0.0
    max_drawdown = float(session_drawdown.min()) if len(session_drawdown) else 0.0
    current_drawdown = float(session_drawdown.iloc[-1]) if len(session_drawdown) else 0.0
    avg_open_positions = float(position_counts["open_positions"].mean()) if not position_counts.empty else 0.0
    max_open_positions = float(position_counts["open_positions"].max()) if not position_counts.empty else 0.0
    time_in_market = float((position_counts["open_positions"] > 0.0).mean()) if not position_counts.empty else 0.0

    summary: dict[str, Any] = {
        "name": name,
        "start": pd.Timestamp(step_equity.index[0]),
        "end": pd.Timestamp(step_equity.index[-1]),
        "steps": int(len(step_equity)),
        "sessions": int(len(session_equity)),
        "total_pnl": total_pnl,
        "realized_pnl": realized_pnl,
        "open_pnl": open_pnl,
        "avg_session_pnl": float(session_pnl.mean()) if len(session_pnl) else 0.0,
        "session_vol": pnl_std * np.sqrt(252.0),
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "current_drawdown": current_drawdown,
        "best_session": float(session_pnl.max()) if len(session_pnl) else 0.0,
        "worst_session": float(session_pnl.min()) if len(session_pnl) else 0.0,
        "var_95": var_95,
        "cvar_95": cvar_95,
        "entry_count": float(trade_flow["entries"].sum()) if not trade_flow.empty else 0.0,
        "exit_count": float(trade_flow["exits"].sum()) if not trade_flow.empty else 0.0,
        "trade_sides": float(trade_flow["trade_sides"].sum()) if not trade_flow.empty else 0.0,
        "closed_trade_count": int(len(closed_trades)),
        "open_trade_count": int(len(open_positions)),
        "trade_hit_rate": hit_rate,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff_ratio,
        "expectancy": float(closed_trades["realized_pnl"].mean()) if not closed_trades.empty else 0.0,
        "avg_holding_days": float(closed_trades["holding_period_days"].mean()) if not closed_trades.empty else 0.0,
        "avg_holding_steps": float(closed_trades["holding_period_steps"].mean()) if not closed_trades.empty else 0.0,
        "avg_open_positions": avg_open_positions,
        "max_open_positions": max_open_positions,
        "time_in_market": time_in_market,
    }

    if capital_base not in (None, 0.0):
        capital = float(capital_base)
        session_returns = session_pnl / capital
        ann_return = float(session_returns.mean() * 252.0)
        ann_vol = float(session_returns.std() * np.sqrt(252.0)) if len(session_returns) > 1 else 0.0
        total_return = total_pnl / capital
        max_dd_pct = max_drawdown / capital
        calmar = (ann_return / abs(max_dd_pct)) if max_dd_pct < 0.0 else np.inf
        summary.update(
            {
                "capital_base": capital,
                "total_return_pct": total_return,
                "annual_return_pct": ann_return,
                "annual_vol_pct": ann_vol,
                "max_drawdown_pct": max_dd_pct,
                "calmar": calmar,
            }
        )

    return summary


def _summary_frame(summary: Mapping[str, Any]) -> pd.DataFrame:
    rows = [
        ("Strategy", summary.get("name")),
        ("Start", summary.get("start")),
        ("End", summary.get("end")),
        ("Steps", summary.get("steps")),
        ("Sessions", summary.get("sessions")),
        ("Total PnL", summary.get("total_pnl")),
        ("Realized PnL", summary.get("realized_pnl")),
        ("Open PnL", summary.get("open_pnl")),
        ("Sharpe", summary.get("sharpe")),
        ("Sortino", summary.get("sortino")),
        ("Max Drawdown", summary.get("max_drawdown")),
        ("Trade Hit Rate", summary.get("trade_hit_rate")),
        ("Closed Trades", summary.get("closed_trade_count")),
        ("Open Trades", summary.get("open_trade_count")),
        ("Avg Hold Days", summary.get("avg_holding_days")),
        ("Time In Market", summary.get("time_in_market")),
    ]
    if "total_return_pct" in summary:
        rows.extend(
            [
                ("Capital Base", summary.get("capital_base")),
                ("Total Return", summary.get("total_return_pct")),
                ("Ann. Return", summary.get("annual_return_pct")),
                ("Ann. Vol", summary.get("annual_vol_pct")),
                ("Calmar", summary.get("calmar")),
            ]
        )
    return pd.DataFrame(rows, columns=["Metric", "Value"])


def _format_value(value: Any, *, kind: str = "auto") -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "-"
    if kind == "date":
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if kind == "int":
        return f"{int(round(float(value))):,d}"
    if kind == "pct":
        return f"{float(value) * 100.0:,.2f}%"
    if kind == "float":
        return f"{float(value):,.2f}"
    if kind == "ratio":
        numeric = float(value)
        return "inf" if np.isinf(numeric) else f"{numeric:,.2f}"
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,d}"
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        if np.isinf(numeric):
            return "inf"
        if abs(numeric) >= 1000.0:
            return f"{numeric:,.0f}"
        return f"{numeric:,.2f}"
    return str(value)


def _summary_display_rows(analytics: QueryBacktestAnalytics) -> list[tuple[str, str]]:
    summary = analytics.summary
    rows = [
        ("Strategy", _format_value(summary.get("name"))),
        ("Start", _format_value(summary.get("start"), kind="date")),
        ("End", _format_value(summary.get("end"), kind="date")),
        ("Steps", _format_value(summary.get("steps"), kind="int")),
        ("Sessions", _format_value(summary.get("sessions"), kind="int")),
        ("Total PnL", _format_value(summary.get("total_pnl"), kind="float")),
        ("Realized PnL", _format_value(summary.get("realized_pnl"), kind="float")),
        ("Open PnL", _format_value(summary.get("open_pnl"), kind="float")),
        ("Sharpe", _format_value(summary.get("sharpe"), kind="ratio")),
        ("Sortino", _format_value(summary.get("sortino"), kind="ratio")),
        ("Max Drawdown", _format_value(summary.get("max_drawdown"), kind="float")),
        ("Trade Hit Rate", _format_value(summary.get("trade_hit_rate"), kind="pct")),
        ("Closed Trades", _format_value(summary.get("closed_trade_count"), kind="int")),
        ("Open Trades", _format_value(summary.get("open_trade_count"), kind="int")),
        ("Avg Hold Days", _format_value(summary.get("avg_holding_days"), kind="float")),
        ("Time In Market", _format_value(summary.get("time_in_market"), kind="pct")),
    ]
    if analytics.capital_base is not None:
        rows.extend(
            [
                ("Capital Base", _format_value(summary.get("capital_base"), kind="float")),
                ("Total Return", _format_value(summary.get("total_return_pct"), kind="pct")),
                ("Ann. Return", _format_value(summary.get("annual_return_pct"), kind="pct")),
                ("Ann. Vol", _format_value(summary.get("annual_vol_pct"), kind="pct")),
                ("Calmar", _format_value(summary.get("calmar"), kind="ratio")),
            ]
        )
    return rows


def _draw_no_data(ax: Any, title: str, message: str) -> None:
    ax.axis("off")
    ax.set_title(title, loc="left")
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=11, transform=ax.transAxes)


def _plot_summary_table_matplotlib(ax: Any, analytics: QueryBacktestAnalytics) -> None:
    rows = _summary_display_rows(analytics)
    ax.axis("off")
    table = ax.table(
        cellText=[[label, value] for label, value in rows],
        colLabels=["Metric", "Value"],
        cellLoc="left",
        colLoc="left",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.0, 1.4)
    ax.set_title("Summary", loc="left", fontsize=13, fontweight="bold")


def _plot_equity_matplotlib(ax: Any, analytics: QueryBacktestAnalytics) -> None:
    ax.plot(analytics.step_equity.index, analytics.step_equity.values, label="Equity", linewidth=2.2)
    ax.plot(analytics.step_realized.index, analytics.step_realized.values, label="Realized", linewidth=1.5, alpha=0.9)
    ax.plot(analytics.step_open_pnl.index, analytics.step_open_pnl.values, label="Open PnL", linewidth=1.5, alpha=0.9)
    ax.set_title("Equity Curve", loc="left")
    ax.grid(alpha=0.25)
    ax.legend(loc="best")


def _plot_drawdown_matplotlib(ax: Any, analytics: QueryBacktestAnalytics) -> None:
    ax.fill_between(analytics.session_drawdown.index, analytics.session_drawdown.values, 0.0, color="#d62728", alpha=0.35)
    ax.plot(analytics.session_drawdown.index, analytics.session_drawdown.values, color="#d62728", linewidth=1.6)
    ax.set_title("Underwater", loc="left")
    ax.grid(alpha=0.25)


def _plot_session_pnl_matplotlib(ax: Any, analytics: QueryBacktestAnalytics) -> None:
    colors = np.where(analytics.session_pnl.values >= 0.0, "#2ca02c", "#d62728")
    ax.bar(analytics.session_pnl.index, analytics.session_pnl.values, color=colors, width=3.0 if len(analytics.session_pnl) > 1 else 0.8, alpha=0.8)
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_title("Session PnL", loc="left")
    ax.grid(alpha=0.25)


def _plot_rolling_metrics_matplotlib(ax: Any, analytics: QueryBacktestAnalytics) -> None:
    ax.plot(analytics.rolling_sharpe.index, analytics.rolling_sharpe.values, color="#1f77b4", label="Rolling Sharpe", linewidth=1.8)
    ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.7)
    ax.set_title("Rolling Metrics", loc="left")
    ax.grid(alpha=0.25)
    vol_ax = ax.twinx()
    vol_ax.plot(analytics.rolling_vol.index, analytics.rolling_vol.values, color="#ff7f0e", label="Rolling Vol", linewidth=1.4, alpha=0.9)
    lines = ax.get_lines() + vol_ax.get_lines()
    labels = [line.get_label() for line in lines]
    ax.legend(lines, labels, loc="upper left")


def _plot_monthly_heatmap_matplotlib(ax: Any, analytics: QueryBacktestAnalytics) -> None:
    if analytics.monthly_pnl.empty:
        _draw_no_data(ax, "Monthly Heatmap", "No session data")
        return
    matrix = analytics.monthly_pnl.fillna(0.0).to_numpy(dtype=float)
    image = ax.imshow(matrix, aspect="auto", cmap="RdYlGn")
    ax.figure.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    ax.set_xticks(range(len(analytics.monthly_pnl.columns)))
    ax.set_xticklabels(list(analytics.monthly_pnl.columns), rotation=0)
    ax.set_yticks(range(len(analytics.monthly_pnl.index)))
    ax.set_yticklabels([str(idx) for idx in analytics.monthly_pnl.index])
    ax.set_title("Monthly PnL Heatmap", loc="left")
    for row_idx in range(matrix.shape[0]):
        for col_idx in range(matrix.shape[1]):
            value = matrix[row_idx, col_idx]
            if np.isnan(value):
                continue
            ax.text(col_idx, row_idx, _format_value(value, kind="float"), ha="center", va="center", fontsize=8)


def _plot_distribution_matplotlib(ax: Any, analytics: QueryBacktestAnalytics) -> None:
    values = analytics.session_pnl.dropna().values
    if len(values) == 0:
        _draw_no_data(ax, "PnL Distribution", "No session PnL")
        return
    ax.hist(values, bins=min(30, max(5, len(values))), color="#1f77b4", alpha=0.75, edgecolor="white")
    ax.axvline(np.mean(values), color="#d62728", linewidth=1.5, label="Mean")
    ax.axvline(np.median(values), color="#2ca02c", linewidth=1.5, linestyle="--", label="Median")
    ax.set_title("Session PnL Distribution", loc="left")
    ax.grid(alpha=0.25)
    ax.legend(loc="best")


def _plot_position_and_flow_matplotlib(ax: Any, analytics: QueryBacktestAnalytics) -> None:
    ax.plot(analytics.position_counts.index, analytics.position_counts["open_positions"].values, color="#1f77b4", linewidth=2.0, label="Open Positions")
    ax.set_title("Open Positions / Trade Sides", loc="left")
    ax.grid(alpha=0.25)
    flow_ax = ax.twinx()
    flow_ax.bar(analytics.trade_flow.index, analytics.trade_flow["trade_sides"].values, color="#ff7f0e", alpha=0.25, label="Trade Sides")
    lines = ax.get_lines()
    legend_lines = lines + [flow_ax.patches[0]] if len(flow_ax.patches) else lines
    legend_labels = ["Open Positions"] + (["Trade Sides"] if len(flow_ax.patches) else [])
    ax.legend(legend_lines, legend_labels, loc="upper left")


def _plot_exposure_or_product_counts_matplotlib(ax: Any, analytics: QueryBacktestAnalytics) -> None:
    if not analytics.size_exposure.empty:
        ax.plot(analytics.size_exposure.index, analytics.size_exposure["gross_size"].values, label=f"Gross {analytics.size_metric or 'Size'}", linewidth=2.0)
        ax.plot(analytics.size_exposure.index, analytics.size_exposure["net_size"].values, label=f"Net {analytics.size_metric or 'Size'}", linewidth=1.6)
        ax.set_title("Sizing Exposure", loc="left")
        ax.grid(alpha=0.25)
        ax.legend(loc="best")
        return
    if analytics.product_open_counts.empty:
        _draw_no_data(ax, "Exposure / Product Counts", "No position snapshots")
        return
    for column in analytics.product_open_counts.columns:
        ax.plot(analytics.product_open_counts.index, analytics.product_open_counts[column].values, linewidth=1.6, label=str(column))
    ax.set_title("Open Position Counts by Product", loc="left")
    ax.grid(alpha=0.25)
    ax.legend(loc="best")


def _plot_group_bar_matplotlib(ax: Any, frame: pd.DataFrame, *, title: str) -> None:
    if frame.empty:
        _draw_no_data(ax, title, "No grouped trade data")
        return
    data = frame.head(8).iloc[::-1]
    ax.barh(data.index.astype(str), data["total_pnl"].values, color=np.where(data["total_pnl"].values >= 0.0, "#2ca02c", "#d62728"), alpha=0.8)
    ax.axvline(0.0, color="black", linewidth=0.8)
    ax.set_title(title, loc="left")
    ax.grid(alpha=0.25, axis="x")


def _plot_trade_scatter_or_tag_bar_matplotlib(ax: Any, analytics: QueryBacktestAnalytics) -> None:
    if not analytics.closed_trades.empty:
        scatter = ax.scatter(
            analytics.closed_trades["holding_period_days"].values,
            analytics.closed_trades["realized_pnl"].values,
            c=analytics.closed_trades["realized_pnl"].values,
            cmap="RdYlGn",
            alpha=0.8,
            edgecolors="black",
            linewidths=0.5,
        )
        ax.figure.colorbar(scatter, ax=ax, fraction=0.046, pad=0.04)
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set_xlabel("Holding Days")
        ax.set_ylabel("Realized PnL")
        ax.set_title("Closed Trade PnL vs Holding Period", loc="left")
        ax.grid(alpha=0.25)
        return
    _plot_group_bar_matplotlib(ax, analytics.tag_summary, title="Tag PnL Mix")


def _plot_summary_table_plotly(fig: Any, analytics: QueryBacktestAnalytics, *, row: int, col: int) -> None:
    import plotly.graph_objects as go

    rows = _summary_display_rows(analytics)
    fig.add_trace(
        go.Table(
            header=dict(values=["Metric", "Value"], fill_color="#1f77b4", font=dict(color="white"), align="left"),
            cells=dict(values=[[label for label, _ in rows], [value for _, value in rows]], align="left"),
        ),
        row=row,
        col=col,
    )


def _plot_equity_plotly(fig: Any, analytics: QueryBacktestAnalytics, *, row: int, col: int) -> None:
    import plotly.graph_objects as go

    fig.add_trace(go.Scatter(x=analytics.step_equity.index, y=analytics.step_equity.values, mode="lines", name="Equity", line=dict(width=2.4)), row=row, col=col)
    fig.add_trace(go.Scatter(x=analytics.step_realized.index, y=analytics.step_realized.values, mode="lines", name="Realized", line=dict(width=1.5)), row=row, col=col)
    fig.add_trace(go.Scatter(x=analytics.step_open_pnl.index, y=analytics.step_open_pnl.values, mode="lines", name="Open PnL", line=dict(width=1.5)), row=row, col=col)


def _plot_drawdown_plotly(fig: Any, analytics: QueryBacktestAnalytics, *, row: int, col: int) -> None:
    import plotly.graph_objects as go

    fig.add_trace(
        go.Scatter(
            x=analytics.session_drawdown.index,
            y=analytics.session_drawdown.values,
            mode="lines",
            fill="tozeroy",
            name="Drawdown",
            line=dict(color="#d62728", width=1.8),
        ),
        row=row,
        col=col,
    )


def _plot_session_pnl_plotly(fig: Any, analytics: QueryBacktestAnalytics, *, row: int, col: int) -> None:
    import plotly.graph_objects as go

    colors = np.where(analytics.session_pnl.values >= 0.0, "#2ca02c", "#d62728")
    fig.add_trace(go.Bar(x=analytics.session_pnl.index, y=analytics.session_pnl.values, marker_color=colors, name="Session PnL"), row=row, col=col)


def _plot_rolling_metrics_plotly(fig: Any, analytics: QueryBacktestAnalytics, *, row: int, col: int) -> None:
    import plotly.graph_objects as go

    fig.add_trace(
        go.Scatter(x=analytics.rolling_sharpe.index, y=analytics.rolling_sharpe.values, mode="lines", name="Rolling Sharpe", line=dict(color="#1f77b4", width=1.8)),
        row=row,
        col=col,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=analytics.rolling_vol.index, y=analytics.rolling_vol.values, mode="lines", name="Rolling Vol", line=dict(color="#ff7f0e", width=1.5)),
        row=row,
        col=col,
        secondary_y=True,
    )


def _plot_monthly_heatmap_plotly(fig: Any, analytics: QueryBacktestAnalytics, *, row: int, col: int) -> None:
    import plotly.graph_objects as go

    if analytics.monthly_pnl.empty:
        return
    matrix = analytics.monthly_pnl.fillna(0.0)
    fig.add_trace(
        go.Heatmap(
            z=matrix.to_numpy(dtype=float),
            x=list(matrix.columns),
            y=[str(index) for index in matrix.index],
            colorscale="RdYlGn",
            colorbar=dict(title="PnL"),
            text=np.vectorize(lambda value: _format_value(value, kind="float"))(matrix.to_numpy(dtype=float)),
            texttemplate="%{text}",
        ),
        row=row,
        col=col,
    )


def _plot_distribution_plotly(fig: Any, analytics: QueryBacktestAnalytics, *, row: int, col: int) -> None:
    import plotly.graph_objects as go

    values = analytics.session_pnl.dropna().values
    if len(values) == 0:
        return
    fig.add_trace(go.Histogram(x=values, nbinsx=min(30, max(5, len(values))), name="Session PnL Dist", marker_color="#1f77b4", opacity=0.8), row=row, col=col)


def _plot_position_and_flow_plotly(fig: Any, analytics: QueryBacktestAnalytics, *, row: int, col: int) -> None:
    import plotly.graph_objects as go

    fig.add_trace(
        go.Scatter(x=analytics.position_counts.index, y=analytics.position_counts["open_positions"].values, mode="lines", name="Open Positions", line=dict(color="#1f77b4", width=2.2)),
        row=row,
        col=col,
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(x=analytics.trade_flow.index, y=analytics.trade_flow["trade_sides"].values, name="Trade Sides", marker_color="#ff7f0e", opacity=0.25),
        row=row,
        col=col,
        secondary_y=True,
    )


def _plot_exposure_or_product_counts_plotly(fig: Any, analytics: QueryBacktestAnalytics, *, row: int, col: int) -> None:
    import plotly.graph_objects as go

    if not analytics.size_exposure.empty:
        fig.add_trace(go.Scatter(x=analytics.size_exposure.index, y=analytics.size_exposure["gross_size"].values, mode="lines", name=f"Gross {analytics.size_metric or 'Size'}", line=dict(width=2.0)), row=row, col=col)
        fig.add_trace(go.Scatter(x=analytics.size_exposure.index, y=analytics.size_exposure["net_size"].values, mode="lines", name=f"Net {analytics.size_metric or 'Size'}", line=dict(width=1.5)), row=row, col=col)
        return
    for column in analytics.product_open_counts.columns:
        fig.add_trace(go.Scatter(x=analytics.product_open_counts.index, y=analytics.product_open_counts[column].values, mode="lines", name=str(column), line=dict(width=1.5)), row=row, col=col)


def _plot_group_bar_plotly(fig: Any, frame: pd.DataFrame, *, title: str, row: int, col: int) -> None:
    import plotly.graph_objects as go

    if frame.empty:
        return
    data = frame.head(8).iloc[::-1]
    colors = np.where(data["total_pnl"].values >= 0.0, "#2ca02c", "#d62728")
    fig.add_trace(go.Bar(x=data["total_pnl"].values, y=data.index.astype(str), orientation="h", marker_color=colors, name=title), row=row, col=col)


def _plot_trade_scatter_or_tag_bar_plotly(fig: Any, analytics: QueryBacktestAnalytics, *, row: int, col: int) -> None:
    import plotly.graph_objects as go

    if not analytics.closed_trades.empty:
        fig.add_trace(
            go.Scatter(
                x=analytics.closed_trades["holding_period_days"].values,
                y=analytics.closed_trades["realized_pnl"].values,
                mode="markers",
                marker=dict(
                    size=11,
                    color=analytics.closed_trades["realized_pnl"].values,
                    colorscale="RdYlGn",
                    showscale=True,
                    colorbar=dict(title="Trade PnL"),
                    line=dict(color="black", width=0.5),
                ),
                text=analytics.closed_trades["query_label"].astype(str),
                name="Closed Trades",
            ),
            row=row,
            col=col,
        )
        return
    _plot_group_bar_plotly(fig, analytics.tag_summary, title="Tag PnL Mix", row=row, col=col)

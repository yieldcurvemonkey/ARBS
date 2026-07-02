"""SERFF structures through QueryDrivenBacktest + STIRFutureMDP (Barchart).

The ledger/walk-forward machinery stays the signal brain (BT/serff/backtest);
this module replays its entry/exit decisions through the repo's query-driven
engine so positions are STIRFutureQuery OUTRIGHT legs and every mark comes
from an ACTUAL Barchart print resolved by ``STIRFutureMDP(source=
"BARCHART_STIRF-RL")`` -- no swap-curve derivation anywhere in the loop.

Conventions verified against Query/STIRFutures:

- direction: positive ``contracts`` + ``risk_weights=[+/-1]``.  (Negative
  contracts would flow into BOTH the leg's PV01 and the risk weight and
  double-flip the handler's MTM sign.)
- ``STIRFutureHandler`` marks (delta weighted price / 0.01) * PV01_quote,
  PV01_quote = contracts * unit bpv ($25/bp SR3 via spec ``usd_stir``,
  $41.67/bp ZQ/SR1 via ``usd_stir1``).
- rateslib STIRFuture legs carry no live ``price`` attribute, so the value
  map's price falls through to the CURRENT pricer's Barchart print.
- integer contracts are required by the query layer; fractional stub hedges
  are expressed by scaling the whole structure by ``unit_scale`` and
  rounding (rounding error reported per trade).

The engine's diskcache is pre-warmed from the settle panel (exact request-key
format ``{iso(_as_datetime(date))}-{SYMBOL}-BARCHART_STIRF-RL``) so a full
replay is cache-hit only; dates/symbols absent from the panel fall back to a
live Barchart fetch through the MDP.
"""

from __future__ import annotations

import datetime
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from BT.serff.config import SerffTradeConfig

logger = logging.getLogger(__name__)

_SRC = "BARCHART_STIRF-RL"


@dataclass
class SerffEngineResult:
    backtest: Any                     # QueryDrivenBacktest
    mtm: pd.Series                    # engine MTM history ($, at unit_scale)
    mtm_per_unit: pd.Series           # normalized back to 1 structure unit
    trades: pd.DataFrame              # replayed trades incl. integer legs + rounding error
    unit_scale: int
    comparison: pd.DataFrame          # engine vs panel-runner cumulative P&L (per unit)
    summary: Dict[str, Any] = field(default_factory=dict)

    def tearsheet(self):
        from BT.query_tearsheet import QueryBacktestTearSheet

        return QueryBacktestTearSheet.from_backtest(self.backtest, name="serff-engine")


# --------------------------------------------------------------------------
# cache warm
# --------------------------------------------------------------------------
def warm_mdp_cache(mdp: Any, settles: pd.DataFrame, symbols: List[str], dates: List[datetime.date]) -> int:
    """Seed the MDP pricer diskcache with settle-panel prices.

    Uses the exact request-timestamp key the MDP probes for ``date``-typed
    requests, so engine pricer resolution never leaves disk.  Each contract's
    settles are forward-filled between its first print and its window end --
    sparsely traded deferred months have no print on some sessions, and an
    unwarmed (symbol, date) would silently fall back to a live Barchart fetch
    (the MDP's own fetch path applies the same last-print carry).
    """
    from BT.serff.mechanics import contract_window
    from MDP.STIRFutures.STIRFutureMDP import _as_datetime

    mdp._ensure_pricer_cache()
    n = 0
    date_idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    for sym in symbols:
        if sym not in settles.columns:
            continue
        last_live = pd.Timestamp(contract_window(sym).end)
        col = settles[sym].reindex(settles.index.union(date_idx)).sort_index().ffill()
        col = col.loc[col.index < last_live]
        for d in dates:
            ts = pd.Timestamp(d)
            if ts not in col.index:
                continue
            px = col.loc[ts]
            if pd.isna(px):
                continue
            key_ts = pd.Timestamp(_as_datetime(d)).isoformat()
            args = {"symbol": sym, "price": float(px), "timestamp": key_ts, "schema": 1}
            mdp._threadsafe_cache_put(f"{key_ts}-{sym}-{_SRC}", args)
            n += 1
    return n


# --------------------------------------------------------------------------
# trigger construction
# --------------------------------------------------------------------------
def _leg_queries(
    trade: pd.Series,
    unit_scale: int,
    tag: str,
) -> Tuple[List[Any], float]:
    """One OUTRIGHT STIRFutureQuery per leg; returns (queries, max rounding err in contracts/scale)."""
    from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
    from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure

    legs: List[Tuple[str, float]] = [(trade["sr3_symbol"], float(trade["sr3_contracts"]))]
    zq = trade["zq_contracts"]
    if isinstance(zq, str):
        import ast

        zq = ast.literal_eval(zq)
    legs += [(s, float(n)) for s, n in dict(zq).items()]

    queries = []
    max_err = 0.0
    for sym, n in legs:
        n_scaled = n * unit_scale
        n_int = int(round(n_scaled))
        if n_int == 0:
            max_err = max(max_err, abs(n_scaled) / unit_scale)
            continue
        max_err = max(max_err, abs(n_int - n_scaled) / unit_scale)
        queries.append(
            STIRFutureQuery(
                structure=STIRFutureStructure.OUTRIGHT,
                symbol=sym,
                structure_kwargs={
                    "contracts": abs(n_int),
                    "risk_weights": [1.0 if n_int > 0 else -1.0],
                },
            )
        )
    return queries, max_err


def build_replay_triggers(
    trades: pd.DataFrame,
    trade_cfg: SerffTradeConfig,
    unit_scale: int,
) -> Tuple[List[Any], pd.DataFrame]:
    """Entry/exit DateTriggers per trade, tagged for unwind matching."""
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.triggers import DateTrigger, DateTriggerRequirements

    triggers: List[Any] = []
    rows = []
    for i, tr in trades.reset_index(drop=True).iterrows():
        tag = f"serff-{i}-{tr['sr3_symbol']}"
        queries, round_err = _leg_queries(tr, unit_scale, tag)
        if not queries:
            continue
        entry_date = pd.Timestamp(tr["entry_date"]).date()
        triggers.append(
            DateTrigger(
                DateTriggerRequirements(dates=[entry_date]),
                actions=[AddQueryAction(query=q, meta={"tags": [tag], "trade": i}) for q in queries],
            )
        )
        exit_date = tr.get("exit_date")
        has_exit = exit_date is not None and not (isinstance(exit_date, float) and math.isnan(exit_date))
        if has_exit:
            fee = float(tr.get("entry_cost", 0.0) + tr.get("exit_cost", 0.0)) * unit_scale
            triggers.append(
                DateTrigger(
                    DateTriggerRequirements(dates=[pd.Timestamp(exit_date).date()]),
                    actions=[UnwindPositionsAction(match_tag=tag, fee=fee)],
                )
            )
        rows.append(
            {
                "trade": i,
                "tag": tag,
                "entry_date": entry_date,
                "exit_date": pd.Timestamp(exit_date).date() if has_exit else None,
                "n_legs": len(queries),
                "rounding_err_contracts_per_unit": round_err,
            }
        )
    return triggers, pd.DataFrame(rows)


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------
def run_serff_engine_backtest(
    trades: pd.DataFrame,
    settles: pd.DataFrame,
    *,
    trade_cfg: Optional[SerffTradeConfig] = None,
    unit_scale: int = 30,
    mdp: Optional[Any] = None,
    panel_daily: Optional[pd.DataFrame] = None,
    show_progress: bool = True,
) -> SerffEngineResult:
    """Replay ledger-driven trades through QueryDrivenBacktest.

    trades      : SerffBacktestResult.trades (or its CSV round-trip)
    settles     : wide settle-price panel (cache warm + time grid)
    panel_daily : SerffBacktestResult.daily for the cross-check comparison
    unit_scale  : structure multiplier so stub hedges become integer contracts
    """
    from BT.data_handler import TimeGrid
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy

    trade_cfg = trade_cfg or SerffTradeConfig()
    trades = trades.dropna(subset=["entry_date"]).copy()
    if trades.empty:
        raise ValueError("no trades to replay")

    if mdp is None:
        from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

        mdp = STIRFutureMDP(source=_SRC)

    triggers, replay = build_replay_triggers(trades, trade_cfg, unit_scale)

    start = min(pd.Timestamp(d) for d in trades["entry_date"])
    exits = [pd.Timestamp(d) for d in trades["exit_date"].dropna()]
    end = max(exits) if exits else pd.Timestamp(settles.index.max())
    grid_dates = [d for d in settles.index if start <= d <= end]

    # every symbol any trade touches
    symbols: List[str] = []
    for _, tr in trades.iterrows():
        zq = tr["zq_contracts"]
        if isinstance(zq, str):
            import ast

            zq = ast.literal_eval(zq)
        symbols.extend([tr["sr3_symbol"], *dict(zq).keys()])
    symbols = sorted(set(symbols))

    if hasattr(mdp, "_threadsafe_cache_put"):
        n_warm = warm_mdp_cache(mdp, settles, symbols, [d.date() for d in grid_dates])
        logger.info("warmed %d (date,symbol) pricer-cache entries", n_warm)

    grid = TimeGrid([datetime.datetime(d.year, d.month, d.day, 16, 0) for d in grid_dates])
    strategy = QueryStrategy(name="serff-engine-replay", triggers=triggers)
    bt = QueryDrivenBacktest(time_grid=grid, mdp=mdp, strategy=strategy, show_progress=show_progress)
    bt.run()

    mtm = pd.Series(
        {pd.Timestamp(ts.date()): float(v) for ts, v in bt.mtm_history.items()}, name="engine_mtm"
    ).sort_index()
    mtm_pu = (mtm / unit_scale).rename("engine_mtm_per_unit")

    comparison = pd.DataFrame({"engine_per_unit": mtm_pu})
    summary: Dict[str, Any] = {
        "unit_scale": unit_scale,
        "n_trades_replayed": int(len(replay)),
        "max_hedge_rounding_err_contracts_per_unit": float(replay["rounding_err_contracts_per_unit"].max()) if len(replay) else 0.0,
        "engine_final_mtm_per_unit": float(mtm_pu.iloc[-1]) if len(mtm_pu) else np.nan,
    }
    if panel_daily is not None and not panel_daily.empty:
        panel_cum = panel_daily["pnl_net"].cumsum()
        panel_cum.index = pd.DatetimeIndex(panel_cum.index)
        comparison["panel_per_unit"] = panel_cum.reindex(comparison.index).ffill()
        comparison["diff"] = comparison["engine_per_unit"] - comparison["panel_per_unit"]
        aligned = comparison.dropna()
        if len(aligned):
            summary["panel_final_per_unit"] = float(aligned["panel_per_unit"].iloc[-1])
            summary["tracking_diff_final"] = float(aligned["diff"].iloc[-1])
            summary["tracking_diff_max_abs"] = float(aligned["diff"].abs().max())
            summary["tracking_corr_daily"] = float(
                aligned["engine_per_unit"].diff().corr(aligned["panel_per_unit"].diff())
            )

    return SerffEngineResult(
        backtest=bt,
        mtm=mtm,
        mtm_per_unit=mtm_pu,
        trades=replay,
        unit_scale=unit_scale,
        comparison=comparison,
        summary=summary,
    )

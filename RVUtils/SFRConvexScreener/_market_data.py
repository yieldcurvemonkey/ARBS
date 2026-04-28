"""Market data loader: thin wrapper around existing MDP infra.

Returns an immutable ``SFRMarketData`` snapshot containing the curve handle,
per-contract futures snapshot, an N-day historical price panel for the
correlation matrix, and a SABR smile per contract.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _imm_cutoff, _next_contracts
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

from RVUtils.SFRConvexScreener._types import SFRConvexScreenerConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SFRMarketData:
    as_of: datetime.date
    symbols: Tuple[str, ...]
    sr3_symbols: Tuple[str, ...]
    curve_handle: Any
    futures_df: pd.DataFrame
    price_panel: pd.DataFrame
    smiles: Dict[str, Any]
    warnings: Tuple[str, ...] = ()


def _sr3_to_sfr(sym: str) -> str:
    return sym.replace("SR3", "SFR", 1)


def _sfr_to_sr3(sym: str) -> str:
    return sym.replace("SFR", "SR3", 1)


def resolve_universe_symbols(
    config: SFRConvexScreenerConfig, *, as_of: datetime.date
) -> Tuple[str, ...]:
    sr3_syms = _next_contracts(
        as_of, prefix="SR3", count=config.universe_size,
        valid_months=[3, 6, 9, 12], cutoff_fn=_imm_cutoff,
    )
    return tuple(_sr3_to_sfr(s) for s in sr3_syms)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _read_price(p: Any) -> float:
    for attr in ("_price", "price"):
        v = getattr(p, attr, None)
        if v is not None:
            return _safe_float(v)
    return float("nan")


def _read_rate(p: Any) -> float:
    for attr in ("_rate", "rate"):
        v = getattr(p, attr, None)
        if v is not None:
            return _safe_float(v)
    return float("nan")


def _read_meta(p: Any, key: str) -> Any:
    meta = getattr(p, "_meta_data", None) or getattr(p, "meta_data", None) or {}
    if isinstance(meta, dict):
        return meta.get(key)
    return None


def load_market_data(
    config: SFRConvexScreenerConfig, *, as_of: datetime.date
) -> SFRMarketData:
    sfr_symbols = resolve_universe_symbols(config, as_of=as_of)
    sr3_symbols = tuple(_sfr_to_sr3(s) for s in sfr_symbols)
    warnings: List[str] = []

    # 1. OIS curve
    curve_mdp = IRSwapsMDP(source=config.curve_source)
    try:
        curve_handle = curve_mdp.get_pricer(
            request={"curve_name": config.curve_name, "timestamp": as_of}
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("curve fetch failed: %s", exc)
        warnings.append(f"curve fetch failed: {exc}")
        curve_handle = None

    # 2. Futures snapshot (price + OI + volume)
    fut_mdp = STIRFutureMDP(source=config.curve_source)
    snap = fut_mdp.get_data({"symbols": list(sr3_symbols), "timestamp": as_of})
    rows: List[Dict[str, Any]] = []
    for sr3, sfr in zip(sr3_symbols, sfr_symbols):
        pricers = snap.get(sr3) or snap.get(sfr) or []
        if not pricers:
            warnings.append(f"missing futures snapshot for {sr3}")
            continue
        p = pricers[0]
        rows.append({
            "symbol": sfr,
            "price": _read_price(p),
            "rate": _read_rate(p),
            "open_interest": _read_meta(p, "openinterest"),
            "volume": _read_meta(p, "volume"),
            "effective": getattr(p, "_effective_date", None) or getattr(p, "effective_date", None),
            "maturity": getattr(p, "_maturity_date", None) or getattr(p, "maturity_date", None),
        })
    futures_df = (
        pd.DataFrame(rows).set_index("symbol") if rows else pd.DataFrame(
            columns=["price", "rate", "open_interest", "volume", "effective", "maturity"]
        )
    )

    # 3. Historical N-day price panel
    bdate_range = pd.bdate_range(end=as_of, periods=config.correlation_window).date.tolist()
    price_panel = pd.DataFrame(index=pd.Index([], name="as_of"), columns=list(sfr_symbols))
    try:
        bulk = fut_mdp.get_bulk_data({
            "symbols": list(sr3_symbols),
            "timestamps": bdate_range,
            "max_workers": 8,
        })
        rows_panel: Dict[datetime.date, Dict[str, float]] = {}
        for d, by_sym in (bulk or {}).items():
            rows_panel[d] = {}
            for sr3, sfr in zip(sr3_symbols, sfr_symbols):
                pricers = (by_sym or {}).get(sr3) or (by_sym or {}).get(sfr) or []
                if pricers:
                    rows_panel[d][sfr] = _read_price(pricers[0])
        if rows_panel:
            price_panel = pd.DataFrame(rows_panel).T.sort_index()
            price_panel = price_panel.reindex(columns=list(sfr_symbols))
    except Exception as exc:  # noqa: BLE001
        logger.warning("bulk price-panel fetch failed: %s", exc)
        warnings.append(f"bulk price-panel fetch failed: {exc}")

    # 4. SABR smiles per contract
    opt_mdp = STIRFutureOptionMDP(source=config.options_source)
    smiles: Dict[str, Any] = {}
    for sfr in sfr_symbols:
        try:
            smile = opt_mdp.fetch_sabr_smile({
                "symbol": sfr, "as_of": as_of, "strike_offsets_bps": "listed",
            })
            smiles[sfr] = smile
        except Exception as exc:  # noqa: BLE001
            logger.warning("SABR smile fetch failed for %s: %s", sfr, exc)
            warnings.append(f"smile fetch failed for {sfr}: {exc}")

    return SFRMarketData(
        as_of=as_of,
        symbols=sfr_symbols,
        sr3_symbols=sr3_symbols,
        curve_handle=curve_handle,
        futures_df=futures_df,
        price_panel=price_panel,
        smiles=smiles,
        warnings=tuple(warnings),
    )

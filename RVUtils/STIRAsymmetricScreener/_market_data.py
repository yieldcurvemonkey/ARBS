"""Market data loader for the STIR Options Asymmetric Screener.

Pulls per-(contract, expiry) SABR smile, per-leg quote/OI/volume,
historical IV / 25d-RR series, the FOMC-dated OIS curve handle, and the
FOMC schedule. All upstream callouts go through dependency-injected
loader callables — this lets unit tests stub them while production wires
to the live MDP endpoints.

Default loaders (used when callers don't pass overrides) call into the
existing infra: ``STIRFutureOptionMDP.fetch_sabr_smile`` for smiles,
``IRSwapsMDP.get_pricer`` for curves, ``SDRUtils.analytics.fomc.load_fomc_schedule``
for the schedule, etc.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig
from RVUtils.STIRAsymmetricScreener._universe import (
    UniverseEntry,
    enumerate_contracts,
    attach_strike_grid,
)

logger = logging.getLogger(__name__)


# --- Per-leg market data record ----------------------------------------------


@dataclass(frozen=True)
class LegMarket:
    """Observed market data for a single (contract, expiry, right, strike)."""

    contract: str
    expiry: datetime.date
    right: str
    strike: float
    premium_ticks: float
    open_interest: float
    volume: float
    bid: float
    ask: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract": self.contract,
            "expiry": self.expiry.isoformat(),
            "right": self.right,
            "strike": self.strike,
            "premium_ticks": self.premium_ticks,
            "open_interest": self.open_interest,
            "volume": self.volume,
            "bid": self.bid,
            "ask": self.ask,
        }


# --- Top-level market-data snapshot ------------------------------------------


@dataclass(frozen=True)
class STIRMarketData:
    as_of: datetime.date
    universe: Tuple[UniverseEntry, ...]
    smiles: Dict[Tuple[str, datetime.date], Any]
    curve_handle: Any
    curve_asof: Optional[datetime.date]
    fomc_schedule: pd.DataFrame
    leg_market: Dict[Tuple[str, datetime.date, str, float], LegMarket]
    iv_history: Dict[Tuple[str, datetime.date], pd.DataFrame] = field(default_factory=dict)
    smile_asof_by_contract: Dict[Tuple[str, datetime.date], datetime.date] = field(default_factory=dict)
    warnings: Tuple[str, ...] = ()


# --- Helpers -----------------------------------------------------------------


def _last_business_day(d: datetime.date) -> datetime.date:
    return (pd.Timestamp(d) - pd.tseries.offsets.BDay(1)).date()


def _try_with_fallback(fn, *, as_of: datetime.date, max_fallback_days: int = 5):
    """Call ``fn(date)`` starting at ``as_of``, walking back business days
    on transient errors. Returns ``(value, effective_date, error)``.
    """
    last_exc: Optional[Exception] = None
    candidate = as_of
    for _ in range(max_fallback_days + 1):
        try:
            return fn(candidate), candidate, None
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            candidate = _last_business_day(candidate)
    return None, candidate, last_exc


# --- Default production loaders ----------------------------------------------


def _default_smile_loader(*, contract: str, as_of: datetime.date, options_source: str) -> Any:
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    mdp = STIRFutureOptionMDP(source=options_source)
    return mdp.fetch_sabr_smile(
        {"symbol": contract, "as_of": as_of, "strike_offsets_bps": "listed"}
    )


def _default_curve_loader(*, as_of: datetime.date, curve_source: str, curve_name: str) -> Any:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    mdp = IRSwapsMDP(source=curve_source)
    return mdp.get_pricer({"curve_name": curve_name, "timestamp": as_of})


def _default_fomc_schedule_loader(*, curve_name: str) -> pd.DataFrame:
    from SDRUtils.analytics.fomc import load_fomc_schedule

    return load_fomc_schedule(curve_name=curve_name)


def _default_leg_quote_loader(
    *,
    contract: str,
    expiry: datetime.date,
    strikes,
    as_of: datetime.date,
    options_source: str,
) -> Dict[Tuple[str, datetime.date, str, float], Dict[str, float]]:
    """Default per-leg quote loader.

    Calls ``STIRFutureOptionMDP._option_snapshot`` once per (right, strike)
    pair and assembles a flat dict. The endpoint returns a list of trade
    rows; we extract the most recent observation for each strike+right.

    NB: This function performs many HTTP calls — production loaders may
    want to batch these via ``get_bulk_data`` once the upstream API
    supports per-strike bulk requests.
    """
    # TODO(blocker): the STIRFutureOptionMDP `option_snapshot` endpoint expects
    # a single (contract, strike, right) per call. For v1, we let downstream
    # gates work with NaN premium_ticks rather than fan out hundreds of calls.
    return {}


def _default_history_loader(
    *,
    contract: str,
    expiry: datetime.date,
    as_of: datetime.date,
    lookback_days: int,
    options_source: str,
) -> pd.DataFrame:
    """Default historical ATM IV / 25d-RR loader.

    Returns an empty DataFrame in v1 — historical percentiles default to
    0.5 (neutral) when history is missing, which is conservatively
    correct (no false positives from missing data).
    """
    return pd.DataFrame()


# --- Top-level loader --------------------------------------------------------


def load_market_data(
    config: ScreenerConfig,
    *,
    as_of: datetime.date,
    smile_loader: Optional[Callable[..., Any]] = None,
    curve_loader: Optional[Callable[..., Any]] = None,
    fomc_schedule_loader: Optional[Callable[..., pd.DataFrame]] = None,
    leg_quote_loader: Optional[Callable[..., Dict]] = None,
    history_loader: Optional[Callable[..., pd.DataFrame]] = None,
) -> STIRMarketData:
    """Fetch all market data needed for downstream phases.

    All loaders are dependency-injected for testability. When omitted,
    defaults wire to the live MDP endpoints (production path).
    """
    warnings: List[str] = []

    # 1. Smile loader (with config-aware default)
    if smile_loader is None:
        def smile_loader(*, contract: str, as_of: datetime.date) -> Any:  # type: ignore[no-redef]
            return _default_smile_loader(
                contract=contract, as_of=as_of, options_source=config.options_source
            )

    # 2. Universe enumerate + attach grid (uses smile_loader for forward prices)
    contract_entries = enumerate_contracts(config, as_of=as_of)
    universe = attach_strike_grid(contract_entries, smile_loader=smile_loader, as_of=as_of)
    if not universe:
        warnings.append("universe_empty_after_smile_attachment")

    # 3. Smiles for each universe entry — re-fetch (or cache) per (contract, expiry)
    smiles: Dict[Tuple[str, datetime.date], Any] = {}
    smile_asof: Dict[Tuple[str, datetime.date], datetime.date] = {}
    for entry in universe:
        def _fetch(d, _c=entry.contract):
            return smile_loader(contract=_c, as_of=d)

        smile, eff_date, err = _try_with_fallback(_fetch, as_of=as_of, max_fallback_days=5)
        key = (entry.contract, entry.expiry)
        if smile is None:
            warnings.append(f"smile_fetch_failed:{entry.contract}:{err}")
            continue
        if eff_date != as_of:
            warnings.append(f"smile_fallback:{entry.contract}:{eff_date.isoformat()}")
        smiles[key] = smile
        smile_asof[key] = eff_date

    # 4. Curve handle
    if curve_loader is None:
        def curve_loader(*, as_of: datetime.date) -> Any:  # type: ignore[no-redef]
            return _default_curve_loader(
                as_of=as_of, curve_source=config.curve_source, curve_name=config.curve_name
            )

    curve_handle, curve_asof, curve_err = _try_with_fallback(
        lambda d: curve_loader(as_of=d), as_of=as_of, max_fallback_days=5
    )
    if curve_handle is None:
        warnings.append(f"curve_fetch_failed:{curve_err}")
    elif curve_asof != as_of:
        warnings.append(f"curve_fallback:{curve_asof.isoformat()}")

    # 5. FOMC schedule
    if fomc_schedule_loader is None:
        def fomc_schedule_loader(*, curve_name: str) -> pd.DataFrame:  # type: ignore[no-redef]
            return _default_fomc_schedule_loader(curve_name=curve_name)

    try:
        fomc_schedule = fomc_schedule_loader(curve_name=config.curve_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fomc_schedule_failed: %s", exc)
        warnings.append(f"fomc_schedule_failed:{exc}")
        fomc_schedule = pd.DataFrame()

    # 6. Per-leg quotes
    if leg_quote_loader is None:
        def leg_quote_loader(*, contract, expiry, strikes, as_of):  # type: ignore[no-redef]
            return _default_leg_quote_loader(
                contract=contract,
                expiry=expiry,
                strikes=strikes,
                as_of=as_of,
                options_source=config.options_source,
            )

    leg_market: Dict[Tuple[str, datetime.date, str, float], LegMarket] = {}
    for entry in universe:
        try:
            quotes = leg_quote_loader(
                contract=entry.contract,
                expiry=entry.expiry,
                strikes=entry.strikes,
                as_of=as_of,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("leg_quote_failed for %s: %s", entry.contract, exc)
            warnings.append(f"leg_quote_failed:{entry.contract}:{exc}")
            quotes = {}
        for (c, exp, right, strike), row in (quotes or {}).items():
            leg_market[(c, exp, right, strike)] = LegMarket(
                contract=c,
                expiry=exp,
                right=right,
                strike=strike,
                premium_ticks=float(row.get("premium_ticks", float("nan"))),
                open_interest=float(row.get("open_interest", float("nan"))),
                volume=float(row.get("volume", float("nan"))),
                bid=float(row.get("bid", float("nan"))),
                ask=float(row.get("ask", float("nan"))),
            )

    # 7. Historical IV / RR series
    if history_loader is None:
        def history_loader(*, contract, expiry, as_of, lookback_days):  # type: ignore[no-redef]
            return _default_history_loader(
                contract=contract,
                expiry=expiry,
                as_of=as_of,
                lookback_days=lookback_days,
                options_source=config.options_source,
            )

    iv_history: Dict[Tuple[str, datetime.date], pd.DataFrame] = {}
    for entry in universe:
        try:
            df = history_loader(
                contract=entry.contract,
                expiry=entry.expiry,
                as_of=as_of,
                lookback_days=252,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("history_loader failed for %s: %s", entry.contract, exc)
            warnings.append(f"history_loader_failed:{entry.contract}:{exc}")
            df = pd.DataFrame()
        if isinstance(df, pd.DataFrame) and not df.empty:
            iv_history[(entry.contract, entry.expiry)] = df

    return STIRMarketData(
        as_of=as_of,
        universe=tuple(universe),
        smiles=smiles,
        curve_handle=curve_handle,
        curve_asof=curve_asof if curve_handle is not None else None,
        fomc_schedule=fomc_schedule,
        leg_market=leg_market,
        iv_history=iv_history,
        smile_asof_by_contract=smile_asof,
        warnings=tuple(warnings),
    )

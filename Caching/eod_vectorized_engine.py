"""Vectorized EOD rate computation engine.

Computes par swap rates from raw discount factor nodes using NumPy,
bypassing per-tenor QuantLib/rateslib curve reconstruction.
"""
from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import QuantLib as ql

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tenor parsing
# ---------------------------------------------------------------------------
_TENOR_RE = re.compile(
    r"^(?:(\d+[MY]))?(\d+[MY])$",
    re.IGNORECASE,
)


def parse_tenor(tenor: str) -> Tuple[Optional[str], str]:
    """Parse a tenor string into (forward_period, swap_period).

    Examples:
        "5Y"    -> (None, "5Y")
        "2Y3Y"  -> ("2Y", "3Y")
        "18M5Y" -> ("18M", "5Y")
        "6M"    -> (None, "6M")
    """
    tenor = tenor.strip().upper()
    m = _TENOR_RE.match(tenor)
    if m is None:
        raise ValueError(f"Cannot parse tenor: {tenor!r}")
    fwd_part, swap_part = m.group(1), m.group(2)
    return (fwd_part, swap_part)


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------
def _period_to_ql(period_str: str) -> ql.Period:
    """Convert e.g. '18M' or '5Y' to a QuantLib Period."""
    period_str = period_str.strip().upper()
    num = int(period_str[:-1])
    unit_char = period_str[-1]
    if unit_char == "M":
        return ql.Period(num, ql.Months)
    elif unit_char == "Y":
        return ql.Period(num, ql.Years)
    raise ValueError(f"Unknown period unit: {unit_char!r}")


def _to_py_date(d) -> datetime.date:
    """Convert any date-like (Timestamp, numpy.datetime64, date, datetime) to datetime.date."""
    if isinstance(d, datetime.date) and not isinstance(d, datetime.datetime):
        return d
    if isinstance(d, datetime.datetime):
        return d.date()
    if isinstance(d, pd.Timestamp):
        return d.date()
    # numpy.datetime64 or other
    return pd.Timestamp(d).date()


def _ql_date(d: datetime.date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _py_date(d: ql.Date) -> datetime.date:
    return datetime.date(d.year(), d.month(), d.dayOfMonth())


# ---------------------------------------------------------------------------
# Payment schedule
# ---------------------------------------------------------------------------
_US_CALENDAR = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
_BDC = ql.ModifiedFollowing
_EOM = False  # no end-of-month convention for SOFR swaps


@dataclass(frozen=True)
class PaymentSchedule:
    """Pre-computed payment schedule for a fixed leg."""
    effective_date: datetime.date
    maturity_date: datetime.date
    payment_dates: List[datetime.date]
    accrual_fractions: List[float]  # ACT/360 day count fractions


def build_payment_schedule(
    trading_date: datetime.date,
    tenor: str,
    *,
    settlement_days: int = 2,
    calendar: ql.Calendar = _US_CALENDAR,
    frequency: int = ql.Annual,
    day_counter: ql.DayCounter = ql.Actual360(),
    business_day_convention: int = _BDC,
) -> PaymentSchedule:
    """Build the fixed-leg payment schedule for a given tenor on a trading date."""
    fwd_period, swap_period = parse_tenor(tenor)

    ql_trade_date = _ql_date(trading_date)
    ql_spot = calendar.advance(ql_trade_date, settlement_days, ql.Days)

    if fwd_period is not None:
        ql_effective = calendar.advance(ql_spot, _period_to_ql(fwd_period), business_day_convention, _EOM)
    else:
        ql_effective = ql_spot

    ql_maturity = calendar.advance(ql_effective, _period_to_ql(swap_period), business_day_convention, _EOM)

    schedule = ql.Schedule(
        ql_effective,
        ql_maturity,
        ql.Period(frequency),
        calendar,
        business_day_convention,
        business_day_convention,
        ql.DateGeneration.Forward,
        _EOM,
    )

    dates = list(schedule)
    payment_dates: List[datetime.date] = []
    accrual_fractions: List[float] = []
    for i in range(1, len(dates)):
        payment_dates.append(_py_date(dates[i]))
        accrual_fractions.append(day_counter.yearFraction(dates[i - 1], dates[i]))

    return PaymentSchedule(
        effective_date=_py_date(ql_effective),
        maturity_date=_py_date(ql_maturity),
        payment_dates=payment_dates,
        accrual_fractions=accrual_fractions,
    )


# ---------------------------------------------------------------------------
# Discount factor interpolation
# ---------------------------------------------------------------------------
def interpolate_discount_factors(
    base_date: datetime.date,
    node_dates: Sequence[datetime.date],
    node_dfs: np.ndarray,
    target_dates: Sequence[datetime.date],
) -> np.ndarray:
    """Log-linear interpolation of discount factors.

    Returns NaN for target dates beyond the last node.
    """
    t_nodes = np.array([(d - base_date).days for d in node_dates], dtype=np.float64)
    t_targets = np.array([(d - base_date).days for d in target_dates], dtype=np.float64)

    log_dfs = np.log(np.maximum(node_dfs, 1e-20))  # guard against log(0)
    log_interp = np.interp(t_targets, t_nodes, log_dfs)

    result = np.exp(log_interp)

    # Mark extrapolated points as NaN
    max_t = t_nodes[-1]
    result[t_targets > max_t + 0.5] = np.nan  # 0.5 day tolerance

    return result


# ---------------------------------------------------------------------------
# Par swap rate
# ---------------------------------------------------------------------------
def compute_par_swap_rate(
    *,
    df_effective: float,
    df_maturity: float,
    df_at_payments: np.ndarray,
    accrual_fractions: np.ndarray,
) -> float:
    """Compute par swap rate from discount factors.

    rate = (DF_eff - DF_mat) / SUM(DF_i * tau_i)
    """
    if np.isnan(df_effective) or np.isnan(df_maturity) or np.any(np.isnan(df_at_payments)):
        return np.nan
    annuity = np.dot(df_at_payments, accrual_fractions)
    if annuity == 0.0:
        return np.nan
    return (df_effective - df_maturity) / annuity


# ---------------------------------------------------------------------------
# Full panel computation
# ---------------------------------------------------------------------------
def compute_eod_rate_panel(
    raw_nodes_df: pd.DataFrame,
    tenors: Sequence[str],
    *,
    settlement_days: int = 2,
    calendar: ql.Calendar = _US_CALENDAR,
    frequency: int = ql.Annual,
    day_counter: ql.DayCounter = ql.Actual360(),
) -> pd.DataFrame:
    """Compute a (dates x tenors) panel of par swap rates from raw curve nodes.

    Parameters
    ----------
    raw_nodes_df : DataFrame
        Must have columns: trading_date, node_dates (list), discount_factors (list).
        One row per trading date.
    tenors : sequence of str
        Tenor strings like "2Y", "5Y", "1Y2Y", etc.
    settlement_days : int
        T+N settlement convention (default 2).

    Returns
    -------
    DataFrame with DatetimeIndex (trading_date) and one column per tenor,
    values are par swap rates as decimals (e.g. 0.04 = 4%).
    """
    if raw_nodes_df.empty or not tenors:
        return pd.DataFrame()

    trading_dates = [_to_py_date(d) for d in raw_nodes_df["trading_date"]]

    # Filter tenors to only those parseable by our engine (skip FOMC, IMM, etc.)
    valid_tenors: List[str] = []
    for tenor in tenors:
        try:
            parse_tenor(tenor)
            valid_tenors.append(tenor)
        except ValueError:
            logger.debug("Skipping unsupported tenor for vectorized engine: %s", tenor)
    tenors = valid_tenors
    if not tenors:
        return pd.DataFrame()

    # Pre-build schedules: {tenor: {trading_date: PaymentSchedule}}
    schedules: Dict[str, Dict[datetime.date, PaymentSchedule]] = {}
    for tenor in tenors:
        tenor_schedules: Dict[datetime.date, PaymentSchedule] = {}
        for td in trading_dates:
            try:
                tenor_schedules[td] = build_payment_schedule(
                    td,
                    tenor,
                    settlement_days=settlement_days,
                    calendar=calendar,
                    frequency=frequency,
                    day_counter=day_counter,
                )
            except Exception:
                logger.debug("Schedule build failed for %s on %s", tenor, td, exc_info=True)
        schedules[tenor] = tenor_schedules

    # Compute rates
    results: Dict[str, List[float]] = {tenor: [] for tenor in tenors}
    for _, row in raw_nodes_df.iterrows():
        td = _to_py_date(row["trading_date"])
        node_dates_raw = row["node_dates"]
        dfs_raw = row["discount_factors"]

        # Convert node dates (handles numpy.datetime64, Timestamp, date, etc.)
        node_dates = [_to_py_date(d) for d in node_dates_raw]
        node_dfs = np.array(dfs_raw, dtype=np.float64)

        for tenor in tenors:
            sched = schedules[tenor].get(td)
            if sched is None:
                results[tenor].append(np.nan)
                continue

            # Interpolate DFs at effective, maturity, and all payment dates
            all_target_dates = [sched.effective_date] + sched.payment_dates
            interp_dfs = interpolate_discount_factors(
                base_date=node_dates[0],
                node_dates=node_dates,
                node_dfs=node_dfs,
                target_dates=all_target_dates,
            )

            df_effective = interp_dfs[0]
            df_at_payments = interp_dfs[1:]
            df_maturity = df_at_payments[-1]  # last payment = maturity

            rate = compute_par_swap_rate(
                df_effective=df_effective,
                df_maturity=df_maturity,
                df_at_payments=df_at_payments,
                accrual_fractions=np.array(sched.accrual_fractions, dtype=np.float64),
            )
            results[tenor].append(rate)

    out = pd.DataFrame(results, index=pd.DatetimeIndex(trading_dates, name="trading_date"))
    return out


# ---------------------------------------------------------------------------
# Persistence — write results to all stores
# ---------------------------------------------------------------------------
def _build_ts_symbol(source: str, curve_name: str, fingerprint: str) -> str:
    """Build the computed timeseries symbol key."""
    return f"IRS::{source}::{curve_name}::{fingerprint}"


def _tenor_fingerprint(tenor: str) -> str:
    """Build a stable fingerprint for a tenor query.

    Matches the format used by TB.IRSwapsTB._query_fingerprint for
    UnifiedQuery(curve=..., tenor=tenor, value=IRS_RATE).
    """
    return f"rate_{tenor.upper()}"


def compute_and_persist_eod_panel(
    raw_nodes_df: pd.DataFrame,
    tenors: Sequence[str],
    *,
    curve_name: str,
    source: str,
    computed_ts_store: Optional[object] = None,
    curve_store: Optional[object] = None,
    settlement_days: int = 2,
) -> Dict[str, object]:
    """Compute vectorized EOD rate panel and persist to all stores.

    Returns a summary dict with status, counts, and symbol keys.
    """
    import time as _time

    started = _time.perf_counter()
    panel = compute_eod_rate_panel(
        raw_nodes_df=raw_nodes_df,
        tenors=tenors,
        settlement_days=settlement_days,
    )

    if panel.empty:
        return {"status": "empty", "rates_computed": 0, "symbols": [], "elapsed_seconds": 0.0}

    trading_dates = [_to_py_date(d) for d in panel.index]
    symbols: List[str] = []

    # --- Write to ComputedTimeseriesStore (DuckDB L1 + Parquet TS) ---
    if computed_ts_store is not None:
        rows_by_symbol: Dict[str, List[Tuple]] = {}
        for tenor in tenors:
            if tenor not in panel.columns:
                continue
            fingerprint = _tenor_fingerprint(tenor)
            symbol = _build_ts_symbol(source, curve_name, fingerprint)
            if symbol not in symbols:
                symbols.append(symbol)
            tenor_rows = []
            for td, rate in zip(trading_dates, panel[tenor]):
                if np.isnan(rate):
                    continue
                tenor_rows.append((td, tenor, float(rate)))
            if tenor_rows:
                rows_by_symbol[symbol] = tenor_rows

        if rows_by_symbol:
            try:
                computed_ts_store.append_many_rows(rows_by_symbol=rows_by_symbol)
            except Exception:
                logger.warning("Failed to write vectorized rates to computed TS store", exc_info=True)

    # --- Write to CurveStore analytics panel ---
    if curve_store is not None:
        for td in trading_dates:
            row_mask = panel.index == pd.Timestamp(td)
            if not row_mask.any():
                continue
            analytics_row = panel.loc[row_mask].copy()
            # Rename columns to rate_{tenor} format for analytics panel
            analytics_row.columns = [f"rate_{t}" for t in analytics_row.columns]
            analytics_row.insert(0, "timestamp_utc", pd.Timestamp(td, tz="UTC"))
            analytics_row.insert(1, "trading_date", td)
            try:
                curve_store.write_analytics_day(
                    curve_name, td, analytics_row, overwrite=True,
                )
            except Exception:
                logger.warning(
                    "Failed to write analytics panel for %s/%s",
                    curve_name, td, exc_info=True,
                )

    elapsed = _time.perf_counter() - started
    rates_computed = int(panel.notna().sum().sum())
    return {
        "status": "ok",
        "rates_computed": rates_computed,
        "tenor_count": len(tenors),
        "date_count": len(trading_dates),
        "symbols": symbols,
        "elapsed_seconds": round(elapsed, 3),
    }

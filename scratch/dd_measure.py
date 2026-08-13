"""Shared wiring for the repricing-pass measurements.

Deliberately NOT ``dd_common``. That module is the parallel wiring the probes
used before ``SDRUtils/dealer_direction/midprice.py`` existed; a measurement of
the production path is only evidence about the production path if it runs the
production path, so everything here goes through the shipped module.
"""
from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import warnings

import pandas as pd

from SDRUtils.dealer_direction import snapshot
from SDRUtils.dealer_direction.types import Clocks, Unit

LEG_COLS = """
    trade_id, package_id, as_of_date, rate_index_clean,
    execution_timestamp, original_execution_timestamp, event_timestamp,
    event_timestamp_granularity, lifecycle_type,
    effective_date, expiration_date, notional, fixed_rate,
    tenor_years, tenor_label, trade_type, venue, platform_identifier,
    special_tenor_type, fomc_meeting_label, is_off_date,
    is_capped, is_block, is_off_market, other_payment_ufro
"""


def connect():
    import psycopg2

    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    return psycopg2.connect(resolve_pg_url())


def read_sql(conn, sql, params=None) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")           # pandas' non-SQLAlchemy notice
        return pd.read_sql(sql, conn, params=params)


def unit_from_leg(row, *, with_upfront: bool = True) -> tuple:
    """One tape leg as a single-leg :class:`Unit`, plus its snapped instant.

    A leg, not a package: the coverage measurement is a **leg**-level success
    rate, so each leg is asked to price on its own terms. Packages assemble from
    exactly these marks, and a package that fails does so because one of its
    legs did.
    """
    ts, field = snapshot.pricing_timestamp(row)
    clocks = Clocks(
        pricing=ts,
        execution=row.get("execution_timestamp"),
        event=row.get("event_timestamp"),
        visibility=row.get("event_timestamp"),
        visibility_source="NOT_SET_FOR_THIS_MEASUREMENT",
    )
    ufro = row.get("other_payment_ufro")
    upfront = float(ufro) if (with_upfront and ufro is not None
                              and not pd.isna(ufro) and float(ufro) > 0) else None
    legs = pd.DataFrame([{
        "trade_id": row["trade_id"],
        "effective_date": row["effective_date"],
        "expiration_date": row["expiration_date"],
        "notional": row["notional"],
        "fixed_rate": row["fixed_rate"],
        "is_capped": bool(row.get("is_capped") or False),
    }])
    unit = Unit(
        unit_key=str(row["trade_id"]),
        kind="OUTRIGHT",
        legs=legs,
        package_id=row.get("package_id"),
        rate_index=row["rate_index_clean"],
        as_of_date=pd.Timestamp(row["as_of_date"]).date(),
        venue_class=row.get("venue") or "VENUE_UNKNOWN",
        clocks=clocks,
        upfront=upfront,
    )
    return unit, snapshot.snap_instant(ts), field


def even_subsample(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """``n`` rows spread evenly over the frame's own order, not the first ``n``.

    The pool is ordered by execution time, so the first ``n`` would be 2024 only.
    A fresh random draw would not be reproducible.
    """
    import numpy as np

    if len(df) <= n:
        return df.reset_index(drop=True)
    idx = np.unique(np.linspace(0, len(df) - 1, n).round().astype(int))
    return df.iloc[idx].reset_index(drop=True)


def describe(x, label: str, width: int = 22) -> None:
    x = pd.Series(x).dropna()
    if len(x) < 5:
        print(f"  {label:{width}s} n={len(x):5d}  (too few)")
        return
    print(f"  {label:{width}s} n={len(x):5d}  median {x.median():+.4f}  "
          f"IQR [{x.quantile(.25):+.4f}, {x.quantile(.75):+.4f}] "
          f"(w={x.quantile(.75) - x.quantile(.25):.3f})  "
          f"|d|<=0.1bp {(x.abs() <= 0.1).mean():5.1%}  frac>0 {(x > 0).mean():5.1%}")

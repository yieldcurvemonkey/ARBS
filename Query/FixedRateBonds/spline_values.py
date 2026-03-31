"""Spline value computation bridge for the FRB Value pattern.

Mirrors the ``carry_roll.py`` pattern: provides ``compute_spline_for_date()``
which lazily builds (or retrieves from cache) a :class:`CashSpline`, and
``expand_pricer_universe_for_spline()`` which ensures the pricer dict covers
the full UST universe needed for cross-sectional fitting.

Used by :class:`FixedRateBondValueFunctionMap` to resolve ``SPLINE_SPREAD``,
``SPLINE_Z_SCORE``, ``SPLINE_RMSE``, and ``SPLINE_RMSE_BUCKET`` values.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JPM-style maturity buckets (from "Sweating the small stuff", May 2016)
# ---------------------------------------------------------------------------
MATURITY_BUCKETS: Dict[str, tuple[float, float]] = {
    "0-2Y": (0.0, 2.0),
    "2-3Y": (2.0, 3.0),
    "3-5Y": (3.0, 5.0),
    "5-7Y": (5.0, 7.0),
    "7-10Y": (7.0, 10.0),
    "10-15Y": (10.0, 15.0),
    "15-20Y": (15.0, 20.0),
    "20-30Y": (20.0, 30.0),
}


def parse_bucket(bucket: str) -> tuple[float, float]:
    """Resolve a bucket name to ``(lo, hi)`` TTM bounds.

    Accepts dictionary keys like ``"7-10Y"`` as well as the sentinel
    ``"ALL"`` which returns ``(0, 100)``.
    """
    if bucket.upper() == "ALL":
        return (0.0, 100.0)
    if bucket in MATURITY_BUCKETS:
        return MATURITY_BUCKETS[bucket]
    raise ValueError(
        f"Unknown maturity bucket {bucket!r}. "
        f"Choose from {list(MATURITY_BUCKETS.keys())} or 'ALL'."
    )


# ---------------------------------------------------------------------------
# Universe expansion (reuses carry_roll infrastructure)
# ---------------------------------------------------------------------------
def expand_pricer_universe_for_spline(
    *,
    pricers: Dict[str, Any],
    as_of_date: datetime.date,
    min_ttm: float = 0.5,
) -> Dict[str, Any]:
    """Expand a pricer dict to the full UST universe needed for spline fitting.

    Delegates to the existing ``expand_pricer_universe_for_carry_roll`` which
    fetches reference data, filters by TTM / rank, and returns an expanded
    pricer dict.
    """
    from Query.FixedRateBonds.carry_roll import expand_pricer_universe_for_carry_roll

    return expand_pricer_universe_for_carry_roll(
        pricers=pricers,
        as_of_date=as_of_date,
        min_ttm=min_ttm,
    )


# ---------------------------------------------------------------------------
# Core: build / cache spline for a date
# ---------------------------------------------------------------------------
def compute_spline_for_date(
    pricers: Dict[str, Any],
    as_of_date: datetime.date,
    config: Optional[Any] = None,
) -> Optional[Any]:
    """Build or retrieve a cached :class:`CashSpline` for *as_of_date*.

    Mirrors :func:`carry_roll.compute_carry_roll_frame` — checks the 3-tier
    cache first, builds from pricers on miss, then caches the result.

    Parameters
    ----------
    pricers : dict
        ``{cusip: pricer}`` mapping.  Should cover the full universe
        (call :func:`expand_pricer_universe_for_spline` first if needed).
    as_of_date : date
    config : CashSplineConfig, optional
        Defaults to ``JPM_PAR_CURVE_CONFIG``.

    Returns
    -------
    CashSpline or None
    """
    from MDP.FixedRateBonds.cash_spline import (
        CashSpline,
        CashSplineBuilder,
        CashSplineConfig,
        JPM_PAR_CURVE_CONFIG,
        get_cached_spline,
        put_cached_spline,
    )

    if config is None:
        config = JPM_PAR_CURVE_CONFIG

    # --- Cache check ---
    cached = get_cached_spline(as_of_date, config)
    if cached is not None:
        return cached

    # --- Build from pricers ---
    if not pricers:
        return None

    rows = []
    for cusip, pricer in pricers.items():
        try:
            ttm = float(pricer.time_to_maturity())
            ytm_val = float(pricer.ytm())
            meta = pricer.meta() if hasattr(pricer, "meta") else {}
            rank = None
            if isinstance(meta, dict):
                rank = meta.get("rank")
            elif hasattr(meta, "rank"):
                rank = meta.rank

            row: Dict[str, Any] = {
                "cusip": str(meta.get("cusip", cusip) if isinstance(meta, dict) else cusip),
                "ttm": ttm,
                "ytm": ytm_val,
            }
            if rank is not None:
                row["rank"] = rank
            rows.append(row)
        except Exception:
            continue

    if not rows:
        return None

    bond_df = pd.DataFrame(rows)

    # --- BPV weighting ---
    weights = None
    if config.weighting == "bpv":
        bpv_vals = []
        for cusip, pricer in pricers.items():
            try:
                mdur = float(pricer.mod_duration())
                dp = float(pricer.dirty_price())
                bpv_vals.append(mdur * dp / 10_000.0)
            except Exception:
                bpv_vals.append(np.nan)
        if bpv_vals:
            bpv_arr = np.array(bpv_vals, dtype=float)
            inv_bpv = np.where(np.isfinite(bpv_arr) & (bpv_arr > 0), 1.0 / bpv_arr, 0.0)
            if inv_bpv.sum() > 0:
                weights = inv_bpv / inv_bpv.sum()

    # --- Fit ---
    builder = CashSplineBuilder(config)
    try:
        spline = builder.fit(
            ttm=bond_df["ttm"].to_numpy(),
            y=bond_df["ytm"].to_numpy(),
            cusips=bond_df["cusip"].to_numpy(),
            ranks=bond_df["rank"].to_numpy() if "rank" in bond_df.columns else None,
            weights=weights,
            as_of_date=as_of_date,
        )
    except (ValueError, Exception) as exc:
        logger.warning("Spline fit failed for %s: %s", as_of_date, exc)
        return None

    # --- Cache ---
    put_cached_spline(spline)
    return spline

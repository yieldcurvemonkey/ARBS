"""Structure carry / 3M roll-down helpers.

Two things to compute:

* ``current_level_bp(legs, futures_df)``: the structure's *current* rate
  level in bp = ``100 * sum(weight * rate)``. Doesn't need the OIS curve
  — just reads contract rates from the futures snapshot. This is what
  the design doc Section 5.1 calls "current_level_bp".
* ``structure_rolldown_bp(legs, curve_handle, curve_name, horizon)``: the
  3M roll-down via ``IRSwapValue.ROLL_BPS_RUNNING`` per IMM-IMM tenor.
  Best-effort; returns ``nan`` on failure (curve mismatches, missing
  schedule, etc.).
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from RVUtils.SFRConvexScreener._types import Leg

logger = logging.getLogger(__name__)


_IMM_MONTH_MAP = {"H": 3, "M": 6, "U": 9, "Z": 12}
_NEXT_IMM_CODE = {"H": "M", "M": "U", "U": "Z", "Z": "H"}


def sfr_to_imm_tenor(symbol: str) -> str:
    """Convert ``SFR{code}{yy}`` to an IMM-IMM swap tenor string.

    Example: ``SFRZ26 → IMM_Z2026xIMM_H2027``.

    Raises ValueError on unrecognised input.
    """
    m = re.match(r"^SFR([HMUZ])(\d{2})$", symbol.upper())
    if not m:
        raise ValueError(f"unrecognised SFR symbol: {symbol!r}")
    code, yy = m.group(1), int(m.group(2))
    full_year = 2000 + yy
    next_code = _NEXT_IMM_CODE[code]
    next_year = full_year + (1 if code == "Z" else 0)
    return f"IMM_{code}{full_year}xIMM_{next_code}{next_year}"


def current_level_bp(
    legs: Sequence[Leg],
    *,
    futures_df: pd.DataFrame,
) -> float:
    """Current structure rate level in bp = ``100 * Σ weight_i × rate_i``.

    Reads rates directly from the futures snapshot — no curve needed.
    Returns ``nan`` if any leg's rate is missing.
    """
    if futures_df is None or futures_df.empty or "rate" not in futures_df.columns:
        return float("nan")
    total = 0.0
    for leg in legs:
        try:
            r = float(futures_df.loc[leg.contract, "rate"])
        except (KeyError, TypeError, ValueError):
            return float("nan")
        if not np.isfinite(r):
            return float("nan")
        total += float(leg.weight) * r
    return total * 100.0


def _curve_reference_date(curve_handle: Any) -> Any:
    """Best-effort extraction of the curve's reference date.

    Falls back to "live" if the handle doesn't expose ``reference_date()``.
    """
    if curve_handle is None:
        return "live"
    for attr in ("reference_date", "as_of_date", "as_of"):
        v = getattr(curve_handle, attr, None)
        if callable(v):
            try:
                return v()
            except Exception:  # noqa: BLE001
                continue
        if v is not None:
            return v
    return "live"


def structure_rolldown_bp(
    legs: Sequence[Leg],
    *,
    curve_handle: Any,
    curve_name: str,
    horizon: str = "3m",
) -> float:
    """Compute the 3M roll-down (bp) of a long-rate structure via
    ``IRSwapValue.ROLL_BPS_RUNNING`` summed with leg weights.

    Returns ``nan`` if the IRSwapQuery integration fails for any leg.
    """
    if curve_handle is None:
        return float("nan")
    try:
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapValue import IRSwapValue
    except Exception as exc:  # noqa: BLE001
        logger.warning("IRSwapQuery import failed: %s", exc)
        return float("nan")

    ref_dt = _curve_reference_date(curve_handle)
    roll_bp = 0.0
    try:
        for leg in legs:
            tenor = sfr_to_imm_tenor(leg.contract)
            q = IRSwapQuery(curve=curve_name, tenor=tenor).resolve_query(
                ref_dt, pricer_or_curve=curve_handle,
            )
            pkg, rws = q.resolve_package(pricer_or_curve=curve_handle)
            vmap = q.build_value_map(
                pricer_or_curve=curve_handle, package=pkg, risk_weights=rws,
            )
            roll_bp += float(leg.weight) * float(
                vmap.apply(value=IRSwapValue.ROLL_BPS_RUNNING, horizon=horizon).real
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("structure rolldown computation failed: %s", exc)
        return float("nan")
    return float(roll_bp)


# Backwards-compat thin wrapper — historically the screener called this
# helper for both "carry" (current level) and "rolldown". The new orchestrator
# uses `current_level_bp` and `structure_rolldown_bp` directly.
def structure_carry_roll_bp(
    legs: Sequence[Leg],
    *,
    curve_handle: Any,
    curve_name: str,
    horizon: str = "3m",
    futures_df: pd.DataFrame = None,
):
    level = current_level_bp(legs, futures_df=futures_df) if futures_df is not None else float("nan")
    roll = structure_rolldown_bp(
        legs, curve_handle=curve_handle, curve_name=curve_name, horizon=horizon,
    )
    return level, roll

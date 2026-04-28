"""Wire structure carry / 3M roll-down via IRSwapQuery + ROLL_BPS_RUNNING.

Pure-string helper ``sfr_to_imm_tenor`` is unit-tested offline; the curve-aware
``structure_carry_roll_bp`` requires a live curve handle and is exercised only
through the integration test in :mod:`tests/test_sfr_convex_screener_orchestrator`.
"""

from __future__ import annotations

import logging
import re
from typing import Sequence, Tuple

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


def structure_carry_roll_bp(
    legs: Sequence[Leg],
    *,
    curve_handle,
    curve_name: str,
    horizon: str = "3m",
) -> Tuple[float, float]:
    """Compute carry (rate today) and 3M roll-down (bp/3M) for the structure.

    Returns ``(carry_bp, rolldown_bp)``. Either may be ``nan`` if the
    underlying query fails.
    """
    try:
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapValue import IRSwapValue
    except Exception as exc:  # noqa: BLE001
        logger.warning("IRSwapQuery import failed: %s", exc)
        return float("nan"), float("nan")

    carry_bp = 0.0
    roll_bp = 0.0
    try:
        for leg in legs:
            tenor = sfr_to_imm_tenor(leg.contract)
            q = IRSwapQuery(curve=curve_name, tenor=tenor).resolve_query(
                "live", pricer_or_curve=curve_handle,
            )
            pkg, rws = q.resolve_package(pricer_or_curve=curve_handle)
            vmap = q.build_value_map(
                pricer_or_curve=curve_handle, package=pkg, risk_weights=rws,
            )
            carry_bp += leg.weight * vmap.apply(value=IRSwapValue.RATE).real * 100.0
            roll_bp += leg.weight * vmap.apply(
                value=IRSwapValue.ROLL_BPS_RUNNING, horizon=horizon,
            ).real
    except Exception as exc:  # noqa: BLE001
        logger.warning("structure carry/roll computation failed: %s", exc)
        return float("nan"), float("nan")
    return float(carry_bp), float(roll_bp)

"""Smile lookup for premium-marking aged straddles off the cube vol panel.

The cube stores (expiry, tenor, offset) -> annual normal bp on a fixed grid
(17 expiries x 9 tenors x 13 offsets). A held straddle ages off-grid (a 1Y
expiry becomes 11M) and drifts off-ATM (strike fixed, forward moves), so marks
need interpolation: LINEAR in offset between quoted offsets, LINEAR in
log-expiry between quoted expiries, at a quoted tenor (no tenor interpolation
— the loci use quoted tails). Extrapolation is REFUSED, not clamped: a mark
outside the quoted surface is a mark the cube does not support, and clamping
would silently price wings at the wrong vol (the 5x wing trap).
"""
from __future__ import annotations

import math
from bisect import bisect_left
from typing import Dict, Tuple

import numpy as np
import pandas as pd

__all__ = ["SmileSurface"]


class SmileSurface:
    """One day's quoted smile for one tenor, interpolable in (expiry, offset)."""

    def __init__(self, day_frame: pd.DataFrame, *, tenor: str):
        g = day_frame[day_frame["tenor"] == tenor]
        if g.empty:
            raise KeyError(f"no cube rows for tenor {tenor!r}")
        self._tenor = tenor
        self._grid: Dict[float, Tuple[np.ndarray, np.ndarray]] = {}
        for e_yrs, ge in g.groupby("expiry_yrs"):
            ge = ge.sort_values("offset_bp")
            self._grid[float(e_yrs)] = (
                ge["offset_bp"].to_numpy(dtype=float),
                ge["vol_bp"].to_numpy(dtype=float),
            )
        self._expiries = sorted(self._grid)

    def _slice_vol(self, e_yrs: float, offset_bp: float) -> float:
        offs, vols = self._grid[e_yrs]
        if offset_bp < offs[0] or offset_bp > offs[-1]:
            raise ValueError(
                f"offset {offset_bp:+.0f}bp outside quoted range "
                f"[{offs[0]:+.0f}, {offs[-1]:+.0f}] at expiry {e_yrs}y {self._tenor} "
                "- refusing to extrapolate a wing"
            )
        return float(np.interp(offset_bp, offs, vols))

    def vol(self, *, expiry_yrs: float, offset_bp: float) -> float:
        """Annual normal bp at an off-grid (expiry, offset)."""
        ex = self._expiries
        if expiry_yrs < ex[0] or expiry_yrs > ex[-1]:
            raise ValueError(
                f"expiry {expiry_yrs:.3f}y outside quoted range [{ex[0]}, {ex[-1]}] "
                "- refusing to extrapolate the term structure"
            )
        i = bisect_left(ex, expiry_yrs)
        if i < len(ex) and ex[i] == expiry_yrs:
            return self._slice_vol(ex[i], offset_bp)
        lo, hi = ex[i - 1], ex[i]
        v_lo = self._slice_vol(lo, offset_bp)
        v_hi = self._slice_vol(hi, offset_bp)
        w = (math.log(expiry_yrs) - math.log(lo)) / (math.log(hi) - math.log(lo))
        return v_lo * (1.0 - w) + v_hi * w

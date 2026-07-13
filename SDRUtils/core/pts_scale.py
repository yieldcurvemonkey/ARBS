# ABOUTME: Canonical scale-aware tie-out between a reported Package
# Transaction Spread (PTS) and a rate-derived spread. SDR PTS values arrive
# in inconsistent units (decimal fraction, percent, or bps — Part 43/45
# notation codes 3/4 plus real-world mis-scaling), so a curve/fly whose PTS
# ties out to its legs' fixed-rate spread at *some* clean scale factor is
# high-confidence evidence of a genuine package.
#
# This mirrors the scale logic in:
#   SDRUtils/analytics/package_confidence.py  (_find_scale_match / _pts_match_signal)
#   SDRUtils/dashboard/.../utils/packageConfidence.ts  (findScaleMatch / ptsMatchSignal)
# Kept in core/ so the *detectors* (packages/curve.py, packages/ptp_grouper.py,
# packages/fly.py) can share ONE tie-out definition with the display overlay
# without an analytics<-packages circular import.
from __future__ import annotations

import math
from typing import Optional, Sequence

# Scale factors for unit-mismatch detection (decimal / percent / bps).
# Order matters: 1 is checked first so an exact match wins on ties.
PTS_SCALE_FACTORS: tuple[float, ...] = (
    1, 10, 0.1, 100, 0.01, 1000, 0.001, 10_000, 0.0001,
)

# Relative tolerance for non-1x scale matches (5%).
SCALE_REL_TOL: float = 0.05

# +/- bp window for a direct (1x) derived-spread vs reported-PTS match.
DEFAULT_PTS_MATCH_BP: float = 0.5


def _finite(v: object) -> bool:
    if v is None:
        return False
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def find_scale_match(
    a: float,
    b: float,
    tol: float = DEFAULT_PTS_MATCH_BP,
    scales: Sequence[float] = PTS_SCALE_FACTORS,
) -> Optional[dict]:
    """Try to express *a* as ``b * factor`` for any factor in *scales*.

    Returns ``{"factor": f, "residual": r}`` for the smallest-residual match,
    or ``None``. factor==1 uses the absolute ``tol``; non-1 factors use the
    relative ``SCALE_REL_TOL`` (order-of-magnitude unit mismatch).
    """
    if not math.isfinite(a) or not math.isfinite(b):
        return None
    if b == 0:
        return {"factor": 1.0, "residual": abs(a)} if abs(a) <= tol else None
    best: Optional[dict] = None
    for f in scales:
        scaled = b * f
        residual = abs(a - scaled)
        if f == 1:
            fits = residual <= tol
        else:
            denom = max(abs(a), abs(scaled))
            fits = residual <= tol if denom < 1e-12 else (residual / denom) <= SCALE_REL_TOL
        if fits and (best is None or residual < best["residual"]):
            best = {"factor": float(f), "residual": residual}
    return best


def fixed_rate_spread_to_bp(spread: float, rates: Sequence[Optional[float]]) -> float:
    """Convert a derived fixed-rate spread to bp, auto-detecting whether the
    legs' rates are decimal (0.0384) or percent (3.84)."""
    finite = [float(r) for r in rates if _finite(r)]
    if not finite:
        return spread * 100
    return spread * (10_000 if max(abs(r) for r in finite) < 1 else 100)


def pts_ties_to_spread(
    rate_a: object,
    rate_b: object,
    reported_pts: object,
    bp_tol: float = DEFAULT_PTS_MATCH_BP,
) -> bool:
    """True when the reported PTS ties out to the two legs' fixed-rate spread
    at some clean scale factor (magnitude-based, sign-convention agnostic).

    Returns False whenever any input is missing/non-finite — an *absent* tie
    is never affirmative curve evidence (callers fall back to shape gates).
    """
    if not (_finite(rate_a) and _finite(rate_b) and _finite(reported_pts)):
        return False
    derived_bp = fixed_rate_spread_to_bp(float(rate_b) - float(rate_a),
                                         [float(rate_a), float(rate_b)])
    a = abs(derived_bp)
    b = abs(float(reported_pts))
    if a == 0 and b == 0:
        return True
    if abs(a - b) <= bp_tol:  # direct (1x) match
        return True
    scale = find_scale_match(a, b, bp_tol)
    return scale is not None and scale["factor"] != 1


def pts_ties_to_value(
    derived_bp: object,
    reported_pts: object,
    bp_tol: float = DEFAULT_PTS_MATCH_BP,
) -> bool:
    """Like :func:`pts_ties_to_spread` but the caller supplies the already
    rate-derived spread in bp (e.g. a fly's 2*belly - wings)."""
    if not (_finite(derived_bp) and _finite(reported_pts)):
        return False
    a = abs(float(derived_bp))
    b = abs(float(reported_pts))
    if a == 0 and b == 0:
        return True
    if abs(a - b) <= bp_tol:
        return True
    scale = find_scale_match(a, b, bp_tol)
    return scale is not None and scale["factor"] != 1


def spread_to_bp(value: object) -> Optional[float]:
    """Normalize a single reported spreadover value to basis points via a
    magnitude band (no counter-leg to tie against). Mirrors the accept-bands in
    ``detect_spreadovers``: decimal (|v|<=0.01 -> x10000) or percent
    (0.10<=|v|<=1.0 -> x100). The ambiguous middle (0.01, 0.10) and clearly
    erroneous magnitudes (>1.0) return None."""
    if not _finite(value):
        return None
    v = float(value)
    a = abs(v)
    if a == 0:
        return 0.0
    if a <= 0.01:
        return v * 10_000.0
    if 0.10 <= a <= 1.0:
        return v * 100.0
    return None

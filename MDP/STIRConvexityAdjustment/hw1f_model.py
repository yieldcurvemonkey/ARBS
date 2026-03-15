"""Hull-White 1-Factor convexity adjustment for STIR futures vs swaps."""
from __future__ import annotations
import math


def hw1f_convexity_adjustment(a: float, sigma: float, T1: float, T2: float) -> float:
    """
    Compute the Hull-White 1-factor convexity adjustment.
    CA = (sigma^2 / 2a^2) * (1 - e^(-a*T1)) * (1 - e^(-a*T2))

    Args:
        a: Mean reversion speed (must be > 0)
        sigma: Short rate volatility
        T1: Start of accrual period (years from now)
        T2: End of accrual period (years from now)

    Returns:
        Convexity adjustment in rate terms (multiply by 10000 for bps)
    """
    if a <= 0:
        raise ValueError(f"Mean reversion 'a' must be positive, got {a}")
    return (sigma**2 / (2 * a**2)) * (1 - math.exp(-a * T1)) * (1 - math.exp(-a * T2))

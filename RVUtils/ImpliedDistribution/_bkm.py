"""Approach 3: Bakshi-Kapadia-Madan (2003) model-free implied moments.

Computes variance, skewness, and kurtosis directly from option prices via
integration — a smoothing operation that avoids the noise amplification
inherent in Breeden-Litzenberger's differentiation step.

The key insight: any payoff g(S_T) can be spanned by bonds + forwards + options
(Carr-Madan spanning formula). Setting g to (S-F)^n gives model-free central
moments without ever estimating a density.

For SOFR futures options (daily-margined, df ≈ 1, Bachelier-style level moves):
    μ₂ = 2[∫₀ᶠ P(K)dK + ∫_F^∞ C(K)dK]
    μ₃ = -6∫₀ᶠ (F-K)P(K)dK + 6∫_F^∞ (K-F)C(K)dK
    μ₄ = 12∫₀ᶠ (F-K)²P(K)dK + 12∫_F^∞ (K-F)²C(K)dK

Reference:
    Bakshi, Kapadia, Madan (2003) "Stock Return Characteristics, Skew Laws,
    and the Differential Pricing of Individual Equity Options"
    Review of Financial Studies, 16(1), 101-143.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
from scipy.integrate import trapezoid

from RVUtils.ImpliedDistribution._types import BKMResult, RNDInput


def extract_bkm_moments(
    rnd_input: RNDInput,
    *,
    interpolation_points: int = 500,
) -> BKMResult:
    """Extract model-free implied moments via BKM integration.

    Parameters
    ----------
    rnd_input : RNDInput
        Market data (strikes in price space, call premiums).
    interpolation_points : int
        Number of points for interpolated integration grid (finer = more
        accurate trapezoidal integration).
    """
    strikes = rnd_input.strikes_price
    call_premiums = rnd_input.call_premiums
    F = rnd_input.forward_price
    df = rnd_input.discount_factor

    if len(strikes) < 4:
        raise ValueError(
            f"BKM requires at least 4 strike points, got {len(strikes)}. "
            f"Use strike_offsets_bps='listed' or use_sabr_vols=True for denser grids."
        )

    otm_call_mask = strikes >= F
    otm_put_mask = strikes <= F

    K_calls = strikes[otm_call_mask]
    C_calls = call_premiums[otm_call_mask]

    K_puts = strikes[otm_put_mask]
    C_puts_as_calls = call_premiums[otm_put_mask]
    P_puts = C_puts_as_calls - df * (F - K_puts)
    P_puts = np.maximum(P_puts, 0.0)

    warnings: List[str] = []

    if len(K_calls) < 2:
        warnings.append("fewer than 2 OTM calls; right tail integration unreliable")
    if len(K_puts) < 2:
        warnings.append("fewer than 2 OTM puts; left tail integration unreliable")

    # --- Second central moment (variance in price space) ---
    # μ₂ = 2[∫₀ᶠ P(K)dK + ∫_F^∞ C(K)dK]
    int_puts = trapezoid(P_puts, K_puts) if len(K_puts) > 1 else 0.0
    int_calls = trapezoid(C_calls, K_calls) if len(K_calls) > 1 else 0.0
    mu2_price = 2.0 * (int_puts + int_calls)

    # --- Third central moment (skewness direction in price space) ---
    # μ₃ = -6∫₀ᶠ (F-K)P(K)dK + 6∫_F^∞ (K-F)C(K)dK
    int_puts_3 = trapezoid((F - K_puts) * P_puts, K_puts) if len(K_puts) > 1 else 0.0
    int_calls_3 = trapezoid((K_calls - F) * C_calls, K_calls) if len(K_calls) > 1 else 0.0
    mu3_price = -6.0 * int_puts_3 + 6.0 * int_calls_3

    # --- Fourth central moment (kurtosis in price space) ---
    # μ₄ = 12∫₀ᶠ (F-K)²P(K)dK + 12∫_F^∞ (K-F)²C(K)dK
    int_puts_4 = trapezoid((F - K_puts) ** 2 * P_puts, K_puts) if len(K_puts) > 1 else 0.0
    int_calls_4 = trapezoid((K_calls - F) ** 2 * C_calls, K_calls) if len(K_calls) > 1 else 0.0
    mu4_price = 12.0 * int_puts_4 + 12.0 * int_calls_4

    # --- Convert to standardized moments ---
    std_price = math.sqrt(max(mu2_price, 1e-12))
    if std_price > 1e-8:
        skewness_price = mu3_price / std_price**3
        kurtosis_price = mu4_price / std_price**4
    else:
        skewness_price = 0.0
        kurtosis_price = 3.0
        warnings.append("near-zero variance; skew/kurtosis unreliable")

    # --- Convert to rate space (R = 100 - P) ---
    # Variance: unchanged (linear transform)
    # Skewness: sign flip (R = -P + const → odd moments negate)
    # Kurtosis: unchanged (even moment)
    variance_rate = mu2_price
    std_rate = std_price
    skewness_rate = -skewness_price
    kurtosis_rate = kurtosis_price
    excess_kurtosis_rate = kurtosis_rate - 3.0

    # Tail mass diagnostics: what fraction of the total variance comes from
    # each side (asymmetry in the tails)
    total_var_contribution = int_puts + int_calls
    if total_var_contribution > 1e-12:
        left_tail_frac = int_puts / total_var_contribution
        right_tail_frac = int_calls / total_var_contribution
    else:
        left_tail_frac = 0.5
        right_tail_frac = 0.5

    return BKMResult(
        input=rnd_input,
        variance_rate=variance_rate,
        std_rate=std_rate,
        skewness_rate=skewness_rate,
        kurtosis_rate=kurtosis_rate,
        excess_kurtosis_rate=excess_kurtosis_rate,
        mu2_price=mu2_price,
        mu3_price=mu3_price,
        mu4_price=mu4_price,
        left_tail_variance_frac=left_tail_frac,
        right_tail_variance_frac=right_tail_frac,
        n_otm_calls=int(otm_call_mask.sum()),
        n_otm_puts=int(otm_put_mask.sum()),
        warnings=tuple(warnings),
    )

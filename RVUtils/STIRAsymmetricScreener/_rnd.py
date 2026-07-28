"""Risk-Neutral Density extraction for the STIR Options Asymmetric Screener.

Implements spec §12 — Breeden-Litzenberger via smoothing-spline
extraction, stability checks, bimodality detection, and side-by-side
SABR-density comparison for §2.9b divergence flagging.

Defers convexity-adjusted bin labeling and FOMC-meeting integration to
Phase 6 (path logic).
"""

from __future__ import annotations

import datetime
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.integrate import trapezoid

from RVUtils.ImpliedDistribution._breeden_litzenberger import (
    extract_rnd_breeden_litzenberger,
)
from RVUtils.ImpliedDistribution._data_prep import smile_to_rnd_input
from RVUtils.STIRAsymmetricScreener._market_data import LegMarket
from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

logger = logging.getLogger(__name__)


# Stability flag enumeration — strings for ergonomic dict export.
STABILITY_STABLE = "stable"
STABILITY_UNSTABLE_SMOOTHING = "unstable_smoothing"
STABILITY_UNSTABLE_ORDER = "unstable_order"
STABILITY_MASS_VIOLATION = "mass_violation"
STABILITY_NEGATIVE_DENSITY = "negative_density"
STABILITY_PARITY_VIOLATION = "parity_violation"
STABILITY_STALE_REFERENCE_QUARTER = "stale_reference_quarter"


# Quarterly month codes — used for reference-quarter staleness check
_QUARTERLY_MONTH_CODES = {"H", "M", "U", "Z"}
_MONTH_CODE_TO_NUM = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}


@dataclass(frozen=True)
class RNDRecord:
    """Per-(contract, expiry) RND record per spec §12.7."""

    contract: str
    expiry: datetime.date
    dte: int
    strike_grid_rate: np.ndarray
    n_strikes_observed: int
    density_pdf: np.ndarray
    density_cdf: np.ndarray
    fed_target_bins: Dict[str, float]
    mode_count: int
    mode_locations: Tuple[float, ...]
    mode_heights: Tuple[float, ...]
    mean_rate: float
    std_rate: float
    skew: float
    kurt: float
    stability_flag: str
    extrapolation_dominated: bool
    sabr_density_on_same_grid: Optional[np.ndarray]
    sabr_rnd_kl_divergence: float
    parity_violation_max: float = 0.0
    forward_rate: float = 0.0
    forward_price: float = 0.0
    smoothing_sensitivity_pp: float = 0.0  # max |Δp| over λ × {0.1, 10}
    order_sensitivity_pp: float = 0.0      # max |Δp| over order ± 1
    negative_density_pct: float = 0.0      # raw negative-mass fraction before clipping
    warnings: Tuple[str, ...] = ()
    prices_source: str = "sabr_smile"  # "sabr_smile" or "market_listed"


def _quarterly_reference_window(contract: str) -> Optional[Tuple[datetime.date, datetime.date]]:
    """Return ``(period_start, period_end)`` for SR3 quarterly contracts.

    Period start = IMM date of the contract's month; period end = IMM
    date of the next quarterly month. Returns None for non-quarterly or
    midcurve / Euribor contracts.
    """
    m = re.fullmatch(r"(SFR|ER)([FGHJKMNQUVXZ])(\d{2})", (contract or "").strip().upper())
    if m is None:
        return None
    code = m.group(2)
    if code not in _QUARTERLY_MONTH_CODES:
        return None
    try:
        from MDP.STIRFutures._sofr_option_contracts import (
            _contract_expiry_date,
            next_quarterly_contract,
        )
        start = _contract_expiry_date(f"{code}{m.group(3)}")
        nxt_token = next_quarterly_contract(contract)
        end = _contract_expiry_date(nxt_token[-3:])
        return start, end
    except Exception:
        return None


def _is_in_reference_quarter(contract: str, *, as_of: datetime.date) -> bool:
    """Spec §9 / §12.2: SOFR options change character once their underlying
    enters its reference period. Conservative rule: as_of within 14 days
    before period start triggers the flag.
    """
    window = _quarterly_reference_window(contract)
    if window is None:
        return False
    start, end = window
    # Stale once we're inside or close to (within 14 cal days of) period start
    return as_of >= (start - datetime.timedelta(days=14))


def _bimodality_count(
    density: np.ndarray,
    *,
    height_fraction: float = 0.5,
) -> Tuple[int, Tuple[int, ...]]:
    """Count local maxima above ``height_fraction × max(density)``.

    Returns ``(count, indices)``.
    """
    if len(density) < 3:
        return 0, ()
    peak = float(np.nanmax(density))
    if peak <= 0:
        return 0, ()
    threshold = height_fraction * peak

    indices: List[int] = []
    for i in range(1, len(density) - 1):
        if (
            density[i] > threshold
            and density[i] >= density[i - 1]
            and density[i] >= density[i + 1]
        ):
            # Avoid plateau double-count: must be strictly greater than at
            # least one neighbor
            if density[i] > density[i - 1] or density[i] > density[i + 1]:
                indices.append(i)
    return len(indices), tuple(indices)


def _kl_divergence(p: np.ndarray, q: np.ndarray, x: np.ndarray) -> float:
    """KL(p || q) on the same grid. Adds floor to avoid log(0)."""
    floor = 1e-12
    pp = np.maximum(p, floor)
    qq = np.maximum(q, floor)
    integrand = pp * np.log(pp / qq)
    return float(trapezoid(integrand, x))


def _refit_payoff_zone_prob(
    *,
    rnd_input,
    config: ScreenerConfig,
    smoothing_param: float,
    spline_order: int,
    fwd_rate: float,
) -> float:
    """Re-extract BL with a different smoothing param/order, return
    payoff-zone probability over a 50bp window centered on forward.
    """
    try:
        bl = extract_rnd_breeden_litzenberger(
            rnd_input,
            smoothing_param=smoothing_param,
            spline_order=min(max(spline_order, 1), 5),
            n_ghost_points=config.rnd_n_ghost_points,
            ghost_extension_bps=config.rnd_ghost_extension_bps,
            bin_width_bps=config.rnd_bin_width_bps,
            grid_points=config.rnd_grid_points,
        )
    except Exception:
        return float("nan")
    grid = bl.strike_grid_rate
    density = bl.rnd_density
    # 50bp window centered on forward
    lo = fwd_rate - 0.25
    hi = fwd_rate + 0.25
    mask = (grid >= lo) & (grid <= hi)
    return float(trapezoid(density[mask], grid[mask])) if mask.any() else 0.0


def _sabr_density_on_grid(
    smile,
    grid_rate: np.ndarray,
) -> np.ndarray:
    """Compute SABR-implied terminal density on the same rate grid as the RND.

    Uses Bachelier model + numerical second derivative of the SABR-priced
    call-price-vs-strike curve. Output is normalized to integrate to 1.
    """
    from RVUtils.ImpliedDistribution._bachelier import (
        bachelier_call_prices_vectorized,
    )

    fwd = float(smile.params.forward_price)
    tte = float(smile.params.time_to_expiry)
    df = 1.0  # futures options are daily-margined
    # rate -> price space
    grid_price = (100.0 - grid_rate)[::-1]
    vols = np.asarray(
        smile.normal_vol(grid_price, strike_space="price", vol_units="price"),
        dtype=float,
    )
    vols = np.maximum(vols, 1e-8)
    calls = bachelier_call_prices_vectorized(grid_price, fwd, vols, tte, df)
    # second derivative ~ density in price space
    d2 = np.gradient(np.gradient(calls, grid_price), grid_price)
    d2 = np.maximum(d2, 0.0)  # truncate negative numerical artifacts
    # Convert to rate-space density (flip; |dp/dr| = 1)
    density_rate = d2[::-1]
    # Normalize
    total = float(trapezoid(density_rate, grid_rate))
    if total > 1e-10:
        density_rate = density_rate / total
    return density_rate


def _convexity_adjusted_bins(
    *,
    grid_rate: np.ndarray,
    density: np.ndarray,
    bin_width_bps: float = 25.0,
    convexity_adj_bp: float = 0.0,
) -> Dict[str, float]:
    """Integrate density over 25bp Fed-target bins. Applies convexity
    adjustment by shifting the rate grid before bin labeling.

    For v1 the convexity adjustment defaults to 0; the orchestrator
    populates it from STIRConvexityAdjustmentMDP at integration.
    """
    if len(grid_rate) < 2:
        return {}
    bin_width = bin_width_bps / 100.0
    rate_lo = float(grid_rate[0]) + convexity_adj_bp / 100.0
    rate_hi = float(grid_rate[-1]) + convexity_adj_bp / 100.0
    edges: List[float] = []
    edge = math.floor(rate_lo / bin_width) * bin_width
    while edge <= rate_hi + bin_width:
        edges.append(edge)
        edge += bin_width
    out: Dict[str, float] = {}
    adj_grid = grid_rate + convexity_adj_bp / 100.0
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        mask = (adj_grid >= lo) & (adj_grid < hi)
        if not mask.any():
            continue
        prob = float(trapezoid(density[mask], adj_grid[mask]))
        mid = (lo + hi) / 2.0
        out[f"{mid:.4f}"] = prob
    return out


def _build_observed_rnd_input(
    smile,
    leg_market: Dict[Tuple[str, datetime.date, str, float], LegMarket],
    *,
    as_of: datetime.date,
    raw_market_open_interest_min: float = 100.0,
    raw_market_otm_only: bool = True,
):
    """Build an RNDInput per JPM Tech Appendix A.

    Priority order:
    1. Observed market premiums attached to ``smile.points`` (preferred —
       this is what the JPM appendix specifies and what
       ``SFRImpliedDistribution`` uses by default). Filter on OI ≥ 100,
       OTM-only; put-call parity converts puts to equivalent calls.
    2. External ``leg_market`` dict (legacy path, retained for callers
       that wire per-leg quotes through a separate channel).
    3. SABR-modeled call premiums on listed strikes (fallback when no
       observed market data is available — e.g., synthetic test smiles).

    Returns ``(rnd_input, max_parity_violation_ticks, source_label)``.
    """
    contract = str(smile.symbol).strip().upper()
    expiry = smile.params.expiry_date
    fwd = float(smile.params.forward_price)
    df = 1.0  # futures options are daily-margined

    # === Path 1: smile.points carries observed market premiums (JPM path) ===
    n_points_with_market = sum(
        1 for pt in smile.points
        if getattr(pt, "market_price", None) is not None
        and math.isfinite(float(getattr(pt, "market_price", float("nan")) or float("nan")))
        and float(getattr(pt, "market_price", 0.0)) > 0.0
    )
    if n_points_with_market >= 8:
        rnd_input = smile_to_rnd_input(
            smile,
            use_sabr_vols=False,
            sabr_extrapolation=False,
            raw_market_open_interest_min=raw_market_open_interest_min,
            raw_market_otm_only=raw_market_otm_only,
        )
        # Parity violations measured by smile_to_rnd_input itself when both
        # call and put are observed at same strike. We don't track per-strike
        # here; downstream stability checks catch fitting issues.
        return rnd_input, 0.0, "market_listed_jpm"

    # === Path 2: external leg_market dict (legacy) ===
    observed_rows: List[LegMarket] = [
        lm
        for (c, exp, _r, _k), lm in leg_market.items()
        if c == contract and exp == expiry and not math.isnan(lm.premium_ticks)
    ]
    if len(observed_rows) >= 8:
        from RVUtils.ImpliedDistribution._bachelier import put_to_call_parity
        from RVUtils.ImpliedDistribution._types import RNDInput

        by_strike: Dict[float, float] = {}
        parity_violations: List[float] = []
        for lm in observed_rows:
            premium_price = lm.premium_ticks / 100.0  # 1 tick = 0.01 of price
            if lm.right == "C":
                call_premium = premium_price
            else:
                call_premium = put_to_call_parity(premium_price, lm.strike, fwd, df)
            existing = by_strike.get(lm.strike)
            if existing is not None:
                parity_violations.append(abs(existing - call_premium))
            by_strike[lm.strike] = call_premium

        sorted_strikes = sorted(by_strike.keys())
        max_parity_violation_ticks = (
            max(parity_violations) * 100.0 if parity_violations else 0.0
        )
        rnd_input = RNDInput(
            symbol=contract,
            as_of=as_of,
            forward_price=fwd,
            forward_rate=float(smile.params.forward_rate),
            time_to_expiry=float(smile.params.time_to_expiry),
            expiry_date=expiry,
            discount_factor=df,
            strikes_price=np.asarray(sorted_strikes, dtype=float),
            call_premiums=np.asarray(
                [by_strike[k] for k in sorted_strikes], dtype=float
            ),
            strike_source="observed_market_legmarket",
        )
        return rnd_input, max_parity_violation_ticks, "market_legmarket"

    # === Path 3: SABR fallback (synthetic / empty smiles) ===
    use_extrap = len(smile.points) == 0
    rnd_input = smile_to_rnd_input(
        smile,
        use_sabr_vols=True,
        sabr_extrapolation=use_extrap,
        sabr_n_strikes=80 if use_extrap else 200,
    )
    return rnd_input, 0.0, "sabr_smile"


def extract_per_expiry_rnd(
    *,
    smile,
    leg_market: Dict[Tuple[str, datetime.date, str, float], LegMarket],
    config: ScreenerConfig,
    as_of: datetime.date,
    convexity_adj_bp: float = 0.0,
) -> RNDRecord:
    """Extract a Breeden-Litzenberger RND for one (contract, expiry) pair.

    Implements spec §12 end-to-end except for the FOMC-meeting bin
    labeling that lives in Phase 6.
    """
    contract = str(smile.symbol).strip().upper()
    expiry = smile.params.expiry_date
    dte = (expiry - as_of).days
    fwd = float(smile.params.forward_price)
    fwd_rate = float(smile.params.forward_rate)
    warnings: List[str] = []

    # Reference-quarter short circuit
    if _is_in_reference_quarter(contract, as_of=as_of):
        return RNDRecord(
            contract=contract,
            expiry=expiry,
            dte=dte,
            strike_grid_rate=np.array([fwd_rate]),
            n_strikes_observed=0,
            density_pdf=np.array([0.0]),
            density_cdf=np.array([0.0]),
            fed_target_bins={},
            mode_count=0,
            mode_locations=(),
            mode_heights=(),
            mean_rate=fwd_rate,
            std_rate=0.0,
            skew=0.0,
            kurt=0.0,
            stability_flag=STABILITY_STALE_REFERENCE_QUARTER,
            extrapolation_dominated=False,
            sabr_density_on_same_grid=None,
            sabr_rnd_kl_divergence=float("nan"),
            forward_rate=fwd_rate,
            forward_price=fwd,
            warnings=("stale_reference_quarter",),
            prices_source="sabr_smile",
        )

    rnd_input, parity_violation_ticks, prices_source = _build_observed_rnd_input(
        smile, leg_market, as_of=as_of
    )

    # Parity violation gate (spec §12.2 step 2)
    if parity_violation_ticks > 2.0:
        return RNDRecord(
            contract=contract,
            expiry=expiry,
            dte=dte,
            strike_grid_rate=np.array([fwd_rate]),
            n_strikes_observed=int(len(rnd_input.strikes_price)),
            density_pdf=np.array([0.0]),
            density_cdf=np.array([0.0]),
            fed_target_bins={},
            mode_count=0,
            mode_locations=(),
            mode_heights=(),
            mean_rate=fwd_rate,
            std_rate=0.0,
            skew=0.0,
            kurt=0.0,
            stability_flag=STABILITY_PARITY_VIOLATION,
            extrapolation_dominated=False,
            sabr_density_on_same_grid=None,
            sabr_rnd_kl_divergence=float("nan"),
            parity_violation_max=parity_violation_ticks,
            forward_rate=fwd_rate,
            forward_price=fwd,
            warnings=(f"parity_violation_max:{parity_violation_ticks:.2f}t",),
            prices_source=prices_source,
        )

    try:
        bl = extract_rnd_breeden_litzenberger(
            rnd_input,
            smoothing_param=config.rnd_smoothing_param,
            spline_order=config.rnd_spline_order,
            n_ghost_points=config.rnd_n_ghost_points,
            ghost_extension_bps=config.rnd_ghost_extension_bps,
            bin_width_bps=config.rnd_bin_width_bps,
            grid_points=config.rnd_grid_points,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("BL extraction failed for %s: %s", contract, exc)
        return RNDRecord(
            contract=contract,
            expiry=expiry,
            dte=dte,
            strike_grid_rate=np.array([fwd_rate]),
            n_strikes_observed=int(len(rnd_input.strikes_price)),
            density_pdf=np.array([0.0]),
            density_cdf=np.array([0.0]),
            fed_target_bins={},
            mode_count=0,
            mode_locations=(),
            mode_heights=(),
            mean_rate=fwd_rate,
            std_rate=0.0,
            skew=0.0,
            kurt=0.0,
            stability_flag=STABILITY_NEGATIVE_DENSITY,
            extrapolation_dominated=False,
            sabr_density_on_same_grid=None,
            sabr_rnd_kl_divergence=float("nan"),
            forward_rate=fwd_rate,
            forward_price=fwd,
            warnings=(f"bl_extraction_failed:{exc}",),
            prices_source=prices_source,
        )

    grid_rate = np.asarray(bl.strike_grid_rate, dtype=float)
    density = np.asarray(bl.rnd_density, dtype=float)
    cdf = np.asarray(bl.rnd_cumulative, dtype=float)

    # Mass conservation.
    #
    # This used to integrate `bl.rnd_density`, which the extractor has already rescaled
    # to unit mass, so it measured 1.0 to machine precision and the guard could never
    # fire. The meaningful quantity is the mass BEFORE that rescale, now reported
    # directly. The check is one-sided on purpose: a value below 1 is legitimate for a
    # truncated smile, where the integral equals P(Kmin < S_T < Kmax) rather than 1.
    # Only an excess can be a real defect - it means the post-clip fitted call curve is
    # carrying more than unit mass, i.e. butterfly arbitrage survived the fit.
    pre_norm_mass = float(getattr(bl, "pre_normalization_mass", float("nan")))
    if not math.isfinite(pre_norm_mass):
        pre_norm_mass = float(trapezoid(density, grid_rate))
    if pre_norm_mass > 1.05:
        warnings.append(f"mass_violation:{pre_norm_mass:.3f}")

    # Negative-density check.
    # BL warns at 0.01% (numerical noise) and already clips. We only flag
    # `negative_density` when the raw fit produced *materially* unphysical
    # mass (default >5%). Parse magnitude from the warning string —
    # format: "negative density mass clipped (X.XX% of total)".
    neg_density_pct = 0.0
    for w in bl.warnings:
        if "negative density" not in w:
            continue
        # extract the percentage between '(' and '%'
        try:
            inside = w[w.index("(") + 1 : w.index("%")]
            neg_density_pct = max(neg_density_pct, float(inside))
        except (ValueError, IndexError):
            pass
    has_negative = neg_density_pct > 5.0

    # Bimodality detection
    mode_count, mode_idx = _bimodality_count(density, height_fraction=0.5)
    mode_locations = tuple(float(grid_rate[i]) for i in mode_idx)
    mode_heights = tuple(float(density[i]) for i in mode_idx)

    # SABR-implied density on same grid (spec §2.9b / §12.7)
    try:
        sabr_density = _sabr_density_on_grid(smile, grid_rate)
        kl = _kl_divergence(density, sabr_density, grid_rate)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"sabr_density_failed:{exc}")
        sabr_density = None
        kl = float("nan")

    # Smoothing-sensitivity check
    p_base = _refit_payoff_zone_prob(
        rnd_input=rnd_input,
        config=config,
        smoothing_param=config.rnd_smoothing_param,
        spline_order=config.rnd_spline_order,
        fwd_rate=fwd_rate,
    )
    p_low_lambda = _refit_payoff_zone_prob(
        rnd_input=rnd_input,
        config=config,
        smoothing_param=max(config.rnd_smoothing_param / 10.0, 1e-10),
        spline_order=config.rnd_spline_order,
        fwd_rate=fwd_rate,
    )
    p_high_lambda = _refit_payoff_zone_prob(
        rnd_input=rnd_input,
        config=config,
        smoothing_param=config.rnd_smoothing_param * 10.0,
        spline_order=config.rnd_spline_order,
        fwd_rate=fwd_rate,
    )
    smoothing_delta = max(
        abs(p_low_lambda - p_base) if math.isfinite(p_low_lambda) else 0.0,
        abs(p_high_lambda - p_base) if math.isfinite(p_high_lambda) else 0.0,
    ) * 100.0  # in percentage points

    p_lower_order = _refit_payoff_zone_prob(
        rnd_input=rnd_input,
        config=config,
        smoothing_param=config.rnd_smoothing_param,
        spline_order=max(config.rnd_spline_order - 1, 1),
        fwd_rate=fwd_rate,
    )
    p_higher_order = _refit_payoff_zone_prob(
        rnd_input=rnd_input,
        config=config,
        smoothing_param=config.rnd_smoothing_param,
        spline_order=min(config.rnd_spline_order + 1, 5),
        fwd_rate=fwd_rate,
    )
    order_delta = max(
        abs(p_lower_order - p_base) if math.isfinite(p_lower_order) else 0.0,
        abs(p_higher_order - p_base) if math.isfinite(p_higher_order) else 0.0,
    ) * 100.0

    # Stability flag selection (priority order)
    stability_flag = STABILITY_STABLE
    if has_negative:
        stability_flag = STABILITY_NEGATIVE_DENSITY
    elif pre_norm_mass > 1.05:
        # One-sided, matching the guard above: sub-unit mass is expected on a truncated
        # smile and must not flip prob_source to sabr_fallback.
        stability_flag = STABILITY_MASS_VIOLATION
    elif smoothing_delta > config.rnd_smoothing_sensitivity_pp_threshold:
        stability_flag = STABILITY_UNSTABLE_SMOOTHING
    elif order_delta > config.rnd_smoothing_sensitivity_pp_threshold:
        stability_flag = STABILITY_UNSTABLE_ORDER

    # Wing-extrapolation flag (spec §12.3): is the payoff zone past the
    # observed strike range?
    obs_min = float(min(rnd_input.strikes_price))
    obs_max = float(max(rnd_input.strikes_price))
    obs_rate_min = 100.0 - obs_max
    obs_rate_max = 100.0 - obs_min
    extrap_mask = (grid_rate < obs_rate_min) | (grid_rate > obs_rate_max)
    extrap_mass = float(trapezoid(density[extrap_mask], grid_rate[extrap_mask])) if extrap_mask.any() else 0.0
    extrapolation_dominated = extrap_mass > 0.5

    # Convexity-adjusted bin labeling (defer FOMC-meeting integration to Phase 6)
    fed_target_bins = _convexity_adjusted_bins(
        grid_rate=grid_rate,
        density=density,
        bin_width_bps=config.rnd_bin_width_bps,
        convexity_adj_bp=convexity_adj_bp,
    )

    return RNDRecord(
        contract=contract,
        expiry=expiry,
        dte=dte,
        strike_grid_rate=grid_rate,
        n_strikes_observed=int(len(rnd_input.strikes_price)),
        density_pdf=density,
        density_cdf=cdf,
        fed_target_bins=fed_target_bins,
        mode_count=mode_count,
        mode_locations=mode_locations,
        mode_heights=mode_heights,
        mean_rate=float(bl.mean_rate),
        std_rate=float(bl.std_rate),
        skew=float(bl.skewness),
        kurt=float(bl.kurtosis),
        stability_flag=stability_flag,
        extrapolation_dominated=extrapolation_dominated,
        sabr_density_on_same_grid=sabr_density,
        sabr_rnd_kl_divergence=kl,
        parity_violation_max=parity_violation_ticks,
        forward_rate=fwd_rate,
        forward_price=fwd,
        smoothing_sensitivity_pp=float(smoothing_delta),
        order_sensitivity_pp=float(order_delta),
        negative_density_pct=float(neg_density_pct),
        warnings=tuple(warnings),
        prices_source=prices_source,
    )


def payoff_zone_probability(
    rnd: RNDRecord,
    *,
    density: str = "rnd",
    lower_rate: float,
    upper_rate: float,
) -> float:
    """Integrate density over a rate-space window.

    ``density`` selects which density to use: ``"rnd"`` for the BL
    extraction, ``"sabr"`` for the SABR-implied density on the same grid.
    """
    if rnd.density_pdf is None or len(rnd.density_pdf) < 2:
        return 0.0
    grid = rnd.strike_grid_rate
    if density == "sabr":
        if rnd.sabr_density_on_same_grid is None:
            return float("nan")
        d = rnd.sabr_density_on_same_grid
    else:
        d = rnd.density_pdf
    if not math.isfinite(lower_rate) or not math.isfinite(upper_rate):
        return float("nan")
    if upper_rate < lower_rate:
        return 0.0
    mask = (grid >= lower_rate) & (grid <= upper_rate)
    if not mask.any():
        return 0.0
    return float(trapezoid(d[mask], grid[mask]))


def sabr_rnd_payoff_zone_diff(
    rnd: RNDRecord,
    *,
    lower_rate: float,
    upper_rate: float,
) -> float:
    """Spec §2.9b: signed difference between RND and SABR payoff-zone probabilities.

    Positive ⇒ RND assigns more probability to the payoff zone than
    SABR (RND is wing-rich here ⇒ SABR underprices wings ⇒ buy-vol
    structures favored).
    """
    if rnd.sabr_density_on_same_grid is None:
        return float("nan")
    p_rnd = payoff_zone_probability(rnd, density="rnd", lower_rate=lower_rate, upper_rate=upper_rate)
    p_sabr = payoff_zone_probability(rnd, density="sabr", lower_rate=lower_rate, upper_rate=upper_rate)
    return float(p_rnd - p_sabr)

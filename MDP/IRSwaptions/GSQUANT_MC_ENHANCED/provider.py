from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Iterable, Optional

import numpy as np
import QuantLib as ql
from scipy.optimize import brentq

from definitions.IRSwaptions import EXPIRY_LABELS, TAIL_LABELS
from MDP.IRSwaptions.MONKEYCUBE.cube import NormalSabrVolCube

logger = logging.getLogger(__name__)

# Module-level cache: (curve_name, date_iso) → EnhancedSabrVolCube
_ENHANCED_CUBE_CACHE: dict[tuple[str, str], EnhancedSabrVolCube] = {}


def _label_to_ql_period(label: str) -> ql.Period:
    token = str(label).strip().lower()
    if token.endswith("m"):
        return ql.Period(int(token[:-1]), ql.Months)
    if token.endswith("y"):
        return ql.Period(int(token[:-1]), ql.Years)
    raise ValueError(f"Unsupported tenor label: {label}")


def _sabr_atm_vol_raw(alpha: float, beta: float, nu: float, rho: float, fwd: float, T: float) -> float:
    """Evaluate the raw ATM normal vol from ql.SabrSmileSection (no normalization)."""
    smile = ql.SabrSmileSection(T, fwd, [alpha, beta, nu, rho], 0.0, ql.Normal)
    return float(smile.volatility(smile.atmLevel(), ql.Normal))


def _recalibrate_alpha(
    *,
    target_atm_vol_decimal: float,
    beta: float,
    nu: float,
    rho: float,
    fwd: float,
    T: float,
    alpha_guess: float,
) -> float:
    """Solve for SABR alpha so that the ATM normal vol matches *target_atm_vol_decimal*.

    Determines the output scale regime (decimal vs bp-vol) from *alpha_guess*
    and works in raw SABR output space to keep the objective smooth and
    monotonic — avoids the discontinuity in ``_normalize_normal_vol`` at 1.0.
    """
    # Determine scale regime from the guess: is the raw SABR output in bp-vol
    # (>1.0, needing /10_000) or already in decimal (<1.0)?
    guess_raw = _sabr_atm_vol_raw(alpha_guess, beta, nu, rho, fwd, T)
    if abs(guess_raw) > 1.0:
        # bp-vol regime: raw output is ~78 for 78bp → target in same scale
        target_raw = target_atm_vol_decimal * 10_000.0
    else:
        # decimal regime: raw output is ~0.0078 for 78bp → target already matches
        target_raw = target_atm_vol_decimal

    def objective(alpha: float) -> float:
        return _sabr_atm_vol_raw(alpha, beta, nu, rho, fwd, T) - target_raw

    # Use absolute bounds that cover the full reasonable alpha range, combined
    # with relative bounds from the guess.
    lo = max(min(alpha_guess * 0.01, 1e-4), 1e-8)
    hi = max(alpha_guess * 20.0, 1.0)
    try:
        return float(brentq(objective, lo, hi, maxiter=200, xtol=1e-12))
    except ValueError:
        # Widen to absolute extremes.
        lo = 1e-8
        hi = max(alpha_guess * 200.0, 5.0)
        return float(brentq(objective, lo, hi, maxiter=200, xtol=1e-12))


class EnhancedSabrVolCube:
    """SABR vol cube with alpha re-calibrated to match GSQUANT ATMF normal vols.

    Wraps a :class:`NormalSabrVolCube`, overriding alpha at each grid node so
    that the SABR ATM vol matches the authoritative GSQUANT ATM vol while
    preserving the MONKEYCUBE skew shape (beta, nu, rho).

    Implements the same interface as :class:`NormalSabrVolCube` so that
    downstream consumers (``leg_cube_vol``, ``_sabr_params``, etc.) work
    unchanged.
    """

    def __init__(
        self,
        base_cube: NormalSabrVolCube,
        gsquant_atm_matrix: np.ndarray,
        expiry_labels: list[str],
        tail_labels: list[str],
    ):
        self._base = base_cube
        self._gsquant_atm = gsquant_atm_matrix
        self._expiry_labels = expiry_labels
        self._tail_labels = tail_labels

        # Pre-compute grid coordinates (year fractions) for bilinear interpolation.
        self._exp_times: list[float] = [base_cube._tenor_to_time(e) for e in expiry_labels]
        self._tail_years: list[float] = [base_cube._tenor_to_years(t) for t in tail_labels]

        # Re-calibrated alphas at each grid node, keyed by (i, j).
        self._recalibrated_alphas: dict[tuple[int, int], float] = {}
        self._calibrate_all_nodes()

    # ------------------------------------------------------------------
    # Delegate read-only base-cube attributes
    # ------------------------------------------------------------------
    @property
    def params(self):  # noqa: D102
        return self._base.params

    @property
    def cal(self):  # noqa: D102
        return self._base.cal

    @property
    def dc(self):  # noqa: D102
        return self._base.dc

    @property
    def today(self):  # noqa: D102
        return self._base.today

    @property
    def _beta(self):  # noqa: D102
        return self._base._beta

    # ------------------------------------------------------------------
    # Core calibration
    # ------------------------------------------------------------------
    def _calibrate_all_nodes(self) -> None:
        for i, exp_label in enumerate(self._expiry_labels):
            T = self._exp_times[i]
            for j, tail_label in enumerate(self._tail_labels):
                swap_yrs = self._tail_years[j]
                target_vol_decimal = float(self._gsquant_atm[i, j])

                pt = np.array([[T, swap_yrs]])
                alpha_mc, beta, nu, rho, fwd = self._base._interpolate_params(pt)

                try:
                    alpha_new = _recalibrate_alpha(
                        target_atm_vol_decimal=target_vol_decimal,
                        beta=beta,
                        nu=nu,
                        rho=rho,
                        fwd=fwd,
                        T=T,
                        alpha_guess=alpha_mc,
                    )
                except Exception as exc:
                    logger.warning(
                        "Alpha re-calibration failed at (%s, %s): %s "
                        "[target=%.6f, alpha_mc=%.6f, beta=%.4f, nu=%.4f, rho=%.4f, fwd=%.6f, T=%.4f]; "
                        "keeping MONKEYCUBE alpha.",
                        exp_label,
                        tail_label,
                        exc,
                        target_vol_decimal,
                        alpha_mc,
                        beta,
                        nu,
                        rho,
                        fwd,
                        T,
                    )
                    alpha_new = alpha_mc
                self._recalibrated_alphas[(i, j)] = alpha_new

    # ------------------------------------------------------------------
    # Interpolation
    # ------------------------------------------------------------------
    def _interpolate_recalibrated_alpha(
        self, T: float, swap_yrs: float, fallback_alpha: float
    ) -> float:
        """Bilinear interpolation of re-calibrated alpha on the calibration grid."""
        exp_t = self._exp_times
        tail_y = self._tail_years

        T_c = max(min(T, exp_t[-1]), exp_t[0])
        S_c = max(min(swap_yrs, tail_y[-1]), tail_y[0])

        # Find bounding indices.
        i_lo = 0
        for k in range(len(exp_t)):
            if exp_t[k] <= T_c:
                i_lo = k
        i_hi = min(i_lo + 1, len(exp_t) - 1)

        j_lo = 0
        for k in range(len(tail_y)):
            if tail_y[k] <= S_c:
                j_lo = k
        j_hi = min(j_lo + 1, len(tail_y) - 1)

        if i_lo == i_hi and j_lo == j_hi:
            return self._recalibrated_alphas.get((i_lo, j_lo), fallback_alpha)

        t_range = exp_t[i_hi] - exp_t[i_lo] if i_hi != i_lo else 1.0
        s_range = tail_y[j_hi] - tail_y[j_lo] if j_hi != j_lo else 1.0
        wt = (T_c - exp_t[i_lo]) / t_range if i_hi != i_lo else 0.0
        ws = (S_c - tail_y[j_lo]) / s_range if j_hi != j_lo else 0.0

        a00 = self._recalibrated_alphas.get((i_lo, j_lo), fallback_alpha)
        a01 = self._recalibrated_alphas.get((i_lo, j_hi), fallback_alpha)
        a10 = self._recalibrated_alphas.get((i_hi, j_lo), fallback_alpha)
        a11 = self._recalibrated_alphas.get((i_hi, j_hi), fallback_alpha)

        return (1 - wt) * (1 - ws) * a00 + (1 - wt) * ws * a01 + wt * (1 - ws) * a10 + wt * ws * a11

    def _interpolate_params(self, pt: np.ndarray) -> tuple[float, float, float, float, float]:
        """Interpolate SABR params with re-calibrated alpha."""
        alpha_mc, beta, nu, rho, fwd = self._base._interpolate_params(pt)
        T = float(pt.ravel()[0])
        swap_yrs = float(pt.ravel()[1])
        alpha_new = self._interpolate_recalibrated_alpha(T, swap_yrs, alpha_mc)
        return alpha_new, beta, nu, rho, fwd

    # ------------------------------------------------------------------
    # Public interface (mirrors NormalSabrVolCube)
    # ------------------------------------------------------------------
    def smile_section(
        self,
        opt_tenor: str | ql.Period,
        swap_tenor: str | ql.Period,
    ) -> ql.SabrSmileSection:
        if isinstance(opt_tenor, str):
            opt_tenor = ql.Period(opt_tenor)
        if isinstance(swap_tenor, str):
            swap_tenor = ql.Period(swap_tenor)
        T = self.dc.yearFraction(self.today, self.cal.advance(self.today, opt_tenor))
        swap_yrs = self._base._tenor_to_years(str(swap_tenor))
        pt = np.array([[T, swap_yrs]])
        a, b, nu, rho, fwd = self._interpolate_params(pt)
        return ql.SabrSmileSection(T, fwd, [a, b, nu, rho], 0.0, ql.Normal)

    def volatility(
        self,
        opt_tenor: str | ql.Period,
        swap_tenor: str | ql.Period,
        strike: float,
        vol_type: Any = None,
    ) -> float:
        if vol_type is None:
            vol_type = ql.Normal
        smile = self.smile_section(opt_tenor, swap_tenor)
        return NormalSabrVolCube._normalize_normal_vol(float(smile.volatility(strike, vol_type)))

    def volatility_at_point(
        self,
        option_time: float,
        swap_years: float,
        strike: float,
    ) -> float:
        pt = np.array([[option_time, swap_years]])
        a, b, nu, rho, fwd = self._interpolate_params(pt)
        smile = ql.SabrSmileSection(option_time, fwd, [a, b, nu, rho], 0.0, ql.Normal)
        return NormalSabrVolCube._normalize_normal_vol(float(smile.volatility(strike, ql.Normal)))

    def atm_vol(
        self,
        opt_tenor: str | ql.Period,
        swap_tenor: str | ql.Period,
        vol_type: Any = None,
    ) -> float:
        if vol_type is None:
            vol_type = ql.Normal
        smile = self.smile_section(opt_tenor, swap_tenor)
        return NormalSabrVolCube._normalize_normal_vol(float(smile.volatility(smile.atmLevel(), vol_type)))

    def sabr_params_at(
        self,
        opt_tenor: str | ql.Period,
        swap_tenor: str | ql.Period,
    ) -> dict[str, float]:
        if isinstance(opt_tenor, str):
            opt_tenor = ql.Period(opt_tenor)
        if isinstance(swap_tenor, str):
            swap_tenor = ql.Period(swap_tenor)
        T = self.dc.yearFraction(self.today, self.cal.advance(self.today, opt_tenor))
        swap_yrs = self._base._tenor_to_years(str(swap_tenor))
        pt = np.array([[T, swap_yrs]])
        a, b, nu, rho, fwd = self._interpolate_params(pt)
        return {"alpha": a, "beta": b, "nu": nu, "rho": rho, "atmf_rate": fwd, "expiry_time": T}

    def atm_vol_matrix(
        self,
        expiry_labels: list[str],
        tail_labels: list[str],
    ) -> np.ndarray:
        matrix = np.empty((len(expiry_labels), len(tail_labels)), dtype=float)
        for i, exp in enumerate(expiry_labels):
            T = self._base._tenor_to_time(exp)
            for j, tail in enumerate(tail_labels):
                swap_yrs = self._base._tenor_to_years(tail)
                pt = np.array([[T, swap_yrs]])
                a, b, nu, rho, fwd = self._interpolate_params(pt)
                smile = ql.SabrSmileSection(T, fwd, [a, b, nu, rho], 0.0, ql.Normal)
                matrix[i, j] = NormalSabrVolCube._normalize_normal_vol(
                    float(smile.volatility(smile.atmLevel(), ql.Normal))
                )
        return matrix


# ----------------------------------------------------------------------
# Provider entry point
# ----------------------------------------------------------------------
def get_enhanced_vol_surfaces(
    *,
    curve_name: str,
    dates: Iterable[dt.date | dt.datetime],
    surface_type: str = "atmf_normal",
    data_dir: Optional[str] = None,
    **kwargs: Any,
) -> dict[dt.date, ql.SwaptionVolatilityStructureHandle]:
    """Build composite vol surfaces: GSQUANT ATM + MONKEYCUBE SABR skew.

    For each date the provider:
    1. Fetches the GSQUANT ATMF normal-vol grid (authoritative ATM).
    2. Loads the MONKEYCUBE SABR cube (skew shape).
    3. Re-calibrates SABR alpha at every grid node so ATM matches GSQUANT.
    4. Returns the GSQUANT ATM handle for ``BachelierSwaptionEngine``.
    5. Caches the :class:`EnhancedSabrVolCube` for metadata injection.
    """
    from MDP.IRSwaptions.GSQUANT.ql.grid import get_atmf_grid
    from MDP.IRSwaptions.MONKEYCUBE.provider import get_cached_cube, get_sabr_vol_surfaces

    # 1. GSQUANT ATM surfaces.
    gsquant_handles = get_atmf_grid(curve=curve_name, dates=dates, surface_type="atmf_normal")

    # 2. Build MONKEYCUBE cubes (populates _CUBE_CACHE as a side-effect).
    mc_kwargs: dict[str, Any] = dict(kwargs)
    if data_dir is not None:
        mc_kwargs["data_dir"] = data_dir
    _ = get_sabr_vol_surfaces(
        curve_name=curve_name, dates=dates, surface_type=surface_type, **mc_kwargs
    )

    # 3. For each date, build the enhanced cube.
    surfaces: dict[dt.date, ql.SwaptionVolatilityStructureHandle] = {}

    for d, gs_handle in gsquant_handles.items():
        mc_cube = get_cached_cube(curve_name, d)
        if mc_cube is None:
            # No MONKEYCUBE data — fall back to GSQUANT-only (no skew).
            surfaces[d] = gs_handle
            continue

        ql_eval = ql.Date(d.day, d.month, d.year)
        ql.Settings.instance().evaluationDate = ql_eval

        # Extract GSQUANT ATM vol matrix at GSQUANT grid nodes.
        gs_atm_matrix = np.empty((len(EXPIRY_LABELS), len(TAIL_LABELS)), dtype=float)
        for i, exp in enumerate(EXPIRY_LABELS):
            T_period = _label_to_ql_period(exp)
            option_date = gs_handle.optionDateFromTenor(T_period)
            for j, tail in enumerate(TAIL_LABELS):
                S_period = _label_to_ql_period(tail)
                gs_atm_matrix[i, j] = float(gs_handle.volatility(option_date, S_period, 0.0, True))

        enhanced = EnhancedSabrVolCube(
            base_cube=mc_cube,
            gsquant_atm_matrix=gs_atm_matrix,
            expiry_labels=EXPIRY_LABELS,
            tail_labels=TAIL_LABELS,
        )
        _ENHANCED_CUBE_CACHE[(curve_name, d.isoformat())] = enhanced

        # Return GSQUANT ATM handle as the vol surface for engine compatibility.
        surfaces[d] = gs_handle

    return surfaces


def get_cached_enhanced_cube(curve_name: str, d: dt.date) -> Optional[EnhancedSabrVolCube]:
    """Retrieve a previously built :class:`EnhancedSabrVolCube` from the module cache."""
    return _ENHANCED_CUBE_CACHE.get((curve_name, d.isoformat()))


def clear_enhanced_cube_cache() -> None:
    """Clear the module-level enhanced cube cache."""
    _ENHANCED_CUBE_CACHE.clear()

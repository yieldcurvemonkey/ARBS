"""UST Cash Spline: cross-sectional fitted curve for US Treasury bonds.

Provides a flexible, cacheable spline building framework following the
CORE (compute once, read everywhere) pattern.  Supports all interpolation
methods available in RVUtils.Interpolation and produces per-bond yield
errors / z-scores for relative-value analysis.

Usage
-----
    from MDP.FixedRateBonds.cash_spline import (
        CashSplineConfig, CashSpline, CashSplineBuilder,
    )

    cfg = CashSplineConfig(method="b_spline_with_knots", knots=[2,3,5,7,10,20,25])
    builder = CashSplineBuilder(cfg)
    spline  = builder.fit(ttm, ytm, cusips=cusips, weights=weights)
    print(spline.yield_at(7.5))
    print(spline.yield_errors)       # per-bond residuals (bp)
    print(spline.rmse)               # aggregate RMSE (bp)
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import pickle
import threading
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, Literal, Optional, Sequence, Tuple, Union

import numpy as np
import numpy.typing as npt
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Picklable tail-linearized evaluator (for disk caching)
# ---------------------------------------------------------------------------
class _TailLinearizedEvaluator:
    """Wraps a base interpolation callable with linear tails.

    Picklable — can be stored via diskcache / Supabase L2.
    """

    __slots__ = (
        "base_func", "x_min", "x_max",
        "left_base", "left_slope",
        "right_anchor", "right_base", "right_slope",
    )

    def __init__(
        self,
        *,
        base_func: Any,
        x_min: float,
        x_max: float,
        left_base: float,
        left_slope: float,
        right_anchor: float,
        right_base: float,
        right_slope: float,
    ) -> None:
        self.base_func = base_func
        self.x_min = x_min
        self.x_max = x_max
        self.left_base = left_base
        self.left_slope = left_slope
        self.right_anchor = right_anchor
        self.right_base = right_base
        self.right_slope = right_slope

    def __call__(self, t) -> np.ndarray:
        arr = np.atleast_1d(np.asarray(t, dtype=float))
        out = np.asarray(self.base_func(arr), dtype=float)
        left_mask = arr < self.x_min
        if np.any(left_mask):
            out = out.copy()
            out[left_mask] = self.left_base + self.left_slope * (arr[left_mask] - self.x_min)
        right_mask = arr > self.x_max
        if np.any(right_mask):
            if not np.any(left_mask):
                out = out.copy()
            out[right_mask] = self.right_base + self.right_slope * (arr[right_mask] - self.right_anchor)
        return out

    def __getstate__(self) -> dict:
        return {
            "base_func": self.base_func,
            "x_min": self.x_min,
            "x_max": self.x_max,
            "left_base": self.left_base,
            "left_slope": self.left_slope,
            "right_anchor": self.right_anchor,
            "right_base": self.right_base,
            "right_slope": self.right_slope,
        }

    def __setstate__(self, state: dict) -> None:
        for k, v in state.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class SplineMethod(str, Enum):
    """Interpolation / fitting methods available for cash spline building."""

    # Non-parametric splines
    LINEAR = "linear"
    LOG_LINEAR = "log_linear"
    CUBIC_SPLINE = "cubic_spline"
    CUBIC_HERMITE = "cubic_hermite"
    PCHIP = "pchip"
    AKIMA = "akima"
    B_SPLINE = "b_spline"
    B_SPLINE_WITH_KNOTS = "b_spline_with_knots"
    SMOOTHING_SPLINE = "smoothing_spline"
    LSQ_UNIVARIATE_SPLINE = "lsq_univariate_spline"
    UNIVARIATE_SPLINE = "univariate_spline"
    MONOTONE_CONVEX = "monotone_convex"
    LOESS = "loess"

    # Parametric yield-curve models
    NELSON_SIEGEL = "nelson_siegel"
    NELSON_SIEGEL_SVENSSON = "nelson_siegel_svensson"
    BJORK_CHRISTENSEN = "bjork_christensen"
    BJORK_CHRISTENSEN_AUGMENTED = "bjork_christensen_augmented"
    DIEBOLD_LI = "diebold_li"
    MLES = "mles"
    SMITH_WILSON = "smith_wilson"


class SplineYAxis(str, Enum):
    """What the y-axis of the spline represents."""

    YTM = "ytm"  # yield-to-maturity
    MMSS = "mmss"  # matched-maturity swap spread
    ASW = "asw"  # asset-swap spread
    Z_SPREAD = "z_spread"  # z-spread to OIS/SOFR


class BondWeighting(str, Enum):
    """Weighting scheme for the fitting objective."""

    EQUAL = "equal"
    BPV = "bpv"  # inverse BPV (normalizes to yield-space)
    DURATION = "duration"  # inverse modified duration
    CUSTOM = "custom"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CashSplineConfig:
    """Immutable configuration for building a UST cash spline.

    Parameters
    ----------
    method : SplineMethod | str
        Interpolation algorithm.  Any ``SplineMethod`` enum value or its
        string equivalent (e.g. ``"b_spline_with_knots"``).
    y_axis : SplineYAxis | str
        What the fitted y-axis represents (default ``"ytm"``).
    knots : tuple[float, ...] | None
        Interior knot positions for methods that accept them
        (``b_spline_with_knots``, ``lsq_univariate_spline``).
    degree : int
        Polynomial degree for B-spline methods (default 3).
    loess_frac : float
        Bandwidth fraction for LOESS (default 0.3).
    loess_it : int
        Robustness iterations for LOESS (default 3).
    smoothing_lambda : float | None
        Smoothing parameter for ``smoothing_spline``.
    ns_tau0 : float | tuple[float, float]
        Initial tau guess(es) for Nelson-Siegel / NSS calibration.
    mles_n : int
        Number of basis functions for Merrill-Lynch exponential spline.
    sw_ufr : float | None
        Ultimate forward rate for Smith-Wilson.
    weighting : BondWeighting | str
        How to weight bonds during fitting (default ``"equal"``).
    exclude_ranks : tuple[int, ...]
        Bond ranks to exclude (0 = OTR, 1 = old, 2 = double-old).
    min_ttm : float
        Minimum time-to-maturity in years (default 0.5).
    max_ttm : float | None
        Maximum time-to-maturity (default None = no cap).
    min_free_float_bn : float | None
        Minimum free-float in $bn (exclude illiquid stubs).
    exclude_repo_special_bp : float | None
        Exclude bonds whose repo rate is > N bp below GC.
    min_points : int
        Minimum number of bonds required for fitting (default 4).
    tail_linearize : bool
        Linearize beyond last-but-one data point (default True).
        Only applies to non-parametric spline methods.
    """

    method: str = SplineMethod.B_SPLINE_WITH_KNOTS.value
    y_axis: str = SplineYAxis.YTM.value

    # Spline-specific
    knots: Optional[Tuple[float, ...]] = (2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 25.0)
    degree: int = 3
    loess_frac: float = 0.3
    loess_it: int = 3
    smoothing_lambda: Optional[float] = None
    ns_tau0: Union[float, Tuple[float, float]] = (2.0, 5.0)
    mles_n: int = 8
    sw_ufr: Optional[float] = None

    # Weighting
    weighting: str = BondWeighting.EQUAL.value

    # Filtering
    exclude_ranks: Tuple[int, ...] = (0, 1, 2)
    min_ttm: float = 0.5
    max_ttm: Optional[float] = None
    min_free_float_bn: Optional[float] = None
    exclude_repo_special_bp: Optional[float] = None
    min_points: int = 4

    # Behavior
    tail_linearize: bool = True

    @property
    def config_hash(self) -> str:
        """Deterministic hash of config for cache keying."""
        raw = str(sorted(asdict(self).items())).encode()
        return hashlib.sha256(raw).hexdigest()[:16]

    def with_overrides(self, **kw) -> "CashSplineConfig":
        """Return a new config with the given fields replaced."""
        d = asdict(self)
        d.update(kw)
        # Freeze mutable defaults
        if isinstance(d.get("knots"), list):
            d["knots"] = tuple(d["knots"])
        if isinstance(d.get("exclude_ranks"), list):
            d["exclude_ranks"] = tuple(d["exclude_ranks"])
        return CashSplineConfig(**d)


# Pre-built config presets
ROLL_SPLINE_CONFIG = CashSplineConfig(
    method=SplineMethod.B_SPLINE.value,
    y_axis=SplineYAxis.YTM.value,
    knots=None,
    degree=3,
    exclude_ranks=(0, 1, 2),
    min_ttm=0.5,
    tail_linearize=True,
    weighting=BondWeighting.EQUAL.value,
)

JPM_PAR_CURVE_CONFIG = CashSplineConfig(
    method=SplineMethod.B_SPLINE_WITH_KNOTS.value,
    y_axis=SplineYAxis.YTM.value,
    knots=(2.0, 3.5, 5.0, 7.0, 10.0, 12.5, 15.0, 17.5, 20.0, 22.5, 25.0, 27.5),
    degree=3,
    exclude_ranks=(0, 1, 2),
    min_ttm=1.0,
    weighting=BondWeighting.BPV.value,
    tail_linearize=True,
)

MMSS_SPLINE_CONFIG = CashSplineConfig(
    method=SplineMethod.B_SPLINE_WITH_KNOTS.value,
    y_axis=SplineYAxis.MMSS.value,
    knots=(2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 25.0),
    degree=2,
    exclude_ranks=(0, 1, 2),
    min_ttm=1.0,
    weighting=BondWeighting.EQUAL.value,
)


# ---------------------------------------------------------------------------
# Fitted spline object
# ---------------------------------------------------------------------------
@dataclass
class CashSpline:
    """A fitted cash bond spline — the primary output of CashSplineBuilder.

    Attributes
    ----------
    curve_func : callable
        ``f(ttm) -> y``  where y is in the units of ``config.y_axis``.
    config : CashSplineConfig
        Configuration used for the fit.
    as_of_date : date | None
        Date the spline was fitted for (None for ad-hoc fits).
    fit_ttm : ndarray
        TTM values of bonds used in the fit.
    fit_y : ndarray
        Observed y values of the bonds used.
    fit_cusips : ndarray | None
        CUSIPs of the bonds in the fit (parallel to fit_ttm).
    fit_weights : ndarray | None
        Weights used (parallel to fit_ttm).
    fitted_y : ndarray
        Model-implied y at each fit_ttm.
    residuals : ndarray
        ``fit_y - fitted_y`` (positive = cheap, negative = rich in yield
        terms; reversed for spread-based y-axes).
    model_obj : Any
        The underlying calibrated model object (parametric curves) or None.
    """

    curve_func: Any  # Callable[[npt.ArrayLike], npt.ArrayLike]
    config: CashSplineConfig
    as_of_date: Optional[datetime.date] = None
    fit_ttm: Optional[np.ndarray] = None
    fit_y: Optional[np.ndarray] = None
    fit_cusips: Optional[np.ndarray] = None
    fit_weights: Optional[np.ndarray] = None
    fitted_y: Optional[np.ndarray] = None
    residuals: Optional[np.ndarray] = None
    model_obj: Any = None

    # ---- Evaluation ----
    def yield_at(self, ttm: Union[float, npt.ArrayLike]) -> Union[float, np.ndarray]:
        """Evaluate the fitted curve at arbitrary TTM(s)."""
        arr = np.atleast_1d(np.asarray(ttm, dtype=float))
        result = np.asarray(self.curve_func(arr), dtype=float)
        if np.ndim(ttm) == 0:
            return float(result.flat[0])
        return result

    def __call__(self, ttm: Union[float, npt.ArrayLike]) -> Union[float, np.ndarray]:
        return self.yield_at(ttm)

    # ---- Residual analytics ----
    @property
    def yield_errors(self) -> Optional[pd.Series]:
        """Per-bond yield errors (bp) indexed by CUSIP if available."""
        if self.residuals is None:
            return None
        errs = self.residuals * 100.0  # pct -> bp
        if self.fit_cusips is not None:
            return pd.Series(errs, index=self.fit_cusips, name="yield_error_bp")
        return pd.Series(errs, name="yield_error_bp")

    @property
    def rmse(self) -> Optional[float]:
        """Root-mean-squared yield error in basis points."""
        if self.residuals is None:
            return None
        return float(np.sqrt(np.mean(self.residuals ** 2)) * 100.0)

    @property
    def mae(self) -> Optional[float]:
        """Mean absolute yield error in basis points."""
        if self.residuals is None:
            return None
        return float(np.mean(np.abs(self.residuals)) * 100.0)

    def z_scores(self, lookback_residuals: Optional[pd.DataFrame] = None) -> Optional[pd.Series]:
        """Compute z-scores of current yield errors.

        Parameters
        ----------
        lookback_residuals : DataFrame, optional
            Historical yield errors (rows = dates, columns = CUSIPs, values
            in the same units as ``self.residuals``).  When provided the
            z-score is ``current_error / std(historical_errors)``.  When
            omitted, uses cross-sectional std of the current fit.
        """
        if self.residuals is None:
            return None
        errs = self.residuals

        if lookback_residuals is not None and self.fit_cusips is not None:
            zs = []
            for i, cusip in enumerate(self.fit_cusips):
                if cusip in lookback_residuals.columns:
                    hist = lookback_residuals[cusip].dropna()
                    sigma = hist.std()
                    zs.append(errs[i] / sigma if sigma > 1e-12 else np.nan)
                else:
                    zs.append(np.nan)
            return pd.Series(zs, index=self.fit_cusips, name="z_score")

        sigma = np.std(errs)
        if sigma < 1e-12:
            return None
        scores = errs / sigma
        if self.fit_cusips is not None:
            return pd.Series(scores, index=self.fit_cusips, name="z_score")
        return pd.Series(scores, name="z_score")

    # ---- Per-CUSIP lookups (for Value pattern integration) ----
    def spread_for_cusip(self, cusip: str) -> float:
        """Yield error (bp) for a single CUSIP.  Returns NaN if not in fit."""
        if self.fit_cusips is None or self.residuals is None:
            return float("nan")
        cusip_list = list(self.fit_cusips)
        if cusip not in cusip_list:
            return float("nan")
        idx = cusip_list.index(cusip)
        return float(self.residuals[idx] * 100.0)

    def z_score_for_cusip(
        self,
        cusip: str,
        lookback_residuals: Optional[pd.DataFrame] = None,
    ) -> float:
        """Z-score of yield error for a single CUSIP.

        Parameters
        ----------
        cusip : str
        lookback_residuals : DataFrame, optional
            Historical residuals (rows=dates, cols=CUSIPs, values in pct
            units matching ``self.residuals``).  Falls back to
            cross-sectional std when omitted.
        """
        if self.fit_cusips is None or self.residuals is None:
            return float("nan")
        cusip_list = list(self.fit_cusips)
        if cusip not in cusip_list:
            return float("nan")
        idx = cusip_list.index(cusip)
        err = self.residuals[idx]

        if lookback_residuals is not None and cusip in lookback_residuals.columns:
            sigma = lookback_residuals[cusip].dropna().std()
            return float(err / sigma) if sigma > 1e-12 else float("nan")

        sigma = float(np.std(self.residuals))
        return float(err / sigma) if sigma > 1e-12 else float("nan")

    def rmse_bucket(self, lo: float, hi: float) -> float:
        """RMSE (bp) for bonds with TTM in [lo, hi)."""
        if self.fit_ttm is None or self.residuals is None:
            return float("nan")
        mask = (self.fit_ttm >= lo) & (self.fit_ttm < hi)
        if not np.any(mask):
            return float("nan")
        return float(np.sqrt(np.mean(self.residuals[mask] ** 2)) * 100.0)

    def to_frame(self) -> pd.DataFrame:
        """Summary DataFrame of the fit — one row per bond."""
        data: Dict[str, Any] = {}
        if self.fit_cusips is not None:
            data["cusip"] = self.fit_cusips
        data["ttm"] = self.fit_ttm
        data["observed"] = self.fit_y
        data["fitted"] = self.fitted_y
        data["residual"] = self.residuals
        data["yield_error_bp"] = self.residuals * 100.0 if self.residuals is not None else None
        if self.fit_weights is not None:
            data["weight"] = self.fit_weights
        df = pd.DataFrame(data)
        if self.fit_cusips is not None:
            df = df.set_index("cusip")
        return df

    # ---- Serialization for caching ----
    def __getstate__(self) -> dict:
        state = {
            "config": self.config,
            "as_of_date": self.as_of_date,
            "fit_ttm": self.fit_ttm,
            "fit_y": self.fit_y,
            "fit_cusips": self.fit_cusips,
            "fit_weights": self.fit_weights,
            "fitted_y": self.fitted_y,
            "residuals": self.residuals,
            "curve_func": self.curve_func,
            "model_obj": self.model_obj,
        }
        return state

    def __setstate__(self, state: dict) -> None:
        for k, v in state.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
class CashSplineBuilder:
    """Builds a :class:`CashSpline` from bond data + config.

    This is the core engine: it handles filtering, weighting, delegation
    to ``GeneralCurveInterpolator``, residual computation, and optional
    tail linearization.
    """

    def __init__(self, config: Optional[CashSplineConfig] = None) -> None:
        self.config = config or CashSplineConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fit(
        self,
        ttm: npt.ArrayLike,
        y: npt.ArrayLike,
        *,
        cusips: Optional[npt.ArrayLike] = None,
        weights: Optional[npt.ArrayLike] = None,
        ranks: Optional[npt.ArrayLike] = None,
        free_float_bn: Optional[npt.ArrayLike] = None,
        as_of_date: Optional[datetime.date] = None,
    ) -> CashSpline:
        """Fit a cash spline to the provided bond data.

        Parameters
        ----------
        ttm : array-like
            Time-to-maturity in years for each bond.
        y : array-like
            Observed metric (YTM / MMSS / ASW / Z-spread) for each bond.
        cusips : array-like, optional
            CUSIP identifiers (parallel to ttm).
        weights : array-like, optional
            Per-bond weights.  Overrides ``config.weighting`` when provided.
        ranks : array-like, optional
            OTR rank per bond (0 = OTR).  Used for ``config.exclude_ranks``.
        free_float_bn : array-like, optional
            Free float in $bn.  Used for ``config.min_free_float_bn`` filter.
        as_of_date : date, optional
            Reference date for the fit.

        Returns
        -------
        CashSpline
        """
        cfg = self.config

        # --- Assemble working frame ---
        df = pd.DataFrame({
            "ttm": np.asarray(ttm, dtype=float),
            "y": np.asarray(y, dtype=float),
        })
        if cusips is not None:
            df["cusip"] = np.asarray(cusips)
        if ranks is not None:
            df["rank"] = np.asarray(ranks)
        if free_float_bn is not None:
            df["free_float_bn"] = np.asarray(free_float_bn, dtype=float)
        if weights is not None:
            df["weight"] = np.asarray(weights, dtype=float)

        # --- Filter ---
        df = self._apply_filters(df, cfg)

        if len(df) < cfg.min_points:
            raise ValueError(
                f"Insufficient data after filtering: {len(df)} bonds "
                f"(need >= {cfg.min_points})"
            )

        # --- Deduplicate by TTM (average) and sort ---
        has_cusips = "cusip" in df.columns
        if not has_cusips:
            df = (
                df.groupby("ttm", as_index=False)
                .agg({"y": "mean", **({k: "first" for k in df.columns if k not in ("ttm", "y")})})
                .sort_values("ttm")
            )
        else:
            df = df.sort_values("ttm")

        x_arr = df["ttm"].to_numpy(dtype=float)
        y_arr = df["y"].to_numpy(dtype=float)
        cusip_arr = df["cusip"].to_numpy() if has_cusips else None
        w_arr = df["weight"].to_numpy(dtype=float) if "weight" in df.columns else None

        # --- Build interpolation function ---
        curve_func, model_obj = self._build_curve(x_arr, y_arr, w_arr, cfg)

        # --- Optional tail linearization ---
        if cfg.tail_linearize and not self._is_parametric(cfg.method):
            curve_func = self._apply_tail_linearization(curve_func, x_arr, y_arr)

        # --- Evaluate fitted values & residuals ---
        fitted_y = np.asarray(curve_func(x_arr), dtype=float)
        residuals = y_arr - fitted_y

        return CashSpline(
            curve_func=curve_func,
            config=cfg,
            as_of_date=as_of_date,
            fit_ttm=x_arr,
            fit_y=y_arr,
            fit_cusips=cusip_arr,
            fit_weights=w_arr,
            fitted_y=fitted_y,
            residuals=residuals,
            model_obj=model_obj,
        )

    def fit_from_frame(
        self,
        df: pd.DataFrame,
        *,
        ttm_col: str = "ttm",
        y_col: str = "ytm",
        cusip_col: str = "cusip",
        rank_col: str = "rank",
        weight_col: Optional[str] = None,
        free_float_col: Optional[str] = None,
        as_of_date: Optional[datetime.date] = None,
    ) -> CashSpline:
        """Convenience: fit from a DataFrame with named columns."""
        kw: Dict[str, Any] = {}
        kw["ttm"] = df[ttm_col].to_numpy()
        kw["y"] = df[y_col].to_numpy()
        if cusip_col in df.columns:
            kw["cusips"] = df[cusip_col].to_numpy()
        if rank_col in df.columns:
            kw["ranks"] = df[rank_col].to_numpy()
        if weight_col and weight_col in df.columns:
            kw["weights"] = df[weight_col].to_numpy()
        if free_float_col and free_float_col in df.columns:
            kw["free_float_bn"] = df[free_float_col].to_numpy()
        return self.fit(**kw, as_of_date=as_of_date)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_filters(df: pd.DataFrame, cfg: CashSplineConfig) -> pd.DataFrame:
        out = df.copy()

        # Drop NaN / Inf
        out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=["ttm", "y"])

        # TTM range
        out = out[out["ttm"] >= cfg.min_ttm]
        if cfg.max_ttm is not None:
            out = out[out["ttm"] <= cfg.max_ttm]

        # Rank exclusion (OTR / old / double-old)
        if cfg.exclude_ranks and "rank" in out.columns:
            rank_num = pd.to_numeric(out["rank"], errors="coerce")
            out = out[~rank_num.isin(cfg.exclude_ranks)]

        # Free-float minimum
        if cfg.min_free_float_bn is not None and "free_float_bn" in out.columns:
            ff = pd.to_numeric(out["free_float_bn"], errors="coerce")
            out = out[ff >= cfg.min_free_float_bn]

        return out.reset_index(drop=True)

    # ------------------------------------------------------------------
    # Curve building dispatch
    # ------------------------------------------------------------------
    def _build_curve(
        self,
        x: np.ndarray,
        y: np.ndarray,
        w: Optional[np.ndarray],
        cfg: CashSplineConfig,
    ) -> Tuple[Callable, Any]:
        """Dispatch to the appropriate interpolation method.

        Returns (callable, model_obj_or_None).
        """
        from RVUtils.Interpolation.GeneralCurveInterpolator import GeneralCurveInterpolator

        method = cfg.method
        interp = GeneralCurveInterpolator(
            x=x, y=y,
            enable_extrapolate_left_fill=True,
            enable_extrapolate_right_fill=True,
            no_logs_plz=True,
        )

        # --- Non-parametric methods ---
        if method == SplineMethod.LINEAR.value:
            return interp.linear_interpolation(return_func=True), None

        if method == SplineMethod.LOG_LINEAR.value:
            return interp.log_linear_interpolation(return_func=True), None

        if method == SplineMethod.CUBIC_SPLINE.value:
            return interp.cubic_spline_interpolation(return_func=True), None

        if method == SplineMethod.CUBIC_HERMITE.value:
            return interp.cubic_hermite_interpolation(return_func=True), None

        if method == SplineMethod.PCHIP.value:
            return interp.pchip_interpolation(return_func=True), None

        if method == SplineMethod.AKIMA.value:
            return interp.akima_interpolation(return_func=True), None

        if method == SplineMethod.B_SPLINE.value:
            degree = max(1, min(cfg.degree, len(x) - 1))
            return interp.b_spline1_interpolation(k=degree, return_func=True), None

        if method == SplineMethod.B_SPLINE_WITH_KNOTS.value:
            knots = np.array(cfg.knots or []) if cfg.knots else None
            if knots is not None:
                # Only keep knots strictly inside the data range
                knots = knots[(knots > x.min()) & (knots < x.max())]
            if knots is None or len(knots) == 0:
                degree = max(1, min(cfg.degree, len(x) - 1))
                return interp.b_spline1_interpolation(k=degree, return_func=True), None
            degree = min(cfg.degree, len(x) - len(knots) - 1)
            degree = max(1, degree)
            return interp.b_spline_with_knots_interpolation(
                knots=knots, k=degree, return_func=True,
            ), None

        if method == SplineMethod.SMOOTHING_SPLINE.value:
            func = interp.smoothing_spline(lam=cfg.smoothing_lambda)
            return func, None

        if method == SplineMethod.LSQ_UNIVARIATE_SPLINE.value:
            knots = np.array(cfg.knots or [])
            knots = knots[(knots > x.min()) & (knots < x.max())]
            if len(knots) == 0:
                return interp.b_spline1_interpolation(k=cfg.degree, return_func=True), None
            return interp.lsq_univariate_spline(knots=knots, k=cfg.degree), None

        if method == SplineMethod.UNIVARIATE_SPLINE.value:
            return interp.univariate_spline(s=cfg.smoothing_lambda or 0.0, return_func=True), None

        if method == SplineMethod.MONOTONE_CONVEX.value:
            return interp.monotone_convex(return_func=True), None

        if method == SplineMethod.LOESS.value:
            return interp.loess_interpolation(
                frac=cfg.loess_frac, it=cfg.loess_it, return_func=True,
            ), None

        # --- Parametric models ---
        if method == SplineMethod.NELSON_SIEGEL.value:
            tau0 = cfg.ns_tau0 if isinstance(cfg.ns_tau0, (int, float)) else cfg.ns_tau0[0]
            curve, opt = interp.calibrate_ns_ols(tau0=float(tau0))
            return lambda t: curve(np.atleast_1d(t)), curve

        if method == SplineMethod.NELSON_SIEGEL_SVENSSON.value:
            tau0 = cfg.ns_tau0 if isinstance(cfg.ns_tau0, tuple) else (cfg.ns_tau0, 5.0)
            try:
                if w is not None:
                    curve, opt, _ = interp.calibrate_nss_weighted_ols(
                        weights=w, tau0=tau0,
                    )
                else:
                    curve, opt, _ = interp.calibrate_nss_ols(tau0=tau0)
                return lambda t: curve(np.atleast_1d(t)), curve
            except np.linalg.LinAlgError:
                # SVD convergence failure — fall back to Nelson-Siegel
                logger.warning("NSS calibration failed (SVD); falling back to NS")
                tau0_ns = float(tau0[0]) if isinstance(tau0, tuple) else float(tau0)
                curve, opt = interp.calibrate_ns_ols(tau0=tau0_ns)
                return lambda t: curve(np.atleast_1d(t)), curve

        if method == SplineMethod.BJORK_CHRISTENSEN.value:
            tau0 = cfg.ns_tau0 if isinstance(cfg.ns_tau0, (int, float)) else cfg.ns_tau0[0]
            curve, opt = interp.calibrate_bc_ols(tau0=float(tau0))
            return lambda t: curve(np.atleast_1d(t)), curve

        if method == SplineMethod.BJORK_CHRISTENSEN_AUGMENTED.value:
            curve, opt = interp.calibrate_bc_augmented()
            return lambda t: curve(np.atleast_1d(t)), curve

        if method == SplineMethod.DIEBOLD_LI.value:
            curve, opt = interp.calibrate_diebold_li_ols()
            return lambda t: curve(np.atleast_1d(t)), curve

        if method == SplineMethod.MLES.value:
            curve, opt = interp.calibrate_mles_ols(N=cfg.mles_n)
            return lambda t: curve(np.atleast_1d(t)), curve

        if method == SplineMethod.SMITH_WILSON.value:
            curve, opt = interp.calibrate_smith_wilson_ols(
                ufr=cfg.sw_ufr, alpha_initial=0.1,
            )
            return lambda t: curve(np.atleast_1d(t)), curve

        raise ValueError(f"Unsupported spline method: {method}")

    # ------------------------------------------------------------------
    # Tail linearization
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_tail_linearization(
        base_func: Callable,
        x: np.ndarray,
        y: np.ndarray,
    ) -> Callable:
        """Wrap ``base_func`` with linear tails beyond data boundaries.

        Returns a picklable :class:`_TailLinearizedEvaluator`.
        """
        if len(x) < 2:
            return base_func

        x_min = float(x[0])
        x_max = float(x[-1])
        left_slope = float(y[1] - y[0]) / float(x[1] - x[0]) if x[1] != x[0] else 0.0
        left_base = float(y[0])
        right_anchor = float(x[-2])
        right_base = float(np.asarray(base_func(np.array([right_anchor])), dtype=float).flat[0])
        right_slope = float(y[-1] - y[-2]) / float(x[-1] - x[-2]) if x[-1] != x[-2] else 0.0

        return _TailLinearizedEvaluator(
            base_func=base_func,
            x_min=x_min,
            x_max=x_max,
            left_base=left_base,
            left_slope=left_slope,
            right_anchor=right_anchor,
            right_base=right_base,
            right_slope=right_slope,
        )

    @staticmethod
    def _is_parametric(method: str) -> bool:
        return method in {
            SplineMethod.NELSON_SIEGEL.value,
            SplineMethod.NELSON_SIEGEL_SVENSSON.value,
            SplineMethod.BJORK_CHRISTENSEN.value,
            SplineMethod.BJORK_CHRISTENSEN_AUGMENTED.value,
            SplineMethod.DIEBOLD_LI.value,
            SplineMethod.MLES.value,
            SplineMethod.SMITH_WILSON.value,
        }


# ---------------------------------------------------------------------------
# Caching infrastructure (CORE pattern)
# ---------------------------------------------------------------------------
_SPLINE_CACHE_VERSION = 1
_SPLINE_CACHE_NS = f"frb_cash_spline_v{_SPLINE_CACHE_VERSION}"
_SPLINE_MEM_CACHE: Dict[str, CashSpline] = {}
_SPLINE_MEM_CACHE_LOCK = threading.RLock()
_SPLINE_DISK_CACHE: Any = None
_SPLINE_DISK_CACHE_LOCK = threading.RLock()


def _resolve_spline_cache_dir() -> Path:
    import os
    arbs_cache_dir = os.getenv("ARBS_CACHE_DIR")
    if arbs_cache_dir:
        return (Path(arbs_cache_dir) / "MDP" / "FixedRateBonds" / "cash_spline_cache").resolve()
    try:
        from platformdirs import user_cache_dir
        return (Path(user_cache_dir(appname="ARBS", appauthor=False)) / "MDP" / "FixedRateBonds" / "cash_spline_cache").resolve()
    except Exception:
        if os.name == "nt":
            return (Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ARBS" / "MDP" / "FixedRateBonds" / "cash_spline_cache").resolve()
        return (Path.home() / ".cache" / "arbs" / "MDP" / "FixedRateBonds" / "cash_spline_cache").resolve()


def _get_spline_disk_cache() -> Any:
    global _SPLINE_DISK_CACHE
    with _SPLINE_DISK_CACHE_LOCK:
        if _SPLINE_DISK_CACHE is None:
            import diskcache
            cache_dir = _resolve_spline_cache_dir()
            cache_dir.mkdir(parents=True, exist_ok=True)
            local_cache = diskcache.Cache(directory=str(cache_dir))
            try:
                from Caching.supabase_engine import SUPABASE_ENABLED
                from Caching.layered_cache_mixin import LayeredDictProxy
                if SUPABASE_ENABLED:
                    _SPLINE_DISK_CACHE = LayeredDictProxy(
                        local_cache, _SPLINE_CACHE_NS,
                        l2_read=True, l2_write=True,
                        ttl_seconds=365 * 24 * 3600,
                    )
                else:
                    _SPLINE_DISK_CACHE = local_cache
            except Exception:
                _SPLINE_DISK_CACHE = local_cache
        return _SPLINE_DISK_CACHE


def _spline_cache_key(as_of_date: datetime.date, config_hash: str) -> str:
    return f"cash_spline:v{_SPLINE_CACHE_VERSION}:{as_of_date.isoformat()}:{config_hash}"


def get_cached_spline(
    as_of_date: datetime.date,
    config: CashSplineConfig,
) -> Optional[CashSpline]:
    """Retrieve a previously cached spline (memory → disk → L2)."""
    key = _spline_cache_key(as_of_date, config.config_hash)

    # L0: in-memory
    with _SPLINE_MEM_CACHE_LOCK:
        hit = _SPLINE_MEM_CACHE.get(key)
    if hit is not None:
        return hit

    # L1/L2: disk / Supabase
    try:
        payload = _get_spline_disk_cache().get(key)
    except Exception:
        payload = None
    if isinstance(payload, CashSpline):
        with _SPLINE_MEM_CACHE_LOCK:
            _SPLINE_MEM_CACHE[key] = payload
        return payload

    return None


def put_cached_spline(spline: CashSpline) -> None:
    """Store a fitted spline into the cache hierarchy."""
    if spline.as_of_date is None:
        return
    key = _spline_cache_key(spline.as_of_date, spline.config.config_hash)

    with _SPLINE_MEM_CACHE_LOCK:
        _SPLINE_MEM_CACHE[key] = spline
    try:
        _get_spline_disk_cache()[key] = spline
    except Exception:
        logger.debug("Failed to write spline to disk cache for %s", key, exc_info=True)


def clear_spline_cache(*, include_persistent: bool = True) -> None:
    """Clear all cached splines."""
    with _SPLINE_MEM_CACHE_LOCK:
        _SPLINE_MEM_CACHE.clear()
    if include_persistent:
        try:
            _get_spline_disk_cache().clear()
        except Exception:
            pass

from __future__ import annotations

import math
import re
from typing import Any, Optional

import numpy as np
import QuantLib as ql
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel


class NormalSabrVolCube:
    """
    Swaption volatility cube using pre-calibrated normal SABR parameters.

    Interpolates SABR params (alpha, nu, rho) and forward rates across the
    (option_expiry, swap_tenor) surface via Gaussian Process regression in
    log-space, then evaluates the Hagan normal SABR expansion analytically
    at any strike.

    Beta is treated as a constant (typically ~0.50 across all nodes) and is
    stored as the mean of all calibrated beta values rather than interpolated.

    Parameters
    ----------
    sabr_params_map : dict
        Keyed by "{expiry}x{tenor}" (e.g., "1Yx10Y"). Each value is a dict
        with keys: alpha, beta, nu, rho, atmf_rate. Current MonkeyCube JSON
        files yield normal-vol outputs in bp-vol units, so this wrapper
        normalizes returned vols to decimal before exposing them downstream.
    cal : ql.Calendar
        Business day calendar.
    dc : ql.DayCounter
        Day count convention.
    today : ql.Date
        Evaluation date.
    """

    def __init__(
        self,
        sabr_params_map: dict[str, dict[str, float]],
        cal: ql.Calendar,
        dc: ql.DayCounter,
        today: ql.Date,
    ):
        self.params = sabr_params_map
        self.cal = cal
        self.dc = dc
        self.today = today

        keys = list(sabr_params_map.keys())
        points: list[list[float]] = []
        param_arrays: dict[str, list[float]] = {p: [] for p in ["alpha", "nu", "rho"]}
        beta_list: list[float] = []
        fwd_list: list[float] = []

        for k in keys:
            o, s = k.split("x")
            T = self._tenor_to_time(o)
            swap_yrs = self._tenor_to_years(s)
            points.append([T, swap_yrs])
            for p in param_arrays:
                param_arrays[p].append(sabr_params_map[k][p])
            beta_list.append(sabr_params_map[k]["beta"])
            fwd_list.append(sabr_params_map[k]["atmf_rate"])

        pts = np.array(points)

        # Log-space transform for GP training coordinates
        log_pts = np.log(pts)
        self._log_min = log_pts.min(axis=0)
        self._log_max = log_pts.max(axis=0)

        # Beta is near-constant across all nodes — store as scalar
        self._beta = float(np.mean(beta_list))

        # Fit independent GPs for alpha, nu, rho, and forward rate
        kernel = (
            ConstantKernel(1.0, constant_value_bounds=(1e-3, 1e3))
            * Matern(nu=2.5, length_scale=[1.0, 1.0], length_scale_bounds=(1e-2, 1e2))
            + WhiteKernel(noise_level=1e-6, noise_level_bounds=(1e-10, 1e-2))
        )

        self._gps: dict[str, GaussianProcessRegressor] = {}
        for p in param_arrays:
            vals = np.array(param_arrays[p])
            gp = GaussianProcessRegressor(
                kernel=kernel,
                n_restarts_optimizer=3,
                normalize_y=True,
                alpha=1e-8,
            )
            gp.fit(log_pts, vals)
            self._gps[p] = gp

        fwd_vals = np.array(fwd_list)
        gp_fwd = GaussianProcessRegressor(
            kernel=kernel,
            n_restarts_optimizer=3,
            normalize_y=True,
            alpha=1e-8,
        )
        gp_fwd.fit(log_pts, fwd_vals)
        self._gps["fwd"] = gp_fwd

    @staticmethod
    def _tenor_to_years(tenor: str) -> float:
        m = re.fullmatch(r"(\d+)\s*([YMWD])", tenor.upper())
        if not m:
            raise ValueError(f"Bad tenor: {tenor}")
        n, u = int(m.group(1)), m.group(2)
        return {"Y": float(n), "M": n / 12.0, "W": n * 7.0 / 365.0, "D": n / 365.0}[u]

    def _tenor_to_time(self, tenor: str) -> float:
        p = ql.Period(tenor)
        end = self.cal.advance(self.today, p)
        return self.dc.yearFraction(self.today, end)

    def _gp_predict(self, gp: GaussianProcessRegressor, pt_log: np.ndarray) -> float:
        """Predict a single value from a fitted GP, clamping input to the training bounding box."""
        clamped = np.clip(pt_log, self._log_min, self._log_max)
        return float(gp.predict(clamped.reshape(1, -1))[0])

    def _interpolate_params(self, pt: np.ndarray) -> tuple[float, float, float, float, float]:
        pt_log = np.log(np.clip(pt.ravel()[:2], a_min=1e-10, a_max=None))

        a = self._gp_predict(self._gps["alpha"], pt_log)
        nu = self._gp_predict(self._gps["nu"], pt_log)
        rho = self._gp_predict(self._gps["rho"], pt_log)
        fwd = self._gp_predict(self._gps["fwd"], pt_log)

        # Safety clamps for SABR parameter constraints
        a = max(a, 1e-6)
        nu = max(nu, 0.0)
        rho = np.clip(rho, -0.9999, 0.9999)

        return a, self._beta, nu, rho, fwd

    @staticmethod
    def _normalize_normal_vol(vol: float) -> float:
        v = float(vol)
        # MonkeyCube SABR files currently yield normal vols in bp-vol units
        # (e.g. ~78 instead of 0.0078). Downstream IR swaption pricing expects
        # decimal vols, so normalize only these clearly out-of-scale values.
        return v / 10_000.0 if abs(v) > 1.0 else v

    def smile_section(
        self,
        opt_tenor: str | ql.Period,
        swap_tenor: str | ql.Period,
    ) -> ql.SabrSmileSection:
        """
        Return a ql.SabrSmileSection for any (expiry, tail) point.

        Parameters
        ----------
        opt_tenor : str or ql.Period
            Option expiry (e.g., "6M", "1Y").
        swap_tenor : str or ql.Period
            Swap tail (e.g., "10Y", "7Y").

        Returns
        -------
        ql.SabrSmileSection
            Normal SABR smile section.
        """
        if isinstance(opt_tenor, str):
            opt_tenor = ql.Period(opt_tenor)
        if isinstance(swap_tenor, str):
            swap_tenor = ql.Period(swap_tenor)

        T = self.dc.yearFraction(self.today, self.cal.advance(self.today, opt_tenor))
        swap_yrs = self._tenor_to_years(str(swap_tenor))
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
        """
        Implied volatility at a specific (expiry, tenor, strike) triple.

        Parameters
        ----------
        opt_tenor : str or ql.Period
        swap_tenor : str or ql.Period
        strike : float
            Absolute strike in decimal (e.g., 0.0375 for 3.75%).
        vol_type : ql.VolatilityType, optional
            Output convention. Defaults to ql.Normal.

        Returns
        -------
        float
            Implied volatility in the requested convention.
        """
        if vol_type is None:
            vol_type = ql.Normal
        smile = self.smile_section(opt_tenor, swap_tenor)
        return self._normalize_normal_vol(float(smile.volatility(strike, vol_type)))

    def volatility_at_point(
        self,
        option_time: float,
        swap_years: float,
        strike: float,
    ) -> float:
        """
        Implied normal vol at a specific (option_time, swap_years, strike) point.

        This method bypasses tenor parsing and works directly with year fractions,
        which is useful for date-based queries from the pricer layer.

        Parameters
        ----------
        option_time : float
            Time to option expiry in year fractions.
        swap_years : float
            Swap length in years.
        strike : float
            Absolute strike in decimal.

        Returns
        -------
        float
            Normal implied volatility (decimal, not bps).
        """
        pt = np.array([[option_time, swap_years]])
        a, b, nu, rho, fwd = self._interpolate_params(pt)
        smile = ql.SabrSmileSection(option_time, fwd, [a, b, nu, rho], 0.0, ql.Normal)
        return self._normalize_normal_vol(float(smile.volatility(strike, ql.Normal)))

    def atm_vol(
        self,
        opt_tenor: str | ql.Period,
        swap_tenor: str | ql.Period,
        vol_type: Any = None,
    ) -> float:
        """ATM implied vol (strike = forward) at a given (expiry, tenor) node."""
        if vol_type is None:
            vol_type = ql.Normal
        smile = self.smile_section(opt_tenor, swap_tenor)
        return self._normalize_normal_vol(float(smile.volatility(smile.atmLevel(), vol_type)))

    def sabr_params_at(
        self,
        opt_tenor: str | ql.Period,
        swap_tenor: str | ql.Period,
    ) -> dict[str, float]:
        """
        Return interpolated SABR params and forward at an arbitrary point.

        Returns
        -------
        dict with keys: alpha, beta, nu, rho, atmf_rate, expiry_time
        """
        if isinstance(opt_tenor, str):
            opt_tenor = ql.Period(opt_tenor)
        if isinstance(swap_tenor, str):
            swap_tenor = ql.Period(swap_tenor)

        T = self.dc.yearFraction(self.today, self.cal.advance(self.today, opt_tenor))
        swap_yrs = self._tenor_to_years(str(swap_tenor))
        pt = np.array([[T, swap_yrs]])

        a, b, nu, rho, fwd = self._interpolate_params(pt)
        return {
            "alpha": a,
            "beta": b,
            "nu": nu,
            "rho": rho,
            "atmf_rate": fwd,
            "expiry_time": T,
        }

    def atm_vol_matrix(
        self,
        expiry_labels: list[str],
        tail_labels: list[str],
    ) -> np.ndarray:
        """
        Extract an ATM normal vol matrix for building a QuantLib SwaptionVolatilityMatrix.

        Returns shape (len(expiry_labels), len(tail_labels)) with vols in decimal.
        Uses the interpolated SABR params at each (expiry, tail) point.
        """
        matrix = np.empty((len(expiry_labels), len(tail_labels)), dtype=float)
        for i, exp in enumerate(expiry_labels):
            T = self._tenor_to_time(exp)
            for j, tail in enumerate(tail_labels):
                swap_yrs = self._tenor_to_years(tail)
                pt = np.array([[T, swap_yrs]])
                a, b, nu, rho, fwd = self._interpolate_params(pt)
                smile = ql.SabrSmileSection(T, fwd, [a, b, nu, rho], 0.0, ql.Normal)
                matrix[i, j] = self._normalize_normal_vol(float(smile.volatility(smile.atmLevel(), ql.Normal)))
        return matrix

import math
from typing import Sequence, Tuple

import numpy as np
from scipy.optimize import differential_evolution, least_squares, minimize
from scipy.stats import norm


_INVALID_OBJECTIVE = 1e12
_INVALID_RESIDUAL = 1e6


def _normal_delta_to_strike(
    *,
    delta_abs: float,
    vol_normal: float,
    forward: float,
    time_to_expiry: float,
    right: str,
) -> float:
    right_token = str(right or "").strip().upper()
    if right_token not in {"C", "P"}:
        raise ValueError(f"Unsupported option right for delta inversion: {right}")
    target = float(delta_abs)
    if target <= 0.0 or target >= 1.0:
        raise ValueError(f"delta_abs must be in (0,1): {delta_abs}")
    scale = float(vol_normal) * math.sqrt(max(float(time_to_expiry), 1e-12))
    call_delta = target if right_token == "C" else (1.0 - target)
    return float(forward) - scale * float(norm.ppf(call_delta))


def _sabr_normal_vol(
    *,
    strike: float,
    forward: float,
    time_to_expiry: float,
    alpha: float,
    beta: float,
    rho: float,
    nu: float,
) -> float:
    eps = 1e-12
    f = float(forward)
    k = float(strike)
    t = max(float(time_to_expiry), 0.0)
    a = float(alpha)
    b = float(beta)
    r = float(rho)
    n = float(nu)

    if abs(f - k) < eps:
        correction = (
            ((b - 1.0) * (b - 2.0) * a * a) / (24.0 * (f ** (2.0 - 2.0 * b)))
            + (r * b * n * a) / (4.0 * (f ** (1.0 - b)))
            + ((2.0 - 3.0 * r * r) * n * n) / 24.0
        )
        return a * (f ** b) * (1.0 + correction * t)

    log_fk = math.log(f / k)
    f_mid = math.sqrt(f * k)

    if abs(b - 1.0) < eps:
        zeta = (n / a) * log_fk
    else:
        zeta = (n / a) * ((f ** (1.0 - b) - k ** (1.0 - b)) / (1.0 - b))

    disc = math.sqrt(max(1.0 - 2.0 * r * zeta + zeta * zeta, 1e-18))
    x_zeta = math.log((disc + zeta - r) / (1.0 - r))
    zeta_over_x = 1.0 if abs(x_zeta) < eps else zeta / x_zeta

    if abs(b) < eps:
        prefactor = a
    elif abs(b - 1.0) < eps:
        prefactor = a * (f - k) / log_fk
    else:
        prefactor = a * (1.0 - b) * (f - k) / (f ** (1.0 - b) - k ** (1.0 - b))

    correction = (
        ((b - 1.0) * (b - 2.0) * a * a) / (24.0 * (f_mid ** (2.0 - 2.0 * b)))
        + (r * b * n * a) / (4.0 * (f_mid ** (1.0 - b)))
        + ((2.0 - 3.0 * r * r) * n * n) / 24.0
    )
    return prefactor * zeta_over_x * (1.0 + correction * t)


def _collapse_duplicate_strikes(
    strikes: np.ndarray,
    vols: np.ndarray,
    *,
    tol: float = 1e-10,
) -> Tuple[np.ndarray, np.ndarray]:
    if strikes.size == 0:
        return strikes, vols
    order = np.argsort(strikes)
    srt_strikes = strikes[order]
    srt_vols = vols[order]
    out_strikes = []
    out_vols = []
    bucket = [float(srt_vols[0])]
    anchor = float(srt_strikes[0])
    for strike, vol in zip(srt_strikes[1:], srt_vols[1:]):
        if abs(float(strike) - anchor) <= tol:
            bucket.append(float(vol))
            continue
        out_strikes.append(anchor)
        out_vols.append(float(sum(bucket) / len(bucket)))
        anchor = float(strike)
        bucket = [float(vol)]
    out_strikes.append(anchor)
    out_vols.append(float(sum(bucket) / len(bucket)))
    return np.asarray(out_strikes, dtype=float), np.asarray(out_vols, dtype=float)


def _sabr_model_vols(
    params: Sequence[float],
    strikes_arr: np.ndarray,
    *,
    forward: float,
    time_to_expiry: float,
    beta: float,
) -> np.ndarray:
    alpha, rho, nu = (float(params[0]), float(params[1]), float(params[2]))
    return np.asarray(
        [
            _sabr_normal_vol(
                strike=float(k),
                forward=float(forward),
                time_to_expiry=float(time_to_expiry),
                alpha=alpha,
                beta=float(beta),
                rho=rho,
                nu=nu,
            )
            for k in strikes_arr
        ],
        dtype=float,
    )


def _prepare_calibration_inputs(
    forward: float,
    time_to_expiry: float,
    strikes_arr: Sequence[float],
    vols_arr: Sequence[float],
    beta: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    forward_val = float(forward)
    time_val = float(time_to_expiry)
    beta_val = float(beta)
    if not math.isfinite(forward_val) or forward_val <= 0.0:
        raise ValueError(f"Invalid forward for SABR calibration: {forward}")
    if not math.isfinite(time_val) or time_val <= 0.0:
        raise ValueError(f"Invalid time_to_expiry for SABR calibration: {time_to_expiry}")
    if not math.isfinite(beta_val):
        raise ValueError(f"Invalid beta for SABR calibration: {beta}")

    strike_values = np.asarray(strikes_arr, dtype=float)
    vol_values = np.asarray(vols_arr, dtype=float)
    if strike_values.ndim != 1 or vol_values.ndim != 1 or strike_values.size != vol_values.size:
        raise ValueError("SABR calibration requires 1D strike and vol arrays of equal length.")
    if strike_values.size == 0:
        raise ValueError("SABR calibration requires at least one strike-vol point.")

    valid = (
        np.isfinite(strike_values)
        & np.isfinite(vol_values)
        & (strike_values > 0.0)
        & (vol_values > 0.0)
    )
    strike_values = strike_values[valid]
    vol_values = vol_values[valid]
    if strike_values.size == 0:
        raise ValueError("SABR calibration requires at least one positive finite strike-vol point.")

    order = np.argsort(strike_values)
    strike_values = strike_values[order]
    vol_values = vol_values[order]
    collapsed_strikes, collapsed_vols = _collapse_duplicate_strikes(strike_values, vol_values)
    if collapsed_strikes.size == 0:
        raise ValueError("No SABR calibration points remain after collapsing duplicate strikes.")

    atm_idx = int(np.argmin(np.abs(collapsed_strikes - forward_val)))
    atm_vol = float(collapsed_vols[atm_idx])
    if not math.isfinite(atm_vol) or atm_vol <= 0.0:
        raise ValueError(f"Invalid ATM normal vol seed for SABR calibration: {atm_vol}")

    near_forward_width = 2.0 * atm_vol * math.sqrt(time_val)
    weights = np.ones_like(collapsed_vols, dtype=float)
    weights[np.abs(collapsed_strikes - forward_val) <= near_forward_width] *= 2.0
    alpha0 = float(atm_vol / (forward_val ** beta_val))
    if not math.isfinite(alpha0) or alpha0 <= 0.0:
        raise ValueError(f"Invalid alpha seed for SABR calibration: {alpha0}")

    return collapsed_strikes, collapsed_vols, weights, atm_vol, alpha0


def _sabr_objective(
    x: np.ndarray,
    strikes_arr: np.ndarray,
    vols_arr: np.ndarray,
    weights: np.ndarray,
    forward: float,
    time_to_expiry: float,
    beta: float,
) -> float:
    alpha, rho, nu = (float(x[0]), float(x[1]), float(x[2]))
    if alpha <= 0.0 or nu <= 0.0 or abs(rho) >= 1.0:
        return _INVALID_OBJECTIVE
    try:
        model = _sabr_model_vols(
            x,
            strikes_arr,
            forward=float(forward),
            time_to_expiry=float(time_to_expiry),
            beta=float(beta),
        )
    except Exception:
        return _INVALID_OBJECTIVE
    if not np.all(np.isfinite(model)):
        return _INVALID_OBJECTIVE
    err = model - vols_arr
    return float(np.sum(weights * err * err))


def _sabr_residual_vector(
    x: np.ndarray,
    strikes_arr: np.ndarray,
    vols_arr: np.ndarray,
    weights: np.ndarray,
    forward: float,
    time_to_expiry: float,
    beta: float,
) -> np.ndarray:
    alpha, rho, nu = (float(x[0]), float(x[1]), float(x[2]))
    if alpha <= 0.0 or nu <= 0.0 or abs(rho) >= 1.0:
        return np.full(len(strikes_arr), _INVALID_RESIDUAL, dtype=float)
    try:
        model = _sabr_model_vols(
            x,
            strikes_arr,
            forward=float(forward),
            time_to_expiry=float(time_to_expiry),
            beta=float(beta),
        )
    except Exception:
        return np.full(len(strikes_arr), _INVALID_RESIDUAL, dtype=float)
    if not np.all(np.isfinite(model)):
        return np.full(len(strikes_arr), _INVALID_RESIDUAL, dtype=float)
    return np.sqrt(weights) * (model - vols_arr)


def _calibrate_nelder_mead(
    strikes: np.ndarray,
    vols: np.ndarray,
    weights: np.ndarray,
    forward: float,
    tte: float,
    beta: float,
    alpha0: float,
) -> Tuple[float, float, float]:
    result = minimize(
        _sabr_objective,
        x0=np.asarray([float(alpha0), -0.1, 0.3], dtype=float),
        args=(strikes, vols, weights, float(forward), float(tte), float(beta)),
        method="Nelder-Mead",
        options={"maxiter": 10000, "xatol": 1e-10, "fatol": 1e-12},
    )
    return float(result.x[0]), float(result.x[1]), float(result.x[2])


def _weighted_fit_score(
    params: Sequence[float],
    strikes: np.ndarray,
    vols: np.ndarray,
    weights: np.ndarray,
    *,
    forward: float,
    tte: float,
    beta: float,
) -> float:
    residuals = _sabr_residual_vector(
        np.asarray(params, dtype=float),
        strikes,
        vols,
        weights,
        float(forward),
        float(tte),
        float(beta),
    )
    return float(np.dot(residuals, residuals))


def _calibrate_de_gn(
    strikes: np.ndarray,
    vols: np.ndarray,
    weights: np.ndarray,
    forward: float,
    tte: float,
    beta: float,
    alpha0: float,
) -> Tuple[float, float, float]:
    alpha_lower = max(1e-8, 0.2 * float(alpha0))
    alpha_upper = max(alpha_lower * 1.0001, 5.0 * float(alpha0))
    bounds = [
        (alpha_lower, alpha_upper),
        (-0.999, 0.999),
        (0.01, 10.0),
    ]

    de_result = differential_evolution(
        _sabr_objective,
        bounds=bounds,
        args=(strikes, vols, weights, float(forward), float(tte), float(beta)),
        maxiter=200,
        tol=1e-8,
        seed=42,
        polish=False,
    )
    best_params = np.asarray(de_result.x, dtype=float)
    best_score = _weighted_fit_score(
        best_params,
        strikes,
        vols,
        weights,
        forward=float(forward),
        tte=float(tte),
        beta=float(beta),
    )

    try:
        gn_result = least_squares(
            _sabr_residual_vector,
            best_params,
            args=(strikes, vols, weights, float(forward), float(tte), float(beta)),
            bounds=(
                np.asarray([alpha_lower, -0.999, 0.01], dtype=float),
                np.asarray([alpha_upper, 0.999, 10.0], dtype=float),
            ),
            method="trf",
        )
    except Exception:
        gn_result = None

    if gn_result is not None and np.all(np.isfinite(gn_result.x)):
        gn_score = _weighted_fit_score(
            gn_result.x,
            strikes,
            vols,
            weights,
            forward=float(forward),
            tte=float(tte),
            beta=float(beta),
        )
        if gn_result.success and gn_score <= best_score + 1e-12:
            best_params = np.asarray(gn_result.x, dtype=float)

    return float(best_params[0]), float(best_params[1]), float(best_params[2])


def calculate_calibration_rmse(
    strikes: Sequence[float],
    vols: Sequence[float],
    forward: float,
    tte: float,
    alpha: float,
    beta: float,
    rho: float,
    nu: float,
) -> float:
    strike_arr = np.asarray(strikes, dtype=float)
    vol_arr = np.asarray(vols, dtype=float)
    if strike_arr.ndim != 1 or vol_arr.ndim != 1 or strike_arr.size != vol_arr.size or strike_arr.size == 0:
        raise ValueError("RMSE requires non-empty 1D strike and vol arrays of equal length.")
    model = _sabr_model_vols(
        [float(alpha), float(rho), float(nu)],
        strike_arr,
        forward=float(forward),
        time_to_expiry=float(tte),
        beta=float(beta),
    )
    err = model - vol_arr
    return float(np.sqrt(np.mean(err * err)))


def calibrate_sabr_normal(
    forward: float,
    time_to_expiry: float,
    strikes_arr: Sequence[float],
    vols_arr: Sequence[float],
    beta: float = 0.5,
    method: str = "nelder-mead",
) -> Tuple[float, float, float, float]:
    strikes, vols, weights, _, alpha0 = _prepare_calibration_inputs(
        forward=float(forward),
        time_to_expiry=float(time_to_expiry),
        strikes_arr=strikes_arr,
        vols_arr=vols_arr,
        beta=float(beta),
    )

    method_key = str(method or "nelder-mead").strip().lower().replace("_", "-")
    if method_key == "nelder-mead":
        alpha, rho, nu = _calibrate_nelder_mead(
            strikes,
            vols,
            weights,
            float(forward),
            float(time_to_expiry),
            float(beta),
            alpha0,
        )
    elif method_key == "de-gn":
        alpha, rho, nu = _calibrate_de_gn(
            strikes,
            vols,
            weights,
            float(forward),
            float(time_to_expiry),
            float(beta),
            alpha0,
        )
    else:
        raise ValueError(f"Unsupported SABR calibration method: {method}")

    if alpha <= 0.0 or nu <= 0.0 or abs(rho) >= 1.0:
        raise ValueError(f"SABR calibration returned invalid params: {(alpha, rho, nu)!r}")

    rmse = calculate_calibration_rmse(
        strikes,
        vols,
        float(forward),
        float(time_to_expiry),
        alpha,
        float(beta),
        rho,
        nu,
    )
    return alpha, rho, nu, rmse

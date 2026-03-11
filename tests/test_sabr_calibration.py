import math

import pytest

from MDP.sabr_calibration import (
    _normal_delta_to_strike,
    _prepare_calibration_inputs,
    _sabr_normal_vol,
    calibrate_sabr_normal,
    calculate_calibration_rmse,
)
from MDP.STIRFutures.STIRFutureOptionMDP import _calibrate_sabr_normal_from_strike_points
from MDP.USTFutures.USTFutureOptionMDP import _calibrate_sabr_normal_from_delta_points


_CHALLENGING_FORWARD = 112.90625
_CHALLENGING_TTE = 14.0 / 365.0
_CHALLENGING_DELTA_POINTS = [
    (0.05, 0.8743551001277796, "C"),
    (0.10, 0.7947520717073492, "C"),
    (0.15, 0.744585347541816, "C"),
    (0.20, 0.7069446705623654, "C"),
    (0.25, 0.679914664934149, "C"),
    (0.35, 0.6353395012298203, "C"),
    (0.50, 0.5901896714842423, "C"),
    (0.05, 0.4490501423454532, "P"),
    (0.10, 0.47186748096972325, "P"),
    (0.15, 0.48312654517147213, "P"),
    (0.20, 0.503349308434299, "P"),
    (0.25, 0.5123877576782433, "P"),
    (0.35, 0.5435641615152281, "P"),
    (0.50, 0.5877889907980123, "P"),
]
_CHALLENGING_STRIKES = [
    113.18791487392102,
    113.10572356055175,
    113.05738792899767,
    113.02277515635585,
    112.99606468445765,
    112.95419524262077,
    112.90625,
    112.76159292450578,
    112.78781673019373,
    112.80818367929939,
    112.8232833134837,
    112.83856511666204,
    112.86523048908755,
    112.90625,
]
_CHALLENGING_VOLS = [point[1] for point in _CHALLENGING_DELTA_POINTS]


def _build_strike_smile(
    *,
    forward: float,
    time_to_expiry: float,
    alpha: float,
    rho: float,
    nu: float,
    strikes: list[float],
) -> list[float]:
    return [
        _sabr_normal_vol(
            strike=float(strike),
            forward=float(forward),
            time_to_expiry=float(time_to_expiry),
            alpha=float(alpha),
            beta=0.5,
            rho=float(rho),
            nu=float(nu),
        )
        for strike in strikes
    ]


def _build_delta_market_points(
    *,
    forward: float,
    time_to_expiry: float,
    alpha: float,
    rho: float,
    nu: float,
    deltas: tuple[float, ...],
    noise: dict[tuple[str, float], float] | None = None,
) -> list[tuple[float, float, str]]:
    market_points = []
    atm_vol = _sabr_normal_vol(
        strike=float(forward),
        forward=float(forward),
        time_to_expiry=float(time_to_expiry),
        alpha=float(alpha),
        beta=0.5,
        rho=float(rho),
        nu=float(nu),
    )
    for right in ("C", "P"):
        for delta_abs in deltas:
            vol = atm_vol
            for _ in range(32):
                strike = _normal_delta_to_strike(
                    delta_abs=float(delta_abs),
                    vol_normal=float(vol),
                    forward=float(forward),
                    time_to_expiry=float(time_to_expiry),
                    right=right,
                )
                next_vol = _sabr_normal_vol(
                    strike=float(strike),
                    forward=float(forward),
                    time_to_expiry=float(time_to_expiry),
                    alpha=float(alpha),
                    beta=0.5,
                    rho=float(rho),
                    nu=float(nu),
                )
                if abs(next_vol - vol) < 1e-12:
                    break
                vol = next_vol
            vol += float((noise or {}).get((right, float(delta_abs)), 0.0))
            market_points.append((float(delta_abs), max(vol, 1e-4), right))
    return market_points


def test_sabr_normal_vol_shared_matches_known_values():
    stir_atm = _sabr_normal_vol(
        strike=96.25,
        forward=96.25,
        time_to_expiry=90.0 / 365.0,
        alpha=0.06,
        beta=0.5,
        rho=-0.15,
        nu=1.8,
    )
    stir_otm = _sabr_normal_vol(
        strike=96.75,
        forward=96.25,
        time_to_expiry=90.0 / 365.0,
        alpha=0.06,
        beta=0.5,
        rho=-0.15,
        nu=1.8,
    )

    assert stir_atm == pytest.approx(0.6264791619605781)
    assert stir_otm == pytest.approx(0.7454766394883441)
    assert stir_atm > 0.0
    assert stir_otm > 0.0


def test_calibrate_nelder_mead_recovers_known_params():
    forward = 96.25
    time_to_expiry = 90.0 / 365.0
    true_alpha = 0.06
    true_rho = -0.20
    true_nu = 1.90
    strikes = [95.0, 95.4, 95.8, 96.0, 96.25, 96.5, 96.7, 97.0, 97.4]
    vols = _build_strike_smile(
        forward=forward,
        time_to_expiry=time_to_expiry,
        alpha=true_alpha,
        rho=true_rho,
        nu=true_nu,
        strikes=strikes,
    )

    alpha, rho, nu, rmse = calibrate_sabr_normal(
        forward=forward,
        time_to_expiry=time_to_expiry,
        strikes_arr=strikes,
        vols_arr=vols,
        beta=0.5,
        method="nelder-mead",
    )

    assert alpha == pytest.approx(true_alpha, rel=2e-1)
    assert rho == pytest.approx(true_rho, rel=2e-1)
    assert nu == pytest.approx(true_nu, rel=2e-1)
    assert rmse == pytest.approx(
        calculate_calibration_rmse(
            strikes,
            vols,
            forward,
            time_to_expiry,
            alpha,
            0.5,
            rho,
            nu,
        )
    )
    assert rmse < 1e-8


def test_calibrate_de_gn_recovers_known_params():
    forward = 112.90625
    time_to_expiry = 30.0 / 365.0
    true_alpha = 0.069
    true_rho = 0.34
    true_nu = 2.45
    strikes = [111.8, 112.1, 112.4, 112.7, 112.90625, 113.1, 113.4, 113.7, 114.0]
    vols = _build_strike_smile(
        forward=forward,
        time_to_expiry=time_to_expiry,
        alpha=true_alpha,
        rho=true_rho,
        nu=true_nu,
        strikes=strikes,
    )

    alpha, rho, nu, rmse = calibrate_sabr_normal(
        forward=forward,
        time_to_expiry=time_to_expiry,
        strikes_arr=strikes,
        vols_arr=vols,
        beta=0.5,
        method="de-gn",
    )

    assert alpha == pytest.approx(true_alpha, rel=1e-1)
    assert rho == pytest.approx(true_rho, rel=1e-1)
    assert nu == pytest.approx(true_nu, rel=1e-1)
    assert rmse < 1e-10


def test_de_gn_rmse_leq_nelder_mead():
    nm = calibrate_sabr_normal(
        forward=_CHALLENGING_FORWARD,
        time_to_expiry=_CHALLENGING_TTE,
        strikes_arr=_CHALLENGING_STRIKES,
        vols_arr=_CHALLENGING_VOLS,
        beta=0.5,
        method="nelder-mead",
    )
    de = calibrate_sabr_normal(
        forward=_CHALLENGING_FORWARD,
        time_to_expiry=_CHALLENGING_TTE,
        strikes_arr=_CHALLENGING_STRIKES,
        vols_arr=_CHALLENGING_VOLS,
        beta=0.5,
        method="de-gn",
    )

    assert de[3] <= nm[3] + 1e-12


def test_calibrate_de_gn_with_noisy_data():
    forward = 96.25
    time_to_expiry = 90.0 / 365.0
    strikes = [95.0, 95.4, 95.8, 96.0, 96.25, 96.5, 96.7, 97.0, 97.4]
    vols = _build_strike_smile(
        forward=forward,
        time_to_expiry=time_to_expiry,
        alpha=0.06,
        rho=-0.2,
        nu=1.9,
        strikes=strikes,
    )
    noisy_vols = [
        max(vol + bump, 1e-4)
        for vol, bump in zip(vols, [0.0015, -0.0010, 0.0005, -0.0008, 0.0, 0.0009, -0.0012, 0.0011, -0.0007])
    ]

    alpha, rho, nu, rmse = calibrate_sabr_normal(
        forward=forward,
        time_to_expiry=time_to_expiry,
        strikes_arr=strikes,
        vols_arr=noisy_vols,
        beta=0.5,
        method="de-gn",
    )

    assert math.isfinite(alpha)
    assert math.isfinite(rho)
    assert math.isfinite(nu)
    assert rmse < 0.005


def test_calibration_rmse_populated():
    stir_params = _calibrate_sabr_normal_from_strike_points(
        forward=96.25,
        time_to_expiry=90.0 / 365.0,
        market_points=list(
            zip(
                [95.0, 95.4, 95.8, 96.0, 96.25, 96.5, 96.7, 97.0, 97.4],
                [0.775595, 0.699890, 0.651858, 0.634692, 0.626479, 0.649421, 0.675713, 0.745477, 0.900521],
            )
        ),
        beta=0.5,
        calibration_method="de-gn",
    )
    ust_params = _calibrate_sabr_normal_from_delta_points(
        forward=_CHALLENGING_FORWARD,
        time_to_expiry=_CHALLENGING_TTE,
        market_points=_CHALLENGING_DELTA_POINTS,
        beta=0.5,
        calibration_method="de-gn",
    )

    assert stir_params.calibration_rmse is not None
    assert stir_params.calibration_rmse > 0.0
    assert ust_params.calibration_rmse is not None
    assert ust_params.calibration_rmse > 0.0


def test_invalid_method_raises():
    strikes = [95.0, 95.4, 95.8, 96.0, 96.25, 96.5]
    vols = [0.80, 0.72, 0.66, 0.63, 0.62, 0.65]

    with pytest.raises(ValueError, match="Unsupported SABR calibration method"):
        calibrate_sabr_normal(
            forward=96.25,
            time_to_expiry=90.0 / 365.0,
            strikes_arr=strikes,
            vols_arr=vols,
            beta=0.5,
            method="bogus",
        )


def test_prepare_calibration_inputs_atm_weighting():
    strikes, vols, weights, atm_vol, alpha0 = _prepare_calibration_inputs(
        forward=100.0,
        time_to_expiry=0.25,
        strikes_arr=[100.0, 99.8, 100.0, 100.2, 102.0],
        vols_arr=[0.42, 0.50, 0.38, 0.50, 0.60],
        beta=0.5,
    )

    assert list(strikes) == pytest.approx([99.8, 100.0, 100.2, 102.0])
    assert list(vols) == pytest.approx([0.50, 0.40, 0.50, 0.60])
    assert list(weights) == pytest.approx([2.0, 2.0, 2.0, 1.0])
    assert atm_vol == pytest.approx(0.40)
    assert alpha0 == pytest.approx(0.04)

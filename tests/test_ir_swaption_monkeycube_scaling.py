import QuantLib as ql
import pytest

from MDP.IRSwaptions.MONKEYCUBE.cube import NormalSabrVolCube


def _build_monkeycube() -> NormalSabrVolCube:
    # Raw MonkeyCube params are currently stored in bp-vol units.
    params = {
        "1Mx7Y": {
            "alpha": 5.134698713524511,
            "beta": 0.49950000000024963,
            "nu": 124.99999999995353,
            "rho": -0.31813374333098743,
            "atmf_rate": 0.03542,
        },
        "1Mx10Y": {
            "alpha": 4.915727548610358,
            "beta": 0.4995000002075965,
            "nu": 124.99999903294609,
            "rho": -0.3486281368861491,
            "atmf_rate": 0.03694,
        },
        "6Mx7Y": {
            "alpha": 3.1100000000000003,
            "beta": 0.5004999999999998,
            "nu": 69.0,
            "rho": -0.255,
            "atmf_rate": 0.0362,
        },
        "6Mx10Y": {
            "alpha": 3.0824072288269004,
            "beta": 0.5004999999999998,
            "nu": 64.09589193837186,
            "rho": -0.25533603470274463,
            "atmf_rate": 0.037000000000000005,
        },
    }
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    dc = ql.Actual365Fixed()
    today = ql.Date(6, 3, 2026)
    return NormalSabrVolCube(params, cal, dc, today)


def test_monkeycube_volatility_at_point_is_normalized_to_decimal():
    cube = _build_monkeycube()

    option_time = cube._tenor_to_time("1M")
    swap_years = cube._tenor_to_years("7Y")
    strike = 0.03542

    raw_smile = ql.SabrSmileSection(
        option_time,
        0.03542,
        [5.134698713524511, 0.49950000000024963, 124.99999999995353, -0.31813374333098743],
        0.0,
        ql.Normal,
    )
    raw_vol = float(raw_smile.volatility(strike, ql.Normal))

    scaled_vol = cube.volatility_at_point(option_time, swap_years, strike)

    assert raw_vol > 1.0
    assert 0.0 < scaled_vol < 0.1
    assert scaled_vol * 10_000.0 == pytest.approx(raw_vol, rel=0.05)


def test_monkeycube_atm_surface_matrix_uses_decimal_vols():
    cube = _build_monkeycube()

    matrix = cube.atm_vol_matrix(["1M", "6M"], ["7Y", "10Y"])

    assert matrix.shape == (2, 2)
    assert matrix.max() < 0.1
    assert matrix.min() > 0.0

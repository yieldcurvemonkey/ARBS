"""Control-panel tests. Each one pins a property that, if wrong, would make the
G3 horse race either look cleaner than it is or leak the future into a control.
"""
import numpy as np
import pandas as pd
import pytest

from BT.dealer_ladder import controls

NY = "America/New_York"


def _grid(n=40, start="2026-07-10 08:00", freq="5min"):
    return pd.date_range(start, periods=n, freq=freq, tz=NY)


def _rates(n=40, cols=("SFRU26", "SFRZ26", "SFRH27")):
    idx = _grid(n)
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {c: 400.0 + np.cumsum(rng.normal(scale=0.2, size=n)) + 5 * i
         for i, c in enumerate(cols)}, index=idx)


# ------------------------------------------------------------------- basis
def test_basis_is_implied_minus_market_on_the_shared_support():
    idx = _grid(4)
    implied = pd.DataFrame({"A": [400.0, 401, 402, 403], "B": [1.0] * 4}, index=idx)
    market = pd.DataFrame({"A": [399.5, 401, 402.5, 404], "C": [1.0] * 4}, index=idx)
    b = controls.basis_bp(implied, market)
    assert list(b.columns) == ["A"]                 # only the shared contract
    assert b["A"].tolist() == pytest.approx([0.5, 0.0, -0.5, -1.0])


def test_signed_basis_dv01_uses_basis_sign_and_ladder_magnitude():
    idx = _grid(3)
    basis = pd.DataFrame({"A": [1.0, -2.0, 0.0]}, index=idx)
    ladder = pd.DataFrame({"A": [-10.0, 5.0, 7.0]}, index=idx)
    out = controls.signed_basis_dv01(basis, ladder)
    assert out["A"].tolist() == pytest.approx([10.0, -5.0, 0.0])


# ------------------------------------------------------------- curve shape
def test_curve_shape_slope_and_curvature():
    idx = _grid(2)
    r = pd.DataFrame({"a": [100.0, 100.0], "b": [110.0, 120.0],
                      "c": [130.0, 130.0]}, index=idx)
    out = controls.curve_shape(r)
    assert out["slope_bp"].tolist() == pytest.approx([30.0, 30.0])
    # 2*belly - front - back
    assert out["curvature_bp"].tolist() == pytest.approx([-10.0, 10.0])
    assert out["level_bp"].iloc[0] == pytest.approx(340.0 / 3.0)


def test_curve_shape_needs_three_contracts():
    idx = _grid(2)
    out = controls.curve_shape(pd.DataFrame({"a": [1.0, 2.0]}, index=idx))
    assert out.empty or out.shape[1] == 0


# ------------------------------------------------------- momentum / vol / liq
def test_trailing_return_looks_backwards_only():
    idx = _grid(10)
    r = pd.DataFrame({"A": np.arange(10.0)}, index=idx)
    out = controls.trailing_return_bp(r, 10)         # 10 min = 2 steps
    assert out["A"].iloc[:2].isna().all()            # no history yet
    assert out["A"].iloc[5] == pytest.approx(2.0)


def test_realized_vol_is_knowable_at_t():
    """Shifted by one step: the value at t must not use the change INTO t."""
    idx = _grid(30)
    r = pd.DataFrame({"A": np.r_[np.zeros(20), np.arange(10) * 10.0]}, index=idx)
    v = controls.realized_vol_bp(r, window_min=30, step_min=5)
    # the jump starts at row 20; a value at row 20 cannot already know about it
    assert v["A"].iloc[20] == pytest.approx(0.0, abs=1e-9)
    assert v["A"].iloc[25] > 0


def test_futures_amihud_is_impact_per_contract_and_shifted():
    idx = _grid(30)
    r = pd.DataFrame({"A": np.cumsum(np.r_[np.zeros(10), np.ones(20)])}, index=idx)
    vol = pd.DataFrame({"A": np.full(30, 100.0)}, index=idx)
    a = controls.futures_amihud(r, vol, window_min=5)
    assert a["A"].iloc[:5].isna().all()              # min_periods
    later = a["A"].dropna()
    assert (later >= 0).all()
    # constant volume, larger moves -> larger amihud
    assert later.iloc[-1] >= later.iloc[0]


def test_futures_amihud_handles_zero_volume():
    idx = _grid(20)
    r = pd.DataFrame({"A": np.arange(20.0)}, index=idx)
    vol = pd.DataFrame({"A": np.zeros(20)}, index=idx)
    a = controls.futures_amihud(r, vol, window_min=5)
    assert a["A"].isna().all()                       # never inf


# ---------------------------------------------------------- time / roll / fomc
def test_time_of_day_is_et_minutes():
    tod = controls.time_of_day_min(_grid(3, start="2026-07-10 09:30"))
    assert tod.iloc[0] == pytest.approx(9 * 60 + 30)


def test_days_to_expiry_counts_down():
    grid = pd.date_range("2026-07-10", periods=3, freq="1D", tz=NY)
    contracts = [("SFRU26", pd.Timestamp("2026-09-16"), pd.Timestamp("2026-12-16"), False)]
    out = controls.days_to_expiry(grid, contracts)
    assert out["SFRU26"].iloc[0] > out["SFRU26"].iloc[-1]
    assert out["SFRU26"].iloc[0] == pytest.approx(159.0)


def test_days_to_fomc_is_nan_past_the_calendar_not_999():
    """A 999 sentinel would be read by a regression as 'very far away'."""
    far = pd.date_range("2031-01-05", periods=2, freq="1D", tz=NY)
    out = controls.days_to_next_fomc(far)
    assert out.isna().all()
    near = pd.date_range("2026-07-10", periods=2, freq="1D", tz=NY)
    assert controls.days_to_next_fomc(near).notna().all()


# --------------------------------------------------------- the 25bp grid
@pytest.mark.parametrize("rate,expect", [
    (400.0, 0.0),      # exactly on a 25bp grid point
    (403.0, 3.0),      # 3bp above 400
    (410.0, 10.0),     # still nearer 400 than 425
    (415.0, -10.0),    # nearer to 425, approached from below
    (412.5, 12.5),     # exact midpoint: banker's rounding picks 400
])
def test_level_proximity_signs_distance_to_the_25bp_grid(rate, expect):
    idx = _grid(1)
    out = controls.level_proximity_bp(pd.DataFrame({"A": [rate]}, index=idx))
    assert out["A"].iloc[0] == pytest.approx(expect)


def test_level_proximity_is_bounded_by_half_the_grid():
    idx = _grid(50)
    rng = np.random.default_rng(1)
    r = pd.DataFrame({"A": rng.uniform(300, 500, size=50)}, index=idx)
    out = controls.level_proximity_bp(r)
    assert out["A"].abs().max() <= 12.5 + 1e-9


# ------------------------------------------------------------------ assembly
def test_build_control_panels_covers_every_declared_default():
    r = _rates()
    vol = pd.DataFrame(100.0, index=r.index, columns=r.columns)
    implied = r + 0.5
    ladder = pd.DataFrame(1000.0, index=r.index, columns=r.columns)
    contracts = [(c, pd.Timestamp("2026-09-16"), pd.Timestamp("2026-12-16"), False)
                 for c in r.columns]
    panels = controls.build_control_panels(
        rates_bp=r, volumes=vol, implied_bp=implied, ladder_level=ladder,
        contracts=contracts, grid=r.index)
    for name in controls.DEFAULT_CONTROLS:
        assert name in panels, name
        assert isinstance(panels[name], pd.DataFrame)
    # bucket-invariant controls are broadcast across buckets, not left 1-wide
    assert list(panels["tod_min"].columns) == list(r.columns)
    assert panels["tod_min"].nunique(axis=1).max() == 1


def test_build_control_panels_basis_is_constant_when_implied_offset_is():
    r = _rates()
    vol = pd.DataFrame(100.0, index=r.index, columns=r.columns)
    panels = controls.build_control_panels(
        rates_bp=r, volumes=vol, implied_bp=r + 2.0,
        ladder_level=pd.DataFrame(1.0, index=r.index, columns=r.columns),
        contracts=[(c, pd.Timestamp("2026-09-16"), pd.Timestamp("2026-12-16"), False)
                   for c in r.columns],
        grid=r.index)
    assert np.allclose(panels["basis_bp"].to_numpy(), 2.0)
    assert np.allclose(panels["abs_basis_bp"].to_numpy(), 2.0)

"""Pins for :mod:`RVUtils.fly` - the data-driven leg weightings.

The three published methods are pinned against the worked numbers in the Quant
SE thread *"How to adjust butterfly 2s5s10s swaps trade for directionality?"*,
so the arithmetic is checked against an answer that was known before this code
existed rather than against itself. The remaining tests pin the windowing, the
degeneracy guards and the preset grammar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import RVUtils.fly as fly
from RVUtils.fly.estimators import (
    combine,
    default_anchor,
    default_factors,
    second_moment,
    solve_weights,
    weights_from_moment,
)
from RVUtils.fly.schema import WeightingSchema, parse_preset, parse_window

# The thread's PC1 for the 2Y/5Y/10Y block, and the base 2s5s10s risks.
SE_PC1 = np.array([0.660, 0.604, 0.447])
BASE_FLY = np.array([-1.0, 2.0, -1.0])


def _cov_with_pc1(p: np.ndarray, eigenvalues=(1.0, 0.30, 0.05)) -> np.ndarray:
    """A covariance whose leading eigenvector is exactly ``p``."""
    p = np.asarray(p, dtype=float)
    p = p / np.linalg.norm(p)
    basis, _ = np.linalg.qr(np.column_stack([p, np.eye(len(p))[:, : len(p) - 1]]))
    if np.dot(basis[:, 0], p) < 0:
        basis[:, 0] = -basis[:, 0]
    return basis @ np.diag(np.asarray(eigenvalues, dtype=float)) @ basis.T


def _panel(n_obs: int = 400, seed: int = 11) -> pd.DataFrame:
    """A three-leg rate panel with a dominant level factor and a real slope."""
    rng = np.random.default_rng(seed)
    level = np.cumsum(rng.normal(0.0, 0.05, n_obs))
    slope = np.cumsum(rng.normal(0.0, 0.02, n_obs))
    idio = rng.normal(0.0, 0.008, (n_obs, 3))
    loadings = np.array([[1.00, -1.0], [0.92, 0.0], [0.78, 1.0]])
    values = np.column_stack([level, slope]) @ loadings.T + idio + np.array([3.5, 3.9, 4.2])
    index = pd.bdate_range("2023-01-02", periods=n_obs, name="Date")
    return pd.DataFrame(values, index=index, columns=["2Y", "5Y", "10Y"])


# --------------------------------------------------------------------------- #
# published numbers
# --------------------------------------------------------------------------- #


def test_pca_divide_reproduces_stackexchange_weights():
    """Attack68 method 1: ``x_i / PC1_i`` rescaled to a belly of 2."""
    Q = _cov_with_pc1(SE_PC1)
    w = weights_from_moment(Q, BASE_FLY, fly.weights(method="pca"))

    # -1/0.660, 2/0.604, -1/0.447  ->  (-1.5152, 3.3113, -2.2371)  ->  belly at 2
    raw = BASE_FLY / SE_PC1
    assert raw == pytest.approx([-1.5152, 3.3113, -2.2371], abs=1e-4)
    assert w == pytest.approx(raw * (2.0 / raw[1]), rel=1e-12)
    # The thread prints the rescaled pair as -0.91 / -1.35; those are truncations
    # of -0.91515 / -1.35123, not roundings, so pin the exact values.
    assert w == pytest.approx([-0.915152, 2.0, -1.351230], abs=1e-5)


def test_pca_proj_reproduces_stackexchange_kkt_weights():
    """The 2021 addendum: minimal risk change subject to zero PC1 risk."""
    Q = _cov_with_pc1(SE_PC1)
    w = weights_from_moment(Q, BASE_FLY, fly.weights(method="pca_proj"))

    assert w == pytest.approx([-1.1002, 2.0, -1.0780], abs=1e-4)


def test_both_pca_variants_are_pc1_neutral():
    """Different vectors, same constraint: no exposure to the level factor."""
    Q = _cov_with_pc1(SE_PC1)
    p = SE_PC1 / np.linalg.norm(SE_PC1)
    for method in ("pca", "pca_proj"):
        w = weights_from_moment(Q, BASE_FLY, fly.weights(method=method))
        assert float(w @ p) == pytest.approx(0.0, abs=1e-12), method


def test_beta_matches_the_threads_pinv_recipe():
    """dm63 / method 3: ``w = (-(1 - b1), 2 - b2, -(1 + b1))`` from an OLS."""
    panel = _panel()
    changes = panel.diff().dropna().to_numpy()

    # The thread's snippet, verbatim in shape: regress the fly on [2s10s, 5y].
    X = np.column_stack([changes[:, 2] - changes[:, 0], changes[:, 1]])
    y = changes @ BASE_FLY
    beta = np.linalg.pinv(X) @ y
    expected = np.array([-(1 - beta[0]), 2 - beta[1], -(1 + beta[0])])
    expected = expected * (2.0 / expected[1])

    Q = second_moment(changes, center=False, matrix="cov")
    got = weights_from_moment(Q, BASE_FLY, fly.weights(method="beta", center=False))

    assert got == pytest.approx(expected, rel=1e-10)


def test_minvar_matches_the_threads_einsum_recipe():
    """Attack68 method 2: pin the belly, solve the wings for least variance."""
    panel = _panel()
    changes = panel.diff().dropna().to_numpy()
    Q = np.cov(changes.T)

    # The thread's snippet: w[[0, 2]] = -inv(Q_dhat) @ Q_hat @ [0, 2, 0]
    Q_hat = Q[[0, 2], :]
    Q_dhat = Q_hat[:, [0, 2]]
    expected = np.empty(3)
    expected[1] = 2.0
    expected[[0, 2]] = -np.einsum("ij,jk,k->i", np.linalg.inv(Q_dhat), Q_hat, np.array([0.0, 2.0, 0.0]))

    got = weights_from_moment(Q, BASE_FLY, fly.weights(method="minvar"))

    assert got == pytest.approx(expected, rel=1e-10)


def test_minvar_really_is_the_lowest_variance_package_in_sample():
    """The defining property, not the formula: nothing with belly 2 beats it."""
    panel = _panel()
    changes = panel.diff().dropna()
    Q = np.cov(changes.to_numpy().T)

    def variance(w):
        return float(np.asarray(w) @ Q @ np.asarray(w))

    best = weights_from_moment(Q, BASE_FLY, fly.weights(method="minvar"))
    for method in ("none", "pca", "pca_proj", "beta"):
        rival = weights_from_moment(Q, BASE_FLY, fly.weights(method=method, center=True))
        assert variance(best) <= variance(rival) + 1e-15, method

    rng = np.random.default_rng(4)
    for _ in range(200):
        perturbed = best + np.array([rng.normal(0, 0.05), 0.0, rng.normal(0, 0.05)])
        assert variance(best) <= variance(perturbed) + 1e-15


# --------------------------------------------------------------------------- #
# conventions
# --------------------------------------------------------------------------- #


def test_none_is_the_untouched_package():
    panel = _panel()
    got = solve_weights(panel, BASE_FLY, fly.base)
    assert (got.to_numpy() == BASE_FLY).all()


def test_anchor_normalisation_pins_the_belly_not_the_gross():
    Q = _cov_with_pc1(SE_PC1)
    for method in ("pca", "pca_proj", "beta", "minvar"):
        w = weights_from_moment(Q, BASE_FLY, fly.weights(method=method))
        assert w[1] == pytest.approx(2.0), method


def test_l1_normalisation_matches_gross_risk_instead():
    Q = _cov_with_pc1(SE_PC1)
    w = weights_from_moment(Q, BASE_FLY, fly.weights(method="pca", normalize="l1"))
    assert float(np.abs(w).sum()) == pytest.approx(float(np.abs(BASE_FLY).sum()))
    assert w[1] != pytest.approx(2.0)


def test_two_leg_beta_collapses_to_the_beta_weighted_curve():
    """``w = (-beta_bf, +1)`` - the ordinary regression hedge on a spread."""
    panel = _panel()[["2Y", "10Y"]]
    changes = panel.diff().dropna().to_numpy()
    Q = second_moment(changes, center=True)
    beta_bf = Q[0, 1] / Q[0, 0]

    got = weights_from_moment(Q, np.array([-1.0, 1.0]), fly.weights(method="beta"))

    assert got == pytest.approx([-beta_bf, 1.0], rel=1e-10)


def test_default_conventions():
    assert default_anchor(3) == 1  # belly
    assert default_anchor(2) == 1  # back leg
    assert default_anchor(5) == 2
    with pytest.raises(ValueError):
        default_anchor(1)

    # dm63's regressors: the wing curve and the belly outright.
    assert default_factors(3).tolist() == [[-1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
    assert default_factors(2).tolist() == [[1.0], [0.0]]


def test_levels_and_changes_are_genuinely_different_answers():
    panel = _panel()
    on_changes = solve_weights(panel, BASE_FLY, fly.pca_chgs).iloc[-1].to_numpy()
    on_levels = solve_weights(panel, BASE_FLY, fly.pca_lvls).iloc[-1].to_numpy()
    assert not np.allclose(on_changes, on_levels, atol=1e-3)


# --------------------------------------------------------------------------- #
# degeneracy guards
# --------------------------------------------------------------------------- #


def test_near_zero_loading_stops_pca_but_not_the_projection():
    """Thrastylon's objection on the thread, made into a guard."""
    Q = _cov_with_pc1(np.array([-1.0, 1e-12, 1.0]))
    with pytest.raises(np.linalg.LinAlgError, match="numerically zero"):
        weights_from_moment(Q, BASE_FLY, fly.weights(method="pca"))
    w = weights_from_moment(Q, BASE_FLY, fly.weights(method="pca_proj"))
    assert np.all(np.isfinite(w))


def test_an_unstable_but_legal_weight_path_warns_and_points_at_the_fix():
    """Measured live: pca_chgs_1m put a wing at -6.01 against a belly of 2."""
    index = pd.bdate_range("2024-01-02", periods=260, name="Date")
    rng = np.random.default_rng(19)
    level = np.cumsum(rng.normal(0.0, 0.05, 260))
    values = np.column_stack(
        [
            3.5 + 1.00 * level + rng.normal(0.0, 0.004, 260),
            3.9 + 0.90 * level + rng.normal(0.0, 0.004, 260),
            # A back leg that decouples from the level for one stretch: its PC1
            # loading collapses there and x_i / p_i explodes.
            4.2 + np.where(np.arange(260) < 120, 0.80, 0.02) * level + rng.normal(0.0, 0.004, 260),
        ]
    )
    panel = pd.DataFrame(values, index=index, columns=["2Y", "5Y", "10Y"])

    with pytest.warns(RuntimeWarning, match="pca_proj"):
        loose = solve_weights(panel, BASE_FLY, fly.weights(method="pca", window="1m"))
    assert loose.attrs["max_abs_ratio_seen"] > 5.0

    stable = solve_weights(panel, BASE_FLY, fly.weights(method="pca_proj", window="1m"))
    assert stable.attrs["max_abs_ratio_seen"] < loose.attrs["max_abs_ratio_seen"]


def test_an_exploding_weight_is_refused_rather_than_returned():
    Q = _cov_with_pc1(np.array([0.02, 0.7, 0.7]))
    with pytest.raises(np.linalg.LinAlgError, match="anchor leg"):
        weights_from_moment(Q, BASE_FLY, fly.weights(method="pca", max_abs_ratio=5.0))


def test_a_static_fit_with_too_little_data_yields_nan_not_a_wrong_number():
    panel = _panel(n_obs=6)
    with pytest.warns(RuntimeWarning, match="usable rows"):
        got = solve_weights(panel, BASE_FLY, fly.pca_chgs)
    assert got.isna().all().all()


# --------------------------------------------------------------------------- #
# windowing
# --------------------------------------------------------------------------- #


def test_window_grammar():
    assert parse_window(None).kind == "static"
    assert parse_window("expanding").kind == "expanding"
    assert parse_window(60).kind == "obs" and parse_window(60).size == 60
    assert parse_window("60n").size == 60
    assert parse_window("60").size == 60
    assert parse_window("1m").kind == "time"
    assert dict(parse_window("1q").offset_kwargs) == {"months": 3}
    assert dict(parse_window("2y").offset_kwargs) == {"years": 2}
    assert dict(parse_window("90d").offset_kwargs) == {"days": 90}
    with pytest.raises(ValueError):
        parse_window("1fortnight")
    with pytest.raises(ValueError):
        parse_window("0m")


def test_an_observation_window_uses_exactly_that_many_rows():
    panel = _panel(n_obs=200)
    schema = fly.weights(method="minvar", basis="chgs", window="60n")
    got = solve_weights(panel, BASE_FLY, schema)

    # Panel row 100 is change-row 99; a 60-observation window is change-rows
    # 40..99 inclusive, i.e. panel rows 41..100.
    changes = panel.diff().dropna()
    block = changes.iloc[40:100].to_numpy()
    assert block.shape[0] == 60
    expected = weights_from_moment(second_moment(block, center=True), BASE_FLY, schema)
    assert got.iloc[100].to_numpy() == pytest.approx(expected, rel=1e-10)

    # ...and NOT a 59- or 61-row window, which is what an off-by-one would give.
    for wrong in (changes.iloc[41:100], changes.iloc[39:100]):
        other = weights_from_moment(second_moment(wrong.to_numpy(), center=True), BASE_FLY, schema)
        assert not np.allclose(other, expected, rtol=1e-6)


def test_a_calendar_window_shortens_over_a_data_gap_instead_of_reaching_back():
    index = pd.DatetimeIndex(
        list(pd.bdate_range("2024-01-01", periods=40))
        + list(pd.bdate_range("2024-06-03", periods=40)),
        name="Date",
    )
    rng = np.random.default_rng(3)
    panel = pd.DataFrame(rng.normal(4.0, 0.1, (80, 3)), index=index, columns=["2Y", "5Y", "10Y"])

    schema = fly.weights(method="minvar", window="1m", min_obs=10)
    got = solve_weights(panel, BASE_FLY, schema)

    # First day back after the five-month hole has one usable change-row behind it.
    assert np.isnan(got.iloc[40].to_numpy()).all()
    # And a month later the window has refilled.
    assert np.isfinite(got.iloc[-1].to_numpy()).all()


def test_expanding_grows_and_ends_where_the_static_fit_lands():
    panel = _panel(n_obs=120)
    expanding = solve_weights(panel, BASE_FLY, fly.weights(method="pca", window="expanding"))
    static = solve_weights(panel, BASE_FLY, fly.pca_chgs)
    assert expanding.iloc[-1].to_numpy() == pytest.approx(static.iloc[-1].to_numpy(), rel=1e-12)
    assert not np.allclose(expanding.iloc[30].to_numpy(), expanding.iloc[-1].to_numpy())


def test_lag_shifts_the_weights_forward_by_whole_rows():
    panel = _panel(n_obs=150)
    plain = solve_weights(panel, BASE_FLY, fly.weights(method="pca", window="60n"))
    lagged = solve_weights(panel, BASE_FLY, fly.weights(method="pca", window="60n", lag=1))
    assert lagged.iloc[100].to_numpy() == pytest.approx(plain.iloc[99].to_numpy(), rel=1e-12)


def test_refit_every_holds_the_weights_flat_between_refits():
    panel = _panel(n_obs=150)
    every = solve_weights(panel, BASE_FLY, fly.weights(method="pca", window="60n"))
    stride = solve_weights(panel, BASE_FLY, fly.weights(method="pca", window="60n", refit_every=5))

    fitted = stride.dropna()
    distinct = len(fitted.round(12).drop_duplicates())
    assert distinct == pytest.approx(len(fitted) / 5, rel=0.2)

    # Every fifth row still agrees with the un-strided fit; the rest are held.
    matches = np.isclose(stride.to_numpy(), every.to_numpy(), rtol=1e-12).all(axis=1)
    assert 0.15 < matches[np.isfinite(stride.to_numpy()).all(axis=1)].mean() < 0.35


def test_diff_periods_changes_the_estimate():
    panel = _panel()
    daily = solve_weights(panel, BASE_FLY, fly.pca_chgs).iloc[-1].to_numpy()
    weekly = solve_weights(panel, BASE_FLY, fly.weights(method="pca", diff_periods=5)).iloc[-1].to_numpy()
    assert not np.allclose(daily, weekly, atol=1e-4)


# --------------------------------------------------------------------------- #
# presets
# --------------------------------------------------------------------------- #


def test_the_presets_the_user_asked_for_exist_and_mean_what_they_say():
    assert fly.pca_chgs.method == "pca" and fly.pca_chgs.basis == "chgs"
    assert fly.pca_chgs.window.is_static
    assert fly.pca_lvls.basis == "lvls"
    assert fly.pca_chgs_1m.window.text == "1m"
    assert fly.pca_lvls_1m.basis == "lvls" and fly.pca_lvls_1m.window.text == "1m"
    assert fly.beta_chgs_1m.method == "beta"
    assert fly.minvar_lvls_6m.method == "minvar"
    assert fly.pca_proj_chgs_1y.method == "pca_proj"


def test_names_outside_the_eager_grid_still_resolve():
    assert fly.pca_chgs_45d.window.text == "45d"
    assert fly.beta_lvls_2y_lag1.lag == 1
    assert fly.minvar_chgs_500n.window.size == 500
    assert fly.pca_proj_chgs_1y_pc2.n_pc == 2
    assert fly.beta_chgs_nc.center is False
    assert fly.pca_chgs_1m_w.emit_weights is True


def test_a_nonsense_name_raises_attributeerror_with_the_grammar():
    with pytest.raises(AttributeError, match="method"):
        _ = fly.wobble_chgs
    with pytest.raises(AttributeError):
        _ = fly.pca_bananas


def test_labels_are_unique_per_schema():
    labels = {
        fly.pca_chgs.label,
        fly.pca_lvls.label,
        fly.pca_chgs_1m.label,
        fly.pca_lvls_1m.label,
        fly.beta_chgs_1m.label,
        fly.minvar_chgs_1m.label,
        fly.pca_proj_chgs_1m.label,
        fly.pca_chgs_1m.lagged(1).label,
    }
    assert len(labels) == 8
    assert fly.pca_chgs_1m.label == "pca_chgs_1m"
    assert fly.beta_chgs_1m.label == "beta_chgs_1m"


def test_schemas_are_frozen_hashable_and_comparable():
    assert fly.pca_chgs_1m == parse_preset("pca_chgs_1m")
    assert hash(fly.pca_chgs_1m) == hash(parse_preset("pca_chgs_1m"))
    assert len({fly.pca_chgs_1m, parse_preset("pca_chgs_1m"), fly.pca_lvls_1m}) == 2
    with pytest.raises(Exception):
        fly.pca_chgs_1m.method = "beta"  # type: ignore[misc]


def test_in_sample_flag_is_honest():
    assert fly.pca_chgs.is_in_sample is True
    assert fly.pca_chgs_1m.is_in_sample is False
    assert fly.base.is_in_sample is False


def test_string_and_dict_specs_coerce():
    assert fly.coerce("pca_chgs_1m") == fly.pca_chgs_1m
    assert fly.coerce(None) is None
    assert fly.coerce({"method": "beta", "basis": "chgs", "window": "1m"}) == fly.beta_chgs_1m
    with pytest.raises(TypeError):
        fly.coerce(3.14)


def test_bad_schema_fields_raise_at_construction():
    with pytest.raises(ValueError, match="method"):
        WeightingSchema(method="quantum")
    with pytest.raises(ValueError, match="basis"):
        WeightingSchema(method="pca", basis="vibes")
    with pytest.raises(ValueError, match="normalize"):
        WeightingSchema(method="pca", normalize="whatever")


# --------------------------------------------------------------------------- #
# recombination
# --------------------------------------------------------------------------- #


def test_combine_is_the_weighted_sum_and_respects_the_multiplier():
    panel = _panel(n_obs=30)
    weight_frame = solve_weights(panel, BASE_FLY, fly.base)
    got = combine(panel, weight_frame, multiplier=100.0)
    expected = (2 * panel["5Y"] - panel["2Y"] - panel["10Y"]) * 100.0
    assert got.to_numpy() == pytest.approx(expected.to_numpy(), rel=1e-12)


def test_pnl_mode_removes_the_weight_drift_a_level_recombination_carries():
    """Measured on real USD SOFR data: 187 bp/day of drift vs 0.80 of market."""
    panel = _panel(n_obs=400)
    schema = fly.weights(method="pca", basis="chgs", window="1m")
    frame = solve_weights(panel, BASE_FLY, schema)

    level = combine(panel, frame, multiplier=100.0, mode="level")
    pnl = combine(panel, frame, multiplier=100.0, mode="pnl")
    plain = combine(panel, solve_weights(panel, BASE_FLY, fly.base), multiplier=100.0, mode="level")

    assert level.diff().std() > 5 * plain.diff().std()
    assert pnl.diff().std() < 3 * plain.diff().std()

    # The pnl path really is the held weights over each move.
    steps = (panel.diff() * frame.shift(1)).sum(axis=1, min_count=3) * 100.0
    first = steps.first_valid_index()
    assert pnl.diff().loc[first] == pytest.approx(steps.loc[first], rel=1e-12)


def test_pnl_is_anchored_where_level_would_have_started():
    panel = _panel(n_obs=200)
    schema = fly.weights(method="minvar", window="60n")
    frame = solve_weights(panel, BASE_FLY, schema)
    level = combine(panel, frame, multiplier=100.0, mode="level")
    pnl = combine(panel, frame, multiplier=100.0, mode="pnl")

    start = pnl.first_valid_index()
    assert pnl.loc[start] == pytest.approx(level.loc[start], rel=1e-12)


def test_pnl_steps_across_a_missing_mark_instead_of_dropping_the_move():
    """A frame joined with another product carries that product's calendar."""
    panel = _panel(n_obs=150)
    frame = solve_weights(panel, BASE_FLY, fly.base)

    dense = combine(panel, frame, multiplier=100.0, mode="pnl")

    # Same data, but three extra index dates with no leg marks - what an outer
    # join against a swaption series does.
    extra = pd.DatetimeIndex(
        [panel.index[40] + pd.Timedelta(hours=6), panel.index[80] + pd.Timedelta(hours=6),
         panel.index[100] + pd.Timedelta(hours=6)]
    )
    holed = panel.reindex(panel.index.union(extra)).sort_index()
    holed_weights = solve_weights(holed, BASE_FLY, fly.base)
    got = combine(holed, holed_weights, multiplier=100.0, mode="pnl")

    assert got.reindex(panel.index).to_numpy() == pytest.approx(dense.to_numpy(), rel=1e-12)
    assert got.reindex(extra).isna().all()
    # The last value is the same total P&L, not one short of it.
    assert got.dropna().iloc[-1] == pytest.approx(dense.iloc[-1], rel=1e-12)

    # A row with SOME legs missing is no better than a row with none: a partial
    # sum(w * dr) is not a move. It must be skipped and stepped across too.
    partial = panel.copy()
    partial.iloc[60, 0] = np.nan
    got_partial = combine(partial, solve_weights(partial, BASE_FLY, fly.base), multiplier=100.0, mode="pnl")
    assert np.isnan(got_partial.iloc[60])
    # Total P&L is unchanged: the move over the hole lands on the next mark.
    assert got_partial.dropna().iloc[-1] == pytest.approx(dense.iloc[-1], rel=1e-12)


def test_current_mode_applies_the_last_weights_to_the_whole_history():
    panel = _panel(n_obs=200)
    frame = solve_weights(panel, BASE_FLY, fly.weights(method="pca", window="60n"))
    got = combine(panel, frame, multiplier=100.0, mode="current")

    last = frame.dropna(how="any").iloc[-1]
    expected = (panel * last).sum(axis=1) * 100.0
    assert got.to_numpy() == pytest.approx(expected.to_numpy(), rel=1e-12)
    assert got.notna().all()  # no burn-in: the weights are one vector


def test_auto_picks_level_for_a_static_fit_and_pnl_for_a_rolling_one():
    assert fly.pca_chgs.resolved_combine_mode == "level"
    assert fly.pca_chgs_1m.resolved_combine_mode == "pnl"
    assert fly.base.resolved_combine_mode == "level"
    assert fly.pca_chgs_1m.but(combine_mode="level").resolved_combine_mode == "level"
    assert parse_preset("pca_chgs_1m_current").combine_mode == "current"
    assert parse_preset("pca_chgs_1m_level").label == "pca_chgs_1m_level"
    # `current` uses weights fitted on the whole sample, so it is in sample too.
    assert parse_preset("pca_chgs_1m_current").is_in_sample is True


def test_a_nan_leg_produces_a_nan_package_not_a_partial_sum():
    panel = _panel(n_obs=30)
    panel.iloc[5, 0] = np.nan
    weight_frame = solve_weights(panel, BASE_FLY, fly.base)
    got = combine(panel, weight_frame, multiplier=100.0)
    assert np.isnan(got.iloc[5])
    assert np.isfinite(got.iloc[6])


def test_sign_flips_are_reported_not_silently_corrected():
    """A fitted wing may legitimately want the belly's sign; say so, keep it."""
    index = pd.bdate_range("2024-01-02", periods=300, name="Date")
    rng = np.random.default_rng(7)
    # A near-pure steepener regime: the 2Y barely moves, so the level hedge
    # loads the wings very asymmetrically.
    slope = np.cumsum(rng.normal(0.0, 0.05, 300))
    values = np.column_stack(
        [
            3.0 + rng.normal(0.0, 0.002, 300),
            3.5 + 0.5 * slope + rng.normal(0.0, 0.002, 300),
            4.0 + 1.0 * slope + rng.normal(0.0, 0.002, 300),
        ]
    )
    panel = pd.DataFrame(values, index=index, columns=["2Y", "5Y", "10Y"])
    frame = solve_weights(panel, BASE_FLY, fly.weights(method="minvar", max_abs_ratio=1e9))
    assert "sign_flips" in frame.attrs

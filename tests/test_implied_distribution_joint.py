import datetime
import math
from dataclasses import dataclass

import matplotlib
import numpy as np
from scipy.optimize import brentq

matplotlib.use("Agg")

from RVUtils.ImpliedDistribution import (
    FOMCPathState,
    FOMCPathStateConfig,
    JointDistributionComparison,
    JointDistributionSnapshot,
    SFRImpliedDistribution,
    plot_joint_comparison_dashboard,
    plot_joint_contour,
    plot_joint_probability_heatmap,
)
from RVUtils.ImpliedDistribution._bachelier import bachelier_call_price, bachelier_call_prices_vectorized
from RVUtils.ImpliedDistribution._joint_analytics import empirical_copula
from RVUtils.ImpliedDistribution._joint_states import contract_rate_matrix


@dataclass(frozen=True)
class _DummyParams:
    forward_price: float
    forward_rate: float
    time_to_expiry: float
    expiry_date: datetime.date
    as_of: datetime.date


@dataclass(frozen=True)
class _DummyPoint:
    strike_price: float
    right: str
    iv_normal_price: float


class _DummySmile:
    def __init__(self, *, symbol: str, params: _DummyParams, strike_vol_map: dict[float, float]):
        self.symbol = symbol
        self.source = "synthetic"
        self.underlying_contract = symbol
        self.quote_timestamp = datetime.datetime.combine(params.as_of, datetime.time(17, 0))
        self.params = params
        self._strike_vol_map = {round(float(k), 8): float(v) for k, v in strike_vol_map.items()}
        self.points = tuple(
            _DummyPoint(strike_price=float(k), right="C", iv_normal_price=float(v))
            for k, v in sorted(self._strike_vol_map.items())
        )

    def normal_vol(self, strikes, strike_space="price", vol_units="price"):
        _ = strike_space, vol_units
        arr = np.asarray(strikes, dtype=float).reshape(-1)
        out = np.array([self._strike_vol_map[round(float(k), 8)] for k in arr], dtype=float)
        if np.isscalar(strikes):
            return float(out[0])
        return out


def _invert_normal_vol(*, forward: float, strike: float, price: float, tte: float) -> float:
    intrinsic = max(float(forward) - float(strike), 0.0)
    if float(price) <= intrinsic + 1e-10:
        return 1e-6

    def _root(vol: float) -> float:
        return bachelier_call_price(strike, forward, vol, tte, 1.0) - price

    return float(brentq(_root, 1e-6, 5.0))


def _mixture_call_prices(strikes, *, mean_rates, weights, sigma, tte):
    prices = np.zeros(len(strikes), dtype=float)
    vols = np.full(len(strikes), float(sigma), dtype=float)
    for rate_mean, weight in zip(mean_rates, weights):
        prices += float(weight) * bachelier_call_prices_vectorized(
            np.asarray(strikes, dtype=float),
            100.0 - float(rate_mean),
            vols,
            float(tte),
            1.0,
        )
    return prices


def _state_config() -> FOMCPathStateConfig:
    meeting_dates = (
        datetime.date(2026, 12, 9),
        datetime.date(2027, 1, 27),
        datetime.date(2027, 12, 8),
        datetime.date(2028, 1, 26),
    )
    states = (
        FOMCPathState(
            label="Flat",
            initial_rate=4.25,
            meeting_dates=meeting_dates,
            meeting_rates=(4.25, 4.25, 4.25, 4.25),
        ),
        FOMCPathState(
            label="Early cuts",
            initial_rate=4.25,
            meeting_dates=meeting_dates,
            meeting_rates=(4.25, 4.10, 4.10, 4.10),
        ),
        FOMCPathState(
            label="Late cuts",
            initial_rate=4.25,
            meeting_dates=meeting_dates,
            meeting_rates=(4.25, 4.25, 4.10, 4.00),
        ),
        FOMCPathState(
            label="Hikes",
            initial_rate=4.25,
            meeting_dates=meeting_dates,
            meeting_rates=(4.35, 4.35, 4.45, 4.45),
        ),
    )
    return FOMCPathStateConfig(current_rate=4.25, states=states, entropy_regularization=1e-8)


def _build_joint_fixture(
    *,
    as_of: datetime.date,
    weights: np.ndarray,
    residual_stds: dict[str, float],
):
    symbols = ["SFRZ26", "SFRZ27"]
    state_config = _state_config()
    _, states = state_config.resolve(as_of=as_of, symbols=symbols)
    rate_matrix, _ = contract_rate_matrix(states, symbols=symbols)
    smiles = {}

    for idx, symbol in enumerate(symbols):
        forward_rate = float(np.dot(weights, rate_matrix[:, idx]))
        forward_price = 100.0 - forward_rate
        strikes = np.round(forward_price + np.array([-0.75, -0.50, -0.25, 0.0, 0.25, 0.50, 0.75]), 8)
        prices = _mixture_call_prices(
            strikes,
            mean_rates=rate_matrix[:, idx],
            weights=weights,
            sigma=residual_stds[symbol],
            tte=1.0,
        )
        strike_vol_map = {
            float(strike): _invert_normal_vol(forward=forward_price, strike=float(strike), price=float(price), tte=1.0)
            for strike, price in zip(strikes, prices)
        }
        smiles[symbol] = _DummySmile(
            symbol=symbol,
            params=_DummyParams(
                forward_price=forward_price,
                forward_rate=forward_rate,
                time_to_expiry=1.0,
                expiry_date=as_of + datetime.timedelta(days=365),
                as_of=as_of,
            ),
            strike_vol_map=strike_vol_map,
        )

    return state_config, smiles, rate_matrix


def test_extract_joint_recovers_shared_weights_and_joint_consistency():
    as_of = datetime.date(2026, 3, 2)
    true_weights = np.array([0.28, 0.34, 0.23, 0.15], dtype=float)
    true_sigmas = {"SFRZ26": 0.055, "SFRZ27": 0.075}
    state_config, smiles, rate_matrix = _build_joint_fixture(
        as_of=as_of,
        weights=true_weights,
        residual_stds=true_sigmas,
    )

    dist = SFRImpliedDistribution(
        use_sabr_vols=True,
        optimize_mixture_stds=True,
        initial_mixture_std_bps=6.0,
    )
    snapshot = dist.extract_joint(smiles, state_config=state_config, run_bl=False, run_legacy_gm=False)

    assert snapshot.optimization_success
    np.testing.assert_allclose(snapshot.state_weights, true_weights, atol=3e-2)
    np.testing.assert_allclose(
        snapshot.contract_residual_stds,
        np.array([true_sigmas["SFRZ26"], true_sigmas["SFRZ27"]]),
        atol=2e-2,
    )

    joint = snapshot.pair_joint_matrix("SFRZ26", "SFRZ27").data
    assert math.isclose(float(joint.to_numpy().sum()), 1.0, rel_tol=1e-8, abs_tol=1e-8)

    marginal_z26 = snapshot.marginal_distribution("SFRZ26").data.set_index("SFRZ26")["probability"]
    marginal_z27 = snapshot.marginal_distribution("SFRZ27").data.set_index("SFRZ27")["probability"]
    np.testing.assert_allclose(joint.sum(axis=1).sort_index().to_numpy(), marginal_z26.sort_index().to_numpy(), atol=1e-8)
    np.testing.assert_allclose(joint.sum(axis=0).sort_index().to_numpy(), marginal_z27.sort_index().to_numpy(), atol=1e-8)

    mean_vec = snapshot.mean_vector().data
    expected_means = rate_matrix.T @ true_weights
    np.testing.assert_allclose(mean_vec.to_numpy(dtype=float), expected_means, atol=1e-8)

    spread = snapshot.linear_combination_distribution({"SFRZ27": 1.0, "SFRZ26": -1.0}).data
    assert math.isclose(float(spread["probability"].sum()), 1.0, rel_tol=1e-8, abs_tol=1e-8)
    assert set(spread.columns) == {"linear_combination", "probability"}


def test_default_templated_path_config_resolves_nonempty_state_library():
    config = FOMCPathStateConfig.default_templated_paths(current_rate=4.25, n_plus_years=2, max_states=12)
    meeting_dates, states = config.resolve(as_of=datetime.date(2026, 3, 2), symbols=["SFRZ26", "SFRZ27"])
    assert meeting_dates
    assert states
    assert states[0].label.startswith("Flat")
    templates = {state.metadata.get("template") for state in states}
    assert {"flat"} <= templates


def test_compare_joint_reports_largest_cell_changes_and_change_metrics():
    state_config = _state_config()
    before_weights = np.array([0.30, 0.36, 0.19, 0.15], dtype=float)
    after_weights = np.array([0.18, 0.22, 0.42, 0.18], dtype=float)
    residual_stds = {"SFRZ26": 0.055, "SFRZ27": 0.075}

    _, smiles_before, _ = _build_joint_fixture(
        as_of=datetime.date(2026, 3, 2),
        weights=before_weights,
        residual_stds=residual_stds,
    )
    _, smiles_after, _ = _build_joint_fixture(
        as_of=datetime.date(2026, 3, 11),
        weights=after_weights,
        residual_stds=residual_stds,
    )

    dist = SFRImpliedDistribution(
        use_sabr_vols=True,
        optimize_mixture_stds=True,
        initial_mixture_std_bps=6.0,
    )
    comparison = dist.compare_joint(
        smiles_before,
        smiles_after,
        symbols=["SFRZ26", "SFRZ27"],
        state_config=state_config,
        run_bl=False,
        run_legacy_gm=False,
    )

    assert isinstance(comparison, JointDistributionComparison)
    assert comparison.snapshot_before.optimization_success
    assert comparison.snapshot_after.optimization_success

    delta_matrix = comparison.pair_joint_delta("SFRZ26", "SFRZ27").data
    top_changes = comparison.top_pair_cell_changes("SFRZ26", "SFRZ27", n=5).data
    assert not delta_matrix.empty
    assert not top_changes.empty

    expected_max = float(np.max(np.abs(delta_matrix.to_numpy(dtype=float))))
    assert math.isclose(abs(float(top_changes.iloc[0]["delta_probability"])), expected_max, rel_tol=1e-8, abs_tol=1e-8)

    copula_change = comparison.copula_change_summary("SFRZ26", "SFRZ27").data
    assert {"spearman_delta", "kendall_delta", "gaussian_rho_delta"} <= set(copula_change.index)
    assert abs(float(copula_change["gaussian_rho_delta"])) > 0

    spread_change = comparison.spread_change({"SFRZ27": 1.0, "SFRZ26": -1.0}).data
    assert spread_change["js_divergence"] > 0
    assert not spread_change["distribution_delta"].empty

    top_z26_value = float(comparison.snapshot_before.marginal_distribution("SFRZ26").data["SFRZ26"].max())
    conditional_change = comparison.conditional_change(
        target_symbol="SFRZ27",
        given_symbol="SFRZ26",
        given_values=[top_z26_value],
    ).data
    assert conditional_change["js_divergence"] >= 0
    assert not conditional_change["distribution_delta"].empty


def test_rank_dependence_uses_weighted_midranks_with_discrete_ties():
    states = tuple(
        FOMCPathState(label=f"S{i}", initial_rate=0.0, meeting_dates=tuple(), meeting_rates=tuple())
        for i in range(4)
    )
    snapshot = JointDistributionSnapshot(
        symbols=["A", "B"],
        as_of=datetime.date(2026, 3, 2),
        meeting_dates=tuple(),
        states=states,
        state_weights=np.array([0.20, 0.30, 0.25, 0.25], dtype=float),
        contract_rate_matrix=np.array(
            [
                [1.0, 1.0],
                [1.0, 2.0],
                [2.0, 2.0],
                [2.0, 3.0],
            ],
            dtype=float,
        ),
        contract_residual_stds=np.array([0.05, 0.05], dtype=float),
        rnd_inputs={},
        contract_snapshots={},
        per_contract_fit={},
        optimization_success=True,
        objective_value=0.0,
        entropy_regularization=0.0,
        fit_message="ok",
        provenance={},
    )

    rank = snapshot.rank_dependence("A", "B").data
    assert 0 <= float(rank["spearman"]) <= 1
    assert 0 <= float(rank["kendall_tau_b"]) <= 1

    copula = empirical_copula(snapshot, symbol_x="A", symbol_y="B").data.sort_values("x_value").reset_index(drop=True)
    assert math.isclose(float(copula.loc[0, "u"]), float(copula.loc[1, "u"]), rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(float(copula.loc[2, "u"]), float(copula.loc[3, "u"]), rel_tol=1e-9, abs_tol=1e-9)


def test_joint_plotting_smoke_includes_provenance_labels():
    state_config = _state_config()
    weights = np.array([0.28, 0.34, 0.23, 0.15], dtype=float)
    residual_stds = {"SFRZ26": 0.055, "SFRZ27": 0.075}
    _, smiles_before, _ = _build_joint_fixture(
        as_of=datetime.date(2026, 3, 2),
        weights=weights,
        residual_stds=residual_stds,
    )
    _, smiles_after, _ = _build_joint_fixture(
        as_of=datetime.date(2026, 3, 11),
        weights=np.array([0.18, 0.22, 0.42, 0.18], dtype=float),
        residual_stds=residual_stds,
    )

    dist = SFRImpliedDistribution(use_sabr_vols=True, optimize_mixture_stds=True, initial_mixture_std_bps=6.0)
    snapshot = dist.extract_joint(smiles_before, state_config=state_config, run_bl=False, run_legacy_gm=False)
    comparison = dist.compare_joint(
        smiles_before,
        smiles_after,
        symbols=["SFRZ26", "SFRZ27"],
        state_config=state_config,
        run_bl=False,
        run_legacy_gm=False,
    )

    ax = plot_joint_probability_heatmap(snapshot, "SFRZ26", "SFRZ27")
    assert "[" in ax.get_title()
    plt_fig = ax.figure

    contour_ax = plot_joint_contour(snapshot, "SFRZ26", "SFRZ27")
    assert "[" in contour_ax.get_title()

    dashboard = plot_joint_comparison_dashboard(comparison, "SFRZ26", "SFRZ27")
    assert len(dashboard.axes) >= 6

    plt_fig.clf()
    contour_ax.figure.clf()
    dashboard.clf()

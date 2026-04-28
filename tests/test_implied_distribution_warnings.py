import datetime
import numpy as np
import pytest

from RVUtils.ImpliedDistribution import (
    BreedenLitzenbergerResult,
    GaussianMixtureResult,
    ImpliedDistributionSnapshot,
    RNDInput,
)


def _trivial_rnd_input() -> RNDInput:
    return RNDInput(
        symbol="SFRZ26",
        as_of=datetime.date(2026, 4, 28),
        forward_price=96.5,
        forward_rate=3.5,
        time_to_expiry=0.5,
        expiry_date=datetime.date(2026, 12, 14),
        discount_factor=1.0,
        strikes_price=np.array([96.0, 96.5, 97.0]),
        call_premiums=np.array([0.6, 0.3, 0.1]),
        strike_source="test",
    )


class TestWarningsField:
    def test_bl_result_has_warnings_tuple_default_empty(self):
        result = BreedenLitzenbergerResult(
            input=_trivial_rnd_input(),
            strike_grid_rate=np.array([3.0, 3.5, 4.0]),
            rnd_density=np.array([0.2, 0.6, 0.2]),
            rnd_cumulative=np.array([0.2, 0.8, 1.0]),
            bin_edges_rate=np.array([3.0, 3.5, 4.0]),
            bin_probabilities=np.array([0.5, 0.5]),
            bin_labels=["3.25", "3.75"],
            mean_rate=3.5,
            std_rate=0.3,
            skewness=0.0,
            kurtosis=3.0,
            smoothing_param=1e-4,
            n_ghost_points=10,
            spline_residual=0.0,
        )
        assert result.warnings == ()

    def test_bl_result_warnings_field_accepts_tuple(self):
        result = BreedenLitzenbergerResult(
            input=_trivial_rnd_input(),
            strike_grid_rate=np.array([3.0]),
            rnd_density=np.array([1.0]),
            rnd_cumulative=np.array([1.0]),
            bin_edges_rate=np.array([3.0, 3.5]),
            bin_probabilities=np.array([1.0]),
            bin_labels=["3.25"],
            mean_rate=3.0,
            std_rate=0.0,
            skewness=0.0,
            kurtosis=3.0,
            smoothing_param=1e-4,
            n_ghost_points=10,
            spline_residual=0.0,
            warnings=("clipped 1.5% of mass below 0% rate floor",),
        )
        assert result.warnings == ("clipped 1.5% of mass below 0% rate floor",)

    def test_gm_result_has_warnings_tuple_default_empty(self):
        result = GaussianMixtureResult(
            input=_trivial_rnd_input(),
            scenarios=(),
            weights=np.array([]),
            fitted_std_rates=np.array([]),
            strike_grid_rate=np.array([3.0]),
            composite_density=np.array([1.0]),
            composite_cdf=np.array([1.0]),
            rmse_price=0.0,
            max_abs_error_price=0.0,
            optimization_success=True,
            component_densities=np.zeros((0, 1)),
        )
        assert result.warnings == ()

    def test_snapshot_aggregates_child_warnings(self):
        bl = BreedenLitzenbergerResult(
            input=_trivial_rnd_input(),
            strike_grid_rate=np.array([3.0]),
            rnd_density=np.array([1.0]),
            rnd_cumulative=np.array([1.0]),
            bin_edges_rate=np.array([3.0, 3.5]),
            bin_probabilities=np.array([1.0]),
            bin_labels=["3.25"],
            mean_rate=3.0,
            std_rate=0.0,
            skewness=0.0,
            kurtosis=3.0,
            smoothing_param=1e-4,
            n_ghost_points=10,
            spline_residual=0.0,
            warnings=("bl warning",),
        )
        snap = ImpliedDistributionSnapshot(
            symbol="SFRZ26",
            as_of=datetime.date(2026, 4, 28),
            bl_result=bl,
            gm_result=None,
        )
        assert snap.all_warnings() == ("bl::bl warning",)

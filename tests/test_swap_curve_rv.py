import datetime as dt

import numpy as np
import pandas as pd

from BT.signals.swap_curve_rv import (
    CurveDataset,
    FlyDefinition,
    SignalBundle,
    build_trade_universe,
    build_curve_dataset,
    compute_two_stage_trade_analytics,
    format_surface_token,
    months_to_tenor,
    shift_surface_token,
    split_surface_token,
    tenor_to_months,
)


def _make_synthetic_triplet(n_days: int = 260, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n_days)

    level = np.cumsum(rng.normal(0, 0.008, n_days))
    slope = np.cumsum(rng.normal(0, 0.004, n_days))
    curve = np.cumsum(rng.normal(0, 0.003, n_days))

    left = 3.0 + level - slope + curve + rng.normal(0, 0.0008, n_days)
    belly = 3.1 + level - 2.0 * curve + rng.normal(0, 0.0008, n_days)
    right = 3.2 + level + slope + curve + rng.normal(0, 0.0008, n_days)

    return pd.DataFrame({"3Y": left, "5Y": belly, "10Y": right}, index=dates)


def test_surface_token_month_helpers_round_trip():
    assert tenor_to_months("1Y") == 12
    assert tenor_to_months("18M") == 18
    assert months_to_tenor(24) == "2Y"
    assert months_to_tenor(11) == "11M"
    assert split_surface_token("5Yx1Y") == ("5Y", "1Y")
    assert format_surface_token("5Y", "1Y") == "5Yx1Y"
    assert shift_surface_token("5Yx1Y", forward_months_delta=1) == "5Yx13M"
    assert shift_surface_token("5Y", swap_months_delta=-1) == "59M"


def test_two_stage_trade_analytics_verifies_neutrality():
    triplet = _make_synthetic_triplet()
    dates = triplet.index
    fly_id = "3Y/5Y/10Y"

    dataset = CurveDataset(
        source="FAKE",
        curve_name="USD-SOFR-1D",
        mdp=None,
        dates=dates,
        curves_by_date={},
        rate_panel=triplet.copy(),
        surface_panel=triplet.copy(),
        surface_token_map={},
        trade_universe=[FlyDefinition("3Y", "5Y", "10Y", "standard_spot")],
    )
    signal_bundle = SignalBundle(
        fly_definitions=dataset.trade_universe,
        residuals={fly_id: pd.Series(np.linspace(-0.001, 0.001, len(dates)), index=dates)},
        residual_stats={fly_id: pd.DataFrame({"mean": 0.0, "std": 1.0, "zscore": 0.0}, index=dates)},
        zscores={fly_id: pd.Series(np.linspace(-1.0, 1.0, len(dates)), index=dates)},
        fit_quality={fly_id: pd.Series(0.95, index=dates)},
        weights={fly_id: pd.DataFrame(index=dates, columns=triplet.columns, dtype=float)},
        rate_triplets={fly_id: triplet.copy()},
        entry_snapshots={fly_id: {}},
        carry_bp={fly_id: pd.Series(1.0, index=dates)},
        roll_bp={fly_id: pd.Series(0.5, index=dates)},
        carry_roll_bp={fly_id: pd.Series(1.5, index=dates)},
        stationarity_pvalues={fly_id: pd.Series(0.01, index=dates)},
        stationarity_half_lives={fly_id: pd.Series(10.0, index=dates)},
        regime=pd.Series("green", index=dates),
        regime_details=pd.DataFrame({"indicator": np.nan, "regime": "green"}, index=dates),
        reference_betas=pd.DataFrame(index=dates),
        surface_residuals=pd.DataFrame(index=dates),
        surface_zscores=pd.DataFrame(index=dates),
        surface_fit_quality=pd.Series(index=dates, dtype=float),
    )

    config = {
        "signal": {
            "pca_window_days": 60,
            "zscore_lookback_days": 60,
            "n_components": 3,
            "pca_input": "levels",
            "use_correlation": False,
        },
        "stationarity": {"lookback_days": 60},
        "costs": {"round_trip_cost_bp": 0.5, "min_profit_to_cost_ratio": 2.0},
    }

    analytics = compute_two_stage_trade_analytics(
        dataset=dataset,
        signal_bundle=signal_bundle,
        config=config,
        fly_id=fly_id,
        as_of=dates[-1],
        validation_weight_mode="latest",
    )

    assert abs(analytics.pc_exposures["PC1"]) < 1e-8
    assert abs(analytics.pc_exposures["PC2"]) < 1e-8
    assert analytics.pc_loadings.shape == (3, 3)
    assert np.isfinite(analytics.current_level)
    assert np.isfinite(analytics.current_ou_zscore)
    assert analytics.carry_roll_bp == 1.5


def test_build_curve_dataset_uses_timeseries_builder_for_rate_panel():
    class _FakeCurveHandle:
        def __init__(self, as_of):
            self._as_of = as_of

        def reference_date(self):
            return self._as_of

    class _FakeMDP:
        source = "FAKE"

        def bulk_get_data(self, request):
            return {ts: _FakeCurveHandle(ts) for ts in request["timestamps"]}

    class _FakeTSBuilder:
        def __init__(self):
            self.calls = []

        def get_timeseries(self, start, end, queries, **kwargs):
            self.calls.append({"start": start, "end": end, "queries": queries, "kwargs": kwargs})
            idx = pd.DatetimeIndex([dt.date(2024, 1, 2), dt.date(2024, 1, 3)])
            cols = [q.name for q in queries]
            data = np.tile(np.arange(1, len(cols) + 1, dtype=float), (len(idx), 1))
            return pd.DataFrame(data + 300.0, index=idx, columns=cols)

    config = {
        "data": {
            "source": "FAKE",
            "curve_name": "USD-SOFR-1D",
            "start": dt.date(2024, 1, 2),
            "end": dt.date(2024, 1, 3),
            "timeseries_n_jobs": 3,
        },
        "surface": {
            "swap_tenors": ["2Y", "5Y"],
            "forward_starts": ["Spot", "1Y"],
            "fly_categories": {"spot": [("2Y", "5Y", "10Y")]},
            "enabled_categories": ["spot"],
        },
    }

    ts_builder = _FakeTSBuilder()
    dataset = build_curve_dataset(config, curve_mdp=_FakeMDP(), ts_builder=ts_builder, show_tqdm=False)

    assert len(ts_builder.calls) == 1
    assert dataset.rate_panel.shape[0] == 2
    assert {"2Y", "5Y", "10Y", "2Yx1Y", "5Yx1Y"}.issubset(dataset.rate_panel.columns)
    assert dataset.rate_panel.max().max() < 10.0  # converted from percent to decimal
    assert len(dataset.curves_by_date) == 2


def test_build_trade_universe_auto_expands_forward_variants_from_flat_config():
    config = {
        "forward_tails": ["2Y", "5Y"],
        "tenors_spot": ["2Y", "5Y", "10Y"],
        "fly_categories": {
            "standard_spot": [
                ("2Y", "5Y", "10Y"),
                ("3Y", "5Y", "7Y"),
            ],
        },
        "enabled_categories": ["standard_spot"],
        "include_forward_fly_variants": True,
        "auto_forward_from_categories": ["standard_spot"],
    }

    universe = build_trade_universe(config)
    fly_ids = {fly.fly_id for fly in universe}
    categories = {fly.fly_id: fly.category for fly in universe}

    assert "2Y/5Y/10Y" in fly_ids
    assert "2Yx2Y/5Yx2Y/10Yx2Y" in fly_ids
    assert "2Yx5Y/5Yx5Y/10Yx5Y" in fly_ids
    assert categories["2Y/5Y/10Y"] == "standard_spot"
    assert categories["2Yx2Y/5Yx2Y/10Yx2Y"] == "standard_fwd"
    assert categories["2Yx5Y/5Yx5Y/10Yx5Y"] == "standard_fwd"

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from BT.signals.pca_momentum import (
    PCAMomentumConfig,
    build_intraday_rate_queries,
    build_rank_tenor_map,
    compute_forward_return_zscore,
    fit_pca_momentum,
    generate_labels,
    generate_ma_features,
    walk_forward_pca_momentum,
)
from BT.signals.pca_momentum_backtest import (
    run_pca_momentum_query_backtest,
    run_pca_momentum_vectorized_backtest,
)


def _test_config(**overrides) -> PCAMomentumConfig:
    config = PCAMomentumConfig(
        contract_ranks=[4],
        ewma_short_spans=[2, 3],
        ewma_long_spans=[4, 5],
        label_forward_window=2,
        label_volatility_window=3,
        label_z_threshold=0.25,
        train_window_sessions=6,
        retrain_every_sessions=2,
        cv_splits=2,
        n_components=2,
        svm_c_grid=[0.1, 1.0],
        svm_gamma_grid=["scale", 0.1],
        trade_bpv=1.0,
        transaction_cost_bps_per_side=0.25,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _sinusoid_series(length: int = 48) -> pd.Series:
    index = pd.date_range("2026-01-01", periods=length, freq="D")
    values = 3.0 + np.sin(np.linspace(0.0, 6.0 * np.pi, length))
    return pd.Series(values, index=index, name="SFR4")


def test_build_rank_tenor_map_uses_q12_imm_pairs():
    mapping = build_rank_tenor_map(range(1, 13))

    assert mapping["SFR1"] == "IMM_1xIMM_2"
    assert mapping["SFR4"] == "IMM_4xIMM_5"
    assert mapping["SFR12"] == "IMM_12xIMM_13"
    assert len(mapping) == 12


def test_intraday_queries_do_not_set_custom_names():
    queries = build_intraday_rate_queries(_test_config(contract_ranks=[4, 12]))

    assert [query.tenor for query in queries] == ["IMM_4xIMM_5", "IMM_12xIMM_13"]
    assert all(query.name is None for query in queries)


def test_generate_ma_features_dimensions_and_warmup():
    series = pd.Series(np.arange(12, dtype=float), index=pd.date_range("2026-01-01", periods=12, freq="D"))
    features = generate_ma_features(series, ewma_short_spans=[2, 3], ewma_long_spans=[4, 5])

    assert list(features.columns) == [
        "ewma_minus_sma_short_2",
        "ewma_minus_sma_short_3",
        "ewma_minus_sma_long_4",
        "ewma_minus_sma_long_5",
        "ewma_cross_4_2",
        "ewma_cross_4_3",
        "ewma_cross_5_2",
        "ewma_cross_5_3",
    ]
    assert features.iloc[:4].isna().any(axis=1).all()
    assert features.iloc[-1].notna().all()


def test_label_construction_matches_forward_mean_over_trailing_vol():
    series = pd.Series(
        [0.0, 1.0, 3.0, 6.0, 10.0, 15.0, 21.0],
        index=pd.date_range("2026-01-01", periods=7, freq="D"),
    )
    target = compute_forward_return_zscore(
        series,
        forward_window=2,
        volatility_window=2,
    )
    labels = generate_labels(target, z_threshold=2.0)

    expected = np.mean([3.0, 4.0]) / np.std([1.0, 2.0], ddof=1)
    assert target.iloc[2] == pytest.approx(expected)
    assert labels.iloc[2] == 1.0
    assert pd.isna(target.iloc[-1])
    assert pd.isna(labels.iloc[-1])


def test_walk_forward_predictions_are_out_of_sample_only():
    config = _test_config()
    frame = fit_pca_momentum(_sinusoid_series(), config=config)

    predicted = frame.dropna(subset=["prediction"])
    assert not predicted.empty
    assert frame.iloc[: config.train_window_sessions]["prediction"].isna().all()
    assert (predicted["train_session_end"] < predicted["predict_session_start"]).all()


def test_walk_forward_retains_neutral_labels():
    config = _test_config(label_z_threshold=0.4)
    result = walk_forward_pca_momentum(_sinusoid_series().to_frame("SFR4"), config=config)
    labels = result.per_contract["SFR4"]["label"].dropna()

    assert 0.0 in set(labels.tolist())
    assert {-1.0, 0.0, 1.0}.issubset(set(labels.tolist()))


def test_vectorized_backtest_uses_receiver_long_sign_and_side_costs():
    index = pd.date_range("2026-01-01", periods=4, freq="30min")
    rates = pd.DataFrame({"SFR4": [1.00, 0.99, 1.00, 1.01]}, index=index)
    signals = pd.DataFrame({"SFR4": [1.0, 1.0, -1.0, -1.0]}, index=index)
    result = run_pca_momentum_vectorized_backtest(rates, signals, config=_test_config())

    expected = pd.Series([-0.25, 1.0, -1.5, 1.0], index=index).cumsum()
    pd.testing.assert_series_equal(result.cumulative_pnl, expected, check_names=False)
    assert result.metrics["total_pnl"] == pytest.approx(0.25)
    assert result.trade_sides["SFR4"] == pytest.approx(3.0)


def test_query_backtest_opens_flips_and_unwinds(mock_mdp):
    index = pd.date_range("2026-01-01 09:00", periods=4, freq="h")
    signals = pd.DataFrame({"SFR4": [1.0, 1.0, -1.0, 0.0]}, index=index)

    result = run_pca_momentum_query_backtest(
        signals,
        config=_test_config(),
        mdp=mock_mdp,
        contract_to_tenor={"SFR4": "IMM_4xIMM_5"},
        show_progress=False,
    )

    assert len(list(result.backtest.portfolio.iter_positions())) == 0
    assert len(result.backtest.portfolio.trades_log) == 2
    assert not result.mtm_history.empty


def test_query_backtest_allows_multiple_contracts(mock_mdp):
    index = pd.date_range("2026-01-01 09:00", periods=3, freq="h")
    signals = pd.DataFrame(
        {
            "SFR4": [1.0, 1.0, 1.0],
            "SFR5": [0.0, -1.0, -1.0],
        },
        index=index,
    )

    result = run_pca_momentum_query_backtest(
        signals,
        config=_test_config(contract_ranks=[4, 5]),
        mdp=mock_mdp,
        contract_to_tenor={"SFR4": "IMM_4xIMM_5", "SFR5": "IMM_5xIMM_6"},
        show_progress=False,
    )

    open_positions = list(result.backtest.portfolio.iter_positions())
    assert len(open_positions) == 2
    assert {position.meta["contract"] for position in open_positions} == {"SFR4", "SFR5"}


@dataclass
class _MomentumInstrument:
    tenor: str
    bpv: float


class _SchedulePricer:
    def __init__(self, curve_name: str, as_of_date: dt.date, schedule: dict[dt.date, float]):
        self.curve_name = curve_name
        self.as_of_date = as_of_date
        self.schedule = schedule

    def id(self) -> str:
        return self.curve_name

    def handle(self):
        return self

    def reference_date(self) -> dt.date:
        return self.as_of_date

    def build_irswap(
        self,
        fwd=None,
        tenor=None,
        effective_date=None,
        maturity_date=None,
        fixed_rate=None,
        notional=None,
        bpv=None,
    ):
        _ = fwd, effective_date, maturity_date, fixed_rate, notional
        return _MomentumInstrument(tenor=tenor or "IMM_4xIMM_5", bpv=float(bpv or 0.0))

    def fair_rate(self, instrument):
        _ = instrument
        return self.schedule[self.as_of_date]

    def npv(self, instrument):
        return -float(instrument.bpv) * self.schedule[self.as_of_date] * 100.0

    def pv01(self, instrument):
        return float(instrument.bpv)

    def analytic_delta(self, instrument):
        return float(instrument.bpv)

    def resolve_pricable(self, pricable, risk_weight=1.0):
        _ = risk_weight
        return pricable


class _ScheduleMDP:
    def __init__(self, schedule: dict[dt.date, float]):
        self.schedule = schedule

    def get_pricer(self, request):
        timestamp = request.get("timestamp")
        if isinstance(timestamp, dt.datetime):
            timestamp = timestamp.date()
        return _SchedulePricer(
            curve_name=request.get("curve_name", "USD-SOFR-1D-Q12STIRT"),
            as_of_date=timestamp,
            schedule=self.schedule,
        )


def test_vectorized_and_query_backtest_agree_on_receiver_long_direction():
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    rates = pd.DataFrame({"SFR4": [5.00, 4.95, 4.90, 4.85]}, index=index)
    signals = pd.DataFrame({"SFR4": [1.0, 1.0, 1.0, 1.0]}, index=index)
    config = _test_config(trade_bpv=1.0, transaction_cost_bps_per_side=0.0)

    vectorized = run_pca_momentum_vectorized_backtest(rates, signals, config=config)
    query = run_pca_momentum_query_backtest(
        signals,
        config=config,
        mdp=_ScheduleMDP({ts.date(): rate for ts, rate in rates["SFR4"].items()}),
        contract_to_tenor={"SFR4": "IMM_4xIMM_5"},
        show_progress=False,
    )

    assert vectorized.metrics["total_pnl"] > 0.0
    assert query.metrics["total_pnl"] > 0.0


def test_load_intraday_rate_panel_renames_cached_curve_columns():
    from BT.signals.pca_momentum import load_intraday_rate_panel

    class _FakeBuilder:
        def get_timeseries(self, start, end, queries, **kwargs):
            _ = start, end, kwargs
            index = pd.date_range("2026-03-02 18:00", periods=2, freq="min", tz="America/New_York")
            return pd.DataFrame(
                {
                    "USD-SOFR-1D IMM_4xIMM_5 OUTRIGHT RATE": [3.1, 3.2],
                    "USD-SOFR-1D IMM_12xIMM_13 OUTRIGHT RATE": [3.3, 3.4],
                },
                index=index,
            )

    @dataclass
    class _FakeMDP:
        source: str = "BARCHART_STIRF-RL"

    config = _test_config(contract_ranks=[4, 12], signal_bar_freq="1min")
    panel = load_intraday_rate_panel(
        start=pd.Timestamp("2026-03-02 18:00", tz="America/New_York").to_pydatetime(),
        end=pd.Timestamp("2026-03-02 18:01", tz="America/New_York").to_pydatetime(),
        config=config,
        ts_builder=_FakeBuilder(),
        curve_mdp=_FakeMDP(),
        show_tqdm=False,
    )

    assert list(panel.columns) == ["SFR4", "SFR12"]
    assert panel.iloc[0]["SFR4"] == pytest.approx(3.1)
    assert panel.iloc[0]["SFR12"] == pytest.approx(3.3)

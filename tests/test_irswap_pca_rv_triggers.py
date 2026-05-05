import pandas as pd

from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.signals.irswap_pca_rv_scanner import (
    IRSwapAnalyzedTrade,
    IRSwapFlyCandidate,
    IRSwapPCARVConfig,
)
from BT.signals.irswap_pca_rv_triggers import IRSwapPCARVTrigger, _build_fly_query
from Query.IRSwaps.IRSwapStructure import IRSwapStructure


def _make_trade(direction="receive_belly", passes=True):
    candidate = IRSwapFlyCandidate(
        forward_start=None,
        tenors=("3Y", "5Y", "10Y"),
        weights=(-0.90, 1.0, -0.46),
        direction=direction,
        zscore_belly=2.0 if direction == "receive_belly" else -2.0,
        zscore_left=-0.8 if direction == "receive_belly" else 0.8,
        zscore_right=-0.7 if direction == "receive_belly" else 0.7,
        neutrality_check=(0.0, 0.0),
    )
    return IRSwapAnalyzedTrade(
        candidate=candidate,
        fly_series=pd.Series([0.0015, 0.0018, 0.0020]),
        ou_speed=0.05,
        ou_mean=0.0010,
        ou_vol=0.0003,
        half_life_days=14.0,
        investment_horizon_days=90.0,
        current_level=0.0020,
        target_level=0.0010,
        stop_loss_level=0.0100,
        lifetime_zscore=2.0,
        adf_pvalue=0.01,
        carry_bps=0.0,
        roll_bps=0.0,
        carry_roll_bps=0.0,
        expected_profit_bps=10.0,
        profit_cost_ratio=3.0,
        passes_filter=passes,
        filter_reasons=[],
    )


def test_pca_fly_query_uses_risk_weights_not_legacy_weights(mock_mdp):
    config = IRSwapPCARVConfig(trade_belly_bpv=100_000.0)
    trade = _make_trade(direction="receive_belly")

    query = _build_fly_query(trade, config)

    assert query.structure == IRSwapStructure.FLY
    assert "risk_weights" in query.structure_kwargs
    assert "weights" not in query.structure_kwargs
    assert query.structure_kwargs["risk_weights"] == [0.9, 1.0, 0.46]

    pricer = mock_mdp.get_pricer(query.build_mdp_request(pd.Timestamp("2025-01-06")))
    _package, resolved_weights = query.resolve_package(pricer_or_curve=pricer)
    assert resolved_weights == [-0.9, 1.0, -0.46]


def test_pay_belly_query_resolves_opposite_signs(mock_mdp):
    config = IRSwapPCARVConfig(trade_belly_bpv=100_000.0)
    trade = _make_trade(direction="pay_belly")

    query = _build_fly_query(trade, config)

    assert query.structure_kwargs["bpv"] == -100_000.0
    pricer = mock_mdp.get_pricer(query.build_mdp_request(pd.Timestamp("2025-01-06")))
    _package, resolved_weights = query.resolve_package(pricer_or_curve=pricer)
    assert resolved_weights == [0.9, -1.0, 0.46]


def test_query_driven_backtest_marks_pca_fly_daily(simple_time_grid, mock_mdp):
    dates = list(simple_time_grid)
    signal_table = {pd.Timestamp(dates[0]): [_make_trade(direction="receive_belly")]}
    config = IRSwapPCARVConfig(trade_belly_bpv=10_000.0, max_concurrent_positions=1)
    trigger = IRSwapPCARVTrigger(signal_table, config)
    strategy = QueryStrategy("test_irswap_pca_rv", triggers=[trigger], default_mdp=mock_mdp)
    backtest = QueryDrivenBacktest(
        time_grid=simple_time_grid,
        strategy=strategy,
        mdp=mock_mdp,
        show_progress=False,
    )

    backtest.run()

    assert len(backtest.portfolio.trades_log) == 1
    assert len(backtest.mtm_history) == len(dates)
    assert set(backtest.mtm_history.keys()) == set(dates)

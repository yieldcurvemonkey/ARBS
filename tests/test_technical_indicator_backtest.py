import datetime as dt

import numpy as np
import pandas as pd
import pytest

from BT.signals.technical_indicator_backtest import (
    TechnicalIndicatorTriggerRequirements,
    run_technical_indicator_query_backtest,
)
from BT.signals.technical_indicators import TechnicalIndicatorSignalResult
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue


def _build_signal_result(index, execution_position, *, name="signal_asset") -> TechnicalIndicatorSignalResult:
    execution = pd.Series(execution_position, index=index, name=name, dtype=float)
    desired = execution.shift(-1)
    raw_series = pd.Series(np.linspace(1.0, 1.0 + len(index) - 1, len(index)), index=index, name=name)
    indicator_frame = pd.DataFrame({"feature": raw_series * 2.0}, index=index)
    return TechnicalIndicatorSignalResult(
        raw_series=raw_series,
        indicator_frame=indicator_frame,
        desired_position=desired,
        execution_position=execution,
    )


def test_technical_indicator_trigger_requirements_respect_fire_mode():
    index = pd.date_range("2026-01-01 09:00", periods=3, freq="h")
    table = {
        index[0]: {"alpha": 1},
        index[1]: {"alpha": 1},
        index[2]: {"alpha": -1},
    }

    changes_only = TechnicalIndicatorTriggerRequirements(position_table=table, fire_mode="changes_only")
    all_steps = TechnicalIndicatorTriggerRequirements(position_table=table, fire_mode="all_steps")

    assert bool(changes_only.has_triggered(index[0]))
    assert not bool(changes_only.has_triggered(index[1]))
    assert bool(changes_only.has_triggered(index[2]))
    assert bool(all_steps.has_triggered(index[1]))


def test_query_backtest_change_only_fires_once_per_position_change(mock_mdp):
    index = pd.date_range("2026-01-01 09:00", periods=5, freq="h")
    signal_result = _build_signal_result(index, [np.nan, 1.0, 1.0, 1.0, 0.0])
    calls = []

    def trade_query_factory(target_position, now, info):
        calls.append((target_position, now, info["signal_key"]))
        return IRSwapQuery(
            curve="USD-SOFR-1D-Q12STIRT",
            tenor="IMM_4xIMM_5",
            value=IRSwapValue.NPV,
            structure_kwargs={"bpv": 100_000.0 * float(target_position)},
        )

    result = run_technical_indicator_query_backtest(
        signal_result,
        trade_query_factory=trade_query_factory,
        mdp=mock_mdp,
        strategy_name="ma_crossover",
        show_progress=False,
    )

    assert len(calls) == 1
    assert calls[0][0] == 1
    assert len(result.backtest.portfolio.orders_log) == 1
    assert len(result.backtest.portfolio.trades_log) == 1
    assert len(list(result.backtest.portfolio.iter_positions())) == 0


def test_query_backtest_unwinds_before_flip_and_exit(mock_mdp):
    index = pd.date_range("2026-01-01 09:00", periods=5, freq="h")
    signal_result = _build_signal_result(index, [np.nan, 1.0, -1.0, -1.0, 0.0])
    calls = []

    def trade_query_factory(target_position, now, info):
        calls.append((target_position, now, info["signal_key"]))
        return IRSwapQuery(
            curve="USD-SOFR-1D-Q12STIRT",
            tenor="IMM_4xIMM_5",
            value=IRSwapValue.NPV,
            structure_kwargs={"bpv": 100_000.0 * float(target_position)},
        )

    result = run_technical_indicator_query_backtest(
        signal_result,
        trade_query_factory=trade_query_factory,
        mdp=mock_mdp,
        strategy_name="flip_test",
        show_progress=False,
    )

    assert [call[0] for call in calls] == [1, -1]
    assert len(result.backtest.portfolio.trades_log) == 2
    assert len(list(result.backtest.portfolio.iter_positions())) == 0
    assert result.metrics["trade_sides"] == 2.0


def test_query_backtest_can_trade_a_different_asset_than_the_signal(mock_mdp):
    index = pd.date_range("2026-01-01 09:00", periods=3, freq="h")
    signal_result = _build_signal_result(index, [np.nan, 1.0, 1.0], name="signal_leg")

    def trade_query_factory(target_position, now, info):
        _ = now, info
        return IRSwapQuery(
            curve="USD-SOFR-1D-Q12STIRT",
            tenor="IMM_5xIMM_6",
            value=IRSwapValue.NPV,
            structure_kwargs={"bpv": 100_000.0 * float(target_position)},
        )

    result = run_technical_indicator_query_backtest(
        signal_result,
        trade_query_factory=trade_query_factory,
        mdp=mock_mdp,
        strategy_name="cross_asset",
        show_progress=False,
    )

    open_positions = list(result.backtest.portfolio.iter_positions())
    assert len(open_positions) == 1
    assert open_positions[0].source_query.tenor == "IMM_5xIMM_6"
    assert open_positions[0].meta["signal_key"] == "signal_leg"


class _RuntimeIgnoreCacheMDP:
    def __init__(self):
        from tests.conftest import MockMDP

        self._base = MockMDP(source="BARCHART_STIRF-RL", base_rate=0.05)
        self.source = "BARCHART_STIRF-RL"
        self.pricer_requests = []

    def bulk_get_data(self, request):
        raise AssertionError("run_technical_indicator_query_backtest should not call bulk_get_data when ignore_cache_miss=True")

    def get_pricer(self, request):
        self.pricer_requests.append(dict(request))
        return self._base.get_pricer(request)


def test_query_backtest_ignore_cache_miss_is_runtime_only_and_skips_bulk_prefetch():
    index = pd.date_range("2026-01-01 09:00", periods=4, freq="h", tz="UTC")
    mdp = _RuntimeIgnoreCacheMDP()
    signal_result = _build_signal_result(index, [np.nan, 1.0, 1.0, 0.0])

    result = run_technical_indicator_query_backtest(
        signal_result,
        trade_query_factory=lambda target_position, now, info: IRSwapQuery(
            curve="USD-SOFR-1D-Q12STIRT",
            tenor="IMM_4xIMM_5",
            value=IRSwapValue.NPV,
            market_request={"timestamp": "now"},
            structure_kwargs={"bpv": 100_000.0 * float(target_position)},
        ),
        mdp=mdp,
        strategy_name="cache_trim",
        show_progress=False,
        ignore_cache_miss=True,
    )

    assert list(result.mtm_history.index) == [pd.Timestamp(ts) for ts in index]
    assert all(request.get("ignore_cache_miss") is True for request in mdp.pricer_requests)


def test_query_backtest_uses_tqdm_for_preparation_when_progress_enabled(monkeypatch, mock_mdp):
    import BT.query_engine as query_engine_module
    import BT.signals.technical_indicator_backtest as technical_bt_module

    index = pd.date_range("2026-01-01 09:00", periods=3, freq="h")
    signal_result = _build_signal_result(index, [np.nan, 1.0, 0.0])
    progress_calls = []

    class _RecordingTqdm:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            self.updates = []
            progress_calls.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        def update(self, n=1):
            self.updates.append(int(n))

    monkeypatch.setattr(technical_bt_module, "_tqdm", _RecordingTqdm)
    monkeypatch.setattr(query_engine_module.tqdm, "tqdm", lambda iterable, **kwargs: iterable)

    result = run_technical_indicator_query_backtest(
        signal_result,
        trade_query_factory=lambda target_position, now, info: IRSwapQuery(
            curve="USD-SOFR-1D-Q12STIRT",
            tenor="IMM_4xIMM_5",
            value=IRSwapValue.NPV,
            structure_kwargs={"bpv": 100_000.0 * float(target_position)},
        ),
        mdp=mock_mdp,
        strategy_name="progress_test",
        show_progress=True,
    )

    assert result.backtest.mtm_history
    assert len(progress_calls) == 1
    assert progress_calls[0].kwargs["desc"] == "PROGRESS_TEST PREP"
    assert progress_calls[0].kwargs["disable"] is False
    assert sum(progress_calls[0].updates) == (3 + 3 + 3 + 3 + 1)

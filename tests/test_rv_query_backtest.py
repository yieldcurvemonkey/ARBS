import datetime as dt
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from BT.signals.rv_backtest import RVBacktestConfig, run_query_rv_backtest
from BT.signals.swap_curve_rv import CurveDataset, FlyDefinition, _compute_carry_roll_panels
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue


def _parse_tenor_years(token: str) -> float:
    text = str(token).strip().upper()
    if "X" in text:
        text = text.split("X", 1)[0]
    if text.endswith("Y"):
        return float(text[:-1])
    if text.endswith("M"):
        return float(text[:-1]) / 12.0
    return 1.0


@dataclass(frozen=True)
class _FakeSwap:
    tenor: str
    notional: float
    fixed_rate: float = 0.0

    def with_notional(self, notional: float) -> "_FakeSwap":
        return replace(self, notional=notional)


class _FakeCurve:
    def __init__(self, as_of_date: dt.date):
        self.as_of_date = as_of_date
        self.day_index = as_of_date.day

    def id(self) -> str:
        return "FAKE-CURVE"

    def reference_date(self) -> dt.date:
        return self.as_of_date

    def build_irswap(
        self,
        fwd=None,
        tenor=None,
        effective_date=None,
        maturity_date=None,
        fixed_rate=-0.0,
        notional=None,
        bpv=None,
    ) -> _FakeSwap:
        tenor_label = tenor or "1Y"
        tenor_years = _parse_tenor_years(tenor_label)
        if notional is None and bpv is not None:
            notional = bpv / max(tenor_years * 1e-4, 1e-12)
        if notional is None:
            notional = 1_000_000.0
        return _FakeSwap(tenor=tenor_label, notional=float(notional), fixed_rate=float(fixed_rate or 0.0))

    def fair_rate(self, instrument: _FakeSwap) -> float:
        return 0.02 + self.day_index * 0.0001 + _parse_tenor_years(instrument.tenor) * 0.0002

    def npv(self, instrument: _FakeSwap) -> float:
        return instrument.notional * self.fair_rate(instrument)

    def pv01(self, instrument: _FakeSwap) -> float:
        return instrument.notional * _parse_tenor_years(instrument.tenor) * 1e-4

    def resolve_pricable(self, pricable: _FakeSwap, risk_weight: float = 1.0) -> _FakeSwap:
        return pricable.with_notional(pricable.notional * risk_weight)

    def carry_bps_running(self, instrument: _FakeSwap, horizon: str) -> float:
        return _parse_tenor_years(instrument.tenor)

    def roll_bps_running(self, instrument: _FakeSwap, horizon: str) -> float:
        return 0.5 * _parse_tenor_years(instrument.tenor)

    def carry_and_roll_bps_running(self, instrument: _FakeSwap, horizon: str) -> float:
        return self.carry_bps_running(instrument, horizon) + self.roll_bps_running(instrument, horizon)


class _FakeMDP:
    source = "FAKE-MDP"

    def get_pricer(self, request):
        ts = request["timestamp"]
        if isinstance(ts, dt.datetime):
            ts = ts.date()
        return _FakeCurve(ts)


def _constant_weights(index: pd.DatetimeIndex, left: float = -0.9, belly: float = 1.0, right: float = -0.46) -> pd.DataFrame:
    return pd.DataFrame(
        np.tile([left, belly, right], (len(index), 1)),
        index=index,
        columns=["left", "belly", "right"],
    )


def _residual_stats(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"mean": 0.0, "std": 1.0}, index=index)


def _query_factory(fly_id: str, weights: np.ndarray, direction: int):
    left, belly, right = fly_id.split("/")
    return IRSwapQuery(
        structure=IRSwapStructure.FLY,
        value=IRSwapValue.NPV,
        curve="USD-SOFR-1D",
        structure_kwargs={
            "front_tenor": left,
            "belly_tenor": belly,
            "back_tenor": right,
            "bpv": 1_000.0 * direction,
            "risk_weights": [float(x) for x in weights],
        },
    )


def test_query_backtest_ranks_entries_by_abs_zscore():
    dates = pd.bdate_range("2025-01-06", periods=4)
    residuals = {
        "2Y/5Y/10Y": pd.Series([-0.0010, -0.0010, -0.0010, -0.0010], index=dates),
        "3Y/5Y/7Y": pd.Series([-0.0015, -0.0015, -0.0015, -0.0015], index=dates),
    }
    zscores = {
        "2Y/5Y/10Y": pd.Series([1.0, 1.0, 1.0, 1.0], index=dates),
        "3Y/5Y/7Y": pd.Series([2.0, 2.0, 2.0, 2.0], index=dates),
    }
    fit_quality = {fid: pd.Series(0.9, index=dates) for fid in residuals}
    weights = {fid: _constant_weights(dates) for fid in residuals}
    stats = {fid: _residual_stats(dates) for fid in residuals}
    entry_snapshots = {fid: {dates[0]: {"kind": "flat"}} for fid in residuals}
    regime = pd.Series("green", index=dates)

    result = run_query_rv_backtest(
        residuals=residuals,
        zscores=zscores,
        fit_quality=fit_quality,
        weights=weights,
        fly_categories={"2Y/5Y/10Y": "spot", "3Y/5Y/7Y": "spot"},
        entry_snapshots=entry_snapshots,
        residual_stats=stats,
        regime=regime,
        mdp=_FakeMDP(),
        query_factory=_query_factory,
        frozen_residual_getter=lambda fid, date_key, snapshot: residuals[fid].loc[pd.Timestamp(date_key)],
        config=RVBacktestConfig(
            trade_belly_bpv=1_000.0,
            entry_min_fit=0.5,
            entry_min_residual_bp=0.5,
            entry_min_zscore=0.5,
            max_concurrent_trades=1,
            round_trip_cost_bp=0.0,
            min_profit_to_cost_ratio=0.0,
            exit_mean_reversion=False,
            exit_max_holding_days=10,
        ),
        show_progress=False,
    )

    assert len(result.trades) == 1
    assert result.trades.iloc[0]["fly_id"] == "3Y/5Y/7Y"


def test_query_backtest_respects_stationarity_filter():
    dates = pd.bdate_range("2025-01-06", periods=3)
    residuals = {"2Y/5Y/10Y": pd.Series([-0.0010, -0.0010, -0.0010], index=dates)}
    zscores = {"2Y/5Y/10Y": pd.Series([2.0, 2.0, 2.0], index=dates)}
    fit_quality = {"2Y/5Y/10Y": pd.Series(0.9, index=dates)}
    weights = {"2Y/5Y/10Y": _constant_weights(dates)}
    stats = {"2Y/5Y/10Y": _residual_stats(dates)}
    entry_snapshots = {"2Y/5Y/10Y": {dates[0]: {"kind": "flat"}}}
    regime = pd.Series("green", index=dates)
    pvalues = {"2Y/5Y/10Y": pd.Series([0.20, 0.20, 0.20], index=dates)}
    half_lives = {"2Y/5Y/10Y": pd.Series([5.0, 5.0, 5.0], index=dates)}

    result = run_query_rv_backtest(
        residuals=residuals,
        zscores=zscores,
        fit_quality=fit_quality,
        weights=weights,
        fly_categories={"2Y/5Y/10Y": "spot"},
        entry_snapshots=entry_snapshots,
        residual_stats=stats,
        regime=regime,
        mdp=_FakeMDP(),
        query_factory=_query_factory,
        frozen_residual_getter=lambda fid, date_key, snapshot: residuals[fid].loc[pd.Timestamp(date_key)],
        config=RVBacktestConfig(
            trade_belly_bpv=1_000.0,
            entry_min_fit=0.5,
            entry_min_residual_bp=0.5,
            entry_min_zscore=0.5,
            stationarity_filter_enabled=True,
            stationarity_max_adf_pvalue=0.05,
            round_trip_cost_bp=0.0,
            min_profit_to_cost_ratio=0.0,
        ),
        stationarity_pvalues=pvalues,
        stationarity_half_lives=half_lives,
        show_progress=False,
    )

    assert result.trades.empty
    assert result.daily_pnl_ccy.abs().sum() == 0.0


def test_query_backtest_daily_pnl_comes_from_pricer_mtm():
    dates = pd.bdate_range("2025-01-06", periods=4)
    residuals = {"2Y/5Y/10Y": pd.Series([-0.0010, -0.0010, -0.0010, -0.0010], index=dates)}
    zscores = {"2Y/5Y/10Y": pd.Series([2.0, 2.0, 2.0, 2.0], index=dates)}
    fit_quality = {"2Y/5Y/10Y": pd.Series(0.9, index=dates)}
    weights = {"2Y/5Y/10Y": _constant_weights(dates)}
    stats = {"2Y/5Y/10Y": _residual_stats(dates)}
    entry_snapshots = {"2Y/5Y/10Y": {dates[0]: {"kind": "flat"}}}
    regime = pd.Series("green", index=dates)

    result = run_query_rv_backtest(
        residuals=residuals,
        zscores=zscores,
        fit_quality=fit_quality,
        weights=weights,
        fly_categories={"2Y/5Y/10Y": "spot"},
        entry_snapshots=entry_snapshots,
        residual_stats=stats,
        regime=regime,
        mdp=_FakeMDP(),
        query_factory=_query_factory,
        frozen_residual_getter=lambda fid, date_key, snapshot: -0.0010,
        config=RVBacktestConfig(
            trade_belly_bpv=1_000.0,
            entry_min_fit=0.5,
            entry_min_residual_bp=0.5,
            entry_min_zscore=0.5,
            round_trip_cost_bp=0.0,
            min_profit_to_cost_ratio=0.0,
            exit_mean_reversion=False,
            exit_max_holding_days=10,
        ),
        show_progress=False,
    )

    assert len(result.trades) == 1
    assert result.daily_pnl_ccy.abs().sum() > 0.0
    assert np.isclose(result.daily_pnl_ccy.sum(), result.metrics["total_pnl_ccy"])
    cat_sum = result.daily_pnl_by_category_ccy.sum(axis=1)
    pd.testing.assert_series_equal(cat_sum, result.daily_pnl_ccy, check_names=False)


def test_custom_weighted_carry_roll_panel_uses_fly_weights():
    dates = pd.bdate_range("2025-01-06", periods=2)
    universe = [FlyDefinition(left="2Y", belly="5Y", right="10Y", category="spot")]
    weights = {
        "2Y/5Y/10Y": pd.DataFrame(
            [[-0.9, 1.0, -0.46], [-0.9, 1.0, -0.46]],
            index=dates,
            columns=["2Y", "5Y", "10Y"],
        )
    }
    dataset = CurveDataset(
        source="FAKE",
        curve_name="USD-SOFR-1D",
        mdp=_FakeMDP(),
        dates=dates,
        curves_by_date={date_key: _FakeCurve(date_key.date()) for date_key in dates},
        rate_panel=pd.DataFrame(index=dates),
        surface_panel=pd.DataFrame(index=dates),
        surface_token_map={},
        trade_universe=universe,
    )

    carry, roll, carry_roll = _compute_carry_roll_panels(
        dataset=dataset,
        universe=universe,
        weights=weights,
        trade_belly_bpv=100_000.0,
        horizon="1M",
    )

    expected_carry = -0.9 * 2.0 + 1.0 * 5.0 - 0.46 * 10.0
    expected_roll = 0.5 * expected_carry
    fid = "2Y/5Y/10Y"
    assert np.allclose(carry[fid].dropna().values, [expected_carry, expected_carry])
    assert np.allclose(roll[fid].dropna().values, [expected_roll, expected_roll])
    assert np.allclose(carry_roll[fid].dropna().values, [expected_carry + expected_roll, expected_carry + expected_roll])

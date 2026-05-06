import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from BT.signals.risk_premia_pairs_pca_backtest import (
    RiskPremiaPairsPCAConfig,
    RiskPremiaPCASignal,
    RiskPremiaPCASnapshot,
    build_risk_premia_pca_signal_table,
    make_irs_query_factory,
    run_risk_premia_pairs_pca_backtest,
)


def test_pca_signal_table_selects_dislocated_idea_with_phase2_weight():
    dates = pd.bdate_range("2025-01-01", periods=60)
    base = np.linspace(0.0, 1.0, len(dates))
    panel = pd.DataFrame(
        {
            "2Y/5Y/10Y": base,
            "3Y/5Y/7Y": 2.0 * base,
            "5Y/10Y/30Y": 3.0 * base,
        },
        index=dates,
    )
    panel.iloc[-1, panel.columns.get_loc("5Y/10Y/30Y")] += 5.0

    config = RiskPremiaPairsPCAConfig(
        pca_window_days=40,
        pca_components=1,
        residual_z_entry=1.0,
        phase1_min_realized_sharpe=-999.0,
        covariance_lookback_days=20,
        phase1_lookback_days=20,
        min_abs_target_weight=0.0,
        max_abs_weight=0.5,
    )

    table = build_risk_premia_pca_signal_table(panel, config)
    last_snapshot = table[pd.Timestamp(dates[-1])]

    assert last_snapshot.signals
    ideas = {signal.idea_id for signal in last_snapshot.signals}
    assert "5Y/10Y/30Y" in ideas
    assert all(abs(signal.target_weight) <= 0.5 + 1e-12 for signal in last_snapshot.signals)
    assert all(np.sign(signal.target_weight) == signal.direction for signal in last_snapshot.signals)


@dataclass(frozen=True)
class _FakeSwap:
    tenor: str
    notional: float
    fixed_rate: float = 0.0

    def with_notional(self, notional: float) -> "_FakeSwap":
        return _FakeSwap(tenor=self.tenor, notional=float(notional), fixed_rate=self.fixed_rate)


class _FakeCurve:
    def __init__(self, as_of_date: dt.date):
        self.as_of_date = as_of_date
        self.day_index = (as_of_date - dt.date(2025, 1, 6)).days

    def id(self) -> str:
        return "USD-SOFR-1D"

    def reference_date(self) -> dt.date:
        return self.as_of_date

    def calendar_advance(self, ref_date, tenor):
        return ref_date

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
        _ = fwd, effective_date, maturity_date
        tenor_label = tenor or "1Y"
        tenor_years = float(str(tenor_label).rstrip("Y"))
        if notional is None:
            notional = float(bpv) / max(tenor_years * 1e-4, 1e-12) if bpv is not None else 1_000_000.0
        return _FakeSwap(tenor=tenor_label, notional=float(notional), fixed_rate=float(fixed_rate or 0.0))

    def fair_rate(self, instrument: _FakeSwap) -> float:
        tenor_years = float(str(instrument.tenor).rstrip("Y"))
        return 0.02 + tenor_years * 0.0002 + self.day_index * 0.00005 * tenor_years

    def npv(self, instrument: _FakeSwap) -> float:
        return float(instrument.notional) * (self.fair_rate(instrument) - float(instrument.fixed_rate))

    def pv01(self, instrument: _FakeSwap) -> float:
        tenor_years = float(str(instrument.tenor).rstrip("Y"))
        return float(instrument.notional) * tenor_years * 1e-4

    def resolve_pricable(self, pricable: _FakeSwap, risk_weight: float = 1.0) -> _FakeSwap:
        return pricable.with_notional(pricable.notional * float(risk_weight))


class _FakeSwapMDP:
    def get_pricer(self, request):
        ts = request["timestamp"]
        if isinstance(ts, dt.datetime):
            ts = ts.date()
        return _FakeCurve(ts)


def _signal(idea_id: str, date, *, zscore: float, target_weight: float) -> RiskPremiaPCASignal:
    return RiskPremiaPCASignal(
        idea_id=idea_id,
        timestamp=pd.Timestamp(date),
        residual=zscore / 10_000.0,
        zscore=zscore,
        direction=1 if target_weight > 0 else -1,
        phase1_sharpe=1.0,
        phase1_weight=target_weight,
        target_weight=target_weight,
        overlay_scale=1.0,
        expected_edge_bp=abs(zscore),
        covariance_vol=0.0,
        rank_score=abs(zscore),
    )


def test_query_driven_backtest_enters_marks_daily_and_exits_on_mean_reversion():
    dates = pd.bdate_range("2025-01-06", periods=3)
    signal_table = {
        pd.Timestamp(dates[0]): RiskPremiaPCASnapshot(
            timestamp=pd.Timestamp(dates[0]),
            signals=(_signal("2Y/5Y/10Y", dates[0], zscore=-2.0, target_weight=1.0),),
            overlay_scale=1.0,
        ),
        pd.Timestamp(dates[1]): RiskPremiaPCASnapshot(
            timestamp=pd.Timestamp(dates[1]),
            signals=(_signal("2Y/5Y/10Y", dates[1], zscore=-0.1, target_weight=1.0),),
            overlay_scale=1.0,
        ),
        pd.Timestamp(dates[2]): RiskPremiaPCASnapshot(
            timestamp=pd.Timestamp(dates[2]),
            signals=tuple(),
            overlay_scale=1.0,
        ),
    }
    config = RiskPremiaPairsPCAConfig(
        trade_bpv=100_000.0,
        residual_z_exit=0.25,
        max_holding_days=10,
        round_trip_cost_bp=0.0,
    )

    result = run_risk_premia_pairs_pca_backtest(
        signal_table=signal_table,
        mdp=_FakeSwapMDP(),
        query_factory=make_irs_query_factory(curve="USD-SOFR-1D", default_bpv=config.trade_bpv),
        config=config,
        show_progress=False,
    )

    bt = result.query_backtest
    assert len(bt.mtm_history) == len(dates)
    assert len(bt.portfolio.closed_positions_log) == 1
    assert result.trades.iloc[0]["exit_reason"] == "mean_reversion"
    assert result.trades.iloc[0]["idea_id"] == "2Y/5Y/10Y"
    assert result.metrics["n_trades"] == 1
    assert result.daily_pnl.index.is_monotonic_increasing


def test_multi_order_idea_is_reported_as_one_trade():
    from BT.query_actions import BuiltQuery
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    dates = pd.bdate_range("2025-01-06", periods=2)
    signal_table = {
        pd.Timestamp(dates[0]): RiskPremiaPCASnapshot(
            timestamp=pd.Timestamp(dates[0]),
            signals=(_signal("spread_CT10", dates[0], zscore=-2.0, target_weight=1.0),),
            overlay_scale=1.0,
        ),
        pd.Timestamp(dates[1]): RiskPremiaPCASnapshot(
            timestamp=pd.Timestamp(dates[1]),
            signals=(_signal("spread_CT10", dates[1], zscore=0.0, target_weight=1.0),),
            overlay_scale=1.0,
        ),
    }
    config = RiskPremiaPairsPCAConfig(trade_bpv=100_000.0, residual_z_exit=0.25)

    def _package_factory(signal):
        signed_bpv = config.trade_bpv * signal.target_weight
        return [
            BuiltQuery(
                IRSwapQuery(
                    structure=IRSwapStructure.OUTRIGHT,
                    value=IRSwapValue.NPV,
                    curve="USD-SOFR-1D",
                    tenor="2Y",
                    structure_kwargs={"bpv": signed_bpv},
                ),
                meta={"package_leg": "front"},
            ),
            BuiltQuery(
                IRSwapQuery(
                    structure=IRSwapStructure.OUTRIGHT,
                    value=IRSwapValue.NPV,
                    curve="USD-SOFR-1D",
                    tenor="10Y",
                    structure_kwargs={"bpv": -signed_bpv},
                ),
                meta={"package_leg": "back"},
            ),
        ]

    result = run_risk_premia_pairs_pca_backtest(
        signal_table=signal_table,
        mdp=_FakeSwapMDP(),
        query_factory=_package_factory,
        config=config,
        show_progress=False,
    )

    assert len(result.query_backtest.portfolio.closed_positions_log) == 2
    assert len(result.trades) == 1
    assert result.metrics["n_trades"] == 1


def test_irs_query_factory_rejects_unparseable_idea_id():
    signal = _signal("2Y/3Y/5Y/7Y", pd.Timestamp("2025-01-06"), zscore=2.0, target_weight=-0.25)
    factory = make_irs_query_factory()

    with pytest.raises(ValueError):
        factory(signal)

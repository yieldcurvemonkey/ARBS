# tests/test_stir_convexity_adjustment_mdp.py
import pytest
import datetime
import math
from dataclasses import dataclass

from MDP.MarketDataProvider import MarketDataProvider
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from TB.TimeseriesBuilder import TimeseriesBuilder
from tests.conftest import MockMDP
from MDP.Spreads.SpreadPricer import SpreadPricer


class TestHW1FModel:
    def test_convexity_adjustment(self):
        from MDP.STIRConvexityAdjustment.hw1f_model import hw1f_convexity_adjustment
        a = 0.03
        sigma = 0.01
        T1 = 1.0
        T2 = 1.25
        result = hw1f_convexity_adjustment(a=a, sigma=sigma, T1=T1, T2=T2)
        expected = (sigma**2 / (2 * a**2)) * (1 - math.exp(-a * T1)) * (1 - math.exp(-a * T2))
        assert abs(result - expected) < 1e-12

    def test_zero_mean_reversion_raises(self):
        from MDP.STIRConvexityAdjustment.hw1f_model import hw1f_convexity_adjustment
        with pytest.raises(ValueError):
            hw1f_convexity_adjustment(a=0.0, sigma=0.01, T1=1.0, T2=1.25)

    def test_convexity_increases_with_maturity(self):
        from MDP.STIRConvexityAdjustment.hw1f_model import hw1f_convexity_adjustment
        adj_short = hw1f_convexity_adjustment(a=0.03, sigma=0.01, T1=0.25, T2=0.5)
        adj_long = hw1f_convexity_adjustment(a=0.03, sigma=0.01, T1=5.0, T2=5.25)
        assert adj_long > adj_short


class TestSTIRConvexityAdjustmentMDP:
    def test_construction(self):
        from MDP.STIRConvexityAdjustment.STIRConvexityAdjustmentMDP import STIRConvexityAdjustmentMDP
        mdp = STIRConvexityAdjustmentMDP(
            _mdp_a=MockMDP(source="STIRT", base_rate=0.04),
            _mdp_b=MockMDP(source="ERIS", base_rate=0.038),
        )
        assert mdp.source == "STIRCVX_EMPIRICAL"

    def test_get_pricer_returns_spread_pricer(self):
        from MDP.STIRConvexityAdjustment.STIRConvexityAdjustmentMDP import STIRConvexityAdjustmentMDP
        mdp = STIRConvexityAdjustmentMDP(
            _mdp_a=MockMDP(source="STIRT", base_rate=0.04),
            _mdp_b=MockMDP(source="ERIS", base_rate=0.038),
        )
        result = mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": datetime.date(2026, 3, 15)})
        assert isinstance(result, SpreadPricer)


@dataclass
class _EmpiricalSwap:
    tenor: str
    notional: float
    fixed_rate: float
    effective_date: datetime.date | None = None
    maturity_date: datetime.date | None = None


class _EmpiricalCurvePricer:
    def __init__(self, curve_name: str, as_of_date: datetime.date, fair_rate: float):
        self.curve_name = curve_name
        self.as_of_date = as_of_date
        self._fair_rate = float(fair_rate)

    def id(self) -> str:
        return self.curve_name

    def reference_date(self) -> datetime.date:
        return self.as_of_date

    def build_irswap(
        self,
        fwd: str | None = None,
        tenor: str | None = None,
        effective_date: datetime.date | None = None,
        maturity_date: datetime.date | None = None,
        fixed_rate: float | None = None,
        notional: float | None = None,
        bpv: float | None = None,
    ) -> _EmpiricalSwap:
        _ = fwd
        resolved_notional = notional or (bpv / 0.0001 if bpv is not None else 1_000_000.0)
        resolved_rate = self._fair_rate if fixed_rate in (None, -0.0, 0.0) else float(fixed_rate)
        return _EmpiricalSwap(
            tenor=tenor or "IMM",
            notional=float(resolved_notional),
            fixed_rate=resolved_rate,
            effective_date=effective_date,
            maturity_date=maturity_date,
        )

    def fair_rate(self, irswap: _EmpiricalSwap) -> float:
        _ = irswap
        return self._fair_rate

    def npv(self, irswap: _EmpiricalSwap) -> float:
        return (irswap.fixed_rate - self._fair_rate) * irswap.notional

    def pv01(self, irswap: _EmpiricalSwap) -> float:
        return abs(irswap.notional) * 0.0001


class _EmpiricalCurveMDP(MarketDataProvider):
    def __init__(self, source: str, fair_rate: float):
        super().__init__(source=source)
        self._fair_rate = float(fair_rate)

    def get_pricer(self, request):
        curve_name = request.get("curve_name", "USD-SOFR-1D")
        timestamp = request.get("timestamp", datetime.date.today())
        if isinstance(timestamp, datetime.datetime):
            timestamp = timestamp.date()
        return _EmpiricalCurvePricer(curve_name=curve_name, as_of_date=timestamp, fair_rate=self._fair_rate)


def test_irswap_query_prices_empirical_convexity_adjustment():
    from MDP.STIRConvexityAdjustment.STIRConvexityAdjustmentMDP import STIRConvexityAdjustmentMDP

    mdp = STIRConvexityAdjustmentMDP(
        _mdp_a=_EmpiricalCurveMDP(source="STIRT", fair_rate=0.0400),
        _mdp_b=_EmpiricalCurveMDP(source="ERIS", fair_rate=0.0380),
    )

    q = IRSwapQuery(
        tenor="IMM_Z27xIMM_H28",
        value=IRSwapValue.CVX_ADJ_EMPIRICAL,
        market_request={
            "curve_name_a": "USD-SOFR-1D-Q16STIRT",
            "curve_name_b": "USD-SOFR-1D",
        },
    )

    now = datetime.datetime(2026, 3, 13, 17, 0)
    request = q.build_mdp_request(now)
    assert request["timestamp"] == now

    pricer = mdp.get_pricer(request)
    package, weights = q.resolve_package(pricer_or_curve=pricer)
    value_map = q.build_value_map(
        pricer_or_curve=pricer,
        package=package,
        risk_weights=weights,
    )

    assert float(value_map.apply(IRSwapValue.CVX_ADJ_EMPIRICAL)) == pytest.approx(20.0)


def test_timeseries_builder_generic_irs_route_supports_empirical_convexity_adjustment():
    from MDP.STIRConvexityAdjustment.STIRConvexityAdjustmentMDP import STIRConvexityAdjustmentMDP

    mdp = STIRConvexityAdjustmentMDP(
        _mdp_a=_EmpiricalCurveMDP(source="STIRT", fair_rate=0.0400),
        _mdp_b=_EmpiricalCurveMDP(source="ERIS", fair_rate=0.0380),
    )
    tb = TimeseriesBuilder()

    q = IRSwapQuery(
        curve="USD-SOFR-1D",
        tenor="5Y",
        value=IRSwapValue.CVX_ADJ_EMPIRICAL,
    )

    out = tb.get_timeseries(
        start=datetime.date(2026, 3, 12),
        end=datetime.date(2026, 3, 13),
        queries=[q],
        mdps={"IRS": mdp},
    )

    assert list(out.columns) == [q.col_name()]
    assert out[q.col_name()].tolist() == pytest.approx([20.0, 20.0])

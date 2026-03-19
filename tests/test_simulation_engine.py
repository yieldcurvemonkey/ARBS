import datetime

import pytest

from Query.Base.bachelier import bachelier_greeks_fd, bachelier_price
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import (
    QLSTIRFutureOptionPricable,
    QLSTIRFutureOptionPricer,
)
from Simulation.engine import SimulationEngine
from Simulation.extractors import BachelierExtractor
from Simulation.grid import ScenarioGrid
from Simulation.scenarios import TimeDecay, UnderlyingShift


def _make_pricer(
    *,
    forward: float = 95.75,
    strike: float = 95.75,
    iv_normal: float = 0.0050,
    right: str = "C",
    tte_days: int = 90,
) -> QLSTIRFutureOptionPricer:
    ts = datetime.datetime(2026, 3, 16, 17, 0)
    expiry = (ts + datetime.timedelta(days=tte_days)).date()
    discount = 0.998
    tte = tte_days / 365.0
    price = bachelier_price(right, strike, forward, iv_normal, tte, discount)
    return QLSTIRFutureOptionPricer(
        symbol=f"SFR{right}{int(strike * 100)}",
        right=right,
        underlying_symbol="SFRM6",
        strike=strike,
        quote_timestamp=ts,
        expiry_date=expiry,
        market_price=price,
        model_price=price,
        iv_normal=iv_normal,
        delta=0.5,
        gamma=100.0,
        vega=0.01,
        theta=-0.001,
        forward=forward,
        discount=discount,
    )


def _make_leg(pricer: QLSTIRFutureOptionPricer) -> QLSTIRFutureOptionPricable:
    return pricer.build_pricable(quantity=1.0)


def _straddle_pricers() -> dict[str, list[QLSTIRFutureOptionPricer]]:
    call_pricer = _make_pricer(right="C", strike=95.75)
    put_pricer = _make_pricer(right="P", strike=95.75)
    return {
        call_pricer.symbol(): [call_pricer],
        put_pricer.symbol(): [put_pricer],
    }


def _straddle_package(pricers: dict[str, list[QLSTIRFutureOptionPricer]]) -> list[QLSTIRFutureOptionPricable]:
    call_symbol, put_symbol = list(pricers.keys())
    return [
        pricers[call_symbol][0].build_pricable(quantity=1.0),
        pricers[put_symbol][0].build_pricable(quantity=1.0),
    ]


class TestSimulationEngine1D:
    def test_underlying_shift_grid(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(axes=[(UnderlyingShift, "shift", [-1.0, 0.0, 1.0])])

        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): [pricer]},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )

        assert result.data.shape == (3, 1)
        base_price = bachelier_price("C", 95.75, 95.75, 0.005, 90.0 / 365.0, 0.998)
        assert result.data[1, 0] == pytest.approx(base_price, rel=1e-6)
        assert result.data[2, 0] > result.data[1, 0]
        assert result.data[0, 0] < result.data[1, 0]

    def test_pnl_with_entry_cost(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        base_price = bachelier_price("C", 95.75, 95.75, 0.005, 90.0 / 365.0, 0.998)
        grid = ScenarioGrid(axes=[(UnderlyingShift, "shift", [0.0])])

        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): [pricer]},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["pnl"],
            entry_cost=base_price,
        )

        assert result.data[0, 0] == pytest.approx(0.0, abs=1e-10)


class TestSimulationEngine2D:
    def test_shift_x_time_grid(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(
            axes=[
                (UnderlyingShift, "shift", [-1.0, 0.0, 1.0]),
                (TimeDecay, "days", [0, 30]),
            ]
        )

        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): [pricer]},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )

        assert result.data.shape == (3, 2, 1)
        assert result.data[1, 1, 0] < result.data[1, 0, 0]


class TestSimulationEngineStraddle:
    def test_straddle_symmetry_at_t0(self):
        pricers = _straddle_pricers()
        package = _straddle_package(pricers)
        grid = ScenarioGrid(axes=[(UnderlyingShift, "shift", [-1.0, 0.0, 1.0])])

        result = SimulationEngine.evaluate(
            pricer=pricers,
            package=package,
            risk_weights=[1.0, 1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )

        assert result.data[0, 0] == pytest.approx(result.data[2, 0], rel=1e-4)

    def test_straddle_time_decay(self):
        pricers = _straddle_pricers()
        package = _straddle_package(pricers)
        grid = ScenarioGrid(axes=[(TimeDecay, "days", [0, 30, 60])])

        result = SimulationEngine.evaluate(
            pricer=pricers,
            package=package,
            risk_weights=[1.0, 1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )

        assert result.data[0, 0] > result.data[1, 0] > result.data[2, 0]

    def test_straddle_expiry_atm_payoff_is_zero(self):
        pricers = _straddle_pricers()
        package = _straddle_package(pricers)
        days_to_expiry = (package[0].expiry_date() - package[0].quote_timestamp().date()).days
        grid = ScenarioGrid(
            axes=[
                (UnderlyingShift, "shift", [0.0]),
                (TimeDecay, "days", [days_to_expiry]),
            ]
        )

        result = SimulationEngine.evaluate(
            pricer=pricers,
            package=package,
            risk_weights=[1.0, 1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )

        assert result.data[0, 0, 0] == pytest.approx(0.0, abs=1e-12)


class TestSimulationEngineGreeks:
    def test_greeks_match_bachelier_helper(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(axes=[(UnderlyingShift, "shift", [0.0])])

        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): [pricer]},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["delta", "gamma", "vega", "theta"],
        )

        expected = bachelier_greeks_fd(
            right="C",
            strike=95.75,
            forward=95.75,
            vol_normal=0.0050,
            tte=90.0 / 365.0,
            discount=0.998,
        )
        assert result.data[0, 0] == pytest.approx(expected[0], rel=1e-8)
        assert result.data[0, 1] == pytest.approx(expected[1], rel=1e-8)
        assert result.data[0, 2] == pytest.approx(expected[2], rel=1e-8)
        assert result.data[0, 3] == pytest.approx(expected[3], rel=1e-8)


class TestSimulationResult:
    def test_to_dataframe_2d(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(
            axes=[
                (UnderlyingShift, "shift", [-1.0, 0.0, 1.0]),
                (TimeDecay, "days", [0, 30]),
            ]
        )

        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): [pricer]},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )

        df = result.to_dataframe("npv")
        assert df.shape == (3, 2)
        assert list(df.index) == [-1.0, 0.0, 1.0]
        assert list(df.columns) == [0, 30]

    def test_to_dataframe_1d(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(axes=[(UnderlyingShift, "shift", [-1.0, 0.0, 1.0])])

        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): [pricer]},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )

        df = result.to_dataframe("npv")
        assert df.shape == (3, 1)

    def test_to_dataframe_default_metric(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(axes=[(UnderlyingShift, "shift", [0.0])])

        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): [pricer]},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )

        assert result.to_dataframe() is not None

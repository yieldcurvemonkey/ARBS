import datetime

import pytest

from Query.Base.bachelier import bachelier_price
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from Query.STIRFutureOptions.STIRFutureOptionStructure import STIRFutureOptionStructure
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import QLSTIRFutureOptionPricer
from Simulation import ScenarioGrid, TimeDecay, UnderlyingShift, simulate_package


def _mock_straddle_pricer() -> dict[str, list[QLSTIRFutureOptionPricer]]:
    ts = datetime.datetime(2026, 3, 16, 17, 0)
    expiry = datetime.date(2026, 6, 15)
    forward = 95.75
    strike = 95.75
    iv_normal = 0.005
    discount = 0.998
    tte = (expiry - ts.date()).days / 365.0

    def _make(right: str) -> QLSTIRFutureOptionPricer:
        price = bachelier_price(right, strike, forward, iv_normal, tte, discount)
        symbol = f"SFRM6|9575{right}"
        return QLSTIRFutureOptionPricer(
            symbol=symbol,
            right=right,
            underlying_symbol="SFRM6",
            strike=strike,
            quote_timestamp=ts,
            expiry_date=expiry,
            market_price=price,
            model_price=price,
            iv_normal=iv_normal,
            delta=0.5 if right == "C" else -0.5,
            gamma=100.0,
            vega=0.01,
            theta=-0.001,
            forward=forward,
            discount=discount,
        )

    call_pricer = _make("C")
    put_pricer = _make("P")
    return {
        call_pricer.symbol(): [call_pricer],
        put_pricer.symbol(): [put_pricer],
    }


class TestSimulatePackageIntegration:
    def test_straddle_expected_return_grid(self):
        pricer = _mock_straddle_pricer()
        query = STIRFutureOptionQuery(
            structure=STIRFutureOptionStructure.STRADDLE,
            structure_kwargs={
                "call_symbol": "SFRM6|9575C",
                "put_symbol": "SFRM6|9575P",
            },
            contracts=1,
        )
        grid = ScenarioGrid(
            axes=[
                (UnderlyingShift, "shift", [-1.0, -0.5, 0.0, 0.5, 1.0]),
                (TimeDecay, "days", [0, 30, 60]),
            ]
        )

        result = simulate_package(
            query=query,
            pricer=pricer,
            grid=grid,
            include_pnl=True,
        )

        assert result.data.shape == (5, 3, 1)
        assert result.metrics == ["pnl"]

        df = result.to_dataframe("pnl")
        assert df.shape == (5, 3)
        assert df.loc[0.0, 0] == pytest.approx(0.0, abs=1e-6)
        assert df.loc[0.0, 30] < df.loc[0.0, 0]
        assert df.loc[0.0, 60] < df.loc[0.0, 30]
        assert df.loc[-1.0, 0] == pytest.approx(df.loc[1.0, 0], rel=1e-3)

    def test_contract_sizing_uses_package_entry_cost(self):
        pricer = _mock_straddle_pricer()
        query = STIRFutureOptionQuery(
            structure=STIRFutureOptionStructure.STRADDLE,
            structure_kwargs={
                "call_symbol": "SFRM6|9575C",
                "put_symbol": "SFRM6|9575P",
            },
            contracts=3,
        )
        grid = ScenarioGrid(axes=[(UnderlyingShift, "shift", [0.0])])

        result = simulate_package(
            query=query,
            pricer=pricer,
            grid=grid,
            include_pnl=True,
        )

        assert result.data[0, 0] == pytest.approx(0.0, abs=1e-6)

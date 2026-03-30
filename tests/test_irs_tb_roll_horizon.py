import datetime as dt

import pytest

from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from TB.IRSwapsTB import _build_row_for_query
from tests.test_arbitrary_pricing_propagation import _IRCurveStub


class _RollCurveStub(_IRCurveStub):
    def __init__(self):
        self.seen_horizons = []

    def roll_bps_running(self, instrument, horizon: str) -> float:
        _ = instrument
        self.seen_horizons.append(horizon)
        if str(horizon).lower() != "3m":
            raise AssertionError(f"unexpected horizon: {horizon!r}")
        return 12.5


def test_irs_tb_forwards_structure_horizon_to_roll_value_map():
    curve = _RollCurveStub()
    query = IRSwapQuery(
        curve="USD-SOFR-1D",
        tenor="1Y1Y",
        value=IRSwapValue.ROLL_BPS_RUNNING,
        structure_kwargs={"horizon": "3m"},
    )
    ref_dt = dt.date(2025, 1, 2)

    row = _build_row_for_query(curve, query, ref_dt, "Date")

    assert row == (ref_dt, query.col_name(curve.id()), pytest.approx(12.5))
    assert curve.seen_horizons == ["3m"]

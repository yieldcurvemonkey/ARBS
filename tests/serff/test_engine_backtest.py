"""Engine-path replay: QueryDrivenBacktest + STIRFutureQuery legs (offline).

Uses a mock MDP serving REAL RLSTIRFuturePricer objects at scripted prices,
so the actual Query/STIRFutures value maps, rateslib specs and the
STIRFutureHandler MTM path are exercised -- in particular:

- $25/bp (SR3, usd_stir) vs $41.67/bp (ZQ, usd_stir1) multipliers,
- the short convention (positive contracts + risk_weights=[-1]) does NOT
  double-flip sign,
- unwind fees hit realized P&L.
"""

import datetime

import pandas as pd
import pytest

from BT.serff.config import SerffTradeConfig
from BT.serff.engine_backtest import run_serff_engine_backtest
from BT.serff.mechanics import contract_window


class _ScriptedSTIRMDP:
    """Serves RLSTIRFuturePricer at prices from a wide (date x symbol) panel."""

    source = "BARCHART_STIRF-RL"

    def __init__(self, settles: pd.DataFrame):
        self._settles = settles

    def get_pricer(self, request):
        from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import RLSTIRFuturePricer

        ts = request["timestamp"]
        d = ts if isinstance(ts, datetime.date) and not isinstance(ts, datetime.datetime) else ts.date()
        out = {}
        for sym in request["symbols"]:
            px = float(self._settles.at[pd.Timestamp(d), sym])
            w = contract_window(sym)
            curve = "USD-SOFR-1D" if sym.startswith("SR3") else "USD-FEDFUNDS"
            out[sym] = [
                RLSTIRFuturePricer(
                    rl_stirf_id=sym,
                    reference_date=d,
                    effective_date=w.start,
                    maturity_date=w.end,
                    curve=curve,
                    price=px,
                    rate=100.0 - px,
                    contracts=1,
                    notional=1_000_000,
                    meta_data={"symbol": sym},
                )
            ]
        return out


@pytest.fixture()
def scripted_world():
    dates = pd.DatetimeIndex([datetime.datetime(2026, 5, 4), datetime.datetime(2026, 5, 5), datetime.datetime(2026, 5, 6)])
    settles = pd.DataFrame(
        {
            "SR3M26": [96.00, 96.01, 96.02],   # +2bp over the window
            "ZQN26": [96.10, 96.10, 96.11],    # +1bp
        },
        index=dates,
    )
    trades = pd.DataFrame(
        [
            {
                "entry_date": datetime.date(2026, 5, 4),
                "exit_date": datetime.date(2026, 5, 6),
                "sr3_symbol": "SR3M26",
                "direction": 1,
                "units": 1,
                "sr3_contracts": 5.0,               # long 5 SR3
                "zq_contracts": {"ZQN26": -1.0},    # short 1 ZQ
                "entry_cost": 10.0,
                "exit_cost": 10.0,
            }
        ]
    )
    return settles, trades


class TestEngineReplay:
    def test_signs_multipliers_and_fees(self, scripted_world):
        settles, trades = scripted_world
        res = run_serff_engine_backtest(
            trades,
            settles,
            trade_cfg=SerffTradeConfig(),
            unit_scale=1,
            mdp=_ScriptedSTIRMDP(settles),
            show_progress=False,
        )
        # long 5 SR3 x $25/bp x +2bp = +250 ; short 1 ZQ x $41.67/bp x +1bp = -41.67
        # fees (entry+exit) x unit_scale = -20 applied at unwind
        expected_gross = 5 * 25.0 * 2 - 1 * 41.67 * 1
        assert res.mtm.iloc[0] == pytest.approx(0.0, abs=1e-9)
        assert res.mtm.iloc[-1] == pytest.approx(expected_gross - 20.0, abs=0.01)
        assert res.summary["n_trades_replayed"] == 1
        assert res.summary["max_hedge_rounding_err_contracts_per_unit"] == 0.0

    def test_short_structure_flips_sign(self, scripted_world):
        settles, trades = scripted_world
        trades = trades.copy()
        trades.at[0, "sr3_contracts"] = -5.0
        trades.at[0, "zq_contracts"] = {"ZQN26": 1.0}
        trades.at[0, "entry_cost"] = 0.0
        trades.at[0, "exit_cost"] = 0.0
        res = run_serff_engine_backtest(
            trades,
            settles,
            unit_scale=1,
            mdp=_ScriptedSTIRMDP(settles),
            show_progress=False,
        )
        expected = -(5 * 25.0 * 2) + 1 * 41.67 * 1
        assert res.mtm.iloc[-1] == pytest.approx(expected, abs=0.01)

    def test_unit_scale_rounds_stub_hedges(self, scripted_world):
        settles, trades = scripted_world
        trades = trades.copy()
        trades.at[0, "zq_contracts"] = {"ZQN26": -0.4667}
        res = run_serff_engine_backtest(
            trades,
            settles,
            unit_scale=30,
            mdp=_ScriptedSTIRMDP(settles),
            show_progress=False,
        )
        # 0.4667 x 30 = 14.001 -> 14 contracts; error ~ 0.001/30
        assert res.summary["max_hedge_rounding_err_contracts_per_unit"] < 0.001
        # per-unit MTM ~ scale-invariant: 5x25x2 - 0.4667x41.67x1 - fees(20)
        approx = 5 * 25 * 2 - 0.4667 * 41.67 - 20.0
        assert res.mtm_per_unit.iloc[-1] == pytest.approx(approx, abs=0.15)

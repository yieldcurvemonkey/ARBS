import datetime
from dataclasses import dataclass

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import Trigger, TriggerRequirements
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue


@dataclass
class _BulkInstrument:
    tenor: str
    bpv: float


class _BulkCurvePricer:
    def __init__(self, curve_name: str, timestamp: datetime.datetime, rates_by_timestamp: dict[datetime.datetime, float]):
        self.curve_name = curve_name
        self.timestamp = timestamp
        self.rates_by_timestamp = rates_by_timestamp

    def id(self) -> str:
        return self.curve_name

    def handle(self):
        return self

    def reference_date(self):
        return self.timestamp.date()

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
        return _BulkInstrument(tenor=tenor or "IMM_4xIMM_5", bpv=float(bpv or 0.0))

    def fair_rate(self, instrument):
        _ = instrument
        return self.rates_by_timestamp[self.timestamp]

    def npv(self, instrument):
        return -float(instrument.bpv) * self.rates_by_timestamp[self.timestamp] * 100.0

    def pv01(self, instrument):
        return float(instrument.bpv)

    def analytic_delta(self, instrument):
        return float(instrument.bpv)

    def resolve_pricable(self, pricable, risk_weight=1.0):
        _ = risk_weight
        return pricable


class _BulkOnlyIRSMDP:
    def __init__(self, rates_by_timestamp: dict[datetime.datetime, float]):
        self.source = "BARCHART_STIRF-RL"
        self.rates_by_timestamp = rates_by_timestamp
        self.bulk_requests = []
        self.get_pricer_calls = 0

    def _supports_curve_store_raw_curve_fast_path(self):
        return True

    def bulk_get_data(self, request):
        self.bulk_requests.append(dict(request))
        return {
            timestamp: _BulkCurvePricer(
                curve_name=request["curve_name"],
                timestamp=timestamp,
                rates_by_timestamp=self.rates_by_timestamp,
            )
            for timestamp in request.get("timestamps", [])
        }

    def get_pricer(self, request):
        self.get_pricer_calls += 1
        raise AssertionError("QueryDrivenBacktest should serve supported IRS requests from the prefetched cache")


class _FirstStepOnlyRequirements(TriggerRequirements):
    def __init__(self, first_state: datetime.datetime):
        self.first_state = first_state

    def has_triggered(self, state, backtest=None):
        _ = backtest
        from BT.event import TriggerInfo

        return TriggerInfo(state == self.first_state)


def test_query_engine_prefetches_bulk_irs_pricers_for_entire_time_grid():
    states = [
        datetime.datetime(2026, 3, 2, 18, 0, tzinfo=datetime.timezone.utc),
        datetime.datetime(2026, 3, 2, 18, 5, tzinfo=datetime.timezone.utc),
        datetime.datetime(2026, 3, 2, 18, 10, tzinfo=datetime.timezone.utc),
    ]
    rates = {
        states[0]: 4.01,
        states[1]: 4.02,
        states[2]: 4.03,
    }
    mdp = _BulkOnlyIRSMDP(rates)
    query = IRSwapQuery(
        curve="USD-SOFR-1D-Q12STIRT",
        tenor="IMM_4xIMM_5",
        value=IRSwapValue.NPV,
        structure_kwargs={"bpv": 100_000.0},
        market_request={"timestamp": "now"},
    )
    trigger = Trigger(
        trigger_requirements=_FirstStepOnlyRequirements(states[0]),
        actions=[AddQueryAction(query=query)],
    )
    backtest = QueryDrivenBacktest(
        time_grid=TimeGrid(states),
        strategy=QueryStrategy(name="bulk-prefetch", triggers=[trigger]),
        mdp=mdp,
        show_progress=False,
    )

    backtest.run()

    assert len(mdp.bulk_requests) == 1
    assert mdp.bulk_requests[0]["curve_name"] == "USD-SOFR-1D-Q12STIRT"
    assert mdp.bulk_requests[0]["timestamps"] == states
    assert mdp.get_pricer_calls == 0
    assert len(backtest.mtm_history) == len(states)

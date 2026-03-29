import datetime as dt
from dataclasses import replace

import pandas as pd

from BT.flow_alpha.builder import FlowAlphaStrategySpec, build_query_strategy
from BT.flow_alpha.rates import (
    TreasuryAuctionEventSource,
    corporate_issuance_rate_lock_spec,
    pre_auction_concession_spec,
    rate_move_state_signal_spec,
)
from BT.flow_alpha.sources import BusinessPeriodEventSource
from BT.flow_alpha.window_rules import NextPeriodBusinessDayWindowRule
from BT.query_engine import QueryDrivenBacktest
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue


def test_builder_runs_scheduled_month_end_strategy_with_query_backtest(mock_mdp):
    source = BusinessPeriodEventSource(
        family="month_end_receive",
        period="month",
        asset_class="RATES",
        direction_hint="RECEIVE_FIXED",
        instrument_scope="IRS",
    )
    spec = FlowAlphaStrategySpec(
        name="IRS Month End",
        source=source,
        window_rule=NextPeriodBusinessDayWindowRule(entry_offset_business_days=-2, next_period="month", exit_business_day=1),
        query_factory=lambda event, **_: IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.NPV,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 100_000.0},
            tags=(event.event_id,),
        ),
    )
    strategy, events, time_grid = build_query_strategy(spec, dt.date(2025, 1, 1), dt.date(2025, 2, 28))

    assert len(events) == 1
    bt = QueryDrivenBacktest(time_grid=time_grid, mdp=mock_mdp, strategy=strategy, show_progress=False)
    bt.run()

    assert len(bt.portfolio.orders_log) == 1
    assert len(list(bt.portfolio.iter_positions())) == 0
    assert len(bt.mtm_history) == len(list(time_grid))


def test_pre_auction_concession_strategy_builds_and_unwinds(mock_mdp):
    ref_df = pd.DataFrame(
        [
            {
                "cusip": "CT10A",
                "oi": "10-Year",
                "auction_date": dt.date(2025, 1, 15),
                "issue_date": dt.date(2025, 1, 17),
                "cpn": 4.25,
            }
        ]
    )
    spec = pre_auction_concession_spec()
    spec = replace(
        spec,
        source=TreasuryAuctionEventSource(
            families=("pre_auction_concession",),
            refdata_loader=lambda **_: ref_df.copy(),
        ),
    )

    strategy, events, time_grid = build_query_strategy(spec, dt.date(2025, 1, 1), dt.date(2025, 1, 31))
    bt = QueryDrivenBacktest(time_grid=time_grid, mdp=mock_mdp, strategy=strategy, show_progress=False)
    bt.run()

    assert [event.family for event in events] == ["pre_auction_concession"]
    assert len(bt.portfolio.orders_log) == 1
    assert len(list(bt.portfolio.iter_positions())) == 0


def test_corporate_issuance_strategy_uses_composite_public_and_sdr_events(mock_mdp):
    public_records = pd.DataFrame(
        [
            {
                "issuer_name": "Example Corp",
                "issuer_id": "EXM",
                "pricing_date": dt.date(2025, 1, 7),
                "settlement_date": dt.date(2025, 1, 9),
                "deal_currency": "USD",
                "deal_size": 500_000_000.0,
                "maturity_bucket": "10Y",
                "source_evidence": "8-K launch",
            }
        ]
    )
    sdr_swaps = pd.DataFrame(
        [
            {
                "execution_timestamp": "2025-01-06T15:00:00Z",
                "tenor_years": 10.0,
                "risk": 150_000_000.0,
                "direction": "PAY_FIXED",
            }
        ]
    )
    spec = corporate_issuance_rate_lock_spec(public_records=public_records, sdr_swaps=sdr_swaps)
    strategy, events, time_grid = build_query_strategy(
        spec,
        dt.date(2025, 1, 1),
        dt.date(2025, 1, 31),
        emit_generic_clusters=False,
    )
    bt = QueryDrivenBacktest(time_grid=time_grid, mdp=mock_mdp, strategy=strategy, show_progress=False)
    bt.run()

    assert any(event.source == "PUBLIC_PLUS_SDR" for event in events)
    assert len(bt.portfolio.orders_log) == 1
    assert len(list(bt.portfolio.iter_positions())) == 0


def test_state_signal_strategy_opens_and_unwinds(mock_mdp):
    values = {
        dt.date(2025, 1, 6): 100.0,
        dt.date(2025, 1, 7): 104.0,
        dt.date(2025, 1, 8): 104.5,
        dt.date(2025, 1, 9): 104.6,
    }

    def fetch(ts: dt.datetime):
        return values.get(ts.date())

    spec = rate_move_state_signal_spec(fetch=fetch, entry_threshold=3.0, exit_threshold=1.0)
    strategy, _, time_grid = build_query_strategy(spec, dt.date(2025, 1, 6), dt.date(2025, 1, 9))
    bt = QueryDrivenBacktest(time_grid=time_grid, mdp=mock_mdp, strategy=strategy, show_progress=False)
    bt.run()

    assert len(bt.portfolio.orders_log) == 1
    assert len(list(bt.portfolio.iter_positions())) == 0

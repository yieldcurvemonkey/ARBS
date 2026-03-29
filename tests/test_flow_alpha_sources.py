import datetime as dt

import pandas as pd
import QuantLib as ql

from BT.flow_alpha.builder import FlowAlphaStrategySpec, build_query_strategy
from BT.flow_alpha.rates import (
    CorporateIssuanceEventSource,
    CorporateIssuancePublicSource,
    SDRHedgeInferenceEventSource,
    TreasuryAuctionEventSource,
    TreasuryCouponReinvestmentEventSource,
    month_end_duration_extension_spec,
)
from BT.flow_alpha.window_rules import AnchorDateWindowRule, NextPeriodBusinessDayWindowRule
from BT.misc import _last_business_day_of_month, _month_iter, _n_business_days_before, _nth_business_day_of_month


def test_window_rules_materialize_expected_business_dates():
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    event = TreasuryAuctionEventSource(families=("pre_auction_concession",)).fetch(
        dt.date(2025, 1, 1),
        dt.date(2025, 1, 31),
        ref_df=pd.DataFrame(
            [
                {
                    "cusip": "CT10A",
                    "oi": "10-Year",
                    "auction_date": dt.date(2025, 1, 31),
                    "issue_date": dt.date(2025, 2, 3),
                    "cpn": 4.0,
                }
            ]
        ),
    )[0]

    anchor_rule = AnchorDateWindowRule(entry_offset_business_days=-2, exit_offset_business_days=1)
    next_rule = NextPeriodBusinessDayWindowRule(entry_offset_business_days=-3, next_period="month", exit_business_day=1)

    anchored = anchor_rule.apply(event, calendar=cal)
    rolled = next_rule.apply(event, calendar=cal)

    assert anchored.entry_date == dt.date(2025, 1, 29)
    assert anchored.exit_date == dt.date(2025, 2, 3)
    assert rolled.entry_date == dt.date(2025, 1, 28)
    assert rolled.exit_date == dt.date(2025, 2, 3)


def test_month_end_spec_matches_manual_cycle_generation():
    spec = month_end_duration_extension_spec(days_pre_month_end=3, days_after_month_end=1)
    start = dt.date(2025, 1, 1)
    end = dt.date(2025, 3, 31)
    strategy, events, _ = build_query_strategy(spec, start, end)
    _ = strategy

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    expected = []
    for y, m in _month_iter(start, end):
        eom_bd = _last_business_day_of_month(cal, y, m)
        entry = _n_business_days_before(cal, eom_bd, 3)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        exit_ = _nth_business_day_of_month(cal, ny, nm, 1)
        if entry < start or exit_ > end:
            continue
        expected.append((entry, exit_))

    assert [(event.entry_date, event.exit_date) for event in events] == expected


def test_treasury_auction_source_normalizes_event_families():
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
    source = TreasuryAuctionEventSource()
    events = source.fetch(dt.date(2025, 1, 1), dt.date(2025, 1, 31), ref_df=ref_df)

    assert {event.family for event in events} == {"pre_auction_concession", "post_auction_squeeze", "wi_otr_basis"}
    assert all(event.payload["cusip"] == "CT10A" for event in events)
    assert all(event.payload["security_term"] == "10-Year" for event in events)


def test_coupon_reinvestment_source_aggregates_coupon_proxy():
    ref_df = pd.DataFrame(
        [
            {"cusip": "AAA", "oi": "10-Year", "maturity_date": dt.date(2035, 2, 15), "cpn": 4.0},
            {"cusip": "BBB", "oi": "5-Year", "maturity_date": dt.date(2030, 2, 15), "cpn": 2.0},
        ]
    )
    source = TreasuryCouponReinvestmentEventSource()
    events = source.fetch(dt.date(2025, 2, 1), dt.date(2025, 2, 28), ref_df=ref_df)

    assert len(events) == 1
    event = events[0]
    assert event.anchor_date == dt.date(2025, 2, 15)
    assert event.payload["coupon_proxy"] == 3.0
    assert event.payload["size_bucket"] == "SMALL"
    assert sorted(event.payload["cusips"]) == ["AAA", "BBB"]


def test_corporate_public_source_normalizes_common_aliases():
    records = pd.DataFrame(
        [
            {
                "issuer": "Example Corp",
                "ticker": "EXM",
                "announce_date": dt.date(2025, 1, 6),
                "price_date": dt.date(2025, 1, 7),
                "close_date": dt.date(2025, 1, 9),
                "currency": "USD",
                "deal_amount": "750mm",
                "maturity": "10Y",
                "headline": "Example Corp launches 10Y deal",
                "source_type": "press_release",
            }
        ]
    )
    source = CorporateIssuancePublicSource(records=records)
    events = source.fetch(dt.date(2025, 1, 1), dt.date(2025, 1, 31))

    assert len(events) == 1
    event = events[0]
    assert event.source == "PRESS_RELEASE"
    assert event.payload["issuer_name"] == "Example Corp"
    assert event.payload["issuer_id"] == "EXM"
    assert event.payload["deal_currency"] == "USD"
    assert event.payload["deal_size"] == 750_000_000.0
    assert event.payload["maturity_bucket"] == "7-12Y"


def test_sdr_inference_matches_public_events_and_preserves_generic_clusters():
    public_source = CorporateIssuancePublicSource(
        records=pd.DataFrame(
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
    )
    sdr_source = SDRHedgeInferenceEventSource(
        swaps=pd.DataFrame(
            [
                {
                    "execution_timestamp": "2025-01-06T14:00:00Z",
                    "tenor_years": 10.0,
                    "risk": 150_000_000.0,
                    "direction": "PAY_FIXED",
                }
            ]
        ),
        min_notional_proxy=100_000_000.0,
    )
    public_events = public_source.materialize(dt.date(2025, 1, 1), dt.date(2025, 1, 31))
    events = sdr_source.fetch(dt.date(2025, 1, 1), dt.date(2025, 1, 31), public_events=public_events, emit_generic_clusters=True)

    assert any(event.source == "PUBLIC_PLUS_SDR" for event in events)
    assert any(event.source == "SDR_INFERRED" for event in events)


def test_corporate_issuance_source_merges_public_and_sdr_views():
    source = CorporateIssuanceEventSource(
        public_source=CorporateIssuancePublicSource(
            records=pd.DataFrame(
                [
                    {
                        "issuer_name": "Matched Corp",
                        "issuer_id": "MTC",
                        "pricing_date": dt.date(2025, 1, 7),
                        "settlement_date": dt.date(2025, 1, 9),
                        "maturity_bucket": "10Y",
                    },
                    {
                        "issuer_name": "Public Only",
                        "issuer_id": "PUB",
                        "pricing_date": dt.date(2025, 1, 8),
                        "settlement_date": dt.date(2025, 1, 10),
                        "maturity_bucket": "5Y",
                    },
                ]
            )
        ),
        sdr_source=SDRHedgeInferenceEventSource(
            swaps=pd.DataFrame(
                [
                    {
                        "execution_timestamp": "2025-01-06T14:00:00Z",
                        "tenor_years": 10.0,
                        "risk": 150_000_000.0,
                        "direction": "PAY_FIXED",
                    }
                ]
            ),
            min_notional_proxy=100_000_000.0,
        ),
    )

    events = source.fetch(dt.date(2025, 1, 1), dt.date(2025, 1, 31), emit_generic_clusters=False)

    assert any(event.source == "PUBLIC_PLUS_SDR" for event in events)
    assert any(event.payload.get("issuer_id") == "PUB" for event in events)

"""Curve-anchor rolling for weekend/holiday intraday timestamps.

The STIRF curve's first node is its RFR valuation anchor. rateslib needs continuous
RFR coverage from the last realized SOFR fixing into the curve; if the anchor lands on
a non-business day (weekend/holiday) it sits *after* the last fixing and the front SR1
future fails to price:

    ValueError: RFRs could not be calculated ... does the `Curve` begin after the start
    of a `FloatPeriod` ...

This was the sole blocker for backfilling holiday-adjacent overnight sessions
(e.g. trade-date 2026-06-01's Sunday-night Globex block on 2026-05-31, and 2026-05-26's
Memorial-Day overnight on 2026-05-25). The anchor must roll back to the last business day;
weekday anchors must be untouched. Pure function -- no network, no calibration.
"""

import datetime

import pytz

from MDP.IRSwaps.BARCHART_STIRF.rl import _build_stirf_nodes
from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES

CHI = pytz.timezone("America/Chicago")
REF = "USD-FEDFUNDS"  # nyc calendar for the MIX23 curve


def _anchor_date(ts: datetime.datetime) -> datetime.date:
    nodes = _build_stirf_nodes(
        timestamp=ts,
        pricers={},
        central_bank_dates=_CENTRAL_BANK_DATES,
        reference_key=REF,
        max_tenor_from_timestamp_months=12,
        initial_nodes=None,
    )
    return min(nodes.keys()).date()


def test_sunday_timestamp_anchors_to_prior_friday():
    """2026-05-31 (Sunday) -> anchor rolls back to 2026-05-29 (Friday)."""
    ts = CHI.localize(datetime.datetime(2026, 5, 31, 20, 0))
    assert _anchor_date(ts) == datetime.date(2026, 5, 29)


def test_holiday_timestamp_anchors_to_last_business_day():
    """2026-05-25 (Memorial Day) -> anchor rolls back to 2026-05-22 (Friday)."""
    ts = CHI.localize(datetime.datetime(2026, 5, 25, 20, 0))
    assert _anchor_date(ts) == datetime.date(2026, 5, 22)


def test_weekday_timestamp_anchor_unchanged():
    """A normal business-day timestamp must keep its own date as the anchor."""
    ts = CHI.localize(datetime.datetime(2026, 5, 28, 20, 0))
    assert _anchor_date(ts) == datetime.date(2026, 5, 28)


def test_saturday_timestamp_anchors_to_prior_friday():
    ts = CHI.localize(datetime.datetime(2026, 5, 30, 12, 0))
    assert _anchor_date(ts) == datetime.date(2026, 5, 29)


def test_anchor_is_the_minimum_node_and_nodes_stay_sorted():
    """Rolling the anchor must not disturb ordering or later nodes."""
    ts = CHI.localize(datetime.datetime(2026, 5, 31, 20, 0))
    nodes = _build_stirf_nodes(
        timestamp=ts,
        pricers={},
        central_bank_dates=_CENTRAL_BANK_DATES,
        reference_key=REF,
        max_tenor_from_timestamp_months=12,
        initial_nodes=None,
    )
    keys = list(nodes.keys())
    assert keys == sorted(keys)
    assert min(keys).date() == datetime.date(2026, 5, 29)
    # every later node is strictly after the anchor
    assert all(k > keys[0] for k in keys[1:])

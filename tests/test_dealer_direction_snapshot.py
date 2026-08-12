"""The pricing clock and the snapshot policy.

Both of the bugs pinned here were live in the first draft of `snapshot.py` and
both are silent: they produce a plausible curve at a wrong instant.
"""
from __future__ import annotations

import datetime

import pandas as pd
import pytest

from SDRUtils.dealer_direction import snapshot as snap

CURVE = "USD-SOFR-1D"


def _row(**kw):
    base = {
        "trade_id": "T",
        "lifecycle_type": "NEW_TRADE",
        "execution_timestamp": pd.Timestamp("2026-06-16 14:15:36", tz="UTC"),
        "original_execution_timestamp": pd.Timestamp("2026-06-16 14:15:36", tz="UTC"),
        "event_timestamp": pd.Timestamp("2026-06-16 14:15:36", tz="UTC"),
        "event_timestamp_granularity": "SECOND",
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# The #96-is-frozen trap.
# --------------------------------------------------------------------------

def test_new_trade_prices_on_the_execution_timestamp():
    ts, field = snap.pricing_timestamp(_row())
    assert field == snap.CLOCK_EXECUTION
    assert ts == pd.Timestamp("2026-06-16 14:15:36", tz="UTC")


def test_termination_prices_on_the_event_timestamp_not_the_frozen_execution():
    """Spec Appendix F Example 3, verbatim.

    The TERM-ETRM row carries event timestamp 2019-12-12T14:57:10Z against
    execution timestamp 2018-04-01T14:15:36Z, because #96 "remains unchanged
    throughout the life of the UTI". Pricing at #96 would value the unwind
    against a curve twenty months before the unwind -- and the failure is
    silent, because a 2018 curve prices perfectly well.
    """
    ts, field = snap.pricing_timestamp(_row(
        lifecycle_type="TERMINATION",
        execution_timestamp=pd.Timestamp("2018-04-01 14:15:36", tz="UTC"),
        original_execution_timestamp=pd.Timestamp("2018-04-01 14:15:36", tz="UTC"),
        event_timestamp=pd.Timestamp("2019-12-12 14:57:10", tz="UTC"),
    ))
    assert field == snap.CLOCK_EVENT
    assert ts == pd.Timestamp("2019-12-12 14:57:10", tz="UTC")
    assert (ts - pd.Timestamp("2018-04-01 14:15:36", tz="UTC")).days > 600


def test_unknown_lifecycle_defaults_to_the_event_clock():
    """The safe default.

    #30 is correct for a NEWT row too -- it equals #96 there. The reverse
    default would price an unrecognised lifecycle row against a stale curve.
    """
    _, field = snap.pricing_timestamp(_row(lifecycle_type=None))
    assert field == snap.CLOCK_EVENT


def test_lifecycle_row_with_no_event_timestamp_refuses_rather_than_using_96():
    with pytest.raises(snap.NoPricingInstant):
        snap.pricing_timestamp(_row(lifecycle_type="TERMINATION", event_timestamp=None))


# --------------------------------------------------------------------------
# The date-only event stamp, and its mirror image.
# --------------------------------------------------------------------------

def test_date_only_event_stamp_degrades_to_eod_in_the_reported_frame():
    """Spec footnote 39: report '00:00:00' when the time is unavailable.

    The zero is written in the field's own UTC clock. Converting to New York
    before testing makes this never fire (00:00Z is 19:00 ET) *and*, if it did
    fire, would hand back the previous calendar day -- a whole day of
    lookbehind introduced by a timezone.
    """
    ts, field = snap.pricing_timestamp(_row(
        lifecycle_type="TERMINATION",
        event_timestamp=pd.Timestamp("2019-12-12 00:00:00", tz="UTC"),
        event_timestamp_granularity=None,
    ))
    assert field == snap.CLOCK_EOD_FALLBACK
    assert ts == datetime.date(2019, 12, 12)


def test_an_ordinary_evening_print_is_not_mistaken_for_a_date():
    """20:00 ET IS 00:00:00Z. The granularity column is what separates them."""
    ts, field = snap.pricing_timestamp(_row(
        lifecycle_type="TERMINATION",
        event_timestamp=pd.Timestamp("2026-03-31 20:00:00", tz="America/New_York"),
        event_timestamp_granularity="SECOND",
    ))
    assert field == snap.CLOCK_EVENT
    assert not isinstance(ts, datetime.date) or isinstance(ts, pd.Timestamp)


# --------------------------------------------------------------------------
# The snap itself.
# --------------------------------------------------------------------------

def test_snap_is_the_previous_whole_minute_in_new_york():
    got = snap.snap_instant(pd.Timestamp("2026-06-16 14:15:36", tz="UTC"))
    assert (got.hour, got.minute, got.second) == (10, 14, 0)   # 10:15:36 ET - 1min


def test_snap_never_returns_an_ambiguous_midnight():
    """A print in the 00:01 ET minute floors-and-decrements to exactly midnight,
    which sources that overload the argument read as END OF DAY -- serving that
    day's close, ~16h after the print. That is lookahead, not staleness.
    """
    got = snap.snap_instant(pd.Timestamp("2026-06-16 00:01:30", tz="America/New_York"))
    assert not snap.is_ambiguous_midnight(got)


def test_evening_snap_stays_in_new_york():
    """`is_ambiguous_midnight` tests the wall clock of the object handed to it,
    so normalising to UTC turns an ordinary 20:00 ET snap into midnight and
    trips `CurvePricer`'s guard. Fired for real on 2026-03-31.
    """
    got = snap.snap_instant(pd.Timestamp("2026-03-31 20:01:00", tz="America/New_York"))
    assert str(got.tzinfo).startswith("America/New_York")
    assert not snap.is_ambiguous_midnight(got)


def test_alternative_snaps_are_the_sensitivity_test():
    alts = snap.alternative_snaps(pd.Timestamp("2026-06-16 14:15:36", tz="UTC"))
    assert set(alts) == {5, 30}
    assert alts[5].second == 31 and alts[30].second == 6


def test_a_date_passes_through_both_snap_functions_unchanged():
    d = datetime.date(2026, 6, 16)
    assert snap.snap_instant(d) is d
    assert snap.alternative_snaps(d) == {}


# --------------------------------------------------------------------------
# The session branch. A global tolerance is the wrong shape.
# --------------------------------------------------------------------------

def test_in_session_is_strict_and_out_of_session_is_bounded():
    """Citi publishes nothing 23:00-00:59 ET, so the 00:xx hour needs a bounded
    reach-back or those prints are lost permanently. But the same tolerance
    applied globally admits two-hour staleness at 10:00 on a Tuesday, worth
    2.63 bp at p90 -- and on 2026-06-01 a global 2h bound serves an in-session
    probe from a curve 15 minutes stale where this branch refuses.
    """
    midday = pd.Timestamp("2026-06-16 14:00", tz="America/New_York")
    overnight = pd.Timestamp("2026-06-16 00:35", tz="America/New_York")

    assert snap.in_session(CURVE, midday)
    assert not snap.in_session(CURVE, overnight)

    strict = snap.policy_for(CURVE, midday)
    hole = snap.policy_for(CURVE, overnight)
    assert strict.max_lag == snap.IN_SESSION_MAX_LAG
    assert hole.max_lag == snap.OUT_OF_SESSION_MAX_LAG
    assert strict.max_lag < hole.max_lag


@pytest.mark.parametrize("instant", [
    pd.Timestamp("2026-06-16 14:00", tz="America/New_York"),
    pd.Timestamp("2026-06-16 00:35", tz="America/New_York"),
])
def test_no_policy_ever_allows_a_curve_from_the_future(instant):
    """A curve from after the print contains the print. That is not staleness,
    it is circularity, and it is the one thing this whole exercise exists to
    prevent.
    """
    assert snap.policy_for(CURVE, instant).allow_future is False


def test_lag_telemetry_reads_meta_not_meta_data():
    """`RLIRSwapCurve` exposes `.meta()`. `getattr(h, "meta_data", None)`
    returns None silently, so a whole strict run reports lag=None on every row
    and is otherwise indistinguishable from a correct one -- while the session
    branch is relying on that value.
    """
    class Handle:
        def meta(self):
            return {"snapshot_lag_signed_seconds": 42.0,
                    "snapshot_served_from_future": False}

    assert snap.snapshot_lag_seconds(Handle()) == 42.0
    assert snap.served_from_future(Handle()) is False


def test_lag_telemetry_is_none_rather_than_wrong_when_absent():
    class Bare:
        pass

    assert snap.snapshot_lag_seconds(Bare()) is None


def test_the_citivelo_source_token_is_an_rl_spelling():
    """`_build_citivelo_excel_curve` gates `_store_eligible` on backend == "rl",
    so a -QL token never consults the minute store and a strict policy then
    misses on EVERY request -- indistinguishable from a cold store.
    """
    assert "QL" not in snap.CURVE_SOURCE.upper().replace("QL_EXCEL", "")
    assert snap.CURVE_SOURCE == "CITIVELO_EXCEL"
    assert set(snap.CURVE_FOR) == {"SOFR", "FED_FUNDS"}

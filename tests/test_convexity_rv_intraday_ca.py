r"""Intraday convexity adjustment — the transport, pinned.

A preflight investigation reported that ``IRSwapQuery.build_mdp_request``
"silently date-truncates ``CVX_ADJ``", so an intraday request would return an EOD
number with no error, and concluded that reaching an instant needed a code
change. That is half right and the half that is wrong matters: the truncation is
real **on the default path**, but the Query layer already carries a mechanism for
asking for an instant, and ``CVX_ADJ`` can use it today.

``BaseQuery.build_mdp_request`` injects ``_request_date(now)`` when
``mdp_time_key`` is absent from ``market_request``, and ``_request_datetime(now)``
when it is present with the literal value ``"now"``. So::

    market_request={"timestamp": "now"}

is the supported way to reach an instant, and it is the same sentinel the STIR
futures query uses — where its absence is already recorded in this codebase as
the reason a request came back with EOD zeros.

``CVX_ADJ_EMPIRICAL`` overrides ``build_mdp_request`` to pass a datetime
*unconditionally*, which is why it looked like the only value that could go
intraday. It is not; it is the only one that goes intraday **without being
asked**.

Pinning this matters because the difference is invisible in the result. Both
paths return a number. Only the type of ``request["timestamp"]`` says which
instant it belongs to, and an EOD number silently standing in for a 15:00 one is
exactly the class of error the convexity work has already been bitten by twice.
"""

from __future__ import annotations

import datetime
import os

import pytest

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

NOW = datetime.datetime(2026, 8, 19, 15, 0, 0)
EFF = datetime.date(2026, 9, 16)
MAT = datetime.date(2027, 9, 15)


def _q(value=IRSwapValue.CVX_ADJ, market_request=None) -> IRSwapQuery:
    return IRSwapQuery(
        curve="USD-SOFR-1D", structure=IRSwapStructure.OUTRIGHT, value=value,
        effective_date=EFF, maturity_date=MAT, structure_kwargs={"bpv": 1},
        market_request=market_request,
    )


def test_the_default_path_really_does_truncate_to_a_date():
    """The half of the report that is right, asserted so it stays visible."""
    ts = _q().build_mdp_request(NOW)["timestamp"]
    assert isinstance(ts, datetime.date) and not isinstance(ts, datetime.datetime)
    assert ts == NOW.date()


def test_the_now_sentinel_delivers_the_instant_to_cvx_adj():
    """The half that is wrong: no code change is needed to go intraday."""
    ts = _q(market_request={"timestamp": "now"}).build_mdp_request(NOW)["timestamp"]
    assert isinstance(ts, datetime.datetime), (
        "the 'now' sentinel no longer reaches CVX_ADJ; intraday convexity has "
        "lost its transport"
    )
    assert ts == NOW
    assert ts.hour == 15 and ts.minute == 0


def test_an_explicit_instant_is_passed_through_untouched():
    """A concrete timestamp must not be rewritten to either end of the day."""
    pinned = datetime.datetime(2026, 8, 19, 11, 32)
    ts = _q(market_request={"timestamp": pinned}).build_mdp_request(NOW)["timestamp"]
    assert ts == pinned


def test_empirical_is_the_one_that_goes_intraday_unasked():
    """Why the default looked like the only intraday-capable value."""
    ts = _q(value=IRSwapValue.CVX_ADJ_EMPIRICAL).build_mdp_request(NOW)["timestamp"]
    assert isinstance(ts, datetime.datetime) and ts == NOW


def test_live_survives_every_path():
    """``"live"`` is a literal, not a time, and must not be coerced."""
    for mr in ({"timestamp": "live"},):
        assert _q(market_request=mr).build_mdp_request(NOW)["timestamp"] == "live"
        assert _q(value=IRSwapValue.CVX_ADJ_EMPIRICAL,
                  market_request=mr).build_mdp_request(NOW)["timestamp"] == "live"


def test_the_sentinel_changes_the_cache_fingerprint_not_at_all():
    """``market_request`` is NOT part of ``_query_fingerprint``.

    Worth knowing before an intraday series is cached next to a daily one: the
    fingerprint covers tenor, dates, structure, value, ``structure_kwargs``,
    name, risk weight and ``value_kwargs`` — not ``market_request``. So a daily
    and an intraday query for the same instrument hash **identically**, and only
    the timestamp in the cache key separates them. That is fine for the mapping
    cache, which is keyed by epoch-ns, and is a trap for anything that keys on
    the fingerprint alone.
    """
    from TB.IRSwapsTB import _query_fingerprint

    assert _query_fingerprint(_q()) == _query_fingerprint(
        _q(market_request={"timestamp": "now"})), (
        "market_request has entered the fingerprint; the note in this test is "
        "now wrong and intraday/daily rows no longer collide"
    )

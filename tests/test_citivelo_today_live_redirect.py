"""An intraday request for TODAY must not be answered from yesterday.

The Citi minute store is filled by a post-close batch, so during a session
today's minutes are not in it. The default snapshot policy is
nearest-in-either-direction over a (date, -1, +1) window with no lag bound, and
returns None only when ALL THREE days are empty - so one present neighbour
answers anything. Measured 2026-08-08: a request for 11:00 today came back with
a curve stamped 2026-08-07 14:07, in 2 ms, from cache, no Excel, no warning,
``snapshot_lag_seconds = 75180``.

``_policy_for_current_session`` bounds the lag for today only, which turns that
into a soft miss and lets the existing live MI01 path serve it. These tests pin
when it fires and - more importantly - the four cases where it must not, because
the cost of firing wrongly is an unattended job opening Excel.

No store, no Excel, no network: the method takes the policy, the asset and the
instant, and returns a policy.
"""

import datetime
import zoneinfo

import pytest

from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotPolicy
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

NY = zoneinfo.ZoneInfo("America/New_York")
ASSET = "USD-SOFR-1D-CITIVELOEXCELMIN"


@pytest.fixture(autouse=True)
def _clear_warn_once():
    """warn_once suppresses repeats process-wide; tests must not depend on order."""
    from MDP.IRSwaps.CITIVELO_EXCEL import snapshot_policy

    snapshot_policy._WARNED.clear()
    yield
    snapshot_policy._WARNED.clear()


def _mdp(**kwargs):
    return IRSwapsMDP(source="citivelo_excel_rl", **kwargs)


def _today_at(hour=11, minute=0):
    now = datetime.datetime.now(NY)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _resolve(mdp, wanted, policy=None):
    return mdp._policy_for_current_session(
        policy if policy is not None else SnapshotPolicy.legacy(),
        asset=ASSET, wanted=wanted, local_zone=NY,
    )


# ── when it fires ────────────────────────────────────────────────────

def test_today_gets_a_bounded_backward_only_policy(monkeypatch):
    monkeypatch.delenv(IRSwapsMDP._TODAY_LIVE_ENV, raising=False)
    got = _resolve(_mdp(), _today_at())
    assert got != SnapshotPolicy.legacy()
    assert got.max_lag is not None, "an unbounded policy is what serves yesterday"
    assert got.allow_future is False, (
        "allow_future is what let an 11:00 request be answered from 14:07"
    )
    assert got.on_miss == "none", (
        "a hard miss would break the read; the point is to fall through to live"
    )


def test_the_bound_is_loose_enough_to_keep_a_warm_store_useful(monkeypatch):
    """If today's minutes HAVE been banked, nothing should go to the wire."""
    monkeypatch.delenv(IRSwapsMDP._TODAY_LIVE_ENV, raising=False)
    got = _resolve(_mdp(), _today_at())
    assert got.max_lag >= datetime.timedelta(minutes=5)
    assert got.max_lag <= datetime.timedelta(hours=1)


def test_it_warns_once_and_names_the_kill_switch(monkeypatch, caplog):
    monkeypatch.delenv(IRSwapsMDP._TODAY_LIVE_ENV, raising=False)
    mdp = _mdp()
    with caplog.at_level("WARNING"):
        _resolve(mdp, _today_at(10))
        _resolve(mdp, _today_at(15))
    warnings = [r for r in caplog.records if "TODAY'S session" in r.getMessage()]
    assert len(warnings) == 1, "one warning per asset per day, not per point"
    assert IRSwapsMDP._TODAY_LIVE_ENV in warnings[0].getMessage()


# ── when it must not ─────────────────────────────────────────────────

def test_a_past_date_is_untouched(monkeypatch):
    """Yesterday's session is complete and banked; there is nothing live to prefer."""
    monkeypatch.delenv(IRSwapsMDP._TODAY_LIVE_ENV, raising=False)
    old = _today_at() - datetime.timedelta(days=3)
    assert _resolve(_mdp(), old) == SnapshotPolicy.legacy()


def test_an_explicit_policy_is_untouched(monkeypatch):
    monkeypatch.delenv(IRSwapsMDP._TODAY_LIVE_ENV, raising=False)
    strict = SnapshotPolicy.strict(minutes=1.0)
    assert _resolve(_mdp(), _today_at(), policy=strict) is strict


def test_an_offline_mdp_is_untouched(monkeypatch):
    """offline means never reach for Excel.

    Turning a store hit into a miss there would replace a stale number with no
    number - and on a scheduled task there is nobody to notice either.
    """
    monkeypatch.delenv(IRSwapsMDP._TODAY_LIVE_ENV, raising=False)
    assert _resolve(_mdp(offline=True), _today_at()) == SnapshotPolicy.legacy()


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "F"])
def test_the_kill_switch_restores_the_old_behaviour_exactly(monkeypatch, value):
    monkeypatch.setenv(IRSwapsMDP._TODAY_LIVE_ENV, value)
    assert _resolve(_mdp(), _today_at()) == SnapshotPolicy.legacy()


def test_a_broken_timezone_degrades_to_the_old_behaviour(monkeypatch):
    """A zone problem must not turn a working read into an exception."""
    monkeypatch.delenv(IRSwapsMDP._TODAY_LIVE_ENV, raising=False)

    class _Exploding:
        def __getattr__(self, name):
            raise RuntimeError("no tzdata")

    got = _mdp()._policy_for_current_session(
        SnapshotPolicy.legacy(), asset=ASSET, wanted=_today_at(),
        local_zone=_Exploding(),
    )
    assert got == SnapshotPolicy.legacy()


# ── the policy itself ────────────────────────────────────────────────

def test_today_live_is_asof_not_nearest():
    policy = SnapshotPolicy.today_live()
    assert policy.method == "asof"
    assert policy.allow_future is False


def test_today_live_minutes_is_configurable():
    assert SnapshotPolicy.today_live(minutes=5).max_lag == datetime.timedelta(minutes=5)


def test_the_policy_actually_changes_what_select_snapshot_returns():
    """The end this exists for, exercised on the selector rather than described.

    A window holding only yesterday's session answers an 11:00 request under the
    legacy policy and misses under today_live. Nothing else in this file proves
    the two are connected.
    """
    import numpy as np
    import pandas as pd

    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import select_snapshot

    wanted = pd.Timestamp("2026-08-21 11:00", tz="America/New_York")
    yesterday_only = np.array(
        [pd.Timestamp(f"2026-08-20 {h}:07", tz="America/New_York").tz_convert("UTC").value
         for h in ("09", "12", "14")],
        dtype=np.int64,
    )
    wanted_ns = wanted.tz_convert("UTC").value

    legacy = select_snapshot(yesterday_only, wanted_ns, SnapshotPolicy.legacy())
    assert legacy is not None, "this is the measured 20.9 h answer"
    assert legacy.lag_seconds > 20 * 3600

    assert select_snapshot(yesterday_only, wanted_ns, SnapshotPolicy.today_live()) is None

    # ...and a store that HAS today's tail still answers, with no wire call.
    fresh = np.append(
        yesterday_only,
        pd.Timestamp("2026-08-21 10:58", tz="America/New_York").tz_convert("UTC").value,
    )
    hit = select_snapshot(fresh, wanted_ns, SnapshotPolicy.today_live())
    assert hit is not None and hit.lag_seconds == pytest.approx(120.0)


def test_today_live_never_serves_a_snapshot_from_the_future():
    """A print stamped after the request is what 'nearest' happily returns."""
    import numpy as np
    import pandas as pd

    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import select_snapshot

    wanted = pd.Timestamp("2026-08-21 11:00", tz="America/New_York")
    later = np.array(
        [pd.Timestamp("2026-08-21 11:05", tz="America/New_York").tz_convert("UTC").value],
        dtype=np.int64,
    )
    wanted_ns = wanted.tz_convert("UTC").value
    assert select_snapshot(later, wanted_ns, SnapshotPolicy.legacy()) is not None
    assert select_snapshot(later, wanted_ns, SnapshotPolicy.today_live()) is None


def test_legacy_is_still_bit_identical_to_the_old_default():
    """Everything above rests on legacy() being the recognisable default."""
    legacy = SnapshotPolicy.legacy()
    assert legacy.method == "nearest"
    assert legacy.max_lag is None
    assert legacy.allow_future is True
    assert legacy.on_miss == "none"

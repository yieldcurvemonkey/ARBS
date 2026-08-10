"""Unit tests for the decoupled curve-warming layer (no network)."""
import pandas as pd
import pytest

from SDRUtils.stir_flow.curve_warm import (
    enumerate_curve_demand, unit_curve_and_snap, warm_pricer,
)


class _U:
    def __init__(self, legs):
        self.legs = legs


def _leg(idx="FED_FUNDS", ts="2026-07-02T13:05:23+00:00", orig=None):
    return pd.DataFrame([{
        "rate_index_clean": idx,
        "execution_timestamp": pd.Timestamp(ts),
        "original_execution_timestamp": pd.Timestamp(orig) if orig else None,
    }])


def test_unit_curve_and_snap_ff():
    cn, snap = unit_curve_and_snap(_U(_leg("FED_FUNDS")))
    assert cn == "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"
    # 13:05:23 UTC -> 09:05 EDT -> secs zeroed, minus 1 minute -> 09:04:00 NY
    assert (snap.minute, snap.second) == (4, 0)
    assert snap.hour == 9 and snap.tzinfo is not None


def test_unit_curve_and_snap_sofr():
    cn, _ = unit_curve_and_snap(_U(_leg("SOFR")))
    assert cn == "USD-SOFR-1D-Q12xM12STIRT"


def test_enumerate_dedupes_same_minute():
    u1 = _U(_leg("SOFR", "2026-07-02T13:05:23+00:00"))
    u2 = _U(_leg("SOFR", "2026-07-02T13:05:47+00:00"))  # same snapped minute
    assert len(enumerate_curve_demand([u1, u2])) == 1


def test_enumerate_separates_index_and_minute():
    us = [
        _U(_leg("SOFR", "2026-07-02T13:05:23+00:00")),
        _U(_leg("FED_FUNDS", "2026-07-02T13:05:23+00:00")),  # diff curve
        _U(_leg("SOFR", "2026-07-02T13:07:23+00:00")),       # diff minute
    ]
    assert len(enumerate_curve_demand(us)) == 3


class _FakeMDP:
    def __init__(self):
        self.calls = []

    def _get_curve(self, curve_name, timestamp):
        self.calls.append((curve_name, timestamp))
        return f"H:{curve_name}:{timestamp}"


class _FakePricer:
    """Models CurvePricer, INCLUDING ``build`` and ``curve_kwargs``.

    ``warm_pricer`` writes straight into ``_handles``, so it must build on the
    same terms ``CurvePricer.handle`` would - that is what ``build`` is for. A
    fake without it would let the warmer go back to calling ``_get_curve``
    directly and this suite would not notice.
    """

    curve_kwargs: dict = {}

    def __init__(self):
        self._mdp = _FakeMDP()
        self._handles = {}

    def build(self, curve_name, ts):
        return self._mdp._get_curve(curve_name=curve_name, timestamp=ts)


def test_warm_builds_all_and_is_idempotent():
    p = _FakePricer()
    demand = {("C", pd.Timestamp("2026-07-02T13:04:00Z")),
              ("C", pd.Timestamp("2026-07-02T13:05:00Z"))}
    r = warm_pricer(p, demand, max_workers=2)
    assert r["built"] == 2 and r["failed"] == 0 and len(p._handles) == 2
    r2 = warm_pricer(p, demand, max_workers=2)
    assert r2["built"] == 0 and r2["reused"] == 2


def test_warm_isolates_failures():
    p = _FakePricer()

    def boom(curve_name, timestamp):
        if "bad" in curve_name:
            raise RuntimeError("x")
        return "H"

    p._mdp._get_curve = boom
    ok_key = ("ok", pd.Timestamp("2026-07-02T13:04:00Z"))
    r = warm_pricer(p, {ok_key, ("bad", pd.Timestamp("2026-07-02T13:04:00Z"))},
                    max_workers=2)
    assert r["built"] == 1 and r["failed"] == 1 and ok_key in p._handles


def test_warm_reraises_when_configured():
    p = _FakePricer()

    def boom(curve_name, timestamp):
        raise RuntimeError("x")

    p._mdp._get_curve = boom
    with pytest.raises(RuntimeError):
        warm_pricer(p, {("bad", pd.Timestamp("2026-07-02T13:04:00Z"))},
                    max_workers=1, on_error="raise")


# --------------------------------------------------------------------------
# bulk seeding: one vendor round trip per curve-day instead of ~479
# --------------------------------------------------------------------------
class _BulkMDP:
    """Fake MDP recording how it was asked for curves."""

    def __init__(self, *, bulk_returns=None, bulk_raises=False):
        self.bulk_calls = []
        self.single_calls = []
        self._bulk_returns = bulk_returns
        self._bulk_raises = bulk_raises

    def bulk_get_data(self, request):
        # mirror the real signature's destructive pops so a caller that reuses a
        # dict across curves would be caught here
        curve_name = request.pop("curve_name")
        timestamps = request.pop("timestamps")
        self.bulk_calls.append((curve_name, list(timestamps)))
        if self._bulk_raises:
            raise RuntimeError("bulk unavailable")
        if self._bulk_returns is None:
            return {ts: f"bulk::{curve_name}::{ts}" for ts in timestamps}
        return self._bulk_returns(curve_name, timestamps)

    def _get_curve(self, curve_name=None, timestamp=None):
        self.single_calls.append((curve_name, timestamp))
        return f"single::{curve_name}::{timestamp}"


class _P:
    def __init__(self, mdp, curve_kwargs=None):
        self._mdp = mdp
        self._handles = {}
        self.curve_kwargs = dict(curve_kwargs or {})

    def build(self, curve_name, ts):
        return self._mdp._get_curve(curve_name=curve_name, timestamp=ts)


def _demand(n=5, curve="USD-SOFR-1D-Q12xM12STIRT"):
    base = pd.Timestamp("2026-07-10 09:00", tz="America/New_York")
    return {(curve, base + pd.Timedelta(minutes=i)) for i in range(n)}


def test_bulk_warm_makes_one_call_per_curve_not_per_minute():
    """The whole point: ~479 vendor round trips per curve-day become one."""
    mdp = _BulkMDP()
    p = _P(mdp)
    demand = _demand(5) | _demand(4, curve="USD-OIS-Q12xM12STIRT-SERFFX-MIX23")
    res = warm_pricer(p, demand, max_workers=4)
    assert len(mdp.bulk_calls) == 2                 # one per curve
    assert mdp.single_calls == []                   # nothing fell through
    assert res["bulk_seeded"] == 9 and res["built"] == 0 and res["failed"] == 0
    assert len(p._handles) == 9
    assert all(str(v).startswith("bulk::") for v in p._handles.values())


def test_bulk_warm_falls_back_per_minute_for_whatever_bulk_missed():
    base = pd.Timestamp("2026-07-10 09:00", tz="America/New_York")
    covered = {base, base + pd.Timedelta(minutes=1)}

    def partial(curve_name, timestamps):
        return {ts: f"bulk::{curve_name}::{ts}" for ts in timestamps if ts in covered}

    mdp = _BulkMDP(bulk_returns=partial)
    p = _P(mdp)
    res = warm_pricer(p, _demand(5), max_workers=2)
    assert res["bulk_seeded"] == 2
    assert res["built"] == 3                        # the residual three
    assert len(mdp.single_calls) == 3
    assert len(p._handles) == 5


def test_bulk_failure_is_survivable():
    """A bulk problem may cost time; it must never cost correctness."""
    mdp = _BulkMDP(bulk_raises=True)
    p = _P(mdp)
    res = warm_pricer(p, _demand(4), max_workers=2)
    assert res["bulk_seeded"] == 0 and res["built"] == 4 and res["failed"] == 0
    assert len(p._handles) == 4


def test_bulk_can_be_disabled():
    mdp = _BulkMDP()
    p = _P(mdp)
    res = warm_pricer(p, _demand(3), max_workers=2, bulk=False)
    assert mdp.bulk_calls == [] and res["built"] == 3


def test_bulk_matches_on_timestamp_value_not_object_identity():
    """The batch path may key by an equal-but-different timestamp type."""
    def as_naive_utc(curve_name, timestamps):
        return {pd.Timestamp(ts).tz_convert("UTC"): f"bulk::{curve_name}::{ts}"
                for ts in timestamps}

    mdp = _BulkMDP(bulk_returns=as_naive_utc)
    p = _P(mdp)
    res = warm_pricer(p, _demand(3), max_workers=2)
    assert res["bulk_seeded"] == 3 and res["built"] == 0


def test_already_warm_handles_are_never_refetched():
    mdp = _BulkMDP()
    p = _P(mdp)
    demand = _demand(3)
    for key in demand:
        p._handles[key] = "preexisting"
    res = warm_pricer(p, demand, max_workers=2)
    assert res == {"built": 0, "reused": 3, "failed": 0, "bulk_seeded": 0}
    assert mdp.bulk_calls == [] and mdp.single_calls == []


def test_bulk_seeds_only_missing_keys():
    mdp = _BulkMDP()
    p = _P(mdp)
    demand = sorted(_demand(4))
    p._handles[demand[0]] = "preexisting"
    res = warm_pricer(p, set(demand), max_workers=2)
    assert res["reused"] == 1 and res["bulk_seeded"] == 3
    assert p._handles[demand[0]] == "preexisting"     # not overwritten
    assert len(mdp.bulk_calls[0][1]) == 3             # only the missing three asked for


# --------------------------------------------------------------------------
# the warmer must build on the PRICER's terms, not on the MDP's defaults
# --------------------------------------------------------------------------
def test_warm_builds_through_the_pricer_so_its_curve_kwargs_apply():
    """A warmed handle is served from the cache forever after.

    ``warm_pricer`` pre-populates ``_handles`` directly, so if it built by
    calling ``_get_curve`` itself it would seed a pricer carrying a strict
    snapshot policy with legacy-selected curves - the cache key and the terms
    disagreeing, silently, for every minute it warmed. That is the production
    dealer-direction path, not a corner.
    """
    from SDRUtils.stir_flow.pricing import CurvePricer

    seen = []

    class _RecordingMDP:
        def _get_curve(self, curve_name, timestamp, kwargs=None):
            seen.append(dict(kwargs or {}))
            return f"H:{curve_name}"

        def bulk_get_data(self, request):
            return {}

    pricer = CurvePricer(mdp=_RecordingMDP(), curve_kwargs={"snapshot_policy": "SENTINEL"})
    res = warm_pricer(
        pricer, {("C", pd.Timestamp("2026-07-02T13:04:00Z"))}, max_workers=1, bulk=False
    )
    assert res["built"] == 1
    assert seen == [{"snapshot_policy": "SENTINEL"}]


def test_bulk_seed_passes_the_pricers_curve_kwargs_too():
    """The bulk seeder writes into the same cache and must use the same terms."""
    requests = []

    class _RecordingMDP:
        def bulk_get_data(self, request):
            requests.append(dict(request))
            return {}

        def _get_curve(self, curve_name=None, timestamp=None, kwargs=None):
            return "H"

    p = _P(_RecordingMDP(), curve_kwargs={"snapshot_policy": "SENTINEL"})
    warm_pricer(p, _demand(2), max_workers=1)
    assert requests and requests[0].get("snapshot_policy") == "SENTINEL"

"""get_data must not cache, or serve, a result that carries no data.

Regression for a poisoned cache entry that made every later call fail with
"Missing SABR smile legs for <date>: [...]. Available quote dates: none." even though
Barchart had the data and ``force_refresh=True`` returned it fine.

The first guard only tested the container (``if hit:``), which catches ``{}`` but not
``{symbol: []}`` - and ``option_snapshot`` returns exactly that shape, so a failed build
produced a twenty-key dict that was perfectly truthy and completely empty.
"""

import datetime

import pandas as pd
import pytest

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP


@pytest.fixture
def mdp():
    return STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")


@pytest.mark.parametrize(
    "payload,expected",
    [
        (None, True),
        ({}, True),
        ([], True),
        ({"SFRU26|25DC": [], "SFRU26|25DP": []}, True),          # the shape that bit us
        ({"a": [], "b": [], "c": []}, True),
        ({"SFRU26|25DC": ["pricer"], "SFRU26|25DP": []}, False),  # partial is NOT empty
        ({"SFRU26|25DC": ["pricer"]}, False),
        ({"sabr_smile": ["smile"]}, False),
    ],
)
def test_is_empty_get_data_result(mdp, payload, expected):
    assert mdp._is_empty_get_data_result(payload) is expected


def test_dataframe_payloads_are_not_mistaken_for_empty(mdp):
    """qs_* endpoints return DataFrames; `not df` raises, and a populated frame must
    never be judged empty."""
    full = pd.DataFrame({"x": [1, 2, 3]})
    assert mdp._is_empty_get_data_result({"SR3Z26": full}) is False
    assert mdp._is_empty_get_data_result({"SR3Z26": pd.DataFrame()}) is True


def test_scalar_values_count_as_content(mdp):
    assert mdp._is_empty_get_data_result({"n": 0}) is False


def test_empty_result_is_not_persisted(mdp, monkeypatch):
    puts = []
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda k, v: puts.append(k))
    monkeypatch.setattr(
        mdp, "_option_snapshot", lambda request: {s: [] for s in request["symbols"]}
    )

    out = mdp.get_data({
        "endpoint": "option_snapshot",
        "symbols": ["SFRU26|25DC", "SFRU26|25DP"],
        "timestamp": datetime.date(2026, 7, 27),
    })
    assert out == {"SFRU26|25DC": [], "SFRU26|25DP": []}
    assert puts == [], "an all-empty result was written to cache"


def _bypass_codec(mdp, monkeypatch):
    """These tests exercise the cache-hit decision, not pricer (de)serialisation."""
    monkeypatch.setattr(mdp, "_serialize_get_data_result", lambda endpoint, out: out)
    monkeypatch.setattr(mdp, "_deserialize_get_data_result", lambda cached: cached)


def test_poisoned_entry_does_not_short_circuit_the_rebuild(mdp, monkeypatch):
    """The whole point: a cached {symbol: []} must be ignored, not returned."""
    _bypass_codec(mdp, monkeypatch)
    request = {
        "endpoint": "option_snapshot",
        "symbols": ["SFRU26|25DC", "SFRU26|25DP"],
        "timestamp": datetime.date(2026, 7, 27),
    }
    poisoned = {s: [] for s in request["symbols"]}
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda *a, **k: poisoned)
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda k, v: None)

    calls = []

    def _fake_snapshot(req):
        calls.append(req)
        return {s: ["pricer"] for s in req["symbols"]}

    monkeypatch.setattr(mdp, "_option_snapshot", _fake_snapshot)

    out = mdp.get_data(dict(request))
    assert calls, "the poisoned entry short-circuited the rebuild"
    assert all(out[s] for s in request["symbols"])


def test_non_empty_entry_still_short_circuits(mdp, monkeypatch):
    _bypass_codec(mdp, monkeypatch)
    request = {
        "endpoint": "option_snapshot",
        "symbols": ["SFRU26|25DC"],
        "timestamp": datetime.date(2026, 7, 27),
    }
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda *a, **k: {"SFRU26|25DC": ["pricer"]})
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda k, v: None)

    def _must_not_run(req):
        raise AssertionError("cache hit should have short-circuited the build")

    monkeypatch.setattr(mdp, "_option_snapshot", _must_not_run)
    out = mdp.get_data(dict(request))
    assert out["SFRU26|25DC"]

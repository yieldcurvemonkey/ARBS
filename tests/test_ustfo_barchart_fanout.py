import datetime
import time

import pandas as pd

from MDP.USTFutures.USTFutureOptionMDP import USTFutureOptionMDP

S = datetime.datetime(2024, 1, 1)
E = datetime.datetime(2024, 3, 1)


def _df():
    return pd.DataFrame({"Close": [110.5]}, index=pd.DatetimeIndex([pd.Timestamp("2024-01-02")]))


def _mk(enabled=True):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    mdp._barchart_fanout_enabled = enabled
    mdp._socksio_enabled = True
    mdp._barchart_fanout_max_shards = 3
    mdp._barchart_fanout_min_symbols_per_shard = 2
    mdp._barchart_fanout_batch_size = 2
    mdp._barchart_fanout_max_batch_attempts = 2
    mdp._barchart_fanout_evict_after = 2
    return mdp


class _FakeFetcher:
    def __init__(self, host, behavior, seen):
        self.host = host
        self.behavior = behavior
        self.seen = seen

    def barchart_timeseries_api(self, *, barchart_symbols, **kw):
        time.sleep(0.005)
        self.seen.append((self.host, list(barchart_symbols)))
        if self.behavior == "raise":
            raise RuntimeError(f"{self.host} down")
        if self.behavior == "none":
            return {s: None for s in barchart_symbols}
        return {s: _df() for s in barchart_symbols}

    def close(self):
        pass


def _patch(monkeypatch, mdp, hosts):
    monkeypatch.setattr(mdp, "_choose_fanout_proxies", lambda k: [({"id": h}, h) for h in hosts])


def test_ust_fanout_workstealing_covers_all_exactly_once(monkeypatch):
    mdp = _mk()
    seen = []
    behaviors = {"h0": "data", "h1": "data", "h2": "data"}
    _patch(monkeypatch, mdp, list(behaviors))
    monkeypatch.setattr(mdp, "_build_barchart_fetcher_for_host", lambda p, h, mc, **kw: _FakeFetcher(h, behaviors[h], seen))
    monkeypatch.setattr(mdp, "_run_eod_fetch_single", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fallback when healthy")))

    syms = [f"S{i}" for i in range(20)]
    out = mdp._run_eod_fetch(syms, S, E, False, 6, 6)
    assert sorted(s for _, sl in seen for s in sl) == sorted(syms)
    assert set(out) == set(syms)
    assert len({h for h, _ in seen}) >= 2


def test_ust_fanout_no_data_loss_with_one_bad_proxy(monkeypatch):
    mdp = _mk()
    seen = []
    behaviors = {"h0": "raise", "h1": "data", "h2": "data"}
    _patch(monkeypatch, mdp, list(behaviors))
    monkeypatch.setattr(mdp, "_build_barchart_fetcher_for_host", lambda p, h, mc, **kw: _FakeFetcher(h, behaviors[h], seen))
    monkeypatch.setattr(mdp, "_run_eod_fetch_single", lambda symbols, *a, **k: {s: _df() for s in symbols})

    syms = [f"S{i}" for i in range(20)]
    out = mdp._run_eod_fetch(syms, S, E, False, 6, 6)
    assert set(out) == set(syms)


def test_ust_fanout_recovers_none_symbols_within_successful_batch(monkeypatch):
    mdp = _mk()
    mdp._barchart_fanout_batch_size = 8

    class _Patchy:
        def __init__(self, host):
            self.host = host

        def barchart_timeseries_api(self, *, barchart_symbols, **kw):
            return {s: (None if s.endswith("9") else _df()) for s in barchart_symbols}

        def close(self):
            pass

    monkeypatch.setattr(mdp, "_choose_fanout_proxies", lambda k: [({"id": 0}, "h0"), ({"id": 1}, "h1")])
    monkeypatch.setattr(mdp, "_build_barchart_fetcher_for_host", lambda p, h, mc, **kw: _Patchy(h))
    recovered = []

    def _single(symbols, *a, **k):
        recovered.extend(symbols)
        return {s: _df() for s in symbols}

    monkeypatch.setattr(mdp, "_run_eod_fetch_single", _single)
    syms = [f"S{i}" for i in range(20)]
    out = mdp._run_eod_fetch(syms, S, E, False, 6, 6)
    assert set(recovered) == {"S9", "S19"}
    assert set(out) == set(syms)
    assert all(out[s] is not None for s in syms)


def test_ust_fanout_disabled_uses_single(monkeypatch):
    mdp = _mk(enabled=False)
    calls = {"n": 0}
    monkeypatch.setattr(mdp, "_run_eod_fetch_single", lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1) or {}))
    mdp._run_eod_fetch(["A", "B", "C", "D", "E", "F"], S, E, False, 6, 6)
    assert calls["n"] == 1


def test_ust_fanout_health_demotes_recently_failed_host(monkeypatch):
    mdp = _mk()
    st = USTFutureOptionMDP._BARCHART_STATE
    st["fanout"] = None
    st["fanout_chosen_at"] = 0.0
    st["proxy_health"] = {}
    st["ttl"] = 60
    mdp._barchart_proxy_hosts = ["h0", "h1", "h2", "h3", None]
    mdp._barchart_fanout_proxy_cooldown = 300
    monkeypatch.setattr("MDP.USTFutures.USTFutureOptionMDP._build_socks5h", lambda h: {"http": h, "https": h})
    monkeypatch.setattr("MDP.USTFutures.USTFutureOptionMDP._preflight_proxy", lambda p, **k: True)

    mdp._record_fanout_proxy_failure("h1")
    hosts = {h for _, h in mdp._choose_fanout_proxies(4)}
    assert "h1" not in hosts
    assert {"h0", "h2", "h3"} <= hosts

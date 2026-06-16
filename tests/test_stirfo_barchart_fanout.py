import datetime
import time

import pandas as pd

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

S = datetime.datetime(2024, 1, 1)
E = datetime.datetime(2024, 3, 1)


def _df():
    return pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2024-01-02")]))


def _mk(enabled=True):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    mdp._barchart_fanout_enabled = enabled
    mdp._socksio_enabled = True
    mdp._barchart_fanout_max_shards = 3
    mdp._barchart_fanout_min_symbols_per_shard = 2  # engage at >= 4 symbols
    mdp._barchart_fanout_batch_size = 2             # many small batches
    mdp._barchart_fanout_max_batch_attempts = 2
    mdp._barchart_fanout_evict_after = 2
    return mdp


class _FakeFetcher:
    """Stand-in worker fetcher: 'data' returns frames, 'raise' errors, 'none' all-None."""

    def __init__(self, host, behavior, seen):
        self.host = host
        self.behavior = behavior
        self.seen = seen

    def barchart_timeseries_api(self, *, barchart_symbols, **kw):
        time.sleep(0.005)  # let workers interleave so the steal is observable
        self.seen.append((self.host, list(barchart_symbols)))
        if self.behavior == "raise":
            raise RuntimeError(f"{self.host} down")
        if self.behavior == "none":
            return {s: None for s in barchart_symbols}
        return {s: _df() for s in barchart_symbols}

    def close(self):
        pass


def _patch_proxies(monkeypatch, mdp, hosts):
    monkeypatch.setattr(mdp, "_choose_fanout_proxies", lambda k: [({"id": h}, h) for h in hosts])


def test_fanout_workstealing_covers_all_exactly_once(monkeypatch):
    mdp = _mk()
    seen = []
    behaviors = {"host0": "data", "host1": "data", "host2": "data"}
    _patch_proxies(monkeypatch, mdp, list(behaviors))
    monkeypatch.setattr(mdp, "_build_barchart_fetcher_for_host", lambda p, h, mc, **kw: _FakeFetcher(h, behaviors[h], seen))

    def _no_fallback(*a, **k):
        raise AssertionError("fallback must not run when all proxies are healthy")

    monkeypatch.setattr(mdp, "_run_eod_fetch_single", _no_fallback)

    syms = [f"S{i}" for i in range(20)]
    out = mdp._run_eod_fetch(syms, S, E, False, 6, 6, 4)

    fetched = sorted(s for _, sl in seen for s in sl)
    assert fetched == sorted(syms)          # every symbol fetched exactly once (no dup, no loss)
    assert set(out) == set(syms)
    assert len({h for h, _ in seen}) >= 2   # genuinely distributed across proxies


def test_fanout_no_data_loss_with_one_bad_proxy(monkeypatch):
    mdp = _mk()
    seen = []
    behaviors = {"host0": "raise", "host1": "data", "host2": "data"}
    _patch_proxies(monkeypatch, mdp, list(behaviors))
    monkeypatch.setattr(mdp, "_build_barchart_fetcher_for_host", lambda p, h, mc, **kw: _FakeFetcher(h, behaviors[h], seen))

    fb = []

    def _single(symbols, *a, **k):
        fb.append(list(symbols))
        return {s: _df() for s in symbols}

    monkeypatch.setattr(mdp, "_run_eod_fetch_single", _single)

    syms = [f"S{i}" for i in range(20)]
    out = mdp._run_eod_fetch(syms, S, E, False, 6, 6, 4)
    assert set(out) == set(syms)  # bad proxy never causes data loss (healthy workers + fallback)


def test_fanout_all_bad_proxies_fall_back_to_single(monkeypatch):
    mdp = _mk()
    behaviors = {"host0": "raise", "host1": "raise", "host2": "raise"}
    _patch_proxies(monkeypatch, mdp, list(behaviors))
    monkeypatch.setattr(mdp, "_build_barchart_fetcher_for_host", lambda p, h, mc, **kw: _FakeFetcher(h, behaviors[h], []))

    fb = []

    def _single(symbols, *a, **k):
        fb.append(list(symbols))
        return {s: _df() for s in symbols}

    monkeypatch.setattr(mdp, "_run_eod_fetch_single", _single)

    syms = [f"S{i}" for i in range(12)]
    out = mdp._run_eod_fetch(syms, S, E, False, 6, 6, 4)
    assert set(out) == set(syms)
    assert sorted(s for sl in fb for s in sl) == sorted(syms)  # everything recovered via fallback


def test_fanout_dead_proxy_at_warm_never_fetches(monkeypatch):
    mdp = _mk()
    seen = []

    def _build(p, h, mc, **kw):
        if h == "host0":
            raise RuntimeError("warm failed")  # dead proxy: worker never starts
        return _FakeFetcher(h, "data", seen)

    _patch_proxies(monkeypatch, mdp, ["host0", "host1", "host2"])
    monkeypatch.setattr(mdp, "_build_barchart_fetcher_for_host", _build)
    monkeypatch.setattr(mdp, "_run_eod_fetch_single", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fallback")))

    syms = [f"S{i}" for i in range(20)]
    out = mdp._run_eod_fetch(syms, S, E, False, 6, 6, 4)
    assert set(out) == set(syms)
    assert "host0" not in {h for h, _ in seen}  # dead worker contributed nothing


def test_fanout_single_live_proxy_uses_single_path(monkeypatch):
    mdp = _mk()
    _patch_proxies(monkeypatch, mdp, ["host0"])  # only one live proxy -> not worth fan-out
    called = {"n": 0}
    monkeypatch.setattr(mdp, "_run_eod_fetch_single", lambda *a, **k: (called.__setitem__("n", called["n"] + 1) or {}))
    mdp._run_eod_fetch([f"S{i}" for i in range(20)], S, E, False, 6, 6, 4)
    assert called["n"] == 1


def test_fanout_disabled_uses_single_path(monkeypatch):
    mdp = _mk(enabled=False)
    called = {"n": 0}
    monkeypatch.setattr(mdp, "_run_eod_fetch_single", lambda *a, **k: (called.__setitem__("n", called["n"] + 1) or {}))
    mdp._run_eod_fetch(["A", "B", "C", "D", "E", "F"], S, E, False, 6, 6, 4)
    assert called["n"] == 1


def test_fanout_too_few_symbols_uses_single_path(monkeypatch):
    mdp = _mk()
    mdp._barchart_fanout_min_symbols_per_shard = 8  # engage only at >= 16
    called = {"n": 0}
    monkeypatch.setattr(mdp, "_run_eod_fetch_single", lambda *a, **k: (called.__setitem__("n", called["n"] + 1) or {}))
    mdp._run_eod_fetch(["A", "B", "C"], S, E, False, 6, 6, 4)
    assert called["n"] == 1


def test_fanout_recovers_none_symbols_within_successful_batch(monkeypatch):
    """A transient per-symbol None inside an otherwise-successful batch must still be
    recovered via the reliable single-proxy path (the completeness backstop)."""
    mdp = _mk()
    mdp._barchart_fanout_batch_size = 8

    class _Patchy:
        def __init__(self, host):
            self.host = host

        def barchart_timeseries_api(self, *, barchart_symbols, **kw):
            # Healthy proxy, but symbols ending in '9' come back None (transient hiccup).
            return {s: (None if s.endswith("9") else _df()) for s in barchart_symbols}

        def close(self):
            pass

    monkeypatch.setattr(mdp, "_choose_fanout_proxies", lambda k: [({"id": 0}, "h0"), ({"id": 1}, "h1")])
    monkeypatch.setattr(mdp, "_build_barchart_fetcher_for_host", lambda p, h, mc, **kw: _Patchy(h))

    recovered = []

    def _single(symbols, *a, **k):
        recovered.extend(symbols)
        return {s: _df() for s in symbols}  # reliable path gets them

    monkeypatch.setattr(mdp, "_run_eod_fetch_single", _single)

    syms = [f"S{i}" for i in range(20)]  # S9, S19 end in '9'
    out = mdp._run_eod_fetch(syms, S, E, False, 6, 6, 4)

    assert set(recovered) == {"S9", "S19"}              # only the None ones went to fallback
    assert set(out) == set(syms)
    assert all(out[s] is not None for s in syms)        # nothing left without data


def _reset_state(ttl=60):
    st = STIRFutureOptionMDP._BARCHART_STATE
    st["fanout"] = None
    st["fanout_chosen_at"] = 0.0
    st["proxy_health"] = {}
    st["ttl"] = ttl
    return st


def test_fanout_health_demotes_recently_failed_host(monkeypatch):
    mdp = _mk()
    _reset_state()
    mdp._barchart_proxy_hosts = ["h0", "h1", "h2", "h3", None]
    mdp._barchart_fanout_proxy_cooldown = 300
    monkeypatch.setattr("MDP.STIRFutures.STIRFutureOptionMDP._build_socks5h", lambda h: {"http": h, "https": h})
    monkeypatch.setattr("MDP.STIRFutures.STIRFutureOptionMDP._preflight_proxy", lambda p, **k: True)

    mdp._record_fanout_proxy_failure("h1")  # worker evicted h1
    hosts = {h for _, h in mdp._choose_fanout_proxies(4)}
    assert "h1" not in hosts                # skipped within cooldown
    assert {"h0", "h2", "h3"} <= hosts


def test_fanout_failure_drops_host_from_cached_set():
    mdp = _mk()
    st = _reset_state()
    st["fanout"] = [({"x": 1}, "h0"), ({"x": 2}, "h1")]
    mdp._record_fanout_proxy_failure("h0")
    assert [h for _, h in st["fanout"]] == ["h1"]


def test_fanout_health_falls_back_when_too_few_healthy(monkeypatch):
    mdp = _mk()
    _reset_state()
    mdp._barchart_proxy_hosts = ["h0", "h1", None]
    mdp._barchart_fanout_proxy_cooldown = 300
    monkeypatch.setattr("MDP.STIRFutures.STIRFutureOptionMDP._build_socks5h", lambda h: {"http": h})
    monkeypatch.setattr("MDP.STIRFutures.STIRFutureOptionMDP._preflight_proxy", lambda p, **k: True)

    mdp._record_fanout_proxy_failure("h0")
    mdp._record_fanout_proxy_failure("h1")  # both demoted -> none healthy
    hosts = {h for _, h in mdp._choose_fanout_proxies(2)}
    assert hosts == {"h0", "h1"}            # fall back to all rather than starve the pool

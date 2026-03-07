import datetime

import pandas as pd

from MDP.FixedRateBonds.FEDINVEST.FedInvestFetcher import FedInvestDataFetcher


class _NoKeysCache:
    def __init__(self, initial=None):
        self._store = dict(initial or {})

    def __contains__(self, key):
        return key in self._store

    def __getitem__(self, key):
        return self._store[key]

    def __setitem__(self, key, value):
        self._store[key] = value

    def keys(self):
        raise AssertionError("runner should not enumerate cache keys")


def test_runner_uses_cache_membership_instead_of_keys(monkeypatch):
    fetcher = FedInvestDataFetcher()
    cached_dt = datetime.datetime(2026, 3, 2, 14, 0)
    cache_key = pd.Timestamp(cached_dt.date())
    cached_df = pd.DataFrame({"cusip": ["912810TM0"], "price": [99.5]})
    cache = _NoKeysCache({cache_key: cached_df})

    monkeypatch.setattr(fetcher, "_ensure_cache", lambda: None)
    monkeypatch.setattr(fetcher, "close_cache", lambda: None)
    setattr(fetcher, fetcher._FEDINVEST_CACHE, cache)

    out = fetcher.runner(dates=[cached_dt], refresh_cache=False)

    assert list(out.keys()) == [cached_dt]
    assert out[cached_dt].equals(cached_df)

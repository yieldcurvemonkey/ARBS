import asyncio

import pandas as pd

from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher


def test_get_option_quotes_filters_failed_symbol_results(monkeypatch):
    bf = BarchartFetcher(debug_verbose=False, info_verbose=False, error_verbose=False)

    class _DummyAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

    async def _fake_gather(*tasks):
        for task in tasks:
            # Prevent un-awaited coroutine warnings in test harness.
            if hasattr(task, "close"):
                task.close()
        return [
            (
                "ZNM26",
                {
                    "call": pd.DataFrame([{"strikePrice": 112.5}]),
                    "put": pd.DataFrame([{"strikePrice": 112.5}]),
                },
            ),
            None,
            ("BAD", None),
        ]

    monkeypatch.setattr(asyncio, "gather", _fake_gather)
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: _DummyAsyncClient())
    monkeypatch.setattr(
        bf,
        "_get_shared_session_token_pool",
        lambda pool_size, dummy_symbol="BTC": [("laravel", "xsrf")] * int(pool_size),
    )

    out = bf.get_option_quotes(symbols=["ZNM26", "BROKEN"], show_tqdm=False)
    assert list(out.keys()) == ["ZNM26"]
    assert "call" in out["ZNM26"]
    assert "put" in out["ZNM26"]

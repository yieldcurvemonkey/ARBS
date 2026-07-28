import datetime
import importlib

import pandas as pd
import pytest

pytest.importorskip("rateslib")
import MDP.STIRFutures.STIRFutureMDP as stir_mdp_module
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP


def _sample_fixings_series() -> pd.Series:
    return pd.Series(
        [0.0475, 0.0480, 0.0485],
        index=pd.to_datetime(["2025-01-05", "2025-01-06", "2025-01-07"]),
        name="Fixing",
    )


def test_sofr_symbol_injects_fixings_scaled_and_filtered(monkeypatch):
    calls = []

    def fake_fetch_fixings(as_of_date, curve_name, force_refresh=False):
        calls.append((as_of_date, curve_name, force_refresh))
        return _sample_fixings_series()

    monkeypatch.setattr(stir_mdp_module, "_fetch_fixings", fake_fetch_fixings)
    mdp = STIRFutureMDP(source="WEBULL_STIRF-RL")

    args = {
        "symbol": "SR3H26",
        "price": 95.125,
        "timestamp": "2025-01-07T15:30:00+00:00",
        "schema": 1,
    }
    pr = mdp._build_pricer_from_args(args)

    assert calls == [(datetime.date(2025, 1, 7), "USD-SOFR-1D", False)]
    fixings = pr.meta()["fixings"]
    assert isinstance(fixings, pd.Series)
    assert list(fixings.index.date) == [datetime.date(2025, 1, 5), datetime.date(2025, 1, 6), datetime.date(2025, 1, 7)]
    assert list(fixings.values) == pytest.approx([4.75, 4.8, 4.85])


def test_fed_funds_symbol_also_fetches_fixings(monkeypatch):
    """ZQ is Fed Funds, whose accrual needs FF fixings just as SR3 needs SOFR.

    This test used to assert ZQ SKIPPED the fetch, which stopped being true when
    USD-FEDFUNDS was added alongside USD-SOFR-1D in _build_pricer_from_args.
    """
    calls = []

    def fake_fetch_fixings(as_of_date, curve_name, force_refresh=False):
        calls.append((as_of_date, curve_name, force_refresh))
        return _sample_fixings_series()

    monkeypatch.setattr(stir_mdp_module, "_fetch_fixings", fake_fetch_fixings)
    mdp = STIRFutureMDP(source="WEBULL_STIRF-RL")

    pr = mdp._build_pricer_from_args(
        {
            "symbol": "ZQH26",
            "price": 95.125,
            "timestamp": "2025-01-07T15:30:00+00:00",
            "schema": 1,
        }
    )

    assert calls == [(datetime.date(2025, 1, 7), "USD-FEDFUNDS", False)]
    assert "fixings" in pr.meta()


def test_non_usd_symbol_skips_fixings_fetch(monkeypatch):
    """Only the two USD RFR curves carry a fixings series."""
    called = {"n": 0}

    def fake_fetch_fixings(*args, **kwargs):
        called["n"] += 1
        return _sample_fixings_series()

    monkeypatch.setattr(stir_mdp_module, "_fetch_fixings", fake_fetch_fixings)
    mdp = STIRFutureMDP(source="WEBULL_STIRF-RL")

    pr = mdp._build_pricer_from_args(
        {
            "symbol": "RGH26",  # CAD-CORRA
            "price": 95.125,
            "timestamp": "2025-01-07T15:30:00+00:00",
            "schema": 1,
        }
    )

    assert called["n"] == 0
    assert "fixings" not in pr.meta()


def test_fixings_fetch_failure_raises(monkeypatch):
    # Production has been fail-closed since commit 4f4c5792 ("dump", 2026-02-18): the try/except
    # around _fetch_fixings was written as commented-out code from day one (# try: / # except:).
    # The original test name "fail_open" was a misnomer — production never suppressed errors.
    # 375961f6 updated the assertion to match; this rename completes that fix. (Task 14 review, 2026-07-02)
    def fake_fetch_fixings(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(stir_mdp_module, "_fetch_fixings", fake_fetch_fixings)
    mdp = STIRFutureMDP(source="WEBULL_STIRF-RL")

    with pytest.raises(RuntimeError, match="boom"):
        mdp._build_pricer_from_args(
            {
                "symbol": "SR3H26",
                "price": 95.125,
                "timestamp": "2025-01-07T15:30:00+00:00",
                "schema": 1,
            }
        )


def test_force_refresh_fixings_flag_forwarded(monkeypatch):
    calls = []

    def fake_fetch_fixings(as_of_date, curve_name, force_refresh=False):
        calls.append((as_of_date, curve_name, force_refresh))
        return _sample_fixings_series()

    monkeypatch.setattr(stir_mdp_module, "_fetch_fixings", fake_fetch_fixings)
    mdp = STIRFutureMDP(source="WEBULL_STIRF-RL", force_refresh_fixings=True)

    mdp._build_pricer_from_args(
        {
            "symbol": "SR3H26",
            "price": 95.125,
            "timestamp": "2025-01-07T15:30:00+00:00",
            "schema": 1,
        }
    )

    assert calls == [(datetime.date(2025, 1, 7), "USD-SOFR-1D", True)]


def test_request_local_memoization_reuses_fixings(monkeypatch):
    calls = []

    def fake_fetch_fixings(as_of_date, curve_name, force_refresh=False):
        calls.append((as_of_date, curve_name, force_refresh))
        return _sample_fixings_series()

    monkeypatch.setattr(stir_mdp_module, "_fetch_fixings", fake_fetch_fixings)
    mdp = STIRFutureMDP(source="WEBULL_STIRF-RL")
    fixings_memo = {}

    mdp._build_pricer_from_args(
        {
            "symbol": "SR3H26",
            "price": 95.125,
            "timestamp": "2025-01-07T15:30:00+00:00",
            "schema": 1,
        },
        fixings_memo=fixings_memo,
    )
    mdp._build_pricer_from_args(
        {
            "symbol": "SR3M26",
            "price": 95.225,
            "timestamp": "2025-01-07T16:00:00+00:00",
            "schema": 1,
        },
        fixings_memo=fixings_memo,
    )

    assert len(calls) == 1
    assert list(fixings_memo.keys()) == [("USD-SOFR-1D", datetime.date(2025, 1, 7))]


def test_pricer_cache_stays_local_when_supabase_enabled(tmp_path, monkeypatch):
    from Caching.DiskCacheMixin import DiskCacheMixin
    from Caching.layered_cache_mixin import LayeredDictProxy
    import Caching.supabase_engine as eng

    saved_root = DiskCacheMixin.CACHE_ROOT
    try:
        with monkeypatch.context() as env_patch:
            env_patch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
            env_patch.setenv("ARBS_DATABASE_URL", "postgresql://user:pass@localhost:6543/testdb")
            importlib.reload(eng)

            DiskCacheMixin.CACHE_ROOT = tmp_path
            DiskCacheMixin._CACHE_REGISTRY.clear()

            mdp = STIRFutureMDP(source="WEBULL_STIRF-RL")
            mdp._ensure_pricer_cache()
            cache = getattr(mdp, mdp._STIR_PRICER_CACHE)

            assert not isinstance(cache, LayeredDictProxy)
            mdp.close_cache()
    finally:
        DiskCacheMixin.CACHE_ROOT = saved_root
        DiskCacheMixin._CACHE_REGISTRY.clear()
        importlib.reload(eng)

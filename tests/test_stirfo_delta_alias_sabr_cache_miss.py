"""A SABR-cache miss must fall through to the full delta-alias build, not vanish.

`_option_snapshot` resolves delta aliases (``SFRZ26|25DC``) from a cached SABR smile when
one is available. On a non-forced request it used to *clear* every spec the cache could
not resolve:

    for raw in sabr_resolved_raws:
        del delta_specs[raw]
    if not force_refresh:
        delta_specs.clear()          # <- everything else, gone

so a cache MISS became a silent empty result: no candidate strikes generated, no pricer
window built, ``option_snapshot`` returning ``{}``. That surfaced far away as

    ValueError: Missing SABR smile legs for 2026-07-27: ['5D Call', ...].
                Available quote dates: none.

and it was self-perpetuating - the SABR smile that would warm the cache is built from this
very snapshot, so a cold contract could never recover except via force_refresh=True.
"""

import datetime

import pandas as pd
import pytest

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP


class _DummyCurve:
    def __getitem__(self, key):
        _ = key
        return 0.99


class _DummyCurveBuilder:
    def build_curve(self, curve_name, timestamp, kwargs=None, curve_only=True):
        _ = curve_name, timestamp, kwargs, curve_only
        return _DummyCurve()


AS_OF = datetime.date(2026, 7, 27)
IDX = pd.DatetimeIndex([pd.Timestamp("2026-07-24"), pd.Timestamp("2026-07-27")])


def _fut_frame():
    return pd.DataFrame(
        {"Open": [95.85, 95.86], "High": [95.90, 95.91], "Low": [95.80, 95.81],
         "Close": [95.85, 95.855], "Volume": [1000, 1100],
         "Open Interest": [50000, 50100]},
        index=IDX,
    )


def _opt_frame(px):
    return pd.DataFrame(
        {"Open": [px, px], "High": [px, px], "Low": [px, px], "Close": [px, px],
         "Volume": [10, 12], "Open Interest": [5000, 5200]},
        index=IDX,
    )


@pytest.fixture
def mdp(monkeypatch):
    m = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    monkeypatch.setattr(m, "_get_curve_builder", lambda: _DummyCurveBuilder())
    # The SABR cache misses for every alias - the case that used to silently drop them.
    monkeypatch.setattr(m, "_resolve_delta_from_sabr_cache", lambda **kwargs: None)

    def _fake_eod(*, symbols, start, end, show_tqdm=False, force_refresh=False, **kw):
        _ = start, end, show_tqdm, force_refresh, kw
        out = {}
        for s in symbols:
            if "|" in s:
                out[s] = _opt_frame(0.05)
            else:
                out[s] = _fut_frame()
        return out

    monkeypatch.setattr(m, "_fetch_barchart_eod_series", _fake_eod)
    monkeypatch.setattr(m, "_threadsafe_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(m, "_threadsafe_cache_put", lambda *a, **k: None)
    return m


def _window_calls(m, monkeypatch):
    calls = []
    original = m._get_or_build_barchart_pricer_window

    def traced(**kwargs):
        calls.append(list(kwargs.get("leg_symbols") or []))
        return original(**kwargs)

    monkeypatch.setattr(m, "_get_or_build_barchart_pricer_window", traced)
    return calls


def test_sabr_cache_miss_still_builds_candidate_strikes(mdp, monkeypatch):
    calls = _window_calls(mdp, monkeypatch)
    with mdp:
        mdp._option_snapshot({
            "endpoint": "option_snapshot",
            "symbols": ["SFRZ26|25DC", "SFRZ26|25DP"],
            "timestamp": AS_OF,
            "force_refresh": False,
        })
    assert calls, (
        "no pricer window was requested: the delta aliases were dropped after the SABR "
        "cache missed, instead of falling through to the candidate-strike build"
    )
    assert any(legs for legs in calls), "pricer window requested with no legs"


def test_force_refresh_and_normal_request_take_the_same_path(mdp, monkeypatch):
    """force_refresh should only control cache reuse, never whether the aliases are
    resolved at all."""
    calls = _window_calls(mdp, monkeypatch)
    with mdp:
        for force in (False, True):
            mdp._option_snapshot({
                "endpoint": "option_snapshot",
                "symbols": ["SFRZ26|25DC"],
                "timestamp": AS_OF,
                "force_refresh": force,
            })
    assert len(calls) == 2, f"expected a window build on both passes, got {len(calls)}"
    assert calls[0] and calls[1]
    assert set(calls[0]) == set(calls[1]), (
        "force_refresh changed which candidate strikes were considered"
    )

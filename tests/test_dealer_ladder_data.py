"""Pure tests for the study's loaders and target construction (no DB, no network)."""
import datetime

import numpy as np
import pandas as pd
import pytest

from BT.dealer_ladder import config as cfg
from BT.dealer_ladder import data as D

NY = "America/New_York"


# ------------------------------------------------------------------ symbols
@pytest.mark.parametrize("bucket,cme", [
    ("SFRU26", "SR3U26"), ("SFRZ28", "SR3Z28"),
    ("FFN26", "ZQN26"), ("FFF27", "ZQF27"),
    ("SERN26", "SR1N26"),
])
def test_bucket_cme_round_trip(bucket, cme):
    assert D.bucket_to_cme(bucket) == cme
    assert D.cme_to_bucket(cme) == bucket


def test_cme_to_bucket_passes_through_unknown_roots():
    assert D.cme_to_bucket("XYZH27") == "XYZH27"


# --------------------------------------------------------------- minute grid
def _sparse(tz=NY):
    """Bars at 09:00, 09:03, 09:04 and 10:00 -- deliberately gappy."""
    idx = pd.to_datetime(["2026-07-10 09:00", "2026-07-10 09:03",
                          "2026-07-10 09:04", "2026-07-10 10:00"]).tz_localize(tz)
    return pd.DataFrame({"SFRU26": [96.00, 96.01, 96.005, 96.02]}, index=idx)


def test_to_minute_grid_fills_gaps_and_reports_staleness():
    grid, stale = D.to_minute_grid(_sparse(), ffill_limit_min=30)
    assert len(grid) == 61                              # 09:00..10:00 inclusive
    # 09:01 and 09:02 carry the 09:00 print, 1 and 2 minutes stale
    at = grid.index.tz_convert(NY)
    i1 = at.get_loc(pd.Timestamp("2026-07-10 09:01", tz=NY))
    assert grid["SFRU26"].iloc[i1] == pytest.approx(96.00)
    assert stale["SFRU26"].iloc[i1] == pytest.approx(1.0)
    i2 = at.get_loc(pd.Timestamp("2026-07-10 09:02", tz=NY))
    assert stale["SFRU26"].iloc[i2] == pytest.approx(2.0)
    # a true observation is zero-stale
    i3 = at.get_loc(pd.Timestamp("2026-07-10 09:03", tz=NY))
    assert stale["SFRU26"].iloc[i3] == pytest.approx(0.0)


def test_to_minute_grid_respects_the_ffill_limit():
    """Beyond the limit the last print is too old to stand in for a price."""
    grid, stale = D.to_minute_grid(_sparse(), ffill_limit_min=5)
    at = grid.index.tz_convert(NY)
    i = at.get_loc(pd.Timestamp("2026-07-10 09:30", tz=NY))   # 26 min after 09:04
    assert np.isnan(grid["SFRU26"].iloc[i])
    assert np.isnan(stale["SFRU26"].iloc[i])
    # inside the limit it still fills
    j = at.get_loc(pd.Timestamp("2026-07-10 09:08", tz=NY))
    assert grid["SFRU26"].iloc[j] == pytest.approx(96.005)


def test_to_minute_grid_never_fills_across_sessions():
    idx = pd.to_datetime(["2026-07-10 15:59", "2026-07-13 09:00"]).tz_localize(NY)
    df = pd.DataFrame({"SFRU26": [96.0, 96.5]}, index=idx)
    grid, _ = D.to_minute_grid(df, ffill_limit_min=10_000)
    # only the two observed minutes exist; no bridge across the weekend
    assert len(grid) == 2
    assert grid["SFRU26"].notna().sum() == 2


def test_to_minute_grid_empty_input():
    grid, stale = D.to_minute_grid(pd.DataFrame())
    assert grid.empty and stale.empty


# ------------------------------------------------------------------ targets
def test_price_to_rate_bp():
    df = pd.DataFrame({"SFRU26": [96.00, 95.50]})
    out = D.price_to_rate_bp(df)
    assert out["SFRU26"].tolist() == pytest.approx([400.0, 450.0])


def test_forward_rate_change_is_strictly_forward():
    idx = pd.date_range("2026-07-10 09:00", periods=10, freq="1min", tz=NY)
    rates = pd.DataFrame({"X": np.arange(10.0)}, index=idx)
    fwd = D.forward_rate_change_bp(rates, 3)
    assert fwd["X"].iloc[0] == pytest.approx(3.0)
    # the last 3 rows have no future point inside the sample
    assert fwd["X"].iloc[-3:].isna().all()


def test_forward_rate_change_uses_time_not_row_offset():
    """A gap must not silently shorten the horizon."""
    idx = pd.to_datetime(["2026-07-10 09:00", "2026-07-10 09:01",
                          "2026-07-10 09:30"]).tz_localize(NY)
    rates = pd.DataFrame({"X": [0.0, 1.0, 50.0]}, index=idx)
    fwd = D.forward_rate_change_bp(rates, 1)
    assert fwd["X"].iloc[0] == pytest.approx(1.0)   # 09:01 exists
    assert np.isnan(fwd["X"].iloc[1])               # 09:02 does NOT exist


def test_forward_rate_change_drops_session_crossing_horizons():
    idx = pd.date_range("2026-07-10 15:30", periods=40, freq="1min", tz=NY)
    rates = pd.DataFrame({"X": np.arange(40.0)}, index=idx)
    fwd = D.forward_rate_change_bp(rates, 1440)     # +1 day
    assert fwd["X"].isna().all()


def test_signed_volume_signs_by_bar_direction():
    idx = pd.date_range("2026-07-10 09:00", periods=4, freq="1min", tz=NY)
    closes = pd.DataFrame({"X": [96.00, 96.01, 96.01, 95.99]}, index=idx)
    vols = pd.DataFrame({"X": [10.0, 20.0, 30.0, 40.0]}, index=idx)
    sv = D.signed_volume(closes, vols)
    assert np.isnan(sv["X"].iloc[0])                 # no prior close
    assert sv["X"].iloc[1] == pytest.approx(+20.0)   # up bar
    assert sv["X"].iloc[2] == pytest.approx(0.0)     # unchanged -> ZERO, documented
    assert sv["X"].iloc[3] == pytest.approx(-40.0)   # down bar


def test_signed_volume_aligns_mismatched_columns():
    idx = pd.date_range("2026-07-10 09:00", periods=3, freq="1min", tz=NY)
    closes = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=idx)
    vols = pd.DataFrame({"B": [5.0, 5.0, 5.0]}, index=idx)
    sv = D.signed_volume(closes, vols)
    assert list(sv.columns) == ["A"]
    assert (sv["A"].fillna(0.0) == 0.0).all()        # no volume for A -> zero


# ------------------------------------------------------------ decision grid
def test_decision_grid_is_session_bounded_and_tz_aware():
    grid = D.decision_grid(["2026-07-10"], cfg.SignalConfig())
    assert str(grid.tz) == NY
    assert grid[0] == pd.Timestamp("2026-07-10 08:00", tz=NY)
    assert grid[-1] == pd.Timestamp("2026-07-10 15:55", tz=NY)   # 16:00 exclusive
    assert len(grid) == 96                                       # 8h / 5min


def test_decision_grid_exists_even_on_a_flowless_session():
    """Built from the session window, not from print times."""
    grid = D.decision_grid(["2026-07-10", "2026-07-13"], cfg.SignalConfig())
    assert len(grid) == 192


def test_decision_grid_empty():
    assert len(D.decision_grid([], cfg.SignalConfig())) == 0


def test_trading_days_excludes_federal_holidays():
    days = D.trading_days((datetime.date(2026, 7, 1), datetime.date(2026, 7, 10)))
    assert pd.Timestamp("2026-07-03") not in days     # July 4th observed
    assert pd.Timestamp("2026-07-02") in days
    assert len(days) == 7


# ----------------------------------------------------------------- universe
def _prints_frame():
    rows = []
    def add(unit, direction, method, curve, venue, vintage="v1"):
        rows.append(dict(
            unit_key=unit, dealer_direction=direction, classification_method=method,
            curve_bucket=curve, venue_bucket=venue, code_vintage=vintage,
            bucket_space="FUTURES", bucket_key="SFRU26", delta_dv01=1.0))
    add("keep1", "PAID", "RATE_VS_MID", "CURVE_CLEAN", "D2C_WHITELISTED")
    add("keep2", "RECEIVED", "SPREAD_VS_MID", "CURVE_CLEAN", "D2C_WHITELISTED")
    add("unk", "UNKNOWN", "RATE_VS_MID", "CURVE_CLEAN", "D2C_WHITELISTED")
    add("offmkt", "PAID", "NPV_VS_UPFRONT", "CURVE_CLEAN", "D2C_WHITELISTED")
    add("tick", "PAID", "TICK_RULE", "CURVE_CLEAN", "D2C_WHITELISTED")
    add("suspect", "PAID", "RATE_VS_MID", "CURVE_SUSPECT", "D2C_WHITELISTED")
    add("badvenue", "PAID", "RATE_VS_MID", "CURVE_CLEAN", "VENUE_UNKNOWN")
    add("d2d", "PAID", "RATE_VS_MID", "CURVE_CLEAN", "D2D")
    add("oldvintage", "PAID", "RATE_VS_MID", "CURVE_CLEAN", "D2C_WHITELISTED", "v0")
    return pd.DataFrame(rows)


def test_apply_universe_keeps_only_the_signed_stratum():
    out = D.apply_universe(_prints_frame(), cfg.UniverseConfig())
    assert set(out["unit_key"]) == {"keep1", "keep2", "oldvintage"}


def test_apply_universe_honours_a_pinned_vintage():
    out = D.apply_universe(_prints_frame(),
                           cfg.UniverseConfig(code_vintage="v1"))
    assert set(out["unit_key"]) == {"keep1", "keep2"}


def test_apply_universe_can_include_off_market_as_its_own_stratum():
    off = cfg.UniverseConfig(methods=cfg.OFF_MARKET_METHODS)
    out = D.apply_universe(_prints_frame(), off)
    assert set(out["unit_key"]) == {"offmkt"}


def test_apply_universe_relaxations():
    out = D.apply_universe(_prints_frame(),
                           cfg.UniverseConfig(require_whitelisted_venue=False))
    assert "badvenue" in set(out["unit_key"])
    out2 = D.apply_universe(_prints_frame(),
                            cfg.UniverseConfig(exclude_curve_suspect=False))
    assert "suspect" in set(out2["unit_key"])


def test_exclusion_ladder_attributes_each_removal_to_its_own_gate():
    lad = D.exclusion_ladder(_prints_frame(), cfg.UniverseConfig(code_vintage="v1"))
    by = lad.set_index("step")
    assert by.loc["start: all projected prints", "units"] == 9
    assert by.loc["direction in PAID/RECEIVED", "removed"] == 1          # UNKNOWN
    assert by.loc["classification method in universe", "removed"] == 2   # off-mkt + tick
    assert by.loc["TICK_RULE excluded", "removed"] == 0                  # already gone
    assert by.loc["curve-clean only", "removed"] == 1
    assert by.loc["whitelisted D2C venue only", "removed"] == 2          # unknown + d2d
    assert by.loc["single code vintage", "removed"] == 1
    assert by["units"].iloc[-1] == 2
    # cumulative accounting must close
    assert by["removed"].sum() + by["units"].iloc[-1] == 9


def test_exclusion_ladder_skips_disabled_gates_without_dropping_rows():
    lad = D.exclusion_ladder(_prints_frame(),
                             cfg.UniverseConfig(require_whitelisted_venue=False,
                                                exclude_curve_suspect=False))
    by = lad.set_index("step")
    assert by.loc["curve-clean only", "removed"] == 0
    assert by.loc["whitelisted D2C venue only", "removed"] == 0



def _fake_stirf_module(monkeypatch, fetch):
    """Stand in for MDP.STIRFutures.STIRFutureMDP.

    It must export the SYMBOL HELPERS too: `_to_barchart` imports `_normalize_symbol`
    and `_to_barchart_symbol` from the same module, so a fake that only supplies the
    MDP class breaks the call it is meant to intercept.
    """
    import sys
    import types

    class _Fetcher:
        barchart_timeseries_api = staticmethod(fetch)

    class _MDP:
        def _get_barchart_fetcher(self, **kw):
            return _Fetcher()

    mod = types.ModuleType("MDP.STIRFutures.STIRFutureMDP")
    mod.STIRFutureMDP = lambda **kw: _MDP()
    mod._normalize_symbol = lambda s: s
    mod._to_barchart_symbol = lambda s: s
    mod._from_barchart_symbol = lambda s: s
    monkeypatch.setitem(sys.modules, "MDP.STIRFutures.STIRFutureMDP", mod)
    return mod


# ---------------------------------------------------- the settled-window bars cache
def test_the_cache_key_is_order_stable_and_window_sensitive():
    k = D._bars_cache_key
    assert k(["a", "b"], "2026-01-01", "2026-02-01", ("Close",)) == \
        k(["b", "a"], "2026-01-01", "2026-02-01", ("Close",))
    assert k(["a"], "2026-01-01", "2026-02-01", ("Close",)) != \
        k(["a"], "2026-01-01", "2026-03-01", ("Close",))
    assert k(["a"], "2026-01-01", "2026-02-01", ("Close",)) != \
        k(["a"], "2026-01-01", "2026-02-01", ("Close", "Volume"))


def test_only_a_window_that_has_ENDED_may_be_cached():
    """A session still in progress keeps receiving bars, so caching it would freeze a
    partial day and every later run would silently read the truncated version."""
    assert D._bars_window_is_settled(
        pd.Timestamp.now(tz=NY) - pd.Timedelta(days=2))
    assert not D._bars_window_is_settled(pd.Timestamp.now(tz=NY))
    assert not D._bars_window_is_settled(
        pd.Timestamp.now(tz=NY) + pd.Timedelta(days=1))


def test_a_settled_window_is_served_from_cache_without_refetching(tmp_path, monkeypatch):
    calls = []
    frame = pd.DataFrame({"Close": [96.0, 96.1], "Volume": [10.0, 12.0]},
                         index=pd.date_range("2026-03-02 09:00", periods=2, freq="1min",
                                             tz=NY))

    def _fake_fetch(**kw):
        calls.append(kw)
        return {"SFRU26": frame}

    _fake_stirf_module(monkeypatch, _fake_fetch)

    lo = pd.Timestamp("2026-03-02 00:00", tz=NY)
    hi = pd.Timestamp("2026-03-02 23:59", tz=NY)
    a = D.load_futures_minutes(["SFRU26"], lo, hi, cache_dir=str(tmp_path))
    b = D.load_futures_minutes(["SFRU26"], lo, hi, cache_dir=str(tmp_path))
    assert len(calls) == 1, "the second call must be served from disk"
    assert set(a) == set(b) == {"Close", "Volume"}
    pd.testing.assert_frame_equal(a["Close"], b["Close"])


def test_an_unsettled_window_is_never_cached(tmp_path, monkeypatch):
    calls = []

    def _fake_fetch(**kw):
        calls.append(kw)
        return {"SFRU26": pd.DataFrame(
            {"Close": [96.0]}, index=[pd.Timestamp.now(tz=NY)])}

    _fake_stirf_module(monkeypatch, _fake_fetch)

    now = pd.Timestamp.now(tz=NY)
    for _ in range(2):
        D.load_futures_minutes(["SFRU26"], now - pd.Timedelta(hours=2), now,
                               fields=("Close",), cache_dir=str(tmp_path))
    assert len(calls) == 2, "a live session must be refetched every time"
    assert not list(tmp_path.glob("bars_*.pkl"))


def test_an_empty_result_is_never_cached(tmp_path, monkeypatch):
    """Usually a transient vendor failure. Freezing it would turn one bad call into a
    permanently empty study."""
    calls = []

    def _fake_fetch(**kw):
        calls.append(kw)
        return {}

    _fake_stirf_module(monkeypatch, _fake_fetch)

    lo = pd.Timestamp("2026-03-02 00:00", tz=NY)
    hi = pd.Timestamp("2026-03-02 23:59", tz=NY)
    for _ in range(2):
        D.load_futures_minutes(["SFRU26"], lo, hi, cache_dir=str(tmp_path))
    assert len(calls) == 2
    assert not list(tmp_path.glob("bars_*.pkl"))

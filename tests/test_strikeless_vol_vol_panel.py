import datetime as dt
import math

import pandas as pd
import pytest

from RVUtils.StrikelessVol.conventions import VolQuote
from RVUtils.StrikelessVol.panels import implied_quote, vol_panel


def test_asset_map_covers_all_four_markets():
    from definitions.IRSwaptions import ASSET_IDS_MAP

    for curve in ("USD-SOFR-1D", "EUR-ESTR", "GBP-SONIA", "JPY-TONAR"):
        assert curve in ASSET_IDS_MAP, f"missing swaption coverage for {curve}"
        assert "2y 10y" in set(ASSET_IDS_MAP[curve].values())
        assert "10y 10y" in set(ASSET_IDS_MAP[curve].values())


def test_implied_quote_is_labelled_and_in_bp_per_day():
    # 5.3025 is USD 2y10y's actual, network-verified impliedNormalVolatility
    # print on 2026-08-03 (see task-5-report.md's fix-report addendum). An
    # earlier version of this fixture paired 5.329 -- which is really
    # 2026-07-31's print -- with 2026-08-03, and only passed because of a
    # loose tolerance on the network test below; fixed here too so the two
    # tests agree with each other and with the real data.
    panel = pd.DataFrame(
        {"2y10y": [5.3025]}, index=pd.DatetimeIndex(["2026-08-03"])
    )
    q = implied_quote(panel, "2y10y", pd.Timestamp("2026-08-03"), market="USD")
    assert isinstance(q, VolQuote)
    assert q.measure == "implied"
    assert "USD" in q.underlying and "2y10y" in q.underlying
    assert q.value_bp_day == pytest.approx(5.3025)
    assert q.annual_normals == pytest.approx(5.3025 * math.sqrt(252), abs=1e-6)


@pytest.mark.network
@pytest.mark.slow
def test_usd_vol_panel_history_starts_2017_and_matches_the_desk_level():
    panel = vol_panel(
        "USD-SOFR-1D",
        ["2y 10y", "10y 10y"],
        dt.date(2016, 1, 1),
        dt.date(2026, 8, 3),
    )
    assert panel.index.min() >= pd.Timestamp("2017-01-01")
    assert panel.index.min() <= pd.Timestamp("2017-01-31")
    # 5.3025 is the real 2026-08-03 print; 5.329 is 2026-07-31's (confirmed
    # by directly querying both dates -- see the fix report). Tolerance is
    # tight enough (0.001) to catch a one-day misdating: the 07-31-vs-08-03
    # gap is ~0.0265, about 26x this tolerance.
    assert panel.loc["2026-08-03", "2y10y"] == pytest.approx(5.3025, abs=0.001)
    assert len(panel) > 2000


# ---------------------------------------------------------------------------
# vol_panel caching: mocked-GS regression tests.
#
# gs_quant.data.Dataset.get_data and MDP.IRSwaptions.GSQUANT.ql.grid's
# _ensure_gs_session are monkeypatched so these run under "not network" --
# no real GS call happens, only the caching logic in panels.py is exercised.
#
# Caching is exact-window only (see _cache_path_for_window in panels.py):
# a hit requires the whole (curve_key, structures, start, end) request to
# match a previous one exactly. An earlier incremental-extension design
# (a fetched-interval sidecar letting one cache file answer an arbitrary
# sub-range) produced a sequence of defects -- a cross-schema merge, served
# NaN, evicted rows, a silently gapped read, and finally a sidecar that
# could outlive its parquet and resurrect a phantom coverage claim -- and
# was deleted rather than patched further. These tests cover the design
# that replaced it.
# ---------------------------------------------------------------------------


def _make_fake_get_data():
    """A stand-in for ``Dataset(...).get_data(start=, end=, assetId=)`` that
    records every call and returns a daily-bp row for each business day in
    ``[start, end]`` and each requested assetId.
    """
    calls: list[tuple[dt.date, dt.date, tuple]] = []

    def fake_get_data(self, start, end, assetId):
        calls.append((start, end, tuple(sorted(assetId))))
        dates = pd.bdate_range(start, end)
        rows = [
            {"date": d, "assetId": aid, "impliedNormalVolatility": 5.0}
            for d in dates
            for aid in assetId
        ]
        return pd.DataFrame(rows).set_index("date")

    fake_get_data.calls = calls
    return fake_get_data


def _patch_gs(monkeypatch, fake_get_data) -> None:
    monkeypatch.setattr("gs_quant.data.Dataset.get_data", fake_get_data)
    monkeypatch.setattr(
        "MDP.IRSwaptions.GSQUANT.ql.grid._ensure_gs_session", lambda: None
    )


def test_vol_panel_exact_window_repeat_call_hits_without_a_second_fetch(
    tmp_path, monkeypatch
):
    fake = _make_fake_get_data()
    _patch_gs(monkeypatch, fake)
    cache_path = tmp_path / "vp.parquet"

    p1 = vol_panel(
        "USD-SOFR-1D", ["2y 10y"], dt.date(2020, 1, 1), dt.date(2020, 1, 31),
        cache_path=cache_path,
    )
    assert len(fake.calls) == 1

    p2 = vol_panel(
        "USD-SOFR-1D", ["2y 10y"], dt.date(2020, 1, 1), dt.date(2020, 1, 31),
        cache_path=cache_path,
    )
    assert len(fake.calls) == 1  # exact-window repeat -- cache hit, no second fetch
    pd.testing.assert_frame_equal(p1, p2)


def test_vol_panel_different_window_misses_and_refetches(tmp_path, monkeypatch):
    """A changed [start, end] is a miss, not an extension -- exact-window
    keying means a different request never reuses another window's file.
    """
    fake = _make_fake_get_data()
    _patch_gs(monkeypatch, fake)
    cache_path = tmp_path / "vp.parquet"

    vol_panel(
        "USD-SOFR-1D", ["2y 10y"], dt.date(2020, 1, 1), dt.date(2020, 1, 31),
        cache_path=cache_path,
    )
    assert len(fake.calls) == 1

    vol_panel(
        "USD-SOFR-1D", ["2y 10y"], dt.date(2020, 2, 1), dt.date(2020, 2, 29),
        cache_path=cache_path,
    )
    assert len(fake.calls) == 2  # a different window always triggers a fresh fetch


def test_vol_panel_different_structure_set_uses_a_separate_cache_file(
    tmp_path, monkeypatch
):
    """Schema-isolation sanity check: a different structure set against the
    same ``cache_path`` prefix must not be treated as covering the first
    structure set's request -- it gets its own file
    (``_cache_path_for_window``) and triggers its own fetch.
    """
    fake = _make_fake_get_data()
    _patch_gs(monkeypatch, fake)
    cache_path = tmp_path / "vp.parquet"
    start, end = dt.date(2020, 1, 1), dt.date(2020, 1, 31)

    p_2y10y = vol_panel("USD-SOFR-1D", ["2y 10y"], start, end, cache_path=cache_path)
    p_10y10y = vol_panel("USD-SOFR-1D", ["10y 10y"], start, end, cache_path=cache_path)

    assert len(fake.calls) == 2
    assert list(p_2y10y.columns) == ["2y10y"]
    assert list(p_10y10y.columns) == ["10y10y"]


def test_vol_panel_different_curves_sharing_a_structure_label_do_not_share_a_cache_file(
    tmp_path, monkeypatch
):
    """curve_key is part of the cache fingerprint: two different curves that
    both quote "2y 10y" and share a ``cache_path`` prefix must not collide
    on one file -- each gets its own fetch. Without curve_key in the key,
    the second call here would have been served EUR-ESTR data cached under
    USD-SOFR-1D's request (or vice versa).
    """
    fake = _make_fake_get_data()
    _patch_gs(monkeypatch, fake)
    cache_path = tmp_path / "vp.parquet"
    start, end = dt.date(2020, 1, 1), dt.date(2020, 1, 31)

    p_usd = vol_panel("USD-SOFR-1D", ["2y 10y"], start, end, cache_path=cache_path)
    p_eur = vol_panel("EUR-ESTR", ["2y 10y"], start, end, cache_path=cache_path)

    assert len(fake.calls) == 2  # not a false hit on the second curve
    assert fake.calls[0][2] != fake.calls[1][2]  # different assetIds were requested
    assert list(p_usd.columns) == ["2y10y"]
    assert list(p_eur.columns) == ["2y10y"]

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
# no real GS call happens, only the caching/interval logic in panels.py is
# exercised. This closes the gap flagged in review: the cache path
# previously had zero committed tests, only an uncommitted scratch script.
# ---------------------------------------------------------------------------


def _make_fake_get_data(min_date: dt.date | None = None):
    """A stand-in for ``Dataset(...).get_data(start=, end=, assetId=)`` that
    records every call and returns a daily-bp row for each business day in
    ``[max(start, min_date), end]`` and each requested assetId. ``min_date``
    lets a test simulate a provider's real earliest-history boundary: the
    returned data can start later than the queried ``start`` without that
    being a "gap" (the market didn't exist yet).
    """
    calls: list[tuple[dt.date, dt.date, tuple]] = []

    def fake_get_data(self, start, end, assetId):
        calls.append((start, end, tuple(sorted(assetId))))
        eff_start = max(start, min_date) if min_date else start
        dates = pd.bdate_range(eff_start, end)
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


def test_vol_panel_cache_hit_serves_without_a_second_fetch(tmp_path, monkeypatch):
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
    assert len(fake.calls) == 1  # cache hit -- no second fetch
    pd.testing.assert_frame_equal(p1, p2)


def test_vol_panel_cache_hit_survives_a_start_earlier_than_the_markets_real_history(
    tmp_path, monkeypatch
):
    """The interval sidecar records the *queried* window, not the narrower
    span the returned data happens to span. A repeat call with the exact
    same (early) start must still hit cache even though the first call's
    data began later than requested -- the market not existing yet is not a
    gap.
    """
    fake = _make_fake_get_data(min_date=dt.date(2017, 1, 3))
    _patch_gs(monkeypatch, fake)
    cache_path = tmp_path / "vp.parquet"
    start, end = dt.date(2016, 1, 1), dt.date(2017, 6, 30)

    p1 = vol_panel("USD-SOFR-1D", ["2y 10y"], start, end, cache_path=cache_path)
    assert len(fake.calls) == 1
    assert p1.index.min() == pd.Timestamp("2017-01-03")  # data started later than the query

    p2 = vol_panel("USD-SOFR-1D", ["2y 10y"], start, end, cache_path=cache_path)
    assert len(fake.calls) == 1  # still a hit
    pd.testing.assert_frame_equal(p1, p2)


def test_vol_panel_disjoint_windows_do_not_silently_serve_a_gap(tmp_path, monkeypatch):
    """CRITICAL regression: two disjoint fetch windows for the same
    structure set/cache_path must never be read together as if the calendar
    time between them were covered. combine_first happily unions the two
    windows in the parquet; an endpoint-only cache check
    (``cached.index.min() <= start and cached.index.max() >= end``) would
    wrongly call that a hit, and the missing years in between produce no NaN
    to trip the "no NaN in the served slice" guard, since they're absent
    rows, not null cells. A request spanning both windows must trigger a
    genuine third fetch instead of silently serving a panel with a hole.
    """
    fake = _make_fake_get_data()
    _patch_gs(monkeypatch, fake)
    cache_path = tmp_path / "vp.parquet"

    # Endpoints deliberately chosen to be business days themselves (Monday
    # and Friday), so cached.index.min()/max() land exactly on start/end
    # with no weekend rounding -- otherwise an endpoint-only check can
    # accidentally fail on a boundary technicality (a weekend `end` that
    # bdate_range never produces) without ever exercising the real bug.
    window_a = (dt.date(2015, 1, 5), dt.date(2015, 6, 30))   # Mon .. Tue
    window_b = (dt.date(2018, 1, 2), dt.date(2018, 6, 29))   # Tue .. Fri
    span = (dt.date(2015, 1, 5), dt.date(2018, 6, 29))

    vol_panel("USD-SOFR-1D", ["2y 10y"], *window_a, cache_path=cache_path)
    vol_panel("USD-SOFR-1D", ["2y 10y"], *window_b, cache_path=cache_path)
    assert len(fake.calls) == 2

    panel = vol_panel("USD-SOFR-1D", ["2y 10y"], *span, cache_path=cache_path)

    # A genuine third fetch: an endpoint-only check would have wrongly
    # reported a cache hit here (both bounds match exactly) even though the
    # ~2.5 years between the two windows were never queried.
    assert len(fake.calls) == 3
    # And the freshly (re)fetched panel actually covers the old "gap" --
    # no missing business days in the middle.
    assert panel.index.min() == pd.Timestamp("2015-01-05")
    assert panel.index.max() == pd.Timestamp("2018-06-29")
    assert pd.Timestamp("2016-06-15") in panel.index


def test_vol_panel_different_structure_set_uses_a_separate_cache_file(
    tmp_path, monkeypatch
):
    """Schema-isolation sanity check: a different structure set against the
    same ``cache_path`` prefix must not be treated as covering the first
    structure set's request -- it gets its own file (``_cache_path_for_legs``)
    and triggers its own fetch.
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

"""Offline tests for the CME-vs-LCH (CCP) basis cache and panel builder.

Every test in this module runs with outbound HTTP hard-blocked (see the autouse
``_no_network`` fixture), so a test can only pass by reading the disk cache or
the in-repo coverage workbook.  Tests that need the *real* warmed cache skip
cleanly when the warm marker is absent.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd
import pytest

from Caching.DiskCacheMixin import DiskCacheMixin
from MDP.IRClearingHouseBasisSwaps.ccp_basis_cache import (
    SIGN_REFERENCE,
    SPOT_TENOR_LADDER,
    CCPBasisCache,
    CCPBasisCacheMiss,
    basis_panel,
    default_coverage_path,
    find_asset,
    find_asset_pair,
    load_coverage,
    verify_sign_convention,
)

CCY, INDEX = "USD", "SOFR"
REAL_START = datetime.date(2018, 4, 27)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any outbound request fails the test rather than silently working."""
    import requests

    def _blocked(self, method, url, *args, **kwargs):  # pragma: no cover
        raise AssertionError(f"network access attempted in an offline test: {method} {url}")

    monkeypatch.setattr(requests.Session, "request", _blocked)


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    """A CCPBasisCache rooted in tmp_path, guaranteed cold."""
    monkeypatch.setattr(DiskCacheMixin, "CACHE_ROOT", tmp_path)
    return CCPBasisCache(cache_name="TEST_CCP_BASIS")


@pytest.fixture(scope="module")
def coverage():
    return load_coverage()


@pytest.fixture
def real_cache():
    """The production cache, skipped unless the 10y legs are actually warm."""
    cache = CCPBasisCache()
    end = datetime.date(2026, 8, 20)
    for ch in ("LCH", "CME"):
        if not cache.is_warm(CCY, INDEX, "10y", ch, REAL_START, end):
            pytest.skip(
                f"CCP basis cache is cold for {CCY} {INDEX} 10y {ch} "
                f"({REAL_START}..{end}); warm it with "
                f"CCPBasisCache().warm(datetime.date(2018,1,1), datetime.date.today())"
            )
    return cache


def _seed(cache, tenor, lch, cme, dates, warm_from=None, warm_to=None):
    """Write both legs for ``dates`` and mark the window warm."""
    for d in dates:
        if lch is not None:
            cache.put_leg(CCY, INDEX, tenor, "LCH", d, lch)
        if cme is not None:
            cache.put_leg(CCY, INDEX, tenor, "CME", d, cme)
    lo = warm_from or dates[0]
    hi = warm_to or dates[-1]
    for ch in ("LCH", "CME"):
        cache.mark_warm(CCY, INDEX, tenor, ch, lo, hi)


# ---------------------------------------------------------------------------
# (b) coverage path resolves from the module, not a hard-coded checkout
# ---------------------------------------------------------------------------


def test_default_coverage_path_is_derived_from_this_module():
    import MDP.IRClearingHouseBasisSwaps.ccp_basis_cache as mod

    got = default_coverage_path()
    mdp_dir = Path(mod.__file__).resolve().parents[1]
    assert got == mdp_dir / "IRSwaps" / "GSQUANT" / "COVERAGE" / "IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx"
    assert got.exists(), f"coverage workbook missing at {got}"
    # It must live under the same tree as the module that resolves it -- the
    # old default was an absolute path into a different checkout.
    assert mdp_dir in got.parents


def test_mdp_default_coverage_path_matches_module_resolution():
    from MDP.IRClearingHouseBasisSwaps.IRClearingHouseBasisSwapsMDP import IRClearingHouseBasisSwapsMDP

    assert IRClearingHouseBasisSwapsMDP().coverage_path == default_coverage_path()


# ---------------------------------------------------------------------------
# asset resolution: the substring-match regression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tenor", ["1y", "2y", "3y", "4y", "5y", "7y", "10y", "15y", "20y", "25y", "30y"])
def test_find_asset_pair_resolves_the_requested_tenor_exactly(coverage, tenor):
    """Regression: substring matching resolved 5y -> the 15y asset on BOTH legs,
    and 1y -> LCH-30y against CME-12y (a curve spread served as a CCP basis)."""
    pair = find_asset_pair(coverage, ccy=CCY, index=INDEX, tenor=tenor)
    names = {}
    for side, key, ch in (("a", "asset_id_a", "LCH"), ("b", "asset_id_b", "CME")):
        row = coverage[coverage["assetId"] == pair[key]]
        assert len(row) == 1
        assert row["tenor"].iloc[0] == tenor, f"{ch} leg resolved to {row['tenor'].iloc[0]}, wanted {tenor}"
        assert row["start"].iloc[0] == "0b"
        assert row["clearing_house"].iloc[0] == ch
        names[side] = str(row["name"].iloc[0])
    # the two legs must be the same instrument, differing only in the CCP
    assert names["a"].replace(" LCH ", " CME ") == names["b"]
    assert pair["asset_id_a"] != pair["asset_id_b"]


def test_find_asset_raises_on_unknown_tenor(coverage):
    with pytest.raises(ValueError, match="No LCH asset"):
        find_asset(coverage, CCY, INDEX, "13579y", "LCH")


def test_legacy_fetcher_entry_point_agrees(coverage):
    """gs_quant_fetcher.find_asset_pair takes a RAW coverage frame; it must
    resolve identically now that it delegates to the exact matcher."""
    from MDP.IRClearingHouseBasisSwaps.gs_quant_fetcher import find_asset_pair as legacy

    raw = pd.read_excel(default_coverage_path())
    for tenor in ("1y", "5y", "10y", "30y"):
        assert legacy(raw, ccy=CCY, index=INDEX, tenor=tenor) == find_asset_pair(
            coverage, ccy=CCY, index=INDEX, tenor=tenor
        )


# ---------------------------------------------------------------------------
# (c) sign and units
# ---------------------------------------------------------------------------


def test_verify_sign_convention_reproduces_the_measured_reference():
    assert verify_sign_convention() == pytest.approx(SIGN_REFERENCE["lch_minus_cme_bp"], abs=1e-9)
    assert SIGN_REFERENCE["rate_lch"] < SIGN_REFERENCE["rate_cme"]


def test_panel_is_long_minus_short_in_bp(tmp_cache):
    """LCH 4.00% vs CME 3.98% must read +2.0 bp, not -2.0 and not +0.0002."""
    dates = [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)]
    _seed(tmp_cache, "10y", lch=0.0400, cme=0.0398, dates=dates)

    panel = basis_panel(dates[0], dates[-1], tenors=["10y"], cache=tmp_cache)
    assert list(panel.columns) == ["10y"]
    assert panel["10y"].tolist() == pytest.approx([2.0, 2.0], abs=1e-9)
    assert panel.attrs["sign_convention"] == "LCH minus CME"
    assert panel.attrs["units"] == "bp"

    flipped = basis_panel(dates[0], dates[-1], tenors=["10y"], long_ch="CME", short_ch="LCH", cache=tmp_cache)
    assert flipped["10y"].tolist() == pytest.approx([-2.0, -2.0], abs=1e-9)
    assert flipped.attrs["sign_convention"] == "CME minus LCH"


def test_panel_index_is_dates_and_columns_are_tenors(tmp_cache):
    dates = [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)]
    _seed(tmp_cache, "5y", lch=0.0400, cme=0.0399, dates=dates)
    _seed(tmp_cache, "10y", lch=0.0400, cme=0.0398, dates=dates)

    panel = basis_panel(dates[0], dates[-1], tenors=["5y", "10y"], cache=tmp_cache)
    assert list(panel.columns) == ["5y", "10y"]
    assert isinstance(panel.index, pd.DatetimeIndex)
    assert panel.index.name == "date"
    assert panel.loc[pd.Timestamp(dates[0]), "5y"] == pytest.approx(1.0)
    assert panel.loc[pd.Timestamp(dates[0]), "10y"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# (a) cache behaviour: a miss must never masquerade as data
# ---------------------------------------------------------------------------


def test_cold_cache_raises_instead_of_returning_empty(tmp_cache):
    with pytest.raises(CCPBasisCacheMiss):
        basis_panel("2024-01-02", "2024-01-03", tenors=["10y"], cache=tmp_cache)


def test_cold_cache_with_allow_network_false_does_not_fetch(tmp_cache):
    """allow_network defaults to False; the _no_network fixture would turn any
    fetch into an AssertionError, so a CCPBasisCacheMiss proves no attempt."""
    with pytest.raises(CCPBasisCacheMiss):
        basis_panel("2024-01-02", "2024-01-03", tenors=["10y"], cache=tmp_cache, allow_network=False)


def test_read_leg_guards_the_warm_marker_itself(tmp_cache):
    """basis_panel checks warmth before calling read_leg, so read_leg's own
    guard needs its own test -- without this, dropping the guard leaves a cold
    read returning an empty Series that a caller would read as "no basis"."""
    d1, d2 = datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)
    # rates present but NO warm marker: the data is there, the provenance is not
    tmp_cache.put_leg(CCY, INDEX, "10y", "LCH", d1, 0.0400)
    tmp_cache.put_leg(CCY, INDEX, "10y", "LCH", d2, 0.0401)
    assert tmp_cache.warm_spans(CCY, INDEX, "10y", "LCH") == []

    with pytest.raises(CCPBasisCacheMiss):
        tmp_cache.read_leg(CCY, INDEX, "10y", "LCH", d1, d2)

    # the escape hatch is explicit, and only then does it return data
    unguarded = tmp_cache.read_leg(CCY, INDEX, "10y", "LCH", d1, d2, require_warm=False)
    assert unguarded.tolist() == pytest.approx([0.0400, 0.0401])


def test_read_leg_raises_on_a_fully_cold_leg(tmp_cache):
    with pytest.raises(CCPBasisCacheMiss):
        tmp_cache.read_leg(CCY, INDEX, "30y", "CME", "2024-01-02", "2024-01-03")


def test_read_outside_the_warm_span_raises(tmp_cache):
    dates = [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)]
    _seed(tmp_cache, "10y", lch=0.04, cme=0.0398, dates=dates)
    assert tmp_cache.is_warm(CCY, INDEX, "10y", "LCH", dates[0], dates[-1])
    # one day past the warm span
    with pytest.raises(CCPBasisCacheMiss):
        basis_panel(dates[0], datetime.date(2024, 1, 4), tenors=["10y"], cache=tmp_cache)


def test_gap_between_two_warm_spans_is_not_claimed_warm(tmp_cache):
    _seed(tmp_cache, "10y", lch=0.04, cme=0.0398, dates=[datetime.date(2024, 1, 2)])
    _seed(tmp_cache, "10y", lch=0.04, cme=0.0398, dates=[datetime.date(2024, 3, 1)])
    spans = tmp_cache.warm_spans(CCY, INDEX, "10y", "LCH")
    assert len(spans) == 2, spans
    assert not tmp_cache.is_warm(CCY, INDEX, "10y", "LCH", datetime.date(2024, 1, 2), datetime.date(2024, 3, 1))
    with pytest.raises(CCPBasisCacheMiss):
        basis_panel("2024-01-02", "2024-03-01", tenors=["10y"], cache=tmp_cache)


def test_adjacent_warm_spans_merge(tmp_cache):
    for ch in ("LCH", "CME"):
        tmp_cache.mark_warm(CCY, INDEX, "10y", ch, datetime.date(2024, 1, 1), datetime.date(2024, 1, 31))
        tmp_cache.mark_warm(CCY, INDEX, "10y", ch, datetime.date(2024, 2, 1), datetime.date(2024, 2, 29))
    assert tmp_cache.warm_spans(CCY, INDEX, "10y", "LCH") == [["2024-01-01", "2024-02-29"]]
    assert tmp_cache.is_warm(CCY, INDEX, "10y", "LCH", datetime.date(2024, 1, 15), datetime.date(2024, 2, 15))


def test_missing_day_inside_a_warm_span_is_dropped_not_forward_filled(tmp_cache):
    """LCH prints on ~62 days a year that CME does not; those dates must leave
    the panel entirely rather than difference a stale leg against a fresh one."""
    d1, d2, d3 = datetime.date(2024, 1, 2), datetime.date(2024, 1, 3), datetime.date(2024, 1, 4)
    for d in (d1, d2, d3):
        tmp_cache.put_leg(CCY, INDEX, "10y", "LCH", d, 0.0400)
    for d in (d1, d3):  # CME did not print on d2
        tmp_cache.put_leg(CCY, INDEX, "10y", "CME", d, 0.0398)
    for ch in ("LCH", "CME"):
        tmp_cache.mark_warm(CCY, INDEX, "10y", ch, d1, d3)

    panel = basis_panel(d1, d3, tenors=["10y"], cache=tmp_cache)
    assert [t.date() for t in panel.index] == [d1, d3]
    assert pd.Timestamp(d2) not in panel.index


def test_cache_key_carries_ccy_index_tenor_clearing_house_and_date():
    key = CCPBasisCache.rate_key("usd", "sofr", "10Y", "lch", "2026-08-10")
    assert key == "rate|USD|SOFR|10y|LCH|2026-08-10"
    for part in ("USD", "SOFR", "10y", "LCH", "2026-08-10"):
        assert part in key
    # different clearing houses and different dates must not collide
    assert CCPBasisCache.rate_key("USD", "SOFR", "10y", "CME", "2026-08-10") != key
    assert CCPBasisCache.rate_key("USD", "SOFR", "10y", "LCH", "2026-08-11") != key
    assert CCPBasisCache.rate_key("USD", "OIS", "10y", "LCH", "2026-08-10") != key


def test_rates_are_cached_as_decimal_not_bp(tmp_cache):
    d = datetime.date(2024, 1, 2)
    _seed(tmp_cache, "10y", lch=0.0400, cme=0.0398, dates=[d])
    leg = tmp_cache.read_leg(CCY, INDEX, "10y", "LCH", d, d)
    assert leg.iloc[0] == pytest.approx(0.0400)


# ---------------------------------------------------------------------------
# MDP wiring
# ---------------------------------------------------------------------------


def test_mdp_get_pricer_signs_basis_as_a_minus_b(tmp_cache):
    from MDP.IRClearingHouseBasisSwaps.IRClearingHouseBasisSwapsMDP import IRClearingHouseBasisSwapsMDP

    d = datetime.date(2024, 1, 2)
    _seed(tmp_cache, "10y", lch=0.0400, cme=0.0398, dates=[d])

    mdp = IRClearingHouseBasisSwapsMDP(cache=tmp_cache)
    pricer = mdp.get_pricer({"tenor": "10y", "start": d, "end": d})
    row = pricer.basis_data.iloc[0]
    assert row["rate_a"] == pytest.approx(0.0400)  # clearing_house_a == LCH
    assert row["rate_b"] == pytest.approx(0.0398)  # clearing_house_b == CME
    assert row["basis_bps"] == pytest.approx(2.0)
    assert row["basis_bps"] == pytest.approx((row["rate_a"] - row["rate_b"]) * 1e4)
    assert pricer.meta_data["sign_convention"] == "LCH minus CME"


def test_mdp_get_pricer_is_offline_by_default(tmp_cache):
    from MDP.IRClearingHouseBasisSwaps.IRClearingHouseBasisSwapsMDP import IRClearingHouseBasisSwapsMDP

    mdp = IRClearingHouseBasisSwapsMDP(cache=tmp_cache)
    with pytest.raises(CCPBasisCacheMiss):
        mdp.get_pricer({"tenor": "10y", "start": "2024-01-02", "end": "2024-01-03"})


# ---------------------------------------------------------------------------
# integration against the real warmed cache (skips when cold)
# ---------------------------------------------------------------------------


def test_real_cache_10y_reference_date(real_cache):
    d = datetime.date(2026, 8, 10)
    panel = basis_panel(d, d, tenors=["10y"], cache=real_cache)
    assert panel.loc[pd.Timestamp(d), "10y"] == pytest.approx(SIGN_REFERENCE["lch_minus_cme_bp"], abs=1e-6)
    lch = real_cache.read_leg(CCY, INDEX, "10y", "LCH", d, d).iloc[0]
    cme = real_cache.read_leg(CCY, INDEX, "10y", "CME", d, d).iloc[0]
    assert lch == pytest.approx(SIGN_REFERENCE["rate_lch"], abs=5e-9)
    assert cme == pytest.approx(SIGN_REFERENCE["rate_cme"], abs=5e-9)
    assert lch < cme, "LCH must print BELOW CME on the reference date"


def test_real_cache_history_starts_2018_04_27(real_cache):
    panel = basis_panel(datetime.date(2018, 1, 1), datetime.date(2026, 8, 20), tenors=["10y"], cache=real_cache)
    assert panel.index.min().date() == REAL_START
    # a 2021-2026 backtest needs daily, not sporadic, coverage
    per_year = panel["10y"].groupby(panel.index.year).size()
    assert per_year.loc[2021:2025].min() >= 240, per_year.to_dict()


def test_real_cache_panel_is_in_bp_and_spans_the_ladder(real_cache):
    panel = basis_panel(datetime.date(2021, 1, 1), datetime.date(2026, 8, 20), tenors=SPOT_TENOR_LADDER, cache=real_cache)
    assert list(panel.columns) == list(SPOT_TENOR_LADDER)
    assert panel.notna().all(axis=None)
    # bp-scaled: the CCP basis lives in single-digit bp. A decimal/percent slip
    # would land at 1e-4 or 1e-2 of this.
    assert panel.abs().max().max() < 25.0
    assert panel.abs().max().max() > 0.1

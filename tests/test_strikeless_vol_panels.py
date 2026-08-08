import datetime as dt

import pandas as pd
import pytest

from RVUtils.StrikelessVol.panels import (
    _cache_path_for_legs,
    forward_rate_panel,
    spread_panel,
)
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair


class _FakeSwap:
    def __init__(self, key):
        self.key = key


class _FakeCurve:
    """Returns a rate that encodes the leg, so column mapping is verifiable."""

    RATES = {"10Y10Y": 0.0400, "20Y10Y": 0.0342}

    def build_irswap(self, fwd=None, tenor=None, **kwargs):
        return _FakeSwap(f"{fwd}{tenor}")

    def fair_rate(self, swap):
        return self.RATES[swap.key]


class _FakeMDP:
    def __init__(self):
        self.bulk_calls = 0

    def bulk_get_data(self, request):
        self.bulk_calls += 1
        return {ts: _FakeCurve() for ts in request["timestamps"]}


def test_panel_has_one_column_per_leg_and_decimal_rates():
    dates = [dt.date(2026, 7, 30), dt.date(2026, 7, 31)]
    legs = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    mdp = _FakeMDP()

    panel = forward_rate_panel("USD-OIS", dates, legs, mdp=mdp)

    assert list(panel.columns) == ["10Y10Y", "20Y10Y"]
    assert isinstance(panel.index, pd.DatetimeIndex)
    assert panel.loc["2026-07-30", "10Y10Y"] == pytest.approx(0.0400)
    assert panel.loc["2026-07-31", "20Y10Y"] == pytest.approx(0.0342)


def test_panel_uses_one_bulk_call_not_one_per_date():
    dates = [dt.date(2026, 7, d) for d in (27, 28, 29, 30, 31)]
    mdp = _FakeMDP()
    forward_rate_panel("USD-OIS", dates, [ForwardLeg("10Y", "10Y")], mdp=mdp)
    assert mdp.bulk_calls == 1


def test_missing_dates_are_dropped_not_filled():
    class _GappyMDP(_FakeMDP):
        def bulk_get_data(self, request):
            out = super().bulk_get_data(request)
            out.pop(request["timestamps"][1], None)
            return out

    # max_missing_frac=1.0: this test is about dropped-not-filled, not about
    # the systemic-failure guard (see the two tests below), so it opts out of
    # that guard explicitly rather than being sized to dodge its default.
    dates = [dt.date(2026, 7, 29), dt.date(2026, 7, 30), dt.date(2026, 7, 31)]
    panel = forward_rate_panel(
        "USD-OIS", dates, [ForwardLeg("10Y", "10Y")], mdp=_GappyMDP(),
        max_missing_frac=1.0,
    )
    assert len(panel) == 2
    assert pd.Timestamp("2026-07-30") not in panel.index


def test_spread_panel_is_long_minus_short_in_bp():
    panel = pd.DataFrame(
        {"10Y10Y": [0.0400], "20Y10Y": [0.0342]},
        index=pd.DatetimeIndex(["2026-08-03"]),
    )
    pair = ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))
    s = spread_panel(panel, pair)
    assert s.iloc[0] == pytest.approx(-58.0)


class _ExplodingCurve:
    """A curve whose pricing path is broken for every leg on every date."""

    def build_irswap(self, fwd=None, tenor=None, **kwargs):
        raise RuntimeError("pricing path broken")

    def fair_rate(self, swap):  # pragma: no cover - build_irswap already raises
        raise RuntimeError("pricing path broken")


class _AllExplodeMDP(_FakeMDP):
    def bulk_get_data(self, request):
        self.bulk_calls += 1
        return {ts: _ExplodingCurve() for ts in request["timestamps"]}


def test_systemic_pricing_failure_raises_loudly_instead_of_returning_near_empty():
    dates = [dt.date(2026, 7, d) for d in (27, 28, 29, 30, 31)]
    with pytest.raises(ValueError, match="USD-OIS"):
        forward_rate_panel(
            "USD-OIS", dates, [ForwardLeg("10Y", "10Y")], mdp=_AllExplodeMDP()
        )


def test_one_missing_date_out_of_twenty_does_not_raise():
    class _OneGapMDP(_FakeMDP):
        def bulk_get_data(self, request):
            out = super().bulk_get_data(request)
            out.pop(request["timestamps"][0], None)
            return out

    dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(20)]
    panel = forward_rate_panel(
        "USD-OIS", dates, [ForwardLeg("10Y", "10Y")], mdp=_OneGapMDP()
    )
    assert len(panel) == 19


def test_live_key_from_bulk_get_data_raises_a_clear_error():
    class _LiveMDP(_FakeMDP):
        def bulk_get_data(self, request):
            self.bulk_calls += 1
            return {"live": _FakeCurve()}

    with pytest.raises(ValueError, match="live"):
        forward_rate_panel(
            "USD-OIS", [dt.date.today()], [ForwardLeg("10Y", "10Y")], mdp=_LiveMDP()
        )


def test_cache_miss_when_cached_legs_do_not_cover_the_request(tmp_path):
    cache_path = tmp_path / "panel.parquet"
    dates = [dt.date(2026, 7, 30), dt.date(2026, 7, 31)]

    # Cache written with only one leg.
    forward_rate_panel(
        "USD-OIS", dates, [ForwardLeg("10Y", "10Y")], mdp=_FakeMDP(), cache_path=cache_path
    )

    # Requesting a second leg the cache doesn't have must re-fetch, not KeyError.
    mdp = _FakeMDP()
    panel = forward_rate_panel(
        "USD-OIS",
        dates,
        [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")],
        mdp=mdp,
        cache_path=cache_path,
    )
    assert list(panel.columns) == ["10Y10Y", "20Y10Y"]
    assert mdp.bulk_calls == 1


def test_cache_write_merges_new_dates_instead_of_overwriting(tmp_path):
    cache_path = tmp_path / "panel.parquet"
    leg = [ForwardLeg("10Y", "10Y")]
    dates_1_3 = [dt.date(2026, 7, d) for d in (27, 28, 29)]
    dates_4_5 = [dt.date(2026, 7, d) for d in (30, 31)]

    forward_rate_panel("USD-OIS", dates_1_3, leg, mdp=_FakeMDP(), cache_path=cache_path)
    forward_rate_panel("USD-OIS", dates_4_5, leg, mdp=_FakeMDP(), cache_path=cache_path)

    # cache_path is a prefix, not the literal file -- the same leg set on
    # both calls resolves to one derived, leg-set-specific file.
    on_disk = pd.read_parquet(_cache_path_for_legs(cache_path, ["10Y10Y"]))
    assert len(on_disk) == 5
    for d in dates_1_3 + dates_4_5:
        assert pd.Timestamp(d) in on_disk.index


def test_cache_never_serves_or_persists_a_partial_row(tmp_path):
    """Guards the complete-or-absent invariant: a cached row must carry every
    column its own file has, or it must not be in that file at all -- never a
    silent NaN served back to a caller asking for the full leg set.

    Each leg set is its own file (see ``_cache_path_for_legs``), so a
    narrower fetch for a different leg set cannot contaminate the wider
    cache's file at all -- there is nothing to evict or NaN-out. What this
    test actually guards is the end state: after both writes, neither file
    has a NaN, and a subsequent both-legs request over the full date union
    still gets a clean, complete re-fetch rather than a served NaN.
    """
    cache_path = tmp_path / "panel.parquet"
    legs_both = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    leg_one = [ForwardLeg("10Y", "10Y")]
    dates_1_3 = [dt.date(2026, 7, d) for d in (27, 28, 29)]
    dates_4_5 = [dt.date(2026, 7, d) for d in (30, 31)]

    # Step 1: cache both legs for dates 1-3.
    forward_rate_panel(
        "USD-OIS", dates_1_3, legs_both, mdp=_FakeMDP(), cache_path=cache_path
    )

    # Step 2: fetch only ONE leg for dates 4-5 against the same cache_path
    # prefix -- a different leg set, so (by design) a different file.
    forward_rate_panel(
        "USD-OIS", dates_4_5, leg_one, mdp=_FakeMDP(), cache_path=cache_path
    )

    both_legs_file = _cache_path_for_legs(cache_path, ["10Y10Y", "20Y10Y"])
    one_leg_file = _cache_path_for_legs(cache_path, ["10Y10Y"])
    assert not pd.read_parquet(both_legs_file).isna().to_numpy().any()
    assert not pd.read_parquet(one_leg_file).isna().to_numpy().any()

    # The both-legs file is untouched by the narrower write -- still exactly
    # its original 3 rows, none contaminated.
    both_legs_on_disk = pd.read_parquet(both_legs_file)
    assert len(both_legs_on_disk) == 3
    for d in dates_1_3:
        assert pd.Timestamp(d) in both_legs_on_disk.index

    # Step 3: request both legs over the full 5-date union. The both-legs
    # file only has dates 1-3, so this must be a clean re-fetch, never a
    # served NaN.
    mdp = _FakeMDP()
    panel = forward_rate_panel(
        "USD-OIS", dates_1_3 + dates_4_5, legs_both, mdp=mdp, cache_path=cache_path
    )
    assert mdp.bulk_calls == 1
    assert len(panel) == 5
    assert not panel.isna().to_numpy().any()


def test_cache_read_rejects_a_slice_containing_nan(tmp_path):
    """Read-side half of the complete-or-absent invariant: even a hand-written
    or legacy cache file with a NaN cell must never be served -- it is a miss.
    """
    cache_path = tmp_path / "panel.parquet"
    dates = [dt.date(2026, 7, 30), dt.date(2026, 7, 31)]
    legs = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    corrupt = pd.DataFrame(
        {"10Y10Y": [0.0400, float("nan")], "20Y10Y": [0.0342, 0.0342]},
        index=pd.DatetimeIndex([pd.Timestamp(d) for d in dates]),
    )
    corrupt.to_parquet(_cache_path_for_legs(cache_path, ["10Y10Y", "20Y10Y"]))

    mdp = _FakeMDP()
    panel = forward_rate_panel(
        "USD-OIS", dates, legs, mdp=mdp, cache_path=cache_path,
    )
    assert mdp.bulk_calls == 1  # the NaN in the cached slice forced a re-fetch
    assert not panel.isna().to_numpy().any()


def test_narrow_then_wide_does_not_evict_the_narrow_cache(tmp_path):
    """The eviction repro: caching a narrow leg set, then fetching a wider
    leg set for disjoint dates against the same cache_path, must not disturb
    the narrow cache -- each leg set has its own file, so a subsequent
    request for the original narrow leg set over its original dates hits the
    cache cleanly instead of losing rows a blanket dropna once evicted.
    """
    cache_path = tmp_path / "panel.parquet"
    leg_a = [ForwardLeg("10Y", "10Y")]
    legs_ab = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    dates_1_3 = [dt.date(2026, 7, d) for d in (27, 28, 29)]
    dates_4_6 = [dt.date(2026, 7, 30), dt.date(2026, 7, 31), dt.date(2026, 8, 1)]

    # Cache the narrow leg set for dates 1-3.
    forward_rate_panel("USD-OIS", dates_1_3, leg_a, mdp=_FakeMDP(), cache_path=cache_path)

    # A wider leg set over disjoint dates, same cache_path prefix.
    forward_rate_panel(
        "USD-OIS", dates_4_6, legs_ab, mdp=_FakeMDP(), cache_path=cache_path
    )

    # Re-requesting the narrow leg set over its original dates must still
    # hit the cache -- zero fresh fetches -- and return all three rows.
    mdp = _FakeMDP()
    panel = forward_rate_panel(
        "USD-OIS", dates_1_3, leg_a, mdp=mdp, cache_path=cache_path
    )
    assert mdp.bulk_calls == 0
    assert len(panel) == 3
    for d in dates_1_3:
        assert pd.Timestamp(d) in panel.index


def test_wide_then_narrow_persists_and_then_hits_not_refetches_forever(tmp_path):
    """The Minor: a narrow request against dates a wider cache does not yet
    have must persist its own (separately-keyed) file after the first fetch,
    then be served from that cache on a repeat of the identical request --
    not re-fetch on every single call forever.
    """
    cache_path = tmp_path / "panel.parquet"
    leg_a = [ForwardLeg("10Y", "10Y")]
    legs_ab = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    dates_1_3 = [dt.date(2026, 7, d) for d in (27, 28, 29)]
    dates_4_6 = [dt.date(2026, 7, 30), dt.date(2026, 7, 31), dt.date(2026, 8, 1)]

    # Cache the wide leg set for dates 1-3.
    forward_rate_panel(
        "USD-OIS", dates_1_3, legs_ab, mdp=_FakeMDP(), cache_path=cache_path
    )

    # First narrow request over dates the wide cache does not have: one fetch.
    mdp_first = _FakeMDP()
    forward_rate_panel(
        "USD-OIS", dates_4_6, leg_a, mdp=mdp_first, cache_path=cache_path
    )
    assert mdp_first.bulk_calls == 1

    # Repeating the identical narrow request must now hit -- zero fresh
    # fetches -- not re-fetch again.
    mdp_second = _FakeMDP()
    panel = forward_rate_panel(
        "USD-OIS", dates_4_6, leg_a, mdp=mdp_second, cache_path=cache_path
    )
    assert mdp_second.bulk_calls == 0
    assert len(panel) == 3


def test_cache_path_for_legs_is_order_independent(tmp_path):
    """The same legs passed in two different orders must resolve to the same
    file, so a caller's leg ordering can't fragment the cache.
    """
    assert _cache_path_for_legs(
        "panel.parquet", ["10Y10Y", "20Y10Y"]
    ) == _cache_path_for_legs("panel.parquet", ["20Y10Y", "10Y10Y"])

    cache_path = tmp_path / "panel.parquet"
    dates = [dt.date(2026, 7, 30), dt.date(2026, 7, 31)]
    leg_10 = ForwardLeg("10Y", "10Y")
    leg_20 = ForwardLeg("20Y", "10Y")

    forward_rate_panel(
        "USD-OIS", dates, [leg_10, leg_20], mdp=_FakeMDP(), cache_path=cache_path
    )

    # Same legs, reversed order: must hit the same file -- zero fresh fetches.
    mdp = _FakeMDP()
    panel = forward_rate_panel(
        "USD-OIS", dates, [leg_20, leg_10], mdp=mdp, cache_path=cache_path
    )
    assert mdp.bulk_calls == 0
    assert list(panel.columns) == ["20Y10Y", "10Y10Y"]


@pytest.mark.network
@pytest.mark.slow
def test_real_usd_panel_matches_desk_levels():
    """The 2026-08-03 USD 10y10y/20y10y slope is deeply inverted (~-58bp)."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    dates = [dt.date(2026, 7, 31), dt.date(2026, 8, 3)]
    legs = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    # max_missing_frac=1.0: this test checks the sign and level of a real
    # slope, not provider health -- a single dropped date out of 2 requested
    # is 50% missing, which would otherwise raise before the assertions below
    # are reached and turn a graceful degrade into a hard failure.
    panel = forward_rate_panel(
        "USD-OIS", dates, legs, mdp=IRSwapsMDP(source="GSQUANT-RL"),
        max_missing_frac=1.0,
    )
    assert len(panel) >= 1
    pair = ForwardPair("USD", "USD-OIS", *legs)
    slope = spread_panel(panel, pair)
    assert slope.iloc[-1] < 0.0            # inverted
    assert -120.0 < slope.iloc[-1] < -10.0  # and in the right neighbourhood

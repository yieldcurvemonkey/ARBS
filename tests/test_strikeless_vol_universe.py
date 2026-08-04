import pytest

from RVUtils.StrikelessVol.universe import (
    ALL_PAIRS,
    MARKET_MAX_POINT_YEARS,
    PLACEBO_PAIRS,
    ForwardLeg,
    ForwardPair,
    supported_pairs,
    tenor_years,
)


def test_tenor_years():
    assert tenor_years("10Y") == 10.0
    assert tenor_years("6M") == pytest.approx(0.5)
    with pytest.raises(ValueError):
        tenor_years("10X")


def test_leg_geometry():
    leg = ForwardLeg("20Y", "10Y")
    assert leg.label == "20Y10Y"
    assert leg.fwd_years == 20.0
    assert leg.tail_years == 10.0
    assert leg.end_years == 30.0


def test_pair_required_point_is_the_longest_end():
    p = ForwardPair(
        market="USD",
        curve_name="USD-OIS",
        short=ForwardLeg("10Y", "10Y"),
        long=ForwardLeg("20Y", "10Y"),
    )
    assert p.name == "USD 10Y10Y/20Y10Y"
    assert p.required_point_years == 30.0


def test_measured_provider_coverage():
    # From MDP/IRSwaps/GSQUANT/COVERAGE/IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx
    assert MARKET_MAX_POINT_YEARS["USD"] == 30.0
    assert MARKET_MAX_POINT_YEARS["JPY"] == 30.0
    assert MARKET_MAX_POINT_YEARS["EUR"] == 50.0
    assert MARKET_MAX_POINT_YEARS["GBP"] == 50.0


def test_usd_25y10y_is_not_in_the_universe():
    # The 35y USD point is not published at any GS tenor. It must never appear.
    usd_ends = {
        p.required_point_years for p in ALL_PAIRS if p.market == "USD"
    }
    assert max(usd_ends) == 30.0


def test_supported_pairs_filters_on_observed_coverage():
    pairs = [
        ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")),
        ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("25Y", "10Y")),
    ]
    kept = supported_pairs(pairs, MARKET_MAX_POINT_YEARS)
    assert len(kept) == 1
    assert kept[0].long.label == "20Y10Y"


def test_every_registered_pair_is_supported_by_its_market():
    for p in ALL_PAIRS:
        assert p.required_point_years <= MARKET_MAX_POINT_YEARS[p.market]


def test_placebo_pairs_are_short_dated_and_disjoint_from_the_universe():
    assert PLACEBO_PAIRS
    for p in PLACEBO_PAIRS:
        assert p.required_point_years <= 10.0
    assert not (set(PLACEBO_PAIRS) & set(ALL_PAIRS))

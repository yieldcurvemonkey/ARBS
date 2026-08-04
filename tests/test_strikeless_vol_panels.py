import datetime as dt

import pandas as pd
import pytest

from RVUtils.StrikelessVol.panels import forward_rate_panel, spread_panel
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

    # 10 dates so the one drop (10%) sits comfortably under the default
    # max_missing_frac=0.2 systemic-failure guard -- this test is about
    # dropped-not-filled, not about that guard (see the two tests below).
    dates = [dt.date(2026, 7, d) for d in range(22, 32)]
    panel = forward_rate_panel(
        "USD-OIS", dates, [ForwardLeg("10Y", "10Y")], mdp=_GappyMDP()
    )
    assert len(panel) == 9
    assert pd.Timestamp(dates[1]) not in panel.index


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

    on_disk = pd.read_parquet(cache_path)
    assert len(on_disk) == 5
    for d in dates_1_3 + dates_4_5:
        assert pd.Timestamp(d) in on_disk.index


@pytest.mark.network
@pytest.mark.slow
def test_real_usd_panel_matches_desk_levels():
    """The 2026-08-03 USD 10y10y/20y10y slope is deeply inverted (~-58bp)."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    dates = [dt.date(2026, 7, 31), dt.date(2026, 8, 3)]
    legs = [ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y")]
    panel = forward_rate_panel(
        "USD-OIS", dates, legs, mdp=IRSwapsMDP(source="GSQUANT-RL")
    )
    assert len(panel) >= 1
    pair = ForwardPair("USD", "USD-OIS", *legs)
    slope = spread_panel(panel, pair)
    assert slope.iloc[-1] < 0.0            # inverted
    assert -120.0 < slope.iloc[-1] < -10.0  # and in the right neighbourhood

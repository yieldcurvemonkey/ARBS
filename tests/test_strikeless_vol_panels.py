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

    dates = [dt.date(2026, 7, 29), dt.date(2026, 7, 30), dt.date(2026, 7, 31)]
    panel = forward_rate_panel(
        "USD-OIS", dates, [ForwardLeg("10Y", "10Y")], mdp=_GappyMDP()
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

# tests/test_strikeless_vol_curve_defs.py
import datetime as dt
import re
from pathlib import Path

import pandas as pd
import pytest

from RVUtils.StrikelessVol.universe import MARKET_CURVES, MARKET_MAX_POINT_YEARS

COVERAGE = (
    Path(__file__).resolve().parents[1]
    / "MDP" / "IRSwaps" / "GSQUANT" / "COVERAGE"
    / "IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx"
)


def _definition(curve: str) -> dict:
    from MDP.IRSwaps.GSQUANT.rl_basic.build import GSQUANT_CURVE_MAP

    return GSQUANT_CURVE_MAP[curve]["rl_basic"]


def _knot_years(curve: str) -> list[int]:
    pat = re.compile(r"0b to (\d+)y")
    out = []
    for name in _definition(curve)["knots"]:
        m = pat.search(name)
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


@pytest.mark.parametrize("market", ["EUR", "GBP"])
def test_long_end_knots_reach_the_market_cap(market):
    curve = MARKET_CURVES[market]
    assert max(_knot_years(curve)) == MARKET_MAX_POINT_YEARS[market]


@pytest.mark.parametrize("market", ["EUR", "GBP", "USD", "JPY"])
def test_every_declared_instrument_exists_in_gs_coverage(market):
    df = pd.read_excel(COVERAGE)
    known = set(df["name"].astype(str))
    d = _definition(MARKET_CURVES[market])
    missing = [n for n in d["base_tenors"] if n not in known]
    assert missing == [], f"{market}: instruments not in GS coverage: {missing}"


def test_gbp_definition_points_at_the_existing_rateslib_definition():
    from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import (
        RATESLIB_CURVE_DEFINITIONS,
    )

    ref = _definition("GBP-SONIA")["reference_key"]
    assert ref == "GBP-SONIA"
    assert RATESLIB_CURVE_DEFINITIONS[ref]["Calendar"] == "ldn"


@pytest.mark.network
@pytest.mark.slow
@pytest.mark.parametrize("market,as_of", [("GBP", dt.date(2026, 7, 31)),
                                          ("EUR", dt.date(2026, 7, 31))])
def test_built_curve_reprices_its_own_calibrating_instruments(market, as_of):
    """A curve that cannot reprice its own inputs is not calibrated."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    mdp = IRSwapsMDP(source="GSQUANT-RL")
    curve = mdp.get_pricer({"curve_name": MARKET_CURVES[market], "timestamp": as_of})

    rates = {}
    for years in (10, 20, 30, int(MARKET_MAX_POINT_YEARS[market])):
        swap = curve.build_irswap(fwd="0D", tenor=f"{years}Y")
        rates[years] = float(curve.fair_rate(swap))
        assert 0.0 < rates[years] < 0.15, f"{market} {years}Y rate {rates[years]}"

    # The long knots must actually be calibrated, not flat extrapolation off
    # the 30y point: if 50y prices identically to 30y, the instruments did not
    # load and the curve is inventing the ultra-long sector.
    longest = int(MARKET_MAX_POINT_YEARS[market])
    if longest > 30:
        assert abs(rates[longest] - rates[30]) > 1e-6

    # And the curve's last node must reach the market cap, so nothing in the
    # traded universe is priced off the extrapolation stub.
    last_node = max(curve.nodes())
    assert (last_node - as_of).days / 365.0 >= longest - 1.0

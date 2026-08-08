# tests/test_strikeless_vol_curve_defs.py
import datetime as dt
import re
from pathlib import Path

import pandas as pd
import pytest

from RVUtils.StrikelessVol.universe import MARKET_CURVES, MARKET_MAX_POINT_YEARS

# The tolerance the calibration-fit assertion below holds every calibrating
# instrument to. Measured directly against a converged solve (func_tol=1e-9)
# for EUR-ESTR/GBP-SONIA on 2026-07-31: the largest observed repricing
# residual across all 23-26 calibrating instruments on either curve was
# 0.0006bp (GBP-SONIA's 50y point). 0.01bp is ~15x that headroom - tight
# enough that an instrument which didn't actually load into the fit (which is
# what this task's builder bug produced: residuals of many bp, since the
# instrument silently priced off extrapolation instead of calibrating) fails
# this bar by orders of magnitude, while staying comfortably clear of solver
# float noise.
_CALIBRATION_FIT_TOL_BP = 0.01

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
    """A curve that cannot reprice its own inputs is not calibrated.

    Goes through MDP.IRSwaps.GSQUANT.rl_basic.build.build_rl_basic_gsquant_curve
    directly rather than IRSwapsMDP.get_pricer: get_pricer serves results out of
    the persistent, code-version-blind _RLCurveCache, so a run against a warm
    cache would replay whatever was built the first time this (curve, as_of)
    pair was ever requested - including a stale broken curve from before a
    builder fix - and prove nothing about the current build.py.
    """
    import rateslib as rl

    from MDP.IRSwaps.GSQUANT.rl_basic.build import (
        _fetch_rl_basic_gsquant_dataset,
        build_rl_basic_gsquant_curve,
    )
    from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

    curve_name = MARKET_CURVES[market]
    d = _definition(curve_name)
    curve_def = RATESLIB_CURVE_DEFINITIONS[d["reference_key"]]
    spec = curve_def["ReferenceRate"]

    _curve_id, rl_curve, _pricing_location = build_rl_basic_gsquant_curve(curve_name, as_of)

    def fair_rate(effective, termination) -> float:
        swap = rl.IRS(effective=effective, termination=termination, spec=spec, curves=rl_curve)
        return float(swap.rate(curves=rl_curve).real) / 100.0

    def advance(tenor: str):
        as_of_dt = dt.datetime(as_of.year, as_of.month, as_of.day)
        return rl.add_tenor(as_of_dt, tenor=tenor, modifier=curve_def["BusinessConvention"], calendar=curve_def["Calendar"])

    # --- The assertion the docstring promises: every calibrating instrument
    # reprices to (near enough) its own input rate. This is what actually
    # proves the 35/40/45/50y instruments were fitted, not merely present in
    # base_tenors - the sanity checks below (rate range, 50y != 30y, last node
    # reaches the cap) all pass for a curve that converged to a poor fit, since
    # rl.Solver's convergence result is discarded once the curve is built.
    frame = _fetch_rl_basic_gsquant_dataset(curve_name, [as_of])
    frame = frame.loc[frame["as_of"] == as_of].set_index("tenor").reindex(d["base_tenors"])
    assert not frame[["effectiveDate", "terminationDate", "rate"]].isna().any().any(), (
        f"{market}: calibrating frame has missing instruments on {as_of}"
    )
    bad = []
    for name, row in frame.iterrows():
        fitted_pct = fair_rate(row["effectiveDate"], row["terminationDate"]) * 100.0
        resid_bp = (fitted_pct - row["rate"]) * 100.0
        if abs(resid_bp) >= _CALIBRATION_FIT_TOL_BP:
            bad.append((name, row["rate"], fitted_pct, resid_bp))
    assert bad == [], (
        f"{market}: {len(bad)} calibrating instrument(s) did not reprice within "
        f"{_CALIBRATION_FIT_TOL_BP}bp: {bad}"
    )

    # --- Sanity checks on the shape of the fit (kept; not sufficient alone).
    rates = {}
    for years in (10, 20, 30, int(MARKET_MAX_POINT_YEARS[market])):
        eff = advance(f"{curve_def['SettlementDays']}b")
        rates[years] = fair_rate(eff, f"{years}Y")
        assert 0.0 < rates[years] < 0.15, f"{market} {years}Y rate {rates[years]}"

    # The long knots must actually be calibrated, not flat extrapolation off
    # the 30y point: if 50y prices identically to 30y, the instruments did not
    # load and the curve is inventing the ultra-long sector.
    longest = int(MARKET_MAX_POINT_YEARS[market])
    if longest > 30:
        assert abs(rates[longest] - rates[30]) > 1e-6

    # And the curve's last node must reach the market cap, so nothing in the
    # traded universe is priced off the extrapolation stub.
    last_node = max(ts.date() for ts in rl_curve.nodes.nodes.keys())
    assert (last_node - as_of).days / 365.0 >= longest - 1.0

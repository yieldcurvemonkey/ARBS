"""Tests for RVUtils.FlyVsVol.view_overlay against the verified 2026-07-27 example.

Fixture (verified live 2026-07-27): view = 70% hike at Oct-28 and Dec-9 each,
independent, hold elsewhere, base 3.92. Candidates: long U26-Z26-H27 fly @ +7.5bp,
Z26 4.125/4.375 rate-call spread @ 10.25bp, short Z26 future @ 4.145.
Expected: E_view = +17.12 / +3.89 / +12.50 bp; worst = -7.5 / -10.25 / -22.5.
"""
import datetime

import numpy as np
import pytest
from scipy.stats import norm

from RVUtils.FlyVsVol import ContractMarginal
from RVUtils.FlyVsVol.view_overlay import (
    Expression,
    FuturesLeg,
    OptionLeg,
    encode_view,
    price_expressions,
    view_vs_market_bins,
)

W_U26 = (datetime.date(2026, 9, 16), datetime.date(2026, 12, 16))
W_Z26 = (datetime.date(2026, 12, 16), datetime.date(2027, 3, 17))
W_H27 = (datetime.date(2027, 3, 17), datetime.date(2027, 6, 16))

VIEW = encode_view(
    {
        datetime.date(2026, 10, 28): {0: 0.30, 1: 0.70},
        datetime.date(2026, 12, 9): {0: 0.30, 1: 0.70},
    },
    base_rate=3.92,
)

FLY = Expression(
    label="long U26-Z26-H27 fly @7.5",
    futures=(
        FuturesLeg("SFRU26", -1.0, W_U26, 3.99),
        FuturesLeg("SFRZ26", +2.0, W_Z26, 4.145),
        FuturesLeg("SFRH27", -1.0, W_H27, 4.225),
    ),
)
PUT_SPREAD = Expression(
    label="Z26 4.125/4.375 rate-call spread",
    options=(
        OptionLeg("SFRZ26", "rate_call", 4.125, +1.0, 20.25, W_Z26),
        OptionLeg("SFRZ26", "rate_call", 4.375, -1.0, 10.00, W_Z26),
    ),
)
SHORT_FUT = Expression(
    label="short Z26 future",
    futures=(FuturesLeg("SFRZ26", +1.0, W_Z26, 4.145),),
)


def test_verified_fixture_evs():
    res = {r.label: r for r in price_expressions(VIEW, [FLY, PUT_SPREAD, SHORT_FUT])}
    assert res[FLY.label].e_view_bp == pytest.approx(17.12, abs=0.05)
    assert res[PUT_SPREAD.label].e_view_bp == pytest.approx(3.89, abs=0.05)
    assert res[SHORT_FUT.label].e_view_bp == pytest.approx(12.50, abs=0.05)
    assert res[FLY.label].worst_bp == pytest.approx(-7.5, abs=0.05)
    assert res[PUT_SPREAD.label].worst_bp == pytest.approx(-10.25, abs=0.05)
    assert res[SHORT_FUT.label].worst_bp == pytest.approx(-22.5, abs=0.05)


def test_ranking_and_convexity_fields():
    results = price_expressions(VIEW, [FLY, PUT_SPREAD, SHORT_FUT])
    assert results[0].label == FLY.label  # best E/|worst| ratio first
    r = results[0]
    assert r.ratio == pytest.approx(17.12 / 7.5, abs=0.02)
    assert r.best_bp == pytest.approx(27.7, abs=0.1)
    assert 0 <= r.p_win <= 1
    assert len(r.scenario_table) == 4
    assert sum(p for p, _ in r.scenario_table) == pytest.approx(1.0, abs=1e-12)


def test_option_premium_accounting():
    res = price_expressions(VIEW, [PUT_SPREAD])[0]
    assert res.premium_bp == pytest.approx(10.25)
    # no-hike scenario loses exactly the premium
    worst = min(pnl for _, pnl in res.scenario_table)
    assert worst == pytest.approx(-10.25, abs=1e-9)


def test_view_probs_validation():
    with pytest.raises(ValueError):
        encode_view({datetime.date(2026, 10, 28): {0: 0.5, 1: 0.4}}, base_rate=3.92)


def test_view_vs_market_bins():
    grid = np.linspace(3.0, 5.5, 2001)
    marginal = ContractMarginal(
        symbol="SFRZ26", grid_rate=grid, cdf=norm.cdf(grid, 4.145, 0.45),
        forward_rate=4.145,
    )
    table = view_vs_market_bins(VIEW, marginal, W_Z26)
    assert sum(v for v, _, _ in table.values()) == pytest.approx(1.0, abs=1e-9)
    # three terminal outcomes: 3.92 / 4.17 / 4.42
    assert set(round(k, 2) for k in table) == {3.92, 4.17, 4.42}
    p_view, p_mkt, edge = table[max(table)]
    assert p_view == pytest.approx(0.49, abs=1e-9)
    assert edge == pytest.approx(p_view - p_mkt, abs=1e-12)

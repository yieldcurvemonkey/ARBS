"""Tests for RVUtils.FlyVsVol.convergence: skew attribution + package construction."""
import datetime
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.stats import norm

from RVUtils.FlyVsVol import ContractMarginal
from RVUtils.FlyVsVol.convergence import (
    WingQuote,
    convergence_package,
    skew_attribution,
)
from RVUtils.FlyVsVol.metrics import build_fly_snapshot

MUS = (3.99, 4.145, 4.225)


def normal_marginal(sym, mu, sigma, n=4001, span=6.0, **kw):
    grid = np.linspace(mu - span * sigma, mu + span * sigma, n)
    return ContractMarginal(
        symbol=sym, grid_rate=grid, cdf=norm.cdf(grid, mu, sigma), forward_rate=mu, **kw
    )


def skewed_marginal(sym, mu, sigma, jump=1.0, w=0.10, n=6001):
    """Mixture 0.9*N(mu, sigma) + w*N(mu+jump, sigma): mean > median (mm > 0)."""
    lo, hi = mu - 6 * sigma, mu + jump + 6 * sigma
    grid = np.linspace(lo, hi, n)
    cdf = (1 - w) * norm.cdf(grid, mu, sigma) + w * norm.cdf(grid, mu + jump, sigma)
    return ContractMarginal(symbol=sym, grid_rate=grid, cdf=cdf, forward_rate=mu + w * jump)


@pytest.fixture()
def skewed_snapshot():
    legs = [
        skewed_marginal("F", MUS[0], 0.30, jump=0.8, w=0.08),
        skewed_marginal("B", MUS[1], 0.45, jump=0.5, w=0.05),
        skewed_marginal("K", MUS[2], 0.60, jump=1.2, w=0.12),
    ]
    return build_fly_snapshot(*legs, as_of=datetime.date(2026, 7, 27))


def wing_quotes_for(snapshot, prem=5.0):
    quotes = {}
    for m in snapshot.legs:
        quotes[m.symbol] = [
            WingQuote(symbol=m.symbol, right="P", strike_rate=k, premium_bp=prem,
                      delta_abs=12.0)
            for k in np.round(np.arange(m.forward_rate + 0.25,
                                        m.forward_rate + 1.30, 0.25), 2)
        ]
    return quotes


def test_attribution_identity(skewed_snapshot):
    att = skew_attribution(skewed_snapshot)
    assert att.skew_g_bp == pytest.approx(
        skewed_snapshot.fly_mean_bp - skewed_snapshot.fly_median_path_bp, abs=1e-9
    )
    assert att.fit_residual_bp == pytest.approx(
        skewed_snapshot.fly_bp - skewed_snapshot.fly_mean_bp, abs=1e-9
    )
    assert att.skew_g_bp + att.fit_residual_bp == pytest.approx(
        skewed_snapshot.tail_rent_bp, abs=1e-9
    )
    total = att.contrib_front_bp + att.contrib_belly_bp + att.contrib_back_bp
    assert total == pytest.approx(att.skew_g_bp, abs=1e-9)
    assert att.contrib_front_bp == pytest.approx(-att.mm_front_bp, abs=1e-9)
    assert att.contrib_belly_bp == pytest.approx(2 * att.mm_belly_bp, abs=1e-9)


def test_attribution_symmetric_zero():
    legs = [normal_marginal(s, m, 0.4) for s, m in zip(("F", "B", "K"), MUS)]
    att = skew_attribution(build_fly_snapshot(*legs))
    assert abs(att.skew_g_bp) < 0.1
    assert abs(att.mm_front_bp) < 0.05


def test_attribution_dominant_leg(skewed_snapshot):
    att = skew_attribution(skewed_snapshot)
    contribs = {
        "F": att.contrib_front_bp, "B": att.contrib_belly_bp, "K": att.contrib_back_bp,
    }
    assert att.dominant_leg == max(contribs, key=lambda s: abs(contribs[s]))


def test_package_long_g_sides_and_lots(skewed_snapshot):
    quotes = wing_quotes_for(skewed_snapshot)
    pkg = convergence_package(skewed_snapshot, quotes, scale_lots=100,
                              target_g_bp=0.0, mode="curvature")
    # skewed marginals give G < 0 -> long_G -> sell front/back wings, buy belly
    assert pkg.direction == "long_G"
    sides = {leg.quote.symbol: leg.side for leg in pkg.legs}
    lots = {leg.quote.symbol: leg.lots for leg in pkg.legs}
    assert sides == {"F": "sell", "B": "buy", "K": "sell"}
    assert lots == {"F": 100, "B": 200, "K": 100}
    assert pkg.expected_reversion_bp == pytest.approx(-pkg.current_g_bp)


def test_package_dominant_mode(skewed_snapshot):
    quotes = wing_quotes_for(skewed_snapshot)
    pkg = convergence_package(skewed_snapshot, quotes, scale_lots=150, mode="dominant")
    att = skew_attribution(skewed_snapshot)
    assert len(pkg.legs) == 1
    assert pkg.legs[0].quote.symbol == att.dominant_leg
    assert pkg.legs[0].lots == 150


def test_package_strike_selection_and_hedge(skewed_snapshot):
    quotes = wing_quotes_for(skewed_snapshot)
    pkg = convergence_package(skewed_snapshot, quotes, scale_lots=100,
                              target_percentile=90.0, mode="curvature")
    for leg in pkg.legs:
        m = next(x for x in skewed_snapshot.legs if x.symbol == leg.quote.symbol)
        target = m.percentile(90)
        ks = [q.strike_rate for q in quotes[leg.quote.symbol]]
        assert abs(leg.quote.strike_rate - target) == pytest.approx(
            min(abs(k - target) for k in ks), abs=1e-9
        )
        # selling a price-put (delta_abs 12) leaves +0.12/lot price delta -> hedge sells futures
        expected = -leg.lots * 12.0 / 100.0
        if leg.side == "buy":
            expected = -expected
        assert leg.hedge_futures_lots == pytest.approx(expected)


def test_package_short_g_flips():
    # negative-jump mixture on wings -> mm < 0 -> G > 0 -> short_G
    legs = [
        skewed_marginal("F", MUS[0], 0.30, jump=-0.8, w=0.08),
        skewed_marginal("B", MUS[1], 0.45, jump=-0.2, w=0.02),
        skewed_marginal("K", MUS[2], 0.60, jump=-1.2, w=0.12),
    ]
    snap = build_fly_snapshot(*legs)
    pkg = convergence_package(snap, wing_quotes_for(snap), scale_lots=100,
                              target_g_bp=0.0, mode="curvature")
    assert pkg.direction == "short_G"
    sides = {leg.quote.symbol: leg.side for leg in pkg.legs}
    assert sides == {"F": "buy", "B": "sell", "K": "buy"}


def test_package_premium_accounting(skewed_snapshot):
    pkg = convergence_package(skewed_snapshot, wing_quotes_for(skewed_snapshot, prem=5.0),
                              scale_lots=100, mode="curvature")
    # sell 100 + sell 100 collect; buy 200 pays -> net (100+100-200)*5 = 0
    assert pkg.net_premium_bp_lots == pytest.approx(0.0)
    sells = sum(l.premium_bp_total for l in pkg.legs if l.side == "sell")
    assert sells == pytest.approx(2 * 100 * 5.0)


def test_schedule_uses_option_expiry():
    legs = [
        normal_marginal("F", MUS[0], 0.3, option_expiry=datetime.date(2026, 9, 11)),
        normal_marginal("B", MUS[1], 0.45, option_expiry=datetime.date(2026, 12, 11)),
        normal_marginal("K", MUS[2], 0.6, option_expiry=datetime.date(2027, 3, 12)),
    ]
    snap = build_fly_snapshot(*legs)
    pkg = convergence_package(snap, wing_quotes_for(snap), scale_lots=10)
    syms = [s for s, _, _ in pkg.schedule]
    dates = [d for _, d, _ in pkg.schedule]
    assert syms == ["F", "B", "K"]
    assert dates == sorted(dates)


def test_from_bl_result_option_expiry():
    grid = np.linspace(3.0, 5.0, 101)
    bl = SimpleNamespace(
        strike_grid_rate=grid,
        rnd_cumulative=norm.cdf(grid, 4.0, 0.3),
        input=SimpleNamespace(forward_rate=4.0, expiry_date=datetime.date(2027, 3, 12)),
        forward_residual_bp=0.0, pre_normalization_mass=1.0,
        ghost_mass_fraction=0.0, warnings=(),
    )
    m = ContractMarginal.from_bl_result("SFRH27", bl)
    assert m.option_expiry == datetime.date(2027, 3, 12)


def test_to_row_has_attribution_columns(skewed_snapshot):
    row = skewed_snapshot.to_row()
    for key in ("mm_front_bp", "mm_belly_bp", "mm_back_bp", "skew_g_bp",
                "fit_residual_bp", "dominant_leg"):
        assert key in row
    assert row["skew_g_bp"] == pytest.approx(
        skewed_snapshot.fly_mean_bp - skewed_snapshot.fly_median_path_bp, abs=1e-9
    )

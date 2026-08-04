# tests/test_strikeless_vol_greeks_control.py
import pytest
import rateslib as rl

from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.greeks import (
    analytic_leg_gamma,
    build_package,
    gamma_by_h,
    package_dv01,
    package_gamma,
)
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

REF = rl.dt(2026, 8, 3)


@pytest.fixture(scope="module")
def curve():
    nodes = {REF: 1.0}
    nodes.update({rl.dt(2026 + y, 8, 3): 1.0 / (1.04 ** y) for y in range(1, 41)})
    handle = rl.Curve(nodes=nodes, convention="act365f", calendar="nyc", id="flat4")
    return RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=handle,
        # rateslib 2.1.1 crashes in _set_fixings on an empty pd.Series and
        # fails later at .npv() on None; only the NoInput sentinel works.
        # See tests/test_strikeless_vol_greeks.py for the full note. Legs
        # here are forward-starting 10-20y out and need no historical fixings.
        fixings=rl.NoInput(0),
        meta_data={"reference_curve_name": "USD-OIS"},
    )


@pytest.fixture(scope="module")
def pkg(curve):
    pair = ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))
    return build_package(curve, pair, package_dv01_usd=100_000.0, sign=FLATTENER)


def test_package_dv01_is_neutral_at_inception(curve, pkg):
    assert package_dv01(curve, pkg) == pytest.approx(0.0, abs=50.0)


def test_bumped_gamma_matches_the_analytic_replication_formula(curve, pkg):
    """The control: an independent closed form, not the bump code."""
    analytic = analytic_leg_gamma(curve, pkg.short) + analytic_leg_gamma(curve, pkg.long)
    bumped = package_gamma(curve, pkg, h_bp=25.0)
    assert analytic != 0.0
    assert bumped == pytest.approx(analytic, rel=0.02)


def test_each_leg_matches_the_control_on_its_own(curve, pkg):
    """The package sum agrees partly by cancellation, so check the legs too.

    The two legs' residuals point opposite ways (the short leg's bumped
    convexity is more negative than analytic, the long leg's more positive),
    so summing them flatters the agreement. Pinning each leg separately is
    what makes the package number evidence rather than coincidence.
    """
    handle = curve.handle()
    for swap in (pkg.short, pkg.long):
        base = swap.npv(curves=handle).real
        up = swap.npv(curves=handle.shift(25.0)).real
        dn = swap.npv(curves=handle.shift(-25.0)).real
        bumped = (up + dn - 2.0 * base) / (25.0 ** 2)
        assert bumped == pytest.approx(analytic_leg_gamma(curve, swap), rel=0.02)


def test_flattener_convexity_is_positive(curve, pkg):
    """Receiving the longer forward against the shorter is long convexity."""
    assert package_gamma(curve, pkg, h_bp=25.0) > 0.0


def test_gamma_is_reported_per_h_not_averaged(curve, pkg):
    g = gamma_by_h(curve, pkg, h_bps=(10.0, 25.0, 50.0))
    assert set(g) == {10.0, 25.0, 50.0}
    assert all(v > 0 for v in g.values())
    # h-dependence is a property of the instrument, so it must be visible.
    # Distinct values are the assertion: if the three ever collapsed to one
    # number, convexity would have been averaged across move size, which is
    # the thing this function exists to prevent.
    assert len(set(g.values())) == 3
    spread = (max(g.values()) - min(g.values())) / max(g.values())
    assert 0.0 < spread < 0.05  # small over 10-50bp, but not zero


def test_control_bites_when_the_bump_unit_is_wrong(curve, pkg, monkeypatch):
    """Mutation check: if h were passed as a decimal instead of bp, this fails.

    A checking tool that is itself wrong reports success. This asserts the
    control can tell the difference.

    Scaling ``shift``'s argument by 1e-4 is exactly "25bp handed to an API
    that wanted a decimal": the curve moves 0.0025bp while ``package_gamma``
    still divides by ``h_bp**2 = 625``, so the bumped number lands ~1e-8 of
    the truth. The analytic side never touches ``shift``, so it is unmoved
    and the 2% band rejects the mutant.
    """
    import RVUtils.StrikelessVol.greeks as g

    real_shift = rl.Curve.shift
    monkeypatch.setattr(
        rl.Curve, "shift", lambda self, spread, **kw: real_shift(self, spread * 1e-4, **kw)
    )
    analytic = analytic_leg_gamma(curve, pkg.short) + analytic_leg_gamma(curve, pkg.long)
    bumped = g.package_gamma(curve, pkg, h_bp=25.0)
    assert analytic != 0.0
    assert bumped != pytest.approx(analytic, rel=0.02)


def test_bp_read_as_a_decimal_cannot_even_be_repriced(curve, pkg, monkeypatch):
    """The same 1e4 unit error in the other direction.

    Scaling ``shift``'s argument *up* by 1e4 asks rateslib for a 250,000bp
    parallel bump, and it raises ``OverflowError`` while building the shifted
    curve (``rateslib/curves/curves.py:960``) rather than handing back a
    wrong number. Asserted explicitly so that direction of the mutation is
    on record as caught rather than silently skipped.
    """
    import RVUtils.StrikelessVol.greeks as g

    real_shift = rl.Curve.shift
    monkeypatch.setattr(
        rl.Curve, "shift", lambda self, spread, **kw: real_shift(self, spread * 1e4, **kw)
    )
    with pytest.raises(OverflowError):
        g.package_gamma(curve, pkg, h_bp=25.0)

# tests/test_strikeless_vol_constructions.py
"""Task 20 (H9): the fly-hedged package and the same-sector pair.

Two things in here are independent of the code they check, and they are the
two that matter:

* ``test_ladder_sums_to_the_parallel_dv01`` ties the tent-bump ladder to
  ``greeks``' own ``rl.Curve.shift`` DV01 -- a different bump primitive, a
  different compounding convention, computed by code this module does not
  touch.
* ``test_a_pc2_shaped_curve_shock_confirms_the_hedge_by_repricing`` reprices
  the actual instruments under a curve shock shaped like the fitted loading,
  and asks whether the hedged book's P&L is smaller than the unhedged one's.
  It never looks at a ladder, a metric or a projection, so it cannot be
  satisfied by a linear-algebra identity that happens to be self-consistent.

Everything else is structural or a refusal.
"""
import numpy as np
import pandas as pd
import pytest
import rateslib as rl

from RVUtils.StrikelessVol.constructions import (
    CONSTRUCTIONS,
    FLY_HEDGED,
    HEDGED_FACTORS,
    SAME_SECTOR,
    TWO_LEG,
    _pca_norm,
    _shock_handle,
    _tent_matrix,
    build_shocks,
    carry_per_vega,
    carry_per_vega_after_costs,
    compare_constructions,
    cost_bp_round_trip,
    factor_exposures,
    fly_hedge_weights,
    key_rate_ladder,
    ladder_tenor_years,
    legs_roll_usd,
    pca_metric,
    same_sector_pair,
)
from RVUtils.StrikelessVol.conventions import FLATTENER, STEEPENER
from RVUtils.StrikelessVol.costs import FREE, CostSchedule
from RVUtils.StrikelessVol.greeks import (
    _reprice_dv01,
    build_package,
    daily_dcf,
    daily_roll_usd,
    package_dv01,
)
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair
from RVUtils.df_based_pca_risk_model import fit_curve_pca_from_timeseries
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

REF = rl.dt(2026, 8, 3)
PAIR = ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))

#: The ladder/PCA grid. Ends at 30Y because that is the longest point USD-OIS
#: publishes (``universe.MARKET_MAX_POINT_YEARS``), so no bucket here asks the
#: curve for a rate no provider quotes.
GRID_TENORS = ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "25Y", "30Y")
GRID_COLS = tuple(f"USD-OIS {t} OUTRIGHT RATE" for t in GRID_TENORS)


# --------------------------------------------------------------- fixtures


def _curve_from(rate_of_year, ref=REF, cid="c"):
    nodes = {ref: 1.0}
    for y in range(1, 41):
        nodes[rl.dt(ref.year + y, ref.month, ref.day)] = 1.0 / ((1.0 + rate_of_year(y)) ** y)
    handle = rl.Curve(nodes=nodes, convention="act360", calendar="nyc", id=cid)
    return RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=handle,
        # Only the NoInput sentinel works here; see
        # tests/test_strikeless_vol_greeks.py for why None and an empty Series
        # both fail.
        fixings=rl.NoInput(0),
        meta_data={"reference_curve_name": "USD-OIS"},
    )


@pytest.fixture(scope="module")
def flat_curve():
    """Flat 4%, act360 -- the zero-roll baseline."""
    return _curve_from(lambda y: 0.04)


@pytest.fixture(scope="module")
def realistic_curve():
    """Flat 4% to y=10, then a smooth quadratic inversion.

    The same shape and the same ``a`` as
    ``tests/test_strikeless_vol_breakeven.py::_realistic_curve``, which is
    calibrated to the real USD 10y10y/20y10y print (-57.31bp). Duplicated
    rather than imported because importing across test modules makes one
    file's fixture edit silently rewrite another file's assertions.
    """
    return _curve_from(lambda y, a=7.4e-6: 0.04 - a * max(0.0, y - 10) ** 2)


def _ordinate(col, i):
    """Where to put this column on the shape axis when building loadings.

    The tenor when it parses, the column position otherwise -- several tests
    hand ``_pca_model`` deliberately malformed labels (``"FRONT"``) so that
    ``ladder_tenor_years`` has something to refuse, and the fixture builder
    must not be the thing that raises.
    """
    from RVUtils.StrikelessVol.universe import tenor_years as _ty

    parts = str(col).split()
    try:
        return _ty(parts[1] if len(parts) >= 2 else str(col))
    except ValueError:
        return float(i + 1)


def _pca_model(seed=0, n=500, cols=GRID_COLS, sigmas=(6e-5, 3e-5, 1.2e-5)):
    """A cov-PCA fitted on synthetic level/slope/curvature curve changes.

    Loadings are FITTED, never hand-written: a hand-written level vector would
    make every projection below tautological, and the point of the factor
    machinery is that it works on whatever ``fit_curve_pca_from_timeseries``
    actually returns.
    """
    yrs = np.array([_ordinate(c, i) for i, c in enumerate(cols)], dtype=float)
    l1 = np.ones(len(cols))
    l2 = (yrs - yrs.mean()) / yrs.std()
    l3 = (yrs - yrs.mean()) ** 2
    l3 = (l3 - l3.mean()) / l3.std()
    rng = np.random.default_rng(seed)
    f = rng.normal(0.0, 1.0, size=(n, 3)) * np.asarray(sigmas)
    changes = f @ np.vstack([l1, l2, l3])
    idx = pd.bdate_range("2024-01-01", periods=n)
    df = pd.DataFrame(np.cumsum(changes, axis=0) + 0.04, index=idx, columns=list(cols))
    model, _ = fit_curve_pca_from_timeseries(df)
    return model


@pytest.fixture(scope="module")
def model():
    return _pca_model()


@pytest.fixture(scope="module")
def grid(model):
    return ladder_tenor_years(model)


# ------------------------------------------------------------ carry_per_vega


def test_carry_per_vega_uses_beta_times_spread_dv01():
    # roll -$500/day, |beta| 0.7, spread DV01 $100k -> -500 / 70,000
    assert carry_per_vega(daily_roll_usd=-500.0, beta=-0.7, spread_dv01=100_000.0) == (
        pytest.approx(-500.0 / 70_000.0)
    )


def test_carry_per_vega_is_nan_when_beta_is_zero():
    assert np.isnan(carry_per_vega(daily_roll_usd=-500.0, beta=0.0, spread_dv01=1e5))


def test_positive_carry_construction_reports_positive_carry_per_vega():
    assert carry_per_vega(daily_roll_usd=+120.0, beta=-0.7, spread_dv01=1e5) > 0


def test_carry_per_vega_reads_the_magnitude_of_beta_not_its_sign():
    """Vega is a size, so the sign of the vol beta must not reach the answer.

    The sign of ``carry_per_vega`` has to come from the ROLL -- a bleeding
    flattener is a bleeding flattener whichever way its beta points -- and a
    ``beta`` that leaked its sign through would silently flip the ranking of
    every construction whose beta happened to be positive.
    """
    a = carry_per_vega(daily_roll_usd=-500.0, beta=-0.7, spread_dv01=1e5)
    b = carry_per_vega(daily_roll_usd=-500.0, beta=+0.7, spread_dv01=1e5)
    assert a == pytest.approx(b)
    assert a < 0.0


def test_carry_per_vega_is_nan_when_spread_dv01_is_zero():
    """Zero vega is undefined, not free. Returning 0.0 would read as "no carry
    cost per unit of vega", i.e. the most attractive row in the table."""
    assert np.isnan(carry_per_vega(daily_roll_usd=-500.0, beta=-0.7, spread_dv01=0.0))


# ------------------------------------------------ carry_per_vega_after_costs


def test_after_costs_amortises_the_round_trip_over_the_holding_period():
    """The brief's prose says "after costs"; its formula has no cost term.
    Both are reported, and this is the after-cost one, spelled out."""
    got = carry_per_vega_after_costs(
        daily_roll_usd=-500.0, beta=-0.7, spread_dv01=1e5,
        cost_bp_round_trip=1.75, holding_days=100.0, package_dv01_usd=1e5,
    )
    # $1.75bp x $100k = $175,000 spread over 100 days = $1,750/day
    assert got == pytest.approx((-500.0 - 1750.0) / 70_000.0)


def test_after_costs_converges_to_the_cost_free_number_as_the_hold_lengthens():
    kw = dict(daily_roll_usd=-500.0, beta=-0.7, spread_dv01=1e5,
              cost_bp_round_trip=1.75, package_dv01_usd=1e5)
    free = carry_per_vega(daily_roll_usd=-500.0, beta=-0.7, spread_dv01=1e5)
    short = carry_per_vega_after_costs(holding_days=21.0, **kw)
    long = carry_per_vega_after_costs(holding_days=10_000_000.0, **kw)
    assert short < long < free
    assert long == pytest.approx(free, rel=1e-3)


def test_a_free_schedule_leaves_the_after_cost_number_equal_to_the_cost_free_one():
    kw = dict(daily_roll_usd=-500.0, beta=-0.7, spread_dv01=1e5, package_dv01_usd=1e5)
    assert carry_per_vega_after_costs(
        cost_bp_round_trip=0.0, holding_days=21.0, **kw
    ) == pytest.approx(carry_per_vega(daily_roll_usd=-500.0, beta=-0.7, spread_dv01=1e5))


def test_a_nonpositive_holding_period_is_undefined_not_infinitely_expensive():
    kw = dict(daily_roll_usd=-500.0, beta=-0.7, spread_dv01=1e5,
              cost_bp_round_trip=1.75, package_dv01_usd=1e5)
    assert np.isnan(carry_per_vega_after_costs(holding_days=0.0, **kw))
    assert np.isnan(carry_per_vega_after_costs(holding_days=-5.0, **kw))


# -------------------------------------------------------- ladder_tenor_years


def test_ladder_tenor_years_parses_full_instrument_labels(model):
    got = ladder_tenor_years(model)
    assert list(got.index) == list(GRID_COLS)
    assert got.to_numpy() == pytest.approx([1, 2, 3, 5, 7, 10, 15, 20, 25, 30])


def test_ladder_tenor_years_parses_bare_tenor_labels():
    m = _pca_model(cols=("2Y", "5Y", "10Y", "30Y"))
    assert ladder_tenor_years(m).to_numpy() == pytest.approx([2.0, 5.0, 10.0, 30.0])


def test_ladder_tenor_years_uses_calendar_years_not_business_days():
    """``universe.tenor_years`` not ``df_based_pca_risk_model._tenor_to_years``.

    The latter maps ``1D`` to 1/252 and ``1W`` to 7/252 -- business-day counts,
    fine for sorting columns and wrong for a tent knot, which has to sit on the
    same clock as the curve's node times. 1/365 vs 1/252 is a 45% error in the
    knot position.
    """
    m = _pca_model(cols=("1D", "1W", "1Y", "10Y"))
    got = ladder_tenor_years(m).to_numpy()
    assert got[0] == pytest.approx(1.0 / 365.0)
    assert got[1] == pytest.approx(7.0 / 365.0)
    assert got[0] != pytest.approx(1.0 / 252.0)


def test_ladder_tenor_years_refuses_an_unparseable_column():
    m = _pca_model(cols=("2Y", "FRONT", "10Y", "30Y"))
    with pytest.raises(ValueError, match="parseable tenor"):
        ladder_tenor_years(m)


def test_ladder_tenor_years_refuses_a_non_monotone_grid(model):
    """A model whose columns are not tenor-sorted makes the tents overlap
    backwards, and the resulting ladder looks perfectly plausible."""
    m = _pca_model()
    order = [0, 1, 2, 4, 3, 5, 6, 7, 8, 9]  # 7Y and 5Y swapped
    m.columns = [m.columns[i] for i in order]
    m.loadings = m.loadings.reindex(m.columns)
    with pytest.raises(ValueError, match="not strictly increasing"):
        ladder_tenor_years(m)


def test_ladder_tenor_years_refuses_a_corr_fitted_model(model):
    """``_build_pca_metric_matrix`` never reads ``scales``, so a corr-PCA's
    metric would be in standardised units against a dollar ladder."""
    m = _pca_model()
    m.scales = pd.Series(2.0, index=m.columns)
    with pytest.raises(ValueError, match="matrix='corr'"):
        ladder_tenor_years(m)


def test_ladder_tenor_years_refuses_loadings_indexed_differently():
    m = _pca_model()
    m.loadings = m.loadings.iloc[::-1]
    with pytest.raises(ValueError, match="loadings.index"):
        ladder_tenor_years(m)


# ------------------------------------------------------------------- tents


def test_tent_rows_sum_to_one_everywhere_including_beyond_the_grid():
    """The partition of unity is what makes ``ladder.sum()`` a parallel DV01.

    Node times deliberately run past both ends of the grid: the first and last
    knots have to extend flat, or a 40y node would contribute to no bucket and
    the ladder would quietly lose the tail.
    """
    g = np.array([1.0, 2.0, 5.0, 10.0, 30.0])
    u = np.array([0.0, 0.5, 1.0, 1.5, 3.7, 10.0, 22.0, 30.0, 35.0, 40.0])
    w = _tent_matrix(u, g)
    assert w.sum(axis=1) == pytest.approx(np.ones(len(u)))
    assert (w >= 0.0).all()


def test_each_tent_is_one_at_its_knot_and_zero_at_its_neighbours():
    g = np.array([1.0, 2.0, 5.0, 10.0, 30.0])
    w = _tent_matrix(g, g)
    assert w == pytest.approx(np.eye(len(g)))


def test_the_tent_splits_an_interior_node_by_distance():
    """Where BETWEEN the knots the mass goes, not just that it adds to one.

    Found by mutation: halving the interpolation fraction
    (``frac -> 0.5 * frac``) keeps every row summing to exactly one -- both
    terms scale -- and puts every knot's own value at exactly one, so neither
    of the two tests above notices. The mass simply moves to the wrong bucket,
    which is a ladder that reports the right total risk in the wrong places
    and a hedge solved against it.
    """
    g = np.array([1.0, 2.0, 5.0, 10.0, 30.0])
    w = _tent_matrix(np.array([3.5, 7.5, 20.0, 1.25]), g)
    assert w[0] == pytest.approx([0.0, 0.5, 0.5, 0.0, 0.0])       # midpoint 2-5
    assert w[1] == pytest.approx([0.0, 0.0, 0.5, 0.5, 0.0])       # midpoint 5-10
    assert w[2] == pytest.approx([0.0, 0.0, 0.0, 0.5, 0.5])       # midpoint 10-30
    assert w[3] == pytest.approx([0.75, 0.25, 0.0, 0.0, 0.0])     # quarter 1-2


def test_a_flat_tent_reproduces_rateslib_shift(flat_curve):
    """The composite-curve shock IS a parallel shift when the weights are flat.

    This pins the primitive :func:`_shock_handle` is built on. rateslib's
    ``Curve.shift`` uses a discrete ``(1 + d*s)**n``; this uses a continuous
    ``exp(-z t)``; they agree because ``d`` here is the curve's own daily DCF.
    Measured on the real 2026-07-31 USD-OIS curve at a 20y point, the two
    agree to 3e-10 relative.
    """
    handle = flat_curve.handle()
    dcf = daily_dcf(handle)
    ref = pd.Timestamp(handle.nodes.initial)
    dates = list(handle.nodes.nodes)
    years = np.array([(pd.Timestamp(d) - ref).days * dcf for d in dates])
    composite = _shock_handle(handle, dates, years, np.ones(len(dates)), 1.0)
    shifted = handle.shift(1.0)
    for probe in (rl.dt(2031, 8, 3), rl.dt(2046, 8, 3), rl.dt(2056, 2, 14)):
        assert float(composite[probe]) == pytest.approx(float(shifted[probe]), rel=1e-8)


def test_a_flat_tent_is_not_a_no_op(flat_curve):
    """Guards the guard: a shock that silently did nothing would pass the
    agreement test above only if ``shift`` also did nothing."""
    handle = flat_curve.handle()
    dcf = daily_dcf(handle)
    ref = pd.Timestamp(handle.nodes.initial)
    dates = list(handle.nodes.nodes)
    years = np.array([(pd.Timestamp(d) - ref).days * dcf for d in dates])
    composite = _shock_handle(handle, dates, years, np.ones(len(dates)), 1.0)
    probe = rl.dt(2046, 8, 3)
    assert float(composite[probe]) < float(handle[probe]) * (1.0 - 1e-4)


# ------------------------------------------------------------ key_rate_ladder


def test_ladder_sums_to_the_parallel_dv01(realistic_curve, grid):
    """The independent tie-out: tent buckets against ``greeks``' shift DV01.

    Two different bump primitives (composite continuous zero bump vs
    ``rl.Curve.shift``'s discrete ``(1+d*s)**n``), two different code paths,
    one number. The 1e-4 band is the compounding difference, which is second
    order in the bump; measured 1.1e-4 relative on a single $100k leg.
    """
    leg = build_package(realistic_curve, PAIR).short
    ladder = key_rate_ladder(realistic_curve, [leg], tenor_grid=grid)
    assert ladder.sum() == pytest.approx(_reprice_dv01(realistic_curve, leg), rel=2e-4)


def test_a_dv01_neutral_package_ladder_sums_to_zero(realistic_curve, grid):
    pkg = build_package(realistic_curve, PAIR)
    ladder = key_rate_ladder(realistic_curve, [pkg.short, pkg.long], tenor_grid=grid)
    assert package_dv01(realistic_curve, pkg) == pytest.approx(0.0, abs=1e-6)
    # ...and the ladder agrees, while its own buckets are enormous. The
    # cancellation is the content: a ladder that summed to zero because every
    # bucket was zero would be a ladder that measured nothing.
    assert ladder.sum() == pytest.approx(0.0, abs=1.0)
    assert ladder.abs().max() > 50_000.0


def test_the_ladder_puts_the_risk_where_the_legs_are(realistic_curve, grid):
    """10y10y/20y10y touches 10y, 20y and 30y and nothing shorter.

    A ladder that smeared risk into the 1-7y buckets would still sum to zero
    and still look like a DV01-neutral package.
    """
    pkg = build_package(realistic_curve, PAIR)
    ladder = key_rate_ladder(realistic_curve, [pkg.short, pkg.long], tenor_grid=grid)
    front = ladder.loc[[c for c in GRID_COLS if c.split()[1] in ("1Y", "2Y", "3Y", "5Y", "7Y")]]
    back = ladder.loc[[c for c in GRID_COLS if c.split()[1] in ("10Y", "20Y", "30Y")]]
    assert front.abs().sum() < 1.0
    assert back.abs().sum() > 500_000.0


def test_the_ladder_is_linear_in_notional(realistic_curve, grid):
    small = build_package(realistic_curve, PAIR, package_dv01_usd=100_000.0)
    big = build_package(realistic_curve, PAIR, package_dv01_usd=300_000.0)
    a = key_rate_ladder(realistic_curve, [small.short, small.long], tenor_grid=grid)
    b = key_rate_ladder(realistic_curve, [big.short, big.long], tenor_grid=grid)
    assert b.to_numpy() == pytest.approx(3.0 * a.to_numpy(), rel=1e-6)


def test_prebuilt_shocks_give_the_same_ladder(realistic_curve, grid):
    """``compare_constructions`` builds the 2K shocked handles once and reuses
    them across three constructions; that reuse must not change a number."""
    pkg = build_package(realistic_curve, PAIR)
    fresh = key_rate_ladder(realistic_curve, [pkg.short, pkg.long], tenor_grid=grid)
    shared = key_rate_ladder(
        realistic_curve,
        [pkg.short, pkg.long],
        tenor_grid=grid,
        shocks=build_shocks(realistic_curve, grid),
    )
    assert shared.to_numpy() == pytest.approx(fresh.to_numpy(), rel=1e-12)


def test_shocks_built_at_one_bump_are_refused_at_another(realistic_curve, grid):
    """The central difference divides by the bump, so a mismatched pair would
    scale every bucket by the ratio -- in the right shape, with the right
    signs, and wrong by a constant. The bump therefore travels with the
    handles."""
    pkg = build_package(realistic_curve, PAIR)
    five = build_shocks(realistic_curve, grid, bump_bp=5.0)
    assert five.bump_bp == 5.0
    with pytest.raises(ValueError, match="bumped at 5.0bp"):
        key_rate_ladder(
            realistic_curve, [pkg.short, pkg.long], tenor_grid=grid,
            bump_bp=1.0, shocks=five,
        )
    # ...and asked for at its own bump it agrees with the 1bp ladder, because a
    # DV01 is a rate: the guard is about the divisor, not about 5bp being wrong
    at_five = key_rate_ladder(
        realistic_curve, [pkg.short, pkg.long], tenor_grid=grid,
        bump_bp=5.0, shocks=five,
    )
    at_one = key_rate_ladder(realistic_curve, [pkg.short, pkg.long], tenor_grid=grid)
    assert at_five.to_numpy() == pytest.approx(at_one.to_numpy(), rel=1e-3)


# --------------------------------------------------------- factor_exposures


def test_factor_exposures_are_linear_in_the_position(model, realistic_curve, grid):
    pkg = build_package(realistic_curve, PAIR)
    ladder = key_rate_ladder(realistic_curve, [pkg.short, pkg.long], tenor_grid=grid)
    one = factor_exposures(model, ladder)
    two = factor_exposures(model, 2.0 * ladder)
    assert two.to_numpy() == pytest.approx(2.0 * one.to_numpy(), rel=1e-12)


def test_a_zero_ladder_has_zero_factor_exposure(model, grid):
    zero = pd.Series(0.0, index=grid.index)
    assert factor_exposures(model, zero).abs().max() == pytest.approx(0.0, abs=1e-12)


def test_pca_transform_would_report_risk_on_a_flat_zero_position(model, grid):
    """Why :func:`factor_exposures` is not ``pca_model.transform``.

    ``transform`` subtracts the fitted mean before projecting. On a risk
    vector that is not a harmless offset: an empty book reports non-zero PC
    exposure, and the fly would then be solved against a phantom. Pinned so
    that anyone tempted to "simplify" ``factor_exposures`` into ``transform``
    has to delete a failing test to do it.
    """
    zero = pd.Series(0.0, index=grid.index)
    assert model.transform(zero).abs().max() > 0.0
    assert factor_exposures(model, zero).abs().max() == pytest.approx(0.0, abs=1e-12)


def test_factor_exposures_refuse_a_ladder_missing_a_bucket(model, grid):
    short = pd.Series(1.0, index=grid.index[:-1])
    with pytest.raises(ValueError, match="does not cover every"):
        factor_exposures(model, short)


# ---------------------------------------------------------------- pca_metric


def test_uniform_pca_weights_are_refused_because_the_metric_is_the_identity(model):
    """``eigh`` gives an orthonormal L, so ``L I L^T = I`` exactly.

    ``_build_pca_metric_matrix``'s own default (``pca_weights=None`` -> ones)
    therefore turns a "PCA-neutralising" hedge into plain unweighted least
    squares on the dollar ladder, silently. Measured before the guard existed:
    the fly removed 0.16% of a "PCA norm" that was the Euclidean norm.
    """
    K = len(model.columns)
    with pytest.raises(ValueError, match="identity"):
        pca_metric(model, pca_weights=np.ones(K))


def test_the_uniform_metric_really_is_the_identity(model):
    """The refusal above is not a superstition; this is the measurement."""
    from RVUtils.rl_swap_risk_ladder_utils import _build_pca_metric_matrix

    K = len(model.columns)
    G = _build_pca_metric_matrix(model, np.ones(K))
    assert G == pytest.approx(np.eye(K), abs=1e-10)


def test_the_default_metric_projects_onto_the_first_two_components(model):
    G = pca_metric(model)
    assert HEDGED_FACTORS == 2
    assert G @ G == pytest.approx(G, abs=1e-10)          # idempotent
    assert np.trace(G) == pytest.approx(float(HEDGED_FACTORS), abs=1e-10)
    L = model.loadings.values
    assert G @ L[:, 0] == pytest.approx(L[:, 0], abs=1e-10)
    assert G @ L[:, 2] == pytest.approx(np.zeros(len(L)), abs=1e-10)


def test_pca_metric_refuses_n_factors_outside_the_model(model):
    with pytest.raises(ValueError, match="n_factors"):
        pca_metric(model, n_factors=0)
    with pytest.raises(ValueError, match="n_factors"):
        pca_metric(model, n_factors=len(model.columns) + 1)


# --------------------------------------------------------- fly_hedge_weights


def test_the_fly_holds_the_wing_belly_bpv_constraint(realistic_curve, model):
    """Each wing carries half the belly's BPV, opposite sign.

    The constraint ``_solve_fly_ls_pca`` enforces is stated in the LADDER
    measure -- ``q`` is built from ``d = B.sum(axis=0)`` -- so it holds there
    exactly (1e-12). The reported ``weights_bpv`` are in the SIZING measure
    (``greeks._reprice_dv01``, an ``rl.Curve.shift`` central difference), and
    the two bump conventions differ by ~1e-4 relative, so the constraint
    survives that translation only to ~1e-7. Both are asserted, at their own
    tolerances, because collapsing them into one band would hide which measure
    the constraint actually lives in.
    """
    pkg = build_package(realistic_curve, PAIR)
    fly = fly_hedge_weights(realistic_curve, pkg, pca_model=model)

    ladder_bpv = {
        t: fly["unit_weights"][t] * fly["basis_dv01_usd"][t] for t in fly["fly_tenors"]
    }
    belly = ladder_bpv["7Y"]
    assert belly != pytest.approx(0.0, abs=1.0)
    assert ladder_bpv["2Y"] == pytest.approx(-0.5 * belly, rel=1e-12)
    assert ladder_bpv["30Y"] == pytest.approx(-0.5 * belly, rel=1e-12)

    w = fly["weights_bpv"]
    assert w["2Y"] == pytest.approx(-0.5 * w["7Y"], rel=1e-6)
    assert w["30Y"] == pytest.approx(-0.5 * w["7Y"], rel=1e-6)


def test_the_fly_adds_no_net_bpv(realistic_curve, model, grid):
    pkg = build_package(realistic_curve, PAIR)
    fly = fly_hedge_weights(realistic_curve, pkg, pca_model=model)
    assert fly["hedge_ladder"].sum() == pytest.approx(0.0, abs=1.0)
    assert fly["hedge_ladder"].abs().max() > 10_000.0


def test_the_fly_legs_are_sized_to_the_solved_weights(realistic_curve, model):
    """The returned instruments must carry the returned DV01s, or the roll and
    the cost are computed on legs that are not the hedge."""
    pkg = build_package(realistic_curve, PAIR)
    fly = fly_hedge_weights(realistic_curve, pkg, pca_model=model)
    for tenor, leg in fly["legs"].items():
        assert _reprice_dv01(realistic_curve, leg) == pytest.approx(
            fly["weights_bpv"][tenor], rel=1e-6
        )


def test_the_fly_cuts_the_level_slope_norm(realistic_curve, model):
    pkg = build_package(realistic_curve, PAIR)
    fly = fly_hedge_weights(realistic_curve, pkg, pca_model=model)
    assert fly["target_pca_norm"] > 0.0
    assert fly["residual_pca_norm"] < 0.1 * fly["target_pca_norm"]


def test_the_pca_norm_is_the_hypotenuse_of_the_hedged_components(realistic_curve, model):
    """An EQUALITY on the number the write-up quotes, not a ratio or a bound.

    Found by a reviewer's mutation: dropping ``_pca_norm``'s ``sqrt`` left all
    59 tests green while doubling the published headline -- the reported cut is
    ``residual_pca_norm / target_pca_norm``, and squaring both turns 0.9475
    into 0.8978, i.e. "5.3% removed" into "10.2% removed". The two tests that
    touched it were a ratio and an inequality, the exact shape three earlier
    survivors had.

    The identity is exact rather than approximate, and it is a genuine
    cross-check rather than a restatement: at the default metric ``G`` is the
    orthogonal projector onto the first ``HEDGED_FACTORS`` components and
    ``L`` is orthonormal, so ``sqrt(x^T G x) == hypot(pc1, pc2)`` -- which is
    true only if ``G`` really is that projector and ``factor_exposures`` really
    is ``L^T x``. Two independent code paths, one number.
    """
    pkg = build_package(realistic_curve, PAIR)
    fly = fly_hedge_weights(realistic_curve, pkg, pca_model=model)
    G = pca_metric(model)
    for key, ladder in (("target", fly["target_ladder"]), ("residual", fly["residual_ladder"])):
        pcs = factor_exposures(model, ladder)
        # rel=1e-9, not 1e-12: the residual norm (369) is a near-cancellation
        # of two ~78,000 exposures, so relative precision bottoms out around
        # 6e-12. It is still nine orders tighter than a squared-vs-rooted
        # confusion, which would move 369 to 135,931.
        assert _pca_norm(G, ladder) == pytest.approx(
            float(np.hypot(pcs.iloc[0], pcs.iloc[1])), rel=1e-9
        ), key
        assert fly[f"{key}_pca_norm"] == pytest.approx(_pca_norm(G, ladder), rel=1e-12)
    # the target norm is large enough that a squared-vs-rooted confusion could
    # not hide inside floating point
    assert fly["target_pca_norm"] > 1_000.0


def test_the_fly_reports_the_dv01_it_actually_trades(realistic_curve, model):
    """``traded_dv01_usd`` is a reported number, so it is pinned as one.

    Found by a reviewer's mutation: reporting the LARGEST leg instead of the
    sum of magnitudes left every test green, because nothing read the field
    numerically -- the cost column reads ``weights_bpv`` directly. On the fly's
    own 0.5/1/0.5 BPV structure, ``max`` is exactly half the sum, so the
    analysis' ``fly_traded_dv01`` would have been understated 2x.
    """
    pkg = build_package(realistic_curve, PAIR)
    fly = fly_hedge_weights(realistic_curve, pkg, pca_model=model)
    legs = list(fly["weights_bpv"].values())
    assert fly["traded_dv01_usd"] == pytest.approx(sum(abs(v) for v in legs), rel=1e-12)
    # sum, not max: the wing/belly structure makes max exactly half the sum
    assert fly["traded_dv01_usd"] == pytest.approx(2.0 * max(abs(v) for v in legs), rel=1e-6)
    assert fly["traded_dv01_usd"] > 0.0


def test_one_scalar_zeroes_one_functional_and_no_more(realistic_curve, model):
    """The exact statement of the one-parameter limit, as a first-order condition.

    ``a`` is the only free number, so the solved residual is G-orthogonal to
    the fly direction ``h`` and to nothing else. Reporting "level and slope are
    neutralised" would require two free parameters; the fly has one, and the
    residual's PC1 stays non-zero to prove it.
    """
    pkg = build_package(realistic_curve, PAIR)
    fly = fly_hedge_weights(realistic_curve, pkg, pca_model=model)
    G = pca_metric(model)
    h = fly["hedge_ladder"].to_numpy()
    resid = fly["residual_ladder"].to_numpy()
    scale = float(np.sqrt(h @ (G @ h)) * np.sqrt(resid @ (G @ resid)))
    assert float(h @ (G @ resid)) == pytest.approx(0.0, abs=max(scale, 1.0) * 1e-8)
    # and the component it did NOT get to choose is still there
    pcs = fly["residual_pc"]
    assert abs(float(pcs.iloc[0])) > 1.0


def test_the_belly_direction_is_solved_not_asserted(realistic_curve, model):
    """H9 names a *received* fly. Flip the package to a steepener and the
    solved belly must flip with it, or the label is decoration."""
    flat = build_package(realistic_curve, PAIR, sign=FLATTENER)
    steep = build_package(realistic_curve, PAIR, sign=STEEPENER)
    a = fly_hedge_weights(realistic_curve, flat, pca_model=model)
    b = fly_hedge_weights(realistic_curve, steep, pca_model=model)
    assert {a["belly_direction"], b["belly_direction"]} == {"received", "paid"}
    assert a["weights_bpv"]["7Y"] == pytest.approx(-b["weights_bpv"]["7Y"], rel=1e-6)


def test_fly_hedge_weights_refuses_anything_that_is_not_three_legs(realistic_curve, model):
    pkg = build_package(realistic_curve, PAIR)
    with pytest.raises(ValueError, match="a fly is three legs"):
        fly_hedge_weights(realistic_curve, pkg, pca_model=model, fly_tenors=("2Y", "30Y"))


def test_a_fly_leg_beyond_the_curve_is_refused_not_extrapolated():
    """H9's own default over-runs a REAL USD curve by a year.

    A 1y-forward 30y wing matures at 31 years. The GS Quant USD-OIS curve's
    final node is 30 years out (measured: reference 2026-07-31, final node
    2056-08-04) and USD publishes no 31y instrument -- the same fact that keeps
    ``10y10y/25y10y`` out of ``universe.USD_PAIRS``. Pricing it anyway hedges
    against an extrapolation.

    This fixture stops at 30 years to reproduce that, rather than the 40 the
    rest of this file uses so it can price the specified structure at all.
    """
    ref = REF
    nodes = {ref: 1.0}
    for y in range(1, 31):
        nodes[rl.dt(ref.year + y, ref.month, ref.day)] = 1.0 / (1.04 ** y)
    short_curve = RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=rl.Curve(nodes=nodes, convention="act360", calendar="nyc", id="s30"),
        fixings=rl.NoInput(0),
        meta_data={"reference_curve_name": "USD-OIS"},
    )
    m = _pca_model(cols=("1Y", "2Y", "5Y", "10Y", "20Y", "30Y"))
    pkg = build_package(short_curve, PAIR)
    with pytest.raises(ValueError, match="beyond the curve's final node"):
        fly_hedge_weights(short_curve, pkg, pca_model=m)
    # ...and a wing that fits prices fine, so the guard is about the span and
    # not about the fixture being unusable.
    got = fly_hedge_weights(short_curve, pkg, pca_model=m, fly_tenors=("2Y", "7Y", "29Y"))
    assert set(got["weights_bpv"]) == {"2Y", "7Y", "29Y"}


def test_a_pc2_shaped_curve_shock_confirms_the_hedge_by_repricing(realistic_curve, model, grid):
    """The independent control: no ladder, no metric, no projection.

    Shock the curve by the fitted PC2 loading (a slope move), reprice the
    actual instruments, and compare the hedged book's P&L against the
    unhedged one's. If the fly's PC2 neutralisation is a real property of the
    position rather than a self-consistent identity inside the linear algebra,
    the hedged book has to move materially less.

    The shock is applied through the same tent interpolation the ladder uses,
    so this shares the bump plumbing -- but it shares nothing with the
    ladder-to-weights arithmetic, which is what the test is about.
    """
    pkg = build_package(realistic_curve, PAIR)
    fly = fly_hedge_weights(realistic_curve, pkg, pca_model=model)
    base_legs = [pkg.short, pkg.long]
    hedged_legs = base_legs + list(fly["legs"].values())

    handle = realistic_curve.handle()
    dcf = daily_dcf(handle)
    ref = pd.Timestamp(handle.nodes.initial)
    dates = list(handle.nodes.nodes)
    years = np.array([(pd.Timestamp(d) - ref).days * dcf for d in dates])
    tents = _tent_matrix(years, grid.to_numpy(dtype=float))
    loading2 = model.loadings.values[:, 1]
    node_weights = tents @ loading2

    def pnl(legs, size_bp):
        up = _shock_handle(handle, dates, years, node_weights, +size_bp)
        dn = _shock_handle(handle, dates, years, node_weights, -size_bp)
        return sum(float(i.npv(curves=up).real) - float(i.npv(curves=dn).real) for i in legs)

    naked = abs(pnl(base_legs, 25.0))
    hedged = abs(pnl(hedged_legs, 25.0))
    assert naked > 100_000.0            # there is something to hedge
    assert hedged < 0.10 * naked        # and the fly removed most of it


# ----------------------------------------------------------- legs_roll_usd


def test_legs_roll_reproduces_the_package_roll(realistic_curve):
    """One roll convention, two entry points. ``greeks.daily_roll_usd`` cannot
    carry a fly, so this generalises it -- and must not become a second,
    subtly different roll."""
    pkg = build_package(realistic_curve, PAIR)
    nxt = realistic_curve.reference_date() + pd.Timedelta(days=1)
    assert legs_roll_usd(realistic_curve, [pkg.short, pkg.long], next_date=nxt) == (
        pytest.approx(daily_roll_usd(realistic_curve, pkg, next_date=nxt), rel=1e-12)
    )


def test_the_realistic_flattener_bleeds(realistic_curve):
    """The study's standing fact, restated through this module's entry point:
    an inverted ultra-long curve makes the flattener carry negatively."""
    pkg = build_package(realistic_curve, PAIR)
    nxt = realistic_curve.reference_date() + pd.Timedelta(days=1)
    assert legs_roll_usd(realistic_curve, [pkg.short, pkg.long], next_date=nxt) < 0.0


# ------------------------------------------------------ cost_bp_round_trip


def test_the_two_leg_round_trip_is_twice_the_initiate_charge():
    """$100k of package DV01 is two $100k legs, and the study's schedule
    charges ``initiate_bp`` once per package one way."""
    assert cost_bp_round_trip([100_000.0, -100_000.0]) == pytest.approx(
        2.0 * CostSchedule().initiate_bp
    )
    assert cost_bp_round_trip([100_000.0, -100_000.0]) == pytest.approx(1.75)


def test_cost_scales_with_the_risk_actually_traded():
    """Traded risk is the SUM OF MAGNITUDES, not the net.

    Found by mutation: with ``traded = abs(sum(x))`` both books below net to
    exactly zero, both costs come back 0.0, and ``five == 2 * two`` passes as
    ``0 == 0``. A cost model in which every BPV-neutral package is free is the
    one failure this study cannot afford (costs are 41% of gross at 1x), so
    both figures are asserted absolutely as well as relatively.
    """
    two = cost_bp_round_trip([100_000.0, -100_000.0])
    five = cost_bp_round_trip([100_000.0, -100_000.0, 50_000.0, -100_000.0, 50_000.0])
    assert two == pytest.approx(1.75)
    assert five == pytest.approx(3.50)
    assert five == pytest.approx(two * 2.0)


def test_cost_is_blind_to_the_sign_of_each_leg():
    assert cost_bp_round_trip([100_000.0, -100_000.0]) == pytest.approx(
        cost_bp_round_trip([-100_000.0, 100_000.0])
    )


def test_a_free_schedule_costs_nothing():
    assert cost_bp_round_trip([1e5, -1e5], schedule=FREE) == pytest.approx(0.0)


def test_a_doubled_multiplier_doubles_the_cost():
    """Costs are first-order in this study -- 41% of gross at 1x, 83% at 2x --
    so the multiplier has to reach this number."""
    base = cost_bp_round_trip([1e5, -1e5])
    twice = cost_bp_round_trip([1e5, -1e5], schedule=CostSchedule(multiplier=2.0))
    assert twice == pytest.approx(2.0 * base)


# --------------------------------------------------------- same_sector_pair


def test_same_sector_pair_is_the_ultra_long_pair_not_the_input():
    got = same_sector_pair(PAIR)
    assert got.name == "USD 15Y5Y/20Y10Y"
    assert got is not PAIR


def test_same_sector_pair_raises_rather_than_falling_back():
    """A SAME_SECTOR row that is secretly the TWO_LEG row is this study's own
    documented failure mode (a placebo leg that reproduced the real number)."""
    with pytest.raises(ValueError, match="no 15Y5Y/20Y10Y pair"):
        same_sector_pair(PAIR, pairs=[PAIR])


# ---------------------------------------------------- compare_constructions


@pytest.fixture(scope="module")
def comparison(realistic_curve, model):
    return compare_constructions(realistic_curve, PAIR, pca_model=model, beta=-1.3)


def test_every_construction_appears_exactly_once(comparison):
    assert list(comparison.index) == list(CONSTRUCTIONS)
    assert comparison["pair"].loc[SAME_SECTOR] == "USD 15Y5Y/20Y10Y"
    assert comparison["pair"].loc[TWO_LEG] == PAIR.name
    assert comparison["n_legs"].to_dict() == {TWO_LEG: 2, FLY_HEDGED: 5, SAME_SECTOR: 2}


def test_the_same_sector_row_is_priced_off_the_same_sector_package(realistic_curve, comparison):
    """The label is not the evidence; the number is.

    Found by mutation: building the SAME_SECTOR package off the INPUT pair
    while still labelling the row ``USD 15Y5Y/20Y10Y`` leaves
    ``test_every_construction_appears_exactly_once`` passing, because that test
    reads the label. This rebuilds the same-sector package independently and
    checks the row's roll came from it -- the "a placebo leg that reproduced
    the real number" failure, one module across.
    """
    sector = same_sector_pair(PAIR)
    pkg = build_package(realistic_curve, sector)
    nxt = realistic_curve.reference_date() + pd.Timedelta(days=1)
    assert comparison.loc[SAME_SECTOR, "daily_roll_usd"] == pytest.approx(
        legs_roll_usd(realistic_curve, [pkg.short, pkg.long], next_date=nxt), rel=1e-12
    )
    ladder = key_rate_ladder(
        realistic_curve, [pkg.short, pkg.long], tenor_grid=ladder_tenor_years(_pca_model())
    )
    pcs = factor_exposures(_pca_model(), ladder)
    assert comparison.loc[SAME_SECTOR, "residual_pc1"] == pytest.approx(
        float(pcs.iloc[0]), rel=1e-9
    )
    assert comparison.loc[SAME_SECTOR, "residual_pc2"] == pytest.approx(
        float(pcs.iloc[1]), rel=1e-9
    )


def test_the_wings_cost_money(comparison):
    """H9's own caveat, made a number rather than a caveat."""
    assert comparison.loc[FLY_HEDGED, "cost_bp_round_trip"] > (
        comparison.loc[TWO_LEG, "cost_bp_round_trip"]
    )
    assert comparison.loc[FLY_HEDGED, "traded_dv01_usd"] > (
        comparison.loc[TWO_LEG, "traded_dv01_usd"]
    )


def test_no_sector_tightness_discount_is_applied(comparison):
    """SAME_SECTOR gets no cost credit it has not earned. Nothing in this study
    has measured the ultra-long sector's bid/ask against the 10y sector's, so
    the two-leg rate is charged to both and the claim stays visibly untested."""
    assert comparison.loc[SAME_SECTOR, "cost_bp_round_trip"] == pytest.approx(
        comparison.loc[TWO_LEG, "cost_bp_round_trip"]
    )
    assert comparison.attrs["sector_tightness_modelled"] is False


def test_the_fly_hedged_row_carries_less_level_slope_risk(comparison):
    a = np.hypot(comparison.loc[TWO_LEG, "residual_pc1"], comparison.loc[TWO_LEG, "residual_pc2"])
    b = np.hypot(
        comparison.loc[FLY_HEDGED, "residual_pc1"], comparison.loc[FLY_HEDGED, "residual_pc2"]
    )
    assert a > 0.0
    assert b < 0.1 * a


def test_every_row_reports_the_carry_per_vega_of_its_own_roll(comparison):
    for name, row in comparison.iterrows():
        assert row["carry_per_vega"] == pytest.approx(
            carry_per_vega(
                daily_roll_usd=row["daily_roll_usd"],
                beta=row["beta"],
                spread_dv01=row["spread_dv01"],
            )
        )


def test_the_three_rolls_are_not_the_same_number(comparison):
    """Three constructions, three different books. Equal rolls would mean the
    fly legs never reached the roll, or the same-sector package was never
    built."""
    rolls = comparison["daily_roll_usd"].to_numpy()
    assert len(set(np.round(rolls, 6))) == 3


def test_a_beta_mapping_gives_each_construction_its_own(realistic_curve, model):
    betas = {TWO_LEG: -1.3, FLY_HEDGED: -1.3, SAME_SECTOR: -0.8}
    out = compare_constructions(realistic_curve, PAIR, pca_model=model, beta=betas)
    assert out["beta"].to_dict() == betas
    assert out.loc[SAME_SECTOR, "carry_per_vega"] == pytest.approx(
        carry_per_vega(
            daily_roll_usd=out.loc[SAME_SECTOR, "daily_roll_usd"],
            beta=-0.8,
            spread_dv01=1e5,
        )
    )


def test_a_scalar_beta_makes_carry_per_vega_a_rescaled_roll(comparison):
    """Recorded because it broke this task's own headline once.

    With one scalar beta and one sizing constant, every row's denominator is
    the same number and ``carry_per_vega`` is ``daily_roll_usd`` divided by a
    constant -- so the per-unit-of-vega normalisation, the whole reason the
    brief chose this metric, is inert for exactly the cross-pair comparison the
    table exists to make. ``attrs["shared_beta"]`` says which mode a frame is
    in, so a reader does not have to notice.
    """
    assert comparison.attrs["shared_beta"] is True
    ratio = (comparison["carry_per_vega"] / comparison["daily_roll_usd"]).to_numpy()
    assert np.allclose(ratio, ratio[0], rtol=1e-12)


def test_a_beta_mapping_is_not_flagged_as_shared(realistic_curve, model):
    out = compare_constructions(
        realistic_curve, PAIR, pca_model=model,
        beta={TWO_LEG: -1.3, FLY_HEDGED: -1.3, SAME_SECTOR: -0.8},
    )
    assert out.attrs["shared_beta"] is False
    ratio = (out["carry_per_vega"] / out["daily_roll_usd"]).to_numpy()
    assert not np.allclose(ratio, ratio[0], rtol=1e-6)


def test_the_after_cost_column_is_nan_until_a_holding_period_is_given(
    realistic_curve, model, comparison
):
    assert comparison.attrs["holding_days"] is None
    assert comparison["carry_per_vega_after_costs"].isna().all()

    out = compare_constructions(
        realistic_curve, PAIR, pca_model=model, beta=-1.3, holding_days=21.0
    )
    assert out.attrs["holding_days"] == 21.0
    assert out["carry_per_vega_after_costs"].notna().all()
    # costs only ever make a bleeding book bleed faster
    assert (out["carry_per_vega_after_costs"] < out["carry_per_vega"]).all()
    for name, row in out.iterrows():
        assert row["carry_per_vega_after_costs"] == pytest.approx(
            carry_per_vega_after_costs(
                daily_roll_usd=row["daily_roll_usd"],
                beta=row["beta"],
                spread_dv01=row["spread_dv01"],
                cost_bp_round_trip=row["cost_bp_round_trip"],
                holding_days=21.0,
                package_dv01_usd=row["spread_dv01"],
            )
        ), name


def test_a_beta_mapping_missing_a_construction_raises(realistic_curve, model):
    with pytest.raises(ValueError, match="no entry for construction"):
        compare_constructions(
            realistic_curve, PAIR, pca_model=model, beta={TWO_LEG: -1.3}
        )


def test_the_comparison_records_what_it_was_run_with(comparison):
    attrs = comparison.attrs
    assert attrs["n_factors"] == HEDGED_FACTORS
    assert attrs["fly"]["fly_tenors"] == ("2Y", "7Y", "30Y")
    assert attrs["fly"]["fly_fwd"] == "1Y"
    assert attrs["reference_date"] == REF


def test_the_default_horizon_is_one_calendar_day(comparison):
    """One CALENDAR day, matching ``greeks.compute_greeks``.

    A business-day step jumps three calendar days over a weekend and four over
    a holiday-adjacent Friday, and the dollar roll -- and every carry-per-vega
    built on it -- grows with the gap. The unit on this table would then be
    "per day" on Tuesdays and "per three days" on Mondays.
    """
    assert pd.Timestamp(comparison.attrs["next_date"]) == pd.Timestamp(REF) + pd.Timedelta(
        days=1
    )

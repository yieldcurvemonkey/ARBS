import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.costs import FREE, CostSchedule
from RVUtils.StrikelessVol.replication import (
    ReplicationConfig,
    reconcile,
    simulate,
)


BASE_DV01 = 100_000.0


class SyntheticCtx:
    """A closed-form world: quadratic PV in the rate, linear time decay.

    With ``k = gamma / 1e4`` and ``dr`` the long rate's move in bp since inception:

        PV   = n_long*(dr + 0.5*k*dr^2) - n_short*dr
               + theta_per_day * days_elapsed * (n_long / BASE_DV01)
        dv01 = 1 + k*dr   (long leg)          # exactly d(PV)/d(dr) per unit
        theta= theta_per_day * n_long / BASE_DV01

    ``dv01`` drifts with the rate, which is what makes the resize rule bite:
    holding DV01 constant means selling delta as rates rise and buying it back
    as they fall. That is the gamma-scalping mechanic the whole strategy rests
    on, so the synthetic world has to contain it or the ledger tests prove
    nothing.
    """

    def __init__(self, path_bp, *, theta_per_day=-500.0, gamma=40.0):
        self.dates = pd.date_range("2026-01-01", periods=len(path_bp), freq="B")
        self.path = dict(zip(self.dates, np.asarray(path_bp, dtype=float)))
        self.day_index = {d: i for i, d in enumerate(self.dates)}
        self.theta_per_day = theta_per_day
        self.k = gamma / 1e4

    def rate(self, date, leg):
        base = 0.04 if leg == "long" else 0.045
        return base + self.path[date] * 1e-4

    def dv01(self, date, leg):
        if leg == "long":
            return 1.0 + self.k * self.path[date]
        return 1.0

    def theta(self, date, notional_long, notional_short):
        return self.theta_per_day * (notional_long / BASE_DV01)

    def pv(self, date, notional_long, notional_short):
        dr = self.path[date]
        i = self.day_index[date]
        convex = (
            notional_long * (dr + 0.5 * self.k * dr * dr)
            - notional_short * dr
        )
        return convex + self.theta_per_day * i * (notional_long / BASE_DV01)


def test_flat_path_produces_only_carry():
    ctx = SyntheticCtx([0.0] * 20)
    led = simulate(ctx, ctx.dates, ReplicationConfig(), FREE)
    assert led["mtm"].abs().sum() == pytest.approx(0.0, abs=1e-6)
    assert led["harvest"].abs().sum() == pytest.approx(0.0, abs=1e-6)
    assert led["cost"].sum() == pytest.approx(0.0)


def test_no_rebalance_below_the_trigger():
    ctx = SyntheticCtx(list(np.linspace(0.0, 20.0, 30)))
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)
    assert led["n_hedges"].sum() == 0


def test_rebalances_once_per_trigger_crossing():
    ctx = SyntheticCtx(list(np.linspace(0.0, 100.0, 101)))
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)
    assert led["n_hedges"].sum() == 4  # 25, 50, 75, 100


def test_harvest_is_positive_for_a_round_trip_on_the_long_convexity_side():
    """Out 50bp and back: the resizes are bought low and sold high."""
    path = list(np.linspace(0.0, 50.0, 51)) + list(np.linspace(49.0, 0.0, 50))
    ctx = SyntheticCtx(path)
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)
    assert led["harvest"].sum() > 0.0


def test_costs_are_charged_on_initiation_and_each_hedge():
    ctx = SyntheticCtx(list(np.linspace(0.0, 100.0, 101)))
    sched = CostSchedule()
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), sched)
    assert led["cost"].iloc[0] == pytest.approx(
        -sched.cost_usd("initiate", 100_000.0)
    )
    assert (led["cost"] < 0).sum() == 1 + 4  # initiation plus four hedges


def test_reconcile_confirms_arithmetic_completeness_at_float_precision():
    """reconcile() only checks that the day's numbers were summed correctly
    (see its docstring for why that is a narrower guarantee than it sounds --
    carry+mtm+harvest cancel to total_pv_change algebraically for ANY input
    values, not just correct ones). This test is about that arithmetic only;
    it is NOT evidence any individual bucket holds the right value -- see
    test_harvest_matches_the_closed_form_replication_pnl and
    test_carry_matches_the_closed_form_theta_integral for that.
    """
    rng = np.random.default_rng(0)
    path = np.cumsum(rng.normal(0.0, 5.0, 250))
    ctx = SyntheticCtx(list(path))
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)
    rec = reconcile(led)
    assert rec["ok"] is True
    assert rec["max_abs_cross"] < 1e-6
    assert rec["max_abs_cross_frac"] < 0.01


def test_position_ages_and_rolls():
    ctx = SyntheticCtx([0.0] * 400)
    led = simulate(ctx, ctx.dates, ReplicationConfig(roll_months=12), FREE)
    # a 12-month roll inside ~400 business days means at least one roll charge
    assert led["position_age_years"].max() < 1.05
    assert led["position_age_years"].iloc[-1] < led["position_age_years"].max()


def test_steepener_mirrors_the_flattener_ledgers():
    """n_long and n_short both flip sign under STEEPENER, and pv()/theta() are
    linear (odd) in (notional_long, notional_short) jointly in this synthetic
    world, so every ledger built from them -- not just harvest and carry --
    should negate cleanly. cost is deliberately excluded: it is a magnitude
    fee (built from abs(delta_n)) that does not depend on position direction,
    so it should be IDENTICAL, not mirrored, between the two runs -- this
    test uses FREE so cost is 0 either way and total mirrors cleanly too.
    """
    from RVUtils.StrikelessVol.conventions import FLATTENER, STEEPENER

    path = list(np.linspace(0.0, 50.0, 51)) + list(np.linspace(49.0, 0.0, 50))
    ctx = SyntheticCtx(path)
    flat = simulate(ctx, ctx.dates, ReplicationConfig(sign=FLATTENER), FREE)
    steep = simulate(ctx, ctx.dates, ReplicationConfig(sign=STEEPENER), FREE)
    assert flat["harvest"].sum() == pytest.approx(-steep["harvest"].sum(), rel=1e-9)
    assert flat["carry"].sum() == pytest.approx(-steep["carry"].sum(), rel=1e-9)
    assert flat["mtm"].sum() == pytest.approx(-steep["mtm"].sum(), rel=1e-9)
    assert flat["cross"].sum() == pytest.approx(-steep["cross"].sum(), abs=1e-6)
    assert flat["total"].sum() == pytest.approx(-steep["total"].sum(), rel=1e-9)


def test_carry_mtm_harvest_alone_match_an_independently_repriced_total():
    """carry + mtm + harvest, WITHOUT cross, must equal the day's actual PV
    change -- recomputed here straight from ctx.pv() and the notionals the
    ledger reports having held, not read off the ledger's own 'total' or
    'cross' columns.

    IMPORTANT LIMITATION, found by mutation testing after this test was
    first written: carry+mtm+harvest cancels down to total_pv_change
    ALGEBRAICALLY (see reconcile()'s docstring for the six-symbol expansion),
    so this test -- like reconcile() -- only catches a bug that changes the
    SUM (e.g. a term dropped from one bucket with nothing added anywhere
    else). It does NOT catch a bug that reallocates value between buckets
    while preserving the sum -- concretely, verified: it stays green under a
    mutant that deletes the prev_base_pv refresh (corrupts harvest by 6
    orders of magnitude while mtm absorbs the exact mirror image) and under
    a mutant that moves increment_carry from carry into harvest (a clean
    0.95% shift on this path). Both of those are caught only by
    test_harvest_matches_the_closed_form_replication_pnl and (the second
    one) test_carry_matches_the_closed_form_theta_integral below, which
    check VALUES against an independent closed form rather than checking
    that a sum holds. Kept as a real, if narrower, guard: a term that goes
    missing without a matching addition elsewhere is still a plausible typo,
    and this catches it as cheaply as reconcile() does.
    """
    path = list(np.linspace(0.0, 50.0, 51)) + list(np.linspace(49.0, 0.0, 50))
    ctx = SyntheticCtx(path)
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)
    assert led["n_hedges"].sum() >= 3  # several resizes, not a degenerate path

    dates = list(ctx.dates)
    held_long = led["long_notional"].shift(1).fillna(led["long_notional"].iloc[0])
    held_short = led["short_notional"].shift(1).fillna(led["short_notional"].iloc[0])

    independent_total = sum(
        ctx.pv(dates[i], held_long.iloc[i], held_short.iloc[i])
        - ctx.pv(dates[i - 1], held_long.iloc[i], held_short.iloc[i])
        for i in range(1, len(dates))
    )
    three_bucket_total = led.iloc[1:][["carry", "mtm", "harvest"]].sum().sum()
    assert three_bucket_total == pytest.approx(independent_total, abs=1e-3)


def _closed_form_harvest(ctx, dates, cfg):
    """Independent replay of the trigger rule and the closed-form harvest
    total: harvest = sum_k dn_k * (f(dr_end) - f(dr_k)), f(dr) = dr +
    0.5*k*dr**2 -- SyntheticCtx.pv()'s own notional-linear rate function,
    since PV = n_long*f(dr) - n_short*dr + theta term (linear in n_long at
    fixed dr), so an increment dn_k held from dr_k to dr_end contributes
    exactly dn_k*(f(dr_end)-f(dr_k)) net of its own carry (a standard Abel
    summation over the piecewise-constant outstanding-increment total S_t
    reduces sum_t S_t*(f(dr_t)-f(dr_{t-1})) to this per-trade form). Derived
    fresh from ctx and cfg here -- does not call simulate() or read any of
    its internals -- so it is a genuine independent check on harvest's
    VALUE, not a restatement of how simulate() computes it.

    Does not handle a roll firing mid-path (the round-trip fixture this is
    used against never rolls); would need to reset ``trades`` and re-anchor
    ``dr_end`` per roll segment to generalize.
    """
    dates = list(dates)
    k = ctx.k

    def f(dr):
        return dr + 0.5 * k * dr * dr

    last_hedge_rate_bp = ctx.rate(dates[0], "long") * 1e4
    n_long = cfg.sign * cfg.package_dv01_usd / ctx.dv01(dates[0], "long")
    trades = []  # (delta_notional, dr_at_trade)
    for d in dates[1:]:
        long_rate_bp = ctx.rate(d, "long") * 1e4
        if abs(long_rate_bp - last_hedge_rate_bp) >= cfg.trigger_bp - 1e-6:
            target_long = cfg.sign * cfg.package_dv01_usd / ctx.dv01(d, "long")
            delta_n = target_long - n_long
            if delta_n != 0.0:
                trades.append((delta_n, ctx.path[d]))
                n_long = target_long
            last_hedge_rate_bp = long_rate_bp
    dr_end = ctx.path[dates[-1]]
    return sum(dn * (f(dr_end) - f(dr_k)) for dn, dr_k in trades)


def test_harvest_matches_the_closed_form_replication_pnl():
    """The value test the vacuous-gate review asked for: harvest checked
    against an independent closed form, not against another quantity
    simulate() itself produced. This is what actually pins down VALUES --
    reconcile() and the three-bucket-sum test above both cancel to
    total_pv_change algebraically regardless of how carry/mtm/harvest are
    individually computed, so neither can tell a correct harvest from a
    reallocated or corrupted one. This one can (verified by mutation: a
    deleted prev_base_pv refresh and a moved increment_carry term are both
    caught here, at a 6-orders-of-magnitude miss and a 0.95% miss
    respectively, while staying invisible to every sum-based check).
    """
    path = list(np.linspace(0.0, 50.0, 51)) + list(np.linspace(49.0, 0.0, 50))
    ctx = SyntheticCtx(path)
    cfg = ReplicationConfig(trigger_bp=25.0)
    led = simulate(ctx, ctx.dates, cfg, FREE)

    expected = _closed_form_harvest(ctx, ctx.dates, cfg)
    assert led["harvest"].sum() == pytest.approx(expected, abs=1e-3)


def test_carry_matches_the_closed_form_theta_integral():
    """carry's independent closed form: theta_per_day/BASE_DV01 * sum(n_long
    held into each day). theta() is exactly linear in notional_long in this
    synthetic world, so this is not an approximation. Catches a symmetric
    misallocation between carry and harvest (verified: the move-
    increment-carry-into-harvest mutant above is caught here too, at the
    same 0.95% the closed-form harvest test finds) -- the pairing the
    coordinator asked for, since a shift hidden from one closed-form check
    by construction (it only touches the OTHER bucket) cannot hide from
    both at once.
    """
    path = list(np.linspace(0.0, 50.0, 51)) + list(np.linspace(49.0, 0.0, 50))
    ctx = SyntheticCtx(path)
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)

    held_long = led["long_notional"].shift(1).fillna(led["long_notional"].iloc[0])
    expected = ctx.theta_per_day / BASE_DV01 * held_long.iloc[1:].sum()
    assert led["carry"].iloc[1:].sum() == pytest.approx(expected, rel=1e-9)

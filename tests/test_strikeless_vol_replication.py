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


def test_ledgers_reconcile_with_a_small_trendless_plug():
    rng = np.random.default_rng(0)
    path = np.cumsum(rng.normal(0.0, 5.0, 250))
    ctx = SyntheticCtx(list(path))
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)
    rec = reconcile(led)
    assert rec["ok"] is True
    assert rec["max_abs_cross_frac"] < 0.01


def test_position_ages_and_rolls():
    ctx = SyntheticCtx([0.0] * 400)
    led = simulate(ctx, ctx.dates, ReplicationConfig(roll_months=12), FREE)
    # a 12-month roll inside ~400 business days means at least one roll charge
    assert led["position_age_years"].max() < 1.05
    assert led["position_age_years"].iloc[-1] < led["position_age_years"].max()


def test_steepener_mirrors_the_flattener_ledgers():
    from RVUtils.StrikelessVol.conventions import FLATTENER, STEEPENER

    path = list(np.linspace(0.0, 50.0, 51)) + list(np.linspace(49.0, 0.0, 50))
    ctx = SyntheticCtx(path)
    flat = simulate(ctx, ctx.dates, ReplicationConfig(sign=FLATTENER), FREE)
    steep = simulate(ctx, ctx.dates, ReplicationConfig(sign=STEEPENER), FREE)
    assert flat["harvest"].sum() == pytest.approx(-steep["harvest"].sum(), rel=1e-9)
    assert flat["carry"].sum() == pytest.approx(-steep["carry"].sum(), rel=1e-9)


def test_carry_mtm_harvest_alone_match_an_independently_repriced_total():
    """carry + mtm + harvest, WITHOUT cross, must equal the day's actual PV
    change -- recomputed here straight from ctx.pv() and the notionals the
    ledger reports having held, not read off the ledger's own 'total' or
    'cross' columns.

    This is deliberately not the same check as reconcile()'s cross-near-zero
    test: cross is defined as total_pv_change - (carry+mtm+harvest), so by
    that definition alone cross ALWAYS absorbs whatever carry+mtm+harvest
    gets wrong, and carry+harvest+mtm+cross sums to total_pv_change as a
    tautology regardless of any bug in the first three. Excluding cross from
    the comparison here is what gives a double-counted or dropped carry term
    (inside harvest's own increment_carry, or mtm's base_carry) somewhere to
    be caught instead of silently absorbed.
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

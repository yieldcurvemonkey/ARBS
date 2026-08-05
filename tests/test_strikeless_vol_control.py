# tests/test_strikeless_vol_control.py
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.costs import FREE
from RVUtils.StrikelessVol.replication import (
    CurvePricer,
    ReplicationConfig,
    simulate,
)
from RVUtils.StrikelessVol.report import distribution_stats, vol_beta
from RVUtils.StrikelessVol.universe import ALL_PAIRS

PACKAGE_DV01 = 100_000.0
NEVER = 12_000  # roll_months out of reach: rolling is the runner's job


def test_distribution_stats_on_a_known_series():
    r = pd.Series([1.0, -1.0] * 126)
    s = distribution_stats(r)
    assert s["skew"] == pytest.approx(0.0, abs=1e-9)
    assert s["daily_pnl_vol"] == pytest.approx(1.0, rel=0.01)
    assert s["sharpe_annualised"] == pytest.approx(0.0, abs=1e-9)


def test_max_drawdown_is_negative_and_measured_on_the_cumulative_path():
    r = pd.Series([1.0, 1.0, -5.0, 1.0])
    assert distribution_stats(r)["max_drawdown"] == pytest.approx(-5.0)


def test_vol_beta_recovers_a_planted_relationship():
    rng = np.random.default_rng(1)
    dvol = pd.Series(rng.normal(0, 1, 60))
    pnl = 0.4 * dvol + rng.normal(0, 0.1, 60)
    out = vol_beta(pnl, dvol)
    assert out["beta"] == pytest.approx(0.4, rel=0.15)
    assert out["corr"] > 0.9


class _BothLegsDriftCtx:
    """A synthetic world where the SHORT leg's unit dv01 drifts too.

    ``SyntheticCtx`` in ``test_strikeless_vol_replication.py`` holds the short
    leg's unit dv01 at exactly 1.0, which makes "resize the long leg to a fixed
    $100k" and "resize the long leg to neutral against the short leg" the same
    rule -- so nothing there can tell them apart. Real curves are not like
    that: the short leg is never resized, so ITS repriced dv01 ages away from
    the target as well, and the two rules diverge. This ctx reproduces that
    asymmetry and nothing else; pv/theta are linear placeholders because only
    the hedge target is under test.
    """

    def __init__(self, path_bp, short_drift_per_day=2e-3):
        self.dates = pd.date_range("2026-01-01", periods=len(path_bp), freq="B")
        self.path = dict(zip(self.dates, np.asarray(path_bp, dtype=float)))
        self.day = {d: i for i, d in enumerate(self.dates)}
        self.short_drift = short_drift_per_day

    def rate(self, date, leg):
        return (0.04 if leg == "long" else 0.045) + self.path[date] * 1e-4

    def dv01(self, date, leg):
        if leg == "long":
            return 1.0 + 0.004 * self.path[date]
        return 1.0 + self.short_drift * self.day[date]

    def pv(self, date, notional_long, notional_short):
        return (notional_long + 0.5 * notional_short) * self.path[date]

    def theta(self, date, notional_long, notional_short):
        return -1e-3 * (notional_long + notional_short)


def test_the_hedge_restores_package_dv01_neutrality_when_both_legs_drift():
    """The resize must neutralise the package, not hit a fixed dollar target.

    A DV01-neutral slope package whose whole premise is that it has no
    direction cannot be allowed to carry one, and hedging the long leg back to
    a fixed $100k leaves exactly that: a residual equal to the short leg's own
    dv01 drift, which grows with the roll period (measured ~$4.6k/bp after two
    months on real USD-OIS curves).
    """
    ctx = _BothLegsDriftCtx(list(np.linspace(0.0, 100.0, 101)))
    led = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)
    hedged = led[led["n_hedges"] == 1]
    assert len(hedged) >= 3

    for d, row in hedged.iterrows():
        residual = (
            row["long_notional"] * ctx.dv01(d, "long")
            + row["short_notional"] * ctx.dv01(d, "short")
        )
        assert residual == pytest.approx(0.0, abs=1e-6)
        # ...and the rule this replaced would NOT have been neutral here, so
        # the assertion above is discriminating rather than trivially true.
        naive_long = FLATTENER * PACKAGE_DV01 / ctx.dv01(d, "long")
        naive_residual = (
            naive_long * ctx.dv01(d, "long")
            + row["short_notional"] * ctx.dv01(d, "short")
        )
        assert abs(naive_residual) > 1_000.0


# --------------------------------------------------------------------------
# Real-curve checks. Task 12's ledger VALUES are pinned only inside its
# synthetic world, and ``reconcile`` is an arithmetic identity that holds for
# any values at all -- so on real curves the four ledgers would otherwise have
# no value check whatsoever. These are that check.
# --------------------------------------------------------------------------

FIXTURE_START = dt.date(2025, 6, 2)
FIXTURE_END = dt.date(2026, 8, 3)


def _usd_pair():
    return next(p for p in ALL_PAIRS if p.market == "USD"
                and p.short.label == "10Y10Y" and p.long.label == "20Y10Y")


@pytest.fixture(scope="module")
def real_curves():
    """Real GSQUANT-RL ``USD-OIS`` curves, ~14 months of business days."""
    import os

    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    dates = pd.bdate_range(FIXTURE_START, FIXTURE_END).date.tolist()
    raw = IRSwapsMDP(source="GSQUANT-RL").bulk_get_data(
        {"curve_name": "USD-OIS", "timestamps": dates}
    )
    curves = {pd.Timestamp(ts): c for ts, c in raw.items()
              if c is not None and ts != "live"}
    if len(curves) < 0.8 * len(dates):
        pytest.fail(
            f"only {len(curves)}/{len(dates)} USD-OIS curves returned -- that is a "
            "provider failure, not a holiday calendar; not shrinking the sample."
        )
    return curves


@pytest.fixture(scope="module")
def pricer(real_curves):
    return CurvePricer(real_curves, _usd_pair(), package_dv01_usd=PACKAGE_DV01)


@pytest.mark.network
@pytest.mark.slow
def test_pricer_notionals_reproduce_build_package(pricer, real_curves):
    """The sign test. A steepener would pass every ledger check and fail the gate.

    ``simulate`` sizes with ``n = sign * package_dv01 / ctx.dv01(...)``, so the
    sign convention ``CurvePricer.dv01`` returns is what decides whether the
    simulated position is the flattener (receive the longer forward, long
    convexity) or its mirror image. Pinned against ``build_package``, which is
    the package the greeks tests were all validated on.
    """
    from RVUtils.StrikelessVol.greeks import build_package

    d0 = pricer.dates()[0]
    n_long = FLATTENER * PACKAGE_DV01 / pricer.dv01(d0, "long")
    n_short = -FLATTENER * PACKAGE_DV01 / pricer.dv01(d0, "short")

    c0 = real_curves[d0]
    pkg = build_package(c0, _usd_pair(), package_dv01_usd=PACKAGE_DV01, sign=FLATTENER)
    assert n_long == pytest.approx(float(c0.notional(pkg.long)), rel=1e-12)
    assert n_short == pytest.approx(float(c0.notional(pkg.short)), rel=1e-12)
    # receive the longer forward, pay the shorter: that IS the flattener
    assert n_long < 0.0 < n_short


@pytest.mark.network
@pytest.mark.slow
def test_the_package_ages_rather_than_being_rebuilt(pricer, real_curves):
    """Trap #1, pinned. A constant-maturity rebuild prices at par every day."""
    from RVUtils.StrikelessVol.greeks import build_package, package_npv

    dates = pricer.dates()
    c0, cN = real_curves[dates[0]], real_curves[dates[-1]]
    leg = pricer.package.long

    # same instrument, same dates, priced on a curve 14 months later
    assert c0.effective_date(leg) == cN.effective_date(leg)
    assert c0.maturity_date(leg) == cN.maturity_date(leg)
    aged_years = (pd.Timestamp(c0.maturity_date(leg))
                  - pd.Timestamp(cN.reference_date())).days / 365.0
    assert 28.0 < aged_years < 29.5  # was ~30.0 at inception: it has aged

    n_long = float(c0.notional(leg))
    n_short = float(c0.notional(pricer.package.short))
    assert pricer.pv(dates[0], n_long, n_short) == pytest.approx(0.0, abs=1.0)
    assert abs(pricer.pv(dates[-1], n_long, n_short)) > 10_000.0

    # ...whereas a package rebuilt on the later curve is struck at par there,
    # which is why rebuilding daily produces a zero-gamma result.
    fresh = build_package(cN, _usd_pair(), package_dv01_usd=PACKAGE_DV01, sign=FLATTENER)
    assert package_npv(cN.handle(), fresh) == pytest.approx(0.0, abs=1.0)


@pytest.mark.network
@pytest.mark.slow
def test_carry_is_the_task9_daily_roll_measured_on_real_curves(pricer, real_curves):
    """``carry`` checked against ``greeks.daily_roll_usd`` -- a different
    function, settled on real curves in Task 9 -- rather than against another
    number ``simulate`` produced.

    Run with the trigger out of reach so no hedge fires: the notionals then
    stay exactly at the built ones and the comparison needs no scaling, which
    is what makes it a value check rather than a restatement of linearity.
    """
    from RVUtils.StrikelessVol.greeks import daily_roll_usd

    dates = pricer.dates()
    led = simulate(
        pricer, dates,
        ReplicationConfig(trigger_bp=1e9, roll_months=NEVER,
                          package_dv01_usd=PACKAGE_DV01),
        FREE,
    )
    assert led["n_hedges"].sum() == 0

    for i in (1, 2, 3, len(dates) // 2, len(dates) - 1):
        d, prev = dates[i], dates[i - 1]
        expected = daily_roll_usd(
            real_curves[prev], pricer.package, next_date=d.to_pydatetime()
        )
        assert led.loc[d, "carry"] == pytest.approx(expected, rel=1e-9)

    carry = led["carry"].iloc[1:]
    # the flattener on an inverted ultra-long curve bleeds, every day
    assert (carry < 0).mean() > 0.95
    span_days = (dates[-1] - dates[0]).days
    per_calendar_day = carry.sum() / span_days
    assert -5_000.0 < per_calendar_day < -800.0  # Task 9 measured ~-$2,400/day


@pytest.mark.network
@pytest.mark.slow
def test_a_path_with_no_trigger_crossings_has_zero_harvest_and_repriced_mtm(
    pricer, real_curves
):
    """The real-curve analogue of the flat-path test.

    With no resizes there are no increments, so ``harvest`` must be exactly
    zero, and ``mtm`` must equal the independently repriced PV change less the
    day's carry -- ``package_npv`` called straight from ``greeks`` on the two
    adjacent curves, not read back off the ledger.
    """
    from RVUtils.StrikelessVol.greeks import package_npv

    dates = pricer.dates()
    led = simulate(
        pricer, dates,
        ReplicationConfig(trigger_bp=1e9, roll_months=NEVER,
                          package_dv01_usd=PACKAGE_DV01),
        FREE,
    )
    assert led["harvest"].abs().max() == 0.0

    for i in (1, 5, len(dates) // 3, len(dates) // 2, len(dates) - 1):
        d, prev = dates[i], dates[i - 1]
        repriced = (
            package_npv(real_curves[d].handle(), pricer.package)
            - package_npv(real_curves[prev].handle(), pricer.package)
        )
        assert led.loc[d, "mtm"] == pytest.approx(
            repriced - led.loc[d, "carry"], abs=1e-6, rel=1e-9
        )


def _replay_harvest(ctx, dates, cfg):
    """Independent replay of the trigger rule and the harvest it implies.

    Derived from the definition of the strategy, not from ``simulate``'s code:
    an increment ``dn_k`` bought at ``t_k`` and still held at ``T`` is worth
    ``dn_k * (L(T) - L(t_k) - sum_{d>t_k} theta_L(d))``, where ``L`` is the
    long leg's per-unit value and ``theta_L`` its per-unit carry -- the
    increment's own repriced P&L net of its own carry, which is what
    ``harvest`` is defined to hold. ``L`` and ``theta_L`` are read off the ctx
    with unit-notional probes, so this needs no closed form and works on real
    curves, where none exists.

    What it catches: any reallocation of value between ``carry``, ``mtm`` and
    ``harvest`` -- the failure mode ``reconcile`` provably cannot see, since
    those three cancel to the day's PV change algebraically whatever values
    they hold. What it cannot catch: an error in ``L`` or ``theta_L``
    themselves, because it reads them from the same ctx; that is what
    ``test_carry_is_the_task9_daily_roll_measured_on_real_curves`` and the
    Task 7 analytic-gamma control are for.
    """
    dates = list(dates)
    n_long = cfg.sign * cfg.package_dv01_usd / ctx.dv01(dates[0], "long")
    n_short = -cfg.sign * cfg.package_dv01_usd / ctx.dv01(dates[0], "short")
    last_hedge_rate_bp = ctx.rate(dates[0], "long") * 1e4

    trades = []  # (delta_notional, index of the day it was traded on)
    for i, d in enumerate(dates[1:], start=1):
        rate_bp = ctx.rate(d, "long") * 1e4
        if abs(rate_bp - last_hedge_rate_bp) >= cfg.trigger_bp - 1e-6:
            target = -n_short * ctx.dv01(d, "short") / ctx.dv01(d, "long")
            if target != n_long:
                trades.append((target - n_long, i))
                n_long = target
            last_hedge_rate_bp = rate_bp

    unit_pv = [ctx.pv(d, 1.0, 0.0) for d in dates]
    unit_theta = [ctx.theta(d, 1.0, 0.0) for d in dates]
    return sum(
        dn * (unit_pv[-1] - unit_pv[i] - sum(unit_theta[i + 1:]))
        for dn, i in trades
    ), trades


@pytest.mark.network
@pytest.mark.slow
def test_harvest_matches_an_independent_replay_on_real_curves(pricer):
    """The value check the real-curve ledgers were missing."""
    dates = pricer.dates()
    cfg = ReplicationConfig(trigger_bp=25.0, roll_months=NEVER,
                            package_dv01_usd=PACKAGE_DV01)
    led = simulate(pricer, dates, cfg, FREE)
    assert led["n_hedges"].sum() >= 3  # a path that actually exercises harvest

    expected, trades = _replay_harvest(pricer, dates, cfg)
    assert len(trades) == int(led["n_hedges"].sum())
    scale = max(led["harvest"].abs().sum(), 1.0)
    assert led["harvest"].sum() == pytest.approx(expected, rel=1e-6, abs=1e-4 * scale)


@pytest.mark.network
@pytest.mark.slow
def test_the_simulated_position_gains_when_the_curve_flattens(pricer, real_curves):
    """Direction, measured rather than asserted: a flattener is short the slope.

    Regresses the day's mark-to-market against the day's change in the
    constant-maturity 20y10y/10y10y spread. The slope must be negative and the
    relationship tight -- a steepener, or a leg-sign flip anywhere upstream,
    would show the opposite sign here while leaving every arithmetic check in
    this module green.
    """
    from RVUtils.StrikelessVol.conventions import slope_bp

    dates = pricer.dates()
    led = simulate(
        pricer, dates,
        ReplicationConfig(trigger_bp=25.0, roll_months=NEVER,
                          package_dv01_usd=PACKAGE_DV01),
        FREE,
    )
    spread = pd.Series(
        [slope_bp(short_rate=pricer.rate(d, "short"), long_rate=pricer.rate(d, "long"))
         for d in dates],
        index=dates,
    )
    d_spread = spread.diff()
    df = pd.concat([led["mtm"].rename("mtm"), d_spread.rename("d")], axis=1).dropna()
    beta = float(np.polyfit(df["d"], df["mtm"], 1)[0])
    assert beta < -50_000.0  # ~ -$100k per bp of steepening, by construction
    assert df["mtm"].corr(df["d"]) < -0.9


@pytest.mark.network
@pytest.mark.slow
def test_static_long_flattener_has_the_long_vol_signature():
    """THE GATE. A long-convexity position cannot have short-vol skew."""
    from scripts.sv_static_long_control import run_control

    res = run_control(
        market="USD",
        start=dt.date(2017, 1, 3),
        end=dt.date(2026, 8, 3),
    )
    daily = res["daily_pnl"]
    stats = distribution_stats(daily)

    assert len(daily) > 1500
    # skew near zero (the brief's ~0 vs ~-3 for a short 1m10y straddle)
    assert stats["skew"] > -1.0
    # positive correlation of monthly P&L to changes in implied vol
    assert res["vol_corr"] > 0.0
    # and a Sharpe in the published neighbourhood rather than a fantasy
    assert -0.5 < stats["sharpe_annualised"] < 1.5

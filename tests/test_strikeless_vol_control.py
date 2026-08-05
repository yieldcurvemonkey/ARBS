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
    ZeroConvexityPricer,
    simulate,
)
from RVUtils.StrikelessVol.report import (
    distribution_stats,
    mirror_split,
    residual_stats,
    vol_beta,
)
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


def test_residual_stats_recovers_a_planted_convexity_and_its_mirror():
    """A book that is linear-plus-``0.5*g*x**2`` must leave a signed residual.

    The whole replacement statistic rests on this: the quadratic term is
    strictly signed, so removing the linear part leaves a right-skewed residual
    for long convexity and its mirror for short. Planted here on a symmetric
    driver so the skew cannot come from the driver's own asymmetry.
    """
    rng = np.random.default_rng(7)
    ds = pd.Series(rng.normal(0.0, 1.0, 2000))
    long_convex = -100_000.0 * ds + 0.5 * 200.0 * ds ** 2
    short_convex = -100_000.0 * ds - 0.5 * 200.0 * ds ** 2

    lo = residual_stats(long_convex, ds)
    sh = residual_stats(short_convex, ds)
    assert lo["resid_skew"] > 1.5
    assert sh["resid_skew"] < -1.5
    assert lo["resid_skew"] == pytest.approx(-sh["resid_skew"], rel=1e-6)
    assert lo["beta"] == pytest.approx(-100_000.0, rel=1e-3)


def test_residual_stats_reports_nan_rather_than_noise_on_a_purely_linear_book():
    """R^2 = 1 has no residual to take a skew of, and inventing one would
    hand the zero-convexity twin a number that looks like evidence."""
    rng = np.random.default_rng(8)
    ds = pd.Series(rng.normal(0.0, 1.0, 500))
    out = residual_stats(-100_000.0 * ds, ds)
    assert out["r2"] == pytest.approx(1.0, abs=1e-12)
    assert np.isnan(out["resid_skew"])
    assert np.isnan(out["resid_kurtosis"])


def test_mirror_split_cancels_a_misfit_common_to_both_books():
    """Tests the DIFFERENCE OPERATOR on a structure this pipeline cannot produce.

    **Do not read this as a model of a real mirror.** It plants a misfit term
    with the SAME sign in both books, and differencing duly cancels it, which
    is a correct test of the arithmetic and nothing more.

    A real ``sign=STEEPENER`` run does not look like this. ``simulate`` is
    exactly antisymmetric in ``sign``, so a real mirror's misfit is the
    NEGATION of the original's rather than a copy, and there is nothing to
    cancel -- see ``test_the_mirror_is_the_negation_so_pairing_only_rescales``
    and ``report.mirror_split``'s docstring for why that makes the function a
    x2 rescaling and hence report-only.

    Kept because the operator's behaviour on common-mode contamination is worth
    pinning, and because the false premise that motivated ``mirror_split``
    should stay visible beside the test that encoded it.
    """
    rng = np.random.default_rng(11)
    ds = pd.Series(rng.normal(0.0, 1.0, 4000))
    misfit = -900.0 * ds ** 3  # asymmetric, not convexity, common to both books
    convex = 0.5 * 200.0 * ds ** 2

    long_pnl = -100_000.0 * ds + convex + misfit
    short_pnl = +100_000.0 * ds - convex + misfit

    # unpaired, the misfit wins and the convex book reads NEGATIVE
    assert residual_stats(long_pnl, ds)["resid_skew"] < 0.0
    # paired, it cancels and the sign is recovered
    out = mirror_split(long_pnl, short_pnl, ds)
    assert out["split"] > 0.0
    assert out["split"] == pytest.approx(
        residual_stats(long_pnl, ds)["resid_skew"]
        - residual_stats(short_pnl, ds)["resid_skew"],
        rel=1e-12,
    )


def test_the_mirror_is_the_negation_so_pairing_only_rescales():
    """Why ``mirror_split`` adds nothing: ``simulate`` is antisymmetric in sign.

    Per-unit ``dv01`` is sign-invariant (numerator and denominator both flip),
    the notionals flip, ``pv``/``theta`` are linear in the notionals, and the
    trigger reads a sign-independent constant-maturity rate -- so both runs
    hedge on the same dates and every P&L bucket negates EXACTLY. ``cost`` is a
    magnitude fee and is the only shared additive term.

    Consequence: ``split == 2 * resid_skew_long`` with no costs, and a monotone
    positive rescaling near it with costs. A rescaling cannot change a sign, so
    pairing cannot rescue one -- which is exactly what was observed on the real
    placebo (-0.4451 unpaired became -0.8296 paired).
    """
    from RVUtils.StrikelessVol.conventions import STEEPENER
    from RVUtils.StrikelessVol.costs import CostSchedule

    rng = np.random.default_rng(3)
    ctx = _BothLegsDriftCtx(list(np.cumsum(rng.normal(0.0, 6.0, 600))))
    ds = pd.Series([ctx.rate(d, "long") for d in ctx.dates],
                   index=ctx.dates).diff() * 1e4

    flat = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), FREE)
    steep = simulate(ctx, ctx.dates,
                     ReplicationConfig(trigger_bp=25.0, sign=STEEPENER), FREE)

    for col in ("carry", "harvest", "mtm", "total"):
        assert flat[col].to_numpy() == pytest.approx(
            -steep[col].to_numpy(), abs=1e-9
        ), f"{col} is not an exact negation under sign flip"

    out = mirror_split(flat["total"], steep["total"], ds)
    solo = residual_stats(flat["total"], ds)["resid_skew"]
    assert out["split"] == pytest.approx(2.0 * solo, rel=1e-9)

    # with costs the two runs share one additive term, so the ratio moves off
    # 2 -- but stays a positive rescaling, which is the load-bearing property
    sched = CostSchedule()
    flat_c = simulate(ctx, ctx.dates, ReplicationConfig(trigger_bp=25.0), sched)
    steep_c = simulate(ctx, ctx.dates,
                       ReplicationConfig(trigger_bp=25.0, sign=STEEPENER), sched)
    assert flat_c["cost"].to_numpy() == pytest.approx(steep_c["cost"].to_numpy())
    ratio = (mirror_split(flat_c["total"], steep_c["total"], ds)["split"]
             / residual_stats(flat_c["total"], ds)["resid_skew"])
    assert 1.5 < ratio < 2.5


def test_mirror_split_reports_unusable_below_the_calibrated_r2_cut():
    """The thresholds are reporting cuts, not a gate -- but they must still fire."""
    from RVUtils.StrikelessVol.report import RESID_R2_FLOOR, RESID_R2_SIGN_USABLE

    assert RESID_R2_FLOOR < RESID_R2_SIGN_USABLE  # floor is the looser cut
    rng = np.random.default_rng(12)
    ds = pd.Series(rng.normal(0.0, 1.0, 2000))
    noisy = pd.Series(rng.normal(0.0, 120_000.0, 2000))  # swamps the linear term

    out = mirror_split(-100_000.0 * ds + noisy, 100_000.0 * ds + noisy, ds)
    assert out["min_r2"] < RESID_R2_SIGN_USABLE
    assert out["usable"] is False

    clean = mirror_split(-100_000.0 * ds + 0.5 * 200.0 * ds ** 2,
                         100_000.0 * ds - 0.5 * 200.0 * ds ** 2, ds)
    assert clean["min_r2"] > RESID_R2_SIGN_USABLE
    assert clean["usable"] is True


def test_distribution_stats_keeps_the_same_keys_when_empty():
    assert set(distribution_stats(pd.Series(dtype=float))) == set(
        distribution_stats(pd.Series([1.0, 2.0, 3.0]))
    )
    assert distribution_stats(pd.Series(dtype=float))["n"] == 0


def test_roll_segments_overlap_by_one_date_and_cover_the_path():
    """The annual roll IS this function, so it gets its own test.

    Each segment must end on the date the next one starts: the old package is
    held through the roll date (its P&L belongs to the closing segment) and the
    new one is struck on that date's curve. Without the overlap the roll date
    would contribute no P&L at all -- one business day silently lost per year.
    """
    from scripts.sv_static_long_control import roll_segments

    dates = list(pd.bdate_range("2017-01-03", "2026-08-03"))
    segs = roll_segments(dates, roll_months=12)

    assert len(segs) == 10  # 9.6 years of annual rolls
    assert segs[0][0] == 0
    assert segs[-1][1] == len(dates) - 1
    for (_, end), (nxt_start, _) in zip(segs, segs[1:]):
        assert end == nxt_start  # shared boundary date, not a gap and not a skip
    # every date is inside some segment
    covered = {i for a, b in segs for i in range(a, b + 1)}
    assert covered == set(range(len(dates)))
    # and each closed segment really is ~12 months, not a row count
    for a, b in segs[:-1]:
        span = (dates[b] - dates[a]).days
        assert 360 <= span <= 372, (dates[a], dates[b], span)


def test_roll_segments_handles_paths_shorter_than_one_roll():
    from scripts.sv_static_long_control import roll_segments

    dates = list(pd.bdate_range("2026-01-05", "2026-03-31"))
    assert roll_segments(dates, roll_months=12) == [(0, len(dates) - 1)]
    assert roll_segments([], roll_months=12) == []


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
    """The sign test, and it has to be its own test.

    ``simulate`` sizes with ``n = sign * package_dv01 / ctx.dv01(...)``, so the
    sign convention ``CurvePricer.dv01`` returns is what decides whether the
    simulated position is the flattener (receive the longer forward, long
    convexity) or its mirror image. A steepener would satisfy every arithmetic
    check in this module -- and, measured, two of the three gate criteria. Its
    ledger is the negative of the flattener's before costs (costs are a
    magnitude fee and are identical in both), so on 2017-2026 it prints skew
    -0.0815, which passes ``skew > -1.0``, and Sharpe -0.111, which passes
    ``-0.5 < sharpe < 1.5``. Only the vol correlation flips (-0.632 against
    +0.635). So the direction cannot be left to the gate; it is pinned here
    against ``build_package``, which is the package every greeks test was
    validated on.
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

    # The leg's dates are the INCEPTION curve's 20y point, not the later
    # curve's -- that is what "aged" means, and it is the assertion with
    # content. (Comparing c0.effective_date(leg) to cN.effective_date(leg)
    # would be trivially true: those dates live on the swap object, so any
    # curve asked about them returns the same answer.)
    fresh_on_cN = build_package(
        cN, _usd_pair(), package_dv01_usd=PACKAGE_DV01, sign=FLATTENER
    ).long
    assert cN.effective_date(leg) != cN.effective_date(fresh_on_cN)
    assert cN.maturity_date(leg) != cN.maturity_date(fresh_on_cN)
    assert cN.effective_date(leg) == c0.effective_date(
        build_package(c0, _usd_pair(), package_dv01_usd=PACKAGE_DV01,
                      sign=FLATTENER).long
    )
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
def test_carry_scales_per_leg_once_the_long_leg_has_been_resized(pricer, real_curves):
    """The test with hedges, which is the only place the per-leg theta bites.

    ``CurvePricer.theta`` decomposes the roll per leg (``nl*th_L + ns*th_S``)
    rather than scaling the whole package roll by the long leg's notional
    ratio. Those two agree EXACTLY while the notionals are the built ones, so
    the zero-hedge test above -- where the scale factor is identically 1.0 --
    cannot tell them apart and has no power over this choice at all. Here the
    trigger fires, the long leg is resized away from its built notional, and
    the two definitions separate.

    Checks both directions: the ledger's carry equals the per-leg value, and
    it is measurably NOT the package-scaled value, so the assertion cannot be
    satisfied by both definitions at once.
    """
    from RVUtils.StrikelessVol.greeks import daily_roll_usd

    dates = pricer.dates()
    led = simulate(
        pricer, dates,
        ReplicationConfig(trigger_bp=25.0, roll_months=NEVER,
                          package_dv01_usd=PACKAGE_DV01),
        FREE,
    )
    assert led["n_hedges"].sum() >= 3

    built_long = float(real_curves[dates[0]].notional(pricer.package.long))
    built_short = float(real_curves[dates[0]].notional(pricer.package.short))
    held_long = led["long_notional"].shift(1)
    held_short = led["short_notional"].shift(1)

    # days on which the long leg is genuinely away from its built size
    resized = [
        i for i in range(1, len(dates))
        if abs(held_long.iloc[i] / built_long - 1.0) > 1e-4
    ]
    assert len(resized) > 20, "path never departs from the built notional"

    separations = []
    for i in resized[:8] + resized[-8:]:
        d, prev = dates[i], dates[i - 1]
        nl, ns = held_long.iloc[i], held_short.iloc[i]

        # per-leg: each leg's own roll, scaled by its own notional
        handle = real_curves[prev].handle()
        rolled = handle.roll(d.to_pydatetime())
        leg_roll = {}
        for name, swap, built in (("long", pricer.package.long, built_long),
                                  ("short", pricer.package.short, built_short)):
            leg_roll[name] = (
                float(swap.npv(curves=rolled).real) - float(swap.npv(curves=handle).real)
            ) / built
        per_leg = nl * leg_roll["long"] + ns * leg_roll["short"]

        # the alternative: whole-package roll scaled by the LONG leg's ratio
        package_scaled = daily_roll_usd(
            real_curves[prev], pricer.package, next_date=d.to_pydatetime()
        ) * abs(nl) / abs(built_long)

        assert led.loc[d, "carry"] == pytest.approx(per_leg, rel=1e-9)
        separations.append(abs(per_leg - package_scaled))

    # ...and the two definitions really are different here, so the equality
    # above is a choice this test enforces rather than one it cannot see.
    assert max(separations) > 1.0


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

    Returns the harvest **per day**, not just the total. An earlier version
    returned only the total, which review pointed out would accept a harvest
    series that was correct in aggregate but temporally shuffled -- and a
    misdated harvest is a real defect, since every per-period statistic
    downstream (the yearly table, the monthly vol regression, residual skew)
    reads the daily series and not the sum.
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

    # Increments outstanding INTO each day: a resize on day t_k is held from
    # t_k+1 onward, which is the same convention simulate uses (it sets the
    # new notional after the day's ledger row is written).
    outstanding = np.zeros(len(dates))
    for dn, i in trades:
        outstanding[i + 1:] += dn
    per_day = pd.Series(
        [0.0] + [
            outstanding[i] * (unit_pv[i] - unit_pv[i - 1] - unit_theta[i])
            for i in range(1, len(dates))
        ],
        index=dates,
    )
    return per_day, trades


@pytest.mark.network
@pytest.mark.slow
def test_harvest_matches_an_independent_replay_on_real_curves(pricer):
    """The value check the real-curve ledgers were missing.

    Checked DAY BY DAY, so a harvest series that summed correctly but landed
    on the wrong dates would fail -- the total alone cannot see that.
    """
    dates = pricer.dates()
    cfg = ReplicationConfig(trigger_bp=25.0, roll_months=NEVER,
                            package_dv01_usd=PACKAGE_DV01)
    led = simulate(pricer, dates, cfg, FREE)
    assert led["n_hedges"].sum() >= 3  # a path that actually exercises harvest

    expected, trades = _replay_harvest(pricer, dates, cfg)
    assert len(trades) == int(led["n_hedges"].sum())
    scale = max(led["harvest"].abs().sum(), 1.0)

    # per-day, then the total as well
    assert led["harvest"].to_numpy() == pytest.approx(
        expected.to_numpy(), rel=1e-6, abs=1e-6 * scale
    )
    assert led["harvest"].sum() == pytest.approx(
        expected.sum(), rel=1e-6, abs=1e-4 * scale
    )
    # a shuffled-but-equal-sum series must NOT pass the per-day check, or the
    # strengthening above bought nothing
    shuffled = pd.Series(
        np.roll(led["harvest"].to_numpy(), 5), index=led.index
    )
    assert shuffled.sum() == pytest.approx(led["harvest"].sum(), rel=1e-9)
    assert shuffled.to_numpy() != pytest.approx(
        expected.to_numpy(), rel=1e-6, abs=1e-6 * scale
    )


@pytest.mark.network
@pytest.mark.slow
def test_the_book_stays_dv01_neutral_while_its_size_drifts(pricer):
    """Both halves of what the hedge rule actually does, on real curves.

    Committed as an assertion because the claim it replaces -- that the book
    shrinks ~10% over a roll period -- was written into a report as fact and
    turned out to be false when measured (the held DV01 averages ~target). The
    measurement should be as durable as the claim was.

    NEUTRALITY is enforced: after each resize the package's net DV01 is ~0,
    which is the point of targeting the held short leg rather than a fixed
    dollar figure (see ``simulate``'s hedge branch). SIZE is not: it is free to
    drift with both legs' repriced DV01s, and it does. Dollar P&L from any run
    is therefore on a moving base.
    """
    dates = pricer.dates()
    led = simulate(
        pricer, dates,
        ReplicationConfig(trigger_bp=25.0, roll_months=NEVER,
                          package_dv01_usd=PACKAGE_DV01),
        FREE,
    )
    # true signed DV01s: pricer.dv01() returns the negated per-unit value
    long_dv01 = pd.Series(
        [-led.loc[d, "long_notional"] * pricer.dv01(d, "long") for d in dates],
        index=dates,
    )
    short_dv01 = pd.Series(
        [-led.loc[d, "short_notional"] * pricer.dv01(d, "short") for d in dates],
        index=dates,
    )

    # 1. sized to target at inception, and neutral there
    assert abs(long_dv01.iloc[0]) == pytest.approx(PACKAGE_DV01, rel=1e-9)
    assert long_dv01.iloc[0] + short_dv01.iloc[0] == pytest.approx(0.0, abs=1e-6)

    # 2. neutral again after every resize -- the (Task 13) hedge-rule change
    hedged = led.index[led["n_hedges"] == 1]
    assert len(hedged) >= 3
    for d in hedged:
        assert long_dv01[d] + short_dv01[d] == pytest.approx(0.0, abs=1e-6)

    # 3. the SIZE is free to drift, and does
    size = long_dv01.abs()
    assert size.max() / size.min() > 1.10
    assert not (size.between(0.99 * PACKAGE_DV01, 1.01 * PACKAGE_DV01)).all()

    # 4. ...but it does NOT systematically shrink. This is the assertion that
    #    actually refutes the withdrawn claim: the mean sits on the target, so
    #    a ~10% average shortfall is excluded, not merely unmentioned. (On the
    #    full 2017-2026 run the daily mean is $98,813 against $100,000, range
    #    $52,672-$148,915; this fixture is one 14-month package, so the band
    #    is looser here.)
    assert size.mean() == pytest.approx(PACKAGE_DV01, rel=0.05)


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
def test_equal_gamma_pairs_receive_opposite_resid_skew_signs():
    """**The counterexample that retired ``resid_skew``. Do not delete it.**

    ``greeks.package_gamma`` measures convexity directly. Measured on real
    GSQUANT curves, the two ``universe.PLACEBO_PAIRS`` have the SAME gamma to
    within 0.2% -- and ``resid_skew`` gives them OPPOSITE SIGNS. That is not a
    marginal disagreement; it is the statistic reading noise at this signal
    level, and it is why ``residual_stats``/``mirror_split`` are report-only.

    This test pins the gamma half, which is the cheap and decisive half. The
    signs come from full 2017-2026 runs (~15 min each) and are recorded here
    rather than recomputed::

        pair                    Gamma $/bp^2   resid_skew   mirror split
        USD 10Y10Y/20Y10Y             203.86      +2.4767       +5.1325
        placebo USD 1Y5Y/2Y5Y          20.31      +0.7835       +1.6769
        placebo USD 2Y2Y/3Y2Y          20.34      -0.4451       -0.8296

    Reproduce the right-hand columns with::

        run_control(market="USD", start=date(2017,1,3), end=date(2026,8,3),
                    pair=p, sign=s, with_vol=False)["residual"]

    Note the structural point the ratio makes: 203.86/20.31 = 10.04, and the
    study pair's legs are a 10-year forward gap against the placebos' 1-year.
    Gamma tracks the forward gap, so this is a property of the instruments and
    not an artefact of one probe date.
    """
    import datetime as _dt
    import os

    from RVUtils.StrikelessVol.greeks import build_package, package_gamma
    from RVUtils.StrikelessVol.universe import PLACEBO_PAIRS

    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    probe = [_dt.date(y, 1, 15) for y in range(2017, 2027)]
    raw = IRSwapsMDP(source="GSQUANT-RL").bulk_get_data(
        {"curve_name": "USD-OIS", "timestamps": probe}
    )
    curves = {pd.Timestamp(k): v for k, v in raw.items()
              if v is not None and k != "live"}
    assert len(curves) >= 3, f"only {len(curves)} probe curves returned"

    gamma = {}
    for pair in (_usd_pair(), *PLACEBO_PAIRS):
        gs = [
            package_gamma(
                curves[d],
                build_package(curves[d], pair, package_dv01_usd=PACKAGE_DV01,
                              sign=FLATTENER),
                h_bp=25.0,
            )
            for d in sorted(curves)
        ]
        gamma[pair.name] = float(np.mean(gs))
        # every flattener here is LONG convexity: the placebos are not secretly
        # short, which is the alternative that would have exonerated -0.4451
        assert min(gs) > 0.0, f"{pair.name} has non-positive gamma somewhere"

    study = gamma[_usd_pair().name]
    p1, p2 = (gamma[p.name] for p in PLACEBO_PAIRS)

    # the two placebos are the same instrument class: same gamma...
    assert p1 == pytest.approx(p2, rel=0.01)
    # ...an order of magnitude below the study pair, tracking the forward gap
    assert study / p1 == pytest.approx(10.0, rel=0.15)
    # ...and yet resid_skew signed them +0.7835 and -0.4451 (see docstring).
    assert study > 150.0 and 15.0 < p1 < 30.0


@pytest.mark.network
@pytest.mark.slow
def test_the_zero_convexity_twin_is_exactly_the_slope_and_nothing_else(
    pricer, real_curves
):
    """The twin's construction, pinned: P&L == -package_dv01 * d(spread).

    If this drifts, the null model stops being a null model and the
    non-discrimination result below stops meaning anything.
    """
    from RVUtils.StrikelessVol.conventions import slope_bp

    dates = pricer.dates()
    twin = ZeroConvexityPricer(real_curves, _usd_pair(), package_dv01_usd=PACKAGE_DV01)
    led = simulate(
        twin, dates,
        ReplicationConfig(trigger_bp=25.0, roll_months=NEVER,
                          package_dv01_usd=PACKAGE_DV01),
        FREE,
    )
    spread = pd.Series(
        [float(slope_bp(short_rate=twin.rate(d, "short"), long_rate=twin.rate(d, "long")))
         for d in dates],
        index=dates,
    )
    expected = -PACKAGE_DV01 * spread.diff()
    assert led["total"].iloc[1:].to_numpy() == pytest.approx(
        expected.iloc[1:].to_numpy(), rel=1e-9, abs=1e-6
    )

    # no aging, no gamma, no carry, and therefore nothing to rebalance
    assert led["n_hedges"].sum() == 0
    assert led["harvest"].abs().sum() == 0.0
    assert led["carry"].abs().sum() == 0.0
    # ...and it carries the SAME first-order slope exposure as the real book
    real = simulate(
        pricer, dates,
        ReplicationConfig(trigger_bp=25.0, roll_months=NEVER,
                          package_dv01_usd=PACKAGE_DV01),
        FREE,
    )
    twin_beta = residual_stats(led["total"], spread.diff())["beta"]
    real_beta = residual_stats(real["total"], spread.diff())["beta"]
    assert twin_beta == pytest.approx(-PACKAGE_DV01, rel=1e-9)
    assert real_beta == pytest.approx(twin_beta, rel=0.15)


@pytest.mark.network
@pytest.mark.slow
def test_the_zero_convexity_twin_clears_the_old_gate_criteria():
    """**This test documents a defect in the original gate. Do not delete it.**

    Task 13 shipped with a distributional gate: daily P&L skew > -1, monthly
    correlation to changes in implied vol > 0, Sharpe in -0.5..1.5. Every one
    of those is cleared here by a book with **no convexity in it at all** -- a
    constant-maturity, DV01-matched, gamma-free, carry-free exposure to the
    same slope. It clears them BETTER than the real package on skew (+0.288 vs
    +0.087) and Sharpe (+0.228 vs +0.046), and effectively EQUAL on the vol
    correlation (+0.6129 vs +0.6353). The mechanism is that all three
    statistics are inherited from the slope itself: raw skew from
    ``skew(d spread)``, and ``vol_corr`` from the market's own
    ``corr(-d spread, d vol)``, neither of which knows anything about gamma.

    So these criteria must never be reinstated as evidence of long convexity.
    If someone tries, this test is the counterexample, runnable, on the same
    data. What replaces them is ``report.residual_stats`` -- and the twin's
    residual is NaN here (R^2 = 1), which is exactly the discrimination the
    raw statistics could not provide.
    """
    from scripts.sv_static_long_control import run_control

    res = run_control(
        market="USD",
        start=dt.date(2017, 1, 3),
        end=dt.date(2026, 8, 3),
        zero_convexity=True,
    )
    daily = res["daily_pnl"]
    stats = distribution_stats(daily)

    # the four assertions the real package is gated on, verbatim
    assert len(daily) > 1500
    assert stats["skew"] > -1.0
    assert res["vol_corr"] > 0.0
    assert -0.5 < stats["sharpe_annualised"] < 1.5

    # and it has no convexity whatsoever to have earned them with
    assert res["ledger"]["harvest"].abs().sum() == 0.0
    assert res["ledger"]["n_hedges"].sum() == 0
    assert res["residual"]["r2"] == pytest.approx(1.0, abs=1e-9)
    assert np.isnan(res["residual"]["resid_skew"])


@pytest.mark.network
@pytest.mark.slow
def test_the_original_gate_criteria_still_hold_but_do_not_discriminate():
    """The original Task 13 gate. **These assertions do not discriminate.**

    Renamed from ``test_static_long_flattener_has_the_long_vol_signature``:
    the function name is what pytest prints, and the old one asserted the
    withdrawn claim on every run.

    Kept because it is a real end-to-end smoke test -- it runs the whole
    machinery on ten years of real curves and would catch a crash, an empty
    sample, or a wildly wrong scale -- and because its numbers are the
    reference the study was originally specified against. It is NOT evidence
    of long convexity, and its title should be read as historical.

    Every assertion below is also satisfied by books with no long convexity:
    the short-convexity steepener clears the skew and Sharpe bounds
    (-0.0815 and -0.111), and the DV01-matched zero-convexity twin clears all
    four on $0 of harvest across 0 hedges, with a BETTER skew (+0.288) and
    Sharpe (+0.228) than the real package. See
    ``test_the_zero_convexity_twin_clears_the_old_gate_criteria`` forty lines
    below, which is the counterexample, and ``report.residual_stats`` for what
    replaced these criteria.
    """
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

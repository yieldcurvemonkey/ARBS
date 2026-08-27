"""``IRSwapValue`` carry/roll: the ageing rule, and the Citi Figure-7 tie-out.

Two layers, the same shape as ``tests/test_cvx_suite_carry.py``:

* PURE tests on an analytic fake curve whose par rate has a closed form, so
  every expected number here is a hand-derived literal rather than whatever the
  code happens to print. The literals discriminate the fix from the bug: the
  shipped-before-this rule aged a forward leg by shortening its TAIL, which on
  this curve gives ``+4.133333`` bp where the correct start-ageing gives
  ``+7.9`` bp.
* An INTEGRATION test (self-skipping) against the offline Citi Velocity curve
  store: ``IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING`` versus the eight published
  Figure-7 pair carries at the close of 2019-05-08. Measured on this machine:
  corr **+0.991**, MAE **0.338 bp**. The pre-fix rule scored |corr| 0.136 /
  MAE 1.578 bp on the identical inputs, and the test's negative control
  re-implements it to prove the bound actually separates them.

MUTATION CHECK (run 2026-08-27, both mutations applied to
``Query/IRSwaps/_carry_roll.py``):

* age the maturity only (restore the bug) -> the forward-leg literal, the
  tenor-preservation test, the short-tail test and the integration bound all
  fail.
* drop the ``aged_effective < spot`` floor -> the spot-leg literals fail
  (the spot row silently becomes the forwards-realised convention).
"""
from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")  # before any repo import

import datetime
import math
import re

import pytest

from Query.IRSwaps import _carry_roll
from Query.IRSwaps.IRSwapValue import IRSwapValue, IRSwapValueFunctionMap

# ---------------------------------------------------------------------------
# Analytic fake curve.
#
# Instantaneous forward f(u) = A + B*u + C*u^2, so the par rate of a leg
# starting f years forward and running t years is its mean over [f, f+t]:
#
#   R(f, t) = A + B*(f + t/2) + C*(f^2 + f*t + t^2/3)
#
# A year is exactly 365 days and settlement is 0 days, so (fwd, tenor) map to
# dates and back with no rounding and every literal below is exact.
# ---------------------------------------------------------------------------

A, B, C = 0.03, 5e-4, 1e-5
REF = datetime.date(2019, 1, 1)
_TENOR = re.compile(r"^(-?)(\d+)\s*([YMDbB])$")
_DAYS = {"Y": 365, "M": 30, "D": 1, "b": 1, "B": 1}


def fake_rate(f: float, t: float) -> float:
    return A + B * (f + t / 2.0) + C * (f * f + f * t + t * t / 3.0)


def bp(x: float) -> float:
    return x * 1e4


class FakeSwap:
    def __init__(self, effective: datetime.date, maturity: datetime.date):
        self.effective = effective
        self.maturity = maturity


class FakeCurve:
    """The slice of ``_IRSwapGenericCurve`` that ``_carry_roll`` actually uses."""

    def reference_date(self) -> datetime.date:
        return REF

    def spot_date(self) -> datetime.date:
        return REF  # 0 settlement days: keeps the closed forms exact

    def calendar_advance(self, d, tenor: str):
        m = _TENOR.match(str(tenor).strip())
        if m is None:
            raise ValueError(f"fake calendar cannot parse tenor {tenor!r}")
        sign = -1 if m.group(1) == "-" else 1
        return d + datetime.timedelta(days=sign * int(m.group(2)) * _DAYS[m.group(3)])

    def effective_date(self, sw: FakeSwap) -> datetime.date:
        return sw.effective

    def maturity_date(self, sw: FakeSwap) -> datetime.date:
        return sw.maturity

    def build_irswap(self, fwd=None, tenor=None, effective_date=None,
                     maturity_date=None, **_) -> FakeSwap:
        if effective_date is not None and maturity_date is not None:
            return FakeSwap(effective_date, maturity_date)
        eff = self.calendar_advance(REF, fwd)
        return FakeSwap(eff, self.calendar_advance(eff, tenor))

    def fair_rate(self, sw: FakeSwap) -> float:
        f = (sw.effective - REF).days / 365.0
        t = (sw.maturity - sw.effective).days / 365.0
        return fake_rate(f, t)

    # The three lines every real backend now carries, so the package-level test
    # exercises the same delegation the shipped curves do.
    def carry_bps_running(self, sw: FakeSwap, horizon: str) -> float:
        return _carry_roll.carry_bps_running(self, sw, horizon)

    def roll_bps_running(self, sw: FakeSwap, horizon: str) -> float:
        return _carry_roll.roll_bps_running(self, sw, horizon)

    def carry_and_roll_bps_running(self, sw: FakeSwap, horizon: str) -> float:
        return _carry_roll.carry_and_roll_bps_running(self, sw, horizon)


def leg(fwd_y: int, tenor_y: int) -> FakeSwap:
    c = FakeCurve()
    return c.build_irswap(fwd=f"{fwd_y}Y", tenor=f"{tenor_y}Y")


# --------------------------------------------------------------- pure: forward

def test_forward_leg_ages_its_start_not_its_tail():
    """10Yx10Y aged 1Y is 9Yx10Y, worth +7.9 bp of roll on this curve.

    Hand-derived: R(10,10) - R(9,10) = h*(B + C*(2f + t - h))
                                     = 5e-4 + 1e-5*29 = 7.9e-4.
    The tail-ageing bug computes R(10,10) - R(10,9) = +4.133333 bp instead, so
    the literal separates the two rules by 3.77 bp on a single leg."""
    c = FakeCurve()
    roll = _carry_roll.roll_bps_running(c, leg(10, 10), "1Y")
    assert roll == pytest.approx(7.9, abs=1e-9)
    # negative control: the number the maturity-only rule would have produced
    assert roll != pytest.approx(bp(fake_rate(10, 10) - fake_rate(10, 9)), abs=1e-3)


def test_forward_leg_aged_tenor_is_preserved():
    """The structural statement behind the literal, checked on the dates."""
    c = FakeCurve()
    sw = leg(10, 10)
    aged_eff, aged_mat = _carry_roll.aged_dates(c, sw, "1Y")
    assert (aged_eff - REF).days == 9 * 365          # start brought 1y nearer
    assert (aged_mat - aged_eff).days == 10 * 365    # tail UNCHANGED


def test_forward_leg_has_zero_carry():
    """A swap that has not started by the horizon has accrued nothing.

    This is the property the user's brief states outright, and it holds for
    every horizon short of the start date."""
    c = FakeCurve()
    for horizon in ("1D", "3M", "1Y", "5Y"):
        assert _carry_roll.carry_bps_running(c, leg(10, 10), horizon) == 0.0
    # ... and the composite is then pure roll
    assert (_carry_roll.carry_and_roll_bps_running(c, leg(10, 10), "1Y")
            == pytest.approx(7.9, abs=1e-9))


def test_short_tail_forward_survives_its_own_horizon():
    """10Yx1Y at a 1Y horizon ages to 9Yx1Y = +7.0 bp.

    Under the maturity-only rule this aged to a ZERO-length swap; on the real
    curve store rateslib raised ``Schedule`` errors for 10Yx1Y, 20Yx1Y and
    5Yx1Y at a 1Y horizon (probe 2019-05-08)."""
    c = FakeCurve()
    roll = _carry_roll.roll_bps_running(c, leg(10, 1), "1Y")
    assert roll == pytest.approx(bp(fake_rate(10, 1) - fake_rate(9, 1)), abs=1e-9)
    assert roll == pytest.approx(7.0, abs=1e-9)


# ------------------------------------------------------------------ pure: spot

def test_spot_leg_ages_to_the_shorter_spot():
    """0Dx10Y aged 1Y is 0Dx9Y: roll R(0,10)-R(0,9) = +3.133333 bp."""
    c = FakeCurve()
    assert _carry_roll.roll_bps_running(c, leg(0, 10), "1Y") == pytest.approx(
        3.1333333333, abs=1e-8)


def test_spot_leg_carry_is_the_forward_drop():
    """carry = R(1,9) - R(0,10) = +2.866667 bp; total = R(1,9) - R(0,9) = 6.0.

    The 6.0 bp literal is the decomposition identity in closed form: B + 10C."""
    c = FakeCurve()
    sw = leg(0, 10)
    carry = _carry_roll.carry_bps_running(c, sw, "1Y")
    total = _carry_roll.carry_and_roll_bps_running(c, sw, "1Y")
    assert carry == pytest.approx(2.8666666667, abs=1e-8)
    assert total == pytest.approx(6.0, abs=1e-8)


def test_decomposition_identity_holds_everywhere():
    """total == R_fwd - R_aged, and == carry + roll, on spot and forward legs."""
    c = FakeCurve()
    for f, t in ((0, 10), (0, 30), (2, 10), (10, 10), (20, 5), (1, 1)):
        sw = leg(f, t)
        carry = _carry_roll.carry_bps_running(c, sw, "1Y")
        roll = _carry_roll.roll_bps_running(c, sw, "1Y")
        total = _carry_roll.carry_and_roll_bps_running(c, sw, "1Y")
        assert total == pytest.approx(carry + roll, abs=1e-12)

        start = _carry_roll.horizon_start(c, "1Y")
        eff = c.effective_date(sw)
        r_fwd = c.fair_rate(sw if eff >= start else c.build_irswap(
            effective_date=start, maturity_date=c.maturity_date(sw)))
        aged_eff, aged_mat = _carry_roll.aged_dates(c, sw, "1Y")
        r_aged = c.fair_rate(c.build_irswap(effective_date=aged_eff,
                                            maturity_date=aged_mat))
        assert total == pytest.approx(bp(r_fwd - r_aged), abs=1e-9)


def test_carry_is_continuous_across_the_horizon_boundary():
    """A start just inside the horizon carries a little; just outside, nothing.

    The pre-fix guard switched on ``effective > spot``, so every forward start
    reported zero carry no matter how far inside the horizon it began."""
    c = FakeCurve()
    inside = c.build_irswap(fwd="6M", tenor="10Y")   # starts 180d out, h = 365d
    assert _carry_roll.carry_bps_running(c, inside, "1Y") > 0.0
    boundary = c.build_irswap(fwd="365D", tenor="10Y")
    assert _carry_roll.carry_bps_running(c, boundary, "1Y") == 0.0


# ------------------------------------------------------------- pure: degenerate

def test_a_swap_that_does_not_survive_the_horizon_raises():
    """A spot 1Y at a 1Y horizon has no aged rate; it used to report 0.000.

    The pre-fix pair was carry -2.348 / roll +2.348 on the real curve, summing
    to an exact zero that reads as "no carry" rather than "not a number"."""
    c = FakeCurve()
    with pytest.raises(ValueError, match="no time left"):
        _carry_roll.aged_dates(c, leg(0, 1), "1Y")
    with pytest.raises(ValueError, match="matures"):
        _carry_roll.carry_bps_running(c, leg(0, 1), "1Y")
    with pytest.raises(ValueError):
        _carry_roll.carry_and_roll_bps_running(c, leg(0, 1), "1Y")


# ----------------------------------------------------------- pure: package math

def test_package_is_the_risk_weighted_sum_of_its_legs():
    """``IRSwapValue`` aggregates ``sum(risk_weight * leg)``, unnormalised.

    A (-1 front, +1 back) curve is the Citi flattener orientation the Figure-7
    tie-out below is quoted in."""
    c = FakeCurve()
    front, back = leg(10, 10), leg(20, 10)
    vmap = IRSwapValueFunctionMap(curve=c, package=[front, back], risk_weights=[-1.0, 1.0])
    got = vmap.apply(value=IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING, horizon="1Y")
    legs = (_carry_roll.carry_and_roll_bps_running(c, back, "1Y")
            - _carry_roll.carry_and_roll_bps_running(c, front, "1Y"))
    assert got == pytest.approx(legs, abs=1e-12)
    # closed form: -h*(B + C*(2f+t-h)) differenced across the two starts
    assert got == pytest.approx(9.9 - 7.9, abs=1e-9)


# ---------------------------------------------------------------- integration

#: Citi Figure 7 is published to 2dp on eight pairs; the measured MAE is
#: 0.338 bp and the worst single pair 0.44 bp. 0.60 gives ~1.8x headroom and
#: still fails the pre-fix rule by a factor of 2.6.
FIG7_MAE_BP = 0.60
FIG7_MIN_CORR = 0.95


def _offline_pricer(day: datetime.date):
    """Store-backed pricer or ``pytest.skip`` — never a live fetch."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    try:
        mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
        pricer = mdp.get_data({"curve_name": "USD-SOFR-1D", "timestamp": day,
                               "offline": True})
    except Exception as exc:  # noqa: BLE001 — any store/build failure => skip
        pytest.skip(f"offline curve-store read failed for {day}: {str(exc)[:140]}")
    meta = pricer.meta()
    if not (isinstance(meta, dict) and meta.get("from_curve_store")):
        pytest.skip(f"curve for {day} did not come from the curve store; "
                    "the tie-out evidence was measured store-backed")
    return pricer


def _corr_mae(published, computed):
    n = len(published)
    mp, mc = sum(published) / n, sum(computed) / n
    cov = sum((p - mp) * (c - mc) for p, c in zip(published, computed))
    vp = math.sqrt(sum((p - mp) ** 2 for p in published))
    vc = math.sqrt(sum((c - mc) ** 2 for c in computed))
    corr = cov / (vp * vc) if vp and vc else float("nan")
    mae = sum(abs(p - c) for p, c in zip(published, computed)) / n
    return corr, mae


@pytest.mark.integration
def test_integration_carry_and_roll_ties_out_to_citi_figure_7():
    """The published external answer: corr +0.991 / MAE 0.338 bp, measured.

    Trade PAYS the short leg and RECEIVES the long leg, so the package weights
    are (-1, +1) and the number is the flattener's own carry — the same sign
    Citi prints."""
    from RVUtils.ConvexityRV.strat3_strikeless_vol import CITI_FIG7_SCREEN, parse_fwd

    pricer = _offline_pricer(datetime.date(2019, 5, 8))

    def pkg_carry(short, long, roll_fn=None):
        legs = []
        for lab in (short, long):
            f, t = parse_fwd(lab)
            legs.append(pricer.build_irswap(fwd=f"{f:g}Y", tenor=f"{t:g}Y", notional=1.0))
        if roll_fn is None:
            vmap = IRSwapValueFunctionMap(curve=pricer, package=legs,
                                          risk_weights=[-1.0, 1.0])
            return float(vmap.apply(value=IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING,
                                    horizon="1Y"))
        return -roll_fn(legs[0]) + roll_fn(legs[1])

    def maturity_only_roll(sw):
        """The pre-fix rule, re-implemented as the negative control."""
        aged = pricer.build_irswap(
            effective_date=pricer.effective_date(sw),
            maturity_date=pricer.calendar_advance(pricer.maturity_date(sw), "-1Y"))
        return (float(pricer.fair_rate(sw)) - float(pricer.fair_rate(aged))) * 1e4

    pairs = list(CITI_FIG7_SCREEN.items())
    published = [row[3] for _, row in pairs]
    computed = [pkg_carry(s, l) for (s, l), _ in pairs]

    corr, mae = _corr_mae(published, computed)
    assert corr >= FIG7_MIN_CORR, (corr, list(zip(published, computed)))
    assert mae <= FIG7_MAE_BP, (mae, list(zip(published, computed)))

    # negative control: the maturity-only ageing must NOT clear the same bars,
    # otherwise the bound is not measuring the fix.
    ctrl = [pkg_carry(s, l, roll_fn=maturity_only_roll) for (s, l), _ in pairs]
    ctrl_corr, ctrl_mae = _corr_mae(published, ctrl)
    assert not (ctrl_corr >= FIG7_MIN_CORR and ctrl_mae <= FIG7_MAE_BP), (ctrl_corr, ctrl_mae)


@pytest.mark.integration
def test_integration_forward_roll_matches_a_rolled_curve_reprice():
    """Independent referee: reprice the SAME swap on ``handle.roll(horizon)``.

    Forward legs only — a spot leg's rolled-curve reprice books the accrued
    floating coupon that the aged-rate identity deliberately does not, the
    wedge already recorded in ``RVUtils.CvxSuite.carry``. Measured worst gap on
    2019-05-08: 0.06 bp across 3M and 1Y horizons."""
    pricer = _offline_pricer(datetime.date(2019, 5, 8))
    handle = pricer.handle()
    for horizon, tol in (("3M", 0.10), ("1Y", 0.10)):
        rolled = handle.roll(horizon)
        for f, t in ((5, 5), (10, 10), (20, 10), (10, 1), (20, 1), (5, 1)):
            sw = pricer.build_irswap(fwd=f"{f}Y", tenor=f"{t}Y", notional=1.0)
            ours = pricer.roll_bps_running(sw, horizon)
            referee = (float(sw.rate(curves=handle)) - float(sw.rate(curves=rolled))) * 100.0
            assert abs(ours - referee) <= tol, (f, t, horizon, ours, referee)

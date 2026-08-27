"""CvxSuite carry: aged-rate identity vs rolled-curve reprice, one sign convention.

Two layers:

* PURE tests on an analytic fake curve where both carry paths are EXACT and the
  known answers are hand-derived closed forms (planted literals -7.9 / -9.9 /
  -2.0 bp). The fake's instantaneous forward is linear-plus-quadratic, so the
  par rate of a (fwd, tenor) leg has the closed form
  ``R(f,t) = A + B*(f + t/2) + C*(f^2 + f*t + t^2/3)`` and the 1y static-curve
  roll of a forward leg is ``-h*(B + C*(2f + t - h))`` in decimal.
* INTEGRATION tests (@integration, self-skipping) against the offline Citi
  Velocity curve store: the G1-style tie-out on 2026-08-21 and the Citi
  Figure-7 published-carry anchor on 2019-05-08.

Tolerances are MEASURED, not assumed (probe run 2026-08-26 on this machine,
offline store, USD-SOFR-1D):

* 2026-08-21: worst forward-leg |identity - roll/dv01| = 0.44 bp (40Yx10Y);
  worst (-1,+1) pair gap 0.42 bp.
* 2019-05-08: worst leg gap 0.19 bp, worst pair gap 0.04 bp; vs the EIGHT
  published Fig-7 carries the worst error is 0.48 bp (leg path) / 0.44 bp
  (identity path), mean |err| 0.354 bp — reproducing strat3's recorded
  CARRY_TIEOUT_2019_05_08 MAE exactly.

TOL_BP = 1.0 gives >= 2x headroom over every measured gap and sits under the
curvefly G1 gate's 1.5 bp forward-leg precedent (scripts/_curvefly_gates.py).
Spot legs are excluded from cross-path tie-outs by design: the rolled-curve
reprice books the accrued floating coupon, the aged-rate identity does not.
"""
from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")  # before any repo import

import datetime
import math

import pandas as pd
import pytest

from RVUtils.CurveFlyScreener.screener import Leg, Structure
from RVUtils.CurveFlyScreener.screener import carry_roll_bp as cfs_carry_roll_bp
from RVUtils.CvxSuite.carry import (
    carry_ccy,
    carry_roll_bp,
    leg_roll_bp,
    leg_structure,
    pair_structure,
)

#: Evidence-based agreement tolerance (module docstring): measured max 0.48 bp,
#: G1 precedent 1.5 bp.
TOL_BP = 1.0


# ---------------------------------------------------------------------------
# Analytic fake curve.
#
# Instantaneous forward f(u) = A + B*u + C*u^2 (upward sloping), so
#   R(f, t) = mean of f over [f, f+t]
#           = A + B*(f + t/2) + C*(f^2 + f*t + t^2/3).
# Static-curve roll of a FORWARD leg over h years (hand-derived):
#   R(f-h, t) - R(f, t) = -h * (B + C*(2f + t - h))          [decimal]
# e.g. f=10, t=10, h=1: -(5e-4 + 1e-5*29)      = -7.9e-4 -> -7.9 bp
#      f=20, t=10, h=1: -(5e-4 + 1e-5*49)      = -9.9e-4 -> -9.9 bp
#      pair (-1 front=10y10y, +1 back=20y10y): -9.9 - (-7.9) = -2.0 bp
# Shift/roll semantics mirror rateslib's: shift(bp) adds bp/1e4 to forwards;
# roll(to a FUTURE date) reprices an unchanged-calendar swap as its AGED self
# (the G1-verified direction). NPV = notional * (R - K) * tenor (undiscounted
# annuity), so on FORWARD legs leg_metrics' roll/dv01 is EXACTLY the aged-rate
# difference and the two carry paths agree to float precision. On SPOT legs
# they differ BY CONSTRUCTION, faithfully to the real G1 finding: the identity
# ages 0x10 to the shorter spot R(0, 9) = -3.1333 bp of roll, while the rolled
# curve reads the whole aged revaluation R(-1, 10) = -5.9 bp — the fake's
# analogue of the accrued-coupon wedge (elapsed segment included).
# ---------------------------------------------------------------------------

A, B, C = 0.03, 5e-4, 1e-5
REF = datetime.datetime(2026, 8, 21)


def fake_rate(f: float, t: float) -> float:
    return A + B * (f + t / 2.0) + C * (f * f + f * t + t * t / 3.0)


def expected_fwd_leg_roll_bp(f: float, t: float, h: float = 1.0) -> float:
    """Hand-derived closed form (see block comment) — NOT via the module."""
    return -h * (B + C * (2.0 * f + t - h)) * 1e4


class FakeHandle:
    def __init__(self, shift_dec: float = 0.0, roll_y: float = 0.0,
                 roll_sign: float = +1.0):
        self.shift_dec = shift_dec
        self.roll_y = roll_y
        self.roll_sign = roll_sign

    def shift(self, bp: float) -> "FakeHandle":
        return FakeHandle(self.shift_dec + bp / 1e4, self.roll_y, self.roll_sign)

    def roll(self, to_dt) -> "FakeHandle":
        h = (pd.Timestamp(to_dt) - pd.Timestamp(REF)).days / 365.0
        return FakeHandle(self.shift_dec, self.roll_y + self.roll_sign * h,
                          self.roll_sign)


class FakeSwap:
    def __init__(self, f: float, t: float, k: float, notional: float):
        self.f, self.t, self.k, self.notional = f, t, k, notional

    def npv(self, curves: FakeHandle) -> float:
        r = fake_rate(self.f - curves.roll_y, self.t) + curves.shift_dec
        return (r - self.k) * self.t * self.notional  # float: .real works


class FakePricer:
    """Duck-typed pricer serving BOTH kernels (curvefly + strat3.leg_metrics)."""

    def __init__(self, roll_sign: float = +1.0):
        self._roll_sign = roll_sign

    def reference_date(self):
        return REF

    def handle(self) -> FakeHandle:
        return FakeHandle(roll_sign=self._roll_sign)

    def build_irswap(self, fwd=None, tenor=None, notional=None, **kw) -> FakeSwap:
        f = float(str(fwd).rstrip("Yy"))
        t = float(str(tenor).rstrip("Yy"))
        return FakeSwap(f, t, fake_rate(f, t), notional if notional else 1.0)

    def fair_rate(self, swap: FakeSwap) -> float:
        return fake_rate(swap.f, swap.t)


# ------------------------------------------------------------------- pure: paths

def test_carry_roll_bp_known_answers_on_the_fake_curve():
    """Planted closed-form literals -7.9 / -9.9 / -2.0 bp.

    MUTATION: age toward LONGER fwd (sign flip) -> -7.9 becomes +8.1; drop the
    front leg's -1 weight -> -2.0 becomes -9.9. Either breaks a literal."""
    p = FakePricer()
    assert carry_roll_bp(p, leg_structure(10, 10)) == pytest.approx(-7.9, abs=1e-9)
    assert carry_roll_bp(p, leg_structure(20, 10)) == pytest.approx(-9.9, abs=1e-9)
    assert carry_roll_bp(p, pair_structure((10, 10), (20, 10))) == pytest.approx(-2.0, abs=1e-9)
    # negative control: the sign-flipped answer is NOT accepted
    assert carry_roll_bp(p, pair_structure((10, 10), (20, 10))) != pytest.approx(+2.0, abs=1e-3)


def test_carry_roll_bp_is_a_verbatim_delegate():
    """MUTATION: reimplement the identity locally with a subtle deviation (e.g.
    ageing tenor instead of fwd) — bit-equality with the kernel fails."""
    p = FakePricer()
    for s in (leg_structure(10, 10), pair_structure((15, 5), (20, 10))):
        assert carry_roll_bp(p, s) == cfs_carry_roll_bp(p, s, 1.0)
    # horizon is forwarded too
    s = leg_structure(10, 10)
    assert carry_roll_bp(p, s, horizon_y=2.0) == cfs_carry_roll_bp(p, s, 2.0)


def test_leg_roll_bp_matches_the_identity_exactly_on_the_fake():
    """On the fake the two paths are algebraically identical (see block comment).

    MUTATION: divide roll by gamma instead of dv01, flip the roll direction, or
    return NPV instead of bp — the closed-form literal catches all three."""
    p = FakePricer()
    assert leg_roll_bp(p, "10Yx10Y") == pytest.approx(-7.9, abs=1e-9)
    assert leg_roll_bp(p, "20Yx10Y") == pytest.approx(
        expected_fwd_leg_roll_bp(20, 10), abs=1e-9)
    for f, t in ((10, 10), (20, 10), (15, 5), (7, 1)):
        ident = carry_roll_bp(p, leg_structure(f, t))
        roll = leg_roll_bp(p, f"{f}Yx{t}Y")
        assert roll == pytest.approx(ident, abs=1e-9)
    # pair tie-out: identity == leg_roll(back) - leg_roll(front)
    pair = carry_roll_bp(p, pair_structure((10, 10), (20, 10)))
    legs = leg_roll_bp(p, "20Yx10Y") - leg_roll_bp(p, "10Yx10Y")
    assert legs == pytest.approx(pair, abs=1e-9)


def test_tieout_negative_control_a_broken_roll_must_fail():
    """The tie-out has teeth: a handle whose roll goes the WRONG WAY (ages the
    swap AWAY from today) must violate the tolerance by a wide margin.

    MUTATION: this is the control itself — if leg_roll_bp stopped consulting
    handle.roll (e.g. returned the identity path), the broken pricer would
    agree and this assert would fail."""
    broken = FakePricer(roll_sign=-1.0)
    ident = carry_roll_bp(broken, leg_structure(10, 10))       # identity: -7.9
    roll = leg_roll_bp(broken, "10Yx10Y")                      # broken:  +8.1
    assert abs(ident - roll) > TOL_BP
    assert roll == pytest.approx(+8.1, abs=1e-9)   # = -expected at h=-1 sign


def test_leg_roll_bp_label_forms_are_equivalent():
    """"20Yx10Y" == "20y10y"; "10y" == "0Yx10Y" — identical numbers.

    MUTATION: uppercase the curvefly form before parsing, or route spot labels
    to a different fwd — the equalities fail."""
    p = FakePricer()
    assert leg_roll_bp(p, "20Yx10Y") == leg_roll_bp(p, "20y10y")
    assert leg_roll_bp(p, "15Yx5Y") == leg_roll_bp(p, "15y5y")
    assert leg_roll_bp(p, "10y") == leg_roll_bp(p, "0Yx10Y")


def test_spot_legs_do_not_tie_out_across_paths():
    """The documented SPOT caveat, pinned with numbers: the identity ages 0x10
    to the shorter spot (-3.1333 bp) while the rolled curve books the whole
    aged revaluation (-5.9 bp) — a 2.77 bp wedge, way outside TOL_BP. The
    forward-leg tie-out must therefore never be extended to spot legs.

    MUTATION: make leg_roll_bp secretly reroute spot labels through the
    aged-rate identity — the wedge vanishes and the > TOL_BP assert fails."""
    p = FakePricer()
    ident = carry_roll_bp(p, leg_structure(0, 10))
    roll = leg_roll_bp(p, "10y")
    assert ident == pytest.approx(-3.1333333333, abs=1e-6)
    assert roll == pytest.approx(-5.9, abs=1e-9)
    assert abs(ident - roll) > TOL_BP


def test_leg_roll_bp_horizon_parsing():
    """"12M" lands on the same calendar date as "1Y"; "1D" matches the identity
    at h = 1/365 exactly (the fake's ACT/365 clock).

    MUTATION: parse the count but ignore the unit (always years) — "12M" would
    roll 12 YEARS and the equality fails."""
    p = FakePricer()
    assert leg_roll_bp(p, "10Yx10Y", "12M") == leg_roll_bp(p, "10Yx10Y", "1Y")
    one_day = leg_roll_bp(p, "10Yx10Y", "1D")
    assert one_day == pytest.approx(expected_fwd_leg_roll_bp(10, 10, 1.0 / 365.0),
                                    abs=1e-9)
    # identity path at h=1/365 goes through the kernel's ":g" leg labels, which
    # truncate the aged fwd to 6 significant digits (~2e-6 bp here) — hence the
    # looser bound on the CROSS-path check only
    assert one_day == pytest.approx(
        carry_roll_bp(p, leg_structure(10, 10), horizon_y=1.0 / 365.0), abs=1e-4)
    for bad in ("", "1", "Y", "1.5Y", "1Q", "one year", "0Y", "-1Y"):
        with pytest.raises(ValueError):
            leg_roll_bp(p, "10Yx10Y", bad)


def test_leg_roll_bp_rejects_garbage_labels():
    """Error paths raise loudly — no NaN-for-typo, no silent spot fallback."""
    p = FakePricer()
    for bad in ("", "10y10", "x10Y", "abc", "10", "-1y2y", "0y", "10Yx0Y", "nanY x 1Y"):
        with pytest.raises(ValueError):
            leg_roll_bp(p, bad)


# ------------------------------------------------------------------ pure: dollars

def test_carry_ccy_is_bp_times_dv01():
    """Planted: -2.0 bp x $100k/bp = -$200,000 over the horizon.

    MUTATION: return bp unscaled — the magnitude assert catches it; flip the
    dv01 sign convention — the sign asserts catch it."""
    p = FakePricer()
    s = pair_structure((10, 10), (20, 10))
    usd = carry_ccy(p, s, dv01_usd=100_000.0)
    assert usd == pytest.approx(-200_000.0, abs=1e-3)
    assert abs(usd) > 1e4                       # dollars, not bp
    # a flattener is SHORT this spread: negative dv01_usd -> POSITIVE carry here
    assert carry_ccy(p, s, dv01_usd=-100_000.0) == pytest.approx(+200_000.0, abs=1e-3)
    # NaN propagates, never coerced to zero
    assert math.isnan(carry_ccy(p, s, dv01_usd=float("nan")))
    # horizon forwarded
    assert carry_ccy(p, leg_structure(10, 10), 1e5, horizon_y=1.0) == pytest.approx(
        -7.9e5, abs=1e-3)


def test_error_paths_age_past_zero_raise():
    """The KINK_GRID spot-1y point at a 1y horizon RAISES (never a silent 0):
    a swap with no time left is not a rate. Same for over-ageing a forward.

    MUTATION: clamp the aged tenor at epsilon instead of raising — these
    pytest.raises fail."""
    p = FakePricer()
    with pytest.raises(ValueError):
        carry_roll_bp(p, leg_structure(0, 1), horizon_y=1.0)
    with pytest.raises(ValueError):
        carry_roll_bp(p, leg_structure(0, 5), horizon_y=5.0)
    with pytest.raises(ValueError):
        carry_ccy(p, leg_structure(0, 1), 1e5, horizon_y=1.0)
    # helpers refuse non-legs
    for bad in ((0.0, 0.0), (-1.0, 5.0), (float("nan"), 1.0)):
        with pytest.raises(ValueError):
            leg_structure(*bad)
    with pytest.raises(ValueError):
        pair_structure((10, 10), (20, -1))


def test_sign_convention_on_an_upward_curve():
    """G3-style: on an upward-sloping curve a long-the-rate (payer) outright has
    NEGATIVE carry (the rate rolls down); the structures are oriented long the
    quoted level. MUTATION: swap the aged/today order in the delegate — sign
    flips and this fails."""
    p = FakePricer()
    r5 = fake_rate(0, 5)
    r10 = fake_rate(0, 10)
    assert r10 > r5                                  # the fake slopes upward
    assert carry_roll_bp(p, leg_structure(0, 10)) < 0.0
    # pair orientation: long (back - front); flattener carry is its negation
    s = pair_structure((10, 10), (20, 10))
    assert -carry_roll_bp(p, s) == pytest.approx(+2.0, abs=1e-9)


def test_structure_helpers_shapes_and_labels():
    """Labels are the curvefly cache form; weights/kind are the screener's."""
    s1 = leg_structure(10, 10)
    assert isinstance(s1, Structure)
    assert s1.label == "10y10y" and s1.weights == (1.0,) and s1.kind == "outright"
    assert s1.legs == (Leg(10.0, 10.0),)
    s0 = leg_structure(0, 10)
    assert s0.label == "10y"                          # spot: no fwd prefix
    s2 = pair_structure((10, 10), (20, 10))
    assert s2.label == "10y10y/20y10y"
    assert s2.weights == (-1.0, 1.0) and s2.kind == "curve"
    assert s2.legs == (Leg(10.0, 10.0), Leg(20.0, 10.0))


# ---------------------------------------------------------------- integration

def _offline_pricer(day: datetime.date):
    """Store-backed pricer or pytest.skip — never a live fetch (offline=True)."""
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
                    "tie-out evidence was measured store-backed")
    return pricer


@pytest.mark.integration
def test_integration_tieout_two_carry_paths_agree_on_forward_legs():
    """G1-style tie-out on the real store, 2026-08-21, 1y horizon.

    Measured (probe 2026-08-26): per-leg diffs 10Yx10Y -0.07, 15Yx5Y +0.16,
    20Yx10Y +0.28, 7Yx1Y -0.33, 40Yx10Y +0.44; pair diffs 10y10y/20y10y +0.35,
    15y5y/20y10y +0.12. TOL_BP=1.0 gives >=2x headroom under G1's 1.5.

    MUTATION: flip leg_roll_bp's sign, divide by gamma, or roll the wrong way —
    every |diff| blows through 1.0 bp (the sign control quantifies it)."""
    pricer = _offline_pricer(datetime.date(2026, 8, 21))
    for lab, (f, t) in {"10Yx10Y": (10, 10), "20Yx10Y": (20, 10),
                        "15Yx5Y": (15, 5), "7Yx1Y": (7, 1),
                        "40Yx10Y": (40, 10)}.items():
        ident = carry_roll_bp(pricer, leg_structure(f, t))
        roll = leg_roll_bp(pricer, lab)
        assert math.isfinite(ident) and math.isfinite(roll)
        assert abs(ident - roll) <= TOL_BP, (lab, ident, roll)
        # negative control (guarded): where the carry is material, the
        # SIGN-FLIPPED roll path must NOT satisfy the tolerance
        if abs(ident) > TOL_BP:
            assert abs(ident - (-roll)) > TOL_BP, (lab, ident, roll)
    for front, back in (((10, 10), (20, 10)), ((15, 5), (20, 10))):
        pair = carry_roll_bp(pricer, pair_structure(front, back))
        legs = (leg_roll_bp(pricer, f"{back[0]}Yx{back[1]}Y")
                - leg_roll_bp(pricer, f"{front[0]}Yx{front[1]}Y"))
        assert abs(pair - legs) <= TOL_BP, (front, back, pair, legs)
        if abs(pair) > TOL_BP:
            assert abs(pair - (-legs)) > TOL_BP
    # label-form equivalence holds on the real engine too
    assert leg_roll_bp(pricer, "20y10y") == leg_roll_bp(pricer, "20Yx10Y")


@pytest.mark.integration
def test_integration_fig7_published_carry_anchor_2019_05_08():
    """External known answer: Citi Figure-7 published 1y carries (Doc A,
    close 2019-05-08) vs BOTH carry paths, all eight published pairs.

    The published flattener carry equals ``leg_roll_bp(short) - leg_roll_bp(long)``
    (algebraically identical to strat3's DV01-neutral ``carry_1y_bp``) and
    ``-carry_roll_bp(pair_structure(short, back=long))``. Measured worst errors:
    0.48 bp (leg path) / 0.44 bp (identity path); mean 0.354 bp — the recorded
    CARRY_TIEOUT_2019_05_08 MAE. TOL_BP=1.0.

    MUTATION: swap short/long in either path (sign flip) — 10Yx10Y/20Yx10Y
    reads +1.29 vs published -1.75, error 3.0 bp; use
    CARRY_AND_ROLL_BPS_RUNNING instead — recorded MAE 1.28 bp with the rank
    order wrong, and the -0.31 pair fails first."""
    from RVUtils.ConvexityRV.strat3_strikeless_vol import CITI_FIG7_SCREEN, parse_fwd

    pricer = _offline_pricer(datetime.date(2019, 5, 8))
    measured = {}
    for (short, long), row in CITI_FIG7_SCREEN.items():
        published = row[3]  # carry_1y_bp of the flattener
        leg_path = leg_roll_bp(pricer, short) - leg_roll_bp(pricer, long)
        ident_path = -carry_roll_bp(
            pricer, pair_structure(parse_fwd(short), parse_fwd(long)))
        measured[(short, long)] = leg_path
        assert abs(leg_path - published) <= TOL_BP, (short, long, leg_path, published)
        assert abs(ident_path - published) <= TOL_BP, (short, long, ident_path, published)
        # negative control (guarded): the sign-flipped measurement must miss
        if abs(published) > TOL_BP:
            assert abs(-leg_path - published) > TOL_BP
    # negative control across pairs: publications 2.60 bp apart (> 2*TOL) must
    # not be interchangeable — the anchor distinguishes pairs, not just scale
    far_published = CITI_FIG7_SCREEN[("10Yx5Y", "15Yx15Y")][3]      # -2.91
    near_measured = measured[("15Yx5Y", "20Yx10Y")]                 # ~= -0.01
    assert abs(CITI_FIG7_SCREEN[("15Yx5Y", "20Yx10Y")][3] - far_published) > 2 * TOL_BP
    assert abs(near_measured - far_published) > TOL_BP

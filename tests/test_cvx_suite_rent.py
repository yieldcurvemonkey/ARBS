"""Tests for RVUtils.CvxSuite.rent — planted-gamma recovery, sigma_BE known
answers with the strat1 status taxonomy, and one real-curve integration check.

Pure-logic tests monkeypatch ``rent.payoff_profile`` with an exact synthetic
quadratic, so no market data is touched; the integration test builds the real
2026-08-21 CITIVELO_EXCEL pricer offline and self-skips when the local curve
store cannot serve it.
"""

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import dataclasses
import datetime as dt
import math

import numpy as np
import pytest

import RVUtils.CvxSuite.rent as rent
from RVUtils.CvxSuite.rent import (
    DEFAULT_SHIFTS_BP,
    RentRow,
    STATUSES,
    package_gamma_usd,
    rent_row,
    sigma_be_bp_day,
)

# Deliberately ASYMMETRIC grid: with it, an even-only fit (dropped linear
# term) is biased — measured 2c = 0.9424 vs true 0.8000 for the planted
# coefficients below — so the exact-recovery assert catches that mutation too.
ASYM_SHIFTS = (-50.0, -25.0, -10.0, 10.0, 25.0, 100.0)

_PRICER = object()  # sentinels: the fake asserts pass-through identity
_PACKAGE = (object(), object())


class _QuadPayoff:
    """Stands in for curve_ops.payoff_profile: exact a + b*s + c*s^2, USD."""

    def __init__(self, a=0.0, b=0.0, c=0.0, nan_at=None):
        self.a, self.b, self.c = float(a), float(b), float(c)
        self.nan_at = nan_at
        self.calls = []

    def __call__(self, pricer, package, shifts, horizon_date=None, *,
                 net_of_spot=True, carry_ccy=0.0):
        self.calls.append({
            "pricer": pricer, "package": package,
            "shifts": np.asarray(list(shifts), dtype=float),
            "horizon_date": horizon_date,
            "net_of_spot": net_of_spot, "carry_ccy": carry_ccy,
        })
        s = np.asarray(list(shifts), dtype=float)
        p = self.a + self.b * s + self.c * s * s
        if self.nan_at is not None:
            p = p.copy()
            p[self.nan_at] = np.nan
        return p


# --------------------------------------------------------------- package gamma


def test_planted_quadratic_recovers_gamma_exactly(monkeypatch):
    """Planted (a=3, b=7, c=0.4) on the asymmetric grid recovers 2c = 0.8.

    MUTATION: return ``c`` instead of ``2c`` — the 0.8 assert fails (0.4 is
    off by 2x). MUTATION: drop the linear term from the fit — on this
    asymmetric grid the even-only estimate is 0.9424, 18% high, and the
    1e-9 relative tolerance fails. MUTATION: pass a nonzero carry_ccy or
    net_of_spot=False into the profile — the recorded-kwargs asserts fail.
    """
    fake = _QuadPayoff(a=3.0, b=7.0, c=0.4)
    monkeypatch.setattr(rent, "payoff_profile", fake)

    g = package_gamma_usd(_PRICER, _PACKAGE, shifts=ASYM_SHIFTS)

    assert g == pytest.approx(0.8, rel=1e-9)
    (call,) = fake.calls
    assert call["pricer"] is _PRICER
    assert call["package"] is _PACKAGE
    assert call["net_of_spot"] is True
    assert call["carry_ccy"] == 0.0
    assert call["horizon_date"] is None
    np.testing.assert_allclose(call["shifts"], np.asarray(ASYM_SHIFTS))


def test_planted_gamma_negative_control_rejects_the_dropped_factor(monkeypatch):
    """Negative control: the factor-2 mutation's answer (c = 0.4) must FAIL.

    Also plants a different curvature (c=0.2 -> gamma 0.4) and asserts the
    original planted answer 0.8 is NOT recovered — the planted-answer assert
    is not vacuous.
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(a=3.0, b=7.0, c=0.4))
    g = package_gamma_usd(_PRICER, _PACKAGE, shifts=ASYM_SHIFTS)
    assert not math.isclose(g, 0.4, rel_tol=1e-3)  # the dropped-2 answer

    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(a=3.0, b=7.0, c=0.2))
    g2 = package_gamma_usd(_PRICER, _PACKAGE, shifts=ASYM_SHIFTS)
    assert not math.isclose(g2, 0.8, rel_tol=1e-3)
    assert g2 == pytest.approx(0.4, rel=1e-9)


def test_gamma_sign_follows_curvature(monkeypatch):
    """Concave payoff (short local convexity, the harvest side) -> negative gamma.

    MUTATION: an ``abs()`` anywhere in the gamma path — the sign assert fails,
    and with it the whole harvest/dislocation split downstream.
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=-0.35))
    g = package_gamma_usd(_PRICER, _PACKAGE, shifts=DEFAULT_SHIFTS_BP)
    assert g == pytest.approx(-0.7, rel=1e-9)
    assert g < 0.0


def test_nonfinite_payoff_returns_nan_never_zero(monkeypatch):
    """A NaN anywhere in the repriced profile -> NaN gamma, not silent 0.

    MUTATION: np.nan_to_num / dropna before the fit — the isnan assert fails.
    """
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=0.4, nan_at=2))
    g = package_gamma_usd(_PRICER, _PACKAGE, shifts=DEFAULT_SHIFTS_BP)
    assert math.isnan(g)


def test_degenerate_inputs_raise_loudly(monkeypatch):
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=0.4))
    with pytest.raises(ValueError):
        package_gamma_usd(_PRICER, _PACKAGE, shifts=(-10.0, 10.0))  # < 3 points
    with pytest.raises(ValueError):
        package_gamma_usd(_PRICER, _PACKAGE, shifts=(5.0, 5.0, 5.0))  # not distinct
    with pytest.raises(ValueError):
        package_gamma_usd(_PRICER, _PACKAGE, shifts=(-10.0, np.nan, 10.0))
    with pytest.raises(ValueError):
        package_gamma_usd(_PRICER, [], shifts=DEFAULT_SHIFTS_BP)  # empty package


# ------------------------------------------------------------------- sigma_BE


def test_sigma_be_known_answer_and_strat3_cross_check():
    """Known answer: theta=-100 USD/day, Gamma=200 USD/bp^2 -> exactly 1.0 bp/day.

    Cross-checked against strat3 screen_frame's published spelling
    ``be_daily_exact = sqrt(2*|roll_1y/252|/gamma)`` with planted
    carry_bp_yr=-2.52, dv01=10_000 (so roll_1y_usd = -25_200 and
    theta = roll_1y/252 = -100).

    MUTATION: drop the factor 2 (sqrt(|theta|/Gamma) = 0.7071) — the 1.0
    equality fails. MUTATION: use theta in bp instead of USD — the strat3
    cross-check fails by a factor sqrt(dv01).
    """
    be, status = sigma_be_bp_day(-100.0, 200.0)
    assert status == "root"
    assert be == pytest.approx(1.0, rel=1e-12)

    carry_bp_yr, dv01, gamma = -2.52, 10_000.0, 200.0
    roll_1y_usd = carry_bp_yr * dv01
    be_strat3 = math.sqrt(2.0 * abs(roll_1y_usd / 252.0) / gamma)
    assert be == pytest.approx(be_strat3, rel=1e-12)

    # ugly-number second anchor, same independent spelling
    th2, g2 = -37.3, 142.7
    roll2_usd = th2 * 252.0  # theta is roll_1y/252 by construction
    be2, s2 = sigma_be_bp_day(th2, g2)
    assert s2 == "root"
    assert be2 == pytest.approx(math.sqrt(2.0 * abs(roll2_usd / 252.0) / g2), rel=1e-12)
    assert be2 == pytest.approx(0.7230318475404895, rel=1e-12)


def test_sigma_be_negative_control_rejects_dropped_factor():
    """Negative control: sqrt(|theta|/Gamma) (the dropped-2 answer) must fail."""
    be, _ = sigma_be_bp_day(-100.0, 200.0)
    wrong = math.sqrt(100.0 / 200.0)  # 0.7071...
    assert not math.isclose(be, wrong, rel_tol=1e-3)


def test_sigma_be_short_gamma_root_side():
    """Gamma < 0 with theta > 0 (harvest book: collects rent, short convexity)
    is a ROOT, not NaN: the realized vol above which the short-gamma book loses.

    MUTATION: gate the root on ``gamma > 0`` only (strat1's long-gamma-only
    habit) — this case would come back NaN/undefined and the harvest book's
    be_over_rv column would go dark exactly where it is the decision statistic.
    """
    be, status = sigma_be_bp_day(+80.0, -150.0)
    assert status == "root"
    assert be == pytest.approx(math.sqrt(2.0 * 80.0 / 150.0), rel=1e-12)


@pytest.mark.parametrize(
    "theta,gamma,want_status,want_kind",
    [
        (-100.0, 200.0, "root", "finite"),
        (+80.0, -150.0, "root", "finite"),
        (+50.0, 200.0, "always_cheap", "zero"),
        (0.0, 200.0, "always_cheap", "zero"),
        (+50.0, 0.0, "always_cheap", "zero"),
        (-50.0, -200.0, "never_cheap", "inf"),
        (0.0, -200.0, "never_cheap", "inf"),
        (-50.0, 0.0, "never_cheap", "inf"),
        (0.0, 0.0, "undefined", "nan"),
        (float("nan"), 200.0, "undefined", "nan"),
        (-100.0, float("nan"), "undefined", "nan"),
        (float("inf"), 200.0, "undefined", "nan"),
    ],
)
def test_sigma_be_status_truth_table(theta, gamma, want_status, want_kind):
    """The full four-quadrant truth table, strat1 value conventions.

    MUTATION: return NaN for always_cheap or never_cheap — the ``zero`` /
    ``inf`` kind asserts fail (the two states a NaN would hide are opposite:
    breakeven 0 = cheap against ANY vol vs breakeven inf = rich against ANY).
    """
    be, status = sigma_be_bp_day(theta, gamma)
    assert status == want_status
    assert status in STATUSES
    if want_kind == "finite":
        assert math.isfinite(be) and be > 0.0
    elif want_kind == "zero":
        assert be == 0.0
    elif want_kind == "inf":
        assert math.isinf(be) and be > 0
    else:
        assert math.isnan(be)


def test_always_cheap_and_never_cheap_are_distinct_states():
    """Negative control on the split itself: the two no-root states must be
    distinguishable from each other AND from NaN.

    MUTATION: collapse both to a single NaN (the exact failure strat1's
    BreakevenResult docstring warns about) — every assert here fails.
    """
    v_cheap, s_cheap = sigma_be_bp_day(+50.0, 200.0)
    v_rich, s_rich = sigma_be_bp_day(-50.0, -200.0)
    assert s_cheap != s_rich
    assert not math.isnan(v_cheap)
    assert not math.isnan(v_rich)
    assert v_cheap == 0.0
    assert math.isinf(v_rich)


# ------------------------------------------------------------------- rent_row


def test_rent_row_composes_the_pieces(monkeypatch):
    """rent_row wires gamma, theta and sigma_BE together with the documented
    unit conversions, and its result is frozen.

    Planted: c=100 -> Gamma=200 USD/bp^2; carry -2.52 bp/yr on $100k DV01
    -> carry_bp_day = -0.01, theta = -1000 USD/day, sigma_BE = sqrt(10).

    MUTATION: multiply carry by 252 instead of dividing — theta comes out
    6.35e4x too big and the sqrt(10) assert fails. MUTATION: pass carry_ccy
    into the gamma profile (double-count) — the planted Gamma changes only if
    the fake sees carry_ccy != 0, which the recorded-kwargs assert forbids.
    """
    fake = _QuadPayoff(a=0.0, b=5.0, c=100.0)
    monkeypatch.setattr(rent, "payoff_profile", fake)

    row = rent_row(_PRICER, _PACKAGE, dv01_usd=100_000.0, carry_bp_yr=-2.52)

    assert isinstance(row, RentRow)
    assert row.gamma_usd_per_bp2 == pytest.approx(200.0, rel=1e-9)
    assert row.carry_bp_day == pytest.approx(-0.01, rel=1e-12)
    assert row.theta_usd_day == pytest.approx(-1000.0, rel=1e-12)
    assert row.status == "root"
    assert row.sigma_be_bp_day == pytest.approx(math.sqrt(10.0), rel=1e-9)

    # identical to the strat3 spelling with roll_1y_usd = carry_bp_yr * dv01
    roll_1y_usd = -2.52 * 100_000.0
    assert row.sigma_be_bp_day == pytest.approx(
        math.sqrt(2.0 * abs(roll_1y_usd / 252.0) / 200.0), rel=1e-9
    )
    assert fake.calls[0]["carry_ccy"] == 0.0

    with pytest.raises(dataclasses.FrozenInstanceError):
        row.status = "tampered"


def test_rent_row_positive_carry_is_always_cheap_and_nan_carry_refuses(monkeypatch):
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=100.0))
    row = rent_row(_PRICER, _PACKAGE, dv01_usd=100_000.0, carry_bp_yr=+3.0)
    assert row.status == "always_cheap"
    assert row.sigma_be_bp_day == 0.0

    row_nan = rent_row(_PRICER, _PACKAGE, dv01_usd=100_000.0, carry_bp_yr=float("nan"))
    assert row_nan.status == "undefined"
    assert math.isnan(row_nan.sigma_be_bp_day)
    assert math.isnan(row_nan.theta_usd_day)


def test_rent_row_bad_scale_raises(monkeypatch):
    monkeypatch.setattr(rent, "payoff_profile", _QuadPayoff(c=100.0))
    for bad in (0.0, -100_000.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            rent_row(_PRICER, _PACKAGE, dv01_usd=bad, carry_bp_yr=-1.0)
    with pytest.raises(ValueError):
        rent_row(_PRICER, _PACKAGE, dv01_usd=1e5, carry_bp_yr=-1.0, business_days=0.0)


# ---------------------------------------------------------------- integration


@pytest.fixture(scope="module")
def citi_pricer_2026_08_21():
    """Offline store-backed CITIVELO_EXCEL pricer for 2026-08-21, or skip."""
    try:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        pricer = IRSwapsMDP(source="CITIVELO_EXCEL").get_data(
            {"curve_name": "USD-SOFR-1D", "timestamp": dt.date(2026, 8, 21),
             "offline": True}
        )
    except Exception as exc:  # noqa: BLE001 — a cold store is not a failure
        pytest.skip(f"local Citi curve store cannot serve 2026-08-21 offline: {exc!r}")
    if pricer is None:
        pytest.skip("IRSwapsMDP.get_data returned None for 2026-08-21 offline (store miss)")
    return pricer


@pytest.mark.integration
def test_real_flattener_gamma_positive_and_u_shaped(citi_pricer_2026_08_21):
    """The 10Yx10Y/20Yx10Y DV01-neutral flattener on the real 2026-08-21 curve.

    Convention (docs/convexityrv/DESIGN.md section 1, measured): outright
    ``bpv > 0`` = payer; the flattener PAYS the front (10Yx10Y, +100k) and
    RECEIVES the back (20Yx10Y, -100k) and is LONG convexity, so its repriced
    profile is a U with the minimum at zero shift. Theory anchor: Gamma ~
    2*(dM/1e4)*DV01 with dM = (20+5)-(10+5) = 10y -> 200 USD/bp^2, measured
    gamma_ratio ~1.00 in the strat3 tie-outs.

    MUTATION: flip either leg's bpv sign (steepener) — gamma goes negative and
    the U-shape asserts fail. MUTATION: return c instead of 2c — the ratio
    band (0.6, 1.6) catches the halved value.
    """
    from RVUtils.ConvexityRV.curve_ops import payoff_profile as real_payoff

    p = citi_pricer_2026_08_21
    assert p.meta().get("from_curve_store") is True, "pricer must be store-backed"

    front = p.build_irswap(fwd="10Y", tenor="10Y", bpv=+100_000.0)  # pay the front
    back = p.build_irswap(fwd="20Y", tenor="10Y", bpv=-100_000.0)   # receive the back
    pkg = [front, back]

    gamma = package_gamma_usd(p, pkg)
    assert math.isfinite(gamma)
    assert gamma > 0.0, "a flattener (CURVE bpv<0 convention) is long convexity"

    theory = 2.0 * (10.0 / 1e4) * 100_000.0  # 200 USD/bp^2
    assert 0.6 < gamma / theory < 1.6

    prof = real_payoff(p, pkg, (-100.0, 0.0, 100.0))
    assert prof[1] == pytest.approx(0.0, abs=1e-6)  # net_of_spot at zero shift
    assert prof[0] > prof[1], "U-shape: -100bp point must sit above the trough"
    assert prof[2] > prof[1], "U-shape: +100bp point must sit above the trough"

    # rent_row end-to-end on the real gamma with a planted negative carry
    row = rent_row(p, pkg, dv01_usd=100_000.0, carry_bp_yr=-5.0)
    assert row.status == "root"
    assert row.sigma_be_bp_day == pytest.approx(
        math.sqrt(2.0 * abs(-5.0 * 100_000.0 / 252.0) / gamma), rel=1e-9
    )

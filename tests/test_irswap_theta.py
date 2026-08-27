"""``IRSwapValue.THETA*``: the four-way split of one day's PV decay.

Two layers:

* PURE tests on an analytic curve and a hand-written cashflow table, where every
  expected number is a closed form. The load-bearing one is
  ``test_theta_is_independent_of_the_rolled_curves_normalisation``: rateslib's
  ``Curve.roll`` keeps its anchor at ``T`` and carries the translated shape
  times some constant, so ``pv_eod`` MUST divide that constant out. Measured on
  the real 2019-05-08 USD-SOFR-1D curve, ``R(T,T+1b)`` came back equal to
  today's ``D1`` to the last digit — which looks like the division is a no-op
  and is not; it is an artefact of that curve's flat first node interval.
* INTEGRATION tests (self-skipping) on the offline curve store: the identity
  closes to floating-point, the forwarding term matches ``-MtM x (1/D1 - 1)``,
  and the rolldown term agrees with ``pv01 x roll_bps_running`` to the usual
  analytic-annuity-versus-reprice gap.

MUTATION CHECK (run 2026-08-27 against ``rl_theta.theta_components``):

* drop the ``/ d1_rolled`` re-anchoring -> the normalisation test fails.
* divide the cashflow term by ``d1_rolled`` instead of ``d1`` -> the closed-form
  ``cashflows == 50.0`` literal fails.
* return ``pv_rolled`` in place of ``pv_eod`` -> both the literal theta and the
  integration rolldown cross-check fail.
"""
from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")  # before any repo import

import datetime
import math
import re

import pandas as pd
import pytest

from Query.IRSwaps.IRSwapValue import IRSwapValue, IRSwapValueFunctionMap

rl_theta = pytest.importorskip("Query.IRSwaps.backends.rateslib.rl_theta")

# ---------------------------------------------------------------------------
# Analytic curve: instantaneous forward f(u) = A + B*u, so
#   D(u) = exp(-(A*u + B*u^2/2)).
# A year is 365 days exactly; the wrapper's spot lag is zero.
# ---------------------------------------------------------------------------

A, B = 0.02, 0.001
REF = datetime.date(2019, 1, 1)
_TENOR = re.compile(r"^(-?)(\d+)\s*([YMDbB])$")
_DAYS = {"Y": 365, "M": 30, "D": 1, "b": 1, "B": 1}

#: (years from REF, cashflow). The 1Y flow is what the cashflow window catches.
FLOWS = ((1.0, 50.0), (2.0, 50.0), (3.0, 1050.0))


def D(u: float) -> float:
    return math.exp(-(A * u + B * u * u / 2.0))


def _advance(d: datetime.date, tenor: str) -> datetime.date:
    m = _TENOR.match(str(tenor).strip())
    if m is None:
        raise ValueError(f"fake calendar cannot parse tenor {tenor!r}")
    sign = -1 if m.group(1) == "-" else 1
    return d + datetime.timedelta(days=sign * int(m.group(2)) * _DAYS[m.group(3)])


class FakeCurveObject:
    """``D(u)`` shifted back by ``roll_y`` years and scaled by ``k``.

    ``k`` stands in for whatever normalisation ``rateslib.Curve.roll`` leaves on
    the rolled curve. Nothing this module reports may depend on it.
    """

    def __init__(self, roll_y: float = 0.0, k: float = 1.0):
        self.roll_y, self.k = roll_y, k

    def __getitem__(self, date) -> float:
        u = (pd.Timestamp(date).date() - REF).days / 365.0
        return self.k * D(u - self.roll_y)


class FakeSwap:
    def cashflows(self, curves: FakeCurveObject) -> pd.DataFrame:
        rows = []
        for u, cf in FLOWS:
            pay = REF + datetime.timedelta(days=int(round(u * 365)))
            rows.append({"Payment": pd.Timestamp(pay), "Cashflow": cf,
                         "NPV": cf * curves[pay]})
        return pd.DataFrame(rows)


class FakeCurve:
    """The slice of ``RLIRSwapCurve`` that ``rl_theta`` uses."""

    def __init__(self, k: float = 1.0):
        self.k = k

    def handle(self) -> FakeCurveObject:
        return FakeCurveObject()

    def reference_date(self) -> datetime.date:
        return REF

    def spot_date(self) -> datetime.date:
        return REF

    def calendar_advance(self, d, tenor: str):
        return _advance(d, tenor)

    def roll_curve(self, horizon: str) -> FakeCurveObject:
        years = (_advance(REF, horizon) - REF).days / 365.0
        return FakeCurveObject(roll_y=years, k=self.k)

    def theta_components(self, irswap, horizon: str = "1b") -> dict:
        return rl_theta.theta_components(self, irswap, horizon)


# closed forms for a 1Y horizon -------------------------------------------
PV_SOD = sum(cf * D(u) for u, cf in FLOWS)
CASHFLOWS_1Y = 50.0                      # the 1Y flow, carried to the horizon
PV_FWD_1Y = (PV_SOD - 50.0 * D(1.0)) / D(1.0)
PV_EOD_1Y = 50.0 * D(1.0) + 1050.0 * D(2.0)   # flows aged one year, k divided out
FORWARDING_1Y = -PV_SOD * (1.0 / D(1.0) - 1.0)
ROLLDOWN_1Y = PV_FWD_1Y - PV_EOD_1Y
THETA_1Y = PV_SOD - PV_EOD_1Y


def test_theta_components_are_the_closed_forms():
    """Planted literals from D(u) = exp(-(A u + B u^2/2)); no number read back.

    ``cashflows == 50.0`` exactly is the sharpest of these: the flow is carried
    from its own payment date to the horizon date, and those coincide at a 1Y
    horizon, so any other discounting choice moves it off the round number."""
    c = rl_theta.theta_components(FakeCurve(), FakeSwap(), "1Y")
    assert c["pv_sod"] == pytest.approx(PV_SOD, rel=1e-12)
    assert c["pv_fwd"] == pytest.approx(PV_FWD_1Y, rel=1e-12)
    assert c["pv_eod"] == pytest.approx(PV_EOD_1Y, rel=1e-12)
    assert c["cashflows"] == pytest.approx(50.0, rel=1e-12)
    assert c["forwarding"] == pytest.approx(FORWARDING_1Y, rel=1e-12)
    assert c["rolldown"] == pytest.approx(ROLLDOWN_1Y, rel=1e-12)
    assert c["option"] == 0.0
    assert c["theta"] == pytest.approx(THETA_1Y, rel=1e-12)


def test_the_four_parts_sum_to_theta():
    for horizon in ("1b", "1M", "1Y", "2Y"):
        c = rl_theta.theta_components(FakeCurve(), FakeSwap(), horizon)
        parts = c["cashflows"] + c["forwarding"] + c["rolldown"] + c["option"]
        assert parts == pytest.approx(c["theta"], abs=1e-9), horizon


def test_theta_is_independent_of_the_rolled_curves_normalisation():
    """``pv_eod`` must divide out the rolled curve's anchor constant.

    ``Curve.roll`` keeps its anchor at T and returns the translated shape times
    some k. Every reported number has to be the same for any k; drop the
    ``/ d1_rolled`` re-anchoring and this fails at k != 1."""
    base = rl_theta.theta_components(FakeCurve(k=1.0), FakeSwap(), "1Y")
    for k in (0.5, 0.9, 1.3, 7.0):
        other = rl_theta.theta_components(FakeCurve(k=k), FakeSwap(), "1Y")
        for field in ("theta", "cashflows", "forwarding", "rolldown", "pv_eod"):
            assert other[field] == pytest.approx(base[field], rel=1e-12), (k, field)


def test_forwarding_is_the_funding_accretion_of_the_mtm():
    """``-MtM x (1/D1 - 1)``, and zero when the MtM is zero."""
    c = rl_theta.theta_components(FakeCurve(), FakeSwap(), "1M")
    d1 = D(30.0 / 365.0)
    assert c["forwarding"] == pytest.approx(-PV_SOD * (1.0 / d1 - 1.0), rel=1e-12)
    assert c["forwarding"] < 0.0  # a positive MtM accretes, so its theta is negative


def test_a_horizon_that_does_not_advance_raises():
    with pytest.raises(ValueError, match="does not advance"):
        rl_theta.theta_components(FakeCurve(), FakeSwap(), "0D")


def test_nan_priced_cashflows_raise_rather_than_vanish():
    """A row that will not price must stop the attribution, not shrink the PV."""

    class NaNSwap(FakeSwap):
        def cashflows(self, curves):
            df = super().cashflows(curves)
            df.loc[1, "NPV"] = float("nan")
            return df

    with pytest.raises(ValueError, match="priced to NaN"):
        rl_theta.theta_components(FakeCurve(), NaNSwap(), "1Y")


def test_value_map_sums_legs_without_risk_weights():
    """THETA is a PV difference: direction lives in the notional, like NPV.

    Weighting it by the package's risk weights would double-count the
    direction, so the map must ignore them."""
    c = FakeCurve()
    pkg = [FakeSwap(), FakeSwap()]
    one = rl_theta.theta_components(c, pkg[0], "1Y")["theta"]
    for weights in ([1.0, 1.0], [-1.0, 1.0], [3.0, -7.0]):
        vm = IRSwapValueFunctionMap(curve=c, package=pkg, risk_weights=weights)
        assert vm.apply(value=IRSwapValue.THETA, horizon="1Y") == pytest.approx(
            2.0 * one, rel=1e-12), weights


def test_value_map_defaults_to_one_business_day():
    c = FakeCurve()
    vm = IRSwapValueFunctionMap(curve=c, package=[FakeSwap()], risk_weights=[1.0])
    assert vm.apply(value=IRSwapValue.THETA) == pytest.approx(
        vm.apply(value=IRSwapValue.THETA, horizon="1b"), rel=1e-12)
    assert vm.apply(value=IRSwapValue.THETA_OPTION) == 0.0


def test_the_theta_family_carries_its_horizon_into_the_query_label():
    """A 1b theta and a 1M theta are different series; the label has to say so.

    Without this the second one overwrites the first in the timeseries cache."""
    from Query.IRSwaps.IRSwapQuery import _HORIZON_VALUE_IDS

    for member in (IRSwapValue.THETA, IRSwapValue.THETA_CASHFLOWS,
                   IRSwapValue.THETA_FORWARDING, IRSwapValue.THETA_ROLLDOWN,
                   IRSwapValue.THETA_OPTION):
        assert member in _HORIZON_VALUE_IDS


def test_quantlib_backend_refuses_rather_than_approximates():
    """QuantLib has no static-curve roll; saying so beats returning the
    forwards-realised curve's answer under the wrong name."""
    from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve

    stub = QLIRSwapCurve.__new__(QLIRSwapCurve)
    with pytest.raises(NotImplementedError, match="static-curve roll"):
        stub.roll_curve("1b")
    with pytest.raises(NotImplementedError, match="THETA"):
        stub.theta_components(None, "1b")


# ---------------------------------------------------------------- integration

def _offline_pricer(day: datetime.date):
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    try:
        mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
        pricer = mdp.get_data({"curve_name": "USD-SOFR-1D", "timestamp": day,
                               "offline": True})
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"offline curve-store read failed for {day}: {str(exc)[:140]}")
    meta = pricer.meta()
    if not (isinstance(meta, dict) and meta.get("from_curve_store")):
        pytest.skip(f"curve for {day} did not come from the curve store")
    return pricer


@pytest.mark.integration
def test_integration_identity_closes_on_the_real_curve():
    """Measured 2019-05-08: every residual is 0 to floating point."""
    import rateslib as rl

    pricer = _offline_pricer(datetime.date(2019, 5, 8))
    specs = [dict(fwd="0D", tenor="10Y", notional=100_000_000),
             dict(fwd="0D", tenor="10Y", notional=-100_000_000),
             dict(fwd="0D", tenor="10Y", notional=100_000_000, fixed_rate=0.0300),
             dict(fwd="5Y", tenor="5Y", notional=100_000_000),
             dict(fwd="0D", tenor="30Y", notional=100_000_000)]
    for horizon in ("1b", "1M"):
        t1 = pricer.calendar_advance(pricer.reference_date(), horizon)
        d1 = float(pricer.handle()[rl.dt(t1.year, t1.month, t1.day)])
        for spec in specs:
            sw = pricer.build_irswap(**spec)
            c = pricer.theta_components(sw, horizon)
            parts = c["cashflows"] + c["forwarding"] + c["rolldown"] + c["option"]
            scale = max(1.0, abs(c["theta"]))
            assert abs(parts - c["theta"]) / scale < 1e-9, (spec, horizon, c)
            # forwarding is exactly the funding accretion of the SOD MtM
            assert c["forwarding"] == pytest.approx(
                -c["pv_sod"] * (1.0 / d1 - 1.0), rel=1e-9), (spec, horizon)


#: The rolled-curve reprice and the aged-instrument par rate are two different
#: measures of the same idea, and the gate between them is an ABSOLUTE bp bound,
#: never a ratio: a one-day rolldown is 0.001-0.04 bp, so a 0.005 bp measurement
#: gap is a 5x ratio and means nothing. Measured worst gap across nine legs on
#: two dates (2019-05-08 26-node, 2026-08-21 45-node) is 0.040 bp; 0.06 gives
#: 1.5x headroom. Reversing the roll direction moves a 10Y by ~0.013 bp -- under
#: this bar -- which is why the SIGN is tested separately, on the legs where the
#: signal is big enough to have one.
ROLL_AGREEMENT_BP = 0.06


@pytest.mark.integration
@pytest.mark.parametrize("day", [datetime.date(2019, 5, 8), datetime.date(2026, 8, 21)])
def test_integration_rolldown_matches_the_bp_roll_measure_in_bp(day):
    """``rolldown / pv01`` against ``roll_bps_running``, in bp, 1b horizon.

    Not a ratio test. On 2019-05-08 the spot 5Y's two measures are +0.0012 and
    -0.0056 bp — opposite signs on a quantity neither resolves — while the gap
    between them is 0.0068 bp, which is the number that is actually bounded."""
    pricer = _offline_pricer(day)
    for fwd, tenor in (("0D", "2Y"), ("0D", "5Y"), ("0D", "10Y"), ("0D", "20Y"),
                       ("0D", "30Y"), ("0D", "40Y"), ("5Y", "5Y"), ("10Y", "10Y"),
                       ("20Y", "10Y")):
        sw = pricer.build_irswap(fwd=fwd, tenor=tenor, notional=100_000_000)
        rolldown_bp = pricer.theta_components(sw, "1b")["rolldown"] / pricer.pv01(sw)
        aged_bp = pricer.roll_bps_running(sw, "1b")
        assert abs(rolldown_bp - aged_bp) <= ROLL_AGREEMENT_BP, (
            day, fwd, tenor, rolldown_bp, aged_bp)


@pytest.mark.integration
def test_integration_rolldown_has_the_right_sign_where_the_signal_is_real():
    """Where a one-day rolldown is big enough to have a sign, it must be right.

    A 10Y and a 5Yx5Y on the 2019-05-08 upward curve both roll DOWN in rate, so
    a payer bleeds: positive theta contribution. MUTATION: rolling the curve the
    other way (``roll("-1b")``) flips both."""
    pricer = _offline_pricer(datetime.date(2019, 5, 8))
    for fwd, tenor in (("0D", "10Y"), ("5Y", "5Y")):
        payer = pricer.build_irswap(fwd=fwd, tenor=tenor, notional=100_000_000)
        receiver = pricer.build_irswap(fwd=fwd, tenor=tenor, notional=-100_000_000)
        rd_pay = pricer.theta_components(payer, "1b")["rolldown"]
        rd_rec = pricer.theta_components(receiver, "1b")["rolldown"]
        assert rd_pay > 0.0, (fwd, tenor, rd_pay)
        assert rd_rec == pytest.approx(-rd_pay, rel=1e-9)
        assert pricer.roll_bps_running(payer, "1b") > 0.0  # rate rolls down


@pytest.mark.integration
def test_integration_a_par_swap_has_no_forwarding_and_no_cashflow_today():
    """At par the MtM is zero, so the whole of one day's theta is rolldown."""
    pricer = _offline_pricer(datetime.date(2019, 5, 8))
    sw = pricer.build_irswap(fwd="0D", tenor="10Y", notional=100_000_000)
    c = pricer.theta_components(sw, "1b")
    assert abs(c["pv_sod"]) < 1e-6
    assert c["cashflows"] == 0.0
    assert abs(c["forwarding"]) < 1e-6
    assert c["rolldown"] == pytest.approx(c["theta"], rel=1e-12)
    assert c["theta"] > 0.0  # a payer on an upward curve bleeds rolldown

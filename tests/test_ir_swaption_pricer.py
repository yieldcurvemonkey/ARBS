import datetime as dt
import importlib

import QuantLib as ql
import pytest

from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMarketContext
from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
from Query.IRSwaptions.pricer import IRSwaptionPricable, leg_charm, leg_metrics, leg_spot_npv, leg_theta_1d, leg_veta


pricer_module = importlib.import_module("Query.IRSwaptions.pricer")


class _DummyCurveHandle:
    @staticmethod
    def referenceDate():
        return ql.Date(4, 3, 2026)


class _DummyContext:
    as_of_date = dt.date(2026, 3, 4)
    curve_handle = _DummyCurveHandle()


class _FakeSwaption:
    def __init__(self, leg):
        self._leg = leg

    def NPV(self):
        # NPV independent of evaluationDate but dependent on option expiry date.
        return float(self._leg.exercise_date.toordinal())


class _FakeGreekSwaption:
    def __init__(self, leg):
        self._leg = leg

    def delta(self):
        return float(self._leg.exercise_date.toordinal())

    def vega(self):
        return float(self._leg.exercise_date.toordinal()) * 2.0


def test_theta_1d_falls_back_when_eval_date_roll_is_flat(monkeypatch):
    leg = IRSwaptionPricable(
        option_type="payer",
        exercise_date=dt.date(2027, 3, 4),
        underlying_effective_date=dt.date(2027, 3, 4),
        underlying_maturity_date=dt.date(2032, 3, 4),
        strike=0.04,
        notional=1.0,
    )

    monkeypatch.setattr(pricer_module, "build_ql_swaption", lambda _ctx, l, **_k: _FakeSwaption(l))
    theta = leg_theta_1d(_DummyContext(), leg)

    # one-day roll-down in exercise date should reduce NPV by exactly 1 in this fake setup
    assert theta == -1.0


def test_charm_and_veta_fall_back_when_eval_date_roll_is_flat(monkeypatch):
    leg = IRSwaptionPricable(
        option_type="payer",
        exercise_date=dt.date(2027, 3, 4),
        underlying_effective_date=dt.date(2027, 3, 4),
        underlying_maturity_date=dt.date(2032, 3, 4),
        strike=0.04,
        notional=1.0,
    )

    monkeypatch.setattr(pricer_module, "build_ql_swaption", lambda _ctx, l, **_k: _FakeGreekSwaption(l))

    assert leg_charm(_DummyContext(), leg) == -1.0
    assert leg_veta(_DummyContext(), leg) == -2.0


def _make_constant_normal_vol_handle(as_of: dt.date, vol: float) -> ql.SwaptionVolatilityStructureHandle:
    ql_date = ql.Date(as_of.day, as_of.month, as_of.year)
    surface = ql.ConstantSwaptionVolatility(
        ql_date,
        ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        ql.ModifiedFollowing,
        float(vol),
        ql.Actual365Fixed(),
        ql.Normal,
        0.0,
    )
    handle = ql.SwaptionVolatilityStructureHandle(surface)
    handle.enableExtrapolation()
    return handle


class _StrikeSkewCube:
    def volatility_at_point(self, option_time: float, swap_years: float, strike: float) -> float:
        _ = option_time, swap_years
        return 0.0090 if strike >= 0.03 else 0.0110


def _make_context(as_of: dt.date, *, with_cube: bool) -> IRSwaptionMarketContext:
    ql_date = ql.Date(as_of.day, as_of.month, as_of.year)
    ql.Settings.instance().evaluationDate = ql_date

    curve = ql.FlatForward(ql_date, 0.03, ql.Actual365Fixed())
    curve_handle = ql.YieldTermStructureHandle(curve)
    swap_index = ql.Sofr(curve_handle)
    curve_obj = QLIRSwapCurve("USD-SOFR-1D", curve_handle, swap_index, meta_data={})
    vol_handle = _make_constant_normal_vol_handle(as_of, 0.01)
    engine = ql.BachelierSwaptionEngine(curve_handle, vol_handle)

    metadata = {"curve_source": "TEST", "surface_type": "atmf_normal", "as_of_date": as_of.isoformat()}
    if with_cube:
        metadata["vol_cube"] = _StrikeSkewCube()

    return IRSwaptionMarketContext(
        curve_name="USD-SOFR-1D",
        as_of_date=as_of,
        curve=curve_obj,
        curve_handle=curve_handle,
        swap_index=swap_index,
        vol_handle=vol_handle,
        pricing_engine=engine,
        provider="TEST",
        engine="QL",
        surface_type="atmf_normal",
        source="TEST-QL",
        metadata=metadata,
    )


def test_cube_backed_pricing_uses_strike_specific_vols_for_premiums():
    as_of = dt.date(2026, 3, 10)
    ctx_atm = _make_context(as_of, with_cube=False)
    ctx_cube = _make_context(as_of, with_cube=True)

    payer = IRSwaptionPricable(
        option_type="payer",
        exercise_date=dt.date(2027, 3, 10),
        underlying_effective_date=dt.date(2027, 3, 10),
        underlying_maturity_date=dt.date(2028, 3, 10),
        strike=0.04,
        notional=100_000_000.0,
    )
    receiver = IRSwaptionPricable(
        option_type="receiver",
        exercise_date=dt.date(2027, 3, 10),
        underlying_effective_date=dt.date(2027, 3, 10),
        underlying_maturity_date=dt.date(2028, 3, 10),
        strike=0.02,
        notional=100_000_000.0,
    )

    atm_payer_metrics = leg_metrics(ctx_atm, payer)
    atm_receiver_metrics = leg_metrics(ctx_atm, receiver)
    payer_metrics = leg_metrics(ctx_cube, payer)
    receiver_metrics = leg_metrics(ctx_cube, receiver)

    atm_fwd_gap = abs(atm_receiver_metrics["FWD_PREM"] - atm_payer_metrics["FWD_PREM"])
    cube_fwd_gap = abs(receiver_metrics["FWD_PREM"] - payer_metrics["FWD_PREM"])

    assert cube_fwd_gap > atm_fwd_gap * 10.0
    assert leg_spot_npv(ctx_cube, payer) != pytest.approx(leg_spot_npv(ctx_cube, receiver))
    assert receiver_metrics["NVOL"] > payer_metrics["NVOL"]
    assert receiver_metrics["FWD_PREM"] > payer_metrics["FWD_PREM"]

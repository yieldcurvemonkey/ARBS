import datetime as dt
import importlib

import QuantLib as ql

from Query.IRSwaptions.pricer import IRSwaptionPricable, leg_theta_1d


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

import datetime as dt
import importlib

import pytest

from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery, IRSwaptionQueryWrapper
from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure
from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue


query_module = importlib.import_module("Query.IRSwaptions.IRSwaptionQuery")


def test_query_requires_tenor_or_explicit_dates():
    with pytest.raises(ValueError):
        IRSwaptionQuery(
            curve="USD-SOFR-1D",
            structure=IRSwaptionStructure.RECEIVER,
            value=IRSwaptionValue.NVOL,
        )


def test_value_list_expansion():
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        expiry="1Y",
        tail="5Y",
        value=[IRSwaptionValue.NVOL, IRSwaptionValue.SPOT_NPV],
    )
    out = q.return_query()
    assert len(out) == 2
    assert out[0].value == IRSwaptionValue.NVOL
    assert out[1].value == IRSwaptionValue.SPOT_NPV


def test_side_and_risk_weight_algebra():
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        expiry="1Y",
        tail="5Y",
        side="buy",
        risk_weight=2.0,
    )
    q_neg = -q
    assert q_neg.risk_weight == -2.0

    q_scaled = q * 0.5
    assert q_scaled.risk_weight == 1.0

    q2 = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="10Y", risk_weight=1.0)
    combo = q + q2
    assert len(combo) == 2
    assert combo[0].risk_weight == 2.0
    assert combo[1].risk_weight == 1.0


def test_trade_date_conversion_hydrates_explicit_dates_and_strike(monkeypatch):
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        expiry="1Y",
        tail="5Y",
        strike="ATMF+10",
        structure=IRSwaptionStructure.PAYER,
        trade_date=dt.date(2026, 3, 2),
    )

    class _FakeCurve:
        @staticmethod
        def calendar_advance(d, tenor):
            token = str(tenor).upper()
            if token.endswith("Y"):
                return d + dt.timedelta(days=365 * int(token[:-1]))
            if token.endswith("M"):
                return d + dt.timedelta(days=30 * int(token[:-1]))
            raise ValueError(token)

        @staticmethod
        def build_irswap(**kwargs):
            return kwargs

        @staticmethod
        def fair_rate(_swap):
            return 0.0400

    class _FakeVol:
        @staticmethod
        def volatility(*args, **kwargs):
            _ = args, kwargs
            return 0.0080

    class _FakeContext:
        curve = _FakeCurve()
        vol_handle = _FakeVol()

    monkeypatch.setattr(query_module, "leg_model_vol", lambda *a, **k: 0.0080)
    monkeypatch.setattr(query_module, "leg_tte_years", lambda *a, **k: 1.0)
    monkeypatch.setattr(query_module, "leg_forward_rate", lambda *a, **k: 0.0400)

    resolved = q.resolve_query(dt.date(2026, 3, 5), pricer_or_curve=_FakeContext())
    skw = resolved.structure_kwargs
    assert skw["exercise_date"] == dt.date(2027, 3, 2)
    assert skw["underlying_effective_date"] == dt.date(2027, 3, 2)
    assert skw["underlying_maturity_date"] == dt.date(2032, 2, 29) or skw["underlying_maturity_date"] == dt.date(2032, 3, 1)
    assert resolved.strike == pytest.approx(0.0410, rel=0, abs=1e-8)


def test_wrapper_expression_generation():
    q1 = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="5Y", risk_weight=1.0, name="A")
    q2 = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="10Y", risk_weight=-2.0, name="B")
    w = IRSwaptionQueryWrapper([q1, q2], "A_minus_2B")
    expr = w.eval_expression()
    assert "`A`" in expr
    assert "`B`" in expr
    assert "-2.0" in expr

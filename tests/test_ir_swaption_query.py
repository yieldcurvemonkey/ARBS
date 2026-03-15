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


def test_shorthand_parses_x_delimited():
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        shorthand="5Yx5Y",
    )
    assert q.expiry == "5Y"
    assert q.tail == "5Y"
    assert q.structure_kwargs["expiry"] == "5Y"
    assert q.structure_kwargs["tail"] == "5Y"


def test_shorthand_parses_compact():
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        shorthand="5y5y",
    )
    assert q.expiry == "5Y"
    assert q.tail == "5Y"
    assert q.structure_kwargs["expiry"] == "5Y"
    assert q.structure_kwargs["tail"] == "5Y"


def test_shorthand_parses_midcurve_three_token_form():
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        shorthand="1Yx1Yx10Y",
    )
    assert q.expiry == "1Y"
    assert q.tail == "1Yx10Y"
    assert q.structure_kwargs["expiry"] == "1Y"
    assert q.structure_kwargs["tail"] == "1Yx10Y"


def test_premium_bps_alias_defaults_to_forward_bps_market_convention():
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        shorthand="1Yx5Y",
        structure_kwargs={"premium_bps": 12.5},
    )
    assert q.structure_kwargs["premium"] == pytest.approx(12.5)
    assert q.structure_kwargs["premium_type"] == "fwd_bps"
    assert "premium_bps" not in q.structure_kwargs


def test_premiums_bps_alias_normalizes_multi_leg_types():
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        shorthand="1Yx5Y",
        structure=IRSwaptionStructure.STRADDLE,
        structure_kwargs={"premiums_bps": [12.5, 8.0]},
    )
    assert q.structure_kwargs["premiums"] == [12.5, 8.0]
    assert q.structure_kwargs["premium_types"] == ["fwd_bps", "fwd_bps"]
    assert "premiums_bps" not in q.structure_kwargs


def test_conflicting_scalar_premium_inputs_raise():
    with pytest.raises(ValueError, match="scalar premium input"):
        IRSwaptionQuery(
            curve="USD-SOFR-1D",
            shorthand="1Yx5Y",
            structure_kwargs={"premium": 125_000.0, "premium_bps": 12.5},
        )


def test_atmf_plus_offset_infers_payer_for_outright():
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        shorthand="1Yx1Y",
        strike="ATMF+100",
    )
    assert q.structure == IRSwaptionStructure.PAYER
    assert q.structure_id == IRSwaptionStructure.PAYER


def test_atmf_minus_offset_infers_receiver_for_outright():
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        shorthand="1Yx1Y",
        strike="ATMF-100",
        structure=IRSwaptionStructure.PAYER,
    )
    assert q.structure == IRSwaptionStructure.RECEIVER
    assert q.structure_id == IRSwaptionStructure.RECEIVER


def test_atmf_offset_inference_uses_structure_kwargs_strike():
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        shorthand="1Yx1Y",
        structure_kwargs={"strike": "ATMF+50"},
    )
    assert q.structure == IRSwaptionStructure.PAYER


def test_atmf_offset_does_not_override_non_outright_structure():
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        shorthand="1Yx1Y",
        structure=IRSwaptionStructure.STRADDLE,
        strike="ATMF+100",
    )
    assert q.structure == IRSwaptionStructure.STRADDLE


@pytest.mark.parametrize(
    ("strike_spec", "expected_structure"),
    [
        ("25DP", IRSwaptionStructure.PAYER),
        ("25DR", IRSwaptionStructure.RECEIVER),
    ],
)
def test_delta_strike_infers_outright_direction(strike_spec, expected_structure):
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        shorthand="1Yx1Y",
        strike=strike_spec,
        structure=IRSwaptionStructure.RECEIVER,
    )
    assert q.structure == expected_structure
    assert q.structure_id == expected_structure


def test_shorthand_conflict_with_explicit_tenor_raises():
    with pytest.raises(ValueError, match="conflicts"):
        IRSwaptionQuery(
            curve="USD-SOFR-1D",
            shorthand="5Yx5Y",
            expiry="10Y",
        )


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


@pytest.mark.parametrize(
    ("strike_spec", "expected_structure", "expected_strike"),
    [
        ("25DP", IRSwaptionStructure.PAYER, 0.042023469250588245),
        ("25DR", IRSwaptionStructure.RECEIVER, 0.037976530749411756),
    ],
)
def test_trade_date_delta_strike_resolution(monkeypatch, strike_spec, expected_structure, expected_strike):
    q = IRSwaptionQuery(
        curve="USD-SOFR-1D",
        expiry="1Y",
        tail="1Y",
        strike=strike_spec,
        trade_date=dt.date(2026, 3, 2),
    )

    class _FakeCurve:
        @staticmethod
        def calendar_advance(d, tenor):
            token = str(tenor).upper()
            if token.endswith("Y"):
                return d + dt.timedelta(days=365 * int(token[:-1]))
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
            return 0.0030

    class _FakeContext:
        curve = _FakeCurve()
        vol_handle = _FakeVol()

    monkeypatch.setattr(query_module, "leg_model_vol", lambda *a, **k: 0.0030)
    monkeypatch.setattr(query_module, "leg_tte_years", lambda *a, **k: 1.0)
    monkeypatch.setattr(query_module, "leg_forward_rate", lambda *a, **k: 0.0400)

    resolved = q.resolve_query(dt.date(2026, 3, 5), pricer_or_curve=_FakeContext())

    assert q.structure == expected_structure
    assert resolved.structure == expected_structure
    assert resolved.strike == pytest.approx(expected_strike, rel=0, abs=1e-8)


def test_wrapper_expression_generation():
    q1 = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="5Y", risk_weight=1.0, name="A")
    q2 = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="10Y", risk_weight=-2.0, name="B")
    w = IRSwaptionQueryWrapper([q1, q2], "A_minus_2B")
    expr = w.eval_expression()
    assert "`A`" in expr
    assert "`B`" in expr
    assert "-2.0" in expr

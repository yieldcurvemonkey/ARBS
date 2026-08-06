import datetime

import pytest

pytest.importorskip("rateslib")
pytest.importorskip("QuantLib")

import MDP.STIRFutures.STIRFutureMDP as stir_mdp_module
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import RLSTIRFuturePricer


def test_build_pricer_from_args_rateslib26_dates_extract():
    mdp = STIRFutureMDP(source="WEBULL_STIRF-RL")

    pricer = mdp._build_pricer_from_args(
        {
            "symbol": "ZQH26",
            "price": 95.125,
            "timestamp": "2026-01-15T15:30:00+00:00",
            "schema": 1,
        }
    )

    assert isinstance(pricer.effective_date(), datetime.date)
    assert isinstance(pricer.maturity_date(), datetime.date)
    assert pricer.effective_date() < pricer.maturity_date()


def test_rlstirfuture_pricer_pv01_stirf_contracts_rateslib26_safe(monkeypatch):
    pricer = RLSTIRFuturePricer(
        rl_stirf_id="SR3H26",
        reference_date=datetime.date(2026, 1, 15),
        effective_date=datetime.date(2026, 3, 18),
        maturity_date=datetime.date(2026, 6, 17),
        curve="USD-SOFR-1D",
        price=95.0,
        contracts=1,
        notional=1_000_000,
        meta_data={},
    )

    class _DummyDelta:
        real = -2.0

    class _DummyPricable:
        def analytic_delta(self, *args, **kwargs):
            # rateslib 2.7 made the curve argument MANDATORY on analytic_delta,
            # so RLSTIRFuturePricer.pv01 now passes a unit (DF==1) discount
            # curve - a future carries no discounting, so that reproduces the
            # old no-argument value exactly. The dummy has to accept it or this
            # test asserts against a signature rateslib no longer has.
            return _DummyDelta()

    class _DummyKwargs:
        meta = {"contracts": 5}

    class _DummyStirf:
        _kwargs = _DummyKwargs()

    monkeypatch.setattr(pricer, "build_stirf", lambda *args, **kwargs: _DummyPricable())
    five_contracts = pricer.pv01(stirf=_DummyStirf())

    assert five_contracts == pytest.approx(10.0)


def test_stir_proxy_fallback_when_socksio_missing(monkeypatch):
    monkeypatch.setattr(stir_mdp_module, "_socksio_available", lambda: False)
    STIRFutureMDP._BARCHART_STATE = {}

    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")

    assert mdp._barchart_proxy_hosts == [None]
    assert mdp._choose_barchart_proxy() == (None, None)

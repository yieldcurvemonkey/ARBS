import datetime

import pytest

import MDP.USTFutures.USTFuturesMDP as ustf_mdp_module
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
from Query.USTFutures.backends.rateslib.RLUSTFuturePricer import RLUSTFuturePricer


class _DummyBasketPricer:
    def clean_price(self) -> float:
        return 100.0

    def settlement_date(self) -> datetime.date:
        return datetime.date(2026, 3, 4)


class _DummyBondFuture:
    def __init__(self):
        self.ctd_inputs = []
        self.ytm_inputs = []

    def ctd_index(self, *, future_price, prices, settlement, ordered=False):
        self.ctd_inputs.append((future_price, tuple(prices), settlement, ordered))
        return 0

    def ytm(self, *, future_price):
        self.ytm_inputs.append(future_price)
        return [0.10 - 0.0005 * float(future_price)]


def test_yield_to_maturity_from_price_uses_supplied_future_price(monkeypatch):
    pricer = RLUSTFuturePricer(
        symbol="TYM26",
        reference_date=datetime.date(2026, 3, 4),
        price=112.0,
    )
    pricer._basket_pricers = [_DummyBasketPricer()]
    dummy_bf = _DummyBondFuture()
    monkeypatch.setattr(pricer, "build_rateslib_object", lambda curves=None, early_or_late_delivery=None: dummy_bf)

    y1 = pricer.yield_to_maturity_from_price(111.0)
    y2 = pricer.yield_to_maturity_from_price(113.0)

    assert y1 == pytest.approx(0.10 - 0.0005 * 111.0)
    assert y2 == pytest.approx(0.10 - 0.0005 * 113.0)
    assert dummy_bf.ctd_inputs[0][0] == pytest.approx(111.0)
    assert dummy_bf.ctd_inputs[1][0] == pytest.approx(113.0)


def test_yield_to_maturity_uses_passed_pricable_price(monkeypatch):
    pricer = RLUSTFuturePricer(
        symbol="TYM26",
        reference_date=datetime.date(2026, 3, 4),
        price=112.0,
    )
    pricer._basket_pricers = [_DummyBasketPricer()]
    dummy_bf = _DummyBondFuture()
    monkeypatch.setattr(pricer, "build_rateslib_object", lambda curves=None, early_or_late_delivery=None: dummy_bf)

    ustf = pricer.build_ustf(price=109.5)
    ytm = pricer.yield_to_maturity(ustf)

    assert ytm == pytest.approx(0.10 - 0.0005 * 109.5)
    assert dummy_bf.ctd_inputs[0][0] == pytest.approx(109.5)
    assert dummy_bf.ytm_inputs[0] == pytest.approx(109.5)


def test_ust_proxy_fallback_when_socksio_missing(monkeypatch):
    monkeypatch.setattr(ustf_mdp_module, "_socksio_available", lambda: False)
    USTFuturesMDP._BARCHART_STATE = {}

    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")

    assert mdp._barchart_proxy_hosts == [None]
    assert mdp._choose_barchart_proxy() == (None, None)


def test_ust_get_barchart_fetcher_builds_fresh_instance_each_call(monkeypatch):
    USTFuturesMDP._BARCHART_STATE = {}
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    created = []

    class _DummyFetcher:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.seed_calls = 0
            created.append(self)

        def _fetch_session_tokens(self, dummy_symbol="BTC"):  # noqa: ARG002
            self.seed_calls += 1

        def close(self):
            return None

    monkeypatch.setattr("MDP.USTFutures.USTFuturesMDP.BarchartFetcher", _DummyFetcher)
    monkeypatch.setattr(
        mdp,
        "_choose_barchart_proxy",
        lambda: (
            {"http": "http://proxy-user:proxy-pass@atlanta:8080", "https": "http://proxy-user:proxy-pass@atlanta:8080"},
            "atlanta.us.socks.nordhold.net",
        ),
    )

    fetcher_a = mdp._get_barchart_fetcher()
    fetcher_b = mdp._get_barchart_fetcher()

    assert fetcher_a is not fetcher_b
    assert len(created) == 2
    assert [fetcher.seed_calls for fetcher in created] == [1, 1]
    assert fetcher_a.kwargs["proxies"] == fetcher_b.kwargs["proxies"]


def test_ust_get_pricer_defaults_bond_source_when_basket_requested(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    seen = {}

    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda key: {"timestamp": "2026-03-04T20:00:00+00:00", "price": 112.0, "schema": 1})
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda key, value: None)

    def _fake_delivery_basket(*, as_of, symbol, usts_mdp_source, source):
        seen["usts_mdp_source"] = usts_mdp_source
        seen["basket_source"] = source
        return {
            "delivery": (datetime.date(2026, 3, 1), datetime.date(2026, 3, 31)),
            "basket_pricers": [],
            "conversion_factors": [],
            "contract_coupon": 6.0,
            "calc_mode": "ust_long",
        }

    monkeypatch.setattr(mdp, "get_delivery_basket", _fake_delivery_basket)
    monkeypatch.setattr(mdp, "_build_pricer", lambda **kwargs: kwargs)

    out = mdp.get_pricer({"symbols": ["TYM26"], "timestamp": datetime.date(2026, 3, 4), "include_basket": True})

    assert "TYM26" in out
    assert seen["usts_mdp_source"] == "USTS_FEDINVEST_WSJ_LIVE-RL"
    assert seen["basket_source"] == "RL_CME_TCF"

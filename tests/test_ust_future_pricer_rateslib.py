import datetime

import pandas as pd
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
        self.gross_basis_inputs = []
        self.net_basis_inputs = []
        self.implied_repo_inputs = []

    def ctd_index(self, *, future_price, prices, settlement, ordered=False):
        self.ctd_inputs.append((future_price, tuple(prices), settlement, ordered))
        return 0

    def ytm(self, *, future_price):
        self.ytm_inputs.append(future_price)
        return [0.10 - 0.0005 * float(future_price)]

    def gross_basis(self, *, future_price, prices, settlement=None, dirty=False):
        self.gross_basis_inputs.append((future_price, tuple(prices), settlement, dirty))
        return [float(price) - float(future_price) for price in prices]

    def net_basis(self, *, future_price, prices, repo_rate, settlement, delivery, convention, dirty=False):
        self.net_basis_inputs.append((future_price, tuple(prices), repo_rate, settlement, delivery, convention, dirty))
        return [float(repo_rate) + idx for idx, _ in enumerate(prices)]

    def implied_repo(self, *, future_price, prices, settlement, delivery=None, convention=None, dirty=False):
        self.implied_repo_inputs.append((future_price, tuple(prices), settlement, delivery, convention, dirty))
        return [0.01 + (0.001 * idx) for idx, _ in enumerate(prices)]


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


def test_gross_basis_uses_default_future_price_and_basket_prices(monkeypatch):
    pricer = RLUSTFuturePricer(
        symbol="TYM26",
        reference_date=datetime.date(2026, 3, 4),
        price=112.0,
    )
    pricer._basket_pricers = [_DummyBasketPricer(), _DummyBasketPricer()]
    dummy_bf = _DummyBondFuture()
    monkeypatch.setattr(pricer, "build_rateslib_object", lambda curves=None, early_or_late_delivery=None: dummy_bf)

    gross_basis = pricer.gross_basis()

    assert gross_basis == pytest.approx((-12.0, -12.0))
    assert dummy_bf.gross_basis_inputs[0] == (112.0, (100.0, 100.0), None, False)


def test_bnoc_defaults_repo_fixing_contract_imm_and_settlement(monkeypatch):
    pricer = RLUSTFuturePricer(
        symbol="TYM26",
        reference_date=datetime.date(2026, 3, 4),
        price=112.0,
        curve_id="USD-SOFR-1D",
    )
    pricer._basket_pricers = [_DummyBasketPricer(), _DummyBasketPricer()]
    dummy_bf = _DummyBondFuture()
    monkeypatch.setattr(pricer, "build_rateslib_object", lambda curves=None, early_or_late_delivery=None: dummy_bf)
    monkeypatch.setattr(
        "Query.USTFutures.backends.rateslib.RLUSTFuturePricer._fetch_fixings",
        lambda as_of_date, curve_name: pd.Series([0.0432], index=[pd.Timestamp("2026-03-03")]),
    )
    monkeypatch.setattr(
        "Query.USTFutures.backends.rateslib.RLUSTFuturePricer.resolve_delivery_contract",
        lambda symbol, as_of: ("TY", datetime.date(2026, 6, 17), 202606),
    )

    bnoc = pricer.bnoc()

    assert bnoc == pytest.approx((4.32, 5.32))
    assert dummy_bf.net_basis_inputs[0][0] == pytest.approx(112.0)
    assert dummy_bf.net_basis_inputs[0][1] == (100.0, 100.0)
    assert dummy_bf.net_basis_inputs[0][2] == pytest.approx(4.32)
    assert dummy_bf.net_basis_inputs[0][3] == datetime.datetime(2026, 3, 4)
    assert dummy_bf.net_basis_inputs[0][4] == datetime.datetime(2026, 6, 17)
    # rateslib 2.7.1 rejects a bare "ActAct"; Act/360 is also the right convention for US repo.
    assert dummy_bf.net_basis_inputs[0][5] == "Act360"
    assert dummy_bf.net_basis_inputs[0][6] is False

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

    def _fake_delivery_basket(*, as_of, symbol, usts_mdp_source, source, usts_mdp=None, ignore_cache=False):
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


def test_ust_get_pricer_live_quotes_use_globex_symbols(monkeypatch):
    mdp = USTFuturesMDP(source="SCHWAB_APP_USTF-RL")
    seen = {}

    def _stub_quotes(**kwargs):
        seen["symbols"] = list(kwargs["symbols"])
        return {
            "/ZNM26": {"bid": 112.40, "ask": 112.60, "last": 112.50, "quoteTime": 1773422799796},
            "/UBM26": {"bid": 124.10, "ask": 124.18, "last": 124.14, "quoteTime": 1773422799796},
        }

    monkeypatch.setattr(ustf_mdp_module, "get_quotes", _stub_quotes)
    monkeypatch.setattr(mdp, "get_delivery_basket", lambda **kwargs: (_ for _ in ()).throw(AssertionError("basket fetch not expected")))
    monkeypatch.setattr(
        mdp,
        "_build_pricer",
        lambda **kwargs: {
            "symbol": kwargs["symbol"],
            "price": kwargs["price"],
            "timestamp": kwargs["meta_data"]["timestamp"],
        },
    )

    out = mdp.get_pricer(
        {
            "symbols": ["TYM26", "WNM26"],
            "timestamp": "live",
            "include_basket": False,
        }
    )

    assert seen["symbols"] == ["/ZNM26", "/UBM26"]
    assert out["TYM26"]["symbol"] == "TYM26"
    assert out["WNM26"]["symbol"] == "WNM26"
    assert out["TYM26"]["price"] == pytest.approx(112.50)
    assert out["WNM26"]["price"] == pytest.approx(124.14)

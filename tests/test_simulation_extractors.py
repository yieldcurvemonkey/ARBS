import datetime
from types import SimpleNamespace

import pytest

from Query.Base.bachelier import bachelier_price
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import (
    QLSTIRFutureOptionPricable,
    QLSTIRFutureOptionPricer,
)
from Simulation.extractors import BachelierExtractor, get_extractor, register_extractor


def _make_pricer(
    *,
    forward: float = 95.75,
    strike: float = 95.75,
    iv_normal: float = 0.0050,
    right: str = "C",
    tte_days: int = 90,
) -> QLSTIRFutureOptionPricer:
    ts = datetime.datetime(2026, 3, 16, 17, 0)
    expiry = (ts + datetime.timedelta(days=tte_days)).date()
    discount = 0.998
    tte = tte_days / 365.0
    price = bachelier_price(right, strike, forward, iv_normal, tte, discount)
    return QLSTIRFutureOptionPricer(
        symbol=f"SFR{right}{int(strike * 100)}",
        right=right,
        underlying_symbol="SFRM6",
        strike=strike,
        quote_timestamp=ts,
        expiry_date=expiry,
        market_price=price,
        model_price=price,
        iv_normal=iv_normal,
        delta=0.5,
        gamma=100.0,
        vega=0.01,
        theta=-0.001,
        forward=forward,
        discount=discount,
    )


def _make_leg(pricer: QLSTIRFutureOptionPricer) -> QLSTIRFutureOptionPricable:
    return pricer.build_pricable(quantity=1.0)


class TestBachelierExtractor:
    def test_extract_produces_valid_market_state(self):
        pricer = _make_pricer()
        leg = _make_leg(pricer)
        extractor = BachelierExtractor()

        state = extractor.extract(pricer, leg)

        assert state.forward == pytest.approx(95.75)
        assert state.vol_normal == pytest.approx(0.0050)
        assert state.discount == pytest.approx(0.998)
        assert state.tte == pytest.approx(90.0 / 365.0)
        assert state.eval_date == datetime.date(2026, 3, 16)

    def test_reprice_matches_bachelier_price(self):
        pricer = _make_pricer(forward=95.75, strike=95.75, iv_normal=0.005)
        leg = _make_leg(pricer)
        extractor = BachelierExtractor()
        state = extractor.extract(pricer, leg)

        repriced = extractor.reprice(state, leg)
        expected = bachelier_price("C", 95.75, 95.75, 0.005, 90.0 / 365.0, 0.998)
        assert repriced == pytest.approx(expected, rel=1e-10)

    def test_reprice_with_shifted_state(self):
        from dataclasses import replace

        pricer = _make_pricer(forward=95.75, strike=95.75, iv_normal=0.005)
        leg = _make_leg(pricer)
        extractor = BachelierExtractor()
        state = extractor.extract(pricer, leg)

        shifted = replace(state, forward=96.75)
        repriced = extractor.reprice(shifted, leg)
        expected = bachelier_price("C", 95.75, 96.75, 0.005, 90.0 / 365.0, 0.998)
        assert repriced == pytest.approx(expected, rel=1e-10)

    def test_reprice_put(self):
        pricer = _make_pricer(right="P", strike=96.0)
        leg = _make_leg(pricer)
        extractor = BachelierExtractor()
        state = extractor.extract(pricer, leg)

        repriced = extractor.reprice(state, leg)
        expected = bachelier_price("P", 96.0, 95.75, 0.005, 90.0 / 365.0, 0.998)
        assert repriced == pytest.approx(expected, rel=1e-10)

    def test_reprice_uses_intrinsic_at_expiry(self):
        from dataclasses import replace

        pricer = _make_pricer(forward=95.75, strike=95.75, iv_normal=0.005)
        leg = _make_leg(pricer)
        extractor = BachelierExtractor()
        state = extractor.extract(pricer, leg)

        atm_expiry = replace(state, tte=0.0)
        itm_expiry = replace(state, forward=96.25, tte=0.0)

        assert extractor.reprice(atm_expiry, leg) == pytest.approx(0.0, abs=1e-12)
        assert extractor.reprice(itm_expiry, leg) == pytest.approx((96.25 - 95.75) * 0.998, abs=1e-12)


class TestSwaptionExpiryPayoff:
    def test_swaption_reprice_uses_intrinsic_at_expiry(self):
        from Simulation.extractors import SwaptionExtractor

        extractor = SwaptionExtractor()
        payer_leg = SimpleNamespace(option_type="payer", strike=0.04)
        receiver_leg = SimpleNamespace(option_type="receiver", strike=0.04)

        atm_state = SimpleNamespace(forward=0.04, vol_normal=0.01, discount=10_000_000.0, tte=0.0)
        itm_payer_state = SimpleNamespace(forward=0.045, vol_normal=0.01, discount=10_000_000.0, tte=0.0)
        itm_receiver_state = SimpleNamespace(forward=0.035, vol_normal=0.01, discount=10_000_000.0, tte=0.0)

        assert extractor.reprice(atm_state, payer_leg) == pytest.approx(0.0, abs=1e-12)
        assert extractor.reprice(atm_state, receiver_leg) == pytest.approx(0.0, abs=1e-12)
        assert extractor.reprice(itm_payer_state, payer_leg) == pytest.approx(50_000.0, abs=1e-8)
        assert extractor.reprice(itm_receiver_state, receiver_leg) == pytest.approx(50_000.0, abs=1e-8)


class TestExtractorRegistry:
    def test_register_and_get(self):
        register_extractor("STIRFUTUREOPTION", BachelierExtractor)
        extractor = get_extractor("STIRFUTUREOPTION")
        assert isinstance(extractor, BachelierExtractor)

    def test_get_unknown_product_raises(self):
        with pytest.raises(KeyError):
            get_extractor("NONEXISTENT_PRODUCT_XYZ_12345")

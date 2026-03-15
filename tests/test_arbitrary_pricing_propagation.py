import datetime as dt
from dataclasses import dataclass

import pytest

from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.FXForwards.FXForwardQuery import FXForwardQuery
from Query.FXForwards.FXForwardValue import FXForwardValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.Spreads.SpreadQuery import SpreadQuery
from Query.Spreads.SpreadStructure import SpreadStructure
from Query.Spreads.SpreadValue import SpreadValue
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
from Query.STIRFutures.STIRFutureValue import STIRFutureValue
from Query.STIRFutures._STIRFutureGenericPricer import _STIRFutureGenericPricer
from Query.USTFutures.USTFutureQuery import USTFutureQuery
from Query.USTFutures.USTFutureStructure import USTFutureStructure
from Query.USTFutures.USTFutureValue import USTFutureValue
from Query.USTFutures._USTFutureGenericPricable import _USTFutureGenericPricable
from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer
from Query.FXForwards.backends.rateslib.RLFXForwardPricer import RLFXForwardPricer


@dataclass
class _SwapInstrument:
    tenor: str
    notional: float
    fixed_rate: float

    @property
    def tenor_years(self) -> float:
        token = self.tenor.upper()
        if token.endswith("Y"):
            return float(token[:-1])
        if token.endswith("M"):
            return float(token[:-1]) / 12.0
        return 1.0


class _IRCurveStub:
    def id(self):
        return "USD-SOFR-1D"

    def reference_date(self):
        return dt.date(2026, 3, 15)

    def calendar_advance(self, ref_date, tenor):
        _ = tenor
        return ref_date

    def build_irswap(self, fwd=None, tenor=None, effective_date=None, maturity_date=None, fixed_rate=-0.0, notional=None, bpv=None):
        _ = fwd, effective_date, maturity_date
        resolved_notional = float(notional if notional is not None else (bpv or 1_000_000.0))
        resolved_rate = 0.05 if fixed_rate in (-0.0, None) else float(fixed_rate)
        return _SwapInstrument(tenor=tenor or "5Y", notional=resolved_notional, fixed_rate=resolved_rate)

    def fair_rate(self, instrument):
        return 0.05

    def npv(self, instrument):
        return (float(instrument.fixed_rate) - 0.05) * float(instrument.notional)

    def pv01(self, instrument):
        return abs(float(instrument.notional)) * instrument.tenor_years * 0.0001

    def dv01(self, instrument):
        return self.pv01(instrument)

    def gamma(self, instrument):
        _ = instrument
        return 0.0

    def notional(self, instrument):
        return instrument.notional


class _SpreadPricerStub(_IRCurveStub):
    def __init__(self, base_rate: float):
        self.base_rate = float(base_rate)
        self.last_built = []

    def build_irswap(self, **kwargs):
        built = super().build_irswap(**kwargs)
        self.last_built.append(built)
        return built

    def fair_rate(self, instrument):
        return float(instrument.fixed_rate)

    def npv(self, instrument):
        return (float(instrument.fixed_rate) - self.base_rate) * float(instrument.notional)


class _BondInstrument:
    def __init__(self, issue_date, maturity_date, coupon, notional):
        self.issue_date = issue_date
        self.maturity_date = maturity_date
        self.coupon = float(coupon)
        self.notional = float(notional)


class _BondPricerStub:
    def __init__(
        self,
        rl_frb_id,
        reference_date,
        issue_date,
        maturity_date,
        cpn,
        notional=None,
        clean_price=None,
        ytm=None,
        meta_data=None,
    ):
        self._rl_frb_id = rl_frb_id
        self._reference_date = reference_date
        self._issue_date = issue_date
        self._maturity_date = maturity_date
        self._cpn = float(cpn)
        self._notional = float(notional or 1_000_000.0)
        self._clean_price = clean_price
        self._ytm = ytm
        self._meta_data = meta_data or {}

    def id(self):
        return self._rl_frb_id

    def reference_date(self):
        return self._reference_date

    def issue_date(self):
        return self._issue_date

    def maturity_date(self):
        return self._maturity_date

    def coupon(self):
        return self._cpn

    def meta(self):
        return self._meta_data

    def clean_price(self):
        if self._clean_price is not None:
            return float(self._clean_price)
        return 100.0 + (self._cpn - 4.0)

    def ytm(self):
        if self._ytm is not None:
            return float(self._ytm)
        return (self._cpn / 100.0) - (self.clean_price() - 100.0) / 1000.0

    def dirty_price(self, notional=None):
        _ = notional
        return self.clean_price() + 0.25

    def npv(self, notional=None):
        effective_notional = float(notional or self._notional)
        return effective_notional * (self.clean_price() / 100.0) * (1.0 + self._cpn / 10_000.0)

    def pv01(self, notional=None):
        effective_notional = float(notional or self._notional)
        return effective_notional * 0.0001 * (1.0 + self._cpn / 100.0)

    def mod_duration(self):
        return 4.0 + self._cpn / 100.0

    def convexity(self):
        return 1.0 + self._cpn / 100.0

    def notional(self, instrument):
        return float(instrument.notional)

    def build_pricable(self, **kwargs):
        issue_date = kwargs.get("issue_date", self._issue_date)
        maturity_date = kwargs.get("maturity_date", self._maturity_date)
        coupon = kwargs.get("coupon") or kwargs.get("cpn", self._cpn)
        bpv = kwargs.get("bpv")
        notional = kwargs.get("notional")
        if notional is None and bpv is not None:
            notional = float(bpv) / self.pv01(notional=1.0)
        return _BondInstrument(issue_date, maturity_date, coupon, notional or self._notional)


class _MockSTIRFuture:
    def __init__(self, symbol, price, contracts=1):
        self._symbol = symbol
        self._price = float(price)
        self._contracts = int(contracts)

    def price(self):
        return self._price

    def fixed_rate(self):
        return 100.0 - self._price

    def npv(self):
        return self._price * self._contracts

    def effective_date(self):
        return dt.date(2026, 3, 15)

    def maturity_date(self):
        return dt.date(2026, 6, 15)


class _MockSTIRFuturePricer(_STIRFutureGenericPricer):
    def __init__(self, symbol, snapshot_price):
        self._symbol = symbol
        self._snapshot_price = float(snapshot_price)

    def id(self):
        return self._symbol

    def build_pricable(self, **kwargs):
        price = kwargs.get("price")
        rate = kwargs.get("rate")
        if price is None and rate is not None:
            price = 100.0 - float(rate)
        return _MockSTIRFuture(self._symbol, price if price is not None else self._snapshot_price, contracts=int(kwargs.get("contracts", 1)))

    def price(self):
        return self._snapshot_price

    def fair_rate(self, future):
        return future.fixed_rate() / 100.0

    def pv01(self, stirf=None):
        contracts = getattr(stirf, "_contracts", 1) if stirf is not None else 1
        return float(contracts)


class _MockUSTFuture(_USTFutureGenericPricable):
    def __init__(self, contract_code: str, price: float, contracts: int = 1, notional: float = 100_000.0):
        self._contract_code = contract_code
        self._price = float(price)
        self._contracts = int(contracts)
        self._notional = float(notional)

    def contract_code(self) -> str:
        return self._contract_code

    def effective_date(self) -> dt.date:
        return dt.date(2026, 3, 15)

    def maturity_date(self) -> dt.date:
        return dt.date(2026, 6, 15)

    def price(self) -> float:
        return self._price

    def contracts(self) -> int:
        return self._contracts

    def notional(self) -> float:
        return self._notional


class _MockUSTFuturePricer(_USTFutureGenericPricer):
    def __init__(self, symbol: str, price: float):
        self._symbol = symbol
        self._price = float(price)

    def id(self) -> str:
        return self._symbol

    def reference_date(self) -> dt.date:
        return dt.date(2026, 3, 15)

    def meta(self):
        return {}

    def effective_date(self, ustf: _MockUSTFuture) -> dt.date:
        return ustf.effective_date()

    def maturity_date(self, ustf: _MockUSTFuture) -> dt.date:
        return ustf.maturity_date()

    def price(self, ustf: _MockUSTFuture) -> float:
        return ustf.price()

    def yield_to_maturity(self, ustf: _MockUSTFuture) -> float:
        return 0.04

    def pv01(self, ustf: _MockUSTFuture) -> float:
        return float(ustf.contracts())

    def dv01(self, ustf: _MockUSTFuture) -> float:
        return float(ustf.contracts())

    def npv(self, instrument: _MockUSTFuture, /, **kwargs):
        _ = kwargs
        return self.price(instrument) * self.pv01(instrument)

    def resolve_pricable(self, priceable: _MockUSTFuture, risk_weight=None) -> _MockUSTFuture:
        _ = risk_weight
        return priceable

    def build_pricable(self, /, **kwargs):
        return self.build_ustf(
            contract_code=kwargs.get("contract_code", self._symbol),
            price=kwargs.get("price", self._price),
            contracts=kwargs.get("contracts", 1),
            notional=kwargs.get("notional", 100_000.0),
        )

    def build_ustf(self, contract_code=None, effective_date=None, maturity_date=None, price=None, contracts=None, notional=None, **kwargs):
        _ = effective_date, maturity_date, kwargs
        return _MockUSTFuture(contract_code or self._symbol, price if price is not None else self._price, contracts=contracts or 1, notional=notional or 100_000.0)


def test_explicit_multi_leg_structures_are_preserved():
    frb_query = FixedRateBondQuery(
        structure=FixedRateBondStructure.CURVE,
        structure_kwargs={"front_cusip": "AAA", "back_cusip": "BBB"},
    )
    stir_query = STIRFutureQuery(
        structure=STIRFutureStructure.CURVE,
        structure_kwargs={"front_symbol": "SFRH26", "back_symbol": "SFRM26"},
    )

    assert frb_query.structure_id == FixedRateBondStructure.CURVE
    assert stir_query.structure_id == STIRFutureStructure.CURVE


def test_ir_swap_coupon_alias_produces_non_par_npv():
    curve = _IRCurveStub()
    query = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        value=IRSwapValue.NPV,
        tenor="5Y",
        curve="USD-SOFR-1D",
        structure_kwargs={"notional": 1_000_000, "coupon": 0.061},
    )

    package, weights = query.resolve_package(pricer_or_curve=curve)
    value_map = query.build_value_map(pricer_or_curve=curve, package=package, risk_weights=weights)

    assert package[0].fixed_rate == pytest.approx(0.061)
    assert value_map.apply(IRSwapValue.NPV) == pytest.approx(11_000.0)


def test_spread_fixed_rate_overrides_propagate_to_both_legs():
    class _SpreadContext:
        def __init__(self):
            self.pricer_a = _SpreadPricerStub(0.04)
            self.pricer_b = _SpreadPricerStub(0.04)

    ctx = _SpreadContext()
    query = SpreadQuery(
        structure=SpreadStructure.CURVE,
        value=SpreadValue.LEG_A_RATE,
        curve_a="A",
        curve_b="B",
        structure_kwargs={
            "front_tenor": "2Y",
            "back_tenor": "5Y",
            "front_coupon": 0.041,
            "back_coupon": 0.052,
            "bpv": 10_000,
        },
    )

    package, weights = query.resolve_package(pricer_or_curve=ctx)
    value_map = query.build_value_map(pricer_or_curve=ctx, package=package, risk_weights=weights)

    assert package[0].inst_a.fixed_rate == pytest.approx(0.041)
    assert package[1].inst_a.fixed_rate == pytest.approx(0.052)
    assert value_map.apply(SpreadValue.LEG_A_RATE) == pytest.approx(0.011)


def test_fixed_rate_bond_coupon_override_changes_priced_outputs():
    pricers = {
        "AAA": _BondPricerStub(
            rl_frb_id="USTS",
            reference_date=dt.date(2026, 3, 15),
            issue_date=dt.date(2020, 1, 1),
            maturity_date=dt.date(2030, 1, 1),
            cpn=4.0,
            clean_price=100.0,
        )
    }
    query = FixedRateBondQuery(
        structure=FixedRateBondStructure.OUTRIGHT,
        value=FixedRateBondValue.YTM,
        cusip="AAA",
        structure_kwargs={"notional": 1_000_000, "coupon": 6.0},
    )

    package, weights = query.resolve_package(pricer_or_curve=pricers)
    value_map = query.build_value_map(pricer_or_curve=pricers, package=package, risk_weights=weights)

    assert package[0].cpn == pytest.approx(6.0)
    assert value_map.apply(FixedRateBondValue.YTM) != pytest.approx(pricers["AAA"].ytm())
    assert value_map.apply(FixedRateBondValue.NPV) != pytest.approx(pricers["AAA"].npv(notional=1_000_000))


def test_stir_future_price_override_moves_price_and_npv():
    pricers = {"SFRH26": [_MockSTIRFuturePricer("SFRH26", 99.75)]}
    query = STIRFutureQuery(
        structure=STIRFutureStructure.OUTRIGHT,
        value=STIRFutureValue.PRICE,
        symbol="SFRH26",
        structure_kwargs={"price": 99.25, "contracts": 2},
    )

    package, weights = query.resolve_package(pricer_or_curve=pricers)
    value_map = query.build_value_map(pricer_or_curve=pricers, package=package, risk_weights=weights)

    assert value_map.apply(STIRFutureValue.PRICE) == pytest.approx(99.25)
    assert value_map.apply(STIRFutureValue.NPV) == pytest.approx(198.5)


def test_ust_future_curve_leg_price_overrides_are_used():
    pricers = {
        "TYM26": [_MockUSTFuturePricer("TYM26", 110.0)],
        "USM26": [_MockUSTFuturePricer("USM26", 108.0)],
    }
    query = USTFutureQuery(
        structure=USTFutureStructure.CURVE,
        value=USTFutureValue.PRICE,
        structure_kwargs={
            "front_symbol": "TYM26",
            "back_symbol": "USM26",
            "front_price": 111.0,
            "back_price": 109.5,
        },
    )

    package, weights = query.resolve_package(pricer_or_curve=pricers)
    value_map = query.build_value_map(pricer_or_curve=pricers, package=package, risk_weights=weights)

    assert value_map.apply(USTFutureValue.PRICE) == pytest.approx(1.5)


def test_fx_forward_query_supports_off_market_forward_and_points_overrides():
    pricer = RLFXForwardPricer(
        pair="USDCAD",
        symbol="USDCAD.B",
        tenor="1W",
        settlement_date=dt.date(2026, 3, 6),
        quote_timestamp=dt.datetime(2026, 2, 27, 17, 0),
        spot=1.35,
        points_raw=25.0,
        points_decimal=0.0025,
        forward_rate=1.3525,
        basis_bps=-5.0,
        fx_rates=None,
        fx_forwards=None,
        meta_data={},
    )
    pricers = {"USDCAD:1W": [pricer]}
    query = FXForwardQuery(
        pair="USDCAD",
        tenor="1W",
        structure_kwargs={"spot": 1.35, "forward_rate": 1.36},
    )

    package, weights = query.resolve_package(pricer_or_curve=pricers)
    value_map = query.build_value_map(pricer_or_curve=pricers, package=package, risk_weights=weights)

    assert value_map.apply(FXForwardValue.FORWARD_RATE) == pytest.approx(1.36)
    assert value_map.apply(FXForwardValue.POINTS_RAW) == pytest.approx(100.0)

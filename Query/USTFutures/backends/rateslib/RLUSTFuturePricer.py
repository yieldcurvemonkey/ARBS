import datetime
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple, Union

import rateslib as rl

from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer
from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer
from Query.USTFutures.backends.rateslib.RLUSTFuturePricable import RLUSTFuturePricable

DateLike = Union[datetime.date, datetime.datetime]
DeliveryLike = Union[DateLike, Tuple[DateLike, DateLike]]
BasketLike = Iterable[Union[RLFixedRateBondPricer, dict]]


@dataclass
class RLUSTFuturePricer(_USTFutureGenericPricer):
    _symbol: str
    _reference_date: datetime.date
    _price: float
    _contracts: int
    _notional: float
    _delivery_dates: Tuple[datetime.date, datetime.date]
    _basket_pricers: List[RLFixedRateBondPricer]
    _conversion_factors: List[float]
    _contract_coupon: float
    _currency: str
    _curve_id: str
    _calc_mode: Optional[str]
    _meta_data: Any

    def __init__(
        self,
        symbol: str,
        reference_date: DateLike,
        price: float,
        delivery: Optional[DeliveryLike] = None,
        basket: Optional[BasketLike] = None,
        conversion_factors: Optional[Sequence[float]] = None,
        coupon: float = 6.0,
        contracts: Optional[int] = None,
        notional: Optional[float] = None,
        currency: str = "USD",
        curve_id: str = "USD-SOFR-1D",
        calc_mode: Optional[str] = None,
        meta_data: Optional[Any] = None,
    ):
        self._symbol = symbol
        self._reference_date = reference_date.date() if isinstance(reference_date, datetime.datetime) else reference_date
        self._price = float(price)
        self._contracts = int(contracts or 1)
        self._notional = float(notional or 100_000.0)
        self._delivery_dates = self._normalize_delivery_dates(delivery or self._reference_date)
        self._basket_pricers = self._coerce_basket(basket or [])
        self._conversion_factors = [float(x) for x in conversion_factors] if conversion_factors is not None else []
        self._contract_coupon = float(coupon)
        self._currency = currency
        self._curve_id = curve_id
        self._calc_mode = calc_mode
        self._meta_data = meta_data or {}

        if self._conversion_factors and len(self._conversion_factors) != len(self._basket_pricers):
            raise ValueError("conversion_factors length must match basket length")

    def _normalize_delivery_dates(self, delivery: DeliveryLike) -> Tuple[datetime.date, datetime.date]:
        if isinstance(delivery, tuple):
            start, end = delivery
        else:
            start = delivery
            end = delivery
        start_date = start.date() if isinstance(start, datetime.datetime) else start
        end_date = end.date() if isinstance(end, datetime.datetime) else end
        return start_date, end_date

    def _coerce_basket(self, basket: BasketLike) -> List[RLFixedRateBondPricer]:
        pricers: List[RLFixedRateBondPricer] = []
        for item in basket:
            if isinstance(item, RLFixedRateBondPricer):
                pricers.append(item)
                continue
            if isinstance(item, dict):
                pricers.append(self._build_pricer_from_dict(item))
                continue
            raise TypeError(f"Unsupported basket item type: {type(item)}")
        return pricers

    def _build_pricer_from_dict(self, spec: dict) -> RLFixedRateBondPricer:
        pricer = spec.get("pricer")
        if isinstance(pricer, RLFixedRateBondPricer):
            return pricer
        try:
            return RLFixedRateBondPricer(
                rl_frb_id=spec.get("rl_frb_id", "USTS"),
                reference_date=spec.get("reference_date", self._reference_date),
                issue_date=spec["issue_date"],
                maturity_date=spec["maturity_date"],
                cpn=spec.get("cpn") or spec.get("coupon"),
                clean_price=spec.get("clean_price"),
                ytm=spec.get("ytm"),
                meta_data=spec.get("meta_data"),
            )
        except KeyError as exc:
            raise ValueError("Bond basket dict missing required fields") from exc

    def _to_rl_dt(self, pydate: datetime.date) -> rl.dt:
        return rl.dt(pydate.year, pydate.month, pydate.day)

    def _build_rl_basket(self) -> List[rl.FixedRateBond]:
        if not self._basket_pricers:
            raise ValueError("No deliverable basket configured for this future")
        return [pricer.build_pricable() for pricer in self._basket_pricers]

    def build_rateslib_object(self, curves: Optional[Any] = None) -> rl.BondFuture:
        delivery_start, delivery_end = self._delivery_dates
        delivery = (self._to_rl_dt(delivery_start), self._to_rl_dt(delivery_end))
        rl_basket = self._build_rl_basket()
        return rl.BondFuture(
            delivery=delivery,
            coupon=self._contract_coupon,
            basket=rl_basket,
            nominal=self._notional,
            contracts=self._contracts,
            currency=self._currency,
            calc_mode=self._calc_mode,
        )

    def _resolve_curves(self, curves: Optional[Any]) -> Any:
        return curves or self._curve_id

    def id(self) -> str:
        return self._symbol

    def reference_date(self) -> datetime.date:
        return self._reference_date

    def meta(self) -> Any:
        return self._meta_data

    def effective_date(self, ustf: RLUSTFuturePricable) -> datetime.date:
        return ustf.effective_date()

    def maturity_date(self, ustf: RLUSTFuturePricable) -> datetime.date:
        return ustf.maturity_date()

    def price(self, ustf: RLUSTFuturePricable, curves: Optional[Any] = None) -> float:
        if not self._basket_pricers:
            return float(self._price)
        bf = self.build_rateslib_object(curves=self._resolve_curves(curves))
        return float(bf.rate(curves=self._resolve_curves(curves), metric="future_price"))

    def yield_to_maturity(self, ustf: RLUSTFuturePricable, curves: Optional[Any] = None) -> float:
        if not self._basket_pricers:
            if isinstance(self._meta_data, dict):
                val = self._meta_data.get("yield")
                if val is not None:
                    return float(val)
            return 0.0
        bf = self.build_rateslib_object(curves=self._resolve_curves(curves))
        return float(bf.rate(curves=self._resolve_curves(curves), metric="ytm"))

    def analytic_delta(self, curves: Optional[Any] = None, shift: float = 1e-4) -> float:
        if not self._basket_pricers:
            raise ValueError("Cannot compute analytic_delta without a deliverable basket")
        bf = self.build_rateslib_object(curves=self._resolve_curves(curves))
        curves_obj = self._resolve_curves(curves)
        if hasattr(bf, "analytic_delta"):
            return float(bf.analytic_delta(curves=curves_obj))
        if self._conversion_factors:
            deltas = []
            for pricer in self._basket_pricers:
                bond = pricer.build_pricable()
                try:
                    deltas.append(float(bond.analytic_delta(curve=curves_obj)))
                except TypeError:
                    deltas.append(float(bond.analytic_delta(curves=curves_obj)))
            return float(sum(cf * delta for cf, delta in zip(self._conversion_factors, deltas)))
        if not hasattr(curves_obj, "shift"):
            raise ValueError("Curves object does not support shifting for analytic delta calculation")
        base = bf.npv(curves=curves_obj)
        bumped = bf.npv(curves=curves_obj.shift(shift))
        return float((bumped - base) / shift)

    def pv01(self, ustf: RLUSTFuturePricable, curves: Optional[Any] = None) -> float:
        return self.analytic_delta(curves=curves)

    def dv01(self, ustf: RLUSTFuturePricable, curves: Optional[Any] = None) -> float:
        return self.pv01(ustf, curves=curves)

    def npv(self, instrument: RLUSTFuturePricable, /, **kwargs: Any) -> float:
        if not self._basket_pricers:
            raise ValueError("Cannot compute NPV without a deliverable basket")
        curves = self._resolve_curves(kwargs.get("curves"))
        bf = self.build_rateslib_object(curves=curves)
        return float(bf.npv(curves=curves, **{k: v for k, v in kwargs.items() if k != "curves"}))

    def ctd_index(self, ordered: bool = False) -> int | List[int]:
        if not self._basket_pricers:
            raise ValueError("Cannot compute CTD without a deliverable basket")
        bf = self.build_rateslib_object(curves=self._curve_id)
        prices = self._basket_prices()
        settlement = self._basket_settlement()
        return bf.ctd_index(
            future_price=self._price,
            prices=prices,
            settlement=settlement,
            ordered=ordered,
        )

    def ctd(self) -> Optional[RLFixedRateBondPricer]:
        if not self._basket_pricers:
            return None
        idx = self.ctd_index(ordered=False)
        return self._basket_pricers[int(idx)]

    def implied_repo(self) -> Tuple[float, ...]:
        if not self._basket_pricers:
            raise ValueError("Cannot compute implied repo without a deliverable basket")
        bf = self.build_rateslib_object(curves=self._curve_id)
        prices = self._basket_prices()
        settlement = self._basket_settlement()
        return tuple(
            float(x)
            for x in bf.implied_repo(
                future_price=self._price,
                prices=prices,
                settlement=settlement,
            )
        )

    def _basket_prices(self) -> List[float]:
        return [float(pricer.clean_price()) for pricer in self._basket_pricers]

    def _basket_settlement(self) -> datetime.date:
        return self._basket_pricers[0].settlement_date()

    def conversion_factors(self) -> List[float]:
        return list(self._conversion_factors)

    def resolve_pricable(self, priceable: RLUSTFuturePricable, risk_weight: Optional[float] = None) -> RLUSTFuturePricable:
        if risk_weight is None or risk_weight >= 0:
            return priceable
        return RLUSTFuturePricable(
            _contract_code=priceable.contract_code(),
            _effective_date=priceable.effective_date(),
            _maturity_date=priceable.maturity_date(),
            _price=priceable.price(),
            _contracts=-abs(priceable.contracts()),
            _notional=priceable.notional(),
        )

    def build_pricable(self, /, **kwargs: Any) -> RLUSTFuturePricable:
        return self.build_ustf(
            contract_code=kwargs.get("contract_code"),
            effective_date=kwargs.get("effective_date"),
            maturity_date=kwargs.get("maturity_date"),
            price=kwargs.get("price"),
            contracts=kwargs.get("contracts"),
            notional=kwargs.get("notional"),
        )

    def build_ustf(
        self,
        contract_code: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        price: Optional[float] = None,
        contracts: Optional[int] = None,
        notional: Optional[float] = None,
        **kwargs: Any,
    ) -> RLUSTFuturePricable:
        eff = effective_date or self.reference_date()
        mat = maturity_date or self.reference_date()
        return RLUSTFuturePricable(
            _contract_code=contract_code or self._symbol,
            _effective_date=eff,
            _maturity_date=mat,
            _price=float(price if price is not None else self._price),
            _contracts=int(contracts or self._contracts),
            _notional=float(notional or self._notional),
        )

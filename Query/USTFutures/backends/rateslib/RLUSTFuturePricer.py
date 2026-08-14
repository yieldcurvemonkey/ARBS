import datetime
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple, Union, Literal

import string
import rateslib as rl
import pandas as pd

from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings
from MDP.USTFutures.treasury_conversion_factors import resolve_delivery_contract
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

    def delivery_dates(self) -> Tuple[datetime.date, datetime.date]:
        """Public accessor for the (start, end) delivery window of this contract.

        Callers like the CME invoice-swap lookup need the delivery window and the
        CTD basket. Previously the lookup fetched the delivery basket separately
        via ``get_delivery_basket`` AND constructed a pricer via ``get_pricer``
        (which itself calls ``get_delivery_basket`` again with basket hydration).
        This accessor lets a single ``get_pricer(include_basket=True)`` cover
        both needs, halving the FixedRateBondsMDP round-trips per contract.
        """
        return self._delivery_dates

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

    def build_rateslib_object(self, curves: Optional[Any] = None, early_or_late_delivery: Optional[Literal["early", "late"]] = None) -> rl.BondFuture:
        delivery_start, delivery_end = self._delivery_dates
        delivery = (
            self._to_rl_dt(delivery_start)
            if early_or_late_delivery == "early"
            else self._to_rl_dt(delivery_end) if early_or_late_delivery == "late" else (self._to_rl_dt(delivery_start), self._to_rl_dt(delivery_end))
        )
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
        if ustf is not None:
            return ustf.price()
        if self._price:
            return float(self._price)
        bf = self.build_rateslib_object(curves=self._resolve_curves(curves))
        return float(bf.rate(curves=self._resolve_curves(curves), metric="future_price"))

    def yield_to_maturity_from_price(self, future_price: float, curves: Optional[Any] = None) -> float:
        if not self._basket_pricers:
            if isinstance(self._meta_data, dict):
                val = self._meta_data.get("yield")
                if val is not None:
                    return float(val)
            return 0.0
        bf = self.build_rateslib_object(curves=self._resolve_curves(curves))
        idx = bf.ctd_index(
            future_price=float(future_price),
            prices=self._basket_prices(),
            settlement=self._basket_settlement(),
        )
        return float(bf.ytm(future_price=float(future_price))[int(idx)])

    def yield_to_maturity(self, ustf: RLUSTFuturePricable, curves: Optional[Any] = None) -> float:
        future_price = self.price(ustf, curves=curves)
        return self.yield_to_maturity_from_price(future_price=future_price, curves=curves)

    # def analytic_delta(self, curves: Optional[Any] = None, shift: float = 1e-4) -> float:
    #     if not self._basket_pricers:
    #         raise ValueError("Cannot compute analytic_delta without a deliverable basket")
    #     bf = self.build_rateslib_object(curves=self._resolve_curves(curves))
    #     curves_obj = self._resolve_curves(curves)

    #     print(bf)

    #     print(bf.duration(self.price(None)) * 100)
    #     if hasattr(bf, "analytic_delta"):
    #         return float(bf.analytic_delta())
    #     if self._conversion_factors:
    #         deltas = []
    #         for pricer in self._basket_pricers:
    #             bond = pricer.build_pricable()
    #             try:
    #                 deltas.append(float(bond.analytic_delta(curve=curves_obj)))
    #             except TypeError:
    #                 deltas.append(float(bond.analytic_delta(curves=curves_obj)))
    #         return float(sum(cf * delta for cf, delta in zip(self._conversion_factors, deltas)))
    #     if not hasattr(curves_obj, "shift"):
    #         raise ValueError("Curves object does not support shifting for analytic delta calculation")
    #     base = bf.npv(curves=curves_obj)
    #     bumped = bf.npv(curves=curves_obj.shift(shift))
    #     return float((bumped - base) / shift)

    def pv01(self, ustf: RLUSTFuturePricable, curves: Optional[Any] = None) -> float:
        if not self._basket_pricers:
            raise ValueError("Cannot compute pv01 without a deliverable basket")
        bf = self.build_rateslib_object(curves=self._resolve_curves(curves))
        risk = bf.duration(future_price=ustf.price(), metric="risk")
        idx = bf.ctd_index(
            future_price=ustf.price(),
            prices=self._basket_prices(),
            settlement=self._basket_settlement(),
        )
        ctd_risk = float(risk[int(idx)])
        return ctd_risk * (ustf.notional() / 10_000.0) * ustf.contracts()

    def dv01(self, ustf: RLUSTFuturePricable, curves: Optional[Any] = None) -> float:
        return self.pv01(ustf, curves=curves)

    def npv(self, instrument: RLUSTFuturePricable, /, **kwargs: Any) -> float:
        if not self._basket_pricers:
            raise ValueError("Cannot compute NPV without a deliverable basket")
        curves = self._resolve_curves(kwargs.get("curves"))
        bf = self.build_rateslib_object(curves=curves)
        return float(bf.npv(curves=curves, **{k: v for k, v in kwargs.items() if k != "curves"}))

    def ctd_index(self, ordered: bool = False, early_or_late_delivery: Optional[Literal["early", "late"]] = None) -> int | List[int]:
        if not self._basket_pricers:
            raise ValueError("Cannot compute CTD without a deliverable basket")
        bf = self.build_rateslib_object(curves=self._curve_id, early_or_late_delivery=early_or_late_delivery)
        prices = self._basket_prices()
        settlement = self._basket_settlement()
        return bf.ctd_index(
            future_price=self._price,
            prices=prices,
            settlement=settlement,
            ordered=ordered,
        )

    def ctd(self, contract_delivery_indicator: Optional[Literal["A", "B", "C", "D", "E", "F"]] = None) -> Optional[RLFixedRateBondPricer]:
        if not self._basket_pricers:
            return None
        if contract_delivery_indicator is not None:
            if contract_delivery_indicator.upper() in ["A", "B", "C"]:
                early_or_late_delivery = "late"
            else:
                early_or_late_delivery = "early"

            idxs = self.ctd_index(ordered=True, early_or_late_delivery=early_or_late_delivery)
            offset = 3 if contract_delivery_indicator in ["D", "E", "F"] else 0
            return self._basket_pricers[idxs[string.ascii_uppercase.index(contract_delivery_indicator) - offset]]
        else:
            idx = self.ctd_index(ordered=False)
            return self._basket_pricers[int(idx)]

    def _basket_prices(self) -> List[float]:
        return [float(pricer.clean_price()) for pricer in self._basket_pricers]

    def _basket_settlement(self) -> datetime.date:
        return self._basket_pricers[0].settlement_date()

    def _resolve_future_price(self, future_price: Optional[float] = None) -> float:
        return float(self._price if future_price is None else future_price)

    def _resolve_prices(self, prices: Optional[Sequence[float]] = None) -> List[float]:
        if prices is None:
            return self._basket_prices()
        return [float(x) for x in prices]

    def _coerce_datetime(self, value: Optional[DateLike]) -> Optional[datetime.datetime]:
        if value is None:
            return None
        if pd.isna(value):
            return None
        if isinstance(value, datetime.datetime):
            return value
        return datetime.datetime(value.year, value.month, value.day)

    def _resolve_settlement(self, settlement: Optional[DateLike] = None) -> datetime.datetime:
        if not self._basket_pricers:
            raise ValueError("Cannot compute settlement-dependent basis metrics without a deliverable basket")
        return self._coerce_datetime(settlement) or self._coerce_datetime(self._basket_settlement())

    def _resolve_delivery(self, delivery: Optional[DateLike] = None) -> datetime.datetime:
        delivery_date = self._coerce_datetime(delivery)
        if delivery_date is not None:
            return delivery_date
        _, contract_imm_date, _ = resolve_delivery_contract(self._symbol, self._reference_date)
        return datetime.datetime(contract_imm_date.year, contract_imm_date.month, contract_imm_date.day)

    def _resolve_repo_rate(
        self,
        repo_rate: Optional[float | Sequence[float]] = None,
        curve_name: Optional[str] = None,
    ) -> float | Sequence[float]:
        if repo_rate is not None:
            return repo_rate
        fixing_curve = curve_name or (self._curve_id if isinstance(self._curve_id, str) else "USD-SOFR-1D")
        fixings = _fetch_fixings(as_of_date=self._reference_date, curve_name=fixing_curve).sort_index()
        if fixings.empty:
            raise ValueError(f"No {fixing_curve} fixings available for {self._reference_date}")

        # _fetch_fixings ignores its as_of_date argument and returns the WHOLE series (measured
        # 2026-08-14: as_of=2018-06-12 still returns 2018-04-02..2026-08-13). Taking .tail(1) of
        # that therefore used TODAY's overnight rate as the repo rate for every historical date --
        # 3.62% for a June-2018 report whose real fixing was 1.67%, and for an October-2020 report
        # whose real fixing was 0.10%. That silently corrupts net basis, BNOC and implied repo
        # across all history, which is exactly where a basis strategy reads. Slice by the
        # reference date here rather than changing _fetch_fixings, which has callers outside this
        # path that do want the full series.
        as_of = pd.Timestamp(self._reference_date)
        on_or_before = fixings[pd.to_datetime(fixings.index) <= as_of]
        if on_or_before.empty:
            raise ValueError(
                f"No {fixing_curve} fixing on or before {self._reference_date}; "
                f"earliest available is {fixings.index[0]}"
            )
        return float(on_or_before.iloc[-1]) * 100.0

    def conversion_factors(self) -> List[float]:
        return list(self._conversion_factors)

    def gross_basis(
        self,
        future_price: Optional[float] = None,
        prices: Optional[Sequence[float]] = None,
        settlement: Optional[DateLike] = None,
        dirty: bool = False,
    ) -> Tuple[float, ...]:
        if not self._basket_pricers:
            raise ValueError("Cannot compute gross basis without a deliverable basket")
        bf = self.build_rateslib_object(curves=self._curve_id)
        kwargs = {
            "future_price": self._resolve_future_price(future_price),
            "prices": self._resolve_prices(prices),
            "dirty": dirty,
        }
        if settlement is not None:
            kwargs["settlement"] = self._coerce_datetime(settlement)
        return tuple(float(x) for x in bf.gross_basis(**kwargs))

    def net_basis(
        self,
        repo_rate: Optional[float | Sequence[float]] = None,
        future_price: Optional[float] = None,
        prices: Optional[Sequence[float]] = None,
        settlement: Optional[DateLike] = None,
        delivery: Optional[DateLike] = None,
        convention: Optional[str] = "Act360",
        dirty: bool = False,
        curve_name: Optional[str] = None,
    ) -> Tuple[float, ...]:
        if not self._basket_pricers:
            raise ValueError("Cannot compute net basis without a deliverable basket")
        bf = self.build_rateslib_object(curves=self._curve_id)
        kwargs = {
            "future_price": self._resolve_future_price(future_price),
            "prices": self._resolve_prices(prices),
            "repo_rate": self._resolve_repo_rate(repo_rate=repo_rate, curve_name=curve_name),
            "settlement": self._resolve_settlement(settlement),
            "delivery": self._resolve_delivery(delivery),
            "dirty": dirty,
        }
        if convention is not None:
            kwargs["convention"] = convention
        return tuple(float(x) for x in bf.net_basis(**kwargs))

    def bnoc(
        self,
        repo_rate: Optional[float | Sequence[float]] = None,
        future_price: Optional[float] = None,
        prices: Optional[Sequence[float]] = None,
        settlement: Optional[DateLike] = None,
        delivery: Optional[DateLike] = None,
        convention: Optional[str] = "Act360",
        dirty: bool = False,
        curve_name: Optional[str] = None,
    ) -> Tuple[float, ...]:
        return self.net_basis(
            repo_rate=repo_rate,
            future_price=future_price,
            prices=prices,
            settlement=settlement,
            delivery=delivery,
            convention=convention,
            dirty=dirty,
            curve_name=curve_name,
        )

    def implied_repo(
        self,
        future_price: Optional[float] = None,
        prices: Optional[Sequence[float]] = None,
        settlement: Optional[DateLike] = None,
        delivery: Optional[DateLike] = None,
        convention: Optional[str] = "Act360",
        dirty: bool = False,
    ) -> Tuple[float, ...]:
        if not self._basket_pricers:
            raise ValueError("Cannot compute implied repo without a deliverable basket")
        bf = self.build_rateslib_object(curves=self._curve_id)
        kwargs = {
            "future_price": self._resolve_future_price(future_price),
            "prices": self._resolve_prices(prices),
            "settlement": self._resolve_settlement(settlement),
            "dirty": dirty,
        }
        if delivery is not None:
            kwargs["delivery"] = self._coerce_datetime(delivery)
        if convention is not None:
            kwargs["convention"] = convention
        return tuple(float(x) for x in bf.implied_repo(**kwargs))

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

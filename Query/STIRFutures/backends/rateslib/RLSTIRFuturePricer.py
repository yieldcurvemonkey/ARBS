import datetime
from dataclasses import dataclass
from typing import Union, Any, Optional

import rateslib as rl
import numpy as np
import pandas as pd

from Query.STIRFutures._STIRFutureGenericPricer import _STIRFutureGenericPricer
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
from utils.rl_compat import rate_fixings_kwargs, stirf_analytic_delta, stirf_pv01


def _extract_stirf_contracts(stirf: rl.STIRFuture) -> int:
    kwargs_obj = getattr(stirf, "_kwargs", None) or getattr(stirf, "kwargs", None)
    if kwargs_obj is not None:
        meta = getattr(kwargs_obj, "meta", None)
        if isinstance(meta, dict) and meta.get("contracts") is not None:
            try:
                return int(meta["contracts"])
            except Exception:
                pass

        leg1 = getattr(kwargs_obj, "leg1", None)
        nominal = meta.get("nominal") if isinstance(meta, dict) else None
        if isinstance(leg1, dict):
            notional = leg1.get("notional")
            try:
                if nominal is not None and notional is not None and float(nominal) != 0.0:
                    return int(round(abs(float(notional)) / float(nominal)))
            except Exception:
                pass

    legacy_kwargs = getattr(stirf, "__dict__", {}).get("kwargs")
    if isinstance(legacy_kwargs, dict) and legacy_kwargs.get("contracts") is not None:
        try:
            return int(legacy_kwargs["contracts"])
        except Exception:
            pass

    contracts_attr = getattr(stirf, "contracts", None)
    if contracts_attr is not None:
        try:
            return int(contracts_attr)
        except Exception:
            pass

    return 1


@dataclass
class RLSTIRFuturePricer(_STIRFutureGenericPricer):
    _curve: str
    _rl_stirf_id: str

    _reference_date: datetime.date
    _effective_date: datetime.date
    _maturity_date: datetime.date

    _price: float
    _rate: float
    _contracts: int
    _notional: float

    _meta_data: Any

    def __init__(
        self,
        rl_stirf_id: str,
        reference_date: Union[datetime.datetime, datetime.date],
        effective_date: Union[datetime.datetime, datetime.date],
        maturity_date: Union[datetime.datetime, datetime.date],
        curve: Optional[str] = None,
        price: Optional[float] = None,
        rate: Optional[float] = None,
        contracts: Optional[int] = None,
        notional: Optional[float] = None,
        meta_data: Optional[Any] = None,
    ):
        assert price is not None or rate is not None, "must pass in price or rate to price STIR future"
        self._rl_stirf_id = rl_stirf_id

        known_id_to_curve_map = {
            "SFR": "USD-SOFR-1D",
            "SR3": "USD-SOFR-1D",
            "SER": "USD-SOFR-1D",
            "SR1": "USD-SOFR-1D",
            "FF": "USD-FEDFUNDS",
            "ZQ": "USD-FEDFUNDS",
            "RA": "EUR-ESTR",
            "EB": "EUR-ESTR",
            "IJ": "EUR-ESTR",
            "RG": "CAD-CORRA",
            "IM": "EUR-EURIBOR-3M",
            "TV": "EUR-EURIBOR-3M",
            "J8": "GBP-SONIA",
            "JU": "GBP-SONIA",
            "T0": "JPY-TONA",
            "IT": "JPY-TONA",
            "J2": "CHF-SARON",
        }
        if self._rl_stirf_id[:-3] in known_id_to_curve_map:
            self._curve = known_id_to_curve_map[self._rl_stirf_id[:-3]]
        else:
            self._curve = curve

        self._reference_date = reference_date
        self._effective_date = effective_date
        self._maturity_date = maturity_date

        if price is not None:
            self._price = price
            self._rate = 100.0 - price
        else:
            self._rate = rate
            self._price = 100.0 - rate

        # Default to 1 contract or 1MM notional if neither provided, similar to FRB defaults
        if contracts is None and notional is None:
            self._contracts = 1
            self._notional = 1_000_000.0  # Placeholder; actual notional depends on spec
        elif contracts is not None:
            self._contracts = contracts
            self._notional = notional  # Can be None, will be derived if needed
        else:
            self._contracts = int(notional / 1_000_000)  # Approx
            self._notional = notional

        self._meta_data = meta_data

    def _to_rl_dt(self, pydate: datetime.date):
        return rl.dt(pydate.year, pydate.month, pydate.day)

    def id(self) -> str:
        return self._rl_stirf_id

    def reference_date(self) -> datetime.date:
        if isinstance(self._reference_date, datetime.datetime):
            return self._reference_date.date()
        return self._reference_date

    def effective_date(self) -> datetime.date:
        if isinstance(self._effective_date, datetime.datetime):
            return self._effective_date.date()
        return self._effective_date

    def maturity_date(self) -> datetime.date:
        if isinstance(self._maturity_date, datetime.datetime):
            return self._maturity_date.date()
        return self._maturity_date

    def calendar(self) -> rl.Cal:
        # Assuming we look up the calendar from the definitions map used for curves/IRSwaps
        # This matches how FRB looked up 'spec' then got 'calendar'
        spec = RATESLIB_CURVE_DEFINITIONS[self._curve].get("ReferenceRate2", RATESLIB_CURVE_DEFINITIONS[self._curve]["ReferenceRate"])
        return rl.defaults.spec[spec]["calendar"]

    def calendar_advance(self, dt1: Union[datetime.date, rl.dt], dt2: str):
        # Using the BusinessConvention from definitions
        return rl.add_tenor(
            self._to_rl_dt(dt1),
            tenor=str(dt2),
            modifier=RATESLIB_CURVE_DEFINITIONS[self._curve]["BusinessConvention"],
            calendar=RATESLIB_CURVE_DEFINITIONS[self._curve]["Calendar"],
        )

    def handle(self) -> Any:
        return None  # No curve handle

    def index(self) -> Any:
        return None

    def meta(self) -> Any:
        return self._meta_data

    def fixed_rate(self) -> float:
        return self._rate

    def set_fixed_rate(self, rate_decimal: float) -> None:
        self._rate = rate_decimal * 100
        self._price = 100.0 - self._rate

    def fair_rate(self) -> float:
        return self._rate / 100.0

    def notional(self) -> float:
        if self._notional is not None:
            return self._notional
        # If notional wasn't passed, we can try to infer it from the rateslib object properties
        # but that requires building it.
        temp = self.build_stirf(contracts=self._contracts)
        # rateslib STIRFuture 'nominal' is usually per-contract
        return float(temp.contracts * temp.nominal)

    def price(self) -> float:
        return self._price

    def npv(self) -> float:
        return self.price() * self.pv01(contracts=self._contracts, notional=self._notional)

    def pv01(self, contracts=None, notional=None, stirf: rl.STIRFuture = None) -> float:
        if stirf is not None:
            unit_bpv = -float(stirf_analytic_delta(self.build_stirf()).real)
            return _extract_stirf_contracts(stirf) * unit_bpv

        # A STIR future's analytic_delta needs no curve of its own -- see
        # utils.rl_compat.stirf_analytic_delta for why 2.7 nonetheless asks for one.
        return -float(
            stirf_analytic_delta(
                self.build_stirf(contracts=contracts or self._contracts, notional=notional or self._notional)
            ).real
        )

    def dv01(self, shift: float = 1e-4) -> float:
        return self.pv01()

    def gamma(self, shift: float = 1e-4) -> float:
        raise NotImplementedError("Gamma not implemented without solver/curve")

    def dollar_carry(self, horizon: str) -> float:
        raise NotImplementedError("Dollar carry not implemented")

    def carry_bps_running(self, horizon: str) -> float:
        # We can implement this purely on price/rate expectations if we assume
        # the curve shape logic is handled by the caller constructing new pricers,
        # but here we don't have a curve to roll down.
        # However, following the pattern:
        # If we can't project forward without a curve, we raise.
        raise NotImplementedError("Cannot calculate carry without a curve")

    def roll_bps_running(self, horizon: str) -> float:
        raise NotImplementedError("Cannot calculate roll without a curve")

    def carry_and_roll_bps_running(self, horizon: str) -> float:
        raise NotImplementedError("Cannot calculate carry/roll without a curve")

    def resolve_pricable(self, stirf: Any, risk_weight: Optional[float] = None) -> Any:
        # Used for flipping signs or adjusting notional based on risk weight
        # RLFixedRateBondPricer raises NotImplementedError here, but let's be helpful.
        # We just return a new pricer/object with inverted direction?
        # Actually, standard pattern in this codebase is to return the rateslib object.

        # If risk_weight is negative, we might want a short position
        new_contracts = self._contracts
        if risk_weight is not None:
            # Heuristic: if RW is negative, flip contracts?
            # Or just return the object as-is and let the ValueMap handle the multiplication.
            pass

        return self.build_stirf()

    _MONTHLY_ROOTS = {"SR1", "ZQ", "IJ", "JU"}
    _CME_TO_BBG = {
        "SR3": "SFR",
        "SR1": "SER",
        "ZQ": "FF",
    }

    def root(self) -> str:
        import re
        m = re.match(r"^([A-Z0-9]+?)[FGHJKMNQUVXZ]\d{2}$", self._rl_stirf_id)
        return m.group(1) if m else self._rl_stirf_id[:-3]

    def bbg_root(self) -> str:
        return self._CME_TO_BBG.get(self.root(), self.root())

    def bbg_id(self) -> str:
        import re
        m = re.match(r"^([A-Z0-9]+?)([FGHJKMNQUVXZ]\d{2})$", self._rl_stirf_id)
        if m:
            return f"{self.bbg_root()}{m.group(2)}"
        return self._rl_stirf_id

    def curve_key(self) -> str:
        return self._curve

    def is_monthly(self) -> bool:
        return self.root() in self._MONTHLY_ROOTS

    def rl_spec(self, curve_key: Optional[str] = None) -> str:
        ck = curve_key or self._curve
        is_ser = self.root() in {"SR1", "SER", "SL"}
        spec_key = "ReferenceRate3" if is_ser else "ReferenceRate2"
        return RATESLIB_CURVE_DEFINITIONS[ck].get(
            spec_key, RATESLIB_CURVE_DEFINITIONS[ck]["ReferenceRate"]
        )

    def build_for_solver(
        self,
        rl_curve,
        curve_key: Optional[str] = None,
        fallback_fixings: Optional[pd.Series] = None,
    ) -> rl.STIRFuture:
        """Build an rl.STIRFuture bound to an external curve (e.g. a risk curve).

        The rateslib spec is always resolved from the instrument's own curve
        (self._curve), not from curve_key — the spec encodes the contract
        structure (monthly vs quarterly) which doesn't change when the
        instrument is mapped to a different risk curve.
        """
        spec = self.rl_spec()
        kwargs = dict(
            effective=self._to_rl_dt(self.effective_date()),
            termination=self._to_rl_dt(self.maturity_date()),
            spec=spec,
            price=float(self._price),
            contracts=1,
            curves=rl_curve,
        )
        meta = self._meta_data if isinstance(self._meta_data, dict) else {}
        fixings = meta.get("fixings")
        if fixings is None:
            fixings = fallback_fixings
        if fixings is not None and isinstance(fixings, pd.Series) and not fixings.empty:
            cal = rl.get_calendar(rl.defaults.spec[spec].get("calendar", "nyc"))
            mask = pd.Series(
                [cal.is_bus_day(d.to_pydatetime() if hasattr(d, "to_pydatetime") else d) for d in fixings.index],
                index=fixings.index,
            )
            fixings = fixings[mask]
            if not fixings.empty:
                return rl.STIRFuture(**kwargs, **rate_fixings_kwargs(fixings))
        return rl.STIRFuture(**kwargs)

    def build_pricable(self, /, **kwargs: Any) -> Any:
        # Generic entry point
        return self.build_stirf(
            effective_date=kwargs.get("effective_date"),
            maturity_date=kwargs.get("maturity_date"),
            price=kwargs.get("price"),
            rate=kwargs.get("rate"),
            contracts=kwargs.get("contracts"),
            notional=kwargs.get("notional"),
            is_ser=kwargs.get("is_ser", False),
        )

    def build_stirf(
        self,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        price: Optional[float] = None,
        rate: Optional[float] = None,
        contracts: Optional[int] = None,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
        is_ser: Optional[bool] = False,
        fixings: Optional[pd.Series] = None,
        **kwargs,
    ) -> rl.STIRFuture:
        if "SR1" in self._rl_stirf_id or "SER" in self._rl_stirf_id: 
            is_ser = True

        eff = effective_date or self.effective_date()
        mat = maturity_date or self.maturity_date()

        p = price if price is not None else (self._price if rate is None else (100.0 - rate))

        c: Optional[int] = contracts

        if c is None and bpv is not None:
            spec_key = "ReferenceRate3" if is_ser else "ReferenceRate2"
            spec = RATESLIB_CURVE_DEFINITIONS[self._curve].get(
                spec_key,
                RATESLIB_CURVE_DEFINITIONS[self._curve]["ReferenceRate"],
            )

            one_contract = rl.STIRFuture(
                effective=self._to_rl_dt(eff),
                termination=self._to_rl_dt(mat),
                spec=spec,
                price=p,
                contracts=1,
                curves=self._curve
            )

            pv01_per_contract = stirf_pv01(one_contract)
            if pv01_per_contract <= 0:
                raise ValueError("Computed pv01_per_contract is zero or invalid")

            c = int(round(bpv / pv01_per_contract))

        if c is None and (notional is not None or self._notional is not None):
            n = notional if notional is not None else self._notional
            # Standard STIR assumption: 1mm face per contract
            c = int(round(n / 1_000_000))

        if c is None:
            c = self._contracts

        if c is None:
            c = 1

        spec_key = "ReferenceRate3" if is_ser else "ReferenceRate2"
        spec = RATESLIB_CURVE_DEFINITIONS[self._curve].get(
            spec_key,
            RATESLIB_CURVE_DEFINITIONS[self._curve]["ReferenceRate"],
        )

        stir_kwargs = {
            "effective": self._to_rl_dt(eff),
            "termination": self._to_rl_dt(mat),
            "spec": spec,
            "price": p,
            "contracts": int(c),
            "curves": self._curve,
        }

        meta_fixings = self._meta_data.get("fixings", None) if isinstance(self._meta_data, dict) else None
        applied_fixings = fixings if fixings is not None else meta_fixings
        return rl.STIRFuture(**stir_kwargs, **rate_fixings_kwargs(applied_fixings))

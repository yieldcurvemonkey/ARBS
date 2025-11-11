# ABOUTME: Concrete implementation of fixed rate bond pricer interface using rateslib library
# ABOUTME: Provides bond pricing, Greeks calculation, and analytics backed by rateslib functionality
import datetime
from dataclasses import dataclass
from typing import Union, Any, Optional

import rateslib as rl
import numpy as np

from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.FixedRateBonds.backends.rateslib.rl_frb_definitions_map import RATESLIB_FRB_DEFINITIONS


@dataclass
class RLFixedRateBondPricer(_FixedRateBondGenericPricer):
    _rl_frb_id: str

    _reference_date: datetime.date
    _issue_date: datetime.date
    _maturity_date: datetime.date
    _cpn: float

    _notional: float
    _clean_price: float
    _ytm: float

    _meta_data: Any

    def __init__(
        self,
        rl_frb_id: str,
        reference_date: Union[datetime.datetime, datetime.date],
        issue_date: Union[datetime.datetime, datetime.date],
        maturity_date: Union[datetime.datetime, datetime.date],
        cpn: float,
        notional: Optional[float] = None,
        clean_price: Optional[float] = None,
        ytm: Optional[float] = None,
        meta_data: Optional[Any] = None,
    ):
        assert clean_price is None or ytm is None, "must pass in clean_price or ytm to price bond"
        self._rl_frb_id = rl_frb_id

        self._reference_date = reference_date
        self._issue_date = issue_date
        self._maturity_date = maturity_date
        self._cpn = cpn

        self._notional = notional
        self._clean_price = clean_price
        self._ytm = ytm

        self._meta_data = meta_data

    def _to_rl_dt(self, pydate: datetime.date):
        return rl.dt(pydate.year, pydate.month, pydate.day)

    def id(self):
        return self._rl_frb_id

    def reference_date(self) -> datetime.date:
        return datetime.date(self._reference_date.year, self._reference_date.month, self._reference_date.day)

    def issue_date(self):
        return datetime.date(self._issue_date.year, self._issue_date.month, self._issue_date.day)

    def maturity_date(self):
        return datetime.date(self._maturity_date.year, self._maturity_date.month, self._maturity_date.day)

    def calendar(self) -> rl.NamedCal:
        return rl.defaults.spec[RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"]]["calendar"]

    def calendar_advance(self, dt1: Union[datetime.date, rl.dt], dt2: str):
        return rl.add_tenor(
            self._to_rl_dt(dt1),
            tenor=str(dt2),
            modifier=rl.defaults.spec[RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"]]["modifier"],
            calendar=rl.defaults.spec[RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"]]["calendar"],
        )

    def meta(self):
        return self._meta_data

    def build_schedule(self) -> rl.Schedule:
        return rl.FixedRateBond(
            self._to_rl_dt(self.issue_date()), self._to_rl_dt(self.maturity_date()), spec=RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"], fixed_rate=self.coupon()
        ).kwargs["schedule"]

    def coupon(self):
        return self._cpn

    def ytm(self):
        if self._ytm is not None:
            return self._ytm
        return rl.FixedRateBond(
            self._to_rl_dt(self.issue_date()), self._to_rl_dt(self.maturity_date()), spec=RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"], fixed_rate=self.coupon()
        ).ytm(
            price=self.clean_price(),
            dirty=False,
            settlement=self.calendar_advance(
                self._to_rl_dt(self.reference_date()), f"{rl.defaults.spec[RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"]]["settle"]}B"
            ),
        )

    def dirty_price(self, notional=None):
        return rl.FixedRateBond(
            self._to_rl_dt(self.issue_date()),
            self._to_rl_dt(self.maturity_date()),
            spec=RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"],
            fixed_rate=self.coupon(),
            notional=notional,
        ).price(
            ytm=self.ytm(),
            dirty=True,
            settlement=self.calendar_advance(
                self._to_rl_dt(self.reference_date()), f"{rl.defaults.spec[RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"]]["settle"]}B"
            ),
        )

    def clean_price(self):
        return rl.FixedRateBond(
            self._to_rl_dt(self.issue_date()),
            self._to_rl_dt(self.maturity_date()),
            spec=RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"],
            fixed_rate=self.coupon(),
        ).price(
            ytm=self.ytm(),
            dirty=False,
            settlement=self.calendar_advance(
                self._to_rl_dt(self.reference_date()), f"{rl.defaults.spec[RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"]]["settle"]}B"
            ),
        )

    def npv(self, notional=None):
        raise NotImplementedError()

    def accured(self):
        raise NotImplementedError()

    def bpv(self, notional=1_000_000):
        return rl.FixedRateBond(
            self._to_rl_dt(self.issue_date()),
            self._to_rl_dt(self.maturity_date()),
            spec=RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"],
            fixed_rate=self.coupon(),
            notional=notional,
        ).duration(
            ytm=self.ytm(),
            settlement=self.calendar_advance(
                self._to_rl_dt(self.reference_date()), f"{rl.defaults.spec[RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"]]["settle"]}B"
            ),
            metric="risk",
        )

    def pv01(self, notional=None):
        return self.bpv(notional=notional)

    def mod_duration(self):
        return rl.FixedRateBond(
            self._to_rl_dt(self.issue_date()),
            self._to_rl_dt(self.maturity_date()),
            spec=RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"],
            fixed_rate=self.coupon(),
        ).duration(
            ytm=self.ytm(),
            settlement=self.calendar_advance(
                self._to_rl_dt(self.reference_date()), f"{rl.defaults.spec[RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"]]["settle"]}B"
            ),
            metric="modified",
        )

    def convexity(self):
        return rl.FixedRateBond(
            self._to_rl_dt(self.issue_date()),
            self._to_rl_dt(self.maturity_date()),
            spec=RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"],
            fixed_rate=self.coupon(),
        ).convexity(
            ytm=self.ytm(),
            settlement=self.calendar_advance(
                self._to_rl_dt(self.reference_date()), f"{rl.defaults.spec[RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"]]["settle"]}B"
            ),
        )

    def time_to_maturity(self):
        return rl.dcf(
            self._to_rl_dt(self.reference_date()),
            self._to_rl_dt(self.maturity_date()),
            rl.defaults.spec[RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"]]["convention"],
        )

    def zspread(self):
        raise NotImplementedError()

    def notional(self, frb: rl.FixedRateBond):
        return float(frb.__dict__["kwargs"]["notional"])

    def resolve_pricable(self, frb: rl.FixedRateBond, risk_weight=None):
        raise NotImplementedError()

    def build_pricable(self, /, **kwargs):
        return self.build_fixed_rate_bond(
            issue_date=kwargs.get("issue_date"),
            maturity_date=kwargs.get("maturity_date"),
            coupon=kwargs.get("coupon") or kwargs.get("cpn"),
            notional=kwargs.get("notional"),
            bpv=kwargs.get("bpv") or kwargs.get("risk"),
        )

    def build_fixed_rate_bond(self, issue_date=None, maturity_date=None, coupon=None, notional=None, bpv=None):
        if notional is None and bpv is not None:
            notional = bpv / self.bpv(notional=1)

        return rl.FixedRateBond(
            self._to_rl_dt(issue_date), self._to_rl_dt(maturity_date), spec=RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"], fixed_rate=coupon, notional=notional
        )

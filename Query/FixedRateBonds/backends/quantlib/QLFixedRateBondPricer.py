import datetime
from dataclasses import dataclass
from typing import Union, Any, Optional

import QuantLib as ql
import numpy as np

from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.FixedRateBonds.backends.quantlib.ql_frb_definitions_map import QUANTLIB_FRB_DEFINITIONS

from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date


@dataclass
class QLFixedRateBondPricer(_FixedRateBondGenericPricer):
    _ql_frb_id: str

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
        ql_frb_id: str,
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
        self._ql_frb_id = ql_frb_id

        self._reference_date = reference_date
        self._issue_date = issue_date
        self._maturity_date = maturity_date
        self._cpn = cpn

        self._notional = notional
        self._clean_price = clean_price
        self._ytm = ytm

        self._meta_data = meta_data

    def id(self):
        return self._ql_frb_id

    def reference_date(self) -> datetime.date:
        return datetime.date(self._reference_date.year, self._reference_date.month, self._reference_date.day)

    def issue_date(self):
        return datetime.date(self._issue_date.year, self._issue_date.month, self._issue_date.day)

    def maturity_date(self):
        return datetime.date(self._maturity_date.year, self._maturity_date.month, self._maturity_date.day)

    def calendar(self) -> ql.Calendar:
        return QUANTLIB_FRB_DEFINITIONS[self.id()]["Calendar"]

    def calendar_advance(self, dt1: Union[datetime.date, ql.Date], dt2: Union[int, ql.Period, str]):
        cal = self.calendar()
        d1 = datetime_to_ql_date(dt1)
        bdc = QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["BusinessConvention"]
        if isinstance(dt2, int):
            return cal.advance(d1, int(dt2), ql.Days, bdc)  # settlement *days*
        elif isinstance(dt2, ql.Period):
            return cal.advance(d1, dt2, bdc)
        elif isinstance(dt2, str):
            return cal.advance(d1, ql.Period(dt2), bdc)
        else:
            raise TypeError("dt2 must be int days, ql.Period, or period string")

    def meta(self):
        return self._meta_data

    def build_schedule(self) -> ql.Schedule:
        return ql.Schedule(
            datetime_to_ql_date(self.issue_date()),
            datetime_to_ql_date(self.maturity_date()),
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["FrequencyPeriod"],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Calendar"],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["BusinessConvention"],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["BusinessConvention"],
            ql.DateGeneration.Backward,
            False,
        )

    def coupon(self):
        return self._cpn

    def ytm(self):
        ql.Settings.instance().evaluationDate = ql.Date(self._reference_date.day, self._reference_date.month, self._reference_date.year)

        if self._ytm is not None:
            return self._ytm
        return (
            self.build_fixed_rate_bond(issue_date=self.issue_date(), maturity_date=self.maturity_date(), coupon=self.coupon()).bondYield(
                ql.BondPrice(self._clean_price, ql.BondPrice.Clean),
                QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["DayCounter"],
                QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Compounded"],
                QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Frequency"],
                self.calendar_advance(self._reference_date, QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["SettlementDays"]),
            )
            * 100
        )

    def dirty_price(self, notional=None):
        ql_eval_date = ql.Date(self._reference_date.day, self._reference_date.month, self._reference_date.year)
        ql.Settings.instance().evaluationDate = ql_eval_date

        ql_frb = self.build_fixed_rate_bond(issue_date=self.issue_date(), maturity_date=self.maturity_date(), coupon=self.coupon(), notional=notional)
        ql_frb.setPricingEngine(
            ql.DiscountingBondEngine(
                ql.YieldTermStructureHandle(
                    ql.FlatForward(
                        ql_eval_date,
                        ql.QuoteHandle(ql.SimpleQuote(self.ytm() / 100)),
                        QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["DayCounter"],
                        QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Frequency"],
                    )
                )
            )
        )
        return ql_frb.dirtyPrice()

    def clean_price(self):
        ql.Settings.instance().evaluationDate = ql.Date(self._reference_date.day, self._reference_date.month, self._reference_date.year)

        if self._clean_price is not None:
            return self._clean_price
        return ql.BondFunctions.cleanPrice(
            self.build_fixed_rate_bond(issue_date=self.issue_date(), maturity_date=self.maturity_date(), coupon=self.coupon()),
            self._ytm / 100,
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["DayCounter"],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Compounded"],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Frequency"],
        )

    def npv(self, notional=None):
        ql_eval_date = ql.Date(self._reference_date.day, self._reference_date.month, self._reference_date.year)
        ql.Settings.instance().evaluationDate = ql_eval_date

        ql_frb = self.build_fixed_rate_bond(issue_date=self.issue_date(), maturity_date=self.maturity_date(), coupon=self.coupon(), notional=notional)
        ql_frb.setPricingEngine(
            ql.DiscountingBondEngine(
                ql.YieldTermStructureHandle(
                    ql.FlatForward(
                        ql_eval_date,
                        ql.QuoteHandle(ql.SimpleQuote(self.ytm() / 100)),
                        QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["DayCounter"],
                        QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Frequency"],
                    )
                )
            )
        )
        return ql_frb.NPV()

    def accured(self):
        ql_eval_date = ql.Date(self._reference_date.day, self._reference_date.month, self._reference_date.year)
        ql.Settings.instance().evaluationDate = ql_eval_date

        ql_frb = self.build_fixed_rate_bond(issue_date=self.issue_date(), maturity_date=self.maturity_date(), coupon=self.coupon())
        ql_frb.setPricingEngine(
            ql.DiscountingBondEngine(
                ql.YieldTermStructureHandle(
                    ql.FlatForward(
                        ql_eval_date,
                        ql.QuoteHandle(ql.SimpleQuote(self.ytm() / 100)),
                        QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["DayCounter"],
                        QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Frequency"],
                    )
                )
            )
        )
        return ql_frb.accruedAmount()

    def bpv(self, notional=1_000_000):
        ql.Settings.instance().evaluationDate = ql.Date(self._reference_date.day, self._reference_date.month, self._reference_date.year)
        return np.copysign(
            ql.BondFunctions.basisPointValue(
                self.build_fixed_rate_bond(issue_date=self.issue_date(), maturity_date=self.maturity_date(), coupon=self.coupon(), notional=notional),
                ql.InterestRate(
                    self.ytm() / 100,
                    QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["DayCounter"],
                    QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Compounded"],
                    QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Frequency"],
                ),
            ),
            notional,
        )

    def pv01(self, notional=None):
        ql.Settings.instance().evaluationDate = ql.Date(self._reference_date.day, self._reference_date.month, self._reference_date.year)
        return np.copysign(
            ql.BondFunctions.basisPointValue(
                self.build_fixed_rate_bond(
                    issue_date=self.issue_date(), maturity_date=self.maturity_date(), coupon=self.coupon(), notional=notional or self._notional
                ),
                ql.InterestRate(
                    self.ytm() / 100,
                    QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["DayCounter"],
                    QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Compounded"],
                    QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Frequency"],
                ),
            ),
            notional or self._notional,
        )

    def mod_duration(self):
        ql.Settings.instance().evaluationDate = ql.Date(self._reference_date.day, self._reference_date.month, self._reference_date.year)
        return ql.BondFunctions.duration(
            self.build_fixed_rate_bond(issue_date=self.issue_date(), maturity_date=self.maturity_date(), coupon=self.coupon()),
            ql.InterestRate(
                self.ytm() / 100,
                QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["DayCounter"],
                QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Compounded"],
                QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Frequency"],
            ),
            ql.Duration.Modified,
        )

    def convexity(self):
        ql.Settings.instance().evaluationDate = ql.Date(self._reference_date.day, self._reference_date.month, self._reference_date.year)
        return ql.BondFunctions.convexity(
            self.build_fixed_rate_bond(issue_date=self.issue_date(), maturity_date=self.maturity_date(), coupon=self.coupon(), notional=self._notional),
            ql.InterestRate(
                self.ytm() / 100,
                QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["DayCounter"],
                QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Compounded"],
                QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Frequency"],
            ),
        )
    
    def time_to_maturity(self):
        as_of = self.reference_date()
        mat = self.maturity_date()
        dc = ql.ActualActual(ql.ActualActual.Actual365)
        ql_as_of = ql.Date(as_of.day, as_of.month, as_of.year)
        ql_mat = ql.Date(mat.day, mat.month, mat.year) 
        ql.Settings.instance().evaluationDate = ql_as_of
        return dc.yearFraction(ql_as_of, ql_mat)

    def zspread(self):
        raise NotImplementedError()

    def notional(self, frb: ql.FixedRateBond):
        return float(frb.notional())

    def resolve_pricable(self, frb: ql.FixedRateBond, risk_weight=None):
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

        ql_sch = ql.Schedule(
            datetime_to_ql_date(issue_date),
            datetime_to_ql_date(maturity_date),
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["FrequencyPeriod"],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Calendar"],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["BusinessConvention"],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["BusinessConvention"],
            ql.DateGeneration.Backward,
            False,
        )

        return ql.FixedRateBond(
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["SettlementDays"],
            notional or 100,
            ql_sch,
            [coupon / 100],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["DayCounter"],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["BusinessConvention"],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Redemption"],
        )

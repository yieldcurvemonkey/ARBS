from typing import Literal, Optional

import numpy as np
import QuantLib as ql
import datetime

from Query.IRSwaps.backends.quantlib.curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date


def build_ql_irswap(
    curve: str,
    curve_handle: ql.YieldTermStructureHandle,
    swap_index: Optional[ql.SwapIndex] = None,
    fwd: Optional[ql.Period] = None,
    tenor: Optional[ql.Period] = None,
    effective_date: Optional[datetime.date] = None,
    maturity_date: Optional[datetime.date] = None,
    fixed_rate: Optional[float] = -0.00,
    notional: Optional[float] = None,
    bpv: Optional[float] = None,
    r_p: Optional[Literal["rec", "r", "pay", "p"]] = None,
) -> ql.VanillaSwap | ql.OvernightIndexedSwap:

    def _make_swap(nominal: float) -> ql.VanillaSwap | ql.OvernightIndexedSwap:
        period_tenor = fwd and tenor
        mm_tenor = effective_date and maturity_date
        assert period_tenor or mm_tenor, "Must specify either tenor (fwd+tenor) or dates (effective+termination)"

        is_ois = "ois" in str(QUANTLIB_CURVE_DEFINITIONS[curve]["UseCase"]).lower()

        if period_tenor:
            fwd_start = ql.Period(fwd) if isinstance(fwd, str) else fwd
            swap_tenor = ql.Period(tenor) if isinstance(tenor, str) else tenor

            if is_ois:
                swap: ql.OvernightIndexedSwap = ql.MakeOIS(
                    fwdStart=fwd_start,
                    swapTenor=swap_tenor,
                    fixedRate=fixed_rate / 100.0,
                    overnightIndex=swap_index or QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRate"](curve_handle),
                    settlementDays=QUANTLIB_CURVE_DEFINITIONS[curve]["SettlementDays"],
                    calendar=QUANTLIB_CURVE_DEFINITIONS[curve]["Calendar"],
                    paymentCalendar=QUANTLIB_CURVE_DEFINITIONS[curve]["Calendar"],
                    fixedLegDayCount=QUANTLIB_CURVE_DEFINITIONS[curve]["DayCounter"],
                    fixedLegConvention=QUANTLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
                    paymentFrequency=QUANTLIB_CURVE_DEFINITIONS[curve]["PaymentFrequency"],
                    paymentLag=QUANTLIB_CURVE_DEFINITIONS[curve]["PaymentLag"],
                    nominal=abs(nominal),
                    receiveFixed=(r_p.startswith("r") if r_p else nominal > 0),
                    fixedLegTerminationDateConvention=ql.Unadjusted,
                    overnightLegTerminationDateConvention=ql.Unadjusted,
                    terminationDateConvention=ql.Unadjusted,
                    endOfMonth=False, # has to be dynamic e.g. true for short swap, false for longer dated swaps
                )
            else:
                swap: ql.VanillaSwap = ql.MakeVanillaSwap(
                    forwardStart=fwd_start,
                    swapTenor=swap_tenor,
                    iborIndex=swap_index or QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRate"](curve_handle),
                    fixedRate=fixed_rate / 100,
                    fixedLegTenor=ql.Period(QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRateTermValue"], QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRateTermUnit"]),
                    fixedLegCalendar=QUANTLIB_CURVE_DEFINITIONS[curve]["Calendar"],
                    fixedLegConvention=QUANTLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
                    fixedLegDayCount=QUANTLIB_CURVE_DEFINITIONS[curve]["DayCounter"],
                    floatingLegTenor=ql.Period(
                        QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRateTermValue"], QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRateTermUnit"]
                    ),
                    floatingLegCalendar=QUANTLIB_CURVE_DEFINITIONS[curve]["Calendar"],
                    floatingLegConvention=QUANTLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
                    floatingLegTerminationDateConvention=QUANTLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
                    nominal=abs(nominal),
                    receiveFixed=r_p.startswith("r") if r_p else nominal > 0,
                    fixedLegTerminationDateConvention=ql.Unadjusted,
                    overnightLegTerminationDateConvention=ql.Unadjusted,
                )
        else:
            eff = datetime_to_ql_date(effective_date)
            term = datetime_to_ql_date(maturity_date)

            if is_ois:
                swap: ql.OvernightIndexedSwap = ql.MakeOIS(
                    fwdStart=ql.Period("-0D"),
                    swapTenor=ql.Period("-0D"),
                    fixedRate=fixed_rate / 100,
                    overnightIndex=swap_index or QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRate"](curve_handle),
                    paymentLag=QUANTLIB_CURVE_DEFINITIONS[curve]["PaymentLag"],
                    settlementDays=QUANTLIB_CURVE_DEFINITIONS[curve]["SettlementDays"],
                    calendar=QUANTLIB_CURVE_DEFINITIONS[curve]["Calendar"],
                    paymentCalendar=QUANTLIB_CURVE_DEFINITIONS[curve]["Calendar"],
                    fixedLegDayCount=QUANTLIB_CURVE_DEFINITIONS[curve]["DayCounter"],
                    fixedLegConvention=QUANTLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
                    paymentAdjustmentConvention=QUANTLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
                    paymentFrequency=QUANTLIB_CURVE_DEFINITIONS[curve]["PaymentFrequency"],
                    nominal=abs(nominal),
                    receiveFixed=r_p.startswith("r") if r_p else nominal > 0,
                    effectiveDate=eff,
                    terminationDate=term,
                    fixedLegTerminationDateConvention=ql.Unadjusted,
                    overnightLegTerminationDateConvention=ql.Unadjusted,
                )
            else:
                swap: ql.VanillaSwap = ql.MakeVanillaSwap(
                    forwardStart=ql.Period("-0D"),
                    swapTenor=ql.Period("-0D"),
                    iborIndex=swap_index or QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRate"](curve_handle),
                    fixedRate=fixed_rate / 100,
                    fixedLegTenor=ql.Period(QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRateTermValue"], QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRateTermUnit"]),
                    fixedLegCalendar=QUANTLIB_CURVE_DEFINITIONS[curve]["Calendar"],
                    fixedLegConvention=QUANTLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
                    fixedLegDayCount=QUANTLIB_CURVE_DEFINITIONS[curve]["DayCounter"],
                    floatingLegTenor=ql.Period(
                        QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRateTermValue"], QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRateTermUnit"]
                    ),
                    floatingLegCalendar=QUANTLIB_CURVE_DEFINITIONS[curve]["Calendar"],
                    floatingLegConvention=QUANTLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
                    floatingLegTerminationDateConvention=QUANTLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
                    nominal=abs(nominal),
                    receiveFixed=r_p.startswith("r") if r_p else nominal > 0,
                    effectiveDate=eff,
                    terminationDate=term,
                    fixedLegTerminationDateConvention=ql.Unadjusted,
                    overnightLegTerminationDateConvention=ql.Unadjusted,
                )

        swap.setPricingEngine(ql.DiscountingSwapEngine(curve_handle))
        return swap

    if fixed_rate == -0.00 or (isinstance(fixed_rate, str) and fixed_rate.lower() == "par"):
        temp = _make_swap(1.0)
        fixed_rate = temp.fairRate() * 100

    if notional is None:
        notional = 1
    swap0 = _make_swap(notional)
    if bpv is not None:
        bps0 = swap0.fixedLegBPS()
        if not bps0:
            raise ValueError("Cannot scale notional: swap fixedLegBPS is zero")
        scale = bpv / bps0
        return _make_swap(np.copysign(notional * scale, bpv))
    return swap0

import datetime
from typing import Literal, Optional

import numpy as np
import QuantLib as ql

from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date, ql_date_to_pydate
from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS


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

    # idk what conventions are: pos risk -> long duration/rec fixed
    if bpv is not None:
        bpv = -bpv

    if notional is not None:
        if notional < 0:
            r_p = "p"
        else:
            r_p = "r"

    def _normalize_side(rp: Optional[str], nom: float) -> bool:
        # True -> receive fixed, False -> pay fixed
        if rp is None:
            return bool(nom > 0.0)
        rpl = str(rp).lower()
        if rpl.startswith(("r", "rec", "receive")):
            return True
        if rpl.startswith(("p", "pay")):
            return False
        # fallback to sign of nominal
        return bool(nom > 0.0)

    def _make_swap(nominal: float) -> ql.VanillaSwap | ql.OvernightIndexedSwap:
        period_tenor = fwd is not None and tenor is not None
        mm_tenor = effective_date is not None and maturity_date is not None
        assert period_tenor or mm_tenor, "Must specify either tenor (fwd+tenor) or dates (effective+termination)"

        is_ois = "ois" in str(QUANTLIB_CURVE_DEFINITIONS[curve]["UseCase"]).lower()

        receive_fixed_flag = bool(_normalize_side(r_p, float(nominal)))

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
                    receiveFixed=receive_fixed_flag,
                    fixedLegTerminationDateConvention=ql.Unadjusted,
                    overnightLegTerminationDateConvention=ql.Unadjusted,
                    terminationDateConvention=ql.Unadjusted,
                    endOfMonth=False,  # has to be dynamic e.g. true for short swap, false for longer dated swaps
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
                    receiveFixed=receive_fixed_flag,
                    fixedLegTerminationDateConvention=ql.Unadjusted,
                    overnightLegTerminationDateConvention=ql.Unadjusted,
                )
        else:
            eff = datetime_to_ql_date(effective_date)
            term = datetime_to_ql_date(maturity_date)
            if term <= eff:
                raise ValueError(f"maturity_date must be after effective_date; got {effective_date} -> {maturity_date}")

            if is_ois:
                # For explicit-date OIS trades, generate the payment schedule forward from the
                # supplied effective date. Backward generation can create a tiny front stub
                # (for example Apr 3 -> Apr 6) that QuantLib then rejects while expanding the
                # overnight coupons.
                payment_schedule = ql.Schedule(
                    eff,
                    term,
                    ql.Period(QUANTLIB_CURVE_DEFINITIONS[curve]["PaymentFrequency"]),
                    QUANTLIB_CURVE_DEFINITIONS[curve]["Calendar"],
                    QUANTLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
                    ql.Unadjusted,
                    ql.DateGeneration.Forward,
                    False,
                )
                swap_type = ql.Swap.Receiver if receive_fixed_flag else ql.Swap.Payer
                swap: ql.OvernightIndexedSwap = ql.OvernightIndexedSwap(
                    swap_type,
                    abs(nominal),
                    payment_schedule,
                    fixed_rate / 100.0,
                    QUANTLIB_CURVE_DEFINITIONS[curve]["DayCounter"],
                    swap_index or QUANTLIB_CURVE_DEFINITIONS[curve]["ReferenceRate"](curve_handle),
                    0.0,
                    QUANTLIB_CURVE_DEFINITIONS[curve]["PaymentLag"],
                    QUANTLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
                    QUANTLIB_CURVE_DEFINITIONS[curve]["Calendar"],
                    False,
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
                    receiveFixed=receive_fixed_flag,
                    effectiveDate=eff,
                    terminationDate=term,
                    fixedLegTerminationDateConvention=ql.Unadjusted,
                    overnightLegTerminationDateConvention=ql.Unadjusted,
                )

        swap.setPricingEngine(ql.DiscountingSwapEngine(curve_handle))
        return swap

    ql.Settings.instance().evaluationDate = curve_handle.referenceDate()
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


def calc_fair_rate(swap: ql.VanillaSwap, curve_handle: ql.YieldTermStructureHandle):
    ql.Settings.instance().evaluationDate = curve_handle.referenceDate()
    swap.setPricingEngine(ql.DiscountingSwapEngine(curve_handle))
    return swap.fairRate()


def calc_npv(swap: ql.VanillaSwap, curve_handle: ql.YieldTermStructureHandle):
    ql.Settings.instance().evaluationDate = curve_handle.referenceDate()
    swap.setPricingEngine(ql.DiscountingSwapEngine(curve_handle))
    return swap.NPV()


def calc_pv01(swap: ql.VanillaSwap, curve_handle: ql.YieldTermStructureHandle):
    ql.Settings.instance().evaluationDate = curve_handle.referenceDate()
    swap.setPricingEngine(ql.DiscountingSwapEngine(curve_handle))
    return swap.fixedLegBPS()  # bumps fixed rate/coupon


def calc_dv01(swap: ql.VanillaSwap, curve_handle: ql.YieldTermStructureHandle, curve: str, shift: Optional[float] = 1e-4) -> float:
    ql.Settings.instance().evaluationDate = curve_handle.referenceDate()
    swap.setPricingEngine(ql.DiscountingSwapEngine(curve_handle))

    embedded_fixed_rate = swap.fixedRate()
    fixed_rate_to_use = embedded_fixed_rate if embedded_fixed_rate > 0 else swap.fairRate()

    bumped_up_ql_curve = ql.ZeroSpreadedTermStructure(curve_handle, ql.QuoteHandle(ql.SimpleQuote(shift)))
    bumped_up_curve_handle = ql.YieldTermStructureHandle(bumped_up_ql_curve)
    bumped_up_swap = build_ql_irswap(
        curve=curve,
        curve_handle=bumped_up_curve_handle,
        effective_date=ql_date_to_pydate(swap.startDate()),
        maturity_date=ql_date_to_pydate(swap.maturityDate()),
        fixed_rate=fixed_rate_to_use * 100,
        notional=swap.nominal() if swap.fixedLegBPS() > 0 else -swap.nominal(),
    )

    bumped_down_ql_curve = ql.ZeroSpreadedTermStructure(curve_handle, ql.QuoteHandle(ql.SimpleQuote(-shift)))
    bumped_down_curve_handle = ql.YieldTermStructureHandle(bumped_down_ql_curve)
    bumped_down_swap = build_ql_irswap(
        curve=curve,
        curve_handle=bumped_down_curve_handle,
        effective_date=ql_date_to_pydate(swap.startDate()),
        maturity_date=ql_date_to_pydate(swap.maturityDate()),
        fixed_rate=fixed_rate_to_use * 100,
        notional=swap.nominal() if swap.fixedLegBPS() > 0 else -swap.nominal(),
    )

    return (calc_npv(swap=bumped_down_swap, curve_handle=bumped_down_curve_handle) - calc_npv(swap=bumped_up_swap, curve_handle=bumped_up_curve_handle)) / 2


def calc_gamma(swap: ql.VanillaSwap, curve_handle: ql.YieldTermStructureHandle, curve: str, shift: Optional[float] = 1e-4):
    ql.Settings.instance().evaluationDate = curve_handle.referenceDate()
    swap.setPricingEngine(ql.DiscountingSwapEngine(curve_handle))
    npv_0 = calc_npv(swap, curve_handle)

    bumped_up_ql_curve = ql.ZeroSpreadedTermStructure(curve_handle, ql.QuoteHandle(ql.SimpleQuote(shift)))
    bumped_up_curve_handle = ql.YieldTermStructureHandle(bumped_up_ql_curve)
    bumped_up_swap = build_ql_irswap(
        curve=curve,
        curve_handle=bumped_up_curve_handle,
        effective_date=ql_date_to_pydate(swap.startDate()),
        maturity_date=ql_date_to_pydate(swap.maturityDate()),
        fixed_rate=swap.fixedRate() * 100,
        notional=swap.nominal() if swap.fixedLegBPS() > 0 else -swap.nominal(),
    )
    npv_up = calc_npv(swap=bumped_up_swap, curve_handle=bumped_up_curve_handle)

    bumped_down_ql_curve = ql.ZeroSpreadedTermStructure(curve_handle, ql.QuoteHandle(ql.SimpleQuote(-shift)))
    bumped_down_curve_handle = ql.YieldTermStructureHandle(bumped_down_ql_curve)
    bumped_down_swap = build_ql_irswap(
        curve=curve,
        curve_handle=bumped_down_curve_handle,
        effective_date=ql_date_to_pydate(swap.startDate()),
        maturity_date=ql_date_to_pydate(swap.maturityDate()),
        fixed_rate=swap.fixedRate() * 100,
        notional=swap.nominal() if swap.fixedLegBPS() > 0 else -swap.nominal(),
    )
    npv_down = calc_npv(swap=bumped_down_swap, curve_handle=bumped_down_curve_handle)

    return ((npv_up - 2 * npv_0 + npv_down) / (shift**2)) / swap.nominal()


def calc_dollar_carry(swap: ql.VanillaSwap, curve_handle: ql.YieldTermStructureHandle, horizon: Optional[ql.Period] = ql.Period("1D")):
    ref_date = curve_handle.referenceDate()
    ql.Settings.instance().evaluationDate = ref_date
    swap.setPricingEngine(ql.DiscountingSwapEngine(curve_handle))

    npv0 = swap.NPV()
    ql.Settings.instance().evaluationDate = curve_handle.referenceDate() + horizon
    dollar_carry = swap.NPV() - npv0
    ql.Settings.instance().evaluationDate = ref_date

    return dollar_carry


def calc_carry_bps_running(swap: ql.VanillaSwap, curve_handle: ql.YieldTermStructureHandle, curve: str, horizon: Optional[ql.Period] = ql.Period("1D")) -> float:
    ql.Settings.instance().evaluationDate = curve_handle.referenceDate()
    swap.setPricingEngine(ql.DiscountingSwapEngine(curve_handle))
    if swap.startDate() > curve_handle.calendar().advance(curve_handle.referenceDate(), ql.Period(QUANTLIB_CURVE_DEFINITIONS[curve]["SettlementDays"], ql.Days)):
        return 0.0

    fwd_rolled_swap = build_ql_irswap(
        curve=curve,
        curve_handle=curve_handle,
        effective_date=ql_date_to_pydate(swap.startDate() + horizon),
        maturity_date=ql_date_to_pydate(swap.maturityDate()),
    )
    return (fwd_rolled_swap.fixedRate() - swap.fixedRate()) * 10_000


def calc_roll_bps_running(swap: ql.VanillaSwap, curve_handle: ql.YieldTermStructureHandle, curve: str, horizon: Optional[ql.Period] = ql.Period("1D")) -> float:
    # TODO handle 2 cases
    # rolldown -> mat - horizon >= effective date and mat - horizon < effective date
    rolled_swap = build_ql_irswap(
        curve=curve,
        curve_handle=curve_handle,
        effective_date=ql_date_to_pydate(swap.startDate()),
        maturity_date=ql_date_to_pydate(swap.maturityDate() - horizon),
    )
    return (swap.fixedRate() - rolled_swap.fixedRate()) * 10_000


def calc_carry_and_roll_bps_running(
    swap: ql.VanillaSwap, curve_handle: ql.YieldTermStructureHandle, curve: str, horizon: Optional[ql.Period] = ql.Period("1D")
) -> float:
    ql.Settings.instance().evaluationDate = curve_handle.referenceDate()

    return calc_carry_bps_running(swap=swap, curve_handle=curve_handle, curve=curve, horizon=horizon) + calc_roll_bps_running(
        swap=swap, curve_handle=curve_handle, curve=curve, horizon=horizon
    )


def calc_notional(swap: ql.VanillaSwap, curve_handle: ql.YieldTermStructureHandle):
    ql.Settings.instance().evaluationDate = curve_handle.referenceDate()
    swap.setPricingEngine(ql.DiscountingSwapEngine(curve_handle))
    return swap.nominal()

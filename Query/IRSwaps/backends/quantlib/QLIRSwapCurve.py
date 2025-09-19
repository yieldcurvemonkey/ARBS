import datetime
from dataclasses import dataclass
from typing import Union, Any

import QuantLib as ql

import Query.IRSwaps.backends.quantlib.ql_pricer as ql_irswaps_pricer
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date, ql_date_to_pydate


@dataclass
class QLIRSwapCurve(_IRSwapGenericCurve):
    _ql_curve_id: str
    _ql_curve_handle: ql.YieldTermStructureHandle
    _ql_curve_index: ql.SwapIndex
    _meta_data: Any

    def __init__(self, ql_curve_id: str, ql_curve_handle: ql.YieldTermStructureHandle, ql_curve_index: ql.SwapIndex, meta_data: Any):
        self._ql_curve_id = ql_curve_id
        self._ql_curve_handle = ql_curve_handle
        self._ql_curve_index = ql_curve_index
        self._meta_data = meta_data 

    def id(self):
        return self._ql_curve_id

    def reference_date(self) -> datetime:
        return ql_date_to_pydate(self._ql_curve_handle.referenceDate())

    def calendar(self) -> ql.Calendar:
        return self._ql_curve_handle.calendar()

    def calendar_advance(self, dt1: Union[datetime.date, ql.Date], dt2: Union[ql.Period, str]):
        ql_cal = self.calendar()
        return ql_cal.advance(datetime_to_ql_date(dt1), ql.Period(dt2) if type(dt2) == str else dt2, QUANTLIB_CURVE_DEFINITIONS[self._ql_curve_id])

    def handle(self) -> ql.YieldTermStructureHandle:
        return self._ql_curve_handle

    def index(self) -> ql.SwapIndex:
        return self._ql_curve_index

    def meta(self):
        return self._meta_data    

    def effective_date(self, irswap: ql.VanillaSwap):
        return ql_date_to_pydate(irswap.startDate())

    def maturity_date(self, irswap: ql.VanillaSwap):
        return ql_date_to_pydate(irswap.maturityDate())

    def fixed_rate(self, irswap: ql.VanillaSwap):
        return float(irswap.fixedRate())

    def notional(self, irswap: ql.VanillaSwap):
        return ql_irswaps_pricer.calc_notional(swap=irswap, curve_handle=self._ql_curve_handle)

    def fair_rate(self, irswap: ql.VanillaSwap):
        return ql_irswaps_pricer.calc_fair_rate(swap=irswap, curve_handle=self._ql_curve_handle)

    def npv(self, irswap: ql.VanillaSwap):
        return ql_irswaps_pricer.calc_npv(swap=irswap, curve_handle=self._ql_curve_handle)

    def pv01(self, irswap: ql.VanillaSwap):
        return ql_irswaps_pricer.calc_pv01(swap=irswap, curve_handle=self._ql_curve_handle)

    def dv01(self, irswap: ql.VanillaSwap):
        return ql_irswaps_pricer.calc_dv01(swap=irswap, curve_handle=self._ql_curve_handle)

    def gamma(self, irswap: ql.VanillaSwap):
        return ql_irswaps_pricer.calc_gamma(swap=irswap, curve_handle=self._ql_curve_handle, curve=self._ql_curve_id)

    def dollar_carry(self, irswap: ql.VanillaSwap, horizon: str):
        return ql_irswaps_pricer.calc_dollar_carry(swap=irswap, curve_handle=self._ql_curve_handle, horizon=ql.Period(horizon))

    def carry_bps_running(self, irswap: ql.VanillaSwap, horizon: str):
        return ql_irswaps_pricer.calc_carry_bps_running(swap=irswap, curve_handle=self._ql_curve_handle, horizon=ql.Period(horizon))

    def roll_bps_running(self, irswap: ql.VanillaSwap, horizon: str):
        return ql_irswaps_pricer.calc_roll_bps_running(swap=irswap, curve_handle=self._ql_curve_handle, horizon=ql.Period(horizon))

    def carry_and_roll_bps_running(self, irswap: ql.VanillaSwap, horizon: str):
        return ql_irswaps_pricer.calc_carry_and_roll_bps_running(swap=irswap, curve_handle=self._ql_curve_handle, horizon=ql.Period(horizon))

    def build_irswap(self, fwd, tenor=None, effective_date=None, maturity_date=None, fixed_rate=-0, notional=None, bpv=None):
        return ql_irswaps_pricer.build_ql_irswap(
            curve=self._ql_curve_id,
            curve_handle=self._ql_curve_handle,
            swap_index=self._ql_curve_index,
            fwd=ql.Period(fwd),
            tenor=ql.Period(tenor),
            effective_date=effective_date,
            maturity_date=maturity_date,
            fixed_rate=fixed_rate,
            notional=notional,
            bpv=bpv,
        )

    def build_stirf(self, fwd = None, tenor = None, effective_date = None, maturity_date = None, fixed_rate = -0, notional = None, bpv = None, is_ser = False):
        raise NotImplementedError("'build_stirf' not implemented for QuantLib backend")
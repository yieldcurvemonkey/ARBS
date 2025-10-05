import datetime
import pandas as pd
from dataclasses import dataclass
from typing import Union, Any, Optional

import rateslib as rl

from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS


@dataclass
class RLIRSwapCurve(_IRSwapGenericCurve):
    _rl_curve_id: str
    _rl_curve_handle: rl.Curve
    # _rl_curve_solver_handle: rl.Solver
    _meta_data: Any

    def __init__(self, rl_curve_id: str, rl_curve_handle: rl.Curve, fixings: pd.Series, meta_data: Any):
        self._rl_curve_id = rl_curve_id
        self._rl_curve_handle = rl_curve_handle
        # self._rl_curve_solver_handle = rl_curve_solver_handle
        self._fixings = fixings
        self._meta_data = meta_data

    def id(self):
        return self._rl_curve_id

    def reference_date(self) -> datetime:
        return next(iter(self._rl_curve_handle.nodes.nodes.keys()))

    def calendar(self) -> rl.Cal:
        return self._rl_curve_handle.meta.calendar

    def calendar_advance(self, dt1: Union[datetime.date, rl.dt], dt2: str):
        return rl.add_tenor(
            datetime.datetime(dt1.year, dt1.month, dt1.day),
            tenor=dt2,
            modifier=RATESLIB_CURVE_DEFINITIONS[self._rl_curve_id]["BusinessConvention"],
            calendar=RATESLIB_CURVE_DEFINITIONS[self._rl_curve_id]["Calendar"],
        )

    def handle(self) -> rl.Curve:
        return self._rl_curve_handle

    def index(self) -> pd.Series:
        return self._fixings

    def meta(self):
        return self._meta_data

    def effective_date(self, irswap: rl.IRS):
        return min(irswap.leg1.cashflows()["Acc Start"])

    def maturity_date(self, irswap: rl.IRS):
        return max(irswap.leg1.cashflows()["Acc End"])

    def fixed_rate(self, irswap: rl.IRS):
        return float(irswap.fixed_rate)

    def notional(self, irswap: rl.IRS):
        return float(irswap.cashflows(curves=self._rl_curve_handle)["Notional"].iloc[-1])

    def fair_rate(self, irswap: rl.IRS):
        return irswap.rate(curves=self._rl_curve_handle).real / 100

    def npv(self, irswap: rl.IRS):
        return (
            rl.IRS(
                effective=self.effective_date(irswap),
                termination=self.maturity_date(irswap),
                fixed_rate=self.fair_rate(irswap) * 100,
                curves=self._rl_curve_handle,
                spec=RATESLIB_CURVE_DEFINITIONS[self._rl_curve_id]["ReferenceRate"],
                notional=self.notional(irswap),
            )
            .npv(curves=self._rl_curve_handle)
            .real
        )

    def pv01(self, irswap: rl.IRS):
        return irswap.analytic_delta(curve=self._rl_curve_handle).real

    def dv01(self, irswap: rl.IRS):
        # return irswap.delta(solver=self._rl_curve_solver_handle)
        raise NotImplementedError("rateslib not implemented")

    def gamma(self, irswap: rl.IRS):
        # return irswap.gamma(solver=self._rl_curve_solver_handle)
        raise NotImplementedError("rateslib not implemented")

    def dollar_carry(self, irswap: rl.IRS, horizon: str):
        raise NotImplementedError("rateslib not implemented")

    def carry_bps_running(self, irswap: rl.IRS, horizon: str):
        raise NotImplementedError("rateslib not implemented")

    def roll_bps_running(self, irswap: rl.IRS, horizon: str):
        return (self.fair_rate(irswap) * 100 - float(irswap.rate(curves=self._rl_curve_handle.roll(horizon)))) * 100

    def carry_and_roll_bps_running(self, irswap: rl.IRS, horizon: str):
        raise NotImplementedError("rateslib not implemented")

    def build_irswap(self, fwd=None, tenor=None, effective_date=None, maturity_date=None, fixed_rate=-0, notional=None, bpv=None):
        if fwd:
            if fwd == "0D":
                rl_effective = self.calendar_advance(self.reference_date(), f"{RATESLIB_CURVE_DEFINITIONS[self._rl_curve_id]["SettlementDays"]}b")
            else:
                rl_effective = self.calendar_advance(self.reference_date(), fwd)
        else:
            rl_effective = effective_date

        rl_effective = rl.dt(rl_effective.year, rl_effective.month, rl_effective.day)
        if type(maturity_date) == datetime.date:
            maturity_date = rl.dt(maturity_date.year, maturity_date.month, maturity_date.day)

        if bpv and not notional:
            unit_delta = rl.IRS(
                effective=rl_effective,
                termination=tenor or maturity_date,
                spec=RATESLIB_CURVE_DEFINITIONS[self._rl_curve_id]["ReferenceRate"],
                curves=self._rl_curve_handle,
                notional=1,
            ).analytic_delta(self._rl_curve_handle)
            notional = bpv / unit_delta

        if not bpv and not notional:
            notional = 1

        return rl.IRS(
            effective=rl_effective,
            termination=tenor or maturity_date,
            fixed_rate=fixed_rate,
            curves=self._rl_curve_handle,
            spec=RATESLIB_CURVE_DEFINITIONS[self._rl_curve_id]["ReferenceRate"],
            notional=notional,
        )

    def build_pricable(self, /, **kwargs: Any) -> rl.IRS:
        fwd: Optional[str] = kwargs.get("fwd")
        tenor: Optional[str] = kwargs.get("tenor")
        eff: Optional[datetime.date] = kwargs.get("effective_date")
        mat: Optional[datetime.date] = kwargs.get("maturity_date")
        k: float = float(kwargs.get("fixed_rate", -0.00))
        notional = kwargs.get("notional")
        bpv = kwargs.get("bpv")

        return self.build_irswap(fwd=fwd, tenor=tenor, effective_date=eff, maturity_date=mat, fixed_rate=k, notional=notional, bpv=bpv)

    def resolve_pricable(self, irswap: rl.IRS):
        return self.build_irswap(
            effective_date=self.effective_date(irswap),
            maturity_date=self.maturity_date(irswap),
            fixed_rate=self.fixed_rate(irswap),
            notional=self.notional(irswap),
        )

    def build_stirf(self, fwd=None, tenor=None, effective_date=None, maturity_date=None, fixed_rate=-0, notional=None, bpv=None, is_ser: Optional[bool] = False):
        if bpv and not notional:
            unit_delta = rl.IRS(
                effective=fwd or effective_date,
                termination=tenor or maturity_date,
                spec=RATESLIB_CURVE_DEFINITIONS[self._rl_curve_id]["ReferenceRate"],
                curves=self._rl_curve_handle,
                notional=1,
            ).analytic_delta(self._rl_curve_handle)
            notional = bpv / unit_delta

        if not bpv and not notional:
            notional = 1_000_000

        return rl.STIRFuture(
            effective=fwd or effective_date,
            termination=tenor or maturity_date,
            price=(100 - fixed_rate),
            curves=self._rl_curve_handle,
            spec=RATESLIB_CURVE_DEFINITIONS[self._rl_curve_id]["ReferenceRate2"] if not is_ser else RATESLIB_CURVE_DEFINITIONS[self._rl_curve_id]["ReferenceRate3"],
            contracts=int(notional / 1_000_000),
        )

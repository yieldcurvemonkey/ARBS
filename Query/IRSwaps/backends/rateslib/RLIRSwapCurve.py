import datetime
import pandas as pd
from dataclasses import dataclass
from typing import Union, Any, Optional

import rateslib as rl

from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
from utils.rl_compat import rate_fixings_kwargs


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

    def _curve_definition_id(self) -> str:
        if isinstance(self._meta_data, dict):
            reference_curve_name = self._meta_data.get("reference_curve_name")
            if isinstance(reference_curve_name, str) and reference_curve_name:
                return reference_curve_name
        return self._rl_curve_id

    def _curve_definition(self) -> dict[str, Any]:
        return RATESLIB_CURVE_DEFINITIONS[self._curve_definition_id()]

    def reference_date(self) -> datetime:
        return next(iter(self._rl_curve_handle.nodes.nodes.keys()))

    def calendar(self) -> rl.Cal:
        return self._rl_curve_handle.meta.calendar

    def calendar_advance(self, dt1: Union[datetime.date, rl.dt], dt2: str):
        curve_def = self._curve_definition()
        return rl.add_tenor(
            datetime.datetime(dt1.year, dt1.month, dt1.day),
            tenor=dt2,
            modifier=curve_def["BusinessConvention"],
            calendar=curve_def["Calendar"],
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
        # Wrapper contract is DECIMAL (matches fair_rate here and
        # QLIRSwapCurve.fixed_rate); rl.IRS itself carries percent.
        return float(irswap.fixed_rate) / 100.0

    def notional(self, irswap: rl.IRS):
        return irswap.kwargs.leg1["notional"]

    def fair_rate(self, irswap: rl.IRS):
        return irswap.rate(curves=self._rl_curve_handle).real / 100

    def npv(self, irswap: rl.IRS):
        curve_def = self._curve_definition()
        return (
            rl.IRS(
                effective=self.effective_date(irswap),
                termination=self.maturity_date(irswap),
                fixed_rate=irswap.fixed_rate,  # already percent, rateslib's own unit
                curves=self._rl_curve_handle,
                spec=curve_def["ReferenceRate"],
                notional=self.notional(irswap),
                **rate_fixings_kwargs(self._fixings),
            )
            .npv(curves=self._rl_curve_handle)
            .real
        )

    def pv01(self, irswap: rl.IRS):
        return irswap.analytic_delta(curves=self._rl_curve_handle).real

    def dv01(self, irswap: rl.IRS):
        # A true DV01 is a full re-solve of the calibrating instruments, which
        # needs the rl.Solver this backend does not carry. PV01 (analytic_delta)
        # is available and is what every shipped consumer uses.
        raise NotImplementedError(
            "IRSwapValue.DV01 is not available on the rateslib backend (needs a "
            "calibrated rl.Solver, which this curve does not carry). Use "
            "IRSwapValue.PV01, or a QuantLib-backed source."
        )

    def gamma(self, irswap: rl.IRS):
        raise NotImplementedError(
            "IRSwapValue.GAMMA_01 is not available on the rateslib backend (needs "
            "a calibrated rl.Solver). Use a QuantLib-backed source."
        )

    def dollar_carry(self, irswap: rl.IRS, horizon: str):
        raise NotImplementedError(
            "dollar_carry is not implemented on the rateslib backend; use "
            "IRSwapValue.CARRY_BPS_RUNNING (which is) or a QuantLib-backed source."
        )

    def carry_bps_running(self, irswap: rl.IRS, horizon: str):
        curve_def = self._curve_definition()
        if self.effective_date(irswap=irswap) > self.calendar_advance(self.reference_date(), f"{curve_def['SettlementDays']}b"):
            return 0
        fwd_irs = self.build_irswap(fwd=horizon, maturity_date=self.maturity_date(irswap))
        return (self.fair_rate(fwd_irs) - self.fair_rate(irswap)) * 10_000

    def roll_bps_running(self, irswap: rl.IRS, horizon: str):
        rolled_irs = self.build_irswap(effective_date=self.effective_date(irswap), maturity_date=self.calendar_advance(self.maturity_date(irswap), f"-{horizon}"))
        return (self.fair_rate(irswap) - self.fair_rate(rolled_irs)) * 10_000
        # return (self.fair_rate(irswap) * 100 - float(irswap.rate(curves=self._rl_curve_handle.roll(horizon)))) * 100

    def carry_and_roll_bps_running(self, irswap: rl.IRS, horizon: str):
        # Keep parity with quantlib backend: running carry + running rolldown.
        return self.carry_bps_running(irswap=irswap, horizon=horizon) + self.roll_bps_running(
            irswap=irswap,
            horizon=horizon,
        )

    def nodes(self):
        rl_nodes: dict[pd.Timestamp, float] = self.handle().nodes._nodes
        return {ts.date(): df for ts, df in rl_nodes.items()}

    def build_irswap(
        self,
        fwd=None,
        tenor=None,
        effective_date=None,
        maturity_date=None,
        fixed_rate=-0,
        notional=None,
        bpv=None,
    ):
        curve_def = self._curve_definition()
        if fwd:
            if fwd == "0D":
                rl_effective = self.calendar_advance(
                    self.reference_date(),
                    f"{curve_def['SettlementDays']}b",
                )
            else:
                rl_effective = self.calendar_advance(self.reference_date(), fwd)
        else:
            rl_effective = effective_date

        if bpv and not notional:
            unit_delta = rl.IRS(
                effective=rl.dt(rl_effective.year, rl_effective.month, rl_effective.day),
                termination=tenor or rl.dt(maturity_date.year, maturity_date.month, maturity_date.day),
                spec=curve_def["ReferenceRate"],
                curves=self._rl_curve_handle,
                notional=1,
                **rate_fixings_kwargs(self._fixings),
            ).analytic_delta(curves=self._rl_curve_handle)
            notional = bpv / unit_delta

        if not bpv and not notional:
            notional = 1_000_000

        if fixed_rate == -0:
            fixed_rate = self.fair_rate(
                irswap=rl.IRS(
                    effective=rl.dt(rl_effective.year, rl_effective.month, rl_effective.day),
                    termination=tenor or rl.dt(maturity_date.year, maturity_date.month, maturity_date.day),
                    spec=curve_def["ReferenceRate"],
                    curves=self._rl_curve_handle,
                    notional=1,
                    **rate_fixings_kwargs(self._fixings),
                )
            )

        return rl.IRS(
            effective=rl.dt(rl_effective.year, rl_effective.month, rl_effective.day),
            termination=tenor or rl.dt(maturity_date.year, maturity_date.month, maturity_date.day),
            spec=curve_def["ReferenceRate"],
            curves=self._rl_curve_handle,
            # `fixed_rate` arrives as a DECIMAL (that is this wrapper's contract,
            # and what fair_rate/fixed_rate return); rl.IRS wants PERCENT. The
            # conversion was missing, so the returned swap was struck 100x too
            # low in rateslib's own units -- a par 5Y came back as 0.0414%
            # instead of 4.1448%, worth ~$184k per $1mm the moment anyone called
            # .npv()/.cashflows()/.delta() on it directly or handed it to a
            # Solver. Only this wrapper's own npv() compensated, so no shipped
            # number was wrong, but every object handed out was.
            fixed_rate=float(fixed_rate) * 100.0,
            notional=notional,
            **rate_fixings_kwargs(self._fixings),
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

    def resolve_pricable(self, irswap: rl.IRS, risk_weight: Optional[float] = None):
        # Mirror the QuantLib backend's resolve_pricable: only invert the
        # notional sign when the caller's direction (risk_weight, fallback
        # to -pv01) is negative. The previous implementation unconditionally
        # multiplied by -1, which flipped the sign of every NPV reported by
        # mark_to_market and on_unwind for IRSwapQuery positions.
        notional_real = irswap.kwargs.leg1["notional"]
        try:
            direction = risk_weight if risk_weight is not None else (
                self.pv01(irswap) * -1
            )
        except Exception:
            direction = risk_weight if risk_weight is not None else 1
        try:
            sign = -1.0 if float(direction) < 0 else 1.0
        except Exception:
            sign = 1.0
        return self.build_irswap(
            effective_date=self.effective_date(irswap),
            maturity_date=self.maturity_date(irswap),
            fixed_rate=self.fixed_rate(irswap),
            notional=notional_real * sign,
        )

    def build_stirf(self, fwd=None, tenor=None, effective_date=None, maturity_date=None, fixed_rate=-0, notional=None, bpv=None, is_ser: Optional[bool] = False, fixings=None):
        """Build an rl.STIRFuture on this curve from explicit dates.

        ``fixings`` (optional) supplies published RFR fixings so a contract whose
        accrual period STARTS BEFORE the curve's reference date can still be
        priced — without them rateslib raises "RFRs could not be calculated".
        This is the norm for the front monthly contract (ZQ/SR1), whose calendar
        month is always partly in the past. Mirrors
        ``RLSTIRFuturePricer.build_for_solver``'s fixings handling: mask to the
        spec calendar's business days, then pass them under whichever kwarg name
        the installed rateslib uses (see ``utils.rl_compat``).
        """
        curve_def = self._curve_definition()
        if bpv and not notional:
            unit_delta = rl.IRS(
                effective=fwd or effective_date,
                termination=tenor or maturity_date,
                spec=curve_def["ReferenceRate"],
                curves=self._rl_curve_handle,
                notional=1,
            ).analytic_delta(curves=self._rl_curve_handle)
            notional = bpv / unit_delta

        if not bpv and not notional:
            notional = 1_000_000

        spec = curve_def["ReferenceRate2"] if not is_ser else curve_def["ReferenceRate3"]
        kwargs = dict(
            effective=fwd or effective_date,
            termination=tenor or maturity_date,
            price=(100 - fixed_rate),
            curves=self._rl_curve_handle,
            spec=spec,
            contracts=int(notional / 1_000_000),
        )
        if fixings is not None and isinstance(fixings, pd.Series) and not fixings.empty:
            cal = rl.get_calendar(rl.defaults.spec[spec].get("calendar", "nyc"))
            mask = pd.Series(
                [cal.is_bus_day(d.to_pydatetime() if hasattr(d, "to_pydatetime") else d)
                 for d in fixings.index],
                index=fixings.index,
            )
            masked = fixings[mask]
            if not masked.empty:
                return rl.STIRFuture(**kwargs, **rate_fixings_kwargs(masked))
        return rl.STIRFuture(**kwargs)

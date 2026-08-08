import datetime
import pandas as pd
from dataclasses import dataclass
from typing import Union, Any, Optional

import rateslib as rl

from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
from utils.rl_compat import rate_fixings_kwargs

#: Where ``build_irswap`` parks the par rate it computed, as
#: ``(wrapper, curve_handle, decimal_rate)``. Read back only by
#: :meth:`RLIRSwapCurve.fair_rate`, and only when BOTH the wrapper and the curve
#: handle are the same objects - so a swap re-priced against a different curve,
#: or handed to a different wrapper, recomputes.
#:
#: Why this exists. ``build_irswap`` defaults to striking at par, which it did by
#: constructing a THROWAWAY unit-notional swap and rating it; the caller then
#: rated the returned swap again to report it. Every par rate in a timeseries was
#: therefore computed twice, each costing a full ``rl.IRS`` construction (1.40 ms)
#: plus ``IRS.rate()`` (4.34 ms) - measured 2026-08-08 on a warmed USD 10Y.
#:
#: The rate is now computed ONCE, on the instrument that is actually returned.
#: That is not merely close to the old number, it is the same one: measured on
#: the same curve, ``rate()`` is bit-identical across notional 1 vs 1,000,000 and
#: across struck vs unstruck, and ``fixed_rate`` is set afterwards - which
#: ``rate()`` does not read.
_PAR_RATE_ATTR = "_arbs_par_rate"


# --------------------------------------------------------------------------- #
#     opt-in: skip the fixings machinery for instruments that consume none     #
# --------------------------------------------------------------------------- #
#
# A swap whose first accrual period starts on or after the curve's reference
# date has no elapsed observation, so no published fixing enters its rate. It
# still costs one, because rateslib's RFR path - taken whenever a fixings series
# is attached - materialises a business-date Series over EVERY accrual period
# before discovering that none of them is in scope. Measured 2026-08-08 on a
# warmed USD 10Y, one ``IRS.rate()``:
#
#     with a 5,445-row fixings series   4.341 ms
#     with no fixings series            0.188 ms       23x
#
# It is NOT bit-identical, which is why this is off by default. The two routes
# are the same quantity computed two ways - daily compounding of curve discount
# factors versus the endpoint ratio the compounding telescopes to - and they
# disagree in the last unit in the last place. Measured across par tenors on the
# same curve:
#
#     10Y, 30Y   identical
#     2Y         4.154360000019888  ->  4.154360000019887
#     5Y         4.120890000061977  ->  4.1208900000619755
#     40Y        4.275369857811132  ->  4.275369857811131
#     5Yx5Y      4.3758958166657465 ->  4.375895816665747
#
# i.e. ~2e-13 bp. Immaterial to any decision, and still a changed number, so a
# caller has to ask for it: set ``ARBS_RL_OMIT_UNUSED_FIXINGS=1`` or call
# :func:`set_omit_unused_fixings`. Seasoned, IMM- and central-bank-dated legs
# that start BEFORE the reference date keep the full series either way - for
# those the fixings are not an optimisation, they are the answer.
_OMIT_UNUSED_FIXINGS: Optional[bool] = None


def set_omit_unused_fixings(enabled: Optional[bool]) -> None:
    """Turn the fixings shortcut on/off for this process (``None`` = re-read env)."""
    global _OMIT_UNUSED_FIXINGS
    _OMIT_UNUSED_FIXINGS = None if enabled is None else bool(enabled)


def omit_unused_fixings() -> bool:
    """Whether the shortcut is active. Default OFF."""
    global _OMIT_UNUSED_FIXINGS
    if _OMIT_UNUSED_FIXINGS is None:
        import os

        raw = str(os.getenv("ARBS_RL_OMIT_UNUSED_FIXINGS", "")).strip().lower()
        _OMIT_UNUSED_FIXINGS = raw in {"1", "true", "yes", "on"}
    return _OMIT_UNUSED_FIXINGS


def _as_date(value: Any) -> Optional[datetime.date]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    to_pydatetime = getattr(value, "to_pydatetime", None)
    if to_pydatetime is not None:
        return to_pydatetime().date()
    return None


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
        # A swap this wrapper struck AT PAR already had its par rate computed,
        # on this same object against this same curve, inside build_irswap. The
        # cached value is therefore that call's result verbatim, not an
        # approximation of it - see _PAR_RATE_ATTR.
        cached = getattr(irswap, _PAR_RATE_ATTR, None)
        if cached is not None:
            owner, handle, value = cached
            if owner is self and handle is self._rl_curve_handle:
                return value
        return irswap.rate(curves=self._rl_curve_handle).real / 100

    def _fixings_kwargs(self, *, effective: Any = None) -> dict[str, Any]:
        """Fixings constructor kwargs for an instrument starting at ``effective``.

        Always the full series unless the opt-in shortcut is enabled AND the
        instrument provably consumes none of it - see ``_OMIT_UNUSED_FIXINGS``.
        An ``effective`` this cannot resolve to a date is treated as "might be
        seasoned", so an unrecognised date type keeps the fixings rather than
        quietly dropping them.
        """
        if omit_unused_fixings():
            start = _as_date(effective)
            reference = _as_date(self.reference_date())
            if start is not None and reference is not None and start >= reference:
                return {}

        # One resolution per wrapper. rate_fixings_kwargs is content-addressed -
        # it cleans, sorts and hashes the series to derive rateslib's identifier -
        # which costs 0.235 ms on a 5,445-row history, and a curve/fly query
        # builds a leg per component on top of a leg per query. Invalidated by
        # IDENTITY, so reassigning _fixings after construction re-resolves.
        cached = self.__dict__.get("_fixings_kwargs_cache")
        if cached is not None and cached[0] is self._fixings:
            return cached[1]
        resolved = rate_fixings_kwargs(self._fixings)
        self.__dict__["_fixings_kwargs_cache"] = (self._fixings, resolved)
        return resolved

    def npv(self, irswap: rl.IRS):
        curve_def = self._curve_definition()
        effective = self.effective_date(irswap)
        return (
            rl.IRS(
                effective=effective,
                termination=self.maturity_date(irswap),
                fixed_rate=irswap.fixed_rate,  # already percent, rateslib's own unit
                curves=self._rl_curve_handle,
                spec=curve_def["ReferenceRate"],
                notional=self.notional(irswap),
                **self._fixings_kwargs(effective=effective),
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
                **self._fixings_kwargs(effective=rl_effective),
            ).analytic_delta(curves=self._rl_curve_handle)
            notional = bpv / unit_delta

        if not bpv and not notional:
            notional = 1_000_000

        termination = tenor or rl.dt(maturity_date.year, maturity_date.month, maturity_date.day)
        strike_at_par = fixed_rate == -0

        irswap = rl.IRS(
            effective=rl.dt(rl_effective.year, rl_effective.month, rl_effective.day),
            termination=termination,
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
            #
            # Left unset when this call is the one choosing the strike: the par
            # rate is then read off THIS instrument (rl.IRS.rate() does not
            # consult fixed_rate) and assigned below, instead of off a throwaway
            # unit-notional copy that was built and rated purely to be discarded.
            **({} if strike_at_par else {"fixed_rate": float(fixed_rate) * 100.0}),
            notional=notional,
            **self._fixings_kwargs(effective=rl_effective),
        )

        if strike_at_par:
            par = irswap.rate(curves=self._rl_curve_handle).real / 100
            irswap.fixed_rate = float(par) * 100.0
            setattr(irswap, _PAR_RATE_ATTR, (self, self._rl_curve_handle, par))

        return irswap

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
        # Mirror the QuantLib backend's resolve_pricable: |notional| first, then
        # sign from the caller's direction (risk_weight, fallback to -pv01).
        # Unlike QuantLib, rateslib notionals arrive ALREADY SIGNED (a receiver
        # built through the bpv path carries notional < 0), so signing the raw
        # notional double-applies direction: a receiver (-N, rw=-1) resolved to
        # (+N) - the direction-blind seam kink-fade v2 §6 reported, verified
        # live 2026-08-08 (bpv=+100k and bpv=-100k priced as the identical
        # all-payer package through QueryDrivenBacktest). abs() restores the
        # QL semantics this method claims to mirror.
        notional_real = abs(irswap.kwargs.leg1["notional"])
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

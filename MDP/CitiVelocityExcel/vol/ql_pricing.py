r"""Price a Citi swaption cube with QuantLib's own swaption machinery.

:mod:`MDP.CitiVelocityExcel.vol.ql_cube` builds the surface -
``ql.SwaptionVolatilityMatrix`` -> ``ql.InterpolatedSwaptionVolatilityCube`` - and
proves its node ordering. It stops there: it never prices anything. What used to
stand in for a QuantLib price was
``CitiVeloPricer.ql_option_premium``, which took the QuantLib cube's *volatility*
and then borrowed the **rateslib** cube's forward, annuity and time to expiry and
pushed all three through ``Query.Base.bachelier``. No ``ql.Swaption``, no
``ql.BachelierSwaptionEngine``, and - because it divided an already-decimal
forward and strike by 100 while leaving the vol in decimals - every off-the-money
premium it returned was wrong by a factor of 100 in moneyness. At the money it
was right, which is why it survived.

This module is the real path: a QuantLib swaption on a QuantLib underlying,
discounted off the QuantLib curve, valued by ``ql.BachelierSwaptionEngine``.

The underlying is the option's own swap
-------------------------------------
``ql.MakeOIS`` normally resolves its start as ``spot + forward_period`` adjusted
FOLLOWING. That is right for a curve instrument and wrong for a swaption, whose
underlying starts a settlement lag after the option **expires**. So the effective
date is derived from the expiry date instead::

    expiry    = cube.optionDateFromTenor(Period(expiry_tenor))   # the vol surface's own
    effective = calendar.advance(expiry, spot_lag business days)

which is also, deliberately, the rule
:class:`~MDP.CitiVelocityExcel.vol.rl_cube.CitiVeloNormalVolCube` uses. When the
two backends still disagree on a premium after that, the disagreement is an
annuity, a day count or a discounting difference - not a schedule one. Every
other convention (payment lag, payment frequency, fixed-leg day count,
end-of-month) is read from the same :class:`CurveConvention` row the curve
bootstrap used, through the same private helpers, so a swaption cannot be built
on conventions the curve was not.

Which volatility the engine sees
--------------------------------
Two modes, because they answer different questions and the difference between
them is itself a diagnostic:

``vol_source='cube'`` (default)
    The engine is handed the cube's own
    ``ql.SwaptionVolatilityStructureHandle`` and QuantLib does the whole lookup -
    option time, swap length, strike, its own ``atmStrike``, its own smile
    section. This is the full QuantLib stack and it is what
    ``source='CITIVELO-QL'`` prices with.
``vol_source='exact'``
    The engine is handed a ``ql.ConstantSwaptionVolatility`` at the volatility
    this package reads for that node **by offset from the underlying's own par
    rate**. Annuity, schedule and discounting are still QuantLib's; only the vol
    lookup is ours.

They differ by exactly the gap between QuantLib's ``atmStrike`` (built from the
``OvernightIndexedSwapIndex``) and the forward of the swaption's actual
underlying. That gap slides the smile along the strike axis, so it is reported
rather than assumed away - see :meth:`QLSwaptionPricer.forward_diagnostics`.

Units
-----
Strikes and forwards are **decimals** on this class's API, volatilities are
**basis points**, premia are currency units for the notional given and are
present-valued to the cube's ``as_of``.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, Optional, Tuple

import QuantLib as ql

from MDP.CitiVelocityExcel.curves.conventions import CurveConvention, conventions_for
from MDP.CitiVelocityExcel.curves.ql_builder import (
    END_OF_MONTH_BY_INDEX,
    PAYMENT_LAG_BY_INDEX,
    _CONVENTION,
    _day_counter,
    _frequency,
    evaluation_date,
)
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.vol.cube_data import SwaptionCubeData
from MDP.CitiVelocityExcel.vol.ql_cube import (
    VOL_CCY_DEFAULT_OIS_INDEX,
    QLSwaptionCube,
    build_ql_atm_matrix,
    build_ql_swaption_cube,
)

__all__ = ["QLSwaptionPricer", "EXPIRY_DAY_COUNT_QL", "resolve_ql_handle"]

_logger = logging.getLogger(__name__)

#: Time-to-expiry basis for the option leg, matching both rateslib backends.
#: ACT/365F regardless of the swap's own accrual convention - the vol is quoted
#: per annum on the option, not on the swap.
EXPIRY_DAY_COUNT_QL = ql.Actual365Fixed()

#: ``ql.Swaption.impliedVolatility`` solver arguments: guess, accuracy, max
#: iterations, min vol, max vol. The bracket is in DECIMAL normal vol, so
#: ``[1e-8, 0.05]`` spans 0 to 500 bp - wider than any quoted swaption vol.
_IMPLIED_VOL_ARGS = (0.008, 1e-10, 500, 1e-8, 0.05)


def _ql_date(when: datetime.date) -> ql.Date:
    return ql.Date(when.day, when.month, when.year)


def resolve_ql_handle(curve: Any) -> Tuple[Any, Optional[datetime.date]]:
    """Accept the several shapes a QuantLib curve arrives in.

    Returns ``(YieldTermStructureHandle, reference_date or None)``. Accepted:
    a :class:`~MDP.CitiVelocityExcel.curves.ql_builder.QLOisCurve` (attribute
    ``handle``), a ``QLIRSwapCurve``-shaped object (callable ``handle()``), a bare
    handle, or a bare term structure.
    """
    reference: Optional[datetime.date] = None
    ref_attr = getattr(curve, "reference_date", None)
    if isinstance(ref_attr, datetime.date):
        reference = ref_attr
    elif callable(ref_attr):
        try:
            candidate = ref_attr()
            if isinstance(candidate, datetime.datetime):
                reference = candidate.date()
            elif isinstance(candidate, datetime.date):
                reference = candidate
        except Exception:  # noqa: BLE001 - a curve that cannot say is not an error
            reference = None

    handle = getattr(curve, "handle", None)
    if callable(handle):
        handle = handle()
    if handle is None:
        handle = curve
    if isinstance(handle, (ql.YieldTermStructureHandle, ql.RelinkableYieldTermStructureHandle)):
        return handle, reference
    if isinstance(handle, ql.YieldTermStructure):
        return ql.YieldTermStructureHandle(handle), reference
    raise TypeError(
        f"Cannot resolve a QuantLib yield term structure from {type(curve).__name__}. "
        "Pass a QLOisCurve, a QLIRSwapCurve, a ql.YieldTermStructureHandle or a "
        "ql.YieldTermStructure."
    )


class QLSwaptionPricer:
    """A Citi cube priced through ``ql.Swaption`` + ``ql.BachelierSwaptionEngine``.

    Parameters
    ----------
    cube
        The source :class:`SwaptionCubeData`, ``measure='NORMAL'``.
    ql_curve
        The discount/forecast curve; see :func:`resolve_ql_handle` for the shapes
        accepted.
    citi_index
        Override the Citi OIS index whose conventions define the underlying swap.
    notional
        Default notional for :meth:`price`, :meth:`vega` and :meth:`greeks`.
    sabr
        Build ``ql.SabrSwaptionVolatilityCube`` instead of the interpolated one.
        A SABR cube is a FIT: it does not reproduce its own input nodes, so the
        ordering assertion is skipped for it (``build_ql_swaption_cube`` says so).
    vol_source
        ``'cube'`` (default) or ``'exact'``; see the module docstring.
    """

    def __init__(
        self,
        *,
        cube: SwaptionCubeData,
        ql_curve: Any,
        citi_index: Optional[str] = None,
        notional: float = 1e8,
        sabr: bool = False,
        vol_source: str = "cube",
        ql_cube: Optional[QLSwaptionCube] = None,
        **build_kwargs: Any,
    ):
        cube.validate()
        if cube.measure.upper() != "NORMAL":
            raise ValueError(
                f"cube.measure={cube.measure!r}; QLSwaptionPricer is a Bachelier pricer and only "
                "'NORMAL' quotes belong in it."
            )
        source = str(vol_source).strip().lower()
        if source not in {"cube", "exact"}:
            raise ValueError(f"vol_source must be 'cube' or 'exact', got {vol_source!r}.")

        self.cube = cube
        self.notional = float(notional)
        self.vol_source = source
        self.as_of = cube.as_of
        self._ql_as_of = _ql_date(cube.as_of)
        self.handle, self.curve_reference_date = resolve_ql_handle(ql_curve)

        token = str(citi_index).upper() if citi_index else VOL_CCY_DEFAULT_OIS_INDEX.get(
            cube.currency.upper()
        )
        if not token:
            raise CitiVelocityError(
                f"No default Citi OIS index for vol currency {cube.currency!r} "
                f"(known: {', '.join(sorted(VOL_CCY_DEFAULT_OIS_INDEX))}). Pass citi_index=."
            )
        self.convention: CurveConvention = conventions_for(token)
        if self.convention.approximate:
            _logger.warning(
                "Underlying swap conventions for %s are %s, not rateslib-supplied: %s",
                self.convention.citi_index,
                self.convention.provenance,
                self.convention.note or "see CurveConvention.note",
            )

        with evaluation_date(self._ql_as_of):
            self.on_index = self.convention.ql_index(self.handle)
            self.calendar = self.on_index.fixingCalendar()
            if ql_cube is not None:
                self.ql_cube = ql_cube
            else:
                caller_offsets = build_kwargs.get("offsets_bp")
                offsets = (
                    [float(o) for o in caller_offsets]
                    if caller_offsets is not None
                    else cube.skew_offsets()
                )
                if any(o != 0.0 for o in offsets):
                    self.ql_cube = build_ql_swaption_cube(
                        cube=cube,
                        curve=self.handle,
                        citi_index=self.convention.citi_index,
                        sabr=bool(sabr),
                        **build_kwargs,
                    )
                else:
                    # ATM-only data (e.g. COM fallback on holidays or unwarmed
                    # dates).  A ql.SwaptionVolatilityMatrix serves ATMF vol
                    # correctly; off-ATM queries return flat ATM vol.
                    atm = build_ql_atm_matrix(cube, calendar=self.calendar)
                    self.ql_cube = QLSwaptionCube(
                        handle=ql.SwaptionVolatilityStructureHandle(atm),
                        structure=atm,
                        atm_matrix=atm,
                        cube=cube,
                        option_tenors=cube.expiries(),
                        swap_tenors=cube.tenors(),
                        strike_spreads=[0.0],
                    )
                    _logger.warning(
                        "Cube data for %s has no strike offsets; built ATM-only "
                        "surface. Off-ATM reads will serve flat ATM vol.",
                        cube.as_of,
                    )
        self.sabr = bool(getattr(self.ql_cube, "sabr", sabr))
        self.eval_date_gap_days = self._check_date_alignment()
        self._point_cache: Dict[Tuple[str, str], Tuple[float, float, float]] = {}

    # -- provenance -----------------------------------------------------

    def _check_date_alignment(self) -> int:
        """Warn when the cube's ``as_of`` and the curve's reference date disagree.

        QuantLib is less exposed here than rateslib - the premium and the greeks
        are both timed off the pinned evaluation date - but a cube priced on a
        curve from another day is still a thing the caller should know they are
        doing, and the rateslib backend warns about the same mismatch.
        """
        reference = self.curve_reference_date
        if reference is None:
            return 0
        gap = (reference - self.as_of).days
        if gap:
            _logger.warning(
                "vol cube as_of=%s but the QuantLib curve's reference date is %s (%+d days). "
                "The premium is timed from the cube's as_of; the discount factors are the "
                "curve's.",
                self.as_of,
                reference,
                gap,
            )
        return gap

    # -- the underlying -------------------------------------------------

    def expiry_date(self, expiry: str) -> datetime.date:
        """The option date the vol surface itself assigns to an expiry token."""
        with evaluation_date(self._ql_as_of):
            d = self.ql_cube.option_date(str(expiry))
        return datetime.date(d.year(), d.month(), d.dayOfMonth())

    def effective_date(self, expiry: str) -> datetime.date:
        """The underlying swap's start: the option date plus the settlement lag."""
        with evaluation_date(self._ql_as_of):
            start = self.calendar.advance(
                _ql_date(self.expiry_date(expiry)),
                ql.Period(int(self.convention.spot_lag), ql.Days),
            )
        return datetime.date(start.year(), start.month(), start.dayOfMonth())

    def underlying(
        self,
        expiry: str,
        tenor: str,
        fixed_rate: float,
        *,
        notional: Optional[float] = None,
        right: str = "payer",
    ) -> Any:
        """The forward-starting OIS the swaption exercises into.

        ``fixed_rate`` is a DECIMAL rate. A payer swaption exercises into a
        payer swap (``ql.Swap.Payer``), which is a call on the swap rate.
        """
        conv = self.convention
        effective = _ql_date(self.effective_date(expiry))
        size = self.notional if notional is None else float(notional)
        swap_type = ql.Swap.Payer if _is_call(right) else ql.Swap.Receiver
        with evaluation_date(self._ql_as_of):
            return ql.MakeOIS(
                ql.Period(str(tenor)),
                self.on_index,
                float(fixed_rate),
                ql.Period("0D"),
                # settlementDays= is NOT passed: MakeOIS::withSettlementDays
                # clears any effective date already set, and the SWIG wrapper
                # applies keywords in the order they are written, so passing both
                # silently reverts the swap to a SPOT start. Measured: the 1Yx10Y
                # underlying came back as the spot 10Y (4.25759%, the par quote
                # itself) against a true forward of 4.32250%, a 6.5 bp error that
                # slides the whole smile. The explicit effective date is the one
                # that matters here; settlementDays only sets the default start.
                effectiveDate=effective,
                nominal=size,
                swapType=swap_type,
                paymentLag=PAYMENT_LAG_BY_INDEX[conv.citi_index],
                paymentAdjustmentConvention=_CONVENTION,
                paymentFrequency=_frequency(conv),
                paymentCalendar=self.calendar,
                # The convention's end-of-month rule applies only when the start
                # really is the last business day of its month; QuantLib does not
                # make that distinction and drifts on a mid-month start. Same rule
                # as curves/ql_builder._end_of_month, and swaption effective dates
                # are almost never month-end.
                endOfMonth=bool(END_OF_MONTH_BY_INDEX[conv.citi_index])
                and bool(self.calendar.isEndOfMonth(effective)),
                fixedLegDayCount=_day_counter(conv),
                discountingTermStructure=self.handle,
            )

    def _point(self, expiry: str, tenor: str) -> Tuple[float, float, float]:
        """``(forward decimal, annuity per unit notional, time to expiry)``.

        The forward is the par rate of the swaption's **own** underlying, not
        QuantLib's ``atmStrike``: the strike offsets are measured from the
        forward of the thing being priced. :meth:`forward_diagnostics` reports
        the gap between the two.
        """
        key = (str(expiry), str(tenor))
        hit = self._point_cache.get(key)
        if hit is not None:
            return hit
        with evaluation_date(self._ql_as_of):
            swap = self.underlying(expiry, tenor, 0.0, notional=self.notional)
            forward = float(swap.fairRate())
            annuity = abs(float(swap.fixedLegBPS())) * 1e4 / self.notional
            tte = float(
                EXPIRY_DAY_COUNT_QL.yearFraction(self._ql_as_of, _ql_date(self.expiry_date(expiry)))
            )
        if not (forward == forward and annuity > 0.0):
            raise CitiVelocityError(
                f"QuantLib produced a degenerate underlying for {expiry}x{tenor}: "
                f"forward={forward}, annuity={annuity}, tte={tte}. The curve is unsolved or does "
                "not span the swap - check its node range against the far corner of the cube."
            )
        out = (forward, annuity, tte)
        self._point_cache[key] = out
        return out

    def forward(self, expiry: str, tenor: str) -> float:
        """The forward par swap rate of the underlying, DECIMAL."""
        return self._point(expiry, tenor)[0]

    def annuity(self, expiry: str, tenor: str) -> float:
        """The discounted fixed-leg annuity per unit notional, in years."""
        return self._point(expiry, tenor)[1]

    def time_to_expiry(self, expiry: str) -> float:
        """ACT/365F year fraction from ``as_of`` to the option date.

        The same basis both rateslib backends use, so the three are comparable.
        """
        return float(
            EXPIRY_DAY_COUNT_QL.yearFraction(self._ql_as_of, _ql_date(self.expiry_date(expiry)))
        )

    def forward_diagnostics(self, expiry: str, tenor: str) -> Dict[str, float]:
        """``atmStrike`` versus the underlying's own par rate, in bp.

        The cube measures every strike spread from ``atmStrike``, which QuantLib
        derives from the ``OvernightIndexedSwapIndex`` rather than from the
        swaption's underlying. A gap here slides the smile along the strike axis
        without changing a single node volatility, so it is worth naming.
        """
        with evaluation_date(self._ql_as_of):
            atm_strike = float(self.ql_cube.atm_strike(str(expiry), str(tenor)))
        forward = self.forward(expiry, tenor)
        return {
            "atm_strike": atm_strike,
            "underlying_forward": forward,
            "gap_bp": (forward - atm_strike) * 1e4,
        }

    # -- the surface ----------------------------------------------------

    def normal_vol(
        self,
        expiry: str,
        tenor: str,
        strike: Optional[float] = None,
        offset_bp: float = 0.0,
    ) -> float:
        """Normal vol in BASIS POINTS at ``(expiry, tenor)``.

        ``strike`` is a decimal absolute strike; the offset it implies is
        measured from :meth:`forward`, so the strike axis is anchored on the
        underlying's own par rate exactly as it is on both rateslib backends.
        """
        if strike is not None:
            offset_bp = (float(strike) - self.forward(expiry, tenor)) * 1e4
        with evaluation_date(self._ql_as_of):
            return float(self.ql_cube.vol(str(expiry), str(tenor), offset_bp=float(offset_bp)))

    def volatility(
        self,
        option_time: float,
        swap_length: float,
        strike: float,
        extrapolate: bool = True,
    ) -> float:
        """``ql.SwaptionVolatilityStructure`` read signature. DECIMAL vol.

        Kept because ``Query/IRSwaptions/pricer.py::_surface_model_vol`` calls
        exactly this on ``context.vol_handle``. Everything - option time to
        option date, swap length, ``atmStrike``, smile section - is QuantLib's
        own, which is why there is no year-to-date reconstruction here.
        """
        with evaluation_date(self._ql_as_of):
            return float(
                self.ql_cube.structure.volatility(
                    float(option_time), float(swap_length), float(strike), bool(extrapolate)
                )
            )

    def volatility_at_point(self, option_time: float, swap_length: float, strike: float) -> float:
        """The repo's vol-cube protocol (MONKEYCUBE, GSQUANT_MC_ENHANCED). DECIMAL."""
        return self.volatility(option_time, swap_length, strike)

    def smile(self, expiry: str, tenor: str) -> Dict[float, float]:
        """``{signed offset bp: normal vol bp}`` at one point, ascending."""
        return {
            float(o): self.normal_vol(expiry, tenor, offset_bp=float(o))
            for o in self.cube.offsets()
        }

    # -- pricing --------------------------------------------------------

    def _engine(self, expiry: str, tenor: str, strike: float) -> Any:
        if self.vol_source == "cube":
            return ql.BachelierSwaptionEngine(self.handle, self.ql_cube.handle)
        vol = self.normal_vol(expiry, tenor, strike=float(strike)) / 1e4
        surface = ql.ConstantSwaptionVolatility(
            self._ql_as_of,
            self.calendar,
            _CONVENTION,
            float(vol),
            EXPIRY_DAY_COUNT_QL,
            ql.Normal,
            0.0,
        )
        vol_handle = ql.SwaptionVolatilityStructureHandle(surface)
        vol_handle.enableExtrapolation()
        return ql.BachelierSwaptionEngine(self.handle, vol_handle)

    def swaption(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        right: str = "payer",
        notional: Optional[float] = None,
        *,
        engine: Optional[Any] = None,
    ) -> ql.Swaption:
        """The live ``ql.Swaption``, engine attached."""
        with evaluation_date(self._ql_as_of):
            underlying = self.underlying(
                expiry, tenor, float(strike), notional=notional, right=right
            )
            option = ql.Swaption(
                underlying, ql.EuropeanExercise(_ql_date(self.expiry_date(expiry)))
            )
            option.setPricingEngine(engine or self._engine(expiry, tenor, float(strike)))
        return option

    def price(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        right: str = "payer",
        notional: Optional[float] = None,
    ) -> float:
        """Present value of the European swaption at ``as_of``, currency units."""
        with evaluation_date(self._ql_as_of):
            return float(self.swaption(expiry, tenor, float(strike), right, notional).NPV())

    def premium(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        right: str = "payer",
        notional: Optional[float] = None,
    ) -> float:
        """The premium on its payment date, undiscounted.

        QuantLib prices a swaption spot-settled, so this is :meth:`price` grossed
        back up by the discount factor to expiry plus the index's payment lag -
        the same payment date rateslib's ``rate(metric='Premium')`` uses, so the
        two backends' premia are comparable.
        """
        pv = self.price(expiry, tenor, strike, right, notional)
        return pv / self.payment_discount(expiry)

    def payment_discount(self, expiry: str) -> float:
        """Discount factor from the premium's payment date to ``as_of``."""
        with evaluation_date(self._ql_as_of):
            pay = self.calendar.advance(
                _ql_date(self.expiry_date(expiry)),
                ql.Period(int(PAYMENT_LAG_BY_INDEX[self.convention.citi_index]), ql.Days),
            )
            return float(self.handle.discount(pay))

    def vega(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        right: str = "payer",
        notional: Optional[float] = None,
        analytic: bool = False,
    ) -> float:
        """PV change per **1 bp** of normal vol, in currency units.

        Defaults to a central difference of :meth:`price` over a +/-0.5 bp
        parallel shift of the volatility, so it means the same thing as
        :meth:`NativeSwaptionCube.vega` and is consistent with the premium this
        object reports. ``analytic=True`` returns ``ql.Swaption.vega()`` instead.
        """
        if analytic:
            with evaluation_date(self._ql_as_of):
                return float(
                    self.swaption(expiry, tenor, float(strike), right, notional).vega()
                ) / 1e4
        base = self.normal_vol(expiry, tenor, strike=float(strike)) / 1e4
        out = []
        for bump in (+0.5e-4, -0.5e-4):
            surface = ql.ConstantSwaptionVolatility(
                self._ql_as_of,
                self.calendar,
                _CONVENTION,
                float(base + bump),
                EXPIRY_DAY_COUNT_QL,
                ql.Normal,
                0.0,
            )
            vol_handle = ql.SwaptionVolatilityStructureHandle(surface)
            vol_handle.enableExtrapolation()
            engine = ql.BachelierSwaptionEngine(self.handle, vol_handle)
            with evaluation_date(self._ql_as_of):
                out.append(
                    float(
                        self.swaption(
                            expiry, tenor, float(strike), right, notional, engine=engine
                        ).NPV()
                    )
                )
        return out[0] - out[1]

    def implied_normal_vol(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        premium: float,
        right: str = "payer",
        notional: Optional[float] = None,
    ) -> float:
        """Invert :meth:`price`: a present-valued premium back to normal vol in bp.

        Uses ``ql.Swaption.impliedVolatility``, i.e. QuantLib inverting its own
        pricer. That makes it a **consistency** check, not an independent one -
        the spot check inverts with the repo's pure-Python bisection instead.
        """
        with evaluation_date(self._ql_as_of):
            option = self.swaption(expiry, tenor, float(strike), right, notional)
            return (
                float(
                    option.impliedVolatility(
                        float(premium), self.handle, *_IMPLIED_VOL_ARGS, ql.Normal
                    )
                )
                * 1e4
            )

    def __repr__(self) -> str:
        kind = "SABR" if self.sabr else "interpolated"
        return (
            f"QLSwaptionPricer({self.cube.currency} {self.cube.as_of} {kind}/"
            f"{self.vol_source}, {len(self.cube.expiries())}x{len(self.cube.tenors())}x"
            f"{len(self.cube.offsets())}, idx={self.convention.citi_index})"
        )


def _is_call(right: str) -> bool:
    from MDP.CitiVelocityExcel.vol.rl_cube import _right

    return _right(right) == "C"

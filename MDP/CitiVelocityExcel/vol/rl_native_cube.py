r"""The rateslib-native IR vol cube backend (``rl.IRSplineCube`` + ``rl.IRSCall``).

rateslib **2.7.0** shipped interest-rate volatility: :class:`rateslib.IRSplineCube`,
:class:`rateslib.IRSabrCube`, their smiles, and a full swaption instrument suite
(``IRSCall``, ``IRSPut``, ``IRSStraddle``, ``IRSStrangle``, ``IRSRiskReversal``).
None of it exists in 2.1.x, which is why
:mod:`MDP.CitiVelocityExcel.vol.rl_cube` builds a cube out of ``PPSplineF64``
primitives and prices it through ``Query.Base.bachelier``. This module is the
native path.

Why prefer the native one
-------------------------
Not the marks - on live Citi quotes the two backends agree on price to 1.7e-10
relative and on vega to 1.6e-05 (see :func:`compare_backends`). It is the risk.
The native premium carries **automatic differentiation back to the curve nodes
and the vol nodes**, so ``delta``/``gamma``/``vanna``/``vomma`` come out of the
same object that produced the price, and the cube can be placed in a
:class:`rateslib.Solver` and calibrated. The hand-built cube can do neither.

``build_rl_vol_cube`` still defaults to the hand-built one, because rateslib
labels IR vol Beta and the live reconciliation below found a real defect in it.

The strike axis is basis points from the ATM forward
----------------------------------------------------
``IRSplineCube(strikes=...)`` takes **signed basis-point offsets from the ATM
forward**, not absolute strikes and not decimals - ``strikes=[-50, -25, 0, 25,
50]``. The smile's nodes are keyed on that offset (``smile.nodes`` reads back
``{-50.0: ..., 0.0: ..., 50.0: ...}``) and evaluation is invariant to the forward
you query with, which :func:`assert_native_cube_round_trips` relies on and
``test_strike_axis_is_forward_invariant`` pins.

That is exactly Citi's own convention - ``OTM_RFR.NORMALABSOLUTE.OTM_M25`` is the
vol 25bp below the forward - so :class:`SwaptionCubeData` maps onto the native
cube with no strike transformation at all.

``parameters`` under ``pricing_model='normal_vol'`` are in **basis points** of
annualised normal vol, which is also what :class:`SwaptionCubeData` stores, so
they too pass through untouched. rateslib divides by 100 internally (the greeks
dict reports ``__vol`` in percent, matching ``__forward``) and multiplies back for
``rate(metric='NormalVol')``.

.. note::

   An earlier revision of this module refused to serve, reporting that off-ATM
   nodes did not round-trip. That was a unit error here - the strike axis was
   being passed in percent - and not a rateslib problem. The guard below is kept
   anyway, because it is what turned a silent 5x mis-parameterisation into a
   loud one.

Premium, PV and what ``npv`` means for an unpriced option
---------------------------------------------------------
Three quantities that are easy to confuse, all verified in
``tests/test_citivelo_native_vol_cube.py``:

* ``opt.rate(metric='Premium')`` - the cash premium **on its payment date**
  (expiry + the series' payment lag). Undiscounted.
* :meth:`NativeSwaptionCube.price` - that premium discounted to ``as_of``. This is
  the number :meth:`CitiVeloNormalVolCube.price` returns, so the two backends are
  directly comparable.
* ``opt.npv()`` on an option built **without** a ``premium`` argument - always
  ``0.0``. rateslib treats it as unpriced and sets the premium to mid, exactly as
  it does for ``FXCall``. It is not a bug and it is not a zero-value option.

rateslib times the option from the CURVE, and its analytic vega pays for it
---------------------------------------------------------------------------
Found on live Citi data on 2026-08-06 and reproduced exactly offline. When the
curve's first node is not the cube's ``eval_date``, rateslib's
``analytic_greeks()['vega_usd']`` is computed at a time to expiry measured from
the **curve**, while the premium uses the cube's eval date. The premium stays
correct - it agrees with the hand-built backend to 1e-15 - but the analytic vega
comes out low by :math:`\sqrt{T'/T}\,\phi(d')/\phi(d)`, which for a one-day gap
on a 1Y expiry is 0.14% at the money and 0.34% at the 100bp wings. Nothing
raises.

Two defences, because either alone would leave a hole:

* :meth:`NativeSwaptionCube.vega` central-differences :meth:`price` over a
  +/-0.5bp shift of the cube rather than reading ``vega_usd``, so it is
  consistent with the premium by construction. It matches the analytic value to
  1e-6 when the dates DO line up.
* the constructor warns when ``cube.as_of`` and the curve's first node disagree,
  naming the size of the error, because ``greeks()`` still hands back rateslib's
  raw dict and someone will read ``vega_usd`` out of it.

The live run that found this had a 2026-08-05 cube on a 2026-08-06 curve, which
is itself worth noticing: the vol cube was a day stale relative to the curve.

What the cube still cannot know
-------------------------------
Citi measures its offsets from **Citi's** ATM forward, which is not published on
this branch. Both backends measure them from the forward implied by the curve
they were handed, so a curve disagreement shifts the whole smile along the strike
axis and nothing in the data reveals it. Node vols round-trip regardless - they
are keyed by offset - but a strike-quoted price is only as good as the curve.
:func:`compare_backends` reports the forward each backend used for that reason.
"""

from __future__ import annotations

import datetime
import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.vol.cube_data import SwaptionCubeData

__all__ = [
    "RATESLIB_NATIVE_AVAILABLE",
    "NATIVE_VOL_PARAM_UNIT",
    "NativeCubeUnverifiedError",
    "NativeSwaptionCube",
    "assert_native_cube_round_trips",
    "build_rl_native_cube",
    "build_rl_native_swaption_cube",
    "compare_backends",
    "irs_series_for",
    "native_spline_order",
]

_logger = logging.getLogger(__name__)

#: The unit of the numbers handed to ``IRSplineCube(parameters=...)`` under
#: ``pricing_model='normal_vol'``. Basis points, same as :class:`SwaptionCubeData`.
NATIVE_VOL_PARAM_UNIT = "bp"

#: A cubic (order 4) spline needs at least this many strike nodes to be worth
#: asking for. Below it the strike axis drops to linear (order 2).
_MIN_CUBIC_SITES = 4

#: rateslib spline orders: 2 is linear, 4 is cubic. There is no 3.
_SPLINE_ORDERS = (2, 4)


def _native_available() -> bool:
    try:
        import rateslib as rl
    except Exception:  # pragma: no cover - rateslib is a hard dependency elsewhere
        return False
    return all(
        hasattr(rl, name) for name in ("IRSplineCube", "IRSabrCube", "IRSCall", "IRSPut")
    )


#: True when the installed rateslib exposes the IR vol cubes and swaptions (>= 2.7.0).
RATESLIB_NATIVE_AVAILABLE: bool = _native_available()


class NativeCubeUnverifiedError(CitiVelocityError):
    """The native cube did not reproduce its own input nodes."""


def _require_native() -> Any:
    if not RATESLIB_NATIVE_AVAILABLE:
        raise CitiVelocityError(
            "The native IR vol cube needs rateslib >= 2.7.0 (IRSplineCube, IRSCall). This "
            "environment has an older rateslib - use build_rl_vol_cube(), which is assembled "
            "from primitives available in every supported version."
        )
    import rateslib as rl

    return rl


# ------------------------------------------------------------------ #
#                        the underlying swap                         #
# ------------------------------------------------------------------ #


def irs_series_for(citi_index: str) -> Any:
    """The underlying-swap conventions for a Citi curve, for ``irs_series=``.

    Returns rateslib's **named spec string** when the currency has one, so the
    cube's underlying is byte-for-byte the swap ``rl.IRS(spec=...)`` builds and
    the two backends cannot drift apart. Only currencies with no named spec get a
    hand-built :class:`~rateslib.data.fixings.IRSSeries` out of
    :class:`~MDP.CitiVelocityExcel.curves.conventions.CurveConvention` - the same
    row the curve builders read, whose ``provenance`` field already says whether
    it is library-supplied or market-standard.

    Hand-building loses one field rateslib's specs set: ``payment_lag``. It is
    left at the rateslib default rather than guessed.
    """
    _require_native()
    from rateslib.data.fixings import IRSSeries

    from MDP.CitiVelocityExcel.curves.conventions import conventions_for

    conv = conventions_for(citi_index)
    if conv.rl_spec:
        return conv.rl_spec
    return IRSSeries(
        currency=conv.currency.lower(),
        settle=int(conv.spot_lag),
        frequency=conv.fixed_frequency.upper(),
        convention=conv.convention,
        calendar=conv.rl_calendar or conv.rl_calendar_object(),
        leg2_fixing_method="rfr_payment_delay",
    )


def native_spline_order(n_strikes: int, requested: Optional[int] = None) -> int:
    """Resolve the strike-axis spline order actually usable for ``n_strikes`` nodes.

    ``None`` means "cubic if the axis can carry it, else linear" - the same rule
    :class:`~MDP.CitiVelocityExcel.vol.rl_cube.CitiVeloNormalVolCube` applies, so
    the two backends interpolate the strike axis the same way. An explicit order
    is honoured and validated, never silently downgraded.
    """
    if requested is None:
        return 4 if int(n_strikes) >= _MIN_CUBIC_SITES else 2
    order = int(requested)
    if order not in _SPLINE_ORDERS:
        raise ValueError(
            f"spline_order must be 2 (linear) or 4 (cubic), got {requested!r}. "
            "rateslib's PPSpline has no order 3."
        )
    return order


# ------------------------------------------------------------------ #
#                          the native cube                           #
# ------------------------------------------------------------------ #


def build_rl_native_cube(
    *,
    cube: SwaptionCubeData,
    citi_index: Optional[str] = None,
    eval_date: Any = None,
    spline_order: Optional[int] = None,
    pricing_model: str = "normal_vol",
    verify: bool = True,
    tol: float = 1e-9,
    id: Optional[str] = None,
) -> Any:
    """Build an ``rl.IRSplineCube`` from a Citi swaption cube.

    Citi's grid maps straight on: expiries and tenors are tenor tokens, the strike
    axis is signed basis points from the ATM forward, and the parameters are
    normal vol in basis points. Nothing is rescaled.

    Parameters
    ----------
    cube
        The Citi cube. Must be ``measure='NORMAL'`` - this is a Bachelier cube.
    citi_index
        Override the Citi OIS index whose conventions define the underlying swap.
        Defaults per currency; KRW has none and must be given one.
    eval_date
        Defaults to ``cube.as_of`` at midnight.
    spline_order
        2 (linear) or 4 (cubic) on the strike axis. ``None`` picks cubic when
        there are at least four strikes. See :func:`native_spline_order`.
    verify
        Read every node back out and raise unless it reproduces its input. Leave
        it True: a mis-parameterised smile prices without complaint.

    Returns
    -------
    rateslib.IRSplineCube

    Raises
    ------
    NativeCubeUnverifiedError
        When a node does not round-trip.
    """
    rl = _require_native()
    cube.validate()
    if cube.measure.upper() != "NORMAL":
        raise ValueError(
            f"cube.measure={cube.measure!r}; the native cube is built with "
            "pricing_model='normal_vol' and only 'NORMAL' quotes belong in it."
        )
    if str(cube.vol_unit).lower() != "bp":
        raise ValueError(
            f"cube.vol_unit={cube.vol_unit!r}; IRSplineCube parameters are in basis points "
            f"({NATIVE_VOL_PARAM_UNIT}) under pricing_model='normal_vol'."
        )

    index_token = _citi_index_for(cube, citi_index)
    expiries = list(cube.expiries())
    tenors = list(cube.tenors())
    offsets = [float(o) for o in cube.offsets()]
    order = native_spline_order(len(offsets), spline_order)

    if eval_date is None:
        as_of = cube.as_of
        eval_date = datetime.datetime(as_of.year, as_of.month, as_of.day)

    parameters = np.array(
        [[[float(cube.vol(e, t, o)) for o in offsets] for t in tenors] for e in expiries],
        dtype=float,
    )
    if not np.isfinite(parameters).all():
        bad = int((~np.isfinite(parameters)).sum())
        raise ValueError(
            f"{bad} of {parameters.size} cube nodes are not finite. IRSplineCube will build "
            "from them and produce NaN premia with no error - fill or drop them first."
        )

    native = rl.IRSplineCube(
        expiries=expiries,
        tenors=tenors,
        strikes=offsets,
        eval_date=eval_date,
        irs_series=irs_series_for(index_token),
        parameters=parameters,
        pricing_model=pricing_model,
        k=order,
        id=id or f"{index_token}-CITIVELO-VOL",
    )
    if verify:
        worst = assert_native_cube_round_trips(native, cube, tol=tol)
        _logger.info(
            "IRSplineCube %s: %d nodes round-tripped, worst %.3e bp, strike spline order %d",
            native.id,
            parameters.size,
            worst,
            order,
        )
    return native


def assert_native_cube_round_trips(
    native: Any,
    cube: SwaptionCubeData,
    forwards: Optional[Dict[Tuple[str, str], float]] = None,
    *,
    tol: float = 1e-9,
) -> float:
    """Read every node back out of the native cube and compare it to the input.

    Returns the worst absolute error in basis points of vol.

    ``forwards`` is ``{(expiry, tenor): forward in PERCENT}`` and is optional: the
    smile's strike axis is bp-from-forward and therefore forward-invariant, so a
    node check needs no curve. Pass real forwards to exercise the same query path
    pricing uses; a placeholder is used otherwise.

    This is the only thing standing between a mis-parameterised smile and a
    plausible-looking wrong premium, so it raises rather than warns.
    """
    _require_native()
    placeholder = 3.0
    worst = 0.0
    worst_key: Optional[Tuple[str, str, float]] = None
    for expiry in cube.expiries():
        for tenor in cube.tenors():
            forward = placeholder if forwards is None else forwards.get((expiry, tenor))
            if forward is None:
                continue
            smile = native.get_smile(expiry, tenor)
            for offset in cube.offsets():
                expected = float(cube.vol(expiry, tenor, offset))
                got = float(smile.get_from_strike(forward + offset / 100.0, f=forward).vol)
                err = abs(got - expected)
                if err > worst:
                    worst, worst_key = err, (expiry, tenor, float(offset))
    if worst > tol:
        expiry, tenor, offset = worst_key or ("?", "?", 0.0)
        raise NativeCubeUnverifiedError(
            f"IRSplineCube {getattr(native, 'id', '?')} did not reproduce its own input nodes: "
            f"worst error {worst:.6g} bp at expiry={expiry}, tenor={tenor}, "
            f"offset={offset:+.0f}bp (tolerance {tol:g}). The strike axis is signed BASIS POINTS "
            "from the ATM forward and the parameters are normal vol in basis points; passing "
            "either in percent or in decimals builds without error and misprices. Use "
            "build_rl_vol_cube() until this is resolved."
        )
    return worst


def _citi_index_for(cube: SwaptionCubeData, citi_index: Optional[str]) -> str:
    from MDP.CitiVelocityExcel.vol.rl_cube import convention_for_cube

    return convention_for_cube(cube, citi_index=citi_index).citi_index


def _curve_initial_node(curve: Any) -> Optional[datetime.datetime]:
    """The curve's first node date, or None if the object does not expose one."""
    nodes = getattr(curve, "nodes", None)
    initial = getattr(nodes, "initial", None)
    if isinstance(initial, datetime.datetime):
        return initial
    if isinstance(nodes, dict) and nodes:
        first = next(iter(nodes))
        return first if isinstance(first, datetime.datetime) else None
    return None


# ------------------------------------------------------------------ #
#                     the priced, wrapped cube                       #
# ------------------------------------------------------------------ #


class NativeSwaptionCube:
    """A Citi swaption cube priced through rateslib's own swaption instruments.

    The public surface deliberately mirrors
    :class:`~MDP.CitiVelocityExcel.vol.rl_cube.CitiVeloNormalVolCube` -
    :meth:`forward`, :meth:`annuity`, :meth:`normal_vol`, :meth:`smile`,
    :meth:`price`, :meth:`vega`, :meth:`implied_normal_vol`,
    :meth:`implied_vol_surface_frame`, :meth:`to_frame` - so the two are
    swappable and :func:`compare_backends` can diff them node by node.

    It adds what only the native path can give: :meth:`swaption` (the live
    ``IRSCall``/``IRSPut``), :meth:`greeks` (rateslib's AD greeks), and
    :attr:`native` (the ``IRSplineCube`` itself, ready for a ``Solver``).

    Units, stated once
    ------------------
    Vols in and out are annualised **normal vol in basis points**. Forwards and
    strikes are **decimals** on this class's own API (rateslib's are percent;
    the conversion happens at the boundary). Premia are currency units for the
    notional given, present-valued to ``as_of``.

    Parameters
    ----------
    cube
        The source :class:`SwaptionCubeData`, ``measure='NORMAL'``.
    rl_curve
        The solved curve the underlying swaps price off. A bare
        :class:`rateslib.Curve`, the repo's ``RLCurveBase`` (anything exposing
        ``rl_pricing_curve``), or a ``(forecast, discount)`` pair.
    spline_order
        Strike-axis spline order; see :func:`native_spline_order`.
    citi_index
        Override the underlying-swap conventions.
    notional
        Default notional for :meth:`price`, :meth:`vega` and :meth:`greeks`.
    """

    def __init__(
        self,
        *,
        cube: SwaptionCubeData,
        rl_curve: Any,
        spline_order: Optional[int] = None,
        citi_index: Optional[str] = None,
        notional: float = 1e8,
        disc_curve: Any = None,
        verify: bool = True,
    ):
        rl = _require_native()
        from MDP.CitiVelocityExcel.vol.rl_cube import _resolve_curves, convention_for_cube

        self.cube = cube
        self.as_of = pd.Timestamp(cube.as_of).to_pydatetime()
        self.notional = float(notional)
        self.forecast_curve, self.disc_curve = _resolve_curves(rl_curve, disc_curve)
        self.convention = convention_for_cube(cube, citi_index=citi_index)
        if self.convention.approximate:
            _logger.warning(
                "Underlying swap conventions for %s are %s, not rateslib-supplied: %s",
                self.convention.citi_index,
                self.convention.provenance,
                self.convention.note or "see CurveConvention.note",
            )

        self._expiries = cube.expiries()
        self._tenors = cube.tenors()
        self._offsets = [float(o) for o in cube.offsets()]
        self.spline_order = native_spline_order(len(self._offsets), spline_order)
        self.irs_series = irs_series_for(self.convention.citi_index)

        self.native = build_rl_native_cube(
            cube=cube,
            citi_index=self.convention.citi_index,
            eval_date=self.as_of,
            spline_order=self.spline_order,
            verify=verify,
        )
        self.interpolation_used: Dict[str, str] = {
            # The cube's expiry/tenor interpolation is rateslib's, and it is
            # bilinear between neighbouring grid points with flat extrapolation
            # outside - documented in IRSplineCube's Notes, not configurable.
            "expiry": "bilinear",
            "tenor": "bilinear",
            "offset": "spline" if self.spline_order == 4 else "linear",
        }
        self._point_cache: Dict[Tuple[str, str], Tuple[float, float, float]] = {}
        self._bumped: Dict[float, Any] = {}
        self.curve_reference_date = _curve_initial_node(self.forecast_curve)
        self.eval_date_gap_days = self._check_date_alignment()

    def _check_date_alignment(self) -> int:
        """Warn when the cube's ``as_of`` and the curve's first node disagree.

        This is not cosmetic. rateslib measures the option's time to expiry from
        the **curve's** initial node while this cube's ``eval_date`` is the cube's
        ``as_of``, and the two feed different parts of the calculation: the price
        comes out right, the analytic vega does not. A one-day gap moves
        ``analytic_greeks()['vega_usd']`` 0.14% at the money and 0.34% at the
        100bp wings, silently. Observed live on 2026-08-06, where a 2026-08-05
        cube met a 2026-08-06 curve.

        :meth:`vega` is immune (it differentiates the price) and so are
        :meth:`annuity`/:meth:`time_to_expiry` (they compute the year fraction
        here and check it reprices), so this warns rather than raises - pricing
        yesterday's cube on today's curve is a legitimate thing to do, as long as
        you know you are doing it. What is NOT protected is a caller reading
        ``vega_usd`` straight out of :meth:`greeks`, which is why this is loud.
        """
        reference = self.curve_reference_date
        if reference is None:
            return 0
        gap = (reference.date() - self.as_of.date()).days
        if gap:
            _logger.warning(
                "vol cube as_of=%s but the curve's first node is %s (%+d days). rateslib times "
                "the option from the CURVE, so analytic_greeks()['vega_usd'] will be off by "
                "roughly %.2f%% at the money. NativeSwaptionCube.vega() differentiates the price "
                "and is unaffected; greeks()['vega_usd'] is not.",
                self.as_of.date(),
                reference.date(),
                gap,
                abs(gap) / 730.0 * 100.0,
            )
        return gap

    # -- the underlying -------------------------------------------------

    def swaption(
        self,
        expiry: str,
        tenor: str,
        strike: Any = "atm",
        right: str = "payer",
        notional: Optional[float] = None,
        **kwargs: Any,
    ) -> Any:
        """The live ``rl.IRSCall`` / ``rl.IRSPut`` for one point.

        ``strike`` accepts what rateslib accepts - ``'atm'``, ``'25bps'``,
        ``'-50bps'`` - or a **decimal** absolute strike, which is converted to the
        percent rateslib wants. Extra keyword arguments go straight to the
        instrument (``premium``, ``settlement_method``, ``payment_lag`` ...).
        """
        rl = _require_native()
        from MDP.CitiVelocityExcel.vol.rl_cube import _right

        cls = rl.IRSCall if _right(right) == "C" else rl.IRSPut
        if isinstance(strike, (int, float)) and not isinstance(strike, bool):
            strike = float(strike) * 100.0
        return cls(
            expiry=str(expiry),
            tenor=str(tenor),
            strike=strike,
            notional=self.notional if notional is None else float(notional),
            irs_series=self.irs_series,
            eval_date=self.as_of,
            **kwargs,
        )

    def _curves(self) -> List[Any]:
        return [self.forecast_curve, self.disc_curve]

    def expiry_date(self, expiry: str) -> datetime.datetime:
        """The option expiry date for a tenor token, rolled modified-following."""
        rl = _require_native()
        return rl.add_tenor(self.as_of, str(expiry), "MF", self.convention.rl_calendar_object())

    def _point(self, expiry: str, tenor: str) -> Tuple[float, float, float]:
        """``(forward decimal, annuity per unit notional, time to expiry)``.

        The forward comes from rateslib's own ATM swaption, so the forward the
        price used and the forward this reports cannot differ.

        The time to expiry is computed here on ACT/365F from ``as_of``, NOT read
        out of ``analytic_greeks()['__sqrt_t']``. That field is timed from the
        curve's first node and is inconsistent with rateslib's own premium
        whenever the curve does not start on ``as_of`` - the same defect that
        makes the analytic vega wrong (see the module docstring). Using it here
        would put the same error into :meth:`annuity` and everything downstream.

        The annuity is then backed out of the ATM premium and **checked against a
        second, off-ATM strike**. That check is what pins ``tte``: a wrong T
        reprices the at-the-money point (annuity absorbs it) but not the wings,
        so if rateslib's internal timing ever stops matching this one, this
        raises instead of quietly reporting a 0.1% annuity error.
        """
        from Query.Base.bachelier import bachelier_price

        key = (str(expiry), str(tenor))
        hit = self._point_cache.get(key)
        if hit is not None:
            return hit

        rl = _require_native()
        tte = float(rl.dcf(self.as_of, self.expiry_date(expiry), "act365f"))
        opt = self.swaption(expiry, tenor, "atm", notional=self.notional)
        greeks = opt.analytic_greeks(curves=self._curves(), vol=self.native)
        forward = float(greeks["__forward"]) / 100.0

        vol = self.normal_vol(expiry, tenor, offset_bp=0.0) / 1e4
        pv = self.price(expiry, tenor, forward, right="payer", notional=self.notional)
        atm_unit = vol * math.sqrt(tte / (2.0 * math.pi)) if tte > 0 else 0.0
        annuity = pv / (self.notional * atm_unit) if atm_unit > 0 else float("nan")
        if not (math.isfinite(forward) and math.isfinite(annuity) and annuity > 0.0):
            raise CitiVelocityError(
                f"rateslib produced a degenerate underlying for {expiry}x{tenor}: "
                f"forward={forward}, annuity={annuity}, tte={tte}. The curve is unsolved or does "
                "not span the swap - check its node range against the far corner of the cube."
            )

        probe_strike = forward + 25e-4
        # offset_bp, not strike=: the strike form resolves the forward through
        # _point() and would recurse.
        probe_vol = self.normal_vol(expiry, tenor, offset_bp=25.0) / 1e4
        expected = self.notional * annuity * bachelier_price(
            "C", probe_strike, forward, probe_vol, tte, 1.0
        )
        actual = self.price(expiry, tenor, probe_strike, right="payer", notional=self.notional)
        if abs(expected - actual) > 1e-6 * max(abs(actual), 1.0):
            raise CitiVelocityError(
                f"the (annuity, tte) backed out of the {expiry}x{tenor} at-the-money premium does "
                f"not reprice a 25bp strike: expected {expected:,.4f} against rateslib's "
                f"{actual:,.4f} (annuity={annuity:.6f}, tte={tte:.8f}). rateslib is timing the "
                "option differently from ACT/365F off as_of, so annuity() and everything derived "
                "from it would be wrong. Use the hand-built backend until this is understood."
            )

        out = (forward, annuity, tte)
        self._point_cache[key] = out
        return out

    def forward(self, expiry: str, tenor: str) -> float:
        """The forward par swap rate, DECIMAL, from the curve (not from Citi)."""
        return self._point(expiry, tenor)[0]

    def annuity(self, expiry: str, tenor: str) -> float:
        """The discounted fixed-leg annuity per unit notional, in years."""
        return self._point(expiry, tenor)[1]

    def time_to_expiry(self, expiry: str) -> float:
        """ACT/365F year fraction from ``as_of`` to the option expiry date.

        The same basis :class:`CitiVeloNormalVolCube` uses, and deliberately not
        ``analytic_greeks()['__sqrt_t']`` - see :meth:`_point`.
        """
        rl = _require_native()
        return float(rl.dcf(self.as_of, self.expiry_date(expiry), "act365f"))

    # -- the surface ----------------------------------------------------

    def normal_vol(
        self,
        expiry: str,
        tenor: str,
        strike: Optional[float] = None,
        offset_bp: float = 0.0,
    ) -> float:
        """Normal vol in BASIS POINTS at ``(expiry, tenor)``.

        ``expiry`` and ``tenor`` need not be cube nodes - rateslib interpolates
        bilinearly inside the grid and holds flat outside. ``strike`` is a decimal
        absolute strike measured against :meth:`forward`; ``offset_bp`` is used
        when it is None.
        """
        smile = self.native.get_smile(str(expiry), str(tenor))
        if strike is not None:
            forward = self.forward(expiry, tenor) * 100.0
            return float(smile.get_from_strike(float(strike) * 100.0, f=forward).vol)
        forward = 3.0  # the axis is bp-from-forward, hence forward-invariant
        return float(smile.get_from_strike(forward + float(offset_bp) / 100.0, f=forward).vol)

    def smile(self, expiry: str, tenor: str) -> Dict[float, float]:
        """``{signed offset bp: normal vol bp}`` at one point, ascending."""
        return {o: self.normal_vol(expiry, tenor, offset_bp=o) for o in self._offsets}

    def implied_vol_surface_frame(
        self,
        *,
        offset_bp: float = 0.0,
        expiries: Optional[Sequence[str]] = None,
        tenors: Optional[Sequence[str]] = None,
    ) -> pd.DataFrame:
        """The interpolated surface at one offset, ``index=expiry``, ``cols=tenor``."""
        exps = list(expiries) if expiries else self._expiries
        tens = list(tenors) if tenors else self._tenors
        frame = pd.DataFrame(
            [[self.normal_vol(e, t, offset_bp=offset_bp) for t in tens] for e in exps],
            index=exps,
            columns=tens,
            dtype=float,
        )
        frame.index.name = "expiry"
        frame.columns.name = "tenor"
        return frame

    def to_frame(self) -> pd.DataFrame:
        """Long form with the rateslib-side underlying attached to every node."""
        rows: List[Dict[str, Any]] = []
        for expiry in self._expiries:
            for tenor in self._tenors:
                fwd, ann, tte = self._point(expiry, tenor)
                for off in self._offsets:
                    rows.append(
                        {
                            "expiry": expiry,
                            "tenor": tenor,
                            "offset_bp": off,
                            "vol_bp": float(self.cube.vol(expiry, tenor, off)),
                            "forward": fwd,
                            "strike": fwd + off / 1e4,
                            "annuity": ann,
                            "tte": tte,
                        }
                    )
        return pd.DataFrame(rows)

    # -- pricing --------------------------------------------------------

    def price(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        right: str = "payer",
        notional: Optional[float] = None,
    ) -> float:
        """Present value of a European swaption at ``as_of``, in currency units.

        This is the premium discounted from its payment date, which is what
        :meth:`CitiVeloNormalVolCube.price` returns. For the undiscounted
        payment-date amount use :meth:`premium`.
        """
        opt = self.swaption(expiry, tenor, float(strike), right=right, notional=notional, premium=0.0)
        return float(opt.npv(curves=self._curves(), vol=self.native))

    def premium(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        right: str = "payer",
        notional: Optional[float] = None,
    ) -> float:
        """The cash premium **on its payment date**, undiscounted."""
        opt = self.swaption(expiry, tenor, float(strike), right=right, notional=notional)
        return float(opt.rate(curves=self._curves(), vol=self.native, metric="Premium"))

    def greeks(
        self,
        expiry: str,
        tenor: str,
        strike: Any = "atm",
        right: str = "payer",
        notional: Optional[float] = None,
    ) -> Dict[str, Any]:
        """rateslib's analytic greeks for one swaption.

        Keys prefixed ``__`` are the pricing inputs rateslib resolved
        (``__forward``, ``__strike``, ``__vol`` - all in PERCENT - ``__sqrt_t``,
        ``__notional``). The ``*_usd`` entries are present-valued cash amounts;
        the unsuffixed ones are per unit of notional. ``vega_usd`` is the PV
        change per **1 basis point** of normal vol.
        """
        opt = self.swaption(expiry, tenor, strike, right=right, notional=notional)
        return dict(opt.analytic_greeks(curves=self._curves(), vol=self.native))

    def _shifted(self, bump_bp: float) -> Any:
        """The whole cube shifted by ``bump_bp`` of vol, built once and cached."""
        key = round(float(bump_bp), 9)
        hit = self._bumped.get(key)
        if hit is not None:
            return hit
        shifted = SwaptionCubeData(
            as_of=self.cube.as_of,
            currency=self.cube.currency,
            measure=self.cube.measure,
            atm=self.cube.atm + key,
            skew={k: v + key for k, v in self.cube.skew.items()},
            skew_measure=self.cube.skew_measure,
            served_unit=self.cube.served_unit,
            vol_unit=self.cube.vol_unit,
            strike_unit=self.cube.strike_unit,
            source=f"{self.cube.source}+{key:+g}bp",
        )
        built = build_rl_native_cube(
            cube=shifted,
            citi_index=self.convention.citi_index,
            eval_date=self.as_of,
            spline_order=self.spline_order,
            verify=False,
            id=f"{self.native.id}{key:+g}",
        )
        self._bumped[key] = built
        return built

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

        By default this is a central difference of :meth:`price` over a +/-0.5bp
        parallel shift of the cube, so it is consistent with the premium this
        object reports by construction. The two shifted cubes are built once and
        cached, so the cost is one extra cube per instance, not per call.

        ``analytic=True`` returns rateslib's ``analytic_greeks()['vega_usd']``
        instead. That is exact and faster **when the cube's ``as_of`` equals the
        curve's first node**, and wrong by ~0.14% per day of gap when it is not:
        rateslib times the option from the curve while the price uses the cube's
        eval date, so its own analytic vega disagrees with its own price
        derivative. See :meth:`_check_date_alignment`.
        """
        if analytic:
            return float(
                self.greeks(expiry, tenor, float(strike), right=right, notional=notional)["vega_usd"]
            )
        opt_up = self.swaption(expiry, tenor, float(strike), right=right, notional=notional, premium=0.0)
        opt_dn = self.swaption(expiry, tenor, float(strike), right=right, notional=notional, premium=0.0)
        curves = self._curves()
        up = float(opt_up.npv(curves=curves, vol=self._shifted(+0.5)))
        down = float(opt_dn.npv(curves=curves, vol=self._shifted(-0.5)))
        return up - down

    def implied_normal_vol(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        premium: float,
        right: str = "payer",
        notional: Optional[float] = None,
    ) -> float:
        """Invert :meth:`price`: a present-valued premium back to normal vol in bp."""
        from Query.Base.bachelier import implied_normal_vol as _inv
        from MDP.CitiVelocityExcel.vol.rl_cube import _right

        fwd, ann, tte = self._point(expiry, tenor)
        size = self.notional if notional is None else float(notional)
        unit = float(premium) / (size * ann)
        return float(_inv(_right(right), float(strike), fwd, tte, unit, 1.0)) * 1e4

    def __repr__(self) -> str:
        return (
            f"NativeSwaptionCube({self.cube.currency} {self.cube.as_of}, "
            f"{len(self._expiries)}x{len(self._tenors)}x{len(self._offsets)}, "
            f"order={self.spline_order}, idx={self.convention.citi_index})"
        )


def build_rl_native_swaption_cube(
    *,
    cube: SwaptionCubeData,
    rl_curve: Any,
    spline_order: Optional[int] = None,
    citi_index: Optional[str] = None,
    notional: float = 1e8,
    disc_curve: Any = None,
    verify: bool = True,
) -> NativeSwaptionCube:
    """Build a :class:`NativeSwaptionCube`. See it for the parameters."""
    return NativeSwaptionCube(
        cube=cube,
        rl_curve=rl_curve,
        spline_order=spline_order,
        citi_index=citi_index,
        notional=notional,
        disc_curve=disc_curve,
        verify=verify,
    )


# ------------------------------------------------------------------ #
#                       backend reconciliation                       #
# ------------------------------------------------------------------ #


def compare_backends(
    *,
    cube: SwaptionCubeData,
    rl_curve: Any,
    citi_index: Optional[str] = None,
    notional: float = 1e8,
    disc_curve: Any = None,
    expiries: Optional[Sequence[str]] = None,
    tenors: Optional[Sequence[str]] = None,
    offsets: Optional[Sequence[float]] = None,
) -> pd.DataFrame:
    """Price every requested node through BOTH backends and return the diff.

    One row per ``(expiry, tenor, offset)`` with each backend's forward, vol,
    premium and vega, plus the differences. Both are handed the same curve and
    resolve the same :class:`CurveConvention`, so a forward disagreement is a
    schedule difference between rateslib's swaption underlying and the ``rl.IRS``
    the hand-built cube constructs, not a data difference.

    This is the reconciliation the native backend is gated on; it is also what
    ``harvest/verify_live.py --vol-compare`` runs against real Citi quotes.
    """
    from MDP.CitiVelocityExcel.vol.rl_cube import build_rl_vol_cube

    hand = build_rl_vol_cube(
        cube=cube, rl_curve=rl_curve, citi_index=citi_index, notional=notional, disc_curve=disc_curve
    )
    native = build_rl_native_swaption_cube(
        cube=cube, rl_curve=rl_curve, citi_index=citi_index, notional=notional, disc_curve=disc_curve
    )

    exps = list(expiries) if expiries else cube.expiries()
    tens = list(tenors) if tenors else cube.tenors()
    offs = [float(o) for o in (offsets if offsets is not None else cube.offsets())]

    rows: List[Dict[str, Any]] = []
    for expiry in exps:
        for tenor in tens:
            f_hand = hand.forward(expiry, tenor)
            f_nat = native.forward(expiry, tenor)
            for off in offs:
                quoted = float(cube.vol(expiry, tenor, off))
                k_hand = f_hand + off / 1e4
                k_nat = f_nat + off / 1e4
                rows.append(
                    {
                        "expiry": expiry,
                        "tenor": tenor,
                        "offset_bp": off,
                        "citi_vol_bp": quoted,
                        "hand_vol_bp": hand.normal_vol(expiry, tenor, offset_bp=off),
                        "native_vol_bp": native.normal_vol(expiry, tenor, offset_bp=off),
                        "hand_forward": f_hand,
                        "native_forward": f_nat,
                        "forward_diff_bp": (f_nat - f_hand) * 1e4,
                        "hand_price": hand.price(expiry, tenor, k_hand),
                        "native_price": native.price(expiry, tenor, k_nat),
                        "hand_vega": hand.vega(expiry, tenor, k_hand),
                        "native_vega": native.vega(expiry, tenor, k_nat),
                    }
                )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["vol_diff_bp"] = frame["native_vol_bp"] - frame["hand_vol_bp"]
    frame["citi_vol_err_bp"] = frame["native_vol_bp"] - frame["citi_vol_bp"]
    frame["price_diff"] = frame["native_price"] - frame["hand_price"]
    denom = frame["hand_price"].abs().where(lambda s: s > 0.0, other=np.nan)
    frame["price_rel"] = frame["price_diff"].abs() / denom
    frame["vega_diff"] = frame["native_vega"] - frame["hand_vega"]
    return frame

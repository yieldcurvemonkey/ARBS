r"""A rateslib-native normal vol cube for Citi swaption quotes.

**This is a locally-built object, not a rateslib class.** rateslib 2.1.1 has no
interest-rate volatility cube and no swaption instrument at all: its only
volatility classes are ``FXDeltaVolSmile``, ``FXDeltaVolSurface``,
``FXSabrSmile``, ``FXSabrSurface`` and ``VolValue``, every one of them FX, and
there is no ``rateslib.volatility`` module - ``IRSabrCube`` and ``IRSplineCube``
do not exist in this version. So the cube below is assembled from rateslib
primitives:

* forwards and annuities from ``rl.IRS`` priced off the solved curve,
* the surface from ``rl.PPSplineF64`` (natural cubic, exact at its data sites),
* option values from ``Query.Base.bachelier``, which wraps QuantLib's Bachelier
  formula - the repo's existing normal-vol pricer.

When a newer rateslib does ship an IR cube, only the surface backend changes:
:class:`CitiVeloNormalVolCube` reads its surface through a single call,
``backend(expiry_years, tenor_years) -> vol_bp``, which is all ``_TensorSurface``
implements. An ``IRSplineCube``/``IRSabrCube`` wrapper with that one method drops
in behind ``self._surfaces`` without touching anything else.

WHAT THIS CUBE CANNOT KNOW
--------------------------
Citi's strike offsets are measured from **Citi's** at-the-money forward, which is
not published on this branch. This object measures them from the forward implied
by the curve it was handed. When the two disagree - a different fixing source, a
different CCP, a stale curve - the whole smile shifts along the strike axis by
that difference, and nothing in the data reveals it. Node volatilities still
round-trip exactly (they are keyed by offset, not by strike); it is the
strike-to-offset MAPPING that is only as good as the curve. Compare
:meth:`CitiVeloNormalVolCube.forward` against ``RATES.OIS.<idx>.FWD.<exp>.<ten>``
before trusting a strike-quoted price.

Interpolation is reported, not assumed
--------------------------------------
A cubic spline needs at least four data sites per axis. When an axis has fewer,
that axis falls back to linear interpolation, and
:attr:`CitiVeloNormalVolCube.interpolation_used` says exactly which axis used
which. It is never silently downgraded.
"""

from __future__ import annotations

import datetime
import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import rateslib as rl

from MDP.CitiVelocityExcel.catalog import tenor_years
from MDP.CitiVelocityExcel.curves.conventions import CurveConvention, conventions_for
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.vol.cube_data import SwaptionCubeData
from MDP.CitiVelocityExcel.vol.ql_cube import VOL_CCY_DEFAULT_OIS_INDEX
from Query.Base.bachelier import bachelier_greeks_fd, bachelier_price, implied_normal_vol

__all__ = [
    "CitiVeloNormalVolCube",
    "build_rl_vol_cube",
    "SurfaceBackendError",
    "EXPIRY_DAY_COUNT",
    "SWAPTION_RIGHTS",
]

_logger = logging.getLogger(__name__)

#: Time-to-expiry basis for the option leg. ACT/365F regardless of the swap's own
#: accrual convention: the vol is quoted per annum on the option, not on the swap.
EXPIRY_DAY_COUNT = "act365f"

#: Accepted spellings for the option right. A PAYER swaption is a CALL on the
#: swap rate; a RECEIVER is a PUT.
SWAPTION_RIGHTS: Dict[str, str] = {
    "C": "C",
    "CALL": "C",
    "PAYER": "C",
    "PAY": "C",
    "P": "P",
    "PUT": "P",
    "RECEIVER": "P",
    "REC": "P",
}

#: Minimum data sites for a natural cubic spline on one axis.
_MIN_SPLINE_SITES = 4


class SurfaceBackendError(CitiVelocityError, ValueError):
    """The requested surface interpolation cannot be built from these nodes."""


# ------------------------------------------------------------------ #
#                        surface backends                            #
# ------------------------------------------------------------------ #


class _Interp1D:
    """One-dimensional interpolator that is EXACT at its data sites.

    ``method='spline'`` uses :class:`rateslib.PPSplineF64` with a natural cubic
    knot sequence; ``method='linear'`` uses :func:`numpy.interp`. Both reproduce
    the input at the nodes, which is what makes the cube's round-trip test
    meaningful.
    """

    def __init__(self, xs: Sequence[float], ys: Sequence[float], *, method: str = "spline"):
        x = np.asarray(xs, dtype=float)
        y = np.asarray(ys, dtype=float)
        if x.size != y.size:
            raise SurfaceBackendError(f"axis length {x.size} != value length {y.size}.")
        if x.size == 0:
            raise SurfaceBackendError("cannot interpolate an empty axis.")
        if np.any(np.diff(x) <= 0.0):
            raise SurfaceBackendError(
                f"interpolation axis is not strictly increasing: {list(x)}. Sort the cube axes "
                "with catalog.sort_tenors() before building."
            )
        self.x = x
        self.y = y
        if method == "spline" and x.size >= _MIN_SPLINE_SITES:
            self.method = "spline"
            knots = [float(x[0])] * 4 + [float(v) for v in x[1:-1]] + [float(x[-1])] * 4
            self._spline = rl.PPSplineF64(k=4, t=knots)
            self._spline.csolve(
                [float(x[0])] + [float(v) for v in x] + [float(x[-1])],
                [0.0] + [float(v) for v in y] + [0.0],
                2,
                2,
                False,
            )
        else:
            self.method = "linear"
            self._spline = None

    def __call__(self, at: float) -> float:
        value = float(at)
        lo, hi = float(self.x[0]), float(self.x[-1])
        if value < lo or value > hi:
            # Flat extrapolation. A cubic extrapolated past its last knot leaves
            # the plausible range within a couple of years and does it smoothly
            # enough to look intentional.
            value = min(max(value, lo), hi)
        if self._spline is not None:
            return float(self._spline.ppev_single(value))
        return float(np.interp(value, self.x, self.y))


class _TensorSurface:
    """Tensor-product interpolation over ``(expiry_years, tenor_years)``.

    Exact at every node because both stages are exact at their own data sites.
    Kept behind a one-method interface so an ``IRSplineCube``/``IRSabrCube``
    backend can be dropped in later without touching
    :class:`CitiVeloNormalVolCube`.
    """

    def __init__(
        self,
        *,
        x: Sequence[float],
        y: Sequence[float],
        z: np.ndarray,
        method: str = "spline",
    ):
        self.x = np.asarray(x, dtype=float)  # expiry years
        self.y = np.asarray(y, dtype=float)  # tenor years
        self.z = np.asarray(z, dtype=float)  # [expiry, tenor]
        self._rows = [_Interp1D(self.y, self.z[i, :], method=method) for i in range(self.z.shape[0])]
        self._method = method
        self._col_cache: Dict[float, _Interp1D] = {}
        self.x_method = "spline" if (method == "spline" and self.x.size >= _MIN_SPLINE_SITES) else "linear"
        self.y_method = self._rows[0].method if self._rows else "linear"

    def __call__(self, expiry_years: float, tenor_years_: float) -> float:
        key = float(tenor_years_)
        column = self._col_cache.get(key)
        if column is None:
            values = [row(key) for row in self._rows]
            column = _Interp1D(self.x, values, method=self._method)
            self._col_cache[key] = column
        return column(float(expiry_years))


# ------------------------------------------------------------------ #
#                              the cube                              #
# ------------------------------------------------------------------ #


class CitiVeloNormalVolCube:
    """A normal (Bachelier) swaption cube over Citi quotes, priced with rateslib.

    Volatilities in and out are **annualised normal vol in basis points**;
    forwards and strikes are decimals; premia are in currency units for the
    notional given.

    Parameters
    ----------
    cube
        The source :class:`SwaptionCubeData`. Must be ``measure='NORMAL'``.
    rl_curve
        The solved curve the underlying swaps price off. Accepted forms:
        a bare :class:`rateslib.Curve`; the repo's ``RLCurveBase`` (any object
        exposing ``rl_pricing_curve``); or a ``(forecast, discount)`` pair.
    interpolation
        ``'spline'`` (default) or ``'linear'``. An axis with fewer than four
        nodes falls back to linear whatever this says - see
        :attr:`interpolation_used`.
    citi_index
        Override the Citi OIS index whose conventions define the underlying swap.
        Defaults per currency; KRW has none and must be given one.
    notional
        Default notional for :meth:`price` and :meth:`vega`.

    Attributes
    ----------
    interpolation_used
        ``{'expiry': 'spline'|'linear', 'tenor': ..., 'offset': ...}`` - what was
        ACTUALLY used per axis, not what was requested.
    """

    def __init__(
        self,
        *,
        cube: SwaptionCubeData,
        rl_curve: Any,
        interpolation: str = "spline",
        citi_index: Optional[str] = None,
        notional: float = 1e8,
        disc_curve: Any = None,
    ):
        cube.validate()
        if cube.measure.upper() != "NORMAL":
            raise ValueError(
                f"cube.measure={cube.measure!r}; CitiVeloNormalVolCube is a Bachelier cube and "
                "only 'NORMAL' quotes belong in it."
            )
        if str(interpolation).lower() not in {"spline", "linear"}:
            raise ValueError(f"interpolation must be 'spline' or 'linear', got {interpolation!r}.")

        self.cube = cube
        self.as_of = pd.Timestamp(cube.as_of).to_pydatetime()
        self.notional = float(notional)
        self._interpolation = str(interpolation).lower()

        self.forecast_curve, self.disc_curve = _resolve_curves(rl_curve, disc_curve)
        self.convention = _convention_for_cube(cube, citi_index=citi_index)
        self.calendar = self.convention.rl_calendar_object()
        if self.convention.approximate:
            _logger.warning(
                "Underlying swap conventions for %s are %s, not rateslib-supplied: %s",
                self.convention.citi_index,
                self.convention.provenance,
                self.convention.note or "see CurveConvention.note",
            )

        self._expiries = cube.expiries()
        self._tenors = cube.tenors()
        self._offsets = cube.offsets()
        self._x = np.array([tenor_years(e) for e in self._expiries], dtype=float)
        self._y = np.array([tenor_years(t) for t in self._tenors], dtype=float)
        self._o = np.array(self._offsets, dtype=float)

        self._surfaces: Dict[float, _TensorSurface] = {}
        for off in self._offsets:
            z = np.array(
                [[cube.vol(e, t, off) for t in self._tenors] for e in self._expiries], dtype=float
            )
            self._surfaces[off] = _TensorSurface(x=self._x, y=self._y, z=z, method=self._interpolation)

        any_surface = self._surfaces[self._offsets[0]]
        offset_method = (
            "spline" if (self._interpolation == "spline" and len(self._offsets) >= _MIN_SPLINE_SITES) else "linear"
        )
        self.interpolation_used: Dict[str, str] = {
            "expiry": any_surface.x_method,
            "tenor": any_surface.y_method,
            "offset": offset_method,
        }
        if self.interpolation_used != {k: self._interpolation for k in self.interpolation_used}:
            _logger.info(
                "CitiVeloNormalVolCube: interpolation=%r requested, actually used %s "
                "(an axis with fewer than %d nodes cannot carry a cubic spline).",
                self._interpolation,
                self.interpolation_used,
                _MIN_SPLINE_SITES,
            )

        self._swap_cache: Dict[Tuple[str, str], Tuple[float, float, float]] = {}

    # -- underlying -----------------------------------------------------

    def expiry_date(self, expiry: str) -> datetime.datetime:
        """The option expiry date for a tenor token, rolled modified-following."""
        return rl.add_tenor(self.as_of, str(expiry), "MF", self.calendar)

    def effective_date(self, expiry: str) -> datetime.datetime:
        """The underlying swap's start: expiry plus the curve's spot lag."""
        return rl.add_tenor(
            self.expiry_date(expiry), f"{int(self.convention.spot_lag)}b", "F", self.calendar
        )

    def time_to_expiry(self, expiry: str) -> float:
        """ACT/365F year fraction from ``as_of`` to the option expiry date."""
        return float(rl.dcf(self.as_of, self.expiry_date(expiry), EXPIRY_DAY_COUNT))

    def _swap(self, expiry: str, tenor: str) -> Any:
        kwargs: Dict[str, Any] = dict(
            effective=self.effective_date(expiry),
            termination=str(tenor),
            notional=self.notional,
            curves=[self.forecast_curve, self.disc_curve],
        )
        if self.convention.rl_spec:
            kwargs["spec"] = self.convention.rl_spec
        else:
            # No rateslib named spec for this currency; the schedule below comes
            # from CurveConvention, whose provenance field already says it is
            # market standard rather than library supplied.
            kwargs.update(
                frequency=self.convention.fixed_frequency,
                convention=self.convention.convention,
                calendar=self.calendar,
                modifier="mf",
                currency=self.convention.currency.lower(),
                leg2_frequency=self.convention.fixed_frequency,
                leg2_convention=self.convention.convention,
                leg2_fixing_method="rfr_payment_delay",
            )
        return rl.IRS(**kwargs)

    def _forward_and_annuity(self, expiry: str, tenor: str) -> Tuple[float, float, float]:
        """``(forward decimal, annuity per unit notional, time to expiry)``."""
        key = (str(expiry), str(tenor))
        hit = self._swap_cache.get(key)
        if hit is not None:
            return hit
        swap = self._swap(expiry, tenor)
        rate = float(swap.rate(curves=[self.forecast_curve, self.disc_curve])) / 100.0
        delta = float(
            swap.analytic_delta(curves=[self.forecast_curve, self.disc_curve])
        )
        annuity = delta * 1e4 / self.notional
        if not math.isfinite(rate) or not math.isfinite(annuity) or annuity <= 0.0:
            raise CitiVelocityError(
                f"rateslib produced a degenerate underlying for {expiry}x{tenor}: forward={rate}, "
                f"annuity={annuity}. The curve is unsolved or does not span the swap - check the "
                "curve's node range against the 30Y x 30Y corner of the cube."
            )
        out = (rate, annuity, self.time_to_expiry(expiry))
        self._swap_cache[key] = out
        return out

    def forward(self, expiry: str, tenor: str) -> float:
        """The forward par swap rate, DECIMAL, from the curve (not from Citi)."""
        return self._forward_and_annuity(expiry, tenor)[0]

    def annuity(self, expiry: str, tenor: str) -> float:
        """The forward fixed-leg annuity per unit notional, in years."""
        return self._forward_and_annuity(expiry, tenor)[1]

    # -- the surface ----------------------------------------------------

    def _smile_values(self, expiry_years: float, tenor_years_: float) -> np.ndarray:
        return np.array(
            [self._surfaces[o](expiry_years, tenor_years_) for o in self._offsets], dtype=float
        )

    def normal_vol(
        self,
        expiry: str,
        tenor: str,
        strike: Optional[float] = None,
        offset_bp: float = 0.0,
    ) -> float:
        """Normal vol in BASIS POINTS at ``(expiry, tenor)``.

        Parameters
        ----------
        expiry, tenor
            Tenor tokens. They need NOT be cube nodes; anything inside the axis
            range is interpolated and anything outside is held flat.
        strike
            Absolute strike, decimal. When given, the strike offset is measured
            from :meth:`forward` - i.e. from the LOCAL curve's forward, not from
            Citi's own ATMF. See the module docstring.
        offset_bp
            Signed offset in bp, used when ``strike`` is None.
        """
        ex = tenor_years(str(expiry))
        te = tenor_years(str(tenor))
        if strike is not None:
            offset_bp = (float(strike) - self.forward(expiry, tenor)) * 1e4
        smile = self._smile_values(ex, te)
        if len(self._offsets) == 1:
            return float(smile[0])
        return float(_Interp1D(self._o, smile, method=self._interpolation)(float(offset_bp)))

    def smile(self, expiry: str, tenor: str) -> Dict[float, float]:
        """``{signed offset bp: normal vol bp}`` at one point, ascending."""
        ex = tenor_years(str(expiry))
        te = tenor_years(str(tenor))
        return {float(o): float(v) for o, v in zip(self._offsets, self._smile_values(ex, te))}

    def implied_vol_surface_frame(
        self,
        *,
        offset_bp: float = 0.0,
        expiries: Optional[Sequence[str]] = None,
        tenors: Optional[Sequence[str]] = None,
    ) -> pd.DataFrame:
        """The interpolated surface at one offset, ``index=expiry``, ``cols=tenor``.

        Defaults to the cube's own axes, where it reproduces the input exactly.
        """
        exps = list(expiries) if expiries else self._expiries
        tens = list(tenors) if tenors else self._tenors
        data = [[self.normal_vol(e, t, offset_bp=offset_bp) for t in tens] for e in exps]
        frame = pd.DataFrame(data, index=exps, columns=tens, dtype=float)
        frame.index.name = "expiry"
        frame.columns.name = "tenor"
        return frame

    def to_frame(self) -> pd.DataFrame:
        """Long form with the rateslib-side underlying attached to every node."""
        rows: List[Dict[str, Any]] = []
        for expiry in self._expiries:
            forward_cache: Dict[str, Tuple[float, float, float]] = {}
            for tenor in self._tenors:
                fwd, ann, tte = self._forward_and_annuity(expiry, tenor)
                forward_cache[tenor] = (fwd, ann, tte)
                for off in self._offsets:
                    rows.append(
                        {
                            "expiry": expiry,
                            "tenor": tenor,
                            "offset_bp": off,
                            "vol_bp": self.cube.vol(expiry, tenor, off),
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
        """Bachelier premium of a European swaption, in currency units.

        ``notional * annuity * bachelier(strike, forward, sigma, T)`` with the
        annuity already discounted, so the Bachelier discount factor is 1.

        Parameters
        ----------
        right
            ``'payer'``/``'call'``/``'C'`` or ``'receiver'``/``'put'``/``'P'``.
        """
        token = _right(right)
        fwd, ann, tte = self._forward_and_annuity(expiry, tenor)
        vol = self.normal_vol(expiry, tenor, strike=float(strike)) / 1e4
        size = self.notional if notional is None else float(notional)
        return float(size * ann * bachelier_price(token, float(strike), fwd, vol, tte, 1.0))

    def vega(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        right: str = "payer",
        notional: Optional[float] = None,
    ) -> float:
        """Premium change per **1 bp** of normal vol, in currency units.

        Uses :func:`Query.Base.bachelier.bachelier_greeks_fd`, which prefers
        QuantLib's ``BachelierCalculator`` and falls back to finite differences.
        """
        token = _right(right)
        fwd, ann, tte = self._forward_and_annuity(expiry, tenor)
        vol = self.normal_vol(expiry, tenor, strike=float(strike)) / 1e4
        size = self.notional if notional is None else float(notional)
        _d, _g, vega_per_unit_vol, _t = bachelier_greeks_fd(
            right=token, strike=float(strike), forward=fwd, vol_normal=vol, tte=tte, discount=1.0
        )
        return float(size * ann * vega_per_unit_vol * 1e-4)

    def implied_normal_vol(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        premium: float,
        right: str = "payer",
        notional: Optional[float] = None,
    ) -> float:
        """Invert :meth:`price`: premium -> normal vol in bp."""
        token = _right(right)
        fwd, ann, tte = self._forward_and_annuity(expiry, tenor)
        size = self.notional if notional is None else float(notional)
        unit_price = float(premium) / (size * ann)
        return float(implied_normal_vol(token, float(strike), fwd, tte, unit_price, 1.0)) * 1e4

    def __repr__(self) -> str:
        return (
            f"CitiVeloNormalVolCube({self.cube.currency} {self.cube.as_of}, "
            f"{len(self._expiries)}x{len(self._tenors)}x{len(self._offsets)}, "
            f"interp={self.interpolation_used}, idx={self.convention.citi_index})"
        )


# ------------------------------------------------------------------ #
#                              helpers                               #
# ------------------------------------------------------------------ #


def _right(token: str) -> str:
    key = str(token).strip().upper()
    if key not in SWAPTION_RIGHTS:
        raise ValueError(
            f"Unknown swaption right {token!r}. Accepted: {', '.join(sorted(SWAPTION_RIGHTS))}. "
            "A payer is a CALL on the swap rate."
        )
    return SWAPTION_RIGHTS[key]


def _resolve_curves(rl_curve: Any, disc_curve: Any = None) -> Tuple[Any, Any]:
    """Accept a Curve, an ``RLCurveBase``-shaped object, or a ``(fwd, disc)`` pair."""
    if isinstance(rl_curve, (tuple, list)) and len(rl_curve) == 2:
        return rl_curve[0], rl_curve[1] if disc_curve is None else disc_curve
    forecast = getattr(rl_curve, "rl_pricing_curve", None)
    if forecast is not None:
        return forecast, (disc_curve if disc_curve is not None else forecast)
    if hasattr(rl_curve, "__getitem__") and hasattr(rl_curve, "nodes"):
        return rl_curve, (disc_curve if disc_curve is not None else rl_curve)
    raise TypeError(
        f"rl_curve must be a rateslib Curve, an RLCurveBase-shaped object with "
        f"`rl_pricing_curve`, or a (forecast, discount) pair; got {type(rl_curve).__name__}."
    )


def _convention_for_cube(
    cube: SwaptionCubeData, *, citi_index: Optional[str] = None
) -> CurveConvention:
    token = str(citi_index).upper() if citi_index else VOL_CCY_DEFAULT_OIS_INDEX.get(cube.currency.upper())
    if not token:
        raise CitiVelocityError(
            f"No default Citi OIS index for vol currency {cube.currency!r} "
            f"(known: {', '.join(sorted(VOL_CCY_DEFAULT_OIS_INDEX))}). "
            "RATES.VOL.KRW has no matching entry in CITI_OIS_CONVENTIONS, so the underlying swap "
            "conventions cannot be inferred - pass citi_index= explicitly."
        )
    return conventions_for(token)


def build_rl_vol_cube(
    *,
    cube: SwaptionCubeData,
    rl_curve: Any,
    interpolation: str = "spline",
    citi_index: Optional[str] = None,
    notional: float = 1e8,
    disc_curve: Any = None,
) -> CitiVeloNormalVolCube:
    """Build a :class:`CitiVeloNormalVolCube`.

    Parameters
    ----------
    cube
        Normal-vol cube data.
    rl_curve
        Solved rateslib curve, ``RLCurveBase``, or ``(forecast, discount)``.
    interpolation
        ``'spline'`` or ``'linear'``; see
        :attr:`CitiVeloNormalVolCube.interpolation_used` for what was really used.

    Returns
    -------
    CitiVeloNormalVolCube
    """
    return CitiVeloNormalVolCube(
        cube=cube,
        rl_curve=rl_curve,
        interpolation=interpolation,
        citi_index=citi_index,
        notional=notional,
        disc_curve=disc_curve,
    )

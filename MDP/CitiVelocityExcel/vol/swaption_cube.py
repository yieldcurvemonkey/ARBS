r"""One Citi Velocity swaption cube, four pricing backends, one API.

Before this module the package had three pricers with three different call
signatures and no common entry point:

===================================  =========================================
``CitiVeloNormalVolCube``            ``PPSplineF64`` + ``Query.Base.bachelier``
``NativeSwaptionCube``               ``rl.IRSplineCube`` + ``rl.IRSCall``
``QLSwaptionCube``                   ``ql.InterpolatedSwaptionVolatilityCube``
                                     - a surface, with no pricer at all
===================================  =========================================

They still exist and still behave exactly as they did; they are the internals
this class delegates to. What is new is that there is now one object to hold,
one vocabulary to learn, and a QuantLib path that actually prices a
``ql.Swaption``.

    >>> cube = build_citivelo_swaption_cube(          # doctest: +SKIP
    ...     cube=cube_data, rl_curve=rl_curve, ql_curve=ql_curve, backend="rl-native")
    >>> k = cube.forward("1Y", "10Y") + 25e-4
    >>> cube.price("1Y", "10Y", k, right="payer")     # doctest: +SKIP
    1857854.33
    >>> cube.with_backend("ql").price("1Y", "10Y", k, right="payer")   # doctest: +SKIP
    1857856.01

Backends
--------
``rl-native``  :class:`~MDP.CitiVelocityExcel.vol.rl_native_cube.NativeSwaptionCube`.
               Carries AD risk back to the curve and the vol nodes and can sit in
               a ``rateslib.Solver``. Needs rateslib >= 2.7.0.
``rl-hand``    :class:`~MDP.CitiVelocityExcel.vol.rl_cube.CitiVeloNormalVolCube`.
               Assembled from primitives available in every supported rateslib.
``ql``         :class:`~MDP.CitiVelocityExcel.vol.ql_pricing.QLSwaptionPricer` -
               ``ql.Swaption`` + ``ql.BachelierSwaptionEngine`` over the
               interpolated cube.
``ql-sabr``    the same, over ``ql.SabrSwaptionVolatilityCube``. A SABR cube is a
               **fit**: it does not reproduce its own input nodes, and the node
               round-trip assertion is skipped for it.

Which are available depends on what you handed in: the rateslib backends need
``rl_curve``, the QuantLib ones need ``ql_curve``. :attr:`backends_available`
says which, and :meth:`with_backend` gives you a sibling that shares the same
cube data and the same curves - so one object really does serve both libraries,
and the spot check can ask it for both without rebuilding anything.

Units, stated once
------------------
Volatilities in and out are annualised **normal vol in basis points**. Forwards
and strikes are **decimals**. Premia are currency units for the notional given.
:meth:`price` is present-valued to ``as_of``; :meth:`premium` is the same cash on
its payment date, undiscounted.

The strike axis is anchored on the underlying's own forward
-----------------------------------------------------------
``normal_vol(..., offset_bp=o)`` reads the smile at signed offset ``o``, which is
exactly how Citi publishes it (``OTM_RFR.NORMALABSOLUTE.OTM_M25`` is the vol 25 bp
below the forward) and is forward-invariant on every backend.
``normal_vol(..., strike=k)`` converts ``k`` into that offset using **this
backend's** :meth:`forward`, i.e. the par rate of the swaption's own underlying.

Citi measures its offsets from *Citi's* forward. On the recorded 2026-08-06
snapshot ours agrees with Citi's published ``RATES.OIS.USD_SOFR.FWD.<e>.<t>`` to
within 0.26 bp across six points. That is a property of the curve, not of this
class, and it must be re-checked whenever the curve source changes: a gap slides
the whole smile along the strike axis without changing a single node volatility.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.vol.cube_data import SwaptionCubeData

__all__ = [
    "BACKENDS",
    "BACKEND_LIBRARY",
    "CitiVeloSwaptionCube",
    "UnavailableBackendError",
    "build_citivelo_swaption_cube",
    "normalise_backend",
    "unwrap_rl_curve",
]

_logger = logging.getLogger(__name__)

#: Every backend this class can drive, in the order they are preferred by
#: ``backend='auto'``.
BACKENDS: tuple[str, ...] = ("rl-native", "rl-hand", "ql", "ql-sabr")

_BACKEND_ALIASES: Dict[str, str] = {
    "rl-native": "rl-native",
    "native": "rl-native",
    "rateslib": "rl-native",
    "rl": "rl-native",
    "rl-hand": "rl-hand",
    "hand": "rl-hand",
    "ql": "ql",
    "quantlib": "ql",
    "ql-interpolated": "ql",
    "ql-sabr": "ql-sabr",
    "sabr": "ql-sabr",
}

#: Which library each backend needs a curve from. Public because the spot check
#: pairs backends ACROSS libraries - a cross-inversion between two rateslib
#: backends would share an annuity and prove nothing.
BACKEND_LIBRARY: Dict[str, str] = {
    "rl-native": "rl",
    "rl-hand": "rl",
    "ql": "ql",
    "ql-sabr": "ql",
}

#: Historical private spelling, kept so nothing that already imported it breaks.
_BACKEND_LIBRARY = BACKEND_LIBRARY


class UnavailableBackendError(CitiVelocityError):
    """The requested backend has no curve, or its library is too old."""


def unwrap_rl_curve(rl_curve: Any) -> Any:
    """Accept the repo's ``RLIRSwapCurve`` wrapper as well as a bare curve.

    ``IRSwapsMDP(source="citivelo_excel_rl")`` - Citi's own warmed SOFR curve -
    returns an ``RLIRSwapCurve``, which is the natural thing for a caller to hand
    straight to this class. It exposes the ``rateslib.Curve`` through a
    ``handle()`` METHOD and satisfies none of the duck tests
    ``rl_cube._resolve_curves`` makes (``rl_pricing_curve``, or ``nodes`` plus
    ``__getitem__``), so it used to raise a TypeError whose message listed three
    shapes and not the one that had just been passed.

    Only unwrapped when the wrapper does not already resolve and what comes back
    looks like a rateslib curve; a ``QLIRSwapCurve``'s ``handle()`` returns a
    QuantLib object and must not be routed here.
    """
    if rl_curve is None or isinstance(rl_curve, (tuple, list)):
        return rl_curve
    if getattr(rl_curve, "rl_pricing_curve", None) is not None:
        return rl_curve
    if hasattr(rl_curve, "__getitem__") and hasattr(rl_curve, "nodes"):
        return rl_curve
    handle = getattr(rl_curve, "handle", None)
    if not callable(handle):
        return rl_curve
    try:
        inner = handle()
    except Exception:  # noqa: BLE001 - a wrapper that cannot say is left alone
        return rl_curve
    if inner is not None and hasattr(inner, "__getitem__") and hasattr(inner, "nodes"):
        return inner
    return rl_curve


def normalise_backend(backend: str) -> str:
    """Canonical backend token, accepting the obvious spellings.

    Raises
    ------
    ValueError
        Naming every accepted token. ``'auto'`` is resolved by the constructor,
        which is the only place that knows which curves were supplied.
    """
    token = str(backend).strip().lower().replace("_", "-")
    if token == "auto":
        return "auto"
    try:
        return _BACKEND_ALIASES[token]
    except KeyError:
        raise ValueError(
            f"Unknown backend {backend!r}. Accepted: {', '.join(sorted(set(_BACKEND_ALIASES)))} "
            "or 'auto'."
        ) from None


class CitiVeloSwaptionCube:
    """A Citi swaption cube priced through one of four backends.

    Parameters
    ----------
    cube
        The source :class:`SwaptionCubeData`, ``measure='NORMAL'``. Unchanged -
        it is still the data layer, and it is still where units, raggedness and
        axis order are enforced.
    rl_curve
        The solved rateslib curve for the ``rl-*`` backends: a bare
        :class:`rateslib.Curve`, an ``RLCurveBase``-shaped object (anything with
        ``rl_pricing_curve``), an ``RLIRSwapCurve`` (``handle()``), or a
        ``(forecast, discount)`` pair.
    ql_curve
        The QuantLib curve for the ``ql*`` backends: a ``QLOisCurve``, a
        ``QLIRSwapCurve``, a ``ql.YieldTermStructureHandle`` or a bare
        ``ql.YieldTermStructure``.
    backend
        One of :data:`BACKENDS`, or ``'auto'`` - the first entry of
        :data:`BACKENDS` whose curve was supplied and whose library is present.
    citi_index
        Override the Citi OIS index whose conventions define the underlying swap.
        Defaults per currency; KRW has none and must be given one.
    notional
        Default notional for :meth:`price`, :meth:`premium`, :meth:`vega`.
    verify
        Read every node back out of the built surface and raise unless it
        reproduces its input. Leave it True - a mis-parameterised smile prices
        without complaint.

    Attributes
    ----------
    backend
        The active backend token.
    inner
        The delegate object, for backend-specific work
        (``NativeSwaptionCube.greeks``, ``QLSwaptionPricer.forward_diagnostics``).
    backends_available
        Which backends this instance can switch to with :meth:`with_backend`.
    """

    def __init__(
        self,
        *,
        cube: SwaptionCubeData,
        rl_curve: Any = None,
        ql_curve: Any = None,
        backend: str = "auto",
        citi_index: Optional[str] = None,
        notional: float = 1e8,
        rl_disc_curve: Any = None,
        interpolation: str = "spline",
        spline_order: Optional[int] = None,
        verify: bool = True,
        vol_source: str = "cube",
        _siblings: Optional[Dict[str, "CitiVeloSwaptionCube"]] = None,
    ):
        cube.validate()
        if cube.measure.upper() != "NORMAL":
            raise ValueError(
                f"cube.measure={cube.measure!r}; every backend here is Bachelier and only "
                "'NORMAL' quotes belong in the cube."
            )
        self.cube = cube
        self.as_of: datetime.date = cube.as_of
        self.notional = float(notional)
        self.rl_curve = unwrap_rl_curve(rl_curve)
        self.ql_curve = ql_curve
        self.rl_disc_curve = unwrap_rl_curve(rl_disc_curve)
        self.interpolation = str(interpolation)
        self.spline_order = spline_order
        self.verify = bool(verify)
        self.vol_source = str(vol_source)

        from MDP.CitiVelocityExcel.vol.rl_cube import convention_for_cube

        self.convention = convention_for_cube(cube, citi_index=citi_index)
        self.citi_index = self.convention.citi_index

        self.backends_available = self._resolve_available()
        self.backend = self._resolve_backend(backend)
        self.inner = self._build(self.backend)
        # Siblings share the dict, so a->b->a returns the original instance and
        # every backend's caches (forwards, annuities, shifted cubes) are built
        # at most once per curve set.
        self._siblings: Dict[str, "CitiVeloSwaptionCube"] = (
            _siblings if _siblings is not None else {}
        )
        self._siblings[self.backend] = self

    # ------------------------------------------------------------------ #
    #                          backend plumbing                          #
    # ------------------------------------------------------------------ #

    def _resolve_available(self) -> List[str]:
        from MDP.CitiVelocityExcel.vol.rl_native_cube import RATESLIB_NATIVE_AVAILABLE

        out: List[str] = []
        for name in BACKENDS:
            library = BACKEND_LIBRARY[name]
            if library == "rl" and self.rl_curve is None:
                continue
            if library == "ql" and self.ql_curve is None:
                continue
            if name == "rl-native" and not RATESLIB_NATIVE_AVAILABLE:
                continue
            out.append(name)
        return out

    def _resolve_backend(self, backend: str) -> str:
        token = normalise_backend(backend)
        if token == "auto":
            if not self.backends_available:
                raise UnavailableBackendError(
                    "No backend is available: pass rl_curve= for the rateslib backends, "
                    "ql_curve= for the QuantLib ones, or both."
                )
            return self.backends_available[0]
        if token not in self.backends_available:
            library = BACKEND_LIBRARY[token]
            if token == "rl-native":
                from MDP.CitiVelocityExcel.vol.rl_native_cube import RATESLIB_NATIVE_AVAILABLE

                if not RATESLIB_NATIVE_AVAILABLE:
                    raise UnavailableBackendError(
                        "backend='rl-native' needs rateslib >= 2.7.0 (IRSplineCube, IRSCall). "
                        "This environment has an older rateslib - use backend='rl-hand', which "
                        "is assembled from primitives available in every supported version."
                    )
            raise UnavailableBackendError(
                f"backend={token!r} needs a {library} curve and none was given. "
                f"Available here: {self.backends_available or '(none)'}. "
                f"Pass {'rl_curve=' if library == 'rl' else 'ql_curve='}."
            )
        return token

    def _build(self, backend: str) -> Any:
        if backend == "rl-native":
            from MDP.CitiVelocityExcel.vol.rl_native_cube import NativeSwaptionCube

            return NativeSwaptionCube(
                cube=self.cube,
                rl_curve=self.rl_curve,
                spline_order=self.spline_order
                if self.spline_order is not None
                else (None if self.interpolation == "spline" else 2),
                citi_index=self.citi_index,
                notional=self.notional,
                disc_curve=self.rl_disc_curve,
                verify=self.verify,
            )
        if backend == "rl-hand":
            from MDP.CitiVelocityExcel.vol.rl_cube import CitiVeloNormalVolCube

            return CitiVeloNormalVolCube(
                cube=self.cube,
                rl_curve=self.rl_curve,
                interpolation=self.interpolation,
                citi_index=self.citi_index,
                notional=self.notional,
                disc_curve=self.rl_disc_curve,
            )
        if backend in {"ql", "ql-sabr"}:
            from MDP.CitiVelocityExcel.vol.ql_pricing import QLSwaptionPricer

            return QLSwaptionPricer(
                cube=self.cube,
                ql_curve=self.ql_curve,
                citi_index=self.citi_index,
                notional=self.notional,
                sabr=(backend == "ql-sabr"),
                vol_source=self.vol_source,
                # A SABR cube fits rather than interpolates, so it does not
                # reproduce its own nodes and the ordering assertion would fire
                # on a correctly built object. build_ql_swaption_cube already
                # skips it for sabr=True and logs that it did.
                check_ordering=self.verify,
            )
        raise UnavailableBackendError(f"No builder for backend {backend!r}.")

    def with_backend(self, backend: str) -> "CitiVeloSwaptionCube":
        """A sibling on the same cube and the same curves, in another backend.

        Built once and cached, so ``cube.with_backend('ql')`` repeated in a loop
        costs one QuantLib cube, not one per call.
        """
        token = self._resolve_backend(backend)
        hit = self._siblings.get(token)
        if hit is not None:
            return hit
        sibling = CitiVeloSwaptionCube(
            cube=self.cube,
            rl_curve=self.rl_curve,
            ql_curve=self.ql_curve,
            backend=token,
            citi_index=self.citi_index,
            notional=self.notional,
            rl_disc_curve=self.rl_disc_curve,
            interpolation=self.interpolation,
            spline_order=self.spline_order,
            verify=self.verify,
            vol_source=self.vol_source,
            _siblings=self._siblings,
        )
        return sibling

    @property
    def is_rateslib(self) -> bool:
        return BACKEND_LIBRARY[self.backend] == "rl"

    @property
    def is_quantlib(self) -> bool:
        return BACKEND_LIBRARY[self.backend] == "ql"

    @property
    def native(self) -> Any:
        """The ``rl.IRSplineCube``, for a ``Solver``. ``rl-native`` only."""
        cube = getattr(self.inner, "native", None)
        if cube is None:
            raise UnavailableBackendError(
                f"backend={self.backend!r} has no rl.IRSplineCube. Use "
                "with_backend('rl-native').native."
            )
        return cube

    @property
    def ql_handle(self) -> Any:
        """The ``ql.SwaptionVolatilityStructureHandle``, for a QuantLib engine.

        Available whenever a QuantLib curve was supplied, whatever the active
        backend - this is what ``source='CITIVELO-QL'`` hands to
        ``ql.BachelierSwaptionEngine``.
        """
        if self.is_quantlib:
            return self.inner.ql_cube.handle
        if "ql" in self.backends_available:
            return self.with_backend("ql").inner.ql_cube.handle
        raise UnavailableBackendError(
            "No QuantLib surface: pass ql_curve= to build one."
        )

    # ------------------------------------------------------------------ #
    #                            the underlying                          #
    # ------------------------------------------------------------------ #

    def expiry_date(self, expiry: str) -> datetime.date:
        """The option expiry date this backend assigns to a tenor token."""
        value = self.inner.expiry_date(str(expiry))
        return value.date() if isinstance(value, datetime.datetime) else value

    def forward(self, expiry: str, tenor: str) -> float:
        """The forward par swap rate of the underlying, DECIMAL, from the curve."""
        return float(self.inner.forward(str(expiry), str(tenor)))

    def annuity(self, expiry: str, tenor: str) -> float:
        """The discounted fixed-leg annuity per unit notional, in years."""
        return float(self.inner.annuity(str(expiry), str(tenor)))

    def time_to_expiry(self, expiry: str) -> float:
        """ACT/365F year fraction from ``as_of`` to expiry. Same basis everywhere."""
        return float(self.inner.time_to_expiry(str(expiry)))

    def payment_date(self, expiry: str) -> datetime.date:
        """When the premium settles: expiry plus the index's payment lag.

        This is rateslib's convention for ``rate(metric='Premium')``, not the
        market's upfront-on-trade-date one - it is chosen so the two backends'
        premia are the same quantity and can be diffed. Use :meth:`price` for a
        present value.
        """
        import rateslib as rl

        from MDP.CitiVelocityExcel.curves.ql_builder import PAYMENT_LAG_BY_INDEX

        lag = int(PAYMENT_LAG_BY_INDEX[self.convention.citi_index])
        stamp = rl.add_tenor(
            pd.Timestamp(self.expiry_date(expiry)).to_pydatetime(),
            f"{lag}b",
            "F",
            self.convention.rl_calendar_object(),
        )
        return stamp.date() if isinstance(stamp, datetime.datetime) else stamp

    def payment_discount(self, expiry: str) -> float:
        """Discount factor from :meth:`payment_date` back to ``as_of``."""
        if self.is_quantlib:
            return float(self.inner.payment_discount(str(expiry)))
        curve = getattr(self.inner, "disc_curve", None) or getattr(
            self.inner, "forecast_curve", None
        )
        if curve is None:
            raise UnavailableBackendError("No discount curve on this backend.")
        return float(curve[pd.Timestamp(self.payment_date(expiry)).to_pydatetime()])

    # ------------------------------------------------------------------ #
    #                              the surface                           #
    # ------------------------------------------------------------------ #

    def normal_vol(
        self,
        expiry: str,
        tenor: str,
        strike: Optional[float] = None,
        offset_bp: float = 0.0,
    ) -> float:
        """Normal vol in BASIS POINTS. See the module docstring for the anchor."""
        return float(
            self.inner.normal_vol(str(expiry), str(tenor), strike=strike, offset_bp=float(offset_bp))
        )

    def smile(self, expiry: str, tenor: str) -> Dict[float, float]:
        """``{signed offset bp: normal vol bp}`` at one point, ascending."""
        return {float(k): float(v) for k, v in self.inner.smile(str(expiry), str(tenor)).items()}

    def volatility(
        self,
        option_time: float,
        swap_length: float,
        strike: float,
        extrapolate: bool = True,
    ) -> float:
        """``ql.SwaptionVolatilityStructure`` read signature. DECIMAL vol.

        Kept so ``Query/IRSwaptions/pricer.py::_surface_model_vol`` works against
        this object unchanged. It is served by the QuantLib surface, which
        resolves option time to an option date and computes its own ``atmStrike``
        internally - there is deliberately no year-to-date reconstruction here,
        because an approximate expiry date moves the strike offset and therefore
        the vol.
        """
        if self.is_quantlib:
            return float(self.inner.volatility(option_time, swap_length, strike, extrapolate))
        if "ql" in self.backends_available:
            return self.with_backend("ql").volatility(option_time, swap_length, strike, extrapolate)
        raise UnavailableBackendError(
            "volatility(option_time, swap_length, strike) is served by the QuantLib surface, "
            "which turns option TIME into an option DATE itself. Pass ql_curve= to build one, "
            "or use normal_vol(expiry, tenor, ...) with tenor tokens."
        )

    def volatility_at_point(self, option_time: float, swap_length: float, strike: float) -> float:
        """The repo's vol-cube protocol (MONKEYCUBE, GSQUANT_MC_ENHANCED). DECIMAL."""
        return self.volatility(option_time, swap_length, strike)

    def implied_vol_surface_frame(
        self,
        *,
        offset_bp: float = 0.0,
        expiries: Optional[Sequence[str]] = None,
        tenors: Optional[Sequence[str]] = None,
    ) -> pd.DataFrame:
        """The surface at one offset, ``index=expiry``, ``cols=tenor``."""
        exps = list(expiries) if expiries else self.cube.expiries()
        tens = list(tenors) if tenors else self.cube.tenors()
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
        """Long form: one row per node, with this backend's underlying attached."""
        rows: List[Dict[str, Any]] = []
        for expiry in self.cube.expiries():
            for tenor in self.cube.tenors():
                fwd = self.forward(expiry, tenor)
                ann = self.annuity(expiry, tenor)
                tte = self.time_to_expiry(expiry)
                for off in self.cube.offsets():
                    rows.append(
                        {
                            "backend": self.backend,
                            "expiry": expiry,
                            "tenor": tenor,
                            "offset_bp": float(off),
                            "vol_bp": float(self.cube.vol(expiry, tenor, off)),
                            "forward": fwd,
                            "strike": fwd + float(off) / 1e4,
                            "annuity": ann,
                            "tte": tte,
                        }
                    )
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ #
    #                               pricing                              #
    # ------------------------------------------------------------------ #

    def strike_for(self, expiry: str, tenor: str, offset_bp: float) -> float:
        """``forward + offset/1e4``, the strike Citi's offset refers to."""
        return self.forward(expiry, tenor) + float(offset_bp) / 1e4

    def price(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        right: str = "payer",
        notional: Optional[float] = None,
    ) -> float:
        """Present value at ``as_of``, in currency units."""
        return float(
            self.inner.price(str(expiry), str(tenor), float(strike), right=right, notional=notional)
        )

    def premium(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        right: str = "payer",
        notional: Optional[float] = None,
    ) -> float:
        """The same cash on its payment date, undiscounted."""
        native = getattr(self.inner, "premium", None)
        if callable(native):
            return float(native(str(expiry), str(tenor), float(strike), right=right, notional=notional))
        return self.price(expiry, tenor, strike, right, notional) / self.payment_discount(expiry)

    def vega(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        right: str = "payer",
        notional: Optional[float] = None,
        analytic: bool = False,
    ) -> float:
        """PV change per **1 bp** of normal vol.

        Every backend defaults to a central difference of :meth:`price` over a
        +/-0.5 bp shift, so the number means the same thing whichever one is
        active. ``analytic=True`` asks the library for its own value where it has
        one - and on rateslib that value is timed off the CURVE while the premium
        is not, so it is wrong by ~0.14%/day when the curve does not start on the
        cube's ``as_of``. See :class:`NativeSwaptionCube`.
        """
        # CitiVeloNormalVolCube.vega has no analytic= switch: it always uses
        # QuantLib's BachelierCalculator on its own forward, annuity and tte,
        # which is already consistent with the premium it reports. Detected by
        # signature rather than by catching TypeError, which would also swallow a
        # TypeError raised from inside the calculation.
        import inspect

        kwargs: Dict[str, Any] = {"right": right, "notional": notional}
        if "analytic" in inspect.signature(self.inner.vega).parameters:
            kwargs["analytic"] = analytic
        elif analytic:
            raise UnavailableBackendError(
                f"backend={self.backend!r} has no separate analytic vega: it differentiates the "
                "Bachelier formula it prices with, so the two are the same number."
            )
        return float(self.inner.vega(str(expiry), str(tenor), float(strike), **kwargs))

    def implied_normal_vol(
        self,
        expiry: str,
        tenor: str,
        strike: float,
        premium: float,
        right: str = "payer",
        notional: Optional[float] = None,
    ) -> float:
        """Invert :meth:`price` back to normal vol in bp, with the backend's own inverter.

        This is a **consistency** check - each backend inverts what it priced.
        :mod:`MDP.CitiVelocityExcel.vol.spot_check` deliberately does not use it:
        it inverts with a pure-Python bisection and crosses the annuities between
        backends, because an inverter that shares a pricer cannot disprove it.
        """
        return float(
            self.inner.implied_normal_vol(
                str(expiry),
                str(tenor),
                float(strike),
                float(premium),
                right=right,
                notional=notional,
            )
        )

    def swaption(self, expiry: str, tenor: str, strike: Any = "atm", right: str = "payer", **kwargs: Any) -> Any:
        """The backend's own instrument: ``rl.IRSCall``/``IRSPut`` or ``ql.Swaption``."""
        builder = getattr(self.inner, "swaption", None)
        if builder is None:
            raise UnavailableBackendError(
                f"backend={self.backend!r} builds no instrument object; it evaluates the "
                "Bachelier formula directly. Use with_backend('rl-native') or "
                "with_backend('ql')."
            )
        return builder(str(expiry), str(tenor), strike, right=right, **kwargs)

    def __repr__(self) -> str:
        return (
            f"CitiVeloSwaptionCube({self.cube.currency} {self.cube.as_of} via {self.backend}, "
            f"{len(self.cube.expiries())}x{len(self.cube.tenors())}x{len(self.cube.offsets())}, "
            f"available={self.backends_available}, idx={self.citi_index})"
        )


def build_citivelo_swaption_cube(
    *,
    cube: SwaptionCubeData,
    rl_curve: Any = None,
    ql_curve: Any = None,
    backend: str = "auto",
    citi_index: Optional[str] = None,
    notional: float = 1e8,
    rl_disc_curve: Any = None,
    interpolation: str = "spline",
    spline_order: Optional[int] = None,
    verify: bool = True,
    vol_source: str = "cube",
) -> CitiVeloSwaptionCube:
    """Build the one Citi swaption pricer. See :class:`CitiVeloSwaptionCube`."""
    return CitiVeloSwaptionCube(
        cube=cube,
        rl_curve=rl_curve,
        ql_curve=ql_curve,
        backend=backend,
        citi_index=citi_index,
        notional=notional,
        rl_disc_curve=rl_disc_curve,
        interpolation=interpolation,
        spline_order=spline_order,
        verify=verify,
        vol_source=vol_source,
    )

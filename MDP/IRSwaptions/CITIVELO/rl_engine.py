r"""A rateslib pricing engine for ``Query/IRSwaptions``, so ``-RL`` means something.

``IRSwaptionMDP`` has had an ``ENGINE_FACTORIES`` registry since it was written,
and ``tests/test_ir_swaption_mdp.py:66`` proves it is data rather than a QuantLib
type: it registers a factory that returns a bare ``object()`` and drives
``source='TESTPROV-TESTENG'`` end to end. Nothing then *priced* with it, because
``Query/IRSwaptions/pricer.py`` reaches straight for ``ql.Swaption``. Only ``QL``
was ever registered.

This is the second engine. It implements the same handful of leaf metrics the
QuantLib path implements, off the same
:class:`~MDP.CitiVelocityExcel.vol.swaption_cube.CitiVeloSwaptionCube` that the
``CITIVELO`` vol provider built, and ``pricer.py`` dispatches to it with a
one-line guard per metric so the QuantLib paths are untouched.

What it deliberately does not do
--------------------------------
``premium_override`` inverts a supplied premium through
``ql.Swaption.impliedVolatility`` and then re-prices at that flat vol. Doing the
same here would mean writing a second inverter and quietly pricing off a
different model whenever a caller set an override. It raises instead, naming the
alternative.

Greeks are finite differences of this engine's own price rather than rateslib's
``analytic_greeks``. That is not laziness: rateslib times the option from the
**curve's** first node while the premium uses the cube's ``eval_date``, so its
analytic vega is low by ~0.14%/day of gap at the money and 0.34% at the 100 bp
wings, silently (see :mod:`MDP.CitiVelocityExcel.vol.rl_native_cube`). A
difference of this engine's own price cannot disagree with this engine's own
price.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from typing import Any, Optional

from MDP.CitiVelocityExcel.errors import CitiVelocityError

__all__ = ["RLSwaptionEngine", "make_rl_swaption_engine"]

_logger = logging.getLogger(__name__)

#: Bump used for the strike derivatives, in decimals of rate. 1 bp, matching what
#: ``Query/IRSwaptions/pricer.py`` uses for its own gamma bumps.
_STRIKE_BUMP = 1e-4

#: One day, for theta / charm / veta. The QuantLib path rolls the evaluation date;
#: rateslib has no global evaluation date, so this rolls the option instead - the
#: same fallback ``leg_theta_1d`` already uses when the eval-date roll is flat.
_ONE_DAY = dt.timedelta(days=1)


class RLSwaptionEngine:
    """Price a repo ``IRSwaptionPricable`` through rateslib.

    Parameters
    ----------
    cube
        The :class:`CitiVeloSwaptionCube` the ``CITIVELO`` provider built, on a
        rateslib backend.
    notional
        Unused - every method takes the leg's own notional. Kept so the engine
        factory signature matches the QuantLib one.

    Notes
    -----
    A leg carries explicit dates (``exercise_date``, ``underlying_effective_date``,
    ``underlying_maturity_date``) while the cube is keyed on tenor tokens, so each
    leg is priced on a swaption built from **its own dates** and only the
    volatility is read from the cube - by option time and swap length, exactly as
    the QuantLib path does through ``vol_handle.volatility(...)``. That keeps a
    midcurve tail, an explicit-date leg and a rolled backtest leg all priceable,
    none of which land on a cube node.
    """

    def __init__(self, *, cube: Any, notional: float = 1e8):
        self.cube = cube
        self.notional = float(notional)
        # A value request regularly asks for several strikes/structures on the
        # same underlying.  Building a rateslib IRS to recover its par rate and
        # PV01 is materially more expensive than the cube lookup, and neither
        # number depends on a swaption strike or side.  Keep it on the engine
        # (one engine per market context in the Citi provider), rather than in a
        # process-wide cache where a new curve snapshot could alias an old one.
        self._underlying_cache: dict[tuple[Any, ...], tuple[float, float]] = {}
        self._underlying_cache_lock = threading.RLock()
        if not getattr(cube, "is_rateslib", False):
            raise CitiVelocityError(
                f"RLSwaptionEngine needs a rateslib-backed CitiVeloSwaptionCube; got "
                f"backend={getattr(cube, 'backend', type(cube).__name__)!r}."
            )

    # -- the pieces every metric is built from --------------------------

    @staticmethod
    def _underlying_key(context: Any, leg: Any) -> tuple[Any, ...]:
        """Identity for curve quantities shared by all strikes of one swap."""
        return (
            id(getattr(context, "curve", None)),
            getattr(context, "as_of_date", None),
            getattr(leg, "underlying_effective_date", None),
            getattr(leg, "underlying_maturity_date", None),
        )

    def _underlying_inputs(self, context: Any, leg: Any) -> tuple[float, float]:
        """Return ``(forward, annuity)`` once for a curve/date/underlying.

        ``RLSwaptionEngine`` is shared by the thread pool for a single context,
        so the lock intentionally covers construction too: it prevents a wide
        package request from simultaneously rebuilding the exact same IRS for
        payer, receiver, and package legs.  Distinct context engines never
        contend with one another.
        """
        key = self._underlying_key(context, leg)
        with self._underlying_cache_lock:
            cached = self._underlying_cache.get(key)
            if cached is not None:
                return cached

            swap = context.curve.build_irswap(
                effective_date=leg.underlying_effective_date,
                maturity_date=leg.underlying_maturity_date,
                fixed_rate=-0.0,
                notional=1.0,
            )
            inputs = (
                abs(float(context.curve.fair_rate(swap))),
                abs(float(context.curve.pv01(swap))) * 1e4,
            )
            self._underlying_cache[key] = inputs
            return inputs

    def _tte(self, context: Any, leg: Any) -> float:
        day_count = 365.0
        return max((leg.exercise_date - context.as_of_date).days / day_count, 1e-10)

    def _swap_years(self, leg: Any) -> float:
        return max(
            (leg.underlying_maturity_date - leg.underlying_effective_date).days / 365.0, 1e-10
        )

    def forward(self, context: Any, leg: Any) -> float:
        """The par rate of the leg's own underlying, DECIMAL."""
        return self._underlying_inputs(context, leg)[0]

    def annuity(self, context: Any, leg: Any) -> float:
        """Discounted fixed-leg annuity per unit notional, in years.

        ``pv01`` on the repo's rateslib curve is ``rl.IRS.analytic_delta``, i.e.
        the PV change per basis point for the notional given; times 1e4 over the
        notional, that is the annuity.
        """
        return self._underlying_inputs(context, leg)[1]

    def normal_vol(self, context: Any, leg: Any, *, strike: Optional[float] = None) -> float:
        """The cube's volatility for this leg, DECIMAL.

        Read by offset from the leg's own forward, which is how Citi publishes the
        skew and what keeps the smile anchored on the instrument being priced.
        """
        k = float(leg.strike if strike is None else strike)
        forward = self.forward(context, leg)
        offset_bp = (k - forward) * 1e4
        expiry, tenor = _tenor_tokens(context, leg)
        return float(self.cube.normal_vol(expiry, tenor, offset_bp=offset_bp)) / 1e4

    # -- the metrics Query/IRSwaptions asks for --------------------------

    def spot_npv(self, context: Any, leg: Any) -> float:
        from Query.Base.bachelier import bachelier_price

        right = "C" if str(leg.option_type).lower().startswith(("pay", "call", "c")) else "P"
        forward = self.forward(context, leg)
        annuity = self.annuity(context, leg)
        vol = self.normal_vol(context, leg)
        tte = self._tte(context, leg)
        size = abs(float(leg.notional))
        return float(
            size * annuity * bachelier_price(right, float(leg.strike), forward, vol, tte, 1.0)
        )

    def implied_normal_vol_bps(self, context: Any, leg: Any) -> float:
        """The volatility this engine priced with, in bp.

        Reading it back off the cube rather than inverting the premium is not a
        shortcut - the two are the same number by construction here, and an
        inversion would only add a solver's error to a value that is already
        exact. ``MDP/CitiVelocityExcel/vol/spot_check.py`` is where the round trip
        is actually tested, with an inverter that shares no code with the pricer.
        """
        return self.normal_vol(context, leg) * 1e4

    def vega_01(self, context: Any, leg: Any) -> float:
        from Query.Base.bachelier import bachelier_greeks_fd

        right = "C" if str(leg.option_type).lower().startswith(("pay", "call", "c")) else "P"
        forward = self.forward(context, leg)
        annuity = self.annuity(context, leg)
        vol = self.normal_vol(context, leg)
        tte = self._tte(context, leg)
        _d, _g, vega, _t = bachelier_greeks_fd(
            right=right,
            strike=float(leg.strike),
            forward=forward,
            vol_normal=vol,
            tte=tte,
            discount=1.0,
        )
        return float(abs(float(leg.notional)) * annuity * vega * 1e-4)

    def delta(self, context: Any, leg: Any) -> float:
        """Bachelier forward delta, signed by the leg's direction."""
        from Query.Base.bachelier import bachelier_greeks_fd

        right = "C" if str(leg.option_type).lower().startswith(("pay", "call", "c")) else "P"
        delta, _g, _v, _t = bachelier_greeks_fd(
            right=right,
            strike=float(leg.strike),
            forward=self.forward(context, leg),
            vol_normal=self.normal_vol(context, leg),
            tte=self._tte(context, leg),
            discount=1.0,
        )
        return float(delta)

    def dv01(self, context: Any, leg: Any) -> float:
        """PV change per 1 bp of the underlying forward, currency units."""
        return float(
            self.delta(context, leg) * abs(float(leg.notional)) * self.annuity(context, leg) * 1e-4
        )

    def gamma(self, context: Any, leg: Any) -> float:
        from Query.Base.bachelier import bachelier_greeks_fd

        right = "C" if str(leg.option_type).lower().startswith(("pay", "call", "c")) else "P"
        _d, gamma, _v, _t = bachelier_greeks_fd(
            right=right,
            strike=float(leg.strike),
            forward=self.forward(context, leg),
            vol_normal=self.normal_vol(context, leg),
            tte=self._tte(context, leg),
            discount=1.0,
        )
        return float(abs(gamma)) / 1e4

    def gamma_01(self, context: Any, leg: Any) -> float:
        """Change in :meth:`dv01` per 1 bp of forward, by central difference."""
        from dataclasses import replace

        up = replace(leg, strike=float(leg.strike) + _STRIKE_BUMP)
        down = replace(leg, strike=float(leg.strike) - _STRIKE_BUMP)
        return abs(self.dv01(context, up) - self.dv01(context, down)) / (2.0 * _STRIKE_BUMP) / 1e4

    def theta_1d(self, context: Any, leg: Any) -> float:
        """One day of time decay, by rolling the option a day closer to expiry.

        rateslib has no global evaluation date to move, so this is the same
        fallback ``leg_theta_1d`` already applies when QuantLib's eval-date roll
        turns out to be flat.
        """
        from dataclasses import replace

        rolled = leg.exercise_date - _ONE_DAY
        if rolled <= context.as_of_date:
            return 0.0
        return self.spot_npv(context, replace(leg, exercise_date=rolled)) - self.spot_npv(
            context, leg
        )

    def charm(self, context: Any, leg: Any) -> float:
        from dataclasses import replace

        rolled = leg.exercise_date - _ONE_DAY
        if rolled <= context.as_of_date:
            return 0.0
        return self.delta(context, replace(leg, exercise_date=rolled)) - self.delta(context, leg)

    def veta(self, context: Any, leg: Any) -> float:
        from dataclasses import replace

        rolled = leg.exercise_date - _ONE_DAY
        if rolled <= context.as_of_date:
            return 0.0
        return self.vega_01(context, replace(leg, exercise_date=rolled)) - self.vega_01(
            context, leg
        )

    def __repr__(self) -> str:
        return f"RLSwaptionEngine({self.cube!r})"


def _tenor_tokens(context: Any, leg: Any) -> tuple[str, str]:
    """``(expiry, tenor)`` tokens for a leg, in months, for the cube lookup.

    The cube interpolates bilinearly between its expiry and tenor nodes and holds
    flat outside, on both libraries, so a month-resolution token is exact on a
    node and correctly interpolated off one. The strike offset - the axis that
    actually needs precision - is computed from the leg's own forward, not from
    these tokens.
    """
    months_to_expiry = max(int(round((leg.exercise_date - context.as_of_date).days / 30.4375)), 1)
    months_of_swap = max(
        int(round((leg.underlying_maturity_date - leg.underlying_effective_date).days / 30.4375)), 1
    )
    return f"{months_to_expiry}M", f"{months_of_swap}M"


def make_rl_swaption_engine(
    *,
    curve_handle: Any = None,
    vol_handle: Any = None,
    day_counter: Any = None,
    **kwargs: Any,
) -> RLSwaptionEngine:
    """``IRSwaptionMDP.ENGINE_FACTORIES['RL']``.

    The registry's signature is QuantLib-shaped (``curve_handle``, ``vol_handle``,
    ``day_counter``) because the QuantLib engine was the only one when it was
    written. Here ``vol_handle`` is the
    :class:`~MDP.CitiVelocityExcel.vol.swaption_cube.CitiVeloSwaptionCube` the
    ``CITIVELO`` provider returned under ``engine='RL'``; the other two are
    unused, because a rateslib swaption reads its curve off the context.
    """
    _ = (curve_handle, day_counter)
    if vol_handle is None:
        raise CitiVelocityError(
            "The RL swaption engine needs a CitiVeloSwaptionCube as its vol object. Only the "
            "CITIVELO provider returns one, so source must be 'CITIVELO-RL'."
        )
    return RLSwaptionEngine(cube=vol_handle, notional=float(kwargs.get("notional", 1e8)))

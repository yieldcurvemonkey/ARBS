"""Version-tolerant shims for the parts of the rateslib API that move between releases.

Why this exists
---------------
rateslib renames constructor kwargs and accessors across minor versions, and its
instrument constructors take **no** ``**kwargs``. Passing a name from the wrong
version is therefore a hard ``TypeError`` at construction, not a silently ignored
argument. This repo has a large body of cached artefacts built under 2.1.x and is
currently running 2.7.1, so a flat rename would only move the breakage.

Each moved name is resolved **once**, at import, by introspecting the installed
rateslib. Callers use the shim and stay version-agnostic.

Resolution is by signature introspection, never by ``try``/``except TypeError``
around the call itself. A ``TypeError`` raised from *inside* rateslib's own
construction is indistinguishable from a rejected kwarg name, so the try-both
idiom this module replaces could swallow a genuine error and fall through to a
constructor call with **no fixings at all** -- which does not raise, it just
misprices the front monthly contract, whose accrual period always starts before
the curve reference date.

What moved (2.1.x/2.6.x -> 2.7.x)
--------------------------------
============================  ==================================================
old                           new
============================  ==================================================
``leg2_fixings=``             ``leg2_rate_fixings=``
``analytic_delta(curve=x)``   ``analytic_delta(curves=x)`` (keyword-only)
``inst.kwargs["notional"]``   ``inst._kwargs.leg1["notional"]`` (grouped)
``STIRFuture.pv01``           ``abs(STIRFuture.analytic_delta())``
============================  ==================================================

2.7 additionally requires a *resolvable* discount curve for
``STIRFuture.analytic_delta()``, which the older versions did not -- see
:func:`stirf_analytic_delta`.
"""

from __future__ import annotations

import inspect
from typing import Any

import rateslib as rl

__all__ = [
    "RATE_FIXINGS_KWARG",
    "rate_fixings_kwargs",
    "analytic_delta",
    "instrument_kwarg",
    "stirf_analytic_delta",
    "stirf_pv01",
]

_MISSING = object()


def _resolve_kwarg_name(func: Any, candidates: tuple[str, ...]) -> str:
    """Return the first name in ``candidates`` that ``func`` actually accepts.

    Candidates are ordered newest-first. Falls back to ``candidates[0]`` when no
    name matches -- which covers both an unreadable signature and a callable that
    takes ``**kwargs`` (any name is forwarded, so the newest is the right guess).
    Nothing downstream depends on that fallback today: rateslib declares every
    name explicitly, which is why a wrong one raises rather than being ignored.
    """
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):  # C-implemented or otherwise opaque
        return candidates[0]

    for name in candidates:
        if name in params:
            return name

    return candidates[0]


#: Name of the constructor kwarg that supplies published RFR fixings to leg 2.
#: ``leg2_rate_fixings`` on rateslib >= 2.7, ``leg2_fixings`` before that.
RATE_FIXINGS_KWARG: str = _resolve_kwarg_name(
    rl.IRS.__init__, ("leg2_rate_fixings", "leg2_fixings")
)


def _accepts_named(func: Any, name: str) -> bool:
    """True when ``func`` declares ``name`` as an actual named parameter."""
    try:
        return name in inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False


# rateslib >= 2.7 made analytic_delta keyword-only and renamed curve -> curves.
# Earlier versions declared ``(self, *args, leg=1, **kwargs)``, so neither name
# appears in the signature and the positional form is the portable one.
_ANALYTIC_DELTA_TAKES_CURVES: bool = _accepts_named(rl.IRS.analytic_delta, "curves")


def rate_fixings_kwargs(fixings: Any) -> dict[str, Any]:
    """Constructor kwargs that attach ``fixings`` to leg 2, or ``{}`` if there are none.

    Use as ``rl.STIRFuture(**kwargs, **rate_fixings_kwargs(masked))`` so the call
    site never names the version-specific kwarg.

    Published fixings are needed whenever an instrument's accrual period starts
    BEFORE the curve's reference date -- the norm for a front monthly contract,
    whose calendar month is always partly in the past. Without them rateslib
    raises "RFRs could not be calculated".
    """
    if fixings is None:
        return {}
    return {RATE_FIXINGS_KWARG: fixings}


def analytic_delta(instrument: Any, curve: Any = None, **kwargs: Any) -> Any:
    """``instrument.analytic_delta`` with the curve passed the way this rateslib wants.

    ``curve=None`` calls it with no curve at all, which is correct for
    instruments that already carry their own ``curves`` (e.g. ``STIRFuture``).
    """
    if curve is None:
        return instrument.analytic_delta(**kwargs)
    if _ANALYTIC_DELTA_TAKES_CURVES:
        return instrument.analytic_delta(curves=curve, **kwargs)
    return instrument.analytic_delta(curve, **kwargs)


def instrument_kwarg(instrument: Any, name: str, default: Any = _MISSING) -> Any:
    """Read one of an instrument's construction kwargs, whatever shape they are in.

    rateslib <= 2.6 kept a flat ``inst.kwargs`` dict. 2.7 replaced it with a
    ``_KWArgs`` namespace grouping arguments into ``.meta`` / ``.leg1`` /
    ``.leg2`` dicts, and dropped the flat form entirely (it is not even
    subscriptable), so ``inst.__dict__["kwargs"]["notional"]`` is a ``KeyError``.

    Schedule-derived names (``effective``, ``termination``) are looked up on the
    leg-1 ``Schedule`` when they are not present as kwargs, so they resolve to
    the same datetimes the older flat dict carried.
    """
    grouped = getattr(instrument, "_kwargs", None)

    # rateslib >= 2.7: grouped namespace.
    if grouped is not None and not isinstance(grouped, dict):
        for group in ("meta", "leg1", "leg2"):
            values = getattr(grouped, group, None)
            if isinstance(values, dict) and name in values:
                return values[name]

        leg1 = getattr(grouped, "leg1", None)
        schedule = leg1.get("schedule") if isinstance(leg1, dict) else None
        if schedule is not None and hasattr(schedule, name):
            return getattr(schedule, name)

    # rateslib <= 2.6: flat dict, reachable either way.
    for flat in (instrument.__dict__.get("kwargs"), grouped):
        if isinstance(flat, dict) and name in flat:
            return flat[name]

    if default is not _MISSING:
        return default
    raise KeyError(
        f"{type(instrument).__name__} has no construction kwarg {name!r} "
        f"(rateslib {getattr(rl, '__version__', '?')})"
    )


_placeholder_curve: Any = None


def _disc_curve_placeholder() -> Any:
    """A flat unit discount curve spanning every date this repo prices on.

    Only ever handed to :func:`stirf_analytic_delta`, whose result is provably
    independent of it (see that docstring).
    """
    global _placeholder_curve
    if _placeholder_curve is None:
        _placeholder_curve = rl.Curve(
            nodes={rl.dt(1990, 1, 1): 1.0, rl.dt(2100, 1, 1): 1.0},
            id="_rl_compat_placeholder_disc",
            convention="act360",
            calendar="all",
        )
    return _placeholder_curve


def stirf_analytic_delta(stirf: Any) -> Any:
    """``STIRFuture.analytic_delta()``, tolerant of an unresolvable curve reference.

    A STIR future's analytic delta is the exchange's linear tick value --
    ``contracts x nominal x dcf x 1e-4``, i.e. $25/bp for a 3-month SR3 and
    $41.67/bp for a 1-month ZQ. It carries **no discounting**, and rateslib
    returns the identical number whatever discount curve it is given (pinned by
    ``test_stirf_analytic_delta_is_discount_independent``).

    rateslib <= 2.6 therefore let the call succeed with no usable curve at all.
    2.7 routes it through a generic protocol that insists on resolving a
    ``disc_curve`` first, so a pricer holding only a curve *name* (with no
    ``Solver`` in scope to resolve it) now raises -- which is the shape
    ``RLSTIRFuturePricer`` is built in. Supplying a placeholder restores the
    older behaviour without changing any number.

    The retry is narrowly conditioned on that one error. Anything else -- a bad
    schedule, a missing spec, a genuine pricing failure -- propagates.
    """
    try:
        return stirf.analytic_delta()
    except ValueError as exc:
        if "disc_curve" not in str(exc):
            raise
        return stirf.analytic_delta(curves=_disc_curve_placeholder())


def stirf_pv01(stirf: Any) -> float:
    """Absolute BPV of a ``STIRFuture``, for however many contracts it holds.

    rateslib <= 2.6 exposed a ``.pv01`` property; 2.7 removed it. ``analytic_delta``
    is the surviving spelling and carries the same magnitude (opposite sign, since
    a long future is short rates), so callers that took ``abs(...)`` are unaffected.
    """
    legacy = getattr(stirf, "pv01", None)
    if legacy is not None:
        return abs(float(legacy))
    return abs(float(stirf_analytic_delta(stirf).real))

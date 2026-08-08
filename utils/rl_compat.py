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
``leg.cashflows(x)``          ``leg.cashflows(rate_curve=x)`` (keyword-only)
``leg.npv(x, d)``             ``leg.npv(rate_curve=x, disc_curve=d)`` (kw-only)
============================  ==================================================

2.7 additionally requires a *resolvable* discount curve for
``STIRFuture.analytic_delta()``, which the older versions did not -- see
:func:`stirf_analytic_delta`.
"""

from __future__ import annotations

import datetime
import hashlib
import inspect
import threading
import weakref
from typing import Any

import numpy as np
import pandas as pd
import rateslib as rl

__all__ = [
    "RATE_FIXINGS_KWARG",
    "FIXINGS_TRANSPORT",
    "fixed_rate",
    "fly",
    "rate_fixings_kwargs",
    "reset_fixings_name_memo",
    "analytic_delta",
    "instrument_kwarg",
    "leg_cashflows",
    "leg_npv",
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


# rateslib <= 2.6 stored an instrument's struck rate on the private
# ``_fixed_rate``; 2.7 dropped the attribute entirely in favour of the public
# ``fixed_rate`` property (which also derives ``100 - price`` for a STIRFuture).
# Resolved once here so the SDR/STIR curve builders, which read it off every
# calibrating instrument to build the Solver's ``s`` vector, stay version-blind.
_FIXED_RATE_ATTR: str = "fixed_rate" if hasattr(rl.IRS, "fixed_rate") else "_fixed_rate"


def fixed_rate(instrument: Any) -> Any:
    """The rate an instrument is struck at, however this rateslib exposes it.

    A vector-valued rate (an amortising or step schedule) collapses to its last
    element, which is what the call sites this replaces did. The value is
    otherwise returned verbatim -- including rateslib's ``NoInput`` for an
    unstruck instrument, so "not set" stays distinguishable from zero.
    """
    value = getattr(instrument, _FIXED_RATE_ATTR)
    return value.iloc[-1] if hasattr(value, "iloc") else value


# ``Solver.__init__`` reads ``inst.rate_scalar`` off every calibrating
# instrument, and that property returns ``self._rate_scalar``. rateslib 2.7.1
# declares it on ``Spread`` (100.0) but NOT on ``Fly``, so any ``Fly`` handed to
# a ``Solver`` dies with ``AttributeError: 'Fly' object has no attribute
# '_rate_scalar'`` -- which is every SDR_INTRADAY curve, all of which calibrate
# FOMC turn flies. The two classes share the convention exactly (``Spread.rate``
# returns ``(r1 - r0) * 100``, ``Fly.rate`` returns ``(-r0 + 2 r1 - r2) * 100``),
# so Fly's scalar is Spread's; taken from the class rather than written as a
# literal so the two cannot drift apart.
_FLY_DECLARES_RATE_SCALAR: bool = hasattr(rl.Fly, "_rate_scalar")
_SPREAD_RATE_SCALAR: float = float(getattr(rl.Spread, "_rate_scalar", 100.0))


def fly(*instruments: Any) -> Any:
    """``rl.Fly`` that a ``Solver`` will accept on any rateslib.

    The scalar drives Solver *risk reporting* (``delta``/``gamma`` scaling), not
    the calibration itself -- pinned by
    ``test_fly_rate_scalar_does_not_move_the_solved_curve``.
    """
    obj = rl.Fly(*instruments)
    if not _FLY_DECLARES_RATE_SCALAR:
        obj._rate_scalar = _SPREAD_RATE_SCALAR
    return obj


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


# ---------------------------------------------------------------------------
# RFR fixings transport
# ---------------------------------------------------------------------------
#
# Getting the *name* of the fixings kwarg right is not enough on rateslib 2.7:
# the kwarg is accepted and then thrown away.
#
# ``periods/parameters/rate.py`` resolves a ``Series`` argument EAGERLY at
# construction: it calls ``RFRFixing._lookup(...)`` and stores only its first
# return value as ``RFRFixing.value``, discarding the ``populated`` half and
# leaving ``identifier`` as ``NoInput``. For a period whose fixings are all in
# the past that value is the finished rate and everything works. For a
# PARTIALLY fixed period -- the front monthly SR1/ZQ contract on any day after
# the first business day of its month -- ``_lookup`` cannot produce a value
# without a curve, returns ``NoInput``, and the known fixings are gone. The
# period then forecasts every observation off the curve, including the ones
# before the curve's own start date, whose discount factors are 0.0:
#
#   * inside a ``Solver`` (Dual arithmetic) that is ``ZeroDivisionError``;
#   * outside one it is a silent ``nan``.
#
# A ``str`` argument takes the other branch: it is stored as an ``identifier``
# and looked up LAZILY at ``rate()`` time, which populates partial periods
# correctly (this is the case rateslib's own ``RFRFixing`` docstring documents).
# So on such a rateslib the shim registers the series in the global
# ``rl.fixings`` store under a content-derived name and passes that name.
#
# Registering full published history means rateslib may emit its ``W02_0``
# "unexpected fixings provided" warning for dates outside the accrual period.
# That is noise, not a defect: the observation window is intersected correctly.

#: Prefix for the names this module registers in ``rl.fixings``.
_FIXINGS_NAME_PREFIX = "ARBS_RFR_"

#: rateslib appends the fixing index's tenor to the identifier it is handed
#: (``_get_tenor_from_frequency``), which for every daily RFR series -- the only
#: kind this repo supplies -- is ``1B``. Verified by the probe below rather than
#: assumed: if the suffix ever changes, the probe fails and the shim falls back
#: to passing the Series instead of silently registering unreachable names.
_FIXINGS_NAME_SUFFIX = "_1B"

_FIXINGS_LOCK = threading.RLock()
_REGISTERED_FIXINGS: dict[str, str] = {}
_FIXINGS_TRANSPORT: str | None = None

#: ``id(series) -> (weakref, fingerprint, name)`` so the SAME series object does
#: not get cleaned, hashed and looked up on every instrument construction.
#:
#: Deriving the identifier from the series' CONTENT is what makes one published
#: history register once - but it also means paying for the content on every
#: call: ``dropna().astype(float).sort_index()`` copies the series and the digest
#: hashes it. Measured 2026-08-08 on a 5,445-row USD SOFR history, that is
#: 0.235 ms per ``rate_fixings_kwargs``, and a timeseries builds an instrument
#: per observation.
#:
#: Keyed on object identity, guarded three ways: a weakref (so a recycled ``id``
#: cannot alias a dead entry), and a cheap fingerprint of length plus both
#: endpoints (so a series appended to or reassigned at either end re-registers).
#: A series mutated only in its INTERIOR, in place, keeping its length and both
#: endpoints, would still hit - which no caller here does, and which the
#: content-addressed name would in any case have already resolved for the
#: unmutated content.
_FIXINGS_NAME_MEMO: dict[int, tuple[Any, Any, str]] = {}


def _fixings_fingerprint(series: pd.Series) -> Any:
    try:
        index = series.index
        return (
            len(series),
            index[0],
            index[-1],
            float(series.iat[0]),
            float(series.iat[-1]),
        )
    except Exception:  # noqa: BLE001 - an unusual series simply is not memoised
        return None


def _series_digest(series: pd.Series) -> str:
    index = pd.DatetimeIndex(series.index)
    return hashlib.sha256(
        index.asi8.tobytes() + series.to_numpy(dtype=float).tobytes()
    ).hexdigest()[:24]


def _clean_fixings(series: Any) -> pd.Series | None:
    """Sorted, NaN-free, float-valued view of a fixings series, or ``None``."""
    if not isinstance(series, pd.Series):
        return None
    try:
        clean = series.dropna().astype(float).sort_index()
    except (TypeError, ValueError):
        return None
    return None if clean.empty else clean


def _register_fixings(series: pd.Series) -> str | None:
    """Register ``series`` in ``rl.fixings`` and return the name to pass rateslib.

    Names are derived from the series *content*, so the same published history
    is registered once however many instruments reference it. Entries are never
    evicted: rateslib resolves an identifier lazily, at ``rate()`` time, so
    removing one would break instruments built earlier in the same process.

    The registry is per-process, which is the right granularity here -- workers
    are handed *pricers* (which carry their own fixings) and build their
    instruments locally. An instrument pickled into a process that never
    registered its series would fail to resolve the name, but it fails LOUDLY,
    with rateslib naming the missing identifier.
    """
    add = getattr(getattr(rl, "fixings", None), "add", None)
    if add is None:
        return None

    # Identity memo, checked before anything is copied or hashed. See
    # _FIXINGS_NAME_MEMO for the guards and the one mutation it does not catch.
    key = id(series)
    fingerprint = _fixings_fingerprint(series)
    if fingerprint is not None:
        with _FIXINGS_LOCK:
            memo = _FIXINGS_NAME_MEMO.get(key)
        if memo is not None:
            ref, cached_fingerprint, cached_name = memo
            if ref() is series and cached_fingerprint == fingerprint:
                return cached_name

    clean = _clean_fixings(series)
    if clean is None:
        return None

    digest = _series_digest(clean)
    with _FIXINGS_LOCK:
        name = _REGISTERED_FIXINGS.get(digest)
        if name is None:
            name = f"{_FIXINGS_NAME_PREFIX}{digest}"
            add(f"{name}{_FIXINGS_NAME_SUFFIX}", clean)
            _REGISTERED_FIXINGS[digest] = name
        if fingerprint is not None:
            try:
                _FIXINGS_NAME_MEMO[key] = (
                    weakref.ref(series, lambda _r, k=key: _FIXINGS_NAME_MEMO.pop(k, None)),
                    fingerprint,
                    name,
                )
            except TypeError:  # not weak-referenceable -> simply not memoised
                pass
    return name


def reset_fixings_name_memo() -> None:
    """Drop the identity memo (not the content registry). For tests."""
    with _FIXINGS_LOCK:
        _FIXINGS_NAME_MEMO.clear()


def _probe_front_month_rate(fixings_argument: Any) -> float:
    """Rate of a half-fixed front monthly contract, or ``nan`` if it cannot price.

    The accrual runs 1 Aug -> 1 Sep on a curve that only starts on 5 Aug, so the
    first observations exist solely in the fixings. Dates are fixed and historic;
    nothing here depends on the wall clock.
    """
    try:
        curve = rl.Curve(
            nodes={datetime.datetime(2010, 8, 5): 1.0, datetime.datetime(2011, 8, 5): 0.96},
            id="_rl_compat_fixings_probe",
            convention="act360",
            calendar="nyc",
            modifier="MF",
        )
        instrument = rl.STIRFuture(
            effective=datetime.datetime(2010, 8, 1),
            termination=datetime.datetime(2010, 9, 1),
            spec="usd_stir1",
            roll="som",
            curves=curve,
            price=99.0,
            **{RATE_FIXINGS_KWARG: fixings_argument},
        )
        return float(instrument.rate())
    except Exception:
        return float("nan")


def _probe_fixings() -> pd.Series:
    calendar = rl.get_calendar("nyc")
    dates = [
        d
        for d in pd.date_range("2010-08-02", "2010-08-04")
        if calendar.is_bus_day(d.to_pydatetime())
    ]
    return pd.Series(1.0, index=pd.DatetimeIndex(dates))


def _resolve_fixings_transport() -> str:
    """Decide how to hand a fixings series to rateslib, by trying both ways.

    Returns ``"series"`` when passing the ``Series`` itself prices a partially
    fixed period, and ``"identifier"`` when it does not but a registered name
    does. Falls back to ``"series"`` if neither works, so a rateslib this module
    has not seen behaves exactly as it would without the shim.
    """
    fixings = _probe_fixings()

    rate = _probe_front_month_rate(fixings)
    if np.isfinite(rate):
        return "series"

    name = _register_fixings(fixings)
    if name is not None and np.isfinite(_probe_front_month_rate(name)):
        return "identifier"

    return "series"


def _fixings_transport() -> str:
    global _FIXINGS_TRANSPORT
    if _FIXINGS_TRANSPORT is None:
        with _FIXINGS_LOCK:
            if _FIXINGS_TRANSPORT is None:
                _FIXINGS_TRANSPORT = _resolve_fixings_transport()
    return _FIXINGS_TRANSPORT


#: Public read of the resolved transport, for tests and diagnostics.
def FIXINGS_TRANSPORT() -> str:  # noqa: N802 - reads as a constant at call sites
    return _fixings_transport()


def rate_fixings_kwargs(fixings: Any) -> dict[str, Any]:
    """Constructor kwargs that attach ``fixings`` to leg 2, or ``{}`` if there are none.

    Use as ``rl.STIRFuture(**kwargs, **rate_fixings_kwargs(masked))`` so the call
    site never names -- or has to reason about the transport of -- the
    version-specific kwarg.

    Published fixings are needed whenever an instrument's accrual period starts
    BEFORE the curve's reference date: the norm for a front monthly contract,
    whose calendar month is always partly in the past, and for any seasoned swap.
    Without them rateslib either raises "RFRs could not be calculated" or prices
    the elapsed days off the curve, which is wrong rather than loud.

    See the block comment above for why a ``Series`` is not always passed through.
    """
    if fixings is None:
        return {}
    if isinstance(fixings, str):
        return {RATE_FIXINGS_KWARG: fixings}
    if isinstance(fixings, pd.Series) and fixings.empty:
        return {}

    if isinstance(fixings, pd.Series) and _fixings_transport() == "identifier":
        name = _register_fixings(fixings)
        if name is not None:
            return {RATE_FIXINGS_KWARG: name}

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


# 2.7 made the *leg* accessors keyword-only as well and renamed their first
# argument. ``leg.cashflows(handle)`` and ``leg.npv(handle, handle)`` -- both
# legal in 2.1.x/2.6.x -- are now ``TypeError: takes 1 positional argument``.
# Resolved once here for the same reason as everything else in this module: the
# name is version-specific, the call sites should not be.
_LEG_RATE_CURVE_KWARG: str = _resolve_kwarg_name(
    rl.legs.FixedLeg.cashflows, ("rate_curve", "curve")
)


def leg_cashflows(leg: Any, curve: Any) -> Any:
    """``leg.cashflows`` with the forecasting curve named the way this rateslib wants.

    Only the forecasting curve is passed, matching the pre-2.7 positional call
    this replaces (whose single argument was ``curve``); ``disc_curve`` then
    defaults to it exactly as it did before.
    """
    return leg.cashflows(**{_LEG_RATE_CURVE_KWARG: curve})


def leg_npv(leg: Any, curve: Any, disc_curve: Any = None) -> Any:
    """``leg.npv`` with forecasting and discount curves named for this rateslib.

    ``disc_curve=None`` means "discount off the same curve", which is what the
    two-positional-argument form ``leg.npv(c, c)`` said before 2.7.
    """
    kwargs = {_LEG_RATE_CURVE_KWARG: curve}
    if _accepts_named(rl.legs.FixedLeg.npv, "disc_curve"):
        kwargs["disc_curve"] = curve if disc_curve is None else disc_curve
        return leg.npv(**kwargs)
    return leg.npv(curve, curve if disc_curve is None else disc_curve)


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

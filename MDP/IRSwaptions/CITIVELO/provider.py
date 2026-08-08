r"""Citi Velocity as a vol provider for the repo's own swaption product.

``MDP/IRSwaptions`` + ``Query/IRSwaptions`` already carry thirteen structures,
twenty value metrics, a strike grammar (``"ATMF+25"``), a backtest position
handler and a timeseries builder. Before this module the Citi cube reached none of
it: it lived in ``MDP/CitiVelocityExcel/vol`` behind three bespoke classes with
three different APIs.

Registering here is all it takes::

    mdp = IRSwaptionMDP(source="CITIVELO-QL", curve_source="ERIS_EOD_LIVE-QL_BASIC")
    ctx = mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": date(2026, 8, 6)})
    q   = IRSwaptionQuery(shorthand="1Yx10Y", strike="ATMF+25",
                          structure=IRSwaptionStructure.PAYER,
                          value=IRSwaptionValue.NVOL)

and every OTM offset Citi publishes is now reachable through the strike grammar.

Where the cube comes from
-------------------------
In descending order of directness, each selected by a request keyword:

``cube=`` / ``cubes={date: cube}``
    An already-built :class:`SwaptionCubeData`. This is how the hermetic tests
    drive it.
``snapshot='usd_cube_2026-08-06.json'``
    A recorded live capture from ``harvest/snapshots/``. Offline, real quotes.
(nothing)
    Fetch through :class:`~MDP.CitiVelocityExcel.mdp.CitiVelocityMDP`, which needs
    a signed-in Excel add-in - COM is the only transport Citi Velocity offers
    here.

Which curve the strikes are measured from
-----------------------------------------
The provider is handed the same ``_IRSwapGenericCurve`` the context will carry,
so the vol surface's ATM anchor and the swaption's underlying come off one curve
rather than two. Whether that curve is Citi's own depends on ``curve_source``:

* ``curve_source="CITIVELO"`` - Citi's own SOFR curve, from the CurveStore. It is
  **rateslib-backed**, so under ``-QL`` a QuantLib view is mirrored off its nodes
  (:func:`build_ql_mirror_curve`); the two are the same curve to 2e-13 bp.
* ``curve_source="ERIS_EOD_LIVE-QL_BASIC"`` (the default) - a QuantLib curve, but
  not Citi's. The volatilities are still Citi's and still round-trip exactly; it
  is the strike-to-offset mapping that is then anchored somewhere else. On the
  recorded snapshot Citi's published forwards and ours agree to 0.26 bp, so the
  mapping is good - but that is a measurement about one date and one currency,
  not a property of the code.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from MDP.CitiVelocityExcel.errors import CitiVelocityError

__all__ = [
    "clear_citivelo_cube_cache",
    "get_cached_citivelo_cube",
    "get_citivelo_vol_objects",
]

_logger = logging.getLogger(__name__)

#: ``(curve_name, date_iso, engine) -> CitiVeloSwaptionCube``. Mirrors
#: ``MONKEYCUBE._CUBE_CACHE`` so ``IRSwaptionMDP`` can attach the built object to
#: the context's metadata the same way.
_CUBE_CACHE: Dict[Tuple[str, str, str], Any] = {}

#: Vol currency per ``IRSwapsMDP`` curve name. Only USD is served by the Citi
#: Velocity curve sources today; anything else must pass ``currency=``.
_CURVE_NAME_CURRENCY: Dict[str, str] = {
    "USD-SOFR-1D": "USD",
    "USD-OIS": "USD",
    "USD-FEDFUNDS": "USD",
}


def _to_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    raise TypeError(f"Unsupported date {value!r} ({type(value).__name__}).")


def _normalise_dates(dates: Iterable[Any]) -> List[dt.date]:
    out: List[dt.date] = []
    seen: set[dt.date] = set()
    for item in dates:
        d = _to_date(item)
        if d not in seen:
            seen.add(d)
            out.append(d)
    return sorted(out)


def _currency_for(curve_name: str, currency: Optional[str]) -> str:
    if currency:
        return str(currency).upper()
    token = _CURVE_NAME_CURRENCY.get(str(curve_name).upper())
    if token:
        return token
    raise CitiVelocityError(
        f"Cannot infer a Citi vol currency from curve_name={curve_name!r} "
        f"(known: {', '.join(sorted(_CURVE_NAME_CURRENCY))}). Pass currency= in the request."
    )


def _split_curves(curve: Any) -> Tuple[Any, Any]:
    """``(rl_curve, ql_curve)`` from one repo curve object, mirroring if needed.

    ``QLIRSwapCurve.handle()`` gives a ``ql.YieldTermStructureHandle`` and
    ``RLIRSwapCurve.handle()`` an ``rl.Curve``; both classes define ``handle()``
    and ``index()``, so the type has to be sniffed rather than asked for.

    A rateslib curve is mirrored into QuantLib because the Citi Velocity
    CurveStore serves rateslib curves and nothing else, and a ``-QL`` engine has
    no other way to price off Citi's own curve. A QuantLib curve is NOT mirrored
    the other way: there is no lossless route, so ``-RL`` on a QuantLib
    ``curve_source`` raises rather than guessing.
    """
    import QuantLib as ql

    handle = getattr(curve, "handle", None)
    resolved = handle() if callable(handle) else handle
    if resolved is None:
        raise TypeError(f"{type(curve).__name__} exposes no handle()/handle.")

    if isinstance(resolved, (ql.YieldTermStructureHandle, ql.RelinkableYieldTermStructureHandle)):
        return None, resolved
    if isinstance(resolved, ql.YieldTermStructure):
        return None, ql.YieldTermStructureHandle(resolved)

    from MDP.CitiVelocityExcel.curves import build_ql_mirror_curve

    return resolved, build_ql_mirror_curve(resolved)


def _cube_for_date(
    *,
    currency: str,
    when: dt.date,
    cube: Any,
    cubes: Optional[Dict[Any, Any]],
    snapshot: Optional[str],
    expiries: Optional[Sequence[str]],
    tenors: Optional[Sequence[str]],
    offsets_bp: Optional[Sequence[float]],
    strict: bool,
    client: Any,
) -> Any:
    """One :class:`SwaptionCubeData`, from whichever source was configured."""
    if cubes:
        hit = cubes.get(when) or cubes.get(when.isoformat())
        if hit is not None:
            return hit
    if cube is not None:
        return cube
    if snapshot:
        from MDP.CitiVelocityExcel.vol.live_snapshot import load_snapshot

        snap = load_snapshot(snapshot)
        if snap.as_of != when:
            raise CitiVelocityError(
                f"Snapshot {snapshot!r} is dated {snap.as_of} but a cube was requested for {when}. "
                "A cube carried to another date is a wrong number that looks right - request the "
                "date the snapshot holds, or pass cubes={date: cube}."
            )
        return snap.cube(
            expiries=expiries, tenors=tenors, offsets_bp=offsets_bp, strict=strict
        )

    from MDP.CitiVelocityExcel.vol.cube_data import fetch_cube

    if client is None:
        from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient

        client = CitiVelocityExcelClient.connect()
    return fetch_cube(
        client=client,
        currency=currency,
        as_of=when,
        expiries=expiries,
        tenors=tenors,
        offsets_bp=offsets_bp or (),
        strict=strict,
    )


def get_citivelo_vol_objects(
    *,
    curve_name: str,
    dates: Iterable[Any],
    surface_type: str = "citivelo_cube",
    engine: str = "QL",
    curves: Optional[Dict[Any, Any]] = None,
    currency: Optional[str] = None,
    citi_index: Optional[str] = None,
    cube: Any = None,
    cubes: Optional[Dict[Any, Any]] = None,
    snapshot: Optional[str] = None,
    expiries: Optional[Sequence[str]] = None,
    tenors: Optional[Sequence[str]] = None,
    offsets_bp: Optional[Sequence[float]] = None,
    strict: bool = False,
    notional: float = 1e8,
    client: Any = None,
    sabr: bool = False,
    **kwargs: Any,
) -> Dict[dt.date, Any]:
    """Build one Citi vol object per date, for ``IRSwaptionMDP.VOL_PROVIDERS``.

    Returns ``{date: vol}`` where ``vol`` is what the engine needs:

    ``engine='QL'``
        a ``ql.SwaptionVolatilityStructureHandle`` - exactly what
        ``ql.BachelierSwaptionEngine`` and ``Query/IRSwaptions``'
        ``_surface_model_vol`` already consume, so nothing downstream changes.
    ``engine='RL'``
        the :class:`CitiVeloSwaptionCube` itself, which also answers
        ``volatility(option_time, swap_length, strike, extrapolate)`` in decimals,
        so the vol-read half of ``Query/IRSwaptions/pricer.py`` needs no dispatch
        either.

    The full :class:`CitiVeloSwaptionCube` is cached for both engines and reachable
    with :func:`get_cached_citivelo_cube`; ``IRSwaptionMDP`` attaches it to the
    context metadata as ``citivelo_cube``.
    """
    _ = (surface_type, kwargs)
    from MDP.CitiVelocityExcel.vol.swaption_cube import build_citivelo_swaption_cube

    ccy = _currency_for(curve_name, currency)
    engine_token = str(engine or "QL").strip().upper()
    wanted = _normalise_dates(dates)
    out: Dict[dt.date, Any] = {}

    for when in wanted:
        curve = None
        if curves:
            curve = curves.get(when) or curves.get("live")
            if curve is None:
                for key, value in curves.items():
                    if isinstance(key, dt.datetime) and key.date() == when:
                        curve = value
                        break
        if curve is None:
            _logger.warning(
                "No curve for %s; the Citi cube's strike axis is anchored on the curve, so the "
                "node is skipped rather than anchored on a different day.",
                when,
            )
            continue

        rl_curve, ql_curve = _split_curves(curve)
        if engine_token == "RL" and rl_curve is None:
            raise CitiVelocityError(
                "source='CITIVELO-RL' needs a rateslib-backed curve, and "
                f"{type(curve).__name__} is QuantLib-backed. There is no lossless QuantLib -> "
                "rateslib mirror, so this raises rather than guessing. Use "
                "curve_source='CITIVELO' (Citi's own SOFR curve) or "
                "'ERIS_EOD_LIVE-RL_BASIC'."
            )

        data = _cube_for_date(
            currency=ccy,
            when=when,
            cube=cube,
            cubes=cubes,
            snapshot=snapshot,
            expiries=expiries,
            tenors=tenors,
            offsets_bp=offsets_bp,
            strict=strict,
            client=client,
        )
        backend = "rl-native" if engine_token == "RL" else ("ql-sabr" if sabr else "ql")
        built = build_citivelo_swaption_cube(
            cube=data,
            rl_curve=rl_curve,
            ql_curve=ql_curve,
            backend=backend,
            citi_index=citi_index,
            notional=float(notional),
        )
        _CUBE_CACHE[(str(curve_name), when.isoformat(), engine_token)] = built
        out[when] = built if engine_token == "RL" else built.ql_handle

    return out


#: ``_build_contexts`` hands ``curves=`` and ``engine=`` only to providers that
#: advertise they want them. ``MONKEYCUBE``'s provider forwards ``**kwargs``
#: straight into ``get_sabr_vol_surfaces``, so an unexpected keyword there would
#: be a TypeError, not an ignored argument.
get_citivelo_vol_objects.wants_curves = True  # type: ignore[attr-defined]
get_citivelo_vol_objects.wants_engine = True  # type: ignore[attr-defined]


def get_cached_citivelo_cube(
    curve_name: str, d: dt.date, engine: str = "QL"
) -> Optional[Any]:
    """The :class:`CitiVeloSwaptionCube` built for one date, or ``None``."""
    return _CUBE_CACHE.get((str(curve_name), d.isoformat(), str(engine).upper()))


def clear_citivelo_cube_cache() -> None:
    """Drop every cached cube. Tests use this; nothing else should need it."""
    _CUBE_CACHE.clear()

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Literal, Optional

import QuantLib as ql

from Caching.layered_cache_mixin import LayeredCacheMixin
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.MarketDataProvider import MarketDataProvider
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve

DateLike = dt.date | dt.datetime | str

_logger = logging.getLogger(__name__)

#: Curve sources whose "don't use the cache" path is not merely slower but
#: reaches OUTSIDE the process for data. ``citivelo_excel*`` falls back from the
#: CurveStore to the quotes layer, which is cached-then-**live** and drives the
#: user's signed-in Excel add-in over COM. Forwarding a swaption-level cache flag
#: into one of these is how a "rebuild my context" request becomes a COM fetch.
_CURVE_SOURCES_WITH_LIVE_REFRESH: tuple[str, ...] = (
    "CITIVELO_EXCEL",
    "CITIVELO-EXCEL",
    "CITIVELO",
    "CITI_VELO",
    "CITIVELOCITY",
)


def _curve_refresh_goes_outside(curve_source: str) -> bool:
    """True when refreshing this curve source can reach Excel or a workbook."""
    token = str(curve_source or "").strip().upper().replace("-", "_")
    return any(token.startswith(t.replace("-", "_")) for t in _CURVE_SOURCES_WITH_LIVE_REFRESH)


@dataclass
class IRSwaptionMarketContext:
    """One dated market snapshot: a curve, a vol object and an engine to use them.

    The four market fields are annotated ``Any`` because the engine decides what
    they are, not this class. Under ``engine='QL'`` they are exactly what they
    always were - ``ql.YieldTermStructureHandle``, ``ql.SwapIndex``,
    ``ql.SwaptionVolatilityStructureHandle``, ``ql.PricingEngine`` - and every
    existing provider still produces those. Under ``engine='RL'`` the curve handle
    is a ``rateslib.Curve``, the vol object is a
    :class:`~MDP.CitiVelocityExcel.vol.swaption_cube.CitiVeloSwaptionCube` and the
    pricing engine is an
    :class:`~MDP.IRSwaptions.CITIVELO.rl_engine.RLSwaptionEngine`.

    The registry was always this permissive - ``tests/test_ir_swaption_mdp.py``
    registers an engine factory returning a bare ``object()`` and drives it end to
    end - so the annotations were describing one engine rather than the contract.
    Writing ``Any`` is not a loosening; it is what the code has always done.
    """

    curve_name: str
    as_of_date: dt.date
    curve: _IRSwapGenericCurve
    curve_handle: Any
    swap_index: Any
    vol_handle: Any
    pricing_engine: Any
    provider: str
    engine: str
    surface_type: str
    source: str
    metadata: dict[str, Any]

    def id(self) -> str:
        return f"{self.curve_name}|{self.as_of_date.isoformat()}|{self.provider}-{self.engine}|{self.surface_type}"

    def resolve_pricable(self, priceable: Any, risk_weight: Optional[float] = None) -> Any:
        _ = risk_weight
        return priceable

    def meta(self) -> dict[str, Any]:
        return dict(self.metadata or {})


_KNOWN_COMPOSITE_PROVIDERS: set[str] = {
    "GSQUANT-MC-ENHANCED",
}


def _parse_source_token(source: str) -> tuple[str, str]:
    token = (source or "GSQUANT-QL").strip().replace("_", "-").upper()
    # Check for known composite provider names (longest match first).
    for composite in sorted(_KNOWN_COMPOSITE_PROVIDERS, key=len, reverse=True):
        if token.startswith(composite):
            remainder = token[len(composite):]
            provider = composite.replace("-", "_")
            if remainder.startswith("-") and len(remainder) > 1:
                engine = remainder[1:]
            else:
                engine = "QL"
            return provider, engine
    parts = [p for p in token.split("-") if p]
    if len(parts) < 2:
        raise ValueError(f"Invalid source '{source}'. Expected format '<provider>-<engine>' e.g. 'GSQUANT-QL'.")
    provider = parts[0].upper()
    engine = parts[1].upper()
    return provider, engine


def resolve_timestamp_mode(timestamp: Any) -> str:
    """``'live'`` | ``'intraday'`` | ``'eod'`` for a request timestamp.

    Delegates to ``CITIVELO_EXCEL.timestamps.resolve_request``, which is the
    curve side's answer to the same question and already carries the evidence for
    every rule. Reusing it is the point: ``pd.Timestamp`` subclasses
    ``datetime.datetime`` subclasses ``datetime.date``, so an isinstance ladder
    gets this wrong in *both* directions - testing ``date`` first swallows every
    intraday request, and testing ``datetime`` first swallows
    ``pd.Timestamp("2026-08-06")``, which is midnight and means EOD. That bug
    shipped on the curve side.

    Falls back to ``'eod'`` rather than raising: the mode only selects *where the
    vol comes from*, and the normal parse below is the thing entitled to reject a
    bad timestamp with a useful message.
    """
    try:
        from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import resolve_request

        return str(resolve_request(timestamp).mode)
    except Exception:  # noqa: BLE001
        return "eod"


def _to_date(value: DateLike) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token == "live":
            return dt.date.today()
        return dt.date.fromisoformat(value)
    raise TypeError(f"Unsupported timestamp type: {type(value)}")


def _normalize_dates(values: Iterable[DateLike]) -> list[dt.date]:
    out: list[dt.date] = []
    seen: set[dt.date] = set()
    for v in values:
        d = _to_date(v)
        if d not in seen:
            seen.add(d)
            out.append(d)
    return sorted(out)


def _citivelo_vol_provider(
    *,
    curve_name: str,
    dates: list[dt.date],
    surface_type: str,
    **kwargs: Any,
) -> dict[dt.date, Any]:
    """Citi Velocity's swaption cube, as a ``VOL_PROVIDERS`` entry.

    A module-level function rather than a static method so the two flags below
    survive attribute lookup: ``_build_contexts`` reads them off whatever object
    the registry holds.
    """
    from MDP.IRSwaptions.CITIVELO.provider import get_citivelo_vol_objects

    return get_citivelo_vol_objects(
        curve_name=curve_name, dates=dates, surface_type=surface_type, **kwargs
    )


#: This provider needs the curve (its strike axis is anchored on one) and the
#: engine token (it returns a QuantLib handle under ``-QL`` and the cube itself
#: under ``-RL``). Both are passed ONLY to providers that ask, because
#: ``MONKEYCUBE``'s provider forwards ``**kwargs`` straight into
#: ``get_sabr_vol_surfaces``, where an unexpected keyword is a TypeError.
_citivelo_vol_provider.wants_curves = True  # type: ignore[attr-defined]
_citivelo_vol_provider.wants_engine = True  # type: ignore[attr-defined]
#: ...and the resolved timestamp mode, so a ``"live"`` request is not served the
#: warmed close. ``_to_date`` turns ``"live"`` into ``date.today()``, which is
#: indistinguishable from a request for today by the time the provider sees it.
_citivelo_vol_provider.wants_timestamp_mode = True  # type: ignore[attr-defined]


class IRSwaptionMDP(LayeredCacheMixin, MarketDataProvider[IRSwaptionMarketContext]):
    _CACHE_VERSION = "v1"
    _CACHE_ATTR = "_irswaption_mdp_cache"

    VOL_PROVIDERS: dict[str, Callable[..., dict[dt.date, ql.SwaptionVolatilityStructureHandle]]] = {}
    ENGINE_FACTORIES: dict[str, Callable[..., ql.PricingEngine]] = {}

    def __init__(
        self,
        source: str = "GSQUANT-QL",
        *,
        curve_source: str = "ERIS_EOD_LIVE-QL_BASIC",
        data_dir: Optional[str] = None,
        cache_stem: Optional[str] = None,
        force_refresh: bool = False,
        request_defaults: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ):
        """``request_defaults`` are merged into every request's kwargs.

        The escape hatch for provider options a caller cannot otherwise reach:
        ``IRSwaptionsTB.get_timeseries`` builds its ``bulk_get_data`` request from
        a fixed set of keys and forwards nothing else, so an option like
        ``verify=False`` (which turns off the CITIVELO cube's 237-second
        node-ordering check - see the provider) had no route through. They land in
        ``_default_request_kwargs``, so they are part of the context cache key and
        two settings cache separately rather than aliasing.
        """
        self.curve_source = curve_source
        # Whether a request's `ignore_cache` should also bypass the CURVE cache.
        # It should not, by default: see _fetch_curve_map. `force_refresh=True`
        # on the constructor is the explicit "refresh everything" switch and does
        # carry through.
        self.curve_ignore_cache = bool(force_refresh)
        self._default_request_kwargs: dict[str, Any] = dict(request_defaults or {})
        if data_dir is not None:
            self._default_request_kwargs["data_dir"] = str(data_dir)
        self._provider_name, self._engine_name = _parse_source_token(source)
        self._runtime_cache: dict[str, IRSwaptionMarketContext] = {}
        self._curve_mdp = IRSwapsMDP(source=curve_source, **kwargs)

        LayeredCacheMixin.__init__(self, source=source, force_refresh=force_refresh, **kwargs)

        default_req_token = self._request_kwargs_token(self._default_request_kwargs)
        stem = cache_stem or f"IRSwaptionMDP_{self._CACHE_VERSION}_{source}_{curve_source}_{default_req_token}"
        path = self.default_cache_path(stem=stem)
        self.open_cache(cache_attr=self._CACHE_ATTR, path=path)

        if "GSQUANT" not in self.VOL_PROVIDERS:
            self.VOL_PROVIDERS["GSQUANT"] = self._gsquant_vol_provider
        if "MONKEYCUBE" not in self.VOL_PROVIDERS:
            self.VOL_PROVIDERS["MONKEYCUBE"] = self._monkeycube_vol_provider
        if "GSQUANT_MC_ENHANCED" not in self.VOL_PROVIDERS:
            self.VOL_PROVIDERS["GSQUANT_MC_ENHANCED"] = self._gsquant_mc_enhanced_vol_provider
        if "CITIVELO" not in self.VOL_PROVIDERS:
            self.VOL_PROVIDERS["CITIVELO"] = _citivelo_vol_provider
        if "QL" not in self.ENGINE_FACTORIES:
            self.ENGINE_FACTORIES["QL"] = self._ql_engine_factory
        if "RL" not in self.ENGINE_FACTORIES:
            self.ENGINE_FACTORIES["RL"] = self._rl_engine_factory

    @staticmethod
    def _gsquant_vol_provider(
        *,
        curve_name: str,
        dates: list[dt.date],
        surface_type: str,
        **kwargs: Any,
    ) -> dict[dt.date, ql.SwaptionVolatilityStructureHandle]:
        _ = kwargs
        from MDP.IRSwaptions.GSQUANT.ql.grid import get_atmf_grid

        return get_atmf_grid(curve=curve_name, dates=dates, surface_type=surface_type)

    @staticmethod
    def _monkeycube_vol_provider(
        *,
        curve_name: str,
        dates: list[dt.date],
        surface_type: str,
        **kwargs: Any,
    ) -> dict[dt.date, ql.SwaptionVolatilityStructureHandle]:
        from MDP.IRSwaptions.MONKEYCUBE.provider import get_sabr_vol_surfaces

        return get_sabr_vol_surfaces(
            curve_name=curve_name, dates=dates, surface_type=surface_type, **kwargs
        )

    @staticmethod
    def _gsquant_mc_enhanced_vol_provider(
        *,
        curve_name: str,
        dates: list[dt.date],
        surface_type: str,
        **kwargs: Any,
    ) -> dict[dt.date, ql.SwaptionVolatilityStructureHandle]:
        from MDP.IRSwaptions.GSQUANT_MC_ENHANCED.provider import get_enhanced_vol_surfaces

        return get_enhanced_vol_surfaces(
            curve_name=curve_name, dates=dates, surface_type=surface_type, **kwargs
        )

    @staticmethod
    def _ql_engine_factory(
        *,
        curve_handle: ql.YieldTermStructureHandle,
        vol_handle: ql.SwaptionVolatilityStructureHandle,
        day_counter: ql.DayCounter,
        **kwargs: Any,
    ) -> ql.PricingEngine:
        _ = kwargs
        try:
            return ql.BachelierSwaptionEngine(curve_handle, vol_handle)
        except TypeError:
            return ql.BachelierSwaptionEngine(curve_handle, vol_handle, day_counter)

    @staticmethod
    def _rl_engine_factory(
        *,
        curve_handle: Any,
        vol_handle: Any,
        day_counter: Any,
        **kwargs: Any,
    ) -> Any:
        """The rateslib swaption engine. See :mod:`MDP.IRSwaptions.CITIVELO.rl_engine`."""
        from MDP.IRSwaptions.CITIVELO.rl_engine import make_rl_swaption_engine

        return make_rl_swaption_engine(
            curve_handle=curve_handle, vol_handle=vol_handle, day_counter=day_counter, **kwargs
        )

    def _cache_key(
        self,
        *,
        curve_name: str,
        d: dt.date,
        provider: str,
        engine: str,
        surface_type: str,
        request_token: str = "",
    ) -> str:
        return "|".join(
            [
                self._CACHE_VERSION,
                str(curve_name).upper(),
                d.isoformat(),
                provider.upper(),
                engine.upper(),
                str(surface_type).lower(),
                str(self.curve_source).upper(),
                str(request_token),
            ]
        )

    @staticmethod
    def _normalize_request_value(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dt.datetime):
            return value.isoformat()
        if isinstance(value, dt.date):
            return value.isoformat()
        if isinstance(value, dict):
            return {
                str(k): IRSwaptionMDP._normalize_request_value(v)
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            }
        if isinstance(value, (list, tuple, set)):
            return [IRSwaptionMDP._normalize_request_value(v) for v in value]
        return repr(value)

    def _request_kwargs_token(self, request_kwargs: dict[str, Any]) -> str:
        if not request_kwargs:
            return "default"
        payload = self._normalize_request_value(request_kwargs)
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]

    def _merge_request_kwargs(self, request_kwargs: dict[str, Any]) -> dict[str, Any]:
        merged = dict(self._default_request_kwargs)
        merged.update(request_kwargs or {})
        return merged

    def _cache_get(self, key: str) -> Optional[IRSwaptionMarketContext]:
        if key in self._runtime_cache:
            return self._runtime_cache[key]
        mapping = getattr(self, self._CACHE_ATTR)
        try:
            v = mapping.get(key)
        except Exception:
            return None
        if isinstance(v, IRSwaptionMarketContext):
            self._runtime_cache[key] = v
            return v
        return None

    def _cache_put(self, key: str, value: IRSwaptionMarketContext) -> None:
        self._runtime_cache[key] = value
        mapping = getattr(self, self._CACHE_ATTR)
        try:
            mapping[key] = value
        except Exception:
            # QuantLib handles may not be serializable across environments.
            mapping[key] = {
                "curve_name": value.curve_name,
                "as_of_date": value.as_of_date.isoformat(),
                "provider": value.provider,
                "engine": value.engine,
                "surface_type": value.surface_type,
            }

    @staticmethod
    def _assert_curve_matches_engine(*, engine: str, curve: Any, curve_handle: Any) -> None:
        """Refuse a curve the engine cannot price with, and say which one to use.

        ``handle()`` returns a ``ql.YieldTermStructureHandle`` on the QuantLib
        curve backend and a ``rateslib.Curve`` on the rateslib one, and both
        classes define it, so the only honest check is on the returned object.
        """
        token = str(engine).upper()
        is_ql = isinstance(
            curve_handle, (ql.YieldTermStructureHandle, ql.RelinkableYieldTermStructureHandle, ql.YieldTermStructure)
        )
        if token == "QL" and not is_ql:
            raise TypeError(
                f"engine='QL' needs a QuantLib curve, but {type(curve).__name__}.handle() returned "
                f"{type(curve_handle).__name__}. Use a -QL_BASIC curve_source (e.g. "
                "'ERIS_EOD_LIVE-QL_BASIC'), or 'CITIVELO-RL' if you meant the rateslib engine."
            )
        if token == "RL" and is_ql:
            raise TypeError(
                f"engine='RL' needs a rateslib curve, but {type(curve).__name__}.handle() returned "
                f"{type(curve_handle).__name__}. Use curve_source='CITIVELO' (Citi's own SOFR "
                "curve) or 'ERIS_EOD_LIVE-RL_BASIC'."
            )

    @staticmethod
    def _extract_curve_for_date(curve_map: dict[Any, _IRSwapGenericCurve], d: dt.date) -> Optional[_IRSwapGenericCurve]:
        if d in curve_map:
            return curve_map[d]
        for k, v in curve_map.items():
            if isinstance(k, dt.datetime) and k.date() == d:
                return v
            if isinstance(k, dt.date) and k == d:
                return v
        return curve_map.get("live")

    def _fetch_curve_map(
        self,
        *,
        curve_name: str,
        dates: list[dt.date],
        ignore_cache: bool,
    ) -> dict[Any, _IRSwapGenericCurve]:
        """Fetch the curves the contexts will carry.

        ``ignore_cache`` here is the CURVE-level flag, which is deliberately NOT
        the request's own ``ignore_cache``. The two mean different things and one
        of them has a side effect outside the process:

        * on a swaption request, ``ignore_cache`` means "do not serve me a cached
          :class:`IRSwaptionMarketContext`" - it is about this MDP's own layered
          cache;
        * on a curve request, it means "do not serve me a warmed curve artefact",
          and for ``citivelo_excel*`` the CurveStore fast path is gated on exactly
          that flag. Bypassing it drops through to the quotes layer, which is
          cached-then-**live**, so on a cold tag cache the curve is rebuilt by
          driving the user's signed-in Excel add-in over COM.

        Forwarding one into the other meant a caller who wanted a fresh context -
        the ordinary thing to want after registering a provider, or in a test -
        silently got a COM fetch against a 3 GB Excel that only a human can
        restart. It also made the common case impossible: rebuild a context off
        the warmed curve.

        So they are separate knobs now. ``curve_ignore_cache`` on the request (or
        ``force_refresh=True`` on the constructor) is the explicit way to ask for
        a curve refresh, and it says so out loud when that refresh can go outside.
        """
        if ignore_cache and _curve_refresh_goes_outside(self.curve_source):
            _logger.warning(
                "curve_ignore_cache=True with curve_source=%r bypasses the CurveStore. That "
                "source rebuilds through a cached-then-LIVE quotes layer, so on a cold tag cache "
                "this drives the signed-in Excel add-in over COM. Drop the flag to use the warmed "
                "curve - it is the same curve.",
                self.curve_source,
            )
        # Route AROUND bulk_get_data for these sources. Not a preference: the
        # CurveStore fast path lives only in IRSwapsMDP.get_data, so
        # bulk_get_data for citivelo_excel* falls through to the fetcher and its
        # cached-then-LIVE quotes layer - which means bulk reaches Excel even
        # when ignore_cache is False and a warmed curve is sitting on disk.
        # Measured: bulk_get_data(..., ignore_cache=False) raised
        # AddInNotSignedInError while get_data(..., ignore_cache=False) served the
        # same day from asset USD-SOFR-1D-CITIVELOEXCEL without touching COM.
        # The upstream fix is a CurveStore branch in bulk_get_data; until then the
        # swaption layer must not be the thing that opens Excel.
        prefer_single = _curve_refresh_goes_outside(self.curve_source)

        bulk_req = {
            "curve_name": curve_name,
            "timestamps": list(dates),
            "ignore_cache": bool(ignore_cache),
        }
        bulk_exc: Optional[Exception] = None
        if not prefer_single:
            try:
                out = self._curve_mdp.bulk_get_data(dict(bulk_req))
                if isinstance(out, dict):
                    return out
            except Exception as exc:
                bulk_exc = exc

        # Some IRSwapsMDP sources do not implement bulk_get_data; fallback to one-by-one.
        out: dict[Any, _IRSwapGenericCurve] = {}
        single_exc: Optional[Exception] = None
        for d in dates:
            req = {"curve_name": curve_name, "timestamp": d, "ignore_cache": bool(ignore_cache)}
            try:
                curve = self._curve_mdp.get_data(req)
            except Exception as exc:  # noqa: BLE001 - one bad date must not kill a batch
                single_exc = single_exc or exc
                _logger.warning(
                    "no %s curve for %s (%s: %s)", self.curve_source, d, type(exc).__name__, exc
                )
                continue
            if curve is not None:
                out[d] = curve

        if out:
            return out

        # Only now is bulk worth trying for a store-backed source: the per-date
        # path found nothing, so there is no warmed curve to protect.
        if prefer_single:
            try:
                bulk_out = self._curve_mdp.bulk_get_data(dict(bulk_req))
                if isinstance(bulk_out, dict) and bulk_out:
                    return bulk_out
            except Exception as exc:
                bulk_exc = exc
            if bulk_exc is None:
                bulk_exc = single_exc

        cause = bulk_exc or single_exc
        if cause is not None:
            hint = ""
            if type(cause).__name__ == "AddInNotSignedInError" or "add-in" in str(cause).lower():
                # Naming this is the difference between a five-minute fix and an
                # afternoon. The CurveStore has the curve; what reaches Excel is
                # the FIXINGS lookup inside the store read
                # (IRSwapsMDP._load_citivelo_excel_curve_store_point ->
                # CITIVELO_EXCEL.fixings.fixings_for -> citi_fixings -> the
                # cached-then-live quotes layer), and for USD_SOFR there is no
                # publisher-direct fallback in CITIVELO_EXCEL.official_sources.
                hint = (
                    " The curve itself is warmed; it is the published overnight FIXINGS that "
                    "went looking for the add-in. Sign in to Velocity, or warm the fixing tags "
                    "into the CitiVeloTagCache, or use a curve_source that does not depend on "
                    "them (e.g. 'ERIS_EOD_LIVE-RL_BASIC')."
                )
            raise RuntimeError(
                f"Failed to fetch IR swap curves for '{curve_name}' from curve_source="
                f"{self.curve_source!r} ({type(cause).__name__}: {cause}).{hint}"
            ) from cause
        raise RuntimeError(
            f"Failed to fetch IR swap curves for '{curve_name}' from curve_source="
            f"{self.curve_source!r}."
        )

    def _build_contexts(
        self,
        *,
        curve_name: str,
        dates: list[dt.date],
        provider: str,
        engine: str,
        surface_type: str,
        ignore_cache: bool,
        request_kwargs: dict[str, Any],
        curve_ignore_cache: bool = False,
        timestamp_mode: str = "eod",
    ) -> dict[dt.date, IRSwaptionMarketContext]:
        out: dict[dt.date, IRSwaptionMarketContext] = {}
        effective_request_kwargs = self._merge_request_kwargs(request_kwargs)
        request_token = self._request_kwargs_token(effective_request_kwargs)

        misses: list[dt.date] = []
        if not ignore_cache:
            for d in dates:
                k = self._cache_key(
                    curve_name=curve_name,
                    d=d,
                    provider=provider,
                    engine=engine,
                    surface_type=surface_type,
                    request_token=request_token,
                )
                hit = self._cache_get(k)
                if hit is not None:
                    out[d] = hit
                else:
                    misses.append(d)
        else:
            misses = list(dates)

        if not misses:
            return out

        vol_provider = self.VOL_PROVIDERS.get(provider.upper())
        if vol_provider is None:
            raise KeyError(f"Unknown swaption vol provider '{provider}'. Registered providers: {sorted(self.VOL_PROVIDERS)}")
        engine_factory = self.ENGINE_FACTORIES.get(engine.upper())
        if engine_factory is None:
            raise KeyError(f"Unknown swaption engine '{engine}'. Registered engines: {sorted(self.ENGINE_FACTORIES)}")

        curve_map = self._fetch_curve_map(
            curve_name=curve_name,
            dates=misses,
            # NOT `ignore_cache`: that one is about this MDP's context cache.
            # See _fetch_curve_map for why conflating them reached Excel.
            ignore_cache=curve_ignore_cache,
        )
        # Checked BEFORE the vol provider runs. The provider call below is
        # wrapped in a broad except that falls back date by date, so a curve the
        # engine cannot use would surface as an empty vol map and then as a bare
        # KeyError on the requested date - the caller would never learn why.
        for candidate in curve_map.values():
            if candidate is None:
                continue
            handle = getattr(candidate, "handle", None)
            if callable(handle):
                self._assert_curve_matches_engine(
                    engine=engine, curve=candidate, curve_handle=handle()
                )
            break

        # Additive, and opt-in per provider: a provider whose strike axis is
        # anchored on the curve needs the curve, and one that serves a different
        # object per engine needs the engine token. GSQUANT and
        # GSQUANT_MC_ENHANCED swallow **kwargs, but MONKEYCUBE forwards them into
        # get_sabr_vol_surfaces, where an unexpected keyword raises - so these
        # are handed only to providers that advertise they want them.
        provider_kwargs = dict(effective_request_kwargs)
        if getattr(vol_provider, "wants_curves", False):
            provider_kwargs.setdefault("curves", curve_map)
        if getattr(vol_provider, "wants_engine", False):
            provider_kwargs.setdefault("engine", engine.upper())
        if getattr(vol_provider, "wants_timestamp_mode", False):
            provider_kwargs.setdefault("timestamp_mode", timestamp_mode)
        try:
            vol_map = vol_provider(
                curve_name=curve_name,
                dates=misses,
                surface_type=surface_type,
                **provider_kwargs,
            )
        except Exception as bulk_exc:  # noqa: BLE001 - fall back per date, but say why
            _logger.warning(
                "%s vol provider failed on the whole batch (%s: %s); retrying date by date.",
                provider.upper(),
                type(bulk_exc).__name__,
                bulk_exc,
            )
            vol_map = {}
            for d in misses:
                try:
                    one = vol_provider(
                        curve_name=curve_name,
                        dates=[d],
                        surface_type=surface_type,
                        **provider_kwargs,
                    )
                except Exception as one_exc:  # noqa: BLE001 - one bad date must not kill a batch
                    _logger.warning(
                        "%s vol provider produced nothing for %s (%s: %s).",
                        provider.upper(),
                        d,
                        type(one_exc).__name__,
                        one_exc,
                    )
                    continue
                if isinstance(one, dict):
                    vol_map.update(one)

        for d in misses:
            curve = self._extract_curve_for_date(curve_map, d)
            if curve is None:
                continue
            if not hasattr(curve, "handle") or not hasattr(curve, "index"):
                raise TypeError(
                    f"IRSwaptionMDP requires a QuantLib curve backend with handle()/index() methods. Got {type(curve).__name__}"
                )
            vol_handle = vol_map.get(d)
            if vol_handle is None:
                continue

            curve_handle = curve.handle()
            swap_index = curve.index()
            # The hasattr() gate above passes for a rateslib curve too - both
            # backends define handle() and index() - and used to let the wrong
            # types through to a QuantLib engine, which then failed inside SWIG
            # with a message about nothing in particular. Check what came OUT.
            self._assert_curve_matches_engine(
                engine=engine, curve=curve, curve_handle=curve_handle
            )
            day_counter = curve.daycounter() if hasattr(curve, "daycounter") else ql.Actual365Fixed()
            if day_counter is None:
                # RLIRSwapCurve does not override daycounter(), and the base class
                # stub makes hasattr() true, so the Actual365Fixed fallback above
                # is unreachable for it and None flows on into the engine factory.
                day_counter = ql.Actual365Fixed()
            pricing_engine = engine_factory(
                curve_handle=curve_handle,
                vol_handle=vol_handle,
                day_counter=day_counter,
            )

            metadata: dict[str, Any] = {
                "curve_source": self.curve_source,
                "surface_type": surface_type,
                "as_of_date": d.isoformat(),
            }
            if "data_dir" in effective_request_kwargs:
                metadata["data_dir"] = effective_request_kwargs["data_dir"]

            if provider.upper() == "MONKEYCUBE":
                from MDP.IRSwaptions.MONKEYCUBE.provider import get_cached_cube

                vol_cube = get_cached_cube(curve_name, d)
                if vol_cube is not None:
                    metadata["vol_cube"] = vol_cube

            if provider.upper() == "GSQUANT_MC_ENHANCED":
                from MDP.IRSwaptions.GSQUANT_MC_ENHANCED.provider import get_cached_enhanced_cube

                vol_cube = get_cached_enhanced_cube(curve_name, d)
                if vol_cube is not None:
                    metadata["vol_cube"] = vol_cube

            if provider.upper() == "CITIVELO":
                from MDP.IRSwaptions.CITIVELO.provider import (
                    get_cached_citivelo_cube,
                    get_cached_citivelo_provenance,
                )

                # Where the numbers came from, and what shape they were. Exposed
                # because "did this read the warmed store or drive Excel?" and
                # "is this an ATM-only day?" were both invisible before, and the
                # second one reads exactly like a cache miss.
                prov = get_cached_citivelo_provenance(curve_name, d, engine)
                if prov is not None:
                    metadata["citivelo_provenance"] = prov
                metadata["timestamp_mode"] = timestamp_mode

                citi_cube = get_cached_citivelo_cube(curve_name, d, engine)
                if citi_cube is not None:
                    # Deliberately NOT metadata['vol_cube']: that key routes
                    # pricer.py's leg_cube_vol into cube.volatility_at_point(),
                    # which takes an option TIME and has to reconstruct an option
                    # DATE from it. The reconstruction moves the strike offset and
                    # therefore the volatility, so the Citi cube is read the way
                    # QuantLib reads a surface instead - through vol_handle - and
                    # the object is exposed here for anything that wants the
                    # smile, the forwards or the other backend.
                    metadata["citivelo_cube"] = citi_cube

            ctx = IRSwaptionMarketContext(
                curve_name=curve_name,
                as_of_date=d,
                curve=curve,
                curve_handle=curve_handle,
                swap_index=swap_index,
                vol_handle=vol_handle,
                pricing_engine=pricing_engine,
                provider=provider.upper(),
                engine=engine.upper(),
                surface_type=surface_type,
                source=f"{provider.upper()}-{engine.upper()}",
                metadata=metadata,
            )
            k = self._cache_key(
                curve_name=curve_name,
                d=d,
                provider=provider,
                engine=engine,
                surface_type=surface_type,
                request_token=request_token,
            )
            self._cache_put(k, ctx)
            out[d] = ctx

        return out

    def _parse_single_request(self, request: dict[str, Any]) -> dict[str, Any]:
        req = dict(request or {})
        endpoint = str(req.pop("endpoint", "swaption_snapshot")).strip().lower()
        if endpoint != "swaption_snapshot":
            raise NotImplementedError(f"Unsupported endpoint '{endpoint}'. Supported: swaption_snapshot")

        curve_name = req.pop("curve_name", None)
        if not curve_name:
            raise ValueError("Request must include 'curve_name'.")

        timestamp = req.pop("timestamp", None)
        if timestamp is None:
            raise ValueError("Request must include 'timestamp'.")

        surface_type = str(req.pop("surface_type", "atmf_normal")).strip().lower()
        ignore_cache = bool(req.pop("ignore_cache", False))
        curve_ignore_cache = bool(req.pop("curve_ignore_cache", self.curve_ignore_cache))
        source = str(req.pop("source", self.source))
        provider, engine = _parse_source_token(source)
        request_kwargs = self._merge_request_kwargs(req)

        return {
            "curve_name": str(curve_name),
            "date": _to_date(timestamp),
            # Resolved from the RAW timestamp, before _to_date flattens it. A
            # provider that must not serve a warmed close to a "live" request
            # cannot recover the distinction afterwards.
            "timestamp_mode": resolve_timestamp_mode(timestamp),
            "curve_ignore_cache": curve_ignore_cache,
            "provider": provider,
            "engine": engine,
            "surface_type": surface_type,
            "ignore_cache": ignore_cache,
            "kwargs": request_kwargs,
        }

    def _parse_bulk_request(self, request: dict[str, Any]) -> dict[str, Any]:
        req = dict(request or {})
        endpoint = str(req.pop("endpoint", "swaption_snapshot")).strip().lower()
        if endpoint != "swaption_snapshot":
            raise NotImplementedError(f"Unsupported endpoint '{endpoint}'. Supported: swaption_snapshot")

        curve_name = req.pop("curve_name", None)
        if not curve_name:
            raise ValueError("Request must include 'curve_name'.")

        timestamps = req.pop("timestamps", None)
        if timestamps is None:
            raise ValueError("Bulk request must include 'timestamps'.")
        if isinstance(timestamps, (str, dt.date, dt.datetime)):
            raw_list = [timestamps]
        else:
            raw_list = list(timestamps)
        date_list = _normalize_dates(raw_list)
        # One mode for the batch. 'live' only if EVERY timestamp is live: a mixed
        # batch that resolved to live would stop the whole range reading the store
        # to satisfy one entry, which is the expensive direction to be wrong in.
        modes = {resolve_timestamp_mode(t) for t in raw_list}
        bulk_mode = modes.pop() if len(modes) == 1 else (
            "intraday" if "intraday" in modes else "eod"
        )

        surface_type = str(req.pop("surface_type", "atmf_normal")).strip().lower()
        ignore_cache = bool(req.pop("ignore_cache", False))
        curve_ignore_cache = bool(req.pop("curve_ignore_cache", self.curve_ignore_cache))
        source = str(req.pop("source", self.source))
        provider, engine = _parse_source_token(source)
        request_kwargs = self._merge_request_kwargs(req)

        return {
            "curve_name": str(curve_name),
            "dates": date_list,
            "timestamp_mode": bulk_mode,
            "curve_ignore_cache": curve_ignore_cache,
            "provider": provider,
            "engine": engine,
            "surface_type": surface_type,
            "ignore_cache": ignore_cache,
            "kwargs": request_kwargs,
        }

    def get_pricer(self, request: dict[str, Any]) -> IRSwaptionMarketContext:
        return self.get_data(request)

    def get_data(self, request: dict[str, Any]) -> IRSwaptionMarketContext:
        p = self._parse_single_request(request)
        ctxs = self._build_contexts(
            curve_name=p["curve_name"],
            dates=[p["date"]],
            provider=p["provider"],
            engine=p["engine"],
            surface_type=p["surface_type"],
            ignore_cache=p["ignore_cache"],
            curve_ignore_cache=p["curve_ignore_cache"],
            request_kwargs=p["kwargs"],
            timestamp_mode=p["timestamp_mode"],
        )
        return ctxs[p["date"]]

    def bulk_get_data(self, request: dict[str, Any]) -> dict[dt.date, IRSwaptionMarketContext]:
        p = self._parse_bulk_request(request)
        return self._build_contexts(
            curve_name=p["curve_name"],
            dates=p["dates"],
            provider=p["provider"],
            engine=p["engine"],
            surface_type=p["surface_type"],
            ignore_cache=p["ignore_cache"],
            curve_ignore_cache=p["curve_ignore_cache"],
            request_kwargs=p["kwargs"],
            timestamp_mode=p["timestamp_mode"],
        )

    def get_bulk_data(self, request: dict[str, Any]) -> dict[dt.date, IRSwaptionMarketContext]:
        return self.bulk_get_data(request)

    def get_bulk_pricer(self, request: dict[str, Any]) -> dict[dt.date, IRSwaptionMarketContext]:
        return self.bulk_get_data(request)

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Literal, Optional

import QuantLib as ql

from Caching.DiskCacheMixin import DiskCacheMixin
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.MarketDataProvider import MarketDataProvider
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve

DateLike = dt.date | dt.datetime | str


@dataclass
class IRSwaptionMarketContext:
    curve_name: str
    as_of_date: dt.date
    curve: _IRSwapGenericCurve
    curve_handle: ql.YieldTermStructureHandle
    swap_index: ql.SwapIndex
    vol_handle: ql.SwaptionVolatilityStructureHandle
    pricing_engine: ql.PricingEngine
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


def _parse_source_token(source: str) -> tuple[str, str]:
    token = (source or "GSQUANT-QL").strip().replace("_", "-")
    parts = [p for p in token.split("-") if p]
    if len(parts) < 2:
        raise ValueError(f"Invalid source '{source}'. Expected format '<provider>-<engine>' e.g. 'GSQUANT-QL'.")
    provider = parts[0].upper()
    engine = parts[1].upper()
    return provider, engine


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


class IRSwaptionMDP(DiskCacheMixin, MarketDataProvider[IRSwaptionMarketContext]):
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
        **kwargs: Any,
    ):
        self.curve_source = curve_source
        self._default_request_kwargs: dict[str, Any] = {}
        if data_dir is not None:
            self._default_request_kwargs["data_dir"] = str(data_dir)
        self._provider_name, self._engine_name = _parse_source_token(source)
        self._runtime_cache: dict[str, IRSwaptionMarketContext] = {}
        self._curve_mdp = IRSwapsMDP(source=curve_source, **kwargs)

        DiskCacheMixin.__init__(self, source=source, force_refresh=force_refresh, **kwargs)

        default_req_token = self._request_kwargs_token(self._default_request_kwargs)
        stem = cache_stem or f"IRSwaptionMDP_{self._CACHE_VERSION}_{source}_{curve_source}_{default_req_token}"
        path = self.default_cache_path(stem=stem)
        self.open_cache(cache_attr=self._CACHE_ATTR, path=path)

        if "GSQUANT" not in self.VOL_PROVIDERS:
            self.VOL_PROVIDERS["GSQUANT"] = self._gsquant_vol_provider
        if "MONKEYCUBE" not in self.VOL_PROVIDERS:
            self.VOL_PROVIDERS["MONKEYCUBE"] = self._monkeycube_vol_provider
        if "QL" not in self.ENGINE_FACTORIES:
            self.ENGINE_FACTORIES["QL"] = self._ql_engine_factory

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
        bulk_req = {
            "curve_name": curve_name,
            "timestamps": list(dates),
            "ignore_cache": bool(ignore_cache),
        }
        bulk_exc: Optional[Exception] = None
        try:
            out = self._curve_mdp.bulk_get_data(dict(bulk_req))
            if isinstance(out, dict):
                return out
        except Exception as exc:
            bulk_exc = exc

        # Some IRSwapsMDP sources do not implement bulk_get_data; fallback to one-by-one.
        out: dict[Any, _IRSwapGenericCurve] = {}
        for d in dates:
            req = {"curve_name": curve_name, "timestamp": d, "ignore_cache": bool(ignore_cache)}
            try:
                curve = self._curve_mdp.get_data(req)
            except Exception:
                continue
            if curve is not None:
                out[d] = curve

        if out:
            return out

        if bulk_exc is not None:
            raise RuntimeError(
                f"Failed to fetch IR swap curves for '{curve_name}' via bulk and single-date fallback."
            ) from bulk_exc
        raise RuntimeError(f"Failed to fetch IR swap curves for '{curve_name}'.")

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
            ignore_cache=ignore_cache,
        )
        try:
            vol_map = vol_provider(
                curve_name=curve_name,
                dates=misses,
                surface_type=surface_type,
                **effective_request_kwargs,
            )
        except Exception:
            vol_map = {}
            for d in misses:
                try:
                    one = vol_provider(
                        curve_name=curve_name,
                        dates=[d],
                        surface_type=surface_type,
                        **effective_request_kwargs,
                    )
                except Exception:
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
            day_counter = curve.daycounter() if hasattr(curve, "daycounter") else ql.Actual365Fixed()
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
        source = str(req.pop("source", self.source))
        provider, engine = _parse_source_token(source)
        request_kwargs = self._merge_request_kwargs(req)

        return {
            "curve_name": str(curve_name),
            "date": _to_date(timestamp),
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
            date_list = _normalize_dates([timestamps])
        else:
            date_list = _normalize_dates(timestamps)

        surface_type = str(req.pop("surface_type", "atmf_normal")).strip().lower()
        ignore_cache = bool(req.pop("ignore_cache", False))
        source = str(req.pop("source", self.source))
        provider, engine = _parse_source_token(source)
        request_kwargs = self._merge_request_kwargs(req)

        return {
            "curve_name": str(curve_name),
            "dates": date_list,
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
            request_kwargs=p["kwargs"],
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
            request_kwargs=p["kwargs"],
        )

    def get_bulk_data(self, request: dict[str, Any]) -> dict[dt.date, IRSwaptionMarketContext]:
        return self.bulk_get_data(request)

    def get_bulk_pricer(self, request: dict[str, Any]) -> dict[dt.date, IRSwaptionMarketContext]:
        return self.bulk_get_data(request)

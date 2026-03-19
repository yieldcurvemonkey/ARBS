import contextlib
import datetime
import io
import sys
import threading
from typing import Any, Dict, Iterable, List, Literal, Optional, Union

import pandas as pd
import pytz
import tqdm 

from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base._GenericPricable import _GenericPricable
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve


class IRSwapsMDP(MarketDataProvider[_GenericPricable]):
    _BARCHART_STIRF_STATE: Dict[str, Any] = {
        "builder": None,
        "lock": threading.RLock(),
        "io_lock": threading.RLock(),
    }
    _CURVE_STORE_STATE: Dict[str, Any] = {
        "store": None,
        "lock": threading.Lock(),
    }

    def __init__(self, source: str = "CME_NY_EOD_LIVE-ql_basic", force_refresh_fixings: Optional[bool] = False, **kwargs: Any):
        super().__init__(source, **kwargs)
        self.force_refresh_fixings = force_refresh_fixings

        if "SDR_INTRADAY-RL" in source.upper() or "SDR_INTRADAY_RL" in source.upper() or "SDR_3PM_EOD-RL" in source.upper() or "SDR_3PM_EOD_RL" in source.upper():
            from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache

            self._rl_curve_cache = _RLCurveCache(cache_name="SDR_INTRADAY-RL_CURVE_CACHE")

        if "ERIS_EOD_LIVE-RL_BASIC" in source.upper() or "ERIS_EOD_LIVE_RL_BASIC" in source.upper():
            from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache

            self._rl_curve_cache = _RLCurveCache(cache_name="ERIS_EOD_LIVE-RL_BASIC")

        if "ERIS_EOD_LIVE-RL_BASIC-NOJUMPS" in source.upper() or "ERIS_EOD_LIVE-RL_BASIC-NOJUMPS" in source.upper():
            from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache

            self._rl_curve_cache = _RLCurveCache(cache_name="ERIS_EOD_LIVE-RL_BASIC-NOJUMPS")

        if "GSQUANT-RL" in source.upper() or "GSQUANT_RL" in source.upper():
            from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache

            self._rl_curve_cache = _RLCurveCache(cache_name="GSQUANT-RL_CURVE_CACHE")

    @staticmethod
    def _get_curve_store() -> Any:
        S = IRSwapsMDP._CURVE_STORE_STATE
        with S["lock"]:
            if S["store"] is None:
                from Caching.curve_store import CurveStore

                S["store"] = CurveStore.default()
            return S["store"]

    def _get_barchart_stirf_curve_builder(self) -> Any:
        from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE

        S = IRSwapsMDP._BARCHART_STIRF_STATE
        with S["lock"]:
            if S["builder"] is None:
                S["builder"] = BARCHART_STIRF_CURVE()
            return S["builder"]

    def _curve_store_source_family(self) -> Optional[str]:
        source = str(self.source).upper()
        if source in {"BARCHART_STIRF-RL", "BARCHART_STIRF_RL"}:
            return "barchart_stirf"
        if source in {"ERIS_EOD_LIVE-RL_BASIC", "ERIS_EOD_LIVE_RL_BASIC"}:
            return "eris_eod_rl_basic"
        if source in {"ERIS_EOD_LIVE-RL_BASIC-NOJUMPS", "ERIS_EOD_LIVE_RL_BASIC-NOJUMPS"}:
            return "eris_eod_rl_basic_nojumps"
        return None

    def _supports_curve_store_fast_path(self) -> bool:
        return self._curve_store_source_family() in {
            "barchart_stirf",
            "eris_eod_rl_basic",
            "eris_eod_rl_basic_nojumps",
        }

    def _supports_curve_store_raw_curve_fast_path(self) -> bool:
        return self._curve_store_source_family() == "barchart_stirf"

    def _supports_curve_store_analytics_fast_path(self) -> bool:
        return self._curve_store_source_family() in {
            "barchart_stirf",
            "eris_eod_rl_basic",
            "eris_eod_rl_basic_nojumps",
        }

    def _get_curve_store_builder(self) -> Any:
        family = self._curve_store_source_family()
        if family == "barchart_stirf":
            return self._get_barchart_stirf_curve_builder()
        return None

    def _resolve_curve_store_curve_name(
        self,
        requested_curve_name: str,
        kwargs: Dict[str, Any],
        builder: Any = None,
    ) -> str:
        family = self._curve_store_source_family()
        if family == "barchart_stirf":
            return self._resolve_barchart_stirf_curve_name(
                requested_curve_name=requested_curve_name,
                kwargs=kwargs,
                builder=builder or self._get_barchart_stirf_curve_builder(),
            )
        return requested_curve_name

    @staticmethod
    def _to_eris_eod_timestamp(
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> Union[datetime.datetime, Literal["live"]]:
        if timestamp == "live":
            return "live"

        if isinstance(timestamp, pd.Timestamp):
            timestamp = timestamp.to_pydatetime()

        ny_tz = pytz.timezone("America/New_York")
        if isinstance(timestamp, datetime.datetime):
            if timestamp.tzinfo is None or timestamp.tzinfo.utcoffset(timestamp) is None:
                timestamp = ny_tz.localize(timestamp)
            else:
                timestamp = timestamp.astimezone(ny_tz)
            return ny_tz.localize(
                datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 15, 0)
            )

        if isinstance(timestamp, datetime.date):
            return ny_tz.localize(
                datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 15, 0)
            )

        raise TypeError("timestamp must be datetime.date, datetime.datetime, pd.Timestamp, or 'live'")

    def _to_curve_store_timestamp(
        self,
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> Union[datetime.datetime, Literal["live"]]:
        family = self._curve_store_source_family()
        if family == "barchart_stirf":
            return self._to_barchart_stirf_timestamp(timestamp)
        if family in {"eris_eod_rl_basic", "eris_eod_rl_basic_nojumps"}:
            return self._to_eris_eod_timestamp(timestamp)
        raise NotImplementedError(f"CurveStore timestamps not supported for source '{self.source}'")

    def _curve_store_cfg(self, resolved_curve_name: str, builder: Any = None) -> Optional[Dict[str, Any]]:
        family = self._curve_store_source_family()
        if family == "barchart_stirf":
            active_builder = builder or self._get_barchart_stirf_curve_builder()
            return getattr(active_builder, "_STIRF_CURVE_CONFIGS", {}).get(resolved_curve_name)
        return None

    def _build_fixings_cache_for_dates(
        self,
        *,
        curve_name: str,
        as_of_dates: Iterable[datetime.date],
    ) -> Dict[datetime.date, pd.Series]:
        unique_dates = sorted({d for d in as_of_dates if isinstance(d, datetime.date)})
        if not unique_dates:
            return {}

        max_ref = max(unique_dates)
        full_fixings = _fetch_fixings(
            as_of_date=max_ref,
            curve_name=curve_name,
            force_refresh=self.force_refresh_fixings,
        ).sort_index()
        full_fixings = full_fixings * 100.0

        out: Dict[datetime.date, pd.Series] = {}
        for ref_date in unique_dates:
            out[ref_date] = full_fixings[full_fixings.index.date < ref_date]
        return out

    def _build_eris_eod_rl_curve(
        self,
        *,
        requested_curve_name: str,
        request_timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
        rl_curve_handle: Any,
        fixings_cache: Optional[Dict[datetime.date, pd.Series]] = None,
    ) -> "_IRSwapGenericCurve":
        import rateslib as rl

        from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
        from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

        if request_timestamp == "live":
            ref_date = datetime.date.today()
        elif isinstance(request_timestamp, pd.Timestamp):
            ref_date = request_timestamp.date()
        elif isinstance(request_timestamp, datetime.datetime):
            ref_date = request_timestamp.date()
        else:
            ref_date = request_timestamp

        fixings_series = None if fixings_cache is None else fixings_cache.get(ref_date)
        if fixings_series is None:
            fixings_series = _fetch_fixings(
                as_of_date=ref_date,
                curve_name=requested_curve_name,
                force_refresh=self.force_refresh_fixings,
            ).sort_index()
            fixings_series = fixings_series[fixings_series.index.date < ref_date] * 100.0
            if fixings_cache is not None:
                fixings_cache[ref_date] = fixings_series

        curve_def = RATESLIB_CURVE_DEFINITIONS[requested_curve_name]
        cal = curve_def.get("Calendar", None)
        if cal is not None:
            try:
                rl_curve_handle.calendar = cal
            except Exception:
                rl_curve_handle = rl.Curve(
                    nodes=dict(rl_curve_handle.nodes.nodes),
                    calendar=cal,
                    id=getattr(rl_curve_handle, "id", None),
                )

        ts_meta = getattr(rl_curve_handle, "timestamp", None) or getattr(rl_curve_handle, "timestamp_utc", None)
        if ts_meta is None:
            ts_meta = self._to_eris_eod_timestamp(request_timestamp)
        curve_id = f"{self.source.upper()}-{requested_curve_name}-{ts_meta}"
        return RLIRSwapCurve(
            rl_curve_id=requested_curve_name,
            rl_curve_handle=rl_curve_handle,
            fixings=fixings_series,
            meta_data={
                "timestamp": ts_meta,
                "id": curve_id,
                "requested_curve_name": requested_curve_name,
                "curve_name": requested_curve_name,
                "reference_curve_name": requested_curve_name,
            },
        )

    def _eris_curve_store_source_variant(self) -> str:
        family = self._curve_store_source_family()
        if family == "eris_eod_rl_basic_nojumps":
            return "ERIS_RL_BASIC_NOJUMPS"
        return "ERIS_RL_BASIC"

    def _promote_eris_curve_store_day(
        self,
        *,
        requested_curve_name: str,
        curve: Any,
        request_timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> None:
        family = self._curve_store_source_family()
        if family not in {"eris_eod_rl_basic", "eris_eod_rl_basic_nojumps"}:
            return
        if request_timestamp == "live":
            return

        store = self._get_curve_store()
        trading_date = (
            request_timestamp.date()
            if isinstance(request_timestamp, (datetime.datetime, pd.Timestamp))
            else request_timestamp
        )
        if trading_date is None:
            return

        need_raw = not bool(getattr(store, "has_day")(requested_curve_name, trading_date))
        has_analytics = getattr(store, "has_analytics_day", None)
        need_analytics = not bool(has_analytics(requested_curve_name, trading_date)) if callable(has_analytics) else True
        if not need_raw and not need_analytics:
            return

        ts_meta = None
        if hasattr(curve, "meta") and callable(curve.meta):
            ts_meta = (curve.meta() or {}).get("timestamp")
        ts_local = self._to_eris_eod_timestamp(ts_meta or request_timestamp)
        if ts_local == "live":
            return
        ts_utc = ts_local.astimezone(pytz.UTC)
        ts_chi = ts_utc.astimezone(pytz.timezone("America/Chicago"))

        rl_curve_handle = curve.handle() if hasattr(curve, "handle") else None
        if rl_curve_handle is None:
            return

        try:
            rl_curve_handle.timestamp = ts_local
            rl_curve_handle.timestamp_utc = ts_utc
        except Exception:
            pass

        if need_raw:
            from Caching.curve_store import CurveSnapshot

            raw_nodes: dict = (
                rl_curve_handle.nodes._nodes
                if hasattr(rl_curve_handle, "nodes") and hasattr(rl_curve_handle.nodes, "_nodes")
                else dict(getattr(rl_curve_handle, "nodes", {}) or {})
            )
            node_dates_sorted = sorted(raw_nodes.keys())
            node_dates = [
                d.date() if hasattr(d, "date") else d
                for d in node_dates_sorted
            ]
            discount_factors = [float(raw_nodes[d]) for d in node_dates_sorted]
            snapshot = CurveSnapshot(
                timestamp_utc=ts_utc,
                timestamp_local=ts_chi,
                trading_date=trading_date,
                session_minute=int((ts_chi - ts_chi.replace(hour=6, minute=0, second=0, microsecond=0)).total_seconds() // 60),
                curve_name=requested_curve_name,
                cfg_hash="",
                reference_key=str(getattr(rl_curve_handle, "id", "") or requested_curve_name),
                interpolation=str(getattr(rl_curve_handle, "interpolation", "log_linear") or "log_linear"),
                source_variant=self._eris_curve_store_source_variant(),
                node_dates=node_dates,
                discount_factors=discount_factors,
            )
            store.write_day(requested_curve_name, trading_date, [snapshot])

        if need_analytics:
            from Caching.curve_analytics import build_analytics_frame, compute_analytics_row

            analytics_df = build_analytics_frame(
                [
                    compute_analytics_row(
                        curve,
                        timestamp_utc=ts_utc,
                        trading_date=trading_date,
                    )
                ]
            )
            if not analytics_df.empty:
                store.write_analytics_day(requested_curve_name, trading_date, analytics_df)

    def _wrap_curve_store_curve(
        self,
        *,
        requested_curve_name: str,
        resolved_curve_name: str,
        request_timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
        rl_curve_handle: Any,
        builder: Any = None,
        fixings_cache: Optional[Dict[Any, pd.Series]] = None,
    ) -> "_IRSwapGenericCurve":
        family = self._curve_store_source_family()
        if family == "barchart_stirf":
            return self._build_barchart_stirf_rl_curve(
                requested_curve_name=requested_curve_name,
                resolved_curve_name=resolved_curve_name,
                request_timestamp=request_timestamp,
                rl_curve_handle=rl_curve_handle,
                builder=builder or self._get_barchart_stirf_curve_builder(),
                fixings_cache=fixings_cache,
            )
        if family in {"eris_eod_rl_basic", "eris_eod_rl_basic_nojumps"}:
            return self._build_eris_eod_rl_curve(
                requested_curve_name=requested_curve_name,
                request_timestamp=request_timestamp,
                rl_curve_handle=rl_curve_handle,
                fixings_cache=fixings_cache,
            )
        raise NotImplementedError(f"CurveStore wrapper not supported for source '{self.source}'")

    @staticmethod
    def _should_suppress_ratelibs_solver_output(line: str) -> bool:
        return "SUCCESS: `conv_tol` reached" in line and "(levenberg_marquardt)" in line

    @staticmethod
    @contextlib.contextmanager
    def _suppress_ratelibs_solver_output() -> Any:
        class _FilteredWriteStream(io.TextIOBase):
            def __init__(self, stream: Any):
                self._stream = stream
                self._buffer = ""

            def write(self, s: str) -> int:
                if not s:
                    return 0

                self._buffer += s
                while "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    self._emit(line + "\n")
                return len(s)

            def flush(self) -> None:
                if self._buffer:
                    self._emit(self._buffer)
                    self._buffer = ""
                self._stream.flush()

            def _emit(self, line: str) -> None:
                if not IRSwapsMDP._should_suppress_ratelibs_solver_output(line):
                    self._stream.write(line)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._stream, name)

        S = IRSwapsMDP._BARCHART_STIRF_STATE
        stdout = _FilteredWriteStream(sys.stdout)
        stderr = _FilteredWriteStream(sys.stderr)
        with S["io_lock"]:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    yield
                finally:
                    stdout.flush()
                    stderr.flush()

    @staticmethod
    def _to_barchart_stirf_timestamp(
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> Union[datetime.datetime, Literal["live"]]:
        if timestamp == "live":
            return "live"

        if isinstance(timestamp, pd.Timestamp):
            timestamp = timestamp.to_pydatetime()

        if isinstance(timestamp, datetime.datetime):
            if timestamp.tzinfo is None or timestamp.tzinfo.utcoffset(timestamp) is None:
                return pytz.timezone("America/New_York").localize(timestamp)
            return timestamp

        if isinstance(timestamp, datetime.date):
            return pytz.timezone("America/New_York").localize(datetime.datetime.combine(timestamp, datetime.time(hour=17, minute=0)))

        raise TypeError("timestamp must be datetime.date, datetime.datetime, pd.Timestamp, or 'live'")

    @staticmethod
    def _dict_get_case_insensitive(mapping: Dict[Any, Any], key: str) -> Any:
        if key in mapping:
            return mapping[key]

        needle = str(key).upper().strip()
        for k, v in mapping.items():
            if str(k).upper().strip() == needle:
                return v
        return None

    @staticmethod
    def _resolve_gsquant_reference_curve_name(curve_name: str) -> str:
        from MDP.IRSwaps.GSQUANT.rl_basic.build import GSQUANT_CURVE_MAP

        curve_cfg = GSQUANT_CURVE_MAP.get(curve_name, {}).get("rl_basic", {})
        return str(curve_cfg.get("reference_key") or curve_name)

    def _resolve_barchart_stirf_curve_name(self, requested_curve_name: str, kwargs: Dict[str, Any], builder: Any) -> str:
        cfgs: Dict[str, Dict[str, Any]] = dict(getattr(builder, "_STIRF_CURVE_CONFIGS", {}))
        if requested_curve_name in cfgs:
            return requested_curve_name

        curve_names_arg = kwargs.pop("curve_names", None)
        if curve_names_arg is not None:
            resolved_name: Optional[str] = None
            if isinstance(curve_names_arg, str):
                resolved_name = curve_names_arg
            elif isinstance(curve_names_arg, dict):
                match = self._dict_get_case_insensitive(curve_names_arg, requested_curve_name)
                if match is None and len(curve_names_arg) == 1:
                    match = next(iter(curve_names_arg.values()))
                if match is not None:
                    resolved_name = str(match)
            else:
                raise TypeError("kwargs['curve_names'] must be a string or a dict")

            if resolved_name is None:
                raise ValueError(
                    f"Could not resolve curve name for '{requested_curve_name}' from kwargs['curve_names']: {curve_names_arg}"
                )
            if resolved_name not in cfgs:
                raise ValueError(f"BARCHART STIRF curve '{resolved_name}' not found in BARCHART_STIRF_CURVE configs")
            return resolved_name

        by_reference = [name for name, cfg in cfgs.items() if str(cfg.get("reference_key", "")).upper().strip() == requested_curve_name.upper().strip()]
        if len(by_reference) == 1:
            return by_reference[0]
        if len(by_reference) > 1:
            raise ValueError(
                f"Multiple BARCHART STIRF curves map to reference curve '{requested_curve_name}': {by_reference}. "
                "Pass kwargs['curve_names'] to disambiguate."
            )

        raise ValueError(
            f"Could not resolve BARCHART STIRF curve for '{requested_curve_name}'. "
            "Pass kwargs['curve_names'] with a concrete BARCHART curve config key."
        )

    @staticmethod
    def _barchart_stirf_reference_date(
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> datetime.date:
        if timestamp == "live":
            return datetime.date.today()
        if isinstance(timestamp, pd.Timestamp):
            return timestamp.date()
        if isinstance(timestamp, datetime.datetime):
            return timestamp.date()
        return timestamp

    def _build_barchart_stirf_rl_curve(
        self,
        *,
        requested_curve_name: str,
        resolved_curve_name: str,
        request_timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
        rl_curve_handle: Any,
        builder: Any,
        fixings_cache: Optional[Dict[tuple[datetime.date, str], pd.Series]] = None,
    ) -> "_IRSwapGenericCurve":
        from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

        reference_curve_name = str(getattr(rl_curve_handle, "id", "") or "")
        if not reference_curve_name:
            reference_curve_name = str(builder._STIRF_CURVE_CONFIGS[resolved_curve_name]["reference_key"])

        ref = self._barchart_stirf_reference_date(request_timestamp)
        fixings_key = (ref, reference_curve_name)
        fixings = None if fixings_cache is None else fixings_cache.get(fixings_key)
        if fixings is None:
            fixings = _fetch_fixings(
                as_of_date=ref,
                curve_name=reference_curve_name,
                force_refresh=self.force_refresh_fixings,
            ).sort_index()
            fixings = fixings[fixings.index.date < ref] * 100
            if fixings_cache is not None:
                fixings_cache[fixings_key] = fixings

        ts_meta = getattr(rl_curve_handle, "timestamp", request_timestamp)
        curve_id = f"{self.source.upper()}-{resolved_curve_name}-{ts_meta}"
        return RLIRSwapCurve(
            rl_curve_id=reference_curve_name,
            rl_curve_handle=rl_curve_handle,
            fixings=fixings,
            meta_data={
                "timestamp": ts_meta,
                "id": curve_id,
                "requested_curve_name": requested_curve_name,
                "curve_name": resolved_curve_name,
            },
        )

    def get_pricer(self, request: dict) -> _IRSwapGenericCurve:
        curve = self.get_data(request)  # reuse the existing logic
        if curve is None:
            raise RuntimeError(f"IRSwapsMDP could not build a curve for request: {request}")
        return curve

    def get_data(self, request: dict) -> Optional[_IRSwapGenericCurve]:
        curve_name = request.pop("curve_name")
        timestamp = request.pop("timestamp")

        if not curve_name or not timestamp:
            raise ValueError("Request must contain 'curve_name' and 'timestamp'.")

        return self._get_curve(curve_name, timestamp, kwargs=request)

    def _get_curve(
        self, curve_name: str, timestamp: Union[datetime.datetime, datetime.date, Literal["live"]], kwargs: Optional[Dict[str, Any]] = {}
    ) -> Optional[_IRSwapGenericCurve]:
        from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
        from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

        try:
            assert not QUANTLIB_CURVE_DEFINITIONS[curve_name]["Calendar"].isHoliday(
                datetime_to_ql_date(
                    timestamp if type(timestamp) == datetime.datetime or type(timestamp) == datetime.date or hasattr(timestamp, "date") else datetime.date.today()
                )
            ), f"{timestamp} is a holiday in the {QUANTLIB_CURVE_DEFINITIONS[curve_name]["Calendar"]}!"
        except:
            if "USD" in curve_name:
                curve_name_check = "USD-OIS"
                assert not QUANTLIB_CURVE_DEFINITIONS[curve_name_check]["Calendar"].isHoliday(
                    datetime_to_ql_date(
                        timestamp
                        if type(timestamp) == datetime.datetime or type(timestamp) == datetime.date or hasattr(timestamp, "date")
                        else datetime.date.today()
                    )
                ), f"{timestamp} is a holiday in the {QUANTLIB_CURVE_DEFINITIONS[curve_name_check]["Calendar"]}!"

        if self.source.upper() in ["CME_NY_EOD_LIVE-QL_BASIC", "CME_NY_EOD_LIVE_QL_BASIC"]:
            import QuantLib as ql

            from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.CMEFetcherV2 import CMEFetcherV2
            from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
            from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

            assert type(timestamp) == datetime.date or timestamp == "live", "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
            assert curve_name in QUANTLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."
            ql_curve_def = QUANTLIB_CURVE_DEFINITIONS[curve_name]

            cmef = CMEFetcherV2(**self.config)

            ts, ql_curve = next(
                iter(
                    cmef.build_ql_eod_curves(
                        curve=curve_name,
                        type="Df",
                        ql_day_count=ql_curve_def["DayCounter"],
                        ql_calendar=ql_curve_def["Calendar"],
                        bdates=[timestamp],
                        show_tqdm=False,
                        **kwargs,
                    ).items()
                )
            )

            ql_curve_handle = ql.YieldTermStructureHandle(ql_curve)
            irswap_index: ql.SwapIndex = QUANTLIB_CURVE_DEFINITIONS[curve_name]["ReferenceRate"](ql_curve_handle)

            ref = datetime.date.today() if type(timestamp) == str else timestamp
            fixings_series = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings_series: pd.Series = fixings_series[fixings_series.index.date < ref]
            fixings_dict = fixings_series.to_dict()
            for d, f in fixings_dict.items():
                try:
                    irswap_index.addFixing(fixingDate=datetime_to_ql_date(d), fixing=f, forceOverwrite=True)
                except:
                    continue

            return QLIRSwapCurve(ql_curve_id=curve_name, ql_curve_handle=ql_curve_handle, ql_curve_index=irswap_index, meta_data={"timestamp": ts})

        elif self.source.upper() in ["CME_NY_EOD_LIVE-RL_BASIC", "CME_NY_EOD_LIVE_RL_BASIC"]:
            from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.CMEFetcherV2 import CMEFetcherV2
            from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            if type(timestamp) == datetime.datetime or hasattr(timestamp, "date"):
                timestamp = timestamp.date()

            assert type(timestamp) == datetime.date or timestamp == "live", "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
            assert curve_name in RATESLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."

            curve_id = f"{self.source.upper()}-{curve_name}-{timestamp}"
            cmef = CMEFetcherV2(**self.config)

            ts, rl_curve_handle = next(
                iter(
                    cmef.build_rl_eod_curves(
                        curve_id=curve_id,
                        curve=curve_name,
                        bdates=["live" if timestamp == datetime.date.today() else timestamp],
                        show_tqdm=False,
                        **kwargs,
                    ).items()
                )
            )

            ref = datetime.date.today() if type(timestamp) == str else timestamp
            fixings_series = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings_series: pd.Series = fixings_series[fixings_series.index.date < ref]

            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=fixings_series, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["ERIS_EOD_LIVE-RL_BASIC", "ERIS_EOD_LIVE_RL_BASIC"]:
            from rateslib import from_json

            from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.ErisFuturesFetcher import ErisFuturesFetcher
            from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

            if type(timestamp) == datetime.datetime or hasattr(timestamp, "date"):
                timestamp = timestamp.date()

            assert type(timestamp) == datetime.date or timestamp == "live", "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
            assert curve_name in RATESLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."

            curve_id = f"{self.source.upper()}-{curve_name}-{timestamp}"

            if timestamp == "live":
                eff = ErisFuturesFetcher(**self.config)
                rl_curve_handle, ts = eff.fetch_intraday_discount_curve(curve_id=curve_id, date=None, show_tqdm=True, return_intraday_timestamp=True, **kwargs)
            else:
                _, rl_json, ts = self._rl_curve_cache.get_eris_eod_live_rl_basic(
                    curve_id=curve_id, as_of=timestamp, force_refresh=kwargs.get("force_refresh", False), fetcher_kwargs={"show_tqdm": False}
                )
                rl_curve_handle = from_json(rl_json)

            curve = self._build_eris_eod_rl_curve(
                requested_curve_name=curve_name,
                request_timestamp=timestamp,
                rl_curve_handle=rl_curve_handle,
            )
            curve._meta_data["timestamp"] = ts
            curve._meta_data["id"] = curve_id
            if timestamp != "live":
                self._promote_eris_curve_store_day(
                    requested_curve_name=curve_name,
                    curve=curve,
                    request_timestamp=timestamp,
                )
            return curve

        elif self.source.upper() in ["ERIS_EOD_LIVE-RL_BASIC-NOJUMPS"]:
            from rateslib import from_json

            from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.ErisFuturesFetcher import ErisFuturesFetcher
            from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

            if type(timestamp) == datetime.datetime or hasattr(timestamp, "date"):
                timestamp = timestamp.date()

            assert type(timestamp) == datetime.date or timestamp == "live", "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
            assert curve_name in RATESLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."

            curve_id = f"{self.source.upper()}-{curve_name}-{timestamp}"

            if timestamp == "live":
                eff = ErisFuturesFetcher(**self.config)
                rl_curve_handle, ts = eff.fetch_intraday_discount_curve(
                    curve_id=curve_id, date=None, show_tqdm=True, return_intraday_timestamp=True, no_jumps_just_interp=True, **kwargs
                )
            else:
                _, rl_json, ts = self._rl_curve_cache.get_eris_eod_live_rl_basic(
                    curve_id=curve_id,
                    as_of=timestamp,
                    force_refresh=kwargs.get("force_refresh", False),
                    no_jumps_just_interp=True,
                    fetcher_kwargs={"show_tqdm": False},
                )
                rl_curve_handle = from_json(rl_json)

            curve = self._build_eris_eod_rl_curve(
                requested_curve_name=curve_name,
                request_timestamp=timestamp,
                rl_curve_handle=rl_curve_handle,
            )
            curve._meta_data["timestamp"] = ts
            curve._meta_data["id"] = curve_id
            if timestamp != "live":
                self._promote_eris_curve_store_day(
                    requested_curve_name=curve_name,
                    curve=curve,
                    request_timestamp=timestamp,
                )
            return curve

        elif self.source.upper() in ["ERIS_EOD_LIVE-QL_BASIC", "ERIS_EOD_LIVE_QL_BASIC"]:
            import QuantLib as ql

            from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.ErisFuturesFetcher import ErisFuturesFetcher
            from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
            from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

            if type(timestamp) == datetime.datetime or hasattr(timestamp, "date"):
                timestamp = timestamp.date()

            assert type(timestamp) == datetime.date or timestamp == "live", "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
            assert curve_name in QUANTLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."
            ql_curve_def = QUANTLIB_CURVE_DEFINITIONS[curve_name]

            erisf = ErisFuturesFetcher(**self.config)

            if "ignore_cache" in kwargs:
                kwargs["force_refresh"] = kwargs.pop("ignore_cache")

            if timestamp == "live" or timestamp == datetime.date.today():
                eff = ErisFuturesFetcher(**self.config)
                ql_curve, ts = eff.fetch_intraday_discount_curve(show_tqdm=True, enable_extrapolation=True, return_intraday_timestamp=True, **kwargs)
            else:
                ts, ql_curve = next(
                    iter(
                        erisf.fetch_historical_eod_discount_curves(
                            ql_dc=ql_curve_def["DayCounter"],
                            ql_cal=ql_curve_def["Calendar"],
                            bdates=[timestamp],
                            enable_extrapolation=True,
                            show_tqdm=False,
                            **kwargs,
                        ).items()
                    )
                )

            ql_curve_handle = ql.YieldTermStructureHandle(ql_curve)
            irswap_index: ql.SwapIndex = QUANTLIB_CURVE_DEFINITIONS[curve_name]["ReferenceRate"](ql_curve_handle)

            ref = datetime.date.today() if type(timestamp) == str else timestamp
            fixings_series = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings_series: pd.Series = fixings_series[fixings_series.index.date < ref]
            fixings_dict = fixings_series.to_dict()
            for d, f in fixings_dict.items():
                try:
                    irswap_index.addFixing(fixingDate=datetime_to_ql_date(d), fixing=f, forceOverwrite=True)
                except:
                    continue

            return QLIRSwapCurve(ql_curve_id=curve_name, ql_curve_handle=ql_curve_handle, ql_curve_index=irswap_index, meta_data={"timestamp": ts})

        elif self.source.upper() in ["ERIS_EOD_LIVE-QL_BASIC-NOJUMPS", "ERIS_EOD_LIVE_QL_BASIC-NOJUMPS"]:
            import QuantLib as ql

            from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.ErisFuturesFetcher import ErisFuturesFetcher
            from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
            from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

            if type(timestamp) == datetime.datetime or hasattr(timestamp, "date"):
                timestamp = timestamp.date()

            assert type(timestamp) == datetime.date or timestamp == "live", "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
            assert curve_name in QUANTLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."
            ql_curve_def = QUANTLIB_CURVE_DEFINITIONS[curve_name]

            erisf = ErisFuturesFetcher(**self.config)

            ts, ql_curve = next(
                iter(
                    erisf.fetch_historical_eod_discount_curves(
                        ql_dc=ql_curve_def["DayCounter"],
                        ql_cal=ql_curve_def["Calendar"],
                        bdates=[timestamp],
                        enable_extrapolation=True,
                        show_tqdm=False,
                        **kwargs,
                    ).items()
                )
            )

            ql_curve_handle = ql.YieldTermStructureHandle(ql_curve)
            irswap_index: ql.SwapIndex = QUANTLIB_CURVE_DEFINITIONS[curve_name]["ReferenceRate"](ql_curve_handle)

            ref = datetime.date.today() if type(timestamp) == str else timestamp
            fixings_series = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings_series: pd.Series = fixings_series[fixings_series.index.date < ref]
            fixings_dict = fixings_series.to_dict()
            for d, f in fixings_dict.items():
                try:
                    irswap_index.addFixing(fixingDate=datetime_to_ql_date(d), fixing=f, forceOverwrite=True)
                except:
                    continue

            return QLIRSwapCurve(ql_curve_id=curve_name, ql_curve_handle=ql_curve_handle, ql_curve_index=irswap_index, meta_data={"timestamp": ts})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MT_Q12", "SDR_INTRADAY_RL_USD_SOFR_MT_Q12"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mt_q12.rl_usd_sofr_mt_q12 import rl_usd_sofr_mt_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100
            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_MT_Q12"
            ts, rl_curve_handle = rl_usd_sofr_mt_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MT_Q16", "SDR_INTRADAY_RL_USD_SOFR_MT_Q16"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mt_q16.rl_usd_sofr_mt_q16 import rl_usd_sofr_mt_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100
            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_MT_Q16"
            ts, rl_curve_handle = rl_usd_sofr_mt_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MT_MISC", "SDR_INTRADAY_RL_USD_SOFR_MT_MISC"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mt_misc.rl_usd_sofr_mt_misc import rl_usd_sofr_mt_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100
            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_MT_MISC"

            ts, rl_curve_handle = rl_usd_sofr_mt_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_STIR_Q12X8", "SDR_INTRADAY_RL_USD_SOFR_STIR_Q12X8"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_stir_q12x8.rl_usd_sofr_stir_q12x8 import rl_usd_sofr_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_STIR_Q12x8"
            ts, rl_curve_handle = rl_usd_sofr_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_STIR_Q13X10", "SDR_INTRADAY_RL_USD_SOFR_STIR_Q13X10"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_stir_q13x10.rl_usd_sofr_stir_q13x10 import rl_usd_sofr_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_STIR_Q13x10"
            ts, rl_curve_handle = rl_usd_sofr_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_OIS_STIR_Q12X9", "SDR_INTRADAY_RL_USD_OIS_STIR_Q12X9"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-FEDFUNDS", "USD-FEDFUNDS!"
            curve_name = "USD-SOFR-1D"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_ois_stir_q12x9.rl_usd_ois_stir_q12x9 import rl_usd_ois_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_OIS_STIR_Q12x9"
            ts, rl_curve_handle = rl_usd_ois_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_OIS_STIR_Q12X12", "SDR_INTRADAY_RL_USD_OIS_STIR_Q12X12"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-FEDFUNDS", "USD-FEDFUNDS!"
            curve_name = "USD-SOFR-1D"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_ois_stir_q12x12.rl_usd_ois_stir_q12x12 import rl_usd_ois_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_OIS_STIR_Q12x12"
            ts, rl_curve_handle = rl_usd_ois_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id="USD-FEDFUNDS", rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_STIR_Q12X12", "SDR_INTRADAY_RL_USD_SOFR_STIR_Q12X12"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_stir_q12x12.rl_usd_sofr_stir_q12x12 import rl_usd_sofr_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_STIR_Q12x12"
            ts, rl_curve_handle = rl_usd_sofr_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_STIR_MISC", "SDR_INTRADAY_RL_USD_SOFR_STIR_MISC"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_stir_misc.rl_usd_sofr_stir_misc import rl_usd_sofr_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_STIR_MISC"
            ts, rl_curve_handle = rl_usd_sofr_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_OIS_STIR_MISC", "SDR_INTRADAY_RL_USD_OIS_STIR_MISC"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-FEDFUNDS", "FEDFUNDS!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_ois_stir_misc.rl_usd_ois_stir_misc import rl_usd_ois_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_OIS_STIR_MISC"
            ts, rl_curve_handle = rl_usd_ois_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MTV2_Q12X11", "SDR_INTRADAY_RL_USD_SOFR_MTV2_Q12X11"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mtv2_q12x11.rl_usd_sofr_mtv2_q12x11 import rl_usd_sofr_mt_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_MTV2_Q12x11"
            ts, rl_curve_handle = rl_usd_sofr_mt_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_3PM_EOD-RL_USD_SOFR_MTV2_Q12X11", "SDR_3PM_EOD_RL_USD_SOFR_MTV2_Q12X11"]:
            assert type(timestamp) == datetime.date or timestamp == "live", "need to pass in a 'datetime.date' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            # 3pm close
            if str(timestamp).lower() != "live":
                timestamp = pytz.timezone("America/New_York").localize(datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 15, 00))

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mtv2_q12x11.rl_usd_sofr_mtv2_q12x11 import rl_usd_sofr_mt_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            curve_id = f"{timestamp}-SDR_3PM_EOD-RL_USD_SOFR_MTV2_Q12x11"
            ts, rl_curve_handle = rl_usd_sofr_mt_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif "GSQUANT-RL" in self.source.upper() or "GSQUANT_RL" in self.source.upper():
            assert type(timestamp) == datetime.date, "GSQUANT ONLY HAS EOD - 'timestamp' must be type 'datetime.date'"

            from rateslib import from_json

            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            reference_curve_name = self._resolve_gsquant_reference_curve_name(curve_name)

            curve_id, rl_curve_serialized, pricing_location = self._rl_curve_cache.get_gsquant_rl_basic(
                curve_id=curve_name, as_of=timestamp, force_refresh=kwargs.get("force_refresh", False)
            )
            rl_curve_handle = from_json(rl_curve_serialized)

            fixings = _fetch_fixings(as_of_date=timestamp, curve_name=reference_curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings: pd.Series = fixings[fixings.index.date < timestamp] * 100

            return RLIRSwapCurve(
                rl_curve_id=curve_name,
                rl_curve_handle=rl_curve_handle,
                fixings=fixings,
                meta_data={
                    "timestamp": timestamp,
                    "id": curve_id,
                    "pricing_location": pricing_location,
                    "curve_name": curve_name,
                    "requested_curve_name": curve_name,
                    "reference_curve_name": reference_curve_name,
                },
            )

        elif self.source.upper() in ["BARCHART_STIRF-RL", "BARCHART_STIRF_RL"]:
            local_kwargs = dict(kwargs)
            builder = self._get_barchart_stirf_curve_builder()
            resolved_curve_name = self._resolve_barchart_stirf_curve_name(
                requested_curve_name=curve_name,
                kwargs=local_kwargs,
                builder=builder,
            )

            rl_timestamp = self._to_barchart_stirf_timestamp(timestamp)
            with self._suppress_ratelibs_solver_output():
                rl_curve_handle = builder.build_curve(
                    curve_name=resolved_curve_name,
                    timestamp=rl_timestamp,
                    kwargs=local_kwargs,
                    curve_only=True,
                )

            return self._build_barchart_stirf_rl_curve(
                requested_curve_name=curve_name,
                resolved_curve_name=resolved_curve_name,
                request_timestamp=timestamp,
                rl_curve_handle=rl_curve_handle,
                builder=builder,
            )

        else:
            raise NotImplementedError(f"Curve Build '{self.source}' does not exist")

    def bulk_get_data(self, request: dict) -> Dict[Union[datetime.date, datetime.datetime], _IRSwapGenericCurve]:
        if not isinstance(request, dict):
            raise ValueError("request must be a dict")

        curve_name: str = request.pop("curve_name", None)
        timestamps_in: Iterable[Union[datetime.date, datetime.datetime, Literal["live"]]] = request.pop("timestamps", None)
        ignore_cache = bool(request.pop("ignore_cache", False))
        n_jobs_raw = request.pop("n_jobs", None)
        n_jobs = int(n_jobs_raw) if n_jobs_raw is not None else 1
        n_jobs_requested = n_jobs_raw is not None
        calibration_executor = str(request.pop("calibration_executor", "thread") or "thread").strip().lower()
        if calibration_executor not in {"thread", "process"}:
            raise ValueError(
                f"Unsupported calibration_executor '{calibration_executor}'. "
                "Expected one of ['process', 'thread']."
            )

        if not curve_name or timestamps_in is None:
            raise ValueError("Request must contain 'curve_name' and 'timestamps'.")

        seen: set = set()
        timestamps: List[Union[datetime.date, datetime.datetime, Literal["live"]]] = []
        for t in timestamps_in:
            if t == datetime.date.today():
                t = "live"
            key = ("live",) if t == "live" else ("dt", t) if isinstance(t, datetime.datetime) else ("d", t)
            if key not in seen:
                seen.add(key)
                timestamps.append(t)

        if not timestamps:
            raise ValueError("Request 'timestamps' resolved to an empty collection.")

        out: Dict[Union[datetime.date, datetime.datetime], _IRSwapGenericCurve] = {}

        if self.source.upper() in ["CME_NY_EOD_LIVE-QL_BASIC", "CME_NY_EOD_LIVE_QL_BASIC"]:
            import QuantLib as ql

            from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.CMEFetcherV2 import CMEFetcherV2
            from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
            from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

            def _to_date(x):
                if x == "live":
                    return datetime.date.today()
                if isinstance(x, datetime.datetime):
                    return x.date()
                return x  # already date

            bdates: List[datetime.date] = [_to_date(t) for t in timestamps]

            ql_curve_def = QUANTLIB_CURVE_DEFINITIONS[curve_name]
            cmef = CMEFetcherV2(**self.config)

            built = cmef.build_ql_eod_curves(
                curve=curve_name,
                type="Df",
                ql_day_count=ql_curve_def["DayCounter"],
                ql_calendar=ql_curve_def["Calendar"],
                bdates=bdates,
                show_tqdm=True,
                ignore_cache=ignore_cache,
                **request,
            )

            for ref_date, ql_curve in built.items():
                ts = ref_date
                if type(ref_date) == datetime.datetime or type(ref_date) == pd.Timestamp:
                    ref_date = ref_date.date()

                if ql_curve is None:
                    continue
                ql_curve_handle = ql.YieldTermStructureHandle(ql_curve)
                irswap_index = ql_curve_def["ReferenceRate"](ql_curve_handle)

                fixings_series = _fetch_fixings(as_of_date=ref_date, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
                fixings_series = fixings_series[fixings_series.index.date < ref_date]
                for d, f in fixings_series.to_dict().items():
                    try:
                        irswap_index.addFixing(fixingDate=datetime_to_ql_date(d), fixing=f, forceOverwrite=True)
                    except Exception:
                        pass

                out[ref_date] = QLIRSwapCurve(
                    ql_curve_id=curve_name,
                    ql_curve_handle=ql_curve_handle,
                    ql_curve_index=irswap_index,
                    meta_data={"timestamp": ts},
                )

            return out

        elif self.source.upper() in ["ERIS_EOD_LIVE-RL_BASIC", "ERIS_EOD_LIVE_RL_BASIC"]:
            from rateslib import from_json

            def _to_date(x):
                if x == "live":
                    return datetime.date.today()
                if isinstance(x, datetime.datetime):
                    return x.date()
                return x  # already a date

            bdates: List[datetime.date] = [_to_date(t) for t in timestamps]

            today = datetime.date.today()
            past_dates = [d for d in bdates if d < today]
            today_dates = [d for d in bdates if d == today]
            fixings_cache = self._build_fixings_cache_for_dates(
                curve_name=curve_name,
                as_of_dates=bdates,
            )

            if not ignore_cache and past_dates and self._supports_curve_store_raw_curve_fast_path():
                try:
                    import pandas as _pd

                    store = self._get_curve_store()
                    day_dfs = []
                    for d in past_dates:
                        day_df = store.read_raw_day(curve_name, d)
                        if not day_df.empty:
                            day_dfs.append(day_df)

                    if len(day_dfs) >= len(past_dates):
                        parquet_df = _pd.concat(day_dfs, ignore_index=True)
                        curves_by_ts = store.reconstruct_curves_batch(parquet_df, cfg=None)

                        parquet_by_date = {}
                        for ts_key, rl_curve in curves_by_ts.items():
                            if hasattr(ts_key, "date"):
                                td = ts_key.date() if callable(ts_key.date) else ts_key.date
                            else:
                                td = _to_date(ts_key)
                            parquet_by_date[td] = rl_curve

                        for ref_date in past_dates:
                            rl_curve = parquet_by_date.get(ref_date)
                            if rl_curve is None:
                                continue
                            out[ref_date] = self._build_eris_eod_rl_curve(
                                requested_curve_name=curve_name,
                                request_timestamp=ref_date,
                                rl_curve_handle=rl_curve,
                                fixings_cache=fixings_cache,
                            )

                        if len([d for d in past_dates if d in out]) >= len(past_dates):
                            for ref_date in today_dates:
                                _, rl_json_live, ts_live = self._rl_curve_cache.get_eris_eod_live_rl_basic(
                                    curve_id=f"{self.source}-{curve_name}-live",
                                    as_of="live",
                                    force_refresh=True if ignore_cache else False,
                                    fetcher_kwargs={"show_tqdm": True},
                                )
                                out[ref_date] = self._build_eris_eod_rl_curve(
                                    requested_curve_name=curve_name,
                                    request_timestamp=ref_date,
                                    rl_curve_handle=from_json(rl_json_live),
                                    fixings_cache=fixings_cache,
                                )
                                out[ref_date]._meta_data["timestamp"] = ts_live
                            return out
                except Exception as _tier0_exc:
                    import logging as _logging

                    _logging.getLogger(__name__).debug(
                        "Eris CurveStore Tier 0 fast path failed: %s", _tier0_exc,
                    )

            built_json: Dict[datetime.date, str] = {}
            if past_dates:
                built_json = self._rl_curve_cache.bulk_get_eris_eod_live_rl_basic(
                    base_curve_id=f"{self.source}-{curve_name}-bulk",
                    bdates=past_dates,
                    force_refresh=ignore_cache,
                    fetcher_kwargs={"show_tqdm": True},
                )

            for ref_date in today_dates:
                _, rl_json_live, ts_live = self._rl_curve_cache.get_eris_eod_live_rl_basic(
                    curve_id=f"{self.source}-{curve_name}-live",
                    as_of="live",
                    force_refresh=True if ignore_cache else False,
                    fetcher_kwargs={"show_tqdm": True},
                )
                out[ref_date] = self._build_eris_eod_rl_curve(
                    requested_curve_name=curve_name,
                    request_timestamp=ref_date,
                    rl_curve_handle=from_json(rl_json_live),
                    fixings_cache=fixings_cache,
                )
                out[ref_date]._meta_data["timestamp"] = ts_live

            for ref_date, json_str in built_json.items():
                out[ref_date] = self._build_eris_eod_rl_curve(
                    requested_curve_name=curve_name,
                    request_timestamp=ref_date,
                    rl_curve_handle=from_json(json_str),
                    fixings_cache=fixings_cache,
                )
                self._promote_eris_curve_store_day(
                    requested_curve_name=curve_name,
                    curve=out[ref_date],
                    request_timestamp=ref_date,
                )

            return out

        elif self.source.upper() in ["CME_NY_EOD_LIVE-RL_BASIC", "CME_NY_EOD_LIVE_RL_BASIC"]:
            from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.CMEFetcherV2 import CMEFetcherV2
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            def _to_date(x):
                if x == "live":
                    return datetime.date.today()
                if isinstance(x, datetime.datetime):
                    return x.date()
                return x  # already a date

            bdates: List[datetime.date] = [_to_date(t) for t in timestamps]
            cmef = CMEFetcherV2(**self.config)
            built = cmef.build_rl_eod_curves(
                curve_id=f"{self.source}-{curve_name}-bulk",
                curve=curve_name,
                type="Df",
                bdates=bdates,
                show_tqdm=True,
                ignore_cache=ignore_cache,
                **request,
            )

            for ref_date, rl_curve in built.items():
                ts = ref_date
                if isinstance(ref_date, (datetime.datetime, pd.Timestamp)):
                    ref_date = ref_date.date()

                if rl_curve is None:
                    continue

                fixings_series = _fetch_fixings(as_of_date=ref_date, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
                fixings_series = fixings_series[fixings_series.index.date < ref_date] * 100.0

                out[ref_date] = RLIRSwapCurve(
                    rl_curve_id=curve_name,
                    rl_curve_handle=rl_curve,
                    fixings=fixings_series,
                    meta_data={"timestamp": ts},
                )

            return out

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MT_Q12", "SDR_INTRADAY_RL_USD_SOFR_MT_Q12"]:
            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mt_q12.rl_usd_sofr_mt_q12 import rl_usd_sofr_mt_curve, rl_usd_sofr_mt_curve_bulk
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            max_ref_date = max(t.date() if isinstance(t, (datetime.date, datetime.datetime)) else datetime.date.today() for t in timestamps)
            full_fixings_series = _fetch_fixings(as_of_date=max_ref_date, curve_name="USD-SOFR-1D", force_refresh=self.force_refresh_fixings).sort_index()

            datetime_snaps = [t for t in timestamps if isinstance(t, datetime.datetime)]
            live_snap_requested = "live" in timestamps

            if not datetime_snaps:
                return {}

            built_curves = rl_usd_sofr_mt_curve_bulk(
                base_curve_id="SDR_INTRADAY-RL_USD_SOFR_MT_Q12",
                snaps=datetime_snaps,
                sofr_fixings=full_fixings_series,
                cache=self._rl_curve_cache,
                max_workers=n_jobs,
                force_refresh=ignore_cache,
            )

            for ts, rl_curve in built_curves.items():
                if rl_curve is None:
                    continue
                ref_date = ts.date()
                fixings_for_curve = full_fixings_series[full_fixings_series.index.date < ref_date] * 100.0
                curve_id_for_snap = f"{ts}-SDR_INTRADAY-RL_USD_SOFR_MT_Q12"
                out[ts] = RLIRSwapCurve(
                    rl_curve_id=curve_name,
                    rl_curve_handle=rl_curve,
                    fixings=fixings_for_curve,
                    meta_data={"timestamp": ts, "id": curve_id_for_snap},
                )

            if live_snap_requested:
                ref_date = datetime.date.today()
                fixings_for_curve = full_fixings_series[full_fixings_series.index.date < ref_date] * 100.0
                curve_id = "live-SDR_INTRADAY-RL_USD_SOFR_MT_Q12"
                ts_out, rl_curve = rl_usd_sofr_mt_curve(
                    curve_id=curve_id,
                    snap="live",
                    sofr_fixings=fixings_for_curve,
                    cache=None,
                    force_refresh=True,
                )
                out["live"] = RLIRSwapCurve(
                    rl_curve_id="USD-SOFR-1D",
                    rl_curve_handle=rl_curve,
                    fixings=fixings_for_curve,
                    meta_data={"timestamp": ts_out, "id": curve_id},
                )

            return out

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MTV2_Q12X11", "SDR_INTRADAY_RL_USD_SOFR_MTV2_Q12X11"]:
            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mtv2_q12x11.rl_usd_sofr_mtv2_q12x11 import rl_usd_sofr_mt_curve, rl_usd_sofr_mt_curve_bulk
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            max_ref_date = max(t.date() if isinstance(t, (datetime.date, datetime.datetime)) else datetime.date.today() for t in timestamps)

            sofr_fixings = _fetch_fixings(as_of_date=max_ref_date, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < max_ref_date] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(max_ref_date) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            datetime_snaps = [t for t in timestamps if isinstance(t, datetime.datetime)]
            live_snap_requested = "live" in timestamps

            if not datetime_snaps:
                return {}

            built_curves = rl_usd_sofr_mt_curve_bulk(
                base_curve_id="SDR_INTRADAY-RL_USD_SOFR_MTV2_Q12X11",
                snaps=datetime_snaps,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache,
                max_workers=n_jobs,
                force_refresh=ignore_cache,
            )

            for ts, rl_curve in built_curves.items():
                if rl_curve is None:
                    continue
                ref_date = ts.date()
                curve_id_for_snap = f"{ts}-SDR_INTRADAY-RL_USD_SOFR_MTV2_Q12X11"
                out[ts] = RLIRSwapCurve(
                    rl_curve_id=curve_name,
                    rl_curve_handle=rl_curve,
                    fixings=sofr_fixings,
                    meta_data={"timestamp": ts, "id": curve_id_for_snap},
                )

            if live_snap_requested:
                ref_date = datetime.date.today()
                curve_id = "live-SDR_INTRADAY-RL_USD_SOFR_MTV2_Q12X11"
                ts_out, rl_curve = rl_usd_sofr_mt_curve(
                    curve_id=curve_id,
                    snap="live",
                    sofr_fixings=sofr_fixings,
                    cache=None,
                    force_refresh=True,
                )
                out["live"] = RLIRSwapCurve(
                    rl_curve_id="USD-SOFR-1D",
                    rl_curve_handle=rl_curve,
                    fixings=sofr_fixings,
                    meta_data={"timestamp": ts_out, "id": curve_id},
                )

            return out

        elif self.source.upper() in ["BARCHART_STIRF-RL", "BARCHART_STIRF_RL"]:
            local_request = dict(request)
            local_request.setdefault("force_refresh", bool(ignore_cache))
            if calibration_executor == "process" and "live" in timestamps:
                raise ValueError("Process-pool calibration only supports bulk historical BARCHART STIRF runs, not live timestamps.")
            if "live" not in timestamps:
                builder = self._get_barchart_stirf_curve_builder()
                bulk_request = dict(local_request)
                bulk_request["cache_full_intraday_fetch"] = True
                bulk_request.setdefault("show_tqdm", False)
                bulk_request["calibration_executor"] = calibration_executor
                if n_jobs_requested:
                    bulk_request.setdefault("calibration_max_workers", n_jobs)
                resolved_curve_name = self._resolve_barchart_stirf_curve_name(
                    requested_curve_name=curve_name,
                    kwargs=bulk_request,
                    builder=builder,
                )

                rl_timestamps: List[datetime.datetime] = []
                timestamps_by_rl_timestamp: Dict[datetime.datetime, List[Union[datetime.date, datetime.datetime, Literal["live"]]]] = {}
                for t in timestamps:
                    rl_timestamp = self._to_barchart_stirf_timestamp(t)
                    assert rl_timestamp != "live"
                    rl_timestamps.append(rl_timestamp)
                    timestamps_by_rl_timestamp.setdefault(rl_timestamp, []).append(t)

                # ── Tier 0: CurveStore Parquet fast path ──
                # Attempt bulk read from Parquet store. If all timestamps are
                # found, reconstruct rl.Curve objects and skip diskcache entirely.
                if not ignore_cache:
                    try:
                        store = self._get_curve_store()
                        import pandas as _pd
                        parquet_df = _pd.DataFrame()
                        try:
                            parquet_df = store.read_raw_nodes(
                                resolved_curve_name,
                                timestamps_utc=list(set(rl_timestamps)),
                            )
                        except TypeError:
                            unique_dates = sorted({
                                builder._trading_date_for_timestamp(t)
                                for t in rl_timestamps
                            })
                            day_dfs = []
                            for d in unique_dates:
                                day_df = store.read_raw_day(resolved_curve_name, d)
                                if not day_df.empty:
                                    day_dfs.append(day_df)
                            if day_dfs:
                                parquet_df = _pd.concat(day_dfs, ignore_index=True)

                        if not parquet_df.empty:
                            # Index by timestamp_utc for fast lookup (normalize to second precision)
                            parquet_ts_set = set()
                            if "timestamp_utc" in parquet_df.columns:
                                for ts_val in parquet_df["timestamp_utc"]:
                                    if hasattr(ts_val, "to_pydatetime"):
                                        parquet_ts_set.add(ts_val.to_pydatetime().replace(tzinfo=pytz.UTC, microsecond=0))
                                    elif isinstance(ts_val, datetime.datetime):
                                        parquet_ts_set.add(ts_val.replace(microsecond=0) if ts_val.tzinfo else pytz.UTC.localize(ts_val.replace(microsecond=0)))
                                    else:
                                        parquet_ts_set.add(ts_val)

                            # Check coverage: do we have ALL requested timestamps?
                            rl_ts_utc = set()
                            for ts in set(rl_timestamps):
                                ts_utc = ts.astimezone(pytz.UTC).replace(microsecond=0)
                                rl_ts_utc.add(ts_utc)

                            # Match with tolerance (second-level)
                            matched_count = sum(
                                1 for ts in rl_ts_utc
                                if ts in parquet_ts_set
                            )

                            if matched_count >= len(rl_ts_utc):
                                # All found — reconstruct and return
                                cfg = builder._STIRF_CURVE_CONFIGS[resolved_curve_name]
                                parquet_ts_keys = parquet_df["timestamp_utc"].map(
                                    lambda ts_val: (
                                        ts_val.to_pydatetime().replace(tzinfo=pytz.UTC, microsecond=0)
                                        if hasattr(ts_val, "to_pydatetime")
                                        else (
                                            ts_val.astimezone(pytz.UTC).replace(microsecond=0)
                                            if isinstance(ts_val, datetime.datetime) and ts_val.tzinfo is not None
                                            else (
                                                pytz.UTC.localize(ts_val.replace(microsecond=0))
                                                if isinstance(ts_val, datetime.datetime)
                                                else ts_val
                                            )
                                        )
                                    )
                                )
                                parquet_df = parquet_df.loc[parquet_ts_keys.isin(rl_ts_utc)].copy()
                                curves_by_ts = store.reconstruct_curves_batch(
                                    parquet_df, cfg=cfg, max_workers=4,
                                )

                                fixings_cache_t0: Dict[tuple, _pd.Series] = {}
                                for rl_timestamp, original_timestamps in timestamps_by_rl_timestamp.items():
                                    ts_utc = rl_timestamp.astimezone(pytz.UTC).replace(microsecond=0)
                                    rl_curve_handle = curves_by_ts.get(ts_utc)
                                    if rl_curve_handle is None:
                                        # Try pandas Timestamp key
                                        for k, v in curves_by_ts.items():
                                            if hasattr(k, "to_pydatetime"):
                                                kk = k.to_pydatetime()
                                                if kk.tzinfo is None:
                                                    kk = pytz.UTC.localize(kk)
                                                if abs((kk - ts_utc).total_seconds()) < 1:
                                                    rl_curve_handle = v
                                                    break
                                            elif isinstance(k, datetime.datetime):
                                                kk = k if k.tzinfo else pytz.UTC.localize(k)
                                                if abs((kk - ts_utc).total_seconds()) < 1:
                                                    rl_curve_handle = v
                                                    break

                                    if rl_curve_handle is None:
                                        continue
                                    curve_wrapper = self._build_barchart_stirf_rl_curve(
                                        requested_curve_name=curve_name,
                                        resolved_curve_name=resolved_curve_name,
                                        request_timestamp=original_timestamps[0],
                                        rl_curve_handle=rl_curve_handle,
                                        builder=builder,
                                        fixings_cache=fixings_cache_t0,
                                    )
                                    for original_timestamp in original_timestamps:
                                        out[original_timestamp] = curve_wrapper

                                if len(out) >= len(timestamps_by_rl_timestamp):
                                    return out
                                # Partial hit — fall through to existing path for misses
                    except Exception as _tier0_exc:
                        import logging as _logging
                        _logging.getLogger(__name__).debug(
                            "CurveStore Tier 0 fast path failed: %s", _tier0_exc,
                        )

                # ── Tier 1+2: diskcache + solver fallback ──
                try:
                    with self._suppress_ratelibs_solver_output():
                        built_curves = builder.build_curve(
                            curve_name=resolved_curve_name,
                            timestamp=rl_timestamps,
                            kwargs=bulk_request,
                            curve_only=True,
                        )
                    fixings_cache: Dict[tuple[datetime.date, str], pd.Series] = {}
                    for rl_timestamp, original_timestamps in timestamps_by_rl_timestamp.items():
                        rl_curve_handle = built_curves.get(rl_timestamp)
                        if rl_curve_handle is None:
                            continue
                        curve = self._build_barchart_stirf_rl_curve(
                            requested_curve_name=curve_name,
                            resolved_curve_name=resolved_curve_name,
                            request_timestamp=original_timestamps[0],
                            rl_curve_handle=rl_curve_handle,
                            builder=builder,
                            fixings_cache=fixings_cache,
                        )
                        for original_timestamp in original_timestamps:
                            out[original_timestamp] = curve
                    return out
                except Exception as exc:
                    if calibration_executor == "process":
                        raise RuntimeError("Process-pool calibration failed for BARCHART STIRF bulk_get_data.") from exc
                    pass

            for t in tqdm.tqdm(timestamps, desc=f"Building curves for {self.source}"):
                try:
                    out[t] = self._get_curve(curve_name=curve_name, timestamp=t, kwargs=dict(local_request) | {"cache_full_intraday_fetch": True})
                except Exception:
                    continue
            return out

        # ------- default / not implemented -------
        # Fallback: build curves one-by-one for sources without a dedicated bulk implementation.
        for t in timestamps:
            single_request = dict(request)
            single_request["curve_name"] = curve_name
            single_request["timestamp"] = t
            single_request["ignore_cache"] = bool(ignore_cache)
            try:
                curve = self.get_data(single_request)
            except Exception:
                continue
            if curve is not None:
                out[t] = curve
        return out


def _normalize_leg(s: str) -> str:
    import re

    # grab tenor tokens like 3M, 6m, 1Y, 2y (case-insensitive)
    parts = re.findall(r"\d+\s*[dwmy]", s, flags=re.I)
    parts = [p.upper().replace(" ", "") for p in parts]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]}x{parts[1]}"
    raise ValueError(f"Unexpected leg format: {s!r}")


def _format_fly_str(s: str) -> tuple[str]:
    w1, b, w2 = s.split("/")
    return _normalize_leg(w1), _normalize_leg(b), _normalize_leg(w2)

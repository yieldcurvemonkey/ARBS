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

    def _get_barchart_stirf_curve_builder(self) -> Any:
        from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE

        S = IRSwapsMDP._BARCHART_STIRF_STATE
        with S["lock"]:
            if S["builder"] is None:
                S["builder"] = BARCHART_STIRF_CURVE()
            return S["builder"]

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
            import rateslib as rl
            from rateslib import from_json

            from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.ErisFuturesFetcher import ErisFuturesFetcher
            from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

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

            curve_def = RATESLIB_CURVE_DEFINITIONS[curve_name]
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

            ref = datetime.date.today() if timestamp == "live" else timestamp
            fixings_series = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings_series = fixings_series[fixings_series.index.date < ref]
            # print(fixings_series)
            # print(timestamp)

            # FIXINGS_TOL = 1
            # if not fixings_series.empty:
            #     from pandas.tseries.holiday import USFederalHolidayCalendar
            #     from pandas.tseries.offsets import CustomBusinessDay

            #     cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
            #     target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
            #     idx_norm = fixings_series.index.normalize()
            #     if target_dt not in idx_norm:
            #         last_val = fixings_series.iloc[-1]
            #         fixings_series.loc[target_dt] = float(last_val)
            #         fixings_series = fixings_series.sort_index()

            return RLIRSwapCurve(
                rl_curve_id=curve_name,
                rl_curve_handle=rl_curve_handle,
                fixings=fixings_series * 100,
                meta_data={"timestamp": ts, "id": curve_id},
            )

        elif self.source.upper() in ["ERIS_EOD_LIVE-RL_BASIC-NOJUMPS"]:
            import rateslib as rl
            from rateslib import from_json

            from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.ErisFuturesFetcher import ErisFuturesFetcher
            from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

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

            curve_def = RATESLIB_CURVE_DEFINITIONS[curve_name]
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

            ref = datetime.date.today() if timestamp == "live" else timestamp
            fixings_series = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings_series = fixings_series[fixings_series.index.date < ref]

            return RLIRSwapCurve(
                rl_curve_id=curve_name,
                rl_curve_handle=rl_curve_handle,
                fixings=fixings_series * 100,
                meta_data={"timestamp": ts, "id": curve_id},
            )

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

            curve_id, rl_curve_serialized, pricing_location = self._rl_curve_cache.get_gsquant_rl_basic(
                curve_id=curve_name, as_of=timestamp, force_refresh=kwargs.get("force_refresh", False)
            )
            rl_curve_handle = from_json(rl_curve_serialized)

            fixings = _fetch_fixings(as_of_date=timestamp, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings: pd.Series = fixings[fixings.index.date < timestamp] * 100

            return RLIRSwapCurve(
                rl_curve_id=curve_name,
                rl_curve_handle=rl_curve_handle,
                fixings=fixings,
                meta_data={"timestamp": timestamp, "id": curve_id, "pricing_location": pricing_location},
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
        n_jobs = int(request.pop("n_jobs", 1))

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

            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

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
                fixings_series = _fetch_fixings(as_of_date=ref_date, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
                fixings_series = fixings_series[fixings_series.index.date < ref_date] * 100.0

                out[ref_date] = RLIRSwapCurve(
                    rl_curve_id=curve_name,
                    rl_curve_handle=from_json(rl_json_live),
                    fixings=fixings_series,
                    meta_data={"timestamp": ts_live},  # live intraday timestamp
                )

            for ref_date, json_str in built_json.items():
                ts = ref_date  # EOD (date) timestamp semantics for cached paths
                fixings_series = _fetch_fixings(as_of_date=ref_date, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
                fixings_series = fixings_series[fixings_series.index.date < ref_date] * 100.0

                out[ref_date] = RLIRSwapCurve(
                    rl_curve_id=curve_name,
                    rl_curve_handle=from_json(json_str),
                    fixings=fixings_series,
                    meta_data={"timestamp": ts},
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
            if "live" not in timestamps:
                builder = self._get_barchart_stirf_curve_builder()
                bulk_request = dict(local_request)
                bulk_request["cache_full_intraday_fetch"] = True
                bulk_request.setdefault("show_tqdm", False)
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
                except Exception:
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

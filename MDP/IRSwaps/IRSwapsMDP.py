import datetime
from typing import Any, Dict, Iterable, List, Literal, Optional, Union

import pandas as pd

from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings
from MDP.MarketDataProvider import MarketDataProvider
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve


class IRSwapsMDP(MarketDataProvider):

    def __init__(self, source: str, force_refresh_fixings: Optional[bool] = False, **kwargs: Any):
        super().__init__(source, **kwargs)
        self.force_refresh_fixings = force_refresh_fixings

        if "SDR_INTRADAY-RL" in source.upper() or "SDR_INTRADAY_RL" in source.upper():
            from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache

            self._rl_curve_cache = _RLCurveCache(cache_name="SDR_INTRADAY-RL_CURVE_CACHE")

        if "GSQUANT-RL" in source.upper() or "GSQUANT_RL" in source.upper():
            from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache

            self._rl_curve_cache = _RLCurveCache(cache_name="GSQUANT-RL_CURVE_CACHE")

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

        assert not QUANTLIB_CURVE_DEFINITIONS[curve_name]["Calendar"].isHoliday(
            datetime_to_ql_date(timestamp if type(timestamp) == datetime.datetime or type(timestamp) == datetime.date else datetime.date.today())
        ), f"{timestamp} is a holiday in the {QUANTLIB_CURVE_DEFINITIONS[curve_name]["Calendar"]}!"

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
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        if "GSQUANT-RL" in self.source.upper() or "GSQUANT_RL" in self.source.upper():
            assert type(timestamp) == datetime.date, "GSQUANT ONLY HAS EOD - 'timestamp' must be type 'datetime.date'"

            from rateslib import from_json

            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            curve_id, rl_curve_serialized, pricing_location = self._rl_curve_cache.get_gsquant_rl_basic(curve_id=curve_name, as_of=timestamp, force_refresh=False)
            rl_curve_handle = from_json(rl_curve_serialized)

            fixings = _fetch_fixings(as_of_date=timestamp, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings: pd.Series = fixings[fixings.index.date < timestamp] * 100

            return RLIRSwapCurve(
                rl_curve_id=curve_name,
                rl_curve_handle=rl_curve_handle,
                fixings=fixings,
                meta_data={"timestamp": timestamp, "id": curve_id, "pricing_location": pricing_location},
            )

        else:
            raise NotImplementedError(f"Curve Build '{self.source}' does not exist")

    def bulk_get_data(self, request: dict) -> Dict[Union[datetime.date, datetime.datetime], _IRSwapGenericCurve]:
        if not isinstance(request, dict):
            raise ValueError("request must be a dict")

        curve_name: str = request.pop("curve_name", None)
        timestamps_in: Iterable[Union[datetime.date, datetime.datetime, Literal["live"]]] = request.pop("timestamps", None)

        if not curve_name or timestamps_in is None:
            raise ValueError("Request must contain 'curve_name' and 'timestamps'.")

        seen: set = set()
        timestamps: List[Union[datetime.date, datetime.datetime, Literal["live"]]] = []
        for t in timestamps_in:
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
                show_tqdm=False,
                **request,
            )

            for ref_date, ql_curve in built.items():
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
                    meta_data={"timestamp": ref_date},
                )

            return out

        if self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MT_Q12", "SDR_INTRADAY_RL_USD_SOFR_MT_Q12"]:
            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mt_q12.rl_usd_sofr_mt_q12 import rl_usd_sofr_mt_curve_bulk, rl_usd_sofr_mt_curve
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
                max_workers=request.get("max_workers", 1),
                force_refresh=bool(request.get("force_refresh", False)),
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

        # ------- default / not implemented -------
        # Fallback: do one-by-one via existing get_data (still avoids concurrent callers hitting cache separately)
        for t in timestamps:
            out[t] = self.get_data({"curve_name": curve_name, "timestamp": t, **request})
        return out

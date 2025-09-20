import datetime
from pathlib import Path
from typing import Any, Literal, Optional, Union

import pandas as pd

from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.FixingsFetcher import FixingsFetcher
from MDP.MarketDataProvider import MarketDataProvider
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve


def _fetch_fixings(as_of_date: datetime.date | Literal["live"], curve_name: str, force_refresh: Optional[bool] = False) -> pd.Series:
    if as_of_date == "live":
        as_of_date = datetime.date.today()

    # TODO refactor
    fixings_cache = Path(rf"C:\Users\chris\clee\ARBS\MDP\IRSwaps\fixings_cache\{curve_name}_fixings")
    # fixings_cache = Path.home() / f".arbs_cache/{curve_name}_fixings"
    fixings_cache.mkdir(parents=True, exist_ok=True)

    tday = datetime.date.today()
    tday_str = tday.strftime("%Y-%m-%d")
    today_dir = fixings_cache / tday_str
    today_dir.mkdir(parents=True, exist_ok=True)

    if force_refresh:
        for p in today_dir.glob("*.csv"):
            try:
                p.unlink()
            except Exception as e:
                print(f"[cache] Could not delete cache file during force_refresh: {p} ({e})")

    cached_csvs = sorted(today_dir.glob("*.csv"))
    if cached_csvs and not force_refresh:
        dfs = [pd.read_csv(p) for p in cached_csvs]
        df = pd.concat(dfs)
        df = df.set_index(curve_name)
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df.loc[~df.index.duplicated(keep="first"), :]
        return df["Fixing"]

    for p in fixings_cache.rglob("*.csv"):
        if today_dir not in p.parents:
            try:
                p.unlink()
            except Exception as e:
                print(f"[cache] Could not delete stale file: {p} ({e})")

    for d in sorted(fixings_cache.rglob("*"), reverse=True):
        if d.is_dir() and d != today_dir:
            try:
                next(d.iterdir())
            except StopIteration:
                try:
                    d.rmdir()
                except Exception:
                    pass

    try:
        fixings_dict = FixingsFetcher().get_fixings(curve=curve_name)
    except:
        fixings_dict = FixingsFetcher(fred_api_key="e06f51338bf093283ce1331c2826b3db").get_fixings(curve=curve_name, use_fred=True)

    fixings_series = pd.Series(fixings_dict)
    fixings_series.index.name = curve_name
    fixings_series.name = "Fixing"

    out_csv = today_dir / "fixings.csv"
    try:
        fixings_series.to_csv(out_csv)
    except Exception as e:
        print(f"[cache] Failed to write cache file {out_csv}: {e}")

    return fixings_series


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

    def _get_curve(self, curve_name: str, timestamp: Union[datetime.datetime, datetime.date, Literal["live"]], kwargs={}) -> Optional[_IRSwapGenericCurve]:
        from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
        from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

        assert not QUANTLIB_CURVE_DEFINITIONS[curve_name]["Calendar"].isHoliday(
            datetime_to_ql_date(timestamp)
        ), f"{timestamp} is a holiday in the {QUANTLIB_CURVE_DEFINITIONS[curve_name]["Calendar"]}!"

        if self.source.upper() in ["CME_NY_EOD_LIVE-QL_BASIC", "CME_NY_EOD_LIVE_QL_BASIC"]:
            import QuantLib as ql

            from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.CMEFetcherV2 import CMEFetcherV2
            from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
            from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

            assert type(timestamp) == datetime.date, "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
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
                force_refresh=False,
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
                force_refresh=False,
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
                force_refresh=False,
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_OIS_STIR_Q12X9", "SDR_INTRADAY_RL_USD_OIS_STIR_Q12X9"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-FEDFUNDS", "OIS!"
            curve_name = "USD-SOFR-1D"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_ois_stir_q12x9.rl_usd_ois_stir_q12x9 import rl_usd_ois_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_OIS_STIR_Q12x9"
            ts, rl_curve_handle = rl_usd_ois_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=False,
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

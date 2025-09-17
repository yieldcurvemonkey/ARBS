import datetime
import pytz

from typing import Any, Optional, Union, Literal
from pathlib import Path

from MDP.MarketDataProvider import MarketDataProvider

from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve

# data sources here


class IRSwapMDP(MarketDataProvider):

    def __init__(self, source: str, **kwargs: Any):
        super().__init__(source, **kwargs)

    def get_data(self, request: dict) -> Optional[_IRSwapGenericCurve]:
        curve_name = request.get("curve_name")
        timestamp = request.get("timestamp")

        if not curve_name or not timestamp:
            raise ValueError("Request must contain 'curve_name' and 'timestamp'.")

        return self._get_curve(curve_name, timestamp)

    def _get_curve(self, curve_name: str, timestamp: Union[datetime.datetime, datetime.date, Literal["live"]]) -> Optional[_IRSwapGenericCurve]:
        if self.source.upper() == "CME_NY_EOD_LIVE":
            import QuantLib as ql
            import pandas as pd

            from MDP.IRSwaps.CME_NY_EOD_LIVE.backends.quantlib.CMEFetcherV2 import CMEFetcherV2
            from MDP.IRSwaps.CME_NY_EOD_LIVE.backends.quantlib.FixingsFetcher import FixingsFetcher

            from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
            from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

            assert curve_name in QUANTLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."
            ql_curve_def = QUANTLIB_CURVE_DEFINITIONS[curve_name]

            cmef = CMEFetcherV2(**self.config)

            if type(timestamp) == datetime.datetime:
                to_fetch = timestamp.date()
            else:
                to_fetch = timestamp

            ts, ql_curve = next(
                iter(
                    cmef.build_ql_eod_curves(
                        curve=curve_name,
                        type="Df",
                        ql_day_count=ql_curve_def["DayCounter"],
                        ql_calendar=ql_curve_def["Calendar"],
                        bdates=[to_fetch],
                    ).items()
                )
            )

            # TODO refactor
            def fetch_fixings(as_of_date: datetime.date) -> pd.Series:
                if as_of_date == "live":
                    as_of_date = datetime.date.today()

                fixings_cache = Path(rf"C:\Users\chris\clee\ARBS\MDP\IRSwaps\CME_NY_EOD_LIVE\backends\quantlib\{curve_name}_fixings")
                # fixings_cache =  Path.home() / f".arbs_cache/{curve_name}_fixings"
                fixings_cache.mkdir(parents=True, exist_ok=True)

                tday = datetime.date.today()
                tday_str = tday.strftime("%Y-%m-%d")
                today_dir = fixings_cache / tday_str
                today_dir.mkdir(parents=True, exist_ok=True)

                cached_csvs = sorted(today_dir.glob("*.csv"))
                if cached_csvs:
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

                fixings_dict = FixingsFetcher().get_fixings(curve=curve_name)
                fixings_series = pd.Series(fixings_dict)
                fixings_series.index.name = curve_name
                fixings_series.name = "Fixing"
                fixings_series = fixings_series.loc[~fixings_series.index.duplicated(keep="first"), :]
                out_csv = today_dir / "fixings.csv"
                try:
                    fixings_series.to_csv(out_csv)
                except Exception as e:
                    print(f"[cache] Failed to write cache file {out_csv}: {e}")

                return fixings_series

            ql_curve_handle = ql.YieldTermStructureHandle(ql_curve)
            irswap_index: ql.SwapIndex = QUANTLIB_CURVE_DEFINITIONS[curve_name]["ReferenceRate"](ql_curve_handle)
            fixings_dict = fetch_fixings(as_of_date=timestamp).to_dict()
            for d, f in fixings_dict.items():
                if d == curve_name or d == "Fixing":
                    continue
                irswap_index.addFixing(fixingDate=datetime_to_ql_date(d), fixing=f, forceOverwrite=True)

            return QLIRSwapCurve(ql_curve_id=curve_name, ql_curve_handle=ql_curve_handle, ql_curve_index=irswap_index, meta_data={"timestamp": ts})

        else:
            raise NotImplementedError(f"Data source '{self.source}' is not supported for IR Swaps.")

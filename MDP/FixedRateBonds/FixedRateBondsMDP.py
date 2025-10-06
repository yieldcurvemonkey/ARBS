import datetime
from typing import Any, Dict, Iterable, List, Literal, Optional, Union

import pandas as pd

from Query.Base._GenericPricable import _GenericPricable
from MDP.MarketDataProvider import MarketDataProvider
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer

from Caching.ZODBCacheMixin import ZODBCacheMixin


class FixedRateBondsMDP(MarketDataProvider[_GenericPricable], ZODBCacheMixin):

    _FRB_PRICER_CACHE = "_frb_pricer_cache"

    def __init__(self, source: str, **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        ZODBCacheMixin.__init__(self)

    def _ensure_pricer_cache(self) -> None:
        cache_path = ZODBCacheMixin.default_cache_path("FixedRateBondPricer_Cache")
        self.zodb_open_cache(
            cache_attr=self._FRB_PRICER_CACHE,
            path=cache_path,
            encode=None,
            decode=None,
        )

    @staticmethod
    def _py_scalar(v):
        try:
            import numpy as np

            if isinstance(v, np.generic):
                return v.item()
        except Exception:
            pass

        if isinstance(v, (pd.Timestamp, datetime.datetime, datetime.date)):
            return v.isoformat()
        return v

    @classmethod
    def _pyify_meta(cls, meta: Dict[str, Any]) -> Dict[str, Any]:
        return {k: cls._py_scalar(v) for k, v in dict(meta or {}).items()}

    @staticmethod
    def _build_pricer_from_args(args: Dict[str, Any], issue_date_key: str, maturity_date_key: str, cpn_key: str) -> _FixedRateBondGenericPricer:
        from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer

        return QLFixedRateBondPricer(
            ql_frb_id=args["ql_frb_id"],
            reference_date=datetime.date.fromisoformat(args["reference_date"]),
            issue_date=datetime.date.fromisoformat(args.get("meta_data")[issue_date_key]),
            maturity_date=datetime.date.fromisoformat(args.get("meta_data")[maturity_date_key]),
            cpn=args.get("meta_data")[cpn_key],
            ytm=float(args["ytm"]),
            meta_data=args.get("meta_data") or {},
        )

    def get_pricer(self, request: dict) -> _FixedRateBondGenericPricer:
        curve = self.get_data(request)  # reuse the existing logic
        if curve is None:
            raise RuntimeError(f"FixedRateBondsMDP could not build a curve for request: {request}")
        return curve

    def get_data(self, request: dict) -> Optional[_FixedRateBondGenericPricer]:
        curve_name = request.pop("curve_name")
        timestamp = request.pop("timestamp")

        if not curve_name or not timestamp:
            raise ValueError("Request must contain 'curve_name' and 'timestamp'.")

        return self._get_curve(curve_name, timestamp, kwargs=request)

    def _get_pricer(
        self, cusip: str, timestamp: Union[datetime.datetime, datetime.date, Literal["live"]], kwargs: Optional[Dict[str, Any]] = {}
    ) -> Optional[_FixedRateBondGenericPricer]:

        if self.source.upper() in ["USTS_PUBLICDOTCOM_WSJ_LIVE-QL"]:
            from MDP.FixedRateBonds.PUBLICDOTCOM.PublicDotcomDataFetcher import PublicDotcomDataFetcher
            from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
            from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer

            ref_df = update_reference_data(source="fiscaldata")
            ref_df = ref_df[ref_df["cusip"] == cusip]

            if timestamp == "live":
                wsj_key = get_isin_from_cusip(cusip, "US")[2:]
                live_ytm_quote = WSJFetcher().wsj_timeseries_api(wsj_ticker_keys=[wsj_key], append_most_recent_last=True)[wsj_key]
                return QLFixedRateBondPricer(
                    ql_frb_id="USTS",
                    reference_date=live_ytm_quote.iloc[0, 0].date(),
                    ytm=live_ytm_quote.iloc[0, 1],
                    meta_data=ref_df.iloc[0].to_dict(),
                )

            if type(timestamp) == datetime.date:
                self._ensure_pricer_cache()
                cache = getattr(self, self._FRB_PRICER_CACHE)
                cache_key = f"{timestamp.isoformat()}-{cusip}-{self.source.upper()}"

                cached = cache.get(cache_key)
                if cached is not None and not kwargs.get("force_refresh", False):
                    if hasattr(cached, "__class__") and cached.__class__.__name__ == "QLFixedRateBondPricer":
                        return cached
                    return self._build_pricer_from_args(cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

                ts_df = PublicDotcomDataFetcher().public_dotcom_timeseries_api(cusips=[cusip], refresh_jwt=True)[cusip]
                ts_df = ts_df[ts_df["Date"].dt.date == timestamp]
                if ts_df.empty:
                    raise KeyError(f"No Public.com timeseries for {cusip} on {timestamp}")

                args = {
                    "ql_frb_id": "USTS",
                    "reference_date": timestamp.isoformat(),
                    "ytm": float(ts_df["YTM"].iloc[0]),
                    "meta_data": self._pyify_meta(ref_df.iloc[0].to_dict()),
                    "schema": 1,  # simple versioning for future-proofing
                }

                cache[cache_key] = args
                self.zodb_commit()

                return self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

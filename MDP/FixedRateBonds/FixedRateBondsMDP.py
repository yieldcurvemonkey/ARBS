import datetime
import re
from typing import Any, Dict, Iterable, List, Literal, Optional, Union

import pandas as pd

from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base._GenericPricable import _GenericPricable
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer


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

    def get_pricer(self, request: dict) -> Dict[str, _FixedRateBondGenericPricer]:
        pricers = self.get_data(request)  # reuse the existing logic
        if pricers is None:
            raise RuntimeError(f"FixedRateBondsMDP could not build a pricer(s) for request: {request}")
        return pricers

    def get_data(self, request: dict) -> Optional[Dict[str, _FixedRateBondGenericPricer]]:
        cusips = request.pop("cusips")
        timestamp = request.pop("timestamp")

        if not cusips or not timestamp:
            raise ValueError("Request must contain 'cusips' and 'timestamp'.")

        return self._get_multi_pricers(cusips=cusips, timestamp=timestamp, kwargs=request)

    def _get_multi_pricers(
        self, cusips: Union[str, List[str]], timestamp: Union[datetime.datetime, datetime.date, Literal["live"]], kwargs: Optional[Dict[str, Any]] = {}
    ) -> Optional[Dict[str, _FixedRateBondGenericPricer]]:
        clean_cusips = []
        for c in cusips:
            if "x" in c and "Ox" not in c:
                clean_cusips.extend(c.split("x"))
            elif "/" in c:
                clean_cusips.extend(c.split("/"))
            else:
                clean_cusips.append(c)

        pricers = {}
        for c in clean_cusips:
            pricers[c] = self._get_single_pricer(cusip=c, timestamp=timestamp, kwargs=kwargs)
        return pricers

    def _get_single_pricer(
        self, cusip: str, timestamp: Union[datetime.datetime, datetime.date, Literal["live"]], kwargs: Optional[Dict[str, Any]] = {}
    ) -> Optional[_FixedRateBondGenericPricer]:

        if self.source.upper() in ["USTS_PUBLICDOTCOM_WSJ_LIVE-QL"]:
            from MDP.FixedRateBonds.PUBLICDOTCOM.PublicDotcomDataFetcher import PublicDotcomDataFetcher
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
            from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
            from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer

            ref_df = update_reference_data(source="fiscaldata", force_refresh=kwargs.get("force_refresh", False))
            as_of_ref = datetime.date.today() if timestamp == "live" else timestamp
            ref_df = ref_df[(ref_df["issue_date"] <= as_of_ref) & (ref_df["maturity_date"] >= as_of_ref)]
            ref_df["rank"] = ref_df.groupby("oi")["issue_date"].rank(method="first", ascending=False).astype(int) - 1

            original_cusip_alias = cusip
            match_ct = re.match(r"^CT(\d+)$", cusip, re.IGNORECASE)
            match_o = re.match(r"^(O{1,3})(\d+)$", cusip, re.IGNORECASE)
            match_ox = re.match(r"^Ox(\d+?)(\d+)$", cusip, re.IGNORECASE)
            rank, tenor = None, None
            if match_ct:
                rank = 0
                tenor = int(match_ct.group(1))
            elif match_o:
                rank = len(match_o.group(1))
                tenor = int(match_o.group(2))
            elif match_ox:
                rank = int(match_ox.group(1))
                tenor = int(match_ox.group(2))

            if rank is not None and tenor is not None:
                oi_str = f"{tenor}-Year"
                target_bond = ref_df[(ref_df["oi"] == oi_str) & (ref_df["rank"] == rank)]

                if not target_bond.empty:
                    cusip = target_bond.iloc[0]["cusip"]
                else:
                    raise KeyError(f"Could not resolve constant maturity alias '{original_cusip_alias}'")

            ref_df = ref_df[ref_df["cusip"] == cusip]

            if timestamp == "live":
                wsj_key = get_isin_from_cusip(cusip, "US")[2:]
                live_ytm_quote = WSJFetcher().wsj_timeseries_api(wsj_ticker_keys=[wsj_key], append_most_recent_last=True)[wsj_key]
                meta_data = ref_df.iloc[0].to_dict()
                meta_data["timestamp"] = live_ytm_quote.iloc[0, 0]
                return QLFixedRateBondPricer(
                    ql_frb_id="USTS",
                    reference_date=live_ytm_quote.iloc[0, 0].date(),
                    issue_date=meta_data["issue_date"],
                    maturity_date=meta_data["maturity_date"],
                    cpn=meta_data["cpn"],
                    ytm=live_ytm_quote.iloc[0, 1],
                    meta_data=meta_data,
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
                if ts_df.empty:
                    raise KeyError(f"No Public.com timeseries for {cusip} on {timestamp}")

                ts_df = ts_df.dropna(subset=["YTM"]).sort_values("Date").copy()
                ts_df["asof_date"] = ts_df["Date"].dt.date

                day_rows = ts_df[ts_df["asof_date"] == timestamp]
                interpolated = False
                interp_bounds = None

                if not day_rows.empty:
                    ytm_on_day = float(day_rows.sort_values("Date")["YTM"].iloc[-1])
                else:
                    before = ts_df[ts_df["asof_date"] < timestamp].tail(1)
                    after = ts_df[ts_df["asof_date"] > timestamp].head(1)

                    if not before.empty and not after.empty:
                        d0 = before["asof_date"].iloc[0]
                        y0 = float(before["YTM"].iloc[0])
                        d1 = after["asof_date"].iloc[0]
                        y1 = float(after["YTM"].iloc[0])

                        total_days = (d1 - d0).days
                        w = ((timestamp - d0).days / total_days) if total_days > 0 else 0.0
                        ytm_on_day = y0 + (y1 - y0) * w

                        interpolated = True
                        interp_bounds = (d0.isoformat(), d1.isoformat())
                    elif not before.empty or not after.empty:
                        near = before if not before.empty else after
                        ytm_on_day = float(near["YTM"].iloc[0])
                        interpolated = True
                        b = near["asof_date"].iloc[0].isoformat()
                        interp_bounds = (b, None) if not after.empty else (None, b)
                    else:
                        raise KeyError(f"No Public.com timeseries neighbors to interpolate {cusip} on {timestamp}")

                args = {
                    "ql_frb_id": "USTS",
                    "reference_date": timestamp.isoformat(),   # mark as the requested date
                    "ytm": float(ytm_on_day),
                    "meta_data": self._pyify_meta(ref_df.iloc[0].to_dict()),
                    "schema": 1,
                }

                if interpolated:
                    md = args["meta_data"]
                    md["ytm_interpolated"] = True
                    md["ytm_interp_method"] = "linear" if interp_bounds and all(interp_bounds) else "nearest"
                    md["ytm_interp_bounds"] = interp_bounds
                    
                cache[cache_key] = args
                self.zodb_commit()

                return self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

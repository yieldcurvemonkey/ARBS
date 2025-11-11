import contextlib
import datetime
import re
import threading
import warnings
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, Union

import pandas as pd
import pytz
import QuantLib as ql
import tqdm

from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base._GenericPricable import _GenericPricable
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer

DateLike = Union[datetime.date, datetime.datetime, Literal["live"]]
_BulkOut = Dict[DateLike, Dict[str, "_FixedRateBondGenericPricer"]]


@contextlib.contextmanager
def _closer(obj):
    try:
        yield obj
    finally:
        getattr(obj, "close_zodb", lambda: None)()


def _alias_to_cusip(alias: str, ref_table: pd.DataFrame) -> Optional[str]:
    if not isinstance(alias, str):
        return None

    # Backward-compat: normalize legacy '/' to '-'
    alias = alias.strip().replace("/", "-")

    m = re.match(r"^(?P<mm>\d{2})(?P<yy>\d{2})(?:-(?P<oi>\d{1,2}))?$", alias)
    if not m:
        return None

    mm = int(m.group("mm"))
    yy = int(m.group("yy"))
    if not (1 <= mm <= 12):
        raise ValueError(f"Invalid alias month in '{alias}'")

    # 80–99 -> 1900s, else 2000s (tweak if you expect many 1980s bonds)
    year = 1900 + yy if yy >= 80 else 2000 + yy
    prev_month = 12 if mm == 1 else (mm - 1)

    # Parse maturity dates
    mats = pd.to_datetime(ref_table["maturity_date"], errors="coerce")
    if mats.isna().all():
        raise ValueError("All maturity_date values failed to parse as dates")

    def _is_eom(ts: pd.Timestamp) -> bool:
        d = ts.date()
        qd = ql.Date(d.day, d.month, d.year)
        return qd == ql.UnitedStates(ql.UnitedStates.GovernmentBond).endOfMonth(qd)

    mask_target = (mats.dt.year.eq(year)) & (mats.dt.month.eq(mm))
    fam = ref_table.loc[mask_target].copy()
    if fam.empty:
        prev_month = 12 if mm == 1 else (mm - 1)
        prev_year = year - 1 if mm == 1 else year
        is_cal_eom = mats.dt.is_month_end
        mask_prev_eom = (mats.dt.year.eq(prev_year)) & (mats.dt.month.eq(prev_month)) & is_cal_eom
        fam = ref_table.loc[mask_prev_eom].copy()

    if fam.empty:
        raise KeyError(f"Alias '{alias}' did not resolve to any CUSIP in reference data")

    oi_num = m.group("oi")
    if oi_num:
        want = str(int(oi_num))

        def _norm_oi_cell(x) -> str:
            if pd.isna(x):
                return ""
            s = str(x)
            mnum = re.search(r"(\d+)", s)
            return mnum.group(1) if mnum else s.strip()

        fam = fam[fam["oi"].map(_norm_oi_cell).str.casefold() == want.casefold()]
        if fam.empty:
            raise KeyError(f"Alias '{alias}' with oi '{want}' found no matches")
    else:
        # Require disambiguation if multiple OI buckets exist
        if "oi" in fam.columns:

            def _oi_num_set(col: pd.Series):
                out = set()
                for v in col.dropna().astype(str):
                    mnum = re.search(r"(\d+)", v)
                    out.add(mnum.group(1) if mnum else v.strip())
                return sorted(out)

            oi_set = _oi_num_set(fam["oi"])
            if len(oi_set) > 1:
                raise AssertionError(
                    f"Ambiguous alias '{alias}'. Multiple original-issue buckets found: {', '.join(oi_set)}. "
                    f"Use an oi-aware alias like 'MMYY-10' (e.g., '{alias}-{oi_set[0]}')."
                )

    sort_cols = [c for c in ["maturity_date", "issue_date"] if c in fam.columns]
    if sort_cols:
        fam = fam.sort_values(sort_cols)
    unique_cusips = fam["cusip"].astype(str).unique()

    if len(unique_cusips) != 1:
        raise AssertionError(f"Alias '{alias}' maps to multiple CUSIPs: {', '.join(unique_cusips)}. " f"Please specify oi explicitly (e.g., '{alias}-30').")

    return unique_cusips[0]


class FixedRateBondsMDP(MarketDataProvider[_GenericPricable], ZODBCacheMixin):

    _FRB_PRICER_CACHE = "_frb_pricer_cache"

    def __init__(self, source: str = "USTS_FEDINVEST_WSJ_LIVE-QL", **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        ZODBCacheMixin.__init__(self)

        self._open_count = 0
        self._open_lock = threading.RLock()
        self._cache_ready = False

        if source == "USTS_FEDINVEST_WSJ_LIVE-QL":
            from MDP.FixedRateBonds.FEDINVEST.FedInvestFetcher import FedInvestDataFetcher

            self.fi = FedInvestDataFetcher()

    def _ensure_pricer_cache(self) -> None:
        if self._cache_ready and hasattr(self, self._FRB_PRICER_CACHE):
            return
        cache_path = ZODBCacheMixin.default_cache_path("FixedRateBondPricer_Cache")
        self.zodb_open_cache(
            cache_attr=self._FRB_PRICER_CACHE,
            path=cache_path,
            encode=None,
            decode=None,
        )
        self._cache_ready = True

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

    def _threadsafe_cache_put(self, key: str, value: dict) -> None:
        # protect ZODB cache writes; avoid holding the lock during network I/O
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._FRB_PRICER_CACHE)
            cache[key] = value

    def _threadsafe_cache_get(self, key: str):
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._FRB_PRICER_CACHE)
            return cache.get(key)

    def _resolve_aliases_bulk(
        self,
        symbols: List[str],
        timestamp: Union[datetime.datetime, datetime.date, Literal["live"]],
        *,
        ref_df: pd.DataFrame,
    ) -> Tuple[OrderedDict, Dict[str, dict]]:
        alias_to_cusip: "OrderedDict[str, str]" = OrderedDict()
        meta_by_cusip: Dict[str, dict] = {}

        # Pre-computed ref view for the as-of filter is already passed in
        # and includes the 'rank' column.
        for raw in symbols:
            alias = raw.strip()
            cusip = alias  # default: treat as CUSIP
            # Constant-maturity aliases
            m_ct = re.match(r"^CT(\d+)$", alias, re.IGNORECASE)
            m_o = re.match(r"^(O{1,3})(\d+)$", alias, re.IGNORECASE)
            m_ox = re.match(r"^Ox(?P<rank>\d+)(?P<tenor>10|20|25|30|7|5|3|2)$", alias, re.IGNORECASE)

            try:
                if m_ct:
                    rank, tenor = 0, int(m_ct.group(1))
                    oi = f"{tenor}-Year"
                    hit = ref_df[(ref_df["oi"] == oi) & (ref_df["rank"] == rank)]
                    if hit.empty:
                        raise KeyError(f"No CT{tenor} in ref data for {alias}")
                    cusip = str(hit.iloc[0]["cusip"])
                elif m_o:
                    rank, tenor = len(m_o.group(1)), int(m_o.group(2))
                    oi = f"{tenor}-Year"
                    hit = ref_df[(ref_df["oi"] == oi) & (ref_df["rank"] == rank)]
                    if hit.empty:
                        raise KeyError(f"No O{'O'* (rank-1)}{tenor} match for {alias}")
                    cusip = str(hit.iloc[0]["cusip"])
                elif m_ox:
                    rank, tenor = int(m_ox.group(1)), int(m_ox.group(2))
                    oi = f"{tenor}-Year"
                    hit = ref_df[(ref_df["oi"] == oi) & (ref_df["rank"] == rank)]
                    if hit.empty:
                        raise KeyError(f"No Ox{rank}{tenor} match for {alias}")
                    cusip = str(hit.iloc[0]["cusip"])
                else:
                    # Monthly alias (MMYY or MMYY-oi)
                    try:
                        resolved = _alias_to_cusip(alias, ref_df)
                        if resolved:
                            cusip = resolved
                    except AssertionError:
                        # bubble "need oi disambiguation" up unchanged
                        raise

            except Exception:
                # not an alias we handle -> keep original (CUSIP expected)
                cusip = alias

            # attach meta (first row for that cusip)
            row = ref_df[ref_df["cusip"] == cusip]
            if row.empty:
                raise KeyError(f"CUSIP {cusip} not present in reference set for {timestamp}")
            meta_by_cusip[cusip] = row.iloc[0].to_dict()
            alias_to_cusip[raw] = cusip

        return alias_to_cusip, meta_by_cusip

    @staticmethod
    def _build_pricer_from_args(args: Dict[str, Any], issue_date_key: str, maturity_date_key: str, cpn_key: str) -> _FixedRateBondGenericPricer:
        if "ql_frb_id" in args:
            from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer

            meta = args.get("meta_data") or {}
            kwargs = dict(
                ql_frb_id=args["ql_frb_id"],
                reference_date=datetime.date.fromisoformat(args["reference_date"]),
                issue_date=datetime.date.fromisoformat(meta[issue_date_key]),
                maturity_date=datetime.date.fromisoformat(meta[maturity_date_key]),
                cpn=meta[cpn_key],
                meta_data=meta,
            )
            if "ytm" in args and args["ytm"] is not None:
                kwargs["ytm"] = float(args["ytm"])
            elif "clean_price" in args and args["clean_price"] is not None:
                kwargs["clean_price"] = float(args["clean_price"])
            else:
                raise ValueError("Cached args must include either 'ytm' or 'clean_price'.")

            return QLFixedRateBondPricer(**kwargs)

        elif "rl_frb_id" in args:
            from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer

            meta = args.get("meta_data") or {}
            kwargs = dict(
                rl_frb_id=args["rl_frb_id"],
                reference_date=datetime.date.fromisoformat(args["reference_date"]),
                issue_date=datetime.date.fromisoformat(meta[issue_date_key]),
                maturity_date=datetime.date.fromisoformat(meta[maturity_date_key]),
                cpn=meta[cpn_key],
                meta_data=meta,
            )
            if "ytm" in args and args["ytm"] is not None:
                kwargs["ytm"] = float(args["ytm"])
            elif "clean_price" in args and args["clean_price"] is not None:
                kwargs["clean_price"] = float(args["clean_price"])
            else:
                raise ValueError("Cached args must include either 'ytm' or 'clean_price'.")

            return RLFixedRateBondPricer(**kwargs)

        else:

            raise NotImplementedError()

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
            elif "/" in c and not re.match(r"^\d{2}\d{2}/\d{1,2}$", c):
                clean_cusips.extend(c.split("/"))
            else:
                clean_cusips.append(c)

        show_tqdm = kwargs.get("show_tqdm", False)
        today = datetime.date.today()
        is_live = (timestamp == "live") or (type(timestamp) == datetime.date and timestamp == today)
        wsj_buffer = self._wsj_buffer_date()
        ts_qldate = ql.Date(timestamp.day, timestamp.month, timestamp.year) if hasattr(timestamp, "day") else ql.Date.todaysDate()
        is_in_wsj_buffer = ts_qldate > wsj_buffer
        if self.source.upper() == "USTS_FEDINVEST_WSJ_LIVE-QL" and (is_live or is_in_wsj_buffer):
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
            from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
            from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer

            force_refresh = bool(kwargs.get("force_refresh", False))
            as_of_ref = datetime.date.today() if timestamp == "live" else timestamp
            ref_df = update_reference_data(
                source="fiscaldata",
                force_refresh=force_refresh,
            )
            ref_df = ref_df[(ref_df["issue_date"] <= as_of_ref) & (ref_df["maturity_date"] >= as_of_ref)].copy()
            ref_df["rank"] = ref_df.groupby("oi")["issue_date"].rank(method="first", ascending=False).astype(int) - 1
            alias_to_cusip, meta_by_cusip = self._resolve_aliases_bulk(clean_cusips, timestamp, ref_df=ref_df)

            out: Dict[str, _FixedRateBondGenericPricer] = {}

            if is_live:
                wsj = WSJFetcher()
                live_data = wsj.fetch_live_ust_quotes(cusips=list(alias_to_cusip.values()))
                for original, cusip in alias_to_cusip.items():
                    try:
                        meta = dict(meta_by_cusip[cusip])
                        meta["timestamp"] = live_data[cusip]["timestamp"]
                        out[original] = QLFixedRateBondPricer(
                            ql_frb_id="USTS",
                            reference_date=live_data[cusip]["timestamp"].date(),
                            issue_date=meta["issue_date"],
                            maturity_date=meta["maturity_date"],
                            cpn=meta["cpn"],
                            ytm=float(live_data[cusip]["ytm"]),
                            meta_data=meta,
                        )
                    except KeyError as e:
                        warnings.warn(f"Missing data for {original} (CUSIP {cusip}): {e}")
                    except (ValueError, TypeError) as e:
                        warnings.warn(f"Invalid data for {original} (CUSIP {cusip}): {e}")
                    except Exception as e:
                        warnings.warn(f"Failed to create pricer for {original} (CUSIP {cusip}): {e}")
                return out

            if is_in_wsj_buffer:
                wsj = WSJFetcher()
                mapping = {get_isin_from_cusip(c, "US")[2:]: c for c in alias_to_cusip.values()}
                wide = wsj.ust_intraday_timeseries(mapping, show_tqdm=show_tqdm)

                est = pytz.timezone("America/New_York")
                t_3pm = est.localize(datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 15, 0, 0)).astimezone(pytz.UTC)
                idx = wide.index
                pos = idx.get_indexer([t_3pm], method="nearest")[0]
                nearest_ts = idx[pos]
                if abs(nearest_ts - t_3pm) > pd.Timedelta("30min"):
                    raise ValueError("No intraday snapshot within 30min of 3pm ET")

                for original, cusip in alias_to_cusip.items():
                    try:
                        y = wide[cusip].iloc[pos]
                        if pd.isna(y):
                            col = wide[cusip].dropna()
                            if col.empty:
                                raise ValueError(f"No intraday data for {cusip} near 3pm")
                            nearest_ts = col.index[col.index.get_indexer([t_3pm], method="nearest")[0]]
                            y = col.loc[nearest_ts]

                        meta = dict(meta_by_cusip[cusip])
                        meta["timestamp"] = nearest_ts
                        out[original] = QLFixedRateBondPricer(
                            ql_frb_id="USTS",
                            reference_date=nearest_ts.date(),
                            issue_date=meta["issue_date"],
                            maturity_date=meta["maturity_date"],
                            cpn=meta["cpn"],
                            ytm=float(y),
                            meta_data=meta,
                        )
                    except KeyError as e:
                        warnings.warn(f"Missing data for {original} (CUSIP {cusip}): {e}")
                    except (ValueError, TypeError) as e:
                        warnings.warn(f"Invalid data for {original} (CUSIP {cusip}): {e}")
                    except Exception as e:
                        warnings.warn(f"Failed to create pricer for {original} (CUSIP {cusip}): {e}")
                return out

        elif self.source.upper() == "USTS_WEBULL_WSJ_LIVE-RL":
            from pandas.tseries.offsets import BDay

            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
            from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher
            from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
            from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer

            force_refresh = bool(kwargs.get("force_refresh", False))
            as_of_ref = datetime.date.today() if timestamp == "live" else timestamp.date()
            ref_df = update_reference_data(source="fiscaldata", force_refresh=force_refresh)
            ref_df = ref_df[(ref_df["issue_date"] <= as_of_ref) & (ref_df["maturity_date"] >= as_of_ref)].copy()
            ref_df["rank"] = ref_df.groupby("oi")["issue_date"].rank(method="first", ascending=False).astype(int) - 1
            alias_to_cusip, meta_by_cusip = self._resolve_aliases_bulk(clean_cusips, timestamp, ref_df=ref_df)

            out: Dict[str, _FixedRateBondGenericPricer] = {}

            if is_live:
                wsj = WSJFetcher()
                live_data = wsj.fetch_live_ust_quotes(cusips=list(alias_to_cusip.values()))
                for original, cusip in alias_to_cusip.items():
                    try:
                        meta = dict(meta_by_cusip[cusip])
                        meta["timestamp"] = live_data[cusip]["timestamp"]
                        out[original] = RLFixedRateBondPricer(
                            rl_frb_id="USTS",
                            reference_date=live_data[cusip]["timestamp"].date(),
                            issue_date=meta["issue_date"],
                            maturity_date=meta["maturity_date"],
                            cpn=meta["cpn"],
                            ytm=float(live_data[cusip]["ytm"]),
                            meta_data=meta,
                        )
                    except KeyError as e:
                        warnings.warn(f"Missing data for {original} (CUSIP {cusip}): {e}")
                    except (ValueError, TypeError) as e:
                        warnings.warn(f"Invalid data for {original} (CUSIP {cusip}): {e}")
                    except Exception as e:
                        warnings.warn(f"Failed to create pricer for {original} (CUSIP {cusip}): {e}")
                return out

            self._ensure_pricer_cache()
            cache = getattr(self, self._FRB_PRICER_CACHE)
            alias_to_cusip_to_fetch = {}
            for original, cusip in alias_to_cusip.items():
                cache_key = f"{timestamp.isoformat()}-{cusip}-{self.source.upper()}"
                cached = cache.get(cache_key)
                if cached is not None and not kwargs.get("force_refresh", False):
                    if hasattr(cached, "__class__") and cached.__class__.__name__ == "RLFixedRateBondPricer":
                        return cached
                    out[original] = self._build_pricer_from_args(cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")
                    continue

                cache_key = f"{timestamp.isoformat()}-{original}-{self.source.upper()}"
                cached = cache.get(cache_key)
                if cached is not None and not kwargs.get("force_refresh", False):
                    if hasattr(cached, "__class__") and cached.__class__.__name__ == "RLFixedRateBondPricer":
                        return cached
                    out[original] = self._build_pricer_from_args(cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")
                    continue

                alias_to_cusip_to_fetch[original] = cusip

            wb = WebullFintechFetcher(debug_verbose=False, error_verbose=True)
            t = timestamp
            ny = pytz.timezone("America/New_York")
            start_ny = ny.localize(datetime.datetime(t.year, t.month, t.day, 7, 0, 0)) - BDay(1)
            end_ny = ny.localize(datetime.datetime(t.year, t.month, t.day, 17, 0, 0)) + BDay(1)
            wide = wb.intraday_by_cusips(cusips=list(alias_to_cusip_to_fetch.values()), start=start_ny, end=end_ny, show_tqdm=bool(kwargs.get("show_tqdm", True)))
            for original, cusip in alias_to_cusip_to_fetch.items():
                for curr_ts, ytm in wide[cusip].items():
                    cache_key = f"{curr_ts.isoformat()}-{cusip}-{self.source.upper()}"
                    meta = dict(meta_by_cusip[cusip])
                    meta["timestamp"] = curr_ts.isoformat()
                    args = {
                        "rl_frb_id": "USTS",
                        "reference_date": curr_ts.date().isoformat(),
                        "ytm": ytm,
                        "meta_data": self._pyify_meta(meta),
                        "schema": 1,
                        "source": cache_key,
                    }
                    cache[cache_key] = args
                    self.zodb_commit()

                    if curr_ts == timestamp:
                        out[original] = self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

            return out

        pricers = {}
        clean_cusips_iter = tqdm.tqdm(clean_cusips, desc="FETCHING CUSIPS...") if show_tqdm else clean_cusips
        for c in clean_cusips_iter:
            try:
                pricers[c] = self._get_single_pricer(cusip=c, timestamp=timestamp, kwargs=kwargs)
            except Exception as e:
                warnings.warn(f"Failed to fetch CUSIP {c}: {e}")

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
            match_ox = re.match(r"^Ox(?P<rank>\d+)(?P<tenor>10|20|25|30|7|5|3|2)$", cusip, re.IGNORECASE)

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
            else:
                try:
                    resolved = _alias_to_cusip(original_cusip_alias, ref_df)
                    if resolved:
                        cusip = resolved
                except AssertionError as e:
                    # Surface explicit "oi required" assertions
                    raise
                except Exception:
                    # Not an alias we handle (fall through to treat input as CUSIP)
                    pass

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
                    "reference_date": timestamp.isoformat(),  # mark as the requested date
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

        if self.source.upper() in ["USTS_FEDINVEST_WSJ_LIVE-QL"]:

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
            match_ox = re.match(r"^Ox(?P<rank>\d+)(?P<tenor>10|20|25|30|7|5|3|2)$", cusip, re.IGNORECASE)

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
            else:
                try:
                    resolved = _alias_to_cusip(original_cusip_alias, ref_df)
                    if resolved:
                        cusip = resolved
                except AssertionError as e:
                    # Surface explicit "oi required" assertions
                    raise
                except Exception:
                    # Not an alias we handle (fall through to treat input as CUSIP)
                    pass

            ref_df = ref_df[ref_df["cusip"] == cusip]

            if timestamp == "live" or timestamp == datetime.date.today():
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

            wsj_buffer = ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(ql.Date.todaysDate(), ql.Period("-3D"))
            if ql.Date(timestamp.day, timestamp.month, timestamp.year) > wsj_buffer:
                wsj_key = get_isin_from_cusip(cusip, "US")[2:]

                # pandas series with timezone aware datetime index in utc
                intraday_df = WSJFetcher().ust_intraday_timeseries(wsj_ticker_keys={wsj_key: cusip})[cusip]
                if intraday_df.empty:
                    raise ValueError("intraday_df is empty")

                ust_3pm_close = pytz.timezone("America/New_York").localize(datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 15, 0, 0))
                # ust_5pm_close = pytz.timezone("America/New_York").localize(datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 17, 0, 0))

                ts_utc = ust_3pm_close.astimezone(pytz.UTC)
                intraday_df = intraday_df.sort_index()
                pos = intraday_df.index.get_indexer([ts_utc], method="nearest")[0]
                nearest_ts = intraday_df.index[pos]
                tolerance = pd.Timedelta("30min")
                if abs(nearest_ts - ts_utc) > tolerance:
                    raise ValueError(f"No snapshot within {tolerance} of 3pm close")

                closest_snapshot_time = nearest_ts
                closest_snapshot = intraday_df.loc[nearest_ts]
                meta_data = ref_df.iloc[0].to_dict()
                meta_data["timestamp"] = closest_snapshot_time
                return QLFixedRateBondPricer(
                    ql_frb_id="USTS",
                    reference_date=closest_snapshot_time.date(),
                    issue_date=meta_data["issue_date"],
                    maturity_date=meta_data["maturity_date"],
                    cpn=meta_data["cpn"],
                    ytm=closest_snapshot,
                    meta_data=meta_data,
                )

            timestamp_dt = datetime.datetime(timestamp.year, timestamp.month, timestamp.day)

            self._ensure_pricer_cache()
            cache = getattr(self, self._FRB_PRICER_CACHE)
            cache_key = f"{timestamp.isoformat()}-{cusip}-{self.source.upper()}"

            cached = cache.get(cache_key)
            if cached is not None and not kwargs.get("force_refresh", False):
                if hasattr(cached, "__class__") and cached.__class__.__name__ == "QLFixedRateBondPricer":
                    return cached
                return self._build_pricer_from_args(cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

            fi_map = self.fi.runner(dates=[timestamp_dt], refresh_cache=kwargs.get("force_refresh", False))
            fi_df = fi_map.get(timestamp_dt)
            if fi_df is None or fi_df.empty:
                raise KeyError(f"No FedInvest snapshot for {timestamp} (key: {timestamp_dt})")

            fi_df = fi_df.set_index("cusip")
            if cusip not in fi_df.index:
                raise KeyError(f"FedInvest snapshot missing CUSIP {cusip} for {timestamp}")

            clean_price = float(fi_df.loc[cusip]["eod_price"])
            meta_data = self._pyify_meta(ref_df.iloc[0].to_dict())

            args = {
                "ql_frb_id": "USTS",
                "reference_date": timestamp.isoformat(),
                "clean_price": clean_price,
                "meta_data": meta_data,
                "schema": 1,
                "source": "fedinvest",
            }

            cache[cache_key] = args
            self.zodb_commit()

            return self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

        elif self.source.upper() in ["USTS_WEBULL_WSJ_LIVE-RL"]:
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data
            from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher
            from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
            from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer

            if timestamp == "live":
                as_of_date = datetime.date.today()
            elif isinstance(timestamp, datetime.datetime):
                as_of_date = timestamp.date()
            elif isinstance(timestamp, datetime.date):
                raise NotImplementedError("must be a timestamp")
            else:
                raise TypeError("timestamp must be 'live', datetime.date, or datetime.datetime")

            ref_df = update_reference_data(source="fiscaldata", force_refresh=kwargs.get("force_refresh", False))
            ref_df = ref_df[(ref_df["issue_date"] <= as_of_date) & (ref_df["maturity_date"] >= as_of_date)]
            ref_df["rank"] = ref_df.groupby("oi")["issue_date"].rank(method="first", ascending=False).astype(int) - 1

            original_cusip_alias = cusip
            m_ct = re.match(r"^CT(\d+)$", cusip, re.IGNORECASE)
            m_o = re.match(r"^(O{1,3})(\d+)$", cusip, re.IGNORECASE)
            m_ox = re.match(r"^Ox(?P<rank>\d+)(?P<tenor>10|20|25|30|7|5|3|2)$", cusip, re.IGNORECASE)
            rank = tenor = None
            if m_ct:
                rank, tenor = 0, int(m_ct.group(1))
            elif m_o:
                rank, tenor = len(m_o.group(1)), int(m_o.group(2))
            elif m_ox:
                rank, tenor = int(m_ox.group(1)), int(m_ox.group(2))

            if rank is not None and tenor is not None:
                oi_str = f"{tenor}-Year"
                tgt = ref_df[(ref_df["oi"] == oi_str) & (ref_df["rank"] == rank)]
                if not tgt.empty:
                    cusip = str(tgt.iloc[0]["cusip"])
                else:
                    raise KeyError(f"Could not resolve constant maturity alias '{original_cusip_alias}'")
            else:
                try:
                    resolved = _alias_to_cusip(original_cusip_alias, ref_df)
                    if resolved:
                        cusip = resolved
                except AssertionError:
                    raise  # surface "oi required"
                except Exception:
                    pass  # treat input as raw CUSIP

            row = ref_df[ref_df["cusip"] == cusip]
            if row.empty:
                raise KeyError(f"CUSIP {cusip} not present in reference set for {as_of_date}")
            meta_data = row.iloc[0].to_dict()

            if timestamp == "live":
                wsj_key = get_isin_from_cusip(cusip, "US")[2:]
                live_ytm_quote = WSJFetcher().wsj_timeseries_api(wsj_ticker_keys=[wsj_key], append_most_recent_last=True)[wsj_key]
                meta_data["timestamp"] = live_ytm_quote.iloc[0, 0]
                return RLFixedRateBondPricer(
                    rl_frb_id="USTS",
                    reference_date=live_ytm_quote.iloc[0, 0].date(),
                    issue_date=meta_data["issue_date"],
                    maturity_date=meta_data["maturity_date"],
                    cpn=meta_data["cpn"],
                    ytm=live_ytm_quote.iloc[0, 1],
                    meta_data=meta_data,
                )

            self._ensure_pricer_cache()
            cache = getattr(self, self._FRB_PRICER_CACHE)
            cache_key = f"{timestamp.isoformat()}-{cusip}-{self.source.upper()}"

            cached = cache.get(cache_key)
            if cached is not None and not kwargs.get("force_refresh", False):
                if hasattr(cached, "__class__") and cached.__class__.__name__ == "RLFixedRateBondPricer":
                    return cached
                return self._build_pricer_from_args(cached, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

            ts_quote_df = WebullFintechFetcher().intraday_by_cusips(
                cusips=[cusip],
                start=timestamp,
                end=timestamp,
            )
            meta_data["timestamp"] = timestamp.isoformat()
            args = {
                "rl_frb_id": "USTS",
                "reference_date": ts_quote_df.index[0].date().isoformat(),
                "ytm": ts_quote_df.iloc[0, 0],
                "meta_data": self._pyify_meta(meta_data),
                "schema": 1,
                "source": cache_key,
            }
            cache[cache_key] = args
            self.zodb_commit()
            return self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

    def get_bond_reference_data(self, as_of_date: datetime.date, kwargs={}):
        if kwargs.get("cme_tcf", None):
            from MDP.FixedRateBonds.reference_data_cache.cme_tcf import read_cme_tcf_with_headers

            return read_cme_tcf_with_headers(as_of=as_of_date)

        if self.source.upper() in ["USTS_FEDINVEST_WSJ_LIVE-QL", "USTS_WEBULL_WSJ_LIVE-RL"]:
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import _fetch_fiscaldata

            return _fetch_fiscaldata(fetch_as_of=as_of_date, process_as_of=as_of_date, **kwargs)

    def _wsj_buffer_date(self) -> ql.Date:
        return ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(ql.Date.todaysDate(), ql.Period("-3D"))

    def bulk_get_data(
        self,
        timestamps: Sequence[DateLike],
        cusips: Sequence[str],
        *,
        show_tqdm: bool = False,
        force_refresh: bool = False,
        max_workers: int = 8,
    ) -> _BulkOut:
        # if not timestamps or not cusips:
        #     return {}

        # -------- helpers (mirror your existing patterns) --------
        def _clean_list(symbols: Iterable[str]) -> List[str]:
            out: List[str] = []
            for s in symbols:
                s = (s or "").strip()
                if "x" in s and "Ox" not in s:
                    out.extend([p for p in s.split("x") if p])
                elif "/" in s and not re.match(r"^\d{2}\d{2}/\d{1,2}$", s):
                    out.extend([p for p in s.split("/") if p])
                else:
                    out.append(s)
            return out

        def _is_live(ts: DateLike) -> bool:
            today = datetime.date.today()
            return (ts == "live") or (isinstance(ts, datetime.date) and not isinstance(ts, datetime.datetime) and ts == today)

        def _as_of_ref(ts: DateLike) -> datetime.date:
            return datetime.date.today() if ts == "live" else (ts.date() if isinstance(ts, datetime.datetime) else ts)

        def _ts_to_ql_date(ts: DateLike):
            if ts == "live":
                return ql.Date.todaysDate()
            if isinstance(ts, datetime.datetime):
                d = ts.date()
            else:
                d = ts
            return ql.Date(d.day, d.month, d.year)

        # Use your existing ZODB open/commit lifecycle.
        with self.__open__():
            out: _BulkOut = defaultdict(dict)

            # Pre-prepare per-timestamp jobs
            jobs: List[Tuple[DateLike, List[str]]] = []
            base_cusips = _clean_list(cusips)
            for ts in timestamps:
                jobs.append((ts, base_cusips))

            def _process_one(ts: DateLike, symbols: List[str]) -> Tuple[DateLike, Dict[str, "_FixedRateBondGenericPricer"]]:
                # --- alias resolution per timestamp ---
                from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

                as_of_ref = _as_of_ref(ts)
                ref_df = update_reference_data(source="fiscaldata", force_refresh=force_refresh)
                ref_df = ref_df[(ref_df["issue_date"] <= as_of_ref) & (ref_df["maturity_date"] >= as_of_ref)].copy()
                ref_df["rank"] = ref_df.groupby("oi")["issue_date"].rank(method="first", ascending=False).astype(int) - 1

                alias_to_cusip, meta_by_cusip = self._resolve_aliases_bulk(symbols, ts, ref_df=ref_df)  # :contentReference[oaicite:0]{index=0}

                result: Dict[str, "_FixedRateBondGenericPricer"] = {}

                # -------------------- QL path (FedInvest/WSJ) --------------------
                if self.source.upper() == "USTS_FEDINVEST_WSJ_LIVE-QL":
                    from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher, get_isin_from_cusip
                    from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer

                    is_live = _is_live(ts)
                    wsj_buffer = self._wsj_buffer_date()
                    ts_qldate = _ts_to_ql_date(ts)
                    in_wsj_buffer = ts_qldate > wsj_buffer

                    if is_live:
                        wsj = WSJFetcher()
                        live_data = wsj.fetch_live_ust_quotes(cusips=list(alias_to_cusip.values()))
                        for original, cusip in alias_to_cusip.items():
                            try:
                                meta = dict(meta_by_cusip[cusip])
                                meta["timestamp"] = live_data[cusip]["timestamp"]
                                result[original] = QLFixedRateBondPricer(
                                    ql_frb_id="USTS",
                                    reference_date=live_data[cusip]["timestamp"].date(),
                                    issue_date=meta["issue_date"],
                                    maturity_date=meta["maturity_date"],
                                    cpn=meta["cpn"],
                                    ytm=float(live_data[cusip]["ytm"]),
                                    meta_data=meta,
                                )
                            except Exception:
                                pass
                        return ts, result

                    if in_wsj_buffer:
                        wsj = WSJFetcher()
                        mapping = {get_isin_from_cusip(c, "US")[2:]: c for c in alias_to_cusip.values()}
                        wide = wsj.ust_intraday_timeseries(mapping, show_tqdm=show_tqdm)

                        est = pytz.timezone("America/New_York")
                        assert isinstance(ts, datetime.date) and not isinstance(ts, datetime.datetime)
                        t_3pm = est.localize(datetime.datetime(ts.year, ts.month, ts.day, 15, 0, 0)).astimezone(pytz.UTC)
                        idx = wide.index
                        pos = idx.get_indexer([t_3pm], method="nearest")[0]
                        nearest_ts = idx[pos]
                        if abs(nearest_ts - t_3pm) > pd.Timedelta("30min"):
                            raise ValueError("No intraday snapshot within 30min of 3pm ET")

                        for original, cusip in alias_to_cusip.items():
                            try:
                                y = wide[cusip].iloc[pos]
                                if pd.isna(y):
                                    col = wide[cusip].dropna()
                                    if col.empty:
                                        raise ValueError(f"No intraday data for {cusip} near 3pm")
                                    nearest_ts = col.index[col.index.get_indexer([t_3pm], method="nearest")[0]]
                                    y = col.loc[nearest_ts]
                                meta = dict(meta_by_cusip[cusip])
                                meta["timestamp"] = nearest_ts
                                result[original] = QLFixedRateBondPricer(
                                    ql_frb_id="USTS",
                                    reference_date=nearest_ts.date(),
                                    issue_date=meta["issue_date"],
                                    maturity_date=meta["maturity_date"],
                                    cpn=meta["cpn"],
                                    ytm=float(y),
                                    meta_data=meta,
                                )
                            except Exception:
                                pass
                        return ts, result

                    # Historical daily close via FedInvest
                    from pandas.tseries.offsets import BDay

                    timestamp_dt = datetime.datetime(as_of_ref.year, as_of_ref.month, as_of_ref.day)

                    self._ensure_pricer_cache()
                    cache = getattr(self, self._FRB_PRICER_CACHE)

                    # One FedInvest snapshot per date; then fill pricers
                    fi_map = self.fi.runner(dates=[timestamp_dt], refresh_cache=force_refresh)
                    fi_df = fi_map.get(timestamp_dt)
                    if fi_df is None or fi_df.empty:
                        raise KeyError(f"No FedInvest snapshot for {as_of_ref} (key: {timestamp_dt})")

                    fi_df = fi_df.set_index("cusip")

                    from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer

                    for original, cusip in alias_to_cusip.items():
                        try:
                            clean_price = float(fi_df.loc[cusip]["eod_price"])
                        except Exception:
                            continue

                        meta = self._pyify_meta(meta_by_cusip[cusip])
                        args = {
                            "ql_frb_id": "USTS",
                            "reference_date": as_of_ref.isoformat(),
                            "clean_price": clean_price,
                            "meta_data": meta,
                            "schema": 1,
                            "source": "fedinvest",
                        }
                        cache_key = f"{as_of_ref.isoformat()}-{cusip}-{self.source.upper()}"
                        self._threadsafe_cache_put(cache_key, args)  # guarded writer
                        result[original] = self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")
                    return ts, result

                # -------------------- RL path (Webull/WSJ live) --------------------
                elif self.source.upper() == "USTS_WEBULL_WSJ_LIVE-RL":
                    from pandas.tseries.offsets import BDay

                    from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher
                    from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher
                    from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer

                    is_live = _is_live(ts)
                    if is_live:
                        wsj = WSJFetcher()
                        live_data = wsj.fetch_live_ust_quotes(cusips=list(alias_to_cusip.values()))
                        for original, cusip in alias_to_cusip.items():
                            try:
                                meta = dict(meta_by_cusip[cusip])
                                meta["timestamp"] = live_data[cusip]["timestamp"]
                                result[original] = RLFixedRateBondPricer(
                                    rl_frb_id="USTS",
                                    reference_date=live_data[cusip]["timestamp"].date(),
                                    issue_date=meta["issue_date"],
                                    maturity_date=meta["maturity_date"],
                                    cpn=meta["cpn"],
                                    ytm=float(live_data[cusip]["ytm"]),
                                    meta_data=meta,
                                )
                            except Exception:
                                pass
                        return ts, result

                    # non-live intraday: try cache first, then batch fetch via Webull
                    self._ensure_pricer_cache()
                    cache = getattr(self, self._FRB_PRICER_CACHE)
                    to_fetch: "OrderedDict[str, str]" = OrderedDict()

                    # exact ts is required (your RL branch keys on exact timestamp)
                    if isinstance(ts, datetime.datetime):
                        # Check for cached pricers/args under both (cusip, original)
                        for original, cusip in alias_to_cusip.items():
                            hit = None
                            for key_c in (cusip, original):
                                cache_key = f"{ts.isoformat()}-{key_c}-{self.source.upper()}"
                                hit = self._threadsafe_cache_get(cache_key)
                                if hit is not None:
                                    break
                            if hit is not None and not force_refresh:
                                # build pricer whether cached object or args
                                if hasattr(hit, "__class__") and hit.__class__.__name__ == "RLFixedRateBondPricer":
                                    result[original] = hit  # already a pricer
                                else:
                                    result[original] = self._build_pricer_from_args(
                                        hit, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
                                    )
                            else:
                                to_fetch[original] = cusip

                        if not to_fetch:
                            return ts, result

                        # Batch fetch all needed cusips around the day, then fill cache for *all* points
                        ny = pytz.timezone("America/New_York")
                        start_ny = ny.localize(datetime.datetime(ts.year, ts.month, ts.day, 7, 0, 0)) - BDay(1)
                        end_ny = ny.localize(datetime.datetime(ts.year, ts.month, ts.day, 17, 0, 0)) + BDay(1)

                        wb = WebullFintechFetcher(debug_verbose=False, error_verbose=True)
                        wide: pd.DataFrame = wb.intraday_by_cusips(
                            cusips=list(to_fetch.values()),
                            start=start_ny,
                            end=end_ny,
                            show_tqdm=show_tqdm,
                        )  # batched async underneath  :contentReference[oaicite:1]{index=1}  :contentReference[oaicite:2]{index=2}

                        # Persist all timeslices to ZODB (same scheme as your RL branch)
                        for original, cusip in to_fetch.items():
                            if cusip not in wide.columns:
                                continue
                            series = wide[cusip].dropna()
                            for curr_ts, ytm in series.items():
                                args = {
                                    "rl_frb_id": "USTS",
                                    "reference_date": curr_ts.date().isoformat(),
                                    "ytm": float(ytm),
                                    "meta_data": self._pyify_meta({**meta_by_cusip[cusip], "timestamp": curr_ts.isoformat()}),
                                    "schema": 1,
                                    "source": f"{curr_ts.isoformat()}-{cusip}-{self.source.upper()}",
                                }
                                cache_key = f"{curr_ts.isoformat()}-{cusip}-{self.source.upper()}"
                                self._threadsafe_cache_put(cache_key, args)

                            # Return the exact request point if present; else leave missing
                            if ts in series.index:
                                curr_ts = ts
                                ytm = float(series.loc[curr_ts])
                                args = {
                                    "rl_frb_id": "USTS",
                                    "reference_date": curr_ts.date().isoformat(),
                                    "ytm": ytm,
                                    "meta_data": self._pyify_meta({**meta_by_cusip[cusip], "timestamp": curr_ts.isoformat()}),
                                    "schema": 1,
                                    "source": f"{curr_ts.isoformat()}-{cusip}-{self.source.upper()}",
                                }
                                result[original] = self._build_pricer_from_args(args, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn")

                        self.zodb_commit()
                        return ts, result

                    # If we got here, user passed a date (not datetime) for RL non-live; no canonical source
                    # for an RL daily close in your repo; we’ll just raise to match your existing semantics.
                    raise NotImplementedError("For RL, pass an intraday datetime for timestamp or 'live'.")

                # -------------------- Unsupported source --------------------
                else:
                    raise NotImplementedError(f"Unsupported source {self.source}")

            # -------- fan out (timestamp-level) with threads --------
            results: List[Tuple[DateLike, Dict[str, "_FixedRateBondGenericPricer"]]] = []
            if max_workers == 1 or len(jobs) == 1:
                iterable = jobs
                if show_tqdm:
                    iterable = tqdm.tqdm(iterable, desc="FETCHING PRICERS")
                for ts, syms in iterable:
                    results.append(_process_one(ts, syms))
            else:
                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="frb-mdp") as pool:
                    futures = {pool.submit(_process_one, ts, syms): (ts, syms) for ts, syms in jobs}
                    iterator = as_completed(futures)
                    if show_tqdm:
                        iterator = tqdm.tqdm(iterator, total=len(futures), desc="FETCHING PRICERS")
                    for fut in iterator:
                        results.append(fut.result())

            for ts, res in results:
                if res:
                    out[ts].update(res)

            return dict(out)

    def __open__(self):
        with self._open_lock:
            if self._open_count == 0:
                self._ensure_pricer_cache()
            self._open_count += 1
        return self

    def __close__(self, *, commit: bool = True):
        with self._open_lock:
            if self._open_count <= 0:
                return
            self._open_count -= 1
            if self._open_count == 0:
                try:
                    if commit:
                        self.zodb_commit()
                finally:
                    try:
                        self.close_zodb()
                    finally:
                        self._cache_ready = False

    def __enter__(self):
        return self.__open__()

    def __exit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))

    async def __aenter__(self):
        return self.__open__()

    async def __aexit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))

from __future__ import annotations

import json
import math
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple

import httpx
import pandas as pd
import QuantLib as ql

TREASURYDIRECT_JQSEARCH_URL = "https://www.treasurydirect.gov/TA_WS/securities/jqsearch"
TREASURYDIRECT_SEARCH_URL = "https://www.treasurydirect.gov/TA_WS/securities/search"

KeepMode = Literal["all", "latest_issue", "original_issue"]
FilterCondition = Literal["EQUAL", "STARTS_WITH"]
DateField = Literal["maturityDate", "issueDate", "auctionDate", "announcementDate", "datedDate"]

_JSONP_RE = re.compile(r"^[^(]*\(\s*(\{.*\}|\[.*\])\s*\)\s*;?\s*$", re.DOTALL)


def _add_ttm_columns_with_quantlib(df: pd.DataFrame, as_of: date) -> pd.DataFrame:
    if df.empty:
        df["ttm_y"] = []
        df["ttm_d"] = []
        return df

    dc = ql.ActualActual(ql.ActualActual.Actual365)
    ql_as_of = ql.Date(as_of.day, as_of.month, as_of.year)
    ql.Settings.instance().evaluationDate = ql_as_of

    def _yf(mdate: date) -> float:
        if pd.isna(mdate):
            return float("nan")
        d2 = ql.Date(mdate.day, mdate.month, mdate.year)
        return dc.yearFraction(ql_as_of, d2)

    def _dcnt(mdate: date) -> int:
        if pd.isna(mdate):
            return pd.NA
        d2 = ql.Date(mdate.day, mdate.month, mdate.year)
        return int(dc.dayCount(ql_as_of, d2))

    df = df.copy()
    df["maturity_date"] = pd.to_datetime(df["maturity_date"]).dt.date
    df["ttm_y"] = df["maturity_date"].map(_yf)
    df["ttm_d"] = df["maturity_date"].map(_dcnt)
    return df


def _format_coupon_to_eighths(coupon_pct: float) -> str:
    if pd.isna(coupon_pct):
        return ""
    whole = int(math.floor(coupon_pct))
    frac = coupon_pct - whole
    eighths = int(round(frac * 8))
    if eighths == 8:
        whole += 1
        eighths = 0
    if eighths == 0:
        return f"{whole}"
    num_map = {1: "1/8", 2: "1/4", 3: "3/8", 4: "1/2", 5: "5/8", 6: "3/4", 7: "7/8"}
    return f"{whole} {num_map.get(eighths, '')}"


def _add_label_column(df: pd.DataFrame) -> pd.DataFrame:
    df["int_rate"] = pd.to_numeric(df["int_rate"], errors="coerce")
    coup_str = df["int_rate"].map(_format_coupon_to_eighths)
    month = pd.to_datetime(df["maturity_date"]).dt.strftime("%b")
    yy = pd.to_datetime(df["maturity_date"]).dt.strftime("%y")
    df["label"] = "T " + coup_str + " " + month + " " + yy
    df["label"] = df["label"].str.replace("T  ", "T ", regex=False)
    return df


def _parse_json_or_jsonp(text: str) -> Any:
    s = text.strip()
    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
        return json.loads(s)
    m = _JSONP_RE.match(s)
    if not m:
        raise ValueError("Response is neither JSON nor JSONP-wrapped JSON.")
    return json.loads(m.group(1))


def _safe_add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # handles Feb-29 -> Feb-28, etc.
        return d.replace(month=2, day=28, year=d.year + years)


def _iter_date_windows(start: date, end: date, *, chunk_years: int) -> Iterable[Tuple[date, date]]:
    if end < start:
        return
    cur = start
    while cur <= end:
        nxt = _safe_add_years(cur, chunk_years)
        win_end = min(end, nxt)
        yield cur, win_end
        cur = win_end + timedelta(days=1)


def _coerce_dates(df: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


@dataclass
class _ThreadLocalClientPool:
    timeout: float
    limits: httpx.Limits
    headers: Dict[str, str]

    def __post_init__(self) -> None:
        self._local = threading.local()
        self._clients: List[httpx.Client] = []
        self._lock = threading.Lock()

    def get(self) -> httpx.Client:
        cli = getattr(self._local, "client", None)
        if cli is None:
            cli = httpx.Client(
                timeout=self.timeout,
                limits=self.limits,
                headers=self.headers,
                http2=True,
                follow_redirects=True,
            )
            self._local.client = cli
            with self._lock:
                self._clients.append(cli)
        return cli

    def close_all(self) -> None:
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for c in clients:
            try:
                c.close()
            except Exception:
                pass


def fetch_ust_refdata_treasurydirect(
    cusips: Optional[Sequence[str]] = None,
    *,
    # ---- date-range "universe" mode ----
    as_of_date: Optional[date] = None,
    horizon_years: int = 30,
    date_field: DateField = "maturityDate",
    chunk_years: int = 1,
    # ---- snapshot semantics ----
    active_only: bool = True,
    drop_future_auctions: bool = True,  # excludes auctions/issuances after as_of_date
    # ---- existing behavior knobs ----
    condition: FilterCondition = "EQUAL",
    keep: KeepMode = "all",
    max_workers: Optional[int] = None,
    pagesize: int = 200,
    timeout: float = 15.0,
    max_retries: int = 2,
    backoff_base: float = 0.35,
    parse_dates: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Exception]]:
    """
    Modes:

    A) CUSIP mode:
       - pass cusips=[...]
       - if as_of_date provided:
           * active_only=True keeps only CUSIPs outstanding as-of (issued on/before; not matured)
           * drop_future_auctions=True drops rows where auction/issue > as_of_date

    B) Universe snapshot mode (as-of):
       - omit cusips (or cusips=[])
       - pass as_of_date=...
       - fetches securities with `date_field` in [as_of_date, as_of_date + horizon_years]
       - then:
           * active_only=True keeps only CUSIPs outstanding as-of (issued on/before; not matured)
           * drop_future_auctions=True drops future auction/issue rows

    Notes on "active":
      - A CUSIP is treated as active as-of if:
          min(datedDate, issueDate) <= as_of_date  AND  max(maturityDate) > as_of_date
        (computed per CUSIP across returned rows)
    """
    cusips = list(dict.fromkeys([c.strip().upper() for c in (cusips or []) if c and str(c).strip()]))
    universe_mode = len(cusips) == 0

    if universe_mode and as_of_date is None:
        raise ValueError("Universe snapshot mode requires as_of_date when cusips is empty.")
    if (not universe_mode) and len(cusips) == 0:
        return pd.DataFrame(), {}

    if max_workers is None:
        max_workers = 12 if universe_mode else min(32, len(cusips))

    limits = httpx.Limits(max_connections=max_workers * 2, max_keepalive_connections=max_workers * 2)
    headers = {
        "User-Agent": "ust-refdata/1.0 (+https://www.treasurydirect.gov/)",
        "Accept": "*/*",
    }
    pool = _ThreadLocalClientPool(timeout=timeout, limits=limits, headers=headers)

    errors: Dict[str, Exception] = {}
    all_rows: List[Dict[str, Any]] = []

    def _request_with_retries(url: str, params: Dict[str, Any]) -> Any:
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                client = pool.get()
                r = client.get(url, params=params)
                if 500 <= r.status_code <= 599:
                    raise httpx.HTTPStatusError("Server error", request=r.request, response=r)
                r.raise_for_status()
                return _parse_json_or_jsonp(r.text)
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError, ValueError) as e:
                last_exc = e
                if attempt >= max_retries:
                    break
                time.sleep(backoff_base * (2**attempt) + random.random() * 0.1)
        assert last_exc is not None
        raise last_exc

    # ------------------------ CUSIP mode ------------------------
    def _build_jqsearch_params(
        cusip_or_prefix: str,
        *,
        condition: FilterCondition,
        pagesize: int,
        callback: str,
    ) -> Dict[str, Any]:
        now_ms = int(time.time() * 1000)
        return {
            "format": "jsonp",
            "callback": callback,
            "cusipoperator": "and",
            "filtervalue0": cusip_or_prefix,
            "filtercondition0": condition,
            "filteroperator0": "1",
            "filterdatafield0": "cusip",
            "filterscount": "1",
            "groupscount": "0",
            "pagenum": "0",
            "pagesize": str(pagesize),
            "recordstartindex": "0",
            "recordendindex": str(pagesize),
            "_": str(now_ms),
        }

    def _fetch_one_cusip(query: str) -> List[Dict[str, Any]]:
        cb = f"cb{random.randint(10_000, 99_999)}"
        params = _build_jqsearch_params(query, condition=condition, pagesize=pagesize, callback=cb)
        payload = _request_with_retries(TREASURYDIRECT_JQSEARCH_URL, params)
        rows = (payload or {}).get("securityList", []) or []
        for row in rows:
            row["query"] = query
        return rows

    # ------------------------ Universe snapshot mode ------------------------
    def _fetch_one_window(start_d: date, end_d: date) -> List[Dict[str, Any]]:
        params = {
            "format": "json",
            date_field: f"{start_d:%Y-%m-%d},{end_d:%Y-%m-%d}",
        }
        payload = _request_with_retries(TREASURYDIRECT_SEARCH_URL, params)

        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("securityList", []) or []
        else:
            rows = []

        out: List[Dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                row = dict(row)
                row["range_start"] = f"{start_d:%Y-%m-%d}"
                row["range_end"] = f"{end_d:%Y-%m-%d}"
                out.append(row)
        return out

    # ------------------------ execute ------------------------
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            if not universe_mode:
                futs = {ex.submit(_fetch_one_cusip, q): q for q in cusips}
                for fut in as_completed(futs):
                    q = futs[fut]
                    try:
                        all_rows.extend(fut.result())
                    except Exception as e:
                        errors[q] = e
            else:
                assert as_of_date is not None
                end_date = _safe_add_years(as_of_date, horizon_years)
                windows = list(_iter_date_windows(as_of_date, end_date, chunk_years=chunk_years))
                futs = {ex.submit(_fetch_one_window, s, e): f"{date_field}:{s:%Y-%m-%d}->{e:%Y-%m-%d}" for (s, e) in windows}
                for fut in as_completed(futs):
                    key = futs[fut]
                    try:
                        all_rows.extend(fut.result())
                    except Exception as e:
                        errors[key] = e
    finally:
        pool.close_all()

    df = pd.DataFrame(all_rows)
    if df.empty:
        return df, errors

    if "cusip" in df.columns:
        df["cusip"] = df["cusip"].astype("string").str.upper()

    # ---- parse key dates early (needed for as-of semantics) ----
    key_date_cols = ["auctionDate", "issueDate", "datedDate", "maturityDate", "updatedTimestamp"]
    for c in key_date_cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")

    # # ------------------------ AS-OF SNAPSHOT: keep ACTIVE CUSIPs ------------------------
    # if as_of_date is not None and active_only and "cusip" in df.columns:
    #     cutoff = pd.Timestamp(as_of_date)

    #     maturity_max = df.groupby("cusip")["maturityDate"].max() if "maturityDate" in df.columns else None
    #     # dated_min = df.groupby("cusip")["datedDate"].min() if "datedDate" in df.columns else None
    #     # issue_min = df.groupby("cusip")["auctionDate"].min() if "auctionDate" in df.columns else None

    #     if maturity_max is not None:
    #         start = None
    #         if dated_min is not None and issue_min is not None:
    #             start = dated_min.fillna(issue_min)
    #         elif dated_min is not None:
    #             start = dated_min
    #         elif issue_min is not None:
    #             start = issue_min

    #         if start is not None:
    #             active_cusips = start.index[(start <= cutoff) & (maturity_max > cutoff)]
    #             df = df[df["cusip"].isin(active_cusips)].copy()

    # if df.empty:
    #     return df.reset_index(drop=True), errors

    # ------------------------ AS-OF SNAPSHOT: drop FUTURE auction/issue rows ------------------------
    if as_of_date is not None and drop_future_auctions:
        cutoff = pd.Timestamp(as_of_date)
        auction_dt = df["auctionDate"] if "auctionDate" in df.columns else pd.Series(pd.NaT, index=df.index)
        # issue_dt = df["issueDate"] if "issueDate" in df.columns else pd.Series(pd.NaT, index=df.index)

        # keep row unless it is clearly in the future (auction or issue after cutoff)
        # future = (auction_dt.notna() & (auction_dt > cutoff)) | (issue_dt.notna() & (issue_dt > cutoff))
        future = auction_dt.notna() & (auction_dt > cutoff)
        df = df.loc[~future].copy()

    if df.empty:
        return df.reset_index(drop=True), errors

    # ------------------------ de-dupe ------------------------
    dedupe_cols = [c for c in ["cusip", "issueDate", "auctionDate", "datedDate", "maturityDate", "reopening"] if c in df.columns]
    df = df.drop_duplicates(subset=dedupe_cols, keep="last") if dedupe_cols else df.drop_duplicates(keep="last")

    # ------------------------ keep policy (per CUSIP) ------------------------
    # If as_of_date is provided and keep is "latest_issue", ensure "latest" is <= as_of_date
    # if keep != "all" and "cusip" in df.columns:
    #     cutoff = pd.Timestamp(as_of_date) if as_of_date is not None else None
    #     issue_dt = df["issueDate"] if "issueDate" in df.columns else pd.Series(pd.NaT, index=df.index)

    #     if keep == "latest_issue":
    #         df2 = df.copy()
    #         if cutoff is not None:
    #             df2 = df2.loc[issue_dt.isna() | (issue_dt <= cutoff)].copy()
    #         df2 = df2.assign(_issue_dt=issue_dt)
    #         df = df2.sort_values("_issue_dt").groupby("cusip", as_index=False).tail(1).drop(columns=["_issue_dt"])

    #     elif keep == "original_issue":
    #         issue_dt = df["issueDate"] if "issueDate" in df.columns else pd.Series(pd.NaT, index=df.index)
    #         is_original = df["reopening"].astype("string").str.upper().eq("NO") if "reopening" in df.columns else pd.Series(False, index=df.index)
    #         df2 = df.assign(_issue_dt=issue_dt, _is_original=is_original)
    #         df2 = df2.sort_values(["cusip", "_is_original", "_issue_dt"], ascending=[True, False, True])
    #         df = df2.groupby("cusip", as_index=False).head(1).drop(columns=["_issue_dt", "_is_original"])

    # ------------------------ optional date parsing (remaining cols) ------------------------
    if parse_dates:
        date_cols = [
            "announcementDate",
            "firstInterestPaymentDate",
            "backDatedDate",
            "maturingDate",
            "originalIssueDate",
            "originalDatedDate",
            "tintCusip1DueDate",
            "tintCusip2DueDate",
        ]
        df = _coerce_dates(df, date_cols)

    df = df.reset_index(drop=True)
    df.columns = [re.sub(r"(?<!^)(?=[A-Z])", "_", col).lower() for col in df.columns]

    df = df[df["maturity_date"].dt.date >= as_of_date]
    df = df[df["auction_date"].dt.date <= as_of_date]

    df = df.sort_values(["cusip", "issue_date"]).drop_duplicates(subset=["cusip"], keep="first")
    df["rank"] = df.groupby("original_security_term")["auction_date"].rank(method="first", ascending=False).astype(int) - 1

    df = _add_ttm_columns_with_quantlib(df, as_of_date)

    df = df.sort_values(["original_security_term", "issue_date", "cusip"], ascending=[True, False, True]).rename(columns={"interest_rate": "int_rate"})
    df = _add_label_column(df)
    keep = [
        c
        for c in ["record_date", "label", "cusip", "rank", "original_security_term", "auction_date", "issue_date", "maturity_date", "ttm_y", "int_rate"]
        if c in df.columns
    ]
    df = df[keep].copy()
    df = df.rename(columns={"original_security_term": "oi", "int_rate": "cpn", "ttm_y": "ttm"})
    df = df.sort_values(by="maturity_date")
    return df

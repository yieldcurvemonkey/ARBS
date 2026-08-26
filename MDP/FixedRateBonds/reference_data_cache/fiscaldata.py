import datetime
import logging
import math
import time
from typing import Iterable, List, Literal, Union

import pandas as pd
import QuantLib as ql
import requests

_logger = logging.getLogger(__name__)
_TIMEOUT = 30
_MAX_RETRIES = 3


def _as_term_strings(otrs: Iterable[Union[int, str]]) -> List[str]:
    out = []
    for x in otrs:
        if isinstance(x, (int, float)):
            out.append(f"{int(x)}-Year")
        else:
            s = str(x)
            out.append(s if s.endswith("-Year") else f"{s}-Year")
    return out


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



def _add_reopening_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Per CUSIP: the term at issue of its SHORTEST tranche, and that tranche's issue date.

    CBOT's re-opening clause (Chapters 19/20/21/26) reads:

        "If the U.S. Treasury Department auctions and issues a Treasury security that meets these
         standards, such that said security is a re-opening of an extant Treasury issue that had
         not previously met these standards, then the extant Treasury issue shall be deemed to be a
         Treasury note meeting these standards and shall be added to the contract grade as of the
         issue date of said newly auctioned Treasury security."

    "Term to maturity at issue" for a re-opening tranche is measured from THAT tranche's issue date,
    which is why this is computed from dates rather than parsed out of `security_term`: that string
    runs to forms like "29-Year 6-Month", and a parser keeping only the leading number rounds DOWN
    -- the permissive direction for a cap, i.e. the direction that admits bonds that cannot be
    delivered.

    Measured on the two CUSIPs CME's published conversion-factor file named and this repo missed:
    912828Z78 (7-Year issued 2020-01-31, reopened as a 5-Year 2022-01-31 -> 60 months) and
    91282CGQ8 (7-Year issued 2023-02-28, reopened as a 5-Year 2025-02-28 -> 60 months).
    """
    out = df.copy()
    if "cusip" not in out.columns or "issue_date" not in out.columns or "maturity_date" not in out.columns:
        out["reopened_term_months"] = pd.NA
        out["reopened_issue_date"] = pd.NaT
        return out

    issue = pd.to_datetime(out["issue_date"], errors="coerce")
    maturity = pd.to_datetime(out["maturity_date"], errors="coerce")
    months = (maturity.dt.year - issue.dt.year) * 12 + (maturity.dt.month - issue.dt.month)
    months = months.where(maturity.dt.day >= issue.dt.day, months - 1)
    out["_tranche_term_months"] = months.where(issue.notna() & maturity.notna())

    valid = out[out["_tranche_term_months"].notna()]
    if valid.empty:
        out["reopened_term_months"] = pd.NA
        out["reopened_issue_date"] = pd.NaT
    else:
        shortest = valid.loc[valid.groupby("cusip")["_tranche_term_months"].idxmin()]
        out["reopened_term_months"] = out["cusip"].map(dict(zip(shortest["cusip"], shortest["_tranche_term_months"])))
        out["reopened_issue_date"] = out["cusip"].map(dict(zip(shortest["cusip"], shortest["issue_date"])))
    return out.drop(columns=["_tranche_term_months"])


def _fetch_auctions_raw_fiscaldata(as_of: Union[datetime.date, Literal["all"]], term_strings: List[str]) -> pd.DataFrame:
    base = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query?"
    terms_csv = ",".join(term_strings)
    f_terms = f"original_security_term:in:({terms_csv})"
    f_tips = "inflation_index_security:eq:No"
    f_type = "security_type:in:(Note,Bond)"

    if as_of == "all":
        params = f"filter={f_terms},{f_tips},{f_type}&sort=-record_date&page[size]=10000"
    else:
        if as_of == "live":
            as_of = datetime.date.today()
        start_pad = as_of - datetime.timedelta(days=365 * 30)
        f_dates = f"record_date:lte:{as_of.strftime('%Y-%m-%d')},record_date:gte:{start_pad.strftime('%Y-%m-%d')}"
        params = f"filter={f_dates},{f_terms},{f_tips},{f_type}&sort=-record_date&page[size]=9999"

    url = base + params
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            break
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt < _MAX_RETRIES - 1:
                wait = 2 ** attempt
                _logger.warning(f"fiscaldata.treasury.gov attempt {attempt+1} failed ({e.__class__.__name__}), retrying in {wait}s")
                time.sleep(wait)
            else:
                raise
    data = resp.json().get("data", [])

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df = df[df["frn_index_determination_rate"] == "null"]

    for col in ["record_date", "auction_date", "issue_date", "maturity_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    return df


def _add_ttm_columns_with_quantlib(df: pd.DataFrame, as_of: datetime.date) -> pd.DataFrame:
    if df.empty:
        df["ttm_y"] = []
        df["ttm_d"] = []
        return df

    dc = ql.ActualActual(ql.ActualActual.Actual365)
    ql_as_of = ql.Date(as_of.day, as_of.month, as_of.year)
    ql.Settings.instance().evaluationDate = ql_as_of

    def _yf(mdate: datetime.date) -> float:
        if pd.isna(mdate):
            return float("nan")
        d2 = ql.Date(mdate.day, mdate.month, mdate.year)
        return dc.yearFraction(ql_as_of, d2)

    def _dcnt(mdate: datetime.date) -> int:
        if pd.isna(mdate):
            return pd.NA
        d2 = ql.Date(mdate.day, mdate.month, mdate.year)
        return int(dc.dayCount(ql_as_of, d2))

    df = df.copy()
    df["maturity_date"] = pd.to_datetime(df["maturity_date"]).dt.date
    df["ttm_y"] = df["maturity_date"].map(_yf)
    df["ttm_d"] = df["maturity_date"].map(_dcnt)
    return df


def _fetch_fiscaldata(
    fetch_as_of: Union[datetime.date, Literal["all"]],
    process_as_of: datetime.date,
    append_mspd_table3: bool = False,
    append_mspd_table5: bool = False,
    append_soma_holdings: bool = False,
    append_free_float: bool = False,
    source_kwargs={},
) -> pd.DataFrame:
    otrs: Iterable[Union[int, str]] = source_kwargs.get("otrs", (2, 3, 5, 7, 10, 20, 30))
    term_strings = _as_term_strings(otrs)

    df = _fetch_auctions_raw_fiscaldata(fetch_as_of, term_strings)
    if df.empty:
        return pd.DataFrame()

    if process_as_of == "live":
        process_as_of = datetime.date.today()
    if fetch_as_of == "live":
        fetch_as_of = datetime.date.today()

    # A CUSIP can be auctioned more than once. Collapsing to the EARLIEST tranche is right for the
    # label and the original term, but it destroys the RE-OPENING information CBOT's deliverable
    # grade turns on: a 7-year note reopened later as a 5-year becomes deliverable into ZF from the
    # reopening's issue date (Chapters 20/21 carry that clause today, 19/26 from March 2026).
    # Keying eligibility off `oi` alone made the basket miss 912828Z78 from CME's own published
    # ZTH25 grade and 91282CGQ8 from ZFH25. So carry the shortest tranche forward alongside it.
    df = _add_reopening_columns(df)
    df = df.sort_values(["cusip", "issue_date"]).drop_duplicates(subset=["cusip"], keep="first")
    if fetch_as_of != "all":
        df = df[df["maturity_date"] > process_as_of].copy()
        df["rank"] = df.groupby("original_security_term")["issue_date"].rank(method="first", ascending=False).astype(int) - 1
        df = _add_ttm_columns_with_quantlib(df, process_as_of)

    df = df.sort_values(["original_security_term", "issue_date", "cusip"], ascending=[True, False, True])
    df = _add_label_column(df)
    keep = [
        c
        # `inflation_index_security` and `floating_rate` are kept so the CBOT fixed-principal grade
        # (no TIPS, no FRNs) can be enforced where a basket is BUILT, not only by the server-side
        # filter in _fetch_auctions_raw_fiscaldata. Both are exact partitions of the dataset.
        # `security_type` is NOT kept: measured, the API returns the identical 2,375 rows with and
        # without it, because TIPS ride as security_type='Note'/'Bond'.
        # `reopened_*` carry the shortest tranche, which CBOT's re-opening clause turns on.
        for c in [
            "record_date", "label", "cusip", "rank", "original_security_term", "auction_date",
            "issue_date", "maturity_date", "ttm_y", "int_rate",
            "inflation_index_security", "floating_rate",
            "reopened_term_months", "reopened_issue_date",
        ]
        if c in df.columns
    ]
    df = df[keep].copy()
    df = df.rename(columns={"original_security_term": "oi", "int_rate": "cpn", "ttm_y": "ttm"})
    df = df.sort_values(by="maturity_date")

    if append_free_float:
        append_mspd_table5 = True
        append_soma_holdings = True

    if append_mspd_table3:
        ql_date = ql.Date(fetch_as_of.day, fetch_as_of.month, fetch_as_of.year)
        to_fetch: ql.Date = ql.NullCalendar().endOfMonth(ql_date - ql.Period("1m"))
        fetch_date = datetime.date(to_fetch.year(), to_fetch.month(), to_fetch.dayOfMonth())
        mspd_table3_url = f"https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_3_market?filter=record_date:eq:{fetch_date.strftime('%Y-%m-%d')}&page[size]=10000"
        mspd_table3_df = pd.DataFrame(requests.get(mspd_table3_url, timeout=_TIMEOUT).json()["data"])
        mspd_table3_df = mspd_table3_df[mspd_table3_df["security_class1_desc"].isin(["Notes", "Bonds"])]
        to_numeric = ["issued_amt", "outstanding_amt"]
        for n in to_numeric:
            mspd_table3_df[n] = pd.to_numeric(mspd_table3_df[n], errors="coerce")

        mspd_table3_df = mspd_table3_df.rename(columns={"security_class2_desc": "cusip"})
        mspd_table3_df = mspd_table3_df[["cusip"] + to_numeric]
        mspd_table3_df = mspd_table3_df.drop_duplicates(subset=["cusip"], keep="first")
        df = pd.merge(left=df, right=mspd_table3_df, on="cusip", how="outer")

    if append_mspd_table5:
        ql_date = ql.Date(fetch_as_of.day, fetch_as_of.month, fetch_as_of.year)
        to_fetch: ql.Date = ql.NullCalendar().endOfMonth(ql_date - ql.Period("1m"))

        fetch_date = datetime.date(to_fetch.year(), to_fetch.month(), to_fetch.dayOfMonth())
        mspd_table5_url = f"https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_5?filter=record_date:eq:{fetch_date.strftime('%Y-%m-%d')}&page[size]=10000"
        # print(mspd_table5_url)
        mspd_table5_df = pd.DataFrame(requests.get(mspd_table5_url, timeout=_TIMEOUT).json()["data"])
        mspd_table5_df = mspd_table5_df[mspd_table5_df["security_class1_desc"].isin(["Treasury Bonds", "Treasury Notes"])]
        to_numeric = ["outstanding_amt", "portion_unstripped_amt", "portion_stripped_amt", "reconstituted_amt"]
        for n in to_numeric:
            mspd_table5_df[n] = pd.to_numeric(mspd_table5_df[n], errors="coerce") * 1000

        mspd_table5_df = mspd_table5_df.drop(columns=["cusip"]).rename(columns={"security_class2_desc": "cusip"})
        mspd_table5_df = mspd_table5_df[["cusip"] + to_numeric]
        mspd_table5_df = mspd_table5_df.drop_duplicates(subset=["cusip"], keep="first")
        df = pd.merge(left=df, right=mspd_table5_df, on="cusip", how="outer")

    if append_soma_holdings:
        valid_soma_holding_dates_reponse = requests.get("https://markets.newyorkfed.org/api/soma/asofdates/list.json", timeout=_TIMEOUT).json()
        valid_soma_dates_dt = [datetime.datetime.strptime(dt_string, "%Y-%m-%d").date() for dt_string in valid_soma_holding_dates_reponse["soma"]["asOfDates"]]
        valid_closest_date = min(
            (valid_date for valid_date in valid_soma_dates_dt if valid_date <= fetch_as_of),
            key=lambda valid_date: abs(fetch_as_of - valid_date),
        )
        soma_url = f'https://markets.newyorkfed.org/api/soma/tsy/get/asof/{valid_closest_date.strftime("%Y-%m-%d")}.json'
        soma_df = pd.DataFrame(requests.get(soma_url, timeout=_TIMEOUT).json()["soma"]["holdings"])
        soma_df = soma_df[soma_df["securityType"] == "NotesBonds"]
        to_numeric = ["parValue", "percentOutstanding"]
        for n in to_numeric:
            soma_df[n] = pd.to_numeric(soma_df[n], errors="coerce")

        soma_df["outstanding_amt_backed_out_from_soma"] = soma_df["parValue"] / soma_df["percentOutstanding"]
        soma_df["percentOutstanding"] = soma_df["percentOutstanding"] * 100
        soma_df = soma_df[["cusip"] + to_numeric + ["outstanding_amt_backed_out_from_soma"]]
        soma_df = soma_df.rename(columns={"parValue": "soma_holdings", "percentOutstanding": "soma_holdings_of_pct_outstanding"})
        df = pd.merge(left=df, right=soma_df, on="cusip", how="outer")

    if append_free_float:
        for c in ["outstanding_amt", "soma_holdings", "portion_stripped_amt"]:
            df[c] = df[c].fillna(0)
        df["free_float"] = df["outstanding_amt"] - df["soma_holdings"] - df["portion_stripped_amt"]

    return df

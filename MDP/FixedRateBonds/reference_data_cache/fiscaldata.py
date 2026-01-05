import datetime
import math
from typing import Iterable, List, Literal, Union

import pandas as pd
import QuantLib as ql
import requests


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


def _fetch_auctions_raw_fiscaldata(as_of: Union[datetime.date, Literal["all"]], term_strings: List[str]) -> pd.DataFrame:
    base = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query?"
    terms_csv = ",".join(term_strings)
    f_terms = f"original_security_term:in:({terms_csv})"
    f_tips = "inflation_index_security:eq:No"
    f_type = "security_type:in:(Note,Bond)"

    if as_of == "all":
        params = f"filter={f_terms},{f_tips},{f_type}&sort=-record_date&page[size]=10000"
    else:
        start_pad = as_of - datetime.timedelta(days=365 * 30)
        f_dates = f"record_date:lte:{as_of.strftime('%Y-%m-%d')},record_date:gte:{start_pad.strftime('%Y-%m-%d')}"
        params = f"filter={f_dates},{f_terms},{f_tips},{f_type}&sort=-record_date&page[size]=9999"

    url = base + params
    resp = requests.get(url)
    resp.raise_for_status()
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

    df = df.sort_values(["cusip", "issue_date"]).drop_duplicates(subset=["cusip"], keep="first")
    if fetch_as_of != "all":
        df = df[df["maturity_date"] > process_as_of].copy()
        df["rank"] = df.groupby("original_security_term")["issue_date"].rank(method="first", ascending=False).astype(int) - 1
        df = _add_ttm_columns_with_quantlib(df, process_as_of)

    df = df.sort_values(["original_security_term", "issue_date", "cusip"], ascending=[True, False, True])
    df = _add_label_column(df)
    keep = [
        c
        for c in ["record_date", "label", "cusip", "rank", "original_security_term", "auction_date", "issue_date", "maturity_date", "ttm_y", "int_rate"]
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
        mspd_table3_df = pd.DataFrame(requests.get(mspd_table3_url).json()["data"])
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
        print(mspd_table5_url)
        mspd_table5_df = pd.DataFrame(requests.get(mspd_table5_url).json()["data"])
        mspd_table5_df = mspd_table5_df[mspd_table5_df["security_class1_desc"].isin(["Treasury Bonds", "Treasury Notes"])]
        to_numeric = ["outstanding_amt", "portion_unstripped_amt", "portion_stripped_amt", "reconstituted_amt"]
        for n in to_numeric:
            mspd_table5_df[n] = pd.to_numeric(mspd_table5_df[n], errors="coerce") * 1000

        mspd_table5_df = mspd_table5_df.drop(columns=["cusip"]).rename(columns={"security_class2_desc": "cusip"})
        mspd_table5_df = mspd_table5_df[["cusip"] + to_numeric]
        mspd_table5_df = mspd_table5_df.drop_duplicates(subset=["cusip"], keep="first")
        df = pd.merge(left=df, right=mspd_table5_df, on="cusip", how="outer")

    if append_soma_holdings:
        valid_soma_holding_dates_reponse = requests.get("https://markets.newyorkfed.org/api/soma/asofdates/list.json").json()
        valid_soma_dates_dt = [datetime.datetime.strptime(dt_string, "%Y-%m-%d").date() for dt_string in valid_soma_holding_dates_reponse["soma"]["asOfDates"]]
        valid_closest_date = min(
            (valid_date for valid_date in valid_soma_dates_dt if valid_date <= fetch_as_of),
            key=lambda valid_date: abs(fetch_as_of - valid_date),
        )
        soma_url = f'https://markets.newyorkfed.org/api/soma/tsy/get/asof/{valid_closest_date.strftime("%Y-%m-%d")}.json'
        soma_df = pd.DataFrame(requests.get(soma_url).json()["soma"]["holdings"])
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

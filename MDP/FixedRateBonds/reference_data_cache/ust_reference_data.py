import datetime
import math
import os
from pathlib import Path
from typing import Iterable, List, Literal, Optional, Union

import polars as pl
import QuantLib as ql
import requests


def _resolve_ust_cache_dir(source: str) -> Path:
    base = Path(__file__).resolve().parent
    ust_cache = base / "ust_reference_data" / source
    ust_cache.mkdir(parents=True, exist_ok=True)
    return ust_cache


def _cleanup_old_cache_dirs(root: Path, keep_last: int = 3) -> None:
    try:
        dated_dirs = sorted([p for p in root.iterdir() if p.is_dir()], reverse=True)
        for d in dated_dirs[keep_last:]:
            for p in d.glob("*.parquet"):
                try:
                    p.unlink()
                except OSError:
                    pass
            try:
                d.rmdir()
            except OSError:
                pass
    except Exception:
        pass


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
    if coupon_pct is None or (isinstance(coupon_pct, float) and math.isnan(coupon_pct)):
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


def _add_label_column(df: pl.DataFrame) -> pl.DataFrame:
    df = df.with_columns(
        pl.col("int_rate").cast(pl.Float64, strict=False).alias("int_rate")
    )

    # Apply coupon formatting
    coup_str = df.select(pl.col("int_rate")).to_series().map_elements(_format_coupon_to_eighths, return_dtype=pl.Utf8)

    # Extract month and year from maturity_date
    df = df.with_columns([
        pl.col("maturity_date").cast(pl.Date).dt.strftime("%b").alias("month"),
        pl.col("maturity_date").cast(pl.Date).dt.strftime("%y").alias("yy"),
    ])

    # Create label column
    df = df.with_columns(
        (pl.lit("T ") + coup_str + pl.lit(" ") + pl.col("month") + pl.lit(" ") + pl.col("yy")).alias("label")
    )

    # Clean up double spaces
    df = df.with_columns(
        pl.col("label").str.replace_all("T  ", "T ").alias("label")
    )

    # Drop temporary columns
    df = df.drop(["month", "yy"])

    return df


def _fetch_auctions_raw_fiscaldata(as_of: Union[datetime.date, Literal["all"]], term_strings: List[str]) -> pl.DataFrame:
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
        return pl.DataFrame()

    df = pl.DataFrame(data)
    df = df.filter(pl.col("frn_index_determination_rate") == "null")

    # Convert date columns
    date_cols = ["record_date", "auction_date", "issue_date", "maturity_date"]
    for col in date_cols:
        if col in df.columns:
            df = df.with_columns(
                pl.col(col).str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias(col)
            )
    return df


def _add_ttm_columns_with_quantlib(df: pl.DataFrame, as_of: datetime.date) -> pl.DataFrame:
    if df.height == 0:
        return df.with_columns([
            pl.lit(None).cast(pl.Float64).alias("ttm_y"),
            pl.lit(None).cast(pl.Int64).alias("ttm_d"),
        ])

    dc = ql.ActualActual(ql.ActualActual.Actual365)
    ql_as_of = ql.Date(as_of.day, as_of.month, as_of.year)
    ql.Settings.instance().evaluationDate = ql_as_of

    def _yf(mdate) -> float:
        if mdate is None:
            return float("nan")
        d2 = ql.Date(mdate.day, mdate.month, mdate.year)
        return dc.yearFraction(ql_as_of, d2)

    def _dcnt(mdate) -> Optional[int]:
        if mdate is None:
            return None
        d2 = ql.Date(mdate.day, mdate.month, mdate.year)
        return int(dc.dayCount(ql_as_of, d2))

    # Ensure maturity_date is Date type
    df = df.with_columns(
        pl.col("maturity_date").cast(pl.Date)
    )

    # Apply QuantLib calculations
    ttm_y = df.select(pl.col("maturity_date")).to_series().map_elements(_yf, return_dtype=pl.Float64)
    ttm_d = df.select(pl.col("maturity_date")).to_series().map_elements(_dcnt, return_dtype=pl.Int64)

    df = df.with_columns([
        ttm_y.alias("ttm_y"),
        ttm_d.alias("ttm_d"),
    ])

    return df


def _fetch_fiscaldata(
    fetch_as_of: Union[datetime.date, Literal["all"]],
    process_as_of: datetime.date,
    append_mspd_table3: bool = False,
    append_mspd_table5: bool = False,
    append_soma_holdings: bool = False,
    append_free_float: bool = False,
    source_kwargs={},
) -> pl.DataFrame:
    otrs: Iterable[Union[int, str]] = source_kwargs.get("otrs", (2, 3, 5, 7, 10, 20, 30))
    term_strings = _as_term_strings(otrs)

    df = _fetch_auctions_raw_fiscaldata(fetch_as_of, term_strings)
    if df.height == 0:
        return pl.DataFrame()

    df = df.sort(["cusip", "issue_date"]).unique(subset=["cusip"], keep="first")
    if fetch_as_of != "all":
        df = df.filter(pl.col("maturity_date") > process_as_of)
        df = df.with_columns(
            (pl.col("issue_date").rank(method="ordinal", descending=True).over("original_security_term") - 1).cast(pl.Int64).alias("rank")
        )
        df = _add_ttm_columns_with_quantlib(df, process_as_of)

    df = df.sort(["original_security_term", "issue_date", "cusip"], descending=[False, True, False])
    df = _add_label_column(df)
    keep = [
        c
        for c in ["record_date", "label", "cusip", "rank", "original_security_term", "auction_date", "issue_date", "maturity_date", "ttm_y", "int_rate"]
        if c in df.columns
    ]
    df = df.select(keep)
    df = df.rename({"original_security_term": "oi", "int_rate": "cpn", "ttm_y": "ttm"})
    df = df.sort("maturity_date")

    if append_free_float:
        append_mspd_table5 = True
        append_soma_holdings = True

    if append_mspd_table3:
        ql_date = ql.Date(fetch_as_of.day, fetch_as_of.month, fetch_as_of.year)
        to_fetch: ql.Date = ql.NullCalendar().endOfMonth(ql_date - ql.Period("1m"))
        mspd_table3_url = f"https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_3_market?filter=record_date:eq:{datetime.date(to_fetch.year(), to_fetch.month(), to_fetch.dayOfMonth()).strftime("%Y-%m-%d")}&page[size]=10000"
        mspd_table3_df = pl.DataFrame(requests.get(mspd_table3_url).json()["data"])
        mspd_table3_df = mspd_table3_df.filter(pl.col("security_class1_desc").is_in(["Notes", "Bonds"]))
        to_numeric = ["issued_amt", "outstanding_amt"]
        for n in to_numeric:
            mspd_table3_df = mspd_table3_df.with_columns(
                pl.col(n).cast(pl.Float64, strict=False).alias(n)
            )

        mspd_table3_df = mspd_table3_df.rename({"security_class2_desc": "cusip"})
        mspd_table3_df = mspd_table3_df.select(["cusip"] + to_numeric)
        mspd_table3_df = mspd_table3_df.unique(subset=["cusip"], keep="first")
        df = df.join(mspd_table3_df, on="cusip", how="full", coalesce=True)

    if append_mspd_table5:
        ql_date = ql.Date(fetch_as_of.day, fetch_as_of.month, fetch_as_of.year)
        to_fetch: ql.Date = ql.NullCalendar().endOfMonth(ql_date - ql.Period("1m"))

        mspd_table5_url = f"https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_5?filter=record_date:eq:{datetime.date(to_fetch.year(), to_fetch.month(), to_fetch.dayOfMonth()).strftime("%Y-%m-%d")}&page[size]=10000"
        mspd_table5_df = pl.DataFrame(requests.get(mspd_table5_url).json()["data"])
        mspd_table5_df = mspd_table5_df.filter(pl.col("security_class1_desc").is_in(["Treasury Bonds", "Treasury Notes"]))
        to_numeric = ["outstanding_amt", "portion_unstripped_amt", "portion_stripped_amt", "reconstituted_amt"]
        for n in to_numeric:
            mspd_table5_df = mspd_table5_df.with_columns(
                (pl.col(n).cast(pl.Float64, strict=False) * 1000).alias(n)
            )

        mspd_table5_df = mspd_table5_df.drop("cusip").rename({"security_class2_desc": "cusip"})
        mspd_table5_df = mspd_table5_df.select(["cusip"] + to_numeric)
        mspd_table5_df = mspd_table5_df.unique(subset=["cusip"], keep="first")
        df = df.join(mspd_table5_df, on="cusip", how="full", coalesce=True)

    if append_soma_holdings:
        valid_soma_holding_dates_reponse = requests.get("https://markets.newyorkfed.org/api/soma/asofdates/list.json").json()
        valid_soma_dates_dt = [datetime.datetime.strptime(dt_string, "%Y-%m-%d").date() for dt_string in valid_soma_holding_dates_reponse["soma"]["asOfDates"]]
        valid_closest_date = min(
            (valid_date for valid_date in valid_soma_dates_dt if valid_date <= fetch_as_of),
            key=lambda valid_date: abs(fetch_as_of - valid_date),
        )
        soma_url = f'https://markets.newyorkfed.org/api/soma/tsy/get/asof/{valid_closest_date.strftime("%Y-%m-%d")}.json'
        soma_df = pl.DataFrame(requests.get(soma_url).json()["soma"]["holdings"])
        soma_df = soma_df.filter(pl.col("securityType") == "NotesBonds")
        to_numeric = ["parValue", "percentOutstanding"]
        for n in to_numeric:
            soma_df = soma_df.with_columns(
                pl.col(n).cast(pl.Float64, strict=False).alias(n)
            )

        soma_df = soma_df.with_columns([
            (pl.col("parValue") / pl.col("percentOutstanding")).alias("outstanding_amt_backed_out_from_soma"),
            (pl.col("percentOutstanding") * 100).alias("percentOutstanding"),
        ])
        soma_df = soma_df.select(["cusip"] + to_numeric + ["outstanding_amt_backed_out_from_soma"])
        soma_df = soma_df.rename({"parValue": "soma_holdings", "percentOutstanding": "soma_holdings_of_pct_outstanding"})
        df = df.join(soma_df, on="cusip", how="full", coalesce=True)

    if append_free_float:
        fill_cols = ["outstanding_amt", "soma_holdings", "portion_stripped_amt"]
        df = df.with_columns([
            pl.col(c).fill_null(0).alias(c) for c in fill_cols
        ])
        df = df.with_columns(
            (pl.col("outstanding_amt") - pl.col("soma_holdings") - pl.col("portion_stripped_amt")).alias("free_float")
        )

    return df


def update_reference_data(
    source: Literal["fiscaldata"],
    source_kwargs={},
    force_refresh: bool = False,
) -> pl.DataFrame:
    as_of = datetime.date.today()
    cache_dir = _resolve_ust_cache_dir(source)

    today_dir = cache_dir / as_of.strftime("%Y-%m-%d")
    today_dir.mkdir(parents=True, exist_ok=True)

    file_path = today_dir / f"{as_of.strftime('%Y-%m-%d')}.parquet"

    if not force_refresh and file_path.exists():
        try:
            return pl.read_parquet(file_path)
        except Exception:
            pass

    if source == "fiscaldata":
        df = _fetch_fiscaldata(fetch_as_of="all", process_as_of=as_of, source_kwargs=source_kwargs)
    else:
        raise NotImplementedError(f"Source '{source}' is not implemented.")

    try:
        df.write_parquet(file_path, compression="zstd")
    except Exception:
        pass

    _cleanup_old_cache_dirs(cache_dir, keep_last=3)

    return df

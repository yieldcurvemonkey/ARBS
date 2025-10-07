import datetime
import math
import os
from pathlib import Path
from typing import Iterable, List, Literal, Optional, Union

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
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

    dc = ql.ActualActual(ql.ActualActual.ISMA)
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

    return df.sort_values(by="maturity_date")


def update_reference_data(
    source: Literal["fiscaldata"],
    source_kwargs={},
    force_refresh: bool = False,
) -> pd.DataFrame:
    as_of = datetime.date.today()
    cache_dir = _resolve_ust_cache_dir(source)

    today_dir = cache_dir / as_of.strftime("%Y-%m-%d")
    today_dir.mkdir(parents=True, exist_ok=True)

    file_path = today_dir / f"{as_of.strftime('%Y-%m-%d')}.parquet"

    if not force_refresh and file_path.exists():
        try:
            return pd.read_parquet(file_path)
        except Exception:
            pass

    if source == "fiscaldata":
        df = _fetch_fiscaldata(fetch_as_of="all", process_as_of=as_of, source_kwargs=source_kwargs)
    else:
        raise NotImplementedError(f"Source '{source}' is not implemented.")

    try:
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, file_path, compression="zstd")
    except Exception:
        pass

    _cleanup_old_cache_dirs(cache_dir, keep_last=3)

    return df

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

from MDP.FixedRateBonds.reference_data_cache.fiscaldata import _fetch_fiscaldata
from MDP.FixedRateBonds.reference_data_cache.treasurydirect import fetch_ust_refdata_treasurydirect


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


def update_reference_data(
    source: Literal["fiscaldata", "treasurydirect"],
    source_kwargs={},
    force_refresh: bool = False,
) -> pd.DataFrame:

    cache_dir = _resolve_ust_cache_dir(source)

    if source == "fiscaldata":

        def _last_ust_govt_business_day(d: datetime.date) -> datetime.date:
            cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
            qd = ql.Date(d.day, d.month, d.year)
            qd_adj = cal.adjust(qd, ql.Preceding)
            return datetime.date(qd_adj.year(), qd_adj.month(), qd_adj.dayOfMonth())

        as_of = _last_ust_govt_business_day(datetime.date.today())

        today_dir = cache_dir / as_of.strftime("%Y-%m-%d")
        today_dir.mkdir(parents=True, exist_ok=True)

        file_path = today_dir / f"{as_of.strftime('%Y-%m-%d')}.parquet"

        if not force_refresh and file_path.exists():
            try:
                return pd.read_parquet(file_path)
            except Exception:
                pass

        df = _fetch_fiscaldata(
            fetch_as_of="all",
            process_as_of=as_of,
            source_kwargs=source_kwargs,
            append_mspd_table3=False,
            append_mspd_table5=False,
            append_free_float=False,
            append_soma_holdings=False,
        )
    elif source == "treasurydirect":
        df = fetch_ust_refdata_treasurydirect(
            as_of_date=source_kwargs["as_of"],
            max_workers=12,
        )
    else:
        raise NotImplementedError(f"Source '{source}' is not implemented.")

    try:
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, file_path, compression="zstd")
    except Exception:
        pass

    _cleanup_old_cache_dirs(cache_dir, keep_last=3)

    return df

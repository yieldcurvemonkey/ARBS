"""On-disk store for scraped ETF holdings: one parquet per (ticker, year), plus a manifest.

Why a manifest and not just the data
------------------------------------
Resume has to distinguish three outcomes for a (ticker, requested date):

* a file came back and was written,
* the endpoint answered but had **no file** for that date (a weekend, a holiday, a date
  before inception), and
* nothing was tried yet.

Only the third should be re-fetched. Without a manifest the second is indistinguishable
from the third, so every resumed run re-requests every non-trading day for the whole
history -- thousands of requests that can only ever return nothing, on an endpoint with
no published rate limit. The manifest records the attempt, so a re-run is cheap and the
run's own coverage is auditable without re-reading the data.

The manifest also carries the content hash. The endpoint re-serves the previous
document on some non-trading days, and the *only* way to see that from the outside is
that the bytes repeat.
"""

from __future__ import annotations

import datetime
import pathlib
from typing import Iterable, Optional, Sequence

import pandas as pd

from utils.storage_paths import repo_store

#: Named distinctly from ``reference_data_cache``: a prior session ran
#: ``git checkout -- .../reference_data_cache`` intending to drop cached parquet and
#: reverted the SOURCE that lives beside it. Nothing importable lives under this path.
CACHE_ENV = "ARBS_ETF_HOLDINGS_DIR"


def cache_root() -> pathlib.Path:
    root = repo_store("MDP", "ETFHoldings", "etf_holdings_cache", env_var=CACHE_ENV)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ticker_dir(ticker: str) -> pathlib.Path:
    d = cache_root() / ticker.upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _year_path(ticker: str, year: int) -> pathlib.Path:
    return _ticker_dir(ticker) / f"{ticker.upper()}_{year}.parquet"


def _manifest_path(ticker: str) -> pathlib.Path:
    return _ticker_dir(ticker) / "_manifest.parquet"


# ------------------------------------------------------------------ manifest

MANIFEST_COLS = ["requested_date", "as_of", "content_sha1", "n_rows", "shares_outstanding", "fetched_at"]


def read_manifest(ticker: str) -> pd.DataFrame:
    p = _manifest_path(ticker)
    if not p.exists():
        return pd.DataFrame(columns=MANIFEST_COLS)
    return pd.read_parquet(p)


def attempted_dates(ticker: str) -> set[datetime.date]:
    m = read_manifest(ticker)
    if m.empty:
        return set()
    return {d.date() for d in pd.to_datetime(m["requested_date"])}


def write_manifest(ticker: str, rows: Sequence[dict]) -> None:
    if not rows:
        return
    new = pd.DataFrame(rows)
    old = read_manifest(ticker)
    both = pd.concat([old, new], ignore_index=True) if not old.empty else new
    both["requested_date"] = pd.to_datetime(both["requested_date"])
    both = both.drop_duplicates(subset=["requested_date"], keep="last").sort_values("requested_date")
    both.to_parquet(_manifest_path(ticker), index=False)


# ------------------------------------------------------------------ holdings

def append_holdings(ticker: str, frames: Iterable[pd.DataFrame]) -> int:
    """Merge new holdings rows into the per-year parquets, keyed on the DOCUMENT date.

    Keyed on ``date`` (the as-of the file claims) and ``CUSIP``, last write wins. A
    re-fetch of a date already stored is therefore idempotent, and a stale document
    re-served under a different request date collapses onto the day it actually
    describes instead of inventing a second observation of it.
    """
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return 0
    new = pd.concat(frames, ignore_index=True)
    new["date"] = pd.to_datetime(new["date"])

    written = 0
    for year, chunk in new.groupby(new["date"].dt.year):
        p = _year_path(ticker, int(year))
        if p.exists():
            chunk = pd.concat([pd.read_parquet(p), chunk], ignore_index=True)
        key = ["date", "CUSIP"] if "CUSIP" in chunk.columns else ["date", "Name"]
        chunk = chunk.drop_duplicates(subset=key, keep="last").sort_values(["date"] + key[1:])
        chunk.to_parquet(p, index=False)
        written += len(chunk)
    return written


def load(
    tickers: str | Sequence[str],
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
) -> pd.DataFrame:
    """Read the stored holdings panel for one or more tickers."""
    if isinstance(tickers, str):
        tickers = [tickers]
    out = []
    for t in tickers:
        d = cache_root() / t.upper()
        if not d.exists():
            continue
        for p in sorted(d.glob(f"{t.upper()}_*.parquet")):
            df = pd.read_parquet(p)
            out.append(df)
    if not out:
        return pd.DataFrame()
    panel = pd.concat(out, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    if start is not None:
        panel = panel[panel["date"] >= pd.Timestamp(start)]
    if end is not None:
        panel = panel[panel["date"] <= pd.Timestamp(end)]
    return panel.sort_values(["ticker", "date"]).reset_index(drop=True)


def coverage(ticker: str) -> pd.DataFrame:
    """Per-year row and date counts -- the cheap way to see a hole before trusting a panel."""
    d = cache_root() / ticker.upper()
    if not d.exists():
        return pd.DataFrame()
    rows = []
    for p in sorted(d.glob(f"{ticker.upper()}_*.parquet")):
        df = pd.read_parquet(p, columns=["date", "CUSIP"])
        rows.append({
            "year": int(p.stem.split("_")[-1]),
            "dates": df["date"].nunique(),
            "rows": len(df),
            "first": df["date"].min(),
            "last": df["date"].max(),
        })
    return pd.DataFrame(rows)

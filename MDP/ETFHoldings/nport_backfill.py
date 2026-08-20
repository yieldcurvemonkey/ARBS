"""Backfill the public N-PORT holdings history for the funds whose issuers serve none.

    python -m MDP.ETFHoldings.nport_backfill --tickers SPTL,VGLT,EDV,ZROZ --verify

Why this writes to its OWN store rather than into ``MDP.ETFHoldings.store``
---------------------------------------------------------------------------
``store.append_holdings`` dedupes on ``(date, CUSIP)``, last write wins, with no source
discriminator. N-PORT rows and issuer-snapshot rows for the same fund would therefore
overwrite one another on any shared date -- and they *will* share dates, because both are
month-end publications. That would be bad enough on its own, but the two sources are not
interchangeable in three measured ways, every one of which a downstream reader has to
decide about deliberately:

* **Market value basis.** N-PORT ``valUSD`` is CLEAN; the iShares daily file is DIRTY
  (+0.15 to +0.54 price points of accrued). Accrued varies with coupon, so the difference
  does not cancel in a cross-sectional weight.
* **Dating.** An N-PORT report stamped D carries the book of D-1 business day, valued at
  D's prices. Same-date joins misallocate ~2% of the book onto the rebalance names.
* **Publication lag.** The issuer files are public within a day; N-PORT is public 53-62
  days after its ``repPdDate``.

Silently merging them into one parquet keyed on ``(date, CUSIP)`` would erase all three
distinctions and leave a panel that looks complete. So the N-PORT history lives beside
the snapshot store, under ``_nport/``, and the panel builder merges it on purpose.

TLT is fetched only when ``--include-validation`` is passed, and even then it is written
to ``_nport/`` where it cannot touch the daily iShares store.
"""

from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from MDP.ETFHoldings import store  # noqa: E402
from MDP.ETFHoldings.providers import nport  # noqa: E402


def nport_root() -> pathlib.Path:
    d = store.cache_root() / "_nport"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(ticker: str) -> pathlib.Path:
    return nport_root() / f"{ticker.upper()}_nport.parquet"


def load(tickers) -> pd.DataFrame:
    """Read the stored N-PORT panel. ``date`` is ``repPdDate``; see ``book_date``."""
    if isinstance(tickers, str):
        tickers = [tickers]
    out = []
    for t in tickers:
        p = path_for(t)
        if p.exists():
            out.append(pd.read_parquet(p))
    if not out:
        return pd.DataFrame()
    df = pd.concat(out, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["ticker", "date", "CUSIP"]).reset_index(drop=True)


def backfill(ticker: str, *, force: bool = False) -> dict:
    p = path_for(ticker)
    have: set = set()
    if p.exists() and not force:
        old = pd.read_parquet(p, columns=["date"])
        have = {pd.Timestamp(d).date() for d in pd.to_datetime(old["date"]).unique()}

    fl = nport.list_filings(ticker)
    if fl.empty:
        print(f"[{ticker}] NO N-PORT filings found", flush=True)
        return {"ticker": ticker, "filings": 0, "periods": 0, "rows": 0, "skipped": 0}

    print(f"[{ticker}] {len(fl)} N-PORT filings {fl.filing_date.min().date()} .. "
          f"{fl.filing_date.max().date()}   already stored: {len(have)} periods", flush=True)

    frames, n_skip = [], 0
    for hf in nport.iter_fund(ticker, filings=fl):
        if hf.as_of in have:
            n_skip += 1
            continue
        frames.append(hf.frame)
        print(f"    {hf.as_of}  rows={len(hf.frame):>4}  "
              f"filed={pd.Timestamp(hf.frame['filing_date'].iloc[0]).date()}  "
              f"lag={(pd.Timestamp(hf.frame['filing_date'].iloc[0]).date() - hf.as_of).days}d",
              flush=True)

    if not frames:
        print(f"[{ticker}] nothing new ({n_skip} periods already stored)", flush=True)
        return {"ticker": ticker, "filings": len(fl), "periods": 0, "rows": 0, "skipped": n_skip}

    new = pd.concat(frames, ignore_index=True)
    new = nport.align_to_daily(new)
    if p.exists() and not force:
        new = pd.concat([pd.read_parquet(p), new], ignore_index=True)
    new["date"] = pd.to_datetime(new["date"])
    # An amendment supersedes: keep the LATEST filing for a (date, CUSIP).
    new = (new.sort_values(["date", "CUSIP", "filing_date"])
              .drop_duplicates(subset=["date", "CUSIP"], keep="last")
              .sort_values(["date", "CUSIP"]).reset_index(drop=True))
    new.to_parquet(p, index=False)
    return {"ticker": ticker, "filings": len(fl),
            "periods": int(new["date"].nunique()), "rows": len(new), "skipped": n_skip}


def coverage(ticker: str) -> pd.DataFrame:
    p = path_for(ticker)
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_parquet(p)
    d["date"] = pd.to_datetime(d["date"])
    d["filing_date"] = pd.to_datetime(d["filing_date"])
    g = d.groupby("date").agg(
        rows=("CUSIP", "size"),
        bonds=("CUSIP", lambda s: s.notna().sum()),
        fixed_income=("Asset Class", lambda s: (s == "Fixed Income").sum()),
        weight_sum=("Weight (%)", "sum"),
        filed=("filing_date", "first"),
        book_date=("book_date", "first"),
    ).reset_index()
    g["lag_days"] = (g["filed"] - g["date"]).dt.days
    return g


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", default=",".join(nport.BACKFILLABLE))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--include-validation", action="store_true",
                    help="also fetch TLT, whose daily iShares history already covers it")
    a = ap.parse_args(argv)

    tks = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    if not a.include_validation:
        dropped = [t for t in tks if t in nport.VALIDATION_ONLY]
        tks = [t for t in tks if t not in nport.VALIDATION_ONLY]
        for t in dropped:
            print(f"[{t}] skipped: validation-only (pass --include-validation to fetch)")

    print(f"nport store: {nport_root()}")
    print(f"EDGAR User-Agent: {nport.contact()}")
    if "example.com" in nport.contact():
        print("  WARNING: placeholder contact. Set ARBS_EDGAR_CONTACT to a real address.")

    res = [backfill(t, force=a.force) for t in tks]
    print("\n=== run summary ===")
    print(pd.DataFrame(res).to_string(index=False))

    if a.verify:
        print("\n=== coverage (re-read from disk) ===")
        for t in tks:
            cov = coverage(t)
            print(f"\n{t}:")
            print("EMPTY" if cov.empty else cov.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

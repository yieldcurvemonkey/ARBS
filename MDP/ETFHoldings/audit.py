"""Coverage audit for the holdings store: which business days actually have a document.

Why this file exists
--------------------
A 127-business-day hole in TLT's 2017 survived a whole study. It survived because the
statistic that would have shown it was a *by-year median over all panel dates*, which
averages a missing day in as a zero and reports the year as "held 0.0% of the board" --
indistinguishable, to a reader, from "held nothing". Absence has to be counted, not
averaged, and it has to be counted against a **grid** rather than against the rows that
happen to be present. A count of what you have can never reveal what you do not have.

The four states of a (ticker, business day)
-------------------------------------------
The store was built to keep these apart and the audit reports them apart:

``never_attempted``  no manifest row. Plain resume will fetch it.
``no_file``          a manifest row with ``as_of`` NaT: the endpoint answered 200 and
                     the body was not a holdings document. **Resume SKIPS these** --
                     ``attempted_dates()`` counts them as done -- so recovering one
                     needs ``--force``.
``stale``            a document came back whose own as-of is a *different* day. It
                     contributes no new stored date; the day it was requested for is
                     still uncovered.
``got_doc``          a document whose as-of is the day it was requested for.

Only the last puts a distinct date into the year parquets, so ``stored_dates`` -- not
the manifest's success count -- is the number that means "days I can actually use".

Run it
------
    python -m MDP.ETFHoldings.audit                    # every ticker in the store
    python -m MDP.ETFHoldings.audit --tickers TLT      # one
    python -m MDP.ETFHoldings.audit --gaps             # list every run of missing days
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from typing import Iterable, List, Optional, Sequence, Tuple

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from MDP.ETFHoldings import store  # noqa: E402
from MDP.ETFHoldings.universe import REGISTRY  # noqa: E402

#: Runs of consecutive missing business days at least this long are called out. Below
#: this a hole is a holiday cluster or a publication hiccup; above it, the fund appears
#: to have stopped existing for a week, which is always worth a look.
GAP_FLAG = 5


def business_days(start: datetime.date, end: datetime.date) -> List[datetime.date]:
    """The same grid ``backfill.py`` requests on -- QuantLib's UST government calendar.

    Audit and backfill MUST share this. An audit on a different calendar reports the
    other calendar's holidays as holes and sends a repair run at days that can never
    have a file.
    """
    import QuantLib as ql

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    return [
        ts.date()
        for ts in pd.date_range(start, end, freq="D")
        if cal.isBusinessDay(ql.Date(ts.day, ts.month, ts.year))
    ]


def _runs(days: Sequence[datetime.date], grid: Sequence[datetime.date]) -> List[Tuple[datetime.date, datetime.date, int]]:
    """Group ``days`` into runs that are consecutive **on the business-day grid**.

    Consecutive-in-calendar-days would break every run at a weekend and report a
    six-month hole as 26 separate five-day ones.
    """
    pos = {d: i for i, d in enumerate(grid)}
    idx = sorted(pos[d] for d in days if d in pos)
    out: List[Tuple[datetime.date, datetime.date, int]] = []
    if not idx:
        return out
    lo = prev = idx[0]
    for i in idx[1:]:
        if i == prev + 1:
            prev = i
            continue
        out.append((grid[lo], grid[prev], prev - lo + 1))
        lo = prev = i
    out.append((grid[lo], grid[prev], prev - lo + 1))
    return out


def audit_ticker(
    ticker: str,
    *,
    end: Optional[datetime.date] = None,
) -> dict:
    """Per-year coverage for one ticker, measured against the business-day grid."""
    ticker = ticker.upper()
    m = store.read_manifest(ticker)
    spec_inception = REGISTRY[ticker].inception if ticker in REGISTRY else None

    if m.empty:
        return {"ticker": ticker, "table": pd.DataFrame(), "gaps": [], "empty": True,
                "lo": None, "hi": None, "dup_sha": pd.DataFrame()}

    m = m.copy()
    m["requested_date"] = pd.to_datetime(m["requested_date"])
    m["as_of"] = pd.to_datetime(m["as_of"])

    lo = m["requested_date"].min().date()
    hi = m["requested_date"].max().date()
    if end is not None:
        hi = min(hi, end)
    if spec_inception is not None:
        lo = max(lo, spec_inception)

    grid = business_days(lo, hi)
    grid_set = set(grid)

    req = m.set_index(m["requested_date"].dt.date)
    attempted = set(req.index)
    ok = req["as_of"].notna()
    got = set(req.index[ok])
    nofile = set(req.index[~ok])
    stale = {
        d for d in got
        if req.loc[d, "as_of"].date() != d
    } if len(got) else set()

    # The document dates actually on disk -- the only ones a panel can use.
    stored: set[datetime.date] = set()
    d = store.cache_root() / ticker
    if d.exists():
        for p in sorted(d.glob(f"{ticker}_*.parquet")):
            s = pd.read_parquet(p, columns=["date"])["date"]
            stored |= set(pd.to_datetime(s).dt.date)

    covered = grid_set & stored           # business days with a usable document
    missing = sorted(grid_set - covered)

    rows = []
    for yr in sorted({d.year for d in grid}):
        g = [d for d in grid if d.year == yr]
        gs = set(g)
        rows.append({
            "year": yr,
            "bdays": len(g),
            "attempted": len(gs & attempted),
            "got_doc": len(gs & got),
            "no_file": len(gs & nofile),
            "stale": len(gs & stale),
            "never_att": len(gs - attempted),
            "stored": len(gs & stored),
            "missing": len(gs - covered),
            "pct": round(100.0 * len(gs & stored) / max(1, len(g)), 1),
        })
    table = pd.DataFrame(rows)

    gaps = [(a, b, n) for a, b, n in _runs(missing, grid) if n > GAP_FLAG]

    # A content hash on more than one requested date == the same document served twice.
    dup = pd.DataFrame()
    sha = m.loc[m["content_sha1"].notna(), ["requested_date", "as_of", "content_sha1", "n_rows"]]
    if not sha.empty:
        c = sha.groupby("content_sha1").size()
        rep = c[c > 1]
        if len(rep):
            dup = sha[sha["content_sha1"].isin(rep.index)].sort_values(["content_sha1", "requested_date"])

    return {"ticker": ticker, "table": table, "gaps": gaps, "empty": False,
            "lo": lo, "hi": hi, "missing": missing, "dup_sha": dup,
            "n_missing": len(missing), "n_never": len(set(grid) - attempted),
            "n_nofile": len(grid_set & nofile), "n_stale": len(grid_set & stale)}


def is_backfillable(ticker: str) -> bool:
    """Does a business-day grid mean anything for this fund?

    Only for an issuer that serves a file for a date you name. SSGA and Vanguard serve
    exactly one document -- whatever is current -- so their store holds one snapshot per
    run and a grid audit would report ~100% of history "missing" for a fund that is
    behaving exactly as designed. Absence has to be measured against what the endpoint
    can actually be asked for.
    """
    sp = REGISTRY.get(ticker.upper())
    return sp is None or getattr(sp, "history", "dated") == "dated"


def store_tickers(*, backfillable_only: bool = True) -> List[str]:
    root = store.cache_root()
    out = sorted(p.name for p in root.iterdir()
                 if p.is_dir() and (p / "_manifest.parquet").exists())
    if backfillable_only:
        out = [t for t in out if is_backfillable(t)]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", default=None, help="comma list; default every ticker in the store")
    ap.add_argument("--end", default=None, help="clip the grid at this date (YYYY-MM-DD)")
    ap.add_argument("--gaps", action="store_true", help="list every flagged gap run")
    ap.add_argument("--dups", action="store_true", help="list repeated content hashes")
    a = ap.parse_args(argv)

    end = datetime.date.fromisoformat(a.end) if a.end else None
    tickers = ([t.strip().upper() for t in a.tickers.split(",") if t.strip()]
               if a.tickers else store_tickers())

    print(f"cache root: {store.cache_root()}")
    print(f"tickers   : {', '.join(tickers)}\n")

    summary = []
    for t in tickers:
        r = audit_ticker(t, end=end)
        if r["empty"]:
            print(f"=== {t}: NO MANIFEST ===\n")
            continue
        print(f"=== {t}   {r['lo']} .. {r['hi']} ===")
        print(r["table"].to_string(index=False))
        tot = r["table"][["bdays", "attempted", "got_doc", "no_file", "stale", "never_att", "stored", "missing"]].sum()
        print(f"  TOTAL bdays={tot['bdays']} stored={tot['stored']} missing={tot['missing']} "
              f"(never_attempted={tot['never_att']}, no_file={tot['no_file']}, stale={tot['stale']})")
        if r["gaps"]:
            print(f"  !! {len(r['gaps'])} run(s) of >{GAP_FLAG} consecutive missing business days:")
            for x, y, n in r["gaps"]:
                print(f"       {x} .. {y}   {n} bdays")
        else:
            print(f"  no run of missing business days longer than {GAP_FLAG}")
        if a.dups and not r["dup_sha"].empty:
            print(f"  repeated content hashes ({r['dup_sha']['content_sha1'].nunique()} docs):")
            print(r["dup_sha"].to_string(index=False))
        if a.gaps and r["missing"]:
            print(f"  all {len(r['missing'])} missing business days:")
            for x, y, n in _runs(r["missing"], business_days(r["lo"], r["hi"])):
                print(f"       {x} .. {y}   {n}")
        print()
        summary.append({
            "ticker": t, "from": r["lo"], "to": r["hi"],
            "bdays": int(tot["bdays"]), "stored": int(tot["stored"]),
            "missing": int(tot["missing"]), "never_att": int(tot["never_att"]),
            "no_file": int(tot["no_file"]), "stale": int(tot["stale"]),
            "gap_runs": len(r["gaps"]),
            "pct": round(100.0 * tot["stored"] / max(1, tot["bdays"]), 2),
        })

    if summary:
        print("=== SUMMARY (all tickers) ===")
        print(pd.DataFrame(summary).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

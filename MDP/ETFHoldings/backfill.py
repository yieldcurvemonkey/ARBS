"""Resumable daily-holdings backfill. Run it as a script; it is meant to be left alone.

    python -m MDP.ETFHoldings.backfill --plan all --verify

Two lessons are built into this file rather than written above it
-----------------------------------------------------------------
**A refusal is not a data point.** The first version used six threads, no pacing, and a
provider that mapped every non-200 to "no file for this date". It fetched 143 documents,
was served ``403 Access Denied`` by an Akamai WAF for the next 2,515, wrote all 2,515 as
absences, and **exited 0**. The manifest it produced was one that resume would have
honoured -- so the failure would have survived the re-run that was meant to catch it.
The provider now raises :class:`~MDP.ETFHoldings.providers.ishares.Blocked` on a refusal,
and this runner records only what a 200 actually said.

**The WAF counts per IP, so use more than one.** The block was IP-level: plain ``curl``
from the same machine was refused identically while every one of the eight NordVPN US
exits the repo's Barchart fetchers already use returned 200. Requests therefore go
through :class:`~MDP.ETFHoldings.proxy_pool.ProxyPool`, which rotates exits, rate-limits
each one separately, and benches an exit that is refused instead of retrying into it.
Aggregate throughput is ``n_exits x per_exit_rate``; the per-IP rate stays well under
what tripped the block.

**A snapshot is not a backfill, and the runner must know the difference.** iShares serves
a file for any date you name. SSGA serves one workbook -- the current one -- and Vanguard
accepts an ``asOfDate`` parameter and ignores it, answering 200 with a different date in
the body. Looping either over a decade of business days would make ~2,500 requests that
all return the same document, and would write 2,500 manifest rows pointing at one
``as_of``. :func:`backfill_ticker` therefore REFUSES a fund whose spec says
``history="current_only"`` and :func:`snapshot_ticker` takes it instead: one request per
run, keyed on the document's own date, so a panel accumulates forward one day at a time.

Plans
-----
``--plan`` names a prioritised set, so the funds the study actually needs land first and
an interrupted run has produced the useful half rather than a uniform tenth of
everything. ``--plan multi_issuer`` is the snapshot set; it is cheap (three requests) and
is the one that wants running on a daily schedule.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from MDP.ETFHoldings import store  # noqa: E402
from MDP.ETFHoldings.proxy_pool import ProxyPool  # noqa: E402
from MDP.ETFHoldings.universe import REGISTRY, provider_module, spec  # noqa: E402

#: (ticker, start) in priority order. TLT and TLH get the full history because the
#: long-end micro-RV study is the point and ten years doubles its statistical power;
#: everything else gets the five years the study window needs.
#:
#: The start date in ``multi_issuer`` is inert -- those three funds are ``current_only``
#: and get one request each -- but it is carried so every plan has one shape.
PLANS: dict[str, list[tuple[str, str]]] = {
    "long_end": [("TLT", "2016-01-01"), ("TLH", "2016-01-01"), ("GOVZ", "2020-09-22")],
    "ladder": [("GOVT", "2018-01-01"), ("IEF", "2018-01-01"),
               ("IEI", "2018-01-01"), ("SHY", "2018-01-01")],
    "term": [("IBTH", "2020-03-03"), ("IBTG", "2020-03-03"), ("IBTI", "2020-03-03"),
             ("IBTJ", "2020-03-03"), ("IBTK", "2021-06-08")],
    "multi_issuer": [("SPTL", "2026-08-20"), ("VGLT", "2026-08-20"), ("EDV", "2026-08-20")],
}
PLANS["all"] = PLANS["long_end"] + PLANS["ladder"] + PLANS["term"] + PLANS["multi_issuer"]

_print_lock = threading.Lock()


def _say(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def business_days(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    """US Treasury market business days -- QuantLib's own calendar, so the request grid
    matches the one every other ARBS panel is built on."""
    import QuantLib as ql

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    return [
        ts.date() for ts in pd.date_range(start, end, freq="D")
        if cal.isBusinessDay(ql.Date(ts.day, ts.month, ts.year))
    ]


def _manifest_row(d: datetime.date, hf=None) -> dict:
    """One attempt, recorded. ``hf=None`` is a 200 that carried no holdings document.

    Only ever called for an answer. A refusal never reaches here -- that is the whole
    point of the provider raising :class:`Blocked` -- because a manifest row is a claim
    that the endpoint was asked and had nothing, and resume honours that claim.

    ``requested_date`` is ``d``, the date THIS RUN asked for, never ``hf.requested``.
    They coincide for iShares. They do not for a snapshot: the provider defaults its
    ``requested`` to ``date.today()`` while the runner may be keying the attempt on a
    different day, and a manifest whose key disagrees with the resume check silently
    re-requests (or silently skips) every run.
    """
    if hf is None:
        return {"requested_date": pd.Timestamp(d), "as_of": pd.NaT,
                "content_sha1": None, "n_rows": 0,
                "shares_outstanding": float("nan"),
                "fetched_at": pd.Timestamp.utcnow().tz_localize(None)}
    return {"requested_date": pd.Timestamp(d),
            "as_of": pd.Timestamp(hf.as_of),
            "content_sha1": hf.content_sha1, "n_rows": len(hf.frame),
            "shares_outstanding": hf.shares_outstanding,
            "fetched_at": pd.Timestamp.utcnow().tz_localize(None)}


def fetch_one(sp, d: datetime.date, *, pool: ProxyPool, max_attempts: int = 6):
    """Dispatch to the issuer's provider. All three share one call shape by design.

    ``fetch(fund_id, date, *, ticker, pool, max_attempts)``: for iShares the second
    argument is the date requested on the wire; for the current-only issuers it is
    bookkeeping the provider compares against the document and warns about. Nothing here
    branches on issuer, so adding a fourth is a registry entry and a module, not an
    edit to the runner.
    """
    mod = provider_module(sp)
    return mod.fetch(sp.fund_id, d, ticker=sp.ticker, pool=pool, max_attempts=max_attempts)


def snapshot_ticker(
    ticker: str,
    *,
    pool: ProxyPool,
    force: bool = False,
    on_date: Optional[datetime.date] = None,
) -> dict:
    """One request for a fund whose issuer publishes only its current holdings.

    Keyed on the document's own ``as_of``, so re-running on a day when the issuer has not
    published anything new re-stores the same rows onto the same date (idempotent, by
    ``store.append_holdings``' ["date", "CUSIP"] dedupe) rather than inventing a second
    observation of it. The content hash is reported against the previous attempt so a
    re-serve is visible: for a month-end publisher like Vanguard, roughly twenty of every
    twenty-one daily runs are re-serves and that is expected, not a fault.

    A refusal is counted and returned; it does NOT write a manifest row.
    """
    sp = spec(ticker)
    if not sp.is_snapshot_only:
        raise ValueError(
            f"{ticker} is history={sp.history!r} -- it has a dated endpoint. Use "
            f"backfill_ticker, which will fetch its real history."
        )
    today = on_date or datetime.date.today()
    man = store.read_manifest(ticker)
    if not force and today in store.attempted_dates(ticker):
        _say(f"[{ticker}] snapshot for {today} already attempted; --force to re-request")
        return {"ticker": ticker, "requested": 0, "stored": 0, "no_file": 0, "blocked": 0}

    t0 = time.time()
    try:
        hf = provider_module(sp).fetch(sp.fund_id, ticker=ticker, pool=pool, max_attempts=6)
    except Exception as exc:
        where = f"   pool: {pool.status()}" if pool is not None else ""
        _say(f"[{ticker}] REFUSED {type(exc).__name__}: {exc}{where}")
        return {"ticker": ticker, "requested": 1, "stored": 0, "no_file": 0, "blocked": 1}

    if hf is None:
        store.write_manifest(ticker, [_manifest_row(today)])
        _say(f"[{ticker}] 200 but no holdings document ({time.time() - t0:.1f}s)")
        return {"ticker": ticker, "requested": 1, "stored": 0, "no_file": 1, "blocked": 0}

    prev = None
    if not man.empty and "content_sha1" in man.columns:
        s = man.dropna(subset=["content_sha1"])
        prev = s.sort_values("requested_date")["content_sha1"].iloc[-1] if not s.empty else None
    store.append_holdings(ticker, [hf.frame])
    store.write_manifest(ticker, [_manifest_row(today, hf)])
    tag = "UNCHANGED re-serve" if prev == hf.content_sha1 else "new document"
    _say(f"[{ticker}] as_of {hf.as_of} ({sp.cadence}, {tag})  {len(hf.frame):,} rows  "
         f"{time.time() - t0:.1f}s")
    return {"ticker": ticker, "requested": 1, "stored": 1, "no_file": 0, "blocked": 0}


def backfill_ticker(
    ticker: str,
    start: datetime.date,
    end: datetime.date,
    *,
    pool: ProxyPool,
    workers: int,
    flush_every: int = 150,
    force: bool = False,
) -> dict:
    sp = spec(ticker)
    if sp.is_snapshot_only:
        raise ValueError(
            f"{ticker} ({sp.issuer}) publishes only its CURRENT holdings -- there is no "
            f"date parameter that works. Looping it over a business-day grid would make "
            f"one request per day for the same document. Use snapshot_ticker()."
        )
    lo = max(start, sp.inception)
    grid = business_days(lo, end)
    done = set() if force else store.attempted_dates(ticker)
    todo = [d for d in grid if d not in done]

    _say(f"[{ticker}] {len(grid):,} business days {lo} .. {end}   "
         f"attempted {len(grid) - len(todo):,}   to fetch {len(todo):,}")
    if not todo:
        return {"ticker": ticker, "requested": 0, "stored": 0, "no_file": 0, "blocked": 0}

    frames: list[pd.DataFrame] = []
    manifest_rows: list[dict] = []
    counts = {"stored": 0, "no_file": 0, "blocked": 0}
    lock = threading.Lock()
    t0 = time.time()

    def _flush_locked() -> None:
        nonlocal frames, manifest_rows
        if frames:
            store.append_holdings(ticker, frames)
        if manifest_rows:
            store.write_manifest(ticker, manifest_rows)
        frames, manifest_rows = [], []

    def one(d: datetime.date):
        return d, fetch_one(sp, d, pool=pool, max_attempts=6)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(one, d) for d in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                d, hf = fut.result()
            except Exception as exc:
                with lock:
                    counts["blocked"] += 1
                if counts["blocked"] % 25 == 1:
                    _say(f"[{ticker}] refused: {exc}   pool: {pool.status()}")
                continue

            with lock:
                if hf is None:
                    counts["no_file"] += 1
                    manifest_rows.append(_manifest_row(d))
                else:
                    counts["stored"] += 1
                    frames.append(hf.frame)
                    manifest_rows.append(_manifest_row(d, hf))

                if len(manifest_rows) >= flush_every:
                    _flush_locked()
                    el = time.time() - t0
                    eta = (len(todo) - i) * el / max(1, i) / 60.0
                    _say(f"[{ticker}] {i:,}/{len(todo):,}  stored={counts['stored']:,} "
                         f"nofile={counts['no_file']:,} refused={counts['blocked']:,}  "
                         f"{i / max(1e-9, el):.2f} req/s  eta {eta:.0f}m  live_exits={pool.n_live}")

    with lock:
        _flush_locked()
    _say(f"[{ticker}] DONE requested={len(todo):,} stored={counts['stored']:,} "
         f"no_file={counts['no_file']:,} refused={counts['blocked']:,}  "
         f"{(time.time() - t0) / 60:.1f}m")
    return {"ticker": ticker, "requested": len(todo), **counts}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", default=None, choices=sorted(PLANS))
    ap.add_argument("--tickers", default=None, help="comma list, overrides --plan")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default=datetime.date.today().isoformat())
    ap.add_argument("--per-exit-rate", type=float, default=0.7,
                    help="requests/second PER EXIT; aggregate is this times the live pool")
    ap.add_argument("--bench-seconds", type=float, default=600.0)
    ap.add_argument("--no-proxy", action="store_true", help="direct only (will be blocked)")
    ap.add_argument("--force", action="store_true", help="re-request dates already attempted")
    ap.add_argument("--verify", action="store_true", help="re-read the store and print coverage")
    a = ap.parse_args(argv)

    end = datetime.date.fromisoformat(a.end)
    if a.tickers:
        jobs = [(t.strip().upper(), datetime.date.fromisoformat(a.start))
                for t in a.tickers.split(",") if t.strip()]
    else:
        jobs = [(t, datetime.date.fromisoformat(s)) for t, s in PLANS[a.plan or "all"]]

    _say(f"cache root: {store.cache_root()}")
    hosts = (None,) if a.no_proxy else None
    pool = ProxyPool(**({"hosts": hosts} if hosts else {}),
                     per_exit_rate=a.per_exit_rate, bench_seconds=a.bench_seconds)
    workers = max(1, len(pool.exits))
    _say(f"proxy pool: {len(pool.exits)} live exits, {a.per_exit_rate} req/s each "
         f"-> ~{a.per_exit_rate * len(pool.exits):.1f} req/s aggregate, {workers} workers")

    results = []
    for t, s in jobs:
        if t not in REGISTRY:
            _say(f"[{t}] not in registry, skipping")
            continue
        sp = spec(t)
        try:
            if sp.is_snapshot_only:
                # One request. The date on the command line is inert for these funds and
                # saying so is cheaper than letting an operator believe --start worked.
                if s > end or a.start != "2021-01-01":
                    _say(f"[{t}] {sp.issuer} publishes CURRENT holdings only; --start/--end "
                         f"are ignored. Taking one snapshot.")
                results.append(snapshot_ticker(t, pool=pool, force=a.force, on_date=end))
            else:
                results.append(backfill_ticker(t, s, end, pool=pool, workers=workers,
                                               force=a.force))
        except Exception as exc:
            _say(f"[{t}] FATAL {type(exc).__name__}: {exc}")
            results.append({"ticker": t, "requested": 0, "stored": 0, "no_file": 0, "blocked": -1})

    _say("\n=== run summary (what this process believes it wrote) ===")
    _say(pd.DataFrame(results).to_string(index=False))
    _say(f"\npool: {pool.status()}")

    if a.verify:
        _say("\n=== store coverage (re-read from disk) ===")
        for t, _ in jobs:
            cov = store.coverage(t)
            _say(f"\n{t}:\n{'EMPTY' if cov.empty else cov.to_string(index=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

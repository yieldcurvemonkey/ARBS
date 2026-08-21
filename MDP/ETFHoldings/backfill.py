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

Plans
-----
``--plan`` names a prioritised set, so the funds the study actually needs land first and
an interrupted run has produced the useful half rather than a uniform tenth of
everything.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from MDP.ETFHoldings import store  # noqa: E402
from MDP.ETFHoldings.providers import ishares  # noqa: E402
from MDP.ETFHoldings.proxy_pool import ProxyPool  # noqa: E402
from MDP.ETFHoldings.universe import REGISTRY, spec  # noqa: E402

#: (ticker, start) in priority order. TLT and TLH get the full history because the
#: long-end micro-RV study is the point and ten years doubles its statistical power;
#: everything else gets the five years the study window needs.
PLANS: dict[str, list[tuple[str, str]]] = {
    "long_end": [("TLT", "2016-01-01"), ("TLH", "2016-01-01"), ("GOVZ", "2020-09-22")],
    "ladder": [("GOVT", "2018-01-01"), ("IEF", "2018-01-01"),
               ("IEI", "2018-01-01"), ("SHY", "2018-01-01")],
    "term": [("IBTH", "2020-03-03"), ("IBTG", "2020-03-03"), ("IBTI", "2020-03-03"),
             ("IBTJ", "2020-03-03"), ("IBTK", "2021-06-08")],
}
PLANS["all"] = PLANS["long_end"] + PLANS["ladder"] + PLANS["term"]

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
        return d, ishares.fetch(sp.fund_id, d, ticker=ticker, pool=pool, max_attempts=6)

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
                    manifest_rows.append({
                        "requested_date": pd.Timestamp(d), "as_of": pd.NaT,
                        "content_sha1": None, "n_rows": 0,
                        "shares_outstanding": float("nan"),
                        "fetched_at": pd.Timestamp.utcnow().tz_localize(None),
                    })
                else:
                    counts["stored"] += 1
                    frames.append(hf.frame)
                    manifest_rows.append({
                        "requested_date": pd.Timestamp(hf.requested),
                        "as_of": pd.Timestamp(hf.as_of),
                        "content_sha1": hf.content_sha1, "n_rows": len(hf.frame),
                        "shares_outstanding": hf.shares_outstanding,
                        "fetched_at": pd.Timestamp.utcnow().tz_localize(None),
                    })

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
        try:
            results.append(backfill_ticker(t, s, end, pool=pool, workers=workers, force=a.force))
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

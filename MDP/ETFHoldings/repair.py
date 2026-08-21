"""Re-request exactly the business days the audit says have no document, and nothing else.

Why not ``backfill.py --force``
-------------------------------
``--force`` re-requests every day in a range. The holes are 293 days scattered across
twelve funds and eleven years; forcing the ranges that contain them is roughly 20,000
requests on an endpoint whose WAF has already blocked this machine once. This runner
takes the audit's ``missing`` list and asks for those days only.

Why re-request days already marked ``no_file``
-----------------------------------------------
Because "no file" is a claim about the endpoint, and the claim was made by a run that
had a documented way of being wrong. Re-asking is what turns "the manifest says these
were empty" into "these were re-requested on this date and were empty again", with
``fetched_at`` as the record. ``store.attempted_dates()`` deliberately treats a
``no_file`` row as done, so a plain resume will never do this.

The four outcomes, and what each one writes
-------------------------------------------
``recovered``   a document whose own as-of IS the requested day. Frame stored, manifest
                row written. This is the only outcome that adds a usable date.
``stale``       a document whose as-of is a DIFFERENT day. Stored under the day it
                actually describes (``append_holdings`` keys on the document date), so
                it is idempotent -- but the requested day is **still missing**. Counted
                separately and never called a recovery.
``empty``       HTTP 200 with a zero-length body. The genuine "no file for this date".
                The manifest row is rewritten so ``fetched_at`` records the re-check.
``refused``     a 403/429/5xx, a transport failure, or -- see below -- an HTML page.
                **Nothing is written.** The day keeps whatever the manifest already said
                and the run exits non-zero so the incompleteness is visible.

The HTML trap this runner guards against
----------------------------------------
Measured 2026-08-20: the legacy ``ishares.com/.../1521942788811.ajax`` route answers
HTTP 200 with ``Content-Type: text/csv`` and 1,523,542 bytes of the fund's **HTML
product page**. ``parse()`` correctly returns ``None`` for it -- which the writer would
record as "no file for this date". Status, content type and parse result all agree, and
all three are wrong. A body that begins with markup is therefore classified as a
refusal here, never as absence. (The shared ``providers/_base.get_with_retries`` has no
such sniff at the time of writing; this guard is local to the repair path.)

Run it
------
    python -m MDP.ETFHoldings.repair --tickers TLT,TLH --dry-run
    python -m MDP.ETFHoldings.repair                       # every ticker in the store
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
from typing import List, Optional

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from MDP.ETFHoldings import store  # noqa: E402
from MDP.ETFHoldings.audit import audit_ticker, is_backfillable, store_tickers  # noqa: E402
from MDP.ETFHoldings.providers import ishares  # noqa: E402
from MDP.ETFHoldings.proxy_pool import ProxyPool  # noqa: E402
from MDP.ETFHoldings.universe import REGISTRY  # noqa: E402

#: Bytes at the head of a body that mean "this is a web page, not a document".
_MARKUP = ("<!doctype", "<html", "<?xml", "<!DOCTYPE")


def _looks_like_markup(text: str) -> bool:
    head = text[:400].lstrip().lower()
    return any(head.startswith(m.lower()) for m in _MARKUP) or "<html" in head


def _fetch_one(
    pid: str,
    d: datetime.date,
    *,
    ticker: str,
    pool: ProxyPool,
    max_attempts: int,
    timeout: float = 45.0,
) -> dict:
    """One day. Returns a classification dict; raises nothing the caller must guess at.

    This keeps its own loop rather than calling ``ishares.fetch`` because the outcome
    the audit needs is finer than that function's return type: it has to tell an empty
    body from a markup body, and ``fetch`` collapses both to ``None``.
    """
    url = ishares.BASE_URL.format(pid=pid, date=d.strftime("%Y%m%d"))
    last: Optional[str] = None

    for _ in range(max_attempts):
        ex = pool.acquire()
        try:
            r = ex.session.get(url, headers=ishares.HEADERS, timeout=timeout, proxies=ex.proxies)
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            pool.report_blocked(ex, transient=True)
            continue

        if r.status_code in ishares.BLOCKED_STATUSES:
            last = f"HTTP {r.status_code}"
            pool.report_blocked(ex)
            continue
        if r.status_code != 200:
            last = f"HTTP {r.status_code}"
            pool.report_blocked(ex)
            continue

        pool.report_ok(ex)
        body = r.text

        if _looks_like_markup(body):
            # A web page wearing text/csv. Not absence -- a refusal.
            return {"kind": "refused", "why": f"markup body ({len(body)} bytes)",
                    "n_bytes": len(body), "hf": None, "exit": ex.label}

        hf = ishares.parse(body, ticker=ticker, requested=d)
        if hf is None:
            return {"kind": "empty", "why": f"200, {len(body)} bytes, no holdings doc",
                    "n_bytes": len(body), "hf": None, "exit": ex.label}
        kind = "recovered" if hf.as_of == d else "stale"
        return {"kind": kind, "why": f"as_of={hf.as_of} rows={len(hf.frame)}",
                "n_bytes": len(body), "hf": hf, "exit": ex.label}

    return {"kind": "refused", "why": f"refused after {max_attempts} attempts ({last})",
            "n_bytes": -1, "hf": None, "exit": None}


def repair_ticker(
    ticker: str,
    *,
    pool: ProxyPool,
    max_attempts: int,
    dry_run: bool,
    limit: Optional[int] = None,
) -> dict:
    ticker = ticker.upper()
    if not is_backfillable(ticker):
        # A snapshot-only issuer has no date parameter to ask with; every "missing" day
        # on its grid is a day the endpoint could never have served.
        print(f"[{ticker}] snapshot-only issuer -- no dated endpoint, nothing to repair")
        return {"ticker": ticker, "targeted": 0}
    a = audit_ticker(ticker)
    if a["empty"]:
        print(f"[{ticker}] no manifest, nothing to repair")
        return {"ticker": ticker, "targeted": 0}

    missing: List[datetime.date] = list(a["missing"])
    if limit:
        missing = missing[:limit]
    pid = REGISTRY[ticker].fund_id

    print(f"[{ticker}] {a['n_missing']} missing business day(s); targeting {len(missing)}")
    if dry_run or not missing:
        return {"ticker": ticker, "targeted": len(missing), "recovered": 0,
                "stale": 0, "empty": 0, "refused": 0}

    counts = {"recovered": 0, "stale": 0, "empty": 0, "refused": 0}
    frames, rows, evidence = [], [], []
    t0 = time.time()

    for i, d in enumerate(missing, 1):
        res = _fetch_one(pid, d, ticker=ticker, pool=pool, max_attempts=max_attempts)
        counts[res["kind"]] += 1
        evidence.append({"ticker": ticker, "date": d, "kind": res["kind"],
                         "n_bytes": res["n_bytes"], "why": res["why"], "exit": res["exit"]})

        if res["kind"] == "refused":
            print(f"[{ticker}] {d} REFUSED: {res['why']}   pool: {pool.status()}")
            continue                       # write NOTHING for a refusal

        hf = res["hf"]
        if hf is not None:
            frames.append(hf.frame)
            rows.append({
                "requested_date": pd.Timestamp(hf.requested), "as_of": pd.Timestamp(hf.as_of),
                "content_sha1": hf.content_sha1, "n_rows": len(hf.frame),
                "shares_outstanding": hf.shares_outstanding,
                "fetched_at": pd.Timestamp.utcnow().tz_localize(None),
            })
        else:                              # confirmed empty -- re-stamp the absence
            rows.append({
                "requested_date": pd.Timestamp(d), "as_of": pd.NaT,
                "content_sha1": None, "n_rows": 0, "shares_outstanding": float("nan"),
                "fetched_at": pd.Timestamp.utcnow().tz_localize(None),
            })

        if i % 50 == 0:
            el = time.time() - t0
            print(f"[{ticker}] {i}/{len(missing)}  {counts}  "
                  f"{i / max(1e-9, el):.2f} req/s  live_exits={pool.n_live}")

    if frames:
        store.append_holdings(ticker, frames)
    if rows:
        store.write_manifest(ticker, rows)

    print(f"[{ticker}] DONE {counts}  {(time.time() - t0) / 60:.1f}m")
    return {"ticker": ticker, "targeted": len(missing), **counts,
            "_evidence": pd.DataFrame(evidence)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", default=None, help="comma list; default every ticker in the store")
    ap.add_argument("--dry-run", action="store_true", help="show what would be re-requested")
    ap.add_argument("--limit", type=int, default=None, help="cap days per ticker (probing)")
    ap.add_argument("--per-exit-rate", type=float, default=0.7)
    ap.add_argument("--bench-seconds", type=float, default=600.0)
    ap.add_argument("--max-attempts", type=int, default=10,
                    help="raised from the backfill default: a failing SOCKS handshake "
                         "burns an attempt, and most of the pool can be auth-failing")
    ap.add_argument("--evidence", default=None, help="write the per-day outcome table here (csv)")
    a = ap.parse_args(argv)

    tickers = ([t.strip().upper() for t in a.tickers.split(",") if t.strip()]
               if a.tickers else store_tickers())
    print(f"cache root: {store.cache_root()}")

    pool = None if a.dry_run else ProxyPool(per_exit_rate=a.per_exit_rate,
                                            bench_seconds=a.bench_seconds)

    results, ev = [], []
    for t in tickers:
        r = repair_ticker(t, pool=pool, max_attempts=a.max_attempts,
                          dry_run=a.dry_run, limit=a.limit)
        e = r.pop("_evidence", None)
        if e is not None and not e.empty:
            ev.append(e)
        results.append(r)

    print("\n=== repair summary ===")
    print(pd.DataFrame(results).to_string(index=False))

    n_refused = int(sum(r.get("refused", 0) for r in results))
    if ev:
        allev = pd.concat(ev, ignore_index=True)
        if a.evidence:
            allev.to_csv(a.evidence, index=False)
            print(f"\nper-day evidence -> {a.evidence}")
        print("\noutcome counts by kind:")
        print(allev.groupby("kind").size().to_string())
        print("\nbody-size distribution for 'empty' days (bytes):")
        emp = allev[allev["kind"] == "empty"]["n_bytes"]
        print(emp.value_counts().to_string() if len(emp) else "  (none)")

    if n_refused:
        print(f"\n!! {n_refused} day(s) were REFUSED and nothing was written for them. "
              f"Re-run to finish; the store is unchanged for those days.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

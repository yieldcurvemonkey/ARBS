r"""Ten years of computed UST timeseries values: constant maturities and specific issues.

What makes ten years possible at all
------------------------------------
Measured 2026-08-08: **Citi serves MATURED bonds on the tag path** - 525/525 of
the matured USTs in the ten-year window returned full history to their maturity
date. ``CVCURVEBOND`` will never name them (asked at five historical as-of dates
it returns today's set filtered, never the set as it stood), so the bond list
comes from the ``fiscaldata`` UST reference table, not from Citi's live listing.
That matters concretely: **531 of the 877 bonds alive in the window (61%) are
absent from ``bond_isins.json``**, so ``resolve_bond(require_quoted=True)`` would
reject bonds Citi quotes perfectly well. Its gate is a *live* universe, not a
*served* one, which is right for a live query and wrong for a historical warm.

Depth is not the binding constraint either: ``US912810EX29`` serves 2006-08-07 ..
2026-08-07, 5,012 rows - twenty years. Each bond starts at its own issue date.

The cost, measured rather than guessed
--------------------------------------
**~0.175 s per (bond, date) pricer build**, and it is roughly flat in the number
of VALUES read off that build - the cost is constructing and solving the pricer,
not reading it. So:

===================  ==========  =========
target               builds      hours
===================  ==========  =========
28 aliases x 10y         73,024        3.5
877 specific issues     834,986       40.6
**total**             **908,010**  **44.1**
===================  ==========  =========

Aliases run FIRST because they are the headline and cost a twelfth of the total.

Two properties this job needs and would not survive without
-----------------------------------------------------------
**It runs OFFLINE.** The ten-year tag warm fetched five values (PRICE, YIELD,
SPREAD_TSY, DURATION, DV01); anything else is a cache miss, and a cache miss on
the online path opens a workbook. Forty-four unattended hours of that against an
add-in whose memory only a human restart reclaims is exactly the failure the
memory ceiling exists to prevent. ``offline=True`` makes a miss an error instead
of a round trip, so the job can only ever fail loudly.

**It isolates per chunk.** rateslib does not solve every bond - a real
``ValueError: max_iter: 50 exceeded in 'ift_1dim'`` surfaced during benchmarking.
Over ~900,000 builds some will fail, and one bad bond must cost its own chunk and
nothing else. Chunks are (alias, year) and (bond, lifetime), so the blast radius
is minutes.

Usage
-----
::

    python scripts/citivelo_ust_10y_value_warm.py aliases
    python scripts/citivelo_ust_10y_value_warm.py issues
    python scripts/citivelo_ust_10y_value_warm.py status
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import os
import pathlib
import sys
import time
from typing import List, Sequence, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd

log = logging.getLogger("ust-10y-values")

END = datetime.date(2026, 8, 7)
YEARS = float(os.environ.get("WARM_YEARS", "10"))
START = END - datetime.timedelta(days=int(YEARS * 365.25))

#: The constant-maturity ladder: on-the-run, old, double-old, triple-old.
TENORS = (2, 3, 5, 7, 10, 20, 30)
ALIASES: Tuple[str, ...] = tuple(
    f"{p}{t}" for p in ("CT", "O", "OO", "OOO") for t in TENORS
)

#: Values reachable from the five tags the ten-year warm actually cached.
#: Deliberately NOT the full 46: a value whose tag was never warmed is a cache
#: miss, and under ``offline=True`` a miss fails the chunk. Widening this list
#: means widening the TAG warm first.
VALUE_NAMES: Tuple[str, ...] = tuple((os.environ.get("WARM_VALUES") or ",".join([
    "FRB_YTM", "FRB_CLEAN_PRICE", "FRB_DIRTY_PRICE", "FRB_DV01", "FRB_MOD_DURATION",
    "FRB_SPREAD_TSY", "FRB_CITI_PRICE", "FRB_CITI_YIELD", "FRB_CITI_DURATION",
    "FRB_CITI_DV01",
])).split(","))


def _manifest_path() -> pathlib.Path:
    """Beside the tag cache, never in the repo: this records what THIS machine
    has computed, and it is rewritten continuously by an unattended job that runs
    from the primary checkout."""
    from MDP.CitiVelocityExcel.cache import default_cache_dir

    return default_cache_dir() / "ust_10y_value_warm_manifest.json"


def _sig() -> str:
    return hashlib.sha1(
        f"{START}|{END}|{','.join(sorted(VALUE_NAMES))}".encode()
    ).hexdigest()[:10]


def _load() -> dict:
    p = _manifest_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a corrupt manifest must not block the job
            log.warning("manifest unreadable; starting fresh")
    return {"done": {}, "failed": {}}


def _save(man: dict) -> None:
    """Write the manifest ATOMICALLY: temp file, flush, then ``os.replace``.

    ``Path.write_text`` opens with truncate. If the write then fails, the old
    manifest is already gone and what remains is a zero-byte file - the resume
    state destroyed by the act of recording it.

    That is not hypothetical. On 2026-08-13 the disk filled mid-save:

        OSError: [Errno 28] No space left on device

    and 754 completed chunks - roughly nineteen hours of work - became an empty
    file. They were recoverable only because the store itself could be re-read,
    and that is luck, not design.

    ``os.replace`` is atomic on Windows and POSIX alike, so a reader either sees
    the whole previous manifest or the whole new one, and a failed write leaves
    the previous one untouched. The temp file sits in the same directory so the
    replace cannot cross a filesystem boundary.
    """
    p = _manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(man, fh, indent=1, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _queries(target: str, values):
    from Query.Unified.UnifiedQuery import UnifiedQuery

    return [UnifiedQuery(cusip=target, value=v) for v in values]


def _run_chunk(tb, router_factory, target: str, lo: datetime.date, hi: datetime.date, values):
    """One (target, window). Returns (rows, cols) or raises."""
    df = tb.get_timeseries(
        start=lo, end=hi, queries=_queries(target, values),
        routers={"FRB": router_factory()}, n_jobs=12, ignore_cache_miss=True,
    )
    return df.shape


def _chunks_for_aliases() -> List[Tuple[str, datetime.date, datetime.date]]:
    """(alias, year-window). One alias-year is ~260 builds, about 45 s — small
    enough that a failure costs little and progress is visible."""
    out = []
    for alias in ALIASES:
        y = START.year
        while datetime.date(y, 1, 1) <= END:
            lo = max(START, datetime.date(y, 1, 1))
            hi = min(END, datetime.date(y, 12, 31))
            if lo <= hi:
                out.append((alias, lo, hi))
            y += 1
    return out


def _chunks_for_issues() -> List[Tuple[str, datetime.date, datetime.date]]:
    """(cusip, its own lifetime inside the window). A bond only has history
    between issue and maturity, so asking outside that is guaranteed waste and,
    past maturity, a guaranteed solver failure."""
    from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

    ref = update_reference_data(source="fiscaldata").copy()
    ref["mat"] = pd.to_datetime(ref["maturity_date"], errors="coerce")
    ref["iss"] = pd.to_datetime(ref["issue_date"], errors="coerce")
    rel = ref[ref["mat"] > pd.Timestamp(START)].drop_duplicates(subset=["cusip"])
    out = []
    for _, r in rel.sort_values("mat", ascending=False).iterrows():
        lo = max(START, (r["iss"].date() if pd.notna(r["iss"]) else START))
        hi = min(END, r["mat"].date() - datetime.timedelta(days=1))
        if lo < hi:
            out.append((str(r["cusip"]), lo, hi))
    return out


def warm(mode: str, *, limit: int = 0, offline: bool = True) -> dict:
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from Query.Unified.registry import UnifiedValue
    from TB.FixedRateBondsTB import FixedRateBondsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    values = [getattr(UnifiedValue, n) for n in VALUE_NAMES]
    sig = _sig()
    man = _load()
    done, failed = man.setdefault("done", {}), man.setdefault("failed", {})

    chunks = _chunks_for_aliases() if mode == "aliases" else _chunks_for_issues()
    todo = [c for c in chunks if done.get(f"{mode}|{c[0]}|{c[1]}", {}).get("sig") != sig]
    if limit:
        todo = todo[:limit]
    already = sum(1 for c in chunks if done.get(f"{mode}|{c[0]}|{c[1]}", {}).get("sig") == sig)
    log.info("%s: %d chunks, %d already done at sig %s, %d to do%s",
             mode, len(chunks), already, sig, len(todo),
             f" (--limit {limit})" if limit else "")
    if not todo:
        return {"mode": mode, "done": 0, "of": 0}

    # offline on the CONSTRUCTOR, not the request. TB.FixedRateBondsTB calls
    # bulk_get_data with a fixed signature and forwards no request kwargs, so a
    # per-request offline flag cannot reach a timeseries build at all - which is
    # exactly why _citivelo_option reads the constructor level too. An earlier
    # draft of this script documented offline=True in its docstring and never
    # passed it anywhere, which is the same assert-both-readings defect this
    # branch has fixed elsewhere three times.
    #
    # It is load-bearing: without it a cache miss opens a workbook, and 44
    # unattended hours of that against an add-in whose memory only a human
    # restart reclaims is the failure the ceiling exists to prevent.
    mdp = FixedRateBondsMDP(source="USTS_CITIVELO-RL", offline=bool(offline))
    tb = TimeseriesBuilder()

    ok = bad = 0
    t0 = time.perf_counter()
    for i, (target, lo, hi) in enumerate(todo):
        key = f"{mode}|{target}|{lo}"
        try:
            shape = _run_chunk(tb, lambda: FixedRateBondsTB(mdp, show_tqdm=False),
                               target, lo, hi, values)
            done[key] = {"sig": sig, "rows": shape[0], "cols": shape[1],
                         "at": datetime.datetime.now().isoformat(timespec="seconds")}
            failed.pop(key, None)
            ok += 1
        except Exception as exc:  # noqa: BLE001 - one bad bond costs its own chunk
            failed[key] = {"sig": sig, "error": f"{type(exc).__name__}: {exc}"[:220],
                           "at": datetime.datetime.now().isoformat(timespec="seconds")}
            bad += 1
        if (i + 1) % 10 == 0 or i + 1 == len(todo):
            _save(man)
            el = time.perf_counter() - t0
            rate = el / max(1, i + 1)
            log.info("  %d/%d (%d ok, %d failed) %.0fs elapsed, ~%.1f min left",
                     i + 1, len(todo), ok, bad, el, rate * (len(todo) - i - 1) / 60)
    _save(man)
    log.info("%s finished: %d ok, %d failed, %.0fs", mode, ok, bad, time.perf_counter() - t0)
    return {"mode": mode, "ok": ok, "failed": bad, "of": len(todo)}


def status() -> None:
    man = _load()
    sig = _sig()
    done = {k: v for k, v in man.get("done", {}).items() if v.get("sig") == sig}
    failed = {k: v for k, v in man.get("failed", {}).items() if v.get("sig") == sig}
    print(f"manifest: {_manifest_path()}")
    print(f"window {START} .. {END}   values {len(VALUE_NAMES)}   sig {sig}")
    for mode, total in (("aliases", len(_chunks_for_aliases())), ("issues", None)):
        d = sum(1 for k in done if k.startswith(mode + "|"))
        f = sum(1 for k in failed if k.startswith(mode + "|"))
        print(f"  {mode:<8} {d} chunks done, {f} failed"
              + (f", {total} total" if total else ""))
    if failed:
        print("\n  sample failures:")
        for k, v in list(failed.items())[:5]:
            print(f"    {k}: {v['error'][:110]}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("mode", choices=["aliases", "issues", "status"])
    p.add_argument("--limit", type=int, default=0, help="only the first N chunks (smoke run)")
    p.add_argument("--online", action="store_true",
                   help="allow Excel on a cache miss. OFF by default: a long unattended "
                        "run must not open workbooks. Use only for a short, watched fill.")
    args = p.parse_args()
    if args.mode == "status":
        status()
        return
    warm(args.mode, limit=args.limit, offline=not args.online)


if __name__ == "__main__":
    main()

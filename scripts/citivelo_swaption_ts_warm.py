r"""Warm swaption VALUE timeseries off the Citi cube store, without touching Excel.

``scripts/citivelo_swaption_vol_warm.py`` warms the *cubes*. This warms the
*values* built from them - ``IRSwaptionsTB.get_timeseries`` over a query grid,
populating that TB's disk cache so a later notebook or backtest reads it instead
of rebuilding.

That was not possible before: ``IRSwaptionMDP`` had no route to
:class:`~Caching.swaption_cube_store.SwaptionCubeStore`, so every date went to
Excel over COM. With the store-backed read path in
``MDP/IRSwaptions/CITIVELO/cube_store.py`` a warmed date is a parquet read.

The tripwire is not optional by default
---------------------------------------
The point of this script is that it does **not** drive Excel, and "it seemed
fast" is not evidence of that. So ``CitiVelocityExcelClient.connect`` is replaced
with a function that RAISES before anything else happens, and the run reports the
count at the end. ``--allow-excel`` lifts it, deliberately awkwardly: the add-in's
cache only ever grows, only a human restart clears it, and it wedged at 5,249 MB
on 2026-08-07.

The pre-2020 history
--------------------
Citi published no strike offsets before 2020-01-24, so 1,067 of the 2,699 stored
USD days are ATM-only. A QuantLib *cube* cannot be built from those (it needs at
least one non-zero offset) while the rateslib backend and an ATM surface can. The
default range therefore starts at the first full-smile date and says so, rather
than starting in 2015 and producing 1,067 logged failures that look like bugs.
``--from-first-stored`` overrides it.

Usage::

    conda run -n stir python scripts/citivelo_swaption_ts_warm.py status
    conda run -n stir python scripts/citivelo_swaption_ts_warm.py warm --limit-days 20
    conda run -n stir python scripts/citivelo_swaption_ts_warm.py warm \
        --start 2024-01-01 --end 2026-08-07 --chunk-days 21
"""

from __future__ import annotations

# Local-only: this script reads two disk caches and writes a third. Nothing here
# wants the CORE cache L2, and the flag is read at Caching import time.
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import argparse
import datetime as dt
import json
import logging
import pathlib
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

LOGGER = logging.getLogger("citivelo_swaption_ts_warm")

#: The first date Citi served strike offsets. Measured from the store, not
#: assumed - see ``MDP/IRSwaptions/CITIVELO/cube_store.py``.
FIRST_SMILE_DATE = dt.date(2020, 1, 24)

#: A small, defensible default grid: the liquid expiry x tail corners plus one
#: OTM strike each side, valued as normal vol and spot premium. 5 x 3 x 3 x 2 =
#: 90 columns per date. Override with --shorthands / --strikes / --values.
DEFAULT_SHORTHANDS = ("1Mx10Y", "3Mx10Y", "1Yx10Y", "1Yx2Y", "5Yx5Y")
DEFAULT_STRIKES = ("ATMF", "ATMF+25", "ATMF-25")
DEFAULT_VALUES = ("NVOL", "SPOT_PREM")


class ExcelWasTouched(RuntimeError):
    """The run reached the add-in. See the module docstring."""


def install_excel_tripwire() -> List[str]:
    """Replace the only COM entry point with something that raises. Returns a log."""
    import MDP.CitiVelocityExcel.com_client as com

    attempts: List[str] = []

    def _connect(*args: Any, **kwargs: Any):
        attempts.append("".join(traceback.format_stack(limit=18)))
        raise ExcelWasTouched(
            "CitiVelocityExcelClient.connect() was called. This warm is supposed to "
            "read the swaption cube store; a date that is not warm falls through to "
            "Excel. Warm it (scripts/citivelo_swaption_vol_warm.py build) or pass "
            "--allow-excel if driving the add-in is really what you want."
        )

    com.CitiVelocityExcelClient.connect = staticmethod(_connect)
    return attempts


# ── the grid ──────────────────────────────────────────────────────────────


def build_queries(
    *,
    curve_name: str,
    shorthands: Sequence[str],
    strikes: Sequence[str],
    values: Sequence[str],
    structures: Sequence[str],
) -> List[Any]:
    from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery
    from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure
    from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue

    out: List[Any] = []
    for shorthand in shorthands:
        for strike in strikes:
            for structure in structures:
                out.append(
                    IRSwaptionQuery(
                        curve=curve_name,
                        shorthand=shorthand,
                        strike=strike,
                        structure=IRSwaptionStructure[structure.upper()],
                        value=[IRSwaptionValue[v.upper()] for v in values],
                    )
                )
    return out


def _chunks(items: Sequence[dt.date], size: int) -> List[Sequence[dt.date]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# ── commands ──────────────────────────────────────────────────────────────


def stored_dates(currency: str, start: Optional[dt.date], end: Optional[dt.date]) -> List[dt.date]:
    from Caching.swaption_cube_store import SwaptionCubeStore, asset_for

    store = SwaptionCubeStore.default()
    days = store.available_dates(asset_for(currency))
    return [d for d in days if (start is None or d >= start) and (end is None or d <= end)]


def cmd_status(args) -> int:
    from Caching.swaption_cube_store import SwaptionCubeStore, asset_for
    from MDP.IRSwaptions.CITIVELO.cube_store import load_stored_cubes

    store = SwaptionCubeStore.default()
    asset = asset_for(args.currency)
    days = store.available_dates(asset)
    print(f"cube store : {asset}")
    print(f"             {len(days)} day(s)  {days[0] if days else '-'} .. {days[-1] if days else '-'}")
    print(f"             base_dir {store.base_dir}")
    if days:
        pre = [d for d in days if d < FIRST_SMILE_DATE]
        post = [d for d in days if d >= FIRST_SMILE_DATE]
        print(f"             ATM-only   {len(pre):5d}  {pre[0] if pre else '-'} .. {pre[-1] if pre else '-'}")
        print(f"             full smile {len(post):5d}  {post[0] if post else '-'} .. {post[-1] if post else '-'}")
        # confirm the split from the data rather than from the constant
        sample = load_stored_cubes(args.currency, [days[0], days[len(days) // 2], days[-1]])
        for d, s in sorted(sample.items()):
            print(f"             {d}  smile={s.smile:9s} offsets={len(s.offsets_bp):2d}  {s.source}")

    from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP
    from TB.IRSwaptionsTB import IRSwaptionsTB

    mdp = IRSwaptionMDP(source=args.source, curve_source=args.curve_source)
    with IRSwaptionsTB(mdp, show_tqdm=False) as tb:
        path = pathlib.Path(tb._cache_path)
        n = 0
        try:
            n = len(getattr(tb, tb._cache_attr))
        except Exception:  # noqa: BLE001
            pass
        print(f"value cache: {path}")
        print(f"             {n:,} cached (date, curve, query) row(s)")
    return 0


def cmd_warm(args) -> int:
    attempts: List[str] = []
    if not args.allow_excel:
        attempts = install_excel_tripwire()

    from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP
    from TB.IRSwaptionsTB import IRSwaptionsTB

    start = dt.date.fromisoformat(args.start) if args.start else None
    end = dt.date.fromisoformat(args.end) if args.end else None
    if start is None and not args.from_first_stored:
        start = FIRST_SMILE_DATE
        LOGGER.info(
            "starting at %s, the first date Citi served strike offsets. Everything "
            "before it is stored ATM-only, which a QuantLib cube cannot use. Pass "
            "--from-first-stored to include it anyway.",
            FIRST_SMILE_DATE,
        )

    days = stored_dates(args.currency, start, end)
    if args.limit_days:
        days = days[-int(args.limit_days) :]
    if not days:
        LOGGER.error("no stored cube days in that range; run the cube warm first.")
        return 1

    queries = build_queries(
        curve_name=args.curve_name,
        shorthands=[s.strip() for s in args.shorthands.split(",") if s.strip()],
        strikes=[s.strip() for s in args.strikes.split(",") if s.strip()],
        values=[s.strip() for s in args.values.split(",") if s.strip()],
        structures=[s.strip() for s in args.structures.split(",") if s.strip()],
    )
    LOGGER.info(
        "warming %d day(s) %s .. %s with %d quer(ies) (source=%s curve_source=%s)",
        len(days), days[0], days[-1], len(queries), args.source, args.curve_source,
    )

    perf_path = pathlib.Path(args.perf_log) if args.perf_log else None
    if perf_path is not None:
        perf_path.parent.mkdir(parents=True, exist_ok=True)

    def perf(event: dict) -> None:
        if perf_path is None:
            return
        with open(perf_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({**event, "ts": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")

    mdp = IRSwaptionMDP(source=args.source, curve_source=args.curve_source)
    if args.verify_every != 1:
        LOGGER.warning(
            "--verify-every %d: the CITIVELO cube's node-ordering check will run on "
            "1 chunk in %d. Measured on one USD date: verify=True 242.4 s for the "
            "first six values, verify=False 7.3 s, and all six values IDENTICAL to "
            "0.0e+00 - the check changes no number, it only detects. What sampling "
            "gives up is detecting a bad DAY (a crossed smile in one day's quotes); "
            "a bad CONSTRUCTION is systematic and any verified chunk catches it. "
            "Pass --verify-every 1 to check every date.",
            args.verify_every, args.verify_every,
        )
    started = time.time()
    total_rows = 0
    failed_chunks = 0
    batches = _chunks(days, max(1, args.chunk_days))
    perf({"event": "warm_start", "days": len(days), "queries": len(queries), "chunks": len(batches)})

    with IRSwaptionsTB(mdp, show_tqdm=args.progress) as tb:
        for i, chunk in enumerate(batches, start=1):
            t0 = time.perf_counter()
            # Chunk 1 is always verified, so a systematically mis-built cube fails
            # in the first minute rather than after the whole range.
            verify = (i == 1) or (args.verify_every > 0 and (i - 1) % args.verify_every == 0)
            mdp._default_request_kwargs["verify"] = bool(verify)
            try:
                frame = tb.get_timeseries(
                    start=chunk[0], end=chunk[-1], queries=queries,
                    n_jobs=args.n_jobs, timestamps=[
                        dt.datetime.combine(d, dt.time.min) for d in chunk
                    ],
                )
                rows = 0 if frame is None else int(frame.notna().to_numpy().sum())
                total_rows += rows
                elapsed = time.perf_counter() - t0
                LOGGER.info(
                    "chunk %d/%d  %s .. %s  %d day(s)  %d value(s)  %.1fs  (%.2fs/day)%s",
                    i, len(batches), chunk[0], chunk[-1], len(chunk), rows,
                    elapsed, elapsed / len(chunk), "  [verified]" if verify else "",
                )
                perf({
                    "event": "chunk", "index": i, "count": len(batches),
                    "start": chunk[0].isoformat(), "end": chunk[-1].isoformat(),
                    "days": len(chunk), "values": rows, "seconds": round(elapsed, 2),
                    "verified": bool(verify),
                })
            except ExcelWasTouched as exc:
                LOGGER.error("STOPPING: %s", exc)
                if attempts:
                    repo = [
                        ln.strip().splitlines()[0]
                        for ln in attempts[-1].splitlines()
                        if "ARBS" in ln and "site-packages" not in ln
                    ]
                    LOGGER.error("call path:\n  %s", "\n  ".join(repo[-8:]))
                perf({"event": "excel_touched", "chunk": i})
                return 3
            except Exception as exc:  # noqa: BLE001 - one chunk must not end the run
                failed_chunks += 1
                LOGGER.warning("chunk %d/%d FAILED: %s: %s", i, len(batches), type(exc).__name__, exc)
                perf({"event": "chunk_failed", "index": i, "error": f"{type(exc).__name__}: {exc}"})

    wall = time.time() - started
    LOGGER.warning(
        "DONE in %.1f min: %d day(s), %s value(s) cached, %d failed chunk(s), "
        "%.2f s/day, Excel connections=%d",
        wall / 60.0, len(days), f"{total_rows:,}", failed_chunks, wall / len(days), len(attempts),
    )
    perf({
        "event": "warm_done", "seconds": round(wall, 1), "days": len(days),
        "values": total_rows, "failed_chunks": failed_chunks, "excel_attempts": len(attempts),
    })
    if attempts:
        LOGGER.error("Excel was reached %d time(s) — that is a bug in the warm.", len(attempts))
        return 3
    return 1 if failed_chunks else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__ or "", formatter_class=argparse.RawDescriptionHelpFormatter
    )

    def common(sub):
        sub.add_argument("--currency", default="USD")
        sub.add_argument("--curve-name", default="USD-SOFR-1D")
        sub.add_argument(
            "--source", default="CITIVELO-RL",
            help="IRSwaptionMDP source token. -RL uses the rateslib engine, which "
                 "can price an ATM-only day; -QL needs a strike smile.",
        )
        sub.add_argument(
            "--curve-source", default="ERIS_EOD_LIVE-RL_BASIC",
            help="NOT citivelo_excel by default: its CurveStore fast path serves the "
                 "curve nodes from the warm but then looks up the published overnight "
                 "FIXINGS through a cached-then-live layer, which reaches Excel.",
        )
        sub.add_argument("--verbose", action="store_true")

    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="what is warm, and what is cached")
    common(s)
    s.set_defaults(func=cmd_status)

    w = sub.add_parser("warm", help="build and cache the value timeseries")
    common(w)
    w.add_argument("--start", default=None, help="YYYY-MM-DD (default: first full-smile date)")
    w.add_argument("--end", default=None, help="YYYY-MM-DD")
    w.add_argument("--from-first-stored", action="store_true",
                   help="include the pre-2020 ATM-only history")
    w.add_argument("--limit-days", type=int, default=None, help="only the last N days")
    w.add_argument("--chunk-days", type=int, default=21)
    w.add_argument("--n-jobs", type=int, default=4)
    w.add_argument(
        "--verify-every", type=int, default=10,
        help="run the cube's node-ordering check on 1 chunk in N (chunk 1 always). "
             "Measured: verify=True 242.4s vs verify=False 7.3s for the first six "
             "values on a date, with every value IDENTICAL. 1 = check every chunk.",
    )
    w.add_argument("--shorthands", default=",".join(DEFAULT_SHORTHANDS))
    w.add_argument("--strikes", default=",".join(DEFAULT_STRIKES))
    w.add_argument("--values", default=",".join(DEFAULT_VALUES))
    w.add_argument("--structures", default="PAYER,RECEIVER")
    w.add_argument("--progress", action="store_true")
    w.add_argument("--perf-log", default=None)
    w.add_argument(
        "--allow-excel", action="store_true",
        help="lift the COM tripwire. The add-in's cache only grows and only a human "
             "restart clears it; it wedged at 5,249 MB on 2026-08-07.",
    )
    w.set_defaults(func=cmd_warm)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

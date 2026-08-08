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

#: The default grid is deliberately SMALL, because the cost is per value and it
#: is not small. Measured 2026-08-08 over 60 real days: 5.31 s/day for 4 values a
#: day, i.e. ~1.33 s per value. Three shorthands x three strikes x one structure
#: x two values = 18 values a day = ~24 s/day, so the 1,632 full-smile days are
#: about 11 hours. A 90-column grid would be 55. Widen it deliberately with
#: --shorthands / --strikes / --values / --structures; the run prints its own
#: projection before it starts.
DEFAULT_SHORTHANDS = ("3Mx10Y", "1Yx10Y", "5Yx5Y")
DEFAULT_STRIKES = ("ATMF", "ATMF+25", "ATMF-25")
DEFAULT_VALUES = ("NVOL", "SPOT_PREM")

#: Seconds per value, measured. Only used to print a projection.
MEASURED_SECONDS_PER_VALUE = 1.33


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
    n_values = len(queries) * max(1, len([v for v in args.values.split(",") if v.strip()]))
    projected_s = len(days) * n_values * MEASURED_SECONDS_PER_VALUE
    LOGGER.warning(
        "warming %d day(s) %s .. %s with %d quer(ies) x %d value(s) = %d value(s)/day "
        "(source=%s curve_source=%s)",
        len(days), days[0], days[-1], len(queries),
        n_values // max(1, len(queries)), n_values, args.source, args.curve_source,
    )
    LOGGER.warning(
        "projected ~%.1f h at the measured %.2f s/value. Narrow the grid if that is "
        "not what you meant - the cost is per VALUE, not per day.",
        projected_s / 3600.0, MEASURED_SECONDS_PER_VALUE,
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

    # PREFLIGHT, not per-chunk sampling. The node-ordering check costs ~240 s per
    # DATE, not per request, so "verify one chunk in ten" still pays it for every
    # date in that chunk - a 10-day chunk is 40 minutes. Verifying N dates once,
    # up front, is one fixed cost for the whole run.
    #
    # Measured on one USD date, six values: verify=True 242.4 s, verify=False
    # 7.3 s, and every value IDENTICAL to 0.0e+00. The check changes no number;
    # it only detects. What this gives up is detecting a bad DAY (a crossed smile
    # in one day's quotes). A bad CONSTRUCTION is systematic and the preflight
    # catches it. --verify-dates 0 skips it; there is no "verify everything"
    # option because at 240 s x 1,632 days it is 109 hours.
    if args.verify_dates > 0:
        preflight = days[: int(args.verify_dates)]
        LOGGER.warning(
            "preflight: verifying the cube's node ordering on %d date(s) (%s). "
            "~240 s each; the rest of the run builds unverified, which is measured "
            "to change no value.",
            len(preflight), ", ".join(d.isoformat() for d in preflight),
        )
        mdp._default_request_kwargs["verify"] = True
        t0 = time.perf_counter()
        from TB.IRSwaptionsTB import _build_row_for_query, _flatten_queries_with_wrappers

        # A query built with value=[NVOL, SPOT_PREM] is NOT directly priceable -
        # BaseValue.apply does `value not in self._map` and a list is unhashable.
        # get_timeseries expands multi-value queries first; the preflight has to
        # do the same rather than hand a raw one to _build_row_for_query.
        flat_queries, _ = _flatten_queries_with_wrappers(queries)
        probe = flat_queries[0]

        for d in preflight:
            try:
                ctx = mdp.get_data(
                    {"curve_name": args.curve_name, "timestamp": d, "ignore_cache": True}
                )
                # Building the context is NOT enough: the QuantLib cube - and so
                # the ordering check - is built lazily on the first volatility()
                # read, which happens when a STRIKE is resolved. A preflight that
                # only builds the context finishes in 2 s and verifies nothing.
                # Price one query to force it.
                _build_row_for_query(ctx, probe, d)
            except ExcelWasTouched:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("preflight FAILED on %s: %s: %s", d, type(exc).__name__, exc)
                perf({"event": "preflight_failed", "date": d.isoformat(),
                      "error": f"{type(exc).__name__}: {exc}"})
                return 4
        LOGGER.warning("preflight OK in %.1f s", time.perf_counter() - t0)
        perf({"event": "preflight_ok", "dates": len(preflight),
              "seconds": round(time.perf_counter() - t0, 1)})
    mdp._default_request_kwargs["verify"] = False

    started = time.time()
    total_rows = 0
    failed_chunks = 0
    batches = _chunks(days, max(1, args.chunk_days))
    perf({"event": "warm_start", "days": len(days), "queries": len(queries), "chunks": len(batches)})

    with IRSwaptionsTB(mdp, show_tqdm=args.progress) as tb:
        for i, chunk in enumerate(batches, start=1):
            t0 = time.perf_counter()
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
                    "chunk %d/%d  %s .. %s  %d day(s)  %d value(s)  %.1fs  (%.2fs/day)",
                    i, len(batches), chunk[0], chunk[-1], len(chunk), rows,
                    elapsed, elapsed / len(chunk),
                )
                perf({
                    "event": "chunk", "index": i, "count": len(batches),
                    "start": chunk[0].isoformat(), "end": chunk[-1].isoformat(),
                    "days": len(chunk), "values": rows, "seconds": round(elapsed, 2),
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
        "--verify-dates", type=int, default=1,
        help="verify the cube's node ordering on the first N dates as a PREFLIGHT, "
             "then build the rest unverified. The check costs ~240s per DATE and "
             "changes no value (measured: 242.4s vs 7.3s for six values, identical "
             "to 0.0e+00), so it is a construction check, not a pricing input. "
             "0 skips it.",
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

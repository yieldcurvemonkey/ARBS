r"""Deep warm for the swaption VALUE cache: a day-level process pool over a wide
query grid, with the redundant pricing removed.

Why this exists alongside ``citivelo_swaption_ts_warm.py``
----------------------------------------------------------
That script warms a small grid through one ``IRSwaptionsTB.get_timeseries`` call
per chunk. It is the right tool for a few hundred values. It cannot reach the
scale of a full-history, full-surface warm, for two measured reasons.

**1. ``leg_metrics`` is recomputed once per VALUE.** ``IRSwaptionQuery`` expands
``value=[A, B, C]`` into separate queries (``return_query``), each of which runs
``_build_row_for_query`` -> ``resolve_package`` -> ``build_value_map`` ->
``apply`` -> ``IRSwaptionValueFunctionMap._metrics`` -> ``leg_metrics``. One
``leg_metrics`` call already returns EVERY metric - NVOL, SPOT_PREM, VEGA_01,
THETA_1D, DV01, DELTA, GAMMA_01, CHARM, VETA, the breakevens - so asking for ten
values prices the same leg ten times.

Profiled 2026-08-13 on one USD date, 3 values on one leg: 4.43 s total, of which
4.26 s (96%) was inside ``leg_metrics``, and inside THAT, 249 ``build_irswap``
calls and 186 ``rl_engine.forward`` calls. ``resolve_package`` was 0.045 s and
``build_value_map`` was 0.000 s - the strike axis is not the cost, the repricing
is.

Memoising ``leg_metrics`` per (context, leg) for the duration of one day made 30
queries (3 strikes x 5 values x named/unnamed) go from 29.01 s to 4.17 s -
**6.96x** - with all 30 rows bit-identical. The value functions are not touched:
``_nvol`` weights by ``|rw|``, ``_spot_prem`` multiplies by 10,000, ``_fwd_prem``
by 100, and reimplementing that off a metrics dict would be a silent-wrongness
generator. Only the expensive thing they all call is cached.

**2. ``n_jobs`` does not scale.** Measured on 3 fresh days x 12 values:
n_jobs=4 -> 0.78 s/value, n_jobs=8 -> 0.86, n_jobs=16 -> 0.86. The pricing is
GIL/QuantLib bound, so threads are exhausted at 4 and the only remaining lever is
PROCESSES. One worker per day, which is also the natural unit: the context (curve
+ cube from the store) costs 0.06 s to build and is then shared by every query
for that day.

The cost model this leaves
--------------------------
The unit of work is the PACKAGE - one (day, shorthand, strike, structure) - not
the value. Values after the first are ~0.14 s. So widening the value axis is
nearly free, widening the strike axis costs ~0.7 s per leg, and a straddle costs
two legs.

Everything here reads the warmed stores. ``CitiVelocityExcelClient.connect`` is
replaced with one that raises before anything else happens, and the day list is
built from ``SwaptionCubeStore.available_dates`` intersected with the curve warm,
so a day that would have driven COM is never requested in the first place.
"""

from __future__ import annotations

import os

# Local-only: this reads two disk caches and writes a third.
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import argparse
import datetime as dt
import itertools
import pathlib
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Iterable, Sequence

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

CURVE = "USD-SOFR-1D"

#: ~20 liquid expiry x tail points. Deliberately not the full 17 x 9 = 153 grid:
#: the cost is per package, so the surface corners nobody trades are the ones
#: that would dominate the bill.
DEFAULT_SHORTHANDS = (
    "1Mx10Y", "3Mx10Y", "6Mx10Y", "1Yx10Y", "2Yx10Y", "5Yx10Y", "10Yx10Y",
    "3Mx2Y", "1Yx2Y", "5Yx2Y",
    "3Mx5Y", "6Mx5Y", "1Yx5Y", "2Yx5Y", "5Yx5Y",
    "3Mx30Y", "1Yx30Y", "5Yx30Y",
    "3Mx1Y", "1Yx1Y",
)

#: Citi publishes 13 offsets; these are the ones with quotes on essentially every
#: full-smile day. A signed strike also picks the side, so ATMF is the only one
#: priced as a straddle.
DEFAULT_STRIKES = ("ATMF", "ATMF+25", "ATMF-25", "ATMF+50", "ATMF-50", "ATMF+100", "ATMF-100")

#: Free once the package is priced - every one of these comes out of the same
#: leg_metrics dict.
DEFAULT_VALUES = (
    "NVOL", "SPOT_PREM", "FWD_PREM", "VEGA_01", "THETA_1D",
    "DV01", "DELTA", "GAMMA_01", "DAILY_BREAKEVEN_NVOL", "ANNUAL_BREAKEVEN_NVOL",
)

#: Measured 2026-08-13: ~0.70 s per leg for the first value, ~0.14 s per value
#: after. Used only to print a projection before committing hours.
SECONDS_PER_LEG = 0.70
SECONDS_PER_EXTRA_VALUE = 0.14


# ── the two things that make this feasible ────────────────────────────────


def install_excel_tripwire() -> list[str]:
    """Replace the only COM entry point with one that raises what a signed-out
    add-in raises.

    ``AddInNotSignedInError``, not a bare ``RuntimeError``: the fixings resolver
    degrades on ``CitiVelocityError`` only (``CITIVELO_EXCEL/fixings.py``), so a
    generic exception propagates and makes a perfectly offline curve build look
    like a hard Excel dependency. That misreading cost an afternoon once already.
    """
    import MDP.CitiVelocityExcel.com_client as com
    from MDP.CitiVelocityExcel.errors import AddInNotSignedInError

    touched: list[str] = []

    def _connect(*_a: Any, **_k: Any):
        touched.append("connect")
        raise AddInNotSignedInError()

    com.CitiVelocityExcelClient.connect = staticmethod(_connect)
    return touched


def install_leg_metrics_memo() -> dict:
    """Memoise ``leg_metrics`` per (context, leg). Returns the stats dict.

    Two details that are not optional:

    * the cache is keyed on ``context.id()``, NOT ``id(context)``. CPython reuses
      object ids after a free, so an id-keyed memo can hand day N+1 the metrics
      of a day N context that has since been collected - a silent wrong number
      that looks like real data. ``IRSwaptionMarketContext.id()`` is
      ``curve|date|provider-engine|surface``, which is what actually identifies
      the market snapshot.
    * the patch goes through ``sys.modules``. ``Query/IRSwaptions/__init__.py``
      re-exports the ENUM under the submodule's own name, so
      ``import Query.IRSwaptions.IRSwaptionValue as m`` binds the Enum CLASS and
      ``m.leg_metrics = ...`` silently does nothing - the memo reports zero calls
      and you conclude leg_metrics was never the cost.
    """
    import Query.IRSwaptions.pricer as pricer_mod

    original = pricer_mod.leg_metrics
    stats: dict[str, Any] = {"calls": 0, "misses": 0, "cache": {}, "original": original}
    cache: dict = stats["cache"]

    def _leg_key(leg: Any) -> tuple:
        return (
            str(getattr(leg, "option_type", "")),
            getattr(leg, "exercise_date", None),
            getattr(leg, "underlying_effective_date", None),
            getattr(leg, "underlying_maturity_date", None),
            float(getattr(leg, "strike", 0.0) or 0.0),
            float(getattr(leg, "notional", 0.0) or 0.0),
            getattr(leg, "premium_override", None),
        )

    def _memo(context: Any, leg: Any):
        stats["calls"] += 1
        try:
            ctx_key = context.id()
        except Exception:  # noqa: BLE001 - an unidentifiable context must not be cached
            return original(context, leg)
        key = (ctx_key, _leg_key(leg))
        hit = cache.get(key)
        if hit is not None:
            return hit
        stats["misses"] += 1
        out = original(context, leg)
        cache[key] = out
        return out

    pricer_mod.leg_metrics = _memo
    sys.modules["Query.IRSwaptions.IRSwaptionValue"].leg_metrics = _memo
    return stats


def uninstall_leg_metrics_memo(stats: dict) -> None:
    import Query.IRSwaptions.pricer as pricer_mod

    original = stats["original"]
    pricer_mod.leg_metrics = original
    sys.modules["Query.IRSwaptions.IRSwaptionValue"].leg_metrics = original


# ── the grid ──────────────────────────────────────────────────────────────


def build_queries(
    *,
    curve_name: str,
    shorthands: Sequence[str],
    strikes: Sequence[str],
    values: Sequence[str],
    naming: str,
) -> list[Any]:
    """One query per (shorthand, strike, value, naming).

    ``naming='both'`` emits each computation twice, named and bare. That is
    nearly free here - the second one hits the memo - but it is two cache KEYS,
    because ``_query_fingerprint`` includes ``name``. Without it a reader that
    labels its columns gets no hits from this warm at all.
    """
    from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery
    from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure
    from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue

    namings = {"named": (True,), "unnamed": (False,), "both": (True, False)}[naming]

    out: list[Any] = []
    for shorthand, strike, value_name in itertools.product(shorthands, strikes, values):
        # ATM is a straddle (vol is a property of the point, not of a side);
        # a signed strike already picks the side, so the wings are single-leg.
        if strike.upper() == "ATMF":
            structure = IRSwaptionStructure.STRADDLE
        elif "+" in strike:
            structure = IRSwaptionStructure.PAYER
        else:
            structure = IRSwaptionStructure.RECEIVER
        for named in namings:
            out.append(
                IRSwaptionQuery(
                    curve=curve_name,
                    shorthand=shorthand,
                    strike=strike,
                    structure=structure,
                    value=IRSwaptionValue[value_name.upper()],
                    name=(f"{shorthand} {strike} {value_name.upper()}" if named else None),
                )
            )
    return out


def priceable_days(
    *,
    curve_name: str,
    start: dt.date,
    end: dt.date,
    require_smile: bool = True,
) -> list[dt.date]:
    """Days with BOTH a cube and a discount curve, so nothing reaches Excel."""
    from Caching.curve_store import CurveStore
    from Caching.swaption_cube_store import SwaptionCubeStore

    cube_store = SwaptionCubeStore.default()
    cube_days = set(cube_store.available_dates("USD-SWAPTIONVOL-CITIVELOEXCEL"))
    curve_days = set(CurveStore.default().available_dates(f"{curve_name}-CITIVELOEXCEL"))

    days = sorted(d for d in (cube_days & curve_days) if start <= d <= end)
    if require_smile:
        # Citi published no strike offsets before this date; a wing on an
        # ATM-only day is not a cache miss, it is data that never existed.
        days = [d for d in days if d >= dt.date(2020, 1, 24)]
    return days


# ── the worker ────────────────────────────────────────────────────────────


def _release_day_caches() -> None:
    """Drop the per-process caches that are keyed by DATE.

    Measured the hard way: the first run of this script held every day's cube in
    ``provider._CUBE_CACHE`` for the life of the worker, so ten processes walking
    forward through history grew without bound. Peak pagefile usage hit 8.7 GB,
    Windows grew ``C:\\pagefile.sys`` on the system disk, free space fell from
    8 GB to 0.2 GB, and the disk guard aborted the run. The cache writes were
    never the problem - they were 28 MB.

    A day's cube costs 0.06 s to rebuild from the store, so holding it across days
    buys nothing here: a worker never revisits a date.
    """
    for module, fn in (
        ("MDP.IRSwaptions.CITIVELO.provider", "clear_citivelo_cube_cache"),
        ("MDP.IRSwaptions.CITIVELO.cube_store", "clear_stored_cube_cache"),
    ):
        try:
            mod = sys.modules.get(module)
            if mod is not None:
                getattr(mod, fn)()
        except Exception:  # noqa: BLE001 - a cache that will not clear is not fatal
            pass


def _warm_one_day(payload: dict) -> dict:
    """Price every query for one date. Runs in its own process."""
    day: dt.date = payload["day"]
    started = time.perf_counter()
    result = {"day": day.isoformat(), "rows": 0, "excel": 0, "error": None,
              "elapsed": 0.0, "metrics_calls": 0, "metrics_misses": 0}

    try:
        touched = install_excel_tripwire()
        memo = install_leg_metrics_memo()

        from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP
        from TB.IRSwaptionsTB import IRSwaptionsTB

        mdp = IRSwaptionMDP(
            source=payload["source"],
            curve_source=payload["curve_source"],
            request_defaults={"verify": False},
        )
        queries = build_queries(
            curve_name=payload["curve_name"],
            shorthands=payload["shorthands"],
            strikes=payload["strikes"],
            values=payload["values"],
            naming=payload["naming"],
        )
        with IRSwaptionsTB(mdp, show_tqdm=False) as tb:
            frame = tb.get_timeseries(day, day, queries, n_jobs=payload["n_jobs"])
            result["rows"] = int(frame.notna().to_numpy().sum()) if not frame.empty else 0

        result["excel"] = len(touched)
        result["metrics_calls"] = memo["calls"]
        result["metrics_misses"] = memo["misses"]
        uninstall_leg_metrics_memo(memo)
        _release_day_caches()
    except Exception as exc:  # noqa: BLE001 - one bad day must not kill the run
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()[-1200:]

    result["elapsed"] = time.perf_counter() - started
    return result


# ── verification ──────────────────────────────────────────────────────────


def cmd_verify(args: argparse.Namespace) -> int:
    """Prove the memo changes nothing, on real days, before trusting hours to it.

    A warm that writes subtly different numbers is worse than no warm: it is
    indistinguishable from a correct one at read time.
    """
    install_excel_tripwire()

    from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP
    from TB.IRSwaptionsTB import _build_row_for_query

    days = priceable_days(curve_name=args.curve_name, start=args.start, end=args.end)[-args.days:]
    if not days:
        print("no priceable days in range", file=sys.stderr)
        return 2

    queries = build_queries(
        curve_name=args.curve_name,
        shorthands=args.shorthands[: args.verify_shorthands],
        strikes=args.strikes,
        values=args.values,
        naming=args.naming,
    )
    print(f"verifying {len(queries)} queries x {len(days)} day(s): {days}")

    mdp = IRSwaptionMDP(source=args.source, curve_source=args.curve_source,
                        request_defaults={"verify": False})

    mismatches = 0
    total = 0
    for day in days:
        ctx = mdp.get_data({"curve_name": args.curve_name, "timestamp": day})

        t0 = time.perf_counter()
        stock = [_build_row_for_query(ctx, q, day) for q in queries]
        stock_el = time.perf_counter() - t0

        memo = install_leg_metrics_memo()
        t0 = time.perf_counter()
        fast = [_build_row_for_query(ctx, q, day) for q in queries]
        fast_el = time.perf_counter() - t0
        uninstall_leg_metrics_memo(memo)

        for (_d1, c1, v1), (_d2, c2, v2) in zip(stock, fast):
            total += 1
            same = (c1 == c2) and (v1 == v2 or (v1 != v1 and v2 != v2))
            if not same:
                mismatches += 1
                print(f"  MISMATCH {day} {c1!r}: stock={v1!r} memo={v2!r}")
        print(f"  {day}: stock {stock_el:6.2f}s  memo {fast_el:6.2f}s  "
              f"speedup {stock_el / max(fast_el, 1e-9):5.2f}x  "
              f"leg_metrics {memo['misses']}/{memo['calls']}")

    print(f"\n{total} rows compared, {total - mismatches} bit-identical, {mismatches} mismatched")
    return 1 if mismatches else 0


# ── projection and warm ───────────────────────────────────────────────────


def _cache_volume() -> pathlib.Path:
    """The volume the TB value cache actually lands on."""
    from Caching.swaption_cube_store import SwaptionCubeStore

    root = os.getenv("ARBS_CACHE_DIR")
    base = pathlib.Path(root) if root else SwaptionCubeStore.default().base_dir.parent
    return pathlib.Path(base.anchor or base)


def _free_gb(volume: pathlib.Path) -> float:
    import shutil

    try:
        return shutil.disk_usage(str(volume)).free / (1024 ** 3)
    except Exception:  # noqa: BLE001 - a guard that cannot read the disk must not stop the warm
        return float("inf")


def _projection(args: argparse.Namespace, n_days: int) -> str:
    n_atm = len(args.shorthands)
    n_wings = len(args.shorthands) * (len(args.strikes) - 1)
    legs_per_day = n_atm * 2 + n_wings  # straddle is two legs
    n_values = len(args.values) * (2 if args.naming == "both" else 1)
    extra = (len(args.shorthands) * len(args.strikes)) * (n_values - 1) * SECONDS_PER_EXTRA_VALUE
    per_day = legs_per_day * SECONDS_PER_LEG + extra
    total_h = per_day * n_days / 3600.0
    rows = len(args.shorthands) * len(args.strikes) * n_values * n_days
    return (
        f"  grid      {len(args.shorthands)} shorthands x {len(args.strikes)} strikes "
        f"x {len(args.values)} values x {args.naming}\n"
        f"  days      {n_days}\n"
        f"  rows      ~{rows:,} (~{rows * 0.57 / 1_048_576:.2f} GB at 0.57 KB/row)\n"
        f"  cost      ~{per_day:.0f} s/day -> ~{total_h:.1f} h single-stream, "
        f"~{total_h / max(args.processes, 1):.1f} h on {args.processes} processes"
    )


def cmd_warm(args: argparse.Namespace) -> int:
    days = priceable_days(curve_name=args.curve_name, start=args.start, end=args.end)
    if not days:
        print("no priceable days in range", file=sys.stderr)
        return 2

    print(f"deep warm  {days[0]} .. {days[-1]}")
    print(_projection(args, len(days)))

    if args.dry_run:
        print("\n--dry-run: nothing priced.")
        return 0

    payload_base = {
        "curve_name": args.curve_name,
        "source": args.source,
        "curve_source": args.curve_source,
        "shorthands": list(args.shorthands),
        "strikes": list(args.strikes),
        "values": list(args.values),
        "naming": args.naming,
        "n_jobs": args.n_jobs,
    }

    started = time.perf_counter()
    done = 0
    rows = 0
    failures: list[str] = []
    excel_touches = 0
    aborted = False

    # max_tasks_per_child recycles a worker periodically. Belt to _release_day_caches'
    # braces: anything else in the import graph that quietly accumulates per date
    # (rateslib fixings frames, QuantLib globals) is bounded by process lifetime
    # rather than by run length.
    pool_kwargs: dict[str, Any] = {"max_workers": args.processes}
    if args.max_tasks_per_child:
        try:
            ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1).shutdown()
            pool_kwargs["max_tasks_per_child"] = args.max_tasks_per_child
        except TypeError:  # pragma: no cover - Python < 3.11
            print("  (max_tasks_per_child unsupported on this Python; relying on cache release)")

    with ProcessPoolExecutor(**pool_kwargs) as pool:
        futures = {
            pool.submit(_warm_one_day, {**payload_base, "day": day}): day
            for day in days
        }
        for fut in as_completed(futures):
            day = futures[fut]
            # The cache volume is the system disk and it starts near full. A warm
            # that runs for hours must not be the thing that fills it - a wedged
            # Windows volume is a far worse outcome than a partial warm, and the
            # warm is resumable (a cached (date, query) is skipped on the rerun)
            # while the disk is not.
            free_gb = _free_gb(_cache_volume())
            if free_gb < args.min_free_gb:
                print(f"\nABORT: {free_gb:.1f} GB free < --min-free-gb {args.min_free_gb}. "
                      f"{done} day(s) already written are kept; rerun to resume.", flush=True)
                aborted = True
                for pending in futures:
                    pending.cancel()
                break
            try:
                res = fut.result()
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{day}: {type(exc).__name__}: {exc}")
                continue
            done += 1
            rows += res["rows"]
            excel_touches += res["excel"]
            if res["error"]:
                failures.append(f"{res['day']}: {res['error']}")
            if done % args.log_every == 0 or done == len(days):
                el = time.perf_counter() - started
                rate = done / max(el, 1e-9)
                eta = (len(days) - done) / max(rate, 1e-9)
                print(
                    f"  {done}/{len(days)} days  {rows:,} rows  "
                    f"{el / 60:.1f} min elapsed  ETA {eta / 60:.1f} min  "
                    f"({res['elapsed']:.1f}s last day)",
                    flush=True,
                )

    el = time.perf_counter() - started
    status = "ABORTED (disk)" if aborted else "done"
    print(f"\n{status}: {done}/{len(days)} days, {rows:,} rows, {el / 3600:.2f} h, "
          f"{_free_gb(_cache_volume()):.1f} GB free")
    if excel_touches:
        # Expect roughly one per worker PROCESS, not per day: the published-fixings
        # lookup asks Excel once per process, fails, warns, and re-serves the cached
        # series (CITIVELO_EXCEL/fixings.py degrades on CitiVelocityError). That is
        # the degrade working. A count that scales with DAYS means something else -
        # a requested date the cube store could not serve - and the day list is
        # built to make that impossible, so it would be a real bug.
        expected = args.processes * (1 + (len(days) // max(args.max_tasks_per_child or len(days), 1)))
        verdict = "consistent with the per-process fixings degrade" if excel_touches <= expected else \
                  "MORE than the fixings degrade explains - investigate"
        print(f"Excel COM attempts: {excel_touches} (<= ~{expected} expected) - {verdict}.")
    if failures:
        print(f"{len(failures)} day(s) failed:")
        for line in failures[:20]:
            print(f"  {line}")
    return 1 if failures else 0


def _date(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__ or "", formatter_class=argparse.RawDescriptionHelpFormatter
    )

    def common(sub):
        sub.add_argument("--curve-name", default=CURVE)
        sub.add_argument("--source", default="CITIVELO-RL")
        sub.add_argument(
            "--curve-source", default="citivelo_excel_rl",
            help="The value cache stem contains this. Two settings cache separately.",
        )
        sub.add_argument("--start", type=_date, default=dt.date(2020, 1, 24))
        sub.add_argument("--end", type=_date, default=dt.date.today())
        sub.add_argument("--shorthands", nargs="+", default=list(DEFAULT_SHORTHANDS))
        sub.add_argument("--strikes", nargs="+", default=list(DEFAULT_STRIKES))
        sub.add_argument("--values", nargs="+", default=list(DEFAULT_VALUES))
        sub.add_argument("--naming", choices=("named", "unnamed", "both"), default="both")
        sub.add_argument("--n-jobs", type=int, default=4,
                         help="Threads WITHIN a day. Measured flat above 4.")
        sub.add_argument("--processes", type=int, default=10,
                         help="Days priced concurrently. This is the lever that works.")

    sub = p.add_subparsers(dest="command", required=True)

    w = sub.add_parser("warm", help="price the grid over the day range")
    common(w)
    w.add_argument("--dry-run", action="store_true", help="print the projection and stop")
    w.add_argument("--log-every", type=int, default=10)
    w.add_argument("--max-tasks-per-child", type=int, default=40,
                   help="Recycle each worker after N days, to bound memory. 0 disables. "
                        "Worker memory, not cache size, is what fills the disk here - it "
                        "grows the pagefile.")
    w.add_argument("--min-free-gb", type=float, default=4.0,
                   help="Abort (keeping what is written) if the cache volume drops below this. "
                        "The cache lives on the system disk.")
    w.set_defaults(func=cmd_warm)

    v = sub.add_parser("verify", help="prove the memo is bit-identical on real days")
    common(v)
    v.add_argument("--days", type=int, default=3)
    v.add_argument("--verify-shorthands", type=int, default=3,
                   help="how many of the grid's shorthands to check")
    v.set_defaults(func=cmd_verify)

    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

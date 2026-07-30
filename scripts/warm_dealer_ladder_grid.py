"""Warm the DECISION-GRID curve minutes for the whole study window. Resumable.

Why this is a separate step rather than something the gates do on the way past.

The backfill warms the minutes prints actually happened at (~445 per session). The
decision grid is a different set — 5-minute marks across the session — and a grid minute
absent from an otherwise-present store partition falls through to a full single-point
build. Measured on the SOFR ladder curve while the backfill was running: 6.8s, 2.4s and
57.9s for three January minutes, against 0.02s for the fully-warmed FF curve. At ~97
grid minutes across ~138 sessions that is ~13,400 single-point builds, each costing ~24
Barchart requests against a ~55-per-rolling-minute origin limit.

`warm_decision_grid` avoids that by fetching the whole session once per curve
(`bulk_get_data`, ~60 requests) and serving every grid minute from those bars, then
persisting the calibrated day so a re-run is a local Parquet read. This script drives it
session by session with a resume ledger, so an interruption costs one session.

**Run it AFTER the classify/project backfill has finished, not alongside.** Both draw on
the same Barchart origin quota, and the rate limiter is constructed per API call rather
than per process, so two warm fronts simply burst through the ceiling and park every
worker in Retry-After sleeps — measured at ~5% CPU with nineteen sockets open and no
progress at all.

    conda run -n stir python scripts/warm_dealer_ladder_grid.py \
        --start 2026-01-12 --end 2026-07-29 --ledger warm_grid.jsonl
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402


def _load_ledger(path):
    """Sessions already warmed, keyed (day, curve). Read before anything is built."""
    done = set()
    if not path or not os.path.exists(path):
        return done
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("ok"):
                done.add((rec["day"], rec["curve"]))
    return done


def _append(path, rec):
    if not path:
        return
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=lambda s: datetime.date.fromisoformat(s),
                    required=True)
    ap.add_argument("--end", type=lambda s: datetime.date.fromisoformat(s),
                    required=True)
    ap.add_argument("--ledger", default=None,
                    help="JSONL resume ledger; a session recorded ok is skipped")
    ap.add_argument("--warm-jobs", type=int, default=8,
                    help="threads for the per-minute mop-up after the bulk seed")
    ap.add_argument("--spaces", default="FUTURES,FED_FUNDS")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the work and exit without touching the vendor")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    from BT.dealer_ladder import config as cfg, data, gates
    from SDRUtils.stir_flow import config as sconfig
    from SDRUtils.stir_flow.pricing import CurvePricer

    conf = cfg.LadderStudyConfig()
    window = (args.start, args.end)
    # `trading_days` yields Timestamps while the grid mask is built from `.date`
    # objects, and `Timestamp == date` is False, so without this normalisation every
    # session silently warms ZERO minutes and the run reports success in 0.0s.
    days = [pd.Timestamp(d).date() for d in data.trading_days(window)]
    grid = data.decision_grid(days, conf.signal)
    et = pd.DatetimeIndex(grid).tz_convert("America/New_York")
    by_day = pd.Series(et.date, index=pd.DatetimeIndex(grid))
    if len(grid):
        covered = set(by_day)
        missing = [d for d in days if d not in covered]
        if missing:
            raise SystemExit(
                f"{len(missing)} sessions have no decision-grid minutes "
                f"(first {missing[0]}) — the day key does not match the grid")

    spaces = [s.strip() for s in args.spaces.split(",") if s.strip()]
    curves = {s: sconfig.CURVE_FOR["SOFR" if s == "FUTURES" else "FED_FUNDS"]
              for s in spaces}
    done = _load_ledger(args.ledger)

    todo = [(day, space) for day in days for space in spaces
            if (str(day), curves[space]) not in done]
    print(f"{len(days)} sessions x {len(spaces)} curves = {len(days) * len(spaces)} "
          f"session-curves; {len(done)} already recorded, {len(todo)} to warm")
    print(f"decision grid: {len(grid)} minutes total "
          f"({len(grid) / max(len(days), 1):.0f} per session)")
    for space, curve in curves.items():
        print(f"  {space}: {curve}")
    if args.dry_run:
        return 0

    pricer = CurvePricer()
    totals = {"bulk_seeded": 0, "built": 0, "reused": 0, "failed": 0}
    t_start = time.perf_counter()
    for i, (day, space) in enumerate(todo, 1):
        curve = curves[space]
        minutes = pd.DatetimeIndex(grid)[(by_day == day).to_numpy()]
        t0 = time.perf_counter()
        try:
            res = gates.warm_decision_grid(pricer, curve, minutes,
                                           warm_jobs=args.warm_jobs, verbose=False)
            ok = True
        except Exception as exc:                      # one session must not stop the run
            res = {"error": f"{type(exc).__name__}: {exc}"}
            ok = False
        dt = time.perf_counter() - t0
        for k in totals:
            totals[k] += int(res.get(k, 0) or 0)
        rec = {"day": str(day), "curve": curve, "space": space, "ok": ok,
               "seconds": round(dt, 2), "minutes": len(minutes), **res}
        _append(args.ledger, rec)
        rate = (time.perf_counter() - t_start) / i
        eta = rate * (len(todo) - i) / 60.0
        print(f"[{i}/{len(todo)}] {day} {space:9s} {dt:7.1f}s  "
              f"{ {k: v for k, v in res.items() if k != 'reused'} }  "
              f"ETA {eta:.0f}min", flush=True)

        # Freeing handles keeps memory flat across ~138 sessions; the store is the
        # cache that matters, and it is on disk.
        pricer._handles.clear()

    print(f"\ndone in {(time.perf_counter() - t_start) / 60:.1f}min: {totals}")
    return 0 if totals["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

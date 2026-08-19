r"""Warm the CurveStore with historical EOD Citi Velocity curves.

    conda run -n stir python scripts/citivelo_excel_warm.py warm
    conda run -n stir python scripts/citivelo_excel_warm.py warm --curves USD-SOFR-1D --start 2020-01-01
    conda run -n stir python scripts/citivelo_excel_warm.py status

Runs entirely **offline** against the banked tag cache - no Excel, no network.
Interruptible and resumable: days already in the store are skipped unless
``--force``, and each day is written atomically.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import pathlib
import re
import sys

# ``--push-l2`` used to be a DEAD FLAG. ``ARBS_SUPABASE_ENABLED`` is read once,
# at ``Caching.supabase_engine`` import time, and this line runs long before
# argparse does - so ``_get_curve_sync`` returned None whatever the flag said and
# ``write_day(push_l2=True)` pushed nothing. Sniffing argv here is ugly, but the
# alternative is a flag that silently does nothing, which is worse. The default is
# unchanged: local-only unless asked.
_WANT_L2 = "--push-l2" in sys.argv
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "1" if _WANT_L2 else "0")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_CURVES = "USD-SOFR-1D,EUR-ESTR-1D,JPY-TONAR-1D,CAD-CORRA-1D,GBP-SONIA-1D"


def _curves(arg: str):
    return [c.strip().upper() for c in arg.split(",") if c.strip()]


def cmd_warm(args) -> int:
    from MDP.IRSwaps.CITIVELO_EXCEL import register
    from MDP.IRSwaps.CITIVELO_EXCEL.warm import warm_many

    register()
    if args.push_l2:
        from Caching.supabase_engine import SUPABASE_ENABLED, get_database_url

        target = re.sub(r"//[^@]+@", "//<redacted>@", get_database_url() or "")
        logging.getLogger(__name__).warning(
            "--push-l2: SUPABASE_ENABLED=%s target=%s. Each written day is pushed as a "
            "whole-day blob. For a bulk backfill prefer scripts/citivelo_l2_sync.py, "
            "which diffs by content and bounds its connection count.",
            SUPABASE_ENABLED, target,
        )
        if not SUPABASE_ENABLED:
            logging.getLogger(__name__).error(
                "--push-l2 was asked for but SUPABASE_ENABLED is False. Something "
                "imported Caching before this script set the env var; the push would "
                "silently do nothing, so refusing instead."
            )
            return 2
    stats = warm_many(
        _curves(args.curves),
        start=datetime.date.fromisoformat(args.start) if args.start else None,
        end=datetime.date.fromisoformat(args.end) if args.end else None,
        min_tenors=args.min_tenors,
        force=args.force,
        push_l2=args.push_l2,
    )
    total = sum(s.written for s in stats.values())
    print(f"\nwrote {total} curve-days across {len(stats)} curve(s)")

    # A curve that wrote nothing AND kept nothing warmed nothing at all. Say so
    # even when the run "succeeded": ``total`` is a sum across curves, so one
    # curve writing masks four writing nothing - which is exactly what happened
    # on 2026-08-15, when USD wrote 2 days, the other four curves were stale
    # since 2026-08-07, and this returned 0.
    idle = [s for s in stats.values() if not s.written and not s.skipped_existing]
    for s in idle:
        reason = s.errors[0] if s.errors else "no reason recorded"
        print(f"  WARMED NOTHING: {s.curve_name}: {reason}", flush=True)

    if total or all(s.skipped_existing for s in stats.values()):
        return 0
    # The exit code has to carry a cause. Printing it LAST is what puts it in
    # front of a caller that keeps only the child's final line.
    lead = idle[0] if idle else next(iter(stats.values()))
    why = lead.errors[0] if lead.errors else "no reason recorded"
    print(f"nothing written and nothing already present: {lead.curve_name}: {why}", flush=True)
    return 1


def cmd_status(args) -> int:
    from MDP.IRSwaps.CITIVELO_EXCEL.warm import warm_status

    frame = warm_status(_curves(args.curves))
    print(frame.to_string(index=False))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    sub = parser.add_subparsers(dest="command", required=True)

    w = sub.add_parser("warm")
    w.add_argument("--curves", default=DEFAULT_CURVES)
    w.add_argument("--start", default="")
    w.add_argument("--end", default="")
    w.add_argument("--min-tenors", type=int, default=20)
    w.add_argument("--force", action="store_true")
    w.add_argument("--push-l2", action="store_true")
    w.set_defaults(func=cmd_warm)

    s = sub.add_parser("status")
    s.add_argument("--curves", default=DEFAULT_CURVES)
    s.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

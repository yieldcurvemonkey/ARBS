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
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

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
    return 0 if total or all(s.skipped_existing for s in stats.values()) else 1


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

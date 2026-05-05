"""CLI entry point for the STIR Options Asymmetric Screener.

Usage:
    python -m scripts.stir_asymmetric_screener --as-of 2026-04-28
    python -m scripts.stir_asymmetric_screener --as-of 2026-04-28 \
        --archetypes wing wide_vertical
    python -m scripts.stir_asymmetric_screener --as-of 2026-04-28 \
        --underlyings SR3 \
        --dte-floor 30 --dte-ceiling 200
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys

from RVUtils.STIRAsymmetricScreener import (
    ArchetypeType,
    ScreenerConfig,
    build_snapshot,
)
from RVUtils.STIRAsymmetricScreener._output import write_snapshot


def _date_from_iso(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="STIR Asymmetric Screener")
    parser.add_argument("--as-of", required=True, type=_date_from_iso)
    parser.add_argument(
        "--underlyings",
        nargs="*",
        default=None,
        help="One or more of SR3, SR1, ER (default: all three).",
    )
    parser.add_argument(
        "--archetypes",
        nargs="*",
        default=None,
        help="Subset of archetypes to enumerate (default: all 8).",
    )
    parser.add_argument("--dte-floor", type=int, default=None)
    parser.add_argument("--dte-ceiling", type=int, default=None)
    parser.add_argument("--include-midcurves", action="store_true", default=None)
    parser.add_argument("--no-include-midcurves", dest="include_midcurves", action="store_false")
    parser.add_argument("--include-serials", action="store_true", default=None)
    parser.add_argument("--no-include-serials", dest="include_serials", action="store_false")
    parser.add_argument(
        "--out",
        default="data/screener_results/stir_asymmetric_screener",
        help="Output root directory.",
    )
    parser.add_argument(
        "--format", choices=["parquet", "csv"], default="parquet"
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    cfg = ScreenerConfig()
    if args.underlyings:
        cfg.underlyings = tuple(args.underlyings)
    if args.archetypes:
        cfg.archetypes = tuple(ArchetypeType(a) for a in args.archetypes)
    if args.dte_floor is not None:
        cfg.dte_floor = args.dte_floor
    if args.dte_ceiling is not None:
        cfg.dte_ceiling = args.dte_ceiling
    if args.include_midcurves is not None:
        cfg.include_midcurves = args.include_midcurves
    if args.include_serials is not None:
        cfg.include_serials = args.include_serials

    snap = build_snapshot(cfg, as_of=args.as_of)
    path = write_snapshot(snap, root=args.out, fmt=args.format)
    print(f"wrote {len(snap.results)} candidates to {path}")
    if snap.run_warnings:
        print(f"warnings: {len(snap.run_warnings)} (first 5):")
        for w in snap.run_warnings[:5]:
            print(f"  - {w}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

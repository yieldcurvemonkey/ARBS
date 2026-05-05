"""CLI entry point for the SR3 vs ZQ distribution-comparison screener.

Usage:
    python -m scripts.sr3_zq_distribution_screener --as-of 2026-05-04
    python -m scripts.sr3_zq_distribution_screener --as-of 2026-05-04 \\
        --contracts SFRU26 SFRZ26 SFRH27
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys

from RVUtils.SR3ZQDistributionScreener import (
    DistributionScreenerConfig,
    build_snapshot,
)
from RVUtils.SR3ZQDistributionScreener._output import write_snapshot


def _date_from_iso(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SR3 vs ZQ Distribution Screener")
    parser.add_argument("--as-of", required=True, type=_date_from_iso)
    parser.add_argument(
        "--contracts",
        nargs="*",
        default=None,
        help="SR3 contracts to evaluate (default: auto-resolve nearest 4 quarterlies).",
    )
    parser.add_argument("--dte-floor", type=int, default=None)
    parser.add_argument("--dte-ceiling", type=int, default=None)
    parser.add_argument("--no-lambda-opt", action="store_true")
    parser.add_argument(
        "--out",
        default="data/screener_results/sr3_zq_distribution_screener",
    )
    parser.add_argument("--format", choices=["parquet", "csv"], default="parquet")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    cfg = DistributionScreenerConfig()
    if args.contracts:
        cfg.sr3_contracts = tuple(args.contracts)
    if args.dte_floor is not None:
        cfg.dte_floor = args.dte_floor
    if args.dte_ceiling is not None:
        cfg.dte_ceiling = args.dte_ceiling
    if args.no_lambda_opt:
        cfg.optimize_lambda = False

    snap = build_snapshot(cfg, as_of=args.as_of)
    path = write_snapshot(snap, root=args.out, fmt=args.format)
    print(f"wrote {len(snap.records)} records to {path}")
    if snap.run_warnings:
        print(f"warnings ({len(snap.run_warnings)} total, first 5):")
        for w in snap.run_warnings[:5]:
            print(f"  - {w}")

    print("\n=== Records ===")
    for r in snap.records:
        print(
            f"{r.sr3_contract} dte={r.sr3_dte:>3} "
            f"fwd={r.forward_rate:.4f}% "
            f"resid_ratio={r.residual_to_explained_ratio:.1f} "
            f"skew={r.sr3_skew:+.3f} "
            f"tail+50={r.tail_upper_50:.3f} "
            f"regime={r.regime_bucket.value} "
            f"flags={[f.kind.value for f in r.flags]}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

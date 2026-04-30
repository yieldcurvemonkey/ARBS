"""Find SFR Convex Screener structures that fade near-term-hike pricing
with positive convexity.

For a given as_of, builds the snapshot and filters for structures whose
preferred trade direction is *long-price / short-rate* (i.e. asymmetry
ratio < 1, so the screener flips the canonical long-rate enumeration).
That side of the trade pays when rates rally — exactly the bet that
the market has over-priced hikes.

Reports the top structures by composite_score on the long-price side,
plus any calendar / butterfly that involves Z26 and/or M27 (the user's
target spread).

Usage::

    conda run -n stir python scripts/_fade_hikes.py --as-of 2026-04-29
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys
from pathlib import Path
from typing import Any, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fade_hikes")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from RVUtils.SFRConvexScreener import (  # noqa: E402
    JointMethod,
    SFRConvexScreenerConfig,
    SFRConvexScreenerSnapshot,
    StructureType,
)
from RVUtils.SFRConvexScreener.screener import build_snapshot  # noqa: E402


def _make_cfg() -> SFRConvexScreenerConfig:
    return SFRConvexScreenerConfig(
        universe_size=12,
        include_outrights=True,
        jpm_method=True,
        primary_joint_method=JointMethod.HISTORICAL_GAUSSIAN_COPULA,
        joint_methods=(
            JointMethod.HISTORICAL_GAUSSIAN_COPULA,
            JointMethod.PERFECT_CORRELATION,
        ),
        correlation_window=60,
        n_simulations=50_000,
    )


def _row_for(r: Any) -> dict:
    """Compact summary of a StructureResult for ranking + display."""
    primary = r.metrics_by_method.get(r.primary_method)
    asym = float(getattr(primary, "asymmetry_ratio", float("nan"))) if primary else float("nan")
    return {
        "structure_id": r.structure_def.structure_id,
        "structure_type": r.structure_def.structure_type.value,
        "direction": r.direction(),
        "rank": r.rank,
        "composite_score": float(r.composite_score),
        "asymmetry_ratio": asym,
        # asymmetry_ratio < 1 -> long-price bias (fade-hikes side)
        "long_price_side": (asym < 1.0) if asym == asym else False,
        "asym_long_price_units": (1.0 / asym) if (asym == asym and asym > 0) else float("nan"),
        "p_profit": float(getattr(primary, "p_profit", float("nan"))) if primary else float("nan"),
        "expected_value_bp": float(getattr(primary, "expected_value_bp", float("nan"))) if primary else float("nan"),
        "carry_3m_bp": float(r.carry_3m_bp),
        "rolldown_bp": float(r.rolldown_bp),
        "leg_contracts": [l.contract for l in r.structure_def.legs],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", required=True)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--targets", nargs="*", default=("SFRZ26", "SFRM27"),
                   help="Highlight structures whose legs include any of these contracts")
    args = p.parse_args()

    as_of = datetime.date.fromisoformat(args.as_of)
    cfg = _make_cfg()

    print(f"\n=== fade-hikes scan @ {as_of} ===")
    snap: SFRConvexScreenerSnapshot = build_snapshot(cfg, as_of=as_of)
    print(f"results={len(snap.results)} | run_warnings={len(snap.run_warnings)}")
    if snap.run_warnings:
        for w in list(snap.run_warnings)[:10]:
            print(f"  - {w}")
    if not snap.results:
        return 1

    rows = [_row_for(r) for r in snap.results]
    rows.sort(key=lambda r: r["composite_score"], reverse=True)

    # 1) Top-K composite (any direction) — gives the screener's overall view.
    print(f"\n=== top-{args.top_k} by composite_score (any direction) ===")
    print(f"{'rank':>4} {'asym':>7} {'p_prof':>6} {'ev_bp':>7} {'score':>7}  {'direction'}")
    for r in rows[: args.top_k]:
        print(f"{r['rank']:>4} {r['asymmetry_ratio']:>7.3f} {r['p_profit']:>6.2f} "
              f"{r['expected_value_bp']:>7.2f} {r['composite_score']:>7.3f}  {r['direction']}")

    # 2) Long-price (fade-hikes) side filtered.
    long_price = [r for r in rows if r["long_price_side"]]
    long_price.sort(key=lambda r: r["asym_long_price_units"], reverse=True)
    print(f"\n=== top-{args.top_k} fade-hikes (long-price / RECEIVE) by long-price asym units ===")
    print(f"{'asym_lp':>8} {'p_prof':>6} {'ev_bp':>7} {'score':>7}  {'direction'}")
    for r in long_price[: args.top_k]:
        print(f"{r['asym_long_price_units']:>8.2f} {r['p_profit']:>6.2f} "
              f"{r['expected_value_bp']:>7.2f} {r['composite_score']:>7.3f}  {r['direction']}")

    # 3) Anything involving the user's target legs.
    target_set = {t.upper() for t in args.targets}
    print(f"\n=== structures touching {sorted(target_set)} ===")
    print(f"{'asym':>7} {'asym_lp':>7} {'p_prof':>6} {'ev_bp':>7} {'score':>7}  {'type':<10} {'direction'}")
    for r in rows:
        if any(c.upper() in target_set for c in r["leg_contracts"]):
            print(f"{r['asymmetry_ratio']:>7.3f} {r['asym_long_price_units']:>7.2f} "
                  f"{r['p_profit']:>6.2f} {r['expected_value_bp']:>7.2f} "
                  f"{r['composite_score']:>7.3f}  {r['structure_type']:<10} {r['direction']}")

    # 4) Calendar / fly subset for fade-hikes (asym < 1) only.
    convex_fade = [
        r for r in rows
        if r["long_price_side"]
        and r["structure_type"] in {"calendar", "butterfly"}
    ]
    convex_fade.sort(key=lambda r: r["asym_long_price_units"], reverse=True)
    print(f"\n=== convex fade-hikes (calendar / butterfly with asym < 1) — top {args.top_k} ===")
    print(f"{'asym_lp':>8} {'p_prof':>6} {'ev_bp':>7} {'score':>7}  {'type':<10} {'direction'}")
    for r in convex_fade[: args.top_k]:
        print(f"{r['asym_long_price_units']:>8.2f} {r['p_profit']:>6.2f} "
              f"{r['expected_value_bp']:>7.2f} {r['composite_score']:>7.3f}  "
              f"{r['structure_type']:<10} {r['direction']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

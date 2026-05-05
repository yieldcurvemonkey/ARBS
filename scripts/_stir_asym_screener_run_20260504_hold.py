"""One-off run of the STIR asymmetric screener for 2026-05-04 close.

Thesis: FOMC holds the policy rate flat for the rest of 2026 (no cuts,
no hikes). We pass that as the *fair* cumulative path so the path-bias
signal triggers wherever the OIS curve is pricing meaningful moves.

Surfaces top-ranked candidates that benefit from this thesis playing out.
"""

from __future__ import annotations

import datetime
import logging
import sys

from RVUtils.STIRAsymmetricScreener import (
    ArchetypeType,
    ScreenerConfig,
    build_snapshot,
)
from RVUtils.STIRAsymmetricScreener._output import write_snapshot


_HOLD_FAIR_PATH_BP = (0.0,) * 32  # zero cumulative change at every meeting through 2027


def main():
    # Force unbuffered stdout so we see progress in real time
    sys.stdout.reconfigure(line_buffering=True)
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    cfg = ScreenerConfig(
        # Just the four near-quarterly SR3 contracts — quick scan
        underlyings=("SR3",),
        include_midcurves=False,
        include_serials=False,
        include_weeklies=False,
        # DTE band: 30d (skip near-zero-DTE noise) through Dec'26 IMM (~226d)
        dte_floor=30,
        dte_ceiling=240,
        archetypes=(
            ArchetypeType.WING,
            ArchetypeType.WIDE_VERTICAL,
            ArchetypeType.RATIO,
            ArchetypeType.LADDER,
            ArchetypeType.CONDOR,
            ArchetypeType.TREE,
        ),
    )

    as_of = datetime.date(2026, 5, 4)
    print(f"Running screener: as_of={as_of}, thesis=FOMC-holds-2026", flush=True)
    print(f"Universe: SR3 quarterlies only (no serials, no midcurves)", flush=True)
    print(f"DTE band: {cfg.dte_floor}-{cfg.dte_ceiling}", flush=True)
    print(f"Archetypes: {[a.value for a in cfg.archetypes]}", flush=True)

    snap = build_snapshot(cfg, as_of=as_of, fair_path_bp=_HOLD_FAIR_PATH_BP)

    print(
        f"\n--- DONE: universe_size={len(snap.config_summary)} "
        f"results={len(snap.results)} warnings={len(snap.run_warnings)}",
        flush=True,
    )

    df = snap.to_dataframe()
    if df.empty:
        print(f"WARNINGS: {list(snap.run_warnings[:5])}", flush=True)
        return

    out_path = write_snapshot(snap, root="data/screener_results/stir_asymmetric_screener", fmt="parquet")
    print(f"Wrote parquet: {out_path}", flush=True)

    cols = [
        "rank", "structure_type", "underlying", "dte",
        "asymmetry_ratio", "max_payoff", "max_loss", "net_premium",
        "composite_score",
    ]
    cols = [c for c in cols if c in df.columns]

    print("\n" + "=" * 80, flush=True)
    print(f"TOP 20 BY COMPOSITE SCORE  —  as_of=2026-05-04  —  THESIS: FOMC HOLDS 2026", flush=True)
    print("=" * 80, flush=True)
    print(df.head(20)[cols].to_string(index=False), flush=True)

    print("\n" + "-" * 80, flush=True)
    print("TOP 5 PER ARCHETYPE", flush=True)
    print("-" * 80, flush=True)
    for archetype in df["structure_type"].unique():
        subset = df[df["structure_type"] == archetype].head(5)
        if subset.empty:
            continue
        print(f"\n  {archetype}:", flush=True)
        print(subset[cols].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()

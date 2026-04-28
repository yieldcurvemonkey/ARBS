"""Quick run of the SFR Convex Screener with reduced correlation window.

Trades correlation accuracy for speed — useful to validate the pipeline.
"""

from __future__ import annotations

import datetime
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from RVUtils.SFRConvexScreener import (  # noqa: E402
    JointMethod,
    SFRConvexScreenerConfig,
    build_snapshot,
    write_snapshot,
)


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)

    as_of = datetime.date.today()
    cfg = SFRConvexScreenerConfig(
        universe_size=12,
        calendar_gaps=(1, 2, 4),
        fly_gaps=(1, 2, 4),
        primary_joint_method=JointMethod.COMMON_STATE,
        correlation_window=10,  # smaller for speed
        n_simulations=20_000,
    )
    print(f"=== SFR Convex Screener — as_of={as_of} ===", flush=True)
    snap = build_snapshot(cfg, as_of=as_of)

    print(f"\n{len(snap.results)} structures ranked", flush=True)
    if snap.run_warnings:
        print("\nrun warnings:", flush=True)
        for w in snap.run_warnings[:20]:
            print(f"  {w}", flush=True)

    df = snap.to_dataframe()
    if df.empty:
        print("no structures to display", flush=True)
        return

    df = df.sort_values("composite_score", ascending=False)
    cols = [
        "rank", "structure_id", "type", "composite_score",
        "asymmetry_ratio", "p_profit", "mean_bp", "std_bp",
        "skew", "tail_ratio", "carry_3m_bp", "rolldown_3m_bp",
        "primary_method",
    ]
    cols = [c for c in cols if c in df.columns]

    print("\n=== Top 20 by composite score ===", flush=True)
    print(df[cols].head(20).to_string(index=False), flush=True)

    print("\n=== Top 10 by asymmetry ratio alone ===", flush=True)
    print(df.sort_values("asymmetry_ratio", ascending=False)[cols].head(10).to_string(index=False), flush=True)

    paths = write_snapshot(snap, root_dir=Path(cfg.output_root))
    print("\nwritten:", flush=True)
    for k, p in paths.items():
        print(f"  {k}: {p}", flush=True)


if __name__ == "__main__":
    main()

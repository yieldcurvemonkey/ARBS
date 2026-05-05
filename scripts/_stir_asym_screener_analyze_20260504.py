"""Post-process the 2026-05-04 hold-thesis screener output.

Filter to realistic trades (premium ≥ 1 tick, asymmetry ratio in 4–50 range)
and present per-archetype top picks aligned with the FOMC-holds-2026 thesis.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


def main():
    sys.stdout.reconfigure(line_buffering=True)
    parquet_path = Path("data/screener_results/stir_asymmetric_screener/2026-05-04/snapshot.parquet")
    if not parquet_path.exists():
        print(f"NOT FOUND: {parquet_path}")
        return

    df = pd.read_parquet(parquet_path)
    print(f"Loaded {len(df)} candidates from {parquet_path}", flush=True)
    print(f"Underlyings present: {sorted(df['underlying'].unique())}", flush=True)
    print(f"Archetypes: {sorted(df['structure_type'].unique())}", flush=True)
    print(f"DTE range: {df['dte'].min()} - {df['dte'].max()}", flush=True)

    # Filter 1: realistic premium (>= 1 tick = actually quotable)
    has_premium = df["net_premium"].abs() >= 1.0
    # Filter 2: asymmetry in usable range (4-50, not model-artifact 3000+)
    sane_asymm = (df["asymmetry_ratio"] >= 4.0) & (df["asymmetry_ratio"] <= 50.0)
    # Filter 3: max_loss is real downside (not zero)
    real_loss = df["max_loss"] < -1.0

    realistic = df[has_premium & sane_asymm & real_loss].copy()
    print(f"\nAfter filtering for realistic premium/asymmetry: {len(realistic)} candidates", flush=True)

    if realistic.empty:
        print("(no realistic candidates after filters; using full set)", flush=True)
        realistic = df.copy()

    realistic = realistic.sort_values("asymmetry_ratio", ascending=False)

    # Add legs as a column readable in print
    import json as _json

    def _legs_str(legs):
        if isinstance(legs, str):
            try:
                legs = _json.loads(legs)
            except Exception:
                return legs
        if not isinstance(legs, list):
            return ""
        parts = []
        for leg in legs:
            qty = leg.get("quantity", 0)
            sign = "+" if qty > 0 else ""
            parts.append(f"{sign}{qty}{leg['right']}{leg['strike']:.4f}".rstrip("0").rstrip("."))
        return " | ".join(parts)

    if "legs" in realistic.columns:
        realistic["legs_str"] = realistic["legs"].apply(_legs_str)

    cols = [
        "rank", "structure_type", "underlying", "dte",
        "asymmetry_ratio", "max_payoff", "max_loss", "net_premium",
        "legs_str",
    ]
    cols = [c for c in cols if c in realistic.columns]

    pd.set_option("display.max_colwidth", 200)
    pd.set_option("display.width", 220)

    print("\n" + "=" * 90, flush=True)
    print("THESIS: FOMC HOLDS RATES 2026 (no cuts, no hikes)", flush=True)
    print("Trade idea filter: net_premium ≥ 1 tick, asymmetry 4-50:1, real max_loss", flush=True)
    print("=" * 90, flush=True)

    print("\nTOP 10 OVERALL BY ASYMMETRY RATIO:", flush=True)
    print(realistic.head(10)[cols].to_string(index=False), flush=True)

    print("\n" + "-" * 90, flush=True)
    print("TOP 5 PER ARCHETYPE", flush=True)
    print("-" * 90, flush=True)
    for archetype in ["wing", "wide_vertical", "ratio", "ladder", "tree", "condor"]:
        subset = realistic[realistic["structure_type"] == archetype]
        if subset.empty:
            print(f"\n{archetype}: (no realistic candidates)", flush=True)
            continue
        print(f"\n{archetype}:", flush=True)
        print(subset.head(5)[cols].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()

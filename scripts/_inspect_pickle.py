"""Inspect a screener cache pickle without going through the cache API."""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("pkl", help="Path to a screener-cache .pkl")
    p.add_argument("--top-k", type=int, default=10)
    args = p.parse_args()

    with open(args.pkl, "rb") as fh:
        snap = pickle.load(fh)
    print(f"as_of:           {snap.as_of}")
    print(f"config_summary:  {snap.config_summary}")
    print(f"n_results:       {len(snap.results)}")
    print(f"run_warnings:    {len(snap.run_warnings)}")
    if snap.run_warnings:
        for w in list(snap.run_warnings)[:5]:
            print(f"  - {w}")
    print(f"\ntop {args.top_k} by composite_score:")
    print(f"{'rank':>4} {'structure_id':<40} {'asym':>8} {'score':>8}")
    sorted_r = sorted(snap.results, key=lambda r: r.composite_score, reverse=True)
    for r in sorted_r[: args.top_k]:
        primary = r.metrics_by_method.get(r.primary_method)
        a = float(getattr(primary, "asymmetry_ratio", float("nan"))) if primary else float("nan")
        print(f"{r.rank:>4} {r.structure_def.structure_id:<40} {a:>8.3f} {r.composite_score:>8.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

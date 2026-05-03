"""Find legacy listed-mode cache pickles with no fallback warnings.

Lists each 60855039beb3-hashed pickle plus its as_of and warning count, so
the operator can pick a methodology-clean date to compare against the new
sparse-mode prime.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CACHE_ROOT = Path("data/screener_results/sfr_convex_screener_backtest_cache")


def main() -> int:
    rows = []
    for p in sorted(CACHE_ROOT.glob("*60855039beb3.pkl")):
        try:
            with p.open("rb") as fh:
                snap = pickle.load(fh)
        except Exception as exc:
            print(f"{p.name}: load_failed: {exc!r}")
            continue
        n_warn = len(snap.run_warnings)
        n_fallback = sum(1 for w in snap.run_warnings if "fallback" in w)
        n_fail = sum(1 for w in snap.run_warnings if "failed" in w.lower())
        rows.append((snap.as_of, n_warn, n_fallback, n_fail, p.name))
    rows.sort()
    print(f"{'as_of':12} {'#warn':>5} {'#fbk':>4} {'#fail':>5}  {'file'}")
    for r in rows:
        print(f"{str(r[0]):12} {r[1]:>5} {r[2]:>4} {r[3]:>5}  {r[4]}")
    print(f"\nclean (0 warnings): {sum(1 for r in rows if r[1] == 0)} of {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

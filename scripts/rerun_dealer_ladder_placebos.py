#!/usr/bin/env python
"""Re-run G4-primary and the placebo suite only, to re-measure the placebos on GROSS.

The placebo fix (gross alongside net) landed after the main gate run had already loaded its
code, so that run's `g4_placebos.csv` carries net only and the gross column in the findings
doc is derived arithmetic rather than a measurement. This re-runs the two stages that produce
it and nothing else.

Everything expensive is skipped. G0's label study is ~99 minutes and answers a question about
the input that this does not change; G1-G3 and the secondary grid are untouched by the placebo
reporting fix. What remains is `load_context` -- fast once the bars and curve caches are warm --
plus the primary and the six placebos, which together run in well under a minute.

The primary is re-run because `run_placebos` takes the reference row from it VERBATIM. Building
the reference here instead would make it match the real primary only by coincidence: this path
rebuilds the signal from `rates.columns` while `load_context` built it from the contract
calendar, and those sets differ whenever a contract returned no bars.

Writes to its OWN results directory by default, so it can never half-overwrite the artifacts of
the run whose verdict is already published.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results-dir", required=True,
                    help="where to write g4_placebos.csv (use a fresh directory)")
    ap.add_argument("--bars-cache", default=None)
    ap.add_argument("--session-quality", action="store_true",
                    help="apply the per-session data-quality gate")
    args = ap.parse_args()

    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    from BT.dealer_ladder import config as cfg, data, gates, session_quality

    conf = cfg.LadderStudyConfig(
        session_quality=session_quality.SessionQualityConfig(
            enabled=bool(args.session_quality)))
    print(f"window {conf.window.start}..{conf.window.end}  "
          f"session-quality={'ON' if args.session_quality else 'OFF'}")
    print(f"results -> {args.results_dir}")
    os.makedirs(args.results_dir, exist_ok=True)

    conn = data.connect()
    t0 = time.time()
    ctx = gates.load_context(conn, conf, results_dir=args.results_dir,
                             show_progress=True, bars_cache=args.bars_cache)
    print(f"context loaded in {time.time() - t0:.0f}s")

    t0 = time.time()
    primary = gates.run_primary(ctx, in_sample=True, claim_lockout=False)
    v = primary.get("verdict", {})
    print(f"[G4-primary] {time.time() - t0:.0f}s  {v.get('headline', '')}")

    t0 = time.time()
    plac = gates.run_placebos(ctx, primary=primary)
    frame = plac.get("placebos")
    print(f"[G4-placebos] {time.time() - t0:.0f}s")
    if frame is not None and len(frame):
        cols = [c for c in ("placebo", "mean", "t", "gross_mean", "gross_t", "gross_stars",
                            "n", "share_long") if c in frame.columns]
        print(frame[cols].to_string(index=False))
        if "gross_mean" not in frame.columns:
            print("\n  WARNING: no gross_mean column -- this process is running code that "
                  "predates the placebo fix, so nothing was re-measured.")
            return 2
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

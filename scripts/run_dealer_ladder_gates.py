"""Run the dealer-ladder gate protocol and write every artifact to CSV.

Split from the notebook on purpose, the repo's convention: the heavy lifting runs
here (curve warming, vendor bars, thousands of solves, bootstraps) and the notebook
reads the CSVs and renders. That keeps the notebook's execution to seconds, which
is what makes an EXECUTED notebook a reviewable artifact rather than a several-hour
job that nobody re-runs.

    python scripts/run_dealer_ladder_gates.py [--start D] [--end D]
        [--results-dir DIR] [--label-limit N] [--lockout] [--skip-grid]

``--lockout`` is off by default and must be passed deliberately: the holdout is
evaluated ONCE, and by the pre-registered burn rule a failure there burns the
configuration.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd


def _date(s):
    return datetime.date.fromisoformat(s)


def main() -> int:
    from BT.dealer_ladder import config as cfg, data, gates

    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=_date, default=None)
    ap.add_argument("--end", type=_date, default=None)
    ap.add_argument("--lockout-start", type=_date, default=None)
    ap.add_argument("--results-dir", default=gates.RESULTS_DIRNAME)
    ap.add_argument("--label-limit", type=int, default=0,
                    help="hard cap on the independent-mid reclassification (0 = none)")
    ap.add_argument("--label-per-day", type=int, default=40,
                    help="time-of-day-stratified sample size per session for G0")
    ap.add_argument("--lockout", action="store_true",
                    help="ALSO evaluate the one-shot holdout (burn rule applies). "
                         "Claiming it writes LOCKOUT_USED.json; a later run under a "
                         "different specification is refused.")
    ap.add_argument("--lockout-note", default="",
                    help="recorded in LOCKOUT_USED.json alongside the claim")
    ap.add_argument("--force-lockout", action="store_true",
                    help="re-register against an ALREADY-BURNED holdout. Only with a "
                         "documented reason: the override is stamped into the ledger.")
    ap.add_argument("--bars-cache", default=None,
                    help="memoise the settled-window minute-bar pull here, "
                         "so a re-run costs nothing at the vendor")
    ap.add_argument("--skip-grid", action="store_true",
                    help="skip the secondary family (the slowest stage)")
    args = ap.parse_args()

    window = cfg.WindowConfig()
    if args.start or args.end or args.lockout_start:
        window = cfg.WindowConfig(
            start=args.start or window.start,
            end=args.end or window.end,
            lockout_start=args.lockout_start or window.lockout_start)
    conf = cfg.LadderStudyConfig(window=window)

    print(f"window {window.start}..{window.end}  lockout from {window.lockout_start}")
    print(f"results -> {args.results_dir}")

    conn = data.connect()
    t0 = time.time()
    ctx = gates.load_context(conn, conf, results_dir=args.results_dir,
                             show_progress=True, bars_cache=args.bars_cache)
    print(f"context loaded in {time.time() - t0:.0f}s: "
          f"{ctx.prints['unit_key'].nunique()} signed units, "
          f"{len(ctx.grid)} decisions")

    stages = []

    def stage(name, fn):
        t = time.time()
        try:
            out = fn()
            v = out.get("verdict") if isinstance(out, dict) else None
            print(f"[{name}] {time.time() - t:.0f}s  "
                  f"{v['headline'] if v else 'ok'}")
            stages.append((name, out))
            return out
        except Exception as exc:  # a stage failure must not lose the earlier ones
            import traceback
            traceback.print_exc(limit=8)
            print(f"[{name}] FAILED after {time.time() - t:.0f}s: {exc}")
            stages.append((name, {"verdict": {"gate": name, "pass": None,
                                              "headline": f"stage error: {exc}"}}))
            return {}

    from BT.dealer_ladder import study

    sink = study.TrialLedger()
    stage("G0", lambda: gates.run_g0(ctx, conn, label_limit=args.label_limit,
                                     label_per_day=args.label_per_day))
    stage("G1", lambda: gates.run_g1(ctx))
    stage("G2", lambda: gates.run_g2(ctx))
    stage("G3", lambda: gates.run_g3(ctx))
    primary = stage("G4-primary", lambda: gates.run_primary(ctx, in_sample=True))
    if primary.get("result") is not None and len(primary["result"]):
        sink.record("PRIMARY (in-sample)",
                    {"horizon": conf.primary.horizon_min,
                     "threshold": conf.primary.z_threshold},
                    {"mean": float(primary["result"]["mean"].iloc[0]),
                     "t": float(primary["result"]["t"].iloc[0])})
    stage("G4-staleness", lambda: gates.run_staleness_sensitivity(ctx))
    stage("G4-placebos", lambda: gates.run_placebos(ctx))
    stage("G4-label-free", lambda: gates.run_label_free(ctx))
    stage("G4-conditioning", lambda: gates.run_conditioning(ctx, primary))
    if not args.skip_grid:
        stage("G4-grid", lambda: gates.run_grid(ctx, sink))
    stage("G5", lambda: gates.run_g5(ctx, primary))
    if args.lockout:
        lock = stage("G4-LOCKOUT", lambda: gates.run_primary(
            ctx, in_sample=False, force_lockout=args.force_lockout,
            lockout_note=args.lockout_note))
        if lock.get("result") is not None and len(lock["result"]):
            sink.record("PRIMARY (LOCKOUT - one shot)", {},
                        {"mean": float(lock["result"]["mean"].iloc[0]),
                         "t": float(lock["result"]["t"].iloc[0])})

    verdicts = [out["verdict"] for _n, out in stages
                if isinstance(out, dict) and out.get("verdict")]
    os.makedirs(args.results_dir, exist_ok=True)
    pd.DataFrame(verdicts).to_csv(
        os.path.join(args.results_dir, "verdicts.csv"), index=False)
    sink.frame().to_csv(os.path.join(args.results_dir, "trial_ledger.csv"),
                        index=False)
    print()
    print("=" * 78)
    for v in verdicts:
        p = v.get("pass")
        word = "N/A " if p is None else ("PASS" if p else "FAIL")
        print(f"  {word}  {v['gate']:<22s} {v['headline']}")
    print("=" * 78)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

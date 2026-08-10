"""Dump the RAW event universe — before the overlap rule and before the data gate.

The configurable notebook needs this. The cached books (`events_manual_manual.pkl`)
were already reduced by ``drop_overlaps``, which keeps one position at a time and
drops whatever collides with it — 368 of 1,164 FED events on the manual build. A
notebook that filters *that* book to, say, voters only is answering the wrong
question: it inherits an overlap resolution decided by non-voter speeches it is
no longer trading.

Filtering has to happen BEFORE the overlap rule, so the notebook needs the book as
it was before that rule ran.

    python _build_raw_events.py --bucket manual --bank FED

Overlaps are always same-day (the exit is clamped to the speech day's session
close), so the raw book asks for no calendar days the gated one did not — the bar
prewarm carries over.
"""

from __future__ import annotations

import argparse
import datetime
import io
import pickle
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")
sys.path.insert(0, str(Path(__file__).parent))

import global_hawk_dove_common as G
from global_hawk_dove_run import (
    CACHE, SCORES_CSV, SCORE_METRIC, QUARTERLY_LABELS, BT_END, BASE_BPV,
    BLACKOUT_BD, ENTRY_OFFSET, EXIT_OFFSET, CONTRACT_RANK, make_bucketer_factory,
)

RAW_START = "2019-01-01"


def _p(*a):
    print(*a, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default="manual")
    ap.add_argument("--bank", default="FED")
    ap.add_argument("--start", default=RAW_START)
    ap.add_argument("--end", default=BT_END)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    scores = G.load_global_scores(SCORES_CSV, SCORE_METRIC)
    factory = make_bucketer_factory(scores, args.bucket)
    eligible = (set(G.load_quarterly_labels(QUARTERLY_LABELS))
                if args.bucket == "manual" else None)
    cfg = G.CB_CONFIGS[args.bank]
    _p(f"{args.bank} {args.bucket}: {args.start} -> {args.end}, "
       f"{len(eligible) if eligible else 'score-based'} eligible speakers")

    events, funnel = G.build_leg_events(
        cfg, scores, start=args.start, end=args.end,
        entry_offset=ENTRY_OFFSET, exit_offset=EXIT_OFFSET,
        base_bpv=BASE_BPV, contract_rank=CONTRACT_RANK,
        bucketer_factory=factory, blackout_bd=BLACKOUT_BD,
        point_in_time=True, eligible_speakers=eligible,
    )
    _p(f"  raw events: {len(events)}  "
       f"(timed {funnel['n_timed']}, synthetic {funnel['n_synthetic']}, "
       f"from {funnel['n_forexfactory_rows']} calendar rows)")
    for k, v in sorted(funnel["forexfactory"].items(), key=lambda x: -x[1]):
        _p(f"      ff-excluded {k}: {v}")
    for k, v in sorted(funnel["synthetic"].items(), key=lambda x: -x[1]):
        _p(f"      syn-excluded {k}: {v}")

    kept, n_ovl = G.drop_overlaps(events)
    _p(f"  the overlap rule would drop {n_ovl}, leaving {len(kept)} — that is what "
       f"the cached book holds, and why this raw dump exists")

    # Reconcile against the gated book this is meant to generalise. A calendar
    # re-fetch can drift, and a raw book that no longer contains the trades the
    # sibling notebook reported would make every comparison meaningless.
    gated_name = (f"events_{args.bucket}_{args.bucket}.pkl"
                  if args.bucket != "peer" else "events.pkl")
    gp = CACHE / gated_name
    if gp.exists():
        with open(gp, "rb") as f:
            gated = pickle.load(f)[args.bank]["events"]
        raw_tags = {e["tag"] for e in events}
        miss = [e["tag"] for e in gated if e["tag"] not in raw_tags]
        _p(f"  reconcile vs {gated_name}: {len(gated)} gated events, "
           f"{len(miss)} NOT present in the raw book")
        for t in miss[:10]:
            _p(f"      missing {t}")

    days = {(e["symbol"], e["entry_ts"].date()) for e in events}
    kept_days = {(e["symbol"], e["entry_ts"].date()) for e in kept}
    _p(f"  symbol-days: raw {len(days)}, post-overlap {len(kept_days)}, "
       f"new {len(days - kept_days)}")

    out = CACHE / (args.out or f"events_{args.bucket}_raw.pkl")
    with open(out, "wb") as f:
        pickle.dump({args.bank: {"events": events, "funnel": funnel,
                                 "n_overlap_dropped": n_ovl}}, f)
    _p(f"\nwrote {out}")


if __name__ == "__main__":
    main()

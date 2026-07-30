"""G0's independent-mid flip study, standalone. READ-ONLY, and no Barchart.

Runs the same `labels.flip_study` the gate runs — one implementation, not a copy — so
this can be pointed at a completed slice of the window while the rest of the backfill is
still going, without competing for the intraday futures quota. The independent source
(Citi Velocity swap-quote curves) is a different store entirely.

What it answers is the study's first kill risk, measured rather than argued: our direction
label is decided by which side of OUR mid a trade printed, and if an independent mid
sits a systematic distance away, the label is reporting curve disagreement rather than
where the trade printed. That would also explain the persistent 68–82% PAID skew.

    conda run -n stir python scripts/dealer_ladder_flip_study.py \
        --start 2026-01-12 --end 2026-01-31 --per-day 40 --out-dir BT/results/flip_jan
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=lambda s: datetime.date.fromisoformat(s),
                    required=True)
    ap.add_argument("--end", type=lambda s: datetime.date.fromisoformat(s),
                    required=True)
    ap.add_argument("--per-day", type=int, default=40,
                    help="time-of-day-stratified sample size per session")
    ap.add_argument("--limit", type=int, default=0, help="blunt cap after sampling")
    ap.add_argument("--source", default="citivelo")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    from BT.dealer_ladder import config as cfg, data, labels
    from SDRUtils._swappulse_scripts.backfill_stir_ladder import _load_units

    window = (args.start, args.end)
    conn = data.connect()
    try:
        prints_all = data.load_prints(conn, window)
        units = _load_units(conn, args.start, args.end)
    finally:
        conn.close()

    if prints_all.empty:
        print("no prints in that window", file=sys.stderr)
        return 1

    # ON-MARKET prints INCLUDING curve-suspect ones. Restricting to curve-clean would
    # throw away the by-bucket comparison, which is the diagnostic that says whether the
    # curve-suspect gate is catching the right prints in the first place.
    pool = prints_all[
        prints_all["classification_method"].isin(cfg.ON_MARKET_METHODS)
        & prints_all["dealer_direction"].isin(("PAID", "RECEIVED"))
    ].drop_duplicates("unit_key")
    print(f"{len(prints_all):,} prints -> {len(pool):,} on-market signed units "
          f"over {prints_all['as_of_date'].nunique()} sessions")

    res = labels.flip_study(units, pool.to_dict(orient="records"), source=args.source,
                            limit=args.limit, per_day=args.per_day, seed=args.seed,
                            strata=pool)
    recon = res["recon"]
    if recon.empty:
        print("the independent source could not price ANY unit", file=sys.stderr)
        return 1

    compared = recon[recon["flipped"].notna()]
    print(f"\nsampled {len(recon):,} units; independent mid available for "
          f"{len(compared):,} ({100.0 * len(compared) / max(len(recon), 1):.1f}%)")
    if len(compared):
        print(f"OVERALL FLIP RATE: {compared['flipped'].mean():.1%}")
    for reason, n in recon["reason"].fillna("").value_counts().items():
        if reason:
            print(f"  no comparison: {reason} x{n}")

    for name in ("flip_by_confidence", "flip_by_curve_bucket", "flip_by_hour",
                 "flip_by_trade_type", "skew_vs_independent",
                 "skew_vs_independent_by_hour", "mid_offset_bps"):
        tab = res.get(name)
        if isinstance(tab, pd.DataFrame) and not tab.empty:
            print(f"\n== {name}")
            print(tab.to_string(index=False))
    if "implied_accuracy" in res:
        print(f"\n== implied accuracy bounds\n{res['implied_accuracy']}")

    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        for name, tab in res.items():
            if isinstance(tab, pd.DataFrame):
                tab.to_csv(os.path.join(args.out_dir, f"g0_{name}.csv"))
        print(f"\nwrote {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

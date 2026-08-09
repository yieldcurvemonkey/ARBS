"""Report the health of stored curve snapshots, per asset per trading date.

Run this after a warm. It answers the question the warm's exit code cannot:
"did we store believable curves?" A backfill can exit 0, write every partition,
and still have laid down 1,381 consecutive identity curves -- that is exactly
what happened to USD-OIS-Q12xM12STIRT-SERFFX-MIX23 on 2026-07-01.

Read-only. Never touches the store.

Columns
-------
minutes            snapshots stored for that trading date
shapes             distinct instrument sets (node signature, anchor-normalised)
anchors            distinct curve reference dates (2 is normal: the evening
                   block anchors a calendar day early)
quarantined        snapshots the read path will drop (see Caching.curve_sanity)
degenerate         un-solved identity curves (every discount factor 1.0)
neg_fwd            snapshots with a forward below the floor -- reported only
outliers           snapshots whose 1Y reference rate is more than `--outlier-bp`
                   from a centred rolling median of its own session. Audit-only:
                   this catches spikes but by construction cannot see a
                   sustained displacement, and can flag genuine policy moves.
max_dev_bp         worst such deviation
block_gap_bp       largest level gap between anchor blocks of the same session

Examples
--------
    python scripts/audit_curve_store_health.py --asset USD-OIS-Q12xM12STIRT-SERFFX-MIX23
    python scripts/audit_curve_store_health.py --asset USD-SOFR-1D-Q12STIRT \
        --start 2026-05-07 --end 2026-08-07 --all-days
"""

from __future__ import annotations

import argparse
import datetime
import glob
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Caching.curve_sanity import (  # noqa: E402
    DEGENERATE_IDENTITY,
    NEGATIVE_FORWARD,
    READ_DROP_CODES,
    frame_defects,
    reference_rate,
    shape_signature,
)

_ROLLING_WINDOW = 61


def _asset_dir(base_dir: Path | None, asset: str) -> Path:
    if base_dir is None:
        from Caching.curve_store import CurveStore

        base_dir = CurveStore.default().base_dir
    return Path(base_dir) / "raw" / f"asset={asset}"


def _load_day(asset_dir: Path, day: str) -> pd.DataFrame | None:
    import pyarrow.parquet as pq

    files = sorted(glob.glob(str(asset_dir / f"date={day}" / "*.parquet")))
    if not files:
        return None
    df = pd.concat([pq.read_table(f).to_pandas() for f in files], ignore_index=True)
    if "trading_date" not in df.columns:
        df["trading_date"] = datetime.date.fromisoformat(day)
    return df.sort_values("timestamp_utc").reset_index(drop=True)


def audit_day(df: pd.DataFrame, *, outlier_bp: float) -> dict:
    codes = frame_defects(df)
    quarantined = int(codes.map(lambda cs: bool(READ_DROP_CODES.intersection(cs))).sum())
    degenerate = int(codes.map(lambda cs: DEGENERATE_IDENTITY in cs).sum())
    neg_fwd = int(codes.map(lambda cs: NEGATIVE_FORWARD in cs).sum())

    sigs = df["node_dates"].map(shape_signature)
    anchors = df["node_dates"].map(lambda v: pd.Timestamp(v[0]).date() if len(v) else None)
    rates = pd.Series(
        [reference_rate(nd, dfv) for nd, dfv in zip(df["node_dates"], df["discount_factors"])],
        index=df.index, dtype=float,
    )

    # Audit-only spike detector: a centred rolling median follows a real move,
    # so a persistent repricing does not trip it -- and neither does a
    # 450-minute displaced block, which is why this is not a quarantine rule.
    med = rates.rolling(_ROLLING_WINDOW, center=True, min_periods=5).median()
    dev = (rates - med).abs() * 100.0
    outliers = int((dev > outlier_bp).sum())
    max_dev = float(dev.max()) if dev.notna().any() else float("nan")

    block_gap = 0.0
    if anchors.nunique(dropna=True) > 1:
        medians = rates.groupby(anchors).median().dropna()
        if len(medians) > 1:
            block_gap = float(medians.max() - medians.min()) * 100.0

    return {
        "minutes": len(df),
        "shapes": int(sigs.nunique()),
        "anchors": int(anchors.nunique(dropna=True)),
        "quarantined": quarantined,
        "degenerate": degenerate,
        "neg_fwd": neg_fwd,
        "outliers": outliers,
        "max_dev_bp": round(max_dev, 2) if np.isfinite(max_dev) else np.nan,
        "block_gap_bp": round(block_gap, 2),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--asset", required=True, help="CurveStore asset name, e.g. USD-OIS-Q12xM12STIRT-SERFFX-MIX23")
    p.add_argument("--start", help="first trading date, YYYY-MM-DD")
    p.add_argument("--end", help="last trading date, YYYY-MM-DD")
    p.add_argument("--base-dir", help="CurveStore base dir (defaults to the configured store)")
    p.add_argument("--outlier-bp", type=float, default=5.0, help="rolling-median deviation to report (default 5)")
    p.add_argument("--all-days", action="store_true", help="print every day, not just days with findings")
    p.add_argument("--csv", help="also write the table here")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")

    asset_dir = _asset_dir(Path(args.base_dir) if args.base_dir else None, args.asset)
    if not asset_dir.is_dir():
        print(f"No stored data for asset {args.asset!r} under {asset_dir}", file=sys.stderr)
        return 2

    days = sorted(d[5:] for d in os.listdir(asset_dir) if d.startswith("date="))
    if args.start:
        days = [d for d in days if d >= args.start]
    if args.end:
        days = [d for d in days if d <= args.end]
    if not days:
        print("No trading dates in range.", file=sys.stderr)
        return 2

    rows = []
    for day in days:
        df = _load_day(asset_dir, day)
        if df is None or df.empty:
            continue
        rows.append({"day": day, **audit_day(df, outlier_bp=args.outlier_bp)})

    table = pd.DataFrame(rows).set_index("day")
    if table.empty:
        print("No snapshots found.", file=sys.stderr)
        return 2

    findings = table[
        (table.quarantined > 0) | (table.degenerate > 0) | (table.outliers > 0) | (table.neg_fwd > 0)
    ]
    shown = table if args.all_days else findings

    pd.set_option("display.width", 200)
    print(f"asset={args.asset}  days={len(table)}  snapshots={int(table.minutes.sum())}")
    print(f"clean days={len(table) - len(findings)}/{len(table)}   "
          f"quarantined={int(table.quarantined.sum())} "
          f"({100 * table.quarantined.sum() / max(1, table.minutes.sum()):.2f}% of snapshots)")
    # Coverage gaps are not corruption but they silently thin an intraday grid.
    typical = table.minutes.median()
    thin = table[table.minutes < 0.6 * typical]
    if len(thin):
        print(f"\nthin sessions (< 60% of the {int(typical)}-snapshot median): "
              f"{', '.join(f'{d} ({int(n)})' for d, n in thin.minutes.items())}")
    if shown.empty:
        print("\nNo findings.")
    else:
        print(f"\n{'all days' if args.all_days else 'days with findings'}:")
        print(shown.to_string())

    if args.csv:
        table.to_csv(args.csv)
        print(f"\nwrote {args.csv}")
    return 1 if len(findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Cross-wrapper breakeven board — one bp/day rent axis for W1/W2/W3/W5.

    C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/breakeven_board.py --date 2026-08-07
    C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/breakeven_board.py            # latest leg-history date
    C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/breakeven_board.py --json

Prints one row per structure (columns ``RVUtils.CvxSuite.board.BOARD_COLUMNS``,
every vol in bp/day) plus Citi's curve-pair anchor thresholds as reference
lines. Data: the offline CITIVELO curve store (``offline=True``, store-backed
asserted), ``docs/cvxsuite/leg_history.parquet``, the swaption cube store, and
cached BARCHART SR3 settles under ``listed_cache_guard`` — this script NEVER
fetches; a wrapper whose data is absent prints ``=== Wx SKIPPED: reason ===``
and the rest of the board still ships.

Exit code: 0 when at least one wrapper priced; 2 when nothing priced (a board
that priced nothing is a failure, not a flat answer — famb convention).
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

pd.set_option("display.width", 210)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--date", default=None,
        help="YYYY-MM-DD as-of date (default: the latest leg-history date)")
    p.add_argument(
        "--json", action="store_true",
        help="emit machine-readable records instead of the report")
    return p.parse_args(argv)


def _resolve_asof(arg: str | None) -> dt.date:
    from RVUtils.CvxSuite import board as B

    if arg:
        return pd.Timestamp(arg).date()
    path = B._default_leg_hist_path()
    if not path.exists():
        raise FileNotFoundError(
            f"no --date given and no leg history at {path} to take the latest date from")
    hist = pd.read_parquet(path)
    return pd.Timestamp(hist.index.max()).date()


def main(argv=None) -> int:
    args = parse_args(argv)
    from RVUtils.CvxSuite import board as B

    asof = _resolve_asof(args.date)
    cfg = B.BoardConfig()
    if args.json:
        # keep stdout pure JSON: board diagnostics (skip/note lines) and any
        # library chatter (e.g. a rateslib solver print) go to stderr instead.
        import contextlib

        with contextlib.redirect_stdout(sys.stderr):
            df = B.build_breakeven_board(asof, cfg=cfg)
    else:
        df = B.build_breakeven_board(asof, cfg=cfg)

    if args.json:
        records = []
        for rec in df.to_dict(orient="records"):
            records.append({k: (None if isinstance(v, float) and not np.isfinite(v) else v)
                            for k, v in rec.items()})
        print(json.dumps({
            "asof": str(asof),
            "rows": records,
            "skips": df.attrs.get("skips", {}),
            "notes": df.attrs.get("notes", []),
            "anchors": list(B.CITI_ANCHOR_LINES),
        }, indent=2))
    else:
        print(f"\n=== breakeven board {asof} ===  (all vols bp/day; theta bp/yr; gamma USD/bp^2)")
        if len(df):
            print(df.to_string(index=False, float_format=lambda v: f"{v:9.3f}"))
        else:
            print("(no structure priced)")
        print()
        for line in B.CITI_ANCHOR_LINES:
            print(line)

    return 0 if B.board_priced(df) else 2


if __name__ == "__main__":
    sys.exit(main())

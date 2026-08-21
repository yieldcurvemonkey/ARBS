r"""Contiguous SR3 settle depth by year, through the repo's own reader.

Uses ``RVUtils.ConvexityRV.strat2_q20.strip_depth_by_date`` -- the function the
panel itself gates on -- so the measurement cannot disagree with the code by
construction. ``min_depth=1`` is the warm's lens: the shipped universe floor is
4 and would hide exactly the shallow dates a coverage report exists to show.

Writes ``notebooks/data/convexity_rv/ca_depth_by_year_<tag>.csv`` so a
before/after comparison is a diff of two files rather than a re-scan.

    python notebooks/backtests/convexity_rv/_measure_ca_depth.py --tag postwarm
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

#: rank -> (colour, depth the rank needs). A pack at rank r spans contracts
#: r..r+3, so it needs a contiguous strip of r+3.
RANKS = [(1, "Whites"), (5, "Reds"), (9, "Greens"), (13, "Blues"), (17, "Golds")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="postwarm")
    ap.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2018, 1, 1))
    ap.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2026, 8, 20))
    a = ap.parse_args(argv)

    from RVUtils.ConvexityRV.strat2_q20 import Q20Config, strip_depth_by_date

    cfg = Q20Config(max_instruments=20, start=a.start, end=a.end)
    depths = strip_depth_by_date(cfg, min_depth=1)
    print(f"dates with an EOD key: {len(depths)}")

    s = pd.Series(depths, name="depth")
    s.index = pd.to_datetime(list(s.index))
    yr = s.index.year

    rows = []
    for y in sorted(set(yr)):
        d = s[yr == y]
        row = {"year": int(y), "dates": int(len(d))}
        for thr in (4, 8, 12, 16, 20):
            row[f"ge{thr}"] = int((d >= thr).sum())
        row["max"] = int(d.max())
        rows.append(row)
    depth_tbl = pd.DataFrame(rows)

    rows = []
    for y in sorted(set(yr)):
        d = s[yr == y]
        row = {"year": int(y)}
        for rank, colour in RANKS:
            row[colour] = int((d >= rank + 3).sum())
        rows.append(row)
    rank_tbl = pd.DataFrame(rows)

    out = REPO / "notebooks" / "data" / "convexity_rv"
    out.mkdir(parents=True, exist_ok=True)
    depth_tbl.to_csv(out / f"ca_depth_by_year_{a.tag}.csv", index=False)
    rank_tbl.to_csv(out / f"ca_rank_by_year_{a.tag}.csv", index=False)

    print("\ncontiguous strip depth, dates per year")
    print(depth_tbl.to_string(index=False))
    print("\ndates on which each pack colour is buildable")
    print(rank_tbl.to_string(index=False))
    print(f"\nwrote {out / f'ca_depth_by_year_{a.tag}.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

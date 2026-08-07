"""Daily outcome-map panels: cells, the even/odd split, and the linear ladders.

Writes to ``--out-dir`` (default ``notebooks/data/outcome_map``, gitignored):

``cells.parquet``       one row per (as_of, symbol, cell) — the map, its
                        decomposition and the conservation ledger
``cells_p1.parquet``    the Gaussian-tree placebo world (no lattice anywhere)
``cells_p2.parquet``    the wrong-calendar placebo world
``jumps_zq.parquet``    per-meeting jumps from the ZQ FedWatch ladder
``jumps_swap.parquet``  per-meeting jumps from the meeting-dated swap curve

Usage::

    conda run -n stir python notebooks/rv/build_outcome_map_history.py --all
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
for p in (REPO, REPO / "notebooks" / "backtests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import outcome_map_common as omc                            # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=Path,
                   default=REPO / "notebooks" / "data" / "outcome_map")
    p.add_argument("--cells", action="store_true")
    p.add_argument("--placebos", action="store_true")
    p.add_argument("--jumps", action="store_true")
    p.add_argument("--swap", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--max-dte", type=int, default=200)
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    if a.all:
        a.cells = a.placebos = a.jumps = a.swap = True
    a.out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    ctx = omc.Context(max_dte=a.max_dte)
    print(f"context: {len(ctx.dates)} dates {ctx.dates[0].date()} -> "
          f"{ctx.dates[-1].date()}, {len(ctx.symbols)} symbols "
          f"({time.time() - t0:.0f}s)", flush=True)

    if a.cells:
        t = time.time()
        panel = omc.build_cell_panel(ctx, progress=200)
        panel.to_parquet(a.out_dir / "cells.parquet", index=False)
        print(f"cells.parquet {panel.shape} ({time.time() - t:.0f}s)",
              flush=True)

    if a.jumps:
        t = time.time()
        zq = omc.zq_jump_panel(ctx)
        zq.to_parquet(a.out_dir / "jumps_zq.parquet", index=False)
        print(f"jumps_zq.parquet {zq.shape} ({time.time() - t:.0f}s)",
              flush=True)

    if a.swap:
        t = time.time()
        sw = omc.swap_jump_panel(ctx.dates, progress=100)
        sw.to_parquet(a.out_dir / "jumps_swap.parquet", index=False)
        print(f"jumps_swap.parquet {sw.shape} ({time.time() - t:.0f}s)",
              flush=True)

    if a.placebos:
        t = time.time()
        p1 = omc.build_cell_panel(omc.gaussian_context(ctx), progress=200)
        p1.to_parquet(a.out_dir / "cells_p1.parquet", index=False)
        print(f"cells_p1.parquet {p1.shape} ({time.time() - t:.0f}s)",
              flush=True)
        t = time.time()
        sctx = omc.shifted_context(ctx)
        p2 = omc.build_cell_panel(sctx, progress=200)
        p2.to_parquet(a.out_dir / "cells_p2.parquet", index=False)
        print(f"cells_p2.parquet {p2.shape} ({time.time() - t:.0f}s)",
              flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())

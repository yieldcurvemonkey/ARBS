"""Build the Strategy-2 butterfly panels: per-leg par rates and per-fly rates.

    C:/Users/chris/anaconda3/envs/stir/python.exe scripts/strat2_build_fly_panel.py [workers]

Outputs land in ``notebooks/data/convexity_rv/``:

``strat2_fly_legs.parquet``   (date, tenor) -> rate_pct, carry_roll_bp (3M horizon)
``strat2_fly_panel.parquet``  (date, fly_id) -> fly_bp, carry_roll_3m_bp + geometry,
                              at DV01-neutral (50/50) wing weights

The LEG panel is the primitive; every fly at every weighting is arithmetic on
top of it (``IRSwapValue.RATE`` on a FLY is exactly the risk-weighted sum of the
legs' fair rates -- measured agreement 1e-13 bp). The regression weighting
cannot be stored as a panel because its weights depend on which pack's CA is
being hedged, so the grid derives it from the legs at each entry.

The date axis is every business day the swap curve covers; a day whose resolved
reference date is not the requested day is dropped by the worker's holiday-ghost
filter rather than served as the previous close.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime as dt
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pandas as pd

START = dt.date(2019, 1, 1)
END = dt.date(2026, 8, 12)


def main() -> None:
    from RVUtils.ConvexityRV.strat2_fly_universe import (
        build_and_write_panels,
        fly_universe,
        universe_tenors,
    )

    specs = fly_universe()
    tenors = universe_tenors(specs)
    print(f"{len(specs)} flies over {len(tenors)} leg tenors: {tenors}", flush=True)
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    days = [d.date() for d in pd.bdate_range(START, END)]
    build_and_write_panels(days, workers=workers)


if __name__ == "__main__":
    main()

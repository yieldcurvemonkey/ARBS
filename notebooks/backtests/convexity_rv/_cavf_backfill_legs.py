r"""CA-vs-fly block: build the fly LEG panel (spot + forward-starting par rates).

Stores per-leg par rates and 3M carry/roll, exactly as ``strat2_fly_universe``
prescribes -- every fly at every weighting is then arithmetic on the legs. The
universe is the module's own (starts 0/1/2/3/5y) EXTENDED with 4y forward
starts, so a fly whose forward start sits at the Golds pack expiry (~4.25y) is
constructible; the deep-rank forward-start-matched-fly hypothesis was only ever
tested to T1 ~ 2.5y and is a headline question of this block.

Output: notebooks/data/convexity_rv/cavf_fly_legs.parquet (long: date, tenor,
rate_pct, carry_roll_bp)
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    from RVUtils.ConvexityRV import strat2_fly_universe as FU

    DATA = REPO / "notebooks" / "data" / "convexity_rv"
    OUT = DATA / "cavf_fly_legs.parquet"

    ca = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
    dates = [d.date() for d in pd.to_datetime(ca.index)]
    print(f"{len(dates)} dates from the CA panel "
          f"{dates[0]}..{dates[-1]}")

    base = list(FU.universe_tenors())
    spot_tenors = sorted({t for _, legs in FU.FLY_SHAPES for t in legs})
    extra = [FU.tenor_key(4.0, t) for t in spot_tenors]
    tenors = tuple(dict.fromkeys(base + extra))
    print(f"{len(base)} base tenors + {len([t for t in extra if t not in base])} "
          f"new 4y-start tenors -> {len(tenors)}")

    legs = FU.build_fly_leg_panel(dates, tenors=tenors, workers=6, chunk=60)
    assert not legs.empty, "leg panel came back empty"
    legs.to_parquet(OUT)
    print(f"wrote {OUT}  {legs.shape}")
    wide = FU.legs_wide(legs)
    print(f"wide {wide.shape}; non-null fraction min "
          f"{float(wide.notna().mean().min()):.4f}")


if __name__ == "__main__":
    main()

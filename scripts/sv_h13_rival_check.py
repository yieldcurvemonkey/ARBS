"""H13 rival-mechanism check (advisor #1, outcome-map style).

The grail state (repriced carry >= 0 & gamma > 0) fires when the spread is
steep-vs-history, so the parsimonious rival for the certified ex-carry timing
is plain SPREAD MEAN-REVERSION from carry-extreme levels. Discriminate at the
winner's own coordinates: per USD pair, build an OCCUPANCY-MATCHED raw-spread
z state (enter when trailing-252d z of the spread >= the quantile that matches
the grail state's occupancy — steep side), lag-1, run it through the IDENTICAL
_book at zero cost, and compare EX-CARRY totals.

If spread-z reproduces most of the grail ex-carry, the surviving claim is
"the state times favorable MTM; convexity-vs-reversion not discriminated".

Run: conda run -n stir python scripts/sv_h13_rival_check.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import importlib.util
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location(
    "sv_citivelo_h13", _REPO / "scripts" / "sv_citivelo_h13.py")
h13 = importlib.util.module_from_spec(spec)
sys.modules["sv_citivelo_h13"] = h13
spec.loader.exec_module(h13)

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"


def main() -> None:
    units_all = pd.read_parquet(DATA / "h13_units_USD.parquet")
    det = pd.read_parquet(DATA / "sv_detector_USD.parquet")
    det["date"] = pd.to_datetime(det["date"])

    rows = []
    for pair in units_all.index.get_level_values("pair").unique():
        unit = units_all.xs(pair, level="pair")
        d = det[det["pair"] == pair].set_index("date").sort_index()
        grail = d["grail_flattener"].astype(float)
        occ = float(grail.mean())
        if occ <= 0.01:
            continue
        z = d["z_1y"]
        # steep side = spread HIGH vs history (less inverted); match occupancy
        thr = float(z.quantile(1.0 - occ))
        rival = (z >= thr).astype(float)
        free = dict(initiate_bp=0.0, hedge_bp=0.0, roll_bp=0.0, mult=0.0,
                    roll_kind="roll")
        g = h13._book(unit, grail.shift(1).fillna(0.0), set(), **free)
        r = h13._book(unit, rival.shift(1).fillna(0.0), set(), **free)
        overlap = float(((grail > 0) & (rival > 0)).sum() / max((grail > 0).sum(), 1))
        rows.append({"pair": pair, "occ_grail": occ, "occ_rival": float(rival.mean()),
                     "state_overlap": overlap,
                     "excarry_grail_bp": g["stats"]["excarry_bp_total"],
                     "excarry_rival_bp": r["stats"]["excarry_bp_total"],
                     "carry_grail_bp": g["stats"]["carry_bp_total"],
                     "carry_rival_bp": r["stats"]["carry_bp_total"]})
    rep = pd.DataFrame(rows)
    rep["rival_retention"] = rep["excarry_rival_bp"] / rep["excarry_grail_bp"]
    rep.to_parquet(DATA / "h13_rival_check.parquet", index=False)
    pd.set_option("display.width", 200)
    print(rep.to_string(index=False, float_format=lambda x: f"{x:8.3f}"))
    print(f"\nmedian rival retention of grail ex-carry: {rep['rival_retention'].median():.1%}")


if __name__ == "__main__":
    main()

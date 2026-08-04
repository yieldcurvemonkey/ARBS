"""The corrected pond: ROLLING front-slot flies at 4h, by spacing.

The first probe measured a fixed far-dated triple and found 0.876bp per 4h
against a 2.0bp round trip. That understates the tradeable object, because for
most of its life all three legs sat in the quiet back of the strip. This builds
the same rolling constant-maturity baskets the EOD lab used -- via the SAME
``enumerate_structures`` code -- and measures the pond properly.

Two things are measured, and the second is the one that makes the first
trustworthy:

1. **The pond by spacing and horizon.** E|move| against the 2.0bp round trip,
   from 4h out to 21 days.
2. **A RECONCILIATION against the EOD lab.** Aggregated to 21 days, this panel
   must reproduce the daily lab's numbers (3m/6m/9m/12m E|move| of
   2.77/6.31/10.42/13.62bp). If it does not, the intraday panel is wrong and
   nothing downstream of it means anything. This check is the entire reason the
   intraday structures are built with the EOD lab's own code rather than a
   parallel implementation.

Run: conda run -n stir python notebooks/rv/_probe_intraday_rolling_pond.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

pd.set_option("display.width", 260, "display.max_columns", 40)

from RVUtils.MeanRev.panel import add_strip_slots, enumerate_structures

DATA = REPO / "notebooks" / "data" / "stir_intraday"
BARS_PER_DAY = 6
FLY_COST_BP = 2.0
MAX_SLOT = 16

# what the EOD lab measured at h=21 days, for the reconciliation
EOD_ABSMOVE_H21 = {1: 2.77, 2: 6.31, 3: 10.42, 4: 13.62}

HORIZONS = [(1, "4h"), (2, "8h"), (3, "12h"), (6, "1d"), (12, "2d"),
            (30, "5d"), (60, "10d"), (126, "21d")]


def main() -> int:
    panel = pd.read_parquet(DATA / "contracts.parquet")
    panel["as_of"] = pd.to_datetime(panel["as_of"])
    live = panel[~panel["accruing"]].copy()
    slots = add_strip_slots(live)
    print(f"panel {len(panel):,} rows -> {len(slots):,} pre-accrual, "
          f"{slots['as_of'].nunique():,} bars", flush=True)

    pond_rows, recon_rows = [], []
    for sp in (1, 2, 3, 4):
        st = enumerate_structures(slots, spacing=sp, max_slot=MAX_SLOT)
        wide = st.pivot_table(index="as_of", columns="key", values="value",
                              aggfunc="first").sort_index()
        # front of the strip only: where the EOD lab found what edge there was
        front = st[st["cm_slot"] <= 4]
        wide_front = front.pivot_table(index="as_of", columns="key",
                                       values="value", aggfunc="first").sort_index()
        print(f"\nspacing {sp} ({3*sp}m): {wide.shape[1]} keys, "
              f"{wide.shape[0]:,} bars   front-slot keys {wide_front.shape[1]}",
              flush=True)

        for panel_name, W in (("all slots", wide), ("front slots 1-4", wide_front)):
            for h, lbl in HORIZONS:
                m = (W.shift(-h) - W).stack(future_stack=True).dropna()
                if len(m) < 200:
                    continue
                pond_rows.append({
                    "spacing_m": 3 * sp, "panel": panel_name, "horizon": lbl,
                    "bars": h, "n": len(m),
                    "mean_abs_bp": float(m.abs().mean()),
                    "sd_bp": float(m.std()),
                    "oracle_net_bp": float(m.abs().mean()) - FLY_COST_BP,
                    "p_beat_cost": float((m.abs() > FLY_COST_BP).mean()),
                })

        m21 = (wide.shift(-126) - wide).stack(future_stack=True).dropna()
        recon_rows.append({
            "spacing_m": 3 * sp,
            "intraday_h21_absmove": float(m21.abs().mean()),
            "eod_h21_absmove": EOD_ABSMOVE_H21[sp],
            "ratio": float(m21.abs().mean()) / EOD_ABSMOVE_H21[sp],
            "level_sd_bp": float(wide.stack(future_stack=True).std()),
        })

    pond = pd.DataFrame(pond_rows)
    print("\n" + "=" * 120)
    print("THE POND -- rolling constant-maturity flies, E|move| vs a 2.0bp round trip")
    print("=" * 120, flush=True)
    for panel_name in ("all slots", "front slots 1-4"):
        sub = pond[pond["panel"] == panel_name]
        piv = sub.pivot_table(index="horizon", columns="spacing_m",
                              values="oracle_net_bp", aggfunc="first")
        piv = piv.reindex([l for _, l in HORIZONS if l in piv.index])
        abs_piv = sub.pivot_table(index="horizon", columns="spacing_m",
                                  values="mean_abs_bp", aggfunc="first")
        abs_piv = abs_piv.reindex(piv.index)
        print(f"\n  [{panel_name}]  E|move| bp:")
        print(abs_piv.round(3).to_string())
        print(f"\n  [{panel_name}]  ORACLE NET of 2.0bp cost:")
        print(piv.round(3).to_string())

    recon = pd.DataFrame(recon_rows)
    print("\n" + "=" * 120)
    print("RECONCILIATION -- does the 4h panel reproduce the EOD lab at 21 days?")
    print("=" * 120, flush=True)
    print(recon.round(3).to_string(index=False), flush=True)
    print("""
  A ratio near 1.0 means the intraday panel, aggregated up, IS the daily panel
  and the two labs can be compared directly. A ratio far from 1.0 means the
  intraday panel is measuring a different object and every number built on it
  has to be re-read before it is believed.""", flush=True)

    print("\n" + "=" * 120)
    print("THE DECISION")
    print("=" * 120, flush=True)
    f = pond[(pond["panel"] == "front slots 1-4") & (pond["horizon"] == "4h")]
    for _, r in f.iterrows():
        verdict = ("clears cost" if r["oracle_net_bp"] > 0
                   else "below cost")
        print(f"  {int(r['spacing_m']):>2}m fly, 4h: E|move| {r['mean_abs_bp']:.3f}bp "
              f"vs {FLY_COST_BP}bp -> oracle {r['oracle_net_bp']:+.3f}bp  "
              f"P(beat) {r['p_beat_cost']:.1%}   {verdict}", flush=True)
    best = f["oracle_net_bp"].max() if len(f) else float("nan")
    print(f"\n  best 4h oracle across spacings: {best:+.3f}bp")
    print("  -> " + ("PROCEED to an intraday-horizon lab" if best > 0 else
                     "the intraday HORIZON is not tradeable; the value of intraday\n"
                     "     data is in EXECUTION and CONDITIONING, not in the hold"),
          flush=True)

    DATA.mkdir(parents=True, exist_ok=True)
    pond.to_csv(DATA / "rolling_pond.csv", index=False)
    recon.to_csv(DATA / "eod_reconciliation.csv", index=False)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

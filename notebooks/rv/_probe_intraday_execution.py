"""STUDY B -- does WHEN you execute matter, holding the strategy fixed?

Study A asked whether a fly can be traded at intraday horizons. It cannot: at 4h
no spacing clears its round trip even with perfect foresight (best -0.52bp), and
the crossover only arrives around 8-12h for the widest fly.

That is a statement about the HOLDING PERIOD, not about intraday data. This asks
the other question, which the EOD lab could not ask at all because it only ever
saw one price per day:

    Same structures, same signal, same 21-day horizon, same 2.0bp cost.
    Only the TIME OF DAY at which the position is opened and closed changes.

Six panels are built from the identical 4h bars -- one per bar-of-day slot
(00/04/08/12/16/20 Central) -- and the whole backtest is run on each. Every
difference between them is execution timing and nothing else: same contracts,
same weights, same rule, same costs, same number of observations per year.

The 12:00 CT bar is the one containing the 15:00 ET settle, so it is the closest
analogue to the EOD lab and acts as the control.

Two ways this can come out, both worth having:

* the six agree -> execution timing is worth nothing, and the EOD lab's marks
  were not costing it anything. A null, but a load-bearing one.
* they disperse -> there is an intraday seasonal in the fly, and the size of
  the spread between best and worst bar is what better execution is WORTH,
  independently of whether any of them is profitable.

Run: conda run -n stir python notebooks/rv/_probe_intraday_execution.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

pd.set_option("display.width", 260, "display.max_columns", 40)

from RVUtils.MeanRev import MRConfig
from RVUtils.MeanRev.engine import run_backtest
from RVUtils.MeanRev.panel import add_strip_slots, enumerate_structures
from RVUtils.MeanRev.signals import zscore_signal

INTRA = REPO / "notebooks" / "data" / "stir_intraday"
FLY_COST_BP = 2.0
MAX_SLOT = 16
FRONT_LEG_MAX = 4
HOURS = (0, 4, 8, 12, 16, 20)
SPACINGS = ((2, "6m"), (3, "9m"), (4, "12m"))
WINDOWS = (42, 63, 126)
ENTRY_Z = (1.5, 2.0, 2.5)


def panel_at_hour(panel: pd.DataFrame, hour: int) -> pd.DataFrame:
    """One observation per DAY, taken from the bar closing at `hour` Central."""
    sub = panel[panel["bar_hour_ct"] == hour].copy()
    sub["as_of"] = sub["as_of"].dt.normalize()
    # a day can only contribute one row per contract
    sub = sub.drop_duplicates(subset=["as_of", "code"], keep="last")
    return sub


def main() -> int:
    panel = pd.read_parquet(INTRA / "contracts.parquet")
    panel["as_of"] = pd.to_datetime(panel["as_of"])
    panel = panel[~panel["accruing"]]

    rows, drift_rows = [], []
    for hour in HOURS:
        day = panel_at_hour(panel, hour)
        slots = add_strip_slots(day)
        for sp, tag in SPACINGS:
            st = enumerate_structures(slots, spacing=sp, max_slot=MAX_SLOT)
            st = st[st["cm_slot"] - sp <= FRONT_LEG_MAX]
            levels = st.pivot_table(index="as_of", columns="key", values="value",
                                    aggfunc="first").sort_index()
            if levels.shape[1] == 0 or len(levels) < 300:
                continue
            for w in WINDOWS:
                sig = zscore_signal(levels, window=w)
                for z in ENTRY_Z:
                    cfg = MRConfig(lag=1, round_trip_cost_bp=FLY_COST_BP,
                                   entry_z=z, exit_style="t21", max_hold=21,
                                   n_packages=1)
                    res = run_backtest(cfg, levels=levels, signal=sig)
                    m = res.metrics
                    if not m["n_trades"]:
                        continue
                    rows.append({
                        "hour_ct": hour, "spacing": tag, "window": w, "entry_z": z,
                        "n_trades": int(m["n_trades"]),
                        "hit_rate": float(m["hit_rate"]),
                        "avg_net_bp": float(m["avg_net_bp"]),
                        "total_net_bp": float(m["total_net_bp"]),
                        "total_gross_bp": float(m["total_gross_bp"]),
                    })

            # a mechanism check that does not depend on the backtest at all:
            # how much does the fly move between this bar and the NEXT day's
            # same bar, conditional on where it sits in its own trailing range?
            lv = levels
            z = zscore_signal(lv, window=63)
            fwd = lv.shift(-1) - lv
            hi = z.stack(future_stack=True) > 2.0
            lo = z.stack(future_stack=True) < -2.0
            f = fwd.stack(future_stack=True)
            drift_rows.append({
                "hour_ct": hour, "spacing": tag,
                "n_hi": int(hi.sum()), "n_lo": int(lo.sum()),
                "fwd_given_hi": float(f[hi.reindex(f.index, fill_value=False)].mean()),
                "fwd_given_lo": float(f[lo.reindex(f.index, fill_value=False)].mean()),
            })

    df = pd.DataFrame(rows)
    if df.empty:
        print("no results")
        return 1
    df.to_csv(INTRA / "execution_timing.csv", index=False)

    print("=" * 112)
    print("STUDY B -- SAME STRATEGY, DIFFERENT EXECUTION HOUR")
    print("=" * 112, flush=True)
    print("\nmean avg_net_bp across the (window x entry_z) grid, by hour and spacing:")
    piv = df.pivot_table(index="hour_ct", columns="spacing",
                         values="avg_net_bp", aggfunc="mean")
    print(piv.round(3).to_string(), flush=True)

    print("\nBEST cell per hour (the selected corner -- read with suspicion):")
    best = df.loc[df.groupby("hour_ct")["avg_net_bp"].idxmax()]
    print(best[["hour_ct", "spacing", "window", "entry_z", "n_trades",
                "hit_rate", "avg_net_bp", "total_net_bp"]].round(3)
          .to_string(index=False), flush=True)

    print("\nGROSS (pre-cost) avg bp per trade -- is the SIGNAL better at some hours?")
    df["avg_gross_bp"] = df["total_gross_bp"] / df["n_trades"]
    pg = df.pivot_table(index="hour_ct", columns="spacing",
                        values="avg_gross_bp", aggfunc="mean")
    print(pg.round(3).to_string(), flush=True)

    spread = piv.max() - piv.min()
    print("\n" + "=" * 112)
    print("WHAT EXECUTION TIMING IS WORTH")
    print("=" * 112, flush=True)
    for tag in piv.columns:
        b, wst = piv[tag].idxmax(), piv[tag].idxmin()
        print(f"  {tag:>3}: best hour {int(b):02d}:00 CT ({piv.loc[b, tag]:+.3f} bp/trade), "
              f"worst {int(wst):02d}:00 CT ({piv.loc[wst, tag]:+.3f}) -> "
              f"spread {spread[tag]:.3f} bp/trade", flush=True)
    print(f"\n  the 12:00 CT bar contains the 15:00 ET settle and is the EOD control.")

    dd = pd.DataFrame(drift_rows)
    print("\n" + "=" * 112)
    print("MECHANISM CHECK -- next-day drift conditional on a 2-sigma extreme")
    print("=" * 112, flush=True)
    print(dd.round(4).to_string(index=False), flush=True)
    print("""
  fwd_given_hi should be NEGATIVE and fwd_given_lo POSITIVE if the fly reverts.
  If the magnitudes differ systematically by hour, the intraday seasonal is real
  and it is in the SIGNAL, not just in the execution price.""", flush=True)
    dd.to_csv(INTRA / "execution_drift.csv", index=False)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

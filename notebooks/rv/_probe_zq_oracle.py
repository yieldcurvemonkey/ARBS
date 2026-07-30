"""The FF oracle ceiling, measured BEFORE anything is built on it.

The SR3 lesson: an oracle that always picks the winning side captured 2.378bp
per trade against a 2.0bp round trip, so perfect direction-calling was barely
profitable and lost at taker. That number, not the signal, was the whole
constraint. The brief for the FF work is explicit -- measure the equivalent
first, and if the FF oracle cannot clear cost, stop and report it.

ZQ cost, per CONTRACT (CBOT Ch. 22 §22102.C):

    normal tick   0.005 index points = 0.5bp   ($20.835)
    near delivery 0.0025             = 0.25bp  ($10.4175)
    round trip    = contracts x 2 sides x half a tick

so a 2-leg calendar spread costs 1.0bp and a 1/-2/1 fly 2.0bp at the full tick,
exactly as SR3 does -- the difference is entirely in how far the things move.

Also measured here: which structures are STRUCTURALLY DEGENERATE. Two adjacent
delivery months with no FOMC meeting between them cannot diverge without a
policy change, so their spread is pinned to the turn-of-month/quarter EFFR
pattern and nothing else. Those are excluded by construction rather than left
to be discovered in a grid.

Run: conda run -n stir python notebooks/rv/_probe_zq_oracle.py
"""
import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

pd.set_option("display.width", 240, "display.max_columns", 40)

from RVUtils.MeanRev.ff import (
    ZQ_TICK_BP, delivery_window, tick_bp, zq_exposure_vector,
)
from RVUtils.MeanRev.meetings import fomc_decisions

DATA = REPO / "notebooks" / "data" / "zq_kink_fade"
COST_SPREAD_BP = 1.0        # 2 contracts x 2 sides x 0.25bp
COST_FLY_BP = 2.0           # 4 contracts x 2 sides x 0.25bp


def main() -> int:
    c = pd.read_parquet(DATA / "contracts.parquet")
    c["as_of"] = pd.to_datetime(c["as_of"])
    print(f"panel {c.shape}  {c['as_of'].min().date()} -> {c['as_of'].max().date()}  "
          f"{c['as_of'].nunique()} sessions  {c['code'].nunique()} contracts", flush=True)

    # ------------------------------------------------------------ liquidity
    live = c[~c["accruing"]].copy()
    live["rank"] = live.groupby("as_of")["imm_start"].rank(method="first").astype(int)
    live["year"] = live["as_of"].dt.year
    print("\nZERO-VOLUME DAYS by contract rank and year (the honest-depth question)")
    zv = live.pivot_table(index="rank", columns="year",
                          values="volume", aggfunc=lambda s: float((s == 0).mean()))
    print((zv * 100).round(0).head(16).to_string(), flush=True)
    print("\nmedian OPEN INTEREST by rank and year")
    oi = live.pivot_table(index="rank", columns="year", values="open_interest",
                          aggfunc="median")
    print(oi.head(16).round(0).to_string(), flush=True)

    # ------------------------------------------------------- structures
    meetings = fomc_decisions(datetime.date(2017, 1, 1), datetime.date(2031, 12, 31))
    codes = sorted(c["code"].unique(), key=lambda k: delivery_window(k)[0])
    win = {k: delivery_window(k) for k in codes}

    def meetings_between(a, b):
        """Decisions effective in [start(a), start(b)) -- the driver of a spread."""
        sa, sb = win[a][0], win[b][0]
        return sum(1 for m in meetings
                   if sa <= m + datetime.timedelta(days=1) < sb)

    wide = live.pivot_table(index="as_of", columns="code", values="rate_pct",
                            aggfunc="first").sort_index()
    rank = live.pivot_table(index="as_of", columns="code", values="rank",
                            aggfunc="first").reindex(index=wide.index,
                                                     columns=wide.columns)

    # consecutive-month pairs and triples, keyed on ABSOLUTE contracts
    pairs, flies = [], []
    for i in range(len(codes) - 1):
        a, b = codes[i], codes[i + 1]
        if a in wide.columns and b in wide.columns:
            pairs.append((a, b))
    for i in range(len(codes) - 2):
        a, b, k = codes[i], codes[i + 1], codes[i + 2]
        if all(x in wide.columns for x in (a, b, k)):
            flies.append((a, b, k))

    def build(struct, weights, max_rank):
        lv, tags = {}, {}
        for legs in struct:
            key = "-".join(legs)
            v = sum(w * wide[l] for w, l in zip(weights, legs)) * 100.0
            ok = np.ones(len(wide), dtype=bool)
            for l in legs:
                ok &= (rank[l] <= max_rank).fillna(False).to_numpy()
            lv[key] = v.where(ok)
            tags[key] = legs
        return pd.DataFrame(lv), tags

    print("\n" + "=" * 100, flush=True)
    print("ORACLE CEILING -- E[|forward move|] over the round trip, no signal",
          flush=True)
    print("=" * 100, flush=True)

    from RVUtils.MeanRev.diagnostics import move_profile

    rows = []
    for name, struct, weights, cost, max_rank in (
            ("M1-M2 spread (rank<=6)", pairs, (-1.0, 1.0), COST_SPREAD_BP, 6),
            ("M1-M2 spread (rank<=12)", pairs, (-1.0, 1.0), COST_SPREAD_BP, 12),
            ("3-month fly (rank<=6)", flies, (-1.0, 2.0, -1.0), COST_FLY_BP, 6),
            ("3-month fly (rank<=12)", flies, (-1.0, 2.0, -1.0), COST_FLY_BP, 12),
    ):
        lv, tags = build(struct, weights, max_rank)
        # split on whether a meeting sits between the FIRST TWO legs
        with_m = [k for k, legs in tags.items() if meetings_between(legs[0], legs[1])]
        without = [k for k in lv.columns if k not in with_m]
        for tag, cols in (("ALL", list(lv.columns)), ("meeting between", with_m),
                          ("NO meeting between", without)):
            if not cols:
                continue
            p = move_profile(lv[cols], None, horizons=(5, 10, 21),
                             round_trip_bp=cost)
            for _, r in p.iterrows():
                rows.append({"structure": name, "subset": tag, "n_keys": len(cols),
                             "round_trip_bp": cost, **r.to_dict()})
    prof = pd.DataFrame(rows)
    keep = ["structure", "subset", "n_keys", "round_trip_bp", "horizon", "n",
            "mean_abs_bp", "median_abs_bp", "oracle_net_bp", "p_beat_cost", "sd_bp"]
    print(prof[keep].round(3).to_string(index=False), flush=True)
    prof.to_csv(DATA / "oracle_ceiling.csv", index=False)

    # -------------------------------------------------- the lattice question
    print("\n" + "=" * 100, flush=True)
    print("THE TICK LATTICE -- sigma in ticks, and how often the thing moves at all",
          flush=True)
    print("=" * 100, flush=True)
    rows = []
    for name, struct, weights, max_rank in (
            ("M1-M2 spread", pairs, (-1.0, 1.0), 12),
            ("3-month fly", flies, (-1.0, 2.0, -1.0), 12)):
        lv, tags = build(struct, weights, max_rank)
        with_m = [k for k, legs in tags.items() if meetings_between(legs[0], legs[1])]
        for tag, cols in (("meeting between", with_m),
                          ("NO meeting between", [k for k in lv.columns if k not in with_m])):
            if not cols:
                continue
            s = lv[cols]
            d = s.diff().stack()
            rows.append({
                "structure": name, "subset": tag, "n_keys": len(cols),
                "sd_bp": float(s.stack().std()),
                "sd_in_ticks": float(s.stack().std() / ZQ_TICK_BP),
                "distinct_values": int(s.stack().round(4).nunique()),
                "pct_unchanged_day": float((d.abs() < 1e-9).mean()),
                "daily_sd_bp": float(d.std()),
            })
    lat = pd.DataFrame(rows)
    print(lat.round(3).to_string(index=False), flush=True)
    lat.to_csv(DATA / "lattice.csv", index=False)
    print("\n  A structure whose sigma is a couple of ticks and which is unchanged on")
    print("  most days is a lattice, not a price series -- the SR3 lab's slots 13-16")
    print("  finding, and the reason no-meeting pairs are excluded structurally.",
          flush=True)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

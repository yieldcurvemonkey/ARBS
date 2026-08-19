"""Intraday auction-concession event study, on the Citi minute SOFR curve.

What is being measured, and what is not
---------------------------------------
There is no historical intraday price source for individual off-the-run Treasuries in
this stack (FedInvest is EOD; the Citi bond warm is EOD; WSJ/Webull are live-only). What
does exist intraday is the Citi Velocity minute SOFR curve store (offline, 2022→2026 at
1-10 minute granularity). A matched-maturity par swap rate sampled off it is the RATE-
LEVEL view of the auction concession: Treasuries cheapen into supply and swaps follow.
So this study times the SECTOR concession -- when, within the day, the cheapening into a
Treasury auction peaks and when the post-auction richening happens -- and the intraday
entry/exit guidance for the switch is drawn from that plus the (daily, bond-specific)
cycle profile already measured. The bond-specific intraday component (the new issue vs
the sector) is NOT observable here; stated, not papered over.

Design
------
For every auction cycle in the minute-store window: event day D = the business day
before the roll (the roll is auction+1bd by construction of the ranking rule). Sample
the par rate to the NEW bond's maturity at fixed ET stamps across D-2 .. D+2, express
everything relative to the D-1 15:00 ET mark, and average across events per tenor.
Auction results print at 13:00 ET, so 13:00->13:30 is the result window.

    <env>/python.exe notebooks/backtests/ust_switch/intraday_auction_study.py
"""

from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import sys
import time
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytz  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "_out" / "intraday"
ET = pytz.timezone("America/New_York")

#: The minute store's safe window (deep warm reaches further for some curves; events
#: with no data simply drop out).
STORE_LO = pd.Timestamp("2022-09-01")
STORE_HI = pd.Timestamp("2026-08-14")

#: ET sample times. 13:00 is the auction result; 15:00 anchors the previous close
#: (the store's coverage at 16:00+ is spottier on short days).
STAMPS = [(7, 30), (9, 0), (10, 30), (12, 0), (12, 45), (13, 0), (13, 15), (13, 30),
          (14, 30), (15, 0), (16, 0)]
REL_DAYS = (-2, -1, 0, 1, 2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenors", default="2,5,10,30")
    ap.add_argument("--max-events", type=int, default=0)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from TB.IRSwapsTB import IRSwapsTB

    amap = pd.read_parquet(HERE / "_data" / "alias_cusip_map.parquet")
    amap["date"] = pd.to_datetime(amap["date"])
    amap["maturity_date"] = pd.to_datetime(amap["maturity_date"])

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")

    # BACKWARD-ONLY snapshots, bounded lag. The store's nearest-snapshot default will
    # happily serve a curve stamped AFTER the requested instant (observed on the first
    # run: a 10:30 request served from 34,200s ahead), and for an event study whose whole
    # point is the 13:00 -> 13:30 auction jump, a future serve FABRICATES the jump at the
    # earlier stamp. asof + allow_future=False forbids it; 12 minutes of tolerance covers
    # the store's 10-minute cadence before 2024; on_miss="none" lets a dead stamp fall
    # through to NaN handling instead of killing the whole event.
    import datetime as _dt

    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotPolicy

    POLICY = SnapshotPolicy(method="asof", max_lag=_dt.timedelta(minutes=12),
                            allow_future=False, on_miss="none")
    for _name in ("get_data", "bulk_get_data"):
        _orig = getattr(mdp, _name)

        def _patched(request, *args, _o=_orig, **kw):
            try:
                request = dict(request)
                request["snapshot_policy"] = POLICY
            except Exception:
                pass
            return _o(request, *args, **kw)

        setattr(mdp, _name, _patched)

    tb = IRSwapsTB(mdp, show_tqdm=False)

    tenors = tuple(int(x) for x in a.tenors.split(","))
    rows = []
    t0 = time.time()
    for tenor in tenors:
        r0 = amap[(amap["tenor"] == tenor) & (amap["rank"] == 0)].sort_values("date")
        flips = r0[r0["cusip"] != r0["cusip"].shift(1)].iloc[1:]
        flips = flips[(flips["date"] >= STORE_LO) & (flips["date"] <= STORE_HI)]
        dates_all = pd.DatetimeIndex(sorted(r0["date"].unique()))
        events = list(flips.itertuples())
        if a.max_events:
            events = events[: a.max_events]
        print(f"{tenor}Y: {len(events)} auctions in window", flush=True)

        for ev in events:
            roll = ev.date
            pos = dates_all.searchsorted(roll)
            if pos < 3 or pos + 2 >= len(dates_all):
                continue
            day_of = {d: dates_all[pos - 1 + d] for d in REL_DAYS}  # d=0 -> auction day (roll-1bd)
            mat = ev.maturity_date.date()
            q = IRSwapQuery(curve="USD-SOFR-1D", value=IRSwapValue.RATE,
                            effective_date=day_of[-2].date(), maturity_date=mat,
                            structure_kwargs={"notional": 1_000_000})
            stamps = []
            for d in REL_DAYS:
                base = day_of[d]
                for h, m in STAMPS:
                    stamps.append((d, (h, m), ET.localize(
                        datetime.datetime(base.year, base.month, base.day, h, m))))
            try:
                df = tb.get_timeseries(start=stamps[0][2], end=stamps[-1][2],
                                       queries=[q], timestamps=[s[2] for s in stamps],
                                       n_jobs=1)
            except Exception as exc:
                print(f"  {tenor}Y {roll.date()}: FAIL {type(exc).__name__}: {str(exc)[:80]}",
                      flush=True)
                continue
            if df is None or df.empty:
                continue
            ser = df.iloc[:, 0]
            vals = {}
            for (d, hm, ts) in stamps:
                v = ser.get(ts, np.nan)
                if pd.notna(v):
                    vals[(d, hm)] = float(v) * 100.0  # bp
            anchor = vals.get((-1, (15, 0)))
            if anchor is None or len(vals) < 20:
                continue
            for (d, hm), v in vals.items():
                rows.append({"tenor": tenor, "roll": roll, "rel_day": d,
                             "stamp": f"{hm[0]:02d}:{hm[1]:02d}",
                             "rate_bp": v, "rel_bp": v - anchor})
    if not rows:
        print("no events sampled")
        return 1
    panel = pd.DataFrame(rows)
    panel.to_parquet(OUT / "auction_intraday_panel.parquet", index=False)

    # mean path per tenor
    g = (panel.groupby(["tenor", "rel_day", "stamp"])["rel_bp"]
         .agg(["mean", "std", "count"]).reset_index())
    g["se"] = g["std"] / np.sqrt(g["count"].clip(lower=1))
    g.to_csv(OUT / "auction_intraday_path.csv", index=False)

    # the 13:00 -> 13:30 result-window move on auction day, per tenor
    res = panel[(panel["rel_day"] == 0) & (panel["stamp"].isin(["13:00", "13:30"]))]
    piv = res.pivot_table(index=["tenor", "roll"], columns="stamp", values="rate_bp")
    if {"13:00", "13:30"}.issubset(piv.columns):
        piv["result_jump_bp"] = piv["13:30"] - piv["13:00"]
        jr = piv.groupby("tenor")["result_jump_bp"].agg(["mean", "std", "count"])
        jr["t"] = jr["mean"] / (jr["std"] / np.sqrt(jr["count"]))
        print("\n13:00 -> 13:30 auction-result jump (bp, negative = richening):")
        print(jr.round(3).to_string())
        jr.to_csv(OUT / "auction_result_jump.csv")

    print(f"\n{len(panel):,} samples, {panel.groupby(['tenor','roll']).ngroups} events "
          f"({(time.time() - t0) / 60:.1f} min) -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

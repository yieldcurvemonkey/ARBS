"""Daily per-CUSIP UST panel for the olds-vs-currents switch study.

Why fetch by ALIAS and then relabel
-----------------------------------
Two facts pull in opposite directions.

*Fetching* wants aliases. There are ~900 distinct CUSIPs that pass through ranks 0-3 of
the seven tenors between 2010 and 2026, but only 7 x 4 = 28 alias slots. Querying the 28
is ~30x fewer round trips through the pricer, and ``FixedRateBondQuery.resolve_query``
re-resolves per date anyway.

*Everything downstream* wants fixed CUSIPs. An alias series SPLICES at each auction roll:
measured on the 2024-02-16 10y refunding, ``O10/CT10`` moved -1.395bp day-over-day while
the continuously-held pair moved -0.358bp. Diffing the alias would have booked 1.04bp of
P&L that nobody earned -- on a trade whose entire premium is 0.1-1.8bp. It would have
manufactured the edge.

So: fetch by alias, then relabel each (date, alias) to the CUSIP that alias resolved to on
that date, using ``_filter_and_rank_ref_df`` -- the SAME function the MDP uses, so the two
rank maps cannot drift -- and pivot to (date x cusip). Everything after this file is
fixed-CUSIP and safe to difference.

The alias->cusip map is also the auction calendar: the date a tenor's rank-0 CUSIP changes
IS the roll, which is the clock the trade lives on.
"""

from __future__ import annotations

import argparse
import datetime
import os
import time
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

OUT_DIR = pathlib.Path(__file__).resolve().parent / "_data"
MAP_PATH = OUT_DIR / "alias_cusip_map.parquet"
PANEL_PATH = OUT_DIR / "bond_panel.parquet"

TENORS = (2, 3, 5, 7, 10, 20, 30)
MAX_RANK = 3  # CT / O / OO / OOO -- the aliases the parser actually supports
ALIAS_BY_RANK = {0: "CT", 1: "O", 2: "OO", 3: "OOO"}

#: FedInvest is the only free source with a per-CUSIP daily history this long.
DEFAULT_START = datetime.date(2010, 1, 1)
DEFAULT_END = datetime.date(2026, 8, 17)


def alias_for(rank: int, tenor: int) -> str:
    return f"{ALIAS_BY_RANK[rank]}{tenor}"


# --------------------------------------------------------------------------- map


def build_alias_map(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    """(date, tenor, rank) -> cusip, using the MDP's own ranking function."""
    import QuantLib as ql

    from MDP.FixedRateBonds.FixedRateBondsMDP import _filter_and_rank_ref_df
    from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import (
        update_reference_data,
    )

    ref = update_reference_data(source="fiscaldata", force_refresh=False)
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

    rows = []
    for ts in pd.date_range(start, end, freq="D"):
        d = ts.date()
        if not cal.isBusinessDay(ql.Date(d.day, d.month, d.year)):
            continue
        r = _filter_and_rank_ref_df(ref, d)
        if r.empty:
            continue
        r = r[r["rank"] <= MAX_RANK]
        for tenor in TENORS:
            sub = r[r["oi"] == f"{tenor}-Year"]
            for _, row in sub.iterrows():
                rows.append(
                    {
                        "date": pd.Timestamp(d),
                        "tenor": tenor,
                        "rank": int(row["rank"]),
                        "cusip": str(row["cusip"]),
                        "cpn": float(row["cpn"]),
                        "issue_date": pd.Timestamp(row["issue_date"]),
                        "maturity_date": pd.Timestamp(row["maturity_date"]),
                    }
                )
    out = pd.DataFrame(rows)
    out["alias"] = [alias_for(r, t) for r, t in zip(out["rank"], out["tenor"])]
    return out


def summarise_map(m: pd.DataFrame) -> None:
    print(f"alias map: {len(m):,} rows, {m['date'].nunique():,} business days, "
          f"{m['cusip'].nunique():,} distinct CUSIPs")
    print(f"  {m['date'].min().date()} .. {m['date'].max().date()}")
    print("\ncoverage by tenor (first/last date a rank-0 exists, distinct CUSIPs at rank<=3):")
    for tenor in TENORS:
        s = m[m["tenor"] == tenor]
        if s.empty:
            print(f"  {tenor:2d}Y: NONE")
            continue
        r0 = s[s["rank"] == 0]
        rolls = (r0.sort_values("date")["cusip"] != r0.sort_values("date")["cusip"].shift()).sum()
        maxr = s["rank"].max()
        print(f"  {tenor:2d}Y: {r0['date'].min().date()} .. {r0['date'].max().date()}  "
              f"cusips={s['cusip'].nunique():4d}  rolls={rolls:4d}  max_rank={maxr}")


# --------------------------------------------------------------------------- panel


def fetch_panel(
    start: datetime.date,
    end: datetime.date,
    amap: pd.DataFrame,
    *,
    source: str = "USTS_FEDINVEST_WSJ_LIVE-QL",
    n_jobs: int = 8,
    tenors=TENORS,
) -> pd.DataFrame:
    """Fetch YTM / DV01 / clean+dirty price per alias slot, then relabel to CUSIP."""
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
    from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
    from TB.FixedRateBondsTB import FixedRateBondsTB

    mdp = FixedRateBondsMDP(source=source)
    tb = FixedRateBondsTB(mdp, show_tqdm=True)

    VALUES = [
        FixedRateBondValue.YTM,
        FixedRateBondValue.DV01,
        FixedRateBondValue.CLEAN_PRICE,
        FixedRateBondValue.DIRTY_PRICE,
        FixedRateBondValue.MOD_DURATION,
    ]

    frames = []
    for tenor in tenors:
        # Clamp to the window where this tenor actually has a rank-0, so a tenor that did
        # not exist yet (20y before 2020-06) costs nothing instead of failing every day.
        sub = amap[(amap["tenor"] == tenor) & (amap["rank"] == 0)]
        if sub.empty:
            print(f"  {tenor}Y: no rank-0 in window, skipping", flush=True)
            continue
        t_start = max(start, sub["date"].min().date())
        t_end = min(end, sub["date"].max().date())

        # Fetch YEAR BY YEAR. A single 16-year get_timeseries call DEADLOCKED: the process
        # sat at 0.00 CPU seconds per 20s of wall clock with 150 threads in Wait and no
        # external sockets open, having written nothing for 55 minutes. The same code over
        # a 3-month window completes in seconds, so the failure is in the size of the
        # request, not the request. Chunking also makes the run resumable -- data/ts caches
        # per (asset, date), so a re-run skips what already landed -- and observable, which
        # the monolithic call was not.
        for yr in range(t_start.year, t_end.year + 1):
            c_start = max(t_start, datetime.date(yr, 1, 1))
            c_end = min(t_end, datetime.date(yr, 12, 31))
            if c_start > c_end:
                continue
            qs = [
                FixedRateBondQuery(cusip=alias_for(r, tenor), value=v,
                                   structure_kwargs={"notional": 1_000_000})
                for r in range(MAX_RANK + 1)
                for v in VALUES
            ]
            t0 = time.time()
            try:
                df = tb.get_timeseries(start=c_start, end=c_end, queries=qs, n_jobs=n_jobs)
            except Exception as exc:
                # A dead chunk is a fact to be printed, not a hole to be discovered later.
                print(f"  {tenor}Y {yr}: FAILED {type(exc).__name__}: {exc}", flush=True)
                continue
            if df is None or df.empty:
                print(f"  {tenor}Y {yr}: EMPTY", flush=True)
                continue
            df.columns = [str(c) for c in df.columns]
            long = df.stack().rename("value").reset_index()
            long.columns = ["date", "col", "value"]
            parts = long["col"].str.split(" ", expand=True)
            long["alias"] = parts[0]
            long["value_id"] = parts[2]
            long["tenor"] = tenor
            frames.append(long[["date", "tenor", "alias", "value_id", "value"]])
            print(f"  {tenor}Y {yr}: {df.shape[0]:4d} days x {df.shape[1]:2d} cols "
                  f"({time.time() - t0:.1f}s)", flush=True)

    if not frames:
        raise RuntimeError("no data fetched")
    long = pd.concat(frames, ignore_index=True)
    # TB indexes by datetime.date; the alias map carries Timestamps. Merging the two
    # raises rather than silently producing an empty join, but only because the dtypes
    # differ enough for pandas to notice -- coerce explicitly.
    long["date"] = pd.to_datetime(long["date"])
    wide = long.pivot_table(
        index=["date", "tenor", "alias"], columns="value_id", values="value", aggfunc="first"
    ).reset_index()
    wide.columns.name = None

    # Relabel to the CUSIP the alias actually was on that date. Inner join: an alias-day
    # with no map entry is a day the alias did not exist, and carrying it as an unlabelled
    # row is how a splice gets back in.
    keys = amap[["date", "tenor", "alias", "rank", "cusip", "cpn", "issue_date", "maturity_date"]]
    out = wide.merge(keys, on=["date", "tenor", "alias"], how="inner")
    return out.sort_values(["tenor", "date", "rank"]).reset_index(drop=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START.isoformat())
    ap.add_argument("--end", default=DEFAULT_END.isoformat())
    ap.add_argument("--map-only", action="store_true")
    ap.add_argument("--tenors", default="")
    ap.add_argument("--n-jobs", type=int, default=8)
    ap.add_argument("--out-suffix", default="")
    a = ap.parse_args(argv)

    start = datetime.date.fromisoformat(a.start)
    end = datetime.date.fromisoformat(a.end)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    map_path = MAP_PATH if not a.out_suffix else MAP_PATH.with_name(f"alias_cusip_map{a.out_suffix}.parquet")
    panel_path = PANEL_PATH if not a.out_suffix else PANEL_PATH.with_name(f"bond_panel{a.out_suffix}.parquet")

    print(f"building alias map {start} .. {end} ...")
    amap = build_alias_map(start, end)
    amap.to_parquet(map_path, index=False)
    summarise_map(amap)
    print(f"-> {map_path}")
    if a.map_only:
        return 0

    tenors = tuple(int(x) for x in a.tenors.split(",")) if a.tenors else TENORS
    print(f"\nfetching panel for tenors {tenors} ...")
    panel = fetch_panel(start, end, amap, n_jobs=a.n_jobs, tenors=tenors)
    panel.to_parquet(panel_path, index=False)
    print(f"\npanel: {panel.shape} -> {panel_path}")
    print(panel.groupby(["tenor", "rank"])["YTM"].agg(["count", "mean"]).round(3).to_string())
    miss = panel["YTM"].isna().mean()
    print(f"\nYTM missing: {miss:.2%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

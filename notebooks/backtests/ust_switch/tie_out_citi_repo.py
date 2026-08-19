"""Third-way tie-out: Citi Velocity GC / OTR repo vs the JPM-derived specialness.

Status on 2026-08-18: BLOCKED, not skipped
------------------------------------------
Citi Velocity repo history only comes through the Excel add-in over COM. Excel was running
(PID 37900, 1.5GB, "Book10") but the add-in was not reachable -- both attempts raised

    MDP.CitiVelocityExcel.errors.ExcelDiedError: Excel is no longer reachable
    ('NoneType' object has no attribute 'Workbooks')

and ``MDP/CitiVelocityExcel/repo/store.py`` deliberately does not retry ("retrying into a
dying OLE server is what wedges it, and recovery costs a full add-in re-login").
``reference_excel_restart_signin_stalls`` records that automated re-login has failed 4/4
times on this machine, so it was not attempted a third time.

This file is the finished harness. When Excel is signed in:

    <env>/python.exe -m MDP.CitiVelocityExcel.repo.store --refresh
    <env>/python.exe notebooks/backtests/ust_switch/tie_out_citi_repo.py

What it compares
----------------
Citi serves ``RATES.REPO.USD.{USTREASGC,USD5YOTR,USD10YOTR,USD30YOTR}.SPOT.<tenor>``, and
its specialness is ``OTR collateral - GC``. Two caveats that shape the comparison and are
NOT defects to be smoothed over:

1. **Citi's tenor axis is degenerate.** ``store.py`` measured 0.0000bp of spread across
   all 14 tenors on 1,255 of 1,255 days: Citi serves ONE number per (date, collateral) and
   replicates it. So Citi is an OVERNIGHT rate only. JPM publishes 1m and 3m TERM repo.
   Comparing Citi-ON against JPM-1m is a comparison of two different instruments, and they
   should agree in level and direction but not tick for tick -- particularly across a
   month-end or an FOMC date inside the 1m window.
2. **Citi covers on-the-run collateral only.** It cannot see ranks 1-3, which is most of
   what this study trades. That is why JPM is the primary source rather than a
   cross-check: it is per-ISSUE, so it prices the old legs too, and it runs nine years
   rather than five.

So this is a confirmation that the GC construction (modal repo across the day's universe)
matches an independently published GC, and that the OTR specialness levels agree. It is
not, and cannot be, a substitute for the JPM panel.
"""

from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
JPM_PANEL = HERE / "_data" / "jpm_issue_repo_panel.parquet"
OUT = HERE / "_data" / "citi_jpm_repo_tieout.parquet"

CITI_TO_TENOR = {"USD5YOTR": 5, "USD10YOTR": 10, "USD30YOTR": 30}


def load_citi() -> pd.DataFrame:
    from MDP.CitiVelocityExcel.repo import store

    df = store.load()
    df.index = pd.to_datetime(df.index)
    return df


def jpm_otr_specialness(tenor: int, horizon: str = "1m") -> pd.Series:
    """JPM specialness of the ON-THE-RUN issue of a tenor, by date.

    The on-the-run is identified as the issue with the LATEST issue date among that
    tenor's rows -- but the JPM extract carries no issue date, so it is resolved through
    the repo's own alias map instead, which is the same ranking the rest of the study
    uses. Falls back to "most special issue of the tenor" only if the map is absent, and
    says so, because silently picking the most special issue would guarantee agreement
    with an OTR series by construction.
    """
    panel = pd.read_parquet(JPM_PANEL)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["maturity"] = pd.to_datetime(panel["maturity"])
    p = panel[panel["oi"] == float(tenor)]

    amap_path = HERE / "_data" / "alias_cusip_map.parquet"
    if amap_path.exists():
        amap = pd.read_parquet(amap_path)
        amap["date"] = pd.to_datetime(amap["date"])
        otr = amap[(amap["tenor"] == tenor) & (amap["rank"] == 0)][
            ["date", "cpn", "maturity_date"]
        ].rename(columns={"maturity_date": "maturity"})
        m = otr.merge(p, on=["date", "cpn", "maturity"], how="inner")
        return m.set_index("date")[f"special_{horizon}_bp"].sort_index()

    print("!! no alias map -- falling back to max-special-of-tenor (NOT a clean control)")
    return p.groupby("date")[f"special_{horizon}_bp"].max().sort_index()


def main() -> int:
    try:
        citi = load_citi()
    except FileNotFoundError as exc:
        print("BLOCKED: no Citi repo store on disk.")
        print(f"  {exc}")
        print("\nRun this first, with Excel signed in to the Velocity add-in:")
        print("  <env>/python.exe -m MDP.CitiVelocityExcel.repo.store --refresh")
        return 2
    except Exception as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}")
        return 2

    from MDP.CitiVelocityExcel.repo import store

    gc_tag = store.repo_tag("USTREASGC", "ON")
    if gc_tag not in citi.columns:
        print(f"BLOCKED: Citi store has no {gc_tag}; columns = {list(citi.columns)[:8]} ...")
        return 2

    rows = []
    for coll, tenor in CITI_TO_TENOR.items():
        tag = store.repo_tag(coll, "ON")
        if tag not in citi.columns:
            print(f"  {coll}: absent from store, skipping")
            continue
        citi_sp = (citi[gc_tag] - citi[tag]) * 100.0
        jpm_sp = jpm_otr_specialness(tenor, "1m")
        j = pd.concat({"citi_bp": citi_sp, "jpm_bp": jpm_sp}, axis=1).dropna()
        if j.empty:
            print(f"  {coll}: no overlapping dates")
            continue
        j["tenor"] = tenor
        j["err_bp"] = j["citi_bp"] - j["jpm_bp"]
        rows.append(j.reset_index().rename(columns={"index": "date"}))
        print(
            f"  {tenor:2d}Y  n={len(j):5d}  "
            f"citi mean {j['citi_bp'].mean():6.2f}  jpm mean {j['jpm_bp'].mean():6.2f}  "
            f"corr {j['citi_bp'].corr(j['jpm_bp']):.3f}  "
            f"mean err {j['err_bp'].mean():+6.2f}  mae {j['err_bp'].abs().mean():5.2f}"
        )

    if not rows:
        print("no comparable series")
        return 1
    out = pd.concat(rows, ignore_index=True)
    out.to_parquet(OUT, index=False)
    print(f"\n-> {OUT}")
    print("\nNOTE: Citi is OVERNIGHT and on-the-run only; JPM is 1m TERM and per-issue. "
          "Level and direction should agree; tick-for-tick they should not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

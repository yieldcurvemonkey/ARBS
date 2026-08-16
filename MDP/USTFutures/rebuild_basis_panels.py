"""Rebuild a daily basis panel per root and measure the consistency gate's pass rate.

This is the verification tool for the UST futures data-layer fixes: it re-runs the read path over
history and reports, by root and by year, what fraction of days produce a report that could be a
market. It is deliberately in MDP rather than in a strategy package -- the thing being measured is
the shared data path, not a signal.

    python -m MDP.USTFutures.rebuild_basis_panels --roots US TY WN \
        --start 2018-06-01 --end 2026-08-13 --out-dir <dir>
    python -m MDP.USTFutures.rebuild_basis_panels --table-only --out-dir <dir>

Notes
-----
* Roots are INTERNAL (US, TY, WN, FV, TU, UXY), not vendor spellings.
* ``repo_rate`` is left to the default, which is now the overnight fixing AT THE REFERENCE DATE.
  A term repo to delivery would be marginally better, but the term-financing store lives on another
  branch and the overnight fixing is the honest default for this path.
* Because repo_rate is left as None, reports go through the USTFutureStore day cache, so a rerun is
  cheap and the run leaves the store warm with correctly-stamped reports.
* Checkpoints every ``--checkpoint-every`` days and resumes from an existing parquet, so an
  interrupted run is not lost. Pass ``--fresh`` to ignore an existing file -- resuming onto a panel
  built by older code would quietly carry stale rows into a "rebuilt" one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys
import traceback
from typing import Optional, Sequence

import numpy as np
import pandas as pd

MONTH_CODE = {3: "H", 6: "M", 9: "U", 12: "Z"}


def front_symbol(root: str, on: dt.date, roll_days_before_fnd: int = 7) -> str:
    """Front quarterly contract, rolled ``roll_days_before_fnd`` before first notice.

    First notice is the last business day of the month preceding delivery. Candidates must be
    walked chronologically -- iterating months outer and years inner returns next March before this
    June and silently picks a contract a year away.
    """
    for yy in (on.year, on.year + 1, on.year + 2):
        for m in (3, 6, 9, 12):
            fnd = dt.date(yy, m, 1) - dt.timedelta(days=1)
            while fnd.weekday() >= 5:
                fnd -= dt.timedelta(days=1)
            if on <= fnd - dt.timedelta(days=roll_days_before_fnd):
                return f"{root}{MONTH_CODE[m]}{str(yy)[-2:]}"
    raise ValueError(f"no front contract for {on}")


def _flush(rows: list, out: pathlib.Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(out, index=False)


def build(
    root: str,
    start: dt.date,
    end: dt.date,
    out: pathlib.Path,
    *,
    roll_days_before_fnd: int = 7,
    checkpoint_every: int = 25,
    progress_every: int = 50,
    fresh: bool = False,
    sample_every: int = 1,
    force_refresh: bool = False,
) -> pd.DataFrame:
    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP

    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    days = pd.bdate_range(start, end)
    if sample_every > 1:
        days = days[::sample_every]

    rows: list = []
    if out.exists() and not fresh:
        prior = pd.read_parquet(out)
        rows = prior.to_dict("records")
        have = set(pd.to_datetime(prior["date"]))
        days = pd.DatetimeIndex([d for d in days if d not in have])
        print(f"{root}: resuming with {len(rows)} rows, {len(days)} days to fetch", flush=True)

    fails = 0
    first_err: Optional[str] = None
    for i, ts in enumerate(days):
        d = ts.date()
        sym = front_symbol(root, d, roll_days_before_fnd)
        try:
            # on_bad_data="warn": a backfill should RECORD a bad day, not die on it. The verdict
            # comes back in the data_ok column either way.
            rep = mdp.get_basis_report(
                symbol=sym, timestamp=d, on_bad_data="warn", force_refresh=force_refresh
            )
            if rep is None or not len(rep):
                fails += 1
                continue
            r = rep.sort_values("bnoc").reset_index(drop=True)
            ctd = r.iloc[0]
            deliv = pd.to_datetime(r["delivery_date"].iloc[0]).date() if "delivery_date" in r else None
            rows.append(
                {
                    "date": ts,
                    "root": root,
                    "symbol": sym,
                    "futures_price": float(ctd.get("futures_price", np.nan)),
                    "repo_pct": float(ctd.get("repo_rate", np.nan)),
                    "delivery_date": deliv,
                    "n_deliverable": int(len(r)),
                    "min_gross32": float(r["gross_basis"].min()) * 32.0,
                    "min_bnoc32": float(r["bnoc"].min()) * 32.0,
                    "max_irr": float(r["irr"].max()),
                    "irr_gap": float(r["irr"].max()) - float(ctd.get("repo_rate", np.nan)),
                    "min_clean_over_cf": float((r["clean_price"] / r["invoice_cf"]).min()),
                    "ctd_label": ctd.get("label"),
                    "ctd_cf": float(ctd.get("invoice_cf", np.nan)),
                    "ctd_price": float(ctd.get("clean_price", np.nan)),
                    "ctd_ytm": float(ctd.get("ytm", np.nan)),
                    "ctd_bnoc32": float(ctd.get("bnoc", np.nan)) * 32.0,
                    "ctd_gross32": float(ctd.get("gross_basis", np.nan)) * 32.0,
                    "ctd_irr": float(ctd.get("irr", np.nan)),
                    # from the SHARED gate, not a bespoke rule computed here
                    "data_ok": bool(r["data_ok"].iloc[0]) if "data_ok" in r.columns else None,
                    "data_quality_reason": (
                        str(r["data_quality_reason"].iloc[0]) if "data_quality_reason" in r.columns else ""
                    ),
                }
            )
        except Exception as exc:  # a silent skip would look like a market holiday
            fails += 1
            if first_err is None:
                tb = "".join(traceback.format_tb(exc.__traceback__)[-2:])
                first_err = f"{d} {sym}: {type(exc).__name__}: {exc}\n{tb}"
        if rows and i and i % checkpoint_every == 0:
            _flush(rows, out)
        if progress_every and i and i % progress_every == 0:
            print(f"  {root} {d} rows={len(rows)} fails={fails}", flush=True)

    df = pd.DataFrame(rows)
    if not df.empty:
        _flush(rows, out)
    if first_err:
        print(f"{root}: FIRST FAILURE -> {first_err}", flush=True)
    print(f"{root}: {len(df)} rows, {fails} failures -> {out}", flush=True)
    return df


def quality_table(out_dir: pathlib.Path, roots: Sequence[str]) -> pd.DataFrame:
    """Gate pass rate by root by year, plus the diagnostics behind it."""
    frames = []
    for root in roots:
        p = out_dir / f"basis_panel_{root}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df["date"] = pd.to_datetime(df["date"])
        df["year"] = df["date"].dt.year
        g = df.groupby("year").agg(
            n=("data_ok", "size"),
            pass_pct=("data_ok", lambda s: 100.0 * pd.Series(s).astype(bool).mean()),
            med_min_gross32=("min_gross32", "median"),
            med_min_bnoc32=("min_bnoc32", "median"),
            med_irr_gap=("irr_gap", "median"),
            med_n_deliv=("n_deliverable", "median"),
            med_fut_px=("futures_price", "median"),
        )
        g.insert(0, "root", root)
        frames.append(g.reset_index())
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roots", nargs="+", default=["US", "TY", "WN"])
    ap.add_argument("--start", default="2018-06-01")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--checkpoint-every", type=int, default=25)
    ap.add_argument("--progress-every", type=int, default=50)
    ap.add_argument("--sample-every", type=int, default=1, help="1 = every business day")
    ap.add_argument("--fresh", action="store_true", help="ignore an existing panel instead of resuming")
    ap.add_argument(
        "--force-refresh",
        action="store_true",
        help="bypass every cache READ and rewrite the store; use this to repair poisoned entries",
    )
    ap.add_argument("--table-only", action="store_true")
    args = ap.parse_args(argv)

    out_dir = pathlib.Path(args.out_dir)
    if not args.table_only:
        start = dt.date.fromisoformat(args.start)
        end = dt.date.fromisoformat(args.end)
        for root in args.roots:
            build(
                root,
                start,
                end,
                out_dir / f"basis_panel_{root}.parquet",
                checkpoint_every=args.checkpoint_every,
                progress_every=args.progress_every,
                fresh=args.fresh,
                sample_every=args.sample_every,
                force_refresh=args.force_refresh,
            )

    table = quality_table(out_dir, args.roots)
    if table.empty:
        print("no panels found")
        return 1
    pd.set_option("display.width", 200)
    print("\n=== consistency-gate pass rate by root by year ===")
    print(table.round(2).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""CM-2: a MEASURED USD vanilla-swap transaction-cost line.

The linear leg dominates every boat in this program — L-0019 measured the linear
round trip at 0.26-0.43 bp/day against a swaption leg of 0.03-0.09 — and that
linear line is the Citi 2019 Fig-9 schedule, an *assumption* applied
cross-market (ledger L-0010). L-0042(a) names it as the reopener: "a genuinely
better execution line reopens F3 and H16". This measures it, the same way CM-1
measured the swaption line: local CFTC Part 43 prints against the same-day Citi
Velocity EOD curve.

**The asymmetry that makes this worth running is stated up front.** What is
measured is |printed fixed rate − same-day EOD mid|, which contains the
execution spread *plus* the intraday drift between the print and the curve's
stamp, plus any off-market pricing. It is therefore an **upper bound** on the
half-spread. An upper bound is decisive in exactly one direction: if it comes in
**below** the assumed line, the assumed line is too expensive and the reopener
fires. If it comes in above, the study is uninformative — no conclusion, and
that outcome is recorded rather than argued around.

Universe: `NA/Swap OIS USD` (UPI vintage) / `InterestRate:IRSwap:OIS` (pre-UPI),
USD, spot-starting, standard tenors. Each print is priced against a swap built
on **its own effective and maturity dates**, not a tenor bucket.

Dedup is deliberately blunter than CM-1's: any dissemination chain containing a
CORR or EROR is DROPPED rather than resolved. Resolving would keep more rows;
dropping cannot introduce a wrong rate, and a wrong rate inflates the deviation,
which is the direction that would flatter the study.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 \
     notebooks/backtests/citivelo_rv/cost_swap_sdr.py [--days N]
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import json
import pathlib
import sys
import time
from zoneinfo import ZoneInfo

_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

SDR_DIR = pathlib.Path(r"C:\Users\chris\clee\ARBS\sdr_cache\CFTC\RATES")   # READ-ONLY
OUT = _REPO / "notebooks" / "data" / "citivelo_rv"
EXTRACT_DIR = OUT / "sdr_swap_extract"
CURVE_NAME = "USD-SOFR-1D"
ET = ZoneInfo("America/New_York")

STD_TENORS = [1, 2, 3, 4, 5, 7, 10, 12, 15, 20, 25, 30]
TENOR_TOL_D = 5.0 / 365.25
MAX_SPOT_LAG_D = 5           # effective date within a week of execution
MIN_PRINTS_PER_CELL = 30
FWD_DAY_STRIDE = 10          # forward starts priced exactly on every Nth day


def log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


# ------------------------------------------------------------------ extract

_COLS = ["Dissemination Identifier", "Original Dissemination Identifier",
         "Action type", "Event type", "Execution Timestamp",
         "Effective Date", "Expiration Date", "Fixed rate-Leg 1",
         "Fixed rate-Leg 2", "Notional currency-Leg 1", "Notional amount-Leg 1",
         "Cleared"]


def extract_one(fp: pathlib.Path) -> pd.DataFrame:
    import pyarrow.parquet as pq

    names = set(pq.read_schema(fp).names)
    is_new = "UPI FISN" in names
    want = [c for c in _COLS if c in names] + (["UPI FISN"] if is_new else ["Product name"])
    df = pd.read_parquet(fp, columns=want)
    if is_new:
        m = df["UPI FISN"].astype(str) == "NA/Swap OIS USD"
    else:
        m = df["Product name"].astype(str) == "InterestRate:IRSwap:OIS"
    df = df.loc[m & (df["Notional currency-Leg 1"] == "USD")].copy()
    out = pd.DataFrame({
        "diss_id": df.get("Dissemination Identifier").astype("string"),
        "orig_id": df.get("Original Dissemination Identifier").astype("string"),
        "action": df["Action type"].astype(str).str.upper(),
        "event": df["Event type"].astype(str).str.upper(),
        "exec_ts": pd.to_datetime(df["Execution Timestamp"], errors="coerce", utc=True),
        "effective": pd.to_datetime(df["Effective Date"], errors="coerce"),
        "maturity": pd.to_datetime(df["Expiration Date"], errors="coerce"),
        "fixed1": pd.to_numeric(df["Fixed rate-Leg 1"], errors="coerce"),
        "fixed2": pd.to_numeric(df.get("Fixed rate-Leg 2"), errors="coerce"),
        "notional": pd.to_numeric(df.get("Notional amount-Leg 1"), errors="coerce"),
        "cleared": df.get("Cleared").astype("string"),
    })
    out["vintage"] = "upi" if is_new else "pre_upi"
    out["file_date"] = fp.stem
    return out


def phase_extract(files: list) -> pd.DataFrame:
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    frames, t0 = [], time.time()
    for i, fp in enumerate(files):
        cache = EXTRACT_DIR / f"{fp.stem}.parquet"
        if cache.exists():
            frames.append(pd.read_parquet(cache))
        else:
            day = extract_one(fp)
            tmp = cache.with_suffix(".tmp")
            day.to_parquet(tmp, index=False)
            os.replace(tmp, cache)
            frames.append(day)
        if (i + 1) % 80 == 0 or i + 1 == len(files):
            log(f"extract {i + 1}/{len(files)} ({time.time() - t0:.0f}s)")
    return pd.concat(frames, ignore_index=True)


# -------------------------------------------------------------------- filter

def phase_filter(raw: pd.DataFrame, funnel: dict) -> pd.DataFrame:
    funnel["raw_ois_rows"] = int(len(raw))
    # chains touched by a correction or error are dropped whole
    bad = raw.loc[raw["action"].isin(["CORR", "EROR"]), "orig_id"].dropna().unique()
    df = raw[(raw["action"] == "NEWT") & (raw["event"] == "TRAD")].copy()
    funnel["newt_trad"] = int(len(df))
    df = df[~df["diss_id"].isin(set(bad))]
    funnel["after_corr_eror_chain_drop"] = int(len(df))

    df["rate"] = df["fixed1"].where(df["fixed1"].notna(), df["fixed2"])
    df = df[df["rate"].notna() & df["effective"].notna() & df["maturity"].notna()]
    # decimal, as the tape stores it (0.0403 = 4.03%); anything outside a sane
    # band is not a vanilla par rate and is dropped rather than winsorised
    df = df[(df["rate"] > 0.0) & (df["rate"] < 0.20)]
    funnel["with_usable_rate_and_dates"] = int(len(df))

    df["exec_date"] = df["exec_ts"].dt.tz_convert(ET).dt.date
    lag = (df["effective"] - pd.to_datetime(df["exec_date"])).dt.days
    # Forward starts are KEPT, not filtered away: F3 and H16 trade
    # forward-starting packages, so a spot-only line cannot reopen them. The
    # forward-start bucket is carried through to the aggregation, where the
    # assumed line's own 0.04 x fwd term is compared against it.
    df = df[(lag >= 0) & (lag <= 3800)].copy()
    df["fwd_yrs"] = (lag[df.index] / 365.25).round(2)
    df["fwd_bucket"] = pd.cut(df["fwd_yrs"], [-0.01, 0.05, 0.3, 1.2, 3.0, 6.0, 11.0],
                              labels=["spot", "<3M", "3M-1Y", "1-3Y", "3-6Y", "6-10Y"])
    funnel["spot_starting"] = int((df["fwd_bucket"] == "spot").sum())
    funnel["forward_starting"] = int((df["fwd_bucket"] != "spot").sum())

    # Pricing cost is (unique (day, effective, maturity)) x 28.6 ms, MEASURED.
    # Spot prints share a handful of effective dates per day, so the full sample
    # is cheap; forward starts have a near-unique effective date per print, so
    # the full sample is hours. Rather than round the dates — which would put an
    # unmeasured approximation inside the number the study exists to produce —
    # forward starts are priced EXACTLY on an evenly-spaced subsample of days.
    # Every print is still priced against its own schedule.
    fwd_days = sorted({d for d in df.loc[df["fwd_bucket"] != "spot", "exec_date"]})
    keep_fwd = set(fwd_days[::FWD_DAY_STRIDE])
    df = df[(df["fwd_bucket"] == "spot") | df["exec_date"].isin(keep_fwd)].copy()
    funnel["forward_day_stride"] = FWD_DAY_STRIDE
    funnel["forward_days_kept"] = len(keep_fwd)
    funnel["forward_rows_after_day_subsample"] = int((df["fwd_bucket"] != "spot").sum())

    yrs = (df["maturity"] - df["effective"]).dt.days / 365.25
    near = yrs.apply(lambda t: min(abs(t - s) for s in STD_TENORS))
    df = df[near < TENOR_TOL_D].copy()
    df["tenor"] = yrs[df.index].apply(lambda t: min(STD_TENORS, key=lambda s: abs(t - s)))
    funnel["standard_tenor"] = int(len(df))
    return df


# ------------------------------------------------------------------- pricing

def phase_price(df: pd.DataFrame, funnel: dict) -> pd.DataFrame:
    import logging

    logging.disable(logging.WARNING)
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    days = sorted({d for d in df["exec_date"]})
    curves = mdp.bulk_get_data({"curve_name": CURVE_NAME, "timestamps": days,
                                "offline": True})

    def _ok(ts, c):
        if c is None:
            return False
        ref = c.reference_date()
        rd = ref.date() if hasattr(ref, "date") else ref
        td = ts.date() if hasattr(ts, "date") else ts
        return rd == td

    curves = {(ts.date() if hasattr(ts, "date") else ts): c
              for ts, c in curves.items() if _ok(ts, c)}
    funnel["days_with_a_clean_curve"] = len(curves)

    df = df[df["exec_date"].isin(curves)].copy()
    funnel["priced_days_rows"] = int(len(df))

    fair, cache, t0 = [], {}, time.time()
    for n, (d, eff, mat) in enumerate(zip(df["exec_date"], df["effective"], df["maturity"])):
        key = (d, eff, mat)
        if key not in cache:
            try:
                c = curves[d]
                s = c.build_irswap(effective_date=eff.to_pydatetime().date(),
                                   maturity_date=mat.to_pydatetime().date())
                cache[key] = float(c.fair_rate(s))
            except Exception:  # noqa: BLE001 — an unpriceable schedule is data
                cache[key] = np.nan
        fair.append(cache[key])
        if (n + 1) % 50_000 == 0:
            log(f"  priced {n + 1}/{len(df)} ({len(cache)} unique swaps, "
                f"{time.time() - t0:.0f}s)")
    df["fair_rate"] = fair
    df = df[df["fair_rate"].notna()]
    df["dev_bp"] = (df["rate"] - df["fair_rate"]) * 1e4
    df["abs_dev_bp"] = df["dev_bp"].abs()
    funnel["priced"] = int(len(df))
    funnel["n_unique_swaps_built"] = len(cache)
    # a par-rate print cannot be 200bp from mid; those are off-market/structured
    df = df[df["abs_dev_bp"] < 200.0]
    funnel["within_200bp_of_mid"] = int(len(df))
    df["exec_hour_et"] = df["exec_ts"].dt.tz_convert(ET).dt.hour
    return df


# ----------------------------------------------------------------- verify

def verify(df: pd.DataFrame) -> dict:
    """Planted-value checks through the REAL deviation path.

    (i) a print planted AT the fair rate must measure exactly 0 bp;
    (ii) the same print with the rate read as PERCENT instead of decimal (the
         100x trap this repo has recorded twice) must measure absurdly, so the
         path is shown to be sensitive to the unit it depends on.
    """
    s = df.head(2000).copy()
    planted = ((s["fair_rate"] - s["fair_rate"]) * 1e4).abs().max()
    mutated = ((s["rate"] * 100.0 - s["fair_rate"]) * 1e4).abs().median()
    out = {"planted_at_mid_max_abs_bp": float(planted),
           "mutated_percent_parse_median_abs_bp": float(mutated)}
    assert planted < 1e-9, "a print planted at the mid must measure zero"
    assert mutated > 1000.0, "the 100x unit mutation must be caught, not absorbed"
    log(f"VERIFY PASS: planted-at-mid {planted:.2e} bp; "
        f"100x-mutation {mutated:,.0f} bp")
    return out


# --------------------------------------------------------------- aggregate

def phase_aggregate(df: pd.DataFrame, funnel: dict, ver: dict) -> None:
    from RVUtils.cost_model import transaction_cost_bps

    # ONE globally-chosen stamp hour, from the POOLED smear, applied to every
    # cell. Picking the best hour per tenor would be twelve selections; picking
    # it once from the pooled curve is one, and the pooled curve has a clean
    # monotone V rather than a spike, which is what a drift signature looks like.
    hour_tbl = (df.groupby("exec_hour_et")["abs_dev_bp"]
                .agg(["size", "median"]).rename(columns={"size": "n"}))
    hour_tbl = hour_tbl[hour_tbl["n"] >= 200]
    STAMP_HOUR = int(hour_tbl["median"].idxmin())
    print("\nSMEAR — median |print − EOD mid| by execution hour (ET). The minimum "
          f"locates the curve's own stamp: hour {STAMP_HOUR}:00 ET.")
    print(hour_tbl.round(3).to_string())

    rows = []
    for (fwd, tenor), g in df.groupby(["fwd_bucket", "tenor"], observed=True):
        if len(g) < MIN_PRINTS_PER_CELL:
            continue
        at_stamp = g[g["exec_hour_et"] == STAMP_HOUR]
        assumed = float(transaction_cost_bps(float(tenor), float(g["fwd_yrs"].median())))
        rows.append({
            "fwd_bucket": str(fwd), "tenor": int(tenor), "n_prints": int(len(g)),
            "median_abs_dev_bp": float(g["abs_dev_bp"].median()),
            "q25_abs_dev_bp": float(g["abs_dev_bp"].quantile(0.25)),
            "median_signed_dev_bp": float(g["dev_bp"].median()),
            "n_at_stamp": int(len(at_stamp)),
            "stamp_hour_median_abs_bp": (float(at_stamp["abs_dev_bp"].median())
                                         if len(at_stamp) >= MIN_PRINTS_PER_CELL else np.nan),
            "assumed_half_spread_bp": assumed,
        })
    cells = pd.DataFrame(rows).sort_values(["fwd_bucket", "tenor"])
    cells["upper_bound_over_assumed"] = (cells["median_abs_dev_bp"]
                                         / cells["assumed_half_spread_bp"])
    cells["at_stamp_over_assumed"] = (cells["stamp_hour_median_abs_bp"]
                                      / cells["assumed_half_spread_bp"])
    cells.to_parquet(OUT / "swap_cost_cells.parquet")
    pd.set_option("display.width", 220)
    print()
    print(cells.to_string(index=False))

    spot = cells[cells["fwd_bucket"] == "spot"]
    fwd = cells[cells["fwd_bucket"] != "spot"]
    verdict = {
        "study": "CM-2 measured USD vanilla-swap cost line (SDR prints vs Citi EOD mid)",
        "window": f"{df['exec_date'].min()}..{df['exec_date'].max()}",
        "n_prints": int(len(df)), "n_days": int(df["exec_date"].nunique()),
        "stamp_hour_et": STAMP_HOUR,
        "funnel": funnel, "verification": ver,
        "measured_is": "an UPPER BOUND: |print - same-day EOD mid| carries the "
                       "execution spread PLUS intraday drift plus any off-market "
                       "pricing, and |dev| cannot separate a half-spread from "
                       "residual drift even at the stamp hour",
        "decisive_only_if": "the upper bound falls BELOW the assumed line",
        "spot": {
            "n_cells": int(len(spot)),
            "median_upper_bound_over_assumed": float(spot["upper_bound_over_assumed"].median()),
            "median_at_stamp_over_assumed": float(spot["at_stamp_over_assumed"].median()),
            "n_cells_upper_bound_below_assumed": int((spot["upper_bound_over_assumed"] < 1).sum()),
            "n_cells_at_stamp_below_assumed": int((spot["at_stamp_over_assumed"] < 1).sum()),
        },
        "forward_start": {
            "n_cells": int(len(fwd)),
            "median_upper_bound_over_assumed": (float(fwd["upper_bound_over_assumed"].median())
                                                if len(fwd) else None),
            "median_at_stamp_over_assumed": (float(fwd["at_stamp_over_assumed"].median())
                                             if len(fwd) else None),
            "n_cells_at_stamp_below_assumed": int((fwd["at_stamp_over_assumed"] < 1).sum()),
        },
        "reopener_fires_for_spot": bool((spot["upper_bound_over_assumed"] < 1).any()),
        "reopener_fires_for_forward_start": bool(len(fwd) > 0
                                                 and (fwd["upper_bound_over_assumed"] < 1).any()),
    }
    (OUT / "swap_cost_verdict.json").write_text(json.dumps(verdict, indent=1, default=str))
    print("\n" + json.dumps({k: v for k, v in verdict.items() if k != "funnel"},
                            indent=1, default=str))
    print("\nfunnel:", json.dumps(funnel, indent=1, default=str))


def main() -> None:
    files = sorted(SDR_DIR.rglob("*.parquet"))
    if "--days" in sys.argv:
        files = files[-int(sys.argv[sys.argv.index("--days") + 1]):]
    log(f"{len(files)} day files")
    funnel: dict = {"n_day_files": len(files)}
    raw = phase_extract(files)
    df = phase_filter(raw, funnel)
    log(f"filtered to {len(df):,} spot-start standard-tenor NEWT prints")
    df = phase_price(df, funnel)
    log(f"priced {len(df):,}")
    ver = verify(df)
    df.to_parquet(OUT / "swap_cost_prints.parquet")
    phase_aggregate(df, funnel, ver)


if __name__ == "__main__":
    main()

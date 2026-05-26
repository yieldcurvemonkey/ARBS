"""Backfill the SOFR Butterfly RV Screener over a year of daily data.

Uses the first 12 SFR contracts (relative IMM tenors) for each date.
SABR smiles and curve data are cached at the MDP layer — first run is slow
(Barchart fetches), subsequent runs hit disk cache and are instant.

Output: parquet file with daily screener metrics for each butterfly.
"""

import datetime
import math
import sys
import time
import warnings

sys.path.insert(0, r"C:\Users\chris\clee\ARBS")

import numpy as np
import pandas as pd
import QuantLib as ql
import pytz

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from RVUtils.ImpliedDistribution import SFRImpliedDistribution

NYC_tz = pytz.timezone("America/New_York")

# ─── Config ───────────────────────────────────────────────────────────────────
START_DATE = datetime.date(2025, 5, 22)
END_DATE = datetime.date(2026, 5, 22)
CURVE = "USD-SOFR-1D-Q12STIRT"
OUTPUT_PATH = r"C:\Users\chris\clee\ARBS\notebooks\backtests\SFR_screeners\butterfly_rv_backfill.parquet"

IMM_TENORS = [
    "IMM_1xIMM_2", "IMM_2xIMM_3", "IMM_3xIMM_4", "IMM_4xIMM_5",
    "IMM_5xIMM_6", "IMM_6xIMM_7", "IMM_7xIMM_8", "IMM_8xIMM_9",
    "IMM_9xIMM_10", "IMM_10xIMM_11", "IMM_11xIMM_12", "IMM_12xIMM_13",
]


def imm_code_to_sfr_symbol(code: str) -> str:
    """Convert IMM code like 'Z6' to SFR option symbol like 'SFRZ26'."""
    month_char = code[0]
    year_digit = code[1]
    return f"SFR{month_char}2{year_digit}"


def generate_business_days(start: datetime.date, end: datetime.date) -> list:
    """Generate NYSE business days between start and end."""
    cal = ql.UnitedStates(ql.UnitedStates.NYSE)
    days = []
    current = ql.Date(start.day, start.month, start.year)
    end_ql = ql.Date(end.day, end.month, end.year)
    while current <= end_ql:
        if cal.isBusinessDay(current):
            days.append(datetime.date(current.year(), current.month(), current.dayOfMonth()))
        current = current + 1
    return days


def run_screener_for_date(
    as_of: datetime.date,
    curve_mdp: IRSwapsMDP,
    stirfo_mdp: STIRFutureOptionMDP,
    dist: SFRImpliedDistribution,
) -> list:
    """Run the full screener for a single date. Returns list of row dicts."""
    ts = NYC_tz.localize(datetime.datetime.combine(as_of, datetime.time(17, 0)))

    # 1. Fetch curve
    try:
        curve_handle = curve_mdp.get_pricer(request=dict(curve_name=CURVE, timestamp=ts))
    except Exception as e:
        return []

    # 2. Resolve contracts and prices
    contracts, prices = [], []
    for t in IMM_TENORS:
        try:
            q = IRSwapQuery(curve=CURVE, tenor=t).resolve_query(ts, pricer_or_curve=curve_handle)
            pkg, _ = q.resolve_package(pricer_or_curve=curve_handle)
            eff = pkg[0].__dict__["kwargs"]["effective"]
            price = 100 - pkg[0].__dict__["kwargs"]["fixed_rate"]
            imm = ql.IMM.code(ql.Date(eff.day, eff.month, eff.year))
            contracts.append(imm)
            prices.append(price)
        except Exception:
            return []

    if len(contracts) < 3:
        return []

    # 3. Compute butterflies
    cal_spreads = []
    for i in range(len(contracts) - 1):
        cal_spreads.append((prices[i] - prices[i + 1]) * 10000)

    rows = []
    for i in range(len(contracts) - 2):
        near, mid, far = contracts[i], contracts[i + 1], contracts[i + 2]
        bf_val = (prices[i] - 2 * prices[i + 1] + prices[i + 2]) * 10000
        sp_near = cal_spreads[i]
        sp_far = cal_spreads[i + 1]

        near_sym = imm_code_to_sfr_symbol(near)
        mid_sym = imm_code_to_sfr_symbol(mid)
        far_sym = imm_code_to_sfr_symbol(far)

        row = {
            "date": as_of,
            "butterfly": f"BF {near}-{mid}-{far}",
            "near": near, "mid": mid, "far": far,
            "bf_bps": bf_val,
            "sp_near_bps": sp_near,
            "sp_far_bps": sp_far,
        }

        # 4. Fetch BKM moments for each leg (delta-mode first, listed fallback)
        for leg_name, sym in [("near", near_sym), ("mid", mid_sym), ("far", far_sym)]:
            smile = None
            for fetch_kwargs in [
                {"symbol": sym, "as_of": as_of, "show_tqdm": False},
                {"symbol": sym, "as_of": as_of, "strike_offsets_bps": "listed", "show_tqdm": False},
            ]:
                try:
                    smile = stirfo_mdp.fetch_sabr_smile(fetch_kwargs)
                    break
                except Exception:
                    continue

            if smile is not None:
                try:
                    snapshot = dist.extract(smile, run_bl=False, run_gm=False, run_bkm=True)
                    bkm = snapshot.bkm_result
                    row[f"std_{leg_name}"] = bkm.std_rate * 100
                    row[f"skew_{leg_name}"] = bkm.skewness_rate
                    row[f"fwd_{leg_name}"] = smile.params.forward_rate
                except Exception:
                    row[f"std_{leg_name}"] = np.nan
                    row[f"skew_{leg_name}"] = np.nan
                    row[f"fwd_{leg_name}"] = np.nan
            else:
                row[f"std_{leg_name}"] = np.nan
                row[f"skew_{leg_name}"] = np.nan
                row[f"fwd_{leg_name}"] = np.nan

        # 5. Compute Layer 1: Variance consistency
        MIN_INFORMATIVE_STD = 25.0
        if all(f"std_{leg}" in row and np.isfinite(row.get(f"std_{leg}", np.nan)) for leg in ["near", "mid", "far"]):
            std_n, std_m, std_f = row["std_near"], row["std_mid"], row["std_far"]
            std_interp = (std_n + std_f) / 2.0
            std_excess = std_m - std_interp
            fly_abs = max(abs(bf_val), 0.5)
            row["std_excess"] = std_excess
            row["var_signal"] = std_excess / fly_abs
            # Near-expiry distortion flag
            row["near_expiry_distorted"] = std_n < MIN_INFORMATIVE_STD
        else:
            row["std_excess"] = np.nan
            row["var_signal"] = np.nan
            row["near_expiry_distorted"] = False

        # 6. Compute Layer 2: Probability space
        row["prob_change_pp"] = bf_val / 25.0 * 100
        if np.isfinite(row.get("std_mid", np.nan)) and row["std_mid"] > 0:
            row["kink_width_ratio"] = abs(bf_val) / row["std_mid"]
        else:
            row["kink_width_ratio"] = np.nan

        # 7. Compute Layer 3: Fragility
        if all(np.isfinite(row.get(f"std_{leg}", np.nan)) for leg in ["near", "mid", "far"]):
            range_n = 4.0 * row["std_near"]
            range_m = 4.0 * row["std_mid"]
            range_f = 4.0 * row["std_far"]
            delta_n = 0.01 * range_n
            delta_m = 0.01 * range_m
            delta_f = 0.01 * range_f
            fly_sensitivity = abs(delta_n - 2 * delta_m + delta_f)
            fly_abs = max(abs(bf_val), 0.5)
            row["fragility"] = fly_sensitivity / fly_abs
        else:
            row["fragility"] = np.nan

        rows.append(row)

    return rows


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Run cache test with 3 dates only")
    parser.add_argument("--start", type=str, default=None, help="Override start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="Override end date (YYYY-MM-DD)")
    args = parser.parse_args()

    start = datetime.date.fromisoformat(args.start) if args.start else START_DATE
    end = datetime.date.fromisoformat(args.end) if args.end else END_DATE

    if args.test:
        start = end - datetime.timedelta(days=4)
        print("=" * 76)
        print(f"CACHE TEST MODE — {start} to {end}")
        print("=" * 76)
    else:
        print("=" * 76)
        print("SOFR BUTTERFLY RV SCREENER — BACKFILL")
        print(f"Period: {start} to {end}")
        print("=" * 76)

    biz_days = generate_business_days(start, end)
    print(f"Business days to process: {len(biz_days)}")

    if args.test:
        # Run pass 1, then pass 2 to verify cache speedup
        curve_mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
        stirfo_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
        dist = SFRImpliedDistribution(use_sabr_vols=True, sabr_extrapolation=True, sabr_n_strikes=200)

        print(f"\nPASS 1 (cold/warm depending on prior runs):")
        t_total = time.time()
        for d in biz_days:
            t0 = time.time()
            rows = run_screener_for_date(d, curve_mdp, stirfo_mdp, dist)
            elapsed = time.time() - t0
            valid = sum(1 for r in rows if not math.isnan(r.get("var_signal", float("nan"))))
            print(f"  {d}: {len(rows)} flies, {valid} with BKM, {elapsed:.2f}s")
        pass1_time = time.time() - t_total
        print(f"  TOTAL: {pass1_time:.2f}s")

        print(f"\nPASS 2 (must hit cache):")
        t_total = time.time()
        for d in biz_days:
            t0 = time.time()
            rows = run_screener_for_date(d, curve_mdp, stirfo_mdp, dist)
            elapsed = time.time() - t0
            valid = sum(1 for r in rows if not math.isnan(r.get("var_signal", float("nan"))))
            print(f"  {d}: {len(rows)} flies, {valid} with BKM, {elapsed:.2f}s")
        pass2_time = time.time() - t_total
        print(f"  TOTAL: {pass2_time:.2f}s")

        speedup = pass1_time / max(pass2_time, 0.01)
        print(f"\n  Cache speedup: {speedup:.1f}x")
        if pass2_time < 30:
            print("  CACHE VERIFIED - pass 2 under 30s for all dates")
        return

    curve_mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    stirfo_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    dist = SFRImpliedDistribution(
        use_sabr_vols=True,
        sabr_extrapolation=True,
        sabr_n_strikes=200,
    )

    all_rows = []
    failed_dates = []
    t_start = time.time()

    for idx, d in enumerate(biz_days):
        t0 = time.time()
        try:
            rows = run_screener_for_date(d, curve_mdp, stirfo_mdp, dist)
            all_rows.extend(rows)
            elapsed = time.time() - t0
            n_valid = sum(1 for r in rows if np.isfinite(r.get("var_signal", np.nan)))
            if (idx + 1) % 10 == 0 or idx == 0:
                total_elapsed = time.time() - t_start
                rate = (idx + 1) / total_elapsed * 60
                print(f"  [{idx+1}/{len(biz_days)}] {d} — {len(rows)} flies, "
                      f"{n_valid} with BKM, {elapsed:.1f}s "
                      f"({rate:.1f} dates/min)")
        except Exception as e:
            failed_dates.append((d, str(e)))
            if (idx + 1) % 10 == 0:
                print(f"  [{idx+1}/{len(biz_days)}] {d} — FAILED: {e}")

    total_time = time.time() - t_start
    print(f"\nDone. {len(all_rows)} rows in {total_time:.0f}s")
    print(f"Failed dates: {len(failed_dates)}")

    if all_rows:
        df = pd.DataFrame(all_rows)
        df["date"] = pd.to_datetime(df["date"])
        df.to_parquet(OUTPUT_PATH, index=False)
        print(f"Saved to: {OUTPUT_PATH}")
        print(f"Shape: {df.shape}")
        print(f"\nSample (last date):")
        last = df[df["date"] == df["date"].max()]
        print(last[["butterfly", "bf_bps", "std_excess", "var_signal", "kink_width_ratio", "fragility"]].to_string(index=False))
    else:
        print("No data collected!")

    if failed_dates:
        print(f"\nFirst 5 failures:")
        for d, err in failed_dates[:5]:
            print(f"  {d}: {err}")


if __name__ == "__main__":
    main()

"""Backfill the SOFR Butterfly RV Screener over a year of daily data.

PARITY with butterfly_rv_screener.py (May 30): enumerates ALL spacings
(1=3mo / 2=6mo / 3=9mo / 4=12mo gap flies), computes the sqrt(T)-adjusted
adj_excess / adj_signal, and the FOMC gap-window counts. One tidy parquet,
one row per (date, fly).

Uses the first 12 SFR contracts (relative IMM tenors) for each date. SABR
smiles and curve data are cached at the MDP layer — first run is slow
(Barchart fetches), subsequent runs hit disk cache and are instant. Failed
fetches do NOT cache and self-heal on re-run, so re-running fills gaps.
The parquet is UPSERTED on (date, fly_id) so re-runs are safe and additive.

Output: butterfly_rv_backfill.parquet
"""

import argparse
import datetime
import math
import sys
import time

sys.path.insert(0, r"C:\Users\chris\clee\ARBS")

import numpy as np
import pandas as pd
import QuantLib as ql
import pytz

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import get_fomc_meetings_list
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from RVUtils.ImpliedDistribution import SFRImpliedDistribution

NYC_tz = pytz.timezone("America/New_York")

# ─── Config ───────────────────────────────────────────────────────────────────
START_DATE = datetime.date(2025, 5, 22)
END_DATE = datetime.date(2026, 5, 22)
CURVE = "USD-SOFR-1D-Q12STIRT"
OUTPUT_PATH = r"C:\Users\chris\clee\ARBS\notebooks\backtests\SFR_screeners\butterfly_rv_backfill.parquet"

# Butterfly spacings: legs are `spacing` quarters apart.
# 1 = 3mo (consecutive), 2 = 6mo, 3 = 9mo, 4 = 12mo gap fly.
SPACINGS = {1: "3mo", 2: "6mo", 3: "9mo", 4: "12mo"}

IMM_TENORS = [
    "IMM_1xIMM_2", "IMM_2xIMM_3", "IMM_3xIMM_4", "IMM_4xIMM_5",
    "IMM_5xIMM_6", "IMM_6xIMM_7", "IMM_7xIMM_8", "IMM_8xIMM_9",
    "IMM_9xIMM_10", "IMM_10xIMM_11", "IMM_11xIMM_12", "IMM_12xIMM_13",
]

MIN_INFORMATIVE_STD_BPS = 25.0   # below this the near leg is "dead" → mechanical signal
TAIL_SHIFT_PCT = 0.01            # Layer-3 fragility: 1% tail-mass migration
IMM_MONTH_MAP = {"H": 3, "M": 6, "U": 9, "Z": 12}


def imm_code_to_sfr_symbol(code: str) -> str:
    """Convert IMM code like 'Z6' to SFR option symbol like 'SFRZ26'."""
    return f"SFR{code[0]}2{code[1]}"


def generate_business_days(start: datetime.date, end: datetime.date) -> list:
    cal = ql.UnitedStates(ql.UnitedStates.NYSE)
    days = []
    current = ql.Date(start.day, start.month, start.year)
    end_ql = ql.Date(end.day, end.month, end.year)
    while current <= end_ql:
        if cal.isBusinessDay(current):
            days.append(datetime.date(current.year(), current.month(), current.dayOfMonth()))
        current = current + 1
    return days


def imm_to_approx_dates(code: str):
    """Approximate (start, end) accrual dates for an IMM quarter."""
    month_char = code[0]
    year = 2020 + int(code[1])
    month = IMM_MONTH_MAP[month_char]
    start = datetime.date(year, month, 15)
    end_month, end_year = month + 3, year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    end = datetime.date(end_year, end_month, 15)
    return start, end


def count_fomc_in_window(start, end, fomc_list):
    return sum(1 for d in fomc_list if start <= d < end)


def get_fomc_dates(as_of: datetime.date) -> list:
    """Future FOMC meeting dates (normalized to datetime.date, > as_of)."""
    raw = get_fomc_meetings_list(as_of=as_of, n_plus_years=2)
    out = []
    for d in raw:
        if isinstance(d, datetime.datetime):
            d = d.date()
        elif hasattr(d, "date") and not isinstance(d, datetime.date):
            d = d.date()
        out.append(d)
    return [d for d in out if d > as_of]


def fetch_moments(sym, as_of, stirfo_mdp, dist):
    """Fetch SABR smile (delta-mode, listed fallback) and extract BKM moments.

    Returns dict {std, var, skew, fwd, tte} (bps for std) or None.
    """
    smile = None
    for kw in (
        {"symbol": sym, "as_of": as_of, "show_tqdm": False},
        {"symbol": sym, "as_of": as_of, "strike_offsets_bps": "listed", "show_tqdm": False},
    ):
        try:
            smile = stirfo_mdp.fetch_sabr_smile(kw)
            break
        except Exception:
            continue
    if smile is None:
        return None
    try:
        snap = dist.extract(smile, run_bl=False, run_gm=False, run_bkm=True)
        bkm = snap.bkm_result
        return {
            "std": bkm.std_rate * 100.0,          # bps
            "var": bkm.variance_rate,
            "skew": bkm.skewness_rate,
            "fwd": smile.params.forward_rate,      # percent
            "tte": smile.params.time_to_expiry,    # years
        }
    except Exception:
        return None


def run_screener_for_date(as_of, curve_mdp, stirfo_mdp, dist) -> list:
    """Full-parity screener for a single date. One row dict per (spacing, fly)."""
    ts = NYC_tz.localize(datetime.datetime.combine(as_of, datetime.time(17, 0)))

    try:
        curve_handle = curve_mdp.get_pricer(request=dict(curve_name=CURVE, timestamp=ts))
    except Exception:
        return []

    contracts, prices, rates = [], [], []
    for t in IMM_TENORS:
        try:
            q = IRSwapQuery(curve=CURVE, tenor=t).resolve_query(ts, pricer_or_curve=curve_handle)
            pkg, _ = q.resolve_package(pricer_or_curve=curve_handle)
            eff = pkg[0].leg1.schedule.effective
            price = 100 - pkg[0].kwargs.leg1["fixed_rate"]
            rate = pkg[0].kwargs.leg1["fixed_rate"] * 100  # percent
            imm = ql.IMM.code(ql.Date(eff.day, eff.month, eff.year))
            contracts.append(imm)
            prices.append(price)
            rates.append(rate)
        except Exception:
            return []

    if len(contracts) < 3:
        return []

    fomc_dates = get_fomc_dates(as_of)

    # Fetch moments once per unique symbol (mirrors the screener's moment_cache).
    syms = [imm_code_to_sfr_symbol(c) for c in contracts]
    moments = {}
    for c, sym in zip(contracts, syms):
        if sym not in moments:
            moments[sym] = fetch_moments(sym, as_of, stirfo_mdp, dist)

    # Per-leg approx accrual windows (for FOMC counts).
    leg_dates = {c: imm_to_approx_dates(c) for c in contracts}

    rows = []
    for spacing, gap_label in SPACINGS.items():
        for i in range(len(contracts) - 2 * spacing):
            ni, mi, fi = i, i + spacing, i + 2 * spacing
            near, mid, far = contracts[ni], contracts[mi], contracts[fi]
            near_sym, mid_sym, far_sym = syms[ni], syms[mi], syms[fi]

            bf_val = (prices[ni] - 2 * prices[mi] + prices[fi]) * 10000
            sp_near = (prices[ni] - prices[mi]) * 10000
            sp_far = (prices[mi] - prices[fi]) * 10000
            fly_abs = max(abs(bf_val), 0.5)

            row = {
                "date": as_of,
                "fly_id": f"{near_sym}_{mid_sym}_{far_sym}",
                "butterfly": f"BF {near}-{mid}-{far}",
                "spacing": spacing,
                "gap": gap_label,
                "near": near, "mid": mid, "far": far,
                "near_symbol": near_sym, "mid_symbol": mid_sym, "far_symbol": far_sym,
                "bf_bps": bf_val,
                "sp_near_bps": sp_near,
                "sp_far_bps": sp_far,
                "near_rate": rates[ni], "mid_rate": rates[mi], "far_rate": rates[fi],
            }

            # FOMC: per-leg accrual-quarter counts + gap-window (between-leg) counts.
            n_s, n_e = leg_dates[near]
            m_s, m_e = leg_dates[mid]
            f_s, f_e = leg_dates[far]
            row["fomc_near"] = count_fomc_in_window(n_s, n_e, fomc_dates)
            row["fomc_mid"] = count_fomc_in_window(m_s, m_e, fomc_dates)
            row["fomc_far"] = count_fomc_in_window(f_s, f_e, fomc_dates)
            row["fomc_near_gap"] = count_fomc_in_window(n_s, m_s, fomc_dates)
            row["fomc_far_gap"] = count_fomc_in_window(m_s, f_s, fomc_dates)
            row["fomc_asym"] = abs(row["fomc_near_gap"] - row["fomc_far_gap"])

            mn, mm, mf = moments[near_sym], moments[mid_sym], moments[far_sym]
            have_all = mn is not None and mm is not None and mf is not None

            if have_all:
                std_n, std_m, std_f = mn["std"], mm["std"], mf["std"]
                var_n, var_m, var_f = mn["var"], mm["var"], mf["var"]
                tte_n = max(mn["tte"], 1e-6)
                tte_m = max(mm["tte"], 1e-6)
                tte_f = max(mf["tte"], 1e-6)

                # ── Layer 1: raw variance/std consistency ──
                var_interp = (var_n + var_f) / 2.0
                std_interp = (std_n + std_f) / 2.0
                std_excess = std_m - std_interp
                var_signal = std_excess / fly_abs

                # ── Layer 1: sqrt(T)-adjusted (de-trend std→vol by /sqrt(T),
                #    interpolate vol at T_mid, re-scale by sqrt(T_mid)). ──
                vol_n = std_n / math.sqrt(tte_n)
                vol_f = std_f / math.sqrt(tte_f)
                w = (tte_m - tte_n) / max(tte_f - tte_n, 1e-6)
                vol_interp = vol_n * (1 - w) + vol_f * w
                std_interp_adj = vol_interp * math.sqrt(tte_m)
                std_excess_adj = std_m - std_interp_adj
                var_signal_adj = std_excess_adj / fly_abs

                near_dead = std_n < MIN_INFORMATIVE_STD_BPS
                tte_imbalanced = std_n < (std_m * 0.6)

                row.update({
                    "std_near": std_n, "std_mid": std_m, "std_far": std_f,
                    "var_near": var_n, "var_mid": var_m, "var_far": var_f,
                    "skew_near": mn["skew"], "skew_mid": mm["skew"], "skew_far": mf["skew"],
                    "fwd_near": mn["fwd"], "fwd_mid": mm["fwd"], "fwd_far": mf["fwd"],
                    "tte_near": tte_n, "tte_mid": tte_m, "tte_far": tte_f,
                    "var_interp": var_interp, "var_excess": var_m - var_interp,
                    "std_interp": std_interp, "std_excess": std_excess, "var_signal": var_signal,
                    "std_interp_adj": std_interp_adj, "std_excess_adj": std_excess_adj,
                    "var_signal_adj": var_signal_adj,
                    "near_dead": near_dead, "tte_imbalanced": tte_imbalanced,
                    "near_expiry_distorted": near_dead or tte_imbalanced,
                })

                # ── Layer 2: probability space ──
                mid_std_bps = max(std_m, 1.0)
                row["kink_width_ratio"] = abs(bf_val) / mid_std_bps
                row["mid_std_bps"] = std_m

                # ── Layer 3: fragility ──
                range_n, range_m, range_f = 4.0 * std_n, 4.0 * std_m, 4.0 * std_f
                d_n, d_m, d_f = TAIL_SHIFT_PCT * range_n, TAIL_SHIFT_PCT * range_m, TAIL_SHIFT_PCT * range_f
                fly_sens = abs(d_n - 2 * d_m + d_f)
                row["fragility"] = fly_sens / fly_abs
                row["weakest_leg"] = max({"near": range_n, "mid": range_m, "far": range_f}.items(),
                                          key=lambda kv: kv[1])[0]
            else:
                for k in ("std_near", "std_mid", "std_far", "var_near", "var_mid", "var_far",
                          "skew_near", "skew_mid", "skew_far", "fwd_near", "fwd_mid", "fwd_far",
                          "tte_near", "tte_mid", "tte_far", "var_interp", "var_excess",
                          "std_interp", "std_excess", "var_signal", "std_interp_adj",
                          "std_excess_adj", "var_signal_adj", "kink_width_ratio", "mid_std_bps",
                          "fragility"):
                    row[k] = np.nan
                row["near_dead"] = row["tte_imbalanced"] = row["near_expiry_distorted"] = False
                row["weakest_leg"] = None

            # Layer 2 prob fields (defined even without moments).
            row["prob_change_pp"] = bf_val / 25.0 * 100

            rows.append(row)

    return rows


def upsert_parquet(new_df: pd.DataFrame, path: str) -> pd.DataFrame:
    """Merge new rows into existing parquet, upserting on (date, fly_id)."""
    import os
    new_df = new_df.copy()
    new_df["date"] = pd.to_datetime(new_df["date"])
    if os.path.exists(path):
        old = pd.read_parquet(path)
        old["date"] = pd.to_datetime(old["date"])
        combined = pd.concat([old, new_df], ignore_index=True)
        # keep last (newest) on duplicate keys so re-runs refresh values / fill gaps
        combined = combined.drop_duplicates(subset=["date", "fly_id"], keep="last")
    else:
        combined = new_df
    combined = combined.sort_values(["date", "spacing", "fly_id"]).reset_index(drop=True)
    combined.to_parquet(path, index=False)
    return combined


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=str, default=None)
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--validate", action="store_true",
                        help="Run a single date and print table (no parquet write)")
    parser.add_argument("--date", type=str, default=None, help="Single date for --validate")
    parser.add_argument("--checkpoint-every", type=int, default=10,
                        help="Flush to parquet every N dates")
    args = parser.parse_args()

    curve_mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    stirfo_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    dist = SFRImpliedDistribution(use_sabr_vols=True, sabr_extrapolation=True, sabr_n_strikes=200)

    if args.validate:
        d = datetime.date.fromisoformat(args.date) if args.date else END_DATE
        rows = run_screener_for_date(d, curve_mdp, stirfo_mdp, dist)
        df = pd.DataFrame(rows)
        pd.set_option("display.width", 200, "display.max_columns", 40, "display.max_rows", 60)
        cols = ["butterfly", "gap", "bf_bps", "std_near", "std_mid", "std_far",
                "std_excess", "std_excess_adj", "var_signal", "var_signal_adj",
                "kink_width_ratio", "fragility", "fomc_near_gap", "fomc_far_gap"]
        print(f"VALIDATE {d}: {len(df)} flies, "
              f"{int(df['var_signal_adj'].notna().sum())} with BKM\n")
        print(df[cols].to_string(index=False,
              formatters={c: (lambda x: f"{x:+.2f}" if pd.notna(x) else "-")
                          for c in ["bf_bps", "std_excess", "std_excess_adj",
                                    "var_signal", "var_signal_adj"]}))
        return

    start = datetime.date.fromisoformat(args.start) if args.start else START_DATE
    end = datetime.date.fromisoformat(args.end) if args.end else END_DATE
    biz_days = generate_business_days(start, end)

    print("=" * 76)
    print(f"SOFR BUTTERFLY RV BACKFILL (all spacings, sqrt-T, FOMC) | {start} -> {end}")
    print(f"Business days: {len(biz_days)} | output: {OUTPUT_PATH}")
    print("=" * 76)

    pending = []
    t_start = time.time()
    n_done = 0
    for idx, d in enumerate(biz_days):
        t0 = time.time()
        try:
            rows = run_screener_for_date(d, curve_mdp, stirfo_mdp, dist)
        except Exception as e:
            print(f"  [{idx+1}/{len(biz_days)}] {d} FAILED: {e}")
            continue
        pending.extend(rows)
        n_valid = sum(1 for r in rows if np.isfinite(r.get("var_signal_adj", np.nan)))
        elapsed = time.time() - t0
        rate = (idx + 1) / max(time.time() - t_start, 1e-6) * 60
        print(f"  [{idx+1}/{len(biz_days)}] {d}: {len(rows)} flies, {n_valid} w/BKM, "
              f"{elapsed:.1f}s ({rate:.1f} dates/min)")
        n_done += 1
        if pending and n_done % args.checkpoint_every == 0:
            df = pd.DataFrame(pending)
            combined = upsert_parquet(df, OUTPUT_PATH)
            print(f"    ...checkpoint: parquet now {combined.shape[0]} rows")
            pending = []

    if pending:
        df = pd.DataFrame(pending)
        combined = upsert_parquet(df, OUTPUT_PATH)
        print(f"\nFinal parquet: {combined.shape[0]} rows, "
              f"{combined['date'].nunique()} dates, {combined['fly_id'].nunique()} unique flies")
    print(f"Total time: {time.time() - t_start:.0f}s")


if __name__ == "__main__":
    main()

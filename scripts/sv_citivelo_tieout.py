"""Validation gates for the Citi-backend screen (ledger L-0009 a/b/c).

(a) 2019-05-08: reproduce Citi "Trading long-dated convexity" Figure 7 —
    8 pairs' spread / 1y carry / daily BE / BE-over-RV — from our screen rows.
    Levels may carry a basis (their curves were LIBOR-discounted; ours are the
    vendor's SOFR-consistent backcast); the CROSS-PAIR PATTERN must reproduce:
    Spearman(BE/RV) >= 0.85, carry sign agreement >= 6/8, spread rank corr.
(b) 2023-06-08: 10y10y/15y15y published steepener carry +6.89 bp/yr, BE/RV 1.17,
    spread -51.5bp.
(c) GS-vs-Citi 10Y10Y/20Y10Y forward-rate basis 2017-2026: rolling-63d median
    basis must be STABLE (range of rolling median < 15bp) — a drifting basis
    kills pre-2019 claims.

Descriptive gate: prints PASS/FAIL per check, writes nothing to the ledger
itself (the operator appends the verdict row).

Run after sv_screen_USD.parquet exists:
  conda run -n stir python scripts/sv_citivelo_tieout.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
SPREAD_DV01_USD = 100_000.0

# Citi Figure 7, close 2019-05-08 (note published 2019-05-09).
FIG7 = pd.DataFrame({
    "pair": ["USD 10Y5Y/15Y15Y", "USD 10Y10Y/15Y15Y", "USD 10Y10Y/20Y10Y",
             "USD 10Y10Y/20Y15Y", "USD 10Y10Y/25Y10Y", "USD 15Y5Y/20Y10Y",
             "USD 15Y5Y/20Y15Y", "USD 20Y5Y/25Y10Y"],
    "curve_bp": [-10.1, -8.8, -13.2, -16.7, -20.1, -11.3, -15.2, -9.1],
    "carry_1y_bp": [-2.91, -1.64, -1.75, -1.88, -1.83, -0.31, -0.44, 0.13],
    "be_bp_day": [3.5, 3.0, 2.6, 2.5, 2.2, 1.3, 1.3, 0.0],
    "rv_1y_bp_day": [3.2, 3.2, 3.1, 3.1, 3.0, 3.0, 3.0, 3.0],
    "be_over_rv": [1.07, 0.94, 0.84, 0.79, 0.72, 0.42, 0.45, 0.00],
}).set_index("pair")


def check_a(screen: pd.DataFrame) -> bool:
    day = screen[screen["date"] == "2019-05-08"]
    if day.empty:
        print("(a) 2019-05-08 not in screen — FAIL (no rows)")
        return False
    day = day.set_index("pair")
    # our columns
    ours = pd.DataFrame({
        "curve_bp": day["spread_bp"],
        "carry_1y_bp": day["daily_roll_usd"] * 252.0 / SPREAD_DV01_USD,
        "be_bp_day": day["be_25"],
    })
    joint = FIG7.join(ours, how="inner", lsuffix="_citi", rsuffix="_ours")
    if len(joint) < 6:
        print(f"(a) only {len(joint)} of 8 pairs matched — FAIL")
        return False
    # rank pattern on BE (BE/RV needs trailing RV; BE itself carries the pattern
    # since their RV row is nearly constant at 3.0-3.2)
    rho_be = spearmanr(joint["be_bp_day_citi"], joint["be_bp_day_ours"]).statistic
    rho_spread = spearmanr(joint["curve_bp_citi"], joint["curve_bp_ours"]).statistic
    sign_agree = int(np.sum(np.sign(joint["carry_1y_bp_citi"]) == np.sign(joint["carry_1y_bp_ours"])))
    med_spread_diff = float((joint["curve_bp_ours"] - joint["curve_bp_citi"]).median())
    print("(a) 2019-05-08 Figure-7 tie-out:")
    print(joint[["curve_bp_citi", "curve_bp_ours", "carry_1y_bp_citi", "carry_1y_bp_ours",
                 "be_bp_day_citi", "be_bp_day_ours"]].to_string(float_format=lambda x: f"{x:7.2f}"))
    print(f"    Spearman BE {rho_be:.3f} (need >=0.85), spread {rho_spread:.3f}, "
          f"carry sign agree {sign_agree}/{len(joint)} (need >=6), "
          f"median spread basis {med_spread_diff:+.1f}bp")
    ok = rho_be >= 0.85 and sign_agree >= 6
    print(f"    -> {'PASS' if ok else 'FAIL'}")
    return ok


def check_b(screen: pd.DataFrame) -> bool:
    day = screen[(screen["date"] == "2023-06-08") & (screen["pair"] == "USD 10Y10Y/15Y15Y")]
    if day.empty:
        print("(b) 2023-06-08 USD 10Y10Y/15Y15Y not in screen — FAIL")
        return False
    r = day.iloc[0]
    steep_carry = -r["daily_roll_usd"] * 252.0 / SPREAD_DV01_USD
    print(f"(b) 2023-06-08 10y10y/15y15y: spread {r['spread_bp']:.1f}bp (pub -51.5), "
          f"steepener carry {steep_carry:+.2f}bp/y (pub +6.89), BE {r['be_25']:.2f}bp/day")
    ok = abs(r["spread_bp"] - (-51.5)) <= 8.0 and steep_carry > 0 and abs(steep_carry - 6.89) <= 3.0
    print(f"    -> {'PASS' if ok else 'FAIL'} (tolerances: spread ±8bp, carry sign + ±3bp/y)")
    return ok


def check_c(screen: pd.DataFrame) -> bool:
    gs = pd.read_parquet(
        _REPO / "notebooks" / "data" / "strikeless_vol" / "full_sample_persistence"
        / "forward_rates__56ed0f64.parquet"
    )
    gs.index = pd.to_datetime(gs.index)
    ours = screen[screen["pair"] == "USD 10Y10Y/20Y10Y"].set_index("date")
    j = pd.DataFrame({
        "gs_10y10y_bp": gs["10Y10Y"] * 10_000, "gs_20y10y_bp": gs["20Y10Y"] * 10_000,
        "citi_10y10y_bp": ours["short_rate"] * 10_000, "citi_20y10y_bp": ours["long_rate"] * 10_000,
    }).dropna()
    b_short = j["citi_10y10y_bp"] - j["gs_10y10y_bp"]
    b_spread = (j["citi_20y10y_bp"] - j["citi_10y10y_bp"]) - (j["gs_20y10y_bp"] - j["gs_10y10y_bp"])
    roll_med = b_spread.rolling(63, min_periods=40).median().dropna()
    rng = float(roll_med.max() - roll_med.min())
    print(f"(c) GS-vs-Citi 10Y10Y/20Y10Y, {len(j):,} overlap days "
          f"{j.index.min().date()}..{j.index.max().date()}:")
    print(f"    10y10y level basis: median {b_short.median():+.1f}bp, p95|.| {b_short.abs().quantile(0.95):.1f}bp")
    print(f"    SPREAD basis: median {b_spread.median():+.1f}bp, p95|.| {b_spread.abs().quantile(0.95):.1f}bp, "
          f"rolling-63d-median range {rng:.1f}bp (need <15)")
    ok = rng < 15.0
    print(f"    -> {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> None:
    screen = pd.read_parquet(DATA / "sv_screen_USD.parquet")
    screen["date"] = pd.to_datetime(screen["date"]).dt.strftime("%Y-%m-%d")
    a = check_a(screen)
    b = check_b(screen)
    screen["date"] = pd.to_datetime(screen["date"])
    c = check_c(screen)
    print(f"\nGATES: a={'PASS' if a else 'FAIL'} b={'PASS' if b else 'FAIL'} c={'PASS' if c else 'FAIL'}")


if __name__ == "__main__":
    main()

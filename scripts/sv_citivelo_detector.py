"""Grail-quadrant detector + Citi Figure-7 screen columns (Task 26, H13 descriptive).

Consumes ``sv_screen_<MKT>.parquet`` (repriced greeks per pair per day) and adds
the derived screen columns, all causal (trailing windows only):

- ``carry_bp_yr``   spread carry of the FLATTENER: daily_roll_usd x 252 / spread DV01
- ``rv_rate_bp_day``  1y trailing realized vol of the LONG forward rate (RATE vol —
  the BE denominator; the spread's own vol is a different, labelled column)
- ``be_over_rv``    be_25 / rv_rate_bp_day    (<1 = embedded convexity cheap)
- ``spread_vol_bp_day``  63d trailing vol of the spread (sizing denominator)
- ``z_1y``/``z_3y`` trailing z-scores of the spread level
- ``flattener_carry_sign`` / ``grail_flattener``  carry >= 0 with positive gamma
  = the free-convexity state (Citi Mar-2020 definition)
- ``grail_steepener``  carry of the STEEPENER >= 0 while short convexity — the
  Jun-2023 positive-carry short-vol state

Descriptive only; nothing selects on performance.
Run: conda run -n stir python scripts/sv_citivelo_detector.py USD [EUR ...]
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
SPREAD_DV01_USD = 100_000.0


def _per_pair(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date").set_index("date")
    out = g.copy()
    out["carry_bp_yr"] = g["daily_roll_usd"] * 252.0 / SPREAD_DV01_USD
    d_long = (g["long_rate"] * 10_000).diff()
    d_spread = g["spread_bp"].diff()
    out["rv_rate_bp_day"] = d_long.rolling(252, min_periods=126).std()
    out["spread_vol_bp_day"] = d_spread.rolling(63, min_periods=40).std()
    out["be_over_rv"] = out["be_25"] / out["rv_rate_bp_day"]
    m1, s1 = g["spread_bp"].rolling(252, min_periods=126).mean(), g["spread_bp"].rolling(252, min_periods=126).std()
    m3, s3 = g["spread_bp"].rolling(756, min_periods=252).mean(), g["spread_bp"].rolling(756, min_periods=252).std()
    out["z_1y"] = (g["spread_bp"] - m1) / s1
    out["z_3y"] = (g["spread_bp"] - m3) / s3
    pos_gamma = g["gamma_25"] > 0
    out["grail_flattener"] = pos_gamma & (g["daily_roll_usd"] >= 0.0)
    out["steepener_carry_bp_yr"] = -out["carry_bp_yr"]
    # DESCRIPTIVE label only: the 1.25 cut is a hardcoded prior for readability.
    # Anything graded must band BE/RV by its own trailing distribution
    # (sv design: bands from the ratio's distribution, not constants).
    out["state_2023"] = pos_gamma & (out["be_over_rv"] > 1.25) & (out["steepener_carry_bp_yr"] > 0)
    return out.reset_index()


def main() -> None:
    markets = [m.upper() for m in (sys.argv[1:] or ["USD"])]
    frames = []
    for mkt in markets:
        p = DATA / f"sv_screen_{mkt}.parquet"
        if not p.exists():
            print(f"{mkt}: no screen parquet yet — skipped")
            continue
        df = pd.read_parquet(p)
        det = df.groupby("pair", group_keys=False).apply(_per_pair)
        out = DATA / f"sv_detector_{mkt}.parquet"
        det.to_parquet(out, index=False)
        frames.append(det)
        print(f"\n=== {mkt}: {det['pair'].nunique()} pairs, "
              f"{det['date'].min().date()}..{det['date'].max().date()} -> {out.name}")
        for pair, g in det.groupby("pair"):
            gg = g.dropna(subset=["be_over_rv"])
            if gg.empty:
                continue
            last = gg.iloc[-1]
            frac_grail = float(gg["grail_flattener"].mean())
            frac_2023 = float(gg["state_2023"].mean())
            print(f"  {pair:26s} n={len(gg):5d}  grail(flat) {frac_grail:5.1%}  "
                  f"state2023 {frac_2023:5.1%} | now: spread {last['spread_bp']:7.1f}bp "
                  f"carry {last['carry_bp_yr']:6.2f}bp/y BE {last['be_25']:4.2f} "
                  f"RV {last['rv_rate_bp_day']:4.2f} BE/RV {last['be_over_rv']:4.2f} "
                  f"z1y {last['z_1y']:5.2f}")
    if frames:
        print("\n(written per-market sv_detector_<MKT>.parquet)")


if __name__ == "__main__":
    main()

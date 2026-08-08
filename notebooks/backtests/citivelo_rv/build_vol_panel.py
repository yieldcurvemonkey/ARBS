"""Build the USD swaption vol panel from the SwaptionCubeStore.

One long parquet: (date, expiry, tenor, offset_bp, vol_bp, source, atm_only),
plus numeric expiry_yrs / tenor_yrs columns. ATM-only days (pre-2020-01-24,
tagged ``.../atm_only`` in source) are kept and flagged — mask on ``atm_only``,
never ffill into them.

Rebuild: ``conda run -n stir python notebooks/backtests/citivelo_rv/build_vol_panel.py``
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys
import time

_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

import pandas as pd

from Caching.swaption_cube_store import SwaptionCubeStore

ASSET = "USD-SWAPTIONVOL-CITIVELOEXCEL"
OUT_DIR = _REPO / "notebooks" / "data" / "citivelo_rv"

_TENOR_YRS = {"1M": 1 / 12, "2M": 2 / 12, "3M": 0.25, "6M": 0.5, "9M": 0.75,
              "1Y": 1.0, "18M": 1.5, "2Y": 2.0, "3Y": 3.0, "4Y": 4.0, "5Y": 5.0,
              "6Y": 6.0, "7Y": 7.0, "8Y": 8.0, "9Y": 9.0, "10Y": 10.0,
              "12Y": 12.0, "15Y": 15.0, "20Y": 20.0, "25Y": 25.0, "30Y": 30.0}


def tenor_to_years(tok: str) -> float:
    if tok in _TENOR_YRS:
        return _TENOR_YRS[tok]
    tok = tok.strip().upper()
    if tok.endswith("Y"):
        return float(tok[:-1])
    if tok.endswith("M"):
        return float(tok[:-1]) / 12.0
    raise ValueError(f"unparseable tenor {tok!r}")


def main() -> None:
    store = SwaptionCubeStore.default()
    dates = store.available_dates(ASSET)
    print(f"{ASSET}: {len(dates)} days {dates[0]} -> {dates[-1]}")

    t0 = time.time()
    frames = []
    for i, d in enumerate(dates):
        df = store.read_day(ASSET, d)
        if df is None or df.empty:
            continue
        keep = df[["expiry", "tenor", "offset_bp", "vol_bp", "source"]].copy()
        keep["date"] = pd.Timestamp(d)
        frames.append(keep)
        if (i + 1) % 250 == 0:
            print(f"  {i + 1}/{len(dates)} ({time.time() - t0:.0f}s)")

    panel = pd.concat(frames, ignore_index=True)
    panel["atm_only"] = panel["source"].str.endswith("atm_only")
    panel["expiry_yrs"] = panel["expiry"].map(tenor_to_years)
    panel["tenor_yrs"] = panel["tenor"].map(tenor_to_years)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "vol_panel.parquet"
    panel.to_parquet(out, index=False)
    print(f"wrote {out}: {len(panel):,} rows, {panel['date'].nunique()} days, "
          f"{time.time() - t0:.0f}s")
    print("expiries:", sorted(panel["expiry"].unique(), key=tenor_to_years))
    print("tenors:", sorted(panel["tenor"].unique(), key=tenor_to_years))
    print("offsets:", sorted(panel["offset_bp"].unique()))
    print("atm_only days:", panel.loc[panel["atm_only"], "date"].nunique())


if __name__ == "__main__":
    main()

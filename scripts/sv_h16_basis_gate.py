"""H16 oracle/pond gate — embedded-vs-traded vol basis, BEFORE any signal work.

Per (pair, locus): basis(t) = BE_25(pair, t) − IV_locus(t), both bp/day.
The gate asks whether the pond exists: on days the pre-registered trigger
(|z| ≥ 1.5 vs trailing 252d) would fire, what does the basis subsequently DO
at 5/21/63bd horizons, and how does the perfect-direction capture compare to
the round trip — linear package (initiate 0.75–1.0bp on $100k DV01, i.e.
$75–100k) plus the swaption leg at the CM-1 measured line (placeholder until
CM-1 lands: 0.5–1.9 annual normal bp of vega, era anchors), all converted to
vol-bp-of-basis via the vega$ match.

Descriptive; nothing selects a strategy. Registered under H-SV-16.

Run after sv_screen_USD.parquet exists:
  conda run -n stir python scripts/sv_h16_basis_gate.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.citivelo import citivelo_atm_vol_panel

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
PAIRS = ["USD 10Y10Y/20Y10Y", "USD 15Y5Y/20Y10Y"]
LOCI = ["2y10y", "10y10y", "20y10y"]
HORIZONS = [5, 21, 63]
SPREAD_DV01 = 100_000.0


def main() -> None:
    screen = pd.read_parquet(DATA / "sv_screen_USD.parquet")
    screen["date"] = pd.to_datetime(screen["date"])
    iv = citivelo_atm_vol_panel(LOCI)  # bp/day, 2015-10+ (ATM has pre-smile history)

    rows = []
    for pair in PAIRS:
        g = screen[screen["pair"] == pair].set_index("date").sort_index()
        be = g["be_25"]
        spread = g["spread_bp"]
        for locus in LOCI:
            j = pd.DataFrame({"be": be, "iv": iv[locus], "spread": spread}).dropna()
            basis = j["be"] - j["iv"]
            mu = basis.rolling(252, min_periods=126).mean()
            sd = basis.rolling(252, min_periods=126).std()
            z = (basis - mu) / sd
            # vega$ of the linear leg via rolling changes-beta (63d):
            db, div = j["spread"].diff(), (j["iv"] * np.sqrt(252)).diff()
            beta = db.rolling(252, min_periods=126).cov(div) / div.rolling(252, min_periods=126).var()
            vega_usd = beta.abs() * SPREAD_DV01  # $ per annual normal bp

            for h in HORIZONS:
                fwd = basis.shift(-h) - basis
                fire = z.abs() >= 1.5
                pond = fwd[fire].dropna()
                # oracle: perfect direction on fired days
                oracle = fwd[fire].abs().dropna()
                rows.append({
                    "pair": pair, "locus": locus, "h_bd": h,
                    "n_days": int(len(j)), "n_fired": int(fire.sum()),
                    "fired_frac": float(fire.mean()),
                    "basis_now": float(basis.iloc[-1]),
                    "z_now": float(z.iloc[-1]) if np.isfinite(z.iloc[-1]) else np.nan,
                    "basis_med": float(basis.median()),
                    "fwd_move_med": float(pond.median()) if len(pond) else np.nan,
                    "oracle_med_bp_day": float(oracle.median()) if len(oracle) else np.nan,
                    "oracle_p75_bp_day": float(oracle.quantile(0.75)) if len(oracle) else np.nan,
                    "vega_usd_med": float(vega_usd.median()),
                    # convert linear round trip to vol-bp-of-basis equivalent:
                    # 2x initiate $ / vega$ -> ANNUAL normal bp; /sqrt(252) -> bp/day
                    "lin_rt_volbp_day": float(
                        (2 * 0.75 * SPREAD_DV01) / vega_usd.median() / np.sqrt(252.0))
                    if vega_usd.median() > 0 else np.nan,
                })

    rep = pd.DataFrame(rows)
    out = DATA / "h16_basis_gate.parquet"
    rep.to_parquet(out, index=False)
    pd.set_option("display.width", 240)
    cols = ["pair", "locus", "h_bd", "n_days", "n_fired", "fired_frac", "basis_med",
            "basis_now", "z_now", "oracle_med_bp_day", "oracle_p75_bp_day",
            "vega_usd_med", "lin_rt_volbp_day"]
    print(rep[cols].to_string(index=False, float_format=lambda x: f"{x:8.3f}"))
    print(f"\nwrote {out.name}")
    print("\nREAD: oracle_med must clear lin_rt + the swaption-leg cost (CM-1, "
          "in bp/day = annual/15.87) with room; a pond smaller than the boat "
          "kills H16 before any signal work.")


if __name__ == "__main__":
    main()

"""H16b gate — the sandwich state: BE < realized < IV (pre-reg H-SV-16B).

The transcript's actual basis-trade thesis: when realized vol sits BETWEEN the
flattener's breakeven and the straddle's implied, both legs collect — the
flattener's convexity beats its roll AND the short straddle's theta beats its
gamma bill. Gate: occupancy of that state per (pair, locus), episode lengths,
and the wedge min(realized − BE, IV − realized) in bp/day vs the combined
round trip (linear leg + CM-1 swaption line). Descriptive; the graded
hold-through-state expression runs only if this pond is not already a puddle.

Run after the clean screen rebuild:
  conda run -n stir python scripts/sv_h16b_sandwich_gate.py
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
SPREAD_DV01 = 100_000.0
SQ252 = np.sqrt(252.0)

# CM-1 measured near-close ATM straddle HALF-spreads, annual bp (upper bounds)
CM1_HALF_ANNUAL = {"2y10y": 0.23, "10y10y": 0.17, "20y10y": 0.17}


def main() -> None:
    screen = pd.read_parquet(DATA / "sv_screen_USD.parquet")
    screen["date"] = pd.to_datetime(screen["date"])
    iv = citivelo_atm_vol_panel(LOCI)  # bp/day

    rows = []
    for pair in PAIRS:
        g = screen[screen["pair"] == pair].set_index("date").sort_index()
        rv = (g["long_rate"] * 1e4).diff().rolling(63, min_periods=63).std()
        for locus in LOCI:
            j = pd.DataFrame({"be": g["be_25"], "rv": rv, "iv": iv[locus],
                              "spread": g["spread_bp"]}).dropna()
            sandwich = (j["be"] < j["rv"]) & (j["rv"] < j["iv"])
            wedge = np.minimum(j["rv"] - j["be"], j["iv"] - j["rv"])
            # episode lengths
            runs, run = [], 0
            for v in sandwich:
                run = run + 1 if v else (runs.append(run) or 0 if run else 0)
            if run:
                runs.append(run)
            # combined round trip in bp/day-of-vol terms via the vega match
            db, div = j["spread"].diff(), (j["iv"] * SQ252).diff()
            beta = db.rolling(252, min_periods=126).cov(div) / div.rolling(252, min_periods=126).var()
            vega_usd = (beta.abs() * SPREAD_DV01).median()
            lin_rt = (2 * 0.75 * SPREAD_DV01) / vega_usd / SQ252 if vega_usd > 0 else np.nan
            swpt_rt = 2 * CM1_HALF_ANNUAL[locus] / SQ252
            rows.append({
                "pair": pair, "locus": locus, "n_days": len(j),
                "occupancy": float(sandwich.mean()),
                "n_episodes": len(runs),
                "median_episode_bd": float(np.median(runs)) if runs else np.nan,
                "wedge_med_bp_day": float(wedge[sandwich].median()) if sandwich.any() else np.nan,
                "wedge_p25": float(wedge[sandwich].quantile(0.25)) if sandwich.any() else np.nan,
                "in_state_now": bool(sandwich.iloc[-1]),
                "lin_rt_volbp_day": float(lin_rt),
                "swpt_rt_volbp_day": float(swpt_rt),
                "boat_volbp_day": float(lin_rt + swpt_rt),
            })

    rep = pd.DataFrame(rows)
    rep.to_parquet(DATA / "h16b_sandwich_gate.parquet", index=False)
    pd.set_option("display.width", 220)
    print(rep.to_string(index=False, float_format=lambda x: f"{x:7.3f}"))
    print("\nREAD: the wedge is a per-day COLLECTION rate while the state holds; "
          "boat is a one-off round trip. Pond-vs-boat = wedge x median episode "
          "length vs boat. Occupancy near zero, or wedge x episode << boat, kills H16b.")


if __name__ == "__main__":
    main()

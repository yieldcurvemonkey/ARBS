"""Reproduce the brief's 2026 USD numbers from raw data before extending.

Targets (2026 YTD, ~147 daily observations, USD 10y10y/20y10y):
  changes, 1 factor : beta ~ -0.78, R2 ~ 0.34, DW ~ 2.54
  changes, 2 factor : vol ~ -0.67 (significant), ASW ~ -0.17 (t ~ -1.2), R2 ~ 0.345
  levels,  2 factor : y = 5.66 - 1.18*vol + 0.443*ASW, R2 ~ 0.455, DW ~ 0.2-0.26
  levels residual   : AR(1) ~ 0.87 -> about a one-week half-life
  spread daily vol  : ~1.65 bp/day

Convention note (see RVUtils/StrikelessVol/panels.py:umep_panel docstring):
this repo's ``mmss_30Y`` is DESK convention (swap - UST, negative, ~-77bp at
30y). The brief's "ASW" regressor is TOOL convention (UST - swap, ~+74.6bp).
They are negatives of each other. This script negates ``mmss_30Y`` into tool
convention before regressing on it, and prints the convention of every
regressor used, so a reader never has to guess which sign a printed beta is
in. ``umep_bp_per_year`` needs no flip -- see the same docstring for why.

Anything that misses badly is a data or convention problem, not a discovery.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from RVUtils.StrikelessVol.factors import (
    ar1_half_life_days,
    ar1_phi,
    changes_regression,
    frequency_ladder,
    levels_regression,
)
from RVUtils.StrikelessVol.panels import forward_rate_panel, spread_panel, umep_panel, vol_panel
from RVUtils.StrikelessVol.universe import ALL_PAIRS
from RVUtils.StrikelessVol.vol_metrics import spread_vol_bp_day


def build(start=dt.date(2026, 1, 2), end=dt.date(2026, 8, 3)) -> dict:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    pair = next(p for p in ALL_PAIRS if p.name == "USD 10Y10Y/20Y10Y")
    dates = pd.bdate_range(start, end).date.tolist()
    rates = forward_rate_panel(
        "USD-OIS", dates, [pair.short, pair.long], mdp=IRSwapsMDP(source="GSQUANT-RL")
    )
    spread = spread_panel(rates, pair)
    vols = vol_panel("USD-SOFR-1D", ["2y 10y", "10y 10y"], start, end)
    vol_ann = vols["2y10y"] * (252 ** 0.5)  # the brief quotes annual normals
    umep = umep_panel(start, end)
    return {"pair": pair, "spread": spread, "vol_ann": vol_ann,
            "umep": umep.get("umep_bp_per_year"), "mmss_30y": umep.get("mmss_30Y")}


def main() -> None:
    print("=" * 78)
    print("Convention ledger (see panels.py:umep_panel docstring for the source):")
    print("  spread_panel        : bp, long forward - short forward (this repo)")
    print("  vol (vol_ann)       : bp/yr annualised normal (2y10y ATM swaption)")
    print("  mmss_30Y (raw)      : bp, DESK convention (swap - UST), ~-77bp at 30y")
    print("  asw30 (regressor)   : bp, TOOL convention (UST - swap) = -mmss_30Y,")
    print("                        matches the brief's ~+74.6bp; this script flips it")
    print("  umep_bp_per_year    : bp/yr, needs NO flip (TFP = -slope already lands")
    print("                        on the Dallas Fed's positive, rising convention)")
    print("=" * 78)

    d = build()
    spread, vol = d["spread"], d["vol_ann"]
    print(f"\nsample: spread n={len(spread)} [{spread.index.min().date()}..{spread.index.max().date()}], "
          f"vol n={len(vol)} [{vol.index.min().date()}..{vol.index.max().date()}]")

    one = changes_regression(spread, {"vol": vol})
    print(f"\nchanges 1F: beta={one.betas['vol']:+.3f} t={one.tstats['vol']:+.2f} "
          f"R2={one.r_squared:.3f} DW={one.durbin_watson:.2f} n={one.n}")
    print("  target   : beta ~ -0.78, R2 ~ 0.34, DW ~ 2.54")

    if d["mmss_30y"] is not None:
        asw30 = -d["mmss_30y"]  # desk -> tool convention; see module docstring above
        two = changes_regression(spread, {"vol": vol, "asw30": asw30})
        print(f"\nchanges 2F: vol={two.betas['vol']:+.3f} (t={two.tstats['vol']:+.2f}) "
              f"asw[tool]={two.betas['asw30']:+.3f} (t={two.tstats['asw30']:+.2f}) "
              f"R2={two.r_squared:.3f} n={two.n}")
        print("  target   : vol ~ -0.67 (significant), ASW ~ -0.17 (t ~ -1.2, insignificant), R2 ~ 0.345")

        lev = levels_regression(spread, {"vol": vol, "asw30": asw30})
        print(f"\nlevels  2F: vol={lev.betas['vol']:+.3f} asw[tool]={lev.betas['asw30']:+.3f} "
              f"R2={lev.r_squared:.3f} DW={lev.durbin_watson:.2f} n={lev.n} [ANCHOR ONLY]")
        print("  target   : y = 5.66 - 1.18*vol + 0.443*ASW, R2 ~ 0.455, DW ~ 0.2-0.26")
        print(f"\nlevels residual: phi={ar1_phi(lev.residuals):.3f} "
              f"half_life={ar1_half_life_days(lev.residuals):.1f}d "
              f"latest={lev.residuals.iloc[-1]:+.2f}bp")
        print("  target   : AR(1) ~ 0.87 -> ~one-week half-life")
    else:
        print("\n[SKIPPED] two-factor / levels: umep_panel returned no mmss_30Y "
              "(DB unavailable or empty result) -- reporting the gap, not "
              "shrinking the sample silently.")

    sv = spread_vol_bp_day(spread, window=63).iloc[-1]
    print(f"\nspread daily vol: {sv:.2f} bp/day")
    print("  target   : ~1.65 bp/day")

    print("\nfrequency ladder (changes regression at 1/5/21-day horizons):")
    print(frequency_ladder(spread, {"vol": vol}).to_string(index=False))


if __name__ == "__main__":
    main()

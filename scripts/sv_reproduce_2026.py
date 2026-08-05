"""Reproduce the brief's 2026 USD numbers from raw data before extending.

Targets (2026 YTD, ~147 daily observations, USD 10y10y/20y10y):
  changes, 1 factor : beta ~ -0.78, R2 ~ 0.34, DW ~ 2.54
  changes, 2 factor : vol ~ -0.67 (significant), ASW ~ -0.17 (t ~ -1.2), R2 ~ 0.345
  levels,  2 factor : y = 5.66 - 1.18*vol + 0.443*ASW, R2 ~ 0.455, DW ~ 0.2-0.26
  levels residual   : AR(1) ~ 0.87 -> about a one-week half-life
  spread daily vol  : ~1.65 bp/day (window unstated in the brief -- see the
                      whole-sample AND 63d-trailing prints below, and
                      RVUtils/StrikelessVol/vol_metrics.py's module docstring:
                      Task 15's review ruled the measured ~1.32bp/day, not the
                      brief's 1.65, is the correct number to size off of)

Convention note (see RVUtils/StrikelessVol/panels.py:umep_panel docstring):
this repo's ``mmss_30Y`` is DESK convention (swap - UST, negative, ~-77bp at
30y). The brief's "ASW" regressor is TOOL convention (UST - swap, ~+74.6bp).
They are negatives of each other. This script negates ``mmss_30Y`` into tool
convention before regressing on it, and prints the convention of every
regressor used, so a reader never has to guess which sign a printed beta is
in. ``umep_bp_per_year`` needs no flip -- see the same docstring for why.

Non-USD note: the ``RATESLIB_CURVE_DEFINITIONS`` fallback warning GS Quant
logs during the curve build below ("falling back to act360/nyc/mf") is a
NUMERIC NO-OP for this USD-OIS run -- act360/nyc/mf already *is* USD-OIS's
convention -- but would NOT be a no-op for a EUR/JPY/GBP run of this same
script; verify the fallback convention against the correct one explicitly
before trusting a non-USD reproduction.

Anything that misses badly is a data or convention problem, not a discovery.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.conventions import bp_day_to_annual_normals
from RVUtils.StrikelessVol.factors import (
    ar1_half_life_days,
    ar1_phi,
    changes_regression,
    frequency_ladder,
    levels_regression,
)
from RVUtils.StrikelessVol.panels import (
    _duration_inversion,
    forward_rate_panel,
    spread_panel,
    vol_panel,
)
from RVUtils.StrikelessVol.universe import ALL_PAIRS
from RVUtils.StrikelessVol.vol_metrics import spread_vol_bp_day


def build(start=dt.date(2026, 1, 2), end=dt.date(2026, 8, 3)) -> dict:
    from BT.signals.tfp_swap_spread import REGRESSION_TENORS, build_tfp_history
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    pair = next(p for p in ALL_PAIRS if p.name == "USD 10Y10Y/20Y10Y")
    dates = pd.bdate_range(start, end).date.tolist()
    # Forwards are re-derived from a log-cubic spline discount curve
    # (GSQUANT-RL, knots at 2-10, 12, 15, 20, 25, 30y), not directly quoted --
    # see vol_metrics.py's module docstring for why this makes the measured
    # spread vol/R2/DW differ from a quote-based series.
    rates = forward_rate_panel(
        "USD-OIS", dates, [pair.short, pair.long], mdp=IRSwapsMDP(source="GSQUANT-RL")
    )
    spread = spread_panel(rates, pair)
    vols = vol_panel("USD-SOFR-1D", ["2y 10y"], start, end)  # only 2y10y is used below
    vol_ann = pd.Series(bp_day_to_annual_normals(vols["2y10y"]), index=vols.index)

    # Fetched once (BT.signals.tfp_swap_spread.build_tfp_history is the slow,
    # per-day swap+bond pricing step) and used to derive BOTH the filtered
    # (umep_panel-equivalent, via the same tested `_duration_inversion` guard
    # Task 6 built) and unfiltered mmss_30Y series, so the two can be compared
    # (I5 robustness check) without a second, redundant network+DB pull.
    raw_tfp = build_tfp_history(start, end)
    if raw_tfp is None or raw_tfp.empty:
        return {"pair": pair, "spread": spread, "vol_ann": vol_ann,
                "mmss_30y_filtered": None, "mmss_30y_unfiltered": None,
                "excluded_dates": []}

    renamed = raw_tfp.rename(columns={"tfp": "umep_bp_per_year", "zds": "zds_bp"})
    exclude_idx = [
        idx for idx, row in renamed.iterrows()
        if _duration_inversion(row, REGRESSION_TENORS) is not None
    ]
    filtered = renamed.drop(index=exclude_idx)
    excluded_dates = sorted(d.date() if hasattr(d, "date") else d for d in exclude_idx)
    return {
        "pair": pair, "spread": spread, "vol_ann": vol_ann,
        "mmss_30y_filtered": filtered.get("mmss_30Y"),
        "mmss_30y_unfiltered": renamed.get("mmss_30Y"),
        "excluded_dates": excluded_dates,
    }


def _print_levels_2f(label: str, spread: pd.Series, vol: pd.Series, asw30: pd.Series) -> None:
    # ADF p-value must be Engle-Granger-corrected, not the standard single-series
    # table: this is a residual from an estimated 2-regressor cointegrating
    # regression (n_cointegrating_vars=3=2 regressors+1), and standard critical
    # values were measured (Task 15 round 4) to open this gate ~4x too often on
    # exactly this class of input. See ar1_half_life_days's docstring.
    from statsmodels.tsa.adfvalues import mackinnonp

    from RVUtils.regression import residual_diagnostics

    lev = levels_regression(spread, {"vol": vol, "asw30": asw30})
    print(f"\nlevels  2F [{label}]: intercept={lev.intercept:+.3f} vol={lev.betas['vol']:+.3f} "
          f"asw[tool]={lev.betas['asw30']:+.3f} "
          f"R2={lev.r_squared:.3f} DW={lev.durbin_watson:.2f} n={lev.n} [ANCHOR ONLY]")
    hl = ar1_half_life_days(lev.residuals, n_cointegrating_vars=3)
    diag = residual_diagnostics(lev.residuals)
    adf_p_eg = float(mackinnonp(diag["adf_stat"], regression="c", N=3)) if np.isfinite(diag["adf_stat"]) else float("nan")
    print(f"  levels residual [{label}]: phi={ar1_phi(lev.residuals):.3f} "
          f"half_life(EG-gated)={'inf' if not (hl < float('inf')) else f'{hl:.1f}d'} "
          f"(EG p={adf_p_eg:.3f}, standard p={diag['adf_pvalue']:.3f} shown for audit only -> "
          f"{'FAILS to reject unit root' if adf_p_eg > 0.05 else 'rejects unit root'}) "
          f"latest={lev.residuals.iloc[-1]:+.2f}bp")


def _print_changes_2f(label: str, spread: pd.Series, vol: pd.Series, asw30: pd.Series) -> None:
    two = changes_regression(spread, {"vol": vol, "asw30": asw30})
    print(f"changes 2F [{label}]: vol={two.betas['vol']:+.3f} (t={two.tstats['vol']:+.2f}) "
          f"asw[tool]={two.betas['asw30']:+.3f} (t={two.tstats['asw30']:+.2f}) "
          f"R2={two.r_squared:.3f} n={two.n}")


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
    print("  RATESLIB_CURVE_DEFINITIONS fallback warning below: numeric no-op for")
    print("                        USD-OIS (act360/nyc/mf IS this curve's convention);")
    print("                        would NOT be a no-op for a non-USD run.")
    print("=" * 78)

    d = build()
    spread, vol = d["spread"], d["vol_ann"]
    print(f"\nsample: spread n={len(spread)} [{spread.index.min().date()}..{spread.index.max().date()}], "
          f"vol n={len(vol)} [{vol.index.min().date()}..{vol.index.max().date()}]")

    one = changes_regression(spread, {"vol": vol})
    print(f"\nchanges 1F: beta={one.betas['vol']:+.3f} t={one.tstats['vol']:+.2f} "
          f"R2={one.r_squared:.3f} DW={one.durbin_watson:.2f} n={one.n}")
    print("  target   : beta ~ -0.78, R2 ~ 0.34, DW ~ 2.54")

    if d["mmss_30y_filtered"] is not None:
        asw30_filtered = -d["mmss_30y_filtered"]  # desk -> tool convention; see module docstring
        asw30_unfiltered = -d["mmss_30y_unfiltered"]

        print()
        _print_changes_2f("filtered, headline", spread, vol, asw30_filtered)
        print("  target   : vol ~ -0.67 (significant), ASW ~ -0.17 (t ~ -1.2, insignificant), R2 ~ 0.345")
        # I5 extension: the changes-2F ASW sign disagreement vs the brief was
        # left unresolved in the prior review round -- test it against the
        # same 7-day duration-monotonicity exclusion the levels-2F check used,
        # rather than leaving it open.
        _print_changes_2f("UNFILTERED, robustness check", spread, vol, asw30_unfiltered)

        # I5 robustness check: the degenerate-duration-monotonicity exclusion
        # (Task 6's guard) drops a temporally-clustered set of days, not a
        # scattered random sample -- fit with and without that block so the
        # headline levels-2F coefficients are not reported as if they were
        # insensitive to it without having checked.
        print("\n  target   : y = 5.66 - 1.18*vol + 0.443*ASW, R2 ~ 0.455, DW ~ 0.2-0.26")
        print("  target (residual): AR(1) ~ 0.87 -> ~one-week half-life")
        _print_levels_2f("filtered, headline", spread, vol, asw30_filtered)
        excl = d["excluded_dates"]
        print(f"  excluded by the duration-monotonicity guard: n={len(excl)} -> {excl}")
        _print_levels_2f("UNFILTERED, robustness check", spread, vol, asw30_unfiltered)
    else:
        print("\n[SKIPPED] two-factor / levels: build_tfp_history returned no mmss_30Y "
              "(DB unavailable or empty result) -- reporting the gap, not "
              "shrinking the sample silently.")

    sv_63 = spread_vol_bp_day(spread, window=63).iloc[-1]
    sv_full = spread.diff().dropna().std(ddof=1)
    print(f"\nspread daily vol (63d trailing, as of {spread.index.max().date()}): {sv_63:.2f} bp/day")
    print(f"spread daily vol (whole sample, n={spread.diff().dropna().shape[0]}): {sv_full:.2f} bp/day")
    print("  target   : ~1.65 bp/day (brief does not state its window)")
    print("  ruling   : Task 15 review adopts the MEASURED value for sizing, not the")
    print("             brief's 1.65 -- see vol_metrics.py's module docstring for the")
    print("             spline-smoothing mechanism and the CostSchedule double-count")
    print("             argument for why the lower, measured number is correct here.")

    print("\nfrequency ladder (changes regression at 1/5/21-day horizons):")
    print(frequency_ladder(spread, {"vol": vol}).to_string(index=False))


if __name__ == "__main__":
    main()

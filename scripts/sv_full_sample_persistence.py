"""Task 15 review round 2: does H6 (levels-residual mean-reversion) survive a
higher-power test than the 146-observation 2026-only sample allows?

An ADF on 146 observations of a near-unit-root process has very little power
-- failing to reject at p=0.267 (the 2026-only result) is weak evidence for a
unit root, not strong evidence. This script re-measures the same test with as
much history as each data source actually supports.

**The two factors do NOT have the same history depth, and this script does
not pretend otherwise:**

- ``spread`` (USD-OIS forward par rates) and ``vol`` (USD-SOFR-1D 2y10y
  implied normal, annualised): the vol panel's documented history starts
  2017-01-03; USD-OIS reaches back to 2010-10. Both are fetched for the full
  2017-01-03..2026-08-03 window here (~2400 business days).
- ``asw30``/UMEP (``BT.signals.tfp_swap_spread``, backed by the
  ``ERIS_EOD_LIVE-RL_BASIC`` SOFR curve): **directly probed before writing
  this script** (small windows at 2017, 2018, 2018-05, 2019, 2020-01,
  2020-04, 2020-07, 2020-09/10/11/12, 2021-01) and confirmed to return ZERO
  rows for every candidate before mid-2020, partial/sparse coverage through
  mid-2020, and dense, reliable coverage from 2021-01-04 onward. The
  two-factor residual therefore runs on 2021-01-04..2026-08-03 (~1450 daily
  observations) -- NOT the full 2017+ vol-panel history a naive reading of
  "vol starts 2017" would suggest. This is a real data-availability
  constraint, not a scope choice; see the round-2 report for the raw probe
  output.

Because the two-factor window is shorter than the one-factor window, this
script runs THREE regressions, not two, so the effect of adding the ASW
factor can be told apart from the effect of a shorter sample:

  (a) one-factor (vol only),  FULL 2017-01-03..2026-08-03  (~2400 obs, full power)
  (b) two-factor (vol+asw),   2021-01-04..2026-08-03        (~1450 obs, max robust UMEP window)
  (c) one-factor (vol only),  SAME 2021-01-04..2026-08-03    (~1450 obs, isolates window length)

(a) vs (c) isolates the effect of sample length alone (same one-factor spec,
different windows). (b) vs (c) isolates the effect of adding the ASW factor
(same window, one vs two factors).

ADF specification (must be stated explicitly per the review's requirement --
this is the SAME specification ``ar1_half_life_days``/
``RVUtils.regression.residual_diagnostics`` already use internally, made
visible here rather than left implicit): ``statsmodels.tsa.stattools.
adfuller``, ``regression="c"`` (constant only, no trend -- the standard
Engle-Granger residual-based cointegration-test convention; a regression
residual is already demeaned by its own intercept, so no additional trend
term is fitted), ``autolag="AIC"`` (lag length chosen to minimise AIC).

A rejection on the long sample is NOT license for Signal 3 on any window: if
the residual is stationary over nine years but its half-life is not short
relative to a tradeable holding period, the z-score bands built on it are
still not tradeable against this package's modeled round-trip cost. This
script prints the half-life next to that cost on every regression so the
comparison cannot be skipped.

**Round 3 addition -- expected reversion, not just half-life.** A half-life
alone is not an expectancy: a 20-day half-life with a small residual sigma
and a 47-day one with a large sigma are very different trades. For each
window this script now also measures the residual's own standard deviation
(bp -- the residual is a bp-denominated spread residual, so this is directly
comparable to the cost schedule) and computes the OU-style expected reversion
from a ``|z|=2`` entry: distance from mean at entry is ``2*sigma``; after one
half-life it has decayed by half to ``sigma``, so the reversion captured is
``2*sigma - sigma = sigma``; after two half-lives it has decayed to
``0.5*sigma`` (a quarter of the original ``2*sigma``), so the reversion
captured is ``2*sigma - 0.5*sigma = 1.5*sigma``. Net expectancy is that
reversion minus the modeled round-trip cost (``MAKER``/``TAKER`` from
``costs.py`` -- already expressed in bp of spread at the package's reference
$100k-DV01 clip, per ``test_initiation_cost_at_the_reference_clip``, so no
further unit conversion against a bp-denominated residual is needed). This is
an expectancy calculation, not a backtest: it says nothing about entry
frequency, path risk between entry and the assumed exit point, or whether
z=2 crossings are themselves well-behaved out of sample -- that is Task 18's
event study and net-of-cost P&L, not this script.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
from statsmodels.tsa.stattools import adfuller

from RVUtils.StrikelessVol.conventions import bp_day_to_annual_normals
from RVUtils.StrikelessVol.costs import MAKER, TAKER
from RVUtils.StrikelessVol.factors import ar1_half_life_days, ar1_phi, levels_regression
from RVUtils.StrikelessVol.panels import (
    PANEL_DIR,
    _duration_inversion,
    forward_rate_panel,
    spread_panel,
    vol_panel,
)
from RVUtils.StrikelessVol.universe import ALL_PAIRS

FULL_START = dt.date(2017, 1, 3)
TWO_FACTOR_START = dt.date(2021, 1, 4)
END = dt.date(2026, 8, 3)

CACHE_DIR = PANEL_DIR / "full_sample_persistence"


def build() -> dict:
    from BT.signals.tfp_swap_spread import REGRESSION_TENORS, build_tfp_history
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pair = next(p for p in ALL_PAIRS if p.name == "USD 10Y10Y/20Y10Y")
    dates = pd.bdate_range(FULL_START, END).date.tolist()
    print(f"fetching forward-rate panel {FULL_START}..{END} ({len(dates)} business days requested)...")
    rates = forward_rate_panel(
        "USD-OIS", dates, [pair.short, pair.long], mdp=IRSwapsMDP(source="GSQUANT-RL"),
        cache_path=CACHE_DIR / "forward_rates.parquet",
    )
    spread = spread_panel(rates, pair)
    vols = vol_panel(
        "USD-SOFR-1D", ["2y 10y"], FULL_START, END,
        cache_path=CACHE_DIR / "vol.parquet",
    )
    vol_ann = pd.Series(bp_day_to_annual_normals(vols["2y10y"]), index=vols.index)

    print(f"fetching UMEP/ASW {TWO_FACTOR_START}..{END} (the max robust window -- see module docstring)...")
    tfp_cache = CACHE_DIR / "tfp_history.parquet"
    raw_tfp = build_tfp_history(TWO_FACTOR_START, END, cache_path=str(tfp_cache))
    if raw_tfp is None or raw_tfp.empty:
        return {"spread": spread, "vol_ann": vol_ann, "asw30": None, "excluded": []}
    renamed = raw_tfp.rename(columns={"tfp": "umep_bp_per_year", "zds": "zds_bp"})
    exclude_idx = [
        idx for idx, row in renamed.iterrows()
        if _duration_inversion(row, REGRESSION_TENORS) is not None
    ]
    filtered = renamed.drop(index=exclude_idx)
    asw30 = -filtered["mmss_30Y"]  # desk -> tool convention
    excluded = sorted(d.date() if hasattr(d, "date") else d for d in exclude_idx)
    return {"spread": spread, "vol_ann": vol_ann, "asw30": asw30, "excluded": excluded}


def _adf_report(resid: pd.Series, label: str) -> dict:
    r = pd.Series(resid).astype(float).dropna()
    stat, pvalue, usedlag, nobs, crit, icbest = adfuller(r.to_numpy(), regression="c", autolag="AIC")
    phi = ar1_phi(resid)
    hl = ar1_half_life_days(resid)
    hl_str = "inf" if not (hl < float("inf")) else f"{hl:.1f}d"
    verdict = "FAILS to reject unit root" if pvalue > 0.05 else "REJECTS unit root"
    print(f"  [{label}] ADF(regression='c', autolag='AIC', lag={usedlag}, nobs={nobs}): "
          f"stat={stat:.3f} p={pvalue:.4f} crit(1%/5%/10%)="
          f"{crit['1%']:.3f}/{crit['5%']:.3f}/{crit['10%']:.3f} -> {verdict} at 5%")
    print(f"  [{label}] phi(downward-biased in finite samples)={phi:.4f} half_life={hl_str}")
    return {"phi": phi, "half_life": hl, "pvalue": pvalue}


def _expectancy_report(resid: pd.Series, hl: float, label: str) -> None:
    """|z|=2 expected-reversion expectancy vs. the modeled round-trip cost.

    See the module docstring for the OU-style sigma/1.5*sigma derivation.
    Skipped (not silently zero-filled) when the half-life is infinite --
    "expected reversion over one half-life" is meaningless without one.
    """
    sigma = float(pd.Series(resid).astype(float).dropna().std(ddof=1))
    print(f"  [{label}] residual sigma={sigma:.3f}bp (full-sample std, ddof=1, n={len(resid.dropna())})")
    if not (hl < float("inf")):
        print(f"  [{label}] expectancy: N/A -- half-life is infinite (no mean-reversion to time)")
        return
    reversion_1hl = sigma          # 2*sigma*(1 - exp(-ln2))   = 2*sigma*0.5  = sigma
    reversion_2hl = 1.5 * sigma    # 2*sigma*(1 - exp(-2*ln2)) = 2*sigma*0.75 = 1.5*sigma
    for n_hl, reversion, days in ((1, reversion_1hl, hl), (2, reversion_2hl, 2 * hl)):
        for name, cost in (("MAKER", 2 * MAKER.initiate_bp), ("TAKER", 2 * TAKER.initiate_bp)):
            net = reversion - cost
            verdict = "POSITIVE" if net > 0 else "NEGATIVE"
            print(f"  [{label}] |z|=2 entry, {n_hl} half-life (~{days:.1f}d holding): "
                  f"reversion={reversion:.2f}bp - {name} round trip {cost:.2f}bp "
                  f"= net {net:+.2f}bp [{verdict}]")


def _run_and_report(label: str, spread: pd.Series, drivers: dict) -> None:
    lev = levels_regression(spread, drivers)
    driver_str = " ".join(f"{k}={lev.betas[k]:+.3f}" for k in drivers)
    print(f"\n=== {label} ===")
    print(f"  intercept={lev.intercept:+.3f} {driver_str} R2={lev.r_squared:.3f} "
          f"DW={lev.durbin_watson:.3f} n={lev.n} [ANCHOR ONLY]")
    diag = _adf_report(lev.residuals, label)
    _expectancy_report(lev.residuals, diag["half_life"], label)


def main() -> None:
    d = build()
    spread, vol_ann, asw30 = d["spread"], d["vol_ann"], d["asw30"]
    print(f"\nspread n={len(spread)} [{spread.index.min().date()}..{spread.index.max().date()}]")
    print(f"vol    n={len(vol_ann)} [{vol_ann.index.min().date()}..{vol_ann.index.max().date()}]")
    if asw30 is not None:
        print(f"asw30  n={len(asw30)} [{asw30.index.min().date()}..{asw30.index.max().date()}] "
              f"(excluded by duration-monotonicity guard: {len(d['excluded'])})")

    # (a) one-factor, full 2017+ window -- does not need UMEP, genuinely full power
    _run_and_report("(a) ONE-FACTOR (vol), FULL 2017-01-03..2026-08-03", spread, {"vol": vol_ann})

    if asw30 is not None:
        # (b) two-factor, maximal robust UMEP window
        _run_and_report(
            "(b) TWO-FACTOR (vol+asw), 2021-01-04..2026-08-03 (max robust UMEP window)",
            spread, {"vol": vol_ann, "asw30": asw30},
        )

        # (c) one-factor, restricted to the SAME 2021+ window -- isolates window
        #     length from the added ASW factor.
        start_ts = pd.Timestamp(TWO_FACTOR_START)
        vol_2021 = vol_ann.loc[vol_ann.index >= start_ts]
        spread_2021 = spread.loc[spread.index >= start_ts]
        _run_and_report(
            "(c) ONE-FACTOR (vol), SAME 2021-01-04..2026-08-03 window as (b)",
            spread_2021, {"vol": vol_2021},
        )
    else:
        print("\n[SKIPPED] two-factor / same-window one-factor: build_tfp_history returned "
              "no data for the 2021+ window (DB/network unavailable) -- reporting the gap.")

    print("\n--- cost context (RVUtils/StrikelessVol/costs.py) ---")
    print(f"MAKER round trip (2x initiate_bp, one-way 0.75bp each): {2*MAKER.initiate_bp:.2f}bp")
    print(f"TAKER round trip (2x initiate_bp, one-way 1.00bp each): {2*TAKER.initiate_bp:.2f}bp")
    print("Already in bp of spread at the reference $100k-DV01 clip -- directly comparable")
    print("to a bp-denominated residual sigma, no further conversion needed (see")
    print("test_initiation_cost_at_the_reference_clip: 0.875bp on $100k DV01 = $87,500,")
    print("i.e. cost_usd = cost_bp * DV01_usd, the standard bp<->DV01 identity).")
    print("A half-life must be short relative to a holding period that can clear this cost")
    print("for z-score bands built on it to be tradeable -- a long sample rejecting a unit")
    print("root does not by itself establish that; see each block's expectancy above.")


if __name__ == "__main__":
    main()

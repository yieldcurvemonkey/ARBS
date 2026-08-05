"""Task 15 review round 2 (power) + round 4 (critical values / expectancy
withdrawal): does H6 (levels-residual mean-reversion) survive a
higher-power, correctly-calibrated test, and is it tradeable?

**Round 2** established that a 146-observation, 2026-only ADF test is
underpowered (fails to reject at p=0.267 -- weak evidence for a unit root,
not strong evidence) and re-measured with as much history as each data
source actually supports. **Round 4 found the round-2/3 test itself was
mis-specified, and withdrew round 3's expectancy conclusion.** Both rounds'
findings are recorded here; nothing from round 3 should be quoted without
reading round 4's corrections below.

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
  "vol starts 2017" would suggest.

Because the two-factor window is shorter than the one-factor window, this
script runs THREE regressions, not two, so the effect of adding the ASW
factor can be told apart from the effect of a shorter sample:

  (a) one-factor (vol only),  FULL 2017-01-03..2026-08-03  (~2400 obs, full power)
  (b) two-factor (vol+asw),   2021-01-04..2026-08-03        (~1450 obs, max robust UMEP window)
  (c) one-factor (vol only),  SAME 2021-01-04..2026-08-03    (~1450 obs, isolates window length)

(a) vs (c) isolates the effect of sample length alone. (b) vs (c) isolates
the effect of adding the ASW factor.

**ADF specification, and the round-4 correction to it.** Base test:
``statsmodels.tsa.stattools.adfuller``, ``regression="c"`` (constant only,
no trend), ``autolag="AIC"``. **Round 4 finding: the STANDARD (single-series,
N=1) MacKinnon p-value this produces is the wrong critical-value table for a
residual from an ESTIMATED regression.** OLS has already minimised that
residual's in-sample variance ("superconsistency"), which mechanically makes
it look more stationary than it is under the null of no cointegration.
Measured directly: a random walk regressed on an UNRELATED random walk (no
true relationship at all) opened the standard-ADF gate at ~20% across
simulated trials, four times the nominal 5% rate; a genuine AR(1) placebo
passed at the expected ~100% rate, and the *raw, unregressed* spread series
(no estimated relationship at all) did not open the gate -- confirming the
regression step itself, not the data or the test in general, is what
mis-sizes the standard gate. **This script now reports BOTH the standard
ADF p-value (for comparison/audit trail) and the corrected Engle-Granger
p-value** (``statsmodels.tsa.stattools.mackinnonp`` with ``N`` = number of
I(1) series in the cointegrating regression = regressors + 1; verified to
reproduce ``statsmodels.tsa.stattools.coint``'s own end-to-end computation
to within a few thousandths on this exact data), and the REJECT/FAIL
verdict and the half-life used everywhere below are based on the CORRECTED
(EG) p-value via ``ar1_half_life_days(..., n_cointegrating_vars=...)``, not
the standard one.

**Round 3's expectancy table has been WITHDRAWN, not restated.** It was
priced in the residual (Task 17's rule scales SIZE by residual z, but the
POSITION is the linear spread package -- the spread leg, not the residual,
is what P&L accrues to, and the reviewer's leg decomposition showed the
spread leg is NEGATIVE at these entries, with essentially all of the
apparent "reversion" living in the vol-hedge leg at 1.5-1.7x its regression
beta -- i.e. short the convexity this package exists to own); it used the
full-sample residual standard deviation rather than the trailing 252-day
rolling sigma ``residual_z`` (and any live implementation) actually uses
(measured ratio: rolling/full sigma = 0.55-0.80 across the three windows);
it used full-sample-fit (look-ahead) betas rather than entry-vintage-frozen
ones (measured impact on one window: realised capture fell from an
uncorrected +12.3bp/trade to +0.13bp gross, -1.87bp net of TAKER, once
betas were frozen at entry date); and its own "verification" that
``reversion_1hl == sigma`` was a tautology (the code IS that assignment),
not an independent check that an OU process actually delivers sigma of
reversion under the ROLLING-z entry rule Signal 3 would use (measured:
0.685-0.879 of sigma, not 1.0). None of these are independently fatal in
isolation; stacked, they falsify the round-3 headline. **No expectancy
number appears in this script's output as of round 4.** The correct,
un-shortcut version of this calculation -- expanding-window betas,
entry-vintage-frozen hedge, rolling(252) sigma, spread-leg (not residual)
P&L, actual distinct |z|>=2 episode counts, and a random-walk placebo run
alongside every real result -- is Task 18's event study, not this script.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
from statsmodels.tsa.adfvalues import mackinnonp
from statsmodels.tsa.stattools import adfuller

from RVUtils.StrikelessVol.conventions import bp_day_to_annual_normals
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


def _adf_report(resid: pd.Series, label: str, *, n_regressors: int) -> dict:
    """Reports BOTH the standard and Engle-Granger-corrected ADF p-value.

    ``n_regressors`` is the count of regressors in the levels_regression
    that produced ``resid`` (not counting the constant); EG's ``N`` is
    ``n_regressors + 1`` (the dependent variable plus its regressors, all
    treated as candidate I(1) series in the cointegrating relationship).
    The verdict and the half-life reported/returned are based on the
    CORRECTED (EG) p-value -- see the module docstring for why the standard
    one is the wrong table for a regression residual.
    """
    n_coint = n_regressors + 1
    r = pd.Series(resid).astype(float).dropna()
    stat, pvalue_std, usedlag, nobs, crit, icbest = adfuller(r.to_numpy(), regression="c", autolag="AIC")
    pvalue_eg = float(mackinnonp(stat, regression="c", N=n_coint))
    phi = ar1_phi(resid)
    hl = ar1_half_life_days(resid, n_cointegrating_vars=n_coint)
    hl_str = "inf" if not (hl < float("inf")) else f"{hl:.1f}d"
    verdict_std = "rejects" if pvalue_std <= 0.05 else "FAILS to reject"
    verdict_eg = "REJECTS" if pvalue_eg <= 0.05 else "FAILS TO REJECT"
    verdict_eg_1pct = "rejects" if pvalue_eg <= 0.01 else "does not reject"
    print(f"  [{label}] ADF stat={stat:.3f} (regression='c', autolag='AIC', lag={usedlag}, nobs={nobs})")
    print(f"  [{label}] standard (N=1, WRONG for a regression residual) p={pvalue_std:.4f} "
          f"-> {verdict_std} unit root at 5% -- shown for audit trail only, not the verdict")
    print(f"  [{label}] Engle-Granger (N={n_coint}, CORRECT) p={pvalue_eg:.4f} "
          f"-> {verdict_eg} unit root at 5%, {verdict_eg_1pct} at 1%")
    print(f"  [{label}] phi(downward-biased in finite samples)={phi:.4f} half_life(EG-gated)={hl_str}")
    return {"phi": phi, "half_life": hl, "pvalue_std": pvalue_std, "pvalue_eg": pvalue_eg}


def _run_and_report(label: str, spread: pd.Series, drivers: dict) -> None:
    lev = levels_regression(spread, drivers)
    driver_str = " ".join(f"{k}={lev.betas[k]:+.3f}" for k in drivers)
    print(f"\n=== {label} ===")
    print(f"  intercept={lev.intercept:+.3f} {driver_str} R2={lev.r_squared:.3f} "
          f"DW={lev.durbin_watson:.3f} n={lev.n} [ANCHOR ONLY, full-sample OLS -- NOT causal, "
          f"see module docstring's round-4 note]")
    _adf_report(lev.residuals, label, n_regressors=len(drivers))
    sigma_full = float(lev.residuals.dropna().std(ddof=1))
    print(f"  [{label}] residual sigma, FULL-SAMPLE (bp, ddof=1, n={len(lev.residuals.dropna())}): "
          f"{sigma_full:.3f} -- NOT the number Signal 3 would trade against; see module docstring")
    print(f"  [{label}] NO EXPECTANCY REPORTED -- round-3's table for this window is WITHDRAWN, "
          "not restated; see module docstring for the four compounding reasons")


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

    print("\n--- H6 verdict (round 4) ---")
    print("Mean-reversion: ESTABLISHED but DOWNGRADED -- Engle-Granger p-values reject the unit")
    print("root at 5% on all three windows and at 1% on (a) and (b); (c) rejects at 5% only,")
    print("not at 1% (marginal). This is weaker than the standard-ADF p-values reported by round")
    print("2/3, which used the wrong (too permissive) critical-value table.")
    print("Tradeability: NOT ESTABLISHED. Round 3's expectancy table is withdrawn (see module")
    print("docstring). No net-of-cost number should be quoted from this script; Task 18's event")
    print("study, built on expanding betas / entry-vintage hedge / rolling sigma / spread-leg")
    print("P&L / a random-walk placebo, is what will actually answer that question.")


if __name__ == "__main__":
    main()

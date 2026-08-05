"""H2: drag vs common factor. H3: does the vol beta scale with the vol level?

H2's discriminator (see ``RVUtils/StrikelessVol/treasury_forwards.py``'s module
docstring): a rising term funding premium (UMEP) mechanically drags long SWAP
rates down relative to bonds -- this "drag" channel has no analogue on a
forward built purely from the Treasury curve, so it must VANISH there. A
single balance-sheet regime that cheapens bonds versus swaps AND removes the
receiving bid ("common factor") would instead move both curves together, so
the UMEP coefficient should be similar (and same-signed) on both.

Per Task 15: UMEP is the correctly-signed regressor (Dallas Fed convention,
no flip needed); ``mmss_*``/desk convention is the opposite sign and must not
be substituted. Inference runs on CHANGES with HAC errors (levels DW ~0.2 in
this sample, spurious by construction). The comparison that actually
discriminates drag from common-factor is not "is the swap coefficient
negative" (Task 15 already found it statistically indistinguishable from
zero) -- it is the DIFFERENCE between the swap-built and Treasury-built
coefficients, with both standard errors. This script computes that
difference two ways: (a) the two coefficients side by side (as the brief's
pseudocode does), and (b) directly, by regressing the swap-minus-Treasury
slope DIFFERENCE on UMEP -- a single HAC t-stat on the quantity H2 is
actually asking about, immune to the two fits' shared-regressor covariance
that makes "eyeballing two separate t-stats" an unreliable comparison.

A placebo (phase-shuffled/circularly-shifted UMEP, preserving its own
autocorrelation and scale but destroying its timing/date correspondence to
the spread) is run alongside every real fit: if a placebo produces a
comparable-magnitude coefficient, the real coefficient is not evidence of
anything -- see the coordinator's brief and this repo's own precedent
(``feedback_adversarial_review_flatters.md``): three prior null models with
no true relationship to their mechanism have cleared a naive criterion in
this same build.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.factors import beta_vs_vol_level, changes_regression
from RVUtils.StrikelessVol.panels import PANEL_DIR, forward_rate_panel, spread_panel, umep_panel, vol_panel
from RVUtils.StrikelessVol.conventions import bp_day_to_annual_normals
from RVUtils.StrikelessVol.treasury_forwards import treasury_forward_panel
from RVUtils.StrikelessVol.universe import ALL_PAIRS

FULL_START = dt.date(2017, 1, 3)
TWO_FACTOR_START = dt.date(2021, 1, 4)
END = dt.date(2026, 8, 3)

# Reuse Task 15's exact cache directory/filenames -- same curve, same legs,
# same structures, same windows, so these are guaranteed cache hits rather
# than a redundant multi-hour network pull for data this package already has.
CACHE_DIR = PANEL_DIR / "full_sample_persistence"


def _circular_shift_placebos(series: pd.Series, *, n_draws: int = 20, seed: int = 42) -> list:
    """Phase-shuffled placebos: circular shifts of ``series``.

    Each draw is the exact same sequence of values (identical own
    autocorrelation, mean, variance -- a rotation changes none of them) but
    rotated by a random offset, so its correspondence to any OTHER series on
    a given date is destroyed. Shifts are restricted to [10%, 90%] of the
    series length so no draw is a near-identity (would leak the real
    alignment) or a near-full-cycle no-op.
    """
    rng = np.random.default_rng(seed)
    n = len(series)
    values = series.to_numpy()
    lo, hi = max(21, n // 10), n - max(21, n // 10)
    draws = []
    for _ in range(n_draws):
        shift = int(rng.integers(lo, hi))
        draws.append(pd.Series(np.roll(values, shift), index=series.index, name=series.name))
    return draws


def build_panels(pair, start=FULL_START, end=END):
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    dates = pd.bdate_range(start, end).date.tolist()

    swap_rates = forward_rate_panel(
        "USD-OIS", dates, [pair.short, pair.long], mdp=IRSwapsMDP(source="GSQUANT-RL"),
        cache_path=CACHE_DIR / "forward_rates.parquet",
    )
    swap_slope = spread_panel(swap_rates, pair)

    from scripts.sv_treasury_splines import spline_map

    ust_dates = pd.bdate_range(TWO_FACTOR_START, end).date.tolist()
    ust_rates = treasury_forward_panel(spline_map(ust_dates), [pair.short, pair.long])
    ust_slope = spread_panel(ust_rates, pair)

    vols = vol_panel(
        "USD-SOFR-1D", ["2y 10y"], start, end,
        cache_path=CACHE_DIR / "vol.parquet",
    )
    vol_ann = pd.Series(bp_day_to_annual_normals(vols["2y10y"]), index=vols.index)

    umep_df = umep_panel(
        TWO_FACTOR_START, end, cache_path=str(CACHE_DIR / "tfp_history.parquet"),
    )
    umep = umep_df["umep_bp_per_year"] if not umep_df.empty else pd.Series(dtype=float)

    return swap_slope, ust_slope, vol_ann, umep


def h2_table(swap_slope: pd.Series, ust_slope: pd.Series, vol_ann: pd.Series, umep: pd.Series,
             horizons=(1, 5, 21)) -> pd.DataFrame:
    rows = []
    diff_slope = (swap_slope - ust_slope).dropna()
    for label, slope in (("swap", swap_slope), ("treasury", ust_slope)):
        for h in horizons:
            r = changes_regression(slope, {"vol": vol_ann, "umep": umep}, horizon_days=h)
            rows.append({
                "label": label, "horizon_days": h,
                "umep_beta": r.betas["umep"], "umep_t": r.tstats["umep"],
                "vol_beta": r.betas["vol"], "vol_t": r.tstats["vol"],
                "r_squared": r.r_squared, "durbin_watson": r.durbin_watson, "n": r.n,
            })
    for h in horizons:
        r = changes_regression(diff_slope, {"vol": vol_ann, "umep": umep}, horizon_days=h)
        rows.append({
            "label": "swap-minus-treasury (diff)", "horizon_days": h,
            "umep_beta": r.betas["umep"], "umep_t": r.tstats["umep"],
            "vol_beta": r.betas["vol"], "vol_t": r.tstats["vol"],
            "r_squared": r.r_squared, "durbin_watson": r.durbin_watson, "n": r.n,
        })
    return pd.DataFrame(rows)


def h2_placebo(swap_slope: pd.Series, ust_slope: pd.Series, vol_ann: pd.Series, umep: pd.Series,
               horizons=(1, 5, 21), n_draws: int = 20) -> pd.DataFrame:
    """For each (label, horizon), the real UMEP |t| against the distribution
    of |t| from ``n_draws`` circular-shift placebos of UMEP.
    """
    placebos = _circular_shift_placebos(umep, n_draws=n_draws)
    diff_slope = (swap_slope - ust_slope).dropna()
    rows = []
    for label, slope in (("swap", swap_slope), ("treasury", ust_slope),
                          ("swap-minus-treasury (diff)", diff_slope)):
        for h in horizons:
            real = changes_regression(slope, {"vol": vol_ann, "umep": umep}, horizon_days=h)
            real_t = abs(real.tstats["umep"])
            placebo_ts = []
            for p in placebos:
                try:
                    pr = changes_regression(slope, {"vol": vol_ann, "umep": p}, horizon_days=h)
                    placebo_ts.append(abs(pr.tstats["umep"]))
                except Exception:
                    continue
            placebo_ts = np.array(placebo_ts)
            frac_ge = float((placebo_ts >= real_t).mean()) if len(placebo_ts) else float("nan")
            rows.append({
                "label": label, "horizon_days": h, "real_abs_t": real_t,
                "placebo_median_abs_t": float(np.median(placebo_ts)) if len(placebo_ts) else float("nan"),
                "placebo_max_abs_t": float(np.max(placebo_ts)) if len(placebo_ts) else float("nan"),
                "frac_placebo_ge_real": frac_ge, "n_placebo_draws": len(placebo_ts),
            })
    return pd.DataFrame(rows)


def h3_table(swap_slope: pd.Series, vol_ann: pd.Series, ust_slope: pd.Series = None) -> dict:
    out = {"swap": beta_vs_vol_level(swap_slope, vol_ann)}
    if ust_slope is not None and not ust_slope.dropna().empty:
        out["treasury"] = beta_vs_vol_level(ust_slope, vol_ann)
    return out


def main(start=FULL_START, end=END) -> None:
    pair = next(p for p in ALL_PAIRS if p.name == "USD 10Y10Y/20Y10Y")

    print("=== Convention ledger ===")
    print("spread (swap_slope, ust_slope) = bp, long fwd - short fwd (this repo's native convention)")
    print("vol_ann = bp/yr annualised normal, 2y10y ATM swaption (conventions.bp_day_to_annual_normals)")
    print("umep = umep_bp_per_year, Dallas Fed / tool convention, ALREADY correctly signed -- no flip "
          "(desk-convention mmss_* is the opposite sign and is NOT used here; see panels.umep_panel docstring)")

    swap_slope, ust_slope, vol_ann, umep = build_panels(pair, start=start, end=end)
    print(f"\nswap_slope  n={len(swap_slope.dropna())} [{swap_slope.index.min().date()}..{swap_slope.index.max().date()}]")
    print(f"ust_slope   n={len(ust_slope.dropna())} [{ust_slope.index.min().date() if len(ust_slope.dropna()) else 'n/a'}"
          f"..{ust_slope.index.max().date() if len(ust_slope.dropna()) else 'n/a'}]")
    print(f"vol_ann     n={len(vol_ann.dropna())} [{vol_ann.index.min().date()}..{vol_ann.index.max().date()}]")
    print(f"umep        n={len(umep.dropna())} [{umep.index.min().date() if len(umep.dropna()) else 'n/a'}"
          f"..{umep.index.max().date() if len(umep.dropna()) else 'n/a'}]")

    print("\n=== H2: swap-built vs Treasury-built UMEP coefficient ===")
    h2 = h2_table(swap_slope, ust_slope, vol_ann, umep)
    for _, row in h2.iterrows():
        print(f"{row['label']:28s} h={int(row['horizon_days']):2d}d  "
              f"umep={row['umep_beta']:+.4f} (t={row['umep_t']:+.2f})  "
              f"vol={row['vol_beta']:+.4f} (t={row['vol_t']:+.2f})  "
              f"R2={row['r_squared']:.3f} DW={row['durbin_watson']:.2f} n={int(row['n'])}")

    print("\n=== H2 placebo: real |t(umep)| vs circular-shift placebo distribution (n=20 draws) ===")
    placebo = h2_placebo(swap_slope, ust_slope, vol_ann, umep)
    for _, row in placebo.iterrows():
        print(f"{row['label']:28s} h={int(row['horizon_days']):2d}d  "
              f"real|t|={row['real_abs_t']:.2f}  placebo median|t|={row['placebo_median_abs_t']:.2f}  "
              f"placebo max|t|={row['placebo_max_abs_t']:.2f}  "
              f"frac(placebo>=real)={row['frac_placebo_ge_real']:.2f}")

    print("\n=== H3: rolling changes-beta vs contemporaneous vol level ===")
    h3 = h3_table(swap_slope, vol_ann, ust_slope)
    for label, tbl in h3.items():
        print(f"\n[{label}] n={len(tbl)}  beta-on-vol slope={tbl.attrs.get('beta_on_vol_slope')}  "
              f"intercept={tbl.attrs.get('beta_on_vol_intercept')}")
        print(tbl.tail())

    return {"h2": h2, "h2_placebo": placebo, "h3": h3,
            "swap_slope": swap_slope, "ust_slope": ust_slope, "vol_ann": vol_ann, "umep": umep}


if __name__ == "__main__":
    main()

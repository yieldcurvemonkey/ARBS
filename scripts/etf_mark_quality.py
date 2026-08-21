r"""Are Citi's intraday bond marks real quotes, or a curve evaluated at each maturity?

This decides whether the delivered layer can answer the question it was warmed
for, and it is the check most likely to be skipped, because a small dispersion
number is exactly what a "no edge here" conclusion wants to see. A matrix-priced
tape would produce that number for free, from an artefact.

Three tests, each of which a synthetic tape fails and a real one passes:

**1. Residual to a smooth curve.** Fit a low-order polynomial in maturity across
the 97 bonds at one instant and look at what is left. A tape produced by
evaluating a curve leaves essentially nothing - fractions of a basis point,
structureless. A tape of real marks leaves the coupon and liquidity effects the
daily study measured at 0.434 bp of cross-sectional richness dispersion, which is
the number to compare against.

**2. Residual PERSISTENCE.** Curve-fit noise is not persistent; a bond's own
cheapness is. The autocorrelation of a bond's residual from one hour to the next,
and from one day to the next, separates a real idiosyncratic level from fitting
error. This is the strongest of the three, because a synthetic tape can be made
to look dispersed and cannot easily be made to look persistent.

**3. Stale-mark fraction.** A carried-forward mark shows a change of exactly
zero. If most bonds are stale across the seam then the seam's measured dispersion
is biased DOWN, and every conclusion drawn from it is flattered in the direction
of "nothing here" - the direction this study's prior has been wrong in before.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes  # noqa: E402

DAILY_RICHNESS_SD_BP = 0.434     # RESULTS.md, FedInvest daily cross-section
FLY_ROUND_TRIP_BP = 0.535


def main() -> int:
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    uni["maturity_date"] = pd.to_datetime(uni["maturity_date"])
    isins = list(uni["isin"].astype(str))
    mat = dict(zip(uni["isin"].astype(str), uni["maturity_date"]))

    q = CitiVeloQuotes(offline=True)
    frame = q.frame([f"RATES.BOND.{i}.YIELD" for i in isins], "HOURLY")
    frame = frame[frame.index >= "2021-01-01"]
    print(f"panel: {frame.shape[0]:,} hourly stamps x {frame.shape[1]} bonds")

    # ---- 3. stale marks first: it conditions how to read 1 and 2 ----------
    idx = pd.Series(frame.index)
    a = frame[(idx.dt.hour == 14).to_numpy()]     # the 15:00 New York mark
    b = frame[(idx.dt.hour == 15).to_numpy()]     # the 16:00 New York mark
    a.index = pd.Series(a.index).dt.normalize()
    b.index = pd.Series(b.index).dt.normalize()
    common = a.index.intersection(b.index)
    d = (b.loc[common] - a.loc[common])
    flat = np.isclose(d.to_numpy(), 0.0, atol=1e-12) & np.isfinite(d.to_numpy())
    finite = np.isfinite(d.to_numpy())
    print(f"\nTEST 3 - stale marks across the 15:00->16:00 seam: "
          f"{flat.sum():,} of {finite.sum():,} bond-days moved EXACTLY zero "
          f"({100 * flat.sum() / max(1, finite.sum()):.2f}%)")

    # ---- 1. residual to a smooth curve -----------------------------------
    ttm_years = {}
    resid_rows = []
    sample = frame.iloc[::7]           # every 7th stamp keeps the fit cheap
    for ts, row in sample.iterrows():
        v = row.dropna()
        if len(v) < 20:
            continue
        x = np.array([(mat[t.split(".")[2]] - ts).days / 365.25 for t in v.index])
        y = v.to_numpy() * 100.0       # bp
        ok = np.isfinite(x) & np.isfinite(y) & (x > 0)
        if ok.sum() < 20:
            continue
        coef = np.polyfit(x[ok], y[ok], 3)
        r = y[ok] - np.polyval(coef, x[ok])
        resid_rows.append(pd.Series(r, index=v.index[ok], name=ts))
    R = pd.DataFrame(resid_rows)
    print(f"\nTEST 1 - residual to a cubic in maturity, {R.shape[0]:,} stamps x "
          f"{R.shape[1]} bonds")
    per_stamp_sd = R.std(axis=1)
    print(f"  cross-sectional residual SD: median {per_stamp_sd.median():.3f} bp, "
          f"IQR {per_stamp_sd.quantile(0.25):.3f}..{per_stamp_sd.quantile(0.75):.3f} bp")
    print(f"  the daily FedInvest study measured {DAILY_RICHNESS_SD_BP:.3f} bp on the "
          f"same kind of cross-section")
    verdict1 = ("CONSISTENT with real marks" if per_stamp_sd.median() > 0.2
                else "SUSPICIOUSLY SMOOTH - consistent with curve-derived marks")
    print(f"  -> {verdict1}")

    # ---- 2. persistence ---------------------------------------------------
    Rs = R.sort_index()
    ac1 = Rs.corrwith(Rs.shift(1), axis=0).median()
    # one trading day is ~24 hourly stamps in this tape, subsampled by 7 -> ~3.4
    ac_day = Rs.corrwith(Rs.shift(4), axis=0).median()
    ac_week = Rs.corrwith(Rs.shift(20), axis=0).median()
    print(f"\nTEST 2 - residual persistence (median across bonds)")
    print(f"  lag 1 stamp  (~7h): {ac1:.3f}")
    print(f"  lag 4 stamps (~1d): {ac_day:.3f}")
    print(f"  lag 20 stamps(~6d): {ac_week:.3f}")
    verdict2 = ("PERSISTENT - a bond-specific level, not fitting noise"
                if ac_day > 0.5 else "NOT persistent - looks like fitting noise")
    print(f"  -> {verdict2}")

    # ---- does the residual MOVE across the seam? --------------------------
    Rh = pd.DataFrame(resid_rows)
    out = pd.DataFrame({
        "metric": ["xsec_residual_sd_bp_median", "residual_ac_1stamp",
                   "residual_ac_1day", "residual_ac_1week",
                   "stale_frac_seam", "daily_study_richness_sd_bp",
                   "fly_round_trip_bp"],
        "value": [float(per_stamp_sd.median()), float(ac1), float(ac_day), float(ac_week),
                  float(flat.sum() / max(1, finite.sum())), DAILY_RICHNESS_SD_BP,
                  FLY_ROUND_TRIP_BP],
    })
    out.to_csv(DATA / "intraday_mark_quality.csv", index=False)
    per_stamp_sd.rename("xsec_resid_sd_bp").to_csv(DATA / "intraday_resid_sd_by_stamp.csv")
    print("\nwrote intraday_mark_quality.csv, intraday_resid_sd_by_stamp.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

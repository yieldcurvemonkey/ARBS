import os; os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")  # noqa: E702
import sys

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-rv")

"""Runner: ING curve-deconstruction screen on the banked Citi Velocity par grids.

Reads notebooks/data/citivelo_rv/par_grid_{CCY}_{INDEX}.parquet (daily par OIS
rates in PERCENT), runs RVUtils.INGCurve DESCRIPTIVELY (no strategy grading),
and writes:

  ing_{ccy}_residuals.parquet : date x kF1Y residual bp + rank_kF1Y columns
                                + pre_rfr_splice / front_extrapolated flags
  ing_{ccy}_frontier.parquet  : per-day slope / intercept / r2 / n of the
                                value-vs-carry regression (2F1Y..15F1Y)

Panel architecture (the spliced pre-RFR history prints nothing below 2Y, so
the 1Y par point does not exist before the RFR launch):

  PRIMARY panel  - forwards 2F1Y..29F1Y, full history.  The bootstrap uses a
                   linear par-space 1Y anchor (s1 = 2*s2 - s3) on days where
                   1Y did not print; forwards at k >= 2 are insensitive to it
                   (tested: < 0.5bp), so these residuals are data.
  MODERN panel   - forwards 1F1Y..29F1Y, only days with a PRINTED 1Y (the
                   RFR era).  Supplies the 1F1Y residual/rank columns, NaN
                   before its own ramp-in.  1F1Y is fit in a different PCA
                   universe than 2..29 - documented, not hidden.
  UNIFORM panel  - anchor forced on EVERY day (no splice seam), print-only,
                   used solely for the construction-dependent 1F1Y* side
                   number in the 2020-01-15 ING worked-example reproduction.

Usage:  python ing_eur_screen.py [--currency EUR] [--repro-date 2020-01-15]
"""

import argparse
import time

import numpy as np
import pandas as pd

from RVUtils.INGCurve import (
    annual_forwards,
    bootstrap_discounts,
    daily_frontier,
    integer_par_grid,
    residual_percentiles,
    reversion_gate,
    rolldown_3m,
    rolling_pc1_residuals,
)

DATA_DIR = r"C:\Users\chris\clee\ARBS-rv\notebooks\data\citivelo_rv"

PAR_FILES = {
    "EUR": "par_grid_EUR_EUROSTR.parquet",
    "USD": "par_grid_USD_SOFR.parquet",
    "GBP": "par_grid_GBP_SONIA.parquet",
    "JPY": "par_grid_JPY_TONAR.parquet",
    "CAD": "par_grid_CAD_CORRA.parquet",
}

# first date the modern RFR itself printed; history before this is Citi's
# vendor-spliced pre-RFR proxy (EUR: pre-ESTR = spliced EONIA-era history).
RFR_START = {
    "EUR": pd.Timestamp("2019-10-01"),
    "USD": pd.Timestamp("2018-04-03"),
    "GBP": pd.Timestamp("2018-04-23"),  # reformed SONIA
    "JPY": None,
    "CAD": None,
}

WINDOW = 756          # 3y of business days: PCA window and percentile window
MIN_WINDOW = 504      # min PCA fit rows (ramp-in)
MIN_OBS = 252         # min residual history for a percentile rank
FRONTIER_KS = tuple(range(2, 16))   # 2F1Y..15F1Y per ING
HORIZONS = (21, 63, 126)
COST_BP = 1.0


def compute_panel(dense: pd.DataFrame, ks_min: int):
    """Bootstrap -> forwards -> walk-forward PC1 residuals -> bands, on ks >= ks_min."""
    dfs = bootstrap_discounts(dense)
    fwd_all = annual_forwards(dfs, include_spot=True)          # k = 0..29
    fwd = fwd_all[[k for k in fwd_all.columns if k >= ks_min]]
    resid, loadings = rolling_pc1_residuals(
        fwd, window=WINDOW, min_window=MIN_WINDOW, return_loadings=True
    )
    pct = residual_percentiles(resid, window=WINDOW, min_obs=MIN_OBS)
    return {"fwd_all": fwd_all, "resid": resid, "pct": pct, "loadings": loadings}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--currency", default="EUR", choices=sorted(PAR_FILES))
    ap.add_argument("--repro-date", default="2020-01-15")
    args = ap.parse_args()
    ccy = args.currency
    rfr_start = RFR_START.get(ccy)
    t0 = time.time()

    path = os.path.join(DATA_DIR, PAR_FILES[ccy])
    par = pd.read_parquet(path)
    print(f"[{ccy}] par grid {par.shape[0]} days x {par.shape[1]} tenors "
          f"({par.index[0].date()} .. {par.index[-1].date()})")

    dense, skipped, front_flag = integer_par_grid(par, min_printed=15)
    n_anchor = int(front_flag.sum())
    print(f"kept {len(dense)} days, skipped {len(skipped)} (<15 printed integer "
          f"tenors in 1Y..30Y, missing 30Y, or no 1Y anchor); "
          f"{n_anchor} days use the extrapolated 1Y anchor (no printed 1Y)")

    # ------------------------------------------------------------- panels
    primary = compute_panel(dense, ks_min=2)                    # full history
    dense_mod, _, _ = integer_par_grid(par, min_printed=15,
                                       anchor_1y="printed_only")
    modern = compute_panel(dense_mod, ks_min=1) if len(dense_mod) else None
    dense_uni, _, _ = integer_par_grid(par, min_printed=15,
                                       anchor_1y="always_extrapolate")
    uniform = compute_panel(dense_uni, ks_min=1)                # print-only

    resid = primary["resid"]
    pct = primary["pct"]
    first_resid = resid.dropna(how="all").index[0]
    shares = np.array([v[2] for v in primary["loadings"].values()])
    print(f"primary panel (2F1Y..29F1Y): residuals start {first_resid.date()}; "
          f"{len(primary['loadings'])} monthly PCA refits; PC1 explained share "
          f"median {np.median(shares):.3f} (min {shares.min():.3f}, "
          f"max {shares.max():.3f})")
    if modern is not None:
        m1 = modern["resid"].dropna(how="all")
        print(f"modern panel (1F1Y..29F1Y, printed-1Y era, {len(dense_mod)} "
              f"days): residuals start "
              f"{m1.index[0].date() if len(m1) else 'never (too short)'}")

    roll = rolldown_3m(primary["fwd_all"])                      # bp/3m, k=1..29
    frontier = daily_frontier(resid, roll, ks=FRONTIER_KS)

    gate = reversion_gate(
        resid, pct["rank"], pct["p50"],
        horizons=HORIZONS, low=0.05, high=0.95, cost_bp=COST_BP,
        revert_frac=0.5, revert_horizon=63,
    )
    if modern is not None:
        gate_1f = reversion_gate(
            modern["resid"][[1]], modern["pct"]["rank"][[1]],
            modern["pct"]["p50"][[1]],
            horizons=HORIZONS, low=0.05, high=0.95, cost_bp=COST_BP,
            revert_frac=0.5, revert_horizon=63,
        )
        gate = pd.concat([gate_1f, gate])

    # ------------------------------------------------------------- output
    out = pd.DataFrame(index=resid.index)
    if modern is not None:
        out["1F1Y"] = modern["resid"][1].reindex(resid.index)
    for k in resid.columns:
        out[f"{k}F1Y"] = resid[k]
    if modern is not None:
        out["rank_1F1Y"] = modern["pct"]["rank"][1].reindex(resid.index)
    for k in resid.columns:
        out[f"rank_{k}F1Y"] = pct["rank"][k]
    out["pre_rfr_splice"] = (
        out.index < rfr_start if rfr_start is not None else False
    )
    out["front_extrapolated"] = front_flag.reindex(out.index).fillna(False)

    lc = ccy.lower()
    resid_path = os.path.join(DATA_DIR, f"ing_{lc}_residuals.parquet")
    frontier_path = os.path.join(DATA_DIR, f"ing_{lc}_frontier.parquet")
    out.to_parquet(resid_path)
    frontier.to_parquet(frontier_path)
    print(f"wrote {resid_path}\nwrote {frontier_path}")
    if rfr_start is not None:
        n_spliced = int(out["pre_rfr_splice"].sum())
        print(f"NOTE: {n_spliced} of {len(out)} days predate the {ccy} RFR "
              f"({rfr_start.date()}) - Citi vendor-spliced proxy history, "
              "flagged in pre_rfr_splice, not silently trusted.")

    # ------------------------------------------------------- frontier summary
    fr_ok = frontier.dropna()
    print("\n=== value-vs-carry frontier (residual bp ~ 3m roll bp, "
          "2F1Y..15F1Y) ===")
    print(f"days with a fit: {len(fr_ok)}; slope median "
          f"{fr_ok['slope'].median():+.2f} "
          f"(IQR {fr_ok['slope'].quantile(0.25):+.2f}.."
          f"{fr_ok['slope'].quantile(0.75):+.2f}); "
          f"R2 median {fr_ok['r2'].median():.2f}")

    # ------------------------------------------------------------ gate-c table
    pd.set_option("display.width", 160)
    print(f"\n=== mean-reversion gate: band breaches (rank <=5% / >=95%) vs "
          f"{COST_BP:.1f}bp round-trip cost ===")
    print("(events are DAYS at/beyond the band - consecutive events overlap, "
          "they are not independent trades)")
    print(gate.to_string(float_format=lambda x: f"{x:8.2f}"))
    if modern is not None:
        print("footnote: the 1F1Y row comes from the MODERN panel (printed-1Y "
              "era only) - short history, small n, different PCA universe.")
    if rfr_start is not None:
        fired_dates = pct["rank"].index[
            ((pct["rank"] <= 0.05) | (pct["rank"] >= 0.95)).any(axis=1)
        ]
        pre_share = float((fired_dates < rfr_start).mean()) if len(fired_dates) else float("nan")
        print(f"pre-splice share of fire-dates (2F1Y..29F1Y): {pre_share:.0%}")
    print("caveat: 21F..29F forwards rest on par-interpolated 21-24Y/26-29Y "
          "quotes - their dislocations are partly interpolation-smoothing "
          "artifacts.")
    print("caveat: pre-splice 2F1Y roll-down uses the anchored f(1) "
          "(~0.25x anchor error, a few bp) - one of 14 frontier points.")

    # ------------------------------------------------- ING worked-example repro
    repro_date = pd.Timestamp(args.repro_date)
    print(f"\n=== ING worked-example reproduction ({repro_date.date()}) ===")
    avail = pct["rank"].index[pct["rank"].index <= repro_date]
    if len(avail) == 0:
        print("repro date precedes the residual history - skipped")
    else:
        d = avail[-1]
        if d != repro_date:
            print(f"(using nearest prior date {d.date()})")
        print("rank = fraction of own trailing 3y residual history strictly "
              "below today (1.00 = cheapest extreme, 0.00 = richest)")

        def _tag(rk: float) -> str:
            if rk >= 0.95:
                return "  <-- CHEAP extreme"
            if rk <= 0.05:
                return "  <-- RICH extreme"
            return ""

        for k in resid.columns:
            rk = pct["rank"].loc[d, k]
            if k in (2, 10) or (not np.isnan(rk) and (rk >= 0.95 or rk <= 0.05)):
                print(f"  {k:>2}F1Y  residual {resid.loc[d, k]:+7.2f} bp   "
                      f"rank {rk:5.2f}{_tag(rk)}")
        print("1F1Y: UNIDENTIFIABLE from this parquet on the ING date - no "
              "sub-2Y tenor printed before the RFR launch, so 1F1Y has no "
              "3y history there.  Construction-dependent side number, uniform "
              "linear-anchor build (no splice seam), print-only:")
        u_rk = uniform["pct"]["rank"]
        u_re = uniform["resid"]
        if d in u_rk.index and not np.isnan(u_rk.loc[d, 1]):
            print(f"  1F1Y*  residual {u_re.loc[d, 1]:+7.2f} bp   "
                  f"rank {u_rk.loc[d, 1]:5.2f}{_tag(u_rk.loc[d, 1])}   "
                  "[construction, not data]")
        else:
            print("  1F1Y*: no rank available at the repro date")
        f_d = frontier.loc[d]
        print(f"frontier on {d.date()}: slope {f_d['slope']:+.2f}, intercept "
              f"{f_d['intercept']:+.2f}, R2 {f_d['r2']:.2f} "
              "(ING 2020-01-15: slope -1.27, R2 0.93 raw) - fully identified, "
              "ks 2..15")
        if rfr_start is not None and d < rfr_start + pd.Timedelta(days=3 * 365):
            print(f"NOTE: the trailing 3y window at {d.date()} is mostly "
                  f"pre-{ccy}-RFR vendor-spliced history.")

    print(f"\ndone in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

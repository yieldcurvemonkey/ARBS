r"""Task 5: the three questions that decide the verdict, each with one number.

A seam can fail to be exploitable in three different ways and they mean different
things, so this script computes one number for each rather than one number overall.

**Is the move there?**  The size of the 15:00->16:00 move, level and total.

**Is it dispersed?**  Only the part of the move that survives removing the day's
level and curve shape is available to a butterfly. Two hazards are handled here
rather than assumed away:

* *Under-fitting inflates it.* A cross-sectional basis too poor to describe the
  curve leaves genuine curve shape in the "idiosyncratic" bucket. The
  idiosyncratic dispersion is therefore recomputed over a grid of bases -- degree
  1 to 4 in time to maturity, with and without a coupon regressor -- and the
  number carried into the verdict is the LARGEST, so it is an upper bound on what
  a level-neutral structure can reach.
* *Mark noise inflates it too.* An hourly mark carries quoting error, and the
  difference of two marks carries twice its variance. The size of that error is
  measured, not assumed: an adjacent pair of hourly moves that SHARE a mark must
  show a negative correlation of exactly ``-var(noise)/var(move)`` even if the
  true moves are independent, while a disjoint pair of same-day moves shows only
  the genuine reversal. The gap between the two placebos identifies the noise
  share, and the noise-corrected idiosyncratic dispersion follows.

**Is it predictable?**  The largest Fama-MacBeth coefficient across every holdings
specification tried, in bp per cross-sectional standard deviation, against cost.

Also settled here: how often the reconstitution itself lands on a day when the
cash market shuts at 14:00 and the 15:00->16:00 seam does not exist at all.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.etf_seam_common import (  # noqa: E402
    DATA, FLY_ROUND_TRIP_BP, MIN_BONDS, load_panel,
)

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)


def idio_sd_for_basis(p: pd.DataFrame, col: str, deg: int, use_cpn: bool) -> dict:
    per_date, pooled = [], []
    for d, g in p.groupby("date", sort=True):
        g = g.dropna(subset=[col, "ttm", "cpn"])
        if len(g) < MIN_BONDS:
            continue
        raw = g["ttm"].to_numpy(float)
        x = (raw - raw.mean()) / max(1e-9, raw.std())
        cols = [np.ones_like(x)] + [x ** k for k in range(1, deg + 1)]
        if use_cpn:
            c = g["cpn"].to_numpy(float)
            cols.append((c - c.mean()) / max(1e-9, c.std()))
        A = np.column_stack(cols)
        if len(g) <= A.shape[1] + 2:
            continue
        y = g[col].to_numpy(float)
        b, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y - A @ b
        per_date.append(float(np.std(r)))
        pooled.append(r)
    pooled = np.concatenate(pooled) if pooled else np.array([np.nan])
    return {"deg": deg, "coupon": use_cpn, "dates": len(per_date),
            "sd_idio_median_bp": float(np.median(per_date)),
            "sd_idio_pooled_bp": float(np.std(pooled)),
            "median_vs_cost": float(np.median(per_date)) / FLY_ROUND_TRIP_BP,
            "pooled_vs_cost": float(np.std(pooled)) / FLY_ROUND_TRIP_BP}


def main() -> int:
    p = load_panel(drop_early_close=True)
    p["seam"] = (p["y16"] - p["y15"]) * 100.0

    rows = [idio_sd_for_basis(p, "seam", deg, cpn)
            for deg in (1, 2, 3, 4) for cpn in (False, True)]
    basis = pd.DataFrame(rows)
    print("=== IDIOSYNCRATIC SEAM DISPERSION vs THE CROSS-SECTIONAL BASIS ===")
    print(basis.round(5).to_string(index=False), flush=True)
    basis.to_csv(DATA / "seam_basis_robustness.csv", index=False)
    ub_med = float(basis["sd_idio_median_bp"].max())
    ub_pool = float(basis["sd_idio_pooled_bp"].max())
    print(f"\nUPPER BOUND across {len(basis)} bases: median-per-date "
          f"{ub_med:.4f} bp = {ub_med / FLY_ROUND_TRIP_BP:.4f}x cost; pooled "
          f"{ub_pool:.4f} bp = {ub_pool / FLY_ROUND_TRIP_BP:.4f}x cost", flush=True)

    # ------------------------------------------------- how much of it is mark noise
    rev = pd.read_csv(DATA / "seam_reversal.csv")
    r = rev[rev["scope"] == "idio"].set_index("pair")["beta"]
    b_shared = float(r["IDIO placebo 13->14 then 14->15 (shares y14)"])
    b_disjoint = float(r["IDIO placebo 13->14 then 15->16 (disjoint)"])
    # For d1 = D1 + e_b - e_a and d2 = D2 + e_c - e_b with independent mark noise,
    # beta(shared) - beta(disjoint) = -var(e) / var(d), and var(d) itself contains
    # 2 var(e). So the noise share of the measured move variance is:
    noise_share = 2.0 * (b_disjoint - b_shared)
    sd_meas = float(p.dropna(subset=["seam"])["seam"].std())
    # Use the pooled idiosyncratic sd from the reported decomposition.
    dec = pd.read_csv(DATA / "seam_decomposition.csv").set_index("window")
    idio_med = float(dec.loc["seam_1500_1600", "sd_idio_bp_median"])
    idio_true_med = idio_med * float(np.sqrt(max(0.0, 1.0 - noise_share)))
    ub_true = ub_med * float(np.sqrt(max(0.0, 1.0 - noise_share)))
    print(f"\n=== HOW MUCH OF THE IDIOSYNCRATIC MOVE IS MARK NOISE ===")
    print(f"adjacent placebo beta (shares a mark)  {b_shared:+.4f}")
    print(f"disjoint placebo beta (shares nothing) {b_disjoint:+.4f}")
    print(f"implied noise share of the idio hourly move variance: "
          f"{noise_share:.3f}")
    print(f"idio seam sd (deg-3 basis)  measured {idio_med:.4f} bp  ->  "
          f"noise-corrected {idio_true_med:.4f} bp = "
          f"{idio_true_med / FLY_ROUND_TRIP_BP:.4f}x cost")
    print(f"idio seam sd (worst basis)  measured {ub_med:.4f} bp  ->  "
          f"noise-corrected {ub_true:.4f} bp = "
          f"{ub_true / FLY_ROUND_TRIP_BP:.4f}x cost", flush=True)

    # -------------------------------- reconstitutions that have no seam at all
    ec = pd.read_csv(DATA / "seam_early_close_days.csv", index_col=0, parse_dates=True)
    all_dates = pd.DatetimeIndex(ec.index)
    me_all = pd.Series(all_dates, index=all_dates).groupby(
        all_dates.to_period("M")).max()
    me_all = me_all[me_all.index < all_dates.max().to_period("M")]
    me_dates = pd.DatetimeIndex(me_all.values)
    lost = ec.loc[ec.index.isin(me_dates) & ec["is_early_close"]]
    print(f"\n=== RECONSTITUTIONS WITH NO 15:00->16:00 WINDOW ===")
    print(f"{len(lost)} of {len(me_dates)} month ends are 14:00-close days "
          f"({100 * len(lost) / len(me_dates):.1f}%): "
          f"{[str(d.date()) for d in lost.index]}", flush=True)
    lost.to_csv(DATA / "seam_monthends_no_seam.csv")

    # ------------------------------------------------------------- the summary
    dist = pd.read_csv(DATA / "seam_move_distribution.csv").set_index("window")
    fm = pd.read_csv(DATA / "seam_holdings_fama_macbeth.csv")
    fm_seam = fm[fm["y"] == "15:00->16:00 idiosyncratic"]
    fm_best = fm_seam.loc[fm_seam["bp_per_1sd"].abs().idxmax()]
    fm_bestt = fm_seam.loc[fm_seam["nw_t"].abs().idxmax()]
    ev = pd.read_csv(DATA / "seam_monthend_event_study.csv")
    ev0 = ev[(ev["k"] == 0) & (ev["measure"] == "15:00->16:00 idio")]

    # Every analysis cell evaluated anywhere in the seam study, so the reader can
    # deflate. 73 of them are the by-year / by-day-type reversal grid in
    # ``etf_seam_reversal_by_group.py``, which writes no cell file of its own.
    n_cells = sum(len(pd.read_csv(DATA / f))
                  for f in ("seam_cells_reversal.csv", "seam_cells_holdings.csv",
                            "seam_cells_monthend.csv")) + len(basis) + 73

    S = [
        ("Q1 is the move there", "seam mean |move| per bond-date",
         dist.loc["seam_1500_1600", "mean_abs_bp"], "bp"),
        ("Q1 is the move there", "seam cross-sectional LEVEL move sd",
         float(dec.loc["seam_1500_1600", "level_sd_bp"]), "bp"),
        ("Q1 is the move there", "seam mean |move| / 13:00-14:00 control",
         dist.loc["seam_1500_1600", "mean_abs_bp"]
         / dist.loc["ctl_1300_1400", "mean_abs_bp"], "ratio"),
        ("Q1 is the move there", "seam mean |move| / 16:00-17:00 control",
         dist.loc["seam_1500_1600", "mean_abs_bp"]
         / dist.loc["ctl_1600_1700", "mean_abs_bp"], "ratio"),
        ("Q1 reversal", "LEVEL reversed by next 10:00 (shared endpoint)",
         -100 * float(rev.set_index("pair").loc[
             "LEVEL seam -> next 10:00 (shares y16)", "beta"]), "%"),
        ("Q1 reversal", "LEVEL reversed by next 10:00 (clean, from 17:00)",
         -100 * float(rev.set_index("pair").loc[
             "LEVEL seam -> next 10:00 from 17:00 (clean)", "beta"]), "%"),
        ("Q1 reversal", "IDIO reversed by next 10:00 (shared endpoint)",
         -100 * float(r["IDIO seam -> next 10:00 (shares y16)"]), "%"),
        ("Q1 reversal", "IDIO reversed by next 10:00 (clean, from 17:00)",
         -100 * float(r["IDIO seam -> next 10:00 from 17:00 (clean)"]), "%"),
        ("Q1 reversal", "IDIO adjacent placebo, no ETF story (shares a mark)",
         -100 * b_shared, "%"),
        ("Q2 is it dispersed", "share of seam mean-square that is LEVEL",
         float(dec.loc["seam_1500_1600", "var_share_level"]), "fraction"),
        ("Q2 is it dispersed", "share that is slope + curvature",
         float(dec.loc["seam_1500_1600", "var_share_slope_curv"]), "fraction"),
        ("Q2 is it dispersed", "share that is IDIOSYNCRATIC",
         float(dec.loc["seam_1500_1600", "var_share_idio"]), "fraction"),
        ("Q2 is it dispersed", "idio sd, deg-3 basis, median per date",
         idio_med, "bp"),
        ("Q2 is it dispersed", "idio sd, WORST of 8 bases (upper bound)",
         ub_med, "bp"),
        ("Q2 is it dispersed", "idio sd, worst basis, noise-corrected",
         ub_true, "bp"),
        ("Q2 is it dispersed", "DECIDING NUMBER idio sd / 0.535bp round trip",
         ub_med / FLY_ROUND_TRIP_BP, "x cost"),
        ("Q3 is it predictable", "largest |FM coef| over holdings specs",
         abs(float(fm_best["bp_per_1sd"])), "bp per 1sd"),
        ("Q3 is it predictable", "  its spec",
         f"{fm_best['signal']} / {fm_best['spec']} / lag {int(fm_best['exec_lag'])}",
         ""),
        ("Q3 is it predictable", "largest |FM coef| / round trip",
         abs(float(fm_best["bp_per_1sd"])) / FLY_ROUND_TRIP_BP, "x cost"),
        ("Q3 is it predictable", "largest |NW t| over holdings specs",
         abs(float(fm_bestt["nw_t"])), "t"),
        ("Q3 is it predictable", "  its spec",
         f"{fm_bestt['signal']} / {fm_bestt['spec']} / lag "
         f"{int(fm_bestt['exec_lag'])}", ""),
        ("Q4 month end", "deletion effect at k=0 vs matched control",
         float(ev0[ev0["kind"] == "deletion"]["mean_diff_bp"].iloc[0]), "bp"),
        ("Q4 month end", "  its t / n",
         f"{float(ev0[ev0['kind'] == 'deletion']['t'].iloc[0]):.2f} / "
         f"{int(ev0[ev0['kind'] == 'deletion']['n'].iloc[0])}", ""),
        ("Q4 month end", "addition effect at k=0 vs matched control",
         float(ev0[ev0["kind"] == "addition"]["mean_diff_bp"].iloc[0]), "bp"),
        ("Q4 month end", "  its t / n",
         f"{float(ev0[ev0['kind'] == 'addition']['t'].iloc[0]):.2f} / "
         f"{int(ev0[ev0['kind'] == 'addition']['n'].iloc[0])}", ""),
        ("Q4 month end", "smallest effect an event study here could see (|t|=2)",
         float(ev0["mde_at_t2_bp"].max()), "bp"),
        ("Q4 month end", "month-end idio dispersion / ordinary",
         float(pd.read_csv(DATA / "seam_idio_by_daytype.csv", index_col=0)
               .loc["month_end", "sd_idio_bp_median"])
         / float(pd.read_csv(DATA / "seam_idio_by_daytype.csv", index_col=0)
                 .loc["ordinary", "sd_idio_bp_median"]), "ratio"),
        ("Q4 month end", "reconstitutions on a 14:00-close day (no seam exists)",
         f"{len(lost)} of {len(me_dates)}", ""),
        ("accounting", "analysis cells evaluated", n_cells, "count"),
        ("accounting", "dates in the panel", int(p["date"].nunique()), "count"),
        ("accounting", "bond-dates in the panel", int(len(p)), "count"),
        ("accounting", "dates excluded as 14:00-close / holiday", 89, "count"),
    ]
    summ = pd.DataFrame(S, columns=["section", "metric", "value", "unit"])
    print("\n=== SEAM SUMMARY ===")
    print(summ.to_string(index=False), flush=True)
    summ.to_csv(DATA / "seam_SUMMARY.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

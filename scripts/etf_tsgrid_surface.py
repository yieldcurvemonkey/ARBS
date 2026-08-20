r"""The time-of-day SURFACE, and H1-H4 as named hypotheses rather than as grid cells.

The grid produced 23,040 gross cells. A top-10 list off that would be a report about the
search. What follows is instead:

* the surface over ``(entry_hour, exit_hour)`` and over ``mark_hour``, for the real
  signals and for the label-permuted placebos side by side, so "is there structure in the
  time-of-day axis" is answered by the gap between two surfaces rather than by the shape
  of one;
* H1, whether the 15:00 cash mark and the 16:00 NAV mark differ systematically and
  whether the difference is forecastable from the ladder;
* H2, whether reading the signal at one hour beats another with everything else fixed;
* H3, the last business day, where the reconstitution happens;
* H4, staleness -- because a "signal" that lives only where the mark does not move is a
  property of the mark.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from scipy import stats

import etf_tsgrid_lib as L

DATA = L.DATA
H = L.CLOCK_HOURS
HOLDINGS = L.HOLDINGS_SIGNALS
CAL = L.CALENDAR_SIGNALS


def spearman_ic(Z: np.ndarray, R: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Per-date cross-sectional Spearman of ``Z`` against ``R`` on the common mask."""
    D = Z.shape[0]
    out = np.full(D, np.nan)
    for d in range(D):
        ok = mask[d] & np.isfinite(Z[d]) & np.isfinite(R[d])
        if ok.sum() < 12:
            continue
        z, r = Z[d][ok], R[d][ok]
        if np.unique(z).size < 6 or np.unique(r).size < 6:
            continue
        out[d] = stats.spearmanr(z, r).statistic
    return out


def main():
    t0 = time.time()
    g = pd.read_csv(DATA / "tsgrid_grid.csv")
    real = g[(g.kind == "real") & (g.signal.isin(HOLDINGS + CAL))]
    ctrl = g[g.signal == "resid"]
    plac = g[g.kind == "placebo"]

    # ================================================================= SURFACE 1
    # entry x exit, intraday (hold=0). Gross of the best REAL holdings/calendar cell in
    # that (entry, exit) box, of the mean over all such cells, and of the PLACEBO band.
    rows = []
    for entry in H:
        for ex in H:
            if ex <= entry:
                continue
            rr = real[(real.entry == entry) & (real.exit == ex) & (real.hold == 0)]
            pp = plac[(plac.entry == entry) & (plac.exit == ex) & (plac.hold == 0)]
            cc = ctrl[(ctrl.entry == entry) & (ctrl.exit == ex) & (ctrl.hold == 0)]
            if rr.empty:
                continue
            rows.append({
                "entry": entry, "exit": ex, "n_cells": len(rr),
                "pf_bp": float(rr["pf_bp"].mean()),
                "cost_measured_bp": float(rr["cost_measured"].mean()),
                "gross_mean_bp": float(rr["gross_bp"].mean()),
                "gross_max_bp": float(rr["gross_bp"].max()),
                "gross_max_t": float(rr.loc[rr["gross_bp"].idxmax(), "t_nw"]),
                "abs_t_max": float(rr["t_nw"].abs().max()),
                "placebo_gross_max_bp": float(pp["gross_bp"].max()) if len(pp) else np.nan,
                "placebo_abs_t_max": float(pp["t_nw"].abs().max()) if len(pp) else np.nan,
                "resid_ctrl_gross_bp": float(cc["gross_bp"].max()) if len(cc) else np.nan,
                "best_over_cost": float(rr["gross_bp"].max() / rr["cost_measured"].mean()),
            })
    s1 = pd.DataFrame(rows)
    s1.to_csv(DATA / "tsgrid_surface_entry_exit.csv", index=False)

    # ================================================================= SURFACE 2
    # mark_hour, everything else fixed at the structural pair: enter 16:00 (the NAV
    # strike), hold one business day, exit 16:00. H2 lives here.
    rows = []
    for sig in HOLDINGS + CAL + ["resid"]:
        for orth in (False, True):
            for mark in H:
                sub = g[(g.signal == sig) & (g.orth == orth) & (g.mark == mark)
                        & (g.entry == 16) & (g.hold == 1) & (g.exit == 16) & (g.lag == 1)]
                if sub.empty:
                    continue
                r = sub.iloc[0]
                rows.append({"signal": sig, "orth": orth, "mark_hour": mark,
                             "gross_bp": r.gross_bp, "t_nw": r.t_nw,
                             "cost_measured": r.cost_measured, "n_dates": r.n_dates})
    for k in range(3):
        for orth in (False, True):
            for mark in H:
                sub = g[(g.signal == f"PLACEBO{k}") & (g.orth == orth) & (g.mark == mark)
                        & (g.entry == 16) & (g.hold == 1) & (g.exit == 16) & (g.lag == 1)]
                if sub.empty:
                    continue
                r = sub.iloc[0]
                rows.append({"signal": f"PLACEBO{k}", "orth": orth, "mark_hour": mark,
                             "gross_bp": r.gross_bp, "t_nw": r.t_nw,
                             "cost_measured": r.cost_measured, "n_dates": r.n_dates})
    s2 = pd.DataFrame(rows)
    s2.to_csv(DATA / "tsgrid_surface_mark_hour.csv", index=False)

    # mark-hour SPREAD per signal: the range across the nine hours, against the placebo's
    rng_rows = []
    for (sig, orth), sub in s2.groupby(["signal", "orth"]):
        rng_rows.append({"signal": sig, "orth": orth,
                         "gross_min_bp": sub.gross_bp.min(),
                         "gross_max_bp": sub.gross_bp.max(),
                         "gross_range_bp": sub.gross_bp.max() - sub.gross_bp.min(),
                         "best_mark_hour": int(sub.loc[sub.gross_bp.idxmax(), "mark_hour"]),
                         "abs_t_max": sub.t_nw.abs().max()})
    s2r = pd.DataFrame(rng_rows).sort_values("gross_range_bp", ascending=False)
    s2r.to_csv(DATA / "tsgrid_mark_hour_range.csv", index=False)

    # ================================================================= SURFACE 3
    # hold x exit for the structural entry hours, so the intraday family and the
    # multi-day family are on one page.
    rows = []
    for entry in (10, 15, 16):
        for hold in (0, 1, 5, 21):
            for ex in H:
                rr = real[(real.entry == entry) & (real.hold == hold) & (real.exit == ex)]
                pp = plac[(plac.entry == entry) & (plac.hold == hold) & (plac.exit == ex)]
                if rr.empty:
                    continue
                rows.append({"entry": entry, "hold": hold, "exit": ex, "n_cells": len(rr),
                             "pf_bp": rr.pf_bp.mean(),
                             "gross_max_bp": rr.gross_bp.max(),
                             "placebo_gross_max_bp": pp.gross_bp.max() if len(pp) else np.nan,
                             "cost_measured_bp": rr.cost_measured.mean(),
                             "best_over_cost": rr.gross_bp.max() / rr.cost_measured.mean()})
    pd.DataFrame(rows).to_csv(DATA / "tsgrid_surface_hold_exit.csv", index=False)

    # ================================================================= COST SWEEP
    rows = []
    for anchor in ("measured", "flat", "sr1170"):
        col = f"cost_{anchor}"
        for mult in (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0):
            net_r = real["gross_bp"] - mult * real[col]
            net_p = plac["gross_bp"] - mult * plac[col]
            net_c = ctrl["gross_bp"] - mult * ctrl[col]
            rows.append({
                "anchor": anchor, "mult": mult,
                "median_cost_bp": float(real[col].median() * mult),
                "real_cells": len(real), "real_net_pos": int((net_r > 0).sum()),
                "real_net_pos_frac": float((net_r > 0).mean()),
                "real_best_net_bp": float(net_r.max()),
                "placebo_net_pos_frac": float((net_p > 0).mean()),
                "placebo_best_net_bp": float(net_p.max()),
                "control_best_net_bp": float(net_c.max()),
            })
    pd.DataFrame(rows).to_csv(DATA / "tsgrid_cost_sweep.csv", index=False)

    # ================================================================= break-even
    be = real.copy()
    be["breakeven_mult_measured"] = be["gross_bp"] / be["cost_measured"]
    top = be.nlargest(40, "breakeven_mult_measured")[
        ["signal", "orth", "lag", "mark", "entry", "hold", "exit", "n_dates",
         "gross_bp", "t_nw", "pf_bp", "cost_measured", "breakeven_mult_measured"]]
    top.to_csv(DATA / "tsgrid_top_cells.csv", index=False)

    print(f"[surface] wrote 6 files in {time.time()-t0:.0f}s", flush=True)
    print("\n--- SURFACE: entry x exit, intraday (hold=0) ---")
    print(s1.pivot(index="entry", columns="exit", values="gross_max_bp").round(4).to_string())
    print("\n--- same box, PLACEBO max ---")
    print(s1.pivot(index="entry", columns="exit", values="placebo_gross_max_bp").round(4).to_string())
    print("\n--- same box, perfect-foresight ceiling ---")
    print(s1.pivot(index="entry", columns="exit", values="pf_bp").round(3).to_string())
    print("\n--- mark-hour range per signal (entry 16, hold 1bd, exit 16) ---")
    print(s2r.round(4).to_string(index=False))
    print("\n--- top 15 cells by break-even multiple of the measured cost ---")
    print(top.head(15).round(4).to_string(index=False))


if __name__ == "__main__":
    main()

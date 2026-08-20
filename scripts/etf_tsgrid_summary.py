r"""The accounting: every configuration counted, the null measured rather than assumed,
and one number that decides the verdict.

Two deflation references are reported side by side.

* **The analytic one**: with ``K`` roughly independent trials the largest |t| you expect
  from nothing is about ``sqrt(2 ln K)``. It is an upper bound on the honest hurdle because
  the grid's cells are anything but independent.
* **The measured one**: the three label-permuted placebo families ran the identical grid.
  Their largest |t| and largest gross are the null this search actually faces, and they
  need no independence assumption at all.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import etf_tsgrid_lib as L

DATA = L.DATA
LAG_INVARIANT = {"resid", "deletion", "addition"}   # read no holdings file


def main():
    g = pd.read_csv(DATA / "tsgrid_grid.csv")
    real = g[(g.kind == "real") & (~g.signal.isin(["resid"]))]
    hold = g[g.signal.isin(L.HOLDINGS_SIGNALS)]
    cal = g[g.signal.isin(L.CALENDAR_SIGNALS)]
    ctrl = g[g.signal == "resid"]
    plac = g[g.kind == "placebo"]

    COST = {"measured": 0.790, "flat": 0.600, "sr1170": 19.80}
    rows = []

    def add(section, metric, value, unit="", source=""):
        rows.append({"section": section, "metric": metric, "value": value,
                     "unit": unit, "source": source})

    # ------------------------------------------------------------------ accounting
    n_dup = len(g[g.signal.isin(LAG_INVARIANT) & (g.lag == 2)])
    add("accounting", "gross cells evaluated", len(g), "count", "tsgrid_grid.csv")
    add("accounting", "of which label-permuted placebo", len(plac), "count", "")
    add("accounting", "of which real signal", len(g) - len(plac), "count", "")
    add("accounting", "duplicate cells (lag axis inert for calendar/control signals)",
        n_dup, "count", "")
    add("accounting", "distinct gross cells after removing inert-lag duplicates",
        len(g) - n_dup, "count", "")
    add("accounting", "cost variants applied (3 anchors x 7 multipliers)", 21, "count", "")
    add("accounting", "TOTAL configurations", len(g) * 21, "count", "")
    add("accounting", "grid axes",
        "mark_hour(9) x entry_hour(<=9) x hold(4) x exit_hour x signal(13) "
        "x orth(2) x exec_lag(2) x cost_anchor(3) x cost_mult(7)", "", "")

    # ------------------------------------------------------------------ the null
    an = np.sqrt(2.0 * np.log(len(g)))
    add("null", "analytic sqrt(2 ln K) hurdle on |t| at K = all cells",
        round(float(an), 2), "|t|", "")
    add("null", "MEASURED placebo max |HAC t| over its own 5,760 cells",
        round(float(plac.t_nw.abs().max()), 2), "|t|", "tsgrid_grid.csv")
    add("null", "MEASURED placebo max gross", round(float(plac.gross_bp.max()), 4),
        "bp/butterfly", "")
    add("null", "MEASURED placebo 99th pct |t|",
        round(float(plac.t_nw.abs().quantile(0.99)), 2), "|t|", "")

    # ------------------------------------------------------------------ the result
    for name, sub in (("holdings signals", hold), ("calendar nulls", cal),
                      ("richness CONTROL", ctrl), ("all real", real)):
        add("result", f"{name}: max gross", round(float(sub.gross_bp.max()), 4),
            "bp/butterfly", "")
        add("result", f"{name}: max |HAC t|", round(float(sub.t_nw.abs().max()), 2),
            "|t|", "")
        be = (sub.gross_bp / sub.cost_measured).max()
        add("result", f"{name}: best break-even multiple of the measured cost",
            round(float(be), 4), "x", "")
    add("result", "cells with net > 0 at measured cost x1", int((real.gross_bp > real.cost_measured).sum()),
        f"of {len(real)}", "")
    add("result", "cells with net > 0 at measured cost x0.25",
        int((real.gross_bp > 0.25 * real.cost_measured).sum()), f"of {len(real)}", "")
    add("result", "cells with net > 0 at the flat 0.30bp/leg anchor x1",
        int((real.gross_bp > real.cost_flat).sum()), f"of {len(real)}", "")
    add("result", "cells with net > 0 at SR1170 x1",
        int((real.gross_bp > real.cost_sr1170).sum()), f"of {len(real)}", "")

    # THE deciding number
    best = real.loc[real.gross_bp.idxmax()]
    add("VERDICT", "best real cell",
        f"{best.signal} orth={best.orth} lag={int(best.lag)} mark={int(best.mark)} "
        f"entry={int(best.entry)} hold={int(best.hold)} exit={int(best.exit)}", "", "")
    add("VERDICT", "best real cell gross", round(float(best.gross_bp), 4),
        "bp/butterfly", "")
    add("VERDICT", "best real cell HAC t", round(float(best.t_nw), 2), "", "")
    add("VERDICT", "best real cell cost (measured)", round(float(best.cost_measured), 3),
        "bp", "")
    add("VERDICT", "BEST GROSS / COST over the whole grid",
        round(float((real.gross_bp / real.cost_measured).max()), 4), "x", "")

    # ------------------------------------------------------------------ time-of-day
    s1 = pd.read_csv(DATA / "tsgrid_surface_entry_exit.csv")
    add("time-of-day", "intraday (hold=0) best real gross over all 36 entry/exit boxes",
        round(float(s1.gross_max_bp.max()), 4), "bp", "tsgrid_surface_entry_exit.csv")
    add("time-of-day", "same boxes, best PLACEBO gross",
        round(float(s1.placebo_gross_max_bp.max()), 4), "bp", "")
    add("time-of-day", "entry/exit boxes where the real max beats every placebo max",
        int((s1.gross_max_bp > s1.placebo_gross_max_bp.max()).sum()), f"of {len(s1)}", "")
    add("time-of-day", "perfect-foresight pond, 15:00->16:00 seam",
        round(float(s1[(s1.entry == 15) & (s1.exit == 16)].pf_bp.iloc[0]), 4), "bp", "")
    add("time-of-day", "perfect-foresight pond, widest intraday window 09:00->16:00",
        round(float(s1[(s1.entry == 9) & (s1.exit == 16)].pf_bp.iloc[0]), 4), "bp", "")
    s2r = pd.read_csv(DATA / "tsgrid_mark_hour_range.csv")
    rr = s2r[~s2r.signal.str.startswith("PLACEBO") & (s2r.signal != "resid")]
    pr = s2r[s2r.signal.str.startswith("PLACEBO")]
    add("time-of-day", "H2 mark-hour range, widest real holdings/calendar family",
        round(float(rr.gross_range_bp.max()), 4), "bp", "tsgrid_mark_hour_range.csv")
    add("time-of-day", "H2 mark-hour range, widest placebo family",
        round(float(pr.gross_range_bp.max()), 4), "bp", "")
    add("time-of-day", "H2 mark-hour range of the richness CONTROL",
        round(float(s2r[s2r.signal == 'resid'].gross_range_bp.iloc[0]), 4), "bp", "")

    # ------------------------------------------------------------------ costs
    for a, v in COST.items():
        add("cost", f"anchor {a}: median butterfly round trip", v, "bp",
            "tsgrid_cost_by_year.csv")
    add("cost", "daily study's TLT-universe median, for comparison", 0.535, "bp",
        "RESULTS.md")

    out = pd.DataFrame(rows)
    out.to_csv(DATA / "tsgrid_SUMMARY.csv", index=False)
    print(out.to_string(index=False))

    # -------------------------------------------------- best HOLDINGS cells, annotated
    STRUCTURAL = {15, 16}
    h = hold.copy()
    h["be_mult"] = h.gross_bp / h.cost_measured
    top = h.nlargest(25, "be_mult")
    top["structural_timestamp"] = [
        ("YES" if (r.entry in STRUCTURAL and r.exit in STRUCTURAL) else
         ("PARTIAL" if (r.entry in STRUCTURAL or r.exit in STRUCTURAL) else "NO"))
        for r in top.itertuples()]
    top.to_csv(DATA / "tsgrid_top_holdings_cells.csv", index=False)
    print("\n--- best 15 HOLDINGS-BASED cells, with the placebo band on the same page ---")
    print(top.head(15)[["signal", "orth", "lag", "mark", "entry", "hold", "exit",
                        "gross_bp", "t_nw", "cost_measured", "be_mult",
                        "structural_timestamp"]].round(4).to_string(index=False))
    print(f"\nplacebo band on the identical grid: max gross {plac.gross_bp.max():.4f} bp, "
          f"max |HAC t| {plac.t_nw.abs().max():.2f}")


if __name__ == "__main__":
    main()

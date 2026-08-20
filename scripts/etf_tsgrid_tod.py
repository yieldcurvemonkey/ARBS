r"""The one table the question "is there structure in the time-of-day axis" is decided on.

The axis carries TWO different objects and conflating them is how an intraday study talks
itself into a trade:

* **the pond** -- how much a butterfly moves in that hour, i.e. how much there is to win.
  This is strongly structured by time of day, and it is structured in every market that has
  ever been measured. It says nothing about whether anyone can capture it.
* **the signal** -- how much of that pond the ladder can call in advance. This is what the
  grid searched, and it is reported next to the label-permuted placebo's own best, because
  a surface that does not leave its placebo is a surface with no signal in it.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import etf_tsgrid_lib as L

DATA = L.DATA
H = L.CLOCK_HOURS
COST_MED = 0.790


def main():
    m = L.load_matrices()
    legs = L.build_legs(m, step=1)
    FLY = {h: L.fly_level(m, legs, h) for h in H}
    g = pd.read_csv(DATA / "tsgrid_grid.csv")
    prof = pd.read_parquet(DATA / "tsgrid_minute_profile_raw.parquet")
    prof = prof[~prof.early_close]

    rows = []
    for i, hh in enumerate(H[1:], start=1):
        prev = H[i - 1]
        R = -(FLY[hh] - FLY[prev]) * 100.0
        el = legs.valid & np.isfinite(R)
        pf = L.perfect_foresight_per_date(R, el, n=3)
        lo, hi = prev * 60, hh * 60
        pm = prof[(prof.minute > lo) & (prof.minute <= hi)]
        real = g[(g.kind == "real") & (g.signal != "resid")
                 & (g.entry == prev) & (g.exit == hh) & (g.hold == 0)]
        plac = g[(g.kind == "placebo") & (g.entry == prev) & (g.exit == hh) & (g.hold == 0)]
        ctrl = g[(g.signal == "resid") & (g.entry == prev) & (g.exit == hh) & (g.hold == 0)]
        rows.append({
            "hour_window": f"{prev:02d}:00->{hh:02d}:00",
            "label": ("THE SEAM (cash mark -> NAV strike)" if (prev, hh) == (15, 16)
                      else ("post-NAV control" if prev >= 16 else
                            ("pre-cash-close control" if prev == 14 else "session"))),
            "bond_dates": int(el.sum()),
            "mean_abs_fly_move_bp": float(np.nanmean(np.abs(np.where(el, R, np.nan)))),
            "xsec_sd_bp": float(np.nanmedian(np.nanstd(np.where(el, R, np.nan), axis=1))),
            "pond_pf_bp": float(np.nanmean(pf)),
            "pond_over_cost": float(np.nanmean(pf) / COST_MED),
            "stale_frac": float(np.nanmean(m.STALE[hh][el])),
            "fresh_prints_per_min": float(pm.n_fresh_prints.mean()) if len(pm) else np.nan,
            "best_real_gross_bp": float(real.gross_bp.max()) if len(real) else np.nan,
            "best_placebo_gross_bp": float(plac.gross_bp.max()) if len(plac) else np.nan,
            "best_control_gross_bp": float(ctrl.gross_bp.max()) if len(ctrl) else np.nan,
            "real_beats_placebo": bool(len(real) and len(plac)
                                       and real.gross_bp.max() > plac.gross_bp.max()),
            "IC_needed_to_breakeven": float(COST_MED / np.nanmean(pf)),
        })
    tod = pd.DataFrame(rows)
    tod.to_csv(DATA / "tsgrid_time_of_day.csv", index=False)
    pd.set_option("display.width", 250)
    print(tod.round(4).to_string(index=False))

    print()
    print("pond spread across the session: "
          f"min {tod.pond_pf_bp.min():.4f} bp at {tod.loc[tod.pond_pf_bp.idxmin(),'hour_window']}, "
          f"max {tod.pond_pf_bp.max():.4f} bp at {tod.loc[tod.pond_pf_bp.idxmax(),'hour_window']}, "
          f"ratio {tod.pond_pf_bp.max()/tod.pond_pf_bp.min():.2f}x")
    print(f"corr(pond, staleness) = {np.corrcoef(tod.pond_pf_bp, tod.stale_frac)[0,1]:+.3f}")
    sub = tod.dropna(subset=["fresh_prints_per_min"])
    print(f"corr(pond, fresh prints/min) = "
          f"{np.corrcoef(sub.pond_pf_bp, sub.fresh_prints_per_min)[0,1]:+.3f}")
    print(f"hour windows where the best real signal beats every placebo: "
          f"{int(tod.real_beats_placebo.sum())} of {len(tod)}")
    print(f"every window needs a cross-sectional IC of "
          f"{tod.IC_needed_to_breakeven.min():.2f}-{tod.IC_needed_to_breakeven.max():.2f} "
          f"to pay the {COST_MED:.3f} bp round trip")


if __name__ == "__main__":
    main()

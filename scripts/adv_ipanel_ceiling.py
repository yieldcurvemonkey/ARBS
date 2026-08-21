r"""ADVERSARIAL CHECK 2: re-derive the DECIDING NUMBER from scratch.

The report's verdict rests on "0.092 bp perfect-foresight gross vs 0.99 bp cost".
That 0.092 was inherited from a DIFFERENT agent's script (etf_horizon_sweep.py) built on
the HOURLY layer. This recomputes it on the MI01 panel, on both fit variants, at two
freshness rules, and adds the test the report never ran: a perfect-foresight trader does
not trade every fly, he trades the ones that beat the cost.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

DATA = pathlib.Path(r"C:\Users\chris\clee\ARBS-etf\notebooks\backtests\etf_rebalance\_data")
COST_DAILY = 0.535
COST_NEW = 0.9915


def flies(vals: np.ndarray) -> np.ndarray:
    """2*belly - wing_lo - wing_hi over maturity-adjacent triples."""
    return 2.0 * vals[1:-1] - vals[:-2] - vals[2:]


def seam_ceiling(p, col, lo, hi, fresh_min, max_wing_gap_y=None, min_bonds=20):
    """mean|d fly|, max|d fly|, and the perfect-foresight SELECTIVE economics."""
    w = p[p["mark_time"].isin((lo, hi)) & p[col].notna()
          & p["stale_min_ytm"].le(fresh_min) & p["stale_min_px"].le(fresh_min)]
    piv = w.pivot_table(index=["date", "cusip"], columns="mark_time", values=col)
    piv = piv.dropna()
    if piv.empty:
        return None
    ttm = w.groupby(["date", "cusip"])["ttm"].first()
    d = (piv[hi] - piv[lo]).rename("dres").to_frame().join(ttm)
    per_date, allf = [], []
    for date, g in d.groupby(level=0):
        g = g.sort_values("ttm")
        if len(g) < min_bonds:
            continue
        v = g["dres"].to_numpy()
        t = g["ttm"].to_numpy()
        f = flies(v)
        if max_wing_gap_y is not None:
            keep = (t[2:] - t[:-2]) <= max_wing_gap_y
            f = f[keep]
        if f.size == 0:
            continue
        af = np.abs(f)
        per_date.append((np.mean(af), np.max(af), af.size))
        allf.append(af)
    if not per_date:
        return None
    arr = np.array(per_date)
    af = np.concatenate(allf)
    out = {
        "col": col, "window": f"{lo}->{hi}", "fresh_max_min": fresh_min,
        "max_wing_gap_y": max_wing_gap_y if max_wing_gap_y is not None else np.inf,
        "dates": len(arr), "flies_per_date_med": float(np.median(arr[:, 2])),
        "mean_abs_fly_bp": float(np.median(arr[:, 0])),
        "max_abs_fly_bp_med": float(np.median(arr[:, 1])),
        "p99_abs_fly_bp": float(np.quantile(af, 0.99)),
    }
    for cost, tag in ((COST_DAILY, "0535"), (COST_NEW, "0991")):
        gross = out["mean_abs_fly_bp"]
        out[f"gross_over_cost_{tag}"] = gross / cost
        # SELECTIVE perfect foresight: trade only flies whose |move| beats the cost.
        hit = af > cost
        out[f"frac_flies_beating_{tag}"] = float(hit.mean())
        out[f"net_per_traded_fly_{tag}"] = float((af[hit] - cost).mean()) if hit.any() else 0.0
        # net bp harvested per date if you could trade every winner
        out[f"net_bp_per_date_{tag}"] = float(
            np.sum(af[hit] - cost) / len(arr)) if hit.any() else 0.0
    return out


def main() -> int:
    pd.set_option("display.width", 260)
    p = pd.read_parquet(DATA / "ipanel_mi01.parquet")
    p["date"] = pd.to_datetime(p["date"])

    rows = []
    for col in ("resid_bp", "resid_bp_tlt19", "resid_bp_band"):
        for lo, hi in (("15:00", "16:00"), ("14:00", "16:00"), ("12:00", "16:00"),
                       ("15:00", "15:30"), ("16:00", "16:15")):
            for fm in (30, 5):
                r = seam_ceiling(p, col, lo, hi, fm)
                if r:
                    rows.append(r)
    # wing-gap discipline: a "fly" whose wings are 3y apart is not a fly
    for gap in (1.0, 2.0):
        r = seam_ceiling(p, "resid_bp_tlt19", "15:00", "16:00", 5, max_wing_gap_y=gap)
        if r:
            rows.append(r)
        r = seam_ceiling(p, "resid_bp", "15:00", "16:00", 5, max_wing_gap_y=gap)
        if r:
            rows.append(r)

    t = pd.DataFrame(rows)
    cols = ["col", "window", "fresh_max_min", "max_wing_gap_y", "dates",
            "flies_per_date_med", "mean_abs_fly_bp", "max_abs_fly_bp_med",
            "p99_abs_fly_bp", "gross_over_cost_0535", "gross_over_cost_0991",
            "frac_flies_beating_0991", "net_per_traded_fly_0991", "net_bp_per_date_0991"]
    print("PERFECT-FORESIGHT CEILING, RE-DERIVED ON THE MI01 PANEL")
    print(t[cols].round(4).to_string(index=False))
    t.to_csv(DATA / "adv_ipanel_ceiling.csv", index=False)

    # ---------------------------------------------------- daily horizon, same machine
    print("\nDAILY HORIZON (16:00 -> 16:00 + n business days), resid_bp_tlt19, fresh<=5")
    w = p[p["mark_time"].eq("16:00") & p["resid_bp_tlt19"].notna()
          & p["stale_min_ytm"].le(5) & p["stale_min_px"].le(5)]
    piv = w.pivot_table(index="date", columns="cusip", values="resid_bp_tlt19").sort_index()
    ttm = w.pivot_table(index="date", columns="cusip", values="ttm")
    drows = []
    for lag in (1, 5, 21):
        dd = piv.shift(-lag) - piv
        acc = []
        for date, row in dd.iterrows():
            v = row.dropna()
            if len(v) < 20:
                continue
            tt = ttm.loc[date, v.index].dropna()
            v = v[tt.index]
            order = tt.sort_values().index
            f = np.abs(flies(v[order].to_numpy()))
            acc.append((f.mean(), f.max(), f.size))
        a = np.array(acc)
        drows.append({"horizon": f"16:00 +{lag}bd", "dates": len(a),
                      "mean_abs_fly_bp": float(np.median(a[:, 0])),
                      "max_abs_fly_bp_med": float(np.median(a[:, 1])),
                      "gross_over_cost_0991": float(np.median(a[:, 0])) / COST_NEW})
    dt = pd.DataFrame(drows)
    print(dt.round(4).to_string(index=False))
    dt.to_csv(DATA / "adv_ipanel_ceiling_daily.csv", index=False)
    print("\nwrote adv_ipanel_ceiling.csv, adv_ipanel_ceiling_daily.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

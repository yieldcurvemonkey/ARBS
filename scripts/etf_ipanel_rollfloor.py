r"""Recalibrate Roll's noise floor at the tape's OWN measured volatility.

``etf_ipanel_costs.py`` simulated the floor at an assumed 3.0 price bp per minute-change.
Roll's spurious estimate on a spreadless series scales with that volatility, so a floor
computed at the wrong sigma is a number about the simulation and not about the tape.
This measures sigma from the same minute changes Roll consumes -- same session filter,
same 5-minute gap cap -- and re-runs the simulation at the measured value, per year, so
the floor tracks the fact that 2022's tape is far more volatile than 2021's.

It also reports the fraction of minute changes that are exactly zero. A repeated stale
mark contributes a zero change, which pulls the autocovariance toward zero and therefore
pulls Roll DOWN; that fraction is the size of the deflator.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from RVUtils.ETFRebalance import intraday_panel as IP  # noqa: E402
from RVUtils.ETFRebalance.intraday_panel import _series, roll_spread  # noqa: E402

DATA = IP.DATA
SESSION = (8, 17)
MAX_GAP_MIN = 5


def measured_sigma(isins, *, sample: int = 30) -> pd.DataFrame:
    """Per-year sd of the usable minute price changes, in PRICE bp."""
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache

    cache = CitiVeloTagCache()
    rows = []
    for isin in list(isins)[:sample]:
        s = _series(cache, f"RATES.BOND.{isin}.PRICE", "MI01")
        if s is None:
            continue
        idx = pd.DatetimeIndex(s.index)
        s = s[(idx.hour >= SESSION[0]) & (idx.hour < SESSION[1])]
        if s.empty:
            continue
        df = pd.DataFrame({"ts": pd.DatetimeIndex(s.index), "px": s.to_numpy(float)})
        gap = df["ts"].diff().dt.total_seconds() / 60.0
        same_day = df["ts"].dt.normalize().eq(df["ts"].dt.normalize().shift())
        usable = same_day & gap.le(MAX_GAP_MIN)
        dp = (df["px"].diff() / df["px"].shift() * 1e4)[usable]
        yr = df["ts"].dt.year[usable]
        for y, g in dp.groupby(yr):
            rows.append({"isin": isin, "year": int(y), "sigma_price_bp": float(g.std()),
                         "frac_zero_change": float((g == 0).mean()), "n": int(len(g))})
    return pd.DataFrame(rows)


def floor_at(sigma: float, n_pairs: int, reps: int = 500, seed: int = 20260820) -> tuple:
    rng = np.random.default_rng(seed)
    est = []
    for _ in range(reps):
        w = 100.0 * np.exp(np.cumsum(rng.normal(0, sigma * 1e-4, n_pairs + 2)))
        s, _, _ = roll_spread(w, np.ones(n_pairs + 2, bool))
        est.append(s)
    e = np.array(est, float)
    fin = e[np.isfinite(e)]
    return (float(np.median(fin)) if len(fin) else np.nan,
            float(np.quantile(fin, .90)) if len(fin) else np.nan,
            float(np.isfinite(e).mean()))


def main() -> int:
    pd.set_option("display.width", 240)
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    sg = measured_sigma(uni["isin"].astype(str))
    by_year = sg.groupby("year").apply(
        lambda g: pd.Series({
            "bonds": g["isin"].nunique(),
            "sigma_price_bp": float(np.average(g["sigma_price_bp"], weights=g["n"])),
            "frac_zero_change": float(np.average(g["frac_zero_change"], weights=g["n"])),
            "changes": int(g["n"].sum())}), include_groups=False).reset_index()
    print("MEASURED minute-change volatility of the Citi price tape (30-bond sample):")
    print(by_year.round(4).to_string(index=False))

    roll = pd.read_csv(DATA / "ipanel_roll_bond_month.csv")
    roll = roll[roll["variant"].eq("all changes")]
    roll["year"] = pd.to_datetime(roll["month"]).dt.year
    obs = roll.groupby("year").agg(
        bond_months=("roll_price_bp", "size"),
        median_n_pairs=("n_pairs", "median"),
        roll_price_bp_median=("roll_price_bp", "median"),
        undefined_frac=("roll_price_bp", lambda s: float(s.isna().mean()))).reset_index()

    t = obs.merge(by_year[["year", "sigma_price_bp", "frac_zero_change"]], on="year",
                  how="left")
    med, p90, defined = [], [], []
    for _, r in t.iterrows():
        a, b, c = floor_at(float(r["sigma_price_bp"]), int(r["median_n_pairs"]))
        med.append(a); p90.append(b); defined.append(c)
    t["floor_median_price_bp"] = med
    t["floor_p90_price_bp"] = p90
    t["floor_frac_defined"] = defined
    t["roll_over_floor"] = t["roll_price_bp_median"] / t["floor_median_price_bp"]
    t["above_p90_floor"] = t["roll_price_bp_median"] > t["floor_p90_price_bp"]

    print("\nROLL vs ITS OWN NOISE FLOOR, at the MEASURED volatility, by year:")
    print(t.round(4).to_string(index=False))
    t.to_csv(DATA / "ipanel_roll_floor_measured.csv", index=False)

    sig_all = float(np.average(by_year["sigma_price_bp"], weights=by_year["changes"]))
    npair = float(roll["n_pairs"].median())
    a, b, c = floor_at(sig_all, int(npair), reps=1500)
    rollmed = float(roll["roll_price_bp"].median())
    print(f"\nPOOLED: measured sigma {sig_all:.4f} price bp/change, median "
          f"{npair:,.0f} pairs per bond-month")
    print(f"  noise floor  median {a:.4f}  p90 {b:.4f} price bp  "
          f"(defined on {c*100:.1f}% of spreadless draws)")
    print(f"  Roll actual  median {rollmed:.4f} price bp  ->  {rollmed/a:.2f}x the "
          f"median floor, {'ABOVE' if rollmed > b else 'BELOW'} the p90 floor")
    pd.DataFrame([{"sigma_price_bp_measured": sig_all, "median_n_pairs": npair,
                   "floor_median_price_bp": a, "floor_p90_price_bp": b,
                   "roll_price_bp_median": rollmed, "roll_over_floor": rollmed / a,
                   "above_p90_floor": bool(rollmed > b),
                   "frac_zero_change": float(np.average(by_year["frac_zero_change"],
                                                        weights=by_year["changes"]))}]
                 ).to_csv(DATA / "ipanel_roll_floor_headline.csv", index=False)
    print("\nwrote ipanel_roll_floor_measured.csv, ipanel_roll_floor_headline.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

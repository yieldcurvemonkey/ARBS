r"""Task 1 and 2: how big is the 15:00->16:00 seam, how much of it reverses, and
how much of it is cross-sectional rather than level.

The two traps this script is built around
-----------------------------------------
**1. A shared endpoint manufactures reversal.** The seam move is ``y16 - y15`` and
the overnight move is ``y10_next - y16``. They share ``y16``, so any measurement
error in that one mark enters the first with a ``+`` and the second with a ``-``
and produces a negative regression coefficient out of nothing. At a 0.1 bp
idiosyncratic scale on a tape whose median print gap is two minutes, that is not a
small effect -- pure iid mark noise drives the coefficient toward -1 for the part
of the variance it owns. So every reversal number here is reported twice: once
with the shared endpoint and once measured from ``y17`` instead, which removes the
mechanical link at the cost of an hour of real drift. The gap between them is the
size of the artefact.

**2. A bounce is not a seam.** Two placebos with no ETF story attached: an adjacent
same-day pair that shares a mark (13->14 then 14->15), and a disjoint same-day pair
that does not (13->14 then 15->16). If the seam's reversal looks like the adjacent
placebo, it is microstructure.

Every number is quoted in basis points against the measured 0.535 bp butterfly
round trip, never as a t or an R-squared alone.
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
    DATA, FLY_ROUND_TRIP_BP, day_types, decompose, load_panel, newey_west_t,
)

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)

#: Every (window) cell this script evaluates, counted for the deflation budget.
CELLS: list[str] = []


def add_move(p: pd.DataFrame, a: str, b: str, name: str) -> pd.DataFrame:
    p[name] = (p[b] - p[a]) * 100.0
    return p


def ols_beta(y: np.ndarray, x: np.ndarray) -> tuple[float, float, int]:
    ok = np.isfinite(y) & np.isfinite(x)
    y, x = y[ok], x[ok]
    if len(y) < 50:
        return float("nan"), float("nan"), len(y)
    xc = x - x.mean()
    denom = float(np.dot(xc, xc))
    if denom <= 0:
        return float("nan"), float("nan"), len(y)
    b = float(np.dot(xc, y - y.mean()) / denom)
    r = float(np.corrcoef(x, y)[0, 1])
    return b, r, len(y)


def main() -> int:
    p = load_panel(drop_early_close=True)
    praw = load_panel(drop_early_close=False)
    print(f"panel: {len(p):,} bond-dates on {p['date'].nunique():,} dates "
          f"(early-close days excluded; {len(praw):,} / {praw['date'].nunique():,} "
          f"before exclusion)", flush=True)

    for src, (a, b) in {
        "seam_1500_1600": ("y15", "y16"),
        "ctl_1400_1500": ("y14", "y15"),
        "ctl_1300_1400": ("y13", "y14"),
        "ctl_1600_1700": ("y16", "y17"),
        "sess_1000_1600": ("y10", "y16"),
        "on_1600_1000n": ("y16", "y10_next"),
        "on_1700_1000n": ("y17", "y10_next"),
        "day_1600_1600n": ("y16", "y16_next"),
    }.items():
        add_move(p, a, b, src)
        add_move(praw, a, b, src)

    dt = day_types(pd.DatetimeIndex(p["date"].unique()))
    p = p.merge(dt.reset_index()[["date", "day_type", "is_month_end", "is_fomc",
                                  "is_auction", "cal_days_to_month_end"]], on="date")

    # ---------------------------------------------------------------- self-check
    # The FOMC flag is DERIVED (effective date minus one business day). Check it
    # against the tape before any result leans on it: the 14:00 New York hour --
    # the statement hour, which is the 13->14 mark pair's own window on the 14:00
    # print, i.e. our ctl_1400_1500 window opens at the statement -- must be
    # visibly more active on flagged dates than on ordinary ones.
    chk = []
    for w in ("ctl_1300_1400", "ctl_1400_1500", "seam_1500_1600"):
        g = p.groupby("is_fomc")[w].apply(lambda s: np.nanmean(np.abs(s)))
        chk.append({"window": w, "ordinary_mean_abs_bp": float(g.get(False, np.nan)),
                    "fomc_mean_abs_bp": float(g.get(True, np.nan)),
                    "ratio": float(g.get(True, np.nan) / g.get(False, np.nan))})
    chk = pd.DataFrame(chk)
    n_fomc = int(p.loc[p["is_fomc"], "date"].nunique())
    print(f"\nSELF-CHECK on the derived FOMC flag ({n_fomc} dates in window):")
    print(chk.round(4).to_string(index=False), flush=True)
    chk.to_csv(DATA / "seam_fomc_flag_selfcheck.csv", index=False)

    # ------------------------------------------------- 1. size of the seam move
    def dist(s: pd.Series) -> dict:
        v = s.dropna().to_numpy(float)
        return {"n": len(v), "mean_bp": float(v.mean()),
                "mean_abs_bp": float(np.abs(v).mean()), "sd_bp": float(v.std()),
                "p50_abs_bp": float(np.percentile(np.abs(v), 50)),
                "p90_abs_bp": float(np.percentile(np.abs(v), 90)),
                "p99_abs_bp": float(np.percentile(np.abs(v), 99)),
                "frac_exactly_zero": float((v == 0).mean())}

    rows = []
    for w in ("seam_1500_1600", "ctl_1400_1500", "ctl_1300_1400", "ctl_1600_1700",
              "sess_1000_1600", "on_1600_1000n", "day_1600_1600n"):
        rows.append({"window": w, **dist(p[w])})
        CELLS.append(f"dist:{w}")
    dist_all = pd.DataFrame(rows)
    print("\n=== 1a. SIZE OF THE MOVE, pooled bond-dates, bp ===")
    print(dist_all.round(4).to_string(index=False), flush=True)
    dist_all.to_csv(DATA / "seam_move_distribution.csv", index=False)

    by_year = p.groupby(p["date"].dt.year)["seam_1500_1600"].apply(
        lambda s: pd.Series(dist(s))).unstack()
    by_year["dates"] = p.groupby(p["date"].dt.year)["date"].nunique()
    print("\n=== 1b. SEAM MOVE BY YEAR ===")
    print(by_year.round(4).to_string(), flush=True)
    by_year.to_csv(DATA / "seam_move_by_year.csv")
    CELLS.extend(f"dist_year:{y}" for y in by_year.index)

    by_type = p.groupby("day_type")["seam_1500_1600"].apply(
        lambda s: pd.Series(dist(s))).unstack()
    by_type["dates"] = p.groupby("day_type")["date"].nunique()
    print("\n=== 1c. SEAM MOVE BY DAY TYPE (fomc > month_end > auction > ordinary) ===")
    print(by_type.round(4).to_string(), flush=True)
    by_type.to_csv(DATA / "seam_move_by_daytype.csv")
    CELLS.extend(f"dist_daytype:{k}" for k in by_type.index)

    # ------------------------------- 2. level / slope / idiosyncratic decomposition
    dec_rows, per_obs = {}, {}
    for w in ("seam_1500_1600", "ctl_1400_1500", "ctl_1300_1400", "ctl_1600_1700",
              "sess_1000_1600", "on_1600_1000n", "on_1700_1000n", "day_1600_1600n"):
        pd_, po_ = decompose(p, col=w)
        dec_rows[w], per_obs[w] = pd_, po_
        CELLS.append(f"decomp:{w}")

    summ = []
    for w, d in dec_rows.items():
        vt, vl, vs, vi = (d["var_total"].sum(), d["var_after_level"].sum(),
                          d["var_after_slope"].sum(), d["var_idio"].sum())
        summ.append({
            "window": w, "dates": len(d),
            "level_sd_bp": float(d["level_bp"].std()),
            "level_mean_bp": float(d["level_bp"].mean()),
            "sd_total_bp_median": float(d["sd_total_bp"].median()),
            "sd_after_level_bp_median": float(d["sd_after_level_bp"].median()),
            "sd_idio_bp_median": float(d["sd_idio_bp"].median()),
            "mad_idio_bp_median": float(d["mad_idio_bp"].median()),
            "var_share_level": float(1 - vl / vt),
            "var_share_slope_curv": float((vl - vi) / vt),
            "var_share_idio": float(vi / vt),
            "idio_sd_vs_fly_cost": float(d["sd_idio_bp"].median() / FLY_ROUND_TRIP_BP),
        })
    summ = pd.DataFrame(summ)
    print("\n=== 2. LEVEL / SLOPE / IDIOSYNCRATIC DECOMPOSITION ===")
    print("(variance shares are of the RAW cross-section including the level, so "
          "they sum to 1)")
    print(summ.round(4).to_string(index=False), flush=True)
    summ.to_csv(DATA / "seam_decomposition.csv", index=False)

    seam_dec = dec_rows["seam_1500_1600"]
    seam_dec.to_csv(DATA / "seam_decomposition_by_date.csv", index=False)
    sd = seam_dec.merge(dt.reset_index()[["date", "day_type"]], on="date")
    by_t = sd.groupby("day_type").agg(
        dates=("date", "size"),
        level_sd_bp=("level_bp", "std"),
        sd_idio_bp_median=("sd_idio_bp", "median"),
        mad_idio_bp_median=("mad_idio_bp", "median"))
    by_t["idio_vs_fly_cost"] = by_t["sd_idio_bp_median"] / FLY_ROUND_TRIP_BP
    by_y = sd.groupby(sd["date"].dt.year).agg(
        dates=("date", "size"),
        level_sd_bp=("level_bp", "std"),
        sd_idio_bp_median=("sd_idio_bp", "median"))
    by_y["idio_vs_fly_cost"] = by_y["sd_idio_bp_median"] / FLY_ROUND_TRIP_BP
    print("\n=== 2b. SEAM IDIOSYNCRATIC DISPERSION BY DAY TYPE ===")
    print(by_t.round(4).to_string(), flush=True)
    print("\n=== 2c. SEAM IDIOSYNCRATIC DISPERSION BY YEAR ===")
    print(by_y.round(4).to_string(), flush=True)
    by_t.to_csv(DATA / "seam_idio_by_daytype.csv")
    by_y.to_csv(DATA / "seam_idio_by_year.csv")
    CELLS.extend([f"idio_daytype:{k}" for k in by_t.index]
                 + [f"idio_year:{y}" for y in by_y.index])

    # ------------------------------------------------------------ 3. reversal
    # LEVEL reversal: the date-level cross-sectional mean.
    lev = {w: dec_rows[w].set_index("date")["level_bp"] for w in dec_rows}
    rev_rows = []
    for name, (xw, yw, shares) in {
        "LEVEL seam -> next 10:00 (shares y16)": ("seam_1500_1600", "on_1600_1000n", True),
        "LEVEL seam -> next 10:00 from 17:00 (clean)": ("seam_1500_1600", "on_1700_1000n", False),
        "LEVEL seam -> next 16:00 (shares y16)": ("seam_1500_1600", "day_1600_1600n", True),
        "LEVEL placebo 13->14 then 14->15 (shares y14)": ("ctl_1300_1400", "ctl_1400_1500", True),
        "LEVEL placebo 13->14 then 15->16 (disjoint)": ("ctl_1300_1400", "seam_1500_1600", False),
        "LEVEL ctl 14->15 -> next 10:00 (shares y15? no)": ("ctl_1400_1500", "on_1600_1000n", False),
    }.items():
        j = pd.concat([lev[xw].rename("x"), lev[yw].rename("y")], axis=1).dropna()
        b, r, n = ols_beta(j["y"].to_numpy(), j["x"].to_numpy())
        rev_rows.append({"scope": "level", "pair": name, "shares_a_mark": shares,
                         "beta": b, "corr": r, "n": n,
                         "pct_reversed": -100.0 * b})
        CELLS.append(f"reversal_level:{name}")

    # IDIOSYNCRATIC reversal, on the per-date level+slope+curvature residuals.
    def idio_join(xw: str, yw: str) -> pd.DataFrame:
        a = per_obs[xw][["date", "isin", "idio"]].rename(columns={"idio": "x"})
        b = per_obs[yw][["date", "isin", "idio"]].rename(columns={"idio": "y"})
        return a.merge(b, on=["date", "isin"], how="inner")

    for name, (xw, yw, shares) in {
        "IDIO seam -> next 10:00 (shares y16)": ("seam_1500_1600", "on_1600_1000n", True),
        "IDIO seam -> next 10:00 from 17:00 (clean)": ("seam_1500_1600", "on_1700_1000n", False),
        "IDIO seam -> next 16:00 (shares y16)": ("seam_1500_1600", "day_1600_1600n", True),
        "IDIO placebo 13->14 then 14->15 (shares y14)": ("ctl_1300_1400", "ctl_1400_1500", True),
        "IDIO placebo 13->14 then 15->16 (disjoint)": ("ctl_1300_1400", "seam_1500_1600", False),
    }.items():
        j = idio_join(xw, yw)
        b, r, n = ols_beta(j["y"].to_numpy(), j["x"].to_numpy())
        # Per-date betas so the t is not an n=120k illusion.
        per = j.groupby("date").apply(
            lambda g: ols_beta(g["y"].to_numpy(), g["x"].to_numpy())[0]
            if len(g) >= 20 else np.nan, include_groups=False)
        m, se, t, nd = newey_west_t(per)
        rev_rows.append({"scope": "idio", "pair": name, "shares_a_mark": shares,
                         "beta": b, "corr": r, "n": n, "pct_reversed": -100.0 * b,
                         "per_date_beta_mean": m, "per_date_beta_nw_t": t,
                         "per_date_n": nd})
        CELLS.append(f"reversal_idio:{name}")

    rev = pd.DataFrame(rev_rows)
    print("\n=== 3. REVERSAL. beta is of the LATER move on the EARLIER one; "
          "beta = -1 is full reversal ===")
    print(rev.round(4).to_string(index=False), flush=True)
    rev.to_csv(DATA / "seam_reversal.csv", index=False)

    # How much of the seam is round-tripped in bp, not in beta: the part of the
    # seam move that is given back by the next morning.
    j = idio_join("seam_1500_1600", "on_1600_1000n")
    sx = float(np.nanstd(j["x"]))
    b = ols_beta(j["y"].to_numpy(), j["x"].to_numpy())[0]
    jc = idio_join("seam_1500_1600", "on_1700_1000n")
    bc = ols_beta(jc["y"].to_numpy(), jc["x"].to_numpy())[0]
    print(f"\nIDIO seam sd = {sx:.4f} bp. A 1-sd idiosyncratic seam move is given "
          f"back by next 10:00 to the tune of {-b * sx:.4f} bp (shared endpoint) / "
          f"{-bc * sx:.4f} bp (clean, from 17:00). "
          f"Fly round trip = {FLY_ROUND_TRIP_BP} bp.", flush=True)

    # ------------------------------ 4. is the idio seam move a BOND-level constant?
    # If the ETF story is right, a held bond should carry a persistent 15->16 drift.
    io = per_obs["seam_1500_1600"]
    half = io["date"].quantile(0.5)
    a = io[io["date"] <= half].groupby("isin")["idio"].agg(["mean", "size"])
    b2 = io[io["date"] > half].groupby("isin")["idio"].agg(["mean", "size"])
    jj = a.join(b2, lsuffix="_h1", rsuffix="_h2").dropna()
    jj = jj[(jj["size_h1"] >= 100) & (jj["size_h2"] >= 100)]
    rho = float(np.corrcoef(jj["mean_h1"], jj["mean_h2"])[0, 1]) if len(jj) > 5 else np.nan
    pers = pd.DataFrame({
        "bonds": [len(jj)],
        "split_date": [str(pd.Timestamp(half).date())],
        "h1_bond_mean_sd_bp": [float(jj["mean_h1"].std())],
        "h2_bond_mean_sd_bp": [float(jj["mean_h2"].std())],
        "corr_h1_h2": [rho],
    })
    print("\n=== 4. IS THE IDIOSYNCRATIC SEAM MOVE A PERSISTENT BOND EFFECT? ===")
    print(pers.round(4).to_string(index=False), flush=True)
    pers.to_csv(DATA / "seam_idio_bond_persistence.csv", index=False)
    jj.to_csv(DATA / "seam_idio_bond_means.csv")
    CELLS.append("bond_persistence:split_half")

    print(f"\nCELLS EVALUATED IN THIS SCRIPT: {len(CELLS)}")
    pd.Series(CELLS, name="cell").to_csv(DATA / "seam_cells_reversal.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

r"""Task 3: does TLT's own holding of a bond predict that bond's 15:00->16:00
IDIOSYNCRATIC move?

This is the sharpest form of the ETF hypothesis. The daily study could only ask
"does the holdings signal predict tomorrow's richness change", where tomorrow is
one 15:00-ish FedInvest mark to the next. Here the dependent variable is the part
of the move inside the single hour where the fund's economics (a 16:00 NAV, a
16:00 share close) and the cash market's marks (15:00) are known to disagree.

Discipline, all of it non-negotiable
------------------------------------
* ``exec_lag >= 1`` business day on everything read from a holdings file. An
  iShares document stamped ``as of T`` publishes overnight; nothing in it is
  knowable at any hour on T, and an intraday dependent variable does not change
  that. The lag is applied along the panel's own date axis
  (``holdings_panel.apply_exec_lag``), so a holiday moves the trade date to the
  next date that exists rather than to one with no marks.
* **The richness control is compulsory.** The daily study's single finding was
  that the holdings signals were the bond's own richness residual wearing the
  signal's clothes. Every specification here is run twice, with and without the
  15:00 richness residual as a second regressor, and the uncontrolled number is
  reported only next to the controlled one.
* Fama-MacBeth: one cross-sectional regression per date, then a Newey-West t on
  the coefficient series. A pooled t over 110k overlapping bond-dates is an
  illusion; the daily study measured naive t's inflated five- to six-fold.
* Every coefficient is quoted in **bp per one cross-sectional standard deviation
  of the signal**, against the measured 0.535 bp butterfly round trip.
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
    DATA, FLY_ROUND_TRIP_BP, decompose, load_panel, newey_west_t,
)
from RVUtils.ETFRebalance import curve as CV  # noqa: E402
from RVUtils.ETFRebalance.holdings_panel import apply_exec_lag  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)

CELLS: list[str] = []


def zscore(s: pd.Series) -> pd.Series:
    sd = s.std()
    return (s - s.mean()) / sd if sd and np.isfinite(sd) and sd > 0 else s * np.nan


def fama_macbeth(df: pd.DataFrame, ycol: str, xcols: list[str], *, min_n: int = 15
                 ) -> pd.DataFrame:
    """Per-date OLS, then the Newey-West t on each coefficient's own time series."""
    coefs = []
    for d, g in df.groupby("date", sort=True):
        g = g.dropna(subset=[ycol] + xcols)
        if len(g) < min_n:
            continue
        X = np.column_stack([np.ones(len(g))] + [g[c].to_numpy(float) for c in xcols])
        y = g[ycol].to_numpy(float)
        if np.linalg.matrix_rank(X) < X.shape[1]:
            continue
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        coefs.append(dict(zip(["const"] + xcols, b), date=d, n=len(g)))
    if not coefs:
        return pd.DataFrame()
    C = pd.DataFrame(coefs).set_index("date")
    rows = []
    for c in xcols:
        m, se, t, n = newey_west_t(C[c])
        rows.append({"regressor": c, "bp_per_1sd": m, "nw_se": se, "nw_t": t,
                     "dates": n, "mean_xsec_n": float(C["n"].mean()),
                     "abs_bp_vs_fly_cost": abs(m) / FLY_ROUND_TRIP_BP})
    return pd.DataFrame(rows)


def main() -> int:
    # ------------------------------------------------------- dependent variable
    p = load_panel(drop_early_close=True)
    p["seam"] = (p["y16"] - p["y15"]) * 100.0
    p["next_day"] = (p["y16_next"] - p["y16"]) * 100.0
    _, seam_obs = decompose(p, col="seam")
    seam_obs = seam_obs.rename(columns={"idio": "idio_seam"})[
        ["date", "cusip", "idio_seam"]]
    _, day_obs = decompose(p, col="next_day")
    day_obs = day_obs.rename(columns={"idio": "idio_next_day"})[
        ["date", "cusip", "idio_next_day"]]

    # ---------------------------------------- the 15:00 richness residual control
    rich_in = p.dropna(subset=["y15"])[["date", "cusip", "ttm", "cpn"]].copy()
    rich_in["ytm"] = p.loc[rich_in.index, "y15"]
    rich = CV.fit_residuals(rich_in, deg=3, x_axis="ttm", include_coupon=True,
                            robust=True)[["date", "cusip", "resid_bp"]]
    print(f"richness residual at 15:00 New York: {len(rich):,} bond-dates, "
          f"sd {rich['resid_bp'].std():.3f} bp", flush=True)

    # ------------------------------------------------------------- the holdings
    act = pd.read_parquet(DATA / "fundfig_active_TLT.parquet")
    act["date"] = pd.to_datetime(act["date"])
    act["cusip"] = act["cusip"].astype(str)
    act = act[act["date"] >= p["date"].min() - pd.Timedelta(days=10)]
    act["d_active_w_1"] = act.sort_values("date").groupby("cusip")["active_w"].diff(1)
    act["d_active_w_5"] = act.sort_values("date").groupby("cusip")["active_w"].diff(5)
    act["d_own_5"] = act.sort_values("date").groupby("cusip")["ownership"].diff(5)
    act["held_dummy"] = act["held"].astype(float)

    SIGNALS = ["active_w", "ownership", "d_active_w_1", "d_active_w_5", "d_own_5",
               "held_dummy", "w_f"]

    out_rows = []
    for exec_lag in (1, 2):
        a = apply_exec_lag(act, exec_lag=exec_lag)
        a = a.rename(columns={"date": "asof_date", "trade_date": "date"})
        m = (seam_obs.merge(day_obs, on=["date", "cusip"], how="left")
                     .merge(rich, on=["date", "cusip"], how="left")
                     .merge(a[["date", "asof_date", "cusip"] + SIGNALS],
                            on=["date", "cusip"], how="inner"))
        assert (m["asof_date"] < m["date"]).all(), "exec lag did not move the date"
        for c in SIGNALS + ["resid_bp"]:
            m["z_" + c] = m.groupby("date")[c].transform(zscore)
        print(f"\nexec_lag={exec_lag}: {len(m):,} bond-dates on "
              f"{m['date'].nunique():,} dates", flush=True)

        for ycol, yname in (("idio_seam", "15:00->16:00 idiosyncratic"),
                            ("idio_next_day", "16:00->next 16:00 idiosyncratic")):
            for sig in SIGNALS:
                for ctrl, cname in (([], "no control"),
                                    (["z_resid_bp"], "+ richness control")):
                    r = fama_macbeth(m, ycol, ["z_" + sig] + ctrl)
                    if r.empty:
                        continue
                    row = r[r["regressor"] == "z_" + sig].iloc[0].to_dict()
                    row.update({"exec_lag": exec_lag, "y": yname, "signal": sig,
                                "spec": cname})
                    out_rows.append(row)
                    CELLS.append(f"fm:{exec_lag}:{yname}:{sig}:{cname}")

    res = pd.DataFrame(out_rows)[
        ["exec_lag", "y", "signal", "spec", "bp_per_1sd", "nw_t", "dates",
         "mean_xsec_n", "abs_bp_vs_fly_cost"]]
    res = res.sort_values(["y", "exec_lag", "signal", "spec"])
    print("\n=== FAMA-MACBETH: bp of IDIOSYNCRATIC move per 1 cross-sectional sd "
          "of the lagged TLT signal ===")
    print(res.round(5).to_string(index=False), flush=True)
    res.to_csv(DATA / "seam_holdings_fama_macbeth.csv", index=False)

    best = res.loc[res["nw_t"].abs().idxmax()]
    print(f"\nlargest |NW t| across {len(res)} cells: {best['signal']} "
          f"({best['spec']}, lag {best['exec_lag']}, y={best['y']}): "
          f"{best['bp_per_1sd']:+.5f} bp per 1sd, t={best['nw_t']:+.2f}", flush=True)
    big = res.loc[res["bp_per_1sd"].abs().idxmax()]
    print(f"largest |bp per 1sd|: {big['signal']} ({big['spec']}, lag "
          f"{big['exec_lag']}, y={big['y']}): {big['bp_per_1sd']:+.5f} bp = "
          f"{big['abs_bp_vs_fly_cost']:.4f}x the 0.535 bp round trip", flush=True)

    # ------------------------------------- held vs never-held, the crudest contrast
    a1 = apply_exec_lag(act, exec_lag=1).rename(
        columns={"date": "asof_date", "trade_date": "date"})
    m = seam_obs.merge(a1[["date", "cusip", "held"]], on=["date", "cusip"], how="inner")
    m = m.merge(p[["date", "cusip", "held_by_tlt"]], on=["date", "cusip"], how="left")
    rows = []
    for key, lbl in (("held", "held by TLT on the day (lag 1)"),
                     ("held_by_tlt", "ever held by TLT 2021-2026")):
        d = m.dropna(subset=[key])
        diff = (d.groupby("date")
                 .apply(lambda g: (g.loc[g[key].astype(bool), "idio_seam"].mean()
                                   - g.loc[~g[key].astype(bool), "idio_seam"].mean()),
                        include_groups=False)
                 .dropna())
        mm, se, t, n = newey_west_t(diff)
        rows.append({"split": lbl, "mean_diff_bp": mm, "nw_t": t, "dates": n,
                     "abs_bp_vs_fly_cost": abs(mm) / FLY_ROUND_TRIP_BP})
        CELLS.append(f"heldsplit:{lbl}")
    hs = pd.DataFrame(rows)
    print("\n=== HELD MINUS NOT-HELD, mean idiosyncratic 15:00->16:00 move ===")
    print(hs.round(5).to_string(index=False), flush=True)
    hs.to_csv(DATA / "seam_holdings_held_split.csv", index=False)

    print(f"\nCELLS EVALUATED IN THIS SCRIPT: {len(CELLS)}")
    pd.Series(CELLS, name="cell").to_csv(DATA / "seam_cells_holdings.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

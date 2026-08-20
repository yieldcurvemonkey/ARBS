r"""ADVERSARIAL CHECK 5: WHEN IS FEDINVEST STRUCK? Independent identification.

The report concludes ~11:34 New York from a two-day step regression on 9 hourly marks,
corroborated by an RMSE contest over 11 coarse marks. Two things are wrong with resting
there: the step regression's R2 is 0.52 (its own docstring calls a capped R2 on this
test "a warning, not a footnote"), and the RMSE contest's winning margin was ~2%.

This identifies the strike DIRECTLY and at 15-minute resolution, without a step model:
resolve the Citi minute tape as-of every 15 minutes from 08:00 to 17:00 (37 candidates),
and for each candidate ask which one best REPRODUCES FedInvest.

  (a) pooled RMSE(citi_T - fed)              -> argmin is the strike
  (b) corr(d fed_t, d citi_T,t) day over day -> argmax is the strike
  (c) both, split by YEAR                    -> a pooled answer that is not stable
                                                across years is a pooled artefact

As-of is the SAME rule the panel claims: last print at or before T, same calendar day.
It is re-implemented here rather than imported.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
DATA = pathlib.Path(r"C:\Users\chris\clee\ARBS-etf\notebooks\backtests\etf_rebalance\_data")

MARKS = [f"{h:02d}:{m:02d}" for h in range(8, 17) for m in (0, 15, 30, 45)] + ["17:00"]


def asof(s: pd.Series, marks) -> pd.DataFrame:
    """last print AT OR BEFORE the mark, same calendar day. Re-implemented."""
    idx = pd.DatetimeIndex(s.index)
    pr = pd.DataFrame({"pts": idx, "v": s.to_numpy(float)}).sort_values("pts")
    days = pd.DatetimeIndex(np.unique(idx.normalize()))
    out = []
    for mt in marks:
        hh, mm = int(mt[:2]), int(mt[3:])
        tgt = pd.DataFrame({"t": days + pd.Timedelta(hours=hh, minutes=mm)})
        m = pd.merge_asof(tgt, pr, left_on="t", right_on="pts", direction="backward",
                          tolerance=pd.Timedelta(minutes=240)).dropna(subset=["pts", "v"])
        m = m[m["pts"].dt.normalize() == m["t"].dt.normalize()]
        if m.empty:
            continue
        assert (m["pts"] <= m["t"]).all(), "LOOKAHEAD in my own resolver"
        out.append(pd.DataFrame({"date": m["t"].dt.normalize().to_numpy(), "mark": mt,
                                 "ytm": m["v"].to_numpy(float),
                                 "stale": ((m["t"] - m["pts"]).dt.total_seconds() / 60).to_numpy()}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def main() -> int:
    pd.set_option("display.width", 260)
    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
    from RVUtils.ETFRebalance import bond_panel as BP
    from RVUtils.ETFRebalance import intraday as ID

    uni = ID.universe()
    uni = uni[uni["in_reference_band"].fillna(False)]
    cache = CitiVeloTagCache()

    parts = []
    for i, row in enumerate(uni.itertuples(index=False)):
        s = cache.read(f"RATES.BOND.{row.isin}.YIELD", "MI01", "CLOSE")
        if s is None or s.empty:
            continue
        s = s.dropna()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        s = s[(s > 0.2) & (s < 12.0)]
        m = asof(s, MARKS)
        if m.empty:
            continue
        m["cusip"] = str(row.cusip)
        parts.append(m)
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(uni)} tags, {sum(len(x) for x in parts):,} rows", flush=True)
    a = pd.concat(parts, ignore_index=True)
    a = a[a["stale"] <= 30]
    print(f"\nfine as-of panel: {len(a):,} rows, {a['date'].nunique()} dates, "
          f"{a['cusip'].nunique()} bonds, {a['mark'].nunique()} marks")

    d = BP.load()
    d = d[d["cusip"].isin(set(a["cusip"])) & d["ytm"].notna() & d["price_source"].eq("mid")]
    fed = d[["date", "cusip", "ytm"]].rename(columns={"ytm": "fed"})
    fed["date"] = pd.to_datetime(fed["date"])
    a = a.merge(fed, on=["date", "cusip"], how="inner")
    print(f"joined to FedInvest: {len(a):,} rows, {a['date'].nunique()} dates")

    a["diff_bp"] = (a["ytm"] - a["fed"]) * 100.0
    a["year"] = a["date"].dt.year

    # ------------------------------------------------------- (a) pooled RMSE by mark
    rows = []
    for mt, g in a.groupby("mark"):
        # day-over-day change correlation needs a per-bond series
        rows.append({"mark": mt, "n": len(g),
                     "rmse_bp": float(np.sqrt(np.mean(g["diff_bp"] ** 2))),
                     "mean_bias_bp": float(g["diff_bp"].mean()),
                     "sd_bp": float(g["diff_bp"].std())})
    r = pd.DataFrame(rows).sort_values("mark")

    # ------------------------------------------------ (b) daily-change correlation
    corrs = {}
    for mt, g in a.groupby("mark"):
        g = g.sort_values(["cusip", "date"])
        gg = g.groupby("cusip")
        dc = (g["ytm"] - gg["ytm"].shift(1)) * 100.0
        df_ = (g["fed"] - gg["fed"].shift(1)) * 100.0
        pd_days = (g["date"] - gg["date"].shift(1)).dt.days
        ok = dc.notna() & df_.notna() & pd_days.le(4)
        corrs[mt] = float(np.corrcoef(dc[ok], df_[ok])[0, 1])
    r["dchg_corr"] = r["mark"].map(corrs)
    print("\n=== WHICH CITI MARK REPRODUCES FEDINVEST? (37 candidates, 15-min grid)")
    print(r.round(4).to_string(index=False))
    r.to_csv(DATA / "adv_strike_grid.csv", index=False)
    print(f"\nargmin RMSE      -> {r.loc[r['rmse_bp'].idxmin(), 'mark']}  "
          f"({r['rmse_bp'].min():.4f} bp; runner-up "
          f"{r.nsmallest(2,'rmse_bp')['rmse_bp'].iloc[1]:.4f})")
    print(f"argmax d-corr    -> {r.loc[r['dchg_corr'].idxmax(), 'mark']}  "
          f"({r['dchg_corr'].max():.4f})")

    # ------------------------------------------------------------- (c) by year
    rows = []
    for (yr, mt), g in a.groupby(["year", "mark"]):
        rows.append({"year": yr, "mark": mt, "n": len(g),
                     "rmse_bp": float(np.sqrt(np.mean(g["diff_bp"] ** 2)))})
    ry = pd.DataFrame(rows)
    piv = ry.pivot(index="mark", columns="year", values="rmse_bp")
    print("\n=== RMSE(citi - fed) BY YEAR (bp) -- is the winner stable?")
    print(piv.round(4).to_string())
    piv.to_csv(DATA / "adv_strike_by_year.csv")
    print("\nargmin per year:")
    for yr in piv.columns:
        c = piv[yr].dropna()
        if len(c):
            print(f"  {yr}: {c.idxmin()}  ({c.min():.4f} bp, runner-up "
                  f"{c.nsmallest(2).iloc[1]:.4f})")

    # --------------------------------------------- how flat is the objective, really?
    best = r["rmse_bp"].min()
    within = r[r["rmse_bp"] <= best * 1.05]["mark"].tolist()
    print(f"\nmarks within 5% of the best RMSE: {within}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

r"""Task 4: on reconstitution days, do the bonds ENTERING and LEAVING the index show
a different 15:00->16:00 signature from maturity-matched controls?

The index rule, and where the event date comes from
---------------------------------------------------
TLT tracks a 20-plus-year ICE index that reconstitutes at month end. A bond whose
remaining maturity falls through twenty years during month M stays in the index for
all of M and is dropped at the end of M -- so the date the fund must have sold it is
the last business day of M, not the day the maturity crossed. A newly auctioned 20y
or 30y issued during M enters at the same reconstitution. Both event sets are
derived here from the INDEX RULE applied to reference data -- issued, and at least
twenty years to run, evaluated at each month end -- rather than from whether Citi
happened to serve a mark. Citi lags a new auction by about eight days, so a
marks-based membership test dates a 30-year's index entry to the wrong month.

* DELETION at month end M: in band at M-1, out of band at M.
* ADDITION at month end M: out of band or not yet issued at M-1, in band at M.

The deletion set is cross-checked against the backfill's own
``intraday_deletion_block_coverage.csv``, built independently from fiscaldata.

The control, and the bug that made the first version meaningless
----------------------------------------------------------------
"Matched on maturity" cannot mean exact matching at a boundary event: a deleted bond
sits just under twenty years by construction and its nearest survivor sits just over.
Worse, the *nearest* match is often catastrophically wrong. For the 30-year deleted
at the end of November 2021 the nearest-maturity bond in the cross-section was the
20-year auctioned that same week -- an exact maturity match, zero days of history,
simultaneously the most special bond in the sector and itself an index ADDITION.
Three conditions are therefore imposed, each a measured necessity:

* not an event bond at this same reconstitution, either side;
* seasoned, at least ``MIN_CONTROL_AGE_D`` days since issue;
* carrying a mark on every day of the event window, so that the event path and the
  control path are measured over the same dates rather than over whatever each
  happened to have. Without this the pre-event window silently collapsed from 27
  events to 14 and the two halves of the path were different samples.

The median maturity gap of the surviving matches is reported so a reader can judge
how good the match is.

Power, stated before the result
-------------------------------
There are of order twenty deletions in the warmed window. With an idiosyncratic seam
dispersion around 0.12 bp, the standard error of a twenty-event mean is about
0.026 bp and the smallest effect that could reach ``|t| = 2`` is about 0.05 bp --
already an order of magnitude inside the 0.535 bp round trip. That minimum
detectable effect is reported next to every measured one, because an event study
with no power produces a null that means nothing by itself.
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
    DATA, FLY_ROUND_TRIP_BP, decompose, load_panel,
)

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)

BAND_LOW_Y = 20.0          # ETFSpec("TLT").maturity_band[0]
MIN_CONTROL_AGE_D = 60     # a control must be seasoned; see the matcher below
WINDOW = list(range(-5, 6))
CELLS: list[str] = []


def main() -> int:
    p = load_panel(drop_early_close=True)
    p["seam"] = (p["y16"] - p["y15"]) * 100.0
    p["day"] = (p["y16_next"] - p["y16"]) * 100.0
    _, seam_obs = decompose(p, col="seam")
    seam_obs = seam_obs.rename(columns={"idio": "idio_seam"})
    _, day_obs = decompose(p, col="day")
    day_obs = day_obs.rename(columns={"idio": "idio_day"})[["date", "cusip", "idio_day"]]
    obs = seam_obs.merge(day_obs, on=["date", "cusip"], how="left")
    issue = p.drop_duplicates("cusip").set_index("cusip")["issue_date"]
    obs["age_d"] = (obs["date"] - obs["cusip"].map(issue)).dt.days

    dates = pd.DatetimeIndex(sorted(p["date"].unique()))
    pos = pd.Series(np.arange(len(dates)), index=dates)

    # Last TRADING date of each month the panel carries. A calendar month end would
    # land on a holiday and silently drop the event. The FINAL month is incomplete
    # -- the tape stops mid-August 2026 -- so its "month end" is not a
    # reconstitution and any event dated there is an artefact of where the data
    # stops; dropping it removed one phantom deletion.
    me_s = pd.Series(dates, index=dates).groupby(dates.to_period("M")).max()
    me_s = me_s[me_s.index < dates.max().to_period("M")]
    me = pd.DatetimeIndex(me_s.values)

    # ------------------------------------------------------------- membership
    uni = p[["cusip", "maturity_date", "issue_date"]].drop_duplicates("cusip")
    grid = uni.assign(_k=1).merge(pd.DataFrame({"date": me, "_k": 1}), on="_k")
    grid["ttm_me"] = (grid["maturity_date"] - grid["date"]).dt.days / 365.25
    grid["in_band"] = ((grid["date"] >= grid["issue_date"])
                       & (grid["ttm_me"] >= BAND_LOW_Y))
    piv = (grid.pivot_table(index="date", columns="cusip", values="in_band")
               .sort_index().fillna(False).astype(bool))
    prev = piv.shift(1)
    first = piv.index[0]

    add = piv & ~prev.fillna(False).astype(bool)
    dele = ~piv & prev.fillna(False).astype(bool)
    add.loc[first] = False          # no predecessor month: nothing is classifiable
    dele.loc[first] = False

    def events(mask: pd.DataFrame, kind: str) -> pd.DataFrame:
        s = mask.stack()
        s = s[s.astype(bool)]
        e = s.reset_index()[["date", "cusip"]]
        e["kind"] = kind
        return e

    ev = pd.concat([events(add, "addition"), events(dele, "deletion")],
                   ignore_index=True).sort_values(["date", "kind"])
    print(f"reconstitution events: {(ev['kind'] == 'addition').sum()} additions, "
          f"{(ev['kind'] == 'deletion').sum()} deletions, over {len(me)} month ends "
          f"{me.min().date()} .. {me.max().date()}", flush=True)
    ev.to_csv(DATA / "seam_monthend_events.csv", index=False)

    ref = pd.read_csv(DATA / "intraday_deletion_block_coverage.csv")
    ref["event_date"] = pd.to_datetime(ref["event_date"])
    mine = set(map(tuple, ev.loc[ev["kind"] == "deletion", ["date", "cusip"]]
                   .itertuples(index=False, name=None)))
    theirs = set(map(tuple, ref[["event_date", "cusip"]]
                     .itertuples(index=False, name=None)))
    print(f"deletion cross-check vs intraday_deletion_block_coverage.csv (which "
          f"starts in 2021): {len(mine & theirs)} agree, {len(mine - theirs)} only "
          f"here, {len(theirs - mine)} only there", flush=True)
    print("  only here :", sorted((str(d.date()), c) for d, c in (mine - theirs)))
    print("  only there:", sorted((str(d.date()), c) for d, c in (theirs - mine)),
          flush=True)

    # --------------------------------------------------- nearest-maturity controls
    ev_by_date = ev.groupby("date")["cusip"].apply(set).to_dict()
    obs_keys = set(map(tuple, obs[["date", "cusip"]]
                       .itertuples(index=False, name=None)))
    obs_ix = obs.set_index(["date", "cusip"])

    rows, skipped = [], []
    for _, e in ev.iterrows():
        e_pos = pos.get(e["date"], None)
        if e_pos is None:
            skipped.append((e["kind"], str(e["date"].date()), e["cusip"],
                            "month end not a panel date"))
            continue
        win = [int(e_pos) + k for k in WINDOW]
        if min(win) < 0 or max(win) >= len(dates):
            skipped.append((e["kind"], str(e["date"].date()), e["cusip"],
                            "window runs off the tape"))
            continue
        win_dates = [dates[j] for j in win]
        if not all((d, e["cusip"]) in obs_keys for d in win_dates):
            skipped.append((e["kind"], str(e["date"].date()), e["cusip"],
                            "event bond has a gap in the window"))
            continue
        same = obs[obs["date"] == e["date"]]
        e_ttm = float(same.loc[same["cusip"] == e["cusip"], "ttm"].iloc[0])
        busy = ev_by_date.get(e["date"], set())
        cand = same[(~same["cusip"].isin(busy)) & (same["age_d"] >= MIN_CONTROL_AGE_D)]
        cand = cand[[all((d, c) in obs_keys for d in win_dates)
                     for c in cand["cusip"]]]
        if cand.empty:
            skipped.append((e["kind"], str(e["date"].date()), e["cusip"],
                            "no eligible control"))
            continue
        ctl = cand.iloc[int((cand["ttm"] - e_ttm).abs().to_numpy().argmin())]
        for k, d in zip(WINDOW, win_dates):
            ge = obs_ix.loc[(d, e["cusip"])]
            gc = obs_ix.loc[(d, ctl["cusip"])]
            rows.append({
                "kind": e["kind"], "event_date": e["date"], "cusip": e["cusip"],
                "control_cusip": ctl["cusip"], "ttm_event": e_ttm,
                "ttm_control": float(ctl["ttm"]), "k": k, "date": d,
                "idio_seam_event": float(ge["idio_seam"]),
                "idio_seam_control": float(gc["idio_seam"]),
                "idio_day_event": float(ge["idio_day"]),
                "idio_day_control": float(gc["idio_day"]),
            })
    if skipped:
        print(f"\nevents skipped: {len(skipped)}")
        for s_ in skipped:
            print("   ", s_)
        pd.DataFrame(skipped, columns=["kind", "date", "cusip", "why"]).to_csv(
            DATA / "seam_monthend_skipped.csv", index=False)

    paths = pd.DataFrame(rows)
    if paths.empty:
        print("no event paths built")
        return 1
    paths["seam_diff"] = paths["idio_seam_event"] - paths["idio_seam_control"]
    paths["day_diff"] = paths["idio_day_event"] - paths["idio_day_control"]
    paths.to_csv(DATA / "seam_monthend_event_paths.csv", index=False)

    n_ev = paths.groupby("kind")[["event_date"]].nunique()
    gap = (paths["ttm_event"] - paths["ttm_control"]).abs()
    print(f"\nevents with a complete path: "
          f"{paths.groupby('kind')['cusip'].nunique().to_dict()} bonds / "
          f"{n_ev['event_date'].to_dict()} dates")
    print(f"maturity match: median |ttm gap| = {gap.median():.3f} y, "
          f"mean {gap.mean():.3f} y, p90 {gap.quantile(0.9):.3f} y", flush=True)

    idio_sd = float(seam_obs["idio_seam"].std())
    out = []
    for kind, g in paths.groupby("kind"):
        for k, gk in g.groupby("k"):
            for col, lbl in (("seam_diff", "15:00->16:00 idio"),
                             ("day_diff", "16:00->next 16:00 idio")):
                v = gk[col].dropna()
                m, sd = float(v.mean()), float(v.std())
                se = sd / np.sqrt(max(1, len(v)))
                out.append({"kind": kind, "k": int(k), "measure": lbl, "n": len(v),
                            "mean_diff_bp": m, "sd_bp": sd, "se_bp": se,
                            "t": m / se if se > 0 else np.nan,
                            "mde_at_t2_bp": 2 * se,
                            "abs_vs_fly_cost": abs(m) / FLY_ROUND_TRIP_BP,
                            "mde_vs_fly_cost": 2 * se / FLY_ROUND_TRIP_BP})
                CELLS.append(f"event:{kind}:{k}:{lbl}")
    res = pd.DataFrame(out)
    res.to_csv(DATA / "seam_monthend_event_study.csv", index=False)

    print("\n=== EVENT MINUS NEAREST-MATURITY CONTROL, idiosyncratic move, bp ===")
    for lbl in ("15:00->16:00 idio", "16:00->next 16:00 idio"):
        print(f"\n--- {lbl} ---")
        print(res[res["measure"] == lbl]
              .pivot_table(index="k", columns="kind",
                           values=["n", "mean_diff_bp", "t", "mde_at_t2_bp"])
              .round(4).to_string(), flush=True)

    on_day = res[res["k"] == 0]
    print("\n=== ON THE RECONSTITUTION DATE ITSELF (k = 0) ===")
    print(on_day.round(5).to_string(index=False), flush=True)
    print(f"\nPOWER: pooled idiosyncratic seam sd = {idio_sd:.4f} bp. The smallest "
          f"event-vs-control effect reaching |t|=2 at k=0 is "
          f"{on_day['mde_at_t2_bp'].min():.4f}-{on_day['mde_at_t2_bp'].max():.4f} bp "
          f"= {on_day['mde_vs_fly_cost'].min():.3f}-"
          f"{on_day['mde_vs_fly_cost'].max():.3f}x the 0.535 bp round trip. Even a "
          f"maximally detectable effect here is not tradeable.", flush=True)

    cum = (paths.groupby(["kind", "event_date", "cusip"])
                .agg(seam_sum=("seam_diff", "sum"), day_sum=("day_diff", "sum"),
                     n_k=("k", "size")).reset_index())
    cs = cum.groupby("kind").agg(events=("seam_sum", "size"),
                                 mean_seam_sum_bp=("seam_sum", "mean"),
                                 sd=("seam_sum", "std"),
                                 mean_day_sum_bp=("day_sum", "mean"))
    cs["se"] = cs["sd"] / np.sqrt(cs["events"])
    cs["t"] = cs["mean_seam_sum_bp"] / cs["se"]
    cs["abs_vs_fly_cost"] = cs["mean_seam_sum_bp"].abs() / FLY_ROUND_TRIP_BP
    cs["mde_at_t2_vs_cost"] = 2 * cs["se"] / FLY_ROUND_TRIP_BP
    print("\n=== CUMULATIVE SEAM OVER k = -5..+5 (11 seams, one per day) ===")
    print(cs.round(5).to_string(), flush=True)
    cs.to_csv(DATA / "seam_monthend_cumulative.csv")
    CELLS.extend(f"event_cum:{k}" for k in cs.index)

    print(f"\nCELLS EVALUATED IN THIS SCRIPT: {len(CELLS)}")
    pd.Series(CELLS, name="cell").to_csv(DATA / "seam_cells_monthend.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

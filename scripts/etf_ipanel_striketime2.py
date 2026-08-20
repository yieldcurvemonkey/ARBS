r"""The strike-time identification, done over a FULL two-day segment chain.

What was wrong with the one-day version
---------------------------------------
``etf_ipanel_striketime.py`` regressed FedInvest's day-over-day change on the overnight
move plus day *t*'s intraday segments. But if FedInvest is struck at ``T``, then

    d(fed)_t  =  [ everything from T on day t-1 to T on day t ]

and that window starts in the AFTERNOON OF DAY t-1, which the one-day regression has no
regressor for. Those omitted segments are ~serially uncorrelated with day *t*'s, so the
coefficients were approximately unbiased -- the cliff it found is real -- but they were
sitting in the error term, which is exactly why its R2 was stuck at 0.35 on two sources
that agree on the cross-section to a correlation of 0.99. A capped R2 on a test whose
whole logic is "which segments are inside the window" is a warning, not a footnote.

The two-day chain
-----------------
Regressors are one unbroken chain of returns:

    [day t-1: 09:30->10:00 ... 16:15->17:00]  [overnight]  [day t: 09:30->10:00 ... ]

and the prediction is a STEP FUNCTION with the step at the strike:

* day t-1 segments AFTER the strike  -> coefficient 1   (they are in fed_t, not fed_{t-1})
* the overnight                       -> coefficient 1
* day t segments BEFORE the strike    -> coefficient 1
* day t-1 segments BEFORE the strike  -> coefficient 0   (in both marks; they cancel)
* day t segments AFTER the strike     -> coefficient 0   (in neither mark yet)

So the strike is identified TWICE from opposite directions in a single regression, and
the R2 now has a chance to reach where two agreeing sources should put it. A pattern
that is a step in one half and not the other would mean the model is wrong, which the
one-day version could not have detected.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import intraday as ID  # noqa: E402
from RVUtils.ETFRebalance import intraday_panel as IP  # noqa: E402
from scripts.etf_ipanel_striketime import ols_cluster  # noqa: E402

DATA = IP.DATA


def two_day_test(marks: pd.DataFrame, fed: pd.DataFrame, times: list[str],
                 label: str) -> tuple[pd.DataFrame, dict]:
    w = marks.pivot_table(index=["date", "cusip"], columns="mark_time", values="ytm")
    w = w[[t for t in times if t in w.columns]].dropna()
    w = w.join(fed.set_index(["date", "cusip"])["ytm_fed"], how="inner").dropna()
    w = w.reset_index().sort_values(["cusip", "date"])
    cols = [t for t in times if t in w.columns]

    g = w.groupby("cusip")
    prev = g[cols + ["ytm_fed"]].shift(1)
    prev_date = g["date"].shift(1)
    has_prev = prev_date.notna()
    gap = np.full(len(w), -1, dtype=int)
    gap[has_prev.to_numpy()] = np.busday_count(
        prev_date[has_prev].values.astype("datetime64[D]"),
        w.loc[has_prev.to_numpy(), "date"].values.astype("datetime64[D]"))
    ok = pd.Series(gap == 1, index=w.index) & has_prev

    segs: dict[str, pd.Series] = {}
    for a, b in zip(cols[:-1], cols[1:]):
        segs[f"t-1 {a}->{b}"] = (prev[b] - prev[a]) * 100.0
    segs["overnight"] = (w[cols[0]] - prev[cols[-1]]) * 100.0
    for a, b in zip(cols[:-1], cols[1:]):
        segs[f"t   {a}->{b}"] = (w[b] - w[a]) * 100.0

    S = pd.DataFrame(segs)
    y = (w["ytm_fed"] - prev["ytm_fed"]) * 100.0
    keep = ok & y.notna() & S.notna().all(axis=1)
    S, y, dates = S[keep], y[keep], w.loc[keep, "date"]

    # a sanity number the one-day version never printed: how well does the WHOLE
    # two-day chain span FedInvest's change at all?
    full = S.sum(axis=1)
    diag = {"corr_fed_vs_full_chain": float(np.corrcoef(
        y.groupby(dates.values).mean(), full.groupby(dates.values).mean())[0, 1])}

    rows = []
    lvl, ylvl = S.groupby(dates.values).mean(), y.groupby(dates.values).mean()
    b, se, r2 = ols_cluster(ylvl.to_numpy(), lvl.to_numpy())
    for name, coef, s in zip(["const"] + list(S.columns), b, se):
        rows.append({"layer": label, "spec": "level", "term": name, "coef": coef,
                     "se": s, "t": coef / s if s > 0 else np.nan,
                     "n": len(ylvl), "r2": r2})
    b, se, r2 = ols_cluster(y.to_numpy(), S.to_numpy(), dates.to_numpy())
    for name, coef, s in zip(["const"] + list(S.columns), b, se):
        rows.append({"layer": label, "spec": "pooled (date-clustered)", "term": name,
                     "coef": coef, "se": s, "t": coef / s if s > 0 else np.nan,
                     "n": len(y), "r2": r2})
    return pd.DataFrame(rows), diag


def main() -> int:
    pd.set_option("display.width", 240)

    p = IP.load_panel("MI01")
    d = BP.load()
    d = d[d["cusip"].isin(set(p["cusip"])) & d["ytm"].notna() & d["price_source"].eq("mid")]
    fed = d[["date", "cusip", "ytm"]].rename(columns={"ytm": "ytm_fed"})

    m = p[p["is_fresh"] & p["ytm"].notna()][["date", "cusip", "mark_time", "ytm"]]
    t1, d1 = two_day_test(m, fed, list(IP.MARK_TIMES), "MI01 (11 marks, 2021-2026)")

    uni = ID.universe()
    meta = uni[["isin", "cusip"]]
    frame = ID.drop_impossible(ID.hourly_frame("YIELD"), "YIELD")
    hrs = []
    for hour in range(9, 18):
        sub = ID.ny_marks(frame, hour)
        long = sub.stack().rename("ytm").reset_index()
        long.columns = ["date", "isin", "ytm"]
        long = long.merge(meta, on="isin", how="left")
        long["mark_time"] = f"{hour:02d}:00"
        hrs.append(long[["date", "cusip", "mark_time", "ytm"]])
    hm = pd.concat(hrs, ignore_index=True).dropna()
    t2, d2 = two_day_test(hm, fed, [f"{h:02d}:00" for h in range(9, 18)],
                          "HOURLY (9 marks, 7y)")

    tab = pd.concat([t1, t2], ignore_index=True)
    print("TWO-DAY SEGMENT CHAIN -- coefficient 1 = this slice is inside FedInvest's "
          "day, 0 = it is not\n")
    for (layer, spec), g in tab.groupby(["layer", "spec"], sort=False):
        print(f"--- {layer} | {spec} | n={int(g['n'].iloc[0]):,}  "
              f"R2={g['r2'].iloc[0]:.4f}")
        print(g[g["term"].ne("const")][["term", "coef", "se", "t"]]
              .round(3).to_string(index=False))
        print()
    print(f"corr(d fed, whole two-day chain): MI01 {d1['corr_fed_vs_full_chain']:.4f}   "
          f"HOURLY {d2['corr_fed_vs_full_chain']:.4f}")
    tab.to_csv(DATA / "ipanel_striketime_twoday.csv", index=False)

    # ------------------------------------------------------ where is the step?
    # Read the strike off the day-t half: the last segment loading materially above
    # half, plus the fraction of the straddling hour that is inside.
    rows = []
    for (layer, spec), g in tab.groupby(["layer", "spec"], sort=False):
        cur = g[g["term"].str.startswith("t   ")]
        prv = g[g["term"].str.startswith("t-1 ")]
        rows.append({
            "layer": layer, "spec": spec, "r2": float(g["r2"].iloc[0]),
            "last_day_t_seg_above_0.5": (cur[cur["coef"] > 0.5]["term"].iloc[-1]
                                         if (cur["coef"] > 0.5).any() else "none"),
            "first_day_tminus1_seg_above_0.5": (prv[prv["coef"] > 0.5]["term"].iloc[0]
                                                if (prv["coef"] > 0.5).any() else "none"),
            "mean_coef_day_t_first3": float(cur["coef"].iloc[:3].mean()),
            "mean_coef_day_t_last4": float(cur["coef"].iloc[-4:].mean()),
            "mean_coef_day_tminus1_last4": float(prv["coef"].iloc[-4:].mean()),
            "mean_coef_day_tminus1_first3": float(prv["coef"].iloc[:3].mean()),
        })
    step = pd.DataFrame(rows)
    print("\nWHERE THE STEP IS:")
    print(step.round(3).to_string(index=False))
    step.to_csv(DATA / "ipanel_striketime_step.csv", index=False)

    # ------------------------------------- repair the Roll file's yield conversion
    rp = DATA / "ipanel_roll_bond_month.csv"
    roll = pd.read_csv(rp)
    if "roll_yield_bp" not in roll.columns:
        roll["month"] = pd.to_datetime(roll["month"])
        p16 = p[p["mark_time"].eq("16:00") & p["is_fresh"]].copy()
        p16["month"] = p16["date"].dt.to_period("M").dt.to_timestamp()
        md = p16.groupby(["cusip", "month"])["mod_dur"].median().rename("mod_dur")
        roll = roll.merge(md, left_on=["cusip", "month"], right_index=True, how="left")
        roll["roll_yield_bp"] = roll["roll_price_bp"] / roll["mod_dur"]
        roll.to_csv(rp, index=False)
        print(f"\nrepaired {rp.name}: mod_dur on {int(roll['mod_dur'].notna().sum()):,}"
              f"/{len(roll):,} rows, roll_yield_bp on "
              f"{int(roll['roll_yield_bp'].notna().sum()):,}")
    print("\nwrote ipanel_striketime_twoday.csv, ipanel_striketime_step.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

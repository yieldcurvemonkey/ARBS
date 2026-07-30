"""The FF oracle ceiling, take two -- with the right degeneracy criterion.

The first pass split structures on "is there an FOMC meeting between the two
delivery-month starts". That is the wrong test and the data said so: the
"no meeting between" spreads moved just as far as the others (sd 9.5bp against
8.8bp). The reason is obvious once stated -- Nov/Dec has no meeting between
1 Nov and 1 Dec, but the December contract is 22/31 exposed to the December
meeting *inside its own month* while November is not exposed at all. The spread
carries most of a meeting.

The right criterion is **differential exposure**: a spread is degenerate only
when its two legs have the *same* exposure vector, i.e. no meeting takes effect
anywhere in ``[start(front), end(back))``. That is what "structurally pinned"
actually means and it is what gets excluded.

This pass also builds the thing the study is actually about: solve the strip for
per-meeting jumps through the exposure matrix and measure the oracle on the
**residual**, which is the FF kink.

Run: conda run -n stir python notebooks/rv/_probe_zq_oracle2.py
"""
import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

pd.set_option("display.width", 250, "display.max_columns", 40)

from RVUtils.MeanRev.diagnostics import move_profile
from RVUtils.MeanRev.ff import ZQ_TICK_BP, delivery_window, zq_exposure_vector
from RVUtils.MeanRev.meetings import fomc_decisions

DATA = REPO / "notebooks" / "data" / "zq_kink_fade"
COST = {"spread": 1.0, "fly": 2.0}


def main() -> int:
    c = pd.read_parquet(DATA / "contracts.parquet")
    c["as_of"] = pd.to_datetime(c["as_of"])
    live = c[~c["accruing"]].copy()
    live["rank"] = live.groupby("as_of")["imm_start"].rank(method="first").astype(int)

    meetings = fomc_decisions(datetime.date(2017, 1, 1), datetime.date(2031, 12, 31))
    codes = sorted(live["code"].unique(), key=lambda k: delivery_window(k)[0])
    win = {k: delivery_window(k) for k in codes}
    # exposure vector per CONTRACT -- a property of the contract, not the date
    exp = {k: zq_exposure_vector(win[k][:2], meetings) for k in codes}

    wide = live.pivot_table(index="as_of", columns="code", values="rate_pct",
                            aggfunc="first").sort_index()
    rank = live.pivot_table(index="as_of", columns="code", values="rank",
                            aggfunc="first").reindex(index=wide.index,
                                                     columns=wide.columns)

    def diff_exposure(legs, weights):
        """Net meeting exposure of the package: max_m |sum_j w_j * W[leg_j, m]|.

        Zero means every meeting loads identically on every leg, so no policy
        decision can move the package at all -- structurally pinned.
        """
        v = sum(w * exp[l] for w, l in zip(weights, legs))
        return float(np.abs(v).max())

    pairs = [(codes[i], codes[i + 1]) for i in range(len(codes) - 1)
             if codes[i] in wide.columns and codes[i + 1] in wide.columns]
    flies = [(codes[i], codes[i + 1], codes[i + 2]) for i in range(len(codes) - 2)
             if all(x in wide.columns for x in codes[i:i + 3])]

    print("=" * 100, flush=True)
    print("DEGENERACY: how many structures carry NO differential meeting exposure?",
          flush=True)
    print("=" * 100, flush=True)
    for name, struct, w in (("M1-M2 spread", pairs, (-1.0, 1.0)),
                            ("3-month fly", flies, (-1.0, 2.0, -1.0))):
        de = pd.Series({"-".join(s): diff_exposure(s, w) for s in struct})
        print(f"\n{name}: {len(de)} structures, differential exposure "
              f"(meetings-equivalent)")
        print(f"  == 0 (pinned): {int((de < 1e-12).sum())}   "
              f"< 0.05: {int((de < 0.05).sum())}   "
              f"median {de.median():.3f}   max {de.max():.3f}")
        print("  quantiles:", de.quantile([0, .1, .25, .5, .75, .9, 1]).round(3).to_dict())

    print("\n" + "=" * 100, flush=True)
    print("ORACLE by differential-exposure bucket (the honest split)", flush=True)
    print("=" * 100, flush=True)
    rows = []
    for name, struct, w, cost in (("M1-M2 spread", pairs, (-1.0, 1.0), COST["spread"]),
                                  ("3-month fly", flies, (-1.0, 2.0, -1.0), COST["fly"])):
        lv, de = {}, {}
        for legs in struct:
            k = "-".join(legs)
            ok = np.ones(len(wide), dtype=bool)
            for l in legs:
                ok &= (rank[l] <= 12).fillna(False).to_numpy()
            lv[k] = (sum(x * wide[l] for x, l in zip(w, legs)) * 100.0).where(ok)
            de[k] = diff_exposure(legs, w)
        lv = pd.DataFrame(lv)
        de = pd.Series(de)
        buckets = pd.cut(de, [-1e-9, 1e-9, 0.2, 0.5, 1.0, 10.0],
                         labels=["pinned (0)", "(0, 0.2]", "(0.2, 0.5]",
                                 "(0.5, 1.0]", "> 1.0"])
        for b in buckets.cat.categories:
            cols = list(de.index[buckets == b])
            if not cols:
                continue
            p = move_profile(lv[cols], None, horizons=(5, 10, 21), round_trip_bp=cost)
            s = lv[cols]
            d = s.diff().stack()
            for _, r in p.iterrows():
                rows.append({
                    "structure": name, "diff_exposure": str(b), "n_keys": len(cols),
                    "cost_bp": cost, "sd_bp": float(s.stack().std()),
                    "sd_ticks": float(s.stack().std() / ZQ_TICK_BP),
                    "pct_unchanged": float((d.abs() < 1e-9).mean()),
                    **{k: r[k] for k in ("horizon", "n", "mean_abs_bp",
                                         "oracle_net_bp", "p_beat_cost")}})
    out = pd.DataFrame(rows)
    print(out.round(3).to_string(index=False), flush=True)
    out.to_csv(DATA / "oracle_by_exposure.csv", index=False)

    # ------------------------------------------------- the meeting residual
    print("\n" + "=" * 100, flush=True)
    print("THE FF KINK: solve the strip for per-meeting jumps, measure the residual",
          flush=True)
    print("=" * 100, flush=True)
    dates = wide.index
    resid = pd.DataFrame(np.nan, index=dates, columns=wide.columns)
    fitted = pd.DataFrame(np.nan, index=dates, columns=wide.columns)
    m_arr = np.array([pd.Timestamp(m) for m in meetings])
    for d in dates:
        row = wide.loc[d].dropna()
        row = row[[k for k in row.index if rank.at[d, k] <= 12]]
        if len(row) < 6:
            continue
        legs = list(row.index)
        lo = min(win[k][0] for k in legs)
        hi = max(win[k][1] for k in legs)
        sel = np.flatnonzero((m_arr >= pd.Timestamp(lo)) & (m_arr < pd.Timestamp(hi)))
        if sel.size == 0:
            continue
        W = np.vstack([exp[k][sel] for k in legs])
        y = row.to_numpy(dtype=float) * 100.0
        X = np.column_stack([np.ones(len(legs)), W])
        # ridge only for conditioning; the FF exposure matrix is nearly
        # triangular so it barely bites
        A = X.T @ X + 1e-6 * np.eye(X.shape[1])
        try:
            beta = np.linalg.solve(A, X.T @ y)
        except np.linalg.LinAlgError:
            continue
        fit = X @ beta
        fitted.loc[d, legs] = fit
        resid.loc[d, legs] = y - fit

    print(f"per-contract residual from the meeting-jump fit (bp):")
    r_by_rank = {}
    for rk in range(1, 13):
        mask = (rank == rk)
        vals = resid.where(mask).stack()
        if len(vals) > 100:
            r_by_rank[rk] = {"n": len(vals), "sd_bp": float(vals.std()),
                             "sd_ticks": float(vals.std() / ZQ_TICK_BP),
                             "mean_bp": float(vals.mean())}
    print(pd.DataFrame(r_by_rank).T.round(3).to_string(), flush=True)

    raw_sd = float(wide.stack().std() * 100.0)
    res_sd = float(resid.stack().std())
    print(f"\n  pooled raw contract rate sd {raw_sd:.1f}bp   "
          f"residual sd {res_sd:.3f}bp   share {res_sd / raw_sd:.4f}")
    print(f"  residual sd in ZQ ticks: {res_sd / ZQ_TICK_BP:.2f}")
    print("\n  The meeting-jump model is an EXACT description of how ZQ settles, so")
    print("  the residual is whatever the market prices that a pure step path")
    print("  cannot express -- intermeeting drift, turn-of-month EFFR, and noise.")

    # oracle on the residual spread/fly
    print("\nORACLE ON THE RESIDUAL STRUCTURES", flush=True)
    rows = []
    for name, struct, w, cost in (("M1-M2 resid spread", pairs, (-1.0, 1.0), COST["spread"]),
                                  ("3-month resid fly", flies, (-1.0, 2.0, -1.0), COST["fly"])):
        lv = {}
        for legs in struct:
            if any(l not in resid.columns for l in legs):
                continue
            ok = np.ones(len(wide), dtype=bool)
            for l in legs:
                ok &= (rank[l] <= 12).fillna(False).to_numpy()
            lv["-".join(legs)] = (sum(x * resid[l] for x, l in zip(w, legs))).where(ok)
        lv = pd.DataFrame(lv)
        p = move_profile(lv, None, horizons=(5, 10, 21), round_trip_bp=cost)
        for _, r in p.iterrows():
            rows.append({"structure": name, "cost_bp": cost,
                         "sd_bp": float(lv.stack().std()), **r.to_dict()})
    rr = pd.DataFrame(rows)
    print(rr[["structure", "cost_bp", "sd_bp", "horizon", "n", "mean_abs_bp",
              "oracle_net_bp", "p_beat_cost"]].round(3).to_string(index=False),
          flush=True)
    rr.to_csv(DATA / "oracle_residual.csv", index=False)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Stage B: the two axes the main grid froze, plus the consolidated league.

Why a second stage rather than one 20,000-cell cartesian product
-----------------------------------------------------------------
The full product of every axis the task names -- column, sign, hold, threshold, exec_lag,
wing offsets, positions, cost -- is about 22,000 configurations at ~2 s each, which is six
hours and, more importantly, a trial count that makes the selection hurdle so high that
nothing could clear it even if something were real. Staging is the standard answer: stage A
sweeps the axes the *hypothesis* is about (which funds, which construction, which bucket
width, which direction, how long to hold, how strong a z to require), stage B sweeps the
axes that are about *implementation* (how far apart the wings sit, how many days after the
file you trade) on the subset stage A identified.

Both stages are counted. ``league`` is recomputed over the union, so the deflated Sharpe
sees stage A + stage B + the IC surface + the parent study's 5,192.

This script also repairs one labelling error in stage A's output
----------------------------------------------------------------
``agg_floattwin__board__*`` is the ownership ladder's NULL TWIN -- the same bucket
construction on the board's own float share, which reads no holdings file at all. Stage A
stamped every attached column ``kind="aggregate"``, which puts a null inside the thesis's
row of the by-kind table and lets "the best aggregate configuration" be a cell that never
touched an ETF. The kind is re-derived here from the construction, the by-kind table is
regenerated, and the headline configuration is re-picked among genuine aggregates only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                      "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ETFRebalance import aggregate as AG  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import grid as GR  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data")
PARENT_TRIALS = 5192
LADDER_TRIALS = 45 * 5 + 39


def banner(s: str) -> None:
    print("\n" + "=" * 100)
    print(s)
    print("=" * 100, flush=True)


def true_kind(row) -> str:
    """The kind a configuration actually is, derived from what it READS.

    ``floattwin`` reads the board's own free float and no holdings file, so it is a null
    however it was built and wherever its column was attached.
    """
    if str(row.get("kind", "")) in ("calendar_null", "matched_placebo"):
        return str(row["kind"])
    return "float_twin_null" if str(row.get("construction", "")) == "floattwin" else "aggregate"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="mi")
    a = ap.parse_args()
    t0 = time.time()

    stage_a = pd.read_csv(os.path.join(DATA_DIR, f"{a.prefix}_grid.csv"))
    stage_a["kind"] = stage_a.apply(true_kind, axis=1)
    stage_a["stage"] = "A"
    #: Stage A's per-trade P&L arrays live in memory, not in its CSV, so the deflated
    #: Sharpe cannot be recomputed for those rows here. Its stored ``dsr`` is kept and
    #: labelled instead. That is not a fudge: DSR is monotone DECREASING in the selection
    #: hurdle, and adding stage B's configurations only raises the hurdle, so a stage A
    #: DSR carried forward is an UPPER BOUND on what it would be under the consolidated
    #: trial count. A row that fails the aliveness test on the upper bound fails it on the
    #: true value, which is the only direction this study needs to be safe in.
    stage_a = stage_a.rename(columns={"dsr": "dsr_stage_a_upper_bound"})
    print(f"stage A: {len(stage_a):,} configurations, re-labelled")
    print(stage_a["kind"].value_counts().to_string())

    banner("STEP 0: rebuild the pinned universe (identical to stage A)")
    panel = FP.asof_join(BP.load(), FP.load())
    cfg0 = EN.merge_config({"fund": "TLT",
                            "universe": {"start": "2016-01-01", "ttm_min": AG.COMMON_BAND[0],
                                         "ttm_max": AG.COMMON_BAND[1]}})
    uni, funnel = EN.prepare_universe(cfg0, panel=panel)
    uni = uni[uni["date"] >= pd.Timestamp("2016-01-01")].reset_index(drop=True)
    built = AG.build_ladders(uni, fund_sets=("tlt_only", "coupon_long", "coupon_long_govt",
                                             "daily_only"),
                             widths=(0.25, 0.5, 1.0), combines=("book", "equal"),
                             verbose=False)
    start = built["ladder_start"]
    U = AG.attach_many(uni, built["specs"])
    U = U[U["date"] >= start].reset_index(drop=True)
    base = {"fund": "TLT",
            "universe": {"start": str(start.date()), "ttm_min": AG.COMMON_BAND[0],
                         "ttm_max": AG.COMMON_BAND[1]},
            "costs": {"basis": "measured", "multiplier": 1.0}, "carry": {"enabled": True}}
    print(f"universe {len(U):,} rows, {U['date'].nunique():,} dates  [{time.time()-t0:.0f}s]")

    banner("STEP 1: stage B -- wing offsets and execution lag")
    #: The subset is chosen on the HYPOTHESIS axes, not on stage A's ranking: both
    #: constructions, the 3-month bucket the request named plus the 1-year control, and
    #: the two fund-set extremes -- so the sweep is not conditioned on which cells
    #: happened to win.
    cols = [AG.column_name("own", fs, w) for fs in ("tlt_only", "coupon_long") for w in (0.25, 1.0)]
    cols += [AG.column_name("act", fs, w, "book")
             for fs in ("tlt_only", "coupon_long") for w in (0.25, 1.0)]
    ovs, axes = [], []
    for col in cols:
        cons, fs, wtail = col.split("__", 2)
        for sign in (1, -1):
            for wg in (0.5, 0.8, 1.5):
                for lag in (1, 2, 5):
                    nm = f"{col}|s{sign:+.0f}|h21|wg{wg}|l{lag}"
                    ovs.append({
                        "name": nm,
                        "signal": {"components": {"precomputed": 1.0}, "z_mode": "raw",
                                   "kwargs": {"precomputed": {"column": col,
                                                              "sign": float(sign)}}},
                        "timing": {"hold_days": 21, "exec_lag": int(lag), "entry_every": 5},
                        "structure": {"min_abs_score": 0.0, "n_positions": 3,
                                      "both_sides": True, "wing_gap_max_y": float(wg)},
                    })
                    axes.append({"name": nm, "kind": "aggregate",
                                 "construction": cons.replace("agg_", ""), "fund_set": fs,
                                 "width_tail": wtail, "sign": sign, "hold_days": 21,
                                 "threshold": 0.0, "exec_lag": lag, "wing_gap_max_y": wg,
                                 "column": col})
    print(f"{len(ovs)} configurations "
          f"({len(cols)} columns x 2 signs x 3 wing gaps x 3 exec lags)")
    stage_b, _ = AG.run_overlays(ovs, base=base, universe=U, funnel=funnel, progress=True)
    stage_b = stage_b.merge(pd.DataFrame(axes), on="name", how="left")
    stage_b["stage"] = "B"

    print("\nexec_lag is a CAUSALITY axis, not a tuning knob -- what does waiting cost?")
    print(stage_b.groupby("exec_lag")[["gross_avg_bp", "avg_bp", "trades"]]
          .mean().round(5).to_string())
    print("\nwing gap (max years between belly and wing):")
    print(stage_b.groupby("wing_gap_max_y")[["gross_avg_bp", "cost_avg_bp", "avg_bp"]]
          .mean().round(5).to_string())

    banner("STEP 2: the consolidated league over BOTH stages")
    both = pd.concat([stage_a, stage_b], ignore_index=True)
    extra = PARENT_TRIALS + LADDER_TRIALS
    lg = GR.league(both, extra_trials=extra, min_trades=30, rank_on="sr_per_trade")
    sr_star = float(lg["sr_star"].iloc[0])
    lg = GR.attach_dsr_from_pnl(lg, sr_star=sr_star)
    #: stage B rows get a freshly computed DSR; stage A rows keep their upper bound.
    lg["dsr"] = lg["dsr"].fillna(lg["dsr_stage_a_upper_bound"])
    lg["dsr_basis"] = np.where(lg["stage"].eq("B"), "recomputed", "stage-A upper bound")
    print(f"  configurations with >=30 trades : {len(lg):,}  "
          f"(stage A {int((lg['stage']=='A').sum()):,} + stage B {int((lg['stage']=='B').sum()):,})")
    print(f"  trials counted                  : {int(lg['n_trials_counted'].iloc[0]):,}")
    print(f"  E[max Sharpe | null] per trade  : {sr_star:.4f}")
    print(f"  best observed per trade         : {lg['sr_per_trade'].max():.4f}")
    alive = GR.alive(lg, dsr_min=0.95, min_trades=50, require_positive_net=True)
    print(f"\n  ALIVE (DSR>0.95, >=50 trades, net>0): {len(alive):,} of {len(lg):,}")
    lg.drop(columns=["_pnl"], errors="ignore").to_csv(
        os.path.join(DATA_DIR, f"{a.prefix}_grid_all.csv"), index=False)

    banner("STEP 3: by kind, with the float twin OUT of the thesis row")
    summ = lg.groupby("kind").agg(
        n=("name", "size"),
        best_gross_bp=("gross_avg_bp", "max"), med_gross_bp=("gross_avg_bp", "median"),
        best_net_bp=("avg_bp", "max"), best_sr_trade=("sr_per_trade", "max"),
        best_dsr=("dsr", "max"), best_breakeven_mult=("breakeven_cost_mult", "max"),
        n_gross_above_cost=("breakeven_cost_mult", lambda s: int((s > 1.0).sum())),
    ).reset_index()
    print(summ.round(5).to_string(index=False))
    summ.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_by_kind.csv"), index=False)

    banner("STEP 4: THE COMPARISON -- aggregate vs single fund, matched cell by cell")
    agg = lg[lg["kind"] == "aggregate"].copy()
    agg["cell"] = (agg["stage"].astype(str) + "|" + agg["construction"] + "|"
                   + agg["width_tail"] + "|s" + agg["sign"].astype(int).astype(str)
                   + "|h" + agg["hold_days"].astype(int).astype(str)
                   + "|t" + agg["threshold"].astype(str)
                   + "|l" + agg["exec_lag"].astype(int).astype(str)
                   + "|wg" + agg.get("wing_gap_max_y", pd.Series(index=agg.index)).astype(str))
    piv_g = agg.pivot_table(index="cell", columns="fund_set", values="gross_avg_bp")
    piv_n = agg.pivot_table(index="cell", columns="fund_set", values="avg_bp")
    rows = []
    for fs in ("coupon_long", "coupon_long_govt", "daily_only"):
        if fs not in piv_g.columns:
            continue
        d = (piv_g[fs] - piv_g["tlt_only"]).dropna()
        dn = (piv_n[fs] - piv_n["tlt_only"]).dropna()
        if not len(d):
            continue
        rows.append({
            "fund_set": fs, "n_matched_cells": len(d),
            "gross_delta_mean_bp": float(d.mean()), "gross_delta_med_bp": float(d.median()),
            "gross_win_rate": float((d > 0).mean()),
            "gross_delta_t": float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d))))
            if len(d) > 2 and d.std(ddof=1) > 0 else np.nan,
            "net_delta_mean_bp": float(dn.mean()), "net_win_rate": float((dn > 0).mean()),
        })
    comp = pd.DataFrame(rows)
    print("PAIRED difference vs the SAME cell run on TLT alone (bp per trade):")
    print(comp.round(5).to_string(index=False))
    comp.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_aggregate_vs_single.csv"), index=False)

    banner("STEP 5: the headline configuration -- best GENUINE aggregate by Sharpe")
    genuine = lg[(lg["kind"] == "aggregate") & (lg["trades"] >= 50)]
    best = genuine.sort_values("sr_per_trade", ascending=False).iloc[0]
    ovb = json.loads(best["config"])
    res = EN.run_config({**base, **ovb}, universe=U, prepared_funnel=funnel)
    perm = GR.sign_flip_permutation(res.closed["gross_bp"].to_numpy(float), n_perm=5000)
    print(f"  name                  : {best['name']}")
    print(f"  fund set              : {best['fund_set']}  construction {best['construction']}")
    print(f"  trades                : {len(res.closed)}")
    print(f"  gross bp/trade        : {res.closed['gross_bp'].mean():+.4f}")
    print(f"  cost  bp/trade        : {res.closed['cost_bp'].mean():.4f}")
    print(f"  net   bp/trade        : {res.closed['pnl_bp'].mean():+.4f}")
    print(f"  break-even cost mult  : {res.closed['gross_bp'].mean()/res.closed['cost_bp'].mean():.4f}")
    print(f"  Sharpe/trade          : {perm['realized_sharpe']:+.4f}  "
          f"vs hurdle {sr_star:.4f}")
    print(f"  sign-flip null        : {perm['perm_mean']:+.4f} +/- {perm['perm_std']:.4f}, "
          f"p = {perm['p_value']:.4f}")
    print(f"  DSR                   : {best.get('dsr', np.nan)}")

    pd.DataFrame([{
        "name": best["name"], "kind": best["kind"], "fund_set": best["fund_set"],
        "construction": best["construction"], "trades": len(res.closed),
        "gross_bp": float(res.closed["gross_bp"].mean()),
        "cost_bp": float(res.closed["cost_bp"].mean()),
        "net_bp": float(res.closed["pnl_bp"].mean()),
        "breakeven_cost_mult": float(res.closed["gross_bp"].mean()
                                     / res.closed["cost_bp"].mean()),
        "sr_realized": perm["realized_sharpe"], "perm_mean": perm["perm_mean"],
        "perm_std": perm["perm_std"], "p_value": perm["p_value"],
        "sr_star": sr_star, "dsr": float(best.get("dsr", np.nan)),
        "n_trials_counted": int(lg["n_trials_counted"].iloc[0]),
    }]).to_csv(os.path.join(DATA_DIR, f"{a.prefix}_best_permutation.csv"), index=False)
    res.closed.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_best_trades.csv"), index=False)
    res.daily.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_best_daily.csv"), index=False)
    res.legs.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_best_legs.csv"), index=False)

    banner("STEP 6: the same cell on TLT alone -- the like-for-like curve")
    ov_tlt = json.loads(best["config"])
    col = ov_tlt["signal"]["kwargs"]["precomputed"]["column"]
    cons, fs, wtail = col.split("__", 2)
    tlt_col = "__".join([cons, "tlt_only", wtail])
    if tlt_col in U.columns and fs != "tlt_only":
        ov_tlt = json.loads(json.dumps(ov_tlt))
        ov_tlt["signal"]["kwargs"]["precomputed"]["column"] = tlt_col
        ov_tlt["name"] = best["name"].replace(fs, "tlt_only")
        res_t = EN.run_config({**base, **ov_tlt}, universe=U, prepared_funnel=funnel)
        print(f"  aggregate : {len(res.closed):4d} trades  gross "
              f"{res.closed['gross_bp'].mean():+.4f}  net {res.closed['pnl_bp'].mean():+.4f}")
        print(f"  TLT only  : {len(res_t.closed):4d} trades  gross "
              f"{res_t.closed['gross_bp'].mean():+.4f}  net {res_t.closed['pnl_bp'].mean():+.4f}")
        res_t.daily.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_best_daily_tltonly.csv"),
                           index=False)
    else:
        print(f"  headline cell is already TLT-only ({col}); no counterpart to draw.")
        res.daily.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_best_daily_tltonly.csv"),
                         index=False)

    print(f"\nALL DONE [{(time.time()-t0)/60:.1f} min]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The grid: aggregate ladder vs TLT-only, same dates, same costs, same pipeline.

The headline this produces is NOT the aggregate's best Sharpe. It is the difference
between the aggregate and the single fund, run through one pipeline on one date axis --
anything else is not a comparison. So ``fund_set`` is an axis of the grid rather than a
separate run, and the two nulls the parent study established (the calendar-only signal
and the matched-rarity placebo) are cells of the same grid rather than a separate table.

Three things that are load-bearing rather than stylistic
--------------------------------------------------------
**The universe is prepared ONCE and pinned.** ``grid.run_grid`` rebuilds it per cache key
with ``prepare_universe``, which would discard every attached aggregate column. This uses
``aggregate.run_overlays``, which is the same loop with the rebuild removed.

**``exec_lag >= 1``, always.** Never zero, in any cell. The parent study measured that the
lookahead is worth 0.0011bp, i.e. nothing -- but a cell with a lookahead in a grid this
size is a cell that can win on it.

**The trial count is the whole research programme, not this table.** The deflated Sharpe
is only honest if it is told how many configurations were looked at anywhere, so
``extra_trials`` carries the parent study's 5,192 plus this script's own IC surface.
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
from RVUtils.ETFRebalance import costs as C  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import grid as GR  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 300)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data")
os.makedirs(DATA_DIR, exist_ok=True)

FUND_SETS = ("tlt_only", "coupon_long", "coupon_long_govt", "daily_only")
WIDTHS = (0.25, 0.5, 1.0)
COMBINES = ("book", "equal")

#: The parent study's own configuration count, from RESULTS.md: 5,192 across four grids.
#: Same research programme, same selection, so it is part of this DSR's denominator.
PARENT_TRIALS = 5192
#: This script's siblings: the IC surface (45 signals x 5 horizons) and the long-short
#: table (39 rows) in ``_run_multi_issuer_ladder.py``.
LADDER_TRIALS = 45 * 5 + 39

#: The parent study's measured full-sample butterfly round trip, in yield bp. Carried as a
#: constant so every chart can mark the same line and the two studies are commensurable.
MEASURED_RT_BP_FULL_SAMPLE = 0.535


def banner(s: str) -> None:
    print("\n" + "=" * 100)
    print(s)
    print("=" * 100, flush=True)


def signal_overlays(specs, *, holds, thresholds, signs, exec_lags):
    """One overlay per (aggregate column, sign, hold, threshold, exec_lag)."""
    out = []
    for col in sorted(specs):
        cons, fs, wtail = col.split("__", 2)
        #: ``floattwin`` is the ownership ladder's NULL twin -- the same bucket
        #: construction on the board's own float share, which reads no holdings file at
        #: all. Labelling it "aggregate" would put a null inside the thesis's row of the
        #: by-kind table and let "the best aggregate configuration" be a cell that never
        #: touched an ETF. That is precisely the labelling error this study exists to
        #: avoid, so the kind is derived from the construction rather than from where the
        #: column happened to be built.
        kind = "float_twin_null" if cons.endswith("floattwin") else "aggregate"
        for sign in signs:
            for hold in holds:
                for thr in thresholds:
                    for lag in exec_lags:
                        out.append({
                            "name": f"{col}|s{sign:+.0f}|h{hold}|t{thr}|l{lag}",
                            "signal": {"components": {"precomputed": 1.0},
                                       "z_mode": "raw",
                                       "kwargs": {"precomputed": {"column": col,
                                                                  "sign": float(sign)}}},
                            "timing": {"hold_days": int(hold), "exec_lag": int(lag),
                                       "entry_every": 5},
                            "structure": {"min_abs_score": float(thr), "n_positions": 3,
                                          "both_sides": True},
                            "_axes": {"kind": kind, "construction": cons.replace("agg_", ""),
                                      "fund_set": fs, "width_tail": wtail, "sign": sign,
                                      "hold_days": hold, "threshold": thr, "exec_lag": lag,
                                      "column": col},
                        })
    return out


def null_overlays(*, holds, signs, exec_lags, band_low):
    """The two nulls, as cells of the SAME grid.

    ``deletion`` is the calendar-only null: it reads no holdings file at all, so if it
    earns what the aggregate earns then the scrape and the EDGAR backfill bought nothing.
    ``crossing`` at 22/24/26/28 years is the matched-rarity placebo: the same event shape
    and the same firing rate at maturities where no index does anything. The parent study
    found the placebo beat the real boundary (|t| 2.74 against 2.40), so carrying it here
    from the start is the only way the calendar result can be read.

    These run in ``cross_section`` z-mode because they are not pre-standardised, so their
    thresholds are not in the same units as the aggregate's -- which is why they are run at
    threshold 0 only and compared on P&L rather than on threshold behaviour.
    """
    out = []
    variants = [("deletion", {"band_low": float(band_low), "horizon_m": 3})]
    variants += [(f"crossing{b:.0f}", {"boundary": float(b), "horizon_m": 3})
                 for b in (22.0, 24.0, 26.0, 28.0)]
    for label, kw in variants:
        base_name = "deletion" if label == "deletion" else "crossing"
        for sign in signs:
            for hold in holds:
                for lag in exec_lags:
                    out.append({
                        "name": f"NULL_{label}|s{sign:+.0f}|h{hold}|l{lag}",
                        "signal": {"components": {base_name: float(sign)},
                                   "z_mode": "cross_section",
                                   "kwargs": {base_name: kw}},
                        "timing": {"hold_days": int(hold), "exec_lag": int(lag),
                                   "entry_every": 5},
                        "structure": {"min_abs_score": 0.0, "n_positions": 3,
                                      "both_sides": True},
                        "_axes": {"kind": "calendar_null" if label == "deletion"
                                  else "matched_placebo",
                                  "construction": label, "fund_set": "none",
                                  "width_tail": "", "sign": sign, "hold_days": hold,
                                  "threshold": 0.0, "exec_lag": lag, "column": label},
                    })
    return out


def strip_axes(overlays):
    """Split the bookkeeping off the config -- ``merge_config`` must not see ``_axes``."""
    axes, clean = [], []
    for ov in overlays:
        o = dict(ov)
        ax = o.pop("_axes", {})
        ax["name"] = o["name"]
        axes.append(ax)
        clean.append(o)
    return clean, pd.DataFrame(axes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--prefix", default="mi")
    ap.add_argument("--quick", action="store_true",
                    help="one width and one hold, for a wiring check")
    a = ap.parse_args()
    t0 = time.time()

    banner("STEP 0: universe + ladders (identical to the ladder script)")
    panel = FP.asof_join(BP.load(), FP.load())
    cfg0 = EN.merge_config({"fund": "TLT",
                            "universe": {"start": a.start, "ttm_min": AG.COMMON_BAND[0],
                                         "ttm_max": AG.COMMON_BAND[1]}})
    uni, funnel = EN.prepare_universe(cfg0, panel=panel)
    uni = uni[uni["date"] >= pd.Timestamp(a.start)].reset_index(drop=True)

    widths = (0.25,) if a.quick else WIDTHS
    built = AG.build_ladders(uni, fund_sets=FUND_SETS, widths=widths,
                             combines=COMBINES, verbose=False)
    start = built["ladder_start"]
    uni2 = AG.attach_many(uni, built["specs"])
    uni2 = uni2[uni2["date"] >= start].reset_index(drop=True)
    print(f"ladder start {start.date()}  |  universe {len(uni2):,} rows, "
          f"{uni2['date'].nunique():,} dates, {uni2['cusip'].nunique()} cusips  "
          f"[{time.time()-t0:.0f}s]")

    banner("STEP 0b: the cost wall, stated BEFORE any P&L")
    cm = C.CostModel(basis="measured", multiplier=1.0)
    leg = cm.leg_round_trip_yield_bp(uni2)
    rt = 2.0 * float(leg.median())
    disp = float(uni2.groupby("date")["resid_bp"].std().median())
    print(f"  measured leg round trip (median)      {leg.median():.4f} yield bp")
    print(f"  3-leg DV01-neutral fly round trip     {rt:.4f} yield bp  "
          f"(parent full-sample figure {MEASURED_RT_BP_FULL_SAMPLE:.3f})")
    print(f"  median cross-sectional dispersion     {disp:.4f} bp")
    print(f"  the ENTIRE dispersion is              {disp/rt:.2f}x one round trip")
    print("  -> a signal has to explain more than all of the cross-sectional dispersion "
          "to break even.")

    base = {
        "fund": "TLT",
        "universe": {"start": str(start.date()), "ttm_min": AG.COMMON_BAND[0],
                     "ttm_max": AG.COMMON_BAND[1]},
        "costs": {"basis": "measured", "multiplier": 1.0},
        "carry": {"enabled": True},
    }

    holds = (21,) if a.quick else (5, 10, 21, 42)
    thresholds = (0.0,) if a.quick else (0.0, 1.0, 1.5)
    signs = (1, -1)
    exec_lags = (1,)

    banner("STEP 1: the main grid")
    ovs = signal_overlays(built["specs"], holds=holds, thresholds=thresholds,
                          signs=signs, exec_lags=exec_lags)
    ovs += null_overlays(holds=holds, signs=signs, exec_lags=exec_lags,
                         band_low=AG.COMMON_BAND[0])
    clean, axes = strip_axes(ovs)
    print(f"{len(clean):,} configurations "
          f"({len(built['specs'])} columns x {len(signs)} signs x {len(holds)} holds x "
          f"{len(thresholds)} thresholds, + {len(clean) - len(built['specs'])*len(signs)*len(holds)*len(thresholds)} nulls)")

    league_raw, _ = AG.run_overlays(clean, base=base, universe=uni2, funnel=funnel,
                                    progress=True)
    league_raw = league_raw.merge(axes, on="name", how="left")
    print(f"\ndone [{time.time()-t0:.0f}s]; "
          f"{int(league_raw['trades'].fillna(0).gt(0).sum())} configs produced trades, "
          f"{int(league_raw.get('error', pd.Series(dtype=object)).notna().sum())} errored")

    banner("STEP 2: the selection hurdle and the deflated Sharpe")
    extra = PARENT_TRIALS + LADDER_TRIALS
    lg = GR.league(league_raw, extra_trials=extra, min_trades=30, rank_on="sr_per_trade")
    sr_star = float(lg["sr_star"].iloc[0]) if len(lg) else np.nan
    lg = GR.attach_dsr_from_pnl(lg, sr_star=sr_star)
    print(f"  rows with >=30 trades : {len(lg):,}")
    print(f"  trials counted        : {int(lg['n_trials_counted'].iloc[0]):,} "
          f"({len(lg):,} here + {extra:,} elsewhere: {PARENT_TRIALS:,} parent + "
          f"{LADDER_TRIALS} IC/long-short)")
    print(f"  E[max Sharpe | null]  : {sr_star:.4f} per trade")
    print(f"  best observed         : {lg['sr_per_trade'].max():.4f} per trade")

    aliveness = GR.alive(lg, dsr_min=0.95, min_trades=50, require_positive_net=True)
    print(f"\n  ALIVE (DSR>0.95, >=50 trades, net>0): {len(aliveness):,} of {len(lg):,}")
    if len(aliveness):
        print(aliveness.head(25)[["name", "trades", "avg_bp", "gross_avg_bp", "cost_avg_bp",
                                  "sr_per_trade", "dsr", "kind", "fund_set"]]
              .round(4).to_string(index=False))

    out = lg.drop(columns=["_pnl"], errors="ignore")
    out.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_grid.csv"), index=False)
    print(f"\nwrote {a.prefix}_grid.csv ({len(out):,} rows)")

    banner("STEP 3: THE COMPARISON -- aggregate vs single fund, matched cell by cell")
    #: Not "best vs best". Every non-fund-set axis is held fixed and only the fund set
    #: changes, so the difference is the fund set and nothing else. Best-vs-best would
    #: compare two different searches.
    agg = lg[lg["kind"] == "aggregate"].copy()
    agg["cell"] = (agg["construction"] + "|" + agg["width_tail"] + "|s"
                   + agg["sign"].astype(int).astype(str) + "|h"
                   + agg["hold_days"].astype(int).astype(str) + "|t"
                   + agg["threshold"].astype(str))
    piv = agg.pivot_table(index="cell", columns="fund_set", values="gross_avg_bp")
    piv_net = agg.pivot_table(index="cell", columns="fund_set", values="avg_bp")
    both = piv.dropna(subset=["tlt_only"], how="any")
    rows = []
    for fs in ("coupon_long", "coupon_long_govt", "daily_only"):
        if fs not in both.columns:
            continue
        d = (both[fs] - both["tlt_only"]).dropna()
        dn = (piv_net[fs] - piv_net["tlt_only"]).dropna()
        rows.append({
            "fund_set": fs, "n_matched_cells": len(d),
            "gross_delta_mean_bp": float(d.mean()), "gross_delta_med_bp": float(d.median()),
            "gross_wins": int((d > 0).sum()), "gross_win_rate": float((d > 0).mean()),
            "gross_delta_t": float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d))))
            if len(d) > 2 and d.std(ddof=1) > 0 else np.nan,
            "net_delta_mean_bp": float(dn.mean()),
            "net_wins": int((dn > 0).sum()), "net_win_rate": float((dn > 0).mean()),
        })
    comp = pd.DataFrame(rows)
    print("PAIRED difference vs the SAME cell run on TLT alone (bp per trade):")
    print(comp.round(5).to_string(index=False))
    comp.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_aggregate_vs_single.csv"), index=False)

    banner("STEP 4: the nulls, on the same rows")
    summ = lg.groupby("kind").agg(
        n=("name", "size"),
        best_gross_bp=("gross_avg_bp", "max"),
        med_gross_bp=("gross_avg_bp", "median"),
        best_net_bp=("avg_bp", "max"),
        best_sr_trade=("sr_per_trade", "max"),
        best_dsr=("dsr", "max"),
        n_gross_above_cost=("breakeven_cost_mult", lambda s: int((s > 1.0).sum())),
    ).reset_index()
    print(summ.round(5).to_string(index=False))
    summ.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_by_kind.csv"), index=False)

    banner("STEP 5: cost sensitivity -- what multiple of the measured spread breaks even")
    #: Cost as a swept parameter, on the best few configs by GROSS (not by net, which is
    #: what cost is being swept over). ``breakeven_cost_mult`` already answers this
    #: analytically per config; the sweep is here so the notebook can draw the curve and
    #: mark the measured round trip on it.
    top = lg.sort_values("gross_avg_bp", ascending=False).head(8)["config"].tolist()
    sens = []
    for cs in top:
        ov = json.loads(cs)
        for mult in (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0):
            o = dict(ov)
            o["costs"] = {"basis": "measured", "multiplier": float(mult)}
            o["name"] = f"{ov['name']}|c{mult}"
            sens.append(o)
    sens_league, _ = AG.run_overlays(sens, base=base, universe=uni2, funnel=funnel,
                                     progress=True)
    sens_league["cost_mult"] = sens_league["name"].str.rsplit("|c", n=1).str[-1].astype(float)
    sens_league["base_name"] = sens_league["name"].str.rsplit("|c", n=1).str[0]
    print(sens_league.pivot_table(index="base_name", columns="cost_mult", values="avg_bp")
          .round(4).to_string())
    sens_league.drop(columns=["_pnl"], errors="ignore").to_csv(
        os.path.join(DATA_DIR, f"{a.prefix}_cost_sensitivity.csv"), index=False)

    banner("STEP 6: sign-flip permutation on the best config's GROSS P&L")
    best = lg.sort_values("sr_per_trade", ascending=False).iloc[0]
    ovb = json.loads(best["config"])
    res = EN.run_config({**base, **ovb}, universe=uni2, prepared_funnel=funnel)
    perm = GR.sign_flip_permutation(res.closed["gross_bp"].to_numpy(float), n_perm=5000)
    print(f"  best config           : {best['name']}")
    print(f"  trades                : {len(res.closed)}")
    print(f"  gross bp/trade        : {res.closed['gross_bp'].mean():+.4f}")
    print(f"  cost bp/trade         : {res.closed['cost_bp'].mean():.4f}")
    print(f"  net bp/trade          : {res.closed['pnl_bp'].mean():+.4f}")
    print(f"  realised Sharpe/trade : {perm['realized_sharpe']:+.4f}")
    print(f"  permutation null      : {perm['perm_mean']:+.4f} +/- {perm['perm_std']:.4f}")
    print(f"  p-value               : {perm['p_value']:.4f}")
    pd.DataFrame([{
        "name": best["name"], "trades": len(res.closed),
        "gross_bp": float(res.closed["gross_bp"].mean()),
        "cost_bp": float(res.closed["cost_bp"].mean()),
        "net_bp": float(res.closed["pnl_bp"].mean()),
        "sr_realized": perm["realized_sharpe"], "perm_mean": perm["perm_mean"],
        "perm_std": perm["perm_std"], "p_value": perm["p_value"],
        "sr_star": sr_star, "dsr": float(best.get("dsr", np.nan)),
    }]).to_csv(os.path.join(DATA_DIR, f"{a.prefix}_best_permutation.csv"), index=False)

    res.closed.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_best_trades.csv"), index=False)
    res.daily.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_best_daily.csv"), index=False)
    res.legs.to_csv(os.path.join(DATA_DIR, f"{a.prefix}_best_legs.csv"), index=False)

    print(f"\nALL DONE [{time.time()-t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

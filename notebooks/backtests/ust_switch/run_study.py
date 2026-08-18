"""Run the olds-vs-currents switch study end to end and persist every artefact.

Order of operations, and why it is not the obvious one:

    coverage  ->  raw object  ->  ONE hand-reconciled trade  ->  baseline  ->  grid
    ->  placebo  ->  deflation  ->  cost curve  ->  seasonality

The raw object (yield pickup by rank) comes before any trading rule, because if the
on-the-run premium does not exist there is nothing for a configuration to find and a grid
run first would only tell us which noise it liked. The single reconciled trade comes before
the grid for the same reason in the other direction: a grid of 500 wrong numbers looks
exactly like a grid of 500 right ones.

Deflation counts EVERY configuration evaluated, including placebos and controls.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from RVUtils.USTSwitch import analytics as A  # noqa: E402
from RVUtils.USTSwitch import grid as G  # noqa: E402
from RVUtils.USTSwitch.costs import CostModel, cost_table_summary  # noqa: E402
from RVUtils.USTSwitch.data import coverage_report, load_prepared, select_financing  # noqa: E402
from RVUtils.USTSwitch.engine import SwitchConfig, run_switch  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "_out"
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)


def hdr(s: str) -> None:
    print("\n" + "=" * 88)
    print(s)
    print("=" * 88)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--financing", default="modelled", choices=["actual", "modelled", "none"])
    ap.add_argument("--quick", action="store_true", help="small axes, for a smoke run")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    panel, amap = load_prepared(rebuild=a.rebuild)

    # ---------------------------------------------------------------- 1. coverage
    hdr("1. COVERAGE -- what the study can actually see")
    cov = coverage_report(panel)
    print(cov.to_string(index=False))
    cov.to_csv(OUT / "coverage.csv", index=False)
    print(f"\npanel {panel.shape}, {panel['date'].min().date()} .. {panel['date'].max().date()}")
    print(f"rows with MEASURED financing: {panel['has_actual_financing'].mean():.1%} "
          f"(JPM window 2016-08-10 .. 2025-08-26)")

    # ---------------------------------------------------------------- 2. raw object
    hdr("2. THE RAW OBJECT -- yield pickup over the on-the-run, before any trading rule")
    ts = {t: A.spread_term_structure(panel, t) for t in G.TENORS}
    for t, d in ts.items():
        if d is not None and not d.empty:
            row = "  ".join(
                f"rank{int(r.rank)} {r.mean_pickup_bp:+6.3f}bp(sd {r.std_bp:5.2f})"
                for r in d.itertuples()
            )
            print(f"{t:2d}Y  {row}")
    pd.concat({t: d for t, d in ts.items() if d is not None and not d.empty},
              names=["tenor"]).to_csv(OUT / "spread_term_structure.csv")

    hdr("2b. COST -- what a round trip costs, from NY Fed SR1170 Table 3")
    ct = cost_table_summary()
    print(ct.pivot_table(index="tenor", columns="pair", values="rt_cost_bp").round(3).to_string())
    ct.to_csv(OUT / "cost_table.csv", index=False)

    hdr("2c. FINANCING -- measured specialness by tenor and rank")
    sp = (panel[panel["has_actual_financing"]]
          .groupby(["tenor", "rank"])["special_actual_bp"].mean().unstack().round(3))
    print(sp.to_string())
    sp.to_csv(OUT / "specialness_by_rank.csv")

    # ---------------------------------------------------------------- 3. baseline
    hdr("3. BASELINE -- the paper's economics, one config, no search")
    base = SwitchConfig(tenor=10, rank_young=0, rank_old=1, direction=1,
                        entry_offset=1, exit_rule="next_roll", exit_offset=1,
                        financing_mode=a.financing)
    p_fin = select_financing(panel, a.financing)
    res = run_switch(p_fin, amap, base, cost_model=CostModel())
    print(f"funnel: {res.funnel}")
    if not res.trades.empty:
        print(A.pnl_decomposition(res).to_string(index=False))
        s = A.summarize_switch(res)
        for k in ("n_trades", "net_bp", "net_bp_per_trade", "gross_bp_per_trade",
                  "cost_bp_per_trade", "special_bp_per_trade", "sharpe", "t_stat_nw",
                  "hit_rate", "breakeven_cost_mult"):
            print(f"  {k:24s} {s.get(k)}")
        res.trades.to_csv(OUT / "baseline_trades.csv", index=False)
        res.daily.to_csv(OUT / "baseline_daily.csv")

    # ---------------------------------------------------------------- 4. grid
    hdr("4. GRID")
    axes = None
    if a.quick:
        axes = {"direction": (1, -1), "entry_offset": (1, 5), "exit_rule": ("next_roll",),
                "exit_offset": (1,), "hold_days": (21,), "z_window": (None,), "z_entry": (None,)}
    cfgs = G.expand(axes=axes, financing_mode=a.financing)
    print(f"{len(cfgs)} configurations "
          f"({len(G.TENORS)} tenors x {len(G.PAIRS)} rank pairs x rules)")
    league, daily, results = G.run_grid(p_fin, amap, cfgs)
    league.to_csv(OUT / "league_raw.csv", index=False)
    errs = league[league.get("error", "").astype(str) != ""]
    if len(errs):
        print(f"!! {len(errs)} configs errored; first: {errs.iloc[0]['error']}")

    scored = A.league_table(league.to_dict("records"), min_trades=8)
    print(f"{len(scored)} configs with >= 8 trades")

    # ---------------------------------------------------------------- 5. placebo
    hdr("5. PLACEBO -- the same rules, entered OFF the auction clock")
    top = scored.head(12)["name"].tolist() if len(scored) else []
    top_cfgs = [c for c in cfgs if c.name in top]
    pl_cfgs = G.placebo_grid(top_cfgs, shifts=(7, 14, -7))
    pl_league, pl_daily, _ = G.run_grid(p_fin, amap, pl_cfgs, progress=False)
    pl_league.to_csv(OUT / "placebo.csv", index=False)
    if len(pl_league):
        real = scored[scored["name"].isin(top)]["sharpe"].mean()
        fake = pl_league["sharpe"].mean()
        print(f"top-12 mean Sharpe   : {real:+.3f}")
        print(f"placebo mean Sharpe  : {fake:+.3f}  ({len(pl_league)} shifted configs)")
        print("  a mechanism that is really the auction must DEGRADE when shifted off it")

    # ---------------------------------------------------------------- 6. deflation
    hdr("6. DEFLATION -- what the search cost")
    n_trials = len(cfgs) + len(pl_cfgs)
    all_daily = {**daily, **pl_daily}
    defl = A.deflate_league(scored, all_daily, n_trials=n_trials)
    defl["verdict"] = defl.apply(A.verdict_row, axis=1)
    defl.to_csv(OUT / "league_deflated.csv", index=False)
    print(f"trials counted: {n_trials} (grid {len(cfgs)} + placebo {len(pl_cfgs)})")
    if len(defl):
        print(f"sr_variance across grid: {defl['sr_variance'].iloc[0]:.4f}   "
              f"expected max Sharpe under the null: {defl['sr_star'].iloc[0]:.3f}")
        cols = ["name", "tenor", "pair", "direction", "entry_offset", "n_trades",
                "net_bp_per_trade", "cost_bp_per_trade", "special_bp_per_trade",
                "sharpe", "t_stat_nw", "dsr_prob", "breakeven_cost_mult", "verdict"]
        cols = [c for c in cols if c in defl.columns]
        print("\nTOP 20 BY SHARPE:")
        print(defl.head(20)[cols].round(4).to_string(index=False))
        print(f"\nverdict counts:\n{defl['verdict'].value_counts().to_string()}")
        alive = defl[defl["verdict"] == "ALIVE"]
        print(f"\nALIVE: {len(alive)} of {len(defl)}")

    # The raw trial count treats every one of the 3,360 overlapping cells as an independent
    # experiment, which over-deflates a grid whose neighbours hold nearly the same positions
    # on nearly the same days. Both bounds are honest -- report both rather than pick the
    # flattering one. Raw is the HARSHER direction, so it stays the headline.
    eff = A.deflate_with_effective_trials({**daily, **pl_daily})
    if eff:
        print("\neffective-trial deflation (correlation-aware):")
        for k, v in eff.items():
            print(f"  {k:30s} {v}")
        with open(OUT / "effective_trials.json", "w") as f:
            json.dump({k: (float(v) if isinstance(v, (int, float)) else str(v))
                       for k, v in eff.items()}, f, indent=2)

    # ---------------------------------------------------------------- 7. cost curve
    hdr("7. COST CURVE -- at what fraction of the assumed cost does it stop working")
    if len(defl):
        best_name = defl.iloc[0]["name"]
        best_cfg = next(c for c in cfgs if c.name == best_name)
        cc = G.cost_curve(panel, amap, best_cfg)
        print(f"best config: {best_name}")
        print(cc.round(4).to_string(index=False))
        cc.to_csv(OUT / "cost_curve.csv", index=False)

    # ---------------------------------------------------------------- 8. seasonality
    hdr("8. SEASONALITY")
    if len(defl):
        best_name = defl.iloc[0]["name"]
        best_res = results.get(best_name)
        if best_res is not None:
            cyc = A.auction_cycle_profile(best_res)
            cyc.to_csv(OUT / "auction_cycle_profile.csv", index=False)
            print("auction-cycle profile (mechanism clock), first 15 days:")
            print(cyc.head(15).round(4).to_string(index=False))
            seas = A.calendar_seasonality(best_res)
            for k, d in seas.items():
                d.to_csv(OUT / f"seasonality_{k}.csv", index=False)
            if "month" in seas:
                print("\nmonth of year:")
                print(seas["month"].round(4).to_string(index=False))

    # pooled seasonality across ALL long-old configs -- one config's calendar is noise
    hdr("8b. POOLED SEASONALITY across every long-old config (the honest version)")
    pool = []
    for nm, r in results.items():
        if r.config.direction > 0 and not r.trades.empty:
            cyc = A.auction_cycle_profile(r)
            if not cyc.empty:
                cyc["name"] = nm
                cyc["tenor"] = r.config.tenor
                pool.append(cyc)
    if pool:
        allc = pd.concat(pool, ignore_index=True)
        allc.to_csv(OUT / "auction_cycle_pooled.csv", index=False)
        g = allc.groupby("cycle_day").apply(
            lambda d: pd.Series({
                "n": d["n"].sum(),
                "mean_pnl_bp": np.average(d["mean_pnl_bp"], weights=d["n"]),
                "mean_price_bp": np.average(d["mean_price_bp"], weights=d["n"]),
            }), include_groups=False)
        print(g.head(20).round(5).to_string())

    with open(OUT / "summary.json", "w") as f:
        json.dump(
            {
                "n_configs": len(cfgs), "n_placebo": len(pl_cfgs), "n_trials": n_trials,
                "n_scored": int(len(scored)),
                "n_alive": int((defl["verdict"] == "ALIVE").sum()) if len(defl) else 0,
                "financing_mode": a.financing,
                "panel_start": str(panel["date"].min().date()),
                "panel_end": str(panel["date"].max().date()),
            },
            f, indent=2,
        )
    print(f"\nartefacts -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

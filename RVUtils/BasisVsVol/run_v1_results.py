"""Run the full V1 grid, controls and verdict once the panels are built.

    <env>/python.exe -m RVUtils.BasisVsVol.run_v1_results [--wait-for-builds]

Pre-registered before the run, same discipline as the V2 search:

* **Direction is fixed in code.** ``z < 0`` means the market pays less than the delivery option is
  worth, so the position is long basis. It is not chosen after the fact.
* **Kill conditions.** Alive requires ALL of: deflated Sharpe > 0.95 against the full trial count;
  survival at 2x costs; a sign-flip permutation percentile > 0.95; top-3 trade share < 0.60.
* **The ablation is a kill condition too.** If the no-model arm (raw net-basis z-score) matches the
  full model, the delivery-option machinery is decoration and the honest name for the strategy is
  "fade the net basis".
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
from dataclasses import replace

import numpy as np
import pandas as pd

from RVUtils.BasisVsVol import analytics as A
from RVUtils.BasisVsVol import v1 as V1

DATA = pathlib.Path(__file__).resolve().parents[2] / "notebooks" / "backtests" / "basis_vs_vol" / "_data"
RESULTS = DATA.parent / "_results"
ROOTS = ("ZB", "ZN", "UB")
AXES = dict(entry_z=[1.0, 1.5, 2.0, 2.5], max_hold_days=[10, 21, 42],
            z_window=[63, 126, 252], switch_vol_bp=[50.0, 70.0, 90.0])
ALIVE = dict(min_dsr=0.95, max_top3=0.60, cost_mult=2.0, perm_pct=0.95)


def _panels() -> dict:
    out = {}
    for r in ROOTS:
        f = DATA / f"basis_panel_{r}.parquet"
        if f.exists():
            p = pd.read_parquet(f)
            if len(p) > 200:
                out[r] = p
    return out


def wait_for_builds(min_rows: int = 1500, timeout_h: float = 14.0) -> None:
    """Block until every panel stops growing, or the timeout expires."""
    t0, last = time.time(), {}
    while time.time() - t0 < timeout_h * 3600:
        sizes = {r: (len(pd.read_parquet(DATA / f"basis_panel_{r}.parquet"))
                     if (DATA / f"basis_panel_{r}.parquet").exists() else 0) for r in ROOTS}
        if sizes == last and min(sizes.values() or [0]) >= min_rows:
            print(f"builds settled: {sizes}", flush=True)
            return
        print(f"waiting, sizes={sizes}", flush=True)
        last = sizes
        time.sleep(600)
    print("wait timed out; running on whatever exists", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-for-builds", action="store_true")
    ap.add_argument("--min-rows", type=int, default=1500)
    a = ap.parse_args(argv)
    if a.wait_for_builds:
        wait_for_builds(a.min_rows)

    RESULTS.mkdir(parents=True, exist_ok=True)
    panels = _panels()
    if not panels:
        print("no panels with >200 rows; nothing to do")
        return 1
    for r, p in panels.items():
        print(f"{r}: {len(p)} days {p['date'].min().date()} -> {p['date'].max().date()}", flush=True)

    base = V1.V1Config()
    rows = []
    for root, p in panels.items():
        for ez in AXES["entry_z"]:
            for mh in AXES["max_hold_days"]:
                for zw in AXES["z_window"]:
                    for sv in AXES["switch_vol_bp"]:
                        c = replace(base, root=root, entry_z=ez, max_hold_days=mh,
                                    z_window=zw, switch_vol_bp=sv)
                        res = V1.run_v1(p, c)
                        if res.daily.empty:
                            continue
                        s = A.summarize(res.daily, res.trades)
                        s.update(root=root, entry_z=ez, max_hold=mh, z_window=zw, switch_vol=sv,
                                 key=c.key())
                        rows.append(s)
    grid = pd.DataFrame(rows)
    grid.to_csv(RESULTS / "v1_grid.csv", index=False)
    print(f"\ngrid: {len(grid)} cells", flush=True)
    if grid.empty:
        return 1

    num = pd.to_numeric(grid["sharpe"], errors="coerce").dropna()
    n_trials, var = int(num.size), float(num.var(ddof=1))
    emax = A.expected_max_sharpe(n_trials, var)
    ranked = grid.sort_values("sharpe", ascending=False)
    cols = ["root", "entry_z", "max_hold", "z_window", "switch_vol", "n_trades", "mean_volbp",
            "hit_rate", "sharpe", "t_nw", "top3_share"]
    print(ranked[cols].head(12).round(3).to_string(index=False), flush=True)
    print(f"\nmedian Sharpe {num.median():.3f} | positive {100*(num>0).mean():.0f}% | "
          f"best {num.max():.3f} | E[max|null] {emax:.3f}", flush=True)

    b = ranked.iloc[0]
    bcfg = replace(base, root=b["root"], entry_z=float(b["entry_z"]),
                   max_hold_days=int(b["max_hold"]), z_window=int(b["z_window"]),
                   switch_vol_bp=float(b["switch_vol"]))
    bres = V1.run_v1(panels[b["root"]], bcfg)
    bres.daily.to_csv(RESULTS / "v1_best_daily.csv")
    bres.trades.to_csv(RESULTS / "v1_best_trades.csv", index=False)
    dsr = A.deflated_sharpe(bres.daily["pnl_volbp"], n_trials, var)
    lo, hi = A.block_bootstrap_ci(bres.daily["pnl_volbp"], block=21, n_boot=2000)

    ladder = []
    for cm in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0):
        r_ = V1.run_v1(panels[b["root"]], replace(bcfg, cost_mult=cm))
        s = A.summarize(r_.daily, r_.trades); s["cost_mult"] = cm; ladder.append(s)
    lad = pd.DataFrame(ladder); lad.to_csv(RESULTS / "v1_cost_ladder.csv", index=False)
    be = lad[lad["sharpe"] > 0]["cost_mult"]

    abl = []
    for lbl, kw in (("switch+wildcard", {}), ("switch only", dict(use_wildcard=False)),
                    ("wildcard only", dict(use_switch=False)),
                    ("no model (raw BNOC)", dict(use_switch=False, use_wildcard=False))):
        r_ = V1.run_v1(panels[b["root"]], replace(bcfg, **kw))
        s = A.summarize(r_.daily, r_.trades); s["model"] = lbl; abl.append(s)
    ablation = pd.DataFrame(abl); ablation.to_csv(RESULTS / "v1_ablation.csv", index=False)
    print("\n=== model ablation ===", flush=True)
    print(ablation[["model", "n_trades", "mean_volbp", "hit_rate", "sharpe", "t_nw"]]
          .round(3).to_string(index=False), flush=True)

    pct = float("nan")
    if len(bres.trades):
        rng = np.random.default_rng(20260814)
        v = bres.trades["pnl"].to_numpy(float) * bres.trades["side"].to_numpy(float)
        tot = (v * rng.choice([-1.0, 1.0], size=(2000, len(v)))).sum(axis=1)
        pct = float((tot < bres.trades["pnl"].sum()).mean())

    full = float(ablation.loc[ablation.model == "switch+wildcard", "sharpe"].iloc[0])
    raw = float(ablation.loc[ablation.model == "no model (raw BNOC)", "sharpe"].iloc[0])
    verdict = {
        "sample": {r: [str(p["date"].min().date()), str(p["date"].max().date()), len(p)]
                   for r, p in panels.items()},
        "best_key": b["key"], "sharpe": float(b["sharpe"]), "t_nw": float(b["t_nw"]),
        "n_trades": int(b["n_trades"]), "hit_rate": float(b["hit_rate"]),
        "top3_share": float(b["top3_share"]), "mean_32nds_per_trade": float(b["mean_volbp"]),
        "n_trials": n_trials, "expected_max_sharpe_null": emax, "dsr": float(dsr),
        "sharpe_ci95": [lo, hi], "permutation_pct": pct,
        "breakeven_cost_mult": float(be.max()) if len(be) else 0.0,
        "grid_median_sharpe": float(num.median()),
        "grid_pct_positive": float((num > 0).mean()),
        "ablation_full_vs_raw_sharpe": [full, raw],
        "model_adds_value": bool(full > raw + 0.10),
        "alive_criteria": ALIVE,
        "alive": bool(dsr > ALIVE["min_dsr"] and float(b["top3_share"]) < ALIVE["max_top3"]
                      and (len(be) and be.max() >= ALIVE["cost_mult"])
                      and np.isfinite(pct) and pct > ALIVE["perm_pct"]),
    }
    (RESULTS / "v1_verdict.json").write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")
    print("\n=== V1 VERDICT ===", flush=True)
    print(json.dumps(verdict, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

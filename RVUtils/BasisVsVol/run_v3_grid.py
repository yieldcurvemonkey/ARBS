"""Run the V3 grid, controls and verdict.

    <env>/python.exe -m RVUtils.BasisVsVol.run_v3_grid

PRE-REGISTERED before the first run -- see
``docs/superpowers/specs/2026-08-14-v3-basis-vs-swaption-preregistration.md``.

* **Direction is fixed in code.** ``richness > 1`` means the swaption costs more per unit of gamma,
  so the basis is the cheaper option and the position is LONG basis. Not chosen after the fact.
* **Guards are fixed, not searched.** ``min_net_basis_ticks``, ``min_gamma`` and the
  days-to-delivery window exist because each degeneracy *inverts* the signal rather than adding
  noise. A guard that is tuned is not a guard. ``min_gamma`` was set from the gamma DISTRIBUTION
  (median 1e-7, p90 1e-3 32nds/bp^2) before any P&L was computed.
* **Two arms, both pre-registered**: A = long basis outright (the note's literal trade, the swaption
  as yardstick); B = long basis + short gamma-matched ATMF receiver (the RV structure).
* **Arm C is the ablation and a kill condition**: enter on cheap net basis alone, no vol leg. If C
  matches A/B then the swaption comparison -- the entire content of the note -- is decoration.
* **Kill conditions.** Alive requires ALL of: deflated Sharpe > 0.95 against the full trial count;
  survival at 2x costs; a sign-flip permutation percentile > 0.95; top-3 trade share < 0.60; and the
  ablation must not match.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from dataclasses import replace

import numpy as np
import pandas as pd

from RVUtils.BasisVsVol import analytics as A
from RVUtils.BasisVsVol import v3 as V3
from RVUtils.BasisVsVol.build_basis_panel import filter_data_ok

DATA = pathlib.Path(__file__).resolve().parents[2] / "notebooks" / "backtests" / "basis_vs_vol" / "_data"
RESULTS = DATA.parent / "_results"

ROOTS = ("ZB", "ZN", "UB")
ARMS = ("A", "B")
AXES = dict(
    entry_richness=[1.10, 1.25, 1.50, 2.00],
    max_hold_days=[10, 21, 42],
    take_profit_ticks=[None, 2.0, 4.0],
)
ALIVE = dict(min_dsr=0.95, max_top3=0.60, cost_mult=2.0, perm_pct=0.95)
MIN_TRADES = 10


def load_panels(start: str, end: str) -> dict:
    out = {}
    for r in ROOTS:
        f = DATA / f"v3_panel_{r}.parquet"
        if not f.exists():
            continue
        raw = pd.read_parquet(f)
        raw["date"] = pd.to_datetime(raw["date"])
        raw = raw[(raw["date"] >= start) & (raw["date"] <= end)]
        p = filter_data_ok(raw, require=True)
        n_rich = int(p["richness"].notna().sum())
        print(f"  {r}: {len(raw)} rows -> {len(p)} pass the shared gate, {n_rich} with a richness",
              flush=True)
        if len(p) > 200:
            out[r] = p
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-08-11")
    ap.add_argument("--tag", default="v3")
    a = ap.parse_args(argv)
    RESULTS.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print(f"=== loading V3 panels {a.start} .. {a.end} ===", flush=True)
    panels = load_panels(a.start, a.end)
    if not panels:
        print("no panels")
        return 1

    base = V3.V3Config()
    rows = []
    for root, p in panels.items():
        for arm in ARMS:
            for er in AXES["entry_richness"]:
                for mh in AXES["max_hold_days"]:
                    for tp in AXES["take_profit_ticks"]:
                        c = replace(base, root=root, arm=arm, entry_richness=er,
                                    max_hold_days=mh, take_profit_ticks=tp)
                        res = V3.run_v3(p, c)
                        if res.daily.empty or res.trades.empty:
                            continue
                        s = A.summarize(res.daily, res.trades)
                        s.update(root=root, arm=arm, entry_richness=er, max_hold=mh,
                                 take_profit=(-1.0 if tp is None else tp), key=c.key())
                        rows.append(s)
    grid = pd.DataFrame(rows)
    grid.to_csv(RESULTS / f"{a.tag}_grid.csv", index=False)
    print(f"\ngrid: {len(grid)} cells in {time.time()-t0:.0f}s", flush=True)
    if grid.empty:
        return 1

    liq = grid[grid["n_trades"] >= MIN_TRADES].copy()
    if liq.empty:
        print(f"no cell reached {MIN_TRADES} trades; reporting the full grid")
        liq = grid
    num = pd.to_numeric(liq["sharpe"], errors="coerce").dropna()
    n_trials, var = int(num.size), float(num.var(ddof=1))
    emax = A.expected_max_sharpe(n_trials, var)
    ranked = liq.sort_values("sharpe", ascending=False)
    cols = ["root", "arm", "entry_richness", "max_hold", "take_profit", "n_trades",
            "hit_rate", "total_volbp", "sharpe", "t_nw", "top3_share"]
    print(ranked[[c for c in cols if c in ranked.columns]].head(12).round(3).to_string(index=False),
          flush=True)
    print(f"\nmedian Sharpe {num.median():.3f} | positive {100*(num>0).mean():.0f}% | "
          f"best {num.max():.3f} | E[max|null] {emax:.3f}", flush=True)

    b = ranked.iloc[0]
    tp = None if float(b["take_profit"]) < 0 else float(b["take_profit"])
    bcfg = replace(base, root=b["root"], arm=b["arm"], entry_richness=float(b["entry_richness"]),
                   max_hold_days=int(b["max_hold"]), take_profit_ticks=tp)
    bres = V3.run_v3(panels[b["root"]], bcfg)
    bres.daily.to_csv(RESULTS / f"{a.tag}_best_daily.csv")
    bres.trades.to_csv(RESULTS / f"{a.tag}_best_trades.csv", index=False)
    dsr = A.deflated_sharpe(bres.daily["pnl_volbp"], n_trials, var)
    lo, hi = A.block_bootstrap_ci(bres.daily["pnl_volbp"], block=21, n_boot=2000)

    ladder = []
    for cm in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0):
        r_ = V3.run_v3(panels[b["root"]], replace(bcfg, cost_mult=cm))
        if r_.trades.empty:
            continue
        s = A.summarize(r_.daily, r_.trades)
        s["cost_mult"] = cm
        ladder.append(s)
    lad = pd.DataFrame(ladder)
    lad.to_csv(RESULTS / f"{a.tag}_cost_ladder.csv", index=False)
    be = lad[lad["sharpe"] > 0]["cost_mult"]

    # --- the ablation: does the swaption comparison do any work at all? -----------------
    abl = []
    for lbl, kw in (("A: long basis (richness)", dict(arm="A")),
                    ("B: basis vs swaption", dict(arm="B")),
                    ("C: cheap net basis only", dict(arm="C"))):
        r_ = V3.run_v3(panels[b["root"]], replace(bcfg, **kw))
        if r_.trades.empty:
            abl.append({"model": lbl, "n_trades": 0, "sharpe": float("nan")})
            continue
        s = A.summarize(r_.daily, r_.trades)
        s["model"] = lbl
        abl.append(s)
    ablation = pd.DataFrame(abl)
    ablation.to_csv(RESULTS / f"{a.tag}_ablation.csv", index=False)
    print("\n=== arm ablation (at the winning cell's other knobs) ===", flush=True)
    print(ablation[[c for c in ("model", "n_trades", "hit_rate", "total_volbp", "sharpe", "t_nw")
                    if c in ablation.columns]].round(3).to_string(index=False), flush=True)

    # --- sign-flip permutation on trade P&L --------------------------------------------
    rng = np.random.default_rng(20260814)
    tp_ = bres.trades["pnl_volbp"].to_numpy(float)
    obs = float(tp_.sum())
    draws = np.array([float((tp_ * rng.choice([-1.0, 1.0], size=tp_.size)).sum()) for _ in range(2000)])
    perm_pct = float((draws < obs).mean())

    conc = A.concentration(bres.trades["pnl_volbp"])
    bs = A.summarize(bres.daily, bres.trades)
    verdict = {
        "sample": {r: [str(p["date"].min().date()), str(p["date"].max().date()), len(p)]
                   for r, p in panels.items()},
        "best_key": bcfg.key(),
        "best_arm": b["arm"],
        "sharpe": float(bs["sharpe"]),
        "t_nw": float(bs.get("t_nw", float("nan"))),
        "n_trades": int(bs["n_trades"]),
        "hit_rate": float(bs["hit_rate"]),
        "total_32nds": float(bs["total_volbp"]),
        "top3_share": float(conc.get("top3_share", float("nan"))),
        "n_trials": n_trials,
        "expected_max_sharpe_null": float(emax),
        "dsr": float(dsr),
        "sharpe_ci95": [float(lo), float(hi)],
        "permutation_pct": perm_pct,
        "breakeven_cost_mult": (float(be.max()) if len(be) else 0.0),
        "grid_median_sharpe": float(num.median()),
        "grid_pct_positive": float((num > 0).mean()),
        "ablation": {r["model"]: (None if not np.isfinite(r.get("sharpe", np.nan)) else float(r["sharpe"]))
                     for r in abl},
        "alive_criteria": ALIVE,
    }
    a_ok = (verdict["dsr"] > ALIVE["min_dsr"] and verdict["top3_share"] < ALIVE["max_top3"]
            and verdict["breakeven_cost_mult"] >= ALIVE["cost_mult"] and perm_pct > ALIVE["perm_pct"])
    verdict["alive"] = bool(a_ok)
    (RESULTS / f"{a.tag}_verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print("\n=== V3 VERDICT ===", flush=True)
    print(json.dumps(verdict, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

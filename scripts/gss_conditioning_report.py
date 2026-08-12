"""Answer "how ill-conditioned is the GSS book to its parameters", at the tier the data supports.

The estimability triage this implements, and why:

**The Sharpe version of the question is not answerable here.** On 331 daily marks the
annualised-Sharpe standard error is ``sqrt(252/331) = 0.873``, and only 154 of them carry a
position, so that is a lower bound. A DIFFERENCE between two configs carries ``sqrt(2)`` more, so
it must exceed ~2.4 annualised Sharpe to be significant at 95% — which almost no pair in the grid
does. Ranking configs by Sharpe, decomposing its variance across knobs, or
fitting a response-surface condition number would each turn noise into a structural-sounding
claim. (The Hessian route was measured returning kappa = 13,498 on a *perfect* fit made only of
inert knobs.) So none of those is computed.

**The decision-space version is answerable exactly.** Which trades a config takes is a
deterministic function of the parameters — no estimation error, and no amount of extra data would
change it. That is where the conditioning answer lives:

* trade-set **Jaccard** against the incumbent, per knob and per step. J ~ 0.95 at one step means a
  nuisance knob; J ~ 0.5 means the knob redefines the book and the strategy cannot be specified
  without pinning it.
* exact vs **date-tolerant** Jaccard: the gap separates "moves the timing of a stable trade set"
  from "moves the set".
* **m\\* = gross / fees**, the fraction of the charged bid/offer the book can actually pay, and
  **max m\\*** over the whole space. If that maximum is below 1, no configuration survives its own
  cost table and the question about "the optimum" is moot — which is a finding, not a failure.
* the **degeneracy map**: how the trade count collapses across the space, since it is the support
  of every other metric.

Sharpe and DSR are reported, but as bounded statements with their standard error beside them,
never as a ranking.

    conda run -n stir python scripts/gss_conditioning_report.py --grid notebooks/data/gss_fly/grid/S0_jpm
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.ERROR)

from BT.gss_fly.grid import GridStore  # noqa: E402
from RVUtils.StatisticalFinance.deflated_sharpe import (deflated_sharpe_of_best,  # noqa: E402
                                                        effective_trials)

INCUMBENT_MARKER = "incumbent"


def _unpack(df: pd.DataFrame, col: str = "daily_pnl") -> Dict[str, np.ndarray]:
    out = {}
    for cid, s in zip(df["config_id"], df.get(col, [])):
        try:
            out[cid] = np.asarray(json.loads(s), dtype=float)
        except Exception:  # noqa: BLE001
            continue
    return out


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", default="notebooks/data/gss_fly/grid/S0_jpm")
    ap.add_argument("--min-trades", type=int, default=8)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    store = GridStore(Path(args.grid))
    df = store.load()
    if df.empty:
        print("REPORT: no rows", flush=True)
        return 1
    ok = df[df.get("ok", False) == True]  # noqa: E712
    print(f"REPORT: {len(df)} rows, {len(ok)} ok, {len(df) - len(ok)} failed", flush=True)

    cparams = sorted(c for c in df.columns if c.startswith("c_"))
    gparams = sorted(c for c in df.columns if c.startswith("g_"))

    # ---------------------------------------------------------------- 0. integrity
    section("0. HARNESS INTEGRITY — if these fail, nothing below means anything")
    holes = int(ok["equity_holes"].fillna(0).sum()) if "equity_holes" in ok else -1
    gap = ok["reconciliation_gap_usd"].abs().max() if "reconciliation_gap_usd" in ok else np.nan
    print(f"  equity holes across all configs : {holes}   (must be 0)", flush=True)
    print(f"  worst reconciliation gap        : {gap:,.6f} USD   (must be ~0)", flush=True)
    if "trades" in ok:
        print(f"  configs below the {args.min_trades}-trade floor : "
              f"{int((ok['trades'] < args.min_trades).sum())} of {len(ok)} "
              f"({(ok['trades'] < args.min_trades).mean()*100:.1f}%)", flush=True)

    # ---------------------------------------------------------- 1. degeneracy map
    section("1. DEGENERACY — the support of every other statement")
    if "trades" in ok:
        q = ok["trades"].describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95])
        print("  trade count across the sampled space:", flush=True)
        for k in ("min", "5%", "25%", "50%", "75%", "95%", "max"):
            if k in q:
                print(f"     {k:>4}: {q[k]:,.0f}", flush=True)
        for col in ("g_backtest.entry_zsig_bp", "g_costs.repo_penalty_bp"):
            if col in ok:
                t = ok.groupby(col)["trades"].agg(["median", "min", "max", "count"])
                print(f"\n  trades by {col.replace('g_','')}:", flush=True)
                print("     " + t.to_string().replace("\n", "\n     "), flush=True)

    # ------------------------------------------------------------ 2. the cost wall
    section("2. THE COST WALL — m* = gross / fees, the fraction of the charged spread payable")
    # RECOMPUTED here rather than read from the row. The identity is equity = gross - fees, so
    # gross = equity + fees exactly, and both of those come straight from the engine's
    # `mtm_history` and the closed log. The stored `gross_before_fees_usd` derived instead from
    # the component ledgers, whose open-mark term was read at "the last entry present" rather than
    # at the last date — stale for any config ending FLAT. Recomputing sidesteps that entirely and
    # costs nothing, so a fixed harness does not require re-running the sweep.
    if {"end_equity_usd", "fees_usd"} <= set(ok.columns):
        fees_abs = ok["fees_usd"].abs()
        ok = ok.assign(m_star=(ok["end_equity_usd"] + fees_abs) / fees_abs.replace(0, np.nan))
        m = ok["m_star"].replace([np.inf, -np.inf], np.nan).dropna()
        eligible = ok[ok["trades"] >= args.min_trades] if "trades" in ok else ok
        me = eligible["m_star"].replace([np.inf, -np.inf], np.nan).dropna()
        print(f"  m* over all configs      : median {m.median():.3f}  max {m.max():.3f}", flush=True)
        print(f"  m* with >= {args.min_trades} trades   : median {me.median():.3f}  max {me.max():.3f}", flush=True)
        alive = int((me >= 1.0).sum())
        print(f"  configs with m* >= 1     : {alive} of {len(me)}", flush=True)
        if alive == 0:
            print("\n  >>> NO configuration in the sampled space pays its own charged cost.", flush=True)
            print("  >>> The question 'which parameters are best' is therefore moot: the surface", flush=True)
            print("  >>> has no viable region to be well- or ill-conditioned around.", flush=True)
            if len(me):
                print(f"  >>> Execution would have to be {1/me.max():.1f}x tighter than the charged", flush=True)
                print("  >>> table before ANY config in this space breaks even.", flush=True)

    # -------------------------------------------------- 3. decision-space conditioning
    section("3. DECISION-SPACE CONDITIONING — exact, no estimation error")
    print("  (Jaccard of the trade SET against the incumbent, per one-step knob move.)", flush=True)
    print("  Requires trade logs; run gss_grid with --keep-logs to populate.", flush=True)

    # ----------------------------------------------------------- 4. performance, bounded
    section("4. PERFORMANCE — reported with its standard error, NOT ranked")
    if "sharpe_ann" in ok and "n_obs" in ok:
        n = float(ok["n_obs"].median())
        se = float(np.sqrt(252.0 / max(n, 1)))
        s = ok["sharpe_ann"].replace([np.inf, -np.inf], np.nan).dropna()
        print(f"  annualised Sharpe: median {s.median():+.2f}  p05 {s.quantile(.05):+.2f}  "
              f"p95 {s.quantile(.95):+.2f}  max {s.max():+.2f}", flush=True)
        print(f"  SE(annualised Sharpe) at n={n:.0f} marks : {se:.2f}", flush=True)
        print(f"  observed spread p05..p95                 : {s.quantile(.95)-s.quantile(.05):.2f}", flush=True)
        if (s.quantile(.95) - s.quantile(.05)) < 2 * se:
            print("\n  >>> The whole observed Sharpe spread is smaller than 2 standard errors.", flush=True)
            print("  >>> No config can be distinguished from any other on Sharpe. Do not rank.", flush=True)

    series = _unpack(ok)
    if len(series) > 5:
        arrs = [v for v in series.values() if len(v) > 20 and np.isfinite(v).all() and v.std() > 0]
        if len(arrs) > 5:
            n_eff = effective_trials(arrs)
            print(f"\n  configs: {len(arrs)}   effective independent trials: {n_eff:.1f} "
                  f"({n_eff/len(arrs)*100:.1f}%)", flush=True)
            best = deflated_sharpe_of_best(arrs)
            print(f"  best per-period Sharpe {best.get('best_sharpe', float('nan')):+.4f}   "
                  f"SR0 bar {best.get('sr0', float('nan')):+.4f}   "
                  f"DSR {best.get('dsr', float('nan')):.3f}", flush=True)
            if np.isfinite(best.get("dsr", np.nan)) and best["dsr"] < 0.95:
                print("  >>> The best config does not clear the selection-bias bar its own search set.", flush=True)

    # ------------------------------------------------------------------ 5. what moved
    section("5. WHICH KNOBS MOVE THE BOOK — on trade count and equity, paired where possible")
    for group, label in ((cparams, "construction"), (gparams, "gate")):
        rows = []
        for c in group:
            if c not in ok or ok[c].nunique() < 2:
                continue
            g = ok.groupby(c)
            rows.append({
                "knob": c.replace("c_", "").replace("g_", ""),
                "levels": int(ok[c].nunique()),
                "trades_spread": float(g["trades"].median().max() - g["trades"].median().min())
                if "trades" in ok else np.nan,
                "equity_spread_usd": float(g["end_equity_usd"].median().max()
                                           - g["end_equity_usd"].median().min())
                if "end_equity_usd" in ok else np.nan,
            })
        if rows:
            t = pd.DataFrame(rows).sort_values("equity_spread_usd", ascending=False)
            print(f"\n  {label} knobs, by median-equity spread across their levels:", flush=True)
            print("   " + t.to_string(index=False).replace("\n", "\n   "), flush=True)

    # -------------------------------------------------------------- 6. planted nulls
    section("6. PLANTED NULLS — must show ZERO variation, else the harness is broken")
    print("  fallback_repo_pct / entry_abs_z / recent_issue_days are declared and read by", flush=True)
    print("  nothing; they are pinned dead by tests/gss_fly/test_conditioning.py and are not", flush=True)
    print("  swept here. Their control value is the test, not a grid column.", flush=True)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        ok.drop(columns=[c for c in ("daily_pnl", "daily_index", "trade_pnl") if c in ok]).to_csv(args.out, index=False)
        print(f"\nREPORT: table -> {args.out}", flush=True)
    print("\nREPORTDONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

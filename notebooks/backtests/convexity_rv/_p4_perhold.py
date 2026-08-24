r"""The SECOND clock the pre-registration promised, and only the first was graded.

§6 and §11 of ``docs/convexityrv/citi-framework-preregistration.md`` require
``E[max SR | null]`` on **both** clocks -- per-hold and annualised.  The grid
runner reported the annualised Sharpe of the DAILY P&L series and graded it
against ``emax_annualised``; that is a correct comparison, but it is only one
of the two, and for a book that is flat on 99% of its dates the two clocks say
materially different things:

* the **annualised daily** Sharpe divides by the sd of a series that is mostly
  zeros, so it measures the equity curve an investor would hold, idle capital
  included.  Four trades over 1,409 dates score low almost by construction.
* the **per-hold** Sharpe is ``mean / sd`` over the EPISODES, and it measures
  the quality of the trades that were taken.  Its null sd is ``1/sqrt(n_eff)``,
  which is exactly what ``null_bars(..., n_eff=...)['emax_perhold']`` returns.

Grading a per-hold Sharpe against an annualised bar, or the reverse, is the
"which column is the claim true in" trap.  This script computes the per-hold
clock for every declared cell, net of the declared costs, and grades it against
its own bar at its own ``n_eff``.

Output: notebooks/data/convexity_rv/p4_perhold.parquet + p4_perhold.json
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 60)

from RVUtils.ConvexityRV import citi_rule as R  # noqa: E402
from RVUtils.ConvexityRV import citi_screen as SC  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
P = pd.read_parquet(DATA / "p4_citi.parquet")
P.index = pd.to_datetime(P.index)
S = SC.build_screen(P)
SPAN = float(json.loads((DATA / "p4_preflight.json").read_text())
             ["span_tradeable_years"])
N_TRIALS = len(R.declared_cells())
RNG = np.random.default_rng(20260824)
N_DRAW = 50_000

rows = []
for spec in R.declared_cells():
    cfg = spec.config()
    ctx = R.build_contexts(P, S, cfg)
    eps = R.episodes_from_contexts(ctx, cfg, panel=P)
    if not eps:
        rows.append({"cell_id": spec.cell_id, "tier": spec.tier,
                     "headline": spec.headline, "n": 0})
        continue
    gross = np.array([float(R.episode_daily_pnl(e, ctx[e.structure], cfg).sum())
                      for e in eps])
    cost = np.array([R.episode_cost_usd(e, cfg, mult=1.0) for e in eps])
    net = gross - cost
    n = len(net)
    holds = np.array([e.hold_bd for e in eps], dtype=float)
    mean_hold = float(holds.mean())
    n_eff_hold = SPAN * 252.0 / mean_hold if mean_hold > 0 else np.nan
    n_eff = float(min(n, n_eff_hold)) if np.isfinite(n_eff_hold) else float(n)

    def _sr(a):
        return float(a.mean() / a.std(ddof=1)) if n > 1 and a.std(ddof=1) > 0 else np.nan

    sr_g, sr_n = _sr(gross), _sr(net)
    bars = R.null_bars(N_TRIALS, n_eff=n_eff, span_years=SPAN)
    # the same shared-sign-flip null, on the per-episode P&L, both gross and net
    def _pflip(a, sr):
        if n < 3 or not np.isfinite(sr) or a.std(ddof=1) <= 0:
            return float("nan")
        f = RNG.choice([-1.0, 1.0], size=(N_DRAW, n))
        sim = a * f
        return float((sim.mean(axis=1) / sim.std(axis=1, ddof=1) >= sr).mean())

    p_flip_g, p_flip = _pflip(gross, sr_g), _pflip(net, sr_n)
    rows.append({
        "cell_id": spec.cell_id, "tier": spec.tier, "headline": spec.headline,
        "n": n, "mean_hold_bd": mean_hold, "n_eff": n_eff,
        "trades_per_year": n / SPAN,
        "gross_usd": float(gross.sum()), "net_usd": float(net.sum()),
        "perhold_sharpe_gross": sr_g, "perhold_sharpe_net": sr_n,
        "bar_perhold": bars["emax_perhold"],
        "bar_annualised": bars["emax_annualised"],
        "clears_perhold_gross": bool(np.isfinite(sr_g) and sr_g > bars["emax_perhold"]),
        "clears_perhold_net": bool(np.isfinite(sr_n) and sr_n > bars["emax_perhold"]),
        "p_signflip_gross": p_flip_g, "p_signflip_net": p_flip,
    })

T = pd.DataFrame(rows)
cols = ["cell_id", "tier", "headline", "n", "mean_hold_bd", "n_eff",
        "trades_per_year", "gross_usd", "net_usd", "perhold_sharpe_gross",
        "perhold_sharpe_net", "bar_perhold", "clears_perhold_gross",
        "clears_perhold_net", "p_signflip_gross", "p_signflip_net"]
print(T[cols].round(4).to_string(index=False))

g = T[T["clears_perhold_gross"].astype("boolean").fillna(False).astype(bool)]
n_ = T[T["clears_perhold_net"].astype("boolean").fillna(False).astype(bool)]
print(f"\ncells clearing the PER-HOLD bar GROSS: {len(g)} of {len(T)}")
if len(g):
    print(g[["cell_id", "n", "perhold_sharpe_gross", "bar_perhold",
             "p_signflip_gross"]].round(4).to_string(index=False))
print(f"cells clearing the PER-HOLD bar NET of 1x costs: {len(n_)} of {len(T)}")
if len(n_):
    print(n_[["cell_id", "n", "perhold_sharpe_net", "bar_perhold",
              "p_signflip_net"]].round(4).to_string(index=False))

print("\nRead the two clocks together, not apart. A per-hold Sharpe measures "
      "the quality of the trades that were TAKEN; an annualised daily Sharpe "
      "measures the equity curve an investor would have held, idle capital "
      "included. A book with four trades in 4.7 years can look respectable on "
      "the first and cannot be run on the second, and both facts are true.")

T.to_parquet(DATA / "p4_perhold.parquet")
(DATA / "p4_perhold.json").write_text(json.dumps({
    "n_trials": N_TRIALS, "span_tradeable_years": SPAN,
    "n_clear_perhold_gross": int(len(g)), "n_clear_perhold_net": int(len(n_)),
    "table": json.loads(T.to_json(orient="records")),
}, indent=1))
print(f"\nwrote {DATA / 'p4_perhold.parquet'}")

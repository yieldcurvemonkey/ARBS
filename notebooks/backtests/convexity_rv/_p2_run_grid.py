r"""GV block: run the 298 declared cells, with the nulls, placebos and controls.

Everything scored here is declared in ``docs/convexityrv/gv-preregistration.md``
and counted against it by ``tests/test_convexity_rv_gv_grid.py``.  Nothing is
added at run time.

Reports, in order:
  1. the grid, by family and by sizing rule;
  2. **the headline 12** -- the brief's own trade at the incumbent sizing and at
     the fix, side by side;
  3. carry vs residual, because a roll-blackout book earns the CA's theta and
     that is carry, not alpha (pre-reg A3.2);
  4. null bars on both clocks, the deflated Sharpe of the best, and the declared
     shared-sign-flip resampling null;
  5. placebo: the same cells with the signal lagged +20 bd;
  6. the blackout-off control, which must reproduce the roll artifact;
  7. the convexity signature as a POINT prediction (pre-reg A3.4).

Output: notebooks/data/convexity_rv/p2_grid_*.parquet
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 80)
pd.set_option("display.max_rows", 400)

from RVUtils.ConvexityRV import gv_grid as GG  # noqa: E402
from RVUtils.ConvexityRV import gv_signals as GS  # noqa: E402
from RVUtils.ConvexityRV import gv_sizing as S  # noqa: E402
from RVUtils.ConvexityRV import gv_universe as U  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
CA = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
LEGS = pd.read_parquet(DATA / "p2_legs.parquet")
LEGS.index = pd.to_datetime(LEGS.index)
IDX = CA.index.intersection(LEGS.index)
CA, LEGS = CA.loc[IDX], LEGS.loc[IDX]
SPAN_Y = (IDX[-1] - IDX[0]).days / 365.25

ALL = list(U.PRIMARY_STRUCTURES) + list(U.SECONDARY_STRUCTURES)
HL = S.fit_denoise_halflives(CA, [U.ca_col(l) for l in ALL])["halflife_bd"].to_dict()


def sec(t: str) -> None:
    print(f"\n{'=' * 80}\n{t}\n{'=' * 80}")


# ---------------------------------------------------------------------------
sec("1. Running the 298 declared cells")
# ---------------------------------------------------------------------------
cells = GG.declared_cells()
print(f"{len(cells)} declared cells, {sum(c.headline for c in cells)} headline; "
      f"{len(IDX)} dates {IDX.min().date()}..{IDX.max().date()} "
      f"({SPAN_Y:.2f} years)")
t0 = time.time()
res = GG.run_grid(cells, CA, LEGS, halflives=HL, progress=True)
print(f"grid done in {time.time() - t0:.0f}s")

st = GG.grid_stats_frame(res, span_years=SPAN_Y)
st.to_parquet(DATA / "p2_grid_stats.parquet")

# episode-level frame, for the nulls
eprows = []
for r in res:
    for e, p in zip(r.episodes, r.per_episode_usd):
        eprows.append({"cell_id": r.spec.cell_id, "entry": e.entry,
                       "exit": e.exit, "side": e.side, "beta": e.beta_entry,
                       "ca_dv01": e.ca_dv01, "segment": e.segment,
                       "reason": e.exit_reason, "pnl_usd": p})
ep = pd.DataFrame(eprows)
ep.to_parquet(DATA / "p2_grid_episodes.parquet")
print(f"{len(ep)} episodes across the grid; "
      f"exit reasons: {ep['reason'].value_counts().to_dict()}")

# ---------------------------------------------------------------------------
sec("2. THE HEADLINE 12 -- the brief's trade, incumbent sizing vs the fix")
# ---------------------------------------------------------------------------
head = st[st["headline"]].copy()
cols = ["structure", "leg_id", "sizing", "n_episodes", "mean_hold_bd",
        "mean_abs_beta", "mean_leg_dv01", "gate_refusal_frac", "hit_rate",
        "net_0.0", "sharpe_0.0", "net_1.0", "sharpe_1.0",
        "carry_usd", "residual_usd", "breakeven_bp"]
print(head[cols].sort_values(["structure", "leg_id", "sizing"])
      .round(4).to_string(index=False))

piv = head.pivot_table(index=["structure", "leg_id"], columns="sizing",
                       values=["mean_leg_dv01", "net_0.0", "sharpe_0.0",
                               "residual_usd"])
print("\nincumbent (beta_lvl) vs the fix (vega_match):")
print(piv.round(3).to_string())

# ---------------------------------------------------------------------------
sec("3. The grid, by sizing rule and by family")
# ---------------------------------------------------------------------------
prim = st[(st["tier"] == "primary") & (st["signal"] == "z_resid")]
g = prim.groupby("sizing").agg(
    n_cells=("cell_id", "size"),
    med_net_0=("net_0.0", "median"), med_net_1=("net_1.0", "median"),
    med_sharpe_0=("sharpe_0.0", "median"), max_sharpe_0=("sharpe_0.0", "max"),
    med_episodes=("n_episodes", "median"),
    med_beta=("mean_abs_beta", "median"),
    med_leg_dv01=("mean_leg_dv01", "median"),
    med_gate_refusal=("gate_refusal_frac", "median"),
    med_carry=("carry_usd", "median"), med_residual=("residual_usd", "median"))
print(g.round(3).to_string())

print("\nby signal family:")
print(st.groupby(["tier", "signal"]).agg(
    n=("cell_id", "size"), med_net_0=("net_0.0", "median"),
    med_sharpe_0=("sharpe_0.0", "median"), max_sharpe_0=("sharpe_0.0", "max"),
    med_residual=("residual_usd", "median")).round(3).to_string())

print("\nby leg (primary z_resid):")
print(prim.groupby("leg_id").agg(
    n=("cell_id", "size"), med_net_0=("net_0.0", "median"),
    med_sharpe_0=("sharpe_0.0", "median"), max_sharpe_0=("sharpe_0.0", "max"),
    med_beta=("mean_abs_beta", "median")).round(3).to_string())

# ---------------------------------------------------------------------------
sec("4. Carry vs residual -- what the roll blackout leaves behind (A3.2)")
# ---------------------------------------------------------------------------
cs = st[st["n_episodes"] > 5].copy()
cs["sharpe_resid_proxy"] = cs["sharpe_0.0"] * cs["residual_usd"] / cs["net_0.0"].replace(0, np.nan)
print(cs.groupby("sizing").agg(
    n=("cell_id", "size"), med_net=("net_0.0", "median"),
    med_carry=("carry_usd", "median"), med_resid=("residual_usd", "median"),
    med_carry_share=("carry_share", "median")).round(3).to_string())
pos = int((cs["net_0.0"] > 0).sum())
posr = int((cs["residual_usd"] > 0).sum())
print(f"\ncells with positive gross: {pos}/{len(cs)}; "
      f"positive gross AFTER removing the analytic CA carry: {posr}/{len(cs)}")

# ---------------------------------------------------------------------------
sec("5. Null bars, deflated Sharpe, and the declared sign-flip null")
# ---------------------------------------------------------------------------
scored = st[st["n_episodes"] >= 5].copy()
n_eff_med = float(scored["n_eff"].median())
for label, n_tr in (("headline", 12), ("full grid", len(cells))):
    nb = GG.null_bars(n_tr, n_eff=n_eff_med, span_years=SPAN_Y)
    print(f"{label:10s} trials={n_tr:4d}  E[max SR|null] per-hold "
          f"{nb['emax_perhold']:.4f}   annualised {nb['emax_annualised']:.4f}")
print(f"median n_eff per cell {n_eff_med:.2f}, span {SPAN_Y:.2f}y")

best = scored.sort_values("sharpe_0.0", ascending=False).head(10)
print("\ntop 10 cells by gross annualised Sharpe:")
print(best[["cell_id", "n_episodes", "mean_abs_beta", "net_0.0", "sharpe_0.0",
            "net_1.0", "sharpe_1.0", "carry_usd", "residual_usd",
            "breakeven_bp"]].round(3).to_string(index=False))

# per-observation Sharpe on episode P&L, for the sign-flip null
by_cell = {cid: grp["pnl_usd"].to_numpy(float)
           for cid, grp in ep.groupby("cell_id") if len(grp) >= 5}


def _sr(x: np.ndarray) -> float:
    s = x.std(ddof=1)
    return float(x.mean() / s) if s > 0 else float("nan")


obs = {c: _sr(v) for c, v in by_cell.items()}
obs_best = max(v for v in obs.values() if np.isfinite(v))
best_cell = max((c for c in obs if np.isfinite(obs[c])), key=lambda c: obs[c])
print(f"\nbest per-observation Sharpe {obs_best:.4f} ({best_cell})")

rng = np.random.default_rng(20260824)
DRAWS = 2000
# SHARED sign flips on a common episode clock -- keeps the grid's cross-cell
# correlation, which a row permutation destroys (and a permutation leaves a
# Sharpe exactly unchanged anyway).
clock = sorted({(r["entry"], r["exit"]) for _, r in ep.iterrows()})
key = {k: i for i, k in enumerate(clock)}
mat = {}
for cid, grp in ep.groupby("cell_id"):
    if len(grp) < 5:
        continue
    v = np.zeros(len(clock))
    m = np.zeros(len(clock), dtype=bool)
    for _, r in grp.iterrows():
        i = key[(r["entry"], r["exit"])]
        v[i] += r["pnl_usd"]
        m[i] = True
    mat[cid] = (v, m)
nullmax = np.empty(DRAWS)
for d in range(DRAWS):
    flip = rng.choice([-1.0, 1.0], size=len(clock))
    b = -np.inf
    for cid, (v, m) in mat.items():
        x = (v * flip)[m]
        sd = x.std(ddof=1)
        if sd > 0:
            b = max(b, x.mean() / sd)
    nullmax[d] = b
pval = float((nullmax >= obs_best).mean())
print(f"shared sign-flip null over {DRAWS} draws: null max mean "
      f"{nullmax.mean():.4f}, 95th {np.quantile(nullmax, 0.95):.4f}; "
      f"family-wise p = {pval:.4f}")

try:
    from RVUtils.StatisticalFinance.deflated_sharpe import deflated_sharpe_of_best
    trials = [v for v in by_cell.values() if len(v) >= 5]
    d = deflated_sharpe_of_best(trials)
    print(f"deflated Sharpe of the best: {json.dumps({k: (round(v, 5) if isinstance(v, float) else v) for k, v in d.items() if not isinstance(v, (list, np.ndarray))})}")
except Exception as exc:                                       # noqa: BLE001
    print(f"deflated_sharpe_of_best unavailable: {type(exc).__name__}: {exc}")

# ---------------------------------------------------------------------------
sec("6. Placebo: the same cells with the signal lagged +20 bd")
# ---------------------------------------------------------------------------
from dataclasses import replace as _replace  # noqa: E402

top = list(best["cell_id"].head(6))
spec_by_id = {c.cell_id: c for c in cells}
rows = []
for cid in top:
    sp = spec_by_id[cid]
    lag = _replace(sp, cfg=GS.SignalConfig(**{**sp.cfg.__dict__,
                                              "signal_lag_bd": 20}))
    r = GG.run_cell(lag, CA, LEGS, halflives=HL)
    s = GG.grid_stats_frame([r], span_years=SPAN_Y).iloc[0]
    base = st[st["cell_id"] == cid].iloc[0]
    rows.append({"cell_id": cid, "net_base": base["net_0.0"],
                 "sharpe_base": base["sharpe_0.0"],
                 "net_lag20": s["net_0.0"], "sharpe_lag20": s["sharpe_0.0"],
                 "n_ep_base": base["n_episodes"], "n_ep_lag": s["n_episodes"]})
pl = pd.DataFrame(rows)
print(pl.round(3).to_string(index=False))
pl.to_parquet(DATA / "p2_grid_placebo.parquet")

# ---------------------------------------------------------------------------
sec("7. Control: the blackout OFF must reproduce the roll artifact")
# ---------------------------------------------------------------------------
rows = []
for cid in top[:4]:
    sp = spec_by_id[cid]
    on = st[st["cell_id"] == cid].iloc[0]
    off = GG.grid_stats_frame(
        [GG.run_cell(sp, CA, LEGS, halflives=HL, blackout=False)],
        span_years=SPAN_Y).iloc[0]
    rows.append({"cell_id": cid, "n_ep_on": on["n_episodes"],
                 "n_ep_off": off["n_episodes"],
                 "net_on": on["net_0.0"], "net_off": off["net_0.0"],
                 "sharpe_on": on["sharpe_0.0"], "sharpe_off": off["sharpe_0.0"]})
bo = pd.DataFrame(rows)
print(bo.round(3).to_string(index=False))
print("\nand the raw artifact, priced: a $100k-DV01 long-CA book held through "
      "every roll, blackout off")
for lab in ("GREENS", "BLUES", "GOLDS"):
    s = CA[U.ca_col(lab)].dropna()
    rolls = [d for d in U.ca_roll_dates(s.index)]
    jump = s.diff().reindex(rolls).dropna()
    print(f"  {lab:7s} {len(jump)} rolls x mean {jump.mean():+.3f} bp = "
          f"{jump.sum() * 100_000:+,.0f} USD of pure label-switching")

# ---------------------------------------------------------------------------
sec("8. Convexity signature -- a point prediction, not a shape (A3.4)")
# ---------------------------------------------------------------------------
rows = []
for cid in top[:6]:
    sp = spec_by_id[cid]
    nv = LEGS[GG.vol_bench_col(sp.structure)].astype(float)
    w = U.time_weight_series(IDX, sp.structure)
    sub = ep[ep["cell_id"] == cid]
    if len(sub) < 8:
        continue
    dsig, pnl = [], []
    for _, r in sub.iterrows():
        try:
            a = float(nv.loc[r["entry"]]); b = float(nv.loc[r["exit"]])
        except KeyError:
            continue
        dsig.append(b - a)
        pnl.append(r["pnl_usd"])
    if len(dsig) < 8:
        continue
    x = np.asarray(dsig); y = np.asarray(pnl)
    X = np.column_stack([np.ones(len(x)), x, x * x])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ b
    r2 = 1 - resid.var(ddof=0) / y.var(ddof=0) if y.var(ddof=0) > 0 else np.nan
    ca_dv01 = float(sub["ca_dv01"].mean())
    predicted = ca_dv01 * float(w.mean()) / 2e4
    rows.append({"cell_id": cid, "n": len(x), "lin_usd_per_bpyr": b[1],
                 "quad_usd_per_bpyr2": b[2], "predicted_quad": predicted,
                 "ratio": b[2] / predicted if predicted else np.nan, "r2": r2})
cx = pd.DataFrame(rows)
print(cx.round(4).to_string(index=False) if len(cx) else "no cell had enough episodes")
if len(cx):
    cx.to_parquet(DATA / "p2_grid_convexity.parquet")

summary = {
    "n_cells": len(cells), "n_headline": int(head.shape[0]),
    "n_episodes": int(len(ep)), "span_years": SPAN_Y,
    "median_n_eff": n_eff_med,
    "best_sharpe_gross": float(scored["sharpe_0.0"].max()),
    "best_cell": str(scored.sort_values("sharpe_0.0", ascending=False).iloc[0]["cell_id"]),
    "best_per_obs_sharpe": obs_best, "signflip_p": pval,
    "emax_perhold_grid": GG.null_bars(len(cells), n_eff=n_eff_med, span_years=SPAN_Y)["emax_perhold"],
    "emax_ann_grid": GG.null_bars(len(cells), n_eff=n_eff_med, span_years=SPAN_Y)["emax_annualised"],
    "cells_positive_gross": pos, "cells_positive_residual": posr,
    "cells_scored": int(len(cs)),
}
(DATA / "p2_grid_summary.json").write_text(json.dumps(summary, indent=1))
print(f"\nwrote {DATA / 'p2_grid_summary.json'}")
print(json.dumps(summary, indent=1))

r"""The control battery of the Citi-framework pre-registration, §8 and §9.

Nothing here is a scored cell.  Each of these is a control ON a cell already
scored, and every one is declared in the pre-registration before the grid ran.

  1. same-day fills          exec_lag_bd 0 vs 1 -- the gap IS the mark-noise
                             harvest, and it must be positive
  2. placebo ladder          +0/10/20/40/60 bd -- a TIMING signal must die
  3. always-short control    the same structure and hedge with the signal
                             switched off, held for the same mean duration
  4. beta = 0                does the fly leg contribute at all
  5. the splice control      with the splice off, a book must pick up the
                             measured +0.95 bp/roll BLUES artifact
  6. sign-flip null          a row permutation cannot test a Sharpe
  7. convexity signature     the quadratic coefficient is a POINT prediction,
                             ``CA_DV01 * w / 2e4`` USD per (bp/yr)^2
  8. sub-period split        first half vs second half
  9. sensitivities           the knobs of §9, on the cells that trade

Output: notebooks/data/convexity_rv/p4_controls_*.parquet + p4_controls.json
"""
from __future__ import annotations

import json
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
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_rows", 200)

from RVUtils.ConvexityRV import citi_rule as R  # noqa: E402
from RVUtils.ConvexityRV import citi_screen as SC  # noqa: E402
from RVUtils.ConvexityRV.gv_sizing import roll_spliced  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
P = pd.read_parquet(DATA / "p4_citi.parquet")
P.index = pd.to_datetime(P.index)
S = SC.build_screen(P)
PRE = json.loads((DATA / "p4_preflight.json").read_text())
SPAN = float(PRE["span_tradeable_years"])
ANN = 252.0
OUT: dict = {}
BY_ID = {c.cell_id: c for c in R.declared_cells()}

#: The cells the battery is run on: the headline, and every cell at the rung
#: that trades.  Declared, not picked by result.
TARGETS = [
    "P|z2.0|screen_best|fitted_refit",
    "P|z1.0|screen_best|fitted_refit",
    "P|z1.0|screen_best|citi_2017",
    "P|z1.0|screen_best|unhedged",
    "P|z1.0|blues|fitted_refit",
    "S|z1.0|screen_best_all5|citi_2017",
]


def sec(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def sharpe(d: pd.Series) -> float:
    d = pd.Series(d).astype(float)
    if len(d[d != 0.0]) < 3 or d.std(ddof=1) == 0:
        return float("nan")
    return float(d.mean() / d.std(ddof=1) * np.sqrt(ANN))


def run(cfg: R.RuleConfig):
    ctx = R.build_contexts(P, S, cfg)
    eps = R.episodes_from_contexts(ctx, cfg, panel=P)
    g = R.book_daily(eps, ctx, cfg, index=P.index, cost_mult=0.0)
    n = R.book_daily(eps, ctx, cfg, index=P.index, cost_mult=1.0)
    per = [float(R.episode_daily_pnl(e, ctx[e.structure], cfg).sum())
           for e in eps]
    return ctx, eps, g, n, per


BASE = {}
for cid in TARGETS:
    BASE[cid] = run(BY_ID[cid].config())
    _, eps, g, n, _ = BASE[cid]
    print(f"{cid:40s} {len(eps):3d} episodes  gross ${g.sum():>12,.0f}  "
          f"net ${n.sum():>12,.0f}  SR_net {sharpe(n):+.4f}")

# ---------------------------------------------------------------------------
sec("1. Same-day fills -- the mark-noise harvest")
# ---------------------------------------------------------------------------
rows = []
for cid in TARGETS:
    for lag in (0, 1):
        base = BY_ID[cid].config()
        cfg = R.RuleConfig(**{**base.__dict__, "exec_lag_bd": lag})
        _, eps, g, n, _ = run(cfg)
        rows.append({"cell_id": cid, "exec_lag_bd": lag, "n_episodes": len(eps),
                     "gross_usd": float(g.sum()), "net_usd": float(n.sum()),
                     "sharpe_gross": sharpe(g)})
L1 = pd.DataFrame(rows)
W = L1.pivot(index="cell_id", columns="exec_lag_bd", values="gross_usd")
W["harvest_usd"] = W[0] - W[1]
print(W.round(0).to_string())
print("\nA POSITIVE harvest is the expected direction: entering at the mark the "
      "signal was computed from banks a reversion nobody can trade.  A negative "
      "one says the signal is not selecting on the mark's own noise.")
OUT["same_day"] = json.loads(L1.to_json(orient="records"))
L1.to_parquet(DATA / "p4_controls_execlag.parquet")

# ---------------------------------------------------------------------------
sec("2. Placebo ladder -- a timing signal must die under lag")
# ---------------------------------------------------------------------------
rows = []
for cid in TARGETS:
    base = BY_ID[cid].config()
    for lag in (0, 10, 20, 40, 60):
        cfg = R.RuleConfig(**{**base.__dict__, "signal_lag_bd": lag})
        _, eps, g, n, _ = run(cfg)
        rows.append({"cell_id": cid, "signal_lag_bd": lag,
                     "n_episodes": len(eps), "gross_usd": float(g.sum()),
                     "sharpe_gross": sharpe(g), "net_usd": float(n.sum())})
L2 = pd.DataFrame(rows)
print(L2.pivot(index="cell_id", columns="signal_lag_bd",
               values="sharpe_gross").round(4).to_string())
print("\ngross $ at each lag:")
print(L2.pivot(index="cell_id", columns="signal_lag_bd",
               values="gross_usd").round(0).to_string())
OUT["placebo"] = json.loads(L2.to_json(orient="records"))
L2.to_parquet(DATA / "p4_controls_placebo.parquet")

# ---------------------------------------------------------------------------
sec("3. Always-short control -- how much of the book is a static position?")
# ---------------------------------------------------------------------------
# The same structures and hedge, the SIGNAL SWITCHED OFF: enter on the first
# defined date, hold for the cell's own mean duration, re-enter, repeat.
rows = []
for cid in TARGETS:
    ctx, eps, g, n, _ = BASE[cid]
    if not eps:
        continue
    cfg = BY_ID[cid].config()
    hold = max(1, int(round(np.mean([e.hold_bd for e in eps]))))
    idx = P.index
    for lab in sorted({e.structure for e in eps}):
        c = ctx[lab]
        ok = c.all_ok.index[np.isfinite(c.beta) & np.isfinite(c.rich_bp)]
        if len(ok) < hold + 2:
            continue
        start = int(idx.get_loc(ok[0]))
        tot, k = 0.0, 0
        u = R.episode_daily_pnl
        while start + hold + 1 < len(idx):
            ep = R.CitiEpisode(lab, idx[start], idx[start + 1],
                               idx[start + hold], idx[start + hold + 1],
                               cfg.side, cfg.ca_dv01,
                               float(c.beta.get(idx[start], np.nan)),
                               float(c.w2.get(idx[start], np.nan)),
                               float(c.w10.get(idx[start], np.nan)),
                               "always")
            if np.isfinite(ep.beta_entry):
                tot += float(u(ep, c, cfg).sum())
                k += 1
            start += hold + 1
        rows.append({"cell_id": cid, "structure": lab, "hold_bd": hold,
                     "n_static_trades": k, "static_gross_usd": tot,
                     "per_trade_usd": tot / k if k else np.nan})
L3 = pd.DataFrame(rows)
print(L3.round(1).to_string(index=False))
cmp3 = []
for cid in TARGETS:
    _, eps, g, _, _ = BASE[cid]
    st = L3[L3.cell_id == cid]
    if not len(eps) or st.empty:
        continue
    per_signal = float(g.sum()) / len(eps)
    per_static = float(st["per_trade_usd"].mean())
    cmp3.append({"cell_id": cid, "per_signal_trade_usd": per_signal,
                 "per_static_trade_usd": per_static,
                 "signal_edge_usd": per_signal - per_static})
C3 = pd.DataFrame(cmp3)
print("\nper-trade, signal versus static (same structures, same hold):")
print(C3.round(0).to_string(index=False))
OUT["always_short"] = json.loads(C3.to_json(orient="records"))
L3.to_parquet(DATA / "p4_controls_static.parquet")

# ---------------------------------------------------------------------------
sec("4. beta = 0 -- does the fly leg contribute?")
# ---------------------------------------------------------------------------
rows = []
for cid in TARGETS:
    base = BY_ID[cid].config()
    if base.hedge == "unhedged":
        continue
    _, eps_h, g_h, n_h, _ = BASE[cid]
    cfg0 = R.RuleConfig(**{**base.__dict__, "hedge": "unhedged"})
    _, eps_0, g_0, n_0, _ = run(cfg0)
    rows.append({"cell_id": cid, "n_hedged": len(eps_h), "n_beta0": len(eps_0),
                 "gross_hedged": float(g_h.sum()),
                 "gross_beta0": float(g_0.sum()),
                 "sharpe_hedged": sharpe(g_h), "sharpe_beta0": sharpe(g_0),
                 "hedge_adds_sharpe": sharpe(g_h) - sharpe(g_0)})
L4 = pd.DataFrame(rows)
print(L4.round(4).to_string(index=False))
OUT["beta_zero"] = json.loads(L4.to_json(orient="records"))
L4.to_parquet(DATA / "p4_controls_beta0.parquet")

# ---------------------------------------------------------------------------
sec("5. The splice control -- switching it off must show the roll artifact")
# ---------------------------------------------------------------------------
rolls = list(P.index[P["is_ca_roll"].astype(bool)])
rows = []
for lab in R.PRIMARY_UNIVERSE:
    raw = P[f"{lab.lower()}_ca_bp"].astype(float)
    spl = roll_spliced(raw, rolls)
    rows.append({"structure": lab,
                 "raw_mean_dCA_on_roll": float(raw.diff().loc[rolls].mean()),
                 "spliced_mean_dCA_on_roll": float(spl.diff().loc[rolls].mean()),
                 "n_rolls": len(rolls)})
L5 = pd.DataFrame(rows).set_index("structure")
print(L5.round(6).to_string())
assert abs(float(L5["spliced_mean_dCA_on_roll"].abs().max())) < 1e-9
assert float(L5.loc["BLUES", "raw_mean_dCA_on_roll"]) > 0.8
print("\nThe splice is switched on: the raw series carries +0.95 bp/roll on "
      "BLUES and the spliced one carries exactly zero.  A P&L run on the raw "
      "series would book that jump as a LOSS for a short-CA book -- 22 times.")
rows = []
for cid in TARGETS:
    base = BY_ID[cid].config()
    for sp in (True, False):
        cfg = R.RuleConfig(**{**base.__dict__, "splice_pnl": sp})
        _, eps, g, n, _ = run(cfg)
        rows.append({"cell_id": cid, "splice_pnl": sp, "n_episodes": len(eps),
                     "gross_usd": float(g.sum()), "sharpe_gross": sharpe(g)})
L5b = pd.DataFrame(rows)
print("\nthe same books with the P&L splice off (i.e. booking the roll jump):")
print(L5b.pivot(index="cell_id", columns="splice_pnl",
                values="gross_usd").round(0).to_string())
OUT["splice"] = {"roll_artifact": json.loads(L5.reset_index().to_json(orient="records")),
                 "books": json.loads(L5b.to_json(orient="records"))}
L5b.to_parquet(DATA / "p4_controls_splice.parquet")

# ---------------------------------------------------------------------------
sec("6. Sign-flip null -- a row permutation cannot test a Sharpe")
# ---------------------------------------------------------------------------
rng = np.random.default_rng(20260824)
rows = []
N_DRAW = 20_000
for cid in TARGETS:
    _, eps, g, n, per = BASE[cid]
    a = np.asarray(per, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) < 3:
        rows.append({"cell_id": cid, "n_episodes": len(a), "t_obs": np.nan,
                     "p_signflip": np.nan})
        continue
    t_obs = float(a.mean() / (a.std(ddof=1) / np.sqrt(len(a))))
    flips = rng.choice([-1.0, 1.0], size=(N_DRAW, len(a)))
    sims = (a * flips)
    t_sim = sims.mean(axis=1) / (sims.std(axis=1, ddof=1) / np.sqrt(len(a)))
    rows.append({"cell_id": cid, "n_episodes": len(a), "t_obs": t_obs,
                 "p_signflip": float((t_sim >= t_obs).mean()),
                 "p_two_sided": float((np.abs(t_sim) >= abs(t_obs)).mean())})
L6 = pd.DataFrame(rows)
print(L6.round(4).to_string(index=False))
print(f"\n{N_DRAW:,} shared sign flips on the per-episode P&L.  At 4-23 "
      "episodes the smallest attainable one-sided p is 2^-n, so a p-value here "
      "is a bound on the evidence, not a measurement of it.")
OUT["signflip"] = json.loads(L6.to_json(orient="records"))
L6.to_parquet(DATA / "p4_controls_signflip.parquet")

# ---------------------------------------------------------------------------
sec("7. Convexity signature -- a POINT prediction, not a shape")
# ---------------------------------------------------------------------------
rows = []
for cid in TARGETS:
    ctx, eps, g, n, per = BASE[cid]
    if len(eps) < 4:
        continue
    d_sigma, pnl, pred = [], [], []
    for e, p in zip(eps, per):
        v = P[SC.VOL_COL[e.structure]].astype(float)
        w = P[f"{e.structure.lower()}_w"].astype(float)
        try:
            ds = float(v.loc[e.exit_fill] - v.loc[e.entry_fill])
        except KeyError:
            continue
        d_sigma.append(ds)
        pnl.append(float(p))
        pred.append(float(e.ca_dv01) * float(w.loc[e.entry_fill]) / 2e4)
    if len(d_sigma) < 4:
        continue
    x = np.asarray(d_sigma)
    y = np.asarray(pnl)
    X = np.column_stack([np.ones(len(x)), x, x ** 2])
    c, *_ = np.linalg.lstsq(X, y, rcond=None)
    rows.append({"cell_id": cid, "n": len(x), "quad_coef_fitted": float(c[2]),
                 "quad_coef_predicted": float(np.mean(pred)),
                 "linear_coef": float(c[1]),
                 "ratio": float(c[2] / np.mean(pred)) if np.mean(pred) else np.nan})
L7 = pd.DataFrame(rows)
print(L7.round(4).to_string(index=False) if len(L7) else "  too few episodes")
print("\nThe prediction is CA_DV01 * w / 2e4 USD per (bp/yr)^2 -- the CA is "
      "exactly quadratic in sigma, so a convexity claim has a NUMBER attached "
      "and not merely a U-shape.  At this episode count the fit is a three-"
      "parameter regression on 4-23 points and cannot confirm or deny it; the "
      "ratio is reported so the order of magnitude is on the record.")
OUT["convexity_signature"] = json.loads(L7.to_json(orient="records")) if len(L7) else []
if len(L7):
    L7.to_parquet(DATA / "p4_controls_signature.parquet")

# ---------------------------------------------------------------------------
sec("8. Sub-period split")
# ---------------------------------------------------------------------------
mid = P.index[len(P) // 2]
rows = []
for cid in TARGETS:
    _, eps, g, n, _ = BASE[cid]
    for tag, sl in (("first", slice(None, mid)), ("second", slice(mid, None))):
        gg, nn = g.loc[sl], n.loc[sl]
        rows.append({"cell_id": cid, "half": tag,
                     "n_episodes": sum(1 for e in eps
                                       if (e.entry_fill <= mid) == (tag == "first")),
                     "gross_usd": float(gg.sum()), "net_usd": float(nn.sum()),
                     "sharpe_gross": sharpe(gg)})
L8 = pd.DataFrame(rows)
print(f"split at {mid.date()}")
print(L8.pivot(index="cell_id", columns="half",
               values=["n_episodes", "gross_usd"]).round(0).to_string())
OUT["subperiod"] = json.loads(L8.to_json(orient="records"))
L8.to_parquet(DATA / "p4_controls_subperiod.parquet")

# ---------------------------------------------------------------------------
sec("9. Sensitivities -- reported, not scored")
# ---------------------------------------------------------------------------
rows = []
HEAD = "P|z1.0|screen_best|fitted_refit"
base = BY_ID[HEAD].config()
for knob, values in (("impl_rlzd_min", (1.0, 1.3, 1.5)),
                     ("z_pos_min", (0.0, 1.0, 1.5)),
                     ("max_hold_bd", (63, 126, 189)),
                     ("fit_window_bd", (252, 504, 756)),
                     ("splice_signal", (False, True)),
                     ("splice_pnl", (True, False))):
    for v in values:
        cfg = R.RuleConfig(**{**base.__dict__, knob: v})
        _, eps, g, n, _ = run(cfg)
        rows.append({"knob": knob, "value": str(v), "n_episodes": len(eps),
                     "gross_usd": float(g.sum()), "net_usd": float(n.sum()),
                     "sharpe_gross": sharpe(g), "sharpe_net": sharpe(n)})
L9 = pd.DataFrame(rows)
print(f"on {HEAD}:")
print(L9.round(4).to_string(index=False))
OUT["sensitivity"] = json.loads(L9.to_json(orient="records"))
L9.to_parquet(DATA / "p4_controls_sensitivity.parquet")

(DATA / "p4_controls.json").write_text(json.dumps(OUT, indent=1))
print(f"\nwrote {DATA / 'p4_controls.json'} and eight parquet siblings")

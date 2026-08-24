r"""GV block: the adversarial pass on the grid's top cells.

The grid's best cells sit on 9-12 episodes over 5.6 years.  At that sample size
almost any plausible number can be produced by a level trend, so the burden is
on the cells, not on the reader.  Six controls, in increasing order of how badly
they hurt:

  1. **Side and epoch.** Where is the P&L, and is the book systematically on
     one side?  The CA fell from ~23 bp (GOLDS, 2022-09) to ~6 bp (2026-05); a
     book that is short more often than long earns that decline for free.
  2. **Always-short / always-long controls.** Buy-and-hold inside every segment,
     no signal at all.  If always-short earns most of the cell's P&L, the signal
     is decoration.
  3. **Episode concentration.** Top-1 and top-3 episode share of gross.
  4. **Sub-period split.** 2021-2023 vs 2024-2026, on the same rule.
  5. **The honest n_eff and the null bar it implies** -- ``min(episodes,
     span*252/hold)``, not the always-invested clock.
  6. **The mark-quality cross-check** -- the top cells' structures against
     their own measured noise ratio and roll behaviour.

Output: printed report + notebooks/data/convexity_rv/p2_adversarial_*.parquet
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import sys

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
SEGS = U.roll_segments(IDX)
CA_DV01 = U.CA_DV01_DEFAULT
ANN = 252.0

st = pd.read_parquet(DATA / "p2_grid_stats.parquet")
ep = pd.read_parquet(DATA / "p2_grid_episodes.parquet")
cells = {c.cell_id: c for c in GG.declared_cells()}


def sec(t: str) -> None:
    print(f"\n{'=' * 80}\n{t}\n{'=' * 80}")


def sharpe(d: pd.Series) -> float:
    d = pd.Series(d).astype(float)
    if len(d[d != 0]) < 10 or d.std(ddof=1) == 0:
        return float("nan")
    return float(d.mean() / d.std(ddof=1) * math.sqrt(ANN))


scored = st[st["n_episodes"] >= 5].copy()
TOP = list(scored.sort_values("sharpe_0.0", ascending=False)["cell_id"].head(8))

# ---------------------------------------------------------------------------
sec("0. The CA's own trend -- what a one-sided book gets for free")
# ---------------------------------------------------------------------------
rows = []
for lab in ALL:
    s = CA[U.ca_col(lab)].dropna()
    rows.append({"structure": lab, "first": s.iloc[0], "max": s.max(),
                 "last": s.iloc[-1], "peak_to_last_bp": s.iloc[-1] - s.max(),
                 "first_to_last_bp": s.iloc[-1] - s.iloc[0],
                 "short_hold_usd": -(s.iloc[-1] - s.iloc[0]) * CA_DV01})
tr = pd.DataFrame(rows).set_index("structure")
print(tr.round(3).to_string())

# ---------------------------------------------------------------------------
sec("1. Side, epoch and concentration of the top cells")
# ---------------------------------------------------------------------------
rows = []
for cid in TOP:
    g = ep[ep["cell_id"] == cid].copy()
    if g.empty:
        continue
    g["year"] = pd.to_datetime(g["entry"]).dt.year
    tot = float(g["pnl_usd"].sum())
    srt = g["pnl_usd"].sort_values(ascending=False)
    rows.append({
        "cell_id": cid, "n": len(g),
        "n_short": int((g["side"] < 0).sum()), "n_long": int((g["side"] > 0).sum()),
        "short_pnl": float(g.loc[g["side"] < 0, "pnl_usd"].sum()),
        "long_pnl": float(g.loc[g["side"] > 0, "pnl_usd"].sum()),
        "top1_share": float(srt.iloc[0] / tot) if tot else np.nan,
        "top3_share": float(srt.iloc[:3].sum() / tot) if tot else np.nan,
        "pnl_2021_23": float(g.loc[g["year"] <= 2023, "pnl_usd"].sum()),
        "pnl_2024_26": float(g.loc[g["year"] >= 2024, "pnl_usd"].sum()),
        "total": tot,
    })
sd = pd.DataFrame(rows)
print(sd.round(3).to_string(index=False))
sd.to_parquet(DATA / "p2_adversarial_sides.parquet")

# ---------------------------------------------------------------------------
sec("2. ALWAYS-SHORT / ALWAYS-LONG controls -- no signal at all")
# ---------------------------------------------------------------------------
def hold_book(structure: str, leg_id, beta: float, side: int) -> dict:
    """Buy and hold inside every tradeable segment, no signal."""
    ca = CA[U.ca_col(structure)].dropna()
    leg = (U.leg_series(LEGS, leg_id, structure).reindex(ca.index)
           if leg_id else pd.Series(0.0, index=ca.index))
    eps = [GS.Episode(a, b, side, beta, CA_DV01, 0.0, "segment_end", i)
           for i, (a, b) in enumerate(SEGS)]
    d = GS.book_daily(eps, ca, leg, leg_id=leg_id, index=ca.index, cost_mult=0.0)
    per = [float(GS.episode_pnl(e, ca, leg).sum()) for e in eps]
    return {"net": float(d.sum()), "sharpe": sharpe(d), "n": len(eps),
            "hit": float(np.mean(np.asarray(per) > 0))}


rows = []
for cid in TOP:
    sp = cells[cid]
    b = float(st.loc[st["cell_id"] == cid, "mean_abs_beta"].iloc[0])
    b = 0.0 if not np.isfinite(b) else b
    cell_net = float(st.loc[st["cell_id"] == cid, "net_0.0"].iloc[0])
    cell_sr = float(st.loc[st["cell_id"] == cid, "sharpe_0.0"].iloc[0])
    sh = hold_book(sp.structure, sp.leg_id, b, -1)
    lo = hold_book(sp.structure, sp.leg_id, b, +1)
    sh0 = hold_book(sp.structure, None, 0.0, -1)
    rows.append({"cell_id": cid, "cell_net": cell_net, "cell_sharpe": cell_sr,
                 "always_short_net": sh["net"], "always_short_sharpe": sh["sharpe"],
                 "always_long_net": lo["net"],
                 "shortCA_only_net": sh0["net"], "shortCA_only_sharpe": sh0["sharpe"],
                 "signal_adds_usd": cell_net - sh["net"],
                 "signal_share": 1.0 - (sh["net"] / cell_net) if cell_net else np.nan})
ctl = pd.DataFrame(rows)
print(ctl.round(3).to_string(index=False))
ctl.to_parquet(DATA / "p2_adversarial_controls.parquet")
print("\nread: `always_short_net` uses the SAME structure, leg and beta, held "
      "through every tradeable segment with the signal switched off.")

# ---------------------------------------------------------------------------
sec("3. Sub-period stability -- the same rule, split at 2024-01-01")
# ---------------------------------------------------------------------------
CUT = pd.Timestamp("2024-01-01")
rows = []
for cid in TOP:
    sp = cells[cid]
    r = GG.run_cell(sp, CA, LEGS, halflives=HL)
    d = r.daily_by_mult[0.0]
    a, b = d.loc[:CUT], d.loc[CUT:]
    rows.append({"cell_id": cid,
                 "net_early": float(a.sum()), "sharpe_early": sharpe(a),
                 "net_late": float(b.sum()), "sharpe_late": sharpe(b),
                 "sign_agree": (a.sum() > 0) == (b.sum() > 0)})
sub = pd.DataFrame(rows)
print(sub.round(3).to_string(index=False))
print(f"\nboth halves same sign on {int(sub['sign_agree'].sum())}/{len(sub)} top cells")
sub.to_parquet(DATA / "p2_adversarial_subperiod.parquet")

# ---------------------------------------------------------------------------
sec("4. The honest n_eff and the null bar it implies")
# ---------------------------------------------------------------------------
rows = []
n_tr = len(cells)
from RVUtils.StatisticalFinance.deflated_sharpe import expected_max_sharpe  # noqa: E402
for cid in TOP:
    r = st[st["cell_id"] == cid].iloc[0]
    n_ep = int(r["n_episodes"])
    bar_ep = expected_max_sharpe(n_tr, 1.0 / max(n_ep, 1))
    bar_ann = expected_max_sharpe(n_tr, 1.0 / SPAN_Y)
    g = ep[ep["cell_id"] == cid]["pnl_usd"].to_numpy(float)
    sr_obs = float(g.mean() / g.std(ddof=1)) if len(g) > 2 and g.std(ddof=1) > 0 else np.nan
    rows.append({"cell_id": cid, "n_episodes": n_ep,
                 "sharpe_ann": r["sharpe_0.0"], "bar_ann_298": bar_ann,
                 "clears_ann": r["sharpe_0.0"] > bar_ann,
                 "sr_per_episode": sr_obs, "bar_per_episode_298": bar_ep,
                 "clears_per_episode": sr_obs > bar_ep})
nb = pd.DataFrame(rows)
print(nb.round(4).to_string(index=False))
print(f"\ncells clearing the ANNUALISED bar: {int(nb['clears_ann'].sum())}/{len(nb)}; "
      f"clearing the PER-EPISODE bar: {int(nb['clears_per_episode'].sum())}/{len(nb)}")
nb.to_parquet(DATA / "p2_adversarial_nulls.parquet")

# ---------------------------------------------------------------------------
sec("5. Mark quality of the structures the top cells actually use")
# ---------------------------------------------------------------------------
noise = pd.read_parquet(DATA / "p2_premise_noise.parquet")
noise.index = [i.split()[1] if " " in str(i) else str(i)
               for i in noise.index]
roll = pd.read_parquet(DATA / "p2_premise_roll.parquet")
used = sorted({cells[c].structure for c in TOP})
q = pd.concat([noise.loc[used, ["ac1_full", "noise_ratio_full", "sigma_noise_burn"]],
               roll.loc[used, ["mean_on_roll_bp", "t", "ratio"]]], axis=1)
q["ca_sd_bp"] = [CA[U.ca_col(l)].std(ddof=1) for l in used]
q["tier"] = [U.structure_by_label(l).tier for l in used]
print(q.round(3).to_string())
print("\nstructures used by the top-8 cells, by tier: "
      f"{q['tier'].value_counts().to_dict()}")

# ---------------------------------------------------------------------------
sec("6. VERDICT INPUTS")
# ---------------------------------------------------------------------------
summary = {
    "top_cells": TOP,
    "n_top_using_secondary": int((q["tier"] == "secondary").sum()),
    "median_signal_share": float(ctl["signal_share"].median()),
    "n_signal_beats_always_short": int((ctl["signal_adds_usd"] > 0).sum()),
    "n_top": len(ctl),
    "n_subperiod_sign_agree": int(sub["sign_agree"].sum()),
    "n_clears_ann_bar": int(nb["clears_ann"].sum()),
    "n_clears_per_episode_bar": int(nb["clears_per_episode"].sum()),
}
(DATA / "p2_adversarial_summary.json").write_text(json.dumps(summary, indent=1))
print(json.dumps(summary, indent=1))

# ---------------------------------------------------------------------------
sec("7. Does the hedge leg do ANYTHING? the same rule with beta forced to 0")
# ---------------------------------------------------------------------------
# Declared as a DIAGNOSTIC (pre-reg amendment A4), not a scored cell: it asks
# whether the fly is contributing to the cells that survived, or whether they
# are CA mean-reversion books with a decorative second leg.
from dataclasses import replace as _replace  # noqa: E402

rows = []
for cid in TOP:
    sp = cells[cid]
    base = st[st["cell_id"] == cid].iloc[0]
    nofly = _replace(sp, sizing="none", leg_id=sp.leg_id)
    r = GG.run_cell(nofly, CA, LEGS, halflives=HL)
    s0 = GG.grid_stats_frame([r], span_years=SPAN_Y).iloc[0]
    rows.append({"cell_id": cid,
                 "net_with_fly": base["net_0.0"], "sharpe_with_fly": base["sharpe_0.0"],
                 "net_no_fly": s0["net_0.0"], "sharpe_no_fly": s0["sharpe_0.0"],
                 "n_ep_with": base["n_episodes"], "n_ep_no": s0["n_episodes"],
                 "fly_adds_usd": base["net_0.0"] - s0["net_0.0"]})
nf = pd.DataFrame(rows)
print(nf.round(3).to_string(index=False))
print(f"\nthe fly leg ADDS money on {int((nf['fly_adds_usd'] > 0).sum())}/{len(nf)} "
      "of the top cells")
nf.to_parquet(DATA / "p2_adversarial_nofly.parquet")

# ---------------------------------------------------------------------------
sec("8. Placebo ladder -- how stale can the signal be and still 'work'?")
# ---------------------------------------------------------------------------
rows = []
for cid in TOP[:5]:
    sp = cells[cid]
    row = {"cell_id": cid}
    for lag in (0, 5, 10, 20, 40, 60):
        lg = _replace(sp, cfg=GS.SignalConfig(
            **{**sp.cfg.__dict__, "signal_lag_bd": lag}))
        r = GG.run_cell(lg, CA, LEGS, halflives=HL)
        d = r.daily_by_mult[0.0]
        row[f"net_{lag}"] = float(d.sum())
        row[f"sr_{lag}"] = sharpe(d)
    rows.append(row)
pl = pd.DataFrame(rows)
print(pl.round(3).to_string(index=False))
print("\na TIMING signal must die as the lag grows.  A signal whose P&L survives "
      "a 40-60 bd lag is a slow LEVEL effect wearing a timing rule.")
pl.to_parquet(DATA / "p2_adversarial_placebo_ladder.parquet")

# ---------------------------------------------------------------------------
sec("9. Residual half-life -- is the traded object mean-reverting at all?")
# ---------------------------------------------------------------------------
rows = []
for cid in TOP:
    sp = cells[cid]
    ca = CA[U.ca_col(sp.structure)].dropna()
    ca_dn = S.denoise(ca, HL[U.ca_col(sp.structure)])
    leg = (U.leg_series(LEGS, sp.leg_id, sp.structure).reindex(ca.index)
           if sp.leg_id else pd.Series(0.0, index=ca.index))
    nv = LEGS[GG.vol_bench_col(sp.structure)].astype(float).reindex(ca.index)
    w = U.time_weight_series(ca.index, sp.structure)
    level = LEGS[GG.LEVEL_COL].astype(float).reindex(ca.index)
    slope = ((LEGS[GG.SLOPE_COLS[1]].astype(float)
              - LEGS[GG.SLOPE_COLS[0]].astype(float)) * 100.0).reindex(ca.index)
    b, _ = S.sizing_beta(sp.sizing, S.SizingInputs(
        ca=ca, ca_denoised=ca_dn, leg=leg, nvol=nv, w=w,
        level=level, slope=slope))
    spread = (ca_dn - b.fillna(0.0) * leg).dropna()
    for freq, x in (("daily", spread), ("weekly", spread.resample("W-WED").last().dropna())):
        y = x.diff().dropna()
        xx = x.shift(1).reindex(y.index)
        j = pd.concat([y.rename("y"), xx.rename("x")], axis=1).dropna()
        if len(j) < 50:
            continue
        bb = float(j["y"].cov(j["x"]) / j["x"].var(ddof=1))
        hl = float(-math.log(2) / math.log(1 + bb)) if -2 < bb < 0 else np.nan
        rows.append({"cell_id": cid, "freq": freq, "ar_coef": 1 + bb,
                     "halflife_periods": hl, "n": len(j)})
hl_df = pd.DataFrame(rows)
print(hl_df.round(4).to_string(index=False))
hl_df.to_parquet(DATA / "p2_adversarial_halflife.parquet")

r"""GV block, measurement 1: **is a swap butterfly a volatility proxy at all?**

The brief's premise is "swap butterflies are vol proxies in linear space".  That
is a testable claim about the leg, and it decides whether a vega-matched hedge
is even definable -- ``vega_match`` divides by ``dleg/dsigma``, so a noise-sized
slope there is an unbounded hedge, not a small one.

Also produces, in one pass and before any backtest:

  * the CA panel tie-out (a copied artifact is a hypothesis until re-priced);
  * the noise decomposition and derived denoise half-lives (pre-reg A1);
  * the two roll clocks and the size of the artifact they create (M3);
  * the vega / theta / variance table per structure (M4, A3.2);
  * the **before/after hedge-notional table** -- the direct answer to
    "was it sizing";
  * level-vs-change betas per (structure, leg), the M1 sign defect at full sample.

Output: notebooks/data/convexity_rv/p2_premise_*.parquet + a printed report.
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
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

from RVUtils.ConvexityRV import gv_grid as GG  # noqa: E402
from RVUtils.ConvexityRV import gv_sizing as S  # noqa: E402
from RVUtils.ConvexityRV import gv_universe as U  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
CA = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
LEGS = pd.read_parquet(DATA / "p2_legs.parquet")
LEGS.index = pd.to_datetime(LEGS.index)
IDX = CA.index.intersection(LEGS.index)
CA, LEGS = CA.loc[IDX], LEGS.loc[IDX]
ALL = list(U.PRIMARY_STRUCTURES) + list(U.SECONDARY_STRUCTURES)

print(f"CA panel {CA.shape}  legs {LEGS.shape}  common dates {len(IDX)} "
      f"{IDX.min().date()}..{IDX.max().date()}")


def sec(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


# ---------------------------------------------------------------------------
sec("0. CA panel tie-out -- the copied artifact, re-priced")
# ---------------------------------------------------------------------------
try:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from TB.IRSwapsTB import IRSwapsTB

    rng = np.random.default_rng(20260824)
    sample = sorted(pd.DatetimeIndex(rng.choice(IDX, size=6, replace=False)))
    tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
    rows = []
    for d in sample:
        got = tb.sfr_cvx_adj(["GREENS", "BLUES", "GOLDS"], d.date(), d.date())
        for lab in ("GREENS", "BLUES", "GOLDS"):
            c = U.ca_col(lab)
            fresh = float(got[c].iloc[0]) if c in got.columns and len(got) else np.nan
            rows.append({"date": d.date(), "label": lab,
                         "panel": float(CA.loc[d, c]), "fresh": fresh})
    tie = pd.DataFrame(rows)
    tie["diff"] = tie["fresh"] - tie["panel"]
    print(tie.round(6).to_string(index=False))
    ok = tie["diff"].abs().max()
    print(f"\nmax |fresh - panel| = {ok:.8f} bp over {len(tie)} cells")
    print("VERDICT:", "panel confirmed" if ok < 1e-6 else "PANEL DISAGREES")
    tb.close()
except Exception as exc:                                        # noqa: BLE001
    print(f"tie-out could not run: {type(exc).__name__}: {exc}")

# ---------------------------------------------------------------------------
sec("1. Mark-noise decomposition and the derived denoise half-lives (A1)")
# ---------------------------------------------------------------------------
cols = [U.ca_col(l) for l in ALL]
hl_df = S.fit_denoise_halflives(CA, cols)
hl_df.index = [c.split()[1] for c in hl_df.index]
print(hl_df[["ac1_burn", "ac1_full", "sigma_true_burn", "sigma_noise_burn",
             "noise_ratio_burn", "noise_ratio_full", "snr_burn", "alpha",
             "halflife_bd", "pure_noise_full"]].round(4).to_string())
HALFLIVES = {U.ca_col(k): float(v) for k, v in hl_df["halflife_bd"].items()}
hl_df.to_parquet(DATA / "p2_premise_noise.parquet")

# ---------------------------------------------------------------------------
sec("2. The two roll clocks, and the artifact (M3)")
# ---------------------------------------------------------------------------
ca_roll = U.ca_roll_dates(IDX)
leg_roll = U.leg_roll_dates(IDX)
print(f"CA rolls {len(ca_roll)}   IMM_k leg rolls {len(leg_roll)}   "
      f"in common {len(set(ca_roll) & set(leg_roll))}")
bo = U.blackout_mask(IDX)
segs = U.roll_segments(IDX)
seglen = [IDX.get_loc(b) - IDX.get_loc(a) + 1 for a, b in segs]
print(f"blackout {int(bo.sum())}/{len(IDX)} dates ({100*bo.mean():.2f}%), "
      f"{len(segs)} tradeable segments, median {int(np.median(seglen))} bd "
      f"(min {min(seglen)}, max {max(seglen)})")
rows = []
rs = set(ca_roll)
for lab in ALL:
    d = CA[U.ca_col(lab)].dropna().diff().dropna()
    on = d[[t in rs for t in d.index]]
    off = d[[t not in rs for t in d.index]]
    t = float(on.mean() / (on.std(ddof=1) / np.sqrt(len(on)))) if len(on) > 2 else np.nan
    rows.append({"structure": lab, "n_roll": len(on),
                 "mean_on_roll_bp": on.mean(), "t": t,
                 "abs_on": on.abs().mean(), "abs_off": off.abs().mean(),
                 "ratio": on.abs().mean() / off.abs().mean()})
roll_df = pd.DataFrame(rows).set_index("structure")
print(roll_df.round(3).to_string())
roll_df.to_parquet(DATA / "p2_premise_roll.parquet")

# ---------------------------------------------------------------------------
sec("3. Vega, theta and the implied variance, per structure (M4 / A3.2)")
# ---------------------------------------------------------------------------
rows = []
for lab in ALL:
    ca = CA[U.ca_col(lab)].dropna()
    w = U.time_weight_series(ca.index, lab)
    t1m = U.mean_t1_series(ca.index, lab)
    nv = LEGS[GG.vol_bench_col(lab)].astype(float).reindex(ca.index)
    v = S.ca_implied_variance_bp2(ca, w)
    sig_ca = S.ca_implied_vol_bp(ca, w)
    vega = S.ca_vega_bp_per_bp(nv, w)
    theta = S.ca_theta_bp_per_year(nv, t1m)
    rows.append({
        "structure": lab, "bench": GG.VOL_BENCH[lab],
        "ca_mean_bp": ca.mean(), "ca_sd_bp": ca.std(ddof=1),
        "w_mean": w.mean(), "t1_mean": t1m.mean(),
        "sigma_ca_bp": sig_ca.mean(), "sigma_bench_bp": nv.mean(),
        "ca_neg_frac": float((ca <= 0).mean()),
        "vega_bp_per_bpyr": vega.mean(),
        "theta_bp_per_month": theta.mean() / 12.0,
        "theta_bp_per_quarter": theta.mean() / 4.0,
        "roll_jump_bp": roll_df.loc[lab, "mean_on_roll_bp"],
    })
vt = pd.DataFrame(rows).set_index("structure")
print(vt.round(4).to_string())
print("\nthe roll jump IS the theta paid back -- quarter decay vs measured jump:")
print((vt[["theta_bp_per_quarter", "roll_jump_bp"]]
       .assign(ratio=lambda d: -d["roll_jump_bp"] / d["theta_bp_per_quarter"])
       ).round(3).to_string())
vt.to_parquet(DATA / "p2_premise_vega.parquet")

# ---------------------------------------------------------------------------
sec("4. IS A BUTTERFLY A VOL PROXY? full-sample levels and changes, controlled")
# ---------------------------------------------------------------------------
level = LEGS[GG.LEVEL_COL].astype(float)
slope = (LEGS[GG.SLOPE_COLS[1]].astype(float)
         - LEGS[GG.SLOPE_COLS[0]].astype(float)) * 100.0
rows = []
for leg_id, spec in U.LEGS.items():
    structs = U.PRIMARY_STRUCTURES if spec.start == "immM" else ("BLUES",)
    for st in structs:
        lg = U.leg_series(LEGS, leg_id, st).dropna()
        nv = LEGS[GG.vol_bench_col(st)].astype(float).reindex(lg.index)
        j = pd.concat([lg.rename("y"), nv.rename("x")], axis=1).dropna()
        r_lvl = float(j["y"].corr(j["x"]))
        b_lvl = float(j["y"].cov(j["x"]) / j["x"].var(ddof=1))
        dj = j.diff().dropna()
        r_chg = float(dj["y"].corr(dj["x"]))
        b_chg = float(dj["y"].cov(dj["x"]) / dj["x"].var(ddof=1))
        n = len(lg)
        bc, tc, pr2 = S.rolling_vol_beta_controlled(lg, nv, level, slope,
                                                    window=n, min_periods=250)
        gate = ((tc.abs() >= S.VOL_BETA_T_MIN)
                & (pr2 >= S.VOL_BETA_PARTIAL_R2_MIN))
        bc_r, tc_r, pr2_r = S.rolling_vol_beta_controlled(lg, nv, level, slope,
                                                          window=252)
        gate_r = ((tc_r.abs() >= S.VOL_BETA_T_MIN)
                  & (pr2_r >= S.VOL_BETA_PARTIAL_R2_MIN))
        rows.append({
            "leg_id": leg_id, "struct": st if spec.start == "immM" else "-",
            "n": n, "leg_sd_bp": float(lg.std(ddof=1)),
            "beta_lvl": b_lvl, "r2_lvl": r_lvl ** 2,
            "beta_chg": b_chg, "r2_chg": r_chg ** 2,
            "beta_ctrl_full": float(bc.dropna().iloc[-1]) if bc.notna().any() else np.nan,
            "t_ctrl_full": float(tc.dropna().iloc[-1]) if tc.notna().any() else np.nan,
            "partial_r2_full": float(pr2.dropna().iloc[-1]) if pr2.notna().any() else np.nan,
            "gate_full": bool(gate.dropna().iloc[-1]) if gate.notna().any() else False,
            "roll_gate_pass": float(gate_r[tc_r.notna()].mean())
            if tc_r.notna().any() else np.nan,
            "roll_beta_median": float(bc_r.median()),
            "roll_beta_sd": float(bc_r.std(ddof=1)),
        })
vp = pd.DataFrame(rows)
print(vp.round(4).to_string(index=False))
vp.to_parquet(DATA / "p2_premise_volproxy.parquet")
print("\nVERDICT on the premise: legs whose FULL-SAMPLE controlled vol term "
      f"clears the gate: {int(vp['gate_full'].sum())}/{len(vp)}; "
      f"median rolling gate-pass fraction {vp['roll_gate_pass'].median():.3f}")

# ---------------------------------------------------------------------------
sec("5. M1 at full sample: level beta vs change beta, per (structure, leg)")
# ---------------------------------------------------------------------------
rows = []
for st in ALL:
    ca = CA[U.ca_col(st)].dropna()
    for leg_id, spec in U.LEGS.items():
        lg = U.leg_series(LEGS, leg_id, st).reindex(ca.index)
        j = pd.concat([ca.rename("y"), lg.rename("x")], axis=1).dropna()
        if len(j) < 200:
            continue
        b_l = float(j["y"].cov(j["x"]) / j["x"].var(ddof=1))
        r_l = float(j["y"].corr(j["x"]))
        dj = j.diff().dropna()
        b_c = float(dj["y"].cov(dj["x"]) / dj["x"].var(ddof=1))
        r_c = float(dj["y"].corr(dj["x"]))
        v0 = float(dj["y"].var(ddof=1))
        v_l = float((dj["y"] - b_l * dj["x"]).var(ddof=1))
        v_c = float((dj["y"] - b_c * dj["x"]).var(ddof=1))
        rows.append({"structure": st, "leg_id": leg_id, "n": len(j),
                     "beta_lvl": b_l, "r2_lvl": r_l ** 2,
                     "beta_chg": b_c, "r2_chg": r_c ** 2,
                     "sign_disagree": (b_l * b_c) < 0,
                     "var_ratio_lvl_hedge": v_l / v0,
                     "var_ratio_chg_hedge": v_c / v0})
m1 = pd.DataFrame(rows)
print(m1.round(4).to_string(index=False))
print(f"\nsign disagreement on {int(m1['sign_disagree'].sum())}/{len(m1)} pairs; "
      f"the level-beta hedge INCREASES daily variance on "
      f"{int((m1['var_ratio_lvl_hedge'] > 1).sum())}/{len(m1)}")
m1.to_parquet(DATA / "p2_premise_m1.parquet")

# ---------------------------------------------------------------------------
sec("6. THE SIZING ANSWER: hedge notional, incumbent vs vega-matched")
# ---------------------------------------------------------------------------
CA_DV01 = U.CA_DV01_DEFAULT
rows = []
for st in U.PRIMARY_STRUCTURES:
    ca = CA[U.ca_col(st)].dropna()
    w = U.time_weight_series(ca.index, st)
    nv = LEGS[GG.vol_bench_col(st)].astype(float).reindex(ca.index)
    ca_dn = S.denoise(ca, HALFLIVES[U.ca_col(st)])
    for leg_id, spec in U.LEGS.items():
        lg = U.leg_series(LEGS, leg_id, st).reindex(ca.index)
        inp = S.SizingInputs(ca=ca, ca_denoised=ca_dn, leg=lg, nvol=nv, w=w,
                             level=level.reindex(ca.index),
                             slope=slope.reindex(ca.index))
        out = {}
        for rule in S.SIZING_RULES:
            b, ok = S.sizing_beta(rule, inp)
            bb = b.where(ok)
            out[rule] = float(bb.abs().median()) if bb.notna().any() else np.nan
            out[rule + "_gate"] = float(ok.mean())
        rows.append({"structure": st, "leg_id": leg_id,
                     "beta_lvl": out["beta_lvl"], "beta_chg": out["beta_chg"],
                     "vega_match": out["vega_match"],
                     "vol_ratio": out["vol_ratio"],
                     "vega_gate_pass": out["vega_match_gate"],
                     "dv01_lvl": out["beta_lvl"] * CA_DV01,
                     "dv01_vega": out["vega_match"] * CA_DV01,
                     "ratio_vega_over_lvl": (out["vega_match"] / out["beta_lvl"])
                     if out["beta_lvl"] else np.nan})
sz = pd.DataFrame(rows)
print(sz.round(4).to_string(index=False))
sz.to_parquet(DATA / "p2_premise_sizing.parquet")
print("\nmedian |beta| by rule, over all (structure, leg) pairs:")
print(sz[["beta_lvl", "beta_chg", "vega_match", "vol_ratio"]].median().round(4).to_string())

summary = {
    "dates": len(IDX), "start": str(IDX.min().date()), "end": str(IDX.max().date()),
    "blackout_frac": float(bo.mean()), "n_segments": len(segs),
    "halflives": {k.split()[1]: v for k, v in HALFLIVES.items()},
    "vol_proxy_gate_full_pass": int(vp["gate_full"].sum()),
    "vol_proxy_n": len(vp),
    "m1_sign_disagree": int(m1["sign_disagree"].sum()), "m1_n": len(m1),
}
(DATA / "p2_premise_summary.json").write_text(json.dumps(summary, indent=1))
print(f"\nwrote {DATA / 'p2_premise_summary.json'}")

r"""Block 5 preflight -- everything measured BEFORE the pre-registration is frozen.

**No P&L is computed here and no cell is scored.**  This produces the numbers
§0 of ``docs/convexityrv/citi-framework-preregistration.md`` cites: the
distribution of each of the five entry conditions' own inputs, the fair-value
refit path on the wider 2021 window, the screen's identities, the roll
cross-check, and the tradeable span every null bar will be graded against.

Looking at the distribution of an INPUT before freezing a threshold is the same
thing block 4's pre-registration did in its §0 M1-M4; looking at a P&L is not,
and nothing here does.

Output: notebooks/data/convexity_rv/p4_preflight.json + a printed report.
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
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)

from RVUtils.ConvexityRV import citi_fv as FV  # noqa: E402
from RVUtils.ConvexityRV import citi_rule as R  # noqa: E402
from RVUtils.ConvexityRV import citi_screen as SC  # noqa: E402
from RVUtils.ConvexityRV import gv_sizing as GS  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
OUT: dict = {}
P = pd.read_parquet(DATA / "p4_citi.parquet")
P.index = pd.to_datetime(P.index)
print(f"panel {P.shape}  {P.index.min().date()}..{P.index.max().date()}")


def sec(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


# ---------------------------------------------------------------------------
sec("1. The screen, and the two identities the note's own table satisfies")
# ---------------------------------------------------------------------------
S = SC.build_screen(P)
ids = SC.verify_identities(S, P)
print(f"max |CA - Model - VsModel|          {ids['ca_minus_model_minus_vsmodel']:.3e} bp "
      f"({ids['n_cells_skipped_vsmodel']} cells skipped for a missing mark)")
print(f"max |implied^2*w/2e4 - CA|          {ids['implied_reconstructs_ca']:.3e} bp "
      f"({ids['n_cells_skipped_implied']} cells skipped: a non-positive CA has "
      "no real implied vol)")
assert ids["ca_minus_model_minus_vsmodel"] < 1e-9
assert ids["implied_reconstructs_ca"] < 1e-6
OUT["screen_identities"] = ids

last = P.index[-1]
print(f"\nFigure 20 analogue, close of {last.date()}:\n")
print(SC.screen_table(S, last).round(2).to_string())
print("\nCiti's H0-Z0 row (12-Jan-2017, ED): CA 10.02, VsModel 4.61, "
      "3m Roll 1.30, Implied 125.5, Realized 95.1, Impl/Rlzd 1.3")
OUT["screen_last_date"] = str(last.date())
OUT["screen_last_table"] = json.loads(
    SC.screen_table(S, last).reset_index().to_json(orient="records"))

print("\nthe roll column, two ways (analytic -theta/4 vs the term structure):")
RI = SC.roll_identity(S)
print(RI.round(4).to_string())
OUT["roll_identity"] = json.loads(RI.reset_index().to_json(orient="records"))

# ---------------------------------------------------------------------------
sec("2. The five entry conditions -- the distribution of each INPUT")
# ---------------------------------------------------------------------------
cfg = R.RuleConfig()
CTX = R.build_contexts(P, S, cfg, structures=SC.SCREEN_STRUCTURES)
rows = []
for lab, c in CTX.items():
    rows.append({
        "structure": lab,
        "z_model_p50": float(c.z_model.median()),
        "z_model_p95": float(c.z_model.quantile(0.95)),
        "frac_z_model_ge_2": float((c.z_model >= 2.0).mean()),
        "z_fly_p50": float(c.z_fly.median()),
        "z_fly_p95": float(c.z_fly.quantile(0.95)),
        "frac_z_fly_ge_2": float((c.z_fly >= 2.0).mean()),
        "roll_3m_p50": float(c.roll_3m.median()),
        "frac_roll_pos": float((c.roll_3m > 0).mean()),
        "impl_rlzd_p50": float(c.impl_rlzd.median()),
        "impl_rlzd_p95": float(c.impl_rlzd.quantile(0.95)),
        "frac_ir_ge_1_3": float((c.impl_rlzd >= 1.3).mean()),
        "frac_zpos_ge_1": float((c.z_pos >= 1.0).mean()),
    })
DIST = pd.DataFrame(rows).set_index("structure")
print(DIST.round(4).to_string())
OUT["condition_inputs"] = json.loads(DIST.reset_index().to_json(orient="records"))

print("\nthe conjunction, and which condition binds (primary universe):")
CTXP = {k: v for k, v in CTX.items() if k in R.PRIMARY_UNIVERSE}
B = R.condition_binding(CTXP, cfg)
print(B.round(4).to_string())
OUT["condition_binding"] = json.loads(B.reset_index().to_json(orient="records"))

any_ok = pd.concat([c.all_ok.rename(l) for l, c in CTXP.items()], axis=1)
n_open_days = int(any_ok.any(axis=1).sum())
print(f"\ndays on which SOME primary structure satisfies all five: {n_open_days} "
      f"of {len(P)} ({100 * n_open_days / len(P):.1f}%)")
OUT["days_conjunction_open"] = n_open_days

# ---------------------------------------------------------------------------
sec("3. The tradeable span every null bar is graded against")
# ---------------------------------------------------------------------------
first_ok = any_ok.any(axis=1)
first_true = first_ok.index[first_ok.to_numpy()][0] if first_ok.any() else None
# the first date the rule COULD open at all: the fair value, the z-scores and
# the realized-vol column must all exist
defined = pd.concat([
    np.isfinite(c.rich_bp) & np.isfinite(c.z_fly) & np.isfinite(c.z_model)
    & np.isfinite(c.impl_rlzd) & np.isfinite(c.z_pos)
    for c in CTXP.values()], axis=1).any(axis=1)
first_defined = defined.index[defined.to_numpy()][0]
span_full = (P.index.max() - P.index.min()).days / 365.25
span_trade = (P.index.max() - first_defined).days / 365.25
print(f"panel span            {span_full:.3f} y  ({P.index.min().date()}..{P.index.max().date()})")
print(f"first date the rule is DEFINED  {first_defined.date()}")
print(f"first date it could OPEN        {first_true.date() if first_true is not None else '-'}")
print(f"TRADEABLE span        {span_trade:.3f} y")
OUT["span_full_years"] = float(span_full)
OUT["span_tradeable_years"] = float(span_trade)
OUT["first_defined"] = str(first_defined.date())
OUT["first_open"] = str(first_true.date()) if first_true is not None else None

for n in (1, 8, 10, 15, 298):
    nb = R.null_bars(n, n_eff=8.0, span_years=span_trade)
    print(f"  E[max SR | null] at {n:3d} trials, span {span_trade:.2f}y:  "
          f"annualised {nb['emax_annualised']:.4f}   "
          f"per-hold (n_eff 8) {nb['emax_perhold']:.4f}")
OUT["null_bars"] = {str(n): R.null_bars(n, n_eff=8.0, span_years=span_trade)
                    for n in (1, 8, 10, 15, 298)}

# ---------------------------------------------------------------------------
sec("4. The fair value on the WIDER window -- does the mid-2023 flip survive?")
# ---------------------------------------------------------------------------
rolls = list(P.index[P["is_ca_roll"].astype(bool)])
print("The fit is on the RAW quoted CA, because that is what the rule fits: "
      f"RuleConfig.splice_signal = {cfg.splice_signal} and citi_rule."
      "build_contexts passes the raw series to the refit. An earlier version of "
      "this cell spliced it and reported a fair value that is never struck -- "
      "on BLUES that inverted the sign of b median and inflated the residual "
      "sd by 39-44%. The spliced path is printed beside it so the difference "
      "is visible rather than assumed.")
for lab in R.PRIMARY_UNIVERSE:
    raw = P[f"{lab.lower()}_ca_bp"].astype(float)
    ca = GS.roll_spliced(raw, rolls) if cfg.splice_signal else raw
    W, F = FV.imm_refit(ca, P, "fly", cfg.fit_window_bd, roll_dates=rolls)
    Ws, Fs = FV.imm_refit(GS.roll_spliced(raw, rolls), P, "fly",
                          cfg.fit_window_bd, roll_dates=rolls)
    ss = FV.refit_summary(Ws)
    rs = (GS.roll_spliced(raw, rolls) - Fs).dropna()
    s = FV.refit_summary(W)
    res = (ca - F).dropna()
    print(f"\n{lab}: {s['n_refits']} refits, w2 median {s['w2_median']:.2f} "
          f"(range {s['w2_range']:.2f}), b median {s['b_median']:+.2f}, "
          f"b sign flips {s['b_sign_flips']}, boundary w2 {s['n_boundary_w2']}")
    print(f"       OOS residual sd {res.std(ddof=1):.3f} bp, "
          f"mae {res.abs().mean():.3f} bp, first fitted {F.dropna().index[0].date()}")
    print(f"       [the spliced path, NOT traded: b median {ss['b_median']:+.2f}, "
          f"flips {ss['b_sign_flips']}, resid sd {rs.std(ddof=1):.3f} bp]")
    OUT.setdefault("fair_value", {})[lab] = {
        **s, "spliced_b_median": ss["b_median"],
        "spliced_b_sign_flips": ss["b_sign_flips"],
        "spliced_oos_resid_sd_bp": float(rs.std(ddof=1)),
        "oos_resid_sd_bp": float(res.std(ddof=1)),
        "oos_resid_mae_bp": float(res.abs().mean()),
        "first_fitted": str(F.dropna().index[0].date()),
        "b_path": [float(x) for x in W["b"]],
        "in_force_from": [str(pd.Timestamp(x).date()) for x in W["in_force_from"]],
    }

# ---------------------------------------------------------------------------
sec("5. The roll jump and the theta -- reproduced on the panel used here")
# ---------------------------------------------------------------------------
rows = []
for lab in SC.SCREEN_STRUCTURES:
    ca = P[f"{lab.lower()}_ca_bp"].astype(float)
    d = ca.diff()
    on = d.loc[[r for r in rolls if r in d.index]].dropna()
    off = d.drop(on.index).dropna()
    th = -(P[SC.VOL_COL[lab]].astype(float) ** 2
           * P[f"{lab.lower()}_t1mean"].astype(float) / 1e4)
    rows.append({"structure": lab, "n_rolls": int(len(on)),
                 "mean_dCA_on_roll": float(on.mean()),
                 "t_on_roll": float(on.mean() / (on.std(ddof=1) / np.sqrt(len(on)))),
                 "mean_abs_off_roll": float(off.abs().mean()),
                 "theta_bp_per_month": float(th.mean() / 12.0),
                 "quarter_theta_bp": float(-th.mean() / 4.0)})
J = pd.DataFrame(rows).set_index("structure")
J["jump_over_quarter_theta"] = J["mean_dCA_on_roll"] / J["quarter_theta_bp"]
print(J.round(4).to_string())
OUT["roll_jump"] = json.loads(J.reset_index().to_json(orient="records"))

(DATA / "p4_preflight.json").write_text(json.dumps(OUT, indent=1))
print(f"\nwrote {DATA / 'p4_preflight.json'}")

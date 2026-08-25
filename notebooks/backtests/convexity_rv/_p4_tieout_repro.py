r"""Known-answer tie-out: ``citi_fv`` against the reproduction it was promoted from.

``notebooks/backtests/convexity_rv/citi_blues_ca_repro.py`` grew the fitting
machinery inside notebook cells (``_fit_on``, ``_combo``, ``imm_refit``,
``FLY_STARTS``).  A backtest cannot import from a notebook, so it moved to
``RVUtils/ConvexityRV/citi_fv.py`` -- and a promoted module is only a promotion
if it reproduces the path it was lifted from, on that path's own window, to the
last decimal.

The recorded answers this asserts against, all from the executed reproduction
(SOFR, 2022-01-03..2026-08-21, fly-constrained, 504 bd, spot 2y/5y/10y):

* the fitted scale ``b`` REVERSES SIGN once, in mid-2023, and ``w2`` moves from
  one wing to the other at the same refit (0.05 -> 0.95, b +19.1 -> -7.6);
* Citi's fixed 2017 Eurodollar weights give the LOWEST out-of-sample residual
  sd (2.149 bp), ahead of the IMM-roll fly-constrained refit (2.232 bp);
* the refit wins on mean absolute residual (1.674 vs 1.892 bp) and on bias;
* fly starts rank monotone in how far forward they start -- spot best at
  2.232 bp, IMM_13 (the matched-expiry case) 3.396 bp, 9th of 10.

Output: notebooks/data/convexity_rv/p4_tieout_repro.json
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
pd.set_option("display.max_columns", 40)

from RVUtils.ConvexityRV import citi_fv as FV  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
#: The reproduction's own window and knob, verbatim.
START, END, WINDOW_BD = "2022-01-03", "2026-08-21", 504
OUT: dict = {"window": [START, END], "fit_window_bd": WINDOW_BD}

P = pd.read_parquet(DATA / "p3_citi_repro.parquet")
P = P.loc[(P.index >= START) & (P.index <= END)]
print(f"{len(P)} dates {P.index.min().date()}..{P.index.max().date()}")
assert len(P) == 1159, f"the reproduction ran on 1,159 dates, this has {len(P)}"

Y = P["blues_ca_bp"]


def sec(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


# ---------------------------------------------------------------------------
sec("1. The fly-constrained quarterly refit -- and the mid-2023 sign reversal")
# ---------------------------------------------------------------------------
W6F, FIT6F = FV.imm_refit(Y, P, "fly", WINDOW_BD)
print(W6F[["in_force_from", "w2", "w10", "a", "b", "r2", "n"]].round(3).to_string())
S = FV.refit_summary(W6F)
print(f"\n{S}")
flip_at = W6F.index[int(np.argmax(np.sign(W6F["b"]).diff().abs().fillna(0).to_numpy()))]
print(f"\nb changes sign at the {pd.Timestamp(flip_at).date()} refit: "
      f"w2 {W6F['w2'].iloc[0]:.2f} -> {W6F['w2'].iloc[-1]:.2f}, "
      f"b {W6F['b'].iloc[0]:+.1f} -> {W6F['b'].iloc[-1]:+.1f}")
OUT["refit"] = {**S, "flip_at": str(pd.Timestamp(flip_at).date()),
                "w2_first": float(W6F["w2"].iloc[0]),
                "w2_last": float(W6F["w2"].iloc[-1]),
                "b_first": float(W6F["b"].iloc[0]),
                "b_last": float(W6F["b"].iloc[-1])}
assert S["b_sign_flips"] == 1, "the recorded path has exactly one sign reversal"
assert str(pd.Timestamp(flip_at).date()).startswith("2023-06")
assert W6F["w2"].iloc[0] == 0.05 and W6F["w2"].iloc[-1] == 0.95
assert abs(W6F["b"].iloc[0] - 19.1) < 0.1 and abs(W6F["b"].iloc[-1] + 7.6) < 0.1

# ---------------------------------------------------------------------------
sec("2. Does the rebalance shrink the error?  The recorded table, rebuilt")
# ---------------------------------------------------------------------------
W6, FIT6 = FV.imm_refit(Y, P, "free", WINDOW_BD)
W6C, FIT6C = FV.imm_refit(Y, P, "citi", WINDOW_BD)
STATIC = FV.fit_fair_value(Y, P, "fly")
static_fitted = FV.fitted_series(P, STATIC)

CMP = pd.DataFrame({
    "IMM refit, free": Y - FIT6,
    "IMM refit, fly-constrained": Y - FIT6F,
    "IMM refit, Citi weights": Y - FIT6C,
    "static fly, full sample (in-sample)": Y - static_fitted,
}).dropna()
TAB = pd.DataFrame({"resid_sd_bp": CMP.std(ddof=1),
                    "resid_mean_bp": CMP.mean(),
                    "resid_mae_bp": CMP.abs().mean()}).round(3)
print(f"over {len(CMP)} common dates:\n")
print(TAB.to_string())
sd_refit = float(CMP["IMM refit, fly-constrained"].std(ddof=1))
sd_citi = float(CMP["IMM refit, Citi weights"].std(ddof=1))
mae_refit = float(CMP["IMM refit, fly-constrained"].abs().mean())
mae_citi = float(CMP["IMM refit, Citi weights"].abs().mean())
OUT["residuals"] = {"sd_refit": sd_refit, "sd_citi": sd_citi,
                    "mae_refit": mae_refit, "mae_citi": mae_citi,
                    "n_common": int(len(CMP))}
print(f"\nrecorded: refit sd 2.232 / Citi sd 2.149;  refit mae 1.674 / Citi mae 1.892")
assert abs(sd_refit - 2.232) < 0.005, sd_refit
assert abs(sd_citi - 2.149) < 0.005, sd_citi
assert abs(mae_refit - 1.674) < 0.005, mae_refit
assert abs(mae_citi - 1.892) < 0.005, mae_citi
assert sd_citi < sd_refit and mae_refit < mae_citi

# ---------------------------------------------------------------------------
sec("3. Which fly START explains the CA -- the recorded ranking")
# ---------------------------------------------------------------------------
rows = []
for name, cols in FV.FLY_STARTS.items():
    if any(c not in P.columns for c in cols):
        print(f"  skipping {name}: missing columns")
        continue
    W, F = FV.imm_refit(Y, P, "fly", WINDOW_BD, cols)
    if W.empty:
        continue
    res = (Y - F).dropna()
    s = FV.refit_summary(W)
    rows.append({"start": name, "insample_r2_med": float(W["r2"].median()),
                 "oos_resid_sd_bp": float(res.std(ddof=1)),
                 "oos_resid_mae_bp": float(res.abs().mean()),
                 "w2_med": s["w2_median"], "b_med": s["b_median"],
                 "b_sign_flips": s["b_sign_flips"], "n_refits": s["n_refits"]})
STARTS = pd.DataFrame(rows).set_index("start").sort_values("oos_resid_sd_bp")
print(STARTS.round(3).to_string())
spot, matched = "spot (Citi's own)", "IMM_13 (Blues front)"
rank_matched = list(STARTS.index).index(matched) + 1
print(f"\nbest {STARTS.index[0]} ({STARTS['oos_resid_sd_bp'].iloc[0]:.3f} bp); "
      f"{matched} ranks {rank_matched} of {len(STARTS)} "
      f"({STARTS.loc[matched, 'oos_resid_sd_bp']:.3f} bp)")
stable = list(STARTS[STARTS["b_sign_flips"] == 0].index)
print(f"starts whose fitted scale b never changes sign: {stable or 'NONE OF THE TEN'}")
OUT["fly_starts"] = {
    "best": STARTS.index[0], "best_sd": float(STARTS["oos_resid_sd_bp"].iloc[0]),
    "matched_rank": int(rank_matched), "n_starts": int(len(STARTS)),
    "matched_sd": float(STARTS.loc[matched, "oos_resid_sd_bp"]),
    "b_stable_starts": stable,
    "table": json.loads(STARTS.reset_index().to_json(orient="records")),
}
assert STARTS.index[0] == spot, "the recorded best start is Citi's own spot fly"
assert abs(STARTS.loc[spot, "oos_resid_sd_bp"] - 2.232) < 0.005
assert rank_matched == 9, rank_matched
assert abs(STARTS.loc[matched, "oos_resid_sd_bp"] - 3.396) < 0.005
assert not stable, "no start had a sign-stable b in the recorded path"

# ---------------------------------------------------------------------------
sec("4. The refit-window sensitivity the reproduction printed")
# ---------------------------------------------------------------------------
rows = []
for wbd in (252, 504, 756):
    W, F = FV.imm_refit(Y, P, "fly", wbd)
    r = (Y - F).dropna()
    rows.append({"window_bd": wbd, "n_refits": len(W),
                 "w2_median": float(W["w2"].median()),
                 "w2_range": float(W["w2"].max() - W["w2"].min()),
                 "oos_resid_sd_bp": float(r.std(ddof=1)), "oos_dates": len(r)})
SENS = pd.DataFrame(rows)
print(SENS.round(3).to_string(index=False))
OUT["window_sensitivity"] = json.loads(SENS.to_json(orient="records"))

(DATA / "p4_tieout_repro.json").write_text(json.dumps(OUT, indent=1))
print(f"\nALL TIE-OUTS PASS.  wrote {DATA / 'p4_tieout_repro.json'}")

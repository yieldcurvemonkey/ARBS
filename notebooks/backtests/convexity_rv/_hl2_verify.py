r"""Verify the ``_MODEL2`` work on live data: nothing moved, and what it prices.

Seven checks, in the order they matter:

  0. the OBSERVED adjustment and the Ho-Lee ``_MODEL`` level are byte-identical
     to the reference captured on the unmodified tree
     (``_hl2_reference_capture.py``) -- the engine that priced ``_MODEL`` was
     refactored to carry a second model, so both need proving, not one;
  1. a ``_MODEL2``-only request makes ZERO BarChart calls;
  2. the level reproduces ``hw1f_sofr`` by hand on a fixed vol;
  3. the three cache entries for one structure stay three;
  4. the strip: observed vs ``_MODEL`` vs ``_MODEL2``, and what each one's
     ``VsModel`` gap looks like -- computed BEFORE any claim is made about it;
  5. what the mean reversion is worth on live data, recalibrated;
  6. the payoff-convention decomposition on live data (compounded / average /
     term), which is the first-order term.

Output: notebooks/data/convexity_rv/hl2_verify.json
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
pd.set_option("display.max_columns", 40)

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from RVUtils.ConvexityRV import hw1f_sofr as HW  # noqa: E402
from TB import IRSwapsTB as M  # noqa: E402
from TB.IRSwapsTB import IRSwapsTB  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
REF = DATA / "hl2_reference.parquet"
REFMETA = json.loads((DATA / "hl2_reference.json").read_text())
OUT: dict = {}
LABELS = REFMETA["labels"]
MODEL_LABELS = REFMETA["model_labels"]
MODEL2_LABELS = [f"{lab}_MODEL2" for lab in LABELS]
START, END = REFMETA["start"], REFMETA["end"]


def sec(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def _tb() -> IRSwapsTB:
    return IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)


def _col(df, needle):
    hits = [c for c in df.columns if needle in str(c)]
    if not hits:
        raise KeyError(f"no column matching {needle!r}")
    return hits[0]


ref = pd.read_parquet(REF)

# ---------------------------------------------------------------------------
sec("0. OBSERVED and _MODEL must be byte-identical to the pre-change reference")
# ---------------------------------------------------------------------------
tb = _tb()
obs = tb.sfr_cvx_adj(LABELS, START, END)
tb.close()
tb = _tb()
mdl = tb.sfr_cvx_adj(MODEL_LABELS, START, END)
tb.close()
now = pd.concat([obs, mdl], axis=1).sort_index(kind="mergesort")

same_cols = list(ref.columns) == list(now.columns)
same_shape = ref.shape == now.shape
delta = float((ref - now).abs().to_numpy().max()) if (same_shape and same_cols) else float("nan")
print(f"reference {ref.shape}  now {now.shape}  same columns {same_cols}")
print(f"max |now - reference| = {delta:.12f}")
print(f"checksum then {REFMETA['checksum']:.10f}   now "
      f"{float(pd.to_numeric(now.stack(), errors='coerce').sum()):.10f}")
assert same_shape and same_cols and delta == 0.0, "THE OBSERVED OR _MODEL PATH MOVED"
print("\nBOTH UNCHANGED.")
OUT["reference_identical"] = True
OUT["reference_max_abs_delta"] = delta

# ---------------------------------------------------------------------------
sec("1. A _MODEL2-only request makes ZERO BarChart calls")
# ---------------------------------------------------------------------------
import MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils as SCU  # noqa: E402

_calls = {"n": 0}
_orig = SCU.get_barchart_timeseries


def _counting(*a, **k):
    _calls["n"] += 1
    return _orig(*a, **k)


SCU.get_barchart_timeseries = _counting
try:
    tb = _tb()
    m2 = tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END, ignore_cache=True)
    tb.close()
finally:
    SCU.get_barchart_timeseries = _orig
print(f"BarChart calls for a _MODEL2-only request: {_calls['n']}")
print(f"returned {m2.shape}  columns {list(m2.columns)}")
assert _calls["n"] == 0, "a model-only request hit BarChart"
OUT["barchart_calls_model2_only"] = _calls["n"]

# ---------------------------------------------------------------------------
sec("2. The level is the Hull-White arithmetic, on a fixed vol")
# ---------------------------------------------------------------------------
FIXED, A = 95.0, M.CVX_MODEL2_MEAN_REVERSION


def _fixed_provider(as_of, t):
    return FIXED


tb = _tb()
fx = tb.sfr_cvx_adj(["BLUES_MODEL2"], START, END, ignore_cache=True,
                    model_vol_provider=_fixed_provider)
tb.close()
d0 = fx.index[0].date()
t1s, t2s = M._cvx_model_t1_t2s(d0, "BLUES")
sig = [HW.sigma_from_normal_vol_bp(FIXED, A, t1, 1.0) for t1 in t1s]
hand = float(np.mean([HW.futures_ca_bp(s, t1, t2, A)
                      for s, t1, t2 in zip(sig, t1s, t2s)]))
print(f"{d0}: T1s {[round(t, 4) for t in t1s]}")
print(f"      T2s {[round(t, 4) for t in t2s]}")
print(f"  sigma_HW from a {FIXED}bp quote at a={A}: "
      f"{[round(s, 3) for s in sig]}")
print(f"  hand  {hand:.10f} bp")
print(f"  method {float(fx.iloc[0, 0]):.10f} bp")
assert abs(hand - float(fx.iloc[0, 0])) < 1e-9
print("\nmatches to 1e-9.")
OUT["fixed_vol_handcheck_bp"] = hand

# ---------------------------------------------------------------------------
sec("3. Three entries for one structure, and they stay three")
# ---------------------------------------------------------------------------
tb = _tb()
three = tb.sfr_cvx_adj(["BLUES", "BLUES_MODEL", "BLUES_MODEL2"], START, END)
tb.close()
obs_c = _col(three, "BLUES PACKS")
mdl_c = _col(three, "BLUES_MODEL PACKS")
m2_c = _col(three, "BLUES_MODEL2 PACKS")
print(three[[obs_c, mdl_c, m2_c]].describe().loc[["count", "mean", "min", "max"]]
      .round(4).to_string())
cross_obs = float((three[obs_c] - ref[_col(ref, "BLUES PACKS")]).abs().max())
cross_mdl = float((three[mdl_c] - ref[_col(ref, "BLUES_MODEL PACKS")]).abs().max())
print(f"\nafter writing _MODEL2 rows, observed max|diff| {cross_obs:.12f}, "
      f"_MODEL max|diff| {cross_mdl:.12f}")
assert cross_obs == 0.0 and cross_mdl == 0.0, "a model write crossed into another entry"
OUT["cache_cross_contamination"] = [cross_obs, cross_mdl]

# ---------------------------------------------------------------------------
sec("4. The strip: observed vs _MODEL vs _MODEL2")
# ---------------------------------------------------------------------------
t0 = time.time()
tb = _tb()
m2_all = tb.sfr_cvx_adj(MODEL2_LABELS, START, END)
fails = {k: len(v) for k, v in (tb.sfr_cvx_adj_failures or {}).items()}
tb.close()
print(f"{m2_all.shape[0]} dates x {m2_all.shape[1]} columns in {time.time() - t0:.0f}s")
print(f"failures: {fails or 'none'}")

rows = []
for lab in LABELS:
    o = ref[_col(ref, f"{lab} ")].mean()
    m1 = ref[_col(ref, f"{lab}_MODEL ")].mean()
    m2v = m2_all[_col(m2_all, f"{lab}_MODEL2 ")].mean()
    rows.append({
        "label": lab,
        "observed": o,
        "MODEL": m1,
        "MODEL2": m2v,
        "vs_MODEL": o - m1,
        "vs_MODEL2": o - m2v,
        "M2/M1": m2v / m1 if m1 else np.nan,
    })
T = pd.DataFrame(rows)
print()
print(T.round(4).to_string(index=False))
print(f"\nmean |vs_MODEL|  {T['vs_MODEL'].abs().mean():.3f} bp")
print(f"mean |vs_MODEL2| {T['vs_MODEL2'].abs().mean():.3f} bp")
print("(packs only, where the model is meant to apply)")
packs = T[T["label"].isin(["WHITES", "REDS", "GREENS", "BLUES", "GOLDS"])]
print(f"packs mean |vs_MODEL|  {packs['vs_MODEL'].abs().mean():.3f} bp")
print(f"packs mean |vs_MODEL2| {packs['vs_MODEL2'].abs().mean():.3f} bp")
OUT["strip"] = T.round(6).to_dict(orient="records")
OUT["mean_abs_vs_model"] = float(T["vs_MODEL"].abs().mean())
OUT["mean_abs_vs_model2"] = float(T["vs_MODEL2"].abs().mean())
OUT["packs_mean_abs_vs_model"] = float(packs["vs_MODEL"].abs().mean())
OUT["packs_mean_abs_vs_model2"] = float(packs["vs_MODEL2"].abs().mean())

# ---------------------------------------------------------------------------
sec("5. What the mean reversion is worth on live data")
# ---------------------------------------------------------------------------
rows = []
for a in (0.0, 0.01, 0.03, 0.05, 0.10):
    tb = _tb()
    df = tb.sfr_cvx_adj(["BLUES_MODEL2", "GOLDS_MODEL2"], START, END,
                        ignore_cache=True, model2_mean_reversion=a)
    tb.close()
    rows.append({"a": a,
                 "BLUES": float(df[_col(df, "BLUES_MODEL2")].mean()),
                 "GOLDS": float(df[_col(df, "GOLDS_MODEL2")].mean())})
Ma = pd.DataFrame(rows)
Ma["BLUES rel"] = Ma["BLUES"] / Ma["BLUES"].iloc[0]
Ma["GOLDS rel"] = Ma["GOLDS"] / Ma["GOLDS"].iloc[0]
print(Ma.round(4).to_string(index=False))
print("\nRecalibrated to the same ATM quote at each `a`, so the damping and the "
      "implied-sigma rise nearly cancel. This is the SECOND-order knob.")
OUT["mean_reversion_scan"] = Ma.round(6).to_dict(orient="records")

# ---------------------------------------------------------------------------
sec("6. The payoff convention -- the FIRST-order term")
# ---------------------------------------------------------------------------
rows = []
for payoff in ("compounded", "average", "term"):
    tb = _tb()
    df = tb.sfr_cvx_adj(["BLUES_MODEL2", "GOLDS_MODEL2"], START, END,
                        ignore_cache=True, model2_payoff=payoff,
                        model2_mean_reversion=0.0)
    tb.close()
    rows.append({"payoff": payoff,
                 "BLUES": float(df[_col(df, "BLUES_MODEL2")].mean()),
                 "GOLDS": float(df[_col(df, "GOLDS_MODEL2")].mean())})
P = pd.DataFrame(rows)
citi = {lab: ref[_col(ref, f"{lab}_MODEL ")].mean() for lab in ("BLUES", "GOLDS")}
P.loc[len(P)] = {"payoff": "citi T1^2 (_MODEL)", **citi}
obs_means = {lab: ref[_col(ref, f"{lab} ")].mean() for lab in ("BLUES", "GOLDS")}
P.loc[len(P)] = {"payoff": "OBSERVED", **obs_means}
print(P.round(4).to_string(index=False))
print("\nAll four model rows use the SAME volatility and a = 0. The spread "
      "between them is the settlement convention alone.")
OUT["payoff_scan"] = P.round(6).to_dict(orient="records")

(DATA / "hl2_verify.json").write_text(json.dumps(OUT, indent=1, default=str))
print(f"\nALL CHECKS PASS.  wrote {DATA / 'hl2_verify.json'}")

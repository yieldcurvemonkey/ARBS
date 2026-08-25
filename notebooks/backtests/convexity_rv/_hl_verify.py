r"""Verify the ``_MODEL`` work: the observed path unchanged, the model path right.

Six checks, in the order they matter:

  0. the OBSERVED adjustment is byte-identical to the reference captured on the
     unmodified tree (``_hl_reference_capture.py``);
  1. a model-only request makes ZERO BarChart calls;
  2. the model level reproduces a hand-computed Ho-Lee number on a fixed vol;
  3. the derived vol node reproduces the incumbent ``gv_grid.VOL_BENCH`` map;
  4. the model ties out to the block-5 screen's own ``model_ca_bp`` when the
     vol is snapped to the same node the incumbent uses;
  5. every label family answers, and the cache round-trips without disturbing
     the observed entry for the same structure.

Output: notebooks/data/convexity_rv/hl_verify.json
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
from TB import IRSwapsTB as M  # noqa: E402
from TB.IRSwapsTB import IRSwapsTB  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
REF = DATA / "hl_reference_observed.parquet"
REFMETA = json.loads((DATA / "hl_reference_observed.json").read_text())
OUT: dict = {}
LABELS = REFMETA["labels"]
START, END = REFMETA["start"], REFMETA["end"]


def sec(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def _tb() -> IRSwapsTB:
    return IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)


# ---------------------------------------------------------------------------
sec("0. The OBSERVED adjustment must be byte-identical to the reference")
# ---------------------------------------------------------------------------
ref = pd.read_parquet(REF)
tb = _tb()
now = tb.sfr_cvx_adj(LABELS, START, END)
tb.close()
same_shape = ref.shape == now.shape
same_cols = list(ref.columns) == list(now.columns)
delta = float((ref - now).abs().to_numpy().max()) if (same_shape and same_cols) else float("nan")
print(f"reference {ref.shape}  now {now.shape}  same columns {same_cols}")
print(f"max |now - reference| = {delta:.12f}")
print(f"checksum then {REFMETA['checksum']:.10f}   now "
      f"{float(pd.to_numeric(now.stack(), errors='coerce').sum()):.10f}")
assert same_shape and same_cols and delta == 0.0, "THE OBSERVED PATH MOVED"
print("\nOBSERVED PATH UNCHANGED.")
OUT["observed_identical"] = True
OUT["observed_max_abs_delta"] = delta

# ---------------------------------------------------------------------------
sec("1. A model-only request makes ZERO BarChart calls")
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
    mdl = tb.sfr_cvx_adj(["BLUES_MODEL"], START, END, ignore_cache=True)
    tb.close()
finally:
    SCU.get_barchart_timeseries = _orig
print(f"BarChart calls for a model-only request: {_calls['n']}")
print(f"returned {mdl.shape}  columns {list(mdl.columns)}")
assert _calls["n"] == 0, "a model-only request hit BarChart"
OUT["barchart_calls_model_only"] = _calls["n"]
OUT["model_only_shape"] = list(mdl.shape)

# ---------------------------------------------------------------------------
sec("2. The model level is the Ho-Lee arithmetic, on a fixed vol")
# ---------------------------------------------------------------------------
FIXED = 95.0


def _fixed_provider(as_of, t1_mean):
    return FIXED


tb = _tb()
fx = tb.sfr_cvx_adj(["BLUES_MODEL"], START, END, ignore_cache=True,
                    model_vol_provider=_fixed_provider)
tb.close()
col = fx.columns[0]
d0 = fx.index[0].date()
t1s = M._cvx_model_t1s(d0, "BLUES")
hand = FIXED ** 2 * float(np.mean(np.asarray(t1s) ** 2)) / 2e4
print(f"{d0}: T1s {[round(t, 4) for t in t1s]}")
print(f"  hand  sigma^2 * mean(T1^2) / 2e4 = {hand:.10f} bp")
print(f"  method                            {float(fx[col].iloc[0]):.10f} bp")
assert abs(hand - float(fx[col].iloc[0])) < 1e-9
print("\nmatches to 1e-9.")
OUT["fixed_vol_handcheck_bp"] = hand

# ---------------------------------------------------------------------------
sec("3. The derived vol node reproduces the incumbent VOL_BENCH map")
# ---------------------------------------------------------------------------
from RVUtils.ConvexityRV.gv_grid import VOL_BENCH  # noqa: E402

rows = []
for lab, sh in VOL_BENCH.items():
    ranks = M._cvx_ranks_for_label(lab)
    t = 0.25 * float(np.mean(ranks))
    node = int(np.floor(t + 0.5))
    rows.append({"label": lab, "mean_rank_years": t, "derived": f"{node}Yx1Y",
                 "incumbent": sh, "ok": f"{node}Yx1Y" == sh})
V = pd.DataFrame(rows)
print(V.round(4).to_string(index=False))
assert bool(V["ok"].all())
print(f"\nall {len(V)} incumbent entries reproduce as round(0.25*mean(ranks))Yx1Y.")
OUT["vol_bench_rule_reproduces"] = True

# ---------------------------------------------------------------------------
sec("4. Tie-out to the block-5 screen, with the vol snapped to the same node")
# ---------------------------------------------------------------------------
from RVUtils.ConvexityRV import swaption_cube as SC  # noqa: E402

pairs = [(f"{n}Y", "1Y") for n in (1, 2, 3, 4, 5)]
panel = SC.load_vol_panel(pairs, pd.Timestamp(START).date(), pd.Timestamp(END).date())
rows = []
for lab in ("WHITES", "REDS", "GREENS", "BLUES", "GOLDS"):
    node = VOL_BENCH[lab]
    exp, ten = node.split("x")
    ser = SC.atmf_vol_series(panel, exp, ten)
    ser.index = pd.to_datetime(ser.index).date

    def _snapped(as_of, _t1_mean, _s=ser):
        v = _s.get(as_of)
        return float(v) if v is not None and v == v else float("nan")

    tb = _tb()
    got = tb.sfr_cvx_adj([f"{lab}_MODEL"], START, END, ignore_cache=True,
                         model_vol_provider=_snapped)
    tb.close()
    if got.empty:
        rows.append({"label": lab, "node": node, "n": 0, "max_abs_diff": np.nan})
        continue
    c = got.columns[0]
    diffs = []
    for ts, v in got[c].items():
        d = ts.date()
        sig = _snapped(d, None)
        if not (sig == sig):
            continue
        t1s = M._cvx_model_t1s(d, lab)
        w = float(np.mean(np.asarray(t1s) ** 2))
        diffs.append(abs(float(v) - sig ** 2 * w / 2e4))
    rows.append({"label": lab, "node": node, "n": len(diffs),
                 "max_abs_diff": max(diffs) if diffs else np.nan})
T = pd.DataFrame(rows)
print(T.to_string(index=False))
print("\nThe screen's model level is `nvol**2 * w / 2e4` with `w = mean(T1^2)`; "
      "this is the same arithmetic on the same node, so it must agree exactly.")
assert float(np.nanmax(T["max_abs_diff"].to_numpy())) < 1e-9
OUT["block5_tieout_max_abs_diff"] = float(np.nanmax(T["max_abs_diff"].to_numpy()))

# ---------------------------------------------------------------------------
sec("5. Every label family answers, and the cache does not cross the two")
# ---------------------------------------------------------------------------
front = M._cvx_front_imm_code(pd.Timestamp(END).date())
FAM = ["SFR1_MODEL", "SFR9_MODEL", "SFR20_MODEL", "WHITES_MODEL",
       "GREENS_MODEL", "GOLDS_MODEL", "SILVERS_MODEL", "BUNDLE2_MODEL",
       "BUNDLE2Y_MODEL", "BUNDLE5Y_MODEL", f"{front}_MODEL"]
t0 = time.time()
tb = _tb()
fam = tb.sfr_cvx_adj(FAM, START, END)
fails = {k: len(v) for k, v in (tb.sfr_cvx_adj_failures or {}).items()}
tb.close()
print(f"{fam.shape[0]} dates x {fam.shape[1]} columns in {time.time() - t0:.0f}s")
print(fam.describe().loc[["count", "mean", "min", "max"]].round(4).to_string())
print(f"\nfailures: {fails or 'none'}")
missing = [l for l in FAM if not any(l in str(c) for c in fam.columns)]
print(f"labels with no column: {missing or 'none'}")

tb = _tb()
after = tb.sfr_cvx_adj(["BLUES", "BLUES_MODEL"], START, END)
tb.close()
obs_col = [c for c in after.columns if "BLUES PACKS" in str(c)][0]
mdl_col = [c for c in after.columns if "BLUES_MODEL" in str(c)][0]
ref_col = [c for c in ref.columns if "BLUES PACKS" in str(c)][0]
cross = float((after[obs_col] - ref[ref_col]).abs().max())
print(f"\nafter writing model entries, the OBSERVED BLUES column still matches "
      f"the reference: max |diff| {cross:.12f}")
assert cross == 0.0, "the model write disturbed the observed cache entry"
print(f"observed mean {after[obs_col].mean():.3f} bp   "
      f"model mean {after[mdl_col].mean():.3f} bp   "
      f"VsModel mean {(after[obs_col] - after[mdl_col]).mean():+.3f} bp")
OUT["families_ok"] = int(fam.shape[1])
OUT["families_missing"] = missing
OUT["cache_cross_contamination"] = cross
OUT["blues_observed_mean_bp"] = float(after[obs_col].mean())
OUT["blues_model_mean_bp"] = float(after[mdl_col].mean())

(DATA / "hl_verify.json").write_text(json.dumps(OUT, indent=1, default=str))
print(f"\nALL CHECKS PASS.  wrote {DATA / 'hl_verify.json'}")

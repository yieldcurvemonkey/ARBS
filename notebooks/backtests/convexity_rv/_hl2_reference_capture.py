r"""Reference frames captured BEFORE the ``_MODEL2`` edit: observed AND ``_MODEL``.

``_MODEL2`` re-enters the same place ``_MODEL`` did -- ``sfr_cvx_adj``'s label
split and the model-frames engine -- so two things have to be proved unchanged
afterwards, not one:

* the OBSERVED adjustment, which five blocks of the convexity programme read;
* the Ho-Lee ``_MODEL`` level shipped in PR #504, whose engine is about to be
  refactored to carry a second model.

Run on the unmodified tree, then again after, and diff byte-exact. Both frames
are captured in the SAME tree so the caches are shared and the comparison is
apples-to-apples -- a capture taken in a sibling worktree would be compared
against a cold recompute here, and a vintage difference would read as a
regression.

Output: notebooks/data/convexity_rv/hl2_reference.parquet + .json
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

import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from TB.IRSwapsTB import IRSwapsTB  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)
OUT = DATA / "hl2_reference.parquet"
META = DATA / "hl2_reference.json"

#: One label per branch of the resolution loop, as in PR #504's capture.
LABELS = [
    "SFR1", "SFR4", "SFR9", "SFR12", "SFR20",      # constant-maturity ranks
    "WHITES", "REDS", "GREENS", "BLUES", "GOLDS",  # colour packs
    "BUNDLE2",                                      # legacy 16-quarter window
    "BUNDLE2Y", "BUNDLE5Y",                         # CME front-anchored bundles
]
MODEL_LABELS = [f"{lab}_MODEL" for lab in LABELS]
START, END = "2025-06-02", "2025-08-29"


def main() -> None:
    tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
    t0 = time.time()
    obs = tb.sfr_cvx_adj(LABELS, START, END)
    t_obs = time.time() - t0
    obs_fails = {k: len(v) for k, v in (tb.sfr_cvx_adj_failures or {}).items()}
    tb.close()
    print(f"observed: {obs.shape[0]} dates x {obs.shape[1]} columns in {t_obs:.0f}s")
    print(f"failures: {obs_fails or 'none'}")

    tb2 = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
    t0 = time.time()
    mdl = tb2.sfr_cvx_adj(MODEL_LABELS, START, END)
    t_mdl = time.time() - t0
    mdl_fails = {k: len(v) for k, v in (tb2.sfr_cvx_adj_failures or {}).items()}
    tb2.close()
    print(f"model:    {mdl.shape[0]} dates x {mdl.shape[1]} columns in {t_mdl:.0f}s")
    print(f"failures: {mdl_fails or 'none'}")

    df = pd.concat([obs, mdl], axis=1).sort_index(kind="mergesort")
    print()
    print(df.describe().loc[["count", "mean", "min", "max"]].round(4).to_string())

    # The baseline behaviour of a _MODEL2 label BEFORE the feature exists, so
    # the change in behaviour is on the record rather than assumed. Today it is
    # an unresolvable PLAIN label, which is a different failure from _MODEL's
    # pre-#504 silent empty frame.
    tb3 = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
    try:
        before = tb3.sfr_cvx_adj(["BLUES_MODEL2"], START, END)
        base = {"shape": list(before.shape), "columns": list(map(str, before.columns)),
                "failures": {k: len(v) for k, v in
                             (tb3.sfr_cvx_adj_failures or {}).items()},
                "raised": None}
    except Exception as exc:  # noqa: BLE001
        base = {"shape": None, "columns": None, "failures": None,
                "raised": f"{type(exc).__name__}: {exc}"}
    tb3.close()
    print(f"\nBASELINE `sfr_cvx_adj(['BLUES_MODEL2'])` on the unmodified tree: {base}")

    df.to_parquet(OUT)
    checksum = float(pd.to_numeric(df.stack(), errors="coerce").sum())
    META.write_text(json.dumps({
        "labels": LABELS, "model_labels": MODEL_LABELS,
        "start": START, "end": END,
        "n_dates": int(df.shape[0]), "n_cols": int(df.shape[1]),
        "columns": list(map(str, df.columns)),
        "observed_elapsed_s": round(t_obs, 1),
        "model_elapsed_s": round(t_mdl, 1),
        "observed_failures": obs_fails,
        "model_failures": mdl_fails,
        "model2_baseline": base,
        "checksum": checksum,
    }, indent=1))
    print(f"\nwrote {OUT}")
    print(f"checksum {checksum:.10f}")


if __name__ == "__main__":
    main()

r"""Repair model rows written under the built-in key by an injected provider.

Before the ``injected:`` namespace existed, ``model_vol_provider=`` wrote its
values under ``cvx_vol_source="swaption_cube"`` -- the built-in model's own key --
and ``ignore_cache=True`` recomputed the READ while still performing that WRITE.
Two verification scripts did exactly that: PR #504's ``_hl_verify.py`` priced
five packs with node-SNAPPED volatilities, and ``_hl2_verify.py`` priced BLUES
with a fixed 95bp vol.

Measured damage before repair, over 2025-06-02..2025-08-29::

    BLUES_MODEL    cached 5.9057   true 5.9549   max |diff| 0.2021 bp
    GOLDS_MODEL    cached 9.5646   true 9.6369   max |diff| 0.2318 bp
    BLUES_MODEL2   cached 6.5636   true 6.9853   (already self-healed)

The guard prevents recurrence; it does not heal what is already stored, because
the built-in key did not change. This does: recompute with the BUILT-IN provider
under ``ignore_cache=True``, which now writes correct rows to that key.

Run it once per store. It reads the swaption cube and no futures data.

Usage:  python notebooks/backtests/convexity_rv/_hl2_repair_cache.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from TB.IRSwapsTB import IRSwapsTB  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
META = json.loads((DATA / "hl2_reference.json").read_text())
LABELS = META["labels"]
START, END = META["start"], META["end"]


def _tb() -> IRSwapsTB:
    return IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)


def main() -> None:
    rows = []
    for suffix in ("_MODEL", "_MODEL2"):
        labels = [f"{lab}{suffix}" for lab in LABELS]
        tb = _tb()
        before = tb.sfr_cvx_adj(labels, START, END)
        tb.close()
        tb = _tb()
        after = tb.sfr_cvx_adj(labels, START, END, ignore_cache=True)
        fails = {k: len(v) for k, v in (tb.sfr_cvx_adj_failures or {}).items()}
        tb.close()
        for c in after.columns:
            if c not in before.columns:
                continue
            d = float((before[c] - after[c]).abs().max())
            rows.append({"column": str(c), "max_abs_repair_bp": d,
                         "before_mean": float(before[c].mean()),
                         "after_mean": float(after[c].mean())})
        print(f"{suffix}: repaired {after.shape}, failures {fails or 'none'}")

    R = pd.DataFrame(rows).sort_values("max_abs_repair_bp", ascending=False)
    print()
    print(R.round(4).to_string(index=False))
    moved = R[R["max_abs_repair_bp"] > 1e-9]
    print(f"\n{len(moved)} of {len(R)} columns were wrong in the store; "
          f"worst {R['max_abs_repair_bp'].max():.4f} bp")

    tb = _tb()
    check = tb.sfr_cvx_adj([f"{lab}{sfx}" for lab in LABELS
                            for sfx in ("_MODEL", "_MODEL2")], START, END)
    tb.close()
    tb = _tb()
    recheck = tb.sfr_cvx_adj([f"{lab}{sfx}" for lab in LABELS
                              for sfx in ("_MODEL", "_MODEL2")], START, END,
                             ignore_cache=True)
    tb.close()
    resid = float((check - recheck).abs().to_numpy().max())
    print(f"\nafter repair, cached vs recomputed: max |diff| {resid:.12f}")
    assert resid == 0.0, "the store still disagrees with a fresh computation"
    (DATA / "hl2_cache_repair.json").write_text(json.dumps({
        "columns": R.round(8).to_dict(orient="records"),
        "n_moved": int(len(moved)),
        "worst_bp": float(R["max_abs_repair_bp"].max()),
        "residual_after_repair": resid,
    }, indent=1))
    print("STORE REPAIRED.")


if __name__ == "__main__":
    main()

r"""Reference frame of the OBSERVED convexity adjustment, captured before any edit.

``sfr_cvx_adj`` is the shared path five blocks of the convexity programme read
from, and the ``_MODEL`` work restructures its fetch loop and its three early
exits (``not need_fetch_labels``, ``not needed_tickers``, ``px_df.empty``).  The
only way to know the restructure changed nothing is to have the answer from
before it.

Run this on the UNMODIFIED tree, then again after, and diff byte-exact.

Covers every label family the method resolves, so each branch of the loop is
exercised: an IMM code, constant-maturity ranks at the front and the back, all
five colour packs, a legacy 16-quarter bundle and two CME bundles.

Output: notebooks/data/convexity_rv/hl_reference_observed.parquet + .json
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
OUT = DATA / "hl_reference_observed.parquet"
META = DATA / "hl_reference_observed.json"

#: One label per branch of the resolution loop.
LABELS = [
    "SFR1", "SFR4", "SFR9", "SFR12", "SFR20",      # constant-maturity ranks
    "WHITES", "REDS", "GREENS", "BLUES", "GOLDS",  # colour packs
    "BUNDLE2",                                      # legacy 16-quarter window
    "BUNDLE2Y", "BUNDLE5Y",                         # CME front-anchored bundles
]
START, END = "2025-06-02", "2025-08-29"


def main() -> None:
    tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
    t0 = time.time()
    df = tb.sfr_cvx_adj(LABELS, START, END)
    elapsed = time.time() - t0
    tb.close()

    print(f"{df.shape[0]} dates x {df.shape[1]} columns in {elapsed:.0f}s")
    print(f"{df.index.min().date()}..{df.index.max().date()}")
    print()
    print(df.describe().loc[["count", "mean", "std", "min", "max"]].round(6).to_string())
    print()
    print("failures recorded:")
    fails = {k: len(v) for k, v in (tb.sfr_cvx_adj_failures or {}).items()}
    print(fails or "  none")

    # The baseline behaviour of a _MODEL label BEFORE the feature exists, so the
    # change in behaviour is on the record rather than assumed.
    tb2 = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
    before = tb2.sfr_cvx_adj(["BLUES_MODEL"], START, END)
    tb2.close()
    print(f"\nBASELINE `sfr_cvx_adj(['BLUES_MODEL'])` on the unmodified tree: "
          f"shape {before.shape}, columns {list(before.columns)}, "
          f"failures {tb2.sfr_cvx_adj_failures or 'none'}")

    df.to_parquet(OUT)
    META.write_text(json.dumps({
        "labels": LABELS, "start": START, "end": END,
        "n_dates": int(df.shape[0]), "n_cols": int(df.shape[1]),
        "columns": list(map(str, df.columns)),
        "elapsed_s": round(elapsed, 1),
        "failures": fails,
        "blues_model_baseline_shape": list(before.shape),
        "blues_model_baseline_failures": tb2.sfr_cvx_adj_failures or {},
        "checksum": float(pd.to_numeric(df.stack(), errors="coerce").sum()),
    }, indent=1))
    print(f"\nwrote {OUT}")
    print(f"checksum {float(pd.to_numeric(df.stack(), errors='coerce').sum()):.10f}")


if __name__ == "__main__":
    main()

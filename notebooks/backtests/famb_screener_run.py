# %% [markdown]
# # Family B screener — the strategy as a daily instrument
#
# `famb_strategy_showcase` presents the two surviving structures as backtests.
# This notebook is the other half: what they say to do on a **given day**,
# including today. Same engine (`famb_common`), same signal, one date.
#
# ```
# conda run -n stir python notebooks/backtests/famb_screener.py --date 2026-07-28
# conda run -n stir python notebooks/backtests/famb_screener.py --date live
# conda run -n stir python notebooks/backtests/famb_screener.py --date live --json
# ```
#
# Two sleeves. The **carry short** (FLY25 on the front quarterly) is always on,
# so the screener reports its position and its roll clock rather than a signal.
# The **richness fade** (STRG75 on the front quarterly) has an entry rule, and
# watching it is what this exists for.

# %%
import sys

import numpy as np
import pandas as pd

sys.path.append("../../")
sys.path.append(".")
import famb_screener as scr                                  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)

CONFIG = dict(
    date="2023-03-20",      # a date, or "live"
    history=250,            # sessions of context for the standing level
    lots=100,
    thr_bp=scr.PREREG["thr_bp"],
)
CONFIG

# %% [markdown]
# ## 1. A day the strategy actually traded
#
# 2023-03-20 is the post-SVB richness spike the findings doc records as the
# fade's best entry (+44bp collected as the panic premium converged). If the
# screener is wired to the same signal, it has to see it.

# %%
ctx = scr.load_context(CONFIG["date"], history=CONFIG["history"])
ideas = scr.screen(ctx, thr_bp=CONFIG["thr_bp"])
carry = scr.carry_state(ctx)
print(scr.format_report(ctx, ideas, carry, lots=CONFIG["lots"]))

# %% [markdown]
# ## 2. What the screen is actually measuring
#
# The column that matters is not `rich` but `dev` — richness minus the cell's
# own standing level. Rank-2 and rank-3 contracts carry a large permanent
# richness because the off-lattice premium grows with days to expiry (the
# feasibility frontier, measured at +1.9 / +9.1 / +19.2bp by rank in the
# findings). Threshold-gating the raw number out there is not a convergence
# signal, it is a standing short of that premium — the passive tail-short the
# referee's ruling killed.

# %%
tab = pd.DataFrame([{
    "cell": f"{i.book} Q{i.rank}", "symbol": i.symbol, "dte": i.dte,
    "rich_bp": round(i.rich_bp, 2), "level_bp": round(i.level_bp, 2),
    "dev_bp": round(i.dev_bp, 2),
    "z": round(i.z_dev, 2) if np.isfinite(i.z_dev) else np.nan,
    "defined_risk": i.defined_risk, "state": i.state,
} for i in ideas if i.state != "NO-DATA"])
print(tab.to_string(index=False))
print("\nstanding level by rank (the frontier, in premium bp):")
print(tab.assign(rank=tab["cell"].str[-1])
      .groupby("rank")["level_bp"].agg(["mean", "min", "max"]).round(2)
      .to_string())

# %% [markdown]
# ## 3. The machine-readable form
#
# `--json` emits one record per cell, so the screen can drive a sheet, an alert
# or an order ticket rather than a human reading a table.

# %%
recs = scr.to_records(ideas)
best = next((r for r in recs if r["state"] == "ACTIONABLE"), recs[0])
print(f"{len(recs)} records; top one:")
for k in ("book", "rank", "symbol", "state", "action", "rich_bp", "dev_bp",
          "z_dev", "net_target_bp", "edge_mult", "exit_rich_bp",
          "max_hold_date", "defined_risk", "prereg"):
    v = best[k]
    print(f"  {k:16s} {round(v, 4) if isinstance(v, float) else v}")
print("  legs:")
for leg in best["legs"]:
    print(f"      {leg}")

# %% [markdown]
# ## 4. A day it says nothing
#
# The screener's normal output is "no trade", and that has to be
# distinguishable from "no data" — the first version of this tool printed the
# former when it meant the latter. A quiet screen with a named closest cell is
# a working screen; a NO DATA banner is a broken pipeline.

# %%
ctx_q = scr.load_context("2026-07-28", history=CONFIG["history"])
ideas_q = scr.screen(ctx_q, thr_bp=CONFIG["thr_bp"], ranks=(1,))
print(scr.format_report(ctx_q, ideas_q, scr.carry_state(ctx_q),
                        lots=CONFIG["lots"]))

# %% [markdown]
# ## How to read any of this
#
# The fade's parameters won a 720-config search: DSR 0.000, house verdict
# SELECTION-ARTIFACT. Its mechanism is measured — 7–18 session richness
# half-lives, frontier-consistent levels by rank, positive skew through SVB —
# but the exact numbers are selection-inflated, and the carry short's NW t is
# 1.51. Running the pre-registered cell unchanged, forward, is the one-trial
# test that discharges the penalty; every other cell the screen prints is an
# exploratory read with no mandate at all.

# %% [markdown]
# # ZQ vs SR3 — the meeting-dated tie-out (the gate, not the trade)
#
# The FedWatch ladder from ZQ settles, day-weighted into each SR3 reference
# window, differs from the SR3 forward by `base + spread`. If the two markets
# agree on the meeting-dated path, that quantity is a **constant across
# contracts** on any given day (the base and the level of the SOFR−EFFR spread
# are common); the cross-contract residual is the meeting-dated disagreement
# plus the spread's term structure (turns).
#
# This is the cross-market analogue of the options lab's `forward_residual_bp`:
# a **gate and diagnostic**. The linear trade it implies is SERFF's basis and is
# explicitly out of scope — the design conversation's Q6 rejection.

# %%
CONFIG = dict(
    resid_gate_bp=6.0,        # per-contract residual beyond which the day is suspect
)
CONFIG

# %%
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append("../../")

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA = Path("../data/meeting_prob")
tie = pd.read_parquet(DATA / "tieout.parquet")
tie["as_of"] = pd.to_datetime(tie["as_of"])
print(f"tie-out rows: {len(tie)}  dates: {tie['as_of'].nunique()}  "
      f"span {tie['as_of'].min().date()} -> {tie['as_of'].max().date()}")

# %% [markdown]
# ## The cross-contract constant test, daily

# %%
g = tie.groupby("as_of")["base_plus_spread_bp"]
daily = pd.DataFrame({
    "median_bp": g.median(),
    "spread_across_contracts_bp": g.apply(lambda s: s.max() - s.min()),
    "n_contracts": g.size(),
})
tie = tie.merge(daily[["median_bp"]], on="as_of")
tie["resid_bp"] = tie["base_plus_spread_bp"] - tie["median_bp"]
print(daily.describe().round(2).to_string())

# %%
fig, axes = plt.subplots(1, 2, figsize=(13, 4))
axes[0].plot(daily.index, daily["median_bp"], lw=1.0)
axes[0].set_title("base + spread (median across contracts), bp", fontsize=10)
axes[0].grid(alpha=0.25)
for sym, sub in tie.groupby("symbol"):
    s = sub.set_index("as_of")["resid_bp"]
    axes[1].plot(s.index, s.to_numpy(), lw=0.7, alpha=0.7, label=sym)
axes[1].axhline(0, color="grey", lw=0.8)
axes[1].set_title("per-contract residual vs the daily median, bp", fontsize=10)
axes[1].legend(fontsize=6, ncol=3)
axes[1].grid(alpha=0.25)
fig.autofmt_xdate()
fig.tight_layout()
plt.show()

# %% [markdown]
# ## Residual anatomy
#
# The residual's structure is informative even though it is not the trade:
# a maturity pattern is the spread's term structure (and the year-end turn for
# windows containing Dec 31); a common blowout is a data problem, not a signal.

# %%
tie["contains_turn"] = tie["symbol"].str.contains("Z2")   # Dec windows
print("residual by contract (bp):")
print(tie.groupby("symbol")["resid_bp"].describe().round(2).to_string())
print("\nresidual by turn-in-window:")
print(tie.groupby("contains_turn")["resid_bp"].describe().round(2).to_string())

# %%
gate = (tie.groupby("as_of")["resid_bp"]
        .apply(lambda s: s.abs().max() <= CONFIG["resid_gate_bp"])
        .rename("tieout_ok"))
print(f"days passing the +/-{CONFIG['resid_gate_bp']}bp gate: "
      f"{gate.mean():.1%} of {len(gate)}")
stale_days = tie.groupby("as_of")["any_stale"].any()
print(f"days with a stale ZQ print inside a window: {stale_days.mean():.1%}")
gate.to_frame().assign(any_stale=stale_days).reset_index().to_parquet(
    DATA / "tieout_gate.parquet", index=False)
print("wrote tieout_gate.parquet")

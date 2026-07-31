# %% [markdown]
# # ZQ vs SR3 meeting-probability RV — summary
#
# The framework in one paragraph: ZQ prices each meeting's move probability
# through its **means**; SR3 options price the same probability through their
# **variance** and node CDF. Parity kills the mean channel (the options lab's
# central result), so everything here is shape — and the empirical questions
# are whether the shape comparison is *feasible* (the 25bp lattice's variance
# ceiling), *identified* (the half-tick bootstrap; exchangeability limits the
# object to the N-space CDF), and *tradeable* (channel-1 episodes surviving
# gates and costs).

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
mon = pd.read_parquet(DATA / "monitor.parquet")
mon["as_of"] = pd.to_datetime(mon["as_of"])
bd = pd.read_parquet(DATA / "boundaries.parquet")
tie = pd.read_parquet(DATA / "tieout.parquet")
gate = pd.read_parquet(DATA / "tieout_gate.parquet")
grid = (pd.read_parquet(DATA / "channel1_grid.parquet")
        if (DATA / "channel1_grid.parquet").exists() else None)

# %% [markdown]
# ## The numbers that decide the framework

# %%
med = tie.groupby("as_of")["base_plus_spread_bp"].median()
tie2 = tie.merge(med.rename("med"), on="as_of")
resid = tie2["base_plus_spread_bp"] - tie2["med"]
print("1. TIE-OUT (the gate): cross-contract residual of ZQ-implied vs SR3 "
      "forwards")
print(f"   |resid| median {resid.abs().median():.2f}bp, "
      f"p90 {resid.abs().quantile(0.9):.2f}bp; "
      f"days passing the 6bp gate: {gate['tieout_ok'].mean():.1%}")

print("\n2. FEASIBILITY: share of (day, contract) surfaces the lattice + smear"
      " cap cannot reproduce")
print(f"   saturated: {mon['saturated'].mean():.1%} overall")
near = mon[mon["days_to_expiry"] <= 60]
print(f"   saturated at <= 60 days to expiry: "
      f"{near['saturated'].mean():.1%} (n={len(near)})")

ok = mon[~mon["saturated"]]
tcols = [c for c in mon.columns if c.startswith("tstat_")]
if len(ok) and tcols:
    tt = ok[tcols].stack().dropna()
    print("\n3. IDENTIFICATION (unsaturated only): |gap| vs its own bootstrap "
          "sigma")
    print(f"   share of meeting-gaps with |t| >= 2: {(tt.abs() >= 2).mean():.1%}"
          f"  (n={len(tt)})")

print("\n4. CHANNEL MIX")
print(mon["channel"].value_counts(normalize=True).round(3).to_string())

if grid is not None and len(grid):
    print("\n5. CHANNEL-1 BACKTEST GRID")
    print(grid.round(2).to_string(index=False))
    n_tot = int(grid["n_trades"].max())
    print(f"\n   max trades under any config: {n_tot}")

# %% [markdown]
# ## Reading
#
# The cells above are computed from the panels; the findings doc
# (`docs/superpowers/specs/2026-07-30-zq-sr3-meeting-prob-findings.md`) carries
# the full interpretation. The one-line version each way:
#
# * If saturation dominates at all horizons: the surface lives outside the
#   lattice-feasible set and the divergence is the standing off-lattice premium
#   — channel 2, one-sided, the cross-market twin of `tail_rent`. Harvest
#   economics at best; the convergence trade has no domain.
# * If a near-expiry feasible window exists but identification fails there
#   (bootstrap sigma comparable to gaps): the framework is
#   **measurement-bound** at EOD half-tick resolution.
# * Only if feasible + identified + channel-1 episodes survive gates does the
#   boundary-digital-vs-ZQ-ladder book exist; its grid and verdict are above.

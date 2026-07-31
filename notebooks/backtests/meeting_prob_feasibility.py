# %% [markdown]
# # ZQ vs SR3 — feasibility, identification, and the standing premium
#
# The framework's three empirical questions, in the order they gate each other:
#
# 1. **Feasibility.** The 25bp lattice has a hard variance ceiling
#    (`12.5·w` bp per meeting). When the option surface prices more total width
#    than lattice + a generous smear cap, the refit *saturates* and no
#    channel-1 signal exists. Where is the feasibility frontier in
#    days-to-expiry?
# 2. **Identification.** Inside the feasible region, are the fitted q's pinned
#    by the premiums? The half-tick bootstrap sigma is the measurement error a
#    gap must clear — and equal-weight meetings are *exchangeable*, so only the
#    N-space CDF (the boundary digitals) is identified at all.
# 3. **The standing premium.** Against the STRICT ZQ-null tree, the listed
#    digitals' gaps measure what the option market pays for everything the
#    lattice throws away — the cross-market twin of `tail_rent`. Its level is a
#    premium (channel 2, harvest at best); only deviations could ever be
#    channel 1.

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
bd["as_of"] = pd.to_datetime(bd["as_of"])
print(f"monitor rows: {len(mon)}  boundaries: {len(bd)}  "
      f"span {mon['as_of'].min().date()} -> {mon['as_of'].max().date()}")
print(f"contracts: {sorted(mon['symbol'].unique())}")

# %% [markdown]
# ## 1. The feasibility frontier

# %%
mon["dte_bucket"] = pd.cut(mon["days_to_expiry"],
                           [0, 30, 60, 90, 135, 200, 300, 500],
                           labels=["<30", "30-60", "60-90", "90-135",
                                   "135-200", "200-300", "300+"])
feas = (mon.groupby("dte_bucket", observed=True)
        .agg(n=("saturated", "size"),
             saturated=("saturated", "mean"),
             smear_bp=("smear_bp", "median"),
             smear_cap_bp=("smear_cap_bp", "median"),
             event_std_opt=("event_std_opt_bp", "median"),
             event_std_zq=("event_std_zq_bp", "median"),
             ceiling=("lattice_ceiling_bp", "median"),
             total_std_opt=("total_std_opt_bp", "median"),
             rmse_bp=("rmse_bp", "median"))
        .round(2))
print(feas.to_string())
print(f"\noverall saturation rate: {mon['saturated'].mean():.1%}")

# %%
fig, axes = plt.subplots(1, 2, figsize=(13, 4))
sat = mon.groupby("days_to_expiry")["saturated"].mean()
axes[0].plot(sat.index, sat.to_numpy(), ".", ms=3, alpha=0.5)
axes[0].set_xlabel("days to option expiry")
axes[0].set_title("saturation rate: the surface exceeds lattice + smear cap",
                  fontsize=10)
axes[0].grid(alpha=0.25)
axes[1].scatter(mon["days_to_expiry"], mon["total_std_opt_bp"], s=4, alpha=0.3,
                label="fitted total std (option)")
axes[1].scatter(mon["days_to_expiry"], mon["lattice_ceiling_bp"], s=4, alpha=0.3,
                label="lattice ceiling")
axes[1].set_xlabel("days to option expiry")
axes[1].set_ylabel("bp")
axes[1].legend(fontsize=8)
axes[1].set_title("total width the surface wants vs what the lattice can supply",
                  fontsize=10)
axes[1].grid(alpha=0.25)
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 2. Identification inside the feasible region

# %%
ok = mon[~mon["saturated"]].copy()
print(f"unsaturated rows: {len(ok)} ({len(ok) / max(len(mon), 1):.1%})")
qstd_cols = [c for c in ok.columns if c.startswith("qstd_")]
if len(ok) and qstd_cols:
    qs = ok[qstd_cols].stack().dropna()
    print(f"\nbootstrap q_std across meetings (probability points):")
    print((qs * 100).describe().round(2).to_string())
    pgap_cols = [c for c in ok.columns if c.startswith("pgap_")]
    pg = ok[pgap_cols].stack().dropna()
    print(f"\n|p_gap| (probability points):")
    print((pg.abs() * 100).describe().round(2).to_string())
    t_cols = [c for c in ok.columns if c.startswith("tstat_")]
    tt = ok[t_cols].stack().dropna()
    print(f"\n|gap t-stat| vs its own bootstrap sigma:")
    print(tt.abs().describe().round(2).to_string())
    print(f"share with |t| >= 2: {(tt.abs() >= 2).mean():.1%}")

# %% [markdown]
# ## 3. The standing premium against the strict null

# %%
bd["moneyness_bp"] = (bd["boundary_rate"]
                      - bd.merge(mon[["as_of", "symbol", "forward_rate"]],
                                 on=["as_of", "symbol"], how="left")
                      ["forward_rate"]) * 100
prem = (bd.groupby(pd.cut(bd["moneyness_bp"], [-80, -40, -15, 15, 40, 80]),
                   observed=True)["gap"]
        .agg(["mean", "std", "count"]).round(4))
print("listed-minus-null digital gap by moneyness of the boundary:")
print(prem.to_string())

# %%
daily_gap = bd.groupby("as_of")["gap"].apply(lambda s: s.abs().max())
fig, ax = plt.subplots(figsize=(10, 3.5))
ax.plot(daily_gap.index, daily_gap.to_numpy(), lw=0.8)
ax.set_title("max |listed - null| digital gap per day (the premium, mostly)",
             fontsize=10)
ax.grid(alpha=0.25)
fig.autofmt_xdate()
fig.tight_layout()
plt.show()

# %% [markdown]
# ## Channel classification through time

# %%
print(mon["channel"].value_counts().to_string())
print("\nby days-to-expiry bucket:")
print(mon.groupby("dte_bucket", observed=True)["channel"]
      .value_counts(normalize=True).round(3).to_string())

# %%
ch = mon.assign(is_c1=mon["channel"] == "channel1")
c1 = (ch.groupby("as_of")["is_c1"].any())
print(f"\ndays with at least one channel-1 classification: {c1.mean():.1%}")
runs = (c1 != c1.shift()).cumsum()
lens = c1.groupby(runs).agg(["first", "size"])
print("channel-1 episode lengths (days):")
print(lens[lens["first"]]["size"].describe().round(1).to_string())

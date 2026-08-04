# %% [markdown]
# # Linear-vs-vol grid — winner autopsy
#
# The best league row gets the treatment the kink-fade lesson demands:
# neighborhood stability (a real edge is not an island), config-matched
# placebos (the same coordinates under a Gaussian tree and a wrong
# calendar), and confound checks (FOMC proximity, IMM-roll windows — 22 of
# 33 SR3 rolls ARE decision dates).

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

from SDRUtils.analytics.fomc import load_fomc_schedule  # noqa: E402
from linvol_grid_common import pick_winner  # noqa: E402

DATA = Path("../data/linvol_grid")
league = pd.read_parquet(DATA / "league.parquet")
real = league[league["family"].isin(["A", "B", "C", "E"])]
live = real[real["n_trades"] > 0]
w = pick_winner(live)
print("WINNER:", w[["family", "boundary", "dte", "gated", "thr", "direction",
                    "n_trades", "total_gross_bp", "net_1x_bp", "net_2x_bp",
                    "t_stat"]].to_dict())

# %% [markdown]
# ## The trade log and the equity curve

# %%
tl_path = DATA / f"trades_{w['family']}_best.parquet"
tl = pd.read_parquet(tl_path) if tl_path.exists() else pd.DataFrame()
if len(tl):
    tl["entry"] = pd.to_datetime(tl["entry"])
    tl["exit"] = pd.to_datetime(tl["exit"])
    print(tl.round(2).to_string(index=False))
    fig, ax = plt.subplots(figsize=(10, 4))
    eq = tl.sort_values("exit").set_index("exit")["net_1x_bp"].cumsum()
    ax.step(eq.index, eq.values, where="post")
    ax.set_title(f"winner equity (net @1x): {w['family']} {w['boundary']} "
                 f"{w['dte']} thr{w['thr']} {w['direction']}")
    ax.set_ylabel("cum net bp")
    ax.axhline(0, color="gray", lw=0.6)
    plt.tight_layout()
    plt.show()
else:
    print("no persisted trade log for the winner family")

# %% [markdown]
# ## Neighborhood — a real edge survives one grid step in every direction

# %%
nb = real[(real["family"] == w["family"])
          & (real["boundary"] == w["boundary"])
          & (real["direction"] == w["direction"])]
print(nb[["dte", "gated", "thr", "n_trades", "net_1x_bp", "net_2x_bp",
          "t_stat"]].round(2).to_string(index=False))
n_pos = int((nb["net_1x_bp"] > 0).sum())
print(f"\nneighborhood: {n_pos}/{len(nb)} configs positive at 1x costs "
      f"(median {nb['net_1x_bp'].median():+.1f}bp) -> "
      + ("SUPPORTED" if n_pos > len(nb) / 2 else "ISLAND — treat the winner "
         "as selection until proven otherwise"))

# %% [markdown]
# ## Config-matched placebos — the mechanism test

# %%
key_cols = ["boundary", "dte", "gated", "thr", "direction"]
if w["family"] == "A":
    for tag, name in (("P1_gauss", "Gaussian tree (same moments, no "
                       "lattice)"), ("P2_calendar", "wrong calendar")):
        p = league[league["family"] == tag]
        m = p.merge(w[key_cols].to_frame().T, on=key_cols, how="inner")
        if len(m):
            r = m.iloc[0]
            print(f"{name}: SAME config -> n={int(r['n_trades'])}  "
                  f"net1x {r['net_1x_bp']:+.1f}bp "
                  f"(real: {w['net_1x_bp']:+.1f}bp)")
        else:
            print(f"{name}: config row not found")
    print("\nRead: lattice information should survive P1 poorly and P2 not "
          "at all; an edge that persists under both is option "
          "mean-reversion wearing a costume.")
else:
    print(f"winner family {w['family']} has no A-family placebo pair; "
          "placebo battery applies to the convergence family only.")

# %% [markdown]
# ## Confounds — where does the PnL actually live?

# %%
if len(tl):
    fomc = load_fomc_schedule("USD-SOFR-1D")
    decisions = pd.to_datetime(fomc["effective_date"])
    tl["days_to_decision"] = tl["entry"].apply(
        lambda d: int((decisions - d).abs().min().days))
    near = tl[tl["days_to_decision"] <= 3]
    print(f"trades entered within 3 days of an FOMC boundary: {len(near)}"
          f"/{len(tl)}  carrying {near['net_1x_bp'].sum():+.1f} of "
          f"{tl['net_1x_bp'].sum():+.1f}bp total net")
    per_sym = tl.groupby("symbol")["net_1x_bp"].agg(["count", "sum"])
    print("\nper-symbol concentration:")
    print(per_sym.round(1).to_string())
    top_share = tl["net_1x_bp"].max() / tl["net_1x_bp"].sum() \
        if tl["net_1x_bp"].sum() != 0 else np.nan
    print(f"\nlargest single trade / total net: {top_share:.0%}"
          if np.isfinite(top_share) else "")
else:
    print("no trade log — confound checks skipped")

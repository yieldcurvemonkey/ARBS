# %% [markdown]
# # SFR Fly Mean-Reversion — 2. Ornstein-Uhlenbeck
#
# **Formulation: fitted OU process.** A z-score assumes the window mean is the
# equilibrium and says nothing about how fast the series returns to it. An OU fit
# gives both: `mu` (the level it reverts to), `kappa` (the speed, hence a
# half-life) and `sigma_eq` (the equilibrium dispersion). The S-score
# `(x - mu)/sigma_eq` is the Avellaneda-Lee signal.
#
# The point of this notebook is the **half-life honesty rule**: holding periods
# are set from measured half-lives rather than swept, and a fly whose fitted
# half-life is sub-1-day is fit noise, not a tradeable signal.
#
# It also carries the cost-aware optimal bands. Three bugs were found and fixed
# in the shipped `optimal_ou_thresholds` while writing this
# (`docs/superpowers/specs/2026-07-29-sfr-fly-meanrev-findings.md`), the material
# one being that its first-passage series had `Gamma(k/2)` in the denominator
# instead of the numerator — Monte Carlo on the standardised OU measures
# `E[tau(-1 -> +1)] = 3.042` against 2.995 for the corrected series and 1.366 for
# the shipped one.

# %%
CONFIG = dict(
    primary_structure="3m",
    primary_window="liquid16",
    long_window="front8",
    cost_bp=1.5,
    n_packages=100,
    ou_windows=(120, 250, 500),     # rolling OU estimation window, business days
    entry_zs=(1.0, 1.5, 2.0, 2.5),
    exits=("z0", "half", "t10", "t20"),
    directions=("fade", "momentum"),
    max_hold=40,
    lag=1,
    hl_window=250,                  # window for the reported half-life table
)
CONFIG

# %%
import sys
from pathlib import Path

sys.path.append("../../")
sys.path.append(str(Path.cwd()))

import dataclasses

import numpy as np
import pandas as pd

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from RVUtils.MeanRev import MRConfig, run_backtest
from RVUtils.MeanRev.signals import ou_sscore_signal
from RVUtils.mean_reversion import (
    adf_pvalue, bertram_thresholds, calibrate_ou, expected_passage_time, half_life,
    ou_band_levels, ou_mle, rolling_ar1, rolling_half_life,
)
from sfr_fly_meanrev_common import (
    coverage_report, header_block, league_row, load_lab, regime_block, run_family,
    three_panel_equity,
)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

BASE = MRConfig(lag=CONFIG["lag"], round_trip_cost_bp=CONFIG["cost_bp"],
                max_hold=CONFIG["max_hold"], n_packages=CONFIG["n_packages"])
lab = load_lab(CONFIG["primary_structure"], CONFIG["primary_window"])
levels = lab["levels"]
print(f"{levels.shape[1]} flies, {levels.shape[0]} sessions")

# %% [markdown]
# ## 1. Measured half-lives, per constant-maturity slot
#
# Fitted on the **absolute** series (no roll), then summarised by the CM slot the
# fly occupied. Both the OLS AR(1) fit and the exact MLE are reported so the fit
# method is a measurement rather than an assumption, along with the ADF p-value:
# a half-life is only meaningful if the series is stationary in the first place.

# %%
def ou_row(s, name, slot):
    ols, mle = calibrate_ou(s), ou_mle(s)
    kap = ols.get("kappa", np.nan)
    return {"name": name, "slot": slot, "n": len(s),
            "mean_bp": s.mean(), "sd_bp": s.std(),
            "hl_ols": ols["half_life"], "hl_mle": mle["half_life"],
            "phi": ols["phi"], "mu_bp": ols["mu"],
            "sigma_eq": (ols["sigma"] / np.sqrt(2 * kap)
                         if np.isfinite(kap) and kap > 0 else np.nan),
            "adf_p": adf_pvalue(s)}


# (a) the CONSTANT-MATURITY series -- roll-adjusted, one per slot. This is what
#     a desk means by "the SFR456 fly" and what the rules of thumb quote. It
#     splices contracts every quarter, so it is reporting only.
cm_levels = lab["cm_levels"]
cm_hl = pd.DataFrame([ou_row(cm_levels[c].dropna(), c, lab["slot_of_label"][c])
                      for c in cm_levels.columns
                      if cm_levels[c].notna().sum() > 250]).sort_values("slot")
print("CONSTANT-MATURITY series (roll-adjusted; for reporting):")
print(cm_hl.round(3).to_string(index=False))

# (b) the ABSOLUTE series the backtest actually trades. A key's CM slot rolls
#     through its life, so it is summarised by the MEDIAN slot it occupied.
med_slot = lab["cm_slot_at"].median(axis=0)
rows = []
for key in levels.columns:
    s = levels[key].dropna()
    if len(s) < 250:
        continue
    rows.append(ou_row(s, key, med_slot.get(key, np.nan)))
hl = pd.DataFrame(rows)
hl["slot_bucket"] = pd.cut(hl["slot"], [0, 4, 8, 12, 16],
                           labels=["whites 1-4", "reds 5-8", "greens 9-12",
                                   "blues 13-16"])
print("\nABSOLUTE keys (what is backtested), bucketed by median slot over life:")
print(hl.groupby("slot_bucket", observed=True)
      .agg(n_keys=("name", "size"), hl_ols=("hl_ols", "median"),
           hl_mle=("hl_mle", "median"), sd_bp=("sd_bp", "median"),
           sigma_eq=("sigma_eq", "median"), adf_p=("adf_p", "median"),
           frac_stationary=("adf_p", lambda s: (s < 0.10).mean()))
      .round(3).to_string())
print(f"\nsub-1-day half-lives: {int((hl['hl_ols'] < 1).sum())}/{len(hl)} keys "
      f"(fit noise, not signal)")
print(f"half-lives above 250d (not reverting inside the window): "
      f"{int((hl['hl_ols'] > 250).sum())}/{len(hl)}")
per_slot = cm_hl.rename(columns={"name": "cm"})
per_slot["frac_stationary"] = (per_slot["adf_p"] < 0.10).astype(float)

# %%
fig, axes = plt.subplots(1, 2, figsize=(14, 4))
axes[0].bar(per_slot["cm"], per_slot["hl_ols"], color="#1f4e79")
axes[0].set_title("median fitted OU half-life by CM slot (business days)", fontsize=10)
axes[0].tick_params(axis="x", rotation=45, labelsize=8)
axes[0].grid(alpha=0.25, axis="y")
axes[1].bar(per_slot["cm"], per_slot["frac_stationary"], color="#2e7d32")
axes[1].axhline(0.5, color="grey", lw=0.8, ls="--")
axes[1].set_title("share of flies with ADF p < 0.10", fontsize=10)
axes[1].tick_params(axis="x", rotation=45, labelsize=8)
axes[1].grid(alpha=0.25, axis="y")
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 2. Cost-aware optimal bands
#
# `ou_band_levels` converts the fitted `(mu, kappa, sigma)` and a round-trip cost
# into an entry level in **bp**, the expected holding time, and the expected
# profit per unit time at that band. A band whose `ret_per_period` is negative
# cannot be traded profitably at that cost however it is parameterised — which is
# a far stronger statement than any single backtest.

# %%
rows = []
for c in cm_levels.columns:
    s = cm_levels[c].dropna()
    if len(s) < 250:
        continue
    p = calibrate_ou(s)
    if not np.isfinite(p.get("kappa", np.nan)) or p["kappa"] <= 0:
        continue
    for cost in (0.0, CONFIG["cost_bp"], 2.5):
        b = ou_band_levels(p, cost=cost)
        rows.append({"cm": c, "slot": lab["slot_of_label"][c], "cost_bp": cost,
                     "mu_bp": p["mu"], "sigma_eq_bp": b["sigma_eq"],
                     "hl_d": p["half_life"],
                     "entry_z": b["entry_z"], "entry_bp": b["entry_level"],
                     "hold_d": b["expected_hold"],
                     "ret_per_day_bp": b["ret_per_period"]})
band_tbl = pd.DataFrame(rows).sort_values(["cost_bp", "slot"])
print("optimal band per CM slot, by cost scenario (bp):")
print(band_tbl.round(3).to_string(index=False))
print("\nNote the shape of the answer: the band the model wants is NARROW "
      "(entry_z well under 1) and the hold it wants is LONG (tens to hundreds "
      "of days). Both are outside the grid a desk would normally sweep.")

# %%
piv = band_tbl.pivot_table(index="cm", columns="cost_bp", values="ret_per_day_bp")
order = band_tbl.drop_duplicates("cm").set_index("cm")["slot"].sort_values().index
piv = piv.reindex(order)
fig, ax = plt.subplots(figsize=(11, 4))
for c in piv.columns:
    ax.plot(piv.index, piv[c], marker="o", lw=1.4, label=f"cost {c}bp")
ax.axhline(0, color="black", lw=0.9)
ax.set_title("expected profit per day at the OPTIMAL band, by CM slot\n"
             "(below zero = no band pays at that cost)", fontsize=11)
ax.set_ylabel("bp per day per package")
ax.tick_params(axis="x", rotation=45, labelsize=8)
ax.legend(fontsize=8)
ax.grid(alpha=0.25)
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 2b. Is the fitted reversion actually regime drift?
#
# A full-sample OU fit assumes one equilibrium `mu` for six years. The panel
# audit already showed `SFR123` with a median of **+29bp in HIKING and −2.5bp in
# CUTTING**, so a single `mu` is an average of incompatible regimes and the slow
# "reversion" it measures may just be the walk between them.
#
# The test: refit inside each regime. If within-regime half-lives collapse and
# the `mu`s are far apart, the full-sample fit was measuring regime change.

# %%
reg = lab["regimes"]
rows = []
for c in cm_levels.columns:
    full = calibrate_ou(cm_levels[c].dropna())
    rec = {"cm": c, "slot": lab["slot_of_label"][c],
           "hl_full": full["half_life"], "mu_full": full["mu"]}
    mus = []
    for rname in ["ZIRP", "HIKING", "PLATEAU", "CUTTING"]:
        s = cm_levels[c][reg.reindex(cm_levels.index) == rname].dropna()
        if len(s) < 120:
            rec[f"hl_{rname}"] = np.nan
            rec[f"mu_{rname}"] = np.nan
            continue
        p = calibrate_ou(s)
        rec[f"hl_{rname}"] = p["half_life"]
        rec[f"mu_{rname}"] = p["mu"]
        if np.isfinite(p["mu"]):
            mus.append(p["mu"])
    rec["mu_spread_bp"] = (max(mus) - min(mus)) if len(mus) > 1 else np.nan
    rows.append(rec)
rg = pd.DataFrame(rows).sort_values("slot")
hl_cols = [c for c in rg.columns if c.startswith("hl_")]
print("OU half-life (business days), full sample vs within regime:")
print(rg[["cm", "slot"] + hl_cols].round(1).to_string(index=False))
print("\nfitted equilibrium mu (bp), full sample vs within regime:")
mu_cols = [c for c in rg.columns if c.startswith("mu_")]
print(rg[["cm"] + mu_cols].round(2).to_string(index=False))
sub = rg[[c for c in hl_cols if c != "hl_full"]].median(axis=1)
print(f"\nmedian half-life: full sample {rg['hl_full'].median():.1f}d vs "
      f"within-regime {sub.median():.1f}d")
print(f"median spread of mu across regimes: {rg['mu_spread_bp'].median():.2f}bp "
      f"(vs a {CONFIG['cost_bp']}bp round trip)")

# %% [markdown]
# ## 3. The corrected first-passage series
#
# The band solver rests on `E[tau]` for the standardised OU. The shipped version
# had `Gamma(k/2)` in the denominator; Monte Carlo settles it.

# %%
mc = {"(-1, +1)": 3.042, "(-0.5, +0.5)": 1.337, "(0, +1)": 2.144, "(-2, +2)": 12.162}
rows = []
for lab_, (a, m) in {"(-1, +1)": (-1.0, 1.0), "(-0.5, +0.5)": (-0.5, 0.5),
                     "(0, +1)": (0.0, 1.0), "(-2, +2)": (-2.0, 2.0)}.items():
    rows.append({"passage": lab_, "monte_carlo": mc[lab_],
                 "series_used": expected_passage_time(a, m, kappa=1.0)})
pt = pd.DataFrame(rows)
pt["error_pct"] = (pt["series_used"] / pt["monte_carlo"] - 1) * 100
print(pt.round(4).to_string(index=False))
print("\n(Monte Carlo run at dt=5e-4 on dz = -z dt + sqrt(2) dW, 40k paths; the "
      "residual is Euler overshoot, which biases MC high.)")

# %% [markdown]
# ## 4. Backtest — rolling OU S-score
#
# `(x - mu_t)/sigma_eq_t` from a trailing OU fit. NaN wherever the window is not
# mean-reverting, so the engine simply does not enter on those bars.

# %%
GRID = {"window": CONFIG["ou_windows"], "entry_z": CONFIG["entry_zs"],
        "exit_style": CONFIG["exits"], "direction": CONFIG["directions"]}
PARAMS = ["window", "entry_z", "exit_style", "direction"]
SIG = lambda L, window: ou_sscore_signal(L, window=window)      # noqa: E731

out = run_family("2. OU S-score (3m, liquid16)", lab=lab, signal_fn=SIG,
                 grid_spec=GRID, params=PARAMS, base=BASE, cls="ou",
                 note="rolling OU fit; entry in sigma_eq units")

# %% [markdown]
# ## 4b. Trade the model's OWN recommended band
#
# The band table above says a band exists that pays. The grid above says no
# config makes money. Those cannot both be right, so this cell resolves them
# directly: for each fly, take the entry threshold and holding period the OU
# model itself recommends at 1.5bp, and trade exactly that.
#
# If this loses money while `ret_per_period` is positive, the failure is not the
# grid — it is that the fitted `(mu, kappa, sigma)` do not persist out of
# sample. That is a much more useful statement than "the sweep was negative".

# %%
sig_full = ou_sscore_signal(levels, window=CONFIG["hl_window"])
rows = []
for key in levels.columns:
    s = levels[key].dropna()
    if len(s) < 300:
        continue
    p = calibrate_ou(s)
    if not np.isfinite(p.get("kappa", np.nan)) or p["kappa"] <= 0:
        continue
    b = ou_band_levels(p, cost=CONFIG["cost_bp"])
    if not np.isfinite(b["entry_z"]) or b["entry_z"] <= 0:
        continue
    hold = int(max(2, min(120, round(b["expected_hold"]))))
    cfg = dataclasses.replace(BASE, entry_z=float(b["entry_z"]),
                              exit_style=f"t{hold}", max_hold=hold + 1,
                              direction="fade", keys=[key])
    r = run_backtest(cfg, levels=levels, signal=sig_full, gate=lab["gate"])
    rows.append({"key": key, "entry_z": b["entry_z"], "hold_d": hold,
                 "model_ret_per_day": b["ret_per_period"],
                 "n_trades": r.metrics["n_trades"],
                 "realised_net_bp": r.metrics["total_net_bp"],
                 "realised_gross_bp": r.metrics["total_gross_bp"]})
own = pd.DataFrame(rows)
if not own.empty:
    print(own.round(3).to_string(index=False))
    print(f"\n  model says every band pays "
          f"({int((own['model_ret_per_day'] > 0).sum())}/{len(own)} positive "
          f"ret_per_day); realised net is positive on "
          f"{int((own['realised_net_bp'] > 0).sum())}/{len(own)} keys, "
          f"total {own['realised_net_bp'].sum():+.1f}bp "
          f"(gross {own['realised_gross_bp'].sum():+.1f}bp) over "
          f"{int(own['n_trades'].sum())} trades")

# %% [markdown]
# ## 5. Holding period set from the measured half-life, not swept
#
# The honesty rule: if the OU fit is the thesis, the exit should come from the
# fit. Each fly is held for `k x its own median half-life`, capped, rather than a
# grid-chosen horizon.

# %%
hl_map = hl.set_index("name")["hl_ols"]      # ou_row() names the column "name"
rows = []
sig = ou_sscore_signal(levels, window=CONFIG["hl_window"])
for k in (0.5, 1.0, 1.5, 2.0):
    tot_bp, tot_tr, tot_usd = 0.0, 0, 0.0
    for key in levels.columns:
        h = hl_map.get(key, np.nan)
        if not np.isfinite(h) or h < 1 or h > 250:
            continue
        hold = int(max(1, min(60, round(k * h))))
        cfg = dataclasses.replace(BASE, exit_style=f"t{hold}", max_hold=hold + 1,
                                  entry_z=2.0, direction="fade", keys=[key])
        r = run_backtest(cfg, levels=levels, signal=sig, gate=lab["gate"])
        tot_bp += r.metrics["total_net_bp"]
        tot_usd += r.metrics["total_net_usd"]
        tot_tr += r.metrics["n_trades"]
    rows.append({"hold_multiple_of_half_life": k, "n_trades": tot_tr,
                 "total_net_bp": tot_bp, "total_net_usd": tot_usd})
print("holding period = k x each fly's OWN fitted half-life:")
print(pd.DataFrame(rows).round(2).to_string(index=False))

# %% [markdown]
# ## 6. Long window and 6m

# %%
lab8 = load_lab(CONFIG["primary_structure"], CONFIG["long_window"])
out8 = run_family("2b. OU S-score (3m, front8, 2019+)", lab=lab8, signal_fn=SIG,
                  grid_spec=GRID, params=PARAMS, base=BASE, cls="ou",
                  note="long history including ZIRP and the hiking cycle")

# %%
lab6 = load_lab("6m", CONFIG["primary_window"])
out6 = run_family("2c. OU S-score (6m, liquid16)", lab=lab6, signal_fn=SIG,
                  grid_spec=GRID, params=PARAMS, base=BASE, cls="ou",
                  note="6m flies")

# %% [markdown]
# ## 7. Rolling half-life stability
#
# A half-life is only usable if it is stable. This plots the rolling estimate for
# the front and back of the strip.

# %%
pick = [c for c in cm_levels.columns
        if lab["slot_of_label"][c] in (2, 5, 8, 12)]
fig, ax = plt.subplots(figsize=(12, 4))
for c in pick:
    rh = rolling_half_life(cm_levels[c].dropna(), CONFIG["hl_window"])
    ax.plot(rh.index, rh.to_numpy(), lw=1.2, label=c)
ax.set_yscale("log")
ax.set_title(f"rolling OU half-life, {CONFIG['hl_window']}d window (log scale)",
             fontsize=11)
ax.set_ylabel("business days")
ax.legend(fontsize=8)
ax.grid(alpha=0.25)
fig.tight_layout()
plt.show()

# %% [markdown]
# # SFR Butterfly — Rules of Thumb
#
# The desk card. For every constant-maturity fly slot, 3m and 6m: where it
# usually trades, how wide the normal range is, where it is now, how fast it
# reverts, and **how far it has to go before fading it has paid net of costs**.
#
# Three things to read before using any number here.
#
# 1. **The regime split is load-bearing.** `SFR123` has a median of **+29bp in
#    the 2022-23 hiking cycle and −2.5bp in the cutting cycle**. A single
#    six-year "typical level" averages incompatible states and is not a level
#    anyone should quote. Every table below is therefore given per regime, and
#    the unconditional column is shown mainly to demonstrate how misleading it is.
#
# 2. **Two band columns, and they answer different questions.** The
#    *descriptive* band uses each slot's full-sample median as the reference, so
#    it is computed with hindsight and states what *would* have paid — it is the
#    "beyond +8 it has historically paid to fade" number, and it is not
#    tradeable. The *causal* band uses a trailing median known at the time, so it
#    is what an actual rule would have earned. Where the two disagree, believe
#    the causal one.
#
# 3. **Cost dominates the back of the strip.** A 1/−2/1 SR3 butterfly costs
#    **1.5bp** round trip (3 legs × 2 sides × 0.25bp). Slots beyond about SFR789
#    have a daily standard deviation under 0.6bp and an interquartile range
#    around 1bp, so the entire normal range of the fly is smaller than the cost
#    of trading it twice.

# %%
CONFIG = dict(
    cost_bp=1.5,
    n_packages=100,
    bands_bp=(0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30),
    max_hold=40,
    ref_window=250,        # trailing window for the CAUSAL reference level
    min_trades=10,
    lag=1,
)
CONFIG

# %%
import sys
from pathlib import Path

sys.path.append("../../")
sys.path.append(str(Path.cwd()))

import numpy as np
import pandas as pd

import matplotlib
if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from RVUtils.MeanRev import MRConfig, run_backtest
from RVUtils.mean_reversion import adf_pvalue, calibrate_ou, half_life
from sfr_fly_meanrev_common import DATA_DIR, REGIME_ORDER, load_lab

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 80)
pd.set_option("display.max_rows", 300)

LABS = {}
for structure in ("3m", "6m"):
    LABS[structure] = load_lab(structure, "liquid16")
    LABS[structure + "_long"] = load_lab(structure, "front8")
print({k: (v["levels"].shape, str(v["levels"].index.min().date()),
           str(v["levels"].index.max().date())) for k, v in LABS.items()})

# %% [markdown]
# ## 1. Where each fly usually trades
#
# On the **constant-maturity** series, which is what a desk means by "the SFR456
# fly". It splices contracts every quarter, so it is a reporting object, never a
# backtest object.

# %%
def level_table(lab, regime=None):
    cm = lab["cm_levels"]
    reg = lab["regimes"].reindex(cm.index)
    rows = []
    for c in cm.columns:
        s = cm[c] if regime is None else cm[c][reg == regime]
        s = s.dropna()
        if len(s) < 60:
            continue
        p = calibrate_ou(s)
        rows.append({"cm": c, "slot": lab["slot_of_label"][c], "n": len(s),
                     "median_bp": s.median(), "mean_bp": s.mean(),
                     "q25": s.quantile(0.25), "q75": s.quantile(0.75),
                     "q05": s.quantile(0.05), "q95": s.quantile(0.95),
                     "sd_bp": s.std(), "iqr_bp": s.quantile(0.75) - s.quantile(0.25),
                     "daily_sd_bp": s.diff().std(),
                     "half_life_d": p["half_life"], "adf_p": adf_pvalue(s)})
    return pd.DataFrame(rows).sort_values("slot")


for structure in ("3m", "6m"):
    lab = LABS[structure]
    print(f"\n{'=' * 100}\n{structure.upper()} FLIES — unconditional "
          f"({lab['levels'].index.min().date()} to "
          f"{lab['levels'].index.max().date()})\n{'=' * 100}")
    t = level_table(lab)
    t["cost_in_iqr"] = CONFIG["cost_bp"] / t["iqr_bp"]
    print(t.round(2).to_string(index=False))

# %% [markdown]
# ## 2. The same table per policy regime
#
# This is the version to quote.

# %%
for structure in ("3m", "6m"):
    lab = LABS[structure + "_long"]     # the long window carries all four regimes
    print(f"\n{'=' * 100}\n{structure.upper()} FLIES — median level (bp) by regime, "
          f"front-8 panel from {lab['levels'].index.min().date()}\n{'=' * 100}")
    parts = {}
    for r in REGIME_ORDER:
        t = level_table(lab, regime=r)
        if t.empty:
            continue
        parts[r] = t.set_index("cm")["median_bp"]
    med = pd.DataFrame(parts)
    med["slot"] = lab["slot_of_label"].reindex(med.index)
    med = med.sort_values("slot").drop(columns="slot")
    # the front-8 panel caps the back leg at slot 8, so deeper slots have no
    # rows in it at all -- drop them rather than print a wall of NaN
    dropped = med.index[med.isna().all(axis=1)].tolist()
    med = med.dropna(how="all")
    med["spread_across_regimes"] = med.max(axis=1) - med.min(axis=1)
    print(med.round(2).to_string())
    if dropped:
        print(f"  (not in the front-8 panel, so no regime history: "
              f"{', '.join(dropped)})")
    print(f"\n  median spread of the 'typical level' across regimes: "
          f"{med['spread_across_regimes'].median():.2f}bp, against a "
          f"{CONFIG['cost_bp']}bp round trip.")

# %%
lab = LABS["3m_long"]
cm = lab["cm_levels"]
reg = lab["regimes"].reindex(cm.index)
show = [c for c in cm.columns if lab["slot_of_label"][c] in (2, 4, 6, 8)]
fig, axes = plt.subplots(len(show), 1, figsize=(13, 2.5 * len(show)), sharex=True)
colors = {"ZIRP": "#90caf9", "HIKING": "#ef9a9a", "PLATEAU": "#fff59d",
          "CUTTING": "#a5d6a7"}
for ax, c in zip(np.atleast_1d(axes), show):
    s = cm[c]
    ax.plot(s.index, s.to_numpy(), lw=1.0, color="#1f4e79")
    for r in REGIME_ORDER:
        m = (reg == r).to_numpy()
        if m.any():
            ax.axvspan(s.index[m][0], s.index[m][-1], color=colors[r], alpha=0.30)
            ax.hlines(s[m].median(), s.index[m][0], s.index[m][-1],
                      color="#c62828", lw=1.6)
    ax.axhline(0, color="grey", lw=0.7)
    ax.set_ylabel(c, fontsize=9)
    ax.grid(alpha=0.2)
np.atleast_1d(axes)[0].set_title(
    "constant-maturity 3m flies with per-regime medians (red)\n"
    "ZIRP / HIKING / PLATEAU / CUTTING shaded", fontsize=11)
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 3. The fade band — how far is far enough?
#
# For each slot and each candidate band `b`, trade the rule: **when the fly is
# more than `b` bp away from its reference, fade it; exit when it returns to the
# reference, or after 40 days.** Lag-1 fills, 1.5bp charged once per completed
# trade. The rule of thumb is the smallest `b` that is net positive with at least
# 10 trades.
#
# Run on the **absolute** flies (no roll), with each trade attributed to the CM
# slot its key occupied on the entry date.

# %%
def band_scan(lab, causal: bool):
    """Net P&L by (CM slot, band). causal=False uses the full-sample median."""
    levels, gate = lab["levels"], lab["gate"]
    cm_at = lab["cm_at"]
    if causal:
        ref = levels.rolling(CONFIG["ref_window"],
                             min_periods=CONFIG["ref_window"] // 2).median()
    else:
        # per-KEY full-sample median. Hindsight by construction.
        ref = pd.DataFrame(np.tile(levels.median(axis=0).to_numpy(), (len(levels), 1)),
                           index=levels.index, columns=levels.columns)
    sig = levels - ref
    rows = []
    for b in CONFIG["bands_bp"]:
        cfg = MRConfig(lag=CONFIG["lag"], entry_z=float(b), exit_style="z0",
                       max_hold=CONFIG["max_hold"], direction="fade",
                       round_trip_cost_bp=CONFIG["cost_bp"],
                       n_packages=CONFIG["n_packages"])
        res = run_backtest(cfg, levels=levels, signal=sig, gate=gate)
        if res.trades.empty:
            continue
        tr = res.trades.copy()
        tr["cm"] = [cm_at.at[pd.Timestamp(e), k] if (pd.Timestamp(e) in cm_at.index
                                                     and k in cm_at.columns) else None
                    for e, k in zip(tr["entry"], tr["key"])]
        for cmv, g in tr.groupby("cm"):
            if cmv is None:
                continue
            rows.append({"cm": cmv, "band_bp": b, "n": len(g),
                         "hit": float((g["net_bp"] > 0).mean()),
                         "avg_net_bp": float(g["net_bp"].mean()),
                         "total_net_bp": float(g["net_bp"].sum()),
                         "avg_gross_bp": float(g["gross_bp"].mean()),
                         "avg_hold": float(g["days"].mean())})
    return pd.DataFrame(rows)


def first_paying_band(scan, min_trades):
    rows = []
    for cmv, g in scan.groupby("cm"):
        g = g.sort_values("band_bp")
        ok = g[(g["total_net_bp"] > 0) & (g["n"] >= min_trades)]
        if ok.empty:
            rows.append({"cm": cmv, "paying_band_bp": np.nan, "n": np.nan,
                         "hit": np.nan, "avg_net_bp": np.nan,
                         "total_net_bp": float(g["total_net_bp"].max()),
                         "best_band_bp": float(g.loc[g["total_net_bp"].idxmax(),
                                                     "band_bp"])})
        else:
            r = ok.iloc[0]
            rows.append({"cm": cmv, "paying_band_bp": r["band_bp"], "n": r["n"],
                         "hit": r["hit"], "avg_net_bp": r["avg_net_bp"],
                         "total_net_bp": r["total_net_bp"],
                         "best_band_bp": float(g.loc[g["total_net_bp"].idxmax(),
                                                     "band_bp"])})
    return pd.DataFrame(rows)


band_out = {}
for structure in ("3m", "6m"):
    lab = LABS[structure]
    for causal in (False, True):
        tag = f"{structure}_{'causal' if causal else 'descriptive'}"
        scan = band_scan(lab, causal=causal)
        band_out[tag] = scan
        fp = first_paying_band(scan, CONFIG["min_trades"])
        fp["slot"] = fp["cm"].map(lab["slot_of_label"])
        fp = fp.sort_values("slot")
        print(f"\n{'=' * 96}\n{structure.upper()} — "
              f"{'CAUSAL (trailing median reference)' if causal else 'DESCRIPTIVE (full-sample median, hindsight)'}"
              f"\n{'=' * 96}")
        print(fp.round(3).to_string(index=False))
        n_pay = int(fp["paying_band_bp"].notna().sum())
        print(f"  slots with ANY band that pays net of "
              f"{CONFIG['cost_bp']}bp: {n_pay}/{len(fp)}")

# %%
fig, axes = plt.subplots(2, 2, figsize=(15, 8))
for i, structure in enumerate(("3m", "6m")):
    for j, causal in enumerate((False, True)):
        scan = band_out[f"{structure}_{'causal' if causal else 'descriptive'}"]
        ax = axes[i][j]
        if scan.empty:
            continue
        piv = scan.pivot_table(index="cm", columns="band_bp", values="avg_net_bp")
        slot = LABS[structure]["slot_of_label"].reindex(piv.index)
        piv = piv.loc[slot.sort_values().index]
        v = np.nanmax(np.abs(piv.to_numpy(dtype=float)))
        im = ax.imshow(piv.to_numpy(dtype=float), aspect="auto", cmap="RdYlGn",
                       vmin=-v, vmax=v)
        ax.set_xticks(range(len(piv.columns)))
        ax.set_xticklabels([f"{c:g}" for c in piv.columns], fontsize=7)
        ax.set_yticks(range(len(piv)))
        ax.set_yticklabels(piv.index, fontsize=7)
        ax.set_xlabel("fade band (bp from reference)")
        ax.set_title(f"{structure} — {'causal' if causal else 'descriptive'} — "
                     f"average net bp per trade", fontsize=10)
        fig.colorbar(im, ax=ax, shrink=0.8)
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 4. The card
#
# Everything a desk needs on one row per slot: where it sits, how wide it swings,
# how fast it reverts, where it is today, and the band beyond which fading it has
# paid.

# %%
cards = []
for structure in ("3m", "6m"):
    lab = LABS[structure]
    lab_long = LABS[structure + "_long"]
    base = level_table(lab).set_index("cm")
    causal = first_paying_band(band_out[f"{structure}_causal"],
                               CONFIG["min_trades"]).set_index("cm")
    desc = first_paying_band(band_out[f"{structure}_descriptive"],
                             CONFIG["min_trades"]).set_index("cm")
    cm = lab["cm_levels"]
    last_date = cm.dropna(how="all").index[-1]
    cur = cm.loc[last_date]
    z = ((cur - cm.median()) / cm.std())
    reg_med = {}
    for r in REGIME_ORDER:
        t = level_table(lab_long, regime=r)
        if not t.empty:
            reg_med[r] = t.set_index("cm")["median_bp"]
    for c in base.index:
        row = {"structure": structure, "cm": c, "slot": base.loc[c, "slot"],
               "typical_bp": base.loc[c, "median_bp"],
               "iqr_bp": base.loc[c, "iqr_bp"],
               "p05_bp": base.loc[c, "q05"], "p95_bp": base.loc[c, "q95"],
               "daily_sd_bp": base.loc[c, "daily_sd_bp"],
               "half_life_d": base.loc[c, "half_life_d"],
               "current_bp": float(cur.get(c, np.nan)),
               "current_z": float(z.get(c, np.nan)),
               "fade_band_causal_bp": causal["paying_band_bp"].get(c, np.nan),
               "hit_at_band": causal["hit"].get(c, np.nan),
               "n_at_band": causal["n"].get(c, np.nan),
               "avg_net_at_band_bp": causal["avg_net_bp"].get(c, np.nan),
               "fade_band_descriptive_bp": desc["paying_band_bp"].get(c, np.nan)}
        for r in REGIME_ORDER:
            row[f"median_{r}"] = (float(reg_med[r].get(c, np.nan))
                                  if r in reg_med else np.nan)
        cards.append(row)
card = pd.DataFrame(cards).sort_values(["structure", "slot"])
print(f"as of {last_date.date()}\n")
print(card.round(2).to_string(index=False))
card.to_csv(DATA_DIR / "rules_of_thumb.csv", index=False)
print(f"\nwrote {DATA_DIR / 'rules_of_thumb.csv'}")

# %% [markdown]
# ## 5. The card in words

# %%
print(f"SFR BUTTERFLY RULES OF THUMB — as of {last_date.date()}")
print(f"1 package = 4 contracts = $25/bp. Round trip {CONFIG['cost_bp']}bp.")
print("=" * 100)
for structure in ("3m", "6m"):
    print(f"\n--- {structure} flies ---")
    for _, r in card[card["structure"] == structure].iterrows():
        band = r["fade_band_causal_bp"]
        rng = f"{r['p05_bp']:+.0f} to {r['p95_bp']:+.0f}"
        line = (f"  {r['cm']:<14s} typically {r['typical_bp']:+5.1f}bp "
                f"(90% range {rng:>12s}, IQR {r['iqr_bp']:4.1f}bp, "
                f"half-life {r['half_life_d']:5.1f}d) | "
                f"now {r['current_bp']:+6.1f}bp (z {r['current_z']:+.2f})")
        if np.isfinite(band):
            line += (f" | FADE beyond +/-{band:.1f}bp "
                     f"(hit {r['hit_at_band']:.0%} over "
                     f"{int(r['n_at_band']) if np.isfinite(r['n_at_band']) else 0} "
                     f"trades)")
        else:
            line += " | NO band pays net of costs"
        print(line)
    hikes = card[card["structure"] == structure]
    cols_r = [f"median_{r}" for r in REGIME_ORDER]
    hikes = hikes[["cm"] + cols_r].dropna(subset=cols_r, how="all")
    if not hikes.empty:
        print(f"\n  regime medians ({structure}, front-8 panel only):")
        print("  " + hikes.round(1).to_string(index=False).replace("\n", "\n  "))

# %% [markdown]
# ## 6. The tick lattice — why the back of the strip only *looks* fast
#
# SR3 settles on a 0.005 price grid outside its final four months (0.0025 inside),
# which is **0.5bp of rate**. A fly is a weighted sum of three settles, so it
# inherits that lattice. When a fly's entire standard deviation is around one
# tick, the series is a 3-5 point lattice — and every mean-reversion estimator
# reads a lattice as strongly reverting. None of it is tradeable, because one
# tick *is* 0.5bp and the round trip is three ticks.

# %%
lab = LABS["3m"]
st = lab["struct"]
TICK = 0.5
rows = []
for cm, g in st.groupby("cm_label_short"):
    v = g["value"].dropna()
    if len(v) < 200:
        continue
    dv = g.sort_values(["key", "as_of"]).groupby("key")["value"].diff().dropna()
    rows.append({"cm": cm, "slot": g["cm_slot"].iloc[0], "sd_bp": v.std(),
                 "sd_in_ticks": v.std() / TICK,
                 "n_distinct_values": v.nunique(),
                 "pct_days_unchanged": float((dv.abs() < 1e-9).mean()),
                 "pct_days_within_1_tick": float((dv.abs() <= TICK + 1e-9).mean()),
                 "half_life_d": half_life(v)})
tick = pd.DataFrame(rows).sort_values("slot")
print(tick.round(3).to_string(index=False))
print(f"\n  the half-life falls monotonically from {tick['half_life_d'].iloc[0]:.1f}d "
      f"to {tick['half_life_d'].iloc[-1]:.1f}d as sd/tick falls from "
      f"{tick['sd_in_ticks'].iloc[0]:.1f} to {tick['sd_in_ticks'].iloc[-1]:.1f}. "
      f"That is discretisation, not economics.")
lattice = tick[tick["sd_in_ticks"] < 2.0]
print(f"  slots whose whole standard deviation is under two ticks: "
      f"{', '.join(lattice['cm']) if len(lattice) else 'none'}")

# %%
fig, ax = plt.subplots(figsize=(11, 4))
ax.plot(tick["cm"], tick["sd_in_ticks"], "o-", color="#1f4e79",
        label="fly sd / 0.5bp tick")
ax.axhline(2.0, color="#c62828", ls="--", lw=1.2, label="two ticks")
ax.set_ylabel("standard deviations per tick")
ax2 = ax.twinx()
ax2.plot(tick["cm"], tick["pct_days_unchanged"] * 100, "s--", color="#2e7d32",
         label="% days unchanged")
ax2.set_ylabel("% of sessions with an unchanged fly", color="#2e7d32")
ax.set_title("the fly's tick lattice by CM slot — the back of the strip barely "
             "moves off its grid", fontsize=11)
ax.tick_params(axis="x", rotation=45, labelsize=8)
ax.legend(fontsize=8, loc="upper right")
ax.grid(alpha=0.25)
fig.tight_layout()
plt.show()

# %% [markdown]
# ## 7. Health warning
#
# Read this before quoting anything above.

# %%
n_slots = len(card)
n_pay = int(card["fade_band_causal_bp"].notna().sum())
spread = (card[[f"median_{r}" for r in REGIME_ORDER]].max(axis=1)
          - card[[f"median_{r}" for r in REGIME_ORDER]].min(axis=1))
print(f"* {n_pay} of {n_slots} constant-maturity slots have ANY causal fade band "
      f"that pays net of {CONFIG['cost_bp']}bp.")
print(f"* The 'typical level' moves by a median of {spread.median():.1f}bp across "
      f"policy regimes, against a {CONFIG['cost_bp']}bp round trip. For "
      f"{int((spread > CONFIG['cost_bp']).sum())} of {n_slots} slots the "
      f"regime-to-regime shift in the fair level is larger than the entire cost "
      f"of the trade, so the unconditional median is not a fair value.")
tight = card[card["iqr_bp"] < CONFIG["cost_bp"]]
print(f"* {len(tight)} slots have an interquartile range narrower than the "
      f"{CONFIG['cost_bp']}bp round trip: "
      f"{', '.join(tight['cm'].tolist()) if len(tight) else 'none'}.")
print("* The descriptive band uses the full-sample median and is therefore "
      "computed with hindsight. Where it disagrees with the causal band, the "
      "causal one is the tradeable number.")
print(f"* {len(lattice)} slots are effectively a tick lattice (standard deviation "
      f"under two 0.5bp ticks): "
      f"{', '.join(lattice['cm']) if len(lattice) else 'none'}. Their short "
      f"fitted half-lives are discretisation, not reversion, and should not be "
      f"used to set a holding period.")

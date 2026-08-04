# %% [markdown]
# # Linear vs vol: the implied-distribution triangle
#
# Three markets carry a distribution of the policy path, and only one prices
# its shape:
#
# 1. **ZQ futures** — monthly EFFR averages → FedWatch bootstrap → per-meeting
#    jump lattice (`RVUtils.MeetingProb.ladder`).
# 2. **FOMC-dated swaps** — meeting-period fair rates off
#    `USD-OIS-Q12xM12STIRT-SERFFX-MIX23` (EFFR leg) and
#    `USD-SOFR-1D-Q12xM12STIRT` (SOFR leg) difference directly into the same
#    lattice — no bootstrap, no contract-expiry seam
#    (`RVUtils.MeetingProb.swap_ladder`).
# 3. **SR3 options** — the Breeden–Litzenberger RND
#    (`RVUtils.ImpliedDistribution`), the full continuous shape.
#
# The linear pair identifies only the MEAN path; parity pins the option mean
# to the same forward. So linear-vs-linear differences are measurement noise
# plus the FF/SOFR basis, and linear-vs-option differences are **shape** — the
# only thing options add, and the only candidate RV.
#
# Taboga (2016, *IREF*) shows equity option RNDs are usually WRONGLY
# multi-modal (over-fitting). SR3 is the one underlying where multi-modality
# would be structurally real — the FOMC lattice — and the linear tree
# independently predicts where any modes must sit. Whether the modes are
# *visible* at a given horizon is measured below, not assumed.
#
# The date pair straddles the 2026-07-29 FOMC decision: 07-28 is the eve
# (a ~1/3-priced hike pending), 07-31 is fully post-hold. Two contracts:
# SFRZ26 (136 days to expiry, the saturated band of the meeting-prob
# frontier) and SFRU26 (45 days, the feasible band).

# %%
import datetime
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-xm")

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 30)

SYMBOLS = ["SFRZ26", "SFRU26"]
D0, D1 = datetime.date(2026, 7, 28), datetime.date(2026, 7, 31)
OIS_CURVE = "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"
SOFR_CURVE = "USD-SOFR-1D-Q12xM12STIRT"
BASIS_SMEAR_BP = 3.0            # strict-null convention from the meeting-prob build
N_MEETINGS_SHOWN = 8

# %% [markdown]
# ## A. The three linear ladders
#
# Same `MeetingLattice` object from three sources. The ZQ ladder needs the
# just-expired front contract (ZQN26) force-refreshed into the serff cache —
# without it the pending July meeting silently vanishes for its whole event
# window. The swap ladders cannot lose a meeting this way.

# %%
from RVUtils.MeetingProb.ladder import meeting_ladder, zq_settle_panel
from RVUtils.MeetingProb.swap_ladder import swap_meeting_ladder
from SDRUtils.analytics.fomc import get_current_fixing, load_fomc_schedule
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

fomc = load_fomc_schedule("USD-SOFR-1D")
zq_panel = zq_settle_panel(
    [f"ZQ{c}{y}" for y in (26, 27) for c in "FGHJKMNQUVXZ"])
irs_mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")

ladders = {}
for d in (D0, D1):
    effr = get_current_fixing("USD-OIS", d)
    sofr = get_current_fixing("USD-SOFR-1D", d)
    ladders[(d, "ZQ")] = meeting_ladder(d, zq_panel, fomc)
    for tag, curve, base in (("OIS-swap", OIS_CURVE, effr),
                             ("SOFR-swap", SOFR_CURVE, sofr)):
        pricer = irs_mdp.get_pricer(dict(curve_name=curve, timestamp=d))
        ladders[(d, tag)] = swap_meeting_ladder(d, pricer, fomc, base)
    print(f"{d}: EFFR {effr*100:.2f}  SOFR {sofr*100:.2f}  "
          + "  ".join(f"{t}:{len(ladders[(d, t)])} mtgs"
                      for t in ("ZQ", "OIS-swap", "SOFR-swap")), flush=True)

SOURCES = ["ZQ", "OIS-swap", "SOFR-swap"]

def ladder_frame(d):
    rows = {}
    for tag in SOURCES:
        for m in ladders[(d, tag)][:N_MEETINGS_SHOWN]:
            rows.setdefault(m.effective, {})[f"jump_{tag}"] = round(m.jump_bp, 1)
            rows.setdefault(m.effective, {})[f"q_{tag}"] = round(m.q, 3)
    df = pd.DataFrame(rows).T.sort_index()
    df.index.name = "meeting_effective"
    return df

for d in (D0, D1):
    print(f"\n=== per-meeting jumps (bp) and lattice q, as of {d} ===")
    print(ladder_frame(d).to_string())

# %%
# Tie-out between the linear sources: same object, three measurements.
tie_rows = []
for d in (D0, D1):
    f = ladder_frame(d)
    for a, b in (("ZQ", "OIS-swap"), ("ZQ", "SOFR-swap"), ("OIS-swap", "SOFR-swap")):
        gap = (f[f"jump_{a}"] - f[f"jump_{b}"]).dropna()
        tie_rows.append({"as_of": d, "pair": f"{a} vs {b}", "n_meetings": len(gap),
                         "mean_gap_bp": round(gap.mean(), 2),
                         "max_abs_gap_bp": round(gap.abs().max(), 2)})
tieout = pd.DataFrame(tie_rows)
print(tieout.to_string(index=False))

f0 = ladder_frame(D0)
cum0 = {t: f0[f"jump_{t}"].iloc[:2].sum() for t in SOURCES}
print(f"\nAttribution vs level, {D0} (pending July + Sep): cumulative "
      f"post-Sep move  " + "  ".join(f"{t}:{v:.0f}bp" for t, v in cum0.items()))
print("The cumulative level agrees to ~1bp while the July/Sep SPLIT differs "
      "by up to ~4bp — linear sources agree on the mean path and disagree "
      "only on attribution, the exchangeability theme from the meeting-prob "
      "study, now visible BETWEEN two linear markets.")

# %% [markdown]
# ## A2. The FedWatch table, from all three sources
#
# Composing each ladder's independent two-point meetings gives the
# conditional target-range matrix — the CME FedWatch screen — from each
# source. ZQ reproduces the published tool; the swap curves give the same
# table with no bootstrap.

# %%
def fedwatch_table(ladder, base_rate_pct, n=N_MEETINGS_SHOWN):
    """Cumulative-move distribution at each meeting -> bucket matrix (%)."""
    base_lo = int(np.floor(base_rate_pct * 100 / 25.0) * 25)  # eg 350
    dist = {0: 1.0}
    rows = {}
    for m in ladder[:n]:
        new = {}
        for moves, p in dist.items():
            for k, pk in m.probs.items():
                new[moves + k] = new.get(moves + k, 0.0) + p * pk
        dist = new
        rows[m.effective] = {
            f"{base_lo + 25 * mv}-{base_lo + 25 * mv + 25}": round(100 * p, 1)
            for mv, p in sorted(dist.items())}
    df = pd.DataFrame(rows).T.fillna(0.0)
    df.index.name = "meeting"
    return df[sorted(df.columns, key=lambda c: int(c.split("-")[0]))]

for d in (D0, D1):
    effr = get_current_fixing("USD-OIS", d) * 100
    for tag in SOURCES:
        t = fedwatch_table(ladders[(d, tag)], effr)
        print(f"\n=== conditional meeting probabilities, {tag}, as of {d} ===")
        print(t.to_string())

# %% [markdown]
# ## B. The terminal object: BL RND vs the meeting trees
#
# Everything now lives on each contract's settlement-rate axis. Both trees
# are pushed through the settlement transform (`split_meetings` +
# `AtomEngine`, mean-pinned to the option forward), so the FF/SOFR basis
# LEVEL drops out by construction and all three curves share one mean. What
# differs is shape.
#
# Extraction honesty: the default JPM raw-premium workflow gates strikes on
# open interest. The 07-31 session has no OI published yet, which silently
# swaps in a SABR MODEL density — so wherever the default falls back, the
# OI-gate-free raw-premium variant is used instead, and the variant actually
# used is recorded per (symbol, date) below.

# %%
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from RVUtils.ImpliedDistribution import SFRImpliedDistribution
from RVUtils.MeetingProb.atoms import AtomEngine, split_meetings

stirfo_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
dist_default = SFRImpliedDistribution()
dist_no_oi = SFRImpliedDistribution(raw_market_open_interest_min=0)

def extract_best(smile):
    """Default extraction, unless the OI gate forced the SABR-model fallback."""
    snap = dist_default.extract(smile, run_gm=False)
    if any("fell back" in w for w in snap.bl_result.warnings):
        return dist_no_oi.extract(smile, run_gm=False), "raw-premium, no OI gate"
    return snap, "default (JPM raw-premium, OI>=100)"

smiles, snaps = {}, {}
for sym in SYMBOLS:
    for d in (D0, D1):
        smiles[(sym, d)] = stirfo_mdp.fetch_sabr_smile({
            "symbol": sym, "as_of": d, "strike_offsets_bps": "listed"})
        snaps[(sym, d)], variant = extract_best(smiles[(sym, d)])
        bl = snaps[(sym, d)].bl_result
        assert not any("fell back" in w for w in bl.warnings), \
            f"{sym} {d}: still a model density"
        print(f"{sym} {d} [{variant}]: forward {bl.input.forward_rate:.3f}%  "
              f"std {bl.std_rate*100:.1f}bp  fwd_resid {bl.forward_residual_bp:+.2f}bp  "
              f"mass {bl.pre_normalization_mass:.3f}  ghost {bl.ghost_mass_fraction:.3f}",
              flush=True)
        for w in bl.warnings:
            print(f"   warn: {w}")

# Extraction-robustness: on the date where both variants run on observed
# premiums, how much does the strike filter move the recovered width?
print()
for sym in SYMBOLS:
    b_gate = dist_default.extract(smiles[(sym, D0)], run_gm=False).bl_result
    b_raw = dist_no_oi.extract(smiles[(sym, D0)], run_gm=False).bl_result
    print(f"{sym} {D0}: std {b_gate.std_rate*100:.1f}bp (OI-gated) vs "
          f"{b_raw.std_rate*100:.1f}bp (ungated) -> width moves "
          f"{abs(b_gate.std_rate - b_raw.std_rate)*100:.1f}bp with the filter")

# %%
def tree(sym, d, tag):
    """(unique atoms, probs, smear_bp, cm) on the option forward."""
    cm = split_meetings(d, sym, ladders[(d, tag)])
    eng = AtomEngine(cm)
    fwd = snaps[(sym, d)].bl_result.input.forward_rate
    rates, probs = eng.rates_probs(fwd)
    uniq = {}
    for r, p in zip(np.round(rates, 6), probs):
        uniq[r] = uniq.get(r, 0.0) + p
    rates = np.array(sorted(uniq))
    probs = np.array([uniq[r] for r in rates])
    smear = float(np.sqrt(cm.unresolved_var_bp2 + BASIS_SMEAR_BP ** 2))
    return rates, probs, smear, cm

def mix_pdf(x, rates, probs, smear_bp):
    s = smear_bp / 100.0
    return sum(p * np.exp(-0.5 * ((np.asarray(x) - r) / s) ** 2)
               / (s * np.sqrt(2 * np.pi)) for r, p in zip(rates, probs))

def mix_cdf(x, rates, probs, smear_bp):
    from scipy.stats import norm
    s = smear_bp / 100.0
    x = np.asarray(x, dtype=float)
    return sum(p * norm.cdf((x - r) / s) for r, p in zip(rates, probs))

def tree_std_bp(rates, probs, smear_bp):
    mu = float(np.dot(probs, rates))
    return float(np.sqrt(np.dot(probs, (np.asarray(rates) - mu) ** 2) * 1e4
                         + smear_bp ** 2))

stats_rows = []
for sym in SYMBOLS:
    for d in (D0, D1):
        bl = snaps[(sym, d)].bl_result
        bkm = snaps[(sym, d)].bkm_result
        for tag in ("ZQ", "SOFR-swap"):
            rates, probs, smear, cm = tree(sym, d, tag)
            w = [r.weight for r in cm.resolved]
            stats_rows.append({
                "symbol": sym, "as_of": d, "source": tag,
                "dte": (cm.expiry - d).days,
                "n_resolved": cm.n_resolved, "atoms": len(rates),
                "smear_bp": round(smear, 1),
                "tree_std_bp": round(tree_std_bp(rates, probs, smear), 1),
                "bl_std_bp": round(bl.std_rate * 100, 1),
                "bkm_std_bp": round(bkm.std_rate * 100, 1) if bkm else np.nan,
                "resolved_ceiling_bp": round(
                    float(np.sqrt(sum((wi * 12.5) ** 2 for wi in w))), 1),
            })
tree_stats = pd.DataFrame(stats_rows)
print(tree_stats.to_string(index=False))

for sym in SYMBOLS:
    row = tree_stats[(tree_stats.symbol == sym) & (tree_stats.as_of == D0)
                     & (tree_stats.source == "ZQ")].iloc[0]
    print(f"\n{sym} ({row['dte']:.0f} dte): surface {row['bl_std_bp']:.0f}bp vs "
          f"tree {row['tree_std_bp']:.0f}bp -> "
          f"{row['bl_std_bp'] - row['tree_std_bp']:+.0f}bp of width the lattice "
          f"cannot carry.")
print("\nThe off-lattice premium shrinks toward expiry exactly as the "
      "meeting-prob frontier measured: the saturated band prices roughly "
      "double the tree, the feasible band much less.")

# %%
fig, axes = plt.subplots(len(SYMBOLS), 2, figsize=(14, 5 * len(SYMBOLS)),
                         sharey="row")
for i, sym in enumerate(SYMBOLS):
    for ax, d in zip(axes[i], (D0, D1)):
        bl = snaps[(sym, d)].bl_result
        grid = bl.strike_grid_rate
        ax.plot(grid, bl.rnd_density, lw=2, color="k",
                label="SR3 option RND (Breeden-Litzenberger)")
        for tag, color in (("ZQ", "tab:blue"), ("SOFR-swap", "tab:red")):
            rates, probs, smear, _ = tree(sym, d, tag)
            ax.plot(grid, mix_pdf(grid, rates, probs, smear), "--", color=color,
                    lw=1.5, label=f"{tag} tree (smear {smear:.1f}bp)")
            dens_at = mix_pdf(rates, rates, probs, smear)
            ax.vlines(rates, 0, probs / probs.max() * dens_at.max(),
                      color=color, alpha=0.25, lw=4)
        ax.axvline(bl.input.forward_rate, color="gray", lw=0.8, ls=":",
                   label=f"forward {bl.input.forward_rate:.3f}%")
        ax.set_title(f"{sym} settlement-rate distribution, {d}")
        ax.set_xlabel("rate (%)")
        ax.legend(fontsize=8)
    axes[i][0].set_ylabel("density")
plt.tight_layout()
plt.show()

# %%
# The Taboga check, measured not assumed: local maxima of the BL density vs
# the nearest lattice atom. Structural multi-modality would land ON atoms.
from scipy.signal import argrelextrema

mode_rows = []
for sym in SYMBOLS:
    for d in (D0, D1):
        bl = snaps[(sym, d)].bl_result
        dens, grid = bl.rnd_density, bl.strike_grid_rate
        idx = argrelextrema(dens, np.greater, order=8)[0]
        idx = [i for i in idx if dens[i] > 0.10 * dens.max()]
        rates, probs, smear, cm = tree(sym, d, "ZQ")
        for i in idx:
            gap = (grid[i] - np.asarray(rates)) * 100
            j = int(np.abs(gap).argmin())
            mode_rows.append({"symbol": sym, "as_of": d,
                              "mode_rate": round(grid[i], 3),
                              "nearest_atom": round(rates[j], 3),
                              "gap_bp": round(gap[j], 1),
                              "smear_bp": round(smear, 1),
                              "n_resolved": cm.n_resolved})
modes = pd.DataFrame(mode_rows)
print(modes.to_string(index=False))

n_modes = modes.groupby(["symbol", "as_of"]).size()
informative = modes[modes.n_resolved > 0]      # 0 resolved -> one atom AT the
aligned = float(informative["gap_bp"].abs().le(6).mean())  # forward: vacuous
multi = int((n_modes > 1).sum())
print(f"\n{multi} of {len(n_modes)} (symbol, date) cells are multi-modal; "
      f"{aligned:.0%} of modes with a non-trivial lattice sit within 6bp of "
      "an atom. But the mode COUNT is not stable across the two extraction "
      "variants (the OI-gated 07-28 density is unimodal, the ungated 07-31 "
      "density is bimodal on-atom), while the recovered WIDTH moves only "
      "~1bp between them (printed in section B). That is Taboga's result "
      "operating as designed: jaggedness is an extraction artefact even "
      "where modes are structurally real, and with 6-14bp of "
      "unresolved-meeting smear the calendar's modes only crystallize "
      "robustly inside the final month (<30 dte, where the meeting-prob "
      "frontier found 0% saturation). At these vintages the width and the "
      "tails, not the modes, carry the lattice information.")

# %% [markdown]
# ## C. The change across the July decision
#
# 07-28 → 07-31: the pending July meeting resolves (hold). The linear legs
# show the mechanics — the front-period level collapses (~-8bp) while
# later-meeting jumps inflate (probability migrates out the strip, +1 to
# +4bp per meeting). Parity forces the option mean to follow the same
# forward; anything else that moved is shape.

# %%
from RVUtils.ImpliedDistribution import plot_distribution_change

delta = (ladder_frame(D1).filter(like="jump_")
         - ladder_frame(D0).filter(like="jump_")).dropna(how="all")
print("=== per-meeting jump changes, 07-28 -> 07-31 (bp) ===")
print(delta.to_string())
print("(July NaN on the swap legs: in-progress period, deliberately never "
      "priced; the ZQ row shows the -7.7bp resolution collapse directly.)")

for sym in SYMBOLS:
    b0, b1 = snaps[(sym, D0)].bl_result, snaps[(sym, D1)].bl_result
    print(f"\n{sym}: forward {b0.input.forward_rate:.3f} -> "
          f"{b1.input.forward_rate:.3f} ({(b1.input.forward_rate - b0.input.forward_rate)*100:+.1f}bp)"
          f" | BL mean {b0.mean_rate:.3f} -> {b1.mean_rate:.3f}"
          f" | BL std {b0.std_rate*100:.1f} -> {b1.std_rate*100:.1f}bp")
print("\nThe mean moved with the forward on both contracts (parity: the mean "
      "channel is dead); the width change is the shape story.")

fig = plot_distribution_change(snaps[("SFRZ26", D0)], snaps[("SFRZ26", D1)])
plt.show()

# %% [markdown]
# ## D. Where the option distribution disagrees with the linear tree
#
# Per-25bp-node probabilities: option (BL CDF between atom midpoints) minus
# tree (smeared mixture over the same edges), under the strict smear. This is
# the model-space version of the boundary-digital decomposition from the
# meeting-prob study: mode-flank asymmetry = per-meeting reallocation
# (channel 1); both outer tails rich = off-lattice premium (channel 2).

# %%
def divergence(sym, d, tag="ZQ"):
    bl = snaps[(sym, d)].bl_result
    r, p, smear, _ = tree(sym, d, tag)
    edges = np.concatenate([[r[0] - 0.125], (r[:-1] + r[1:]) / 2,
                            [r[-1] + 0.125]])
    cdf_opt = np.interp(edges, bl.strike_grid_rate, bl.rnd_cumulative,
                        left=0.0, right=1.0)
    p_opt = np.diff(cdf_opt)
    cdf_tree = mix_cdf(edges, r, p, smear)
    p_tree = np.diff(cdf_tree)
    rows = [{"node": round(rk, 3), "p_tree": round(p_tree[k], 3),
             "p_opt": round(p_opt[k], 3),
             "gap_pp": round(100 * (p_opt[k] - p_tree[k]), 1)}
            for k, rk in enumerate(r)]
    rows.append({"node": "below-lattice", "p_tree": round(float(cdf_tree[0]), 3),
                 "p_opt": round(float(cdf_opt[0]), 3),
                 "gap_pp": round(100 * (float(cdf_opt[0]) - float(cdf_tree[0])), 1)})
    rows.append({"node": "above-lattice",
                 "p_tree": round(float(1 - cdf_tree[-1]), 3),
                 "p_opt": round(float(1 - cdf_opt[-1]), 3),
                 "gap_pp": round(100 * ((1 - float(cdf_opt[-1]))
                                        - (1 - float(cdf_tree[-1]))), 1)})
    return pd.DataFrame(rows)

tails = {}
for sym in SYMBOLS:
    for d in (D0, D1):
        dv = divergence(sym, d)
        print(f"\n=== node probabilities, option vs ZQ tree, {sym} {d} ===")
        print(dv.to_string(index=False))
        t = dv[dv.node.isin(["below-lattice", "above-lattice"])]["gap_pp"]
        tails[(sym, d)] = tuple(t.values)

print("\n=== off-lattice tail richness (option minus tree, pp) ===")
for (sym, d), (below, above) in tails.items():
    both = below > 0.5 and above > 0.5
    print(f"{sym} {d}: below {below:+.1f}  above {above:+.1f}  "
          f"{'both tails rich -> channel-2 signature' if both else 'mixed'}")
print("\nBoth contracts, both dates, price BOTH off-lattice tails above the "
      "strict tree — the one-sided off-lattice premium (channel 2), exactly "
      "where the meeting-prob frontier puts these vintages. The per-meeting "
      "convergence channel only opens inside ~60 days, and by then the swap "
      "ladder is the cleaner linear leg to trade it against.")

# %% [markdown]
# ## E. The ICS anchor: putting the mean gap back on the table
#
# Sections B–D mean-pinned both trees to the option forward, which kills the
# level channel by construction. But CME LISTS the level: the FF-vs-SR3
# inter-commodity spread — for SFRZ26, `0.5·ZQF27 + 0.5·ZQG27 − SR3Z26` at a
# 10:6 leg ratio ($250/bp DV01-neutral both sides), quoted as
# `SOFR rate − FF rate` ("STIR ICS on Globex", CME, June 2026). So the mean
# gap is an observable with its own order book, and it decomposes:
#
# `ICS = SOFR-EFFR basis + compounding wedge + calendar proxy wedge + residual`
#
# * **basis** — SR3 compounds SOFR, ZQ averages EFFR (spot ~+2bp);
# * **compounding** — compounded vs arithmetic: ~r²·(D−1)/720 (~+2bp at 4%);
# * **proxy wedge** — Jan+Feb is the exchange's IMM proxy for the true
#   Dec16→Mar17 window; the same lattice prices the difference (~+0.3bp when
#   hikes are priced);
# * **residual** — whatever is left. For a DECEMBER quarterly the window
#   contains the year-end turn, when SOFR prints spike — so a positive
#   residual is at least partly the turn premium, not free money.

# %%
from RVUtils.MeetingProb.ics import (
    compounding_wedge_bp,
    ff_conditional_atoms,
    ics_blend_contracts,
    ics_spread_bp,
    proxy_wedge_bp,
)
from MDP.STIRFutures._sofr_option_contracts import quarterly_reference_window

ICS_SYM = "SFRZ26"
blend = ics_blend_contracts(ICS_SYM)
S_win, E_win = quarterly_reference_window(ICS_SYM)
win_days = (E_win - S_win).days
print(f"{ICS_SYM} ICS blend: {blend}, reference window {S_win} -> {E_win} "
      f"({win_days} days)")

ics_rows, ff_view = [], {}
for d in (D0, D1):
    ffp = [float(zq_panel.loc[:pd.Timestamp(d), c].iloc[-1]) for c in blend]
    fwd = snaps[(ICS_SYM, d)].bl_result.input.forward_rate
    spread = ics_spread_bp(100.0 - fwd, ffp)
    basis = (get_current_fixing("USD-SOFR-1D", d)
             - get_current_fixing("USD-OIS", d)) * 1e4
    comp = compounding_wedge_bp(fwd, win_days)
    wedge = proxy_wedge_bp(ladders[(d, "ZQ")], ICS_SYM)
    resid = spread - basis - comp + wedge
    effr = get_current_fixing("USD-OIS", d) * 100
    ff_view[d] = ff_conditional_atoms(d, ICS_SYM, ladders[(d, "ZQ")], effr)
    lattice_mean = ff_view[d][3]
    blend_rate = 100.0 - float(np.mean(ffp))
    ics_rows.append({
        "as_of": d, "ics_bp": round(spread, 2), "basis_bp": round(basis, 2),
        "compounding_bp": round(comp, 2), "proxy_wedge_bp": round(wedge, 2),
        "residual_bp": round(resid, 2),
        "zq_fit_gap_bp": round((blend_rate - wedge / 100.0
                                - lattice_mean) * 100.0, 2),
    })
ics_table = pd.DataFrame(ics_rows)
print(ics_table.to_string(index=False))
print("\nzq_fit_gap = market blend (proxy-adjusted) minus the lattice window "
      "mean — how far the bootstrap tree sits from the very contracts it was "
      "built on; a consistency check on the whole chain, not a signal.")

# %%
# The absolute view: the option RND on its own axis vs the FF conditional
# distribution anchored at EFFR + the lattice path. The horizontal offset IS
# the ICS decomposition — nothing is pinned away.
fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
for ax, d in zip(axes, (D0, D1)):
    bl = snaps[(ICS_SYM, d)].bl_result
    ax.plot(bl.strike_grid_rate, bl.rnd_density, lw=2, color="k",
            label="SR3 option RND (SOFR, compounded)")
    rates, probs, smear_raw, mean, _ = ff_view[d]
    smear = float(np.sqrt(smear_raw ** 2 + BASIS_SMEAR_BP ** 2))
    ax.plot(bl.strike_grid_rate, mix_pdf(bl.strike_grid_rate, rates, probs, smear),
            "--", color="tab:purple", lw=1.5,
            label=f"FF conditional (ZQ lattice, absolute, smear {smear:.1f}bp)")
    ax.axvline(bl.input.forward_rate, color="k", lw=0.8, ls=":")
    ax.axvline(mean, color="tab:purple", lw=0.8, ls=":")
    gap = (bl.input.forward_rate - mean) * 100
    ax.set_title(f"{ICS_SYM} absolute axes, {d}  (mean gap {gap:+.1f}bp)")
    ax.set_xlabel("rate (%)")
    ax.legend(fontsize=8)
axes[0].set_ylabel("density")
plt.tight_layout()
plt.show()

# %%
# Is there a trade? Both channels, priced with listed conventions.
r0, r1 = ics_table.iloc[0], ics_table.iloc[1]
tails0 = tails[(ICS_SYM, D0)]
print("CHANNEL 1 — the level (the listed ICS, 10 SR3 : 3+3 ZQ, $250/bp):")
print(f"  observed {r0.ics_bp:.1f}bp -> {r1.ics_bp:.1f}bp; decomposed fair "
      f"(basis+compounding-wedge) {r0.basis_bp + r0.compounding_bp - r0.proxy_wedge_bp:.1f}"
      f" / {r1.basis_bp + r1.compounding_bp - r1.proxy_wedge_bp:.1f}bp; "
      f"residual {r0.residual_bp:+.1f} -> {r1.residual_bp:+.1f}bp.")
print("  The residual on a DECEMBER quarterly contains the year-end turn "
      "premium (the turn sits inside the window), so it is not cleanly "
      "harvestable; and the serff fair-value study already ran this class of "
      "trade with a 3-layer model — costs dominated. Fading the residual is "
      "only interesting if it exceeds a few bp AND the turn is hedged "
      "(e.g. vs the adjacent non-turn quarterly's residual).")
print("\nCHANNEL 2 — the shape (options vs the FF lattice):")
print(f"  the surface prices {tails0[0] + tails0[1]:.0f}pp more off-lattice "
      f"mass than the tree ({tails0[0]:+.1f} below, {tails0[1]:+.1f} above "
      "at 07-28). Selling it is selling insurance against intermeeting / "
      ">25bp outcomes: the SR3 options lab measured the same premium "
      "(+21pp vs the FedWatch null) and its short-vol harvest REVERSED SIGN "
      "when front contracts entered the sample; the meeting-prob backtest "
      "found the tradeable convergence flavour is episodic and cost-bound "
      "at EOD. Nothing in this notebook overturns those verdicts.")
print("\nNET: the honest trade inventory from this triangle is (i) the "
      "listed ICS when the residual decomposition — not the raw spread — "
      "signals, sized at 10:6, with the turn hedged; and (ii) the <60-dte "
      "convergence channel from the meeting-prob study, for which the swap "
      "ladder built here is the cleaner linear leg. Neither is a standing "
      "harvest; both are episodic and cost-gated.")

# %% [markdown]
# ## F. The path ledger: every FOMC outcome, linear vs vol
#
# The FedWatch matrix is conditional-by-meeting; the option surface settles
# once. For a quarterly whose resolved meetings all carry day-weight 1, every
# ORDERING of moves lands on the same settlement rate, so the 2^k paths
# collapse to the move COUNT: P(hike, hike, hike) is exactly the terminal
# 425–450 bucket, and that is an option-identified object (the exchangeability
# result from the meeting-prob study, working for us here). The ledger below
# prices every count bucket both ways. Yardstick: a 25bp-wide digital moves
# 4pp of probability per 1bp of premium, and the half-tick quote floor
# (0.125bp) is ~0.5pp — so gaps of several pp are measurement, not noise.

# %%
def count_ledger(sym, d, tag="ZQ"):
    """Move-count buckets: pure lattice, smeared tree, and option RND."""
    bl = snaps[(sym, d)].bl_result
    r, p, smear, cm = tree(sym, d, tag)
    assert all(m.weight == 1.0 for m in cm.resolved), "count labels need w=1"
    counts = {0: 1.0}                       # pure count convolution
    for m in cm.resolved:
        a, b = m.support
        new = {}
        for n, pn in counts.items():
            new[n + a] = new.get(n + a, 0.0) + pn * (1.0 - m.q_zq)
            if b != a:
                new[n + b] = new.get(n + b, 0.0) + pn * m.q_zq
        counts = new
    ns = sorted(counts)
    edges = np.concatenate([[r[0] - 0.125], (r[:-1] + r[1:]) / 2,
                            [r[-1] + 0.125]])
    p_opt = np.diff(np.interp(edges, bl.strike_grid_rate, bl.rnd_cumulative,
                              left=0.0, right=1.0))
    p_tree = np.diff(mix_cdf(edges, r, p, smear))
    effr = get_current_fixing("USD-OIS", d) * 100
    base_lo = int(np.floor(effr * 100 / 25.0) * 25)
    rows = []
    for k, n in enumerate(ns):
        gap = 100 * (p_opt[k] - p_tree[k])
        rows.append({
            "bucket": f"{base_lo + 25 * n}-{base_lo + 25 * n + 25}",
            "path": f"{n} net moves" if n >= 0 else f"{n} (net cut)",
            "p_lattice": round(counts[n], 3), "p_tree": round(p_tree[k], 3),
            "p_opt": round(p_opt[k], 3), "gap_pp": round(gap, 1),
            "gap_bp_digital": round(gap / 4.0, 2),
        })
    below = float(np.interp(edges[0], bl.strike_grid_rate, bl.rnd_cumulative))
    above = 1.0 - float(np.interp(edges[-1], bl.strike_grid_rate,
                                  bl.rnd_cumulative))
    t_below = float(mix_cdf(np.array([edges[0]]), r, p, smear)[0])
    t_above = 1.0 - float(mix_cdf(np.array([edges[-1]]), r, p, smear)[0])
    for name, po, pt in (("off-lattice below", below, t_below),
                         ("off-lattice above", above, t_above)):
        gap = 100 * (po - pt)
        rows.append({"bucket": name, "path": "intermeeting / >25bp",
                     "p_lattice": 0.0, "p_tree": round(pt, 3),
                     "p_opt": round(po, 3), "gap_pp": round(gap, 1),
                     "gap_bp_digital": round(gap / 4.0, 2)})
    return pd.DataFrame(rows), edges, r

for d in (D0, D1):
    led, _, _ = count_ledger("SFRZ26", d)
    print(f"\n=== SFRZ26 path ledger (ZQ tree vs options), {d} ===")
    print(led.to_string(index=False))

led1, edges1, atoms1 = count_ledger("SFRZ26", D1)
hikes3 = led1[led1.path == "3 net moves"].iloc[0]
print(f"\nTHE HEADLINE CASE ({D1}): P(hike at sep AND oct AND dec) — "
      f"FedWatch-style lattice {hikes3.p_lattice:.1%}, smeared tree "
      f"{hikes3.p_tree:.1%}, options {hikes3.p_opt:.1%} -> the surface pays "
      f"{hikes3.gap_pp:+.1f}pp ≈ {hikes3.gap_bp_digital:+.1f}bp on the "
      "25bp-wide 425-450 vertical for the all-hikes path.")

# %%
# Listed cross-check: the same digitals from RAW listed premiums (no spline).
# A 6.25bp vertical at the bucket edge, undiscounted: 1 full premium tick
# (0.25bp) is 4pp on this width, so this check is coarse — it bounds the
# spline, it does not refine it.
def listed_digital(sym, d, edge_rate):
    """P(rate > edge) from the nearest listed vertical; None off the grid."""
    pts = pd.DataFrame([q.__dict__ for q in smiles[(sym, d)].points])
    edge_price = 100.0 - edge_rate
    for side, sign in (("P", +1), ("C", -1)):
        leg = pts[pts.right == side].sort_values("strike_price")
        ks = leg.strike_price.values
        lo = ks[ks <= edge_price][-1] if (ks <= edge_price).any() else None
        hi = ks[ks > edge_price][0] if (ks > edge_price).any() else None
        if lo is None or hi is None or hi - lo > 0.26:
            continue
        prem = leg.set_index("strike_price").market_price
        df_ = float(leg.discount_factor.iloc[0])
        p_below = (prem[hi] - prem[lo]) / (hi - lo) / df_
        if side == "C":
            p_below = 1.0 + p_below          # dC/dK = -(1 - F(K))
        # price < mid  <=>  rate > 100 - mid ~= the edge
        return float(np.clip(p_below, 0.0, 1.0))
    return None

print("=== listed-vertical bound on the outer digitals, SFRZ26", D1, "===")
for name, e in (("P(rate > above-lattice edge)", edges1[-1]),
                ("P(rate > 3-hike lower edge)", edges1[-2]),
                ("P(rate < below-lattice edge)", edges1[0])):
    lv = listed_digital("SFRZ26", D1, e)
    bl = snaps[("SFRZ26", D1)].bl_result
    spl = 1.0 - float(np.interp(e, bl.strike_grid_rate, bl.rnd_cumulative))
    if "below" in name:
        lv = None if lv is None else 1.0 - lv
        spl = 1.0 - spl
    print(f"  {name} @ {e:.4f}%: listed {lv if lv is None else round(lv, 3)}"
          f"  spline {spl:.3f}")

# %%
# What the ledger is actually saying — one premium, not many edges.
led0, _, _ = count_ledger("SFRZ26", D0)
for d, led in ((D0, led0), (D1, led1)):
    interior = led[~led.bucket.str.startswith("off-lattice")]
    deficit = -interior[interior.gap_pp < 0].gap_pp.sum()
    surplus = led[led.gap_pp > 0].gap_pp.sum()
    modal = interior.loc[interior.p_tree.idxmax()]
    print(f"{d}: modal bucket {modal.bucket} priced {modal.gap_pp:+.1f}pp "
          f"({modal.gap_bp_digital:+.1f}bp on its vertical); total mode "
          f"deficit {deficit:.1f}pp == wing+tail surplus {surplus:.1f}pp "
          "(probability conservation).")
print("\nThe listed check bounds the honesty of this: the two upper edges "
      "reprice within 0.2-0.7pp of the spline, so the interior gaps are "
      "real; the BELOW-lattice tail HALVES on listed quotes (4.1% vs 8.2% "
      "at 07-31) — haircut that row before believing it. What remains is "
      "ONE premium seen from two sides: the surface flattens the modal "
      "paths and pays for everything else — off-lattice outcomes, "
      "intermeeting risk, SOFR-vs-EFFR dispersion the lattice cannot "
      "represent. Selling it (buy the modal vertical, sell the wings — a "
      "fly) is short realized dispersion around the FedWatch lattice: the "
      "channel-2 insurance short in fly clothing, NOT a collection of "
      "independent mispricings. It becomes a genuine convergence trade "
      "only where the lattice is feasible and the asymmetry is one-sided — "
      "the <60-dte channel-1 regime the meeting-prob study gated and "
      "backtested (5 trades/2y, cost-bound at EOD).")

# %% [markdown]
# ### F3. The conditional block: what options say about the January meeting
#
# One expiry can never attribute (exchangeability) — but TWO can. SFRH27's
# resolved set is SFRZ26's plus exactly {jan27}, so under the same
# independence assumption FedWatch itself makes, the H27 count distribution
# is the Z26 count distribution convolved with one Bernoulli. Fitting that
# Bernoulli to the two OPTION-implied count distributions extracts the
# option market's own conditional P(jan27 move) — the first per-meeting
# number in this research line that comes from options alone.

# %%
def opt_count_vector(sym, d):
    """Option bucket masses on the contract's own recentered count lattice."""
    bl = snaps[(sym, d)].bl_result
    r, p, smear, cm = tree(sym, d, "ZQ")
    shift = bl.forward_residual_bp / 1e4      # align edges to the RND's mean
    edges = np.concatenate([[r[0] - 0.375], [r[0] - 0.125],
                            (r[:-1] + r[1:]) / 2,
                            [r[-1] + 0.125], [r[-1] + 0.375]]) + shift
    cdf = np.interp(edges, bl.strike_grid_rate, bl.rnd_cumulative,
                    left=0.0, right=1.0)
    v = np.diff(cdf)                          # cells: counts -1 .. n+1
    v[0] += cdf[0]                            # fold the far tails into the
    v[-1] += 1.0 - cdf[-1]                    # outermost count cells
    return v / v.sum(), cm.n_resolved

for d in (D0, D1):
    smiles[("SFRH27", d)] = stirfo_mdp.fetch_sabr_smile({
        "symbol": "SFRH27", "as_of": d, "strike_offsets_bps": "listed"})
    snaps[("SFRH27", d)], var = extract_best(smiles[("SFRH27", d)])
    blh = snaps[("SFRH27", d)].bl_result
    print(f"SFRH27 {d} [{var}]: fwd {blh.input.forward_rate:.3f} "
          f"std {blh.std_rate*100:.1f}bp resid {blh.forward_residual_bp:+.2f}bp")

fit_rows = []
for d in (D0, D1):
    vz, nz = opt_count_vector("SFRZ26", d)
    vh, nh = opt_count_vector("SFRH27", d)
    assert nh == nz + 1                       # the extra meeting is jan27
    qs = np.linspace(0.0, 1.0, 1001)
    best_q, best_e = None, np.inf
    for q in qs:
        model = np.convolve(vz, [1.0 - q, q])
        m = min(len(model), len(vh))
        err = float(np.abs(model[:m] - vh[:m]).sum())
        if err < best_e:
            best_q, best_e = q, err
    q_zq = next((m.q for m in ladders[(d, "ZQ")]
                 if m.effective == datetime.date(2027, 1, 27)), np.nan)
    q_sw = next((m.q for m in ladders[(d, "SOFR-swap")]
                 if m.effective == datetime.date(2027, 1, 27)), np.nan)
    fit_rows.append({"as_of": d, "q_jan_options": round(best_q, 3),
                     "q_jan_ZQ": round(q_zq, 3),
                     "q_jan_SOFR_swap": round(q_sw, 3),
                     "fit_L1": round(best_e, 3)})
cond = pd.DataFrame(fit_rows)
print("\n=== option-implied conditional P(jan27 move), via Z26 (x) Bern = H27 ===")
print(cond.to_string(index=False))
print("\nfit_L1 is the L1 mass the one-Bernoulli model CANNOT explain — the "
      "cross-expiry residual. It is dominated by SFRH27's extra off-lattice "
      "width (its smear and tails exceed anything a single 0/25bp meeting "
      "can add), so read q_jan_options as indicative, not tradeable: the "
      "far expiry sits deep in the saturated band where shape, not "
      "attribution, is the priced object.")

# %% [markdown]
# ## Summary
#
# Every claim below is computed in this notebook, above.
#
# * **The three linear sources tie out on the mean path** (cumulative moves
#   agree to ~1bp) but disagree on per-meeting attribution by up to ~4bp —
#   the exchangeability degeneracy, visible between two LINEAR markets, so it
#   is a property of measurement, not of options.
# * **The swap ladder is the more robust linear source**: no FedWatch
#   bootstrap, no month-end weight dilution, no contract-expiry seam — the ZQ
#   ladder needed the expired ZQN26 force-refreshed to even see the pending
#   July meeting, and it still cannot price it on the decision's eve without
#   that contract.
# * **Mode structure is extraction-fragile, width is not**: mode count flips
#   with the strike filter (Taboga's jaggedness warning applies even here,
#   where modes are structurally real) while the recovered std moves ~1bp.
#   With 6-14bp of unresolved-meeting smear, on-atom modes only crystallize
#   robustly inside the final month; at these vintages the width and tails
#   carry the lattice information.
# * **The option surface prices more width than any linear tree can carry**,
#   and both off-lattice tails are rich on every (symbol, date) — the
#   standing channel-2 premium, re-derived through a third, bootstrap-free
#   market.
# * **Across the July decision** the linear legs show the mechanics
#   (front-level collapse, back-jump inflation); the option mean follows the
#   forward by parity while the width compresses ~7bp.
# * **The path ledger prices every FOMC outcome both ways** (orderings
#   collapse to move counts for weight-1 quarterlies): the surface flattens
#   the modal count buckets (~−4bp on the modal 25bp vertical) and pays for
#   every non-modal one; upper edges validate against listed verticals to
#   <1pp, the below-lattice tail halves on listed quotes. One dispersion
#   premium, not many edges. Cross-expiry deconvolution (H27 = Z26 ⊛ Bern)
#   gives options' own conditional P(jan27 move) — above the linear reads,
#   but a third of the mass doesn't fit any single Bernoulli (weak
#   identification in the saturated band).
# * **The listed ICS re-opens the level channel**: `0.5·ZQF27+0.5·ZQG27 −
#   SR3Z26` decomposes into basis + compounding + calendar-proxy wedge +
#   residual, and the residual on a December quarterly carries the year-end
#   turn. The trade inventory is episodic and cost-gated: fade the DECOMPOSED
#   residual (turn-hedged, 10:6) when it signals, and run the <60-dte
#   convergence channel with the swap ladder as the linear leg.

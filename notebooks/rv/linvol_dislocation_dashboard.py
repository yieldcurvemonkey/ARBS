# %% [markdown]
# # Linear vs Vol — the dislocation dashboard (interactive)
#
# Every layer of the linear-vs-vol RV framework in one interactive view
# (plotly, dark, unified-hover crosshairs — hover, zoom, toggle legends,
# switch dropdowns):
#
# 1. **The triangle** — option-implied RND vs the ZQ-lattice tree vs the
#    FOMC-swap tree on one settlement-rate axis, per (contract, date).
# 2. **The count-bucket ledger** — every FOMC path priced both ways.
# 3. **The ICS residual** — the level channel decomposed (basis /
#    compounding / calendar wedge / residual) through time.
# 4. **The feasibility frontier** — where the lattice can and cannot carry
#    the surface's width, every contract-day in the panel.
# 5. **Boundary-digital gaps** — the per-day shape dislocation the
#    convergence channel trades.
# 6. **Family-B richness** — listed premium minus tree-fair for the
#    dispersion books, with the pre-registered fade's trades marked.

# %%
CONFIG = dict(
    snap_symbols=("SFRZ26", "SFRU26"),
    snap_dates=("2026-07-28", "2026-07-31"),
    ledger_symbol="SFRZ26",
    richness_books=(("STRG75", 1), ("STRG50", 1), ("FLY25", 1),
                    ("STRG75", 2)),
    fade=dict(book="STRG75", rank=1, thr_bp=4.0, exit_frac=0.25,
              max_hold=15, direction="fade"),
    ics_default_symbol="SFRZ26",
)
CONFIG

# %%
import datetime
import os
import sys
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.append("../../")
sys.path.append("../backtests")

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

pio.renderers.default = "notebook_connected"   # plotly.js from CDN keeps
                                               # the committed .ipynb small
DARK = "plotly_dark"
C = dict(opt="#e0e0e0", zq="#42a5f5", swap="#ef5350", atom="#42a5f5",
         fwd="#9e9e9e", resid="#ffca28", rich="#ce93d8", entry="#ef5350",
         exit="#66bb6a")


def style(fig, title, *, xtitle=None, ytitle=None, height=430):
    fig.update_layout(
        template=DARK, title=title, height=height,
        hovermode="x unified", legend=dict(font=dict(size=10)),
        margin=dict(l=55, r=25, t=55, b=45),
    )
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                     spikethickness=1, spikedash="dot", title=xtitle)
    fig.update_yaxes(showspikes=True, spikethickness=1, spikedash="dot",
                     title=ytitle)
    return fig


def show(fig):
    """Display in a kernel; in a plain-python dry-run just summarize —
    dumping 5MB of plotly HTML into a cp1252 console dies on encode."""
    if "ipykernel" in sys.modules:
        fig.show()
    else:
        t = fig.layout.title.text or ""
        print(f"[fig] {t[:64]} - {len(fig.data)} traces", flush=True)


DATA_MP = Path("../data/meeting_prob")
DATA_LG = Path("../data/linvol_grid")

# %% [markdown]
# ## Data spine: ladders, swap ladders, smiles, panels

# %%
from RVUtils.MeetingProb import meeting_ladder, split_meetings, zq_settle_panel
from RVUtils.MeetingProb.atoms import AtomEngine
from RVUtils.MeetingProb.swap_ladder import swap_meeting_ladder
from SDRUtils.analytics.fomc import get_current_fixing, load_fomc_schedule
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from RVUtils.ImpliedDistribution import SFRImpliedDistribution

fomc = load_fomc_schedule("USD-SOFR-1D")
zq_panel = zq_settle_panel([f"ZQ{c}{y}" for y in (26, 27)
                            for c in "FGHJKMNQUVXZ"])
irs_mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
stirfo = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
dist_default = SFRImpliedDistribution()
dist_no_oi = SFRImpliedDistribution(raw_market_open_interest_min=0)

SNAP_DATES = [pd.Timestamp(d).date() for d in CONFIG["snap_dates"]]
ladders, swap_ladders, snaps = {}, {}, {}
for d in SNAP_DATES:
    ladders[d] = meeting_ladder(d, zq_panel, fomc)
    sofr = get_current_fixing("USD-SOFR-1D", d)
    pricer = irs_mdp.get_pricer(dict(
        curve_name="USD-SOFR-1D-Q12xM12STIRT", timestamp=d))
    swap_ladders[d] = swap_meeting_ladder(d, pricer, fomc, sofr)
    for sym in CONFIG["snap_symbols"]:
        sm = stirfo.fetch_sabr_smile({"symbol": sym, "as_of": d,
                                      "strike_offsets_bps": "listed"})
        snap = dist_default.extract(sm, run_gm=False)
        if any("fell back" in w for w in snap.bl_result.warnings):
            snap = dist_no_oi.extract(sm, run_gm=False)
        snaps[(sym, d)] = snap
print(f"spine ready: {len(SNAP_DATES)} dates x {len(CONFIG['snap_symbols'])} "
      f"symbols", flush=True)


def tree_curve(sym, d, ladder, grid):
    cm = split_meetings(d, sym, ladder)
    if cm is None:
        return None
    fwd = snaps[(sym, d)].bl_result.input.forward_rate
    rates, probs = AtomEngine(cm).rates_probs(fwd)
    uniq = {}
    for r, p in zip(np.round(rates, 6), probs):
        uniq[r] = uniq.get(r, 0.0) + p
    rr = np.array(sorted(uniq))
    pp = np.array([uniq[r] for r in rr])
    smear = float(np.sqrt(cm.unresolved_var_bp2 + 9.0)) / 100.0
    dens = sum(p * np.exp(-0.5 * ((grid - r) / smear) ** 2)
               / (smear * np.sqrt(2 * np.pi)) for r, p in zip(rr, pp))
    return rr, pp, dens, smear * 100

# %% [markdown]
# ## 1. The triangle — three markets, one distribution axis
#
# Solid = the option RND (the only curve that prices shape). Dashed = the
# two linear trees (ZQ lattice / FOMC-swap lattice) under the strict smear.
# Stems = the lattice atoms. Use the dropdown to switch (contract, date);
# the horizontal gap between dashed and solid IS the dislocation.

# %%
fig = go.Figure()
groups, labels = [], []
for sym in CONFIG["snap_symbols"]:
    for d in SNAP_DATES:
        bl = snaps[(sym, d)].bl_result
        grid = bl.strike_grid_rate
        idx0 = len(fig.data)
        fig.add_scatter(x=grid, y=bl.rnd_density, mode="lines",
                        line=dict(color=C["opt"], width=2.2),
                        name="option RND (BL)")
        for lad, key, col in ((ladders[d], "ZQ tree", C["zq"]),
                              (swap_ladders[d], "swap tree", C["swap"])):
            tc = tree_curve(sym, d, lad, grid)
            if tc is None:
                continue
            rr, pp, dens, smear = tc
            fig.add_scatter(x=grid, y=dens, mode="lines",
                            line=dict(color=col, width=1.4, dash="dash"),
                            name=f"{key} (smear {smear:.1f}bp)")
            if key == "ZQ tree":
                fig.add_bar(x=rr, y=pp * float(np.max(dens)) / pp.max(),
                            width=0.012, marker_color=col, opacity=0.30,
                            name="lattice atoms (scaled)")
        fig.add_scatter(x=[bl.input.forward_rate] * 2, y=[0, 1.05],
                        mode="lines", line=dict(color=C["fwd"], width=1,
                                                dash="dot"),
                        name=f"forward {bl.input.forward_rate:.3f}%")
        groups.append(list(range(idx0, len(fig.data))))
        labels.append(f"{sym}  {d}")
n_tr = len(fig.data)
for i, g in enumerate(groups):
    for j in range(n_tr):
        fig.data[j].visible = j in groups[0]
buttons = [dict(label=lb, method="update",
                args=[{"visible": [j in g for j in range(n_tr)]}])
           for lb, g in zip(labels, groups)]
fig.update_layout(updatemenus=[dict(buttons=buttons, x=1.0, y=1.18,
                                    xanchor="right")], barmode="overlay")
style(fig, "The triangle: option RND vs the two linear trees",
      xtitle="settlement rate (%)", ytitle="density", height=470)
show(fig)

# %% [markdown]
# ## 2. The count-bucket ledger — every FOMC path, priced both ways

# %%
fig = go.Figure()
groups, labels = [], []
for d in SNAP_DATES:
    sym = CONFIG["ledger_symbol"]
    bl = snaps[(sym, d)].bl_result
    tc = tree_curve(sym, d, ladders[d], bl.strike_grid_rate)
    rr, pp, _, smear = tc
    edges = np.concatenate([[rr[0] - 0.125], (rr[:-1] + rr[1:]) / 2,
                            [rr[-1] + 0.125]])
    cdf_o = np.interp(edges, bl.strike_grid_rate, bl.rnd_cumulative,
                      left=0.0, right=1.0)
    from scipy.stats import norm
    s = smear / 100.0
    cdf_t = sum(p * norm.cdf((edges - r) / s) for r, p in zip(rr, pp))
    po, pt = np.diff(cdf_o), np.diff(cdf_t)
    names = [f"{r:.2f}%" for r in rr]
    names = ["below"] + names + ["above"]
    po = np.concatenate([[cdf_o[0]], po, [1 - cdf_o[-1]]])
    pt = np.concatenate([[cdf_t[0]], pt, [1 - cdf_t[-1]]])
    idx0 = len(fig.data)
    fig.add_bar(x=names, y=pt * 100, name="tree (ZQ lattice)",
                marker_color=C["zq"], opacity=0.85,
                customdata=(po - pt) * 100,
                hovertemplate="tree %{y:.1f}pp<extra></extra>")
    fig.add_bar(x=names, y=po * 100, name="options",
                marker_color=C["opt"], opacity=0.7,
                customdata=(po - pt) * 25,
                hovertemplate="options %{y:.1f}pp | gap on 25bp vertical "
                              "%{customdata:.1f}bp<extra></extra>")
    groups.append(list(range(idx0, len(fig.data))))
    labels.append(f"{sym}  {d}")
n_tr = len(fig.data)
for j in range(n_tr):
    fig.data[j].visible = j in groups[0]
fig.update_layout(
    updatemenus=[dict(buttons=[
        dict(label=lb, method="update",
             args=[{"visible": [j in g for j in range(n_tr)]}])
        for lb, g in zip(labels, groups)], x=1.0, y=1.18, xanchor="right")],
    barmode="group")
style(fig, f"Count-bucket ledger — {CONFIG['ledger_symbol']}: "
           "P(bucket) tree vs options",
      xtitle="settlement bucket (atom rate)", ytitle="probability (pp)")
show(fig)

# %% [markdown]
# ## 3. The ICS residual — the level channel through time
#
# `SOFR−FF spread = basis + compounding + calendar wedge + residual`. The
# residual (yellow) is the only priced object; toggle components in the
# legend, drag the range slider.

# %%
ics = pd.read_parquet(DATA_LG / "ics_residuals.parquet")
ics["as_of"] = pd.to_datetime(ics["as_of"])
fig = go.Figure()
syms = sorted(ics["symbol"].unique())
groups, labels = [], []
for sym in syms:
    g = ics[ics.symbol == sym].sort_values("as_of")
    idx0 = len(fig.data)
    for col, name, colr, w in (
            ("ics_bp", "observed ICS", "#90a4ae", 1.0),
            ("basis_bp", "SOFR-EFFR basis", "#4db6ac", 0.9),
            ("comp_bp", "compounding", "#7986cb", 0.9),
            ("wedge_bp", "calendar wedge", "#8d6e63", 0.9),
            ("resid_bp", "RESIDUAL", C["resid"], 2.0)):
        fig.add_scatter(x=g["as_of"], y=g[col], mode="lines", name=name,
                        line=dict(color=colr, width=w))
    groups.append(list(range(idx0, len(fig.data))))
    labels.append(sym)
n_tr = len(fig.data)
d0 = labels.index(CONFIG["ics_default_symbol"]) \
    if CONFIG["ics_default_symbol"] in labels else 0
for j in range(n_tr):
    fig.data[j].visible = j in groups[d0]
fig.update_layout(updatemenus=[dict(buttons=[
    dict(label=lb, method="update",
         args=[{"visible": [j in g for j in range(n_tr)]}])
    for lb, g in zip(labels, groups)], x=1.0, y=1.2, xanchor="right",
    active=d0)])
fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
style(fig, "ICS decomposition — the level dislocation and its mechanical "
           "layers", xtitle=None, ytitle="bp", height=470)
fig.add_hline(y=0, line_color="#616161", line_width=0.7)
show(fig)

# %% [markdown]
# ## 4. The feasibility frontier — when can the lattice carry the surface?
#
# Every contract-day: x = days to expiry, y = surface width / lattice
# ceiling. Above 1 the option market prices more width than any meeting
# lattice can represent (channel 2, the standing premium); the convergence
# channel only exists in the cloud that dips below.

# %%
mon = pd.read_parquet(DATA_MP / "monitor.parquet")
mon["as_of"] = pd.to_datetime(mon["as_of"])
mon["width_ratio"] = mon["total_std_opt_bp"] / (
    mon["lattice_ceiling_bp"] + mon["smear_bp"])
fig = go.Figure()
for ch, colr in (("channel1", "#66bb6a"), ("channel2", "#ef5350"),
                 ("flat", "#90a4ae")):
    g = mon[mon.channel == ch]
    fig.add_scatter(
        x=g["days_to_expiry"], y=g["width_ratio"], mode="markers",
        name=f"{ch} ({len(g)})",
        marker=dict(size=5, color=colr, opacity=0.55,
                    symbol=np.where(g["saturated"], "x", "circle")),
        customdata=np.stack([g["symbol"],
                             g["as_of"].dt.strftime("%Y-%m-%d")], axis=1),
        hovertemplate="%{customdata[0]} %{customdata[1]}<br>dte %{x} | "
                      "ratio %{y:.2f}<extra></extra>")
fig.add_hline(y=1.0, line_color="#ffca28", line_width=1, line_dash="dash",
              annotation_text="lattice ceiling", annotation_font_size=10)
fig.update_layout(template=DARK, height=440, hovermode="closest",
                  title="The feasibility frontier — surface width vs the "
                        "lattice ceiling (x = saturated refit)")
fig.update_xaxes(title="days to option expiry", showspikes=True,
                 spikemode="across", spikedash="dot", spikethickness=1)
fig.update_yaxes(title="option width / (ceiling + smear)", showspikes=True,
                 spikedash="dot", spikethickness=1)
show(fig)

# %% [markdown]
# ## 5. Boundary-digital gaps — the shape dislocation, daily
#
# Largest |listed − tree| digital gap per contract-day, colored by channel.
# These are the raw materials of the channel-1 convergence trades.

# %%
bd = pd.read_parquet(DATA_MP / "boundaries.parquet")
bd["as_of"] = pd.to_datetime(bd["as_of"])
best = bd.loc[bd.groupby(["as_of", "symbol"])["gap"]
              .apply(lambda s: s.abs().idxmax()).to_numpy()]
best = best.merge(mon[["as_of", "symbol", "channel", "days_to_expiry"]],
                  on=["as_of", "symbol"], how="left")
fig = go.Figure()
for sym in sorted(best["symbol"].unique()):
    g = best[best.symbol == sym].sort_values("as_of")
    fig.add_scatter(
        x=g["as_of"], y=g["gap"].abs() * 100, mode="lines+markers",
        name=sym, line=dict(width=1),
        marker=dict(size=4, color=np.where(g["channel"] == "channel1",
                                           "#66bb6a", "#ef5350")),
        customdata=np.stack([g["channel"].fillna(""),
                             g["days_to_expiry"]], axis=1),
        hovertemplate=f"{sym}" + " %{x|%Y-%m-%d}<br>|gap| %{y:.1f}pp | "
                      "%{customdata[0]} | dte %{customdata[1]:.0f}"
                      "<extra></extra>", visible="legendonly")
for tr in fig.data[:3]:
    tr.visible = True
fig.add_hline(y=6.0, line_color="#ffca28", line_width=0.8, line_dash="dash",
              annotation_text="6pp entry region", annotation_font_size=10)
style(fig, "Largest boundary-digital gap per contract-day (green marker = "
           "channel 1) — click legend to add contracts",
      ytitle="|listed − tree| (pp)", height=460)
show(fig)

# %% [markdown]
# ## 6. Family-B richness — the premium the fade trades
#
# Listed package premium minus ZQ-tree fair, daily, for the dispersion
# books. The pre-registered fade's entries (red) and exits (green) are
# marked on its own series.

# %%
from famb_common import (TreeCtx, build_book, intra_quarter_backtest,
                         load_quotes, n_contracts, premium_surface,
                         richness_frame, sr3_forwards)

quotes = load_quotes()
symbols = sorted(quotes["symbol"].unique())
fwdf = sr3_forwards(symbols)
fwdf["as_of"] = pd.to_datetime(fwdf["as_of"])
surface = premium_surface(quotes, fwdf)
fwd_idx = fwdf.set_index(["as_of", "symbol"])["fwd_rate"].sort_index()
qdates = pd.DatetimeIndex(sorted(quotes["as_of"].unique()))
tree_full = TreeCtx([d.date() for d in qdates])

fig = go.Figure()
fade_cfg = CONFIG["fade"]
for book, rank in CONFIG["richness_books"]:
    hs = build_book(book, rank, qdates, surface, fwd_idx, tree_full)
    rf = richness_frame(hs)
    if rf.empty:
        continue
    s = rf.groupby("as_of")["rich_bp"].mean()
    is_fade = (book == fade_cfg["book"] and rank == fade_cfg["rank"])
    fig.add_scatter(x=s.index, y=s.values, mode="lines",
                    name=f"{book} Q{rank}",
                    line=dict(width=1.6 if is_fade else 0.9,
                              color=C["rich"] if is_fade else None))
    if is_fade:
        trades = intra_quarter_backtest(
            hs, thr_bp=fade_cfg["thr_bp"], exit_frac=fade_cfg["exit_frac"],
            max_hold=fade_cfg["max_hold"], direction=fade_cfg["direction"],
            cost_mult=1.0, n_legs=n_contracts(book))
        tl = pd.DataFrame(trades)
        if len(tl):
            fig.add_scatter(x=tl["entry"], y=tl["entry_rich"],
                            mode="markers", name="fade entry",
                            marker=dict(symbol="triangle-down", size=10,
                                        color=C["entry"]))
            ex = s.reindex(pd.DatetimeIndex(tl["exit"])).fillna(0.0)
            fig.add_scatter(x=tl["exit"], y=ex.values, mode="markers",
                            name="fade exit",
                            marker=dict(symbol="triangle-up", size=10,
                                        color=C["exit"]))
fig.add_hline(y=fade_cfg["thr_bp"], line_color="#ffca28", line_width=0.8,
              line_dash="dash",
              annotation_text=f"entry thr {fade_cfg['thr_bp']}bp",
              annotation_font_size=10)
fig.add_hline(y=0, line_color="#616161", line_width=0.7)
fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
style(fig, "Dispersion-book richness (market − tree-fair) with the "
           "pre-registered fade's trades", ytitle="richness (bp)",
      height=480)
show(fig)

# %% [markdown]
# ### Reading the dashboard
#
# The five dislocations are one object seen at different resolutions: the
# triangle shows the SHAPE gap at a snapshot; the ledger prices it per
# FOMC path; the frontier says WHERE in expiry space it is tradeable vs
# structural; the boundary gaps and the richness series are its daily time
# series in probability and premium units; and the ICS residual is the
# LEVEL channel the mean-pinned layers deliberately exclude. Verdicts and
# discipline live in the findings docs — this notebook is the instrument
# panel, not the judge.

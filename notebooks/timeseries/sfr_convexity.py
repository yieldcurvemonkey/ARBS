# %%
# %load_ext autoreload
# %autoreload 2

# The Barchart settle fetcher underneath `sfr_cvx_adj` calls `asyncio.run()`, and
# a Jupyter kernel already owns a running loop -- without this the whole notebook
# dies on "asyncio.run() cannot be called from a running event loop". This is why
# eod_linear_rates.ipynb opens the same way.
import nest_asyncio
nest_asyncio.apply()

import plotly.io as pio
pio.renderers.default = "plotly_mimetype+notebook_connected"

import matplotlib.pyplot as plt
import matplotlib.pylab as pylab
plt.style.use("ggplot")
pylab.rcParams.update({
    "legend.fontsize": "medium", "figure.figsize": (18, 6),
    "axes.labelsize": "medium", "axes.titlesize": "medium",
    "xtick.labelsize": "medium", "ytick.labelsize": "medium",
})

import datetime
import os
import sys

import numpy as np
import pandas as pd
import pytz

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
NYC_tz = pytz.timezone("America/New_York")
sys.path.append("../../")

from RVUtils.plt_timeseries import make_secondary_axis_plot

# %% [markdown]
# # SFR convexity adjustment
#
# `CA = pack_rate − matched_swap_rate`, in basis points, for each of the five
# pack colours Citi prints. The pack rate is the average of four consecutive SR3
# settles; the matched swap is the forward swap covering the same window,
# **quarterly/quarterly** — Citi specifies that verbatim, and the `usd_irs` spec
# quotes annual fixed, which is a 4.6–5.9 bp error on a quantity that is itself
# 1–20 bp.
#
# Two things to know before reading any number here:
#
# * **The adjustment grows with rank.** Whites sit ~0.3 months out and Golds
#   ~4 years; `CA = ½·σ²·mean(T1²)`, so it is a variance quantity and the deeper
#   colour should always carry more. That monotonicity is the cheapest sanity
#   check available on this series.
# * **Deep colours were unavailable until recently.** Blues had 49 usable dates
#   in 2023 and Golds had none at all in 2026 before the SR3 settle warm; they
#   now carry ~250 dates a year.

# %%
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from TB.IRSwapsTB import IRSwapsTB

curve_mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
tb = IRSwapsTB(curve_mdp, show_tqdm=True, use_ts_cache=False)

COLOURS = ["WHITES", "REDS", "GREENS", "BLUES", "GOLDS"]

start = datetime.date(2026, 1, 2)
end = datetime.date(2026, 8, 20)

# %%
ca = tb.sfr_cvx_adj(COLOURS, start, end)
ca.columns = [c.split()[1] for c in ca.columns]        # "USD-SOFR-1D BLUES PACKS CVX_ADJ" -> "BLUES"
print(f"{ca.shape[0]} dates  {ca.index.min().date()} .. {ca.index.max().date()}")
print(f"dates the builder could not price: "
      f"{ {k: len(v) for k, v in tb.sfr_cvx_adj_failures.items()} }")
ca.tail(10)

# %% [markdown]
# ## The term structure should be monotone in rank
#
# Asserted rather than eyeballed. A colour that carries *less* convexity than a
# nearer one is a data problem, not a market view.

# %%
med = ca.median().reindex(COLOURS)
print("median CA by colour, bp:")
print(med.round(3).to_string())

_ok = med.dropna()
assert _ok.is_monotonic_increasing, (
    f"the adjustment is not increasing with rank: {_ok.to_dict()}. "
    "CA is a variance quantity in T1^2, so a deeper pack must carry more."
)
print("\nOK: monotone in rank, as a variance quantity must be.")

# %%
plot, fig, ax, ax2, legend = make_secondary_axis_plot(
    engine="plotly", ylabel_left="convexity adjustment, bp",
    title="SFR convexity adjustment by pack colour")
for c in COLOURS:
    if c in ca.columns:
        plot(ca[c].dropna(), which="left", label=c)
legend(show_date=True)
fig.show()

# %% [markdown]
# ## The current term structure

# %%
latest = ca.dropna(how="all").iloc[-1]
asof = ca.dropna(how="all").index[-1]
print(f"as of {asof.date()}")
print(latest.reindex(COLOURS).round(3).to_string())

import plotly.graph_objects as go
_c = latest.reindex(COLOURS).dropna()
f2 = go.Figure(go.Bar(x=_c.index, y=_c.to_numpy(),
                      text=[f"{v:.2f}" for v in _c], textposition="outside"))
f2.update_layout(title=f"SFR convexity adjustment by colour, {asof.date()}",
                 yaxis_title="bp", height=380)
f2.show()

# %% [markdown]
# ## Against the 2s5s10s fly
#
# Citi's Figure 9 argues the adjustment is directional with the 2s5s10s swap
# fly, and therefore hedgeable with it. On 2021–2026 SOFR that relationship did
# **not** reproduce — hedge R² 0.000–0.010 with a sign-flipping beta — so this
# panel is here to be looked at rather than relied on.

# %%
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

try:
    # The slash form is what the query layer auto-detects as a FLY; passing
    # `structure_kwargs={"tenors": [...]}` raises "FLY requires all three leg
    # tenors". Construction is inside the try because that is where it raises.
    fly_q = IRSwapQuery(curve="USD-SOFR-1D", tenor="2Y/5Y/10Y",
                        value=IRSwapValue.RATE, structure_kwargs={"bpv": 1.0})
    fly = tb.get_timeseries(start=start, end=end, queries=[fly_q], n_jobs=8)
    fly.columns = ["2s5s10s fly"]
    print(fly.tail(3).to_string())
except Exception as exc:                                     # noqa: BLE001
    fly = pd.DataFrame()
    print(f"fly unavailable: {type(exc).__name__}: {exc}")

# %%
if not fly.empty:
    j = ca.join(fly, how="inner").dropna(subset=["2s5s10s fly"])
    plot, fig3, ax, ax2, legend = make_secondary_axis_plot(
        engine="plotly", ylabel_left="CA, bp", ylabel_right="fly, bp",
        title="Greens / Blues convexity adjustment vs the 2s5s10s fly")
    for c in ("GREENS", "BLUES"):
        if c in j.columns and j[c].notna().any():
            plot(j[c].dropna(), which="left", label=c)
    plot(j["2s5s10s fly"].dropna(), which="right", label="2s5s10s fly")
    legend(show_date=True)
    fig3.show()

    corr = j[[c for c in COLOURS if c in j.columns]].corrwith(j["2s5s10s fly"])
    print("\ncorrelation of LEVELS with the fly:")
    print(corr.round(3).to_string())
    dcorr = j.diff().dropna()
    print("\ncorrelation of daily CHANGES with the fly (the one that matters):")
    print(dcorr[[c for c in COLOURS if c in j.columns]]
          .corrwith(dcorr["2s5s10s fly"]).round(3).to_string())
else:
    print("skipped: no fly series")

# %%
tb.close()
print("done")
